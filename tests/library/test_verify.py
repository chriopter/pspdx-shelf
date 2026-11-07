import hashlib
import json
import os

import pytest

from umdlibrary.jobs.runner import Job
from umdlibrary.library import hash as hashmod
from umdlibrary.library import scan, verify

from ..helpers import make_iso, write


def _record(folder, sha, size, identifier, title, disc_id=None):
    os.makedirs(folder, exist_ok=True)
    record = {"kind": "iso", "schema_version": 1, "sha256": sha, "sha1": "0" * 40, "size_bytes": size,
              "metadata": {"identifier": identifier, "umd_uid": "05FC10F031E498EA", "type_code": "0001",
                           "media_code": "G", "disc_id": disc_id or identifier.replace("-", ""),
                           "disc_version": "1.02", "title": title, "required_firmware": "5.02"}}
    path = os.path.join(folder, f"{sha}-ingest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    with open(os.path.join(folder, f"{sha}-tree.json"), "w") as f:
        f.write("{}")
    return path


@pytest.fixture
def pspdb(tmp_path, library, dirs):
    """A fake checkout with two records: one for an image in the library,
    one for a dump that is not there."""
    known = write(os.path.join(dirs["lib"], "known.iso"), make_iso("Known Game", "ULUS-10404", vol_ident="ULUS10404"))
    write(os.path.join(dirs["lib"], "other.iso"), make_iso("Other Game", "ULES-00002", vol_ident="ULES00002"))
    write(os.path.join(dirs["lib"], "nohash.iso"), make_iso("No Hash", "ULES-00003", vol_ident="ULES00003"))
    scan.scan(library)
    for row in library.all():
        if row["name"] != "nohash.iso":
            hashmod.hash_image(library, row["id"])
    sha = hashlib.sha256(open(known, "rb").read()).hexdigest()
    root = tmp_path / "pspdb"
    _record(str(root / "catalog" / "iso" / "v6"), sha, os.path.getsize(known), "ULUS-10404", "Air Conflicts: Aces of World War II")
    _record(str(root / "catalog" / "iso" / "v3"), "ab" * 32, 1_275_996_160, "Family Guy Vol 1 Disc 5", "Family Guy Vol. 1 (Disc 5)")
    (root / "catalog" / "iso" / "v3" / "broken-ingest.json").write_text("{not json")
    return str(root)


def test_records_dir_and_load(pspdb):
    assert verify.records_dir(pspdb).endswith(os.path.join("catalog", "iso"))
    assert verify.records_dir(os.path.join(pspdb, "catalog", "iso")) == os.path.join(pspdb, "catalog", "iso")
    assert verify.records_dir(os.path.join(pspdb, "nope")) is None
    records = verify.load_records(pspdb)
    assert len(records) == 2 and records["ab" * 32]["title"] == "Family Guy Vol. 1 (Disc 5)"
    assert records["ab" * 32]["file"] == os.path.join("v3", "ab" * 32 + "-ingest.json")
    with pytest.raises(RuntimeError, match="no pspdb"):
        verify.load_records(os.path.join(pspdb, "nope"))


def test_verify_marks_known_and_unknown(pspdb, library):
    job = Job(1, "verify", "t")
    result = verify.verify(library, pspdb, job)
    assert result == {"records": 2, "known": 1, "unknown": 1, "waiting_for_hash": 1}
    rows = {r["name"]: r for r in library.all()}
    assert rows["known.iso"]["pspdb_status"] == "known"
    assert rows["known.iso"]["pspdb_title"] == "Air Conflicts: Aces of World War II"
    assert rows["known.iso"]["pspdb_identifier"] == "ULUS-10404" and rows["known.iso"]["pspdb_file"].startswith("v6")
    assert rows["other.iso"]["pspdb_status"] == "unknown" and rows["nohash.iso"]["pspdb_status"] is None
    assert library.counts()["known_dumps"] == 1 and library.counts()["unknown_dumps"] == 1
    assert any("known dump, ULUS-10404" in line for line in job.lines)
    # A size mismatch is not a match.
    path = os.path.join(pspdb, "catalog", "iso", "v6")
    name = [n for n in os.listdir(path) if n.endswith("-ingest.json")][0]
    record = json.load(open(os.path.join(path, name)))
    record["size_bytes"] += 1
    json.dump(record, open(os.path.join(path, name), "w"))
    assert verify.verify(library, pspdb)["known"] == 0
    assert library.all()[0]["pspdb_status"] == "unknown"


def test_verify_needs_a_path(library):
    with pytest.raises(RuntimeError, match="pspdb_dir"):
        verify.verify(library, "")


def test_a_changed_file_forgets_the_verdict(pspdb, library, dirs):
    verify.verify(library, pspdb)
    row = {r["name"]: r for r in library.all()}["known.iso"]
    write(row["abs_path"], make_iso("Known Game v2", "ULUS-10404", vol_ident="ULUS10404"), mtime=row["mtime"] + 100)
    scan.scan(library)
    assert library.get(row["id"])["pspdb_status"] is None

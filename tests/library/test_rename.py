import os

import pytest

from umdlibrary.jobs.runner import Job
from umdlibrary.library import hash as hashmod
from umdlibrary.library import rename, scan

from ..helpers import make_cso, make_iso, write


@pytest.mark.parametrize("stem, ext, expected", [
    ("Test Game", "iso", "Test Game.iso"),
    ("Café Größe", "ISO", "Cafe Groe.iso"),
    ("a/b\\c:d*e?f\"g<h>i|j", "cso", "abcdefghij.cso"),
    ("ctrl\x00\x1fchars\ttab", "iso", "ctrl chars tab.iso"),
    ("trailing dot.", "iso", "trailing dot.iso"),
    ("   spaced   out   ", "iso", "spaced out.iso"),
    ("", "iso", "disc.iso"),
    ("日本語のみ", "iso", "disc.iso"),
    ("x" * 300, "iso", "x" * 116 + ".iso"),
    ("name", "", "name.iso"),
])
def test_safe_filename(stem, ext, expected):
    out = rename.safe_filename(stem, ext)
    assert out == expected
    assert len(out) <= rename.MAX_NAME and "/" not in out and not out.rstrip(".iso").endswith(".")


def test_check_pattern():
    rename.check_pattern("{title} [{disc_id}].{ext}")
    with pytest.raises(ValueError, match="unknown field"):
        rename.check_pattern("{nope}.iso")
    with pytest.raises(ValueError, match="no field"):
        rename.check_pattern("static.iso")
    with pytest.raises(ValueError, match="bad pattern"):
        rename.check_pattern("{title")


def _row(**over):
    row = {"name": "orig.iso", "title": "Test Game", "disc_id": "ULES-01234", "disc_key": "ULES-01234",
           "region": "EU", "format": "iso", "sfo": {"DISC_VERSION": "1.02", "CATEGORY": "UG"}}
    row.update(over)
    return row


def test_target_name():
    assert rename.target_name(_row(), "{title} [{disc_id}].{ext}") == "Test Game [ULES-01234].iso"
    assert rename.target_name(_row(name="x.CSO", format="cso"), "{disc_id}.{ext}") == "ULES-01234.cso"
    assert rename.target_name(_row(title=None), "{title}.{ext}") == "orig.iso"
    assert rename.target_name(_row(), "{region}/{name}.{format}") == "EUorig.iso"
    assert rename.target_name(_row(), "{title} v{disc_version} {category}.{ext}") == "Test Game v1.02 UG.iso"
    assert rename.target_name(_row(), "{title}") == "Test Game.iso"


@pytest.fixture
def folder(library, dirs):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(), mtime=1_700_000_000)
    write(os.path.join(dirs["lib"], "Second [ULUS-10001].cso"),
          make_cso(make_iso("Second", "ULUS-10001", vol_ident="ULUS10001")), mtime=1_700_000_001)
    write(os.path.join(dirs["lib"], "dup.iso"), make_iso(), mtime=1_700_000_002)
    write(os.path.join(dirs["lib"], "junk.iso"), b"junk" * 1000)
    write(os.path.join(dirs["lib"], "taken.iso"), make_iso("Taken", "ULES-99999", vol_ident="ULES99999"))
    write(os.path.join(dirs["lib"], "Taken [ULES-99999].iso"), b"an unrelated file")
    scan.scan(library)
    hashmod.hash_missing(library)
    return library


def test_plan(folder):
    plan = {e["from"]: e for e in rename.plan(folder, "{title} [{disc_id}].{ext}")}
    assert plan["a.iso"]["status"] == "conflict" and "two images" in plan["a.iso"]["reason"]
    assert plan["dup.iso"]["status"] == "conflict"
    assert plan["Second [ULUS-10001].cso"]["status"] == "unchanged"
    assert plan["junk.iso"]["status"] == "skipped" and plan["junk.iso"]["to"] is None
    assert plan["taken.iso"]["status"] == "conflict" and "exists" in plan["taken.iso"]["reason"]
    # Taken [ULES-99999].iso is junk to the reader, so it is skipped, never renamed over.
    assert plan["Taken [ULES-99999].iso"]["status"] == "skipped"
    plan = {e["from"]: e for e in rename.plan(folder, "{name}-{disc_id}.{ext}")}
    assert plan["a.iso"]["status"] == "clean" and plan["a.iso"]["to"] == "a-ULES-01234.iso"


def test_apply_renames_and_db_follows(folder, dirs):
    before = {r["name"]: r for r in folder.all()}
    job = Job(1, "rename", "t")
    result = rename.apply(folder, "{name}-{disc_id}.{ext}", job)
    assert result["failed"] == 0 and result["renamed"] == 4
    names = sorted(os.listdir(dirs["lib"]))
    assert "a-ULES-01234.iso" in names and "dup-ULES-01234.iso" in names and "taken-ULES-99999.iso" in names
    assert "Second [ULUS-10001]-ULUS-10001.cso" in names
    assert "a.iso" not in names
    after = {r["name"]: r for r in folder.all()}
    moved = after["a-ULES-01234.iso"]
    assert moved["id"] == before["a.iso"]["id"] and moved["sha256"] == before["a.iso"]["sha256"]
    assert moved["has_media"]["ICON0.PNG"]
    # A rescan sees nothing to do: the database followed the file.
    assert scan.scan(folder) == {"added": 0, "changed": 0, "removed": 0, "unchanged": 6}
    history = folder.rename_history()
    assert len(history) == 4 and all(h["ok"] for h in history)
    assert any("a.iso -> a-ULES-01234.iso" in line for line in job.lines)
    # The unrelated file was never touched.
    assert open(os.path.join(dirs["lib"], "Taken [ULES-99999].iso"), "rb").read() == b"an unrelated file"


def test_apply_only_some(folder, dirs):
    ids = {r["id"] for r in folder.all() if r["name"] == "a.iso"}
    assert rename.apply(folder, "{name}-{disc_id}.{ext}", only_ids=ids)["renamed"] == 1
    assert "dup.iso" in os.listdir(dirs["lib"])


def test_apply_never_overwrites_a_file_that_appeared(folder, dirs, monkeypatch):
    """A file that lands on the target name between the plan and the
    rename is not overwritten."""
    real_plan = rename.plan

    def plan_then_block(library, pattern):
        entries = real_plan(library, pattern)
        write(os.path.join(dirs["lib"], "a-ULES-01234.iso"), b"appeared")
        return entries
    monkeypatch.setattr(rename, "plan", plan_then_block)
    ids = {r["id"] for r in folder.all() if r["name"] == "a.iso"}
    result = rename.apply(folder, "{name}-{disc_id}.{ext}", only_ids=ids)
    assert result["renamed"] == 0 and result["failed"] == 1
    assert open(os.path.join(dirs["lib"], "a-ULES-01234.iso"), "rb").read() == b"appeared"
    assert os.path.exists(os.path.join(dirs["lib"], "a.iso"))
    assert not folder.rename_history()[0]["ok"]


def test_apply_refuses_source_changed_since_dry_run(folder, dirs, monkeypatch):
    real_plan = rename.plan

    def plan_then_change_source(library, pattern):
        entries = real_plan(library, pattern)
        write(os.path.join(dirs["lib"], "a.iso"), make_iso(title="Changed"), mtime=1_800_000_000)
        return entries

    monkeypatch.setattr(rename, "plan", plan_then_change_source)
    ids = {r["id"] for r in folder.all() if r["name"] == "a.iso"}
    result = rename.apply(folder, "{name}-{disc_id}.{ext}", only_ids=ids)
    assert result["renamed"] == 0 and result["failed"] == 1
    assert "changed since the dry run" in result["failures"][0]["error"]
    assert os.path.exists(os.path.join(dirs["lib"], "a.iso"))
    assert not folder.rename_history()[0]["ok"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_folder_fails_harmlessly(folder, dirs):
    os.chmod(dirs["lib"], 0o555)
    try:
        result = rename.apply(folder, "{name}-{disc_id}.{ext}")
    finally:
        os.chmod(dirs["lib"], 0o755)
    assert result["renamed"] == 0 and result["failed"] == 4
    assert "a.iso" in os.listdir(dirs["lib"])
    assert all(not h["ok"] and "read-only" in h["error"] for h in folder.rename_history())
    assert {r["name"] for r in folder.all()} >= {"a.iso", "dup.iso"}


def test_pattern_cannot_leave_the_folder(folder, dirs):
    plan = {e["from"]: e for e in rename.plan(folder, "../{disc_id}.{ext}")}
    assert plan["taken.iso"]["to"] == "..ULES-99999.iso"
    rename.apply(folder, "../{disc_id}.{ext}")
    assert not os.path.exists(os.path.join(os.path.dirname(dirs["lib"]), "ULES-99999.iso"))

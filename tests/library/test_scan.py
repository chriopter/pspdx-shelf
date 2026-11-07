import os
import time

from umdlibrary.jobs.runner import Job
from umdlibrary.library import scan

from ..helpers import make_cso, make_iso, write


def test_add_change_remove(library, dirs):
    a = write(os.path.join(dirs["lib"], "a.iso"), make_iso(), mtime=1_700_000_000)
    job = Job(1, "scan", "t")
    assert scan.scan(library, job) == {"added": 1, "changed": 0, "removed": 0, "unchanged": 0}
    assert job.total == 1 and job.progress == 1
    rows = library.all()
    assert len(rows) == 1 and rows[0]["disc_key"] == "ULES-01234" and rows[0]["status"] == "ok"
    assert rows[0]["disc_id"] == "ULES01234" and rows[0]["identifier"] == "ULES-01234"
    assert rows[0]["umd_data"]["umd_uid"] == "05FC10F031E498EA" and rows[0]["languages"] == ["en"]
    assert rows[0]["has_media"]["ICON0.PNG"] and os.path.exists(os.path.join(rows[0]["media_dir"], "ICON0.PNG"))
    row_id = rows[0]["id"]
    assert scan.scan(library) == {"added": 0, "changed": 0, "removed": 0, "unchanged": 1}
    # Changed: a new mtime and other content, the same row id.
    write(a, make_iso(title="Renamed Title"), mtime=1_700_000_500)
    assert scan.scan(library)["changed"] == 1
    assert library.get(row_id)["title"] == "Renamed Title"
    os.remove(a)
    assert scan.scan(library)["removed"] == 1
    assert library.all() == [] and not os.path.exists(os.path.join(library.media_dir, str(row_id)))


def test_ignores_other_files_and_subfolders(library, dirs):
    write(os.path.join(dirs["lib"], "readme.txt"), b"hi")
    write(os.path.join(dirs["lib"], ".hidden.iso"), make_iso())
    os.makedirs(os.path.join(dirs["lib"], "sub"))
    write(os.path.join(dirs["lib"], "sub", "deep.iso"), make_iso())
    assert scan.scan(library)["added"] == 0


def test_unreadable_images_get_a_row_with_the_error(library, dirs):
    write(os.path.join(dirs["lib"], "junk.iso"), b"junk" * 3000)
    write(os.path.join(dirs["lib"], "plain.iso"), make_iso(psp_game=False, umd_data=False, vol_ident="DATA"))
    packed = make_cso(make_iso(pad_bytes=100_000))
    write(os.path.join(dirs["lib"], "cut.cso"), packed[:len(packed) // 2])
    scan.scan(library)
    rows = {r["name"]: r for r in library.all()}
    assert rows["junk.iso"]["status"] == "error" and "ISO 9660" in rows["junk.iso"]["error"]
    assert rows["plain.iso"]["status"] == "error" and "PSP_GAME" in rows["plain.iso"]["error"]
    assert rows["cut.cso"]["status"] == "error" and "CSO" in rows["cut.cso"]["error"]
    assert library.counts()["errors"] == 3


def test_duplicates_newest_first(library, dirs):
    write(os.path.join(dirs["lib"], "old.iso"), make_iso(), mtime=1_700_000_000)
    write(os.path.join(dirs["lib"], "new.cso"), make_cso(make_iso()), mtime=1_700_500_000)
    scan.scan(library)
    rows = library.all()
    assert [r["name"] for r in rows] == ["new.cso", "old.iso"]
    assert all(r["duplicate"] for r in rows)
    assert rows[0]["primary"] and not rows[1]["primary"]
    assert library.by_key("ULES-01234")["name"] == "new.cso"
    assert library.counts()["duplicates"] == 2


def test_unicode_names(library, dirs):
    write(os.path.join(dirs["lib"], "モンハン [ULJM-05500].iso"), make_iso(title="モンスターハンター", disc_id="ULJM-05500"))
    scan.scan(library)
    row = library.all()[0]
    assert row["name"] == "モンハン [ULJM-05500].iso" and row["title"] == "モンスターハンター" and row["region"] == "JP"


def test_missing_folder(library):
    library.library_dir = library.library_dir + "-missing"
    try:
        scan.scan(library)
    except RuntimeError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("expected an error")


def test_unreadable_folder_reports_runtime_error(library, monkeypatch):
    def denied(path):
        raise PermissionError("nope")

    monkeypatch.setattr(scan.os, "listdir", denied)
    try:
        scan.scan(library)
    except RuntimeError as exc:
        assert "not readable" in str(exc)
    else:
        raise AssertionError("expected an error")


def test_cancel_between_files(library, dirs):
    for i in range(3):
        write(os.path.join(dirs["lib"], f"{i}.iso"), make_iso(disc_id=f"ULES-0000{i}"))
    job = Job(1, "scan", "t")
    job.cancel_requested = True
    from umdlibrary.jobs.runner import Cancelled
    try:
        scan.scan(library, job)
    except Cancelled:
        pass
    assert len(library.all()) < 3

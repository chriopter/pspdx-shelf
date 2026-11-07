import os
import shutil
import subprocess

import pytest

from umdlibrary.jobs.runner import Job
from umdlibrary.library import media, scan

from ..helpers import make_iso, write


def test_extract_all_only_missing(library, dirs):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(media=("ICON0.PNG", "PIC1.PNG", "ICON1.PMF")))
    scan.scan(library)
    row = library.all()[0]
    assert media.extract_all(library) == {"images": 0, "files": 0}
    os.remove(os.path.join(row["media_dir"], "ICON1.PMF"))
    assert not library.get(row["id"])["has_media"]["ICON1.PMF"]
    job = Job(1, "media", "t")
    assert media.extract_all(library, job) == {"images": 1, "files": 3}
    assert library.get(row["id"])["has_media"]["ICON1.PMF"]
    assert media.extract_all(library, only_missing=False)["images"] == 1


def test_convert_film_without_ffmpeg(library, dirs, monkeypatch):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(media=("ICON0.PNG", "ICON1.PMF")))
    scan.scan(library)
    row = library.all()[0]
    monkeypatch.setattr(media, "ffmpeg_path", lambda: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        media.convert_film(library, row["id"])


def test_convert_film_needs_a_film(library, dirs):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(media=("ICON0.PNG",)))
    scan.scan(library)
    with pytest.raises(RuntimeError, match="no ICON1.PMF"):
        media.convert_film(library, library.all()[0]["id"])


def test_convert_film_timeout_cleans_temp(library, dirs, monkeypatch):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(media=("ICON0.PNG", "ICON1.PMF")))
    scan.scan(library)
    row = library.all()[0]
    monkeypatch.setattr(media, "ffmpeg_path", lambda: "/bin/ffmpeg")

    def timeout(*args, **kwargs):
        open(os.path.join(row["media_dir"], "ICON1.mp4.part.mp4"), "wb").write(b"partial")
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(media.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        media.convert_film(library, row["id"])
    assert not any(n.endswith(".part.mp4") for n in os.listdir(row["media_dir"]))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg")
def test_convert_film_with_ffmpeg_on_a_fake_pmf_fails_cleanly(library, dirs):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso(media=("ICON0.PNG", "ICON1.PMF")))
    scan.scan(library)
    row = library.all()[0]
    job = Job(1, "film", "t")
    with pytest.raises(RuntimeError, match="could not convert"):
        media.convert_film(library, row["id"], job)
    assert any("ffmpeg" in line for line in job.lines)
    assert not any(n.endswith(".part.mp4") for n in os.listdir(row["media_dir"]))

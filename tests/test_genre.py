import hashlib
import json
import os

import pytest

from shelf import genre

from .conftest import make_iso, write
from .test_shelf import published


def test_a_disc_carries_its_genre_as_a_tag(shelf):
    write(f"{shelf.discs_dir}/known.iso", make_iso("Known", "ULUS-10080"))
    write(f"{shelf.discs_dir}/unknown.iso", make_iso("Unknown", "ULES-00001"))
    shelf.refresh()
    apps = {a["name"]: a for a in published(shelf)["apps"]}
    assert apps["Known (US)"]["tags"] == ["Adventure"]
    assert "tags" not in apps["Unknown (EU)"]


def test_the_list_is_the_pinned_one():
    with open(genre.FILE, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == genre.PIN["sha256"]
    assert len(genre.PIN["commit"]) == 40 and genre.PIN["license"] == "CC-BY-SA-4.0"
    assert len(genre.GENRES) > 2000
    assert all(0 < len(g) <= 24 for g in genre.GENRES.values())


def test_another_file_is_refused(tmp_path, monkeypatch):
    other = tmp_path / os.path.basename(genre.FILE)
    other.write_bytes(b'game (\n\tserial "ULUS-10080"\n\tgenre "Puzzle"\n)\n')
    monkeypatch.setattr(genre, "FILE", str(other))
    with pytest.raises(RuntimeError):
        genre.load()


def test_parse():
    text = 'game (\n\tcomment "A (USA)"\n\tserial "ulus-10001"\n\tgenre "Racing"\n)\n\ngame (\n\tserial "ULES-00002"\n)\n'
    assert genre.parse(text) == {"ULUS-10001": "Racing"}

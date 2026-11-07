import io
import os
import random

import pytest

from shelf import cso, disc, sfo

from .conftest import make_cso, make_iso, make_sfo, write


def test_sfo():
    assert sfo.parse(make_sfo({"TITLE": "Spiel ü", "PARENTAL_LEVEL": 3})) == {"TITLE": "Spiel ü", "PARENTAL_LEVEL": 3}
    with pytest.raises(sfo.SfoError):
        sfo.parse(b"\0PSX" + b"\0" * 16)


def test_cso_reads_like_the_iso():
    iso = make_iso() + os.urandom(5000)  # random bytes do not compress: raw blocks
    reader = cso.CsoFile(io.BytesIO(make_cso(iso)))
    assert reader.read() == iso
    for _ in range(50):
        start, n = random.randrange(len(iso)), random.randrange(1, 9000)
        reader.seek(start)
        assert reader.read(n) == iso[start:start + n]
    with pytest.raises(cso.CsoError):
        cso.CsoFile(io.BytesIO(b"ZISO" + b"\0" * 40))


@pytest.mark.parametrize("ext", ["iso", "cso"])
def test_read(tmp_path, ext):
    iso = make_iso("Game", "ULUS-10404", media=("ICON0.PNG", "SND0.AT3"))
    write(tmp_path / f"a.{ext}", make_cso(iso) if ext == "cso" else iso)
    found = disc.read(str(tmp_path / f"a.{ext}"))
    assert (found.id, found.title, found.version, found.region) == ("ULUS-10404", "Game", "1.02", "US")
    assert found.media == {"ICON0.PNG": b"ICON0.PNG" * 50, "SND0.AT3": b"SND0.AT3" * 50}


def test_id_from_the_sfo_without_umd_data(tmp_path):
    write(tmp_path / "a.iso", make_iso(disc_id="ULJS-00001", umd_data=False))
    assert disc.read(str(tmp_path / "a.iso")).id == "ULJS-00001"


def test_not_a_psp_disc(tmp_path):
    write(tmp_path / "a.iso", make_iso(disc_id="NOPE", umd_data=False))
    with pytest.raises(disc.DiscError, match="no disc id"):
        disc.read(str(tmp_path / "a.iso"))
    write(tmp_path / "b.iso", b"not an image" * 1000)
    with pytest.raises(Exception):
        disc.read(str(tmp_path / "b.iso"))

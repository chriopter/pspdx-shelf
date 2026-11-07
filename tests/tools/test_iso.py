import os

import pytest

from umdlibrary.tools import iso as isotool
from umdlibrary.tools import sfo

from ..helpers import make_cso, make_iso, make_png, make_sfo, write


def test_read_info_iso(tmp_path):
    path = write(str(tmp_path / "a.iso"), make_iso())
    info = isotool.read_info(path)
    assert info.format == "iso" and info.image_size == info.iso_size == os.path.getsize(path)
    assert info.canonical_id == "ULES-01234" and info.disc_id_source == "umd_data"
    assert info.disc_id == "ULES01234" and info.identifier == "ULES-01234"
    assert info.umd_data == {"identifier": "ULES-01234", "umd_uid": "05FC10F031E498EA",
                             "type_code": "0001", "media_code": "G"}
    assert info.title == "Test Game" and info.region == "EU"
    assert info.has_psp_game
    assert info.sfo["DISC_VERSION"] == "1.02" and info.sfo["PARENTAL_LEVEL"] == 3
    assert set(info.media) == {"ICON0.PNG", "PIC1.PNG"} and info.media["ICON0.PNG"] == len(make_png())
    assert info.volume_id == "ULES01234"


def test_read_info_cso(tmp_path):
    iso = make_iso("Second", "ULUS-10001", media=("ICON0.PNG", "ICON1.PMF", "SND0.AT3", "PIC0.PNG"))
    path = write(str(tmp_path / "b.cso"), make_cso(iso))
    info = isotool.read_info(path)
    assert info.format == "cso" and info.iso_size == len(iso) and info.image_size < len(iso)
    assert info.canonical_id == "ULUS-10001" and info.region == "US"
    assert set(info.media) == {"ICON0.PNG", "ICON1.PMF", "SND0.AT3", "PIC0.PNG"}


def test_disc_id_fallbacks(tmp_path):
    a = write(str(tmp_path / "a.iso"), make_iso(umd_data=False))
    info = isotool.read_info(a)
    assert (info.canonical_id, info.disc_id_source, info.disc_id, info.umd_data) == ("ULES-01234", "sfo", "ULES01234", {})
    b = write(str(tmp_path / "b.iso"), make_iso(umd_data=False, sfo_extra={"DISC_ID": None}, vol_ident="MYVOL"))
    info = isotool.read_info(b)
    assert (info.canonical_id, info.disc_id_source, info.region, info.disc_id) == ("MYVOL", "volume", "unknown", None)
    c = write(str(tmp_path / "c.iso"), make_iso(umd_data=False, sfo_extra={"DISC_ID": None}, vol_ident=""))
    info = isotool.read_info(c)
    assert info.canonical_id is None and info.disc_id_source == "none"
    d = write(str(tmp_path / "d.iso"), make_iso(disc_id="ULJS-00001", umd_data=False))
    assert isotool.read_info(d).region == "JP"
    # A video UMD: the identifier is a title, so the SFO's id (if any) or the volume decides.
    e = write(str(tmp_path / "e.iso"), make_iso(psp_game=False, umd_line="Family Guy Vol 1 Disc 5|EEC|0002|V", vol_ident="FAMILYGUY"))
    info = isotool.read_info(e)
    assert info.umd_data == {"identifier": "Family Guy Vol 1 Disc 5", "umd_uid": "EEC", "type_code": "0002", "media_code": "V"}
    assert (info.canonical_id, info.disc_id_source) == ("FAMILYGUY", "volume")


@pytest.mark.parametrize("raw, expected", [
    (b"ULUS-10404|05FC10F031E498EA|0001|G\x00\x00", {"identifier": "ULUS-10404", "umd_uid": "05FC10F031E498EA", "type_code": "0001", "media_code": "G"}),
    (b"ULUS-10404|05FC10F031E498EA|0001|G   ", {"identifier": "ULUS-10404", "umd_uid": "05FC10F031E498EA", "type_code": "0001", "media_code": "G"}),
    (b"ULES-01234|", {"identifier": "ULES-01234"}),
    (b"\x00\x00", {}),
    (b"ULES-01234", {"identifier": "ULES-01234"}),
])
def test_parse_umd_data(raw, expected):
    assert isotool.parse_umd_data(raw) == expected


@pytest.mark.parametrize("text, expected", [
    ("ULUS10404", "ULUS-10404"), ("ulus-10404", "ULUS-10404"), (" ULES_01234 ", "ULES-01234"),
    ("Family Guy", None), ("", None), (None, None), ("ULUS1040", None),
])
def test_canonical_id(text, expected):
    assert isotool.canonical_id(text) == expected


def test_not_an_iso(tmp_path):
    path = write(str(tmp_path / "x.iso"), b"nothing like an iso" * 5000)
    with pytest.raises(isotool.DiscError, match="not an ISO 9660"):
        isotool.read_info(path)
    empty = write(str(tmp_path / "e.iso"), b"")
    with pytest.raises(isotool.DiscError):
        isotool.read_info(empty)
    with pytest.raises(isotool.DiscError, match="not an .iso"):
        isotool.read_info(str(tmp_path / "x.bin"))


def test_iso_without_psp_game(tmp_path):
    path = write(str(tmp_path / "plain.iso"), make_iso(psp_game=False, umd_data=False, vol_ident="DATA"))
    info = isotool.read_info(path)
    assert not info.has_psp_game and info.sfo == {} and info.media == {}
    assert info.canonical_id == "DATA" and info.disc_id_source == "volume"


def test_broken_sfo_is_reported_not_fatal(tmp_path):
    path = write(str(tmp_path / "a.iso"), make_iso(sfo_bytes=b"\x00PSX" + b"\x00" * 40))
    info = isotool.read_info(path)
    assert info.title is None and "_error" in info.sfo and info.canonical_id == "ULES-01234"


def test_truncated_cso(tmp_path):
    packed = make_cso(make_iso(pad_bytes=100 * 1024))
    path = write(str(tmp_path / "t.cso"), packed[:len(packed) // 2])
    with pytest.raises(isotool.DiscError, match="CSO"):
        isotool.read_info(path)


def test_unicode_title(tmp_path):
    path = write(str(tmp_path / "ゲーム.iso"), make_iso(title="モンスターハンター ポータブル 2nd G", disc_id="ULJM-05500"))
    info = isotool.read_info(path)
    assert info.title == "モンスターハンター ポータブル 2nd G" and info.region == "JP"


def test_extract_media(tmp_path):
    path = write(str(tmp_path / "a.iso"), make_iso(media=("ICON0.PNG", "PIC1.PNG", "ICON1.PMF")))
    out = str(tmp_path / "media")
    found = isotool.extract_media(path, out)
    assert set(found) == {"ICON0.PNG", "PIC1.PNG", "ICON1.PMF"}
    assert open(os.path.join(out, "ICON0.PNG"), "rb").read() == make_png()
    assert open(os.path.join(out, "ICON1.PMF"), "rb").read()[:4] == b"PSMF"
    assert not any(n.endswith(".part") for n in os.listdir(out))


def test_media_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(isotool, "MEDIA_LIMIT", 100)
    path = write(str(tmp_path / "a.iso"), make_iso())
    found = isotool.extract_media(path, str(tmp_path / "m"))
    assert all(v < 0 for v in found.values()) and not os.listdir(tmp_path / "m")


def test_large_sparse_image_is_read_without_touching_the_tail(tmp_path):
    """A 4 GB image: the ISO structures sit at the start, and read_info
    must not read the rest. A sparse file makes this cheap."""
    path = write(str(tmp_path / "big.iso"), make_iso())
    with open(path, "r+b") as f:
        f.truncate(4 * 1024 ** 3 + 2048)
    info = isotool.read_info(path)
    assert info.image_size == 4 * 1024 ** 3 + 2048 and info.canonical_id == "ULES-01234"


@pytest.mark.parametrize("disc_id, region", [
    ("ULES-01234", "EU"), ("UCES-00001", "EU"), ("ULUS-10001", "US"), ("UCUS-98600", "US"),
    ("ULJS-00001", "JP"), ("ULJM-05500", "JP"), ("NPJH-50000", "JP"), ("ULAS-42000", "AS"),
    ("XXXX-00000", "unknown"), (None, "unknown"), ("", "unknown"), ("AB", "unknown"),
])
def test_region_table(disc_id, region):
    assert isotool.region_of(disc_id) == region


def test_cli(tmp_path, capsys):
    path = write(str(tmp_path / "a.iso"), make_iso())
    assert isotool.main([str(path), "--media", str(tmp_path / "m")]) == 0
    out = capsys.readouterr().out
    assert "ULES-01234" in out and "Test Game" in out and "wrote" in out and "05FC10F031E498EA" in out
    write(str(tmp_path / "bad.iso"), b"x" * 100)
    assert isotool.main([str(tmp_path / "bad.iso")]) == 1


def test_sfo_written_by_tests_parses_like_a_real_one():
    values = sfo.parse(make_sfo())
    assert values["TITLE"] == "Test Game" and values["BOOTABLE"] == 1

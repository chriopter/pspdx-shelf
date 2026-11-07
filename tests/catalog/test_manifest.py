import re

import jsonschema
import pytest

from umdlibrary.catalog import manifest, validate
from umdlibrary.tools import iso as isotool


def _row(**over):
    row = {"id": 1, "name": "Test Game.iso", "path": "Test Game.iso", "title": "Test Game",
           "disc_id": "ULES01234", "disc_key": "ULES-01234", "disc_id_source": "umd_data",
           "identifier": "ULES-01234", "languages": ["en", "de"], "languages_from": "override",
           "umd_data": {"identifier": "ULES-01234", "umd_uid": "05FC10F031E498EA", "type_code": "0001", "media_code": "G"},
           "pspdb_status": None, "pspdb_title": None,
           "region": "EU", "format": "iso", "size": 1_234_567_890, "iso_size": 1_234_567_890,
           "mtime": 1_700_000_000.0, "sha256": "ab" * 32, "status": "ok", "primary": True,
           "sfo": {"DISC_VERSION": "1.02", "PSP_SYSTEM_VER": "3.52", "CATEGORY": "UG", "PARENTAL_LEVEL": 3},
           "has_media": {n: n in ("ICON0.PNG", "PIC1.PNG") for n in isotool.MEDIA_FILES}}
    row.update(over)
    return row


@pytest.mark.parametrize("source, name, expected", [
    ("https://psp.lan/umd/ULES-01234", "God of War", "lan.psp.godofwar"),
    ("https://192.168.1.10:8443/umd/X", "Test Game", "10.1.168.192.testgame"),
    ("https://www.example.com/x", "A-B c", "com.example.abc"),
    ("https://user@host.tld./p", "N1", "tld.host.n1"),
    ("https://me.github.io/x", "N", None),
    ("https://psp.lan/x", "日本語", None),
    ("http://psp.lan/x", "N", None),
])
def test_console_id(source, name, expected):
    assert manifest.console_id(source, name) == expected


def test_our_id():
    assert manifest.our_id("ULES-01234") == "local.umd.ules-01234"


def test_display_name():
    assert manifest.display_name(_row()) == "Test Game"
    assert len(manifest.display_name(_row(title="x" * 80))) == 40
    assert manifest.display_name(_row(title=None)) == "ULES-01234"
    jp = manifest.display_name(_row(title="モンスターハンター", disc_id="ULJM-05500", disc_key="ULJM-05500"))
    assert jp == "モンスターハンター ULJM-05500" and re.search(r"[A-Za-z0-9]", jp)
    assert manifest.display_name(_row(title="tab\there")) == "tab here"


def test_summary_description_tags():
    row = _row()
    assert manifest.summary(row) == "UMD ULES-01234, EU, 1.2 GB"
    assert len(manifest.summary(_row(disc_key="X" * 32))) <= 60
    desc = manifest.description(row)
    assert "Title: Test Game" in desc and "DISC_VERSION: 1.02" in desc and "Media: ICON0.PNG, PIC1.PNG" in desc
    assert "Languages: en, de" in desc and "uid 05FC10F031E498EA" in desc
    assert manifest.description(_row(format="cso", iso_size=2_000_000_000)).count("uncompressed") == 1
    assert len(manifest.description(_row(title="y" * 5000))) <= 2500
    tags = manifest.tags(row)
    assert tags == ["game", "umd", "iso", "eu", "ug"] and len(tags) == len(set(tags)) <= 8
    assert "unknown" not in manifest.tags(_row(region="unknown"))


def test_published_at():
    assert manifest.published_at(1_700_000_000) == "2023-11-14T22:13:20Z"
    assert manifest.published_at(0) == "1970-01-01T00:00:01Z"


def test_author_and_publishers():
    assert manifest.author(_row(), {}) is None
    assert manifest.author(_row(), {"ULES-01234": "Sony"}) == "Sony"
    assert manifest.author(_row(disc_id="ules-01234"), {"ULES-01234": "x" * 100}) == "x" * 60


def test_umd_extension_is_flat_and_complete():
    umd = manifest.umd_extension(_row(format="cso", iso_size=99))
    assert set(umd) == {"disc_id", "disc_key", "identifier", "umd_uid", "type_code", "media_code", "title",
                        "disc_version", "psp_system_ver", "required_firmware", "region", "languages",
                        "languages_from", "parental_level", "category", "format", "file", "image_size",
                        "iso_size", "has_media", "pspdb_status", "pspdb_title"}
    assert umd["format"] == "cso" and umd["iso_size"] == 99 and umd["has_media"]["PIC1.PNG"] is True
    # The fields pspdb records, named as pspdb names them, so the two can be compared.
    assert (umd["identifier"], umd["umd_uid"], umd["type_code"], umd["media_code"]) == ("ULES-01234", "05FC10F031E498EA", "0001", "G")
    assert umd["disc_id"] == "ULES01234" and umd["required_firmware"] == "3.52" and umd["languages"] == ["en", "de"]
    assert all(not isinstance(v, dict) for k, v in umd.items() if k != "has_media")


def test_entry_and_manifest_validate():
    row = _row()
    entry = manifest.app_entry(row, "https://psp.lan", {"ULES-01234": "Sony"},
                               {"icon": "apps/local.umd.ules-01234/icon-12345678.png",
                                "screenshots": ["apps/local.umd.ules-01234/picture-12345678.png"]})
    assert entry["type"] == "iso" and entry["category"] == "game" and "installdir" not in entry
    assert entry["source"] == "https://psp.lan/umd/ULES-01234"
    assert entry["releases"][0] == {"tag": "1.02", "published_at": "2023-11-14T22:13:20Z",
                                    "url": "https://psp.lan/umd/ULES-01234.iso", "size": 1_234_567_890,
                                    "sha256": "ab" * 32}
    assert entry["author"] == "Sony" and entry["umd"]["disc_id"] == "ULES01234"
    assert entry["languages"] == ["en", "de"]
    doc = manifest.catalog_document([entry], "2026-09-16T00:00:00Z")
    assert validate.catalog_problems(doc) == []
    m = manifest.pspdx_manifest(row, "https://psp.lan", {})
    assert validate.manifest_problems(m) == []
    assert "umd" not in m and m["release"]["url"].endswith("ULES-01234.iso")
    assert m["languages"] == ["en", "de"]
    assert "languages" not in manifest.pspdx_manifest(_row(languages=[]), "https://psp.lan", {})
    bad = manifest.app_entry(_row(languages=["EN", "x"]), "https://psp.lan", {})
    assert validate.catalog_problems(manifest.catalog_document([bad], "2026-09-16T00:00:00Z"))


@pytest.mark.parametrize("public_url, ok", [
    ("https://psp.lan", True),
    ("https://192.168.1.10", True),
    ("https://192.168.1.10:8443", True),
    ("https://my-nas.home.arpa:443", True),
    ("https://www.psp.lan", True),           # the console drops the www.
    ("https://me.github.io", False),         # would collide with io.github. ids
    ("http://psp.lan", False),
    ("https://psp_lan", False),              # underscore is not a host label
])
def test_source_urls_against_the_schema_regex(public_url, ok):
    entry = manifest.app_entry(_row(), public_url, {})
    doc = manifest.catalog_document([entry], "2026-09-16T00:00:00Z")
    problems = validate.catalog_problems(doc)
    assert (problems == []) == ok, problems


def test_release_url_is_ascii_even_for_odd_keys():
    entry = manifest.app_entry(_row(disc_key="NOID-1A2B3C4D", disc_id=None, title="ゲーム"), "https://psp.lan", {})
    assert re.fullmatch(r"https://[\x21-\x7e]+", entry["releases"][0]["url"])
    doc = manifest.catalog_document([entry], "2026-09-16T00:00:00Z")
    assert validate.catalog_problems(doc) == []


def test_validator_checks_formats():
    doc = manifest.catalog_document([manifest.app_entry(_row(mtime=1_700_000_000), "https://psp.lan", {})],
                                    "not a date")
    problems = validate.catalog_problems(doc)
    assert problems and problems[0].startswith("$.generated_at")
    bad = manifest.app_entry(_row(), "https://psp.lan", {}, {"icon": "ht tp://x y"})
    doc = manifest.catalog_document([bad], "2026-09-16T00:00:00Z")
    assert any("icon" in p for p in validate.catalog_problems(doc))
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate({"schema": "x"}, validate.load_schema("pspdx-v1.json"))

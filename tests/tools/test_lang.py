import pytest

from umdlibrary.tools import lang


@pytest.mark.parametrize("text, expected", [
    ("en", "en"), ("EN", "en"), ("en_GB", "en-gb"), ("pt-BR", "pt-br"), ("English", "en"),
    ("deutsch", "de"), ("zh-Hant", "zh-hant"), ("x", None), ("", None), ("e n", None), ("1234", None),
])
def test_normalize(text, expected):
    assert lang.normalize(text) == expected


def test_parse_codes():
    assert lang.parse_codes("en, de; fr|it/ja  english EN") == ["en", "de", "fr", "it", "ja"]
    assert lang.parse_codes("") == []
    assert len(lang.parse_codes(" ".join(f"a{c}" for c in "abcdefghijklmnopqrstuvwxyz"))) == lang.MAX


def test_from_sfo():
    assert lang.from_sfo({"TITLE": "x"}) == []
    assert lang.from_sfo({"TITLE_00": "ゲーム", "TITLE_01": "Game", "TITLE_04": "Spiel", "TITLE_99": "?"}) == ["ja", "en", "de"]
    assert lang.from_sfo({"TITLE_01": "   "}) == []
    assert lang.from_sfo({"LANGUAGE": "English, German", "Lang": "fr"}) == ["en", "de", "fr"]
    assert lang.from_sfo({"LANGUAGE": 5}) == []


@pytest.mark.parametrize("sfo, region, override, expected", [
    ({}, "JP", None, ["ja"]),
    ({}, "US", None, ["en"]),
    ({}, "EU", None, ["en"]),
    ({}, "KR", None, ["ko"]),
    ({}, "unknown", None, []),
    ({"TITLE_02": "Jeu"}, "EU", None, ["fr"]),
    ({"TITLE_02": "Jeu"}, "EU", ["en", "de"], ["en", "de"]),
    ({}, "EU", [], ["en"]),
])
def test_languages_of(sfo, region, override, expected):
    assert lang.languages_of(sfo, region, override) == expected

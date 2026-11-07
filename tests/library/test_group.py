import os

import pytest

from umdlibrary.library import group, scan

from ..helpers import make_iso, write


@pytest.mark.parametrize("title, expected", [
    ("God of War: Chains of Olympus", "god of war: chains of olympus"),
    ("God of War: Chains of Olympus (Europe)", "god of war: chains of olympus"),
    ("GOD OF WAR: CHAINS OF OLYMPUS [USA]", "god of war: chains of olympus"),
    ("God of War™: Chains of Olympus (v1.01) (EU)", "god of war: chains of olympus"),
    ("God of War: Chains of Olympus [ULES-01234]", "god of war: chains of olympus"),
    ("Tekken 6 Platinum", "tekken 6"),
    ("Tekken 6 (Essentials)", "tekken 6"),
    ("FIFA 08 - European Version", "fifa 08"),
    ("Patapon 2 (En,Fr,De,Es,It)", "patapon 2"),
    ("Lumines (Puzzle Fusion)", "lumines (puzzle fusion)"),     # not a marker: kept
    ("Ｍｏｎｓｔｅｒ　Ｈｕｎｔｅｒ", "monster hunter"),            # NFKC folds full-width
    ("  spaced   out  ", "spaced out"),
    ("", ""),
])
def test_normalize_title(title, expected):
    assert group.normalize_title(title) == expected


@pytest.fixture
def versions(library, dirs):
    """One game in three language versions, one multi-language EU disc of
    another game, and a lone disc."""
    write(os.path.join(dirs["lib"], "gow-eu.iso"), make_iso("God of War: Chains of Olympus", "UCES-00842", vol_ident="UCES00842"), mtime=3)
    write(os.path.join(dirs["lib"], "gow-us.iso"), make_iso("God of War: Chains of Olympus", "UCUS-98653", vol_ident="UCUS98653", media=()), mtime=2)
    write(os.path.join(dirs["lib"], "gow-jp.iso"), make_iso("God of War: Chains of Olympus (Japan)", "UCJS-10071", vol_ident="UCJS10071"), mtime=1)
    write(os.path.join(dirs["lib"], "patapon.iso"), make_iso("Patapon 2", "UCES-01177", vol_ident="UCES01177"), mtime=4)
    write(os.path.join(dirs["lib"], "lone.iso"), make_iso("Lone Disc", "ULJM-05500", vol_ident="ULJM05500"), mtime=5)
    scan.scan(library)
    return library


def test_games(versions):
    versions.language_overrides = lambda: {"UCES-01177": ["en", "fr", "de", "es", "it"]}
    games = {g["key"]: g for g in versions.games()}
    assert set(games) == {"god of war: chains of olympus", "patapon 2", "lone disc"}
    gow = games["god of war: chains of olympus"]
    assert [v["disc_key"] for v in gow["versions"]] == ["UCES-00842", "UCUS-98653", "UCJS-10071"]
    assert gow["regions"] == ["EU", "US", "JP"] and gow["languages"] == ["en", "ja"]
    assert gow["face"]["disc_key"] == "UCES-00842" and gow["title"] == "God of War: Chains of Olympus"
    assert [v["languages"] for v in gow["versions"]] == [["en"], ["en"], ["ja"]]
    patapon = games["patapon 2"]
    assert patapon["languages"] == ["en", "fr", "de", "es", "it"] and len(patapon["versions"]) == 1
    assert patapon["versions"][0]["languages_from"] == "override"
    assert games["lone disc"]["versions"][0]["languages_from"] == "region"
    assert versions.counts()["games"] == 3 and versions.counts()["images"] == 5


def test_face_prefers_a_version_with_an_icon(library, dirs):
    write(os.path.join(dirs["lib"], "a.iso"), make_iso("Game", "ULES-00001", media=(), vol_ident="A"))
    write(os.path.join(dirs["lib"], "b.iso"), make_iso("Game", "ULUS-00001", vol_ident="B"))
    scan.scan(library)
    assert library.games()[0]["face"]["disc_key"] == "ULUS-00001"

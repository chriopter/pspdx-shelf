import hashlib
import json
import os

from shelf import catalog

from .conftest import make_cso, make_iso, write


def published(shelf):
    with open(os.path.join(shelf.data_dir, "catalog.json")) as f:
        return json.load(f)


def test_catalog(shelf):
    iso = make_iso("Game", "ULUS-10404", media=("ICON0.PNG", "PIC1.PNG", "ICON1.PMF", "SND0.AT3"))
    write(f"{shelf.discs_dir}/Game.iso", iso)
    write(f"{shelf.discs_dir}/second.cso", make_cso(make_iso("Second", "ULES-00001", media=())))
    write(f"{shelf.discs_dir}/notes.txt", b"not a disc")
    shelf.refresh()
    doc = published(shelf)
    assert catalog.problems(doc) == []
    sha = hashlib.sha256(iso).hexdigest()
    assert [a["name"] for a in doc["apps"]] == ["Game (US)", "Second (EU)"]
    game = doc["apps"][0]
    assert game["source"] == "https://pspdx-shelf.local/discs/ULUS-10404"
    assert (game["name"], game["type"], game["category"], game["summary"]) == ("Game (US)", "iso", "game", "ULUS-10404, US, 0 MB")
    assert game["game"] == "game"
    assert game["releases"] == [{"tag": "1.02", "published_at": "2023-11-14T22:13:20Z",
                                 "url": "http://pspdx-shelf.base/discs/ULUS-10404.iso", "size": len(iso), "sha256": sha}]
    key = game["media"]["icon"].split("/")[1]
    assert game["media"] == {"icon": f"media/{key}/icon0.png", "screenshots": [f"media/{key}/pic1.png"],
                             "video": f"media/{key}/icon1.pmf", "sound": f"media/{key}/snd0.at3"}
    with open(os.path.join(shelf.data_dir, game["media"]["icon"]), "rb") as f:
        assert f.read() == b"ICON0.PNG" * 50
    assert "media" not in doc["apps"][1]


def test_unchanged_files_are_not_read_again(shelf, monkeypatch):
    write(f"{shelf.discs_dir}/a.iso", make_iso())
    shelf.refresh()
    first = shelf.items[0]
    shelf.refresh()
    assert shelf.items[0] is first
    write(f"{shelf.discs_dir}/a.iso", make_iso(title="Changed"), mtime=1_800_000_000)
    shelf.refresh()
    assert shelf.items[0]["title"] == "Changed"


def test_hashes_survive_a_restart(shelf, monkeypatch):
    write(f"{shelf.discs_dir}/a.iso", make_iso())
    shelf.refresh()
    again = type(shelf)(shelf.discs_dir, shelf.data_dir)
    monkeypatch.setattr("hashlib.sha256", None)
    again.refresh()
    assert again.items[0]["sha256"] == shelf.items[0]["sha256"]


def test_the_newest_file_is_listed_between_equals(shelf):
    write(f"{shelf.discs_dir}/old.iso", make_iso("Old"), mtime=1_700_000_000)
    write(f"{shelf.discs_dir}/new.cso", make_cso(make_iso("New")), mtime=1_700_000_100)
    shelf.refresh()
    assert [a["name"] for a in published(shelf)["apps"]] == ["New (EU)"]
    assert shelf.disc("ULES-01234")["file"] == "new.cso"
    assert next(i for i in shelf.items if i["file"] == "old.iso")["duplicate"] == "new.cso"


def test_a_broken_file_is_shown_not_listed(shelf):
    write(f"{shelf.discs_dir}/broken.iso", b"junk" * 1000)
    write(f"{shelf.discs_dir}/good.iso", make_iso())
    shelf.refresh()
    assert len(published(shelf)["apps"]) == 1
    assert next(i for i in shelf.items if i["file"] == "broken.iso")["error"]


def test_a_name_without_ascii_letters(shelf):
    write(f"{shelf.discs_dir}/a.iso", make_iso(title="モンスターハンター"))
    shelf.refresh()
    assert published(shelf)["apps"][0]["name"] == "モンスターハンター (EU)"
    write(f"{shelf.discs_dir}/a.iso", make_iso(title="モンスターハンター", disc_id="ULXX-01234"), mtime=1_800_000_000)
    shelf.refresh()
    assert published(shelf)["apps"][0]["name"] == "モンスターハンター ULXX-01234"


def test_the_regions_of_one_game_share_it(shelf):
    write(f"{shelf.discs_dir}/eu.iso", make_iso(title="LocoRoco™ 2", disc_id="UCES-01059"))
    write(f"{shelf.discs_dir}/us.iso", make_iso(title="LOCOROCO 2", disc_id="UCUS-98662"))
    shelf.refresh()
    assert {a["game"] for a in published(shelf)["apps"]} == {"locoroco 2"}


def test_all_discs_are_listed_before_the_slow_part(shelf, monkeypatch):
    for n in range(3):
        write(f"{shelf.discs_dir}/{n}.iso", make_iso(title=f"Game {n}", disc_id=f"ULUS-1000{n}"))
    clock = iter(range(0, 1000, 11))
    monkeypatch.setattr("shelf.shelf.time.monotonic", lambda: next(clock))
    seen = []
    publish = shelf._publish
    monkeypatch.setattr(shelf, "_publish", lambda apps, items, final: (seen.append(len(apps)), publish(apps, items, final)))
    shelf.refresh()
    # Every disc is on the page before the first is hashed; the catalog fills one by one.
    assert seen == [0, 1, 2, 3, 3]


def test_two_discs_of_one_title_and_region_are_two_apps(shelf):
    write(f"{shelf.discs_dir}/a.iso", make_iso(title="Daxter", disc_id="UCUS-98654"))
    write(f"{shelf.discs_dir}/b.iso", make_iso(title="DAXTER", disc_id="UCUS-98618"))
    shelf.refresh()
    assert sorted(a["name"] for a in published(shelf)["apps"]) == ["DAXTER (US)", "Daxter (UCUS-98654)"]


def test_a_restart_lists_known_discs_at_once(shelf, monkeypatch):
    write(f"{shelf.discs_dir}/a.iso", make_iso(media=("ICON0.PNG",)))
    shelf.refresh()
    again = type(shelf)(shelf.discs_dir, shelf.data_dir)
    seen = []
    publish = again._publish
    monkeypatch.setattr(again, "_publish", lambda apps, items, final: (seen.append([a["media"] for a in apps]), publish(apps, items, final)))
    again.refresh()
    assert seen[0] == seen[-1] == [published(shelf)["apps"][0]["media"]] and seen[0][0]["icon"]


def test_the_highest_version_and_a_release_win(shelf):
    write(f"{shelf.discs_dir}/Game (Beta).iso", make_iso("Beta", version="1.00"), mtime=1_800_000_000)
    write(f"{shelf.discs_dir}/Game (v2.00).iso", make_iso("Two", version="2.00"), mtime=1_600_000_000)
    write(f"{shelf.discs_dir}/Game.iso", make_iso("One", version="1.00"), mtime=1_700_000_000)
    shelf.refresh()
    assert [a["name"] for a in published(shelf)["apps"]] == ["Two (EU)"]
    os.remove(f"{shelf.discs_dir}/Game (v2.00).iso")
    shelf.refresh()
    assert [a["name"] for a in published(shelf)["apps"]] == ["One (EU)"]

import hashlib
import json
import os
import re

from umdlibrary.catalog import build, manifest, validate
from umdlibrary.jobs.runner import Job
from umdlibrary.library import hash as hashmod
from umdlibrary.library import scan

from ..helpers import make_cso, make_iso, write


def _fill(library, dirs):
    write(os.path.join(dirs["lib"], "Test Game.iso"), make_iso(), mtime=1_700_000_000)
    write(os.path.join(dirs["lib"], "second.cso"),
          make_cso(make_iso("Second Game", "ULUS-10001", media=("ICON0.PNG", "PIC1.PNG", "PIC0.PNG", "ICON1.PMF", "SND0.AT3"),
                            vol_ident="ULUS10001")), mtime=1_700_100_000)
    write(os.path.join(dirs["lib"], "older dup.iso"), make_iso(), mtime=1_600_000_000)
    write(os.path.join(dirs["lib"], "junk.iso"), b"junk" * 1000)
    write(os.path.join(dirs["lib"], "nohash.iso"), make_iso("No Hash", "ULES-00002", vol_ident="ULES00002"))
    scan.scan(library)


def test_build_validates_and_lays_out_media(library, dirs):
    _fill(library, dirs)
    nohash = [r for r in library.all() if r["name"] == "nohash.iso"][0]
    for r in library.all():
        if r["id"] != nohash["id"]:
            hashmod.hash_image(library, r["id"])
    job = Job(1, "catalog", "t")
    report = build.build(library, "https://psp.lan", {"ULUS-10001": "Publisher"}, dirs["out"], job)
    assert report["apps"] == 2 and report["media_files"] == 7
    reasons = {s["name"]: s["reason"] for s in report["skipped"]}
    assert "waiting for a hash" in reasons["nohash.iso"]
    assert "duplicate" in reasons["older dup.iso"]
    assert "not readable" in reasons["junk.iso"]
    root = os.path.join(dirs["out"], "catalog")
    doc = json.load(open(os.path.join(root, "catalog.json"), encoding="utf-8"))
    assert validate.catalog_problems(doc) == []
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", doc["generated_at"])
    assert [a["id"] for a in doc["apps"]] == ["local.umd.ules-01234", "local.umd.ulus-10001"]
    second = doc["apps"][1]
    assert second["author"] == "Publisher"
    for field, stem, suffix in (("icon", "icon", ".png"), ("video", "film", ".pmf"), ("sound", "sound", ".at3")):
        path = second["media"][field]
        assert re.fullmatch(rf"apps/local\.umd\.ulus-10001/{stem}-[0-9a-f]{{8}}{suffix}", path)
        data = open(os.path.join(root, *path.split("/")), "rb").read()
        assert hashlib.sha256(data).hexdigest()[:8] in path
    assert len(second["media"]["screenshots"]) == 2 and "picture-" in second["media"]["screenshots"][0]
    assert second["releases"][0]["url"] == "https://psp.lan/umd/ULUS-10001.cso"
    assert second["umd"]["format"] == "cso" and second["umd"]["iso_size"] > second["umd"]["image_size"]
    assert second["languages"] == ["en"] and second["umd"]["languages_from"] == "region"
    # Compact JSON, one line, as the reference catalog writes it.
    assert open(os.path.join(root, "catalog.json"), encoding="utf-8").read().count("\n") == 1
    # One .pspdx per published disc, each valid.
    pspdx = sorted(os.listdir(os.path.join(root, "pspdx")))
    assert pspdx == ["ULES-01234.pspdx", "ULUS-10001.pspdx"]
    for name in pspdx:
        m = json.load(open(os.path.join(root, "pspdx", name), encoding="utf-8"))
        assert validate.manifest_problems(m) == [], name
    assert build.published(dirs["out"])["apps"] == 2
    assert build.published_catalog(dirs["out"]) == doc
    assert job.state == "queued" and any("published 2 apps" in line for line in job.lines)
    assert not [n for n in os.listdir(dirs["out"]) if n.startswith(".catalog-build")]


def test_preview_says_who_waits(library, dirs):
    _fill(library, dirs)
    pv = build.preview(library, "https://psp.lan", {})
    assert pv["catalog"]["apps"] == [] and len(pv["skipped"]) == 5 and pv["problems"] == []


def test_failed_build_keeps_the_previous_one(library, dirs, monkeypatch):
    _fill(library, dirs)
    hashmod.hash_missing(library)
    build.build(library, "https://psp.lan", {}, dirs["out"])
    before = build.published_catalog(dirs["out"])
    # A public URL the schema refuses: the build must raise and publish nothing.
    try:
        build.build(library, "https://me.github.io", {}, dirs["out"])
    except RuntimeError as exc:
        assert "does not validate" in str(exc)
    else:
        raise AssertionError("expected the build to fail")
    assert build.published_catalog(dirs["out"]) == before
    assert not [n for n in os.listdir(dirs["out"]) if n.startswith(".catalog-build")]
    # A crash while writing also leaves the old build and no temp dir.
    monkeypatch.setattr(build.shutil, "copyfile", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    try:
        build.build(library, "https://psp.lan", {}, dirs["out"])
    except OSError:
        pass
    assert build.published_catalog(dirs["out"]) == before
    assert not [n for n in os.listdir(dirs["out"]) if n.startswith(".catalog-build")]


def test_media_for_names_by_bytes(library, dirs):
    _fill(library, dirs)
    row = library.by_key("ULES-01234")
    fields, copies = build.media_for(row, manifest.our_id(row["disc_key"]))
    assert set(fields) == {"icon", "screenshots"} and len(copies) == 2
    icon = open(os.path.join(row["media_dir"], "ICON0.PNG"), "rb").read()
    assert fields["icon"].endswith(f"icon-{hashlib.sha256(icon).hexdigest()[:8]}.png")


def test_language_versions_are_separate_apps(library, dirs, service):
    """One game, three discs: each its own app with its own id and
    languages; a multi-language EU disc says so through the override."""
    write(os.path.join(dirs["lib"], "gow-eu.iso"), make_iso("God of War: Chains of Olympus", "UCES-00842", vol_ident="UCES00842"))
    write(os.path.join(dirs["lib"], "gow-us.iso"), make_iso("God of War: Chains of Olympus", "UCUS-98653", vol_ident="UCUS98653"))
    write(os.path.join(dirs["lib"], "gow-jp.iso"), make_iso("God of War: Chains of Olympus (Japan)", "UCJS-10071", vol_ident="UCJS10071"))
    write(os.path.join(dirs["lib"], "patapon.iso"), make_iso("Patapon 2", "UCES-01177", vol_ident="UCES01177"))
    service.apply_settings({"languages": {"UCES-01177": "en, fr, de, es, it"}})
    scan.scan(library)
    hashmod.hash_missing(library)
    build.build(library, "https://psp.lan", {}, dirs["out"])
    doc = build.published_catalog(dirs["out"])
    apps = {a["id"]: a for a in doc["apps"]}
    assert set(apps) == {"local.umd.uces-00842", "local.umd.uces-01177", "local.umd.ucjs-10071", "local.umd.ucus-98653"}
    assert apps["local.umd.uces-00842"]["languages"] == ["en"]
    assert apps["local.umd.ucus-98653"]["languages"] == ["en"]
    assert apps["local.umd.ucjs-10071"]["languages"] == ["ja"]
    assert apps["local.umd.uces-01177"]["languages"] == ["en", "fr", "de", "es", "it"]
    assert apps["local.umd.uces-01177"]["umd"]["languages_from"] == "override"
    assert len({a["source"] for a in doc["apps"]}) == 4
    assert validate.catalog_problems(doc) == []
    for key in ("UCES-00842", "UCES-01177"):
        m = json.load(open(os.path.join(dirs["out"], "catalog", "pspdx", f"{key}.pspdx"), encoding="utf-8"))
        assert validate.manifest_problems(m) == [] and "languages" in m

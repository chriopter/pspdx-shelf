import json
import os
import time

from umdlibrary.catalog import build
from umdlibrary.library import hash as hashmod
from umdlibrary.library import scan

from ..helpers import make_iso, write

PAGES = ["/", "/scan", "/hash", "/rename", "/catalog", "/settings", "/jobs", "/logs", "/about", "/api/jobs"]


def test_pages_render_empty(client):
    for url in PAGES:
        assert client.get(url).status_code == 200, url
    assert b"No images" in client.get("/").data
    assert client.get("/disc/1").status_code == 404
    assert client.get("/jobs/1").status_code == 404
    assert client.get("/catalog/catalog.json").status_code == 404
    assert client.get("/umd/ULES-01234.iso").status_code == 404
    assert client.get("/umd/ULES-01234.pspdx").status_code == 404
    assert b"LAN" in client.get("/about").data and b"MIT" in client.get("/about").data


def test_pages_with_discs(client, library, two_discs):
    scan.scan(library)
    for url in PAGES + ["/disc/1", "/disc/2", "/?region=EU", "/?format=cso&sort=size", "/?missing=ICON1.PMF",
                        "/?dup=1", "/?q=zweites", "/rename?pattern={disc_id}.{ext}", "/rename?pattern={bad}"]:
        r = client.get(url)
        assert r.status_code == 200, url
    page = client.get("/").data.decode()
    assert "Test Game" in page and "Zweites Spiel" in page
    assert "Zweites" not in client.get("/?region=EU").data.decode()
    assert "Test Game" not in client.get("/?format=cso").data.decode()
    detail = client.get("/disc/1").data.decode()
    assert "ULES-01234" in detail and "PARAM.SFO" in detail and "local.umd.ules-01234" in detail
    assert "lan.psp.testgame" in detail          # the console id
    assert "unknown field" in client.get("/rename?pattern={bad}").data.decode()


def test_media_routes(client, library, two_discs):
    scan.scan(library)
    r = client.get("/media/1/ICON0.PNG")
    assert r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n" and r.mimetype == "image/png"
    r = client.get("/media/2/ICON1.PMF")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    assert client.get("/media/1/ICON1.PMF").status_code == 404
    assert client.get("/media/1/../settings.json").status_code == 404
    assert client.get("/media/1/EBOOT.PBP").status_code == 404
    assert client.get("/media/9/ICON0.PNG").status_code == 404


def test_served_files_and_range(client, library, service, two_discs, dirs):
    scan.scan(library)
    hashmod.hash_missing(library)
    build.build(library, service.settings.public_url(), {}, dirs["out"])
    r = client.get("/catalog/catalog.json")
    assert r.status_code == 200 and r.mimetype == "application/json"
    doc = json.loads(r.data)
    assert len(doc["apps"]) == 2
    icon = doc["apps"][0]["media"]["icon"]
    assert client.get("/catalog/" + icon).status_code == 200
    assert client.get("/catalog/apps/nope/icon-00000000.png").status_code == 404
    assert client.get("/catalog/apps/../build.json").status_code == 404
    assert client.get("/catalog/apps/%2e%2e/build.json").status_code == 404
    m = client.get("/umd/ULES-01234.pspdx")
    assert m.status_code == 200 and json.loads(m.data)["name"] == "Test Game"
    assert client.get("/umd/ULES-01234", follow_redirects=False).status_code == 302
    assert client.get("/umd/../ULES-01234").status_code == 404
    assert client.get("/umd/%2e%2e.pspdx").status_code == 404
    assert client.get("/umd/NOPE").status_code == 404
    # The image, whole and in ranges.
    whole = client.get("/umd/ULES-01234.iso")
    data = open(two_discs[0], "rb").read()
    assert whole.status_code == 200 and whole.data == data
    assert whole.headers["Accept-Ranges"] == "bytes"
    part = client.get("/umd/ULES-01234.iso", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.data == data[100:200]
    assert part.headers["Content-Range"] == f"bytes 100-199/{len(data)}"
    tail = client.get("/umd/ULES-01234.iso", headers={"Range": "bytes=-16"})
    assert tail.status_code == 206 and tail.data == data[-16:]
    beyond = client.get("/umd/ULES-01234.iso", headers={"Range": f"bytes={len(data) + 10}-"})
    assert beyond.status_code == 416
    # Wrong extension for the format, unknown ids, other extensions.
    assert client.get("/umd/ULES-01234.cso").status_code == 404
    assert client.get("/umd/ULUS-10001.cso").status_code == 200
    assert client.get("/umd/ULUS-10001.iso").status_code == 404
    assert client.get("/umd/NOPE.iso").status_code == 404
    assert client.get("/umd/ULES-01234.exe").status_code == 404
    # The catalog page shows the published state.
    page = client.get("/catalog").data.decode()
    assert "2 apps" in page and "Validates" in page


def test_duplicate_is_flagged_and_newest_served(client, library, dirs):
    old = write(os.path.join(dirs["lib"], "old.iso"), make_iso(), mtime=1_600_000_000)
    new = write(os.path.join(dirs["lib"], "new.iso"), make_iso(title="Newer"), mtime=1_700_000_000)
    scan.scan(library)
    page = client.get("/?dup=1").data.decode()
    assert "older duplicate" in page and page.count("duplicate") >= 2
    assert client.get("/umd/ULES-01234.iso").data == open(new, "rb").read()


def _wait(service, job):
    for _ in range(200):
        if job.state in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job.id} still {job.state}")


def test_actions_queue_jobs(client, service, library, two_discs):
    service.jobs.start()
    r = client.post("/scan/run")
    assert r.status_code == 302 and r.headers["Location"].endswith("/jobs/1")
    job = _wait(service, service.jobs.get(1))
    assert job.state == "done" and job.result["added"] == 2
    assert client.get("/jobs/1").status_code == 200
    api = client.get("/api/jobs/1").json
    assert api["state"] == "done" and api["percent"] == 100 and api["lines"]
    _wait(service, service.jobs.get(int(client.post("/hash/run").headers["Location"].rsplit("/", 1)[1])))
    assert library.counts()["unhashed"] == 0
    _wait(service, service.jobs.get(int(client.post("/catalog/build").headers["Location"].rsplit("/", 1)[1])))
    assert client.get("/catalog/catalog.json").status_code == 200
    _wait(service, service.jobs.get(int(client.post("/scan/media", data={"all": "1"}).headers["Location"].rsplit("/", 1)[1])))
    r = client.post("/rename/apply", data={"pattern": "{disc_id}.{ext}"})
    job = _wait(service, service.jobs.get(int(r.headers["Location"].rsplit("/", 1)[1])))
    assert job.result["renamed"] == 2 and sorted(os.listdir(os.path.dirname(two_discs[0]))) == ["ULES-01234.iso", "ULUS-10001.cso"]
    assert client.post("/rename/apply", data={"pattern": "{bad}"}).status_code == 302
    assert client.post("/disc/1/film").status_code == 302
    assert client.post("/disc/99/film").status_code == 404
    _wait(service, service.jobs.all()[0])
    assert client.post("/disc/1/reread").status_code == 302
    assert len(client.get("/api/jobs").json["jobs"]) == 6
    assert client.post("/jobs/1/cancel").status_code == 302   # done already: harmless
    assert client.get("/jobs").status_code == 200


def test_settings_pages(client, service):
    good = {"library_dir": service.settings["library_dir"], "output_dir": service.settings["output_dir"],
            "host": "192.168.1.10", "http_port": "8080", "public_url": "https://umd.home:8443",
            "rename_pattern": "{title}.{ext}", "watch_interval": "30", "catalog_name": "Mine", "log_lines": "100"}
    r = client.post("/settings", data=good)
    assert r.status_code == 302 and "saved=1" in r.headers["Location"]
    assert service.settings["host"] == "192.168.1.10" and service.settings.public_url() == "https://umd.home:8443"
    assert "https://umd.home:8443/catalog/catalog.json" in client.get("/catalog").data.decode()
    r = client.post("/settings", data=dict(good, host="bad_host"))
    assert "error=" in r.headers["Location"] and service.settings["host"] == "192.168.1.10"
    r = client.post("/settings", data=dict(good, rename_pattern="{nope}"))
    assert "error=" in r.headers["Location"]
    assert client.get(r.headers["Location"]).status_code == 200
    client.post("/settings/publishers", data={"disc_id": "ules-01234", "publisher": "Sony"})
    assert service.settings["publishers"] == {"ULES-01234": "Sony"}
    assert "Sony" in client.get("/settings").data.decode()
    client.post("/settings/publishers", data={"remove": "ULES-01234"})
    assert service.settings["publishers"] == {}
    client.post("/scan/watch", data={"enabled": "1", "interval": "15"})
    assert service.settings["watch_enabled"] is True and service.settings["watch_interval"] == 15
    assert "On:" in client.get("/scan").data.decode()
    client.post("/scan/watch", data={"enabled": "0"})
    assert service.settings["watch_enabled"] is False
    client.post("/rename/pattern", data={"pattern": "{disc_id}.{ext}"})
    assert service.settings["rename_pattern"] == "{disc_id}.{ext}"


def test_bad_route_inputs_are_rejected(client):
    assert client.get("/?format=../../iso").status_code == 400
    assert client.get("/?missing=../ICON0.PNG").status_code == 400
    assert client.post("/rename/apply", data={"pattern": "{disc_id}.{ext}", "id": "nope"}).status_code == 400
    assert client.post("/settings", data={"library_dir": "x" * 1001}).status_code == 400


def test_logs_page(client, service):
    import logging
    logging.getLogger("test").info("a line to find")
    assert "a line to find" in client.get("/logs").data.decode()
    assert client.get("/logs?n=5").status_code == 200


def test_versions_are_grouped_and_language_filter(client, library, service, dirs):
    write(os.path.join(dirs["lib"], "gow-eu.iso"), make_iso("God of War: Chains of Olympus", "UCES-00842", vol_ident="UCES00842"))
    write(os.path.join(dirs["lib"], "gow-us.iso"), make_iso("God of War: Chains of Olympus", "UCUS-98653", vol_ident="UCUS98653"))
    write(os.path.join(dirs["lib"], "gow-jp.iso"), make_iso("God of War: Chains of Olympus (Japan)", "UCJS-10071", vol_ident="UCJS10071"))
    write(os.path.join(dirs["lib"], "patapon.iso"), make_iso("Patapon 2", "UCES-01177", vol_ident="UCES01177"))
    client.post("/settings/languages", data={"disc_id": "uces-01177", "languages": "en, fr, de, es, it"})
    assert service.settings["languages"] == {"UCES-01177": ["en", "fr", "de", "es", "it"]}
    scan.scan(library)
    page = client.get("/").data.decode()
    assert page.count('class="tile game') == 2 and "3 versions" in page
    assert "UCES-00842" in page and "UCUS-98653" in page and "UCJS-10071" in page
    assert page.index('class="badge region">EU') < page.index('class="badge region">US') < page.index('class="badge region">JP')
    only_ja = client.get("/?lang=ja").data.decode()
    assert only_ja.count('class="tile game') == 1 and "UCJS-10071" in only_ja and "UCES-00842" not in only_ja
    assert "Patapon" not in only_ja
    de = client.get("/?lang=de").data.decode()
    assert "Patapon" in de and "God of War" not in de
    # The detail page lists the versions side by side.
    eu = [r for r in library.all() if r["disc_key"] == "UCES-00842"][0]
    detail = client.get(f"/disc/{eu['id']}").data.decode()
    assert "Versions of this game" in detail and detail.count("<tr class=") >= 3 and "UCJS-10071" in detail
    assert "from the region" in detail
    client.post("/settings/languages", data={"remove": "UCES-01177"})
    assert service.settings["languages"] == {}


def test_verify_page_and_job(client, library, service, dirs, tmp_path):
    assert b"Off" in client.get("/verify").data
    service.apply_settings({"pspdb_dir": str(tmp_path / "nowhere")})
    assert b"has no" in client.get("/verify").data
    root = tmp_path / "pspdb" / "catalog" / "iso" / "v6"
    root.mkdir(parents=True)
    known = write(os.path.join(dirs["lib"], "known.iso"), make_iso("Known", "ULUS-10404", vol_ident="ULUS10404"))
    import hashlib
    sha = hashlib.sha256(open(known, "rb").read()).hexdigest()
    (root / f"{sha}-ingest.json").write_text(json.dumps({"sha256": sha, "size_bytes": os.path.getsize(known),
                                                          "metadata": {"identifier": "ULUS-10404", "title": "Known Game"}}))
    service.apply_settings({"pspdb_dir": str(tmp_path / "pspdb")})
    scan.scan(library)
    hashmod.hash_missing(library)
    service.jobs.start()
    r = client.post("/verify/run")
    job = _wait(service, service.jobs.get(int(r.headers["Location"].rsplit("/", 1)[1])))
    assert job.result["known"] == 1
    assert "known dump" in client.get("/verify").data.decode()
    assert "known dump" in client.get("/").data.decode()
    assert "Known Game" in client.get("/disc/1").data.decode()

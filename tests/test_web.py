import json

import pytest

from shelf import web

from .conftest import make_cso, make_iso, write


@pytest.fixture
def client(shelf):
    write(f"{shelf.discs_dir}/game.cso", make_cso(make_iso("Game", "ULUS-10404")))
    write(f"{shelf.discs_dir}/broken.iso", b"junk" * 1000)
    shelf.refresh()
    return web.create(shelf).test_client()


def test_pages(client):
    page = client.get("/").get_data(as_text=True)
    assert "Game" in page and "broken.iso" in page and "https://psp.lan/" in page
    assert "ULUS-10404" in client.get("/discs/ULUS-10404").get_data(as_text=True)
    assert client.get("/discs/ULES-99999").status_code == 404


def test_catalog_and_media(client):
    doc = json.loads(client.get("/catalog.json").data)
    assert [a["name"] for a in doc["apps"]] == ["Game (US)"]
    assert client.get("/" + doc["apps"][0]["media"]["icon"]).data == b"ICON0.PNG" * 50
    assert client.get("/media/../catalog.json").status_code == 404


def test_catalog_gzipped_when_asked(client):
    import gzip
    plain = client.get("/catalog.json")
    packed = client.get("/catalog.json", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in plain.headers and packed.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(packed.data) == plain.data


def test_download_resumes(client, shelf):
    with open(f"{shelf.discs_dir}/game.cso", "rb") as f:
        image = f.read()
    whole = client.get("/discs/ULUS-10404.cso")
    assert whole.status_code == 200 and whole.data == image
    part = client.get("/discs/ULUS-10404.cso", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.data == image[100:200]
    assert client.get("/discs/ULUS-10404.iso").status_code == 404


def test_rebuild(client, shelf):
    assert client.post("/rebuild").status_code == 303
    assert shelf._force


def test_a_disc_still_being_read_has_its_page(shelf):
    write(f"{shelf.discs_dir}/game.iso", make_iso("Game", "ULUS-10404"))
    shelf._list([shelf._identify(shelf._files()[0])], final=False)
    client = web.create(shelf).test_client()
    assert "pending" in client.get("/").get_data(as_text=True)
    assert "Still being read" in client.get("/discs/ULUS-10404").get_data(as_text=True)


def test_a_password_is_the_path(shelf):
    write(f"{shelf.discs_dir}/game.iso", make_iso("Game", "ULUS-10404"))
    shelf.url += "/1234567890123456"
    shelf.refresh()
    from werkzeug.test import Client
    client = Client(web.mounted(shelf, "/1234567890123456"))
    assert client.get("/").status_code == 404 and client.get("/catalog.json").status_code == 404
    page = client.get("/1234567890123456/").get_data(as_text=True)
    assert 'href="/1234567890123456/static/style.css"' in page and 'href="/1234567890123456/discs/ULUS-10404"' in page
    catalog = json.loads(client.get("/1234567890123456/catalog.json").get_data())
    assert catalog["apps"][0]["releases"][0]["url"] == "https://psp.lan/1234567890123456/discs/ULUS-10404.iso"
    assert client.get("/1234567890123456/" + catalog["apps"][0]["media"]["icon"]).status_code == 200
    assert client.get("/1234567890123456/discs/ULUS-10404.iso").status_code == 200
    assert client.post("/1234567890123456/rebuild").headers["Location"].endswith("/1234567890123456/")

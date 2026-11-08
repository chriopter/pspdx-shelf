"""The pages and the files PSPDX fetches. Plain HTTP; HTTPS is the proxy's job."""
import json

import functools
import gzip
import hmac
import os

from flask import Flask, Response, abort, redirect, render_template, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from . import catalog
from .catalog import size

FLAGS = {"EU": "🇪🇺", "US": "🇺🇸", "JP": "🇯🇵", "KR": "🇰🇷", "AS": "🌏"}


@functools.lru_cache(maxsize=8)
def _served(path: str, mtime: float, base: str, zipped: bool) -> bytes:
    with open(path, "rb") as f:
        body = catalog.served(f.read(), base)
    return gzip.compress(body, 9) if zipped else body


def served(path: str, base: str, zipped: bool) -> bytes:
    """The catalog for base, made once per base and catalog."""
    return _served(path, os.path.getmtime(path), base, zipped)


def create(shelf, password: str = "") -> Flask:
    """With a password, everything asks for it, HTTP Basic, any user name:
    the pages in a browser, and the catalog and downloads in PSPDX."""
    app = Flask(__name__)
    # Behind a proxy (Caddy, Tailscale) the address asked for is in its
    # X-Forwarded headers: one proxy in front is trusted for them.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_port=1)

    @app.before_request
    def ask():
        given = request.authorization.password if request.authorization else None
        if password and not (given and hmac.compare_digest(given.encode(), password.encode())):
            return Response("A password is needed.\n", 401, {"WWW-Authenticate": 'Basic realm="pspdx-shelf"'})

    app.jinja_env.filters["size"] = size
    app.jinja_env.filters["flag"] = lambda region: FLAGS.get(region, "")
    app.jinja_env.filters["json"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)

    @app.get("/")
    def index():
        return render_template("index.html", shelf=shelf)

    @app.post("/rebuild")
    def rebuild():
        shelf.rebuild()
        return redirect("/", 303)

    @app.get("/discs/<disc_id>")
    def disc(disc_id):
        item = shelf.disc(disc_id) or abort(404)
        return render_template("disc.html", shelf=shelf, item=item)

    @app.get("/discs/<disc_id>.<fmt>")
    def image(disc_id, fmt):
        item = shelf.disc(disc_id)
        if not item or item["format"] != fmt:
            abort(404)
        # conditional: Range requests get 206, so a download can resume.
        return send_from_directory(shelf.discs_dir, item["file"], as_attachment=True,
                                   download_name=f"{disc_id}.{fmt}", conditional=True, max_age=0)

    @app.get("/catalog.json")
    def catalog_json():
        # Downloads point back the way this request came: the LAN address at
        # home, the VPN's or the proxy's from outside. PSPDX asks for gzip,
        # and over a PSP's radio every kilobyte counts.
        path = os.path.join(shelf.data_dir, "catalog.json")
        if not os.path.exists(path):
            abort(404)
        zipped = "gzip" in request.headers.get("Accept-Encoding", "")
        body = served(path, request.host_url, zipped)
        response = Response(body, mimetype="application/json", headers={"Cache-Control": "no-cache", "Vary": "Accept-Encoding"})
        if zipped:
            response.headers["Content-Encoding"] = "gzip"
        return response

    @app.get("/media/<path:path>")
    def media(path):
        return send_from_directory(shelf.media_dir, path)

    return app

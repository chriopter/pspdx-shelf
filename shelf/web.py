"""The pages and the files PSPDX fetches. Plain HTTP; HTTPS is the proxy's job."""
import json

from flask import Flask, abort, redirect, render_template, request, send_from_directory
from werkzeug.exceptions import NotFound
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from .catalog import size

FLAGS = {"EU": "🇪🇺", "US": "🇺🇸", "JP": "🇯🇵", "KR": "🇰🇷", "AS": "🌏"}


def mounted(shelf, prefix: str):
    """The app at prefix, /<password>, and 404 everywhere else."""
    app = create(shelf)
    return DispatcherMiddleware(NotFound(), {prefix: app}) if prefix else app


def create(shelf) -> Flask:
    app = Flask(__name__)
    app.jinja_env.filters["size"] = size
    app.jinja_env.filters["flag"] = lambda region: FLAGS.get(region, "")
    app.jinja_env.filters["json"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)

    @app.get("/")
    def index():
        return render_template("index.html", shelf=shelf)

    @app.post("/rebuild")
    def rebuild():
        shelf.rebuild()
        return redirect(request.script_root + "/", 303)

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
        if "gzip" not in request.headers.get("Accept-Encoding", ""):
            return send_from_directory(shelf.data_dir, "catalog.json", max_age=0)
        response = send_from_directory(shelf.data_dir, "catalog.json.gz", mimetype="application/json", max_age=0)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Vary"] = "Accept-Encoding"
        return response

    @app.get("/media/<path:path>")
    def media(path):
        return send_from_directory(shelf.media_dir, path)

    return app

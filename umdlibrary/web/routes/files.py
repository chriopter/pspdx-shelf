"""What the PSP fetches: the published catalog and its media, the images
with HTTP range support so a download can resume, and the manifests.
All plain HTTP; the reverse proxy that adds HTTPS goes in front."""
from __future__ import annotations

import os

from flask import Blueprint, abort, send_file, send_from_directory

from ...catalog.build import CATALOG_DIR
from . import service, valid_catalog_path, valid_disc_key

bp = Blueprint("files", __name__)


def _catalog_dir() -> str:
    """Return the published catalog directory."""
    return os.path.join(service().output_dir, CATALOG_DIR)


@bp.route("/catalog/catalog.json")
def catalog_json():
    """Serve the published catalog JSON."""
    return send_from_directory(_catalog_dir(), "catalog.json", mimetype="application/json",
                               conditional=True, max_age=0)


@bp.route("/catalog/apps/<path:name>")
def catalog_media(name: str):
    """Serve published app media below catalog/apps."""
    name = valid_catalog_path(name)
    return send_from_directory(os.path.join(_catalog_dir(), "apps"), name, conditional=True)


@bp.route("/umd/<key>.pspdx")
def manifest(key: str):
    """Serve one published PSPDX manifest by disc key."""
    key = valid_disc_key(key)
    return send_from_directory(os.path.join(_catalog_dir(), "pspdx"), key + ".pspdx",
                               mimetype="application/json", conditional=True, max_age=0)


@bp.route("/umd/<key>.<ext>")
def image(key: str, ext: str):
    """Serve one primary image by disc key and extension."""
    key = valid_disc_key(key)
    if ext not in ("iso", "cso"):
        abort(404)
    row = service().library.by_key(key)
    if row is None or row["format"] != ext or not os.path.exists(row["abs_path"]):
        abort(404)
    # send_file with conditional=True answers Range requests with 206.
    return send_file(row["abs_path"], mimetype="application/octet-stream", as_attachment=True,
                     download_name=f"{key}.{ext}", conditional=True, max_age=0)


@bp.route("/umd/<key>")
def source(key: str):
    """The source URL the catalog names: a human lands on the disc page."""
    from flask import redirect, url_for
    key = valid_disc_key(key)
    row = service().library.by_key(key)
    if row is None:
        abort(404)
    return redirect(url_for("library.disc", image_id=row["id"]))

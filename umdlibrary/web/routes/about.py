"""About: versions, what the service does and does not do, the license."""
from __future__ import annotations

import platform
import sys
from importlib import metadata

from flask import Blueprint, render_template

from ...library import media as mediamod
from . import service

bp = Blueprint("about", __name__)


@bp.route("/about")
def page():
    """Show version and environment information."""
    versions = {"umdlibrary": service().version, "python": sys.version.split()[0]}
    for package in ("flask", "werkzeug", "jinja2", "pycdlib", "jsonschema"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "?"
    versions["platform"] = platform.platform()
    versions["ffmpeg"] = mediamod.ffmpeg_path() or "not installed"
    return render_template("about.html", versions=versions)

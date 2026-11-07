"""The Library page (tiles, sort, filter) and the detail page per disc,
with its media, its .pspdx preview and its catalog entry."""
from __future__ import annotations

import os

from flask import Blueprint, abort, redirect, render_template, request, send_from_directory, url_for

from ...catalog import build as catalog_build
from ...catalog import manifest
from ...library import group
from ...library import media as mediamod
from ...tools import iso as isotool
from ...tools import sfo as sfotool
from . import limited_text, service

bp = Blueprint("library", __name__)

SORTS = {
    "title": lambda g: (g["title"].casefold(),),
    "versions": lambda g: (-len(g["versions"]), g["title"].casefold()),
    "size": lambda g: (-g["size"], g["title"].casefold()),
    "mtime": lambda g: (-g["mtime"], g["title"].casefold()),
}


@bp.route("/")
def index():
    """Tiles, one per game; filters apply to the versions, and a game stays
    as long as one version matches."""
    svc = service()
    rows = svc.library.all()
    region = limited_text(request.args.get("region"), 16)
    fmt = limited_text(request.args.get("format"), 8)
    missing = limited_text(request.args.get("missing"), 32)
    dup = limited_text(request.args.get("dup"), 8)
    language = limited_text(request.args.get("lang"), 16)
    q = limited_text(request.args.get("q"), 200).lower()
    sort = limited_text(request.args.get("sort") or "title", 32)
    if fmt and fmt not in ("iso", "cso"):
        abort(400)
    if missing and missing not in isotool.MEDIA_FILES:
        abort(400)
    if sort not in SORTS:
        sort = "title"
    if region:
        rows = [r for r in rows if r["region"] == region]
    if fmt:
        rows = [r for r in rows if r["format"] == fmt]
    if missing:
        rows = [r for r in rows if not r["has_media"].get(missing)]
    if dup:
        rows = [r for r in rows if r["duplicate"]]
    if language:
        rows = [r for r in rows if language in r["languages"]]
    if q:
        rows = [r for r in rows if q in (r["title"] or "").lower() or q in r["name"].lower()
                or q in (r["disc_id"] or "").lower()]
    games = group.games(rows)
    games.sort(key=SORTS.get(sort, SORTS["title"]))
    everything = svc.library.all()
    regions = sorted({r["region"] for r in everything})
    languages = sorted({code for r in everything for code in r["languages"]})
    return render_template("library.html", games=games, regions=regions, languages=languages,
                           counts=svc.library.counts(),
                           filters={"region": region, "format": fmt, "missing": missing,
                                    "dup": dup, "lang": language, "q": q, "sort": sort},
                           media_files=isotool.MEDIA_FILES)


@bp.route("/disc/<int:image_id>")
def disc(image_id: int):
    """Show one image detail page."""
    svc = service()
    row = svc.library.get(image_id)
    if row is None:
        abort(404)
    public = svc.settings.public_url()
    publishers = svc.settings["publishers"]
    fields, _ = catalog_build.media_for(row, manifest.our_id(row["disc_key"])) if row["status"] == "ok" else ({}, [])
    entry = manifest.app_entry(row, public, publishers, fields or None) if row["status"] == "ok" else None
    pspdx = manifest.pspdx_manifest(row, public, publishers) if row["status"] == "ok" else None
    everything = svc.library.all()
    others = [r for r in everything if r["disc_key"] == row["disc_key"] and r["id"] != row["id"]]
    versions = group.games([r for r in everything if r["game_key"] == row["game_key"]])[0]["versions"]
    film_jobs = [j for j in svc.jobs.all() if j.kind == "film" and f"image {image_id} " in j.title]
    return render_template("disc.html", row=row, entry=entry, pspdx=pspdx, others=others, versions=versions,
                           console_id=manifest.console_id(entry["source"], entry["name"]) if entry else None,
                           urls=manifest.urls(row, public), ffmpeg=mediamod.ffmpeg_path(),
                           film_jobs=film_jobs, sfo_keys=sfotool.KNOWN_KEYS,
                           media_files=isotool.MEDIA_FILES)


@bp.route("/disc/<int:image_id>/film", methods=["POST"])
def film(image_id: int):
    """Queue MP4 conversion for one image."""
    svc = service()
    if svc.library.get(image_id) is None:
        abort(404)
    job = svc.start_film(image_id)
    return redirect(url_for("jobs.job", job_id=job.id))


@bp.route("/disc/<int:image_id>/reread", methods=["POST"])
def reread(image_id: int):
    """Read this one image again (and extract its media)."""
    svc = service()
    row = svc.library.get(image_id)
    if row is None:
        abort(404)
    from ...library import scan as scanmod
    from ...library.db import now_iso
    st = os.stat(row["abs_path"]) if os.path.exists(row["abs_path"]) else None
    if st is None:
        svc.library.forget(image_id)
        return redirect(url_for("library.index"))
    scanmod.read_image(svc.library, row["path"], st.st_size, st.st_mtime, now_iso(), image_id)
    return redirect(url_for("library.disc", image_id=image_id))


@bp.route("/media/<int:image_id>/<name>")
def media(image_id: int, name: str):
    """Serve extracted media for one image."""
    svc = service()
    row = svc.library.get(image_id)
    if row is None or name not in (*isotool.MEDIA_FILES, "ICON1.mp4"):
        abort(404)
    directory = row["media_dir"]
    if not os.path.exists(os.path.join(directory, name)):
        abort(404)
    as_attachment = not (name.endswith(".PNG") or name.endswith(".mp4"))
    return send_from_directory(directory, name, as_attachment=as_attachment, conditional=True)

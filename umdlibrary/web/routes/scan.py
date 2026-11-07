"""Scan: rescan the folder, the watch-folder toggle, and the media and hash
jobs, which are the other two jobs that read the library."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from ...library import media as mediamod
from . import limited_text, service

bp = Blueprint("scan", __name__)


@bp.route("/scan")
def page():
    """Show scan/media job controls."""
    svc = service()
    jobs = [j for j in svc.jobs.all() if j.kind in ("scan", "media")][:20]
    return render_template("scan.html", counts=svc.library.counts(), watcher=svc.watcher.status(),
                           jobs=jobs, ffmpeg=mediamod.ffmpeg_path())


@bp.route("/scan/run", methods=["POST"])
def run():
    """Queue a library scan."""
    job = service().start_scan()
    return redirect(url_for("jobs.job", job_id=job.id))


@bp.route("/scan/media", methods=["POST"])
def media():
    """Queue media extraction."""
    job = service().start_media(only_missing=request.form.get("all") != "1")
    return redirect(url_for("jobs.job", job_id=job.id))


@bp.route("/scan/watch", methods=["POST"])
def watch():
    """Persist watch-folder settings."""
    svc = service()
    enabled = request.form.get("enabled") == "1"
    changes = {"watch_enabled": enabled}
    if request.form.get("interval"):
        changes["watch_interval"] = limited_text(request.form["interval"], 16)
    svc.apply_settings(changes)
    return redirect(url_for("scan.page"))


@bp.route("/hash")
def hash_page():
    """Show hash job controls."""
    svc = service()
    rows = [r for r in svc.library.all() if r["status"] == "ok"]
    jobs = [j for j in svc.jobs.all() if j.kind == "hash"][:20]
    return render_template("hash.html", rows=rows, counts=svc.library.counts(), jobs=jobs)


@bp.route("/hash/run", methods=["POST"])
def hash_run():
    """Queue hashing of missing SHA-256 values."""
    job = service().start_hash()
    return redirect(url_for("jobs.job", job_id=job.id))

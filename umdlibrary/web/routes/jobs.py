"""Jobs: every job of this process, its state, progress and log, and the
JSON the page polls."""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from . import limited_text, service

bp = Blueprint("jobs", __name__)


@bp.route("/jobs")
def page():
    """Show all jobs and watcher status."""
    return render_template("jobs.html", jobs=service().jobs.all(), watcher=service().watcher.status())


@bp.route("/jobs/<int:job_id>")
def job(job_id: int):
    """Show one job."""
    j = service().jobs.get(job_id)
    if j is None:
        abort(404)
    return render_template("job.html", job=j)


@bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel(job_id: int):
    """Cancel a queued or running job."""
    service().jobs.cancel(job_id)
    target = limited_text(request.form.get("next"), 500)
    if not target or urlsplit(target).netloc:
        target = url_for("jobs.job", job_id=job_id)
    return redirect(target)


@bp.route("/api/jobs")
def api_jobs():
    """Return all jobs as JSON."""
    return jsonify({"jobs": [j.to_dict() for j in service().jobs.all()],
                    "watcher": service().watcher.status()})


@bp.route("/api/jobs/<int:job_id>")
def api_job(job_id: int):
    """Return one job as JSON."""
    j = service().jobs.get(job_id)
    if j is None:
        abort(404)
    return jsonify(j.to_dict())

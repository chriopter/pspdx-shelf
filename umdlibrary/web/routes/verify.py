"""Verify: the pspdb tool, on when a checkout path is set."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from ...library import verify as verifymod
from . import service

bp = Blueprint("verify", __name__)


@bp.route("/verify")
def page():
    """Show pspdb verification status and controls."""
    svc = service()
    pspdb_dir = svc.settings["pspdb_dir"]
    where = verifymod.records_dir(pspdb_dir) if pspdb_dir else None
    rows = [r for r in svc.library.all() if r["status"] == "ok"]
    jobs = [j for j in svc.jobs.all() if j.kind == "verify"][:20]
    return render_template("verify.html", pspdb_dir=pspdb_dir, where=where, rows=rows,
                           counts=svc.library.counts(), jobs=jobs)


@bp.route("/verify/run", methods=["POST"])
def run():
    """Queue pspdb verification."""
    job = service().start_verify()
    return redirect(url_for("jobs.job", job_id=job.id))

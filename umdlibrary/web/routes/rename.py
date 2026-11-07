"""Rename: the pattern, the dry-run table, and the apply button."""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from ...library import rename as renamemod
from . import limited_text, service

bp = Blueprint("rename", __name__)


@bp.route("/rename")
def page():
    """Show the rename dry run."""
    svc = service()
    pattern = limited_text(request.args.get("pattern"), 500) or svc.settings["rename_pattern"]
    error = None
    entries = []
    try:
        entries = renamemod.plan(svc.library, pattern)
    except ValueError as exc:
        error = str(exc)
    summary = {s: sum(e["status"] == s for e in entries) for s in ("clean", "unchanged", "conflict", "skipped")}
    jobs = [j for j in svc.jobs.all() if j.kind == "rename"][:20]
    return render_template("rename.html", pattern=pattern, entries=entries, error=error, summary=summary,
                           fields=renamemod.FIELDS, history=svc.library.rename_history(50), jobs=jobs,
                           max_name=renamemod.MAX_NAME)


@bp.route("/rename/apply", methods=["POST"])
def apply():
    """Queue a rename job for selected clean dry-run rows."""
    svc = service()
    pattern = limited_text(request.form.get("pattern"), 500) or svc.settings["rename_pattern"]
    try:
        renamemod.check_pattern(pattern)
    except ValueError:
        return redirect(url_for("rename.page", pattern=pattern))
    ids = request.form.getlist("id")
    try:
        only = {int(i) for i in ids} if ids else None
    except ValueError:
        abort(400)
    job = svc.start_rename(pattern, only)
    return redirect(url_for("jobs.job", job_id=job.id))


@bp.route("/rename/pattern", methods=["POST"])
def save_pattern():
    """Persist the default rename pattern."""
    svc = service()
    pattern = limited_text(request.form.get("pattern"), 500)
    try:
        renamemod.check_pattern(pattern)
        svc.apply_settings({"rename_pattern": pattern})
    except ValueError:
        pass
    return redirect(url_for("rename.page"))

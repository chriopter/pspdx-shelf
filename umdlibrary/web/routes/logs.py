"""Logs: the last N lines of the service log."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from . import service

bp = Blueprint("logs", __name__)


@bp.route("/logs")
def page():
    """Show recent service log lines."""
    svc = service()
    n = request.args.get("n", type=int) or svc.settings["log_lines"]
    n = max(1, min(5000, n))
    return render_template("logs.html", lines=svc.ring.tail(n), n=n, path=svc.log_path)

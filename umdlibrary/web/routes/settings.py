"""Settings: the JSON file, every value, and the publisher overrides."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from ...library import rename as renamemod
from ...settings import SettingsError
from . import limited_text, service

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def page():
    """Show current settings and override tables."""
    svc = service()
    return render_template("settings.html", error=request.args.get("error"), saved=request.args.get("saved"),
                           path=svc.settings.path, publishers=sorted(svc.settings["publishers"].items()),
                           languages=sorted(svc.settings["languages"].items()))


@bp.route("/settings", methods=["POST"])
def save():
    """Validate and persist settings from the form."""
    svc = service()
    form = request.form
    changes = {
        "library_dir": limited_text(form.get("library_dir"), 1000),
        "output_dir": limited_text(form.get("output_dir"), 1000),
        "host": limited_text(form.get("host"), 255),
        "http_port": limited_text(form.get("http_port"), 16),
        "public_url": limited_text(form.get("public_url"), 500),
        "rename_pattern": limited_text(form.get("rename_pattern"), 500),
        "watch_interval": limited_text(form.get("watch_interval"), 16),
        "watch_enabled": form.get("watch_enabled") == "1",
        "catalog_name": limited_text(form.get("catalog_name"), 200),
        "log_lines": limited_text(form.get("log_lines"), 16),
        "pspdb_dir": limited_text(form.get("pspdb_dir"), 1000),
    }
    try:
        renamemod.check_pattern(changes["rename_pattern"])
        svc.apply_settings(changes)
    except (SettingsError, ValueError) as exc:
        return redirect(url_for("settings.page", error=str(exc)))
    return redirect(url_for("settings.page", saved="1"))


@bp.route("/settings/publishers", methods=["POST"])
def publishers():
    """Add or remove publisher overrides."""
    svc = service()
    table = dict(svc.settings["publishers"])
    if request.form.get("remove"):
        table.pop(limited_text(request.form["remove"], 64).upper(), None)
    disc_id = limited_text(request.form.get("disc_id"), 64).upper()
    name = limited_text(request.form.get("publisher"), 200)
    if disc_id and name:
        table[disc_id] = name
    try:
        svc.apply_settings({"publishers": table})
    except SettingsError as exc:
        return redirect(url_for("settings.page", error=str(exc)))
    return redirect(url_for("settings.page", saved="1"))


@bp.route("/settings/languages", methods=["POST"])
def languages():
    """Per-disc language overrides: for the multi-language EU disc the SFO
    says nothing about."""
    svc = service()
    table = dict(svc.settings["languages"])
    if request.form.get("remove"):
        table.pop(limited_text(request.form["remove"], 64).upper(), None)
    disc_id = limited_text(request.form.get("disc_id"), 64).upper()
    codes = limited_text(request.form.get("languages"), 200)
    if disc_id and codes:
        table[disc_id] = codes
    try:
        svc.apply_settings({"languages": table})
    except SettingsError as exc:
        return redirect(url_for("settings.page", error=str(exc)))
    return redirect(url_for("settings.page", saved="1"))

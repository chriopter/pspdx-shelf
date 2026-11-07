"""The Flask app: server-rendered pages, one blueprint per page under
routes/, a little JS for job polling. No middleware, no framework magic."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from ..library.db import human_size
from ..settings import SettingsError
from .routes import about, catalog, files, jobs, library, logs, rename, scan, settings, verify

HERE = os.path.dirname(os.path.abspath(__file__))


def create_app(service) -> Flask:
    """Create the Flask app for a service object."""
    app = Flask("umdlibrary", template_folder=os.path.join(HERE, "templates"),
                static_folder=os.path.join(HERE, "static"), static_url_path="/static")
    app.config["SERVICE"] = service
    app.config["MAX_CONTENT_LENGTH"] = 1 << 20
    app.jinja_env.filters["human_size"] = human_size
    app.jinja_env.filters["json"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
    app.jinja_env.filters["stamp"] = lambda t: (
        dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") if t else "never")

    @app.before_request
    def _service():
        g.service = service

    @app.context_processor
    def _globals():
        active = service.jobs.active()
        return {"service": service, "settings": service.settings.values,
                "active_jobs": active, "version": service.version,
                "served_url": service.settings.served_url(),
                "public_url": service.settings.public_url()}

    @app.errorhandler(RuntimeError)
    @app.errorhandler(sqlite3.DatabaseError)
    @app.errorhandler(SettingsError)
    def _operational_error(exc):
        if isinstance(exc, HTTPException):
            return exc
        return f"{type(exc).__name__}: {exc}", 500, {"Content-Type": "text/plain; charset=utf-8"}

    for bp in (library.bp, scan.bp, rename.bp, catalog.bp, verify.bp, settings.bp, jobs.bp,
               logs.bp, about.bp, files.bp):
        app.register_blueprint(bp)
    return app

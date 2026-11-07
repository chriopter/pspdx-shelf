"""One module per page. Each holds a blueprint; app.py registers them."""
from __future__ import annotations

import re

from flask import abort
from flask import current_app

DISC_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,255}$")


def service():
    """Return the process service object for the current request."""
    return current_app.config["SERVICE"]


def limited_text(value: str | None, limit: int = 500) -> str:
    """Return a stripped form/query value, rejecting oversized input."""
    text = (value or "").strip()
    if len(text) > limit:
        abort(400)
    return text


def valid_disc_key(value: str) -> str:
    """Validate a disc key/path component before it can reach storage."""
    if not DISC_KEY_RE.fullmatch(value):
        abort(404)
    return value


def valid_catalog_path(value: str) -> str:
    """Validate a relative catalog media path before send_from_directory."""
    if value.startswith(("/", ".")) or "/." in value or "\\" in value or not SAFE_PATH_RE.fullmatch(value):
        abort(404)
    return value

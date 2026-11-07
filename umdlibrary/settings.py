"""Settings: one JSON file in the data volume. Every key has a default, the
file only holds what the user changed, and the UI shows where it is."""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from .tools import lang

# A host the PSPDX schema accepts for a non-GitHub source: ASCII labels of
# letters, digits and hyphens with a letter or digit in each, no www.,
# nothing under github.io. IPv4 addresses are labels of digits, so they pass.
HOST_LABEL = re.compile(r"^-*[A-Za-z0-9][A-Za-z0-9-]*$")

DEFAULTS: dict[str, Any] = {
    "library_dir": "/isos",
    "output_dir": "/out",
    "host": "localhost",
    "http_port": 8080,
    "public_url": "",          # what the catalog writes; https://<host> when empty
    "rename_pattern": "{title} [{disc_id}].{ext}",
    "watch_enabled": False,
    "watch_interval": 60,
    "publishers": {},          # disc id -> publisher name (the catalog's author)
    "languages": {},           # disc id -> [codes], for discs the SFO and region cannot tell
    "catalog_name": "UMD library",
    "pspdb_dir": "",           # a local checkout of ryp/pspdb; empty = the verify tool is off
    "log_lines": 400,
}

class SettingsError(ValueError):
    """The settings file or a submitted setting is not valid."""

    pass


def check_host(host: str) -> str:
    """The host as the catalog will print it, or a SettingsError that says
    which rule of the PSPDX schema it breaks."""
    host = host.strip().rstrip(".")
    if not host:
        raise SettingsError("host is empty")
    labels = host.split(".")
    for label in labels:
        if not HOST_LABEL.match(label):
            raise SettingsError(f"host label {label!r} must be ASCII letters, digits and "
                                "hyphens with at least one letter or digit "
                                "(write other names in punycode, xn--)")
    if len(labels) >= 2 and labels[-2].lower() == "github" and labels[-1].lower() == "io":
        raise SettingsError("a host under github.io is refused by the PSPDX schema")
    return host


def check_public_url(url: str) -> str:
    """The base the catalog writes URLs under: empty (meaning https://<host>)
    or an https:// URL with a host the schema accepts, no path."""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith("https://"):
        raise SettingsError("public_url must start with https:// (PSPDX reads catalogs "
                            "over HTTPS only; put a reverse proxy in front)")
    rest = url[len("https://"):]
    if "/" in rest or "?" in rest or "#" in rest or "@" in rest or "\\" in rest:
        raise SettingsError("public_url is scheme, host and port only, no path")
    host, _, port = rest.partition(":")
    check_host(host)
    if port:
        check_port(port, "public_url port")
    return url


def check_port(value: Any, name: str) -> int:
    """Validate and return a TCP port number."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} must be a number") from None
    if not 1 <= port <= 65535:
        raise SettingsError(f"{name} must be between 1 and 65535")
    return port


def validate(values: dict[str, Any]) -> dict[str, Any]:
    """A full, typed settings dict out of values on top of the defaults."""
    out = dict(DEFAULTS)
    out["publishers"] = dict(DEFAULTS["publishers"])
    out["languages"] = dict(DEFAULTS["languages"])
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        out[key] = value
    out["host"] = check_host(str(out["host"]))
    out["http_port"] = check_port(out["http_port"], "http_port")
    out["public_url"] = check_public_url(str(out["public_url"]))
    try:
        out["watch_interval"] = max(5, int(out["watch_interval"]))
        out["log_lines"] = max(50, min(5000, int(out["log_lines"])))
    except (TypeError, ValueError):
        raise SettingsError("watch_interval and log_lines must be numbers") from None
    out["watch_enabled"] = bool(out["watch_enabled"])
    for key in ("library_dir", "output_dir", "rename_pattern", "catalog_name"):
        out[key] = str(out[key]).strip()
        if not out[key]:
            raise SettingsError(f"{key} is empty")
    out["pspdb_dir"] = str(out["pspdb_dir"] or "").strip()
    if not isinstance(out["publishers"], dict):
        raise SettingsError("publishers must be an object of disc id -> publisher")
    out["publishers"] = {str(k).strip().upper(): str(v).strip()
                         for k, v in out["publishers"].items()
                         if str(k).strip() and str(v).strip()}
    if not isinstance(out["languages"], dict):
        raise SettingsError("languages must be an object of disc id -> list of codes")
    languages = {}
    for key, value in out["languages"].items():
        if isinstance(value, str):
            raw_codes = value
        elif isinstance(value, (list, tuple, set)):
            raw_codes = ",".join(map(str, value))
        else:
            raise SettingsError("languages values must be strings or lists of codes")
        codes = lang.parse_codes(raw_codes)
        if str(key).strip() and codes:
            languages[str(key).strip().upper()] = codes
    out["languages"] = languages
    return out


class Settings:
    """The settings file, read once and written on every change."""

    def __init__(self, path: str, env: dict[str, str] | None = None):
        self.path = path
        self._lock = threading.Lock()
        env = os.environ if env is None else env
        base = dict(DEFAULTS)
        # The container sets these; a fresh settings file starts from them.
        for key, var in (("library_dir", "UMD_LIBRARY_DIR"), ("output_dir", "UMD_OUTPUT_DIR"),
                         ("host", "UMD_HOST"), ("http_port", "UMD_HTTP_PORT"),
                         ("public_url", "UMD_PUBLIC_URL"), ("pspdb_dir", "UMD_PSPDB_DIR")):
            if env.get(var):
                base[key] = env[var]
        self._env_base = base
        self.values = validate(base)
        self.load()

    def load(self) -> None:
        """Load the JSON file if it exists, validating it against defaults."""
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    stored = json.load(f)
            except json.JSONDecodeError as exc:
                raise SettingsError(f"settings file is malformed JSON: {exc.msg}") from None
            except OSError as exc:
                raise SettingsError(f"settings file cannot be read: {exc}") from None
            if not isinstance(stored, dict):
                raise SettingsError("settings file must be a JSON object")
            merged = dict(self._env_base)
            merged.update(stored)
            self.values = validate(merged)

    def save(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Validate changes on top of the current values, write, return."""
        with self._lock:
            merged = dict(self.values)
            merged.update(changes)
            self.values = validate(merged)
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
            return self.values

    def __getitem__(self, key: str) -> Any:
        """Return a setting by key."""
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting by key, or default when it is absent."""
        return self.values.get(key, default)

    def served_url(self) -> str:
        """http://host:port, where this process answers."""
        port = self.values["http_port"]
        host = self.values["host"]
        return f"http://{host}" if port == 80 else f"http://{host}:{port}"

    def public_url(self) -> str:
        """The https base the catalog writes: public_url, or https://<host>
        when it is empty. The schema wants https, so a proxy has to provide
        it; this prototype serves plain HTTP."""
        return self.values["public_url"] or f"https://{self.values['host']}"

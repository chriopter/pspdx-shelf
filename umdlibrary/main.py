"""The entry point: python -m umdlibrary. Wires settings, database, jobs,
watcher and the web app together and serves plain HTTP on one port."""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from . import __version__, logs
from .catalog import build as catalog_build
from .jobs.runner import Job, JobManager
from .jobs.watch import Watcher
from .library import hash as hashmod
from .library import media as mediamod
from .library import rename as renamemod
from .library import scan as scanmod
from .library import verify as verifymod
from .library.db import Library
from .settings import Settings

log = logging.getLogger("main")


class Service:
    """Everything the routes need, in one object: what the process knows
    and the jobs it can start. Each start_* is a button in the UI."""

    def __init__(self, data_dir: str, env: dict[str, str] | None = None, log_file: bool = True):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.log_path = os.path.join(data_dir, "umdlibrary.log")
        self.ring = logs.setup(self.log_path if log_file else None)
        self.settings = Settings(os.path.join(data_dir, "settings.json"), env)
        self.library = Library(os.path.join(data_dir, "library.sqlite3"),
                               self.settings["library_dir"], os.path.join(data_dir, "media"),
                               language_overrides=lambda: self.settings["languages"])
        self.jobs = JobManager()
        self.watcher = Watcher(lambda title: self.start_scan(title),
                               lambda: self.settings["watch_enabled"],
                               lambda: self.settings["watch_interval"])
        self.version = __version__

    def start(self) -> None:
        """Start background services."""
        self.jobs.start()
        self.watcher.start()
        log.info("umdlibrary %s: library %s, data %s, output %s, serving %s",
                 self.version, self.settings["library_dir"], self.data_dir,
                 self.settings["output_dir"], self.settings.served_url())

    def stop(self) -> None:
        """Stop background services."""
        self.watcher.stop()
        self.jobs.stop()

    # -- settings that other parts read live ----------------------------------
    def apply_settings(self, changes: dict[str, Any]) -> None:
        """Persist settings and refresh live paths."""
        self.settings.save(changes)
        self.library.library_dir = self.settings["library_dir"]

    @property
    def output_dir(self) -> str:
        """Return the current output directory."""
        return self.settings["output_dir"]

    # -- jobs ----------------------------------------------------------------
    def start_scan(self, title: str = "scan the library folder") -> Job:
        """Queue a scan job."""
        return self.jobs.submit("scan", title, lambda job: scanmod.scan(self.library, job), unique=True)

    def start_hash(self) -> Job:
        """Queue a hash job."""
        return self.jobs.submit("hash", "hash images without a SHA-256",
                                lambda job: hashmod.hash_missing(self.library, job), unique=True)

    def start_media(self, only_missing: bool = True) -> Job:
        """Queue a media extraction job."""
        what = "extract missing media" if only_missing else "extract all media again"
        return self.jobs.submit("media", what,
                                lambda job: mediamod.extract_all(self.library, job, only_missing), unique=True)

    def start_rename(self, pattern: str, only_ids: set[int] | None = None) -> Job:
        """Queue a rename job."""
        return self.jobs.submit("rename", f"rename with {pattern}",
                                lambda job: renamemod.apply(self.library, pattern, job, only_ids))

    def start_catalog(self) -> Job:
        """Queue a catalog build job."""
        return self.jobs.submit("catalog", "build and publish the catalog",
                                lambda job: catalog_build.build(
                                    self.library, self.settings.public_url(),
                                    self.settings["publishers"], self.output_dir, job), unique=True)

    def start_verify(self) -> Job:
        """Queue a pspdb verification job."""
        return self.jobs.submit("verify", "verify images against pspdb",
                                lambda job: verifymod.verify(self.library, self.settings["pspdb_dir"], job),
                                unique=True)

    def start_film(self, image_id: int) -> Job:
        """Queue film conversion for one image."""
        return self.jobs.submit("film", f"convert the film of image {image_id} to MP4",
                                lambda job: mediamod.convert_film(self.library, image_id, job))


def main(argv: list[str] | None = None) -> int:
    """Run the HTTP service."""
    import argparse
    from werkzeug.serving import make_server

    from .web.app import create_app

    parser = argparse.ArgumentParser(description="umdlibrary: a LAN-only PSP UMD library with a PSPDX catalog")
    parser.add_argument("--data", default=os.environ.get("UMD_DATA_DIR", "/data"))
    parser.add_argument("--bind", default=os.environ.get("UMD_BIND", "0.0.0.0"))
    args = parser.parse_args(argv)

    service = Service(args.data)
    service.start()
    app = create_app(service)
    port = service.settings["http_port"]
    server = make_server(args.bind, port, app, threaded=True)
    log.info("listening on http://%s:%d (plain HTTP; PSPDX needs HTTPS in front)", args.bind, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

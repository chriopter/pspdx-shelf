from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from umdlibrary.main import Service  # noqa: E402
from umdlibrary.web.app import create_app  # noqa: E402

from . import helpers  # noqa: E402


@pytest.fixture
def dirs(tmp_path):
    lib = tmp_path / "isos"
    data = tmp_path / "data"
    out = tmp_path / "out"
    lib.mkdir()
    return {"lib": str(lib), "data": str(data), "out": str(out)}


@pytest.fixture
def service(dirs):
    env = {"UMD_LIBRARY_DIR": dirs["lib"], "UMD_OUTPUT_DIR": dirs["out"],
           "UMD_HOST": "psp.lan", "UMD_HTTP_PORT": "8080"}
    svc = Service(dirs["data"], env=env, log_file=False)
    yield svc
    svc.stop()


@pytest.fixture
def library(service):
    return service.library


@pytest.fixture
def app(service):
    app = create_app(service)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def two_discs(dirs):
    """An ISO and a CSO in the library folder."""
    a = helpers.write(os.path.join(dirs["lib"], "Test Game.iso"), helpers.make_iso(), mtime=1_700_000_000)
    cso = helpers.make_cso(helpers.make_iso("Zweites Spiel", "ULUS-10001", media=("ICON0.PNG", "PIC1.PNG", "ICON1.PMF", "SND0.AT3"), vol_ident="ULUS10001"))
    b = helpers.write(os.path.join(dirs["lib"], "second.cso"), cso, mtime=1_700_100_000)
    return a, b

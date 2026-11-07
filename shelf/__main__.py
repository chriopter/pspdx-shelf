"""python -m shelf: read the folder, keep the catalog current, serve it."""
import logging
import os
import re
import sys
import threading

from werkzeug.serving import make_server

from . import web
from .shelf import Shelf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logging.getLogger("werkzeug").setLevel(logging.WARNING)

url = os.environ.get("SHELF_URL", "")
if not url.startswith(("http://", "https://")):
    sys.exit("SHELF_URL must be the address PSPDX reaches this at, e.g. http://192.168.1.10:8080")
# A password is a path: PSPDX sends no credentials, but it fetches any
# address, so the whole shelf -- pages, catalog, downloads -- lives under
# /<password>/ and everything else is 404.
password = os.environ.get("SHELF_PASSWORD", "")
if password and not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", password):
    sys.exit("SHELF_PASSWORD must be 8 to 64 letters, digits, - or _")
prefix = f"/{password}" if password else ""
shelf = Shelf(os.environ.get("SHELF_DISCS", "/discs"), os.environ.get("SHELF_DATA", "/data"), url.rstrip("/") + prefix)
interval = int(os.environ.get("SHELF_INTERVAL", "86400"))
threading.Thread(target=shelf.run, args=(interval,), daemon=True).start()
port = int(os.environ.get("SHELF_PORT", "8080"))
logging.info("serving %s on port %d", shelf.discs_dir, port)
make_server("0.0.0.0", port, web.mounted(shelf, prefix), threaded=True).serve_forever()

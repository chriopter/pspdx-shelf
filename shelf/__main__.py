"""python -m shelf: read the folder, keep the catalog current, serve it."""
import logging
import os
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
shelf = Shelf(os.environ.get("SHELF_DISCS", "/discs"), os.environ.get("SHELF_DATA", "/data"), url)
interval = int(os.environ.get("SHELF_INTERVAL", "86400"))
threading.Thread(target=shelf.run, args=(interval,), daemon=True).start()
port = int(os.environ.get("SHELF_PORT", "8080"))
logging.info("serving %s on port %d", shelf.discs_dir, port)
make_server("0.0.0.0", port, web.create(shelf, os.environ.get("SHELF_PASSWORD", "")), threaded=True).serve_forever()

"""Catalog: what the next build would publish, what is published, the
URLs, the build button and the schema problems."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from ...catalog import build as catalog_build
from . import service

bp = Blueprint("catalog", __name__)


@bp.route("/catalog")
def page():
    """Show catalog preview, published state, and build jobs."""
    svc = service()
    public = svc.settings.public_url()
    preview = catalog_build.preview(svc.library, public, svc.settings["publishers"])
    published = catalog_build.published(svc.output_dir)
    live = catalog_build.published_catalog(svc.output_dir)
    jobs = [j for j in svc.jobs.all() if j.kind == "catalog"][:20]
    served = svc.settings.served_url()
    urls = {"catalog": f"{served}/catalog/catalog.json", "public": f"{public}/catalog/catalog.json",
            "apps": f"{served}/catalog/apps/", "umd": f"{served}/umd/<DISC_ID>.iso",
            "pspdx": f"{served}/umd/<DISC_ID>.pspdx"}
    return render_template("catalog.html", preview=preview, published=published, live=live,
                           jobs=jobs, urls=urls, out_dir=svc.output_dir)


@bp.route("/catalog/build", methods=["POST"])
def build():
    """Queue catalog build and publish."""
    job = service().start_catalog()
    return redirect(url_for("jobs.job", job_id=job.id))

"""The media files out of PSP_GAME, copied into the data volume once per
image, and the optional MP4 made from ICON1.PMF with ffmpeg so the film
plays in a browser."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

from ..jobs.runner import Job
from ..tools import iso as isotool
from .db import Library

log = logging.getLogger("media")


def extract(library: Library, image_id: int) -> dict[str, int]:
    """Extract PSP_GAME media for one image, returning names and sizes."""
    row = library.get(image_id)
    if row is None or row["status"] != "ok":
        return {}
    dest = os.path.join(library.media_dir, str(image_id))
    shutil.rmtree(dest, ignore_errors=True)
    try:
        found = isotool.extract_media(row["abs_path"], dest)
    except (isotool.DiscError, OSError) as exc:
        log.warning("media of %s: %s", row["path"], exc)
        return {}
    library.set_media(image_id, {k: abs(v) for k, v in found.items()})
    return found


def extract_all(library: Library, job: Job | None = None, only_missing: bool = True) -> dict[str, Any]:
    """Extract media for readable images, optionally only missing files."""
    rows = [r for r in library.all() if r["status"] == "ok"]
    if only_missing:
        rows = [r for r in rows if not r["media_extracted"]
                or any(name in r["media"] and not r["has_media"][name] for name in isotool.MEDIA_FILES)]
    files = 0
    if job:
        job.set_progress(0, len(rows), f"{len(rows)} images")
    for i, row in enumerate(rows):
        found = extract(library, row["id"])
        files += len(found)
        if job:
            job.log(f"{row['path']}: {', '.join(sorted(found)) or 'no media'}")
            job.set_progress(i + 1, len(rows), row["path"])
    return {"images": len(rows), "files": files}


def ffmpeg_path() -> str | None:
    """Return the ffmpeg executable path, if it is installed."""
    return shutil.which("ffmpeg")


def convert_film(library: Library, image_id: int, job: Job | None = None) -> str:
    """ICON1.PMF -> ICON1.mp4 next to it, H.264 + AAC; without audio when
    ffmpeg cannot decode the ATRAC3+ track. Returns the mp4 path."""
    row = library.get(image_id)
    if row is None or not row["has_media"]["ICON1.PMF"]:
        raise RuntimeError("this image has no ICON1.PMF")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed in this container")
    src = os.path.join(row["media_dir"], "ICON1.PMF")
    dst = os.path.join(row["media_dir"], "ICON1.mp4")
    tmp = dst + ".part.mp4"
    base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    for extra in (["-c:a", "aac", "-b:a", "128k"], ["-an"]):
        if job:
            job.log("running: " + " ".join(base + extra + [tmp]))
        try:
            proc = subprocess.run(base + extra + [tmp], capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg is not installed in this container") from None
        except subprocess.TimeoutExpired:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise RuntimeError("ffmpeg timed out while converting the film") from None
        if proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, dst)
            if job:
                job.log(f"wrote {dst} ({os.path.getsize(dst)} bytes)")
            return dst
        if job:
            job.log(f"ffmpeg failed ({proc.returncode}): {proc.stderr.strip()[:800]}")
    if os.path.exists(tmp):
        os.remove(tmp)
    raise RuntimeError("ffmpeg could not convert the film; see the job log")

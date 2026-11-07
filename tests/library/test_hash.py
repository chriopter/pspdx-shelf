import hashlib
import os
import tracemalloc

from umdlibrary.jobs.runner import Job
from umdlibrary.library import hash as hashmod
from umdlibrary.library import scan

from ..helpers import make_iso, write


def test_hash_matches_and_is_cached(library, dirs):
    path = write(os.path.join(dirs["lib"], "a.iso"), make_iso(), mtime=1_700_000_000)
    scan.scan(library)
    row = library.all()[0]
    assert row["sha256"] is None and library.counts()["unhashed"] == 1
    job = Job(1, "hash", "t")
    assert hashmod.hash_missing(library, job) == {"hashed": 1}
    expected = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert library.get(row["id"])["sha256"] == expected
    assert any(expected in line for line in job.lines)
    assert hashmod.hash_missing(library) == {"hashed": 0}
    # A rescan of the unchanged file keeps the hash; the cache is by path, size, mtime.
    scan.scan(library)
    assert library.get(row["id"])["sha256"] == expected
    # A touched file (new mtime) is hashed again; the same bytes give the same digest.
    os.utime(path, (1_700_000_900, 1_700_000_900))
    scan.scan(library)
    assert library.get(row["id"])["sha256"] is None
    hashmod.hash_missing(library)
    assert library.get(row["id"])["sha256"] == expected
    # And a changed file gives another digest.
    write(path, make_iso(title="Other"), mtime=1_700_001_000)
    scan.scan(library)
    hashmod.hash_missing(library)
    assert library.get(row["id"])["sha256"] != expected


def test_cache_survives_a_rename(library, dirs):
    path = write(os.path.join(dirs["lib"], "a.iso"), make_iso(), mtime=1_700_000_000)
    scan.scan(library)
    hashmod.hash_missing(library)
    digest = library.all()[0]["sha256"]
    os.rename(path, os.path.join(dirs["lib"], "b.iso"))
    library.move(library.all()[0]["id"], "b.iso")
    scan.scan(library)
    assert library.all()[0]["sha256"] == digest


def test_hashing_streams(library, dirs, monkeypatch):
    """A 64 MB sparse image is hashed with a peak allocation far below its
    size, so a 4 GB one is fine too."""
    path = write(os.path.join(dirs["lib"], "big.iso"), make_iso())
    with open(path, "r+b") as f:
        f.truncate(64 * 1024 * 1024)
    scan.scan(library)
    row = library.all()[0]
    job = Job(1, "hash", "t")
    tracemalloc.start()
    digest = hashmod.hash_image(library, row["id"], job)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 3 * hashmod.CHUNK
    assert job.total == 64 * 1024 * 1024 and job.progress == job.total
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    assert digest == h.hexdigest()


def test_errors_are_not_hashed(library, dirs):
    write(os.path.join(dirs["lib"], "junk.iso"), b"junk" * 1000)
    scan.scan(library)
    assert hashmod.hash_missing(library) == {"hashed": 0}

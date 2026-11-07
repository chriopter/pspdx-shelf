import pytest

from umdlibrary.library import db as dbmod
from umdlibrary.library.db import Library, disc_key_for, human_size


def test_disc_key():
    assert disc_key_for("ULES-01234", "x.iso") == "ULES-01234"
    assert disc_key_for("ules 01234/..", "x.iso") == "ULES01234.."[:-2] or disc_key_for("ules 01234/..", "x.iso") == "ULES01234"
    assert disc_key_for("日本語", "a.iso").startswith("NOID-")
    assert disc_key_for(None, "a.iso") == disc_key_for(None, "a.iso") != disc_key_for(None, "b.iso")
    assert len(disc_key_for("X" * 100, "a")) == 32


def test_human_size():
    assert human_size(1_500_000_000) == "1.5 GB"
    assert human_size(700_000_000) == "700 MB"
    assert human_size(2048) == "2 kB"
    assert human_size(None) == "?"


def test_database_open_errors_are_wrapped(tmp_path, monkeypatch):
    def locked(*args, **kwargs):
        raise dbmod.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(dbmod.sqlite3, "connect", locked)
    with pytest.raises(RuntimeError, match="database cannot be opened: database is locked"):
        Library(str(tmp_path / "library.sqlite3"), str(tmp_path), str(tmp_path / "media"))

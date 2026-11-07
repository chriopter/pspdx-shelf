import json
import os

import pytest

from umdlibrary import settings as s


def test_defaults_from_env_and_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    st = s.Settings(path, env={"UMD_LIBRARY_DIR": "/lib", "UMD_HOST": "psp.lan", "UMD_HTTP_PORT": "9000"})
    assert st["library_dir"] == "/lib" and st["host"] == "psp.lan" and st["http_port"] == 9000
    assert st["watch_enabled"] is False and st["publishers"] == {}
    assert st.served_url() == "http://psp.lan:9000" and st.public_url() == "https://psp.lan"
    assert not os.path.exists(path)
    st.save({"public_url": "https://umd.home:8443/", "publishers": {" ules-01234 ": " Sony "}, "watch_interval": "1"})
    assert st.public_url() == "https://umd.home:8443"
    assert st["publishers"] == {"ULES-01234": "Sony"} and st["watch_interval"] == 5
    stored = json.load(open(path))
    assert stored["public_url"] == "https://umd.home:8443"
    again = s.Settings(path, env={"UMD_LIBRARY_DIR": "/lib", "UMD_HOST": "psp.lan"})
    assert again["public_url"] == "https://umd.home:8443" and again["publishers"] == {"ULES-01234": "Sony"}
    assert again["host"] == "psp.lan"


@pytest.mark.parametrize("changes, message", [
    ({"languages": "en"}, "object"),
    ({"host": "me.github.io"}, "github.io"),
    ({"host": "psp_lan"}, "label"),
    ({"host": ""}, "empty"),
    ({"http_port": "0"}, "between"),
    ({"http_port": "abc"}, "number"),
    ({"public_url": "http://psp.lan"}, "https"),
    ({"public_url": "https://psp.lan/catalog"}, "no path"),
    ({"public_url": "https://psp.lan:99999"}, "between"),
    ({"library_dir": "  "}, "empty"),
    ({"publishers": ["x"]}, "object"),
    ({"languages": {"ULES-01234": 3}}, "strings or lists"),
])
def test_validation(tmp_path, changes, message):
    st = s.Settings(str(tmp_path / "settings.json"), env={})
    with pytest.raises(s.SettingsError, match=message):
        st.save(changes)


def test_language_overrides_are_normalized(tmp_path):
    st = s.Settings(str(tmp_path / "s.json"), env={})
    st.save({"languages": {"ules-01234": "EN, de,fr", "ULUS-10001": ["ja", "x", "pt_BR"], "bad": "?"}})
    assert st["languages"] == {"ULES-01234": ["en", "de", "fr"], "ULUS-10001": ["ja", "pt-br"]}
    assert st["pspdb_dir"] == ""
    st.save({"pspdb_dir": " /pspdb "})
    assert st["pspdb_dir"] == "/pspdb"


def test_unknown_keys_are_dropped_and_ports_default(tmp_path):
    st = s.Settings(str(tmp_path / "s.json"), env={"UMD_HTTP_PORT": "80"})
    st.save({"nonsense": 1, "host": "192.168.1.10"})
    assert "nonsense" not in st.values and st.served_url() == "http://192.168.1.10"


def test_malformed_settings_file_is_a_settings_error(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ nope", encoding="utf-8")
    with pytest.raises(s.SettingsError, match="malformed JSON"):
        s.Settings(str(path), env={})


def test_settings_file_must_be_an_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(s.SettingsError, match="JSON object"):
        s.Settings(str(path), env={})

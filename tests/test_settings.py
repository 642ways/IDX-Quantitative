import pytest

from idxquant.settings import load_settings


def test_local_defaults():
    settings = load_settings({})
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.data_path == "data/idxquant.sqlite"
    assert settings.is_server is False


def test_server_settings_come_from_the_environment():
    settings = load_settings({"HOST": "0.0.0.0", "PORT": "9000", "DATA_PATH": "/data/app.sqlite"})
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.data_path == "/data/app.sqlite"
    assert settings.is_server is True


def test_bad_port_gives_a_clear_error():
    with pytest.raises(SystemExit, match="PORT"):
        load_settings({"PORT": "abc"})

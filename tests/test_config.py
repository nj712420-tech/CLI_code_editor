from aide.config import load_config
from aide.core.errors import ConfigError


def test_defaults_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("AIDE_API__MODEL", raising=False)
    cfg = load_config(tmp_path)
    assert cfg.api.base_url == "http://localhost:11434/v1"
    assert cfg.api.model == "gpt-oss:120b-cloud"
    assert cfg.api.api_key == "ollama"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("AIDE_API__MODEL", "my-model")
    monkeypatch.setenv("AIDE_API__BASE_URL", "http://example.test/v1")
    cfg = load_config(tmp_path)
    assert cfg.api.model == "my-model"
    assert cfg.api.base_url == "http://example.test/v1"


def test_unknown_keys_warn_but_load(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cfg_path = tmp_path / "cfg" / "aide" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("[api]\nmodel = 'from-file'\n")
    monkeypatch.delenv("AIDE_API__MODEL", raising=False)
    assert load_config(tmp_path).api.model == "from-file"


def test_invalid_toml_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cfg_path = tmp_path / "cfg" / "aide" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("[api\nthis is not toml")
    try:
        load_config(tmp_path)
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")

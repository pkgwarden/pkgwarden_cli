import os
import tomllib
from pathlib import Path

from pkgwarden_cli import credentials


def test_config_home_prefers_xdg_config_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert credentials.config_home() == tmp_path


def test_config_home_falls_back_to_dot_config_under_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert credentials.config_home() == tmp_path / ".config"


def test_save_and_load_token_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token(
        api_base="https://gate.test/api/v1",
        token_type="gate",
        token="pyf_gate_abc",
    )
    path = credentials.credentials_path()
    assert path.is_file()
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    api_key = "https://gate.test/api/v1"
    assert data[api_key]["gate"] == "pyf_gate_abc"
    assert credentials.load_token("https://gate.test/api/v1", "gate") == "pyf_gate_abc"


def test_save_token_overwrites_same_type_but_preserves_others(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://api/api/v1", "user", "t1")
    credentials.save_token("https://api/api/v1", "project", "t2")
    credentials.save_token("https://api/api/v1", "user", "t1-new")
    assert credentials.load_token("https://api/api/v1", "user") == "t1-new"
    assert credentials.load_token("https://api/api/v1", "project") == "t2"


def test_load_token_returns_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert credentials.load_token("https://nope/api/v1", "gate") is None


def test_delete_token_removes_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://api/api/v1", "gate", "t1")
    credentials.delete_token("https://api/api/v1", "gate")
    assert credentials.load_token("https://api/api/v1", "gate") is None

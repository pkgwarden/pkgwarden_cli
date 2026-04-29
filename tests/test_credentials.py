import os
import tomllib
from pathlib import Path

from pkgwarden_cli import credentials


def test_save_and_load_token_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token(
        api_base="https://tape.test/api/v1",
        token_type="tape",
        token="pyf_tape_abc",
    )
    path = credentials.credentials_path()
    assert path.is_file()
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    api_key = "https://tape.test/api/v1"
    assert data[api_key]["tape"] == "pyf_tape_abc"
    assert credentials.load_token("https://tape.test/api/v1", "tape") == "pyf_tape_abc"


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
    assert credentials.load_token("https://nope/api/v1", "tape") is None


def test_delete_token_removes_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://api/api/v1", "tape", "t1")
    credentials.delete_token("https://api/api/v1", "tape")
    assert credentials.load_token("https://api/api/v1", "tape") is None

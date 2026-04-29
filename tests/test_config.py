import json
from pathlib import Path

import pytest

from pkgwarden_cli.config import CliConfig, load_cli_config


def test_load_cli_config_from_env_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PKGWARDEN_API_URL", raising=False)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_abc")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_def")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.api_base == "https://a.test/api/v1"
    assert cfg.user_token == "pyf_user_abc"
    assert cfg.project_token == "pyf_proj_def"
    assert cfg.project_id == "proj-1"


def test_load_cli_config_env_overrides_toml_for_api_url_and_project_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://env.example/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "from-env")
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://toml.example/api/v1"\nproject_id = "from-toml"\n',
        encoding="utf-8",
    )
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.api_base == "https://env.example/api/v1"
    assert cfg.project_id == "from-env"


def test_load_cli_config_uses_toml_when_env_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PKGWARDEN_API_URL", raising=False)
    monkeypatch.delenv("PKGWARDEN_PROJECT_ID", raising=False)
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://toml-only.example/api/v1"\nproject_id = "from-toml"\n',
        encoding="utf-8",
    )
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.api_base == "https://toml-only.example/api/v1"
    assert cfg.project_id == "from-toml"


def test_load_cli_config_cli_project_id_override_beats_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a/api/v1")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "from-env")
    (tmp_path / ".pkgwarden.toml").write_text('project_id = "from-toml"\n', encoding="utf-8")
    cfg = load_cli_config(cwd=tmp_path, project_id_override="from-cli")
    assert cfg.project_id == "from-cli"


def test_load_cli_config_rejects_non_string_api_url_in_toml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PKGWARDEN_API_URL", raising=False)
    (tmp_path / ".pkgwarden.toml").write_text("api_url = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="api_url"):
        load_cli_config(cwd=tmp_path)


def test_cli_config_json_roundtrip() -> None:
    c = CliConfig(
        api_base="https://h/api/v1",
        user_token=None,
        project_token="t",
        project_id="p",
    )
    assert json.loads(c.model_dump_json())["api_base"] == "https://h/api/v1"


def test_load_cli_config_reads_mode_and_package_manager_from_toml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://tape.test/api/v1")
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ignored/api/v1"\nmode = "tape"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.mode == "tape"
    assert cfg.package_manager == "uv"


def test_load_cli_config_rejects_unknown_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a/api/v1")
    (tmp_path / ".pkgwarden.toml").write_text('mode = "nope"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="mode"):
        load_cli_config(cwd=tmp_path)


def test_load_cli_config_rejects_unknown_package_manager(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a/api/v1")
    (tmp_path / ".pkgwarden.toml").write_text('package_manager = "yarnpkg"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="package_manager"):
        load_cli_config(cwd=tmp_path)


def test_load_cli_config_tape_token_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://tape.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_TAPE_TOKEN", "pyf_tape_abc")
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.tape_token == "pyf_tape_abc"


def test_load_cli_config_env_overrides_toml_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a/api/v1")
    monkeypatch.setenv("PKGWARDEN_MODE", "enterprise")
    (tmp_path / ".pkgwarden.toml").write_text('mode = "tape"\n', encoding="utf-8")
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.mode == "enterprise"

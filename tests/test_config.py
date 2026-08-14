import json
from pathlib import Path

import pytest

from pkgwarden_cli.config import (
    CliConfig,
    find_pkgwarden_toml,
    load_cli_config,
    stripped_or_none,
)


class PathWithoutAncestors(Path):
    """Bounds the walk-up to the path itself, keeping tests hermetic to tmp_path."""

    @property
    def parents(self) -> tuple[Path, ...]:  # type: ignore[override]
        return ()


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
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://gate.test/api/v1")
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ignored/api/v1"\nmode = "gate"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.mode == "gate"
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


def test_load_cli_config_gate_token_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://gate.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "pyf_gate_abc")
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.gate_token == "pyf_gate_abc"


def test_find_pkgwarden_toml_walks_up_to_ancestor(tmp_path: Path) -> None:
    (tmp_path / ".pkgwarden.toml").write_text('api_url = "https://a/api/v1"\n', encoding="utf-8")
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    assert find_pkgwarden_toml(nested) == tmp_path / ".pkgwarden.toml"


def test_find_pkgwarden_toml_prefers_nearest_ancestor(tmp_path: Path) -> None:
    (tmp_path / ".pkgwarden.toml").write_text('api_url = "https://far/api/v1"\n', encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    near_toml = nested / ".pkgwarden.toml"
    near_toml.write_text('api_url = "https://near/api/v1"\n', encoding="utf-8")
    assert find_pkgwarden_toml(nested / "deeper") == near_toml


def test_find_pkgwarden_toml_returns_none_when_absent(tmp_path: Path) -> None:
    assert find_pkgwarden_toml(PathWithoutAncestors(tmp_path)) is None


def test_load_cli_config_env_overrides_toml_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://a/api/v1")
    monkeypatch.setenv("PKGWARDEN_MODE", "enterprise")
    (tmp_path / ".pkgwarden.toml").write_text('mode = "gate"\n', encoding="utf-8")
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.mode == "enterprise"


def test_load_cli_config_treats_whitespace_env_api_url_as_unset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "   ")
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://toml.example/api/v1"\n',
        encoding="utf-8",
    )
    cfg = load_cli_config(cwd=tmp_path)
    assert cfg.api_base == "https://toml.example/api/v1"


def test_load_cli_config_treats_whitespace_override_as_unset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://env.example/api/v1")
    cfg = load_cli_config(cwd=tmp_path, api_url_override="   ")
    assert cfg.api_base == "https://env.example/api/v1"


def test_load_cli_config_rejects_whitespace_toml_api_url_when_only_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("PKGWARDEN_API_URL", raising=False)
    (tmp_path / ".pkgwarden.toml").write_text('api_url = "   "\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.pkgwarden\.toml"):
        load_cli_config(cwd=PathWithoutAncestors(tmp_path))


def test_stripped_or_none_strips_and_drops_blank_values() -> None:
    assert stripped_or_none("  https://a/api/v1  ") == "https://a/api/v1"
    assert stripped_or_none("   ") is None
    assert stripped_or_none("") is None
    assert stripped_or_none(None) is None

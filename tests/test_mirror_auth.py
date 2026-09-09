import stat
from pathlib import Path

from pkgwarden_cli.config import CliConfig, PackageManager
from pkgwarden_cli.mirror_auth import (
    NPM_CLIENT_RETRY_SETTINGS,
    cleanup_native_auth_env,
    native_auth_env,
    npm_client_pacing_settings,
    npmrc_for_registry,
    poetry_gate_sources,
)


def _config(**overrides) -> CliConfig:
    values: dict = {
        "api_base": "http://127.0.0.1:8002/api/v1",
        "mode": "enterprise",
        "package_manager": "uv",
        "project_id": "p1",
        "mirror_token": "pyf_proj_tok",
    }
    values.update(overrides)
    return CliConfig.model_validate(values)


def _write_uv_pyproject(tmp_path: Path, index_name: str, url: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "0"\n\n'
        f'[[tool.uv.index]]\nname = "{index_name}"\nurl = "{url}"\ndefault = true\n',
        encoding="utf-8",
    )


def test_uv_index_credentials_injected_for_matching_mirror(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "pkgwarden-mirror", "http://127.0.0.1:8002/simple/")
    env = native_auth_env(_config(), "uv", tmp_path)
    assert env["UV_INDEX_PKGWARDEN_MIRROR_USERNAME"] == "pyf_proj_tok"
    assert env["UV_INDEX_PKGWARDEN_MIRROR_PASSWORD"] == ""


def test_uv_foreign_index_not_touched(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "public", "https://pypi.org/simple/")
    assert native_auth_env(_config(), "uv", tmp_path) == {}


def test_no_token_yields_empty_env(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "pkgwarden-mirror", "http://127.0.0.1:8002/simple/")
    env = native_auth_env(_config(mirror_token=None, project_token=None), "uv", tmp_path)
    assert env == {}


def test_missing_pyproject_yields_empty_env(tmp_path: Path) -> None:
    assert native_auth_env(_config(), "uv", tmp_path) == {}


def test_pip_gets_credentialed_index_url(tmp_path: Path) -> None:
    env = native_auth_env(_config(package_manager="pip"), "pip", tmp_path)
    assert env["PIP_INDEX_URL"] == "http://pyf_proj_tok@127.0.0.1:8002/simple/"


def _gate_config(**overrides) -> CliConfig:
    values: dict = {
        "api_base": "https://gate.test/api/v1",
        "mode": "gate",
        "gate_token": "pyf_gate_tok",
    }
    values.update(overrides)
    return CliConfig.model_validate(values)


def test_pip_gate_mode_uses_resolution_simple_path(tmp_path: Path) -> None:
    env = native_auth_env(_gate_config(), "pip", tmp_path)
    assert env["PIP_INDEX_URL"] == "https://pyf_gate_tok@gate.test/resolution/simple/"


def test_uv_gate_mode_credentials_use_gate_token(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "pkgwarden-gate", "https://gate.test/resolution/simple/")
    env = native_auth_env(_gate_config(), "uv", tmp_path)
    assert env["UV_INDEX_PKGWARDEN_GATE_USERNAME"] == "pyf_gate_tok"
    assert env["UV_INDEX_PKGWARDEN_GATE_PASSWORD"] == ""


def test_npm_gate_mode_uses_gate_token(tmp_path: Path) -> None:
    env = native_auth_env(_gate_config(), "npm", tmp_path)
    npmrc = Path(env["NPM_CONFIG_USERCONFIG"]).read_text(encoding="utf-8")
    assert "registry=https://gate.test/resolution/npm/" in npmrc
    assert "_authToken=pyf_gate_tok" in npmrc


def test_npm_injects_userconfig_with_registry_auth(tmp_path: Path) -> None:
    env = native_auth_env(_config(), "npm", tmp_path)
    userconfig = Path(env["NPM_CONFIG_USERCONFIG"])
    assert userconfig.is_file()
    npmrc = userconfig.read_text(encoding="utf-8")
    assert "registry=http://127.0.0.1:8002/resolution/npm/\n" in npmrc
    assert "//127.0.0.1:8002/resolution/npm/:_authToken=pyf_proj_tok" in npmrc


def test_pnpm_injects_same_npmrc_auth(tmp_path: Path) -> None:
    env = native_auth_env(_config(), "pnpm", tmp_path)
    npmrc = Path(env["NPM_CONFIG_USERCONFIG"]).read_text(encoding="utf-8")
    assert "registry=http://127.0.0.1:8002/resolution/npm/" in npmrc
    assert "_authToken=pyf_proj_tok" in npmrc


def test_yarn_injects_registry_server(tmp_path: Path) -> None:
    env = native_auth_env(_config(), "yarn", tmp_path)
    assert env["YARN_NPM_REGISTRY_SERVER"] == "http://127.0.0.1:8002/resolution/npm"
    assert Path(env["NPM_CONFIG_USERCONFIG"]).is_file()


def test_npm_without_token_yields_empty_env(tmp_path: Path) -> None:
    assert native_auth_env(_config(mirror_token=None, project_token=None), "npm", tmp_path) == {}


def test_cleanup_removes_temp_npmrc(tmp_path: Path) -> None:
    env = native_auth_env(_config(), "npm", tmp_path)
    userconfig = Path(env["NPM_CONFIG_USERCONFIG"])
    assert userconfig.is_file()
    cleanup_native_auth_env(env)
    assert not userconfig.is_file()


def _write_poetry_pyproject(tmp_path: Path, name: str, url: str, priority: str | None) -> None:
    priority_line = f'priority = "{priority}"\n' if priority else ""
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "0"\n\n'
        f'[[tool.poetry.source]]\nname = "{name}"\nurl = "{url}"\n{priority_line}',
        encoding="utf-8",
    )


def test_poetry_gate_sources_matches_mirror_url(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002/simple/", "primary")
    sources = poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002")
    assert [(source.name, source.priority) for source in sources] == [("gate", "primary")]


def test_poetry_gate_sources_priority_absent_is_none(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002/simple/", None)
    sources = poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002")
    assert [(source.name, source.priority) for source in sources] == [("gate", None)]


def test_poetry_gate_sources_ignores_foreign_url(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "public", "https://pypi.org/simple/", "primary")
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002") == []


def test_poetry_gate_sources_missing_pyproject_returns_empty(tmp_path: Path) -> None:
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002") == []


def test_poetry_gate_sources_unparseable_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not [ valid toml", encoding="utf-8")
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002") == []


def test_poetry_source_credentials_injected_for_matching_mirror(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002/simple/", "primary")
    env = native_auth_env(_config(), "poetry", tmp_path)
    assert env["POETRY_HTTP_BASIC_GATE_USERNAME"] == "pyf_proj_tok"
    assert env["POETRY_HTTP_BASIC_GATE_PASSWORD"] == ""


def test_poetry_foreign_source_not_touched(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "public", "https://pypi.org/simple/", "primary")
    assert native_auth_env(_config(), "poetry", tmp_path) == {}


def test_poetry_no_token_yields_empty_env(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002/simple/", "primary")
    env = native_auth_env(_config(mirror_token=None, project_token=None), "poetry", tmp_path)
    assert env == {}


def test_poetry_missing_pyproject_yields_empty_env(tmp_path: Path) -> None:
    assert native_auth_env(_config(), "poetry", tmp_path) == {}


def test_poetry_gate_mode_credentials_use_gate_token(tmp_path: Path) -> None:
    _write_poetry_pyproject(
        tmp_path, "pkgwarden", "https://gate.test/resolution/simple/", "primary"
    )
    env = native_auth_env(_gate_config(), "poetry", tmp_path)
    assert env["POETRY_HTTP_BASIC_PKGWARDEN_USERNAME"] == "pyf_gate_tok"
    assert env["POETRY_HTTP_BASIC_PKGWARDEN_PASSWORD"] == ""


def test_poetry_gate_sources_rejects_lookalike_host_suffix(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002.evil.test/simple/", "primary")
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002") == []


def test_poetry_gate_sources_rejects_userinfo_smuggled_host(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002@evil.test/simple/", "primary")
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "http://127.0.0.1:8002") == []


def test_poetry_lookalike_host_gets_no_credentials(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "http://127.0.0.1:8002.evil.test/simple/", "primary")
    assert native_auth_env(_config(), "poetry", tmp_path) == {}


def test_uv_lookalike_host_gets_no_credentials(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "mirror", "http://127.0.0.1:8002.evil.test/simple/")
    assert native_auth_env(_config(), "uv", tmp_path) == {}


def test_uv_userinfo_smuggled_host_gets_no_credentials(tmp_path: Path) -> None:
    _write_uv_pyproject(tmp_path, "mirror", "http://127.0.0.1:8002@evil.test/simple/")
    assert native_auth_env(_config(), "uv", tmp_path) == {}


def test_gate_source_under_a_path_prefixed_deployment_is_matched(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "https://host.test/pkgwarden/simple/", "primary")
    sources = poetry_gate_sources(tmp_path / "pyproject.toml", "https://host.test/pkgwarden")
    assert [source.name for source in sources] == ["gate"]


def test_sibling_path_of_a_path_prefixed_deployment_is_not_matched(tmp_path: Path) -> None:
    _write_poetry_pyproject(tmp_path, "gate", "https://host.test/pkgwarden-evil/simple/", "primary")
    assert poetry_gate_sources(tmp_path / "pyproject.toml", "https://host.test/pkgwarden") == []


def test_npmrc_paces_the_client_after_the_auth_line() -> None:
    npmrc = npmrc_for_registry("https://gate.test/resolution/npm", "tok", ("pnpm",))
    lines = npmrc.splitlines()
    assert lines[0] == "registry=https://gate.test/resolution/npm/"
    assert lines[1] == "//gate.test/resolution/npm/:_authToken=tok"
    assert lines[2:] == [f"{key}={value}" for key, value in npm_client_pacing_settings(("pnpm",))]


def test_pacing_settings_are_the_reviewed_numbers() -> None:
    assert dict(npm_client_pacing_settings(("pnpm",))) == {
        "network-concurrency": "8",
        "fetch-retries": "5",
        "fetch-retry-mintimeout": "2000",
        "fetch-retry-maxtimeout": "60000",
    }


def test_pacing_uses_maxsockets_for_npm_which_warns_on_network_concurrency() -> None:
    """npm 11 warns "Unknown user config" on ``network-concurrency`` and says it will stop
    working in the next major, so npm gets its own socket cap instead."""
    settings = dict(npm_client_pacing_settings(("npm",)))
    assert settings["maxsockets"] == "8"
    assert "network-concurrency" not in settings


def test_pacing_carries_both_concurrency_keys_when_both_clients_are_configured() -> None:
    settings = dict(npm_client_pacing_settings(("npm", "pnpm", "yarn")))
    assert settings["maxsockets"] == "8"
    assert settings["network-concurrency"] == "8"


def test_pacing_always_carries_the_retry_settings() -> None:
    npm_family: tuple[PackageManager, ...] = ("npm", "pnpm", "yarn")
    for manager in npm_family:
        assert set(NPM_CLIENT_RETRY_SETTINGS) <= set(npm_client_pacing_settings((manager,)))


def test_temp_npmrc_holding_the_token_is_private_to_its_owner(tmp_path: Path) -> None:
    env = native_auth_env(_config(), "npm", tmp_path)
    userconfig = Path(env["NPM_CONFIG_USERCONFIG"])
    assert stat.S_IMODE(userconfig.stat().st_mode) == 0o600

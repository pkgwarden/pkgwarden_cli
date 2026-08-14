from pathlib import Path

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.mirror_auth import cleanup_native_auth_env, native_auth_env


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

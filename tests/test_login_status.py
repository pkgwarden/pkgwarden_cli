import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from pkgwarden_cli import credentials, http_client
from pkgwarden_cli import main as main_module

_ENVIRONMENT_VARIABLES = (
    "PKGWARDEN_API_URL",
    "PKGWARDEN_USER_TOKEN",
    "PKGWARDEN_PROJECT_TOKEN",
    "PKGWARDEN_GATE_TOKEN",
    "PKGWARDEN_MIRROR_TOKEN",
)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch) -> None:
    for name in _ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_login_writes_token_to_credentials_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "login",
            "--api-url",
            "https://gate.test/api/v1",
            "--token",
            "pyf_gate_abc",
            "--type",
            "gate",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert credentials.load_token("https://gate.test/api/v1", "gate") == "pyf_gate_abc"
    assert "--api-url" in result.stdout


def test_login_rejects_unknown_token_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "login",
            "--api-url",
            "https://t/api/v1",
            "--token",
            "x",
            "--type",
            "ghost",
        ],
    )
    assert result.exit_code != 0


def test_login_rejects_empty_api_url_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("pkgwarden_cli.auth_cli.find_pkgwarden_toml", lambda _start: None)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["login", "--api-url", "", "--token", "x", "--type", "gate"],
    )
    assert result.exit_code == 1
    assert ".pkgwarden.toml" in result.stderr
    assert credentials.load_token("/api/v1", "gate") is None


def test_login_rejects_whitespace_api_url_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PKGWARDEN_API_URL", "   ")
    monkeypatch.setattr("pkgwarden_cli.auth_cli.find_pkgwarden_toml", lambda _start: None)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["login", "--token", "x", "--type", "gate"],
    )
    assert result.exit_code == 1


def test_login_treats_whitespace_toml_api_url_as_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / ".pkgwarden.toml").write_text('api_url = "   "\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["login", "--token", "x", "--type", "gate"])
    assert result.exit_code == 1
    assert ".pkgwarden.toml" in result.stderr


def test_login_reports_malformed_ancestor_toml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    toml_path = tmp_path / ".pkgwarden.toml"
    toml_path.write_text("api_url = [unclosed\n", encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    monkeypatch.chdir(nested)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["login", "--token", "x", "--type", "gate"],
    )
    assert result.exit_code == 1
    assert str(toml_path) in result.stderr


def test_logout_deletes_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://t/api/v1", "gate", "x")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["logout", "--api-url", "https://t/api/v1", "--type", "gate"],
    )
    assert result.exit_code == 0
    assert credentials.load_token("https://t/api/v1", "gate") is None


def test_status_json_reports_mode_and_token_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        ('api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "uv"\n'),
        encoding="utf-8",
    )
    credentials.save_token("https://gate.test/api/v1", "gate", "pyf_gate_x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "status"])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["mode"] == "gate"
    assert data["tokens"]["gate"] == "credentials"
    assert data["api_base"] == "https://gate.test/api/v1"


def test_login_finds_pkgwarden_toml_in_ancestor_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    toml_path = tmp_path / ".pkgwarden.toml"
    toml_path.write_text('api_url = "https://gate.test/api/v1"\n', encoding="utf-8")
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["login", "--token", "pyf_gate_abc", "--type", "gate"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert credentials.load_token("https://gate.test/api/v1", "gate") == "pyf_gate_abc"
    assert str(toml_path) in result.stdout


def test_logout_reports_resolved_deployment_and_toml_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    toml_path = tmp_path / ".pkgwarden.toml"
    toml_path.write_text('api_url = "https://gate.test/api/v1"\n', encoding="utf-8")
    credentials.save_token("https://gate.test/api/v1", "gate", "pyf_gate_abc")
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["logout", "--type", "gate"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "https://gate.test/api/v1" in result.stdout
    assert str(toml_path) in result.stdout
    assert credentials.load_token("https://gate.test/api/v1", "gate") is None


def test_logout_reports_flag_as_source_when_api_url_passed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://t/api/v1", "gate", "x")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["logout", "--api-url", "https://t/api/v1", "--type", "gate"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "--api-url" in result.stdout


def test_logout_reports_env_var_as_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://t/api/v1")
    credentials.save_token("https://t/api/v1", "gate", "x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["logout", "--type", "gate"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "PKGWARDEN_API_URL" in result.stdout


def test_logout_resolves_root_level_api_url_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://root.test/api/v1", "gate", "x")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--api-url", "https://root.test/api/v1", "logout", "--type", "gate"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "https://root.test/api/v1" in result.stdout
    assert "--api-url" in result.stdout
    assert credentials.load_token("https://root.test/api/v1", "gate") is None


def test_cli_config_reads_token_from_credentials_file_when_env_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://api.test/api/v1"\n',
        encoding="utf-8",
    )
    credentials.save_token("https://api.test/api/v1", "user", "pyf_user_from_file")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer pyf_user_from_file"
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(200, json={"blocked": False})
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_client.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_client, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "why-blocked", "httpx==0.27.0"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

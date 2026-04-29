import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import credentials, http_client
from pkgwarden_cli import main as main_module


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
            "https://tape.test/api/v1",
            "--token",
            "pyf_tape_abc",
            "--type",
            "tape",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert credentials.load_token("https://tape.test/api/v1", "tape") == "pyf_tape_abc"


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


def test_logout_deletes_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    credentials.save_token("https://t/api/v1", "tape", "x")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["logout", "--api-url", "https://t/api/v1", "--type", "tape"],
    )
    assert result.exit_code == 0
    assert credentials.load_token("https://t/api/v1", "tape") is None


def test_status_json_reports_mode_and_token_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        ('api_url = "https://tape.test/api/v1"\nmode = "tape"\npackage_manager = "uv"\n'),
        encoding="utf-8",
    )
    credentials.save_token("https://tape.test/api/v1", "tape", "pyf_tape_x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "status"])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["mode"] == "tape"
    assert data["tokens"]["tape"] == "credentials"
    assert data["api_base"] == "https://tape.test/api/v1"


def test_cli_config_reads_token_from_credentials_file_when_env_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PKGWARDEN_USER_TOKEN", raising=False)
    monkeypatch.delenv("PKGWARDEN_PROJECT_TOKEN", raising=False)
    monkeypatch.delenv("PKGWARDEN_TAPE_TOKEN", raising=False)
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

    real_build = http_client.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_client, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "why-blocked", "httpx==0.27.0"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

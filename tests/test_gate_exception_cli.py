import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module


def _gate_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "pyf_gate_x")


def _enterprise_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")


def test_gate_exception_add_posts_body(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/exceptions"):
            captured["json"] = json.loads(request.content.decode())
            return httpx.Response(
                201,
                json={
                    "id": "exc-1",
                    "vulnerability_id": "CVE-2026-1",
                    "reason": "not applicable",
                    "created_by_user_id": "user-1",
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["exception", "add", "-v", "CVE-2026-1", "-r", "not applicable"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["json"] == {"vulnerability_id": "CVE-2026-1", "reason": "not applicable"}


def test_gate_exception_list_uses_enterprise_handler_in_enterprise_mode(
    tmp_path: Path, monkeypatch
) -> None:
    _enterprise_env(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/exceptions"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["exception", "list"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "(empty)" in result.stdout


def test_gate_exception_add_requires_gate_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("PKGWARDEN_GATE_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["exception", "add", "-v", "CVE-2026-1", "-r", "x"],
    )
    assert result.exit_code != 0
    assert "PKGWARDEN_GATE_TOKEN" in result.stdout + result.stderr


def test_gate_exception_list_forwards_query_params(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/exceptions"):
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"items": []})
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["exception", "list", "--include-revoked", "-v", "CVE-x"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["params"] == {
        "include_revoked": "true",
        "include_expired": "false",
        "vulnerability_id": "CVE-x",
    }

import json

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module


def test_why_blocked_reports_cve_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            params = dict(request.url.params)
            assert params["name"] == "requests"
            assert params["version"] == "2.28.0"
            assert params["ecosystem"] == "pypi"
            return httpx.Response(
                200,
                json={
                    "blocked": True,
                    "reason": "cve",
                    "details": {"cves": ["CVE-2023-32681"]},
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.28.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "cve" in combined.lower()


def test_why_blocked_json_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(
                200,
                json={"blocked": False, "reason": "available"},
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "why-blocked", "httpx==0.27.0"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["blocked"] is False


def test_why_blocked_requires_pinned_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "httpx"])
    assert result.exit_code != 0
    assert "==" in (result.stdout + result.stderr)


def test_why_blocked_npm_spec_with_at(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            params = dict(request.url.params)
            assert params["name"] == "lodash"
            assert params["version"] == "4.17.21"
            assert params["ecosystem"] == "npm"
            return httpx.Response(200, json={"blocked": False})
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["why-blocked", "lodash@4.17.21", "--ecosystem", "npm"],
    )
    assert result.exit_code == 0

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import doctor as doctor_mod
from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module


def _build_handler(caps_payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=caps_payload)
        if request.url.path.endswith("/requests") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "limit": 20,
                    "has_more": False,
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    return httpx.MockTransport(handler)


def test_doctor_reports_gate_deployment_from_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://gate.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(
            **{
                **kwargs,
                "transport": _build_handler(
                    {
                        "deployment_type": "gate",
                        "features": ["cve_scan", "why_blocked"],
                        "min_cli_version": "0.1.0",
                    },
                ),
            },
        )

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "doctor"])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "pw" in data
    assert "pkgwarden-cli" in data["pw"]
    assert data["deployment_type"] == "gate"
    assert "uv" in [d["manager"] for d in data["detected_managers"]]


def test_doctor_reports_enterprise_deployment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://ent.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "p1")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(
            **{
                **kwargs,
                "transport": _build_handler(
                    {
                        "deployment_type": "enterprise",
                        "features": ["requests", "approvals", "bulk_resolve"],
                        "min_cli_version": "0.1.0",
                    },
                ),
            },
        )

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "doctor"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "pw" in data
    assert data["deployment_type"] == "enterprise"
    assert "bulk_resolve" in data["features"]
    assert "enterprise_plugin_installed" in data


def test_doctor_hints_when_enterprise_api_without_plugin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://ent.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(
            **{
                **kwargs,
                "transport": _build_handler(
                    {
                        "deployment_type": "enterprise",
                        "features": ["requests"],
                        "min_cli_version": "0.1.0",
                    },
                ),
            },
        )

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    monkeypatch.setattr(doctor_mod, "enterprise_distribution_version", lambda: None)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["doctor"])
    assert result.exit_code == 0
    assert "enterprise_plugin: missing" in result.stdout
    assert "/install/pw.sh" in result.stdout


def test_doctor_reports_unknown_when_capabilities_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://legacy.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "doctor"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "pw" in data
    assert data["deployment_type"] == "unknown"


def test_doctor_exits_nonzero_when_api_unreachable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://dead.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(refuse)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    result = CliRunner().invoke(main_module.app, ["doctor"])
    assert result.exit_code == 1, result.stdout + result.stderr
    assert "unhealthy" in (result.stdout + result.stderr)


def test_doctor_enterprise_without_requests_token_is_unhealthy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\n', encoding="utf-8"
    )
    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(
            **{
                **kwargs,
                "transport": _build_handler(
                    {"deployment_type": "enterprise", "features": [], "min_cli_version": None}
                ),
            }
        )

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    result = CliRunner().invoke(main_module.app, ["doctor"])
    assert result.exit_code == 1, result.stdout + result.stderr
    assert "unhealthy" in (result.stdout + result.stderr)

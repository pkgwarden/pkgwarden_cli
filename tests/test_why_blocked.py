import json
import re

import httpx
from typer.testing import CliRunner

from ansi import strip_ansi
from pkgwarden_cli import enterprise_hooks
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

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.28.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "cve" in combined.lower()


def test_why_blocked_renders_scan_verdict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(
                200,
                json={
                    "blocked": True,
                    "reason": "scan_verdict",
                    "details": {
                        "status": "malicious",
                        "risk_score": 92,
                        "summary": "install hook exfiltrates env",
                        "findings": [
                            {
                                "engine": "guarddog",
                                "category": "exfil",
                                "rule_id": "exfiltrate-sensitive-data",
                                "severity": "critical",
                            }
                        ],
                    },
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "evilpkg==1.0.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = (result.stdout + result.stderr).lower()
    assert "malicious" in combined
    assert "guarddog" in combined
    assert "exfil" in combined
    assert "install hook exfiltrates env" in combined


def test_why_blocked_renders_known_malware(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(
                200,
                json={
                    "blocked": True,
                    "reason": "known_malware",
                    "details": {
                        "status": "malicious",
                        "risk_score": 100,
                        "summary": "Malicious code in evilpkg",
                        "is_known_malware": True,
                        "findings": [
                            {
                                "engine": "intel",
                                "category": "known_malware",
                                "rule_id": "MAL-2024-1",
                                "severity": "critical",
                                "detail": {"source": "MAL-2024-1"},
                            }
                        ],
                    },
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "evilpkg==1.0.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = (result.stdout + result.stderr).lower()
    assert "known malware (intel)" in combined
    assert "mal-2024-1" in combined


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

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "why-blocked", "httpx==0.27.0"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["blocked"] is False


def test_why_blocked_allowed_by_exception_human(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(
                200,
                json={
                    "blocked": False,
                    "reason": "allowed_by_exception",
                    "details": {
                        "exception_id": "exc-1",
                        "vulnerability_id": "vuln-row-1",
                        "created_by_email": "analyst@example.com",
                        "created_at": "2026-06-01T12:00:00+00:00",
                        "expires_at": None,
                    },
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.31.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "allowed by exception" in combined.lower()
    assert "exc-1" in combined
    assert "analyst@example.com" in combined


def test_why_blocked_allowed_by_exception_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            return httpx.Response(
                200,
                json={
                    "blocked": False,
                    "reason": "allowed_by_exception",
                    "details": {
                        "exception_id": "exc-1",
                        "vulnerability_id": "vuln-row-1",
                        "created_by_email": "analyst@example.com",
                        "created_at": "2026-06-01T12:00:00+00:00",
                        "expires_at": None,
                    },
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "why-blocked", "requests==2.31.0"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["reason"] == "allowed_by_exception"
    assert data["details"]["exception_id"] == "exc-1"
    assert data["details"]["created_by_email"] == "analyst@example.com"


def test_why_blocked_requires_pinned_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "httpx"])
    assert result.exit_code != 0
    combined = _plain(result.stdout + result.stderr)
    assert "==" in combined
    assert "--version" in combined


def test_why_blocked_enterprise_mode_dispatches_to_impl(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")

    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        enterprise_hooks,
        "_why_blocked_impl",
        lambda runtime, name, version, ecosystem: calls.append((name, version, ecosystem)),
    )

    def boom(**kwargs):
        raise AssertionError("gate client must not be used in enterprise mode")

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", boom)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.28.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [("requests", "2.28.0", "pypi")]


def test_why_blocked_enterprise_mode_without_plugin_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setattr(enterprise_hooks, "_why_blocked_impl", None)

    def boom(**kwargs):
        raise AssertionError("must not fall through to the gate client without the plugin")

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", boom)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.28.0"])
    assert result.exit_code == 1
    assert "plugin" in (result.stdout + result.stderr).lower()


def test_why_blocked_gate_mode_ignores_enterprise_impl(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://api.test/api/v1"\nmode = "gate"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def never(*args, **kwargs):
        raise AssertionError("enterprise impl must not run in gate mode")

    monkeypatch.setattr(enterprise_hooks, "_why_blocked_impl", never)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/packages/why-blocked"
        return httpx.Response(200, json={"blocked": False, "reason": "available"})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["why-blocked", "requests==2.28.0"])
    assert result.exit_code == 0, result.stdout + result.stderr


def test_why_blocked_npm_spec_with_at(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages/why-blocked"):
            params = dict(request.url.params)
            assert params["name"] == "lodash"
            assert params["version"] == "4.17.21"
            assert params["ecosystem"] == "npm"
            return httpx.Response(200, json={"blocked": False, "reason": "available"})
        return httpx.Response(404, json={"detail": str(request.url)})

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["why-blocked", "lodash@4.17.21", "--ecosystem", "npm"],
    )
    assert result.exit_code == 0


def test_why_blocked_accepts_version_option(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        enterprise_hooks,
        "_why_blocked_impl",
        lambda runtime, name, version, ecosystem: calls.append((name, version, ecosystem)),
    )
    result = CliRunner().invoke(main_module.app, ["why-blocked", "requests", "--version", "2.28.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [("requests", "2.28.0", "pypi")]


def _plain(text: str) -> str:
    return re.sub(r"[\s│╭╮╰╯─]+", "", strip_ansi(text))


def test_why_blocked_bare_name_mentions_both_forms(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    result = CliRunner().invoke(main_module.app, ["why-blocked", "httpx"])
    assert result.exit_code != 0
    # rich wraps/colors the error box in CI; compare on de-styled, de-wrapped text
    combined = _plain(result.stdout + result.stderr)
    assert "==" in combined
    assert "--version" in combined


def _invoke_with_payload(monkeypatch, payload: dict):
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "pyf_gate_x")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", wrapped)
    return CliRunner().invoke(main_module.app, ["why-blocked", "flask==3.1.2"])


def test_why_blocked_renders_pending_approval(tmp_path, monkeypatch) -> None:
    result = _invoke_with_payload(
        monkeypatch,
        {
            "blocked": True,
            "reason": "pending_approval",
            "details": {
                "request_group_id": "g1",
                "request_status": "pending",
                "web_url": "https://demo.test/approvals/a1",
            },
        },
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = result.stdout
    assert "pending approval" in out
    assert "g1" in out
    assert "https://demo.test/approvals/a1" in out


def test_why_blocked_renders_not_requested(tmp_path, monkeypatch) -> None:
    result = _invoke_with_payload(
        monkeypatch, {"blocked": True, "reason": "not_requested", "details": None}
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "pw add flask==3.1.2" in result.stdout


def test_why_blocked_renders_unknown_version(tmp_path, monkeypatch) -> None:
    result = _invoke_with_payload(
        monkeypatch, {"blocked": True, "reason": "unknown_version", "details": None}
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "unknown version" in result.stdout.lower()

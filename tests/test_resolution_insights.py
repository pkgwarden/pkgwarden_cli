import json

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import credentials as credentials_store
from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module
from pkgwarden_cli.credentials import TokenType

_MINIMAL_INSIGHTS_PAYLOAD: dict = {
    "ecosystem": "pypi",
    "package_requested": "requests",
    "package_normalized": "requests",
    "quarantine_days": 7,
    "quarantine_cutoff_utc": "2026-01-01T00:00:00+00:00",
    "simple_versions": ["2.0.0"],
    "registry_versions": ["2.0.0", "3.0.0"],
    "versions": [
        {
            "version": "2.0.0",
            "included_on_simple": True,
            "exclusion_reasons": [],
            "vulnerability_references": [],
            "effective_moment_utc": None,
            "registry_upload_or_publish_utc": None,
        },
        {
            "version": "3.0.0",
            "included_on_simple": False,
            "exclusion_reasons": ["quarantine"],
            "vulnerability_references": [],
            "effective_moment_utc": None,
            "registry_upload_or_publish_utc": None,
        },
    ],
}


def _wrap_gate_client(handler):
    real_build = http_mod.build_gate_resolution_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    return wrapped


def test_resolution_insights_pypi_hits_gate_origin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert url.startswith("https://api.test/resolution/insights/pypi/requests")
        assert request.headers.get("authorization") == "Bearer gate_secret"
        return httpx.Response(200, json=_MINIMAL_INSIGHTS_PAYLOAD)

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", _wrap_gate_client(handler))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["resolution-insights", "requests"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "requests" in combined
    assert "included" in combined.lower() or "2.0.0" in combined


def test_resolution_insights_json_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MINIMAL_INSIGHTS_PAYLOAD)

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", _wrap_gate_client(handler))
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["--json", "resolution-insights", "requests"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["ecosystem"] == "pypi"
    assert data["package_requested"] == "requests"


def test_resolution_insights_npm_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    npm_body = {**_MINIMAL_INSIGHTS_PAYLOAD, "ecosystem": "npm"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/resolution/insights/npm/lodash")
        return httpx.Response(200, json=npm_body)

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", _wrap_gate_client(handler))
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["resolution-insights", "lodash", "--ecosystem", "npm"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr


def test_resolution_insights_scoped_npm_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    npm_body = {**_MINIMAL_INSIGHTS_PAYLOAD, "ecosystem": "npm"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert "/resolution/insights/npm/" in path
        assert "types" in path and "node" in path
        return httpx.Response(200, json=npm_body)

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", _wrap_gate_client(handler))
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["resolution-insights", "@types/node", "--ecosystem", "npm"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr


def test_resolution_insights_requires_gate_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.delenv("PKGWARDEN_GATE_TOKEN", raising=False)
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_user_x")
    real_load = credentials_store.load_token

    def no_gate_file(api_base: str, token_type: TokenType):
        if token_type == "gate":
            return None
        return real_load(api_base, token_type)

    monkeypatch.setattr(credentials_store, "load_token", no_gate_file)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["resolution-insights", "requests"])
    assert result.exit_code != 0
    combined = (result.stdout + result.stderr).lower()
    assert "gate" in combined and "token" in combined


def test_resolution_insights_rejects_invalid_ecosystem(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["resolution-insights", "x", "--ecosystem", "nuget"],
    )
    assert result.exit_code != 0


def test_resolution_insights_enterprise_mode_calls_hook_not_gate_http(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_impl(runtime, package: str, ecosystem: str) -> None:
        calls.append((package, ecosystem))

    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_MODE", "enterprise")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_should_not_be_used")
    monkeypatch.setattr(
        "pkgwarden_cli.enterprise_hooks.get_resolution_insights_impl",
        lambda: fake_impl,
    )
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["resolution-insights", "demo-pkg"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [("demo-pkg", "pypi")]


def test_resolution_insights_human_includes_index_source() -> None:
    from pkgwarden_cli.resolution_insights_cli import format_resolution_insights_human

    text = format_resolution_insights_human(
        {
            "package_requested": "x",
            "package_normalized": "x",
            "quarantine_days": 0,
            "registry_versions": ["1.0.0"],
            "versions": [
                {
                    "version": "1.0.0",
                    "included_on_simple": True,
                    "exclusion_reasons": [],
                }
            ],
            "index_source": "local_cve_free",
            "insight_note": "hello",
        }
    )
    assert "index_source: local_cve_free" in text
    assert "note: hello" in text


def test_resolution_insights_http_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://api.test/api/v1")
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Package not found on PyPI"})

    monkeypatch.setattr(http_mod, "build_gate_resolution_client", _wrap_gate_client(handler))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["resolution-insights", "missing-pkg"])
    assert result.exit_code != 0
    assert "not found" in (result.stdout + result.stderr).lower()

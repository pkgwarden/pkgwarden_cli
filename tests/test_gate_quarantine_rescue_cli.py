"""`pw exception add --quarantine` and the kind column on list/show (#814)."""

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from ansi import strip_ansi
from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module

RESCUE_ROW = {
    "id": "rescue-1",
    "kind": "quarantine",
    "vulnerability_id": None,
    "ecosystem": "pypi",
    "package_name": "requests",
    "package_version": "2.31.0",
    "reason": "hotfix",
    "created_by_user_id": "user-1",
}
CVE_ROW = {
    "id": "exc-1",
    "kind": "cve",
    "vulnerability_id": "CVE-2026-1",
    "ecosystem": "pypi",
    "package_name": "flask",
    "package_version": "3.0.0",
    "reason": "not reachable",
    "created_by_user_id": "user-1",
}


def _gate_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "pyf_gate_x")


def _mock_api(monkeypatch, handler) -> None:
    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)


def test_quarantine_rescue_posts_a_pinned_body(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/exceptions"):
            captured["json"] = json.loads(request.content.decode())
            return httpx.Response(201, json=RESCUE_ROW)
        return httpx.Response(404, json={"detail": str(request.url)})

    _mock_api(monkeypatch, handler)
    result = CliRunner().invoke(
        main_module.app,
        [
            "exception",
            "add",
            "--quarantine",
            "--ecosystem",
            "pypi",
            "--package",
            "requests",
            "--version",
            "2.31.0",
            "--reason",
            "hotfix",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["json"] == {
        "kind": "quarantine",
        "reason": "hotfix",
        "ecosystem": "pypi",
        "package_name": "requests",
        "version": "2.31.0",
    }


def test_quarantine_rescue_rejects_a_vulnerability_id(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        main_module.app,
        [
            "exception",
            "add",
            "--quarantine",
            "-v",
            "CVE-2026-1",
            "--ecosystem",
            "pypi",
            "--package",
            "requests",
            "--version",
            "2.31.0",
            "--reason",
            "hotfix",
        ],
    )
    assert result.exit_code != 0
    output = strip_ansi(result.stdout + result.stderr)
    assert "--quarantine" in output
    assert "--vulnerability-id" in output


def test_quarantine_rescue_requires_the_full_pin(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        main_module.app,
        ["exception", "add", "--quarantine", "--package", "requests", "--reason", "hotfix"],
    )
    assert result.exit_code != 0
    output = strip_ansi(result.stdout + result.stderr)
    assert "--ecosystem" in output and "--version" in output


def test_cve_exception_still_requires_a_vulnerability_id(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)
    result = CliRunner().invoke(main_module.app, ["exception", "add", "--reason", "why not"])
    assert result.exit_code != 0
    assert "--vulnerability-id" in strip_ansi(result.stdout + result.stderr)


def test_list_renders_the_kind_of_each_row(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/exceptions"):
            return httpx.Response(200, json={"items": [RESCUE_ROW, CVE_ROW]})
        return httpx.Response(404, json={"detail": str(request.url)})

    _mock_api(monkeypatch, handler)
    result = CliRunner().invoke(main_module.app, ["exception", "list"])
    assert result.exit_code == 0, result.stdout + result.stderr
    quarantine_line, cve_line = result.stdout.strip().splitlines()[:2]
    assert "quarantine" in quarantine_line
    assert "pypi/requests/2.31.0" in quarantine_line
    assert "cve" in cve_line
    assert "CVE-2026-1" in cve_line


def test_show_renders_a_rescue(tmp_path: Path, monkeypatch) -> None:
    _gate_env(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/exceptions/rescue-1"):
            return httpx.Response(200, json=RESCUE_ROW)
        return httpx.Response(404, json={"detail": str(request.url)})

    _mock_api(monkeypatch, handler)
    result = CliRunner().invoke(main_module.app, ["exception", "show", "rescue-1"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "quarantine" in result.stdout

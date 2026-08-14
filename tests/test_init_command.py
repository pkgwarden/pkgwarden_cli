import tomllib
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module


def _capabilities_gate() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(
                200,
                json={
                    "deployment_type": "gate",
                    "features": ["cve_scan"],
                    "min_cli_version": "0.1.0",
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    return httpx.MockTransport(handler)


def _capabilities_enterprise() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(
                200,
                json={
                    "deployment_type": "enterprise",
                    "features": ["requests", "bulk_resolve"],
                    "min_cli_version": "0.1.0",
                },
            )
        return httpx.Response(404, json={"detail": str(request.url)})

    return httpx.MockTransport(handler)


def test_init_detects_uv_and_writes_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["init", "--api-url", "https://gate.test/api/v1", "--yes"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    toml_path = tmp_path / ".pkgwarden.toml"
    assert toml_path.is_file()
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert data["api_url"] == "https://gate.test/api/v1"
    assert data["mode"] == "gate"
    assert data["package_manager"] == "uv"


def test_init_enterprise_writes_mode_from_capabilities(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_enterprise()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "init",
            "--api-url",
            "https://ent.example/api/v1",
            "--project-id",
            "proj-123",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["mode"] == "enterprise"
    assert data["package_manager"] == "pnpm"
    assert data["project_id"] == "proj-123"


def test_init_explicit_mode_overrides_capabilities(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_enterprise()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "init",
            "--api-url",
            "https://ent.example/api/v1",
            "--mode",
            "gate",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["mode"] == "gate"


def test_init_refuses_to_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / ".pkgwarden.toml"
    existing.write_text('api_url = "https://existing/api/v1"\n', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["init", "--api-url", "https://new/api/v1", "--yes"],
    )
    assert result.exit_code != 0
    assert existing.read_text(encoding="utf-8").startswith('api_url = "https://existing')


def test_init_force_overwrites(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / ".pkgwarden.toml"
    existing.write_text('api_url = "https://existing/api/v1"\n', encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "init",
            "--api-url",
            "https://new/api/v1",
            "--yes",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads(existing.read_text(encoding="utf-8"))
    assert data["api_url"] == "https://new/api/v1"


def test_init_requires_api_url_in_non_interactive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PKGWARDEN_API_URL", raising=False)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["init", "--yes"])
    assert result.exit_code != 0
    assert "api" in (result.stdout + result.stderr).lower()


def test_init_no_manager_detected_errors_without_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        ["init", "--api-url", "https://t/api/v1", "--yes"],
    )
    assert result.exit_code != 0
    assert (
        "package_manager" in (result.stdout + result.stderr).lower()
        or "manager" in (result.stdout + result.stderr).lower()
    )


def test_init_non_interactive_dotenv_api_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PKGWARDEN_API_URL=https://gate.test/api/v1\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["init", "--yes"])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["api_url"] == "https://gate.test/api/v1"
    assert data["mode"] == "gate"


def test_init_non_interactive_project_api_token_alias_sets_enterprise(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PKGWARDEN_API_URL=https://ent.test/api/v1\nPKGWARDEN_PROJECT_API_TOKEN=pyf_x\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["init", "--yes"])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["mode"] == "enterprise"


def test_init_interactive_accepts_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PKGWARDEN_API_URL=https://gate.test/api/v1\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["init"], input="\n\ny\n")
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["api_url"] == "https://gate.test/api/v1"


def test_init_with_explicit_manager_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": _capabilities_gate()})

    monkeypatch.setattr(http_mod, "build_api_client", wrapped)
    runner = CliRunner()
    result = runner.invoke(
        main_module.app,
        [
            "init",
            "--api-url",
            "https://t/api/v1",
            "--package-manager",
            "npm",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / ".pkgwarden.toml").read_text(encoding="utf-8"))
    assert data["package_manager"] == "npm"

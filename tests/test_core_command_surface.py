"""Core-only boundary tests: prove no enterprise source or runtime coupling.

If the `pkgwarden-cli-enterprise` plugin is installed in the same environment
(which is the default in the monorepo via `just cli-install`) these tests
temporarily hide the entry point so the core can be verified in isolation.
"""

from importlib.metadata import entry_points
from pathlib import Path

import typer
from typer.testing import CliRunner

from pkgwarden_cli import main as main_module
from pkgwarden_cli import plugin_loader


def _fresh_core_app() -> typer.Typer:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = {"runtime": None, "cli_inputs": {}}

    from pkgwarden_cli.add_cli import register_add
    from pkgwarden_cli.auth_cli import register_auth
    from pkgwarden_cli.ci_cli import register_ci
    from pkgwarden_cli.doctor import register_doctor
    from pkgwarden_cli.init_cli import register_init
    from pkgwarden_cli.sync_cli import register_sync
    from pkgwarden_cli.why_blocked_cli import register_why_blocked

    register_doctor(app)
    register_init(app)
    register_auth(app)
    register_sync(app)
    register_add(app)
    register_why_blocked(app)
    register_ci(app)
    return app


def test_core_app_exposes_ci_setup() -> None:
    result = CliRunner().invoke(_fresh_core_app(), ["ci", "setup", "--help"])
    assert result.exit_code == 0, result.stdout + result.stderr


def test_core_app_has_no_enterprise_commands() -> None:
    app = _fresh_core_app()
    runner = CliRunner()
    for cmd in ("request", "approval", "package", "mirror", "registry", "sbom"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code != 0, (
            f"core CLI should not know about `{cmd}` without the enterprise plugin"
        )


def test_core_source_tree_has_no_enterprise_modules() -> None:
    core_src = Path(__file__).parent.parent / "src" / "pkgwarden_cli"
    banned = {
        "request_cli.py",
        "approval_cli.py",
        "package_cli.py",
        "mirror_cli.py",
        "registry_cli.py",
        "sbom_cli.py",
        "bulk_upload_poll.py",
    }
    present = {p.name for p in core_src.iterdir() if p.is_file()}
    leaks = banned & present
    assert not leaks, f"enterprise modules must not live in public core: {sorted(leaks)}"


def test_core_imports_do_not_reference_enterprise_package() -> None:
    core_src = Path(__file__).parent.parent / "src" / "pkgwarden_cli"
    for path in core_src.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pkgwarden_cli_enterprise" not in text, (
            f"{path.name} imports from the enterprise package; core must stay decoupled"
        )


def test_load_enterprise_plugins_returns_empty_when_no_entry_points(monkeypatch) -> None:
    def _no_entry_points(group: str | None = None):
        return []

    monkeypatch.setattr(plugin_loader, "entry_points", _no_entry_points)
    fresh_app = _fresh_core_app()
    loaded = plugin_loader.load_enterprise_plugins(fresh_app)
    assert loaded == []


def test_entry_point_group_is_pkgwarden_cli_enterprise() -> None:
    assert plugin_loader.ENTRY_POINT_GROUP == "pkgwarden_cli.enterprise"


def test_entry_point_loader_is_referenced_from_main() -> None:
    assert main_module.load_enterprise_plugins is plugin_loader.load_enterprise_plugins
    _ = entry_points(group=plugin_loader.ENTRY_POINT_GROUP)

from pathlib import Path

import typer

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli.config import PackageManager
from pkgwarden_cli.package_manager import detect_managers, sync_command
from pkgwarden_cli.process_runner import ProcessResult, run_process
from pkgwarden_cli.runtime import CliRuntime


def sync(
    ctx: typer.Context,
    manager_override: str | None = typer.Option(
        None,
        "--manager",
        help="Force package manager (uv, poetry, pip, pnpm, npm, yarn)",
    ),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    first = run_process(sync_command(manager), cwd=cwd)
    _echo_process(first)
    if first.returncode == 0:
        typer.echo(f"pw sync: {manager} completed successfully")
        return
    mode = runtime.config.mode or "unknown"
    if mode != "enterprise":
        _print_tape_guidance()
        raise typer.Exit(1)
    fallback = enterprise_hooks.get_sync_fallback()
    if fallback is None:
        typer.echo(
            "pw sync: native resolution failed. Enterprise server-side fallback is "
            "unavailable (pkgwarden-cli-enterprise plugin not installed).",
            err=True,
        )
        raise typer.Exit(1)
    if not fallback(runtime, manager, cwd):
        raise typer.Exit(1)
    second = run_process(sync_command(manager), cwd=cwd)
    _echo_process(second)
    if second.returncode != 0:
        typer.echo(
            "pw sync: native resolution still failing after server-side resolution",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"pw sync: {manager} succeeded after enterprise server-side resolution")


def _resolve_manager(
    runtime: CliRuntime,
    override: str | None,
    cwd: Path,
) -> PackageManager:
    if override:
        if override not in ("uv", "poetry", "pip", "pnpm", "npm", "yarn"):
            raise typer.BadParameter(f"Unknown package manager {override!r}")
        return override  # type: ignore[return-value]
    if runtime.config.package_manager:
        return runtime.config.package_manager
    detections = detect_managers(cwd)
    if not detections:
        typer.echo(
            "No package_manager configured and none detected. "
            "Run `pw init --package-manager <uv|pnpm|...>` or pass --manager.",
            err=True,
        )
        raise typer.Exit(1)
    return detections[0].manager


def _echo_process(result: ProcessResult) -> None:
    if result.stdout:
        typer.echo(result.stdout.rstrip())
    if result.stderr:
        typer.echo(result.stderr.rstrip(), err=True)


def _print_tape_guidance() -> None:
    typer.echo(
        "pw sync: native resolution failed. "
        "Run `pw why-blocked <pkg>==<version>` for a pinned spec, or "
        "`pw resolution-insights <package>` for tape index version coverage.",
        err=True,
    )


def register_sync(app: typer.Typer) -> None:
    app.command("sync")(sync)

from pathlib import Path

import typer

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli.config import PackageManager
from pkgwarden_cli.package_manager import (
    add_command,
    detect_managers,
    lock_command,
    remove_command,
)
from pkgwarden_cli.process_runner import ProcessResult, run_process
from pkgwarden_cli.runtime import CliRuntime


def add(
    ctx: typer.Context,
    package: str = typer.Argument(..., help="Package name (without version)"),
    version: str | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Pin a specific version (required for enterprise server fallback)",
    ),
    manager_override: str | None = typer.Option(None, "--manager"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    spec = _spec(manager, package, version)
    first = run_process(add_command(manager, spec), cwd=cwd)
    _echo_process(first)
    if first.returncode == 0:
        typer.echo(f"pw add: {manager} added {spec}")
        return
    mode = runtime.config.mode or "unknown"
    if mode != "enterprise":
        typer.echo(
            f"pw add: {manager} could not add {spec}. "
            f"Run `pw why-blocked {package}{'==' + version if version else ''}` for details.",
            err=True,
        )
        raise typer.Exit(1)
    if version is None:
        typer.echo(
            "pw add: enterprise server fallback requires --version <pinned>",
            err=True,
        )
        raise typer.Exit(1)
    fallback = enterprise_hooks.get_add_fallback()
    if fallback is None:
        typer.echo(
            "pw add: native add failed. Enterprise server-side fallback is "
            "unavailable (pkgwarden-cli-enterprise plugin not installed).",
            err=True,
        )
        raise typer.Exit(1)
    if not fallback(runtime, manager, package, version):
        raise typer.Exit(1)
    second = run_process(add_command(manager, spec), cwd=cwd)
    _echo_process(second)
    if second.returncode != 0:
        typer.echo(
            f"pw add: native add still failing after opening server request "
            f"for {package}=={version}; approval may still be pending.",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"pw add: {manager} added {spec} after enterprise request approval")


def remove(
    ctx: typer.Context,
    package: str = typer.Argument(...),
    manager_override: str | None = typer.Option(None, "--manager"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    result = run_process(remove_command(manager, package), cwd=cwd)
    _echo_process(result)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def lock(
    ctx: typer.Context,
    manager_override: str | None = typer.Option(None, "--manager"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    result = run_process(lock_command(manager), cwd=cwd)
    _echo_process(result)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def _spec(manager: PackageManager, package: str, version: str | None) -> str:
    if version is None:
        return package
    if manager in ("pnpm", "npm", "yarn"):
        return f"{package}@{version}"
    return f"{package}=={version}"


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


def register_add(app: typer.Typer) -> None:
    app.command("add")(add)
    app.command("remove")(remove)
    app.command("lock")(lock)

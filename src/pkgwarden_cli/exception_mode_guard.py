import sys

import typer

from pkgwarden_cli.runtime import CliRuntime


def exception_group_guard(ctx: typer.Context) -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        return
    obj = ctx.find_root().obj
    if not isinstance(obj, dict):
        return
    runtime = obj.get("runtime")
    if not isinstance(runtime, CliRuntime):
        return
    mode = runtime.config.mode
    if mode is None or mode in ("gate", "enterprise"):
        return
    typer.echo(
        f"pw exception is only available for gate or enterprise deployments. "
        f"Current mode is {mode!r}. Switch profiles or set mode in .pkgwarden.toml.",
        err=True,
    )
    raise typer.Exit(1)


def cli_mode(ctx: typer.Context) -> str | None:
    obj = ctx.find_root().obj
    if not isinstance(obj, dict):
        return None
    runtime = obj.get("runtime")
    if not isinstance(runtime, CliRuntime):
        return None
    return runtime.config.mode

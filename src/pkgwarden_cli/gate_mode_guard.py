"""Gate mode guard for core CLI commands."""

import sys

import typer

from pkgwarden_cli.runtime import CliRuntime


def require_gate(ctx: typer.Context, command_label: str) -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        return
    obj = ctx.find_root().obj
    if not isinstance(obj, dict):
        return
    runtime = obj.get("runtime")
    if not isinstance(runtime, CliRuntime):
        return
    mode = runtime.config.mode
    if mode is None or mode == "gate":
        return
    typer.echo(
        f"{command_label} is only available for gate deployments. "
        f'Current mode is {mode!r}. Switch profiles or set mode = "gate" in .pkgwarden.toml.',
        err=True,
    )
    raise typer.Exit(1)

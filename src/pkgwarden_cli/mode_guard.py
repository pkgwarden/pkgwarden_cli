import sys

import typer

from pkgwarden_cli.runtime import CliRuntime


def require_enterprise(ctx: typer.Context, command_label: str) -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        return
    obj = ctx.find_root().obj
    if not isinstance(obj, dict):
        return
    runtime = obj.get("runtime")
    if not isinstance(runtime, CliRuntime):
        return
    mode = runtime.config.mode
    if mode is None or mode == "enterprise":
        return
    typer.echo(
        f"{command_label} is only available for enterprise/airgapped deployments. "
        f"Current mode is {mode!r}. Switch profiles or remove `mode` in .pkgwarden.toml.",
        err=True,
    )
    raise typer.Exit(1)

from pathlib import Path

import typer

from pkgwarden_cli import add_cli, http_client
from pkgwarden_cli.output import emit_structured
from pkgwarden_cli.process_runner import run_process
from pkgwarden_cli.relock import RelockError, RelockResult, relock_to_pypi
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.urls import simple_index_url


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(1)


def _print_commands(result: RelockResult) -> None:
    for command in result.commands:
        environment = " ".join(f"{key}={value}" for key, value in command.env.items())
        typer.echo(f"{environment} {' '.join(command.argv)}".strip())


def _print_outcome(result: RelockResult) -> None:
    if result.identical:
        typer.echo(
            f"{len(result.gate_versions)} packages identical between pkgwarden and PyPI. "
            "uv.lock now points at PyPI; resolution was vetted by pkgwarden"
        )
        return
    typer.echo("PyPI resolved different versions than pkgwarden:")
    for line in (*(f"- {pin}" for pin in result.removed), *(f"+ {pin}" for pin in result.added)):
        typer.echo(line)
    typer.echo(
        f"uv.lock is the PyPI re-lock; the pkgwarden lock is kept at {result.gate_lock_path}"
    )


def lock_pypi(
    ctx: typer.Context,
    project: Path = typer.Option(Path("."), "--project", help="uv project directory"),
    index_name: str = typer.Option("pkgwarden", "--index-name"),
    keep_gate_lock: bool = typer.Option(
        False,
        "--keep-gate-lock",
        help="Also write the pkgwarden-resolved lock to uv.lock.pkgwarden",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the commands without running them"
    ),
) -> None:
    """Resolve a uv project through the pkgwarden gate, then re-lock against PyPI.

    The committed uv.lock keeps the versions pkgwarden vetted but fetches from PyPI.
    uv projects only.
    """
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    if runtime.config.mode != "gate":
        raise _fail(
            f"pw lock pypi is only available in gate mode; current mode is {runtime.config.mode!r}."
        )
    try:
        result = relock_to_pypi(
            project,
            index_name=index_name,
            index_url=simple_index_url(runtime.config.api_base, runtime.config.mode),
            token=http_client.mirror_basic_username(runtime.config),
            keep_gate_lock=keep_gate_lock,
            dry_run=dry_run,
            runner=run_process,
        )
    except (RelockError, ValueError) as error:
        raise _fail(str(error)) from error
    if runtime.json_output:
        emit_structured(runtime, result.model_dump(mode="json"))
    elif dry_run:
        _print_commands(result)
    else:
        _print_outcome(result)
    if not dry_run and not result.identical:
        raise typer.Exit(1)


def register_lock(app: typer.Typer) -> None:
    group = typer.Typer(
        callback=add_cli.lock,
        invoke_without_command=True,
        help="Refresh the native lockfile against the gated mirror, or relock to another index",
    )
    group.command("pypi")(lock_pypi)
    app.add_typer(group, name="lock")

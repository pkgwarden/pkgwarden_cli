import sys

import typer

from pkgwarden_cli.add_cli import register_add
from pkgwarden_cli.auth_cli import register_auth
from pkgwarden_cli.ci_cli import register_ci
from pkgwarden_cli.config import load_cli_config
from pkgwarden_cli.doctor import register_doctor
from pkgwarden_cli.gate_exception_cli import register_gate_exception
from pkgwarden_cli.init_cli import register_init
from pkgwarden_cli.plugin_loader import load_enterprise_plugins
from pkgwarden_cli.resolution_insights_cli import register_resolution_insights
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.sync_cli import register_sync
from pkgwarden_cli.version_info import format_pw_version_line
from pkgwarden_cli.vscode_cli import register_vscode
from pkgwarden_cli.why_blocked_cli import register_why_blocked

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="pkgwarden CLI (`pw`): gate core; enterprise/airgapped plugin adds more",
)

CONFIG_OPTIONAL_COMMANDS: frozenset[str] = frozenset({"init", "login", "logout"})


@app.callback()
def root(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", envvar="PKGWARDEN_API_URL"),
    json_output: bool = typer.Option(False, "--json", envvar="PKGWARDEN_JSON"),
    timeout: float = typer.Option(120.0, "--timeout"),
    project_id: str | None = typer.Option(None, "--project-id", envvar="PKGWARDEN_PROJECT_ID"),
) -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        ctx.obj = {"runtime": None, "cli_inputs": _cli_inputs(api_url, json_output, timeout)}
        return
    if ctx.invoked_subcommand is None:
        ctx.obj = {"runtime": None, "cli_inputs": _cli_inputs(api_url, json_output, timeout)}
        return
    if ctx.invoked_subcommand in CONFIG_OPTIONAL_COMMANDS:
        ctx.obj = {
            "runtime": None,
            "cli_inputs": _cli_inputs(api_url, json_output, timeout, project_id=project_id),
        }
        return
    try:
        configuration = load_cli_config(
            api_url_override=api_url,
            project_id_override=project_id,
        )
    except ValueError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    ctx.obj = {
        "runtime": CliRuntime(
            config=configuration,
            json_output=json_output,
            timeout=timeout,
        ),
    }


def _cli_inputs(
    api_url: str | None,
    json_output: bool,
    timeout: float,
    project_id: str | None = None,
) -> dict[str, object]:
    return {
        "api_url": api_url,
        "json_output": json_output,
        "timeout": timeout,
        "project_id": project_id,
    }


register_doctor(app)
register_init(app)
register_auth(app)
register_sync(app)
register_add(app)
register_why_blocked(app)
register_gate_exception(app)
register_resolution_insights(app)
register_vscode(app)
register_ci(app)
load_enterprise_plugins(app)


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) == 1 and argv[0] in ("--version", "-V"):
        typer.echo(format_pw_version_line())
        raise SystemExit(0)
    app(prog_name="pw")

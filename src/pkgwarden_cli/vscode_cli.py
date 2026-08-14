import typer

from pkgwarden_cli.gate_mode_guard import require_gate
from pkgwarden_cli.vscode_sync_policy_cli import sync_policy

vscode_app = typer.Typer(
    name="vscode",
    help="VS Code extension safety tools for gate (self-serve allowlist sync).",
    no_args_is_help=True,
)


@vscode_app.callback()
def vscode_group(ctx: typer.Context) -> None:
    require_gate(ctx, "pw vscode")


def register_vscode(app: typer.Typer) -> None:
    vscode_app.command("sync-policy")(sync_policy)
    app.add_typer(vscode_app)

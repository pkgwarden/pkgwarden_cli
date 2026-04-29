from importlib.metadata import entry_points
from typing import Protocol

import typer

ENTRY_POINT_GROUP = "pkgwarden_cli.enterprise"


class _PluginRegister(Protocol):
    def __call__(self, app: typer.Typer) -> None: ...


def load_enterprise_plugins(app: typer.Typer) -> list[str]:
    loaded: list[str] = []
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register: _PluginRegister = entry.load()
        except Exception as exc:
            typer.echo(
                f"pw: failed to load enterprise plugin {entry.name}: {exc}",
                err=True,
            )
            continue
        try:
            register(app)
        except Exception as exc:
            typer.echo(
                f"pw: enterprise plugin {entry.name} failed to register: {exc}",
                err=True,
            )
            continue
        loaded.append(entry.name)
    return loaded

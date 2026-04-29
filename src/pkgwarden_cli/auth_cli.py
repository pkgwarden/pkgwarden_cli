from pathlib import Path
from typing import Any

import typer

from pkgwarden_cli import credentials
from pkgwarden_cli.credentials import SUPPORTED_TOKEN_TYPES, TokenType
from pkgwarden_cli.output import emit
from pkgwarden_cli.package_manager import detect_managers
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.urls import normalize_api_base


def login(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", envvar="PKGWARDEN_API_URL"),
    token: str = typer.Option(..., "--token", help="Personal/project/tape/mirror token to store"),
    token_type: str = typer.Option(
        "user",
        "--type",
        help=f"Token kind; one of {', '.join(SUPPORTED_TOKEN_TYPES)}",
    ),
) -> None:
    resolved_api = api_url or _api_from_ctx(ctx) or _api_from_toml()
    if not resolved_api:
        typer.echo(
            "Provide --api-url or set PKGWARDEN_API_URL before running pw login",
            err=True,
        )
        raise typer.Exit(1)
    validated_type = _validate_token_type(token_type)
    api_base = normalize_api_base(resolved_api)
    credentials.save_token(api_base, validated_type, token)
    typer.echo(
        f"Stored {validated_type} token for {api_base} in {credentials.credentials_path()}",
    )


def logout(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", envvar="PKGWARDEN_API_URL"),
    token_type: str = typer.Option("user", "--type"),
) -> None:
    resolved_api = api_url or _api_from_ctx(ctx) or _api_from_toml()
    if not resolved_api:
        typer.echo("Provide --api-url or set PKGWARDEN_API_URL", err=True)
        raise typer.Exit(1)
    validated_type = _validate_token_type(token_type)
    api_base = normalize_api_base(resolved_api)
    credentials.delete_token(api_base, validated_type)
    typer.echo(f"Removed {validated_type} token for {api_base}")


def status(ctx: typer.Context) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cfg = runtime.config
    detected = [d.manager for d in detect_managers(Path.cwd())]
    payload: dict[str, Any] = {
        "api_base": cfg.api_base,
        "mode": cfg.mode or "unset",
        "configured_package_manager": cfg.package_manager,
        "detected_managers": detected,
        "project_id": cfg.project_id,
        "tokens": {
            "user": _source(cfg.user_token, cfg.api_base, "user"),
            "project": _source(cfg.project_token, cfg.api_base, "project"),
            "tape": _source(cfg.tape_token, cfg.api_base, "tape"),
            "mirror": _source(cfg.mirror_token, cfg.api_base, "mirror"),
        },
        "credentials_path": str(credentials.credentials_path()),
    }
    human = _format(payload)
    emit(runtime, human, payload)


def _source(resolved: str | None, api_base: str, token_type: TokenType) -> str:
    if resolved is None:
        return "missing"
    from_file = credentials.load_token(api_base, token_type)
    if from_file == resolved:
        return "credentials"
    return "environment"


def _format(payload: dict[str, Any]) -> str:
    lines = [
        f"api_base: {payload['api_base']}",
        f"mode: {payload['mode']}",
        f"project_id: {payload['project_id'] or 'unset'}",
        f"configured_package_manager: {payload['configured_package_manager'] or 'unset'}",
        f"detected_managers: {', '.join(payload['detected_managers']) or '(none)'}",
        "tokens:",
    ]
    for name, source in payload["tokens"].items():
        lines.append(f"  {name}: {source}")
    lines.append(f"credentials_path: {payload['credentials_path']}")
    return "\n".join(lines)


def _validate_token_type(raw: str) -> TokenType:
    if raw not in SUPPORTED_TOKEN_TYPES:
        raise typer.BadParameter(
            f"Unknown token type {raw!r}; expected one of {', '.join(SUPPORTED_TOKEN_TYPES)}",
        )
    return raw  # type: ignore[return-value]


def _api_from_ctx(ctx: typer.Context) -> str | None:
    obj = ctx.find_root().obj
    if not isinstance(obj, dict):
        return None
    inputs = obj.get("cli_inputs")
    if not isinstance(inputs, dict):
        return None
    api = inputs.get("api_url")
    return api if isinstance(api, str) else None


def _api_from_toml() -> str | None:
    import tomllib

    path = Path.cwd() / ".pkgwarden.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    raw = data.get("api_url") if isinstance(data, dict) else None
    return raw if isinstance(raw, str) else None


def register_auth(app: typer.Typer) -> None:
    app.command("login")(login)
    app.command("logout")(logout)
    app.command("status")(status)

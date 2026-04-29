import httpx
import typer

from pkgwarden_cli import http_client
from pkgwarden_cli.output import emit
from pkgwarden_cli.runtime import CliRuntime


def why_blocked(
    ctx: typer.Context,
    spec: str = typer.Argument(..., help="Pinned package spec: name==version or name@version"),
    ecosystem: str = typer.Option("pypi", "--ecosystem", "-e"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    name, version = _split_spec(spec)
    try:
        token = http_client.user_bearer_token(runtime.config)
    except ValueError:
        token = http_client.requests_bearer_token(runtime.config)
    client = http_client.build_api_client(
        api_base=runtime.config.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )
    try:
        response = client.get(
            "/packages/why-blocked",
            params={"name": name, "version": version, "ecosystem": ecosystem},
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    human = _format_human(name, version, ecosystem, payload)
    emit(runtime, human, payload)


def _split_spec(spec: str) -> tuple[str, str]:
    if "==" in spec:
        name, _, version = spec.partition("==")
        return _require_both(name, version, spec)
    if "@" in spec and not spec.startswith("@"):
        name, _, version = spec.partition("@")
        return _require_both(name, version, spec)
    raise typer.BadParameter(
        f"Spec {spec!r} must be pinned: use name==version (pypi) or name@version (npm)",
    )


def _require_both(name: str, version: str, original: str) -> tuple[str, str]:
    if not name or not version:
        raise typer.BadParameter(f"Spec {original!r} must include both name and version")
    return name, version


def _format_human(
    name: str,
    version: str,
    ecosystem: str,
    payload: object,
) -> str:
    if not isinstance(payload, dict):
        return f"{name}=={version} ({ecosystem}): {payload}"
    blocked = payload.get("blocked")
    reason = payload.get("reason")
    header = f"{name}=={version} ({ecosystem})"
    if blocked is False:
        return f"{header}: available"
    if blocked is True:
        details = payload.get("details")
        if isinstance(details, dict) and details:
            return f"{header}: blocked ({reason}) - {details}"
        return f"{header}: blocked ({reason})"
    return f"{header}: {payload}"


def register_why_blocked(app: typer.Typer) -> None:
    app.command("why-blocked")(why_blocked)

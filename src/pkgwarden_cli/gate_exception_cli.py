import httpx
import typer
from pydantic import BaseModel, Field

from pkgwarden_cli import http_client
from pkgwarden_cli.exception_mode_guard import exception_group_guard
from pkgwarden_cli.output import emit_structured
from pkgwarden_cli.runtime import CliRuntime


class GateExceptionResponse(BaseModel):
    id: str
    vulnerability_id: str
    ecosystem: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    reason: str
    created_by_user_id: str
    created_by_email: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None


class GateExceptionListResponse(BaseModel):
    items: list[GateExceptionResponse] = Field(default_factory=list)


def _gate_token(runtime: CliRuntime) -> str:
    try:
        return http_client.gate_bearer_token(runtime.config)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _api_client(runtime: CliRuntime, token: str) -> httpx.Client:
    return http_client.build_api_client(
        api_base=runtime.config.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )


def _scope_body(
    *,
    ecosystem: str | None,
    package: str | None,
    version: str | None,
) -> dict[str, str | None]:
    body: dict[str, str | None] = {}
    if ecosystem is not None:
        body["ecosystem"] = ecosystem
    if package is not None:
        body["package_name"] = package
    if version is not None:
        body["version"] = version
    return body


def _format_row(row: GateExceptionResponse) -> str:
    if row.ecosystem is None and row.package_name is None and row.package_version is None:
        scope = "CVE-only"
    else:
        parts = [part for part in (row.ecosystem, row.package_name, row.package_version) if part]
        scope = "/".join(parts)
    return f"{row.id}  {row.vulnerability_id}  {scope}  {row.reason}"


def gate_exception_add(
    ctx: typer.Context,
    vulnerability_id: str = typer.Option(..., "--vulnerability-id", "-v"),
    reason: str = typer.Option(..., "--reason", "-r"),
    ecosystem: str | None = typer.Option(None, "--ecosystem", "-e"),
    package: str | None = typer.Option(None, "--package"),
    version: str | None = typer.Option(None, "--version"),
    expires_at: str | None = typer.Option(None, "--expires-at"),
    acknowledge_kev: bool = typer.Option(False, "--acknowledge-kev"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    token = _gate_token(runtime)
    body: dict[str, object] = {
        "vulnerability_id": vulnerability_id,
        "reason": reason,
        **_scope_body(ecosystem=ecosystem, package=package, version=version),
    }
    if expires_at:
        body["expires_at"] = expires_at
    if acknowledge_kev:
        body["acknowledge_kev"] = True
    client = _api_client(runtime, token)
    try:
        response = client.post("/exceptions", json=body)
        response.raise_for_status()
        data = GateExceptionResponse.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    emit_structured(runtime, data.model_dump(mode="json"))


def gate_exception_list(
    ctx: typer.Context,
    include_revoked: bool = typer.Option(False, "--include-revoked"),
    include_expired: bool = typer.Option(False, "--include-expired"),
    vulnerability_id: str | None = typer.Option(None, "--vulnerability-id", "-v"),
) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    token = _gate_token(runtime)
    params: dict[str, bool | str] = {
        "include_revoked": include_revoked,
        "include_expired": include_expired,
    }
    if vulnerability_id:
        params["vulnerability_id"] = vulnerability_id
    client = _api_client(runtime, token)
    try:
        response = client.get("/exceptions", params=params)
        response.raise_for_status()
        parsed = GateExceptionListResponse.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    if runtime.json_output:
        emit_structured(runtime, parsed.model_dump(mode="json"))
        return
    if not parsed.items:
        typer.echo("(empty)")
        return
    for line in (_format_row(row) for row in parsed.items):
        typer.echo(line)


def gate_exception_show(ctx: typer.Context, exception_id: str = typer.Argument(...)) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    token = _gate_token(runtime)
    client = _api_client(runtime, token)
    try:
        response = client.get(f"/exceptions/{exception_id}")
        response.raise_for_status()
        data = GateExceptionResponse.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    emit_structured(runtime, data.model_dump(mode="json"))


def gate_exception_remove(ctx: typer.Context, exception_id: str = typer.Argument(...)) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    token = _gate_token(runtime)
    client = _api_client(runtime, token)
    try:
        response = client.delete(f"/exceptions/{exception_id}")
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    if runtime.json_output:
        emit_structured(runtime, {"id": exception_id, "revoked": True})
        return
    typer.echo(f"Revoked exception {exception_id}")


def _gate_exception_group_guard(ctx: typer.Context) -> None:
    exception_group_guard(ctx)


EXCEPTION_GROUP: typer.Typer | None = None


def register_gate_exception(app: typer.Typer) -> None:
    global EXCEPTION_GROUP
    group = typer.Typer(
        help="CVE exceptions (gate or enterprise; token depends on mode)",
        callback=_gate_exception_group_guard,
    )
    group.command("add")(gate_exception_add)
    group.command("list")(gate_exception_list)
    group.command("show")(gate_exception_show)
    group.command("remove")(gate_exception_remove)
    app.add_typer(group, name="exception")
    EXCEPTION_GROUP = group

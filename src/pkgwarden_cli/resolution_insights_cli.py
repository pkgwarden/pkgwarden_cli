import httpx
import typer

from pkgwarden_cli import enterprise_hooks, http_client
from pkgwarden_cli.output import emit
from pkgwarden_cli.runtime import CliRuntime


def resolution_insights(
    ctx: typer.Context,
    package: str = typer.Argument(..., help="PyPI or npm package name (npm scoped: @scope/name)"),
    ecosystem: str = typer.Option(
        "pypi",
        "--ecosystem",
        "-e",
        help="pypi or npm (airgapped path requires enterprise plugin and mode=enterprise)",
    ),
) -> None:
    """Explain how the CVE-free resolution index treats a package."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    if ecosystem not in ("pypi", "npm"):
        raise typer.BadParameter(f"Unknown ecosystem {ecosystem!r}; use pypi or npm")
    name = package.strip()
    if not name:
        raise typer.BadParameter("Package name must not be empty")
    if ecosystem == "pypi" and "/" in name:
        raise typer.BadParameter("PyPI package name must be a single segment without '/'")
    if runtime.config.mode == "enterprise":
        impl = enterprise_hooks.get_resolution_insights_impl()
        if impl is None:
            typer.echo(
                "pw resolution-insights: enterprise mode needs the airgapped API, but the "
                "pkgwarden-cli-enterprise plugin is not installed.",
                err=True,
            )
            raise typer.Exit(1)
        impl(runtime, name, ecosystem)
        return
    try:
        token = http_client.gate_bearer_token(runtime.config)
    except ValueError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    client = http_client.build_gate_resolution_client(
        api_base=runtime.config.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )
    path = (
        f"/resolution/insights/pypi/{name}"
        if ecosystem == "pypi"
        else f"/resolution/insights/npm/{name}"
    )
    try:
        response = client.get(path)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    if not isinstance(payload, dict):
        typer.echo("Unexpected response shape from resolution insights API", err=True)
        raise typer.Exit(1)
    human = format_resolution_insights_human(payload)
    emit(runtime, human, payload)


def format_resolution_insights_human(payload: dict[str, object]) -> str:
    requested = str(payload.get("package_requested", "?"))
    normalized = str(payload.get("package_normalized", "?"))
    quarantine_days = payload.get("quarantine_days", "?")
    registry_versions = payload.get("registry_versions")
    versions_raw = payload.get("versions")
    if not isinstance(registry_versions, list):
        registry_versions = []
    if not isinstance(versions_raw, list):
        versions_raw = []
    included = sum(
        1 for row in versions_raw if isinstance(row, dict) and row.get("included_on_simple") is True
    )
    lines = [
        f"{requested} (normalized: {normalized}) — quarantine_days={quarantine_days}",
        f"Resolution index: {included} included of {len(registry_versions)} registry versions.",
    ]
    index_source = payload.get("index_source")
    if isinstance(index_source, str) and index_source:
        lines.insert(1, f"index_source: {index_source}")
    insight_note = payload.get("insight_note")
    if isinstance(insight_note, str) and insight_note.strip():
        lines.append(f"note: {insight_note.strip()}")
    for row in versions_raw:
        if not isinstance(row, dict):
            continue
        version = str(row.get("version", "?"))
        on_simple = row.get("included_on_simple") is True
        reasons_raw = row.get("exclusion_reasons")
        reasons = reasons_raw if isinstance(reasons_raw, list) else []
        reason_strings = [str(r) for r in reasons]
        status = "included" if on_simple else "excluded"
        reason_text = ", ".join(reason_strings) if reason_strings else "(none)"
        lines.append(f"  {version}: {status}; reasons: {reason_text}")
    return "\n".join(lines)


def register_resolution_insights(app: typer.Typer) -> None:
    app.command("resolution-insights")(resolution_insights)

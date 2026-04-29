from pathlib import Path

import typer

from pkgwarden_cli import http_client
from pkgwarden_cli.capabilities import fetch_capabilities
from pkgwarden_cli.config import (
    SUPPORTED_MODES,
    SUPPORTED_PACKAGE_MANAGERS,
    CliMode,
    PackageManager,
)
from pkgwarden_cli.init_discovery import build_init_defaults, merged_env_for_init
from pkgwarden_cli.urls import normalize_api_base


def init(
    ctx: typer.Context,
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        envvar="PKGWARDEN_API_URL",
        help="Non-interactive only: override discovered API URL",
    ),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help=f"Override mode; one of {', '.join(SUPPORTED_MODES)}",
    ),
    package_manager: str | None = typer.Option(
        None,
        "--package-manager",
        help=f"Override package manager; one of {', '.join(SUPPORTED_PACKAGE_MANAGERS)}",
    ),
    project_id: str | None = typer.Option(None, "--project-id", envvar="PKGWARDEN_PROJECT_ID"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing .pkgwarden.toml"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive: use discovered values; error if API URL or package manager missing",
    ),
) -> None:
    cwd = Path.cwd()
    target = cwd / ".pkgwarden.toml"
    if target.exists() and not force:
        typer.echo(f"{target} already exists; pass --force to overwrite", err=True)
        raise typer.Exit(1)

    merged = merged_env_for_init(cwd)
    mode_validated = _validate_mode(mode)
    manager_validated = _validate_manager(package_manager)
    defaults = build_init_defaults(
        cwd,
        merged,
        api_url_override=api_url,
        mode_override=mode_validated,
        package_manager_override=manager_validated,
        project_id_override=project_id,
    )

    if yes:
        _init_non_interactive(
            ctx,
            target,
            defaults,
            mode_flag=mode_validated,
            package_manager_flag=manager_validated,
        )
        return

    _init_interactive_wizard(ctx, cwd, target, defaults)


def _init_non_interactive(
    ctx: typer.Context,
    target: Path,
    defaults,
    *,
    mode_flag: CliMode | None,
    package_manager_flag: PackageManager | None,
) -> None:
    if not defaults.api_url:
        typer.echo(
            "No API URL found. Set PKGWARDEN_API_URL, add PKGWARDEN_API_URL to a .env file in this "
            "directory, configure a pkgwarden index URL in pyproject.toml or .npmrc, or pass "
            "--api-url. For prompts, run `pw init` without --yes.",
            err=True,
        )
        raise typer.Exit(1)
    api_base = defaults.api_url
    resolved_mode = mode_flag if mode_flag is not None else defaults.mode
    if resolved_mode is None:
        resolved_mode = _probe_mode(api_base, ctx)
    resolved_manager = (
        package_manager_flag if package_manager_flag is not None else defaults.package_manager
    )
    if resolved_manager is None:
        typer.echo(
            "No package manager detected; pass --package-manager or run `pw init` without --yes.",
            err=True,
        )
        raise typer.Exit(1)
    _write_config(
        target,
        api_base=api_base,
        mode=resolved_mode,
        package_manager=resolved_manager,
        project_id=defaults.project_id,
    )
    _echo_wrote(target, api_base, resolved_mode, resolved_manager, defaults.project_id)


def _init_interactive_wizard(ctx: typer.Context, cwd: Path, target: Path, defaults) -> None:
    typer.echo("pkgwarden setup")
    if defaults.notes:
        typer.echo("Discovered from your project and environment:")
        for note in defaults.notes:
            typer.echo(f"  • {note}")

    default_api = defaults.api_url or ""
    api_prompt = typer.prompt("API base URL (pkgwarden /api/v1 endpoint)", default=default_api)
    api_stripped = api_prompt.strip()
    if not api_stripped:
        typer.echo("API URL is required.", err=True)
        raise typer.Exit(1)
    api_base = normalize_api_base(api_stripped)

    probed_mode = _probe_mode(api_base, ctx)
    mode_default: str = defaults.mode if defaults.mode is not None else (probed_mode or "tape")
    mode_prompt = typer.prompt(
        "Deployment mode (tape or enterprise)",
        default=mode_default,
    )
    if mode_prompt not in SUPPORTED_MODES:
        typer.echo(f"Mode must be one of: {', '.join(SUPPORTED_MODES)}", err=True)
        raise typer.Exit(1)
    resolved_mode = mode_prompt  # type: ignore[assignment]
    if defaults.mode is not None and mode_prompt == defaults.mode:
        typer.echo(f"  (default matched {defaults.mode_source})")

    resolved_manager = defaults.package_manager
    if resolved_manager is None:
        mgr_default = "uv"
        mgr_prompt = typer.prompt(
            f"Package manager ({', '.join(SUPPORTED_PACKAGE_MANAGERS)})",
            default=mgr_default,
        )
        if mgr_prompt not in SUPPORTED_PACKAGE_MANAGERS:
            typer.echo(
                f"Unknown package manager {mgr_prompt!r}; "
                f"expected one of {', '.join(SUPPORTED_PACKAGE_MANAGERS)}",
                err=True,
            )
            raise typer.Exit(1)
        resolved_manager = mgr_prompt  # type: ignore[assignment]
    else:
        typer.echo(f"Using package manager {resolved_manager!r} from your project files.")

    resolved_project_id = defaults.project_id
    if resolved_mode == "enterprise":
        pid_default = resolved_project_id or ""
        pid_prompt = typer.prompt(
            "Project ID (optional; needed for some commands like package publish)",
            default=pid_default,
        )
        resolved_project_id = pid_prompt.strip() or None

    if not typer.confirm("Write .pkgwarden.toml in this directory?", default=True):
        typer.echo("Cancelled.")
        raise typer.Exit(0)

    _write_config(
        target,
        api_base=api_base,
        mode=resolved_mode,
        package_manager=resolved_manager,
        project_id=resolved_project_id,
    )
    _echo_wrote(target, api_base, resolved_mode, resolved_manager, resolved_project_id)


def _echo_wrote(
    path: Path,
    api_base: str,
    mode: CliMode | None,
    package_manager: PackageManager,
    project_id: str | None,
) -> None:
    message = (
        f"Wrote {path}\n"
        f"  api_url: {api_base}\n"
        f"  mode: {mode or 'unknown'}\n"
        f"  package_manager: {package_manager}"
    )
    if project_id:
        message += f"\n  project_id: {project_id}"
    typer.echo(message)


def _validate_mode(mode: str | None) -> CliMode | None:
    if mode is None:
        return None
    if mode not in SUPPORTED_MODES:
        raise typer.BadParameter(
            f"Invalid --mode {mode!r}; expected one of {', '.join(SUPPORTED_MODES)}",
        )
    return mode  # type: ignore[return-value]


def _validate_manager(manager: str | None) -> PackageManager | None:
    if manager is None:
        return None
    if manager not in SUPPORTED_PACKAGE_MANAGERS:
        raise typer.BadParameter(
            f"Invalid --package-manager {manager!r}; "
            f"expected one of {', '.join(SUPPORTED_PACKAGE_MANAGERS)}",
        )
    return manager  # type: ignore[return-value]


def _probe_mode(api_base: str, ctx: typer.Context) -> CliMode | None:
    inputs = ctx.find_root().obj.get("cli_inputs") if ctx.find_root().obj else None
    timeout = float(inputs.get("timeout", 30.0)) if isinstance(inputs, dict) else 30.0
    client = http_client.build_api_client(
        api_base=api_base,
        bearer_token="",
        timeout=timeout,
    )
    try:
        caps = fetch_capabilities(client)
    finally:
        client.close()
    if caps.deployment_type == "unknown":
        return None
    return caps.deployment_type  # type: ignore[return-value]


def _write_config(
    path: Path,
    *,
    api_base: str,
    mode: CliMode | None,
    package_manager: PackageManager,
    project_id: str | None,
) -> None:
    lines = [
        f'api_url = "{api_base}"',
        f'package_manager = "{package_manager}"',
    ]
    if mode is not None:
        lines.insert(1, f'mode = "{mode}"')
    if project_id:
        lines.append(f'project_id = "{project_id}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def register_init(app: typer.Typer) -> None:
    app.command("init")(init)

from pathlib import Path

import typer

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli.config import PackageManager
from pkgwarden_cli.mirror_auth import cleanup_native_auth_env, native_auth_env
from pkgwarden_cli.output import emit_structured
from pkgwarden_cli.package_manager import (
    add_command,
    detect_managers,
    lock_command,
    manifest_write_command,
    remove_command,
)
from pkgwarden_cli.process_runner import ProcessResult, run_process
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.spec import ParsedSpec, native_spec, parse_package_argument

REQUEST_PENDING_EXIT_CODE = 10


def add(
    ctx: typer.Context,
    packages: list[str] = typer.Argument(
        ..., help="Packages: name, name==version, name@version, name[extras]==version"
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Exact version pin (single package only; inline name==version also works)",
    ),
    manager_override: str | None = typer.Option(None, "--manager"),
    dev: bool = typer.Option(False, "--dev", help="Add to the dev dependency group"),
    group: str | None = typer.Option(None, "--group", help="Add to a named dependency group"),
) -> None:
    """Add packages via the native manager; blocked ones open approval requests."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    if version is not None and len(packages) > 1:
        raise typer.BadParameter(
            "--version applies to a single package; pin batches inline (name==version)."
        )
    if dev and group is not None:
        raise typer.BadParameter("Pass --dev or --group, not both.")
    parsed_specs = [parse_package_argument(raw, version) for raw in packages]
    native_specs = [native_spec(manager, parsed) for parsed in parsed_specs]
    try:
        native_argv = add_command(manager, native_specs, dev=dev, group=group)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from err
    auth_env = native_auth_env(runtime.config, manager, cwd)
    try:
        skip_native = _should_skip_native_add(runtime, manager, parsed_specs)
        if skip_native:
            first = ProcessResult(1, "", "")
        else:
            first = run_process(native_argv, cwd=cwd, env_overrides=auth_env or None)
        if first.returncode == 0:
            _echo_process(first)
            typer.echo(f"pw add: {manager} added {', '.join(native_specs)}")
            return
        mode = runtime.config.mode or "unknown"
        if mode != "enterprise":
            _echo_process(first)
            hint = (
                f"{parsed_specs[0].name}=={parsed_specs[0].version}"
                if parsed_specs[0].exact
                else "<name>==<version>"
            )
            typer.echo(
                f"pw add: {manager} could not add {', '.join(native_specs)}. "
                f"Run `pw why-blocked {hint}` for details.",
                err=True,
            )
            raise typer.Exit(1)
        fallback = enterprise_hooks.get_add_fallback()
        if fallback is None:
            _echo_process(first)
            typer.echo(
                "pw add: native add failed. Enterprise server-side fallback is "
                "unavailable (pkgwarden-cli-enterprise plugin not installed).",
                err=True,
            )
            raise typer.Exit(1)
        pending, errors, results = _open_requests(runtime, manager, parsed_specs, fallback)
        if errors:
            _echo_process(first)
        manifest_updated = _write_through(
            runtime, manager, cwd, [spec for spec, _ in pending], dev, group, auth_env
        )
        if runtime.json_output:
            emit_structured(runtime, {"results": results, "manifest_updated": manifest_updated})
        else:
            for line in errors:
                typer.echo(line, err=True)
            for parsed, outcome in pending:
                typer.echo(_pending_text(manager, parsed, outcome))
        if errors:
            raise typer.Exit(1)
        if pending:
            raise typer.Exit(REQUEST_PENDING_EXIT_CODE)
        raise typer.Exit(1)
    finally:
        cleanup_native_auth_env(auth_env)


def _open_requests(
    runtime: CliRuntime,
    manager: PackageManager,
    parsed_specs: list[ParsedSpec],
    fallback: enterprise_hooks.AddFallback,
) -> tuple[list[tuple[ParsedSpec, enterprise_hooks.EnterpriseAddOutcome]], list[str], list[dict]]:
    pending: list[tuple[ParsedSpec, enterprise_hooks.EnterpriseAddOutcome]] = []
    errors: list[str] = []
    results: list[dict] = []
    for parsed in parsed_specs:
        spec_text = native_spec(manager, parsed)
        if not parsed.exact:
            errors.append(
                f"pw add: {spec_text} needs an exact version to open an approval request — "
                f"use {parsed.name}==<version> (or --version <version>)."
            )
            results.append(
                {"package": parsed.name, "version": parsed.version, "status": "needs_pin"}
            )
            continue
        outcome = fallback(runtime, manager, parsed.name, parsed.version or "", parsed.extras)
        if outcome is None:
            errors.append(f"pw add: could not open a request for {spec_text} (see message above).")
            results.append({"package": parsed.name, "version": parsed.version, "status": "error"})
            continue
        if outcome.status == enterprise_hooks.ALREADY_AVAILABLE_STATUS:
            errors.append(
                f"pw add: {spec_text} is already available in the mirror; {manager} could not "
                "resolve the project for another reason (shown above)."
            )
            results.append(
                {"package": parsed.name, "version": parsed.version, "status": "already_available"}
            )
            continue
        if outcome.status == enterprise_hooks.VERSION_TOO_YOUNG_STATUS:
            errors.append(
                f"pw add: {spec_text} was rejected: this version was published too recently "
                "to pass the cooldown window. Try again later or ask an admin to override."
            )
            results.append(
                {"package": parsed.name, "version": parsed.version, "status": "version_too_young"}
            )
            continue
        pending.append((parsed, outcome))
        results.append(
            {
                "package": outcome.package,
                "version": outcome.version,
                "status": "pending"
                if outcome.status != enterprise_hooks.DUPLICATE_PENDING_STATUS
                else "already_pending",
                "blocking_status": outcome.blocking_status,
                "request_group_id": outcome.request_group_id,
                "web_url": outcome.web_url,
                "linked_exception_request_count": outcome.linked_exception_request_count,
            }
        )
    return pending, errors, results


def _pending_text(
    manager: PackageManager,
    parsed: ParsedSpec,
    outcome: enterprise_hooks.EnterpriseAddOutcome,
) -> str:
    spec_text = native_spec(manager, parsed)
    if outcome.status == enterprise_hooks.DUPLICATE_PENDING_STATUS:
        return _duplicate_pending_text(manager, spec_text, outcome)
    return format_enterprise_add_pending(spec_text, outcome)


def _duplicate_pending_text(
    manager: PackageManager,
    spec_text: str,
    outcome: enterprise_hooks.EnterpriseAddOutcome,
) -> str:
    status = outcome.blocking_status or "pending"
    if outcome.conflict_message:
        header = f"{spec_text}: {outcome.conflict_message}"
    elif status == "pending":
        header = f"{spec_text} is already awaiting approval — no new request opened."
    else:
        header = (
            f"{spec_text} is already {status} — no new request opened. "
            "Ask an admin if you're unsure whether it succeeded."
        )
    lines = [header]
    if outcome.web_url:
        lines.append(f"    track           {outcome.web_url}")
    lines.append(
        f"  Once approved, re-run  pw add {outcome.package}=={outcome.version}"
        f"  (or `{manager} sync`)."
    )
    return "\n".join(lines)


def _write_through(
    runtime: CliRuntime,
    manager: PackageManager,
    cwd: Path,
    pending_specs: list[ParsedSpec],
    dev: bool,
    group: str | None,
    auth_env: dict[str, str],
) -> bool:
    if not pending_specs:
        return False
    argv = manifest_write_command(
        manager, [native_spec(manager, spec) for spec in pending_specs], dev=dev, group=group
    )
    if argv is None:
        if not runtime.json_output:
            typer.echo(
                f"pw add: note — {manager} manifest not updated; re-run pw add after approval.",
                err=True,
            )
        return False
    result = run_process(argv, cwd=cwd, env_overrides=auth_env or None)
    if result.returncode != 0 and not runtime.json_output:
        typer.echo(
            "pw add: note — could not record the pending dependency in pyproject.toml.", err=True
        )
    return result.returncode == 0


def remove(
    ctx: typer.Context,
    package: str = typer.Argument(..., help="Package name (a name==version spec is accepted)"),
    manager_override: str | None = typer.Option(None, "--manager"),
) -> None:
    """Remove a dependency with the native package manager."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    parsed = parse_package_argument(package, None)
    auth_env = native_auth_env(runtime.config, manager, cwd)
    try:
        result = run_process(
            remove_command(manager, parsed.name), cwd=cwd, env_overrides=auth_env or None
        )
        _echo_process(result)
        if result.returncode != 0:
            raise typer.Exit(1)
    finally:
        cleanup_native_auth_env(auth_env)


def lock(
    ctx: typer.Context,
    manager_override: str | None = typer.Option(None, "--manager"),
) -> None:
    """Refresh the native lockfile against the gated mirror."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cwd = Path.cwd()
    manager = _resolve_manager(runtime, manager_override, cwd)
    auth_env = native_auth_env(runtime.config, manager, cwd)
    try:
        result = run_process(lock_command(manager), cwd=cwd, env_overrides=auth_env or None)
        _echo_process(result)
        if result.returncode != 0:
            raise typer.Exit(1)
    finally:
        cleanup_native_auth_env(auth_env)


def _should_skip_native_add(
    runtime: CliRuntime,
    manager: PackageManager,
    parsed_specs: list[ParsedSpec],
) -> bool:
    if (runtime.config.mode or "unknown") != "enterprise":
        return False
    if enterprise_hooks.get_add_fallback() is None:
        return False
    skip_check = enterprise_hooks.get_add_native_skip_check()
    return skip_check(runtime, manager, parsed_specs) if skip_check is not None else False


def _resolve_manager(
    runtime: CliRuntime,
    override: str | None,
    cwd: Path,
) -> PackageManager:
    if override:
        if override not in ("uv", "poetry", "pip", "pnpm", "npm", "yarn"):
            raise typer.BadParameter(f"Unknown package manager {override!r}")
        return override  # type: ignore[return-value]
    if runtime.config.package_manager:
        return runtime.config.package_manager
    detections = detect_managers(cwd)
    if not detections:
        typer.echo(
            "No package_manager configured and none detected. "
            "Run `pw init --package-manager <uv|pnpm|...>` or pass --manager.",
            err=True,
        )
        raise typer.Exit(1)
    return detections[0].manager


def _echo_process(result: ProcessResult) -> None:
    if result.stdout:
        typer.echo(result.stdout.rstrip())
    if result.stderr:
        typer.echo(result.stderr.rstrip(), err=True)


def format_enterprise_add_pending(spec: str, outcome: enterprise_hooks.EnterpriseAddOutcome) -> str:
    header = "✓ Approval request opened"
    if outcome.project_name:
        header += f"  ·  {outcome.project_name}"
    lines = [
        f"{spec} isn't installable yet — it needs security approval.",
        "",
        header,
    ]
    if outcome.request_group_id:
        lines.append(f"    request group   {outcome.request_group_id}")
    lines.append(f"    package         {spec}  ({outcome.status})")
    if outcome.linked_exception_request_count > 0:
        count = outcome.linked_exception_request_count
        noun = "CVE exception" if count == 1 else "CVE exceptions"
        lines.append(f"    {noun:<14}  {count} opened (time-bounded, pending review)")
    if outcome.web_url:
        lines.append(f"    track           {outcome.web_url}")
    lines.append("")
    lines.append(
        f"  Once approved, re-run  pw add {outcome.package}=={outcome.version}  (or `pw sync`)."
    )
    return "\n".join(lines)


def register_add(app: typer.Typer) -> None:
    app.command("add")(add)
    app.command("remove")(remove)
    app.command("lock")(lock)

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer
from pydantic import BaseModel, ConfigDict, Field

from pkgwarden_cli import http_client
from pkgwarden_cli.gate_mode_guard import require_gate
from pkgwarden_cli.output import emit
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.vscode_editor import EditorKind, parse_editor_kind, user_settings_path
from pkgwarden_cli.vscode_inventory import (
    InventoryCollectionError,
    VscodeInventoryEntry,
    collect_installed_extensions,
)
from pkgwarden_cli.vscode_settings import (
    SettingsJsonError,
    read_settings_object,
    write_extensions_allowed,
)
from pkgwarden_cli.vscode_sync_state import (
    format_stale_sync_warning,
    is_sync_stale,
    load_last_success_at,
    save_last_success_at,
)


class VscodePolicyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Per-extension version-pin lists, plus trusted-publisher wholesale allows keyed by bare
    # publisher -> True (VS Code's native publisher-wide allow, #425).
    extensions_allowed: dict[str, list[str] | bool] = Field(alias="extensions.allowed")
    generated_at: datetime


class DryRunExtension(BaseModel):
    extension_id: str
    current_version: str | None = None
    allowed_versions: list[str] = Field(default_factory=list)


class DryRunPreview(BaseModel):
    allowed_at_current_version: list[DryRunExtension]
    allowed_but_version_excluded: list[DryRunExtension]
    fully_blocked: list[DryRunExtension]
    would_be_removed_from_settings: list[str]
    pins_changed: list[str]
    settings_diff_skipped: bool


def _version_list(value: list[str] | bool | None) -> list[str]:
    return value if isinstance(value, list) else []


def classify_dry_run(
    inventory: list[VscodeInventoryEntry],
    pin_map: Mapping[str, list[str] | bool],
    current_extensions_allowed: Mapping[str, object] | None,
) -> DryRunPreview:
    """The gate server emits every inventoried id, with [] pins when blocked;
    a missing id is treated the same, defensively. A trusted-publisher entry is a bare
    ``publisher`` key mapped to ``True`` (a wholesale allow, #425), so extensions under it
    are allowed even though the extension id itself is absent from the pin map. Write mode
    wholesale-replaces extensions.allowed, so entries only in the current settings surface
    as removals; current_extensions_allowed=None means the settings could not be read."""
    allowed_at_current_version: list[DryRunExtension] = []
    allowed_but_version_excluded: list[DryRunExtension] = []
    fully_blocked: list[DryRunExtension] = []
    inventoried = {entry.extension_id for entry in inventory}
    trusted_publishers = {key for key, value in pin_map.items() if value is True}
    for entry in inventory:
        # A specific ``"publisher.extension": false`` deny always beats the publisher-wide
        # allow -- that entry exists precisely to carve a malware-marked extension back out.
        if pin_map.get(entry.extension_id) is False:
            fully_blocked.append(
                DryRunExtension(
                    extension_id=entry.extension_id, current_version=entry.current_version
                )
            )
            continue
        if entry.extension_id.split(".", 1)[0] in trusted_publishers:
            allowed_at_current_version.append(
                DryRunExtension(
                    extension_id=entry.extension_id, current_version=entry.current_version
                )
            )
            continue
        allowed_versions = _version_list(pin_map.get(entry.extension_id))
        classified = DryRunExtension(
            extension_id=entry.extension_id,
            current_version=entry.current_version,
            allowed_versions=allowed_versions,
        )
        if not allowed_versions:
            fully_blocked.append(classified)
        elif entry.current_version in allowed_versions:
            allowed_at_current_version.append(classified)
        else:
            allowed_but_version_excluded.append(classified)
    for extension_id, value in pin_map.items():
        if extension_id in inventoried or value is True:
            continue
        allowed_versions = _version_list(value)
        classified = DryRunExtension(extension_id=extension_id, allowed_versions=allowed_versions)
        (allowed_at_current_version if allowed_versions else fully_blocked).append(classified)
    current = current_extensions_allowed if current_extensions_allowed is not None else {}
    return DryRunPreview(
        allowed_at_current_version=allowed_at_current_version,
        allowed_but_version_excluded=allowed_but_version_excluded,
        fully_blocked=fully_blocked,
        would_be_removed_from_settings=sorted(set(current) - set(pin_map)),
        pins_changed=sorted(
            extension_id
            for extension_id, versions in current.items()
            if extension_id in pin_map and versions != pin_map[extension_id]
        ),
        settings_diff_skipped=current_extensions_allowed is None,
    )


def _format_extension(extension: DryRunExtension) -> str:
    if extension.current_version is None:
        return f"{extension.extension_id} (not installed)"
    return f"{extension.extension_id}@{extension.current_version}"


def _format_dry_run_preview(preview: DryRunPreview) -> str:
    lines = [
        "pw vscode sync-policy --dry-run: settings.json was not written.",
        f"  allowed at current version ({len(preview.allowed_at_current_version)}):",
        *(
            f"    {_format_extension(extension)}"
            for extension in preview.allowed_at_current_version
        ),
        f"  allowed but current version excluded ({len(preview.allowed_but_version_excluded)}):",
        *(
            f"    {_format_extension(extension)} "
            f"(would pin to {', '.join(extension.allowed_versions)})"
            for extension in preview.allowed_but_version_excluded
        ),
        f"  fully blocked, would be DISABLED ({len(preview.fully_blocked)}):",
        *(f"    {_format_extension(extension)}" for extension in preview.fully_blocked),
    ]
    if preview.settings_diff_skipped:
        lines.append("  current-settings diff skipped: settings.json could not be read.")
        return "\n".join(lines)
    lines.append(f"  pins changed ({len(preview.pins_changed)}):")
    lines.extend(f"    {extension_id}" for extension_id in preview.pins_changed)
    lines.append(
        f"  would be removed from settings.json ({len(preview.would_be_removed_from_settings)}):",
    )
    lines.extend(f"    {extension_id}" for extension_id in preview.would_be_removed_from_settings)
    return "\n".join(lines)


def sync_policy(
    ctx: typer.Context,
    editor: str = typer.Option(
        EditorKind.CODE.value,
        "--editor",
        help="Editor binary: code, cursor, windsurf, or codium",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Re-run sync on an interval (see docs for cron guidance)",
    ),
    watch_interval_minutes: int = typer.Option(
        60,
        "--watch-interval-minutes",
        min=5,
        help="Minutes between syncs when --watch is set",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview the allowlist effect without writing settings.json",
    ),
) -> None:
    """Refresh extensions.allowed in the editor settings from gate policy."""
    if watch and dry_run:
        raise typer.BadParameter("--dry-run cannot be combined with --watch")
    require_gate(ctx, "pw vscode")
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    try:
        editor_kind = parse_editor_kind(editor)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    if watch:
        while True:
            exit_code = _run_sync_policy(runtime, editor_kind, dry_run=dry_run)
            if exit_code != 0:
                raise typer.Exit(exit_code)
            time.sleep(watch_interval_minutes * 60)
    exit_code = _run_sync_policy(runtime, editor_kind, dry_run=dry_run)
    if exit_code != 0:
        raise typer.Exit(exit_code)


def _run_sync_policy(runtime: CliRuntime, editor: EditorKind, *, dry_run: bool = False) -> int:
    now = datetime.now(UTC)
    if not dry_run:
        last_success_at = load_last_success_at(editor)
        if is_sync_stale(last_success_at, now=now):
            typer.echo(
                format_stale_sync_warning(editor, last_success_at=last_success_at, now=now),
                err=True,
            )
    try:
        token = http_client.gate_bearer_token(runtime.config)
    except ValueError as error:
        typer.echo(str(error), err=True)
        return 1
    try:
        inventory = collect_installed_extensions(editor, timeout=runtime.timeout, cwd=Path.cwd())
    except InventoryCollectionError as error:
        typer.echo(str(error), err=True)
        return 1
    try:
        policy = fetch_vscode_policy(runtime, token=token, inventory=inventory)
    except httpx.HTTPStatusError as error:
        typer.echo(http_client.http_error_message(error), err=True)
        return 1
    except httpx.RequestError as error:
        typer.echo(f"pw vscode sync-policy: could not reach the API ({error}).", err=True)
        return 1
    if dry_run:
        try:
            current_extensions = _current_extensions_allowed(editor)
        except SettingsJsonError as error:
            typer.echo(
                f"pw vscode sync-policy --dry-run: {error}; write mode would fail on this file.",
                err=True,
            )
            return 1
        preview = classify_dry_run(inventory, policy.extensions_allowed, current_extensions)
        emit(
            runtime,
            _format_dry_run_preview(preview),
            {"dry_run": True, "editor": editor.value, **preview.model_dump(mode="json")},
        )
        return 0
    settings_path = user_settings_path(editor)
    try:
        write_extensions_allowed(settings_path, policy.extensions_allowed)
    except SettingsJsonError as error:
        typer.echo(f"pw vscode sync-policy: {error}", err=True)
        return 1
    save_last_success_at(editor, now)
    extension_count = len(policy.extensions_allowed)
    human = (
        f"pw vscode sync-policy: synced {extension_count} extension(s) into "
        f"{settings_path} (generated_at={policy.generated_at.isoformat()})"
    )
    emit(
        runtime,
        human,
        {
            "editor": editor.value,
            "settings_path": str(settings_path),
            "extension_count": extension_count,
            "generated_at": policy.generated_at.isoformat(),
            "extensions_allowed": policy.extensions_allowed,
        },
    )
    return 0


def _current_extensions_allowed(editor: EditorKind) -> dict[str, object] | None:
    """None means the settings path could not be resolved; diffing is skipped.
    A malformed or unreadable file raises SettingsJsonError — write mode would fail on it.
    All keys are kept regardless of value type; the removal diff compares keys."""
    try:
        settings_path = user_settings_path(editor)
    except ValueError:
        return None
    try:
        settings = read_settings_object(settings_path)
    except OSError as error:
        raise SettingsJsonError(
            f"settings.json at {settings_path} could not be read: {error}",
        ) from error
    raw = settings.get("extensions.allowed")
    if not isinstance(raw, dict):
        return {}
    return {key: versions for key, versions in raw.items() if isinstance(key, str)}


def fetch_vscode_policy(
    runtime: CliRuntime,
    *,
    token: str,
    inventory: list[VscodeInventoryEntry],
) -> VscodePolicyResponse:
    client = http_client.build_api_client(
        api_base=runtime.config.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )
    try:
        response = client.post(
            "/vscode/policy",
            json={
                "inventory": [entry.model_dump(mode="json") for entry in inventory],
            },
        )
        response.raise_for_status()
        return VscodePolicyResponse.model_validate(response.json())
    finally:
        client.close()

import os
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pkgwarden_cli.vscode_editor import EditorKind

STALE_SYNC_THRESHOLD = timedelta(hours=24)


def _state_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "pkgwarden" / "vscode-sync.toml"


def _read_state() -> dict[str, dict[str, str]]:
    path = _state_path()
    if not path.is_file():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for section, values in raw.items():
        if isinstance(section, str) and isinstance(values, dict):
            clean = {
                key: value
                for key, value in values.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if clean:
                result[section] = clean
    return result


def _write_state(data: dict[str, dict[str, str]]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section in sorted(data):
        lines.append(f"[{section}]")
        for key in sorted(data[section]):
            value = data[section][key]
            lines.append(f'{key} = "{_escape(value)}"')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def load_last_success_at(editor: EditorKind) -> datetime | None:
    section = _read_state().get(editor.value)
    if section is None:
        return None
    raw = section.get("last_success_at")
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def save_last_success_at(editor: EditorKind, moment: datetime) -> None:
    data = _read_state()
    data.setdefault(editor.value, {})["last_success_at"] = moment.astimezone(UTC).isoformat()
    _write_state(data)


def is_sync_stale(last_success_at: datetime | None, *, now: datetime) -> bool:
    if last_success_at is None:
        return True
    return now - last_success_at > STALE_SYNC_THRESHOLD


def format_stale_sync_warning(
    editor: EditorKind,
    *,
    last_success_at: datetime | None,
    now: datetime,
) -> str:
    if last_success_at is None:
        age_text = "never synced"
    else:
        age = now - last_success_at
        hours = int(age.total_seconds() // 3600)
        age_text = f"last successful sync {hours}h ago ({last_success_at.isoformat()})"
    return (
        "WARNING: STALE VS Code allowlist — "
        f"{editor.value} extensions.allowed is out of date ({age_text}). "
        "Auto-updates may be frozen until you run `pw vscode sync-policy` on a schedule "
        "(cron or --watch). See docs/changes/gate-vscode-pr4-sync-policy-cli.md."
    )

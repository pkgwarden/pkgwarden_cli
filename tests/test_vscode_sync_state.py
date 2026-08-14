from datetime import UTC, datetime, timedelta

from pkgwarden_cli.vscode_editor import EditorKind
from pkgwarden_cli.vscode_sync_state import (
    STALE_SYNC_THRESHOLD,
    format_stale_sync_warning,
    is_sync_stale,
    load_last_success_at,
    save_last_success_at,
)


def test_is_sync_stale_when_never_synced() -> None:
    assert is_sync_stale(None, now=datetime(2026, 7, 9, tzinfo=UTC)) is True


def test_is_sync_stale_when_older_than_threshold() -> None:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    last = now - STALE_SYNC_THRESHOLD - timedelta(minutes=1)
    assert is_sync_stale(last, now=now) is True


def test_is_sync_stale_when_within_threshold() -> None:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    last = now - STALE_SYNC_THRESHOLD + timedelta(minutes=5)
    assert is_sync_stale(last, now=now) is False


def test_format_stale_sync_warning_is_loud() -> None:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    last = now - timedelta(days=3)
    message = format_stale_sync_warning(EditorKind.CODE, last_success_at=last, now=now)
    assert "STALE" in message
    assert "code" in message
    assert "sync-policy" in message


def test_save_and_load_last_success_at_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    moment = datetime(2026, 7, 8, 9, 30, 0, tzinfo=UTC)
    save_last_success_at(EditorKind.CURSOR, moment)
    loaded = load_last_success_at(EditorKind.CURSOR)
    assert loaded == moment

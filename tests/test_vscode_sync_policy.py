import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ansi import strip_ansi
from pkgwarden_cli import http_client as http_mod
from pkgwarden_cli import main as main_module
from pkgwarden_cli.vscode_editor import EditorKind, user_settings_path
from pkgwarden_cli.vscode_inventory import VscodeInventoryEntry
from pkgwarden_cli.vscode_settings import (
    MANAGED_EXTENSIONS_ALLOWED_BANNER,
    SettingsJsonError,
    parse_jsonc,
)
from pkgwarden_cli.vscode_sync_policy_cli import _current_extensions_allowed
from pkgwarden_cli.vscode_sync_state import (
    STALE_SYNC_THRESHOLD,
    load_last_success_at,
    save_last_success_at,
)

_POLICY_RESPONSE = {
    "extensions.allowed": {
        "demo.publisher": ["1.2.3", "1.3.0"],
    },
    "generated_at": "2026-07-09T12:00:00+00:00",
}

# The gate server emits every inventoried extension id; blocked ones get [].
_DRY_RUN_POLICY_RESPONSE = {
    "extensions.allowed": {
        "demo.publisher": ["1.2.3", "1.3.0"],
        "demo.pinned": ["1.0.0", "1.1.0"],
        "demo.blocked": [],
    },
    "generated_at": "2026-07-09T12:00:00+00:00",
}


def _write_gate_config(tmp_path: Path) -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://gate.test/api/v1"\nmode = "gate"\n',
        encoding="utf-8",
    )


def _wrap_api_client(handler):
    real_build = http_mod.build_api_client

    def wrapped(**kwargs):
        return real_build(**{**kwargs, "transport": httpx.MockTransport(handler)})

    return wrapped


def test_sync_policy_happy_path_writes_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    editor_settings.write_text('{"editor.fontSize": 14}', encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        assert editor == EditorKind.CODE
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/vscode/policy")
        assert request.headers.get("authorization") == "Bearer gate_secret"
        body = json.loads(request.content.decode())
        assert body == {
            "inventory": [{"extension_id": "demo.publisher", "current_version": "1.2.3"}],
        }
        return httpx.Response(200, json=_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code == 0, result.stdout + result.stderr
    on_disk = editor_settings.read_text(encoding="utf-8")
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in on_disk
    written = parse_jsonc(on_disk)
    assert isinstance(written, dict)
    assert written["extensions.allowed"] == {"demo.publisher": ["1.2.3", "1.3.0"]}
    assert written["editor.fontSize"] == 14
    assert "synced" in (result.stdout + result.stderr).lower()


def test_sync_policy_preserves_jsonc_comments_when_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    original = '{\n  // keep me\n  "editor.fontSize": 14,\n}\n'
    editor_settings.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code == 0, result.stdout + result.stderr
    on_disk = editor_settings.read_text(encoding="utf-8")
    assert "// keep me" in on_disk
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in on_disk
    assert '"editor.fontSize": 14' in on_disk
    parsed = parse_jsonc(on_disk)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == _POLICY_RESPONSE["extensions.allowed"]
    assert parsed["editor.fontSize"] == 14


def test_sync_policy_warns_when_last_sync_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    stale_moment = datetime.now(UTC) - STALE_SYNC_THRESHOLD - timedelta(hours=1)
    save_last_success_at(EditorKind.CODE, stale_moment)

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "STALE" in combined


def test_sync_policy_malformed_settings_exits_with_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    editor_settings.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code != 0
    assert "Malformed settings.json" in result.stderr


@pytest.mark.parametrize("extra_args", [[], ["--dry-run"]])
def test_sync_policy_non_utf8_settings_exits_cleanly(
    tmp_path: Path, monkeypatch, extra_args: list[str]
) -> None:
    """A UTF-16/corrupted settings.json must fail like any other malformed file, in write
    mode and dry-run alike -- never an unhandled UnicodeDecodeError traceback."""
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    editor_settings.write_bytes(b'\xff\xfe{\x00"a\x00"\x00}')
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy", *extra_args])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not valid UTF-8" in strip_ansi(result.stderr)


def test_sync_policy_rejects_enterprise_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "tok")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code != 0
    assert "only available for gate" in result.stderr.lower()


def test_dry_run_writes_nothing_and_prints_preview_buckets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    original_settings = (
        '{"editor.fontSize": 14, "extensions.allowed":'
        ' {"demo.stale-manual": ["9.9.9"], "demo.publisher": ["1.0.0"]}}'
    )
    editor_settings.write_text(original_settings, encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [
            VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3"),
            VscodeInventoryEntry(extension_id="demo.pinned", current_version="0.9.0"),
            VscodeInventoryEntry(extension_id="demo.blocked", current_version="9.9.9"),
        ]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DRY_RUN_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy", "--dry-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert editor_settings.read_text(encoding="utf-8") == original_settings
    assert load_last_success_at(EditorKind.CODE) is None
    combined = result.stdout + result.stderr
    assert "demo.publisher@1.2.3" in combined
    assert "demo.pinned@0.9.0 (would pin to 1.0.0, 1.1.0)" in combined
    assert "demo.blocked@9.9.9" in combined
    assert "DISABLED" in combined
    assert "would be removed from settings.json (1):" in combined
    assert "demo.stale-manual" in combined
    assert "pins changed (1):" in combined
    assert "STALE" not in combined


def test_dry_run_json_output_lists_preview_buckets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [
            VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3"),
            VscodeInventoryEntry(extension_id="demo.pinned", current_version="0.9.0"),
            VscodeInventoryEntry(extension_id="demo.blocked", current_version="9.9.9"),
        ]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DRY_RUN_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["--json", "vscode", "sync-policy", "--dry-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert not editor_settings.is_file()
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert [e["extension_id"] for e in data["allowed_at_current_version"]] == ["demo.publisher"]
    assert [e["extension_id"] for e in data["allowed_but_version_excluded"]] == ["demo.pinned"]
    assert [e["extension_id"] for e in data["fully_blocked"]] == ["demo.blocked"]
    assert data["would_be_removed_from_settings"] == []
    assert data["pins_changed"] == []
    assert data["settings_diff_skipped"] is False


def test_dry_run_exits_one_when_settings_malformed(tmp_path: Path, monkeypatch) -> None:
    """A faithful simulation includes simulating the write-mode failure."""
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    editor_settings.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DRY_RUN_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy", "--dry-run"])
    assert result.exit_code == 1
    assert str(editor_settings) in result.stderr
    assert "write mode would fail" in result.stderr


def test_dry_run_notes_skipped_diff_when_settings_path_unresolvable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def unresolvable_settings_path(_editor):
        raise ValueError("APPDATA is not set; cannot locate editor settings on Windows")

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        unresolvable_settings_path,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3")]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DRY_RUN_POLICY_RESPONSE)

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy", "--dry-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "demo.publisher@1.2.3" in combined
    assert "settings.json could not be read" in combined


def test_dry_run_rejects_watch_combination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy", "--watch", "--dry-run"])
    assert result.exit_code == 2
    assert "--dry-run cannot be combined with --watch" in strip_ansi(result.stderr)


def test_user_settings_path_code_on_macos(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    path = user_settings_path(EditorKind.CODE)
    assert path.name == "settings.json"
    assert "Code" in str(path)
    assert "User" in str(path)


def _point_settings_at(monkeypatch, settings_path: Path) -> None:
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: settings_path,
    )


def test_current_extensions_allowed_keeps_non_list_valued_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{"extensions.allowed": {"github.copilot": true, "demo.x": ["1.0.0"], "demo.s": "1"}}',
        encoding="utf-8",
    )
    _point_settings_at(monkeypatch, settings_path)
    current = _current_extensions_allowed(EditorKind.CODE)
    assert current is not None
    assert set(current) == {"github.copilot", "demo.x", "demo.s"}


def test_current_extensions_allowed_returns_empty_for_non_dict_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"extensions.allowed": "banana"}', encoding="utf-8")
    _point_settings_at(monkeypatch, settings_path)
    assert _current_extensions_allowed(EditorKind.CODE) == {}


def test_current_extensions_allowed_returns_empty_for_missing_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _point_settings_at(monkeypatch, tmp_path / "missing.json")
    assert _current_extensions_allowed(EditorKind.CODE) == {}


def test_current_extensions_allowed_raises_when_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def permission_denied(_settings_path: Path) -> dict[str, object]:
        raise PermissionError("settings.json unreadable")

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.read_settings_object",
        permission_denied,
    )
    _point_settings_at(monkeypatch, tmp_path / "settings.json")
    with pytest.raises(SettingsJsonError, match="could not be read"):
        _current_extensions_allowed(EditorKind.CODE)


def test_current_extensions_allowed_raises_on_malformed_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{bad", encoding="utf-8")
    _point_settings_at(monkeypatch, settings_path)
    with pytest.raises(SettingsJsonError):
        _current_extensions_allowed(EditorKind.CODE)


def test_current_extensions_allowed_raises_on_missing_separator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Dry-run must agree with write mode: a settings.json with a missing separator
    comma (no comments involved) is written past by no code path -- read mode must
    reject it too, or --dry-run would preview a file write mode then fails on."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{\n  "foo": 1\n  "bar": 2\n}\n', encoding="utf-8")
    _point_settings_at(monkeypatch, settings_path)
    with pytest.raises(SettingsJsonError, match="expected ','"):
        _current_extensions_allowed(EditorKind.CODE)


def test_sync_policy_writes_publisher_true_allow(tmp_path: Path, monkeypatch) -> None:
    """#425: the gate policy payload can carry a trusted-publisher ``"publisher": true`` entry
    alongside version-list pins; sync-policy must parse and write it, not fail validation."""
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", "gate_secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    editor_settings = tmp_path / "editor" / "settings.json"
    editor_settings.parent.mkdir(parents=True)
    editor_settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.user_settings_path",
        lambda _editor: editor_settings,
    )

    def fake_inventory(editor, *, timeout, cwd):
        return [
            VscodeInventoryEntry(
                extension_id="anysphere.cursor-retrieval", current_version="1.4.0"
            ),
            VscodeInventoryEntry(extension_id="demo.publisher", current_version="1.2.3"),
        ]

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_sync_policy_cli.collect_installed_extensions",
        fake_inventory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "extensions.allowed": {
                    "anysphere": True,
                    "demo.publisher": ["1.2.3", "1.3.0"],
                },
                "generated_at": "2026-07-09T12:00:00+00:00",
            },
        )

    monkeypatch.setattr(http_mod, "build_api_client", _wrap_api_client(handler))

    runner = CliRunner()
    result = runner.invoke(main_module.app, ["vscode", "sync-policy"])
    assert result.exit_code == 0, result.stdout + result.stderr
    on_disk = editor_settings.read_text(encoding="utf-8")
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in on_disk
    written = parse_jsonc(on_disk)
    assert isinstance(written, dict)
    assert written["extensions.allowed"] == {
        "anysphere": True,
        "demo.publisher": ["1.2.3", "1.3.0"],
    }

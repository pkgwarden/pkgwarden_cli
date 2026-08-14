from pathlib import Path

import pytest

from pkgwarden_cli import process_runner as runner_mod
from pkgwarden_cli.vscode_editor import EditorKind
from pkgwarden_cli.vscode_inventory import (
    InventoryCollectionError,
    collect_installed_extensions,
    parse_inventory_line,
    parse_inventory_output,
)


def test_parse_inventory_line_with_version() -> None:
    entry = parse_inventory_line("ms-python.python@2024.12.0")
    assert entry is not None
    assert entry.extension_id == "ms-python.python"
    assert entry.current_version == "2024.12.0"


def test_parse_inventory_line_normalizes_extension_id_case() -> None:
    entry = parse_inventory_line("MS-Python.Python@1.0.0")
    assert entry is not None
    assert entry.extension_id == "ms-python.python"


def test_parse_inventory_line_skips_blank_and_versionless() -> None:
    assert parse_inventory_line("") is None
    assert parse_inventory_line("   ") is None
    assert parse_inventory_line("ms-python.python") is None


def test_parse_inventory_output_collects_multiple_entries() -> None:
    text = "\n".join(
        [
            "ms-python.python@2024.12.0",
            "",
            "ms-python.vscode-pylance@2024.11.1",
            "bad-line-without-version",
        ]
    )
    entries = parse_inventory_output(text)
    assert len(entries) == 2
    assert entries[0].extension_id == "ms-python.python"
    assert entries[1].current_version == "2024.11.1"


def test_collect_installed_extensions_invokes_editor_binary(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(
            returncode=0,
            stdout="demo.publisher@1.2.3\n",
            stderr="",
        )

    monkeypatch.setattr("pkgwarden_cli.vscode_inventory.run_process", fake_run)
    entries = collect_installed_extensions(EditorKind.CURSOR, timeout=30.0)
    assert calls == [["cursor", "--list-extensions", "--show-versions"]]
    assert len(entries) == 1
    assert entries[0].extension_id == "demo.publisher"
    assert entries[0].current_version == "1.2.3"


def test_collect_installed_extensions_raises_on_editor_failure(monkeypatch) -> None:
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        return runner_mod.ProcessResult(returncode=1, stdout="", stderr="editor missing")

    monkeypatch.setattr("pkgwarden_cli.vscode_inventory.run_process", fake_run)
    with pytest.raises(InventoryCollectionError, match="editor missing"):
        collect_installed_extensions(EditorKind.CODE, timeout=30.0, cwd=Path("/tmp"))

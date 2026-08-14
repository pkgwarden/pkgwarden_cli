from pathlib import Path

from pydantic import BaseModel

from pkgwarden_cli.process_runner import run_process
from pkgwarden_cli.vscode_editor import EditorKind, editor_binary


class VscodeInventoryEntry(BaseModel):
    extension_id: str
    current_version: str


class InventoryCollectionError(RuntimeError):
    pass


def parse_inventory_line(line: str) -> VscodeInventoryEntry | None:
    stripped = line.strip()
    if not stripped or "@" not in stripped:
        return None
    extension_id, current_version = stripped.rsplit("@", 1)
    extension_id = extension_id.strip().lower()
    current_version = current_version.strip()
    if not extension_id or not current_version:
        return None
    return VscodeInventoryEntry(extension_id=extension_id, current_version=current_version)


def parse_inventory_output(text: str) -> list[VscodeInventoryEntry]:
    entries: list[VscodeInventoryEntry] = []
    for line in text.splitlines():
        parsed = parse_inventory_line(line)
        if parsed is not None:
            entries.append(parsed)
    return entries


def collect_installed_extensions(
    editor: EditorKind,
    *,
    timeout: float,
    cwd: Path | None = None,
) -> list[VscodeInventoryEntry]:
    result = run_process(
        [editor_binary(editor), "--list-extensions", "--show-versions"],
        cwd=cwd or Path.cwd(),
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise InventoryCollectionError(
            f"pw vscode sync-policy: {editor_binary(editor)} --list-extensions failed: {detail}",
        )
    return parse_inventory_output(result.stdout)

import os
import sys
from enum import StrEnum
from pathlib import Path


class EditorKind(StrEnum):
    CODE = "code"
    CURSOR = "cursor"
    WINDSURF = "windsurf"
    CODIUM = "codium"


_EDITOR_BINARY: dict[EditorKind, str] = {
    EditorKind.CODE: "code",
    EditorKind.CURSOR: "cursor",
    EditorKind.WINDSURF: "windsurf",
    EditorKind.CODIUM: "codium",
}

_EDITOR_DATA_DIR: dict[EditorKind, str] = {
    EditorKind.CODE: "Code",
    EditorKind.CURSOR: "Cursor",
    EditorKind.WINDSURF: "Windsurf",
    EditorKind.CODIUM: "VSCodium",
}


def parse_editor_kind(value: str) -> EditorKind:
    normalized = value.strip().lower()
    try:
        return EditorKind(normalized)
    except ValueError as error:
        supported = ", ".join(member.value for member in EditorKind)
        raise ValueError(f"Unknown editor {value!r}; expected one of {supported}") from error


def editor_binary(editor: EditorKind) -> str:
    return _EDITOR_BINARY[editor]


def user_settings_path(editor: EditorKind) -> Path:
    data_dir = _EDITOR_DATA_DIR[editor]
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / data_dir / "User"
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ValueError("APPDATA is not set; cannot locate editor settings on Windows")
        base = Path(appdata) / data_dir / "User"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        root = Path(config_home) if config_home else Path.home() / ".config"
        base = root / data_dir / "User"
    return base / "settings.json"

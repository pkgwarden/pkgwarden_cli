import os
import tomllib
from pathlib import Path
from typing import Literal

TokenType = Literal["user", "project", "tape", "mirror"]

SUPPORTED_TOKEN_TYPES: tuple[TokenType, ...] = ("user", "project", "tape", "mirror")


def credentials_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        base = Path(config_home)
    else:
        base = Path.home() / ".config"
    return base / "pkgwarden" / "credentials.toml"


def load_all() -> dict[str, dict[str, str]]:
    path = credentials_path()
    if not path.is_file():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for api_base, entries in raw.items():
        if not isinstance(api_base, str) or not isinstance(entries, dict):
            continue
        clean: dict[str, str] = {}
        for key, value in entries.items():
            if isinstance(key, str) and isinstance(value, str):
                clean[key] = value
        if clean:
            result[api_base] = clean
    return result


def load_token(api_base: str, token_type: TokenType) -> str | None:
    return load_all().get(api_base, {}).get(token_type)


def save_token(api_base: str, token_type: TokenType, token: str) -> None:
    data = load_all()
    data.setdefault(api_base, {})[token_type] = token
    _write(data)


def delete_token(api_base: str, token_type: TokenType) -> None:
    data = load_all()
    if api_base in data and token_type in data[api_base]:
        del data[api_base][token_type]
        if not data[api_base]:
            del data[api_base]
        _write(data)


def _write(data: dict[str, dict[str, str]]) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for api_base in sorted(data):
        lines.append(f"[{_escape(api_base)}]")
        for token_type in sorted(data[api_base]):
            token = data[api_base][token_type]
            lines.append(f'{token_type} = "{_escape_value(token)}"')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _escape(value: str) -> str:
    return f'"{_escape_value(value)}"'


def _escape_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

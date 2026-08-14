import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_STRUCTURAL = "{}[]:,"
_OPENERS = "{["
_CLOSERS = "}]"
_TokenKind = Literal["punct", "string", "literal"]


class SettingsJsonError(ValueError):
    pass


MANAGED_EXTENSIONS_ALLOWED_BANNER = (
    '// Managed by pkgwarden. To install a new extension: install the "pkgwarden" '
    'editor extension and run "pkgwarden: Install Extension…"'
)


@dataclass(frozen=True)
class _Token:
    kind: _TokenKind
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class _Member:
    key: str
    key_start: int
    value_start: int
    value_end: int


def _tokenize_jsonc(text: str) -> list[_Token]:
    """Tokenize JSONC (JSON with // and /* */ comments and trailing commas), the format
    VS Code and its forks use for settings.json. Comments and whitespace are dropped;
    strings are consumed whole so comment-like sequences inside them are never mistaken
    for comments."""
    tokens: list[_Token] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
        elif char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] != "\n":
                index += 1
        elif char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            if index + 1 >= length:
                raise SettingsJsonError("unterminated block comment in settings.json")
            index += 2
        elif char == '"':
            index = _append_string_token(text, index, tokens)
        elif char in _STRUCTURAL:
            tokens.append(_Token("punct", char, index, index + 1))
            index += 1
        else:
            start = index
            while index < length and text[index] not in ' \t\r\n"/' + _STRUCTURAL:
                index += 1
            tokens.append(_Token("literal", text[start:index], start, index))
    return tokens


def _append_string_token(text: str, index: int, tokens: list[_Token]) -> int:
    start = index
    index += 1
    length = len(text)
    while index < length:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            index += 1
            tokens.append(_Token("string", text[start:index], start, index))
            return index
        index += 1
    raise SettingsJsonError("unterminated string in settings.json")


def _decode_scalar(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SettingsJsonError(f"invalid value {raw!r} in settings.json") from error


def parse_jsonc(text: str) -> object | None:
    """Parse JSONC into a Python object; None when the document is empty or comments only.
    Raises SettingsJsonError on malformed content."""
    return _parse_jsonc(text, strict=False)


def _parse_jsonc(text: str, strict: bool) -> object | None:
    tokens = _tokenize_jsonc(text)
    if not tokens:
        return None
    value, index = _parse_value(tokens, 0, strict)
    if index != len(tokens):
        raise SettingsJsonError("trailing content in settings.json")
    return value


def _parse_value(tokens: list[_Token], index: int, strict: bool) -> tuple[object, int]:
    if index >= len(tokens):
        raise SettingsJsonError("unexpected end of settings.json")
    token = tokens[index]
    if token.kind in ("string", "literal"):
        return _decode_scalar(token.value), index + 1
    if token.value == "{":
        return _parse_object(tokens, index, strict)
    if token.value == "[":
        return _parse_array(tokens, index, strict)
    raise SettingsJsonError(f"unexpected token {token.value!r} in settings.json")


def _consume_separator(tokens: list[_Token], index: int, closer: str, strict: bool) -> int:
    """Advance past a member/element separator comma. In strict mode, a missing comma
    before the next member or element (as opposed to the closing bracket) is an error —
    this is how a JSONC-tolerant re-parse still fails closed on a corrupted separator.
    Truncated input (index at end-of-tokens) is left to the caller's own "unterminated"
    check rather than reported here as a missing comma."""
    if index < len(tokens) and tokens[index].value == ",":
        return index + 1
    if strict and index < len(tokens) and tokens[index].value != closer:
        raise SettingsJsonError("expected ',' before next entry in settings.json")
    return index


def _parse_object(tokens: list[_Token], index: int, strict: bool) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {}
    index += 1
    while True:
        if index >= len(tokens):
            raise SettingsJsonError("unterminated object in settings.json")
        token = tokens[index]
        if token.value == "}":
            return result, index + 1
        if token.kind != "string":
            raise SettingsJsonError("expected property name in settings.json")
        key = _decode_scalar(token.value)
        index += 1
        if index >= len(tokens) or tokens[index].value != ":":
            raise SettingsJsonError("expected ':' in settings.json")
        value, index = _parse_value(tokens, index + 1, strict)
        result[str(key)] = value
        index = _consume_separator(tokens, index, "}", strict)


def _parse_array(tokens: list[_Token], index: int, strict: bool) -> tuple[list[object], int]:
    result: list[object] = []
    index += 1
    while True:
        if index >= len(tokens):
            raise SettingsJsonError("unterminated array in settings.json")
        if tokens[index].value == "]":
            return result, index + 1
        value, index = _parse_value(tokens, index, strict)
        result.append(value)
        index = _consume_separator(tokens, index, "]", strict)


def read_settings_object(settings_path: Path) -> dict[str, object]:
    """Reads with the same separator-strict JSONC parsing apply_extensions_allowed uses to
    validate its own output, so a preview (e.g. --dry-run) agrees with what a write would
    do: a pre-existing missing separator comma fails closed here too, not just on write."""
    if not settings_path.is_file():
        return {}
    try:
        text = settings_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise SettingsJsonError(f"settings.json at {settings_path} is not valid UTF-8") from error
    try:
        parsed = _parse_jsonc(text, strict=True)
    except SettingsJsonError as error:
        raise SettingsJsonError(f"Malformed settings.json at {settings_path}: {error}") from error
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise SettingsJsonError(f"settings.json at {settings_path} must be a JSON object")
    return parsed


def _skip_value(tokens: list[_Token], index: int) -> int:
    token = tokens[index]
    if token.kind != "punct" or token.value not in _OPENERS:
        return index + 1
    depth = 0
    while index < len(tokens):
        current = tokens[index]
        if current.kind == "punct" and current.value in _OPENERS:
            depth += 1
        elif current.kind == "punct" and current.value in _CLOSERS:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise SettingsJsonError("unbalanced brackets in settings.json")


def _root_members(tokens: list[_Token]) -> list[_Member]:
    members: list[_Member] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.value == "}":
            return members
        if token.kind != "string":
            raise SettingsJsonError("expected property name in settings.json")
        key = str(_decode_scalar(token.value))
        key_start = token.start
        index += 1
        if index >= len(tokens) or tokens[index].value != ":":
            raise SettingsJsonError("expected ':' in settings.json")
        index += 1
        if index >= len(tokens):
            raise SettingsJsonError("expected value in settings.json")
        value_start = tokens[index].start
        end_index = _skip_value(tokens, index)
        members.append(_Member(key, key_start, value_start, tokens[end_index - 1].end))
        index = end_index
        if index < len(tokens) and tokens[index].value == ",":
            index += 1
    raise SettingsJsonError("unterminated object in settings.json")


def _detect_indent_unit(text: str) -> str:
    match = re.search(r"\n([ \t]+)\S", text)
    return match.group(1) if match else "    "


def _leading_whitespace(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    prefix = text[line_start:offset]
    return prefix if prefix.strip() == "" else ""


def _render_value(pin_map: Mapping[str, list[str] | bool], indent_unit: str) -> str:
    body = json.dumps(dict(pin_map), indent=indent_unit)
    lines = body.split("\n")
    if len(lines) == 1:
        return body
    return lines[0] + "".join(f"\n{indent_unit}{line}" for line in lines[1:])


def _assert_applied_pins(updated: str, pin_map: Mapping[str, list[str] | bool]) -> None:
    """Re-parse the written text with a JSONC-tolerant but separator-strict parser. The
    comma-placement fix above already keeps this insertion's own output well-formed; this
    is forward-looking insurance against future writer bugs and pre-existing corruption
    elsewhere in the file, not a currently-live gap it is closing."""
    parsed = _parse_jsonc(updated, strict=True)
    if not isinstance(parsed, dict) or parsed.get("extensions.allowed") != dict(pin_map):
        raise SettingsJsonError("failed to apply extensions.allowed surgically")


def _is_managed_banner_comment_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("// Managed by pkgwarden")


def _is_current_managed_banner(line: str) -> bool:
    return line.strip() == MANAGED_EXTENSIONS_ALLOWED_BANNER.strip()


def _is_legacy_managed_banner_continuation(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("//") and "pw vscode install" in stripped


def _strip_managed_banner_block(lines: list[str]) -> tuple[list[str], bool]:
    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    index = end
    while index > 0:
        stripped = lines[index - 1].strip()
        if not stripped:
            index -= 1
            continue
        if stripped.startswith("//"):
            index -= 1
            continue
        break
    block = lines[index:end]
    has_current = any(_is_current_managed_banner(line) for line in block)
    has_legacy_managed = any(
        _is_managed_banner_comment_line(line) and not _is_current_managed_banner(line)
        for line in block
    )
    if has_current and not has_legacy_managed:
        return lines, True
    if not has_current and not has_legacy_managed:
        return lines, False
    kept_block = [
        line
        for line in block
        if not (_is_managed_banner_comment_line(line) and not _is_current_managed_banner(line))
        and not _is_legacy_managed_banner_continuation(line)
    ]
    return lines[:index] + kept_block, False


def ensure_managed_banner_above_extensions_allowed(text: str) -> str:
    """Insert the pkgwarden managed banner directly above extensions.allowed."""
    tokens = _tokenize_jsonc(text)
    if not tokens or tokens[0].kind != "punct" or tokens[0].value != "{":
        return text
    members = _root_members(tokens)
    allowed_members = [member for member in members if member.key == "extensions.allowed"]
    if len(allowed_members) != 1:
        return text
    key_start = allowed_members[0].key_start
    prefix = text[:key_start].rstrip("\n")
    lines, already_current = _strip_managed_banner_block(prefix.split("\n") if prefix else [])
    if already_current:
        return text
    while lines and not lines[-1].strip():
        lines.pop()
    indent = _leading_whitespace(text, key_start) or _detect_indent_unit(text)
    banner_line = f"{indent}{MANAGED_EXTENSIONS_ALLOWED_BANNER}"
    if lines:
        rebuilt_prefix = "\n".join(lines) + f"\n{banner_line}\n"
    else:
        open_brace_end = tokens[0].end
        between = text[tokens[0].end : key_start]
        rebuilt_prefix = text[:open_brace_end] + between + banner_line + "\n"
        return rebuilt_prefix + text[key_start:]
    return rebuilt_prefix + indent + text[key_start:]


def apply_extensions_allowed(text: str, pin_map: Mapping[str, list[str] | bool]) -> str:
    """Surgically set the top-level "extensions.allowed" property.

    Preserves other top-level keys and comments outside the replaced value.
    New keys are appended before the closing brace. Duplicate top-level
    "extensions.allowed" keys fail closed (VS Code last-wins would otherwise
    leave a stale pin map after updating only the first occurrence).
    """
    tokens = _tokenize_jsonc(text)
    if not tokens:
        if text.strip():
            raise SettingsJsonError("settings.json has comments but no JSON object")
        indent_unit = "    "
        updated = (
            f'{{\n{indent_unit}"extensions.allowed": {_render_value(pin_map, indent_unit)}\n}}\n'
        )
        _assert_applied_pins(updated, pin_map)
        return updated
    if tokens[0].kind != "punct" or tokens[0].value != "{":
        raise SettingsJsonError("settings.json root must be a JSON object")
    if tokens[-1].kind != "punct" or tokens[-1].value != "}":
        raise SettingsJsonError("unterminated object in settings.json")
    members = _root_members(tokens)
    indent_unit = _detect_indent_unit(text)
    allowed_members = [member for member in members if member.key == "extensions.allowed"]
    if len(allowed_members) > 1:
        raise SettingsJsonError('duplicate top-level "extensions.allowed" key in settings.json')
    if len(allowed_members) == 1:
        existing = allowed_members[0]
        indent = _leading_whitespace(text, existing.key_start) or indent_unit
        rendered = _render_value(pin_map, indent)
        updated = text[: existing.value_start] + rendered + text[existing.value_end :]
        _assert_applied_pins(updated, pin_map)
        return updated
    close_start = tokens[-1].start
    if members:
        indent = _leading_whitespace(text, members[0].key_start) or indent_unit
        last = members[-1]
        needs_comma = not any(
            token.kind == "punct"
            and token.value == ","
            and last.value_end <= token.start < close_start
            for token in tokens
        )
        # Insert the separator comma right after the last member's value, not after
        # whatever text (possibly a trailing comment) precedes the closing brace —
        # otherwise the comma lands inside the comment and the file is invalid JSONC.
        comma = "," if needs_comma else ""
        trailer = text[last.value_end : close_start].rstrip()
        rendered = _render_value(pin_map, indent)
        insertion = f'\n{indent}"extensions.allowed": {rendered}\n'
        updated = text[: last.value_end] + comma + trailer + insertion + text[close_start:]
        _assert_applied_pins(updated, pin_map)
        return updated
    rendered = _render_value(pin_map, indent_unit)
    insertion = f'\n{indent_unit}"extensions.allowed": {rendered}\n'
    updated = text[: tokens[0].start + 1] + insertion + text[tokens[0].start + 1 :]
    _assert_applied_pins(updated, pin_map)
    return updated


def write_extensions_allowed(settings_path: Path, pin_map: Mapping[str, list[str] | bool]) -> None:
    text = ""
    if settings_path.is_file():
        try:
            text = settings_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise SettingsJsonError(
                f"settings.json at {settings_path} is not valid UTF-8"
            ) from error
        except OSError as error:
            raise SettingsJsonError(
                f"settings.json at {settings_path} could not be read: {error}",
            ) from error
    try:
        updated = ensure_managed_banner_above_extensions_allowed(
            apply_extensions_allowed(text, pin_map),
        )
    except SettingsJsonError as error:
        raise SettingsJsonError(f"Malformed settings.json at {settings_path}: {error}") from error
    _atomic_write_text(settings_path, updated)


def _atomic_write_text(settings_path: Path, text: str) -> None:
    temp_path = settings_path.with_name(f"{settings_path.name}.tmp.{os.getpid()}")
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if settings_path.is_file():
            backup_path = settings_path.with_suffix(".json.pkgwarden-backup")
            shutil.copy2(settings_path, backup_path)
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, settings_path)
    except OSError as error:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise SettingsJsonError(
            f"could not write settings.json at {settings_path}: {error}",
        ) from error

import json
from pathlib import Path

import pytest

from pkgwarden_cli.vscode_settings import (
    MANAGED_EXTENSIONS_ALLOWED_BANNER,
    SettingsJsonError,
    _assert_applied_pins,
    apply_extensions_allowed,
    ensure_managed_banner_above_extensions_allowed,
    parse_jsonc,
    read_settings_object,
    write_extensions_allowed,
)


def test_parse_jsonc_plain_object() -> None:
    assert parse_jsonc('{"a": 1}') == {"a": 1}


def test_parse_jsonc_line_comment() -> None:
    text = '{\n  "a": 1 // trailing\n  , "b": 2\n}'
    assert parse_jsonc(text) == {"a": 1, "b": 2}


def test_parse_jsonc_block_comment() -> None:
    assert parse_jsonc('{ /* hi */ "a": 1 }') == {"a": 1}


def test_parse_jsonc_trailing_comma_object_and_array() -> None:
    assert parse_jsonc('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}


def test_parse_jsonc_double_slash_inside_string_is_literal() -> None:
    assert parse_jsonc('{"url": "https://example/y"}') == {"url": "https://example/y"}


def test_parse_jsonc_comment_only_returns_none() -> None:
    assert parse_jsonc("// nothing\n") is None


def test_parse_jsonc_malformed_raises() -> None:
    with pytest.raises(SettingsJsonError, match="settings.json"):
        parse_jsonc("{bad")


def test_parse_jsonc_trailing_content_raises() -> None:
    with pytest.raises(SettingsJsonError, match="trailing content"):
        parse_jsonc('{"a": 1} true')


def test_parse_jsonc_unterminated_block_comment_raises() -> None:
    with pytest.raises(SettingsJsonError, match="unterminated block comment"):
        parse_jsonc('{"a": 1 /* oops')


def test_read_settings_object_reads_jsonc_with_comments_and_trailing_comma(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{\n  "editor.fontSize": 14, // size\n  "a.b": ["1.0.0"],\n}\n',
        encoding="utf-8",
    )
    assert read_settings_object(settings_path) == {"editor.fontSize": 14, "a.b": ["1.0.0"]}


def test_read_settings_object_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_settings_object(tmp_path / "missing.json") == {}


def test_read_settings_object_empty_file_returns_empty(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("  \n", encoding="utf-8")
    assert read_settings_object(settings_path) == {}


def test_read_settings_object_comment_only_returns_empty(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("// just a note\n", encoding="utf-8")
    assert read_settings_object(settings_path) == {}


def test_read_settings_object_malformed_raises_clear_error(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="Malformed settings.json"):
        read_settings_object(settings_path)


def test_read_settings_object_non_utf8_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_bytes(b'\xff\xfe{\x00"a\x00"\x00}')
    with pytest.raises(SettingsJsonError, match="not valid UTF-8"):
        read_settings_object(settings_path)


def test_read_settings_object_non_object_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="must be a JSON object"):
        read_settings_object(settings_path)


def test_apply_inserts_key_after_existing_members_preserving_comments() -> None:
    text = '{\n  // top comment\n  "editor.fontSize": 14,\n  "git.autofetch": true // inline\n}\n'
    result = apply_extensions_allowed(text, {"demo.ext": ["1.0.0"]})
    assert "// top comment" in result
    assert "// inline" in result
    assert result.index('"editor.fontSize"') < result.index('"extensions.allowed"')
    parsed = parse_jsonc(result)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"demo.ext": ["1.0.0"]}
    assert parsed["editor.fontSize"] == 14
    assert parsed["git.autofetch"] is True


def test_apply_replaces_existing_key_value_preserving_comments() -> None:
    text = (
        "{\n"
        '  "extensions.allowed": {\n'
        '    "old.ext": ["0.1.0"]\n'
        "  },\n"
        '  "editor.fontSize": 14 // keep\n'
        "}\n"
    )
    result = apply_extensions_allowed(text, {"new.ext": ["2.0.0", "2.1.0"]})
    assert "// keep" in result
    assert "old.ext" not in result
    parsed = parse_jsonc(result)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"new.ext": ["2.0.0", "2.1.0"]}
    assert parsed["editor.fontSize"] == 14


def test_apply_preserves_double_slash_inside_string_value() -> None:
    text = '{\n  "r.rterm": "https://example/bin"\n}\n'
    result = apply_extensions_allowed(text, {"a.b": ["1.0.0"]})
    assert "https://example/bin" in result
    parsed = parse_jsonc(result)
    assert isinstance(parsed, dict)
    assert parsed["r.rterm"] == "https://example/bin"


def test_apply_empty_object_creates_key() -> None:
    result = apply_extensions_allowed("{}", {"a.b": ["1.0.0"]})
    assert parse_jsonc(result) == {"extensions.allowed": {"a.b": ["1.0.0"]}}


def test_apply_empty_text_creates_document() -> None:
    result = apply_extensions_allowed("", {"a.b": ["1.0.0"]})
    assert parse_jsonc(result) == {"extensions.allowed": {"a.b": ["1.0.0"]}}


def test_apply_comment_only_raises() -> None:
    with pytest.raises(SettingsJsonError, match="no JSON object"):
        apply_extensions_allowed("// team notes\n", {"a.b": ["1.0.0"]})


def test_apply_duplicate_extensions_allowed_raises() -> None:
    text = (
        "{\n"
        '  "extensions.allowed": {"old.ext": ["1.0.0"]},\n'
        '  "editor.fontSize": 14,\n'
        '  "extensions.allowed": {"stale.ext": ["0.9.0"]}\n'
        "}\n"
    )
    with pytest.raises(SettingsJsonError, match="duplicate"):
        apply_extensions_allowed(text, {"new.ext": ["2.0.0"]})


def test_apply_preserves_pin_map_key_order() -> None:
    pin_map = {"z.ext": ["1.0.0"], "a.ext": ["2.0.0"]}
    result = apply_extensions_allowed("{}", pin_map)
    assert result.index('"z.ext"') < result.index('"a.ext"')
    assert parse_jsonc(result) == {"extensions.allowed": pin_map}


def test_apply_uses_two_space_indent_detected_from_file() -> None:
    text = '{\n  "editor.fontSize": 14\n}\n'
    result = apply_extensions_allowed(text, {"a.b": ["1.0.0"]})
    assert '\n  "extensions.allowed": {' in result


def test_apply_malformed_raises() -> None:
    with pytest.raises(SettingsJsonError, match="unterminated object|invalid value"):
        apply_extensions_allowed("{bad", {"a.b": ["1.0.0"]})


def test_parse_jsonc_unterminated_string_raises() -> None:
    with pytest.raises(SettingsJsonError, match="unterminated string"):
        parse_jsonc('{"a": "oops')


def test_write_creates_backup_and_preserves_comments(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    original = '{\n  // hi\n  "editor.fontSize": 12\n}\n'
    settings_path.write_text(original, encoding="utf-8")
    write_extensions_allowed(settings_path, {"x.y": ["1.0.0"]})
    on_disk = settings_path.read_text(encoding="utf-8")
    assert "// hi" in on_disk
    parsed = parse_jsonc(on_disk)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"x.y": ["1.0.0"]}
    assert parsed["editor.fontSize"] == 12
    backup_path = settings_path.with_suffix(".json.pkgwarden-backup")
    assert backup_path.read_text(encoding="utf-8") == original


def test_write_without_existing_file_skips_backup(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    write_extensions_allowed(settings_path, {})
    assert parse_jsonc(settings_path.read_text(encoding="utf-8")) == {"extensions.allowed": {}}
    assert not settings_path.with_suffix(".json.pkgwarden-backup").exists()


def test_apply_non_object_root_raises() -> None:
    with pytest.raises(SettingsJsonError, match="root must be a JSON object"):
        apply_extensions_allowed("[1, 2]", {"a.b": ["1.0.0"]})


def test_write_malformed_existing_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{bad", encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="Malformed settings.json"):
        write_extensions_allowed(settings_path, {"x.y": ["1.0.0"]})


def test_write_comment_only_existing_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("// notes only\n", encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="no JSON object"):
        write_extensions_allowed(settings_path, {"x.y": ["1.0.0"]})


def test_write_non_utf8_existing_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_bytes(b"\xff\xfe{\x00}")
    with pytest.raises(SettingsJsonError, match="not valid UTF-8"):
        write_extensions_allowed(settings_path, {"x.y": ["1.0.0"]})


def test_write_permission_denied_raises_settings_json_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"editor.fontSize": 12}\n', encoding="utf-8")

    def refuse_replace(_source: Path | str, _destination: Path | str) -> None:
        raise PermissionError("refused")

    monkeypatch.setattr(
        "pkgwarden_cli.vscode_settings.os.replace",
        refuse_replace,
    )
    with pytest.raises(SettingsJsonError, match="could not write"):
        write_extensions_allowed(settings_path, {"x.y": ["1.0.0"]})


def test_apply_inserts_comma_after_last_value_not_inside_trailing_comment() -> None:
    text = '{\n  "breadcrumbs.enabled": false\n  // "git.terminalAuthentication": false,\n}\n'
    result = apply_extensions_allowed(text, {"demo.ext": ["1.0.0"]})
    assert ",," not in result
    assert '"breadcrumbs.enabled": false,' in result
    assert result.index('"breadcrumbs.enabled": false,') < result.index('"extensions.allowed"')
    without_comments = "\n".join(
        line for line in result.splitlines() if not line.strip().startswith("//")
    )
    assert json.loads(without_comments) == {
        "breadcrumbs.enabled": False,
        "extensions.allowed": {"demo.ext": ["1.0.0"]},
    }


def test_apply_does_not_double_comma_when_trailing_comment_already_ends_with_comma() -> None:
    text = '{\n  "editor.fontSize": 14\n  // "old.setting": true,\n}\n'
    result = apply_extensions_allowed(text, {"a.b": ["1.0.0"]})
    assert ",," not in result
    assert '"editor.fontSize": 14,' in result


def test_apply_inserts_comma_before_trailing_block_comment() -> None:
    text = '{\n  "editor.fontSize": 14\n  /* legacy setting */\n}\n'
    result = apply_extensions_allowed(text, {"a.b": ["1.0.0"]})
    assert '"editor.fontSize": 14,' in result
    assert "/* legacy setting */" in result
    parsed = parse_jsonc(result)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"a.b": ["1.0.0"]}
    assert parsed["editor.fontSize"] == 14


def test_assert_applied_pins_raises_on_missing_separator_comma() -> None:
    pin_map = {"a.b": ["1.0.0"]}
    corrupt = '{\n  "editor.fontSize": 14\n  "extensions.allowed": {"a.b": ["1.0.0"]}\n}\n'
    with pytest.raises(SettingsJsonError):
        _assert_applied_pins(corrupt, pin_map)


def test_apply_raises_on_pre_existing_missing_separator_elsewhere() -> None:
    """A missing comma between two unrelated members (no comments involved) must fail
    closed through the real write path, not just when checked directly."""
    text = '{\n  "foo": 1\n  "bar": 2\n}\n'
    with pytest.raises(SettingsJsonError, match="expected ','"):
        apply_extensions_allowed(text, {"a.b": ["1.0.0"]})


def test_read_settings_object_raises_on_missing_separator(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{\n  "foo": 1\n  "bar": 2\n}\n', encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="Malformed settings.json"):
        read_settings_object(settings_path)


def test_read_settings_object_raises_on_missing_array_separator(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"arr": [1 2]}', encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="expected ','"):
        read_settings_object(settings_path)


def test_read_settings_object_raises_unterminated_on_truncated_array(tmp_path: Path) -> None:
    """Truncated input should report 'unterminated', not the unrelated separator error
    the strict comma check would otherwise raise first at end-of-input."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"arr": [1', encoding="utf-8")
    with pytest.raises(SettingsJsonError, match="unterminated array"):
        read_settings_object(settings_path)


def test_write_extensions_allowed_supports_publisher_true(tmp_path: Path) -> None:
    """#425: a trusted publisher is emitted as a bare ``"publisher": true`` (VS Code's native
    publisher-wide allow), mixed with normal per-extension version-pin lists."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"editor.fontSize": 14}', encoding="utf-8")
    write_extensions_allowed(settings_path, {"anysphere": True, "demo.pub": ["1.0.0"]})
    on_disk = settings_path.read_text(encoding="utf-8")
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in on_disk
    written = parse_jsonc(on_disk)
    assert isinstance(written, dict)
    assert written["extensions.allowed"] == {"anysphere": True, "demo.pub": ["1.0.0"]}
    assert written["editor.fontSize"] == 14


def test_apply_extensions_allowed_roundtrips_bool_value() -> None:
    updated = apply_extensions_allowed("{}", {"anysphere": True})
    assert '"anysphere": true' in updated
    _assert_applied_pins(updated, {"anysphere": True})


def test_managed_banner_on_create_path() -> None:
    updated = ensure_managed_banner_above_extensions_allowed(
        apply_extensions_allowed("{}", {"demo.ext": ["1.0.0"]}),
    )
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in updated
    assert updated.index(MANAGED_EXTENSIONS_ALLOWED_BANNER) < updated.index('"extensions.allowed"')


def test_managed_banner_on_replace_preserves_user_comments() -> None:
    text = (
        "{\n"
        "  // team note\n"
        '  "extensions.allowed": {"old.ext": ["0.1.0"]},\n'
        '  "editor.fontSize": 14\n'
        "}\n"
    )
    updated = ensure_managed_banner_above_extensions_allowed(
        apply_extensions_allowed(text, {"new.ext": ["2.0.0"]}),
    )
    assert "// team note" in updated
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in updated
    assert updated.index("// team note") < updated.index(MANAGED_EXTENSIONS_ALLOWED_BANNER)
    assert updated.index(MANAGED_EXTENSIONS_ALLOWED_BANNER) < updated.index('"extensions.allowed"')
    parsed = parse_jsonc(updated)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"new.ext": ["2.0.0"]}


def test_managed_banner_idempotent() -> None:
    once = ensure_managed_banner_above_extensions_allowed(
        apply_extensions_allowed("{}", {"a.b": ["1.0.0"]}),
    )
    twice = ensure_managed_banner_above_extensions_allowed(once)
    assert twice == once
    assert once.count(MANAGED_EXTENSIONS_ALLOWED_BANNER) == 1


def test_managed_banner_idempotent_preserves_user_comments() -> None:
    text = (
        "{\n"
        "  // team note\n"
        '  "extensions.allowed": {"old.ext": ["0.1.0"]},\n'
        '  "editor.fontSize": 14\n'
        "}\n"
    )
    once = ensure_managed_banner_above_extensions_allowed(
        apply_extensions_allowed(text, {"new.ext": ["2.0.0"]}),
    )
    twice = ensure_managed_banner_above_extensions_allowed(once)
    assert "// team note" in twice
    assert twice == once


def test_managed_banner_upgrades_legacy_two_line_banner() -> None:
    text = (
        "{\n"
        "// Managed by pkgwarden. To install a new extension:\n"
        "//   pw vscode install demo.ext\n"
        '  "extensions.allowed": {"demo.ext": ["1.0.0"]}\n'
        "}\n"
    )
    updated = ensure_managed_banner_above_extensions_allowed(text)
    assert "pw vscode install" not in updated
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in updated
    assert updated.count(MANAGED_EXTENSIONS_ALLOWED_BANNER) == 1


def test_write_extensions_allowed_writes_managed_banner(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    write_extensions_allowed(settings_path, {"demo.ext": ["1.0.0"]})
    on_disk = settings_path.read_text(encoding="utf-8")
    assert MANAGED_EXTENSIONS_ALLOWED_BANNER in on_disk
    parsed = parse_jsonc(on_disk)
    assert isinstance(parsed, dict)
    assert parsed["extensions.allowed"] == {"demo.ext": ["1.0.0"]}

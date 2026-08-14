import pytest
import typer

from pkgwarden_cli.spec import ParsedSpec, native_spec, parse_package_argument


def test_bare_name() -> None:
    parsed = parse_package_argument("flask", None)
    assert parsed == ParsedSpec(name="flask", extras=[], version=None, exact=False)


def test_inline_double_equals_pin() -> None:
    parsed = parse_package_argument("flask==3.1.2", None)
    assert parsed.name == "flask"
    assert parsed.version == "3.1.2"
    assert parsed.exact is True


def test_inline_at_pin() -> None:
    parsed = parse_package_argument("flask@3.1.2", None)
    assert parsed.version == "3.1.2"
    assert parsed.exact is True


def test_extras_with_pin() -> None:
    parsed = parse_package_argument("flask[async,dotenv]==3.1.2", None)
    assert parsed.name == "flask"
    assert parsed.extras == ["async", "dotenv"]
    assert parsed.version == "3.1.2"


def test_range_spec_is_not_exact() -> None:
    parsed = parse_package_argument("flask>=3,<4", None)
    assert parsed.name == "flask"
    assert parsed.version == ">=3,<4"
    assert parsed.exact is False


def test_version_option_merges_with_bare_name() -> None:
    parsed = parse_package_argument("flask", "3.1.2")
    assert parsed.version == "3.1.2"
    assert parsed.exact is True


def test_version_option_conflicting_with_inline_pin_errors() -> None:
    with pytest.raises(typer.BadParameter, match="both"):
        parse_package_argument("flask==3.1.2", "3.1.3")


def test_version_option_matching_inline_pin_ok() -> None:
    parsed = parse_package_argument("flask==3.1.2", "3.1.2")
    assert parsed.version == "3.1.2"


def test_version_option_with_range_operator_errors() -> None:
    with pytest.raises(typer.BadParameter, match="exact"):
        parse_package_argument("metaghost", ">=0.1.0")


def test_empty_name_errors() -> None:
    with pytest.raises(typer.BadParameter, match="name"):
        parse_package_argument("==1.2.3", None)
    with pytest.raises(typer.BadParameter, match="name"):
        parse_package_argument("", None)


def test_dangling_equals_errors() -> None:
    with pytest.raises(typer.BadParameter, match="version"):
        parse_package_argument("flask==", None)


def test_native_spec_python_manager() -> None:
    parsed = parse_package_argument("flask[async]==3.1.2", None)
    assert native_spec("uv", parsed) == "flask[async]==3.1.2"


def test_native_spec_js_manager_uses_at() -> None:
    parsed = parse_package_argument("chalk==5.3.0", None)
    assert native_spec("npm", parsed) == "chalk@5.3.0"


def test_native_spec_range_passthrough() -> None:
    parsed = parse_package_argument("flask>=3,<4", None)
    assert native_spec("uv", parsed) == "flask>=3,<4"


def test_native_spec_bare_name() -> None:
    parsed = parse_package_argument("flask", None)
    assert native_spec("uv", parsed) == "flask"


def test_scoped_npm_package_with_at_pin() -> None:
    parsed = parse_package_argument("@types/node@22.5.0", None)
    assert parsed.name == "@types/node"
    assert parsed.version == "22.5.0"
    assert native_spec("npm", parsed) == "@types/node@22.5.0"


def test_scoped_npm_package_bare() -> None:
    parsed = parse_package_argument("@tanstack/react-query", None)
    assert parsed.name == "@tanstack/react-query"
    assert parsed.version is None

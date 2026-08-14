"""Package-spec parsing shared by add/remove/why-blocked — accepts every uv-style form."""

import re

import typer
from pydantic import BaseModel

from pkgwarden_cli.config import PackageManager

_NAME_PATTERN = re.compile(r"^@?[A-Za-z0-9]([A-Za-z0-9._/-]*[A-Za-z0-9])?$")
_EXACT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!*-]*$")
_RANGE_OPERATORS = ("<", ">", "~=", "!=", ",")


class ParsedSpec(BaseModel):
    name: str
    extras: list[str]
    version: str | None
    exact: bool


def _split_inline(raw: str) -> tuple[str, str | None]:
    if "==" in raw:
        name, _, version = raw.partition("==")
        return name, version
    if "@" in raw[1:]:
        index = raw.rindex("@")
        return raw[:index], raw[index + 1 :]
    for operator in ("<=", ">=", "~=", "!=", "<", ">"):
        if operator in raw:
            index = raw.index(operator)
            return raw[:index], raw[index:]
    return raw, None


def _split_extras(name: str) -> tuple[str, list[str]]:
    match = re.fullmatch(r"(?P<name>[^\[\]]+)\[(?P<extras>[^\[\]]*)\]", name)
    if not match:
        return name, []
    extras = [part.strip() for part in match.group("extras").split(",") if part.strip()]
    return match.group("name"), extras


def _is_range(version: str) -> bool:
    return any(operator in version for operator in _RANGE_OPERATORS)


def parse_package_argument(raw: str, version_option: str | None) -> ParsedSpec:
    name_part, inline_version = _split_inline(raw.strip())
    name, extras = _split_extras(name_part.strip())
    if not name or not _NAME_PATTERN.fullmatch(name):
        raise typer.BadParameter(
            f"{raw!r} has no valid package name. Use name, name==version, or name@version."
        )
    if inline_version is not None and not inline_version:
        raise typer.BadParameter(f"{raw!r} is missing a version after the operator.")
    if version_option is not None:
        if _is_range(version_option) or not _EXACT_VERSION_PATTERN.fullmatch(version_option):
            raise typer.BadParameter(
                f"--version must be an exact version (got {version_option!r}). "
                f'For ranges, pass the spec inline: pw add "{name}{version_option}".'
            )
        if inline_version is not None and inline_version != version_option:
            raise typer.BadParameter(
                f"{raw!r} and --version {version_option} both pin a version; pass one."
            )
        return ParsedSpec(name=name, extras=extras, version=version_option, exact=True)
    if inline_version is None:
        return ParsedSpec(name=name, extras=extras, version=None, exact=False)
    return ParsedSpec(
        name=name, extras=extras, version=inline_version, exact=not _is_range(inline_version)
    )


def native_spec(manager: PackageManager, parsed: ParsedSpec) -> str:
    name = parsed.name
    if parsed.extras and manager in ("uv", "poetry", "pip"):
        name = f"{name}[{','.join(parsed.extras)}]"
    if parsed.version is None:
        return name
    if not parsed.exact:
        return f"{name}{parsed.version}"
    if manager in ("pnpm", "npm", "yarn"):
        return f"{name}@{parsed.version}"
    return f"{name}=={parsed.version}"

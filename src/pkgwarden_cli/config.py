import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pkgwarden_cli import credentials as credentials_store
from pkgwarden_cli.urls import normalize_api_base

CliMode = Literal["tape", "enterprise"]
PackageManager = Literal["uv", "poetry", "pip", "pnpm", "npm", "yarn"]

SUPPORTED_MODES: tuple[CliMode, ...] = ("tape", "enterprise")
SUPPORTED_PACKAGE_MANAGERS: tuple[PackageManager, ...] = (
    "uv",
    "poetry",
    "pip",
    "pnpm",
    "npm",
    "yarn",
)


class CliConfig(BaseModel):
    api_base: str
    mode: CliMode | None = None
    user_token: str | None = None
    project_token: str | None = None
    tape_token: str | None = None
    project_id: str | None = None
    package_manager: PackageManager | None = None
    mirror_token: str | None = Field(
        default=None,
        description="Token for PEP 503 Basic auth; defaults to project token when unset.",
    )


def _find_pkgwarden_toml(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / ".pkgwarden.toml"
        if candidate.is_file():
            return candidate
    return None


def _read_optional_string(data: dict[str, object], key: str, source: Path) -> str | None:
    raw = data.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} in {source} must be a string")
    return raw


def _validate_mode(value: str | None, *, source: str) -> CliMode | None:
    if value is None:
        return None
    if value not in SUPPORTED_MODES:
        raise ValueError(
            f"Invalid mode {value!r} in {source}; expected one of {', '.join(SUPPORTED_MODES)}",
        )
    return value  # type: ignore[return-value]


def _validate_package_manager(
    value: str | None,
    *,
    source: str,
) -> PackageManager | None:
    if value is None:
        return None
    if value not in SUPPORTED_PACKAGE_MANAGERS:
        raise ValueError(
            f"Invalid package_manager {value!r} in {source}; "
            f"expected one of {', '.join(SUPPORTED_PACKAGE_MANAGERS)}",
        )
    return value  # type: ignore[return-value]


def load_cli_config(
    cwd: Path | None = None,
    *,
    api_url_override: str | None = None,
    project_id_override: str | None = None,
) -> CliConfig:
    root = cwd or Path.cwd()
    toml_path = _find_pkgwarden_toml(root)
    file_api: str | None = None
    file_project_id: str | None = None
    file_mode: CliMode | None = None
    file_manager: PackageManager | None = None
    if toml_path:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid TOML root in {toml_path}")
        file_api = _read_optional_string(data, "api_url", toml_path)
        file_project_id = _read_optional_string(data, "project_id", toml_path)
        file_mode = _validate_mode(
            _read_optional_string(data, "mode", toml_path),
            source=str(toml_path),
        )
        file_manager = _validate_package_manager(
            _read_optional_string(data, "package_manager", toml_path),
            source=str(toml_path),
        )

    env_api = os.environ.get("PKGWARDEN_API_URL")
    raw_url = api_url_override or env_api or file_api
    if not raw_url:
        raise ValueError(
            "Set PKGWARDEN_API_URL, pass --api-url, or define api_url in .pkgwarden.toml",
        )

    project_id = os.environ.get("PKGWARDEN_PROJECT_ID") or file_project_id or None
    if project_id_override is not None:
        project_id = project_id_override
    env_mode = _validate_mode(os.environ.get("PKGWARDEN_MODE"), source="PKGWARDEN_MODE")
    env_manager = _validate_package_manager(
        os.environ.get("PKGWARDEN_PACKAGE_MANAGER"),
        source="PKGWARDEN_PACKAGE_MANAGER",
    )
    api_base = normalize_api_base(raw_url)
    user_token = os.environ.get("PKGWARDEN_USER_TOKEN") or credentials_store.load_token(
        api_base,
        "user",
    )
    project_token = os.environ.get("PKGWARDEN_PROJECT_TOKEN") or credentials_store.load_token(
        api_base,
        "project",
    )
    tape_token = os.environ.get("PKGWARDEN_TAPE_TOKEN") or credentials_store.load_token(
        api_base,
        "tape",
    )
    mirror_token = (
        os.environ.get("PKGWARDEN_MIRROR_TOKEN")
        or credentials_store.load_token(api_base, "mirror")
        or project_token
    )
    return CliConfig(
        api_base=api_base,
        mode=env_mode or file_mode,
        user_token=user_token,
        project_token=project_token,
        tape_token=tape_token,
        project_id=project_id,
        package_manager=env_manager or file_manager,
        mirror_token=mirror_token,
    )

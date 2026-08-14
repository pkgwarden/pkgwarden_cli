"""Discover defaults for ``pw init`` from .env, pyproject.toml, and .npmrc."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pkgwarden_cli.config import CliMode, PackageManager
from pkgwarden_cli.package_manager import detect_managers
from pkgwarden_cli.urls import normalize_api_base


def parse_dotenv_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def merged_env_for_init(cwd: Path) -> dict[str, str]:
    dotenv = parse_dotenv_file(cwd / ".env")
    merged = {**dotenv, **dict(os.environ)}
    return merged


def effective_project_token(env: dict[str, str]) -> str | None:
    for key in ("PKGWARDEN_PROJECT_TOKEN", "PKGWARDEN_PROJECT_API_TOKEN"):
        value = env.get(key, "").strip()
        if value:
            return value
    return None


def effective_gate_token(env: dict[str, str]) -> str | None:
    for key in (
        "PKGWARDEN_GATE_TOKEN",
        "PKGWARDEN_GATE_API_TOKEN",
    ):
        value = env.get(key, "").strip()
        if value:
            return value
    return None


def infer_mode_from_tokens(env: dict[str, str]) -> CliMode | None:
    if effective_project_token(env) is not None:
        return "enterprise"
    if effective_gate_token(env) is not None:
        return "gate"
    return None


def registry_url_to_api_base(url: str) -> str | None:
    stripped = url.strip().rstrip("/")
    if not stripped.startswith("https://") and not stripped.startswith("http://"):
        return None
    if stripped.endswith("/api/v1") or "/api/v1/" in stripped:
        return normalize_api_base(stripped)
    if stripped.endswith("/simple"):
        origin = stripped[: -len("/simple")].rstrip("/")
        if origin:
            return normalize_api_base(origin)
    return None


def discover_api_url_from_pyproject(cwd: Path) -> str | None:
    path = cwd / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    tool = data.get("tool") if isinstance(data, dict) else None
    if not isinstance(tool, dict):
        return None
    uv = tool.get("uv")
    if isinstance(uv, dict):
        indexes = uv.get("index")
        if isinstance(indexes, list):
            for item in indexes:
                if not isinstance(item, dict):
                    continue
                raw_url = item.get("url")
                if isinstance(raw_url, str):
                    converted = registry_url_to_api_base(raw_url)
                    if converted is not None:
                        return converted
    poetry = tool.get("poetry")
    if isinstance(poetry, dict):
        sources = poetry.get("source")
        if isinstance(sources, list):
            for item in sources:
                if not isinstance(item, dict):
                    continue
                raw_url = item.get("url")
                if isinstance(raw_url, str):
                    converted = registry_url_to_api_base(raw_url)
                    if converted is not None:
                        return converted
    return None


def discover_api_url_from_npmrc(cwd: Path) -> str | None:
    path = cwd / ".npmrc"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        segment = line.split("#")[0].strip()
        if not segment or "=" not in segment:
            continue
        key, _, value = segment.partition("=")
        if "registry" not in key.lower():
            continue
        candidate = value.strip().strip('"').strip("'")
        converted = registry_url_to_api_base(candidate)
        if converted is not None:
            return converted
    return None


def discover_api_url(cwd: Path, env: dict[str, str]) -> str | None:
    direct = env.get("PKGWARDEN_API_URL", "").strip()
    if direct:
        return normalize_api_base(direct)
    from_py = discover_api_url_from_pyproject(cwd)
    if from_py:
        return from_py
    from_npm = discover_api_url_from_npmrc(cwd)
    if from_npm:
        return from_npm
    return None


@dataclass
class InitDefaults:
    api_url: str | None
    mode: CliMode | None
    mode_source: str
    package_manager: PackageManager | None
    project_id: str | None
    notes: list[str] = field(default_factory=list)


def build_init_defaults(
    cwd: Path,
    env: dict[str, str],
    *,
    api_url_override: str | None,
    mode_override: CliMode | None,
    package_manager_override: PackageManager | None,
    project_id_override: str | None,
) -> InitDefaults:
    notes: list[str] = []
    api_url: str | None = None
    if api_url_override and api_url_override.strip():
        api_url = normalize_api_base(api_url_override.strip())
        notes.append("api_url from CLI flag")
    else:
        discovered = discover_api_url(cwd, env)
        if discovered:
            api_url = discovered
            notes.append("api_url from environment, .env, pyproject.toml, or .npmrc")

    mode: CliMode | None = None
    mode_source = "unset"
    if mode_override is not None:
        mode = mode_override
        mode_source = "CLI flag"
    else:
        inferred = infer_mode_from_tokens(env)
        if inferred is not None:
            mode = inferred
            mode_source = "project or gate token (or *_API_TOKEN alias) in environment / .env"
            notes.append("mode: enterprise with project token env; gate with gate token only only")

    manager: PackageManager | None = None
    if package_manager_override is not None:
        manager = package_manager_override
        notes.append("package_manager from CLI flag")
    else:
        detections = detect_managers(cwd)
        if detections:
            manager = detections[0].manager
            notes.append(f"package_manager from lockfile ({detections[0].lockfile})")

    project_id = None
    if project_id_override and project_id_override.strip():
        project_id = project_id_override.strip()
        notes.append("project_id from CLI flag")
    else:
        from_env = env.get("PKGWARDEN_PROJECT_ID", "").strip()
        if from_env:
            project_id = from_env
            notes.append("project_id from environment / .env")

    return InitDefaults(
        api_url=api_url,
        mode=mode,
        mode_source=mode_source,
        package_manager=manager,
        project_id=project_id,
        notes=notes,
    )

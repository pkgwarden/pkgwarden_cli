"""Credential injection for shelled package-manager processes.

pw holds a mirror token but the native manager resolves against the gated mirror
in its own process — without these env overrides every resolution 401s.
"""

import re
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import quote, urlsplit

from pkgwarden_cli.config import CliConfig, PackageManager
from pkgwarden_cli.http_client import mirror_basic_username
from pkgwarden_cli.urls import mirror_origin_from_api_base, simple_index_url


def _uv_index_names(pyproject: Path, mirror_origin: str) -> list[str]:
    if not pyproject.is_file():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    indexes = data.get("tool", {}).get("uv", {}).get("index", [])
    if not isinstance(indexes, list):
        return []
    names: list[str] = []
    for entry in indexes:
        if not isinstance(entry, dict):
            continue
        name, url = entry.get("name"), entry.get("url")
        if isinstance(name, str) and isinstance(url, str) and url.startswith(mirror_origin):
            names.append(name)
    return names


def _env_key_fragment(index_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", index_name).upper()


def npm_registry_base(api_base: str) -> str:
    return f"{mirror_origin_from_api_base(api_base)}/resolution/npm"


def _npm_auth_scope(registry_base: str) -> str:
    parsed = urlsplit(registry_base.rstrip("/") + "/")
    scope_path = (parsed.path or "").rstrip("/") + "/"
    return f"//{parsed.netloc}{scope_path}"


def npmrc_for_registry(registry_base: str, registry_auth_token: str) -> str:
    body = f"registry={registry_base}/\n"
    return body + f"{_npm_auth_scope(registry_base)}:_authToken={registry_auth_token}\n"


_NPMRC_TEMP_PREFIX = "pkgwarden-npmrc-"


def _write_temp_npmrc(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=_NPMRC_TEMP_PREFIX,
        suffix=".npmrc",
        delete=False,
    )
    with handle:
        handle.write(content)
    return Path(handle.name)


def cleanup_native_auth_env(env: dict[str, str]) -> None:
    userconfig = env.get("NPM_CONFIG_USERCONFIG")
    if not userconfig:
        return
    path = Path(userconfig)
    if path.name.startswith(_NPMRC_TEMP_PREFIX):
        path.unlink(missing_ok=True)


def _npm_family_auth_env(
    config: CliConfig, manager: PackageManager, username: str
) -> dict[str, str]:
    registry_base = npm_registry_base(config.api_base)
    npmrc_path = _write_temp_npmrc(npmrc_for_registry(registry_base, username))
    env = {"NPM_CONFIG_USERCONFIG": str(npmrc_path)}
    if manager == "yarn":
        env["YARN_NPM_REGISTRY_SERVER"] = registry_base
    return env


def native_auth_env(config: CliConfig, manager: PackageManager, cwd: Path) -> dict[str, str]:
    try:
        username = mirror_basic_username(config)
    except ValueError:
        return {}
    mirror_origin = mirror_origin_from_api_base(config.api_base)
    if manager == "uv":
        env: dict[str, str] = {}
        for name in _uv_index_names(cwd / "pyproject.toml", mirror_origin):
            fragment = _env_key_fragment(name)
            env[f"UV_INDEX_{fragment}_USERNAME"] = username
            env[f"UV_INDEX_{fragment}_PASSWORD"] = ""
        return env
    if manager == "pip":
        index_url = simple_index_url(config.api_base, config.mode)
        parts = urlsplit(index_url)
        credentialed_netloc = f"{quote(username, safe='')}@{parts.netloc}"
        return {"PIP_INDEX_URL": f"{parts.scheme}://{credentialed_netloc}{parts.path}"}
    if manager in ("npm", "pnpm", "yarn"):
        return _npm_family_auth_env(config, manager, username)
    return {}

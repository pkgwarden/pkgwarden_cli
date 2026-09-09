"""Credential injection for shelled package-manager processes.

pw holds a mirror token but the native manager resolves against the gated mirror
in its own process — without these env overrides every resolution 401s.
"""

import re
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote, urlsplit

from pydantic import BaseModel

from pkgwarden_cli.config import CliConfig, PackageManager
from pkgwarden_cli.http_client import mirror_basic_username
from pkgwarden_cli.urls import mirror_origin_from_api_base, simple_index_url


class PoetrySource(BaseModel):
    """One `[[tool.poetry.source]]` entry; `priority` absent means poetry's default (primary)."""

    name: str
    url: str
    priority: str | None


def url_targets_origin(url: str, origin: str) -> bool:
    """Whether `url` really lives at `origin`, matching host and path exactly, not by prefix.

    A bare `url.startswith(origin)` would accept `https://gate.example.com.attacker.test/`
    and `https://gate.example.com@attacker.test/`, so a crafted manifest would pass gate
    verification while the manager resolved elsewhere -- with our token in the Basic header.
    """
    target, expected = urlsplit(url), urlsplit(origin)
    if (target.scheme.lower(), target.netloc.lower()) != (
        expected.scheme.lower(),
        expected.netloc.lower(),
    ):
        return False
    base = expected.path.rstrip("/")
    return target.path == base or target.path.startswith(f"{base}/")


def _manifest_table(pyproject: Path, *keys: str) -> list[object]:
    if not pyproject.is_file():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    node: object = data
    for key in keys:
        if not isinstance(node, dict):
            return []
        node = node.get(key, {})
    return node if isinstance(node, list) else []


def _uv_index_names(pyproject: Path, mirror_origin: str) -> list[str]:
    names: list[str] = []
    for entry in _manifest_table(pyproject, "tool", "uv", "index"):
        if not isinstance(entry, dict):
            continue
        name, url = entry.get("name"), entry.get("url")
        if (
            isinstance(name, str)
            and isinstance(url, str)
            and url_targets_origin(url, mirror_origin)
        ):
            names.append(name)
    return names


def env_key_fragment(index_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", index_name).upper()


def poetry_sources(pyproject: Path) -> list[PoetrySource]:
    sources: list[PoetrySource] = []
    for entry in _manifest_table(pyproject, "tool", "poetry", "source"):
        if not isinstance(entry, dict):
            continue
        name, url, priority = entry.get("name"), entry.get("url"), entry.get("priority")
        if not (isinstance(name, str) and isinstance(url, str)):
            continue
        sources.append(
            PoetrySource(
                name=name, url=url, priority=priority if isinstance(priority, str) else None
            )
        )
    return sources


def poetry_gate_sources(pyproject: Path, mirror_origin: str) -> list[PoetrySource]:
    return [
        source
        for source in poetry_sources(pyproject)
        if url_targets_origin(source.url, mirror_origin)
    ]


def npm_registry_base(api_base: str) -> str:
    return f"{mirror_origin_from_api_base(api_base)}/resolution/npm"


def _npm_auth_scope(registry_base: str) -> str:
    parsed = urlsplit(registry_base.rstrip("/") + "/")
    scope_path = (parsed.path or "").rstrip("/") + "/"
    return f"//{parsed.netloc}{scope_path}"


NPM_CLIENT_RETRY_SETTINGS: tuple[tuple[str, str], ...] = (
    ("fetch-retries", "5"),
    ("fetch-retry-mintimeout", "2000"),
    ("fetch-retry-maxtimeout", "60000"),
)
"""Retry settings every npm-family client reads from the user config file, so an install queues
against the gate's per-token resolution ceiling instead of aborting on a 429. See walrus issue
#981: pnpm's default ``fetch-retries`` is 2 and uv's default is 3, so four cold jobs sharing one
token gave up long before the burst drained. Five retries backing off from 2 s to 60 s outlast a
burst the gate is shedding."""

NPM_CLIENT_CONCURRENCY_LIMIT = "8"
"""In-flight requests per job. Four concurrent jobs then present about 32 requests against a
production per-token share of 30, where pnpm's default of 16 presented about 64."""

NPM_CLIENT_CONCURRENCY_KEYS: dict[PackageManager, str] = {
    "npm": "maxsockets",
    "pnpm": "network-concurrency",
    "yarn": "network-concurrency",
}
"""Each client's own concurrency knob, written only for the managers actually configured: npm
does not know ``network-concurrency`` and warns "Unknown user config" on it (verified against npm
11.8.0), announcing that it will stop working in npm's next major, while pnpm ignores
``maxsockets`` (verified against pnpm 9.15.9 and 10.34.2)."""


def npm_client_pacing_settings(
    managers: Iterable[PackageManager],
) -> tuple[tuple[str, str], ...]:
    keys = sorted(
        {
            NPM_CLIENT_CONCURRENCY_KEYS[manager]
            for manager in managers
            if manager in NPM_CLIENT_CONCURRENCY_KEYS
        }
    )
    return tuple((key, NPM_CLIENT_CONCURRENCY_LIMIT) for key in keys) + NPM_CLIENT_RETRY_SETTINGS


def npmrc_for_registry(
    registry_base: str, registry_auth_token: str, managers: Iterable[PackageManager]
) -> str:
    body = f"registry={registry_base}/\n"
    body += f"{_npm_auth_scope(registry_base)}:_authToken={registry_auth_token}\n"
    return body + "".join(f"{key}={value}\n" for key, value in npm_client_pacing_settings(managers))


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
    npmrc_path = _write_temp_npmrc(npmrc_for_registry(registry_base, username, (manager,)))
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
            fragment = env_key_fragment(name)
            env[f"UV_INDEX_{fragment}_USERNAME"] = username
            env[f"UV_INDEX_{fragment}_PASSWORD"] = ""
        return env
    if manager == "poetry":
        env = {}
        for source in poetry_gate_sources(cwd / "pyproject.toml", mirror_origin):
            fragment = env_key_fragment(source.name)
            env[f"POETRY_HTTP_BASIC_{fragment}_USERNAME"] = username
            env[f"POETRY_HTTP_BASIC_{fragment}_PASSWORD"] = ""
        return env
    if manager == "pip":
        index_url = simple_index_url(config.api_base, config.mode)
        parts = urlsplit(index_url)
        credentialed_netloc = f"{quote(username, safe='')}@{parts.netloc}"
        return {"PIP_INDEX_URL": f"{parts.scheme}://{credentialed_netloc}{parts.path}"}
    if manager in ("npm", "pnpm", "yarn"):
        return _npm_family_auth_env(config, manager, username)
    return {}

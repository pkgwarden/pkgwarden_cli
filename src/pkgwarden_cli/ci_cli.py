"""`pw ci setup`: persist registry credentials and env for a CI runner.

Unlike `pw sync`, which injects per-invocation credentials into a child process, CI
runners install with their own commands (`uv sync`, `pnpm install`, ...) in later
steps, so the config has to outlive this process as files plus exported env.
"""

import os
import shlex
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import typer
from pydantic import BaseModel, Field, model_validator

from pkgwarden_cli import credentials
from pkgwarden_cli.config import CliConfig, PackageManager
from pkgwarden_cli.http_client import mirror_basic_username
from pkgwarden_cli.mirror_auth import (
    PoetrySource,
    env_key_fragment,
    npm_registry_base,
    npmrc_for_registry,
    poetry_sources,
    url_targets_origin,
)
from pkgwarden_cli.package_manager import detect_managers, ecosystem_for_manager
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.urls import mirror_origin_from_api_base, simple_index_url

NETRC_FILENAME = "pkgwarden.netrc"
NPMRC_FILENAME = "pkgwarden.npmrc"
TOKEN_FILENAME = "pkgwarden.token"
YARN_BERRY_MARKER = ".yarnrc.yml"

# Gate accepts an empty Basic password, but netrc syntax needs a non-empty token.
NETRC_PASSWORD = "x"

# Poetry priorities under which the gate source displaces PyPI rather than sitting beside it.
# Absent means poetry's own default (primary); "default" is the pre-1.8 spelling of the same.
GATE_SOURCE_PRIORITIES: frozenset[str | None] = frozenset({None, "primary", "default"})

# The only priority poetry never resolves from implicitly; everything else routes around us.
OPT_IN_SOURCE_PRIORITY = "explicit"


class CiSetupPlan(BaseModel):
    """What `pw ci setup` configured. `secret_env` values are token-bearing; `env` is not."""

    configured: list[PackageManager]
    unsupported: list[str]
    env: dict[str, str]
    secret_env: dict[str, str] = Field(default_factory=dict)
    token_path: Path | None = None

    @model_validator(mode="after")
    def _secret_env_needs_a_token_file(self) -> Self:
        if self.secret_env and self.token_path is None:
            raise ValueError("secret_env values are read from token_path, which is unset")
        return self


def ci_config_dir() -> Path:
    runner_temp = os.environ.get("RUNNER_TEMP")
    base = Path(runner_temp) if runner_temp else credentials.config_home() / "pkgwarden" / "ci"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_private(path: Path, content: str) -> Path:
    """Materialize a token-bearing file 0600 from the first byte, then swap it in.

    Write-then-chmod would leave the token world-readable on a shared runner for a
    window, would follow a pre-existing symlink out of the config directory, and would
    expose a half-written file to a concurrent reader. The pid keeps two concurrent
    `pw ci setup` runs off each other's staging file; `os.replace` is atomic.
    """
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(staging, path)
    return path


def _unsupported_reason(manager: PackageManager, cwd: Path) -> str | None:
    if manager == "yarn" and (cwd / YARN_BERRY_MARKER).is_file():
        return (
            f"yarn: Yarn Berry ({YARN_BERRY_MARKER} present) is not supported; "
            "set npmRegistryServer in .yarnrc.yml manually"
        )
    return None


def _python_env(config: CliConfig, token: str, config_dir: Path) -> dict[str, str]:
    index_url = simple_index_url(config.api_base, config.mode)
    host = urlsplit(index_url).hostname or ""
    netrc = _write_private(
        config_dir / NETRC_FILENAME,
        f"machine {host} login {token} password {NETRC_PASSWORD}\n",
    )
    return {
        "NETRC": str(netrc),
        # UV_INDEX would only ADD an index and leave PyPI as a fallback, defeating the gate.
        "UV_DEFAULT_INDEX": index_url,
        "PIP_INDEX_URL": index_url,
    }


def _poetry_stanza_message(index_url: str) -> str:
    return (
        "pw ci setup: poetry has no gate source in pyproject.toml. Commit this, then re-run:\n"
        "\n"
        "[[tool.poetry.source]]\n"
        'name = "gate"\n'
        f'url = "{index_url}"\n'
        'priority = "primary"\n'
        "\n"
        "If you have a committed poetry.lock, run `poetry lock` first and commit both files."
    )


def _reject_sources_outside_the_gate(sources: list[PoetrySource], mirror_origin: str) -> None:
    """Only `explicit` sources are never resolved implicitly; any other one bypasses the gate."""
    reachable = [
        source
        for source in sources
        if not url_targets_origin(source.url, mirror_origin)
        and source.priority != OPT_IN_SOURCE_PRIORITY
    ]
    if not reachable:
        return
    named = ", ".join(f"{source.name} ({source.url})" for source in reachable)
    typer.echo(
        f"pw ci setup: pyproject.toml declares poetry sources outside the gate: {named}. "
        "Poetry can resolve from them, so blocked packages would still install. Set priority = "
        '"explicit" on each one (or remove it), then re-run.',
        err=True,
    )
    raise typer.Exit(1)


def _poetry_env(
    config: CliConfig, token: str, cwd: Path, config_dir: Path
) -> tuple[dict[str, str], dict[str, str], Path]:
    mirror_origin = mirror_origin_from_api_base(config.api_base)
    sources = poetry_sources(cwd / "pyproject.toml")
    qualifying = [
        source
        for source in sources
        if url_targets_origin(source.url, mirror_origin)
        and source.priority in GATE_SOURCE_PRIORITIES
    ]
    if not qualifying:
        index_url = simple_index_url(config.api_base, config.mode)
        typer.echo(_poetry_stanza_message(index_url), err=True)
        raise typer.Exit(1)
    _reject_sources_outside_the_gate(sources, mirror_origin)
    token_path = _write_private(config_dir / TOKEN_FILENAME, token)
    env: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    for source in qualifying:
        fragment = env_key_fragment(source.name)
        secret_env[f"POETRY_HTTP_BASIC_{fragment}_USERNAME"] = token
        env[f"POETRY_HTTP_BASIC_{fragment}_PASSWORD"] = ""
    return env, secret_env, token_path


def _npm_env(config: CliConfig, token: str, config_dir: Path, include_yarn: bool) -> dict[str, str]:
    registry_base = npm_registry_base(config.api_base)
    npmrc = _write_private(
        config_dir / NPMRC_FILENAME,
        npmrc_for_registry(registry_base, token),
    )
    env = {"NPM_CONFIG_USERCONFIG": str(npmrc)}
    if include_yarn:
        env["YARN_NPM_REGISTRY_SERVER"] = registry_base
    return env


def build_plan(config: CliConfig, token: str, cwd: Path, config_dir: Path) -> CiSetupPlan:
    supported: list[PackageManager] = []
    unsupported: list[str] = []
    for detection in detect_managers(cwd):
        reason = _unsupported_reason(detection.manager, cwd)
        if reason:
            unsupported.append(reason)
            continue
        supported.append(detection.manager)
    env: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    token_path: Path | None = None
    if "poetry" in supported:
        poetry_env, poetry_secret_env, token_path = _poetry_env(config, token, cwd, config_dir)
        env.update(poetry_env)
        secret_env.update(poetry_secret_env)
    if any(manager in ("uv", "pip") for manager in supported):
        env.update(_python_env(config, token, config_dir))
    if any(ecosystem_for_manager(manager) == "npm" for manager in supported):
        env.update(_npm_env(config, token, config_dir, "yarn" in supported))
    return CiSetupPlan(
        configured=supported,
        unsupported=unsupported,
        env=env,
        secret_env=secret_env,
        token_path=token_path,
    )


def _emit_env(plan: CiSetupPlan) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        for key, value in plan.env.items():
            typer.echo(f"export {key}={shlex.quote(value)}")
        for key in plan.secret_env:
            typer.echo(f'export {key}="$(cat {shlex.quote(str(plan.token_path))})"')
        return
    combined = {**plan.env, **plan.secret_env}
    injected = [key for key, value in combined.items() if "\n" in value or "\r" in value]
    if injected:
        typer.echo(
            f"pw ci setup: refusing to write {', '.join(injected)} to $GITHUB_ENV: "
            "the value contains a newline, which GitHub Actions would read as another "
            "variable. Point $RUNNER_TEMP at a path without newlines.",
            err=True,
        )
        raise typer.Exit(1)
    try:
        with Path(github_env).open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in combined.items())
    except OSError as error:
        typer.echo(f"pw ci setup: cannot append to $GITHUB_ENV ({github_env}): {error}", err=True)
        raise typer.Exit(1) from error


def setup(ctx: typer.Context) -> None:
    """Write registry auth files and export the env CI package managers need."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    config = runtime.config
    cwd = Path.cwd()
    if not urlsplit(simple_index_url(config.api_base, config.mode)).hostname:
        typer.echo(
            f"pw ci setup: {config.api_base} has no host; set PKGWARDEN_API_URL to the "
            "full https:// URL of your deployment.",
            err=True,
        )
        raise typer.Exit(1)
    if config.mode is None:
        typer.echo(
            "pw ci setup: mode is unset, so the airgapped index path is used. Gate "
            'deployments must set mode = "gate" in .pkgwarden.toml or PKGWARDEN_MODE, '
            "or installs will 404.",
            err=True,
        )
    try:
        token = mirror_basic_username(config)
    except ValueError as error:
        typer.echo(f"pw ci setup: {error}", err=True)
        raise typer.Exit(1) from error
    if not detect_managers(cwd):
        typer.echo(
            f"pw ci setup: no supported package manager detected in {cwd}. "
            "Run it from the directory holding your lockfile.",
            err=True,
        )
        raise typer.Exit(1)
    plan = build_plan(config, token, cwd, ci_config_dir())
    for reason in plan.unsupported:
        typer.echo(f"pw ci setup: {reason}", err=True)
    if not plan.configured:
        typer.echo("pw ci setup: nothing could be configured", err=True)
        raise typer.Exit(1)
    _emit_env(plan)
    typer.echo(f"pw ci setup: configured {', '.join(plan.configured)}", err=True)


ci_app = typer.Typer(
    name="ci",
    help="CI runner integration for pkgwarden-gated package installs.",
    no_args_is_help=True,
)


def register_ci(app: typer.Typer) -> None:
    ci_app.command("setup")(setup)
    app.add_typer(ci_app)

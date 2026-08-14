"""`pw ci setup`: persist registry credentials and env for a CI runner.

Unlike `pw sync`, which injects per-invocation credentials into a child process, CI
runners install with their own commands (`uv sync`, `pnpm install`, ...) in later
steps, so the config has to outlive this process as files plus exported env.
"""

import os
import shlex
from pathlib import Path
from urllib.parse import urlsplit

import typer
from pydantic import BaseModel

from pkgwarden_cli import credentials
from pkgwarden_cli.config import CliConfig, PackageManager
from pkgwarden_cli.http_client import mirror_basic_username
from pkgwarden_cli.mirror_auth import npm_registry_base, npmrc_for_registry
from pkgwarden_cli.package_manager import detect_managers, ecosystem_for_manager
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.urls import simple_index_url

NETRC_FILENAME = "pkgwarden.netrc"
NPMRC_FILENAME = "pkgwarden.npmrc"
YARN_BERRY_MARKER = ".yarnrc.yml"

# Gate accepts an empty Basic password, but netrc syntax needs a non-empty token.
NETRC_PASSWORD = "x"


class CiSetupPlan(BaseModel):
    """What `pw ci setup` configured, minus the token itself."""

    configured: list[PackageManager]
    unsupported: list[str]
    env: dict[str, str]


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
    if manager == "poetry":
        return "poetry: not supported by `pw ci setup`; configure the index in pyproject.toml"
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
    if any(ecosystem_for_manager(manager) == "pypi" for manager in supported):
        env.update(_python_env(config, token, config_dir))
    if any(ecosystem_for_manager(manager) == "npm" for manager in supported):
        env.update(_npm_env(config, token, config_dir, "yarn" in supported))
    return CiSetupPlan(configured=supported, unsupported=unsupported, env=env)


def _emit_env(env: dict[str, str]) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        for key, value in env.items():
            typer.echo(f"export {key}={shlex.quote(value)}")
        return
    injected = [key for key, value in env.items() if "\n" in value or "\r" in value]
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
            handle.writelines(f"{key}={value}\n" for key, value in env.items())
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
    _emit_env(plan.env)
    typer.echo(f"pw ci setup: configured {', '.join(plan.configured)}", err=True)


ci_app = typer.Typer(
    name="ci",
    help="CI runner integration for pkgwarden-gated package installs.",
    no_args_is_help=True,
)


def register_ci(app: typer.Typer) -> None:
    ci_app.command("setup")(setup)
    app.add_typer(ci_app)

import shutil
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, computed_field

from pkgwarden_cli.process_runner import ProcessResult, run_process

ProcessRunner = Callable[..., ProcessResult]

REDACTED = "<redacted>"
LOCK_FILE = "uv.lock"
GATE_LOCK_SIDECAR = "uv.lock.pkgwarden"
UV_LOCK = ["uv", "lock"]
UV_EXPORT = [
    "uv",
    "export",
    "--frozen",
    "--format",
    "requirements.txt",
    "--no-hashes",
    "--no-header",
    "--no-emit-project",
    "--all-extras",
    "--all-groups",
]


class RelockError(Exception):
    pass


class PlannedCommand(BaseModel):
    argv: list[str]
    env: dict[str, str]


class RelockResult(BaseModel):
    commands: list[PlannedCommand]
    gate_versions: list[str] = []
    pypi_versions: list[str] = []
    dry_run: bool = False
    gate_lock_path: str | None = None

    @computed_field
    @property
    def added(self) -> list[str]:
        return sorted(set(self.pypi_versions) - set(self.gate_versions))

    @computed_field
    @property
    def removed(self) -> list[str]:
        return sorted(set(self.gate_versions) - set(self.pypi_versions))

    @computed_field
    @property
    def identical(self) -> bool:
        return not self.added and not self.removed


def parse_exported_versions(requirements_text: str) -> set[str]:
    """Reduce `uv export` output to `name==version` pins, dropping extras and markers."""
    pins = (line.split(";")[0].strip() for line in requirements_text.splitlines())
    return {
        f"{name.split('[')[0].lower()}=={version}"
        for name, _, version in (
            pin.partition("==") for pin in pins if not pin.startswith(("#", "-"))
        )
        if version
    }


def _gate_environment(index_name: str, index_url: str, token: str) -> dict[str, str]:
    variable = index_name.upper().replace("-", "_")
    return {
        "UV_INDEX": f"{index_name}={index_url}",
        "UV_DEFAULT_INDEX": index_url,
        f"UV_INDEX_{variable}_USERNAME": token,
        f"UV_INDEX_{variable}_PASSWORD": "",
    }


def _redacted(environment: dict[str, str], token: str) -> dict[str, str]:
    return {key: REDACTED if value == token else value for key, value in environment.items()}


def _run(
    runner: ProcessRunner, argv: list[str], project: Path, environment: dict[str, str], token: str
) -> str:
    result = runner(argv, cwd=project, env_overrides=environment)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace(token, REDACTED)
        raise RelockError(f"`{' '.join(argv)}` failed ({result.returncode}): {detail}")
    return result.stdout


def relock_to_pypi(
    project: Path,
    *,
    index_name: str,
    index_url: str,
    token: str,
    keep_gate_lock: bool,
    dry_run: bool,
    runner: ProcessRunner = run_process,
) -> RelockResult:
    if not (project / "pyproject.toml").is_file():
        raise RelockError(
            f"No pyproject.toml in {project}; run from a uv project or pass --project"
        )
    gate_environment = _gate_environment(index_name, index_url, token)
    plan = [
        PlannedCommand(argv=argv, env=env)
        for argv, env in (
            (UV_LOCK, _redacted(gate_environment, token)),
            (UV_EXPORT, {}),
            (UV_LOCK, {}),
            (UV_EXPORT, {}),
        )
    ]
    if dry_run:
        return RelockResult(commands=plan, dry_run=True)
    if runner(["uv", "--version"], cwd=project, env_overrides={}).returncode != 0:
        raise RelockError(
            "uv is not installed or not on PATH; pw lock pypi supports uv projects only"
        )
    _run(runner, UV_LOCK, project, gate_environment, token)
    gate_lock = project / GATE_LOCK_SIDECAR
    shutil.copyfile(project / LOCK_FILE, gate_lock)
    gate_versions = parse_exported_versions(_run(runner, UV_EXPORT, project, {}, token))
    try:
        _run(runner, UV_LOCK, project, {}, token)
    except RelockError as error:
        raise RelockError(
            f"{error}\nuv.lock still holds the pkgwarden resolution; a copy is at {gate_lock}"
        ) from error
    if index_url in (project / LOCK_FILE).read_text(encoding="utf-8"):
        raise RelockError(
            f"uv.lock still references {index_url}: pyproject.toml declares the pkgwarden "
            f"index, which uv reads ahead of the environment. Remove it and re-run; "
            f"the pkgwarden resolution is kept at {gate_lock}"
        )
    pypi_versions = parse_exported_versions(_run(runner, UV_EXPORT, project, {}, token))
    result = RelockResult(
        commands=plan,
        gate_versions=sorted(gate_versions),
        pypi_versions=sorted(pypi_versions),
        gate_lock_path=str(gate_lock),
    )
    if result.identical and not keep_gate_lock:
        gate_lock.unlink()
        result.gate_lock_path = None
    return result

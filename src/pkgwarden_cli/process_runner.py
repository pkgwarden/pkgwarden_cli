import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def run_process(
    argv: list[str],
    *,
    cwd: Path,
    env_overrides: dict[str, str] | None = None,
    timeout: float | None = None,
) -> ProcessResult:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return ProcessResult(returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr) + f"\ntimeout after {timeout}s"
        return ProcessResult(returncode=124, stdout=stdout, stderr=stderr)
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value

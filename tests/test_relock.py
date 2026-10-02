import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pkgwarden_cli import add_cli, lock_cli
from pkgwarden_cli import main as main_module
from pkgwarden_cli.process_runner import ProcessResult
from pkgwarden_cli.relock import RelockError, RelockResult, parse_exported_versions, relock_to_pypi

TOKEN = "pyf_gate_secret"
INDEX_URL = "https://gate.test/resolution/simple/"
GATE_EXPORT = "requests==2.32.0\nidna==3.7\n"
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


class FakeRunner:
    """Stands in for run_process: `uv lock` writes a lock naming its source index."""

    def __init__(self, project: Path, exports: list[str], missing_uv: bool = False) -> None:
        self.project = project
        self.exports = list(exports)
        self.missing_uv = missing_uv
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env_overrides: dict[str, str] | None = None
    ) -> ProcessResult:
        self.calls.append((argv, env_overrides or {}))
        if self.missing_uv:
            return ProcessResult(127, "", "uv: not found")
        if argv == UV_LOCK:
            source = "gate" if env_overrides else "pypi"
            (cwd / "uv.lock").write_text(f"lock from {source}", encoding="utf-8")
        if argv == UV_EXPORT:
            return ProcessResult(0, self.exports.pop(0), "")
        return ProcessResult(0, "", "")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    return tmp_path


def _relock(project: Path, runner: FakeRunner, **overrides: bool) -> RelockResult:
    return relock_to_pypi(
        project,
        index_name="pkgwarden",
        index_url=INDEX_URL,
        token=TOKEN,
        runner=runner,
        **{"keep_gate_lock": False, "dry_run": False, **overrides},
    )


def test_parse_ignores_comments_blanks_flags_and_markers() -> None:
    text = (
        "# comment\n\nRequests[socks]==2.32.0 ; python_version >= '3.9'\n"
        "-e .\n--index-url https://x\nidna==3.7\n"
    )
    assert parse_exported_versions(text) == {"requests==2.32.0", "idna==3.7"}


def test_identical_sets_succeed_and_leave_pypi_lock(project: Path) -> None:
    runner = FakeRunner(project, [GATE_EXPORT, "idna==3.7\nrequests==2.32.0\n"])
    result = _relock(project, runner)
    assert result.identical
    assert result.gate_versions == ["idna==3.7", "requests==2.32.0"]
    assert (project / "uv.lock").read_text(encoding="utf-8") == "lock from pypi"
    assert not (project / "uv.lock.pkgwarden").exists()


def test_command_sequence_and_environments(project: Path) -> None:
    runner = FakeRunner(project, [GATE_EXPORT, GATE_EXPORT])
    _relock(project, runner)
    assert [argv for argv, _ in runner.calls] == [
        ["uv", "--version"],
        UV_LOCK,
        UV_EXPORT,
        UV_LOCK,
        UV_EXPORT,
    ]
    gate_env = runner.calls[1][1]
    assert gate_env == {
        "UV_INDEX": f"pkgwarden={INDEX_URL}",
        "UV_DEFAULT_INDEX": INDEX_URL,
        "UV_INDEX_PKGWARDEN_USERNAME": TOKEN,
        "UV_INDEX_PKGWARDEN_PASSWORD": "",
    }
    assert runner.calls[3][1] == {}
    assert all(TOKEN not in " ".join(argv) for argv, _ in runner.calls)


def test_index_name_is_normalised_for_environment_variables(project: Path) -> None:
    runner = FakeRunner(project, [GATE_EXPORT, GATE_EXPORT])
    relock_to_pypi(
        project,
        index_name="my-gate",
        index_url=INDEX_URL,
        token=TOKEN,
        keep_gate_lock=False,
        dry_run=False,
        runner=runner,
    )
    assert "UV_INDEX_MY_GATE_USERNAME" in runner.calls[1][1]


def test_differing_sets_report_diff_and_write_sidecar(project: Path) -> None:
    runner = FakeRunner(project, [GATE_EXPORT, "requests==2.33.0\nidna==3.7\n"])
    result = _relock(project, runner)
    assert not result.identical
    assert result.removed == ["requests==2.32.0"]
    assert result.added == ["requests==2.33.0"]
    assert (project / "uv.lock").read_text(encoding="utf-8") == "lock from pypi"
    assert (project / "uv.lock.pkgwarden").read_text(encoding="utf-8") == "lock from gate"


def test_keep_gate_lock_writes_sidecar_even_when_identical(project: Path) -> None:
    runner = FakeRunner(project, [GATE_EXPORT, GATE_EXPORT])
    _relock(project, runner, keep_gate_lock=True)
    assert (project / "uv.lock.pkgwarden").read_text(encoding="utf-8") == "lock from gate"


def test_missing_uv_raises_clear_error(project: Path) -> None:
    with pytest.raises(RelockError, match="uv is not installed"):
        _relock(project, FakeRunner(project, [], missing_uv=True))


def test_missing_pyproject_raises(tmp_path: Path) -> None:
    with pytest.raises(RelockError, match="pyproject.toml"):
        _relock(tmp_path, FakeRunner(tmp_path, []))


def test_failed_lock_redacts_token(project: Path) -> None:
    class Failing(FakeRunner):
        def __call__(
            self, argv: list[str], *, cwd: Path, env_overrides: dict[str, str] | None = None
        ) -> ProcessResult:
            if argv == UV_LOCK:
                return ProcessResult(2, "", f"boom {TOKEN}")
            return ProcessResult(0, "", "")

    with pytest.raises(RelockError) as raised:
        _relock(project, Failing(project, []))
    assert TOKEN not in str(raised.value)
    assert "boom <redacted>" in str(raised.value)


def test_dry_run_runs_nothing_and_redacts_token(project: Path) -> None:
    runner = FakeRunner(project, [])
    result = _relock(project, runner, dry_run=True)
    assert runner.calls == []
    assert [command.argv for command in result.commands] == [UV_LOCK, UV_EXPORT, UV_LOCK, UV_EXPORT]
    assert result.commands[0].env["UV_INDEX_PKGWARDEN_USERNAME"] == "<redacted>"
    assert TOKEN not in result.model_dump_json()


def _gate_cli(project: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "gate") -> None:
    monkeypatch.chdir(project)
    (project / ".pkgwarden.toml").write_text(
        f'api_url = "https://gate.test/api/v1"\nmode = "{mode}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", TOKEN)
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", TOKEN)


def test_cli_dry_run_prints_commands_without_token(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate_cli(project, monkeypatch)
    result = CliRunner().invoke(main_module.app, ["lock", "pypi", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "uv lock" in result.output
    assert "UV_INDEX_PKGWARDEN_USERNAME=<redacted>" in result.output
    assert TOKEN not in result.output


def test_cli_success_message_and_json(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_cli(project, monkeypatch)
    monkeypatch.setattr(lock_cli, "run_process", FakeRunner(project, [GATE_EXPORT, GATE_EXPORT]))
    result = CliRunner().invoke(main_module.app, ["lock", "pypi"])
    assert result.exit_code == 0, result.output
    assert "2 packages" in result.output
    assert "uv.lock now points at PyPI; resolution was vetted by pkgwarden" in result.output
    monkeypatch.setattr(lock_cli, "run_process", FakeRunner(project, [GATE_EXPORT, GATE_EXPORT]))
    as_json = CliRunner().invoke(main_module.app, ["--json", "lock", "pypi"])
    assert json.loads(as_json.output)["identical"] is True


def test_cli_mismatch_exits_one_with_diff(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_cli(project, monkeypatch)
    monkeypatch.setattr(
        lock_cli, "run_process", FakeRunner(project, [GATE_EXPORT, "requests==2.33.0\n"])
    )
    result = CliRunner().invoke(main_module.app, ["lock", "pypi"])
    assert result.exit_code == 1
    assert "- requests==2.32.0" in result.output
    assert "+ requests==2.33.0" in result.output
    assert "uv.lock.pkgwarden" in result.output


def test_cli_refuses_non_gate_mode(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_cli(project, monkeypatch, mode="enterprise")
    result = CliRunner().invoke(main_module.app, ["lock", "pypi", "--dry-run"])
    assert result.exit_code == 1
    assert "gate" in result.output


def test_cli_reports_relock_error(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_cli(project, monkeypatch)
    monkeypatch.setattr(lock_cli, "run_process", FakeRunner(project, [], missing_uv=True))
    result = CliRunner().invoke(main_module.app, ["lock", "pypi"])
    assert result.exit_code == 1
    assert "uv is not installed" in result.output


class ScriptedRunner(FakeRunner):
    """Fails the Nth `uv lock` / `uv export` call (1-based per kind)."""

    def __init__(self, project: Path, exports: list[str], fail_lock: int = 0, fail_export: int = 0):
        super().__init__(project, exports)
        self.fail_lock = fail_lock
        self.fail_export = fail_export
        self.lock_calls = 0
        self.export_calls = 0

    def __call__(
        self, argv: list[str], *, cwd: Path, env_overrides: dict[str, str] | None = None
    ) -> ProcessResult:
        if argv == UV_LOCK:
            self.lock_calls += 1
            if self.lock_calls == self.fail_lock:
                return ProcessResult(2, "", f"resolution failed for {TOKEN}")
        if argv == UV_EXPORT:
            self.export_calls += 1
            if self.export_calls == self.fail_export:
                return ProcessResult(2, "", "export failed")
        return super().__call__(argv, cwd=cwd, env_overrides=env_overrides)


def test_first_lock_failure_leaves_no_sidecar(project: Path) -> None:
    with pytest.raises(RelockError, match="resolution failed for <redacted>"):
        _relock(project, ScriptedRunner(project, [], fail_lock=1))
    assert not (project / "uv.lock.pkgwarden").exists()


def test_first_export_failure_keeps_gate_lock_sidecar(project: Path) -> None:
    with pytest.raises(RelockError, match="export failed"):
        _relock(project, ScriptedRunner(project, [], fail_export=1))
    assert (project / "uv.lock.pkgwarden").read_text(encoding="utf-8") == "lock from gate"


def test_second_lock_failure_keeps_sidecar_and_says_where_the_lock_is(project: Path) -> None:
    with pytest.raises(RelockError, match=r"uv\.lock still holds the pkgwarden resolution"):
        _relock(project, ScriptedRunner(project, [GATE_EXPORT], fail_lock=2))
    assert (project / "uv.lock.pkgwarden").read_text(encoding="utf-8") == "lock from gate"
    assert (project / "uv.lock").read_text(encoding="utf-8") == "lock from gate"


def test_second_export_failure_keeps_sidecar(project: Path) -> None:
    with pytest.raises(RelockError, match="export failed"):
        _relock(project, ScriptedRunner(project, [GATE_EXPORT], fail_export=2))
    assert (project / "uv.lock.pkgwarden").exists()


def test_parse_keeps_versions_verbatim_and_drops_url_pins() -> None:
    text = "foo==1.0\nbar==1.0.0\nbaz @ https://example.test/baz.whl\n"
    assert parse_exported_versions(text) == {"foo==1.0", "bar==1.0.0"}


def test_token_never_appears_in_any_cli_output(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate_cli(project, monkeypatch)
    outputs = []
    for arguments, exports, fail_lock in (
        (["lock", "pypi", "--dry-run"], [], 0),
        (["--json", "lock", "pypi", "--dry-run"], [], 0),
        (["--json", "lock", "pypi"], [GATE_EXPORT, GATE_EXPORT], 0),
        (["lock", "pypi"], [GATE_EXPORT, "requests==2.33.0\n"], 0),
        (["lock", "pypi"], [], 1),
    ):
        monkeypatch.setattr(
            lock_cli, "run_process", ScriptedRunner(project, exports, fail_lock=fail_lock)
        )
        result = CliRunner().invoke(main_module.app, arguments)
        outputs.append(result.output + str(result.exception or ""))
    assert all(TOKEN not in output for output in outputs)


def test_lock_pypi_does_not_run_the_native_lock(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate_cli(project, monkeypatch)
    native_calls: list[list[str]] = []
    monkeypatch.setattr(
        add_cli,
        "run_process",
        lambda argv, **_: native_calls.append(argv) or ProcessResult(0, "", ""),
    )
    CliRunner().invoke(main_module.app, ["lock", "pypi", "--dry-run"])
    assert native_calls == []


def test_user_index_env_is_overridden_on_gate_lock_and_inherited_on_pypi_lock(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = project / "bin"
    bin_dir.mkdir()
    log = project / "env.log"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'echo "$1 UV_INDEX=$UV_INDEX DEFAULT=$UV_DEFAULT_INDEX USER=$UV_INDEX_PKGWARDEN_USERNAME" '
        f">> {log}\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("UV_INDEX", "corp=https://corp.test/simple")
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://corp.test/simple")
    (project / "uv.lock").write_text("", encoding="utf-8")
    relock_to_pypi(
        project,
        index_name="pkgwarden",
        index_url=INDEX_URL,
        token=TOKEN,
        keep_gate_lock=False,
        dry_run=False,
    )
    lock_lines = [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if "lock " in line or line.startswith("lock")
    ]
    gate_line, pypi_line = lock_lines
    assert f"UV_INDEX=pkgwarden={INDEX_URL}" in gate_line and f"USER={TOKEN}" in gate_line
    assert "UV_INDEX=corp=https://corp.test/simple" in pypi_line
    assert "DEFAULT=https://corp.test/simple" in pypi_line and f"USER={TOKEN}" not in pypi_line


def test_pypi_lock_still_pointing_at_the_gate_is_an_error(project: Path) -> None:
    class PinnedIndex(FakeRunner):
        def __call__(
            self, argv: list[str], *, cwd: Path, env_overrides: dict[str, str] | None = None
        ) -> ProcessResult:
            result = super().__call__(argv, cwd=cwd, env_overrides=env_overrides)
            if argv == UV_LOCK:
                (cwd / "uv.lock").write_text(f'registry = "{INDEX_URL}"', encoding="utf-8")
            return result

    with pytest.raises(RelockError, match="still references"):
        _relock(project, PinnedIndex(project, [GATE_EXPORT, GATE_EXPORT]))
    assert (project / "uv.lock.pkgwarden").exists()

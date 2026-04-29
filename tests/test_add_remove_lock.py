from pathlib import Path

from typer.testing import CliRunner

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli import main as main_module
from pkgwarden_cli import process_runner as runner_mod


def _tape_cfg(tmp_path: Path, manager: str = "uv") -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        f'api_url = "https://tape.test/api/v1"\nmode = "tape"\npackage_manager = "{manager}"\n',
        encoding="utf-8",
    )


def _ent_cfg(tmp_path: Path, manager: str = "uv") -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        (
            'api_url = "https://ent.test/api/v1"\n'
            'mode = "enterprise"\n'
            f'package_manager = "{manager}"\n'
            'project_id = "proj-1"\n'
        ),
        encoding="utf-8",
    )


def _stub_ok(calls):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(0, "added", "")

    return fake_run


def _stub_fail(calls):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(1, "", "package not found")

    return fake_run


def _stub_fail_then_ok(calls):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        if len(calls) == 1:
            return runner_mod.ProcessResult(1, "", "package not found")
        return runner_mod.ProcessResult(0, "added", "")

    return fake_run


def test_add_tape_runs_native_add(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _tape_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_tape_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["add", "httpx"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "add", "httpx"]]


def test_add_tape_failure_suggests_why_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _tape_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_tape_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["add", "httpx", "--version", "0.27.0"])
    assert result.exit_code != 0
    assert "why-blocked" in (result.stdout + result.stderr).lower()


def test_add_enterprise_without_plugin_refuses_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    enterprise_hooks.reset()
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["add", "httpx", "--version", "0.27.0"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "plugin" in combined.lower() or "fallback is" in combined.lower()
    assert len(calls) == 1


def test_add_enterprise_invokes_registered_fallback_then_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail_then_ok(calls))
    invocations: list[tuple[str, str, str]] = []

    def fake_fallback(runtime, manager, package, version):
        invocations.append((manager, package, version))
        return True

    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(fake_fallback)
    try:
        runner = CliRunner()
        result = runner.invoke(main_module.app, ["add", "httpx", "--version", "0.27.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [
        ["uv", "add", "httpx==0.27.0"],
        ["uv", "add", "httpx==0.27.0"],
    ]
    assert invocations == [("uv", "httpx", "0.27.0")]


def test_add_enterprise_fallback_without_version_skips_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []

    def never_fallback(runtime, manager, package, version):
        invocations.append((manager, package, version))
        return True

    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(never_fallback)
    try:
        runner = CliRunner()
        result = runner.invoke(main_module.app, ["add", "httpx"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "--version" in combined or "version" in combined.lower()
    assert invocations == []


def test_remove_tape_runs_native_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _tape_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_tape_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["remove", "httpx"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "remove", "httpx"]]


def test_lock_tape_runs_native_lock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _tape_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_tape_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["lock"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "lock"]]

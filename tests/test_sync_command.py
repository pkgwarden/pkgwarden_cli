from pathlib import Path

from typer.testing import CliRunner

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli import main as main_module
from pkgwarden_cli import process_runner as runner_mod


def _write_gate_config(tmp_path: Path, manager: str = "uv") -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        f'api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "{manager}"\n',
        encoding="utf-8",
    )


def _write_enterprise_config(tmp_path: Path, manager: str = "uv") -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        (
            'api_url = "https://ent.test/api/v1"\n'
            'mode = "enterprise"\n'
            f'package_manager = "{manager}"\n'
            'project_id = "proj-1"\n'
        ),
        encoding="utf-8",
    )


def _stub_success(calls: list[list[str]]):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(returncode=0, stdout="ok", stderr="")

    return fake_run


def _stub_fail(calls: list[list[str]]):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(returncode=1, stdout="", stderr="resolve failed")

    return fake_run


def _stub_fail_then_success(calls: list[list[str]]):
    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        if len(calls) == 1:
            return runner_mod.ProcessResult(returncode=1, stdout="", stderr="fail")
        return runner_mod.ProcessResult(returncode=0, stdout="ok", stderr="")

    return fake_run


def test_sync_gate_success_runs_uv_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path, "uv")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", _stub_success(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["sync"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "sync"]]


def test_sync_gate_failure_prints_guidance_and_exits_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path, "uv")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", _stub_fail(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["sync"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "why-blocked" in combined.lower() or "blocked" in combined.lower()


def test_sync_enterprise_without_plugin_refuses_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_enterprise_config(tmp_path, "uv")
    (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", _stub_fail(calls))
    enterprise_hooks.reset()
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["sync"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "plugin" in combined.lower() or "fallback is" in combined.lower()
    assert len(calls) == 1


def test_sync_enterprise_invokes_registered_fallback_then_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_enterprise_config(tmp_path, "uv")
    (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "pkgwarden_cli.sync_cli.run_process",
        _stub_fail_then_success(calls),
    )
    invocations: list[tuple[str, Path]] = []

    def fake_fallback(runtime, manager, cwd):
        invocations.append((manager, cwd))
        return True

    enterprise_hooks.reset()
    enterprise_hooks.register_sync_fallback(fake_fallback)
    try:
        runner = CliRunner()
        result = runner.invoke(main_module.app, ["sync"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "sync"], ["uv", "sync"]]
    assert len(invocations) == 1
    assert invocations[0][0] == "uv"


def test_sync_enterprise_fallback_failure_exits_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_enterprise_config(tmp_path, "uv")
    (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    monkeypatch.setenv("PKGWARDEN_PROJECT_ID", "proj-1")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", _stub_fail(calls))
    enterprise_hooks.reset()
    enterprise_hooks.register_sync_fallback(lambda runtime, manager, cwd: False)
    try:
        runner = CliRunner()
        result = runner.invoke(main_module.app, ["sync"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code != 0
    assert len(calls) == 1


def test_sync_respects_configured_manager_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_gate_config(tmp_path, "pnpm")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", _stub_success(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["sync"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["pnpm", "install"]]


def test_sync_errors_when_no_manager_configured_or_detected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://gate.test/api/v1"\nmode = "gate"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["sync"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "manager" in combined.lower()


def test_sync_injects_mirror_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.test/api/v1"\nmode = "enterprise"\npackage_manager = "uv"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_tok")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n\n'
        '[[tool.uv.index]]\nname = "pkgwarden-mirror"\n'
        'url = "https://ent.test/simple/"\ndefault = true\n',
        encoding="utf-8",
    )
    envs: list[dict | None] = []

    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        envs.append(env_overrides)
        return runner_mod.ProcessResult(0, "ok", "")

    monkeypatch.setattr("pkgwarden_cli.sync_cli.run_process", fake_run)
    result = CliRunner().invoke(main_module.app, ["sync"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert envs[0] is not None
    assert envs[0]["UV_INDEX_PKGWARDEN_MIRROR_USERNAME"] == "pyf_proj_tok"

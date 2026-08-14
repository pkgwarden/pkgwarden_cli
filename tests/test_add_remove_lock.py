import json
import re
from pathlib import Path

from typer.testing import CliRunner

from ansi import strip_ansi
from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli import main as main_module
from pkgwarden_cli import process_runner as runner_mod
from pkgwarden_cli.add_cli import format_enterprise_add_pending


def _gate_cfg(tmp_path: Path, manager: str = "uv") -> None:
    (tmp_path / ".pkgwarden.toml").write_text(
        f'api_url = "https://gate.test/api/v1"\nmode = "gate"\npackage_manager = "{manager}"\n',
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


def test_add_gate_runs_native_add(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _gate_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["add", "httpx"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "add", "httpx"]]


def test_add_gate_failure_suggests_why_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _gate_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
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


def _pending_fallback(invocations):
    def fake_fallback(runtime, manager, package, version, extras):
        invocations.append((manager, package, version, extras))
        return enterprise_hooks.EnterpriseAddOutcome(
            package=package,
            version=version,
            status="pending",
            request_group_id="g1",
            linked_exception_request_count=2,
            project_name="Reseller Demo API",
            web_url="https://demo.pkgwarden.com/approvals/r1",
        )

    return fake_fallback


def test_add_enterprise_invokes_registered_fallback_and_reports_pending(
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
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        runner = CliRunner()
        result = runner.invoke(main_module.app, ["add", "httpx", "--version", "0.27.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    # native add runs once, then only the manifest write-through (no resolving retry)
    assert calls == [["uv", "add", "httpx==0.27.0"], ["uv", "add", "--frozen", "httpx==0.27.0"]]
    assert invocations == [("uv", "httpx", "0.27.0", [])]
    out = result.stdout + result.stderr
    assert "Approval request opened" in out
    assert "Reseller Demo API" in out
    assert "https://demo.pkgwarden.com/approvals/r1" in out
    assert "CVE exceptions" in out
    assert "package not found" not in out  # raw native error not echoed on pending path


def test_add_inline_pin_reaches_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["add", "httpx==0.27.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    assert invocations == [("uv", "httpx", "0.27.0", [])]


def test_add_multi_package_opens_a_request_per_pin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["add", "httpx==0.27.0", "attrs==23.2.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    assert calls[0] == ["uv", "add", "httpx==0.27.0", "attrs==23.2.0"]
    assert invocations == [("uv", "httpx", "0.27.0", []), ("uv", "attrs", "23.2.0", [])]


def test_add_extras_forwarded_to_native_and_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["add", "flask[async]==3.1.2"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    assert calls[0] == ["uv", "add", "flask[async]==3.1.2"]
    assert invocations == [("uv", "flask", "3.1.2", ["async"])]


def test_add_dev_flag_passed_to_native_and_write_through(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["add", "pytest==8.3.4", "--dev"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    assert calls == [
        ["uv", "add", "--dev", "pytest==8.3.4"],
        ["uv", "add", "--frozen", "--dev", "pytest==8.3.4"],
    ]


def test_add_duplicate_pending_is_friendly_and_exits_pending(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))

    def duplicate_fallback(runtime, manager, package, version, extras):
        return enterprise_hooks.EnterpriseAddOutcome(
            package=package,
            version=version,
            status=enterprise_hooks.DUPLICATE_PENDING_STATUS,
        )

    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(duplicate_fallback)
    try:
        result = CliRunner().invoke(main_module.app, ["add", "httpx==0.27.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    out = result.stdout + result.stderr
    assert "already awaiting approval" in out
    assert "package not found" not in out  # resolver wall suppressed


def test_add_json_output_is_machine_readable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["--json", "add", "httpx==0.27.0"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 10, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"][0]["package"] == "httpx"
    assert payload["results"][0]["status"] == "pending"
    assert payload["results"][0]["request_group_id"] == "g1"


def test_add_mixed_pinned_and_unpinned_reports_error_and_exits_one(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_fail(calls))
    invocations: list[tuple] = []
    enterprise_hooks.reset()
    enterprise_hooks.register_add_fallback(_pending_fallback(invocations))
    try:
        result = CliRunner().invoke(main_module.app, ["add", "httpx==0.27.0", "attrs"])
    finally:
        enterprise_hooks.reset()
    assert result.exit_code == 1, result.stdout + result.stderr
    out = result.stdout + result.stderr
    assert "attrs==<version>" in out  # both-forms guidance for the unpinned one
    assert "Approval request opened" in out  # the pinned one still went through
    assert invocations == [("uv", "httpx", "0.27.0", [])]


def test_add_version_option_with_multiple_packages_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_PROJECT_TOKEN", "pyf_proj_x")
    result = CliRunner().invoke(main_module.app, ["add", "httpx", "attrs", "--version", "1.0.0"])
    assert result.exit_code == 2
    stripped = strip_ansi(result.stdout + result.stderr)
    assert "single package" in re.sub(r"[\s│╭╮╰╯─]+", " ", stripped)


def test_add_injects_mirror_credentials_into_native_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ent_cfg(tmp_path, "uv")
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
        return runner_mod.ProcessResult(0, "added", "")

    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", fake_run)
    result = CliRunner().invoke(main_module.app, ["add", "httpx==0.27.0"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert envs[0] is not None
    assert envs[0]["UV_INDEX_PKGWARDEN_MIRROR_USERNAME"] == "pyf_proj_tok"


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

    def never_fallback(runtime, manager, package, version, extras):
        invocations.append((manager, package, version, extras))
        return None

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


def test_format_enterprise_add_pending_minimal_outcome() -> None:
    outcome = enterprise_hooks.EnterpriseAddOutcome(
        package="httpx", version="0.27.0", status="pending"
    )
    text = format_enterprise_add_pending("httpx==0.27.0", outcome)
    assert "Approval request opened" in text
    assert "httpx==0.27.0" in text
    assert "pw add httpx==0.27.0" in text
    assert "CVE exception" not in text
    assert "track" not in text


def test_format_enterprise_add_pending_with_single_exception_and_link() -> None:
    outcome = enterprise_hooks.EnterpriseAddOutcome(
        package="requests",
        version="2.32.3",
        status="pending",
        request_group_id="g9",
        linked_exception_request_count=1,
        project_name="Reseller Demo API",
        web_url="https://demo.pkgwarden.com/approvals/r9",
    )
    text = format_enterprise_add_pending("requests==2.32.3", outcome)
    assert "Reseller Demo API" in text
    assert "g9" in text
    assert "1 opened" in text
    assert "CVE exception " in text  # singular noun
    assert "https://demo.pkgwarden.com/approvals/r9" in text


def test_remove_gate_runs_native_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _gate_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["remove", "httpx"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "remove", "httpx"]]


def test_lock_gate_runs_native_lock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _gate_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []
    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", _stub_ok(calls))
    runner = CliRunner()
    result = runner.invoke(main_module.app, ["lock"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [["uv", "lock"]]


def test_remove_failure_exits_one_not_native_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _gate_cfg(tmp_path, "uv")
    monkeypatch.setenv("PKGWARDEN_USER_TOKEN", "pyf_gate_x")
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd, env_overrides=None, timeout=None):
        calls.append(list(argv))
        return runner_mod.ProcessResult(2, "", "not found in dependencies")

    monkeypatch.setattr("pkgwarden_cli.add_cli.run_process", fake_run)
    result = CliRunner().invoke(main_module.app, ["remove", "flask==3.1.2"])
    # exit 1 (pw failure), never the native tool's raw code (2 means usage error / 10 pending)
    assert result.exit_code == 1
    assert calls == [["uv", "remove", "flask"]]  # spec form accepted, version stripped
    assert "not found in dependencies" in (result.stdout + result.stderr)

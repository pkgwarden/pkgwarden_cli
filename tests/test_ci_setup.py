import os
import shlex
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from pkgwarden_cli import main as main_module
from pkgwarden_cli.ci_cli import CiSetupPlan

GATE_TOKEN = "pkgw_gate_secret_token"


def _write_gate_config(root: Path) -> None:
    (root / ".pkgwarden.toml").write_text(
        'api_url = "https://index.pkgwarden.com/api/v1"\nmode = "gate"\n',
        encoding="utf-8",
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    for variable in ("PKGWARDEN_MIRROR_TOKEN", "PKGWARDEN_PROJECT_TOKEN", "PKGWARDEN_API_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PKGWARDEN_GATE_TOKEN", GATE_TOKEN)
    _write_gate_config(root)
    return root


def _run(args: list[str] | None = None):
    return CliRunner().invoke(main_module.app, ["ci", "setup", *(args or [])])


def _env_lines(github_env: Path) -> dict[str, str]:
    pairs = (
        line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines() if line
    )
    return {key: value for key, value in pairs}


def _runner_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    return runner_temp


def _write_poetry_pyproject(root: Path, name: str, url: str, priority: str | None) -> None:
    priority_line = f'priority = "{priority}"\n' if priority else ""
    (root / "pyproject.toml").write_text(
        f'[tool.poetry]\nname = "x"\nversion = "0"\n\n'
        f'[[tool.poetry.source]]\nname = "{name}"\nurl = "{url}"\n{priority_line}',
        encoding="utf-8",
    )


GATE_INDEX_URL = "https://index.pkgwarden.com/resolution/simple/"


def test_python_manager_writes_netrc_with_restrictive_permissions(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    netrc = runner_temp / "pkgwarden.netrc"
    assert netrc.read_text(encoding="utf-8") == (
        f"machine index.pkgwarden.com login {GATE_TOKEN} password x\n"
    )
    assert stat.S_IMODE(netrc.stat().st_mode) == 0o600


def test_npm_manager_writes_npmrc_with_scoped_auth_token(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    npmrc = (runner_temp / "pkgwarden.npmrc").read_text(encoding="utf-8")
    assert "registry=https://index.pkgwarden.com/resolution/npm/\n" in npmrc
    assert f"//index.pkgwarden.com/resolution/npm/:_authToken={GATE_TOKEN}\n" in npmrc


def test_github_env_gets_every_variable_for_both_ecosystems(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    github_env = tmp_path / "github.env"
    github_env.write_text("PRE_EXISTING=1\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    variables = _env_lines(github_env)
    assert variables["PRE_EXISTING"] == "1"
    assert variables["NETRC"] == str(runner_temp / "pkgwarden.netrc")
    assert variables["UV_DEFAULT_INDEX"] == "https://index.pkgwarden.com/resolution/simple/"
    assert variables["PIP_INDEX_URL"] == "https://index.pkgwarden.com/resolution/simple/"
    assert variables["NPM_CONFIG_USERCONFIG"] == str(runner_temp / "pkgwarden.npmrc")


def test_without_github_env_prints_evaluable_exports(project: Path) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "export UV_DEFAULT_INDEX=https://index.pkgwarden.com/resolution/simple/" in (
        result.stdout
    )
    assert "export NETRC=" in result.stdout


def test_yarn_classic_also_gets_registry_server(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "yarn.lock").write_text("", encoding="utf-8")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    variables = _env_lines(github_env)
    assert variables["YARN_NPM_REGISTRY_SERVER"] == "https://index.pkgwarden.com/resolution/npm"


def test_yarn_berry_is_reported_unsupported_and_not_configured(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "yarn.lock").write_text("", encoding="utf-8")
    (project / ".yarnrc.yml").write_text("nodeLinker: node-modules\n", encoding="utf-8")
    (project / "uv.lock").write_text("", encoding="utf-8")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "yarn" in result.stderr.lower()
    assert "YARN_NPM_REGISTRY_SERVER" not in _env_lines(github_env)


def test_poetry_only_project_is_unsupported_and_exits_nonzero(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr
    assert GATE_INDEX_URL in result.stderr


def test_poetry_lockless_project_without_gate_source_exits_nonzero_with_no_uv_pip_env(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr
    variables = _env_lines(github_env)
    assert "UV_DEFAULT_INDEX" not in variables
    assert "PIP_INDEX_URL" not in variables


def test_poetry_gate_source_supplemental_priority_still_fails(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "supplemental")
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr


def test_poetry_gate_source_missing_priority_is_accepted(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, None)
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _env_lines(github_env)["POETRY_HTTP_BASIC_GATE_USERNAME"] == GATE_TOKEN


def test_poetry_configured_source_writes_basic_auth_env_to_github_env(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "primary")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    variables = _env_lines(github_env)
    assert variables["POETRY_HTTP_BASIC_GATE_USERNAME"] == GATE_TOKEN
    assert variables["POETRY_HTTP_BASIC_GATE_PASSWORD"] == ""
    assert "poetry" in result.stderr.lower()


def test_poetry_configured_source_without_github_env_reads_token_from_file(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "primary")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    token_path = runner_temp / "pkgwarden.token"
    export_line = next(
        line for line in result.stdout.splitlines() if "POETRY_HTTP_BASIC_GATE_USERNAME" in line
    )
    assert export_line == f'export POETRY_HTTP_BASIC_GATE_USERNAME="$(cat {token_path})"'
    assert token_path.read_text(encoding="utf-8") == GATE_TOKEN
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert GATE_TOKEN not in result.stdout
    assert GATE_TOKEN not in result.stderr


def test_poetry_source_name_drives_the_env_key_fragment(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "pkgwarden", GATE_INDEX_URL, "primary")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _env_lines(github_env)["POETRY_HTTP_BASIC_PKGWARDEN_USERNAME"] == GATE_TOKEN


def test_poetry_alongside_unconfigured_still_fails(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr


def test_poetry_alongside_supported_manager_both_succeed(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "primary")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    variables = _env_lines(github_env)
    assert variables["POETRY_HTTP_BASIC_GATE_USERNAME"] == GATE_TOKEN
    assert "NPM_CONFIG_USERCONFIG" in variables
    assert "poetry" in result.stderr.lower()
    assert "pnpm" in result.stderr.lower()


def test_no_manager_detected_exits_nonzero(project: Path) -> None:
    result = _run()
    assert result.exit_code == 1
    assert "no supported package manager" in result.stderr.lower()


def test_missing_token_exits_with_actionable_message(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.delenv("PKGWARDEN_GATE_TOKEN")
    result = _run()
    assert result.exit_code == 1
    assert "PKGWARDEN_GATE_TOKEN" in result.stderr


def test_token_never_appears_in_output(project: Path, tmp_path: Path, monkeypatch) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert GATE_TOKEN not in result.stdout + result.stderr


def test_token_never_appears_in_output_with_poetry_configured(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "primary")
    _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert GATE_TOKEN not in result.stdout + result.stderr


def test_config_files_default_to_user_config_home_without_runner_temp(project: Path) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    expected = Path.home() / ".config" / "pkgwarden" / "ci" / "pkgwarden.netrc"
    assert expected.is_file()
    assert f"export NETRC={expected}" in result.stdout


def test_enterprise_mode_uses_bare_simple_index(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / ".pkgwarden.toml").write_text(
        'api_url = "https://ent.customer.test/api/v1"\nmode = "enterprise"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_MIRROR_TOKEN", "pyf_mirror_tok")
    (project / "uv.lock").write_text("", encoding="utf-8")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _env_lines(github_env)["UV_DEFAULT_INDEX"] == "https://ent.customer.test/simple/"


def test_netrc_is_never_created_world_readable(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    previous_umask = os.umask(0o000)
    try:
        result = _run()
    finally:
        os.umask(previous_umask)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert stat.S_IMODE((runner_temp / "pkgwarden.netrc").stat().st_mode) == 0o600


def test_credential_files_do_not_follow_a_pre_existing_symlink(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    (project / "uv.lock").write_text("", encoding="utf-8")
    victim = tmp_path / "victim"
    victim.write_text("untouched\n", encoding="utf-8")
    (runner_temp / "pkgwarden.netrc").symlink_to(victim)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    netrc = runner_temp / "pkgwarden.netrc"
    assert not netrc.is_symlink()
    assert GATE_TOKEN in netrc.read_text(encoding="utf-8")


def test_export_lines_quote_values_containing_shell_metacharacters(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    runner_temp = tmp_path / "runner temp; echo pwned"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    exported = shlex.split(
        next(line for line in result.stdout.splitlines() if line.startswith("export NETRC="))
    )
    assert exported == ["export", f"NETRC={runner_temp / 'pkgwarden.netrc'}"]


def test_unwritable_github_env_fails_loudly(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "missing-dir" / "github.env"))
    result = _run()
    assert result.exit_code == 1
    assert "GITHUB_ENV" in result.stderr


def test_env_value_with_a_newline_is_rejected_instead_of_injecting(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    runner_temp = tmp_path / "runner\ntemp"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 1
    assert "newline" in result.stderr.lower()
    assert github_env.read_text(encoding="utf-8") == ""


def test_mode_unset_warns_that_the_gate_index_path_is_not_used(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / ".pkgwarden.toml").write_text(
        'api_url = "https://index.pkgwarden.com/api/v1"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PKGWARDEN_MIRROR_TOKEN", "pyf_mirror_tok")
    (project / "uv.lock").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "mode" in result.stderr.lower()
    assert "export UV_DEFAULT_INDEX=https://index.pkgwarden.com/simple/" in result.stdout


def test_api_url_without_a_host_is_rejected(project: Path) -> None:
    (project / ".pkgwarden.toml").write_text(
        'api_url = "not-a-url"\nmode = "gate"\n', encoding="utf-8"
    )
    (project / "uv.lock").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 1
    assert "not-a-url" in result.stderr


def test_summary_lists_configured_managers(project: Path) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "uv" in result.stderr
    assert "pnpm" in result.stderr


def test_poetry_lookalike_gate_url_is_not_accepted_as_the_gate(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(
        project, "gate", "https://index.pkgwarden.com.evil.test/resolution/simple/", "primary"
    )
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr
    assert GATE_TOKEN not in result.stdout + result.stderr


def test_poetry_second_resolvable_source_alongside_the_gate_fails(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\n\n'
        f'[[tool.poetry.source]]\nname = "gate"\nurl = "{GATE_INDEX_URL}"\n'
        'priority = "primary"\n\n'
        '[[tool.poetry.source]]\nname = "public"\nurl = "https://pypi.org/simple/"\n'
        'priority = "supplemental"\n',
        encoding="utf-8",
    )
    result = _run()
    assert result.exit_code == 1
    assert "public" in result.stderr
    assert 'priority = "explicit"' in result.stderr
    assert GATE_TOKEN not in result.stdout + result.stderr


def test_poetry_explicit_extra_source_alongside_the_gate_succeeds(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\n\n'
        f'[[tool.poetry.source]]\nname = "gate"\nurl = "{GATE_INDEX_URL}"\n'
        'priority = "primary"\n\n'
        '[[tool.poetry.source]]\nname = "torch"\nurl = "https://download.pytorch.org/whl/"\n'
        'priority = "explicit"\n',
        encoding="utf-8",
    )
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _env_lines(github_env)["POETRY_HTTP_BASIC_GATE_USERNAME"] == GATE_TOKEN


def test_uv_lockfile_with_a_leftover_poetry_table_still_requires_a_gate_source(
    project: Path,
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr


def test_ci_setup_plan_rejects_secret_env_without_a_token_file() -> None:
    with pytest.raises(ValidationError):
        CiSetupPlan(
            configured=["poetry"],
            unsupported=[],
            env={},
            secret_env={"POETRY_HTTP_BASIC_GATE_USERNAME": "tok"},
        )


def test_poetry_legacy_default_priority_qualifies(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "default")
    github_env = tmp_path / "github.env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _env_lines(github_env)["POETRY_HTTP_BASIC_GATE_USERNAME"] == GATE_TOKEN


def test_poetry_legacy_secondary_priority_does_not_qualify(project: Path) -> None:
    (project / "poetry.lock").write_text("", encoding="utf-8")
    _write_poetry_pyproject(project, "gate", GATE_INDEX_URL, "secondary")
    result = _run()
    assert result.exit_code == 1
    assert "[[tool.poetry.source]]" in result.stderr


def test_pnpm_npmrc_carries_the_client_pacing_settings(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    lines = (runner_temp / "pkgwarden.npmrc").read_text(encoding="utf-8").splitlines()
    assert f"//index.pkgwarden.com/resolution/npm/:_authToken={GATE_TOKEN}" in lines
    assert lines[-4:] == [
        "network-concurrency=8",
        "fetch-retries=5",
        "fetch-retry-mintimeout=2000",
        "fetch-retry-maxtimeout=60000",
    ]


def test_npm_npmrc_paces_with_the_key_npm_itself_knows(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """npm warns "Unknown user config" on pnpm's ``network-concurrency`` and announces that it
    will stop working, so an npm-only project gets ``maxsockets`` instead."""
    (project / "package-lock.json").write_text("{}", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    lines = (runner_temp / "pkgwarden.npmrc").read_text(encoding="utf-8").splitlines()
    assert lines[-4:] == [
        "maxsockets=8",
        "fetch-retries=5",
        "fetch-retry-mintimeout=2000",
        "fetch-retry-maxtimeout=60000",
    ]


def test_npmrc_paces_both_clients_when_both_lockfiles_are_present(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "package-lock.json").write_text("{}", encoding="utf-8")
    (project / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    runner_temp = _runner_temp(tmp_path, monkeypatch)
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    lines = (runner_temp / "pkgwarden.npmrc").read_text(encoding="utf-8").splitlines()
    assert "maxsockets=8" in lines
    assert "network-concurrency=8" in lines


def test_python_env_asks_uv_and_pip_to_retry(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "uv.lock").write_text("", encoding="utf-8")
    _runner_temp(tmp_path, monkeypatch)
    github_env = tmp_path / "github.env"
    github_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    result = _run()
    assert result.exit_code == 0, result.stdout + result.stderr
    variables = _env_lines(github_env)
    assert variables["UV_HTTP_RETRIES"] == "5"
    assert variables["PIP_RETRIES"] == "5"
    assert variables["UV_DEFAULT_INDEX"] == GATE_INDEX_URL
    assert variables["PIP_INDEX_URL"] == GATE_INDEX_URL
    assert "NETRC" in variables

from pathlib import Path

import pytest

from pkgwarden_cli.package_manager import (
    ManagerDetection,
    add_command,
    detect_managers,
    ecosystem_for_manager,
    lock_command,
    lockfile_for_manager,
    manifest_write_command,
    sync_command,
)


def test_detect_uv_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = detect_managers(tmp_path)
    assert "uv" in [d.manager for d in result]
    uv = next(d for d in result if d.manager == "uv")
    assert uv.ecosystem == "pypi"


def test_detect_poetry_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = detect_managers(tmp_path)
    assert any(d.manager == "poetry" for d in result)


def test_detect_pip_from_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    result = detect_managers(tmp_path)
    assert any(d.manager == "pip" for d in result)


def test_detect_pnpm_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    result = detect_managers(tmp_path)
    pnpm = next(d for d in result if d.manager == "pnpm")
    assert pnpm.ecosystem == "npm"


def test_detect_npm_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    result = detect_managers(tmp_path)
    assert any(d.manager == "npm" for d in result)


def test_detect_yarn_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    result = detect_managers(tmp_path)
    assert any(d.manager == "yarn" for d in result)


def test_detect_empty_when_no_markers(tmp_path: Path) -> None:
    assert detect_managers(tmp_path) == []


def test_detect_multiple_managers(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    result = detect_managers(tmp_path)
    managers = {d.manager for d in result}
    assert managers == {"uv", "pnpm"}


def test_detect_prefers_lockfile_over_bare_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv]\n", encoding="utf-8")
    result = detect_managers(tmp_path)
    uv = next(d for d in result if d.manager == "uv")
    assert isinstance(uv, ManagerDetection)


def test_sync_command_uv() -> None:
    assert sync_command("uv") == ["uv", "sync"]


def test_sync_command_pnpm() -> None:
    assert sync_command("pnpm") == ["pnpm", "install"]


def test_sync_command_poetry() -> None:
    assert sync_command("poetry") == ["poetry", "install"]


def test_sync_command_pip() -> None:
    assert sync_command("pip") == ["pip", "install", "-r", "requirements.txt"]


def test_sync_command_npm() -> None:
    assert sync_command("npm") == ["npm", "install"]


def test_sync_command_yarn() -> None:
    assert sync_command("yarn") == ["yarn", "install"]


def test_add_command_uv() -> None:
    assert add_command("uv", ["httpx"]) == ["uv", "add", "httpx"]


def test_add_command_uv_multi_and_dev() -> None:
    assert add_command("uv", ["a==1", "b==2"], dev=True) == ["uv", "add", "--dev", "a==1", "b==2"]


def test_add_command_uv_named_group() -> None:
    assert add_command("uv", ["pytest==8.3.4"], group="test") == [
        "uv",
        "add",
        "--group",
        "test",
        "pytest==8.3.4",
    ]


def test_add_command_npm_dev_uses_save_dev() -> None:
    assert add_command("npm", ["chalk@5.3.0"], dev=True) == [
        "npm",
        "install",
        "--save-dev",
        "chalk@5.3.0",
    ]


def test_add_command_pip_rejects_groups() -> None:
    with pytest.raises(ValueError, match="pip"):
        add_command("pip", ["httpx"], dev=True)


def test_manifest_write_command_uv_only() -> None:
    assert manifest_write_command("uv", ["httpx==0.27.0"], dev=True) == [
        "uv",
        "add",
        "--frozen",
        "--dev",
        "httpx==0.27.0",
    ]
    assert manifest_write_command("poetry", ["httpx==0.27.0"]) is None


def test_add_command_pnpm() -> None:
    assert add_command("pnpm", ["lodash"]) == ["pnpm", "add", "lodash"]


def test_add_command_poetry() -> None:
    assert add_command("poetry", ["httpx"]) == ["poetry", "add", "httpx"]


def test_add_command_pip_uses_install() -> None:
    assert add_command("pip", ["httpx"]) == ["pip", "install", "httpx"]


def test_lock_command_uv() -> None:
    assert lock_command("uv") == ["uv", "lock"]


def test_lock_command_pnpm_uses_install_lock_only() -> None:
    assert lock_command("pnpm") == ["pnpm", "install", "--lockfile-only"]


def test_lockfile_paths() -> None:
    assert lockfile_for_manager("uv") == "uv.lock"
    assert lockfile_for_manager("poetry") == "poetry.lock"
    assert lockfile_for_manager("pip") == "requirements.txt"
    assert lockfile_for_manager("pnpm") == "pnpm-lock.yaml"
    assert lockfile_for_manager("npm") == "package-lock.json"
    assert lockfile_for_manager("yarn") == "yarn.lock"


def test_ecosystem_mappings() -> None:
    assert ecosystem_for_manager("uv") == "pypi"
    assert ecosystem_for_manager("poetry") == "pypi"
    assert ecosystem_for_manager("pip") == "pypi"
    assert ecosystem_for_manager("pnpm") == "npm"
    assert ecosystem_for_manager("npm") == "npm"
    assert ecosystem_for_manager("yarn") == "npm"

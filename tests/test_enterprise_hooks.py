from collections.abc import Iterator
from pathlib import Path

import pytest

from pkgwarden_cli import enterprise_hooks
from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.runtime import CliRuntime


@pytest.fixture(autouse=True)
def reset_hooks() -> Iterator[None]:
    enterprise_hooks.reset()
    yield
    enterprise_hooks.reset()


def _runtime() -> CliRuntime:
    return CliRuntime(
        config=CliConfig(api_base="https://ent.test/api/v1", mode="enterprise"),
        json_output=False,
        timeout=1.0,
    )


def test_sync_fallback_returns_none_by_default(tmp_path: Path) -> None:
    assert enterprise_hooks.get_sync_fallback() is None


def test_register_sync_fallback_roundtrip(tmp_path: Path) -> None:
    def fallback(runtime: CliRuntime, manager: str, cwd: Path) -> bool:
        return True

    enterprise_hooks.register_sync_fallback(fallback)
    resolved = enterprise_hooks.get_sync_fallback()
    assert resolved is fallback
    assert fallback(_runtime(), "uv", tmp_path) is True


def test_add_fallback_returns_none_by_default() -> None:
    assert enterprise_hooks.get_add_fallback() is None


def test_register_add_fallback_roundtrip(tmp_path: Path) -> None:
    def fallback(runtime: CliRuntime, manager: str, package: str, version: str) -> bool:
        return version == "0.27.0"

    enterprise_hooks.register_add_fallback(fallback)
    resolved = enterprise_hooks.get_add_fallback()
    assert resolved is fallback
    assert fallback(_runtime(), "uv", "httpx", "0.27.0") is True


def test_reset_clears_registrations() -> None:
    def sync_fb(runtime: CliRuntime, manager: str, cwd: Path) -> bool:
        return False

    def add_fb(runtime: CliRuntime, manager: str, package: str, version: str) -> bool:
        return False

    enterprise_hooks.register_sync_fallback(sync_fb)
    enterprise_hooks.register_add_fallback(add_fb)
    enterprise_hooks.reset()
    assert enterprise_hooks.get_sync_fallback() is None
    assert enterprise_hooks.get_add_fallback() is None


def test_register_twice_overrides_previous() -> None:
    def first(runtime: CliRuntime, manager: str, cwd: Path) -> bool:
        return True

    def second(runtime: CliRuntime, manager: str, cwd: Path) -> bool:
        return False

    enterprise_hooks.register_sync_fallback(first)
    enterprise_hooks.register_sync_fallback(second)
    fallback = enterprise_hooks.get_sync_fallback()
    assert fallback is second

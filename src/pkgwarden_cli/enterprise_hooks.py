from collections.abc import Callable
from pathlib import Path

from pkgwarden_cli.runtime import CliRuntime

SyncFallback = Callable[[CliRuntime, str, Path], bool]
AddFallback = Callable[[CliRuntime, str, str, str], bool]
ResolutionInsightsImpl = Callable[[CliRuntime, str, str], None]

_sync_fallback: SyncFallback | None = None
_add_fallback: AddFallback | None = None
_resolution_insights_impl: ResolutionInsightsImpl | None = None


def register_sync_fallback(fallback: SyncFallback) -> None:
    global _sync_fallback
    _sync_fallback = fallback


def get_sync_fallback() -> SyncFallback | None:
    return _sync_fallback


def register_add_fallback(fallback: AddFallback) -> None:
    global _add_fallback
    _add_fallback = fallback


def get_add_fallback() -> AddFallback | None:
    return _add_fallback


def register_resolution_insights_impl(impl: ResolutionInsightsImpl) -> None:
    global _resolution_insights_impl
    _resolution_insights_impl = impl


def get_resolution_insights_impl() -> ResolutionInsightsImpl | None:
    return _resolution_insights_impl


def reset() -> None:
    global _sync_fallback, _add_fallback, _resolution_insights_impl
    _sync_fallback = None
    _add_fallback = None
    _resolution_insights_impl = None

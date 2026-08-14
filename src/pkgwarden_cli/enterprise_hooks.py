from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.spec import ParsedSpec

ALREADY_AVAILABLE_STATUS = "already_available"
DUPLICATE_PENDING_STATUS = "duplicate_pending"
VERSION_TOO_YOUNG_STATUS = "version_too_young"


class EnterpriseAddOutcome(BaseModel):
    package: str
    version: str
    status: str
    request_id: str | None = None
    request_group_id: str | None = None
    linked_exception_request_count: int = 0
    project_name: str | None = None
    web_url: str | None = None
    blocking_status: str | None = None
    conflict_message: str | None = None


SyncFallback = Callable[[CliRuntime, str, Path], bool]
AddFallback = Callable[[CliRuntime, str, str, str, list[str]], EnterpriseAddOutcome | None]
AddNativeSkipCheck = Callable[[CliRuntime, str, list[ParsedSpec]], bool]
ResolutionInsightsImpl = Callable[[CliRuntime, str, str], None]
WhyBlockedImpl = Callable[[CliRuntime, str, str, str], None]

_sync_fallback: SyncFallback | None = None
_add_fallback: AddFallback | None = None
_add_native_skip_check: AddNativeSkipCheck | None = None
_resolution_insights_impl: ResolutionInsightsImpl | None = None
_why_blocked_impl: WhyBlockedImpl | None = None


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


def register_add_native_skip_check(check: AddNativeSkipCheck) -> None:
    global _add_native_skip_check
    _add_native_skip_check = check


def get_add_native_skip_check() -> AddNativeSkipCheck | None:
    return _add_native_skip_check


def register_resolution_insights_impl(impl: ResolutionInsightsImpl) -> None:
    global _resolution_insights_impl
    _resolution_insights_impl = impl


def get_resolution_insights_impl() -> ResolutionInsightsImpl | None:
    return _resolution_insights_impl


def register_why_blocked_impl(impl: WhyBlockedImpl) -> None:
    global _why_blocked_impl
    _why_blocked_impl = impl


def get_why_blocked_impl() -> WhyBlockedImpl | None:
    return _why_blocked_impl


def reset() -> None:
    global _sync_fallback, _add_fallback, _add_native_skip_check
    global _resolution_insights_impl, _why_blocked_impl
    _sync_fallback = None
    _add_fallback = None
    _add_native_skip_check = None
    _resolution_insights_impl = None
    _why_blocked_impl = None

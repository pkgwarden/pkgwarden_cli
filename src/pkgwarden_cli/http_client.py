from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.urls import mirror_origin_from_api_base, simple_index_url

_LOCATION_CONTAINER_SEGMENTS = {"body", "query", "path", "header", "cookie"}


class FastApiValidationError(BaseModel):
    """One entry of a FastAPI/pydantic 422 `detail` list."""

    loc: list[str | int]
    msg: str
    type: str


def _field_path(loc: list[str | int]) -> str:
    segments = loc[1:] if loc and loc[0] in _LOCATION_CONTAINER_SEGMENTS else loc
    return ".".join(str(segment) for segment in segments) if segments else "request"


def _parse_validation_errors(detail: object) -> list[FastApiValidationError] | None:
    if not isinstance(detail, list) or not detail:
        return None
    try:
        return [FastApiValidationError.model_validate(item) for item in detail]
    except ValidationError:
        return None


def _render_validation_errors(errors: list[FastApiValidationError]) -> str:
    lines = (f"  - {_field_path(error.loc)}: {error.msg}" for error in errors)
    return "Validation error:\n" + "\n".join(lines)


def build_api_client(
    *,
    api_base: str,
    bearer_token: str,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        base_url=api_base.rstrip("/") + "/",
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
        transport=transport,
    )


def build_gate_resolution_client(
    *,
    api_base: str,
    bearer_token: str,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    origin = mirror_origin_from_api_base(api_base)
    return httpx.Client(
        base_url=origin.rstrip("/") + "/",
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=timeout,
        transport=transport,
    )


def build_mirror_client(
    *,
    config: CliConfig,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        base_url=mirror_index_url(config),
        auth=(mirror_basic_username(config), ""),
        timeout=timeout,
        transport=transport,
    )


def http_error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body: Any = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
            if isinstance(detail, str):
                return detail
            validation_errors = _parse_validation_errors(detail)
            if validation_errors is not None:
                return _render_validation_errors(validation_errors)
            return str(detail)
    except ValueError:
        pass
    return exc.response.text or str(exc)


def requests_bearer_token(config: CliConfig) -> str:
    if config.project_token:
        return config.project_token
    if config.user_token:
        return config.user_token
    raise ValueError(
        "Set PKGWARDEN_PROJECT_TOKEN or PKGWARDEN_USER_TOKEN for /requests "
        "(optional PKGWARDEN_PROJECT_ID when you want the CLI to send an explicit project_id)",
    )


def user_bearer_token(config: CliConfig) -> str:
    if not config.user_token:
        raise ValueError(
            "This command requires PKGWARDEN_USER_TOKEN (personal API token from Settings)",
        )
    return config.user_token


def gate_bearer_token(config: CliConfig) -> str:
    if not config.gate_token:
        raise ValueError(
            "This command requires PKGWARDEN_GATE_TOKEN "
            "(gate resolution API token from gate Settings)",
        )
    return config.gate_token


def mirror_basic_username(config: CliConfig) -> str:
    """Token used as the Basic-auth username against the PEP 503 index.

    Gate validates its own resolution tokens the same way, so gate deployments can
    authenticate with PKGWARDEN_GATE_TOKEN alone.
    """
    token = config.mirror_token or config.project_token
    if not token and config.mode == "gate":
        token = config.gate_token
    if token:
        return token
    accepted = "PKGWARDEN_MIRROR_TOKEN or PKGWARDEN_PROJECT_TOKEN"
    if config.mode == "gate":
        accepted = f"{accepted} or PKGWARDEN_GATE_TOKEN"
    raise ValueError(f"Set {accepted} to authenticate against the package index")


def mirror_index_url(config: CliConfig) -> str:
    return simple_index_url(config.api_base, config.mode)

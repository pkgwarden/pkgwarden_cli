from typing import Any

import httpx

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.urls import mirror_origin_from_api_base


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


def build_tape_resolution_client(
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


def http_error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body: Any = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
            if isinstance(detail, str):
                return detail
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


def tape_bearer_token(config: CliConfig) -> str:
    if not config.tape_token:
        raise ValueError(
            "This command requires PKGWARDEN_TAPE_TOKEN "
            "(tape resolution API token from tape Settings)",
        )
    return config.tape_token


def mirror_basic_username(config: CliConfig) -> str:
    token = config.mirror_token or config.project_token
    if not token:
        raise ValueError(
            "Set PKGWARDEN_MIRROR_TOKEN or PKGWARDEN_PROJECT_TOKEN for mirror instructions",
        )
    return token


def mirror_index_url(config: CliConfig) -> str:
    return f"{mirror_origin_from_api_base(config.api_base)}/simple/"

import httpx
import pytest

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.http_client import (
    build_api_client,
    build_tape_resolution_client,
    http_error_message,
    tape_bearer_token,
)


def test_build_api_client_authorization_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"path": str(request.url)})

    client = build_api_client(
        api_base="https://example.com/api/v1",
        bearer_token="pyf_test",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )
    response = client.get("/requests", params={"limit": 1})
    assert response.status_code == 200
    assert captured[0].headers["authorization"] == "Bearer pyf_test"
    assert "/api/v1/requests" in response.json()["path"]


def test_http_error_message_json_detail() -> None:
    client = build_api_client(
        api_base="https://example.com/api/v1",
        bearer_token="t",
        timeout=1.0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(400, json={"detail": "bad input"})
        ),
    )
    try:
        client.get("/x")
    except httpx.HTTPStatusError as exc:
        assert http_error_message(exc) == "bad input"


def test_build_tape_resolution_client_uses_mirror_origin() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"path": str(request.url)})

    client = build_tape_resolution_client(
        api_base="https://example.com/api/v1",
        bearer_token="tape_t",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )
    response = client.get("/resolution/insights/pypi/foo")
    assert response.status_code == 200
    assert captured[0].headers["authorization"] == "Bearer tape_t"
    assert response.json()["path"] == "https://example.com/resolution/insights/pypi/foo"


def test_tape_bearer_token_returns_config_value() -> None:
    cfg = CliConfig(api_base="https://x/api/v1", tape_token="pyf_tape")
    assert tape_bearer_token(cfg) == "pyf_tape"


def test_tape_bearer_token_missing_raises() -> None:
    cfg = CliConfig(api_base="https://x/api/v1", tape_token=None)
    with pytest.raises(ValueError, match="PKGWARDEN_TAPE_TOKEN"):
        tape_bearer_token(cfg)


def test_http_error_message_non_json_body() -> None:
    client = build_api_client(
        api_base="https://example.com/api/v1",
        bearer_token="t",
        timeout=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, text="plain")),
    )
    try:
        client.get("/x")
    except httpx.HTTPStatusError as exc:
        assert http_error_message(exc) == "plain"

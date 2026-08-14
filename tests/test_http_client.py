import httpx
import pytest

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.http_client import (
    build_api_client,
    build_gate_resolution_client,
    gate_bearer_token,
    http_error_message,
    mirror_basic_username,
    mirror_index_url,
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
        client.get("/x").raise_for_status()
        raise AssertionError("expected HTTPStatusError")
    except httpx.HTTPStatusError as exc:
        assert http_error_message(exc) == "bad input"


def test_build_gate_resolution_client_uses_mirror_origin() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"path": str(request.url)})

    client = build_gate_resolution_client(
        api_base="https://example.com/api/v1",
        bearer_token="gate_t",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )
    response = client.get("/resolution/insights/pypi/foo")
    assert response.status_code == 200
    assert captured[0].headers["authorization"] == "Bearer gate_t"
    assert response.json()["path"] == "https://example.com/resolution/insights/pypi/foo"


def test_gate_bearer_token_returns_config_value() -> None:
    cfg = CliConfig(api_base="https://x/api/v1", gate_token="pyf_gate")
    assert gate_bearer_token(cfg) == "pyf_gate"


def test_gate_bearer_token_missing_raises() -> None:
    cfg = CliConfig(api_base="https://x/api/v1", gate_token=None)
    with pytest.raises(ValueError, match="PKGWARDEN_GATE_TOKEN"):
        gate_bearer_token(cfg)


def test_mirror_index_url_gate_mode_uses_resolution_prefix() -> None:
    cfg = CliConfig(api_base="https://gate.test/api/v1", mode="gate", mirror_token="t")
    assert mirror_index_url(cfg) == "https://gate.test/resolution/simple/"


def test_mirror_index_url_enterprise_mode_unchanged() -> None:
    cfg = CliConfig(api_base="https://ent.test/api/v1", mode="enterprise", mirror_token="t")
    assert mirror_index_url(cfg) == "https://ent.test/simple/"


def test_mirror_basic_username_prefers_mirror_token() -> None:
    cfg = CliConfig(
        api_base="https://gate.test/api/v1",
        mode="gate",
        mirror_token="mirror_t",
        project_token="proj_t",
        gate_token="gate_t",
    )
    assert mirror_basic_username(cfg) == "mirror_t"


def test_mirror_basic_username_gate_mode_falls_back_to_gate_token() -> None:
    cfg = CliConfig(api_base="https://gate.test/api/v1", mode="gate", gate_token="gate_t")
    assert mirror_basic_username(cfg) == "gate_t"


def test_mirror_basic_username_gate_mode_prefers_project_token_over_gate_token() -> None:
    cfg = CliConfig(
        api_base="https://gate.test/api/v1",
        mode="gate",
        project_token="proj_t",
        gate_token="gate_t",
    )
    assert mirror_basic_username(cfg) == "proj_t"


def test_mirror_basic_username_enterprise_mode_ignores_gate_token() -> None:
    cfg = CliConfig(api_base="https://ent.test/api/v1", mode="enterprise", gate_token="gate_t")
    with pytest.raises(ValueError, match="PKGWARDEN_MIRROR_TOKEN"):
        mirror_basic_username(cfg)


def test_mirror_basic_username_gate_mode_error_mentions_gate_token() -> None:
    cfg = CliConfig(api_base="https://gate.test/api/v1", mode="gate")
    with pytest.raises(ValueError, match="PKGWARDEN_GATE_TOKEN"):
        mirror_basic_username(cfg)


def test_http_error_message_non_json_body() -> None:
    client = build_api_client(
        api_base="https://example.com/api/v1",
        bearer_token="t",
        timeout=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, text="plain")),
    )
    try:
        client.get("/x").raise_for_status()
        raise AssertionError("expected HTTPStatusError")
    except httpx.HTTPStatusError as exc:
        assert http_error_message(exc) == "plain"


# Captured verbatim from a real FastAPI/pydantic v2 422 response for an invalid
# `Ecosystem` enum query param (see backend Ecosystem StrEnum + `/approvals` route).
SINGLE_VALIDATION_ERROR_BODY: dict[str, object] = {
    "detail": [
        {
            "type": "enum",
            "loc": ["query", "ecosystem"],
            "msg": "Input should be 'pypi', 'npm', 'vscode', 'pypi_customer' or 'npm_customer'",
            "input": "not_a_real_ecosystem",
            "ctx": {"expected": "'pypi', 'npm', 'vscode', 'pypi_customer' or 'npm_customer'"},
        },
    ],
}

# Captured verbatim from a real FastAPI/pydantic v2 422 response for a request body
# missing a required field alongside a field with the wrong type.
MULTI_VALIDATION_ERROR_BODY: dict[str, object] = {
    "detail": [
        {
            "type": "missing",
            "loc": ["body", "status"],
            "msg": "Field required",
            "input": {"approve_dependencies": "not-a-bool"},
        },
        {
            "type": "bool_parsing",
            "loc": ["body", "approve_dependencies"],
            "msg": "Input should be a valid boolean, unable to interpret input",
            "input": "not-a-bool",
        },
    ],
}


def _http_status_error(status_code: int, body: dict[str, object]) -> httpx.HTTPStatusError:
    client = build_api_client(
        api_base="https://example.com/api/v1",
        bearer_token="t",
        timeout=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(status_code, json=body)),
    )
    try:
        client.get("/x").raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("expected HTTPStatusError")


def test_http_error_message_single_field_validation_error() -> None:
    exc = _http_status_error(422, SINGLE_VALIDATION_ERROR_BODY)
    assert http_error_message(exc) == (
        "Validation error:\n"
        "  - ecosystem: Input should be 'pypi', 'npm', 'vscode', "
        "'pypi_customer' or 'npm_customer'"
    )


def test_http_error_message_multi_field_validation_error() -> None:
    exc = _http_status_error(422, MULTI_VALIDATION_ERROR_BODY)
    assert http_error_message(exc) == (
        "Validation error:\n"
        "  - status: Field required\n"
        "  - approve_dependencies: Input should be a valid boolean, "
        "unable to interpret input"
    )


def test_http_error_message_400_with_validation_shaped_detail_also_renders_clean() -> None:
    """Any 4xx body of this shape should render the same way, not just 422s."""
    exc = _http_status_error(400, SINGLE_VALIDATION_ERROR_BODY)
    assert http_error_message(exc).startswith("Validation error:\n  - ecosystem: ")


def test_http_error_message_list_detail_not_shaped_like_validation_errors_falls_back() -> None:
    exc = _http_status_error(422, {"detail": ["just a plain string", "another one"]})
    assert http_error_message(exc) == "['just a plain string', 'another one']"


def test_http_error_message_keeps_fields_named_like_location_containers() -> None:
    """Only the leading loc segment is a location container; a body field named
    `header` (or `query`, `path`, ...) must not vanish from the rendered path."""
    body: dict[str, object] = {
        "detail": [
            {"type": "missing", "loc": ["body", "header"], "msg": "Field required"},
            {
                "type": "string_type",
                "loc": ["body", "items", 0, "query"],
                "msg": "Input should be a valid string",
            },
        ],
    }
    exc = _http_status_error(422, body)
    assert http_error_message(exc) == (
        "Validation error:\n"
        "  - header: Field required\n"
        "  - items.0.query: Input should be a valid string"
    )


def test_http_error_message_body_without_detail_falls_back_to_text() -> None:
    exc = _http_status_error(422, {"error": "no detail key here"})
    assert http_error_message(exc) == '{"error":"no detail key here"}'


def test_http_error_message_dict_detail_falls_back_to_str() -> None:
    exc = _http_status_error(422, {"detail": {"code": "oops", "hint": "not a list"}})
    assert http_error_message(exc) == "{'code': 'oops', 'hint': 'not a list'}"

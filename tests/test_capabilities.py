import httpx
import pytest
from pydantic import ValidationError

from pkgwarden_cli.capabilities import (
    Capabilities,
    fetch_capabilities,
)


def _make_client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.test/api/v1/",
        transport=httpx.MockTransport(handler),
    )


def test_fetch_capabilities_returns_gate_deployment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/capabilities")
        return httpx.Response(
            200,
            json={
                "deployment_type": "gate",
                "features": ["cve_scan", "why_blocked"],
                "min_cli_version": "0.1.0",
            },
        )

    client = _make_client(handler)
    caps = fetch_capabilities(client)
    assert caps.deployment_type == "gate"
    assert "cve_scan" in caps.features
    assert caps.min_cli_version == "0.1.0"


def test_fetch_capabilities_returns_enterprise_with_plugin_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "deployment_type": "enterprise",
                "features": ["requests", "approvals", "bulk_resolve"],
                "min_cli_version": "0.1.0",
            },
        )

    client = _make_client(handler)
    caps = fetch_capabilities(client)
    assert caps.deployment_type == "enterprise"
    assert caps.supports("bulk_resolve") is True
    assert caps.supports("ghost") is False


def test_fetch_capabilities_handles_unknown_endpoint_as_unknown() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    client = _make_client(handler)
    caps = fetch_capabilities(client)
    assert caps.deployment_type == "unknown"
    assert caps.features == ()


def test_fetch_capabilities_handles_network_errors_as_unknown() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make_client(handler)
    caps = fetch_capabilities(client)
    assert caps.deployment_type == "unknown"


def test_capabilities_rejects_unknown_deployment_type() -> None:
    with pytest.raises(ValidationError):
        Capabilities.model_validate(
            {
                "deployment_type": "other",
                "features": [],
                "min_cli_version": "0.1.0",
            },
        )

from typing import Literal

import httpx
from pydantic import BaseModel, Field

DeploymentType = Literal["tape", "enterprise", "unknown"]


class Capabilities(BaseModel):
    deployment_type: DeploymentType
    features: tuple[str, ...] = Field(default_factory=tuple)
    min_cli_version: str | None = None

    def supports(self, feature: str) -> bool:
        return feature in self.features


_UNKNOWN = Capabilities(deployment_type="unknown")


def fetch_capabilities(client: httpx.Client) -> Capabilities:
    try:
        response = client.get("capabilities")
    except httpx.HTTPError:
        return _UNKNOWN
    if response.status_code != 200:
        return _UNKNOWN
    try:
        payload = response.json()
    except ValueError:
        return _UNKNOWN
    if not isinstance(payload, dict):
        return _UNKNOWN
    deployment = payload.get("deployment_type")
    if deployment not in ("tape", "enterprise"):
        return _UNKNOWN
    return Capabilities.model_validate(payload)

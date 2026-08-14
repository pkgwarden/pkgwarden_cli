"""Deployment mode vocabulary, kept import-free so both config and urls can use it."""

from typing import Literal

CliMode = Literal["gate", "enterprise"]

SUPPORTED_MODES: tuple[CliMode, ...] = ("gate", "enterprise")

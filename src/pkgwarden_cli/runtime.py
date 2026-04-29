from dataclasses import dataclass

from pkgwarden_cli.config import CliConfig


@dataclass(frozen=True)
class CliRuntime:
    config: CliConfig
    json_output: bool
    timeout: float

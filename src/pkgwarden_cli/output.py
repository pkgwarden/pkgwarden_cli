import json
from typing import Any

from pkgwarden_cli.runtime import CliRuntime


def emit(runtime: CliRuntime, human: str, payload: Any) -> None:
    if runtime.json_output:
        print(json.dumps(payload, indent=2, default=str))
        return
    print(human)


def emit_structured(runtime: CliRuntime, payload: Any) -> None:
    text = json.dumps(payload, indent=2, default=str)
    if runtime.json_output:
        print(text)
        return
    print(text)

import json

from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.output import emit_structured
from pkgwarden_cli.runtime import CliRuntime


def test_emit_structured_text_prints_indented_json(capsys) -> None:
    cfg = CliConfig(api_base="https://x/api/v1")
    runtime = CliRuntime(config=cfg, json_output=False, timeout=1.0)
    emit_structured(runtime, {"version": "1"})
    out = capsys.readouterr().out
    assert json.loads(out)["version"] == "1"


def test_emit_structured_json_mode_prints_payload(capsys) -> None:
    cfg = CliConfig(api_base="https://x/api/v1")
    runtime = CliRuntime(config=cfg, json_output=True, timeout=1.0)
    emit_structured(runtime, [1, 2])
    assert json.loads(capsys.readouterr().out) == [1, 2]

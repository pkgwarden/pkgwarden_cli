import sys

import pytest

from ansi import strip_ansi
from pkgwarden_cli import main as main_module


def test_help_usage_line_shows_pw_not_dash_c(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["-c", "--help"])
    with pytest.raises(SystemExit) as exc:
        main_module.main()
    assert exc.value.code == 0
    captured = strip_ansi(capsys.readouterr().out)
    assert "Usage: pw " in captured
    assert "-c" not in captured.splitlines()[1]


def test_subcommand_help_usage_line_shows_pw(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["-c", "vscode", "sync-policy", "--help"])
    with pytest.raises(SystemExit) as exc:
        main_module.main()
    assert exc.value.code == 0
    captured = strip_ansi(capsys.readouterr().out)
    assert "Usage: pw vscode sync-policy " in captured

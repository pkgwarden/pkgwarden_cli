import sys

import pytest

from pkgwarden_cli import main as main_module


def test_version_flag_prints_distribution_line(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pw", "--version"])
    with pytest.raises(SystemExit) as exc:
        main_module.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "pkgwarden-cli" in captured.out

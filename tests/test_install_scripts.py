import subprocess
from pathlib import Path


def test_install_shell_scripts_parse() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("install/install.sh", "install/build_pyapp.sh"):
        script = root / relative
        assert script.is_file(), script
        subprocess.run(
            ["bash", "-n", str(script)],
            check=True,
            capture_output=True,
        )

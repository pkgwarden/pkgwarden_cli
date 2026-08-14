"""The release workflow rewrites install.sh's tag placeholder with `sed s/.../g`, so the
script must not decide "am I pinned?" by comparing against that same placeholder: the
substitution rewrites the comparison too and every released installer rejects itself."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

INSTALL_SCRIPT = Path(__file__).resolve().parents[1] / "install" / "install.sh"
RELEASE_TAG = "pw-v9.9.9"
PLACEHOLDER = "__PW_RELEASE" + "_TAG__"
NOT_PINNED_MESSAGE = "not pinned to a release"


def _released_copy(tmp_path: Path) -> Path:
    """What the release workflow uploads: the placeholder replaced everywhere."""
    pinned = tmp_path / "install.sh"
    pinned.write_text(
        INSTALL_SCRIPT.read_text(encoding="utf-8").replace(PLACEHOLDER, RELEASE_TAG),
        encoding="utf-8",
    )
    pinned.chmod(pinned.stat().st_mode | stat.S_IXUSR)
    return pinned


def _stub_downloader_path(tmp_path: Path) -> Path:
    """A curl that records its arguments and fails, so the script never hits the network."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/curl.log"\nexit 22\n', encoding="utf-8")
    stub.chmod(0o755)
    (bin_dir / "wget").symlink_to(stub)
    return bin_dir


def _run(script: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PKGWARDEN_VERSION", None)
    env["PATH"] = f"{_stub_downloader_path(tmp_path)}:{env['PATH']}"
    return subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, env=env, cwd=tmp_path
    )


def test_source_copy_refuses_to_install_without_a_tag(tmp_path: Path) -> None:
    result = _run(INSTALL_SCRIPT, tmp_path)
    assert result.returncode == 1
    assert NOT_PINNED_MESSAGE in result.stderr
    assert not (tmp_path / "curl.log").exists()


def test_released_copy_downloads_from_its_pinned_tag(tmp_path: Path) -> None:
    result = _run(_released_copy(tmp_path), tmp_path)
    assert NOT_PINNED_MESSAGE not in result.stderr
    requested = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert f"/releases/download/{RELEASE_TAG}/pw-" in requested


def test_placeholder_appears_once_so_substitution_cannot_rewrite_a_comparison() -> None:
    source = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert source.count(PLACEHOLDER) == 1


@pytest.mark.parametrize("asset", ["pw-x86_64-unknown-linux-gnu", "pw-aarch64-apple-darwin"])
def test_documented_asset_names_match_the_names_the_script_builds(asset: str) -> None:
    """install/README.md lists the release assets by name; the script derives them from
    uname, so a rename on either side has to be a deliberate edit to both."""
    source = INSTALL_SCRIPT.read_text(encoding="utf-8")
    architecture, platform = asset.removeprefix("pw-").split("-", 1)
    assert 'ASSET_NAME="pw-${TRIPLE}"' in source
    assert f"echo {architecture}" in source
    assert f'-{platform}"' in source

"""Pick the highest packaging.version from wheels matching a dist glob."""

import argparse
import re
import sys
from pathlib import Path

from packaging.version import Version


def select_latest_wheel(wheels: list[Path], package_prefix: str) -> Path | None:
    best: Path | None = None
    best_version: Version | None = None
    pattern = re.compile(rf"^{re.escape(package_prefix)}-(.+?)-")
    for wheel in wheels:
        match = pattern.match(wheel.name)
        if match is None:
            continue
        try:
            version = Version(match.group(1))
        except ValueError:
            continue
        if best_version is None or version > best_version:
            best = wheel
            best_version = version
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("glob_pattern", help="Wheel filename glob, e.g. pkgwarden_cli-*.whl")
    parser.add_argument("package_prefix", help="Package name prefix before the version segment")
    args = parser.parse_args()
    selected = select_latest_wheel(list(args.dist_dir.glob(args.glob_pattern)), args.package_prefix)
    if selected is None:
        sys.exit(1)
    print(selected.resolve())


if __name__ == "__main__":
    main()

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pkgwarden_cli.config import PackageManager

Ecosystem = Literal["pypi", "npm"]


@dataclass(frozen=True)
class ManagerDetection:
    manager: PackageManager
    ecosystem: Ecosystem
    lockfile: str | None


_LOCKFILES: dict[PackageManager, str] = {
    "uv": "uv.lock",
    "poetry": "poetry.lock",
    "pip": "requirements.txt",
    "pnpm": "pnpm-lock.yaml",
    "npm": "package-lock.json",
    "yarn": "yarn.lock",
}

_ECOSYSTEM: dict[PackageManager, Ecosystem] = {
    "uv": "pypi",
    "poetry": "pypi",
    "pip": "pypi",
    "pnpm": "npm",
    "npm": "npm",
    "yarn": "npm",
}

_DETECTION_ORDER: tuple[PackageManager, ...] = (
    "uv",
    "poetry",
    "pip",
    "pnpm",
    "npm",
    "yarn",
)


def lockfile_for_manager(manager: PackageManager) -> str:
    return _LOCKFILES[manager]


def ecosystem_for_manager(manager: PackageManager) -> Ecosystem:
    return _ECOSYSTEM[manager]


def _present(root: Path, name: str) -> bool:
    return (root / name).is_file()


def _detection_for(root: Path, manager: PackageManager) -> ManagerDetection | None:
    lockfile = _LOCKFILES[manager]
    ecosystem = _ECOSYSTEM[manager]
    if _present(root, lockfile):
        return ManagerDetection(manager=manager, ecosystem=ecosystem, lockfile=lockfile)
    if manager == "uv" and _present(root, "pyproject.toml"):
        return ManagerDetection(manager="uv", ecosystem="pypi", lockfile=None)
    return None


def detect_managers(root: Path) -> list[ManagerDetection]:
    results: list[ManagerDetection] = []
    for manager in _DETECTION_ORDER:
        detection = _detection_for(root, manager)
        if detection is not None:
            results.append(detection)
    return results


def sync_command(manager: PackageManager) -> list[str]:
    match manager:
        case "uv":
            return ["uv", "sync"]
        case "poetry":
            return ["poetry", "install"]
        case "pip":
            return ["pip", "install", "-r", "requirements.txt"]
        case "pnpm":
            return ["pnpm", "install"]
        case "npm":
            return ["npm", "install"]
        case "yarn":
            return ["yarn", "install"]


def _group_flags(manager: PackageManager, dev: bool, group: str | None) -> list[str]:
    if not dev and group is None:
        return []
    match manager:
        case "uv":
            return ["--dev"] if dev else ["--group", str(group)]
        case "poetry":
            return ["--group", "dev" if dev else str(group)]
        case "pnpm" | "npm" | "yarn":
            if group is not None:
                raise ValueError(f"{manager} has no named dependency groups; use --dev")
            return ["--save-dev"]
        case "pip":
            raise ValueError("pip has no dependency groups; drop --dev/--group")


def add_command(
    manager: PackageManager,
    packages: list[str],
    dev: bool = False,
    group: str | None = None,
) -> list[str]:
    flags = _group_flags(manager, dev, group)
    match manager:
        case "uv":
            return ["uv", "add", *flags, *packages]
        case "poetry":
            return ["poetry", "add", *flags, *packages]
        case "pip":
            return ["pip", "install", *packages]
        case "pnpm":
            return ["pnpm", "add", *flags, *packages]
        case "npm":
            return ["npm", "install", *flags, *packages]
        case "yarn":
            return ["yarn", "add", *flags, *packages]


def manifest_write_command(
    manager: PackageManager,
    packages: list[str],
    dev: bool = False,
    group: str | None = None,
) -> list[str] | None:
    """Record intent in the manifest without resolving (uv only)."""
    if manager != "uv":
        return None
    return ["uv", "add", "--frozen", *_group_flags(manager, dev, group), *packages]


def lock_command(manager: PackageManager) -> list[str]:
    match manager:
        case "uv":
            return ["uv", "lock"]
        case "poetry":
            return ["poetry", "lock"]
        case "pip":
            return ["pip", "freeze"]
        case "pnpm":
            return ["pnpm", "install", "--lockfile-only"]
        case "npm":
            return ["npm", "install", "--package-lock-only"]
        case "yarn":
            return ["yarn", "install", "--mode=update-lockfile"]


def remove_command(manager: PackageManager, package: str) -> list[str]:
    match manager:
        case "uv":
            return ["uv", "remove", package]
        case "poetry":
            return ["poetry", "remove", package]
        case "pip":
            return ["pip", "uninstall", "-y", package]
        case "pnpm":
            return ["pnpm", "remove", package]
        case "npm":
            return ["npm", "uninstall", package]
        case "yarn":
            return ["yarn", "remove", package]

from importlib import metadata


def core_distribution_version() -> str:
    return metadata.version("pkgwarden-cli")


def enterprise_distribution_version() -> str | None:
    try:
        return metadata.version("pkgwarden-cli-enterprise")
    except metadata.PackageNotFoundError:
        return None


def format_pw_version_line() -> str:
    core = core_distribution_version()
    enterprise = enterprise_distribution_version()
    if enterprise is None:
        return f"pw: pkgwarden-cli {core} (gate core only)"
    return f"pw: pkgwarden-cli {core}; pkgwarden-cli-enterprise {enterprise}"

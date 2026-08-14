from pkgwarden_cli.modes import CliMode


def normalize_api_base(raw: str) -> str:
    stripped = raw.strip().rstrip("/")
    if stripped.endswith("/api/v1"):
        return stripped
    if stripped.endswith("/api"):
        return f"{stripped}/v1"
    return f"{stripped}/api/v1"


def mirror_origin_from_api_base(api_base: str) -> str:
    base = api_base.rstrip("/")
    suffix = "/api/v1"
    if base.endswith(suffix):
        return base[: -len(suffix)]
    return base


def simple_index_url(api_base: str, mode: CliMode | None) -> str:
    """PEP 503 index root: gate mounts it under /resolution, airgapped at the origin root."""
    origin = mirror_origin_from_api_base(api_base)
    prefix = "/resolution" if mode == "gate" else ""
    return f"{origin}{prefix}/simple/"

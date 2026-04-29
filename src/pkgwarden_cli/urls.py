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

from pkgwarden_cli.urls import mirror_origin_from_api_base, normalize_api_base


def test_normalize_api_base_appends_api_v1() -> None:
    assert normalize_api_base("https://api.example.com") == "https://api.example.com/api/v1"


def test_normalize_api_base_preserves_api_v1() -> None:
    assert normalize_api_base("https://x/api/v1") == "https://x/api/v1"


def test_normalize_api_base_api_suffix() -> None:
    assert normalize_api_base("https://x/api") == "https://x/api/v1"


def test_mirror_origin_from_api_base() -> None:
    assert mirror_origin_from_api_base("https://host/api/v1") == "https://host"

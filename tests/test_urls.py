from pkgwarden_cli.urls import (
    mirror_origin_from_api_base,
    normalize_api_base,
    simple_index_url,
)


def test_normalize_api_base_appends_api_v1() -> None:
    assert normalize_api_base("https://api.example.com") == "https://api.example.com/api/v1"


def test_normalize_api_base_preserves_api_v1() -> None:
    assert normalize_api_base("https://x/api/v1") == "https://x/api/v1"


def test_normalize_api_base_api_suffix() -> None:
    assert normalize_api_base("https://x/api") == "https://x/api/v1"


def test_mirror_origin_from_api_base() -> None:
    assert mirror_origin_from_api_base("https://host/api/v1") == "https://host"


def test_simple_index_url_gate_mode_uses_resolution_prefix() -> None:
    """Gate only mounts /resolution/simple; a bare /simple/ 404s there."""
    assert simple_index_url("https://host/api/v1", "gate") == "https://host/resolution/simple/"


def test_simple_index_url_enterprise_mode_uses_bare_simple() -> None:
    assert simple_index_url("https://host/api/v1", "enterprise") == "https://host/simple/"


def test_simple_index_url_unset_mode_defaults_to_bare_simple() -> None:
    assert simple_index_url("https://host/api/v1", None) == "https://host/simple/"

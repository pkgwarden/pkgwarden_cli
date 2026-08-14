from pathlib import Path

from pkgwarden_cli.init_discovery import (
    build_init_defaults,
    discover_api_url_from_pyproject,
    effective_project_token,
    infer_mode_from_tokens,
    merged_env_for_init,
    parse_dotenv_file,
    registry_url_to_api_base,
)


def test_parse_dotenv_basic(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "PKGWARDEN_API_URL=https://x.test/api/v1\n"
        "export PKGWARDEN_GATE_TOKEN=tok\n"
        "# comment\n"
        'PKGWARDEN_PROJECT_API_TOKEN="proj"\n',
        encoding="utf-8",
    )
    d = parse_dotenv_file(p)
    assert d["PKGWARDEN_API_URL"] == "https://x.test/api/v1"
    assert d["PKGWARDEN_GATE_TOKEN"] == "tok"
    assert d["PKGWARDEN_PROJECT_API_TOKEN"] == "proj"


def test_merged_env_os_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PKGWARDEN_API_URL=https://from-dotenv/api/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PKGWARDEN_API_URL", "https://from-os/api/v1")
    merged = merged_env_for_init(tmp_path)
    assert merged["PKGWARDEN_API_URL"] == "https://from-os/api/v1"


def test_effective_project_token_prefers_canonical_name(monkeypatch) -> None:
    env = {"PKGWARDEN_PROJECT_API_TOKEN": "alias", "PKGWARDEN_PROJECT_TOKEN": "canonical"}
    assert effective_project_token(env) == "canonical"


def test_infer_mode_project_wins_over_gate(monkeypatch) -> None:
    env = {
        "PKGWARDEN_PROJECT_TOKEN": "p",
        "PKGWARDEN_GATE_TOKEN": "t",
    }
    assert infer_mode_from_tokens(env) == "enterprise"


def test_registry_url_to_api_base_from_simple() -> None:
    assert registry_url_to_api_base("https://host.example/simple") == "https://host.example/api/v1"


def test_discover_api_url_from_pyproject_uv_index(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.uv.index]]\nurl = "https://idx.example/simple"\ndefault = true\n',
        encoding="utf-8",
    )
    assert discover_api_url_from_pyproject(tmp_path) == "https://idx.example/api/v1"


def test_build_init_defaults_token_sets_enterprise(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PKGWARDEN_API_URL=https://ent.test/api/v1\nPKGWARDEN_PROJECT_API_TOKEN=pyf_proj\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    merged = merged_env_for_init(tmp_path)
    d = build_init_defaults(
        tmp_path,
        merged,
        api_url_override=None,
        mode_override=None,
        package_manager_override=None,
        project_id_override=None,
    )
    assert d.api_url == "https://ent.test/api/v1"
    assert d.mode == "enterprise"
    assert d.package_manager == "uv"

from pkgwarden_cli import version_info


def test_core_version_is_non_empty() -> None:
    version = version_info.core_distribution_version()
    assert version
    assert version[0].isdigit()


def test_format_pw_version_line_mentions_core() -> None:
    line = version_info.format_pw_version_line()
    assert "pkgwarden-cli" in line

from pkgwarden_cli.vscode_inventory import VscodeInventoryEntry
from pkgwarden_cli.vscode_sync_policy_cli import (
    DryRunPreview,
    _format_dry_run_preview,
    classify_dry_run,
)


def test_classify_dry_run_buckets_with_server_shaped_pin_map() -> None:
    """The gate server emits every inventoried extension id, with [] when blocked."""
    inventory = [
        VscodeInventoryEntry(extension_id="demo.current", current_version="1.2.3"),
        VscodeInventoryEntry(extension_id="demo.pinned-elsewhere", current_version="0.9.0"),
        VscodeInventoryEntry(extension_id="demo.blocked", current_version="2.0.0"),
    ]
    pin_map = {
        "demo.current": ["1.2.3", "1.3.0"],
        "demo.pinned-elsewhere": ["1.0.0", "1.1.0"],
        "demo.blocked": [],
    }

    preview = classify_dry_run(inventory, pin_map, {})

    assert isinstance(preview, DryRunPreview)
    assert [entry.extension_id for entry in preview.allowed_at_current_version] == ["demo.current"]
    assert [entry.extension_id for entry in preview.allowed_but_version_excluded] == [
        "demo.pinned-elsewhere",
    ]
    assert [entry.extension_id for entry in preview.fully_blocked] == ["demo.blocked"]
    assert preview.allowed_but_version_excluded[0].allowed_versions == ["1.0.0", "1.1.0"]
    assert preview.would_be_removed_from_settings == []
    assert preview.settings_diff_skipped is False


def test_classify_dry_run_treats_missing_pin_entry_as_fully_blocked() -> None:
    inventory = [VscodeInventoryEntry(extension_id="demo.unknown", current_version="1.0.0")]
    preview = classify_dry_run(inventory, {}, {})
    assert [entry.extension_id for entry in preview.fully_blocked] == ["demo.unknown"]
    assert preview.allowed_at_current_version == []
    assert preview.allowed_but_version_excluded == []


def test_classify_dry_run_returns_empty_installed_buckets_for_empty_inventory() -> None:
    preview = classify_dry_run([], {}, {})
    assert preview.allowed_at_current_version == []
    assert preview.allowed_but_version_excluded == []
    assert preview.fully_blocked == []


def test_classify_dry_run_reports_settings_entries_the_write_would_remove() -> None:
    """Write mode wholesale-replaces extensions.allowed, so stale entries must surface."""
    inventory = [VscodeInventoryEntry(extension_id="demo.current", current_version="1.2.3")]
    pin_map = {"demo.current": ["1.2.3"]}
    current_settings = {
        "demo.current": ["1.2.3"],
        "demo.stale-manual": ["9.9.9"],
        "demo.other-stale": ["0.1.0"],
    }
    preview = classify_dry_run(inventory, pin_map, current_settings)
    assert preview.would_be_removed_from_settings == ["demo.other-stale", "demo.stale-manual"]
    assert preview.settings_diff_skipped is False


def test_classify_dry_run_removal_diff_keeps_non_list_valued_entries() -> None:
    """VS Code's schema permits boolean/string values; those keys must still diff."""
    current_settings: dict[str, object] = {"github.copilot": True, "demo.stale": "1.0.0"}
    preview = classify_dry_run([], {}, current_settings)
    assert preview.would_be_removed_from_settings == ["demo.stale", "github.copilot"]


def test_classify_dry_run_reports_pins_changed_for_retained_keys() -> None:
    inventory = [
        VscodeInventoryEntry(extension_id="demo.repinned", current_version="1.0.0"),
        VscodeInventoryEntry(extension_id="demo.unchanged", current_version="1.2.3"),
    ]
    pin_map = {"demo.repinned": ["2.0.0"], "demo.unchanged": ["1.2.3"]}
    current_settings: dict[str, object] = {
        "demo.repinned": ["1.0.0"],
        "demo.unchanged": ["1.2.3"],
        "github.copilot": True,
    }
    preview = classify_dry_run(inventory, pin_map, current_settings)
    assert preview.pins_changed == ["demo.repinned"]


def test_classify_dry_run_counts_non_list_current_value_as_pins_changed() -> None:
    preview = classify_dry_run([], {"github.copilot": ["1.0.0"]}, {"github.copilot": True})
    assert preview.pins_changed == ["github.copilot"]
    assert preview.would_be_removed_from_settings == []


def test_classify_dry_run_includes_pin_map_keys_beyond_inventory() -> None:
    inventory = [VscodeInventoryEntry(extension_id="demo.current", current_version="1.2.3")]
    pin_map = {
        "demo.current": ["1.2.3"],
        "demo.org-wide": ["2.0.0"],
        "demo.org-blocked": [],
    }
    preview = classify_dry_run(inventory, pin_map, {})
    allowed = {entry.extension_id: entry for entry in preview.allowed_at_current_version}
    assert set(allowed) == {"demo.current", "demo.org-wide"}
    assert allowed["demo.org-wide"].current_version is None
    assert [entry.extension_id for entry in preview.fully_blocked] == ["demo.org-blocked"]


def test_classify_dry_run_marks_diff_skipped_when_settings_unreadable() -> None:
    preview = classify_dry_run([], {}, None)
    assert preview.settings_diff_skipped is True
    assert preview.would_be_removed_from_settings == []


def test_format_dry_run_preview_renders_pin_targets_as_joined_versions() -> None:
    preview = classify_dry_run(
        [VscodeInventoryEntry(extension_id="demo.pinned", current_version="0.9.0")],
        {"demo.pinned": ["1.0.0", "1.1.0"]},
        {},
    )
    text = _format_dry_run_preview(preview)
    assert "demo.pinned@0.9.0 (would pin to 1.0.0, 1.1.0)" in text
    assert "['1.0.0'" not in text


def test_format_dry_run_preview_renders_removed_and_not_installed_entries() -> None:
    preview = classify_dry_run(
        [],
        {"demo.org-wide": ["2.0.0"]},
        {"demo.stale": ["1.0.0"]},
    )
    text = _format_dry_run_preview(preview)
    assert "demo.org-wide (not installed)" in text
    assert "would be removed from settings.json (1):" in text
    assert "demo.stale" in text


def test_format_dry_run_preview_notes_skipped_settings_diff() -> None:
    text = _format_dry_run_preview(classify_dry_run([], {}, None))
    assert "settings.json could not be read" in text
    assert "would be removed" not in text
    assert "pins changed" not in text


def test_format_dry_run_preview_renders_pins_changed_line() -> None:
    preview = classify_dry_run([], {"demo.repinned": ["2.0.0"]}, {"demo.repinned": ["1.0.0"]})
    text = _format_dry_run_preview(preview)
    assert "pins changed (1):" in text
    assert "demo.repinned" in text


def test_classify_dry_run_handles_publisher_true_allow() -> None:
    """#425: a trusted publisher maps its bare ``publisher`` key to ``True``; installed
    extensions under it are allowed, and the bool key must not crash classification."""
    inventory = [
        VscodeInventoryEntry(extension_id="anysphere.cursor-retrieval", current_version="1.4.0"),
        VscodeInventoryEntry(extension_id="demo.blocked", current_version="2.0.0"),
    ]
    pin_map = {"anysphere": True, "demo.blocked": []}

    preview = classify_dry_run(inventory, pin_map, {})

    allowed_ids = {entry.extension_id for entry in preview.allowed_at_current_version}
    assert "anysphere.cursor-retrieval" in allowed_ids
    assert [entry.extension_id for entry in preview.fully_blocked] == ["demo.blocked"]


def test_classify_dry_run_specific_false_deny_beats_publisher_true_allow() -> None:
    """#425 fail-open guard: the gate emits ``"publisher.extension": false`` to carve a
    malware-marked extension back out of a publisher-wide allow. The preview must show it
    blocked -- a security preview that says "allowed" for a denied extension is a lie."""
    inventory = [
        VscodeInventoryEntry(extension_id="anysphere.cursor-retrieval", current_version="1.4.0"),
        VscodeInventoryEntry(extension_id="anysphere.malicious-fork", current_version="9.9.9"),
    ]
    pin_map = {"anysphere": True, "anysphere.malicious-fork": False}

    preview = classify_dry_run(inventory, pin_map, {})

    assert [entry.extension_id for entry in preview.allowed_at_current_version] == [
        "anysphere.cursor-retrieval"
    ]
    assert [entry.extension_id for entry in preview.fully_blocked] == ["anysphere.malicious-fork"]


def test_classify_dry_run_blocks_an_uninstalled_false_deny() -> None:
    """A ``false`` deny for an extension that is not installed still reads as blocked, never
    as an allow with an empty pin list."""
    preview = classify_dry_run([], {"anysphere": True, "anysphere.malicious-fork": False}, {})

    assert [entry.extension_id for entry in preview.fully_blocked] == ["anysphere.malicious-fork"]
    assert preview.allowed_at_current_version == []

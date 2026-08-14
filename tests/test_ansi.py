from ansi import strip_ansi


def test_strip_ansi_removes_style_codes_and_keeps_text() -> None:
    assert strip_ansi("\x1b[1mUsage: pw\x1b[0m plain") == "Usage: pw plain"


def test_strip_ansi_leaves_plain_text_unchanged() -> None:
    assert strip_ansi("no codes here") == "no codes here"

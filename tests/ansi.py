import re

_ANSI_STYLE_CODES = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_STYLE_CODES.sub("", text)

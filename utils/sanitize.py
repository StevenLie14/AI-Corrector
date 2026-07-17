import re
import unicodedata

_INVISIBLE_RE = re.compile(
    "["
    "­"
    "᠎"
    "​-‏"
    "‪-‮"
    "⁠-⁤"
    "⁦-⁩"
    "﻿"
    "]"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _INVISIBLE_RE.sub("", cleaned)
    cleaned = _CONTROL_RE.sub(" ", cleaned)
    return cleaned

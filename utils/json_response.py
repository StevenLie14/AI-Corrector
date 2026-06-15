import json
import re

from fastapi.responses import JSONResponse

_SCI_RE = re.compile(r'(?<!["\w])(\d+(?:\.\d+)?[eE][+-]?\d+)(?!["\w])')


def _expand(match: re.Match) -> str:
    return f"{float(match.group()):.10f}".rstrip("0").rstrip(".")


class NeatJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        raw = json.dumps(content, ensure_ascii=False)
        return _SCI_RE.sub(_expand, raw).encode("utf-8")

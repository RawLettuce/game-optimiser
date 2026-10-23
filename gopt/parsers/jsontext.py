"""Lossless edits of scalar values in a JSON file (Brotato keeps its options in save_v2.json).

The text is parsed by a small recursive descent parser that records the
character span of every scalar value under a dotted path ("options.fullscreen",
list items as "items.0"). A write replaces exactly that span, so the rest of the
file (formatting, key order, the save progress next to the options) is byte
identical. The result is re-parsed with the json module as a cross check.
"""

from __future__ import annotations

import json


class JsonTextError(ValueError):
    pass


class _P:
    def __init__(self, t: str):
        self.t, self.i, self.spans = t, 0, {}

    def ws(self):
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
            self.i += 1

    def value(self, path: str):
        self.ws()
        if self.i >= len(self.t):
            raise JsonTextError("unexpected end of file")
        c = self.t[self.i]
        if c == "{":
            self.i += 1
            self.ws()
            if self.t[self.i] == "}":
                self.i += 1
                return
            while True:
                self.ws()
                key = self.string()
                self.ws()
                if self.t[self.i] != ":":
                    raise JsonTextError(f"expected ':' at {self.i}")
                self.i += 1
                self.value(f"{path}.{key}" if path else key)
                self.ws()
                if self.t[self.i] == ",":
                    self.i += 1
                    continue
                if self.t[self.i] == "}":
                    self.i += 1
                    return
                raise JsonTextError(f"expected ',' or '}}' at {self.i}")
        if c == "[":
            self.i += 1
            self.ws()
            if self.t[self.i] == "]":
                self.i += 1
                return
            n = 0
            while True:
                self.value(f"{path}.{n}" if path else str(n))
                n += 1
                self.ws()
                if self.t[self.i] == ",":
                    self.i += 1
                    continue
                if self.t[self.i] == "]":
                    self.i += 1
                    return
                raise JsonTextError(f"expected ',' or ']' at {self.i}")
        start = self.i
        if c == '"':
            self.string()
        else:
            while self.i < len(self.t) and self.t[self.i] not in ",}] \t\r\n":
                self.i += 1
            if start == self.i:
                raise JsonTextError(f"unexpected character {c!r} at {start}")
        self.spans[path] = (start, self.i)

    def string(self) -> str:
        if self.t[self.i] != '"':
            raise JsonTextError(f"expected a string at {self.i}")
        j = self.i + 1
        while j < len(self.t):
            if self.t[j] == "\\":
                j += 2
                continue
            if self.t[j] == '"':
                break
            j += 1
        else:
            raise JsonTextError("unterminated string")
        raw = self.t[self.i:j + 1]
        self.i = j + 1
        return json.loads(raw)


class JsonText:
    def __init__(self, text: str):
        self._text = text
        body = text[1:] if text.startswith("﻿") else text
        off = len(text) - len(body)
        try:
            self.obj = json.loads(body)
        except ValueError as e:
            raise JsonTextError(str(e))
        p = _P(body)
        p.value("")
        p.ws()
        if p.i != len(body):
            raise JsonTextError("trailing data after the JSON value")
        self.spans = {k: (a + off, b + off) for k, (a, b) in p.spans.items()}

    def text(self) -> str:
        return self._text

    def get(self, path: str, default=None):
        span = self.spans.get(path)
        if span is None:
            return default
        v = json.loads(self._text[span[0]:span[1]])
        if isinstance(v, bool):
            return "true" if v else "false"
        return "null" if v is None else str(v)

    def set(self, path: str, value: str) -> "JsonText":
        """Replace an existing scalar. The new value keeps the old JSON type (number, bool or string)."""
        span = self.spans.get(path)
        if span is None:
            raise JsonTextError(f"{path} is not an existing scalar value; refusing to add keys to this file")
        old = json.loads(self._text[span[0]:span[1]])
        if isinstance(old, bool):
            if value.lower() not in ("true", "false"):
                raise JsonTextError(f"{path} is a boolean, got {value!r}")
            lit = value.lower()
        elif isinstance(old, (int, float)):
            try:
                float(value)
            except ValueError:
                raise JsonTextError(f"{path} is a number, got {value!r}")
            lit = value
        else:
            lit = json.dumps(value, ensure_ascii=False)
        return JsonText(self._text[:span[0]] + lit + self._text[span[1]:])

    def flat(self) -> dict[str, str]:
        return {k: self.get(k) for k in self.spans}

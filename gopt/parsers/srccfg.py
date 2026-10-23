"""Lossless parser for Source engine .cfg files (Garry's Mod autoexec.cfg).

Shape: one command per line, `cvar value` or `cvar "value"`, `//` comments, blank
lines. The last assignment of a cvar wins (the engine runs the lines in order),
so get() reads the last one and set() rewrites the last one or appends a line.
Everything else (order, comments, line endings) is kept byte for byte.
"""

from __future__ import annotations

import re


class SrcCfgError(ValueError):
    pass


LINE_RE = re.compile(r'^(\s*)([A-Za-z_][A-Za-z0-9_.]*)(\s+)("([^"]*)"|(\S+))(.*)$')


class SrcCfg:
    def __init__(self, text: str):
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.trailing_newline = text.endswith("\n")
        body = text[:-len(self.newline)] if text.endswith(self.newline) else text
        self.lines: list[str] = body.split(self.newline) if body else []

    def text(self) -> str:
        out = self.newline.join(self.lines)
        if self.trailing_newline or self.lines:
            out += self.newline
        return out

    def _find(self, key: str) -> tuple[int, re.Match] | None:
        kl = key.lower()
        for i in range(len(self.lines) - 1, -1, -1):
            code = self.lines[i].split("//", 1)[0]
            m = LINE_RE.match(code)
            if m and m.group(2).lower() == kl:
                return i, m
        return None

    def get(self, key: str, default=None):
        hit = self._find(key)
        if hit is None:
            return default
        m = hit[1]
        return m.group(5) if m.group(5) is not None else m.group(6)

    def set(self, key: str, value: str) -> "SrcCfg":
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", key) or '"' in value or "\n" in value:
            raise SrcCfgError(f"refusing to write {key!r} = {value!r}")
        new = SrcCfg.__new__(SrcCfg)
        new.newline, new.trailing_newline = self.newline, True
        new.lines = list(self.lines)
        hit = self._find(key)
        if hit is None:
            new.lines.append(f'{key} "{value}"')
        else:
            i, m = hit
            line = self.lines[i]
            start, end = m.span(4)
            new.lines[i] = line[:start] + f'"{value}"' + line[end:]
        return new

    def flat(self) -> dict[str, str]:
        out = {}
        for line in self.lines:
            m = LINE_RE.match(line.split("//", 1)[0])
            if m:
                out[m.group(2)] = m.group(5) if m.group(5) is not None else m.group(6)
        return out

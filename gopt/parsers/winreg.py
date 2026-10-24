"""Lossless reader and minimal editor for Wine registry files (a Proton prefix's user.reg).

Shape (Wine's own format):
    WINE REGISTRY Version 2
    ;; All keys relative to \\User\\S-1-5-21-0-0-0-1000

    [Software\\\\Ninja Kiwi\\\\BloonsTD6] 1700000000
    #time=1da...
    "Screenmanager Resolution Width_h182942802"=dword:00000f00

Keys are addressed as "<registry key>::<value name>" with single backslashes,
e.g. "Software\\Ninja Kiwi\\BloonsTD6::Screenmanager Resolution Width_h182942802".
get() returns dwords as decimal strings and strings unquoted; set() only changes an
existing dword in place. Unity stores PlayerPrefs under "<name>_h<djb2 xor hash>".
"""

from __future__ import annotations

import re


class WinRegError(ValueError):
    pass


SECTION_RE = re.compile(r"^\[(.+?)\](\s+\d+)?\s*$")
VALUE_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"=(.*)$')


def unity_pref_name(name: str) -> str:
    """Registry value name Unity uses for a PlayerPrefs key (verified against the well known
    'Screenmanager Resolution Width_h182942802')."""
    h = 5381
    for c in name:
        h = ((h * 33) ^ ord(c)) & 0xFFFFFFFF
    return f"{name}_h{h}"


def _unesc(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


class WinReg:
    def __init__(self, text: str):
        self._text = text
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.split(self.newline)
        if not self.lines or not self.lines[0].startswith("WINE REGISTRY"):
            raise WinRegError("not a Wine registry file (no 'WINE REGISTRY' header)")
        self.index: dict[str, dict[str, int]] = {}
        cur = None
        for i, line in enumerate(self.lines):
            m = SECTION_RE.match(line)
            if m:
                cur = _unesc(m.group(1)).lower()
                self.index.setdefault(cur, {})
                continue
            m = VALUE_RE.match(line)
            if m and cur is not None:
                self.index[cur].setdefault(_unesc(m.group(1)).lower(), i)

    def text(self) -> str:
        return self._text

    def _loc(self, key: str) -> int | None:
        if "::" not in key:
            raise WinRegError(f"registry keys look like 'Software\\\\Vendor\\\\Game::ValueName', got {key!r}")
        sec, name = key.rsplit("::", 1)
        return self.index.get(sec.lower(), {}).get(name.lower())

    def get(self, key: str, default=None):
        i = self._loc(key)
        if i is None:
            return default
        raw = VALUE_RE.match(self.lines[i]).group(2)
        if raw.startswith("dword:"):
            return str(int(raw[6:], 16))
        if raw.startswith('"') and raw.endswith('"'):
            return _unesc(raw[1:-1])
        return raw

    def set(self, key: str, value: str) -> "WinReg":
        i = self._loc(key)
        if i is None:
            raise WinRegError(f"{key} does not exist; refusing to add registry values")
        m = VALUE_RE.match(self.lines[i])
        if not m.group(2).startswith("dword:"):
            raise WinRegError(f"{key} is not a dword; only dwords are edited")
        try:
            n = int(value)
        except ValueError:
            raise WinRegError(f"{key} needs an integer, got {value!r}")
        if not 0 <= n <= 0xFFFFFFFF:
            raise WinRegError(f"{key}: {n} out of dword range")
        lines = list(self.lines)
        lines[i] = f'"{m.group(1)}"=dword:{n:08x}'
        return WinReg(self.newline.join(lines))

    def flat(self) -> dict[str, str]:
        out = {}
        for sec, vals in self.index.items():
            for name, i in vals.items():
                out[f"{sec}::{name}"] = VALUE_RE.match(self.lines[i]).group(2)
        return out

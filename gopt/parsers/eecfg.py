"""Lossless parser for Warframe's EE.cfg.

Shape (community documented, header names unverified on PC):
    [SectionName,/EE/Types/Base/Config]
    Graphics.ShadowQuality=SQ_HIGH
    ...
Blank lines, comments, unknown lines, line endings and a BOM are preserved.
Only planned keys change; a missing key is appended to the end of its section.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class EECfgError(ValueError):
    pass


@dataclass
class Section:
    header: str            # text inside the brackets
    start: int             # index of the header line in lines (or -1 for the preamble)
    keys: dict[str, int] = field(default_factory=dict)   # key -> line index


class EECfg:
    def __init__(self, text: str):
        self.bom = text.startswith("﻿")
        if self.bom:
            text = text[1:]
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.trailing_newline = text.endswith("\n")
        body = text[:-len(self.newline)] if text.endswith(self.newline) else text
        self.lines: list[str] = body.split(self.newline) if body else []
        self._index()

    @classmethod
    def load(cls, path) -> "EECfg":
        with open(path, "r", encoding="utf-8", newline="") as f:
            return cls(f.read())

    def _index(self):
        self.sections: list[Section] = []
        cur = Section(header="", start=-1)
        self.sections.append(cur)
        for i, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                cur = Section(header=s[1:-1], start=i)
                self.sections.append(cur)
            elif "=" in s and not s.startswith(("#", ";", "//")):
                key = s.split("=", 1)[0].strip()
                if key and key not in cur.keys:
                    cur.keys[key] = i

    def text(self) -> str:
        out = self.newline.join(self.lines)
        if self.trailing_newline or self.lines:
            out += self.newline
        return ("﻿" if self.bom else "") + out

    # ---- reading -----------------------------------------------------
    def section_names(self) -> list[str]:
        return [s.header for s in self.sections if s.start >= 0]

    def find_section(self, header: str) -> Section | None:
        for s in self.sections:
            if s.header == header:
                return s
        return None

    def get(self, key: str, section: str | None = None, default=None):
        for s in self.sections:
            if section is not None and s.header != section:
                continue
            if key in s.keys:
                return self.lines[s.keys[key]].split("=", 1)[1].strip()
        return default

    def all_items(self) -> dict[str, dict[str, str]]:
        return {
            s.header: {k: self.lines[i].split("=", 1)[1].strip() for k, i in s.keys.items()}
            for s in self.sections
        }

    def graphics_section(self) -> Section | None:
        """Section holding Graphics.* keys, else the *_Config,/EE/Types/Base/Config one."""
        for s in self.sections:
            if any(k.startswith("Graphics.") for k in s.keys):
                return s
        for s in self.sections:
            if s.header.endswith("_Config,/EE/Types/Base/Config"):
                return s
        return None

    # ---- writing -----------------------------------------------------
    def set(self, key: str, value: str, section: str | None = None) -> "EECfg":
        """Return a new document with key set (replaced in place or appended to the section)."""
        sec = self.find_section(section) if section else self.graphics_section()
        if sec is None:
            raise EECfgError("no suitable section for graphics keys; refusing to guess")
        lines = list(self.lines)
        if key in sec.keys:
            i = sec.keys[key]
            lines[i] = f"{key}={value}"
        else:
            # append after the last key line of the section (or after its header)
            last = max(sec.keys.values()) if sec.keys else sec.start
            lines.insert(last + 1, f"{key}={value}")
        new = EECfg.__new__(EECfg)
        new.bom, new.newline, new.trailing_newline = self.bom, self.newline, True
        new.lines = lines
        new._index()
        return new

    def flat(self) -> dict[str, str]:
        out = {}
        for s in self.sections:
            for k, i in s.keys.items():
                out[f"{s.header}::{k}"] = self.lines[i].split("=", 1)[1].strip()
        return out

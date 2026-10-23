"""Lossless parser for Valve text KeyValues (localconfig.vdf, cs2_video.txt, appmanifest_*.acf).

The document keeps the original text. Reads walk a tree of nodes that point
at character offsets. Writes are minimal textual edits (one quoted value, or
one inserted line) followed by a re-parse, so everything else in the file is
byte identical. Conditionals like [$WIN32] are kept as text and ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class KeyValuesError(ValueError):
    pass


@dataclass
class Node:
    key: str
    key_span: tuple[int, int]
    value: str | None = None            # None for a block
    value_span: tuple[int, int] | None = None
    children: list["Node"] = field(default_factory=list)
    open_span: tuple[int, int] | None = None   # position of '{'
    close_span: tuple[int, int] | None = None  # position of '}'

    def child(self, key: str) -> "Node | None":
        kl = key.lower()
        for c in self.children:
            if c.key.lower() == kl:
                return c
        return None

    def to_obj(self):
        if self.value is not None:
            return self.value
        out = {}
        for c in self.children:
            out[c.key] = c.to_obj()
        return out


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t")


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


class _Tokenizer:
    def __init__(self, text: str):
        self.t = text
        self.i = 0
        self.n = len(text)

    def next(self):
        """Return (kind, text, start, end) or None at EOF. kind in STR, BARE, LBRACE, RBRACE, COND."""
        t, n = self.t, self.n
        while self.i < n:
            c = t[self.i]
            if c in " \t\r\n":
                self.i += 1
                continue
            if c == "/" and self.i + 1 < n and t[self.i + 1] == "/":
                while self.i < n and t[self.i] != "\n":
                    self.i += 1
                continue
            start = self.i
            if c == "{":
                self.i += 1
                return ("LBRACE", "{", start, self.i)
            if c == "}":
                self.i += 1
                return ("RBRACE", "}", start, self.i)
            if c == '"':
                self.i += 1
                buf = []
                while self.i < n:
                    ch = t[self.i]
                    if ch == "\\" and self.i + 1 < n:
                        buf.append(ch)
                        buf.append(t[self.i + 1])
                        self.i += 2
                        continue
                    if ch == '"':
                        self.i += 1
                        return ("STR", _unescape("".join(buf)), start, self.i)
                    buf.append(ch)
                    self.i += 1
                raise KeyValuesError(f"unterminated string at offset {start}")
            if c == "[":
                while self.i < n and t[self.i] != "]":
                    self.i += 1
                self.i += 1
                return ("COND", t[start:self.i], start, self.i)
            # bare word
            while self.i < n and t[self.i] not in ' \t\r\n{}"':
                self.i += 1
            return ("BARE", t[start:self.i], start, self.i)
        return None


class KeyValues:
    def __init__(self, text: str):
        self.text = text
        self.roots: list[Node] = []
        self._parse()

    @classmethod
    def load(cls, path) -> "KeyValues":
        with open(path, "r", encoding="utf-8", newline="") as f:
            return cls(f.read())

    def _parse(self):
        tok = _Tokenizer(self.text)
        self.roots = []
        stack: list[Node] = []
        pending_key = None
        while True:
            tk = tok.next()
            if tk is None:
                break
            kind, val, s, e = tk
            if kind == "COND":
                continue
            if pending_key is None:
                if kind in ("STR", "BARE"):
                    pending_key = Node(key=val, key_span=(s, e))
                elif kind == "RBRACE":
                    if not stack:
                        raise KeyValuesError(f"unexpected '}}' at offset {s}")
                    node = stack.pop()
                    node.close_span = (s, e)
                else:
                    raise KeyValuesError(f"unexpected token {val!r} at offset {s}")
            else:
                if kind in ("STR", "BARE"):
                    pending_key.value = val
                    pending_key.value_span = (s, e)
                    (stack[-1].children if stack else self.roots).append(pending_key)
                    pending_key = None
                elif kind == "LBRACE":
                    pending_key.open_span = (s, e)
                    (stack[-1].children if stack else self.roots).append(pending_key)
                    stack.append(pending_key)
                    pending_key = None
                else:
                    raise KeyValuesError(f"expected value after key {pending_key.key!r} at offset {s}")
        if stack or pending_key is not None:
            raise KeyValuesError("unexpected end of file (unbalanced braces or dangling key)")

    # ---- reading -----------------------------------------------------
    def root(self, key: str | None = None) -> Node | None:
        if key is None:
            return self.roots[0] if self.roots else None
        kl = key.lower()
        for r in self.roots:
            if r.key.lower() == kl:
                return r
        return None

    def find(self, path: list[str]) -> Node | None:
        """Case insensitive path lookup starting at the roots."""
        if not path:
            return None
        node = self.root(path[0])
        for key in path[1:]:
            if node is None:
                return None
            node = node.child(key)
        return node

    def get(self, path: list[str], default=None):
        node = self.find(path)
        if node is None or node.value is None:
            return default
        return node.value

    def to_obj(self) -> dict:
        return {r.key: r.to_obj() for r in self.roots}

    # ---- writing -----------------------------------------------------
    def with_value(self, path: list[str], new_value: str) -> "KeyValues":
        """Return a new document with one existing value replaced textually."""
        node = self.find(path)
        if node is None or node.value_span is None:
            raise KeyValuesError(f"no value at path {path}")
        s, e = node.value_span
        quoted = self.text[s] == '"'
        rep = f'"{_escape(new_value)}"' if quoted else new_value
        if not quoted and any(ch in new_value for ch in ' \t"{}'):
            rep = f'"{_escape(new_value)}"'
        return KeyValues(self.text[:s] + rep + self.text[e:])

    def with_added(self, parent_path: list[str], key: str, value: str) -> "KeyValues":
        """Return a new document with a key/value line inserted at the end of a block."""
        parent = self.find(parent_path)
        if parent is None or parent.close_span is None:
            raise KeyValuesError(f"no block at path {parent_path}")
        cs, _ = parent.close_span
        # indentation: copy the leading whitespace of the closing brace line, add one tab
        line_start = self.text.rfind("\n", 0, cs) + 1
        indent = self.text[line_start:cs]
        if not indent.strip() == "":
            indent = ""
        child_indent = indent + "\t"
        if parent.children:
            first = parent.children[0]
            ls = self.text.rfind("\n", 0, first.key_span[0]) + 1
            cand = self.text[ls:first.key_span[0]]
            if cand.strip() == "":
                child_indent = cand
        nl = "\r\n" if "\r\n" in self.text else "\n"
        line = f'{child_indent}"{_escape(key)}"\t\t"{_escape(value)}"{nl}'
        insert_at = line_start
        return KeyValues(self.text[:insert_at] + line + self.text[insert_at:])

    def set(self, path: list[str], value: str) -> "KeyValues":
        """Set an existing value or add the key to its parent block."""
        if self.find(path) is not None and self.find(path).value is not None:
            return self.with_value(path, value)
        return self.with_added(path[:-1], path[-1], value)


def diff_paths(a: dict, b: dict, prefix: tuple = ()) -> list[tuple]:
    """Paths whose values differ between two to_obj() trees."""
    out = []
    keys = set(a) | set(b)
    for k in sorted(keys):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out.extend(diff_paths(va, vb, prefix + (k,)))
        elif va != vb:
            out.append(prefix + (k,))
    return out

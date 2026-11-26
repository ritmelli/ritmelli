"""The one YAML reader of the workflow tests (standard library only, so the STDLIB of dev/testa_tudo.py can use it).

It reads the YAML the files of .github/ are written in: block mappings and sequences, flow sequences of plain or quoted
scalars, single and double quoted scalars, plain scalars and the | block scalar. Scalars come back as strings and an
empty value as None. Anything else (anchors, aliases, tags, flow mappings, folded scalars, a plain scalar that goes on
to the next line, a repeated key, a tab in the indentation) raises YamlError, so a construct the reader does not know
fails the test instead of being read wrong."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class YamlError(ValueError):
    pass


_KEY = re.compile(r"""(?P<key>'(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|[^\s'"#\[\]{}&*!|>%@`][^#]*?)\s*:(?:\s+(?P<rest>.*)|$)""")
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "/": "/"}


def _strip_comment(text, where):
    out, quote, i = [], None, 0
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'" and text[i + 1:i + 2] == "'":
                out.append("''")
                i += 2
                continue
            if c == "'":
                quote = None
        elif quote == '"':
            if c == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == '"':
                quote = None
        elif c in "'\"" and (not out or "".join(out).rstrip() == "" or text[i - 1] in " [,"):
            quote = c
        elif c == "#" and (i == 0 or text[i - 1] in " \t"):
            break
        out.append(c)
        i += 1
    if quote:
        raise YamlError(f"{where}: unterminated quoted scalar")
    return "".join(out).rstrip()


def _quoted(text, where):
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'") or re.search(r"(?<!')'(?!')", text[1:-1]):
            raise YamlError(f"{where}: bad single quoted scalar {text}")
        return text[1:-1].replace("''", "'")
    if len(text) < 2 or not text.endswith('"'):
        raise YamlError(f"{where}: bad double quoted scalar {text}")
    out, i, body = [], 0, text[1:-1]
    while i < len(body):
        if body[i] == "\\":
            esc = body[i + 1:i + 2]
            if esc not in _ESCAPES:
                raise YamlError(f"{where}: escape \\{esc} the reader does not know")
            out.append(_ESCAPES[esc])
            i += 2
        elif body[i] == '"':
            raise YamlError(f"{where}: bad double quoted scalar {text}")
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _scalar(text, where):
    if not text:
        return None
    if text[0] in "'\"":
        return _quoted(text, where)
    if text[0] in "&*!{}%@`|>" or text in ("---", "..."):
        raise YamlError(f"{where}: {text!r} is a YAML construct the reader does not know")
    if text[0] == "[":
        return _flow_sequence(text, where)
    if ": " in text or text.endswith(":"):
        raise YamlError(f"{where}: a plain scalar with ': ' ({text!r})")
    return text


def _flow_sequence(text, where):
    if not text.endswith("]"):
        raise YamlError(f"{where}: a flow sequence that does not close on its line ({text!r})")
    body = text[1:-1].strip()
    if not body:
        return []
    items, current, quote = [], [], None
    for c in body:
        if quote:
            current.append(c)
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            current.append(c)
        elif c in "[]{}":
            raise YamlError(f"{where}: a nested flow collection ({text!r})")
        elif c == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(c)
    items.append("".join(current).strip())
    if any(not item for item in items):
        raise YamlError(f"{where}: an empty item in a flow sequence ({text!r})")
    return [_scalar(item, where) for item in items]


class _Reader:
    def __init__(self, text, name):
        self.name = name
        self.lines = text.split("\n")
        self.i = 0

    def where(self, i=None):
        return f"{self.name}:{(self.i if i is None else i) + 1}"

    def next_content(self):
        while self.i < len(self.lines):
            raw = self.lines[self.i].rstrip("\r")
            stripped = raw.lstrip(" ")
            if raw[:len(raw) - len(stripped)].count("\t") or stripped.startswith("\t"):
                raise YamlError(f"{self.where()}: a tab in the indentation")
            if stripped and not stripped.startswith("#"):
                if stripped in ("---", "..."):
                    raise YamlError(f"{self.where()}: more than one document")
                return len(raw) - len(stripped), _strip_comment(stripped, self.where())
            self.i += 1
        return None

    def block(self):
        head = self.next_content()
        if head is None:
            return None
        if head[1].startswith("- ") or head[1] == "-":
            return self.sequence(head[0])
        return self.mapping(head[0])

    def value(self, rest, parent_indent, where):
        if rest in ("|", "|-"):
            return self.block_scalar(parent_indent, rest)
        if not rest:
            nxt = self.next_content()
            if nxt is not None and (nxt[0] > parent_indent or (nxt[0] == parent_indent and nxt[1].startswith("- "))):
                return self.block()
            return None
        value = _scalar(rest, where)
        nxt = self.next_content()
        if nxt is not None and nxt[0] > parent_indent:
            raise YamlError(f"{self.where()}: a scalar that goes on to the next line, or a value after a scalar")
        return value

    def mapping(self, indent):
        out = {}
        while True:
            head = self.next_content()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                raise YamlError(f"{self.where()}: unexpected indentation")
            if head[1].startswith("- "):
                return out
            where = self.where()
            m = _KEY.match(head[1])
            if not m:
                raise YamlError(f"{where}: not a mapping entry ({head[1]!r})")
            key = m.group("key").strip()
            key = _quoted(key, where) if key[0] in "'\"" else key
            if key in out:
                raise YamlError(f"{where}: the key {key!r} appears twice")
            self.i += 1
            out[key] = self.value(m.group("rest"), indent, where)

    def sequence(self, indent):
        out = []
        while True:
            head = self.next_content()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                raise YamlError(f"{self.where()}: unexpected indentation")
            if not head[1].startswith("- "):
                return out
            where = self.where()
            item = head[1][2:].lstrip(" ")
            if _KEY.match(item):
                raw = self.lines[self.i]
                self.lines[self.i] = raw[:indent] + " " + raw[indent + 1:]
                out.append(self.mapping(indent + len(head[1]) - len(item)))
            else:
                self.i += 1
                out.append(self.value(item, indent, where))

    def block_scalar(self, parent_indent, header):
        start, body, indent = self.i, [], None
        while self.i < len(self.lines):
            raw = self.lines[self.i].rstrip("\r")
            if raw.strip():
                width = len(raw) - len(raw.lstrip(" "))
                if indent is None:
                    if width <= parent_indent:
                        break
                    indent = width
                if width < indent:
                    break
                body.append(raw[indent:])
            else:
                body.append("")
            self.i += 1
        if indent is None:
            raise YamlError(f"{self.where(start - 1)}: an empty block scalar")
        while body and body[-1] == "":
            body.pop()
            self.i -= 1
        text = "\n".join(body)
        return text if header == "|-" else text + "\n"


def loads(text, name="<yaml>"):
    reader = _Reader(text, name)
    data = reader.block()
    if reader.next_content() is not None:
        raise YamlError(f"{reader.where()}: content the reader could not place")
    return data


def load(path):
    path = Path(path)
    return loads(path.read_text(encoding="utf-8"), str(path))


def workflows(root=ROOT):
    """Every workflow of .github/workflows/ (.yml and .yaml), by its path from the root (with /)."""
    root = Path(root)
    found = sorted(p for p in (root / ".github" / "workflows").iterdir() if p.suffix in (".yml", ".yaml"))
    return {p.relative_to(root).as_posix(): load(p) for p in found}


def job_steps(job):
    return job.get("steps") or []


def find_step(job, name):
    """The one step of the job with that name, or None when there is none or more than one."""
    found = [s for s in job_steps(job) if s.get("name") == name]
    return found[0] if len(found) == 1 else None

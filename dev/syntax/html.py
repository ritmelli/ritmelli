import html
import re
from dataclasses import dataclass, field

from .text import Comment, Source, Span, SyntaxProblem

TAG_NAME = re.compile(r"[A-Za-z][^\s/>]*")
ATTRIBUTE_NAME = re.compile(r"[^\s/>\"'=]+")
UNQUOTED = re.compile(r"[^\s>]+")
REFERENCE = re.compile(r"&(?:#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[A-Za-z][A-Za-z0-9]*;?)")
RAW_TEXT = {"script", "style"}
JAVASCRIPT_TYPES = {"", "text/javascript", "application/javascript", "module"}


class HtmlError(SyntaxProblem):
    pass


@dataclass
class Text:
    value: str
    offsets: list

    def offset(self, i):
        return self.offsets[min(max(i, 0), len(self.offsets) - 1)] if self.offsets else 0


@dataclass(eq=False)
class Attribute:
    name: str
    span: Span
    value: Text = None


@dataclass(eq=False)
class Tag:
    name: str
    span: Span
    attributes: list = field(default_factory=list)
    end: bool = False
    self_closing: bool = False

    def attribute(self, name):
        return next((a for a in self.attributes if a.name == name), None)


@dataclass(eq=False)
class Document:
    source: Source
    tags: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    scripts: list = field(default_factory=list)
    styles: list = field(default_factory=list)
    handlers: list = field(default_factory=list)
    style_attributes: list = field(default_factory=list)


def decoded(text, start):
    chars, offsets, at = [], [], 0
    for m in REFERENCE.finditer(text):
        for k in range(at, m.start()):
            chars.append(text[k])
            offsets.append(start + k)
        value = html.unescape(m.group(0))
        chars.append(value)
        offsets += [start + m.start()] * len(value)
        at = m.end()
    for k in range(at, len(text)):
        chars.append(text[k])
        offsets.append(start + k)
    return Text("".join(chars), offsets + [start + len(text)])


class _Reader:
    def __init__(self, text, name):
        self.source = Source(text, name)
        self.t, self.n, self.i = text, len(text), 0
        self.document = Document(self.source)

    def error(self, message, at):
        raise HtmlError(self.source, at, message)

    def read(self):
        while self.i < self.n:
            lt = self.t.find("<", self.i)
            if lt < 0:
                break
            self.i = lt
            if self.t.startswith("<!--", lt):
                self.comment()
            elif self.t.startswith("<!", lt) or self.t.startswith("<?", lt):
                end = self.t.find(">", lt)
                if end < 0:
                    self.error("a declaration that is never closed", lt)
                self.i = end + 1
            elif self.t.startswith("</", lt) and TAG_NAME.match(self.t, lt + 2):
                self.end_tag()
            elif TAG_NAME.match(self.t, lt + 1):
                self.start_tag()
            else:
                self.i = lt + 1
        return self.document

    def comment(self):
        start = self.i
        end = self.t.find("-->", start + 4)
        if self.t.startswith("<!-->", start) or self.t.startswith("<!--->", start):
            end = start + (2 if self.t.startswith("<!-->", start) else 3)
        if end < 0:
            self.error("a comment that is never closed", start)
        self.document.comments.append(Comment(Span(start, end + 3), self.t[start + 4:end]))
        self.i = end + 3

    def end_tag(self):
        start = self.i
        m = TAG_NAME.match(self.t, start + 2)
        end = self.t.find(">", m.end())
        if end < 0:
            self.error("an end tag that is never closed", start)
        self.document.tags.append(Tag(m.group(0).lower(), Span(start, end + 1), end=True))
        self.i = end + 1

    def start_tag(self):
        start = self.i
        m = TAG_NAME.match(self.t, start + 1)
        tag = Tag(m.group(0).lower(), Span(start, start))
        self.i = m.end()
        while True:
            while self.i < self.n and self.t[self.i] in " \t\n\r\f":
                self.i += 1
            if self.i >= self.n:
                self.error("a start tag that is never closed", start)
            if self.t.startswith("/>", self.i):
                tag.self_closing = True
                self.i += 2
                break
            if self.t[self.i] == ">":
                self.i += 1
                break
            if self.t[self.i] == "/":
                self.i += 1
                continue
            tag.attributes.append(self.attribute())
        tag.span = Span(start, self.i)
        self.document.tags.append(tag)
        if tag.name in RAW_TEXT and not tag.self_closing:
            self.raw_text(tag)
        for a in tag.attributes:
            if a.value is None:
                continue
            if a.name.startswith("on"):
                self.document.handlers.append((tag, a))
            elif a.name == "style":
                self.document.style_attributes.append((tag, a))

    def attribute(self):
        start = self.i
        m = ATTRIBUTE_NAME.match(self.t, self.i)
        if not m:
            m = re.compile(r".").match(self.t, self.i)
        name = m.group(0).lower()
        self.i = m.end()
        j = self.i
        while j < self.n and self.t[j] in " \t\n\r\f":
            j += 1
        if j >= self.n or self.t[j] != "=":
            return Attribute(name, Span(start, self.i))
        j += 1
        while j < self.n and self.t[j] in " \t\n\r\f":
            j += 1
        if j < self.n and self.t[j] in "\"'":
            quote = self.t[j]
            end = self.t.find(quote, j + 1)
            if end < 0:
                self.error("an attribute value that is never closed", j)
            value = decoded(self.t[j + 1:end], j + 1)
            self.i = end + 1
        else:
            v = UNQUOTED.match(self.t, j)
            raw = v.group(0) if v else ""
            value = decoded(raw, j)
            self.i = j + len(raw)
        return Attribute(name, Span(start, self.i), value)

    def raw_text(self, tag):
        start = self.i
        closing = re.compile(rf"</{tag.name}[\s/>]", re.I)
        m = closing.search(self.t, start)
        if not m:
            self.error(f"a <{tag.name}> that is never closed", tag.span.start)
        content = Text(self.t[start:m.start()], list(range(start, m.start() + 1)))
        if tag.name == "script":
            if script_type(tag) in JAVASCRIPT_TYPES:
                self.document.scripts.append((tag, content))
        else:
            self.document.styles.append((tag, content))
        self.i = m.start()


def script_type(tag):
    kind = tag.attribute("type")
    return kind.value.value.strip().lower() if kind and kind.value else ""


def parse(text, name="<html>"):
    return _Reader(text, name).read()

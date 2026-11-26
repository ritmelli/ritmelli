from dataclasses import dataclass, field

from .text import Comment, Source, Span, SyntaxProblem

BREAK = "\n"
END = "\0"
BLANK = " \t"
FLOW_INDICATORS = ",[]{}"
ANCHOR_CHARS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_")
TAG_CHARS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-;/?:@&=+$,_.!~*'()[]%")
ESCAPES = {"0": "\0", "a": "\x07", "b": "\x08", "t": "\t", "\t": "\t", "n": "\n", "v": "\x0b", "f": "\x0c",
           "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
           "L": " ", "P": " "}
ESCAPE_CODES = {"x": 2, "u": 4, "U": 8}
HEX = frozenset("0123456789abcdefABCDEF")


class YamlError(SyntaxProblem):
    pass


@dataclass(eq=False)
class Node:
    span: Span
    tag: str = None
    anchor: str = None


@dataclass(eq=False)
class Empty(Node):
    pass


@dataclass(eq=False)
class Scalar(Node):
    value: str = ""
    style: str = "plain"
    offsets: tuple = ()


@dataclass(eq=False)
class Alias(Node):
    name: str = ""
    target: Node = None


@dataclass(eq=False)
class Sequence(Node):
    items: list = field(default_factory=list)
    flow: bool = False


@dataclass(eq=False)
class Mapping(Node):
    pairs: list = field(default_factory=list)
    flow: bool = False

    def node(self, key):
        for k, v in self.pairs:
            if isinstance(k, Scalar) and k.value == key:
                return v
        return None


@dataclass(eq=False)
class Document:
    root: Node
    span: Span
    explicit: bool = False


@dataclass(eq=False)
class Stream:
    source: Source
    documents: list
    comments: list


def resolved(node):
    seen = set()
    while isinstance(node, Alias):
        if id(node) in seen:
            break
        seen.add(id(node))
        node = node.target
    return node


def scalar_text(node):
    node = resolved(node)
    return node.value if isinstance(node, Scalar) else None


def data(node, _stack=()):
    node = resolved(node)
    if node is None or isinstance(node, Empty):
        return None
    if isinstance(node, Scalar):
        return node.value
    if id(node) in _stack:
        raise ValueError("a recursive alias")
    stack = (*_stack, id(node))
    if isinstance(node, Sequence):
        return [data(item, stack) for item in node.items]
    out = {}
    for key, value in node.pairs:
        k = data(key, stack)
        if isinstance(k, (list, dict)):
            raise ValueError("a collection as a mapping key")
        out[k] = data(value, stack)
    return out


class _Parser:
    def __init__(self, source):
        self.source = source
        self.t = source.text
        self.n = len(self.t)
        self.i = 0
        self.flow = 0
        self.comments = []
        self.anchors = {}

    def error(self, message, at=None):
        raise YamlError(self.source, self.i if at is None else at, message)

    def ch(self, k=0):
        j = self.i + k
        return self.t[j] if j < self.n else END

    def col(self, at=None):
        at = self.i if at is None else at
        return at - self.source.line_start(at)

    def blank_after(self, k=1):
        return self.ch(k) in BLANK + BREAK + END

    def marker(self, at=None):
        at = self.i if at is None else at
        if self.col(at) != 0:
            return None
        head = self.t[at:at + 3]
        if head in ("---", "...") and (at + 3 >= self.n or self.t[at + 3] in BLANK + BREAK):
            return head
        return None

    def comment(self):
        start = self.i
        while self.i < self.n and self.t[self.i] != BREAK:
            self.i += 1
        self.comments.append(Comment(Span(start, self.i), self.t[start + 1:self.i]))

    def skip_blank(self):
        while self.i < self.n and self.t[self.i] in BLANK:
            self.i += 1

    def at_line_end(self):
        return self.ch() in BREAK + END or self.ch() == "#"

    def skip_to_content(self):
        indentation_tab = None
        line_start = not self.t[self.source.line_start(self.i):self.i].strip(BLANK) if self.i < self.n else True
        while self.i < self.n:
            c = self.t[self.i]
            if c == " ":
                self.i += 1
            elif c == "\t":
                if line_start and indentation_tab is None:
                    indentation_tab = self.i
                self.i += 1
            elif c == BREAK:
                self.i += 1
                line_start, indentation_tab = True, None
            elif c == "#":
                self.comment()
            else:
                if indentation_tab is not None and self.flow == 0:
                    self.error("a tab in the indentation", indentation_tab)
                return

    def end_of_line(self, what):
        self.skip_blank()
        if self.ch() == "#":
            self.comment()
        if self.ch() not in BREAK + END:
            if self.ch() == ":":
                self.error(f"a mapping value is not allowed after {what}")
            self.error(f"unexpected content after {what}")

    def stream(self):
        if self.t.startswith("﻿"):
            self.i = 1
        documents = []
        while True:
            self.skip_to_content()
            if self.i >= self.n:
                break
            start = self.i
            self.anchors = {}
            directives = False
            while self.ch() == "%" and self.col() == 0:
                directives = True
                while self.i < self.n and self.t[self.i] not in BREAK + "#":
                    self.i += 1
                self.skip_to_content()
            if self.marker() == "---":
                self.i += 3
                root = self.after_indicator(-1, "entry")
                explicit = True
            elif directives:
                self.error("a directive must be followed by ---")
            elif self.marker() == "...":
                self.i += 3
                self.end_of_line("the document end marker")
                continue
            else:
                root = self.block(self.col(), -1)
                explicit = False
            end = root.span.end
            self.skip_to_content()
            if self.marker() == "...":
                self.i += 3
                self.end_of_line("the document end marker")
            elif self.i < self.n and self.marker() != "---":
                self.error("content that the document could not place")
            documents.append(Document(root, Span(start, end), explicit))
        return Stream(self.source, documents, self.comments)

    def register(self, node):
        if node.anchor is not None:
            self.anchors[node.anchor] = node
        return node

    def empty(self, at, tag=None, anchor=None):
        return self.register(Empty(Span(at, at), tag, anchor))

    def with_properties(self, node, tag, anchor, start):
        if tag is None and anchor is None:
            return node
        if node.tag is not None or node.anchor is not None:
            self.error("a node with two sets of properties", start)
        node.tag, node.anchor = tag, anchor
        node.span = Span(start, node.span.end)
        return self.register(node)

    def anchor_name(self):
        start = self.i
        self.i += 1
        while self.i < self.n and self.t[self.i] in ANCHOR_CHARS:
            self.i += 1
        name = self.t[start + 1:self.i]
        if not name:
            self.error("an anchor or alias without a name", start)
        if self.ch() not in BLANK + BREAK + END + "?:,]}%@`":
            self.error(f"an anchor or alias name with {self.ch()!r}")
        return name

    def tag_text(self):
        start = self.i
        if self.ch(1) == "<":
            end = self.t.find(">", self.i + 2)
            if end < 0 or BREAK in self.t[self.i:end]:
                self.error("a verbatim tag that does not close")
            self.i = end + 1
        else:
            self.i += 1
            while self.i < self.n and self.t[self.i] in TAG_CHARS and not (
                    self.flow and self.t[self.i] in FLOW_INDICATORS):
                self.i += 1
        if self.ch() not in BLANK + BREAK + END + (FLOW_INDICATORS if self.flow else ""):
            self.error(f"a tag with {self.ch()!r}")
        return self.t[start:self.i]

    def properties(self):
        tag = anchor = None
        while True:
            if self.ch() == "&":
                if anchor is not None:
                    self.error("a node with two anchors")
                anchor = self.anchor_name()
            elif self.ch() == "!":
                if tag is not None:
                    self.error("a node with two tags")
                tag = self.tag_text()
            else:
                return tag, anchor
            self.skip_blank()

    def is_entry(self):
        return self.ch() == "-" and self.blank_after()

    def is_explicit_key(self):
        return self.ch() == "?" and (self.blank_after() or (self.flow and self.ch(1) in FLOW_INDICATORS))

    def after_indicator(self, indent, context):
        self.skip_blank()
        start = self.i
        tag, anchor = self.properties()
        if self.at_line_end():
            if self.ch() == "#":
                self.comment()
            self.skip_to_content()
            if self.i >= self.n or self.marker():
                return self.empty(start, tag, anchor)
            c = self.col()
            if c > indent:
                return self.with_properties(self.block(c, indent), tag, anchor, start)
            if c == indent and context == "value" and self.is_entry():
                return self.with_properties(self.sequence(c, indent), tag, anchor, start)
            return self.empty(start, tag, anchor)
        if context == "entry" and tag is None and anchor is None and self.is_entry():
            return self.sequence(self.col(), indent)
        if context == "entry" and (self.is_explicit_key() or self.implicit_key_ahead(start)):
            self.i = start
            return self.mapping(self.col(start), indent)
        if context == "value" and self.is_entry():
            self.error("a sequence entry is not allowed after a mapping key on the same line")
        node = self.inline(indent)
        self.after_inline(node)
        return self.with_properties(node, tag, anchor, start)

    def after_inline(self, node):
        if not (isinstance(node, Scalar) and node.style in ("literal", "folded")):
            self.end_of_line("a value")

    def block(self, c, indent):
        if self.is_entry():
            return self.sequence(c, indent)
        start = self.i
        if self.is_explicit_key() or self.implicit_key_ahead(start):
            return self.mapping(c, indent)
        tag, anchor = self.properties()
        if (tag or anchor) and self.at_line_end():
            if self.ch() == "#":
                self.comment()
            self.skip_to_content()
            if self.i < self.n and not self.marker() and self.col() > indent:
                return self.with_properties(self.block(self.col(), indent), tag, anchor, start)
            return self.empty(start, tag, anchor)
        node = self.inline(indent)
        self.after_inline(node)
        return self.with_properties(node, tag, anchor, start)

    def implicit_key_ahead(self, at):
        j, t = at, self.t

        def blank(k):
            return k >= self.n or t[k] in BLANK + BREAK

        while j < self.n and t[j] in "&!":
            while j < self.n and t[j] not in BLANK + BREAK:
                j += 1
            while j < self.n and t[j] in BLANK:
                j += 1
        if j >= self.n or t[j] in BREAK + "#":
            return False
        c = t[j]
        if c in "'\"":
            j += 1
            while j < self.n and t[j] != BREAK:
                if c == '"' and t[j] == "\\":
                    j += 2
                    continue
                if t[j] == c:
                    if c == "'" and j + 1 < self.n and t[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= self.n or t[j] != c:
                return False
            j += 1
        elif c == "*":
            j += 1
            while j < self.n and t[j] in ANCHOR_CHARS:
                j += 1
        elif c in "[{":
            depth, quote = 0, None
            while j < self.n and t[j] != BREAK:
                ch = t[j]
                if quote:
                    if quote == '"' and ch == "\\":
                        j += 1
                    elif ch == quote:
                        quote = None
                elif ch in "'\"":
                    quote = ch
                elif ch in "[{":
                    depth += 1
                elif ch in "]}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            else:
                return False
            if depth:
                return False
        elif c in "|>%@`" or (c in "-?:" and blank(j + 1)):
            return False
        else:
            while j < self.n and t[j] != BREAK:
                if t[j] == ":" and blank(j + 1):
                    break
                if t[j] == "#" and t[j - 1] in BLANK:
                    return False
                j += 1
            else:
                return False
            while j > at and t[j - 1] in BLANK:
                j -= 1
        while j < self.n and t[j] in BLANK:
            j += 1
        return j < self.n and t[j] == ":" and blank(j + 1)

    def key(self):
        start = self.i
        tag, anchor = self.properties()
        c = self.ch()
        if c in "'\"":
            node = self.quoted(single_line=True)
        elif c == "*":
            node = self.alias()
        elif c in "[{":
            node = self.flow_collection()
        else:
            node = self.plain(-1, key=True)
        return self.with_properties(node, tag, anchor, start)

    def mapping(self, c, indent):
        start, pairs, seen = self.i, [], set()
        end = start
        while True:
            if self.is_explicit_key():
                self.i += 1
                colon_end = self.i
                key = self.after_indicator(c, "entry")
                self.skip_to_content()
                if self.i < self.n and not self.marker() and self.col() == c and self.ch() == ":" and self.blank_after():
                    self.i += 1
                    colon_end = self.i
                    value = self.after_indicator(c, "entry")
                else:
                    value = self.empty(self.i)
            else:
                key = self.key()
                self.skip_blank()
                if self.ch() != ":":
                    self.error("a mapping key without ':'")
                self.i += 1
                colon_end = self.i
                value = self.after_indicator(c, "value")
            text = scalar_text(key)
            if text is not None and not isinstance(resolved(key), Empty):
                if text in seen:
                    self.error(f"the key {text!r} appears twice", key.span.start)
                seen.add(text)
            pairs.append((key, value))
            end = max(colon_end, key.span.end, value.span.end)
            self.skip_to_content()
            if self.i >= self.n or self.marker():
                break
            k = self.col()
            if k < c:
                break
            if k > c:
                self.error("a mapping entry indented more than the mapping")
            if self.is_entry():
                break
        return Mapping(Span(start, end), pairs=pairs)

    def sequence(self, c, indent):
        start, items = self.i, []
        end = start
        while True:
            self.i += 1
            dash_end = self.i
            item = self.after_indicator(c, "entry")
            items.append(item)
            end = max(dash_end, item.span.end)
            self.skip_to_content()
            if self.i >= self.n or self.marker():
                break
            k = self.col()
            if k < c:
                break
            if k > c:
                self.error("a sequence entry indented more than the sequence")
            if not self.is_entry():
                break
        return Sequence(Span(start, end), items=items)

    def inline(self, indent):
        c = self.ch()
        if c == "*":
            return self.alias()
        if c in "|>":
            if self.flow:
                self.error("a block scalar inside a flow collection")
            return self.block_scalar(indent)
        if c in "'\"":
            return self.quoted()
        if c in "[{":
            return self.flow_collection()
        if c in "@`":
            self.error(f"{c!r} is reserved and cannot start a plain scalar")
        if c in FLOW_INDICATORS or c in "#%":
            self.error(f"{c!r} cannot start a plain scalar")
        if c in "-?:" and self.blank_after():
            self.error(f"{c!r} followed by a space cannot start a plain scalar")
        return self.plain(indent)

    def alias(self):
        start = self.i
        name = self.anchor_name()
        node = Alias(Span(start, self.i), name=name, target=self.anchors.get(name))
        if node.target is None:
            self.error(f"the alias *{name} names no anchor defined before it", start)
        return node

    def plain(self, indent, key=False):
        start, t = self.i, self.t
        chunks, offsets = [], []
        spaces, space_offsets = [], []
        end = start
        min_col = indent + 1
        while True:
            if self.ch() == "#":
                break
            j = self.i
            while j < self.n:
                c = t[j]
                if c in BLANK + BREAK:
                    break
                if c == ":":
                    after = t[j + 1] if j + 1 < self.n else END
                    if after in BLANK + BREAK + END or (self.flow and after in FLOW_INDICATORS):
                        break
                if self.flow and c in FLOW_INDICATORS + "?":
                    break
                j += 1
            if j == self.i:
                break
            chunks += spaces
            offsets += space_offsets
            chunks.append(t[self.i:j])
            offsets += range(self.i, j)
            self.i = j
            end = j
            spaces, space_offsets = self.plain_spaces(single_line=key)
            if not spaces or self.ch() == "#" or (not self.flow and self.col() < min_col):
                break
            if not self.flow and self.marker():
                break
        if end == start:
            self.error("an empty plain scalar")
        if end < self.i:
            self.i = end
        value = "".join(chunks)
        return Scalar(Span(start, end), value=value, style="plain", offsets=tuple(offsets))

    def plain_spaces(self, single_line=False):
        t = self.t
        j = self.i
        while j < self.n and t[j] in BLANK:
            j += 1
        if j < self.n and t[j] == BREAK and single_line:
            return [], []
        if j < self.n and t[j] == BREAK:
            line_break = j
            j += 1
            breaks = []
            while j < self.n and t[j] in BLANK + BREAK:
                if t[j] == BREAK:
                    breaks.append(j)
                j += 1
            self.i = j
            if self.marker():
                return [], []
            for b in [line_break, *breaks]:
                if self.marker(b + 1):
                    return [], []
            if breaks:
                return ["\n"] * len(breaks), list(breaks)
            return [" "], [line_break]
        if j > self.i:
            spaces = t[self.i:j]
            offsets = list(range(self.i, j))
            self.i = j
            return [spaces], offsets
        return [], []

    def quoted(self, single_line=False):
        start, t = self.i, self.t
        quote = t[start]
        double = quote == '"'
        self.i += 1
        chunks, offsets = [], []
        while True:
            if self.i >= self.n:
                self.error("a quoted scalar that does not close", start)
            c = t[self.i]
            if c == quote:
                if not double and self.ch(1) == "'":
                    chunks.append("'")
                    offsets.append(self.i)
                    self.i += 2
                    continue
                self.i += 1
                break
            if double and c == "\\":
                self.escape(chunks, offsets, start, single_line)
                continue
            if c in BLANK + BREAK:
                self.quoted_spaces(chunks, offsets, start, single_line)
                continue
            chunks.append(c)
            offsets.append(self.i)
            self.i += 1
        return Scalar(Span(start, self.i), value="".join(chunks), style="double" if double else "single",
                      offsets=tuple(offsets))

    def escape(self, chunks, offsets, start, single_line):
        at = self.i
        self.i += 1
        c = self.ch()
        if c in ESCAPES:
            chunks.append(ESCAPES[c])
            offsets.append(at)
            self.i += 1
        elif c in ESCAPE_CODES:
            size = ESCAPE_CODES[c]
            digits = self.t[self.i + 1:self.i + 1 + size]
            if len(digits) != size or not set(digits) <= HEX:
                self.error(f"a \\{c} escape needs {size} hexadecimal digits", at)
            chunks.append(chr(int(digits, 16)))
            offsets.append(at)
            self.i += 1 + size
        elif c == BREAK:
            if single_line:
                self.error("a quoted key that goes on to the next line", start)
            self.i += 1
            self.quoted_breaks(chunks, offsets, start)
        else:
            self.error(f"an unknown escape \\{c}", at)

    def quoted_spaces(self, chunks, offsets, start, single_line):
        t = self.t
        j = self.i
        while j < self.n and t[j] in BLANK:
            j += 1
        if j >= self.n:
            self.error("a quoted scalar that does not close", start)
        if t[j] == BREAK:
            if single_line:
                self.error("a quoted key that goes on to the next line", start)
            line_break = j
            self.i = j + 1
            before = len(chunks)
            self.quoted_breaks(chunks, offsets, start)
            if len(chunks) == before:
                chunks.append(" ")
                offsets.append(line_break)
            return
        chunks.append(t[self.i:j])
        offsets += range(self.i, j)
        self.i = j

    def quoted_breaks(self, chunks, offsets, start):
        t = self.t
        while True:
            if self.marker():
                self.error("a document marker inside a quoted scalar", start)
            while self.i < self.n and t[self.i] in BLANK:
                self.i += 1
            if self.i < self.n and t[self.i] == BREAK:
                chunks.append("\n")
                offsets.append(self.i)
                self.i += 1
            else:
                return

    def block_scalar(self, indent):
        start, t = self.i, self.t
        folded = t[start] == ">"
        self.i += 1
        chomping, increment = None, None
        for _ in range(2):
            c = self.ch()
            if c in "+-" and chomping is None:
                chomping = c == "+"
                self.i += 1
            elif c.isdigit() and c != END and increment is None:
                increment = int(c)
                if increment == 0:
                    self.error("a block scalar indentation indicator of 0")
                self.i += 1
        if self.ch() not in BLANK + BREAK + END:
            self.error(f"a block scalar header with {self.ch()!r}")
        self.skip_blank()
        if self.ch() == "#":
            self.comment()
        if self.ch() not in BREAK + END:
            self.error("content after a block scalar header")
        if self.ch() == BREAK:
            self.i += 1
        min_indent = max(indent + 1, 1)
        if increment is None:
            breaks, max_indent = self.block_indentation()
            content_indent = max(min_indent, max_indent)
        else:
            content_indent = min_indent + increment - 1
            breaks = self.block_breaks(content_indent)
        chunks, offsets = [], []
        line_break = None
        end = self.i
        while self.col() == content_indent and self.i < self.n:
            for b in breaks:
                chunks.append("\n")
                offsets.append(b)
            leading_text = t[self.i] not in BLANK
            j = t.find(BREAK, self.i)
            j = self.n if j < 0 else j
            chunks.append(t[self.i:j])
            offsets += range(self.i, j)
            end = j
            self.i = j
            line_break = None
            if self.i < self.n:
                line_break = self.i
                self.i += 1
            breaks = self.block_breaks(content_indent)
            if self.col() == content_indent and self.i < self.n:
                if folded and line_break is not None and leading_text and t[self.i] not in BLANK:
                    if not breaks:
                        chunks.append(" ")
                        offsets.append(line_break)
                else:
                    chunks.append("\n")
                    offsets.append(line_break)
            else:
                break
        if chomping is not False and line_break is not None:
            chunks.append("\n")
            offsets.append(line_break)
        if chomping is True:
            for b in breaks:
                chunks.append("\n")
                offsets.append(b)
        return Scalar(Span(start, max(end, start + 1)), value="".join(chunks), style="folded" if folded else "literal",
                      offsets=tuple(offsets))

    def block_indentation(self):
        t = self.t
        breaks, max_indent = [], 0
        while self.i < self.n and t[self.i] in " " + BREAK:
            if t[self.i] == BREAK:
                breaks.append(self.i)
            else:
                max_indent = max(max_indent, self.col() + 1)
            self.i += 1
        return breaks, max_indent

    def block_breaks(self, content_indent):
        t = self.t
        breaks = []
        while self.col() < content_indent and self.i < self.n and t[self.i] == " ":
            self.i += 1
        while self.i < self.n and t[self.i] == BREAK:
            breaks.append(self.i)
            self.i += 1
            while self.col() < content_indent and self.i < self.n and t[self.i] == " ":
                self.i += 1
        return breaks

    def flow_space(self):
        t = self.t
        while self.i < self.n:
            c = t[self.i]
            if c in BLANK + BREAK:
                self.i += 1
            elif c == "#" and (self.i == 0 or t[self.i - 1] in BLANK + BREAK):
                self.comment()
            else:
                return

    def flow_node(self):
        self.flow_space()
        start = self.i
        if self.ch() in ",]}" or (self.ch() == ":" and (self.blank_after() or self.ch(1) in FLOW_INDICATORS)):
            return self.empty(start)
        tag, anchor = self.properties()
        self.flow_space()
        if self.ch() in ",]}" or (self.ch() == ":" and (self.blank_after() or self.ch(1) in FLOW_INDICATORS)):
            return self.empty(start, tag, anchor)
        if self.marker():
            self.error("a document marker inside a flow collection")
        return self.with_properties(self.inline(-1), tag, anchor, start)

    def flow_collection(self):
        start, t = self.i, self.t
        opening = t[start]
        closing = "]" if opening == "[" else "}"
        self.i += 1
        self.flow += 1
        entries = []
        while True:
            self.flow_space()
            if self.i >= self.n:
                self.error("a flow collection that does not close", start)
            if self.ch() == closing:
                self.i += 1
                break
            entry_start = self.i
            if self.is_explicit_key():
                self.i += 1
                key = self.flow_node()
                self.flow_space()
                if self.ch() == ":":
                    self.i += 1
                    value = self.flow_node()
                else:
                    value = self.empty(self.i)
                entries.append((entry_start, key, value))
            else:
                node = self.flow_node()
                self.flow_space()
                if self.ch() == ":":
                    self.i += 1
                    value = self.flow_node()
                    entries.append((entry_start, node, value))
                else:
                    entries.append((entry_start, node, None))
            self.flow_space()
            if self.ch() == ",":
                self.i += 1
            elif self.ch() != closing:
                self.error(f"a flow collection expects ',' or {closing!r} here")
        self.flow -= 1
        span = Span(start, self.i)
        if opening == "[":
            items = []
            for at, key, value in entries:
                if value is None:
                    items.append(key)
                else:
                    items.append(Mapping(Span(at, value.span.end), pairs=[(key, value)], flow=True))
            return Sequence(span, items=items, flow=True)
        pairs, seen = [], set()
        for at, key, value in entries:
            text = scalar_text(key)
            if text is not None and not isinstance(resolved(key), Empty):
                if text in seen:
                    self.error(f"the key {text!r} appears twice", at)
                seen.add(text)
            pairs.append((key, value if value is not None else self.empty(key.span.end)))
        return Mapping(span, pairs=pairs, flow=True)


def parse(text, name="<yaml>"):
    source = text if isinstance(text, Source) else Source(text, name)
    return _Parser(source).stream()


def loads(text, name="<yaml>"):
    stream = parse(text.replace("\r\n", "\n"), name)
    if len(stream.documents) > 1:
        raise YamlError(stream.source, stream.documents[1].span.start, "more than one document")
    if not stream.documents:
        return None
    return data(stream.documents[0].root)


def walk(node):
    node = node if not isinstance(node, Document) else node.root
    stack = [node]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        yield current
        if isinstance(current, Mapping):
            for k, v in reversed(current.pairs):
                stack += [v, k]
        elif isinstance(current, Sequence):
            stack += reversed(current.items)

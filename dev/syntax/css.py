import re
from dataclasses import dataclass, field

from .text import Comment, Source, Span, SyntaxProblem

URL = re.compile(r"url\(\s*(?=[^'\"\s])", re.I)
PLAIN = re.compile(r"[^/'\"{}()uU\\]+|.", re.S)


class CssError(SyntaxProblem):
    pass


@dataclass(eq=False)
class Token:
    kind: str
    span: Span
    text: str


@dataclass(eq=False)
class Sheet:
    source: Source
    tokens: list = field(default_factory=list)
    comments: list = field(default_factory=list)


class _Reader:
    def __init__(self, text, name):
        self.source = Source(text, name)
        self.t, self.n = text, len(text)
        self.sheet = Sheet(self.source)
        self.depth = []

    def error(self, message, at):
        raise CssError(self.source, at, message)

    def add(self, kind, start, end):
        self.sheet.tokens.append(Token(kind, Span(start, end), self.t[start:end]))
        return end

    def read(self):
        i = 0
        while i < self.n:
            c = self.t[i]
            if self.t.startswith("/*", i):
                end = self.t.find("*/", i + 2)
                if end < 0:
                    self.error("a comment that is never closed", i)
                self.sheet.comments.append(Comment(Span(i, end + 2), self.t[i + 2:end], block=True))
                i = self.add("comment", i, end + 2)
            elif c in "'\"":
                i = self.add("string", i, self.string(i))
            elif c == "\\":
                i = self.add("code", i, min(i + 2, self.n))
            elif (m := URL.match(self.t, i)) and (i == 0 or not re.match(r"[\w-]", self.t[i - 1])):
                end = self.t.find(")", m.end())
                if end < 0:
                    self.error("a url( that is never closed", i)
                i = self.add("url", i, end + 1)
            elif c in "{}":
                self.brace(c, i)
                i = self.add("code", i, i + 1)
            else:
                m = PLAIN.match(self.t, i)
                i = self.add("code", i, m.end())
        if self.depth:
            self.error("a block that is never closed", self.depth[-1])
        return self.sheet

    def brace(self, c, i):
        if c == "{":
            self.depth.append(i)
        elif not self.depth:
            self.error("a '}' with no block to close", i)
        else:
            self.depth.pop()

    def string(self, i):
        quote, j = self.t[i], i + 1
        while j < self.n and self.t[j] != quote:
            if self.t[j] == "\\":
                j += 2
            elif self.t[j] in "\n\r\f":
                self.error("a string that runs into the end of the line", j)
            else:
                j += 1
        if j >= self.n:
            self.error("a string that is never closed", i)
        return j + 1


def parse(text, name="<css>"):
    return _Reader(text, name).read()

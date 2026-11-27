import bisect
from dataclasses import dataclass


class Source:
    def __init__(self, text, name="<text>"):
        self.text = text
        self.name = name
        self.starts = [0]
        self.starts += [i + 1 for i, c in enumerate(text) if c == "\n"]

    def line(self, offset):
        return bisect.bisect_right(self.starts, offset)

    def column(self, offset):
        return offset - self.starts[self.line(offset) - 1] + 1

    def line_start(self, offset):
        return self.starts[self.line(offset) - 1]

    def where(self, offset):
        return f"{self.name}:{self.line(offset)}:{self.column(offset)}"

    def lines_of(self, start, end):
        return range(self.line(start), self.line(max(start, end - 1)) + 1)


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass(frozen=True)
class Comment:
    span: Span
    text: str
    block: bool = False


class SyntaxProblem(ValueError):
    def __init__(self, source, offset, message):
        super().__init__(f"{source.where(offset)}: {message}")
        self.source, self.offset, self.message = source, offset, message

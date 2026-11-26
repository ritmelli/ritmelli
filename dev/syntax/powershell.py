import re
from dataclasses import dataclass, field

from .text import Comment, Source, Span, SyntaxProblem

SINGLE_QUOTES = "'\u2018\u2019\u201a\u201b"
DOUBLE_QUOTES = '"\u201c\u201d\u201e'
DASHES = "-\u2013\u2014\u2015"
BLANK = " \t\f\v\u00a0"
END = "\0"
KEYWORDS = {"begin", "break", "catch", "class", "continue", "data", "define", "do", "dynamicparam", "else", "elseif",
            "end", "enum", "exit", "filter", "finally", "for", "foreach", "from", "function", "hidden", "if", "in",
            "param", "process", "return", "static", "switch", "throw", "trap", "try", "until", "using", "var", "while",
            "workflow", "parallel", "sequence", "inlinescript", "configuration"}
COMPARISON = {"eq", "ne", "gt", "ge", "lt", "le", "like", "notlike", "match", "notmatch", "replace", "contains",
              "notcontains", "in", "notin", "split", "join", "is", "isnot", "as", "shl", "shr"}
CASED = {p + op for op in COMPARISON - {"is", "isnot", "as", "join"} for p in ("i", "c")}
LOGICAL = {"and", "or", "xor"}
BITWISE = {"band", "bor", "bxor"}
BINARY_WORDS = {**{op: 3 for op in COMPARISON | CASED}, **{op: 1 for op in LOGICAL}, **{op: 2 for op in BITWISE},
                "f": 6}
UNARY_WORDS = {"not", "bnot", "split", "isplit", "csplit", "join"}
NUMBER = re.compile(r"(?:0[xX][0-9a-fA-F]+|0[bB][01]+|(?:\d+(?:\.(?!\.)\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"

                    r"(?:[dD]|[lL]|[uU][lL]?|[yY]|[sS]|[nN])?(?:[kKmMgGtTpP][bB])?")
REDIRECTION = re.compile(r"(?:[1-6*]?>>?(?:&[12])?|<)")
NAME_START = re.compile(r"[\w?]", re.UNICODE)
VARIABLE_NAME = re.compile(r"(?:(?:global|local|private|script|using|workflow|env|function|variable|alias|[A-Za-z]\w*):"
                           r"(?=[\w?]))?[\w?]+", re.UNICODE)
WORD = re.compile(r"[\w-]+", re.UNICODE)
LABEL = re.compile(r"\w+", re.UNICODE)


class PowerShellError(SyntaxProblem):
    pass


@dataclass(eq=False)
class Node:
    span: Span


@dataclass(eq=False)
class Block(Node):
    statements: list = field(default_factory=list)


@dataclass(eq=False)
class Attribute(Node):
    name: str = ""
    arguments: list = field(default_factory=list)


@dataclass(eq=False)
class Param(Node):
    attributes: list = field(default_factory=list)
    variable: Node = None
    default: Node = None


@dataclass(eq=False)
class ParamBlock(Node):
    attributes: list = field(default_factory=list)
    params: list = field(default_factory=list)


@dataclass(eq=False)
class ScriptBlock(Node):
    params: ParamBlock = None
    blocks: dict = field(default_factory=dict)
    usings: list = field(default_factory=list)

    @property
    def statements(self):
        return [s for b in self.blocks.values() for s in b.statements]


@dataclass(eq=False)
class Pipeline(Node):
    elements: list = field(default_factory=list)
    background: bool = False


@dataclass(eq=False)
class Chain(Node):
    left: Node = None
    op: str = ""
    right: Node = None


@dataclass(eq=False)
class Command(Node):
    name: str = None
    name_node: Node = None
    invocation: str = None
    elements: list = field(default_factory=list)
    redirections: list = field(default_factory=list)

    def parameters(self):
        return [e for e in self.elements if isinstance(e, CommandParameter)]


@dataclass(eq=False)
class CommandParameter(Node):
    name: str = ""
    argument: Node = None


@dataclass(eq=False)
class Bareword(Node):
    text: str = ""
    parts: list = field(default_factory=list)


@dataclass(eq=False)
class Redirection(Node):
    operator: str = ""
    target: Node = None


@dataclass(eq=False)
class ExpressionElement(Node):
    expression: Node = None
    redirections: list = field(default_factory=list)


@dataclass(eq=False)
class Assign(Node):
    target: Node = None
    op: str = "="
    value: Node = None


@dataclass(eq=False)
class If(Node):
    clauses: list = field(default_factory=list)
    else_block: Block = None


@dataclass(eq=False)
class While(Node):
    label: str = None
    condition: Node = None
    body: Block = None


@dataclass(eq=False)
class DoLoop(Node):
    label: str = None
    body: Block = None
    condition: Node = None
    until: bool = False


@dataclass(eq=False)
class For(Node):
    label: str = None
    initializer: Node = None
    condition: Node = None
    iterator: Node = None
    body: Block = None


@dataclass(eq=False)
class Foreach(Node):
    label: str = None
    flags: list = field(default_factory=list)
    variable: Node = None
    iterable: Node = None
    body: Block = None


@dataclass(eq=False)
class Switch(Node):
    label: str = None
    flags: list = field(default_factory=list)
    condition: Node = None
    clauses: list = field(default_factory=list)
    default: Block = None


@dataclass(eq=False)
class Catch(Node):
    types: list = field(default_factory=list)
    body: Block = None


@dataclass(eq=False)
class Try(Node):
    body: Block = None
    catches: list = field(default_factory=list)
    finally_block: Block = None


@dataclass(eq=False)
class Trap(Node):
    type: str = None
    body: Block = None


@dataclass(eq=False)
class Function(Node):
    name: str = ""
    kind: str = "function"
    params: list = field(default_factory=list)
    body: ScriptBlock = None


@dataclass(eq=False)
class Flow(Node):
    kind: str = ""
    value: Node = None


@dataclass(eq=False)
class Using(Node):
    text: str = ""


@dataclass(eq=False)
class DataSection(Node):
    name: str = None
    body: Block = None


@dataclass(eq=False)
class TypeDefinition(Node):
    kind: str = "class"
    name: str = ""
    bases: list = field(default_factory=list)
    members: list = field(default_factory=list)


@dataclass(eq=False)
class Method(Node):
    name: str = ""
    static: bool = False
    params: list = field(default_factory=list)
    body: ScriptBlock = None


@dataclass(eq=False)
class Property(Node):
    name: str = ""
    default: Node = None


@dataclass(eq=False)
class Binary(Node):
    op: str = ""
    left: Node = None
    right: Node = None


@dataclass(eq=False)
class Unary(Node):
    op: str = ""
    operand: Node = None
    postfix: bool = False


@dataclass(eq=False)
class Ternary(Node):
    condition: Node = None
    then: Node = None
    otherwise: Node = None


@dataclass(eq=False)
class TypeName(Node):
    name: str = ""


@dataclass(eq=False)
class Cast(Node):
    type: TypeName = None
    operand: Node = None


@dataclass(eq=False)
class Member(Node):
    target: Node = None
    name: Node = None
    static: bool = False
    null_conditional: bool = False


@dataclass(eq=False)
class InvokeMember(Node):
    target: Node = None
    name: Node = None
    arguments: list = field(default_factory=list)
    static: bool = False
    null_conditional: bool = False


@dataclass(eq=False)
class Index(Node):
    target: Node = None
    index: Node = None
    null_conditional: bool = False


@dataclass(eq=False)
class Number(Node):
    text: str = ""


@dataclass(eq=False)
class String(Node):
    kind: str = "single"
    value: str = ""
    parts: list = field(default_factory=list)

    @property
    def expandable(self):
        return self.kind in ("double", "here-double")


@dataclass(eq=False)
class Variable(Node):
    name: str = ""
    splat: bool = False


@dataclass(eq=False)
class SubExpression(Node):
    kind: str = "$("
    statements: list = field(default_factory=list)


@dataclass(eq=False)
class Hashtable(Node):
    pairs: list = field(default_factory=list)


@dataclass(eq=False)
class ArrayLiteral(Node):
    items: list = field(default_factory=list)


@dataclass(eq=False)
class Paren(Node):
    pipeline: Node = None


@dataclass(eq=False)
class ScriptBlockExpression(Node):
    block: ScriptBlock = None


@dataclass(eq=False)
class Script:
    source: Source
    block: ScriptBlock
    comments: list
    tokens: list


class _Parser:
    def __init__(self, source):
        self.source = source
        self.t = source.text
        self.n = len(self.t)
        self.i = 0
        self.comments = {}
        self.tokens = {}
        self.last_end = 0
        self.comma = True

    def error(self, message, at=None):
        raise PowerShellError(self.source, self.i if at is None else at, message)

    def ch(self, k=0):
        j = self.i + k
        return self.t[j] if 0 <= j < self.n else END

    def token(self, start, end, kind):
        if end > start:
            self.tokens[start] = (start, end, kind)
            if kind not in ("comment", "continuation"):
                self.last_end = max(self.last_end, end)

    def end(self):
        return self.last_end

    def rewind(self, at, last_end):
        self.i, self.last_end = at, last_end
        self.tokens = {k: v for k, v in self.tokens.items() if k < at}
        self.comments = {k: v for k, v in self.comments.items() if k < at}

    def take(self, text, kind="operator"):
        if not self.t.startswith(text, self.i):
            self.error(f"expected {text!r}")
        self.token(self.i, self.i + len(text), kind)
        self.i += len(text)

    def word_at(self, at=None):
        at = self.i if at is None else at
        m = WORD.match(self.t, at)
        return m.group(0).lower() if m else ""

    def keyword(self, word):
        m = WORD.match(self.t, self.i)
        return bool(m) and m.group(0).lower() == word

    def ws(self, newlines=False):
        t = self.t
        while self.i < self.n:
            c = t[self.i]
            if c in BLANK:
                self.i += 1
            elif c == "`" and self.i + 1 < self.n and t[self.i + 1] == "\n":
                self.token(self.i, self.i + 2, "continuation")
                self.i += 2
            elif c == "\r" and self.i + 1 < self.n and t[self.i + 1] == "\n":
                self.i += 1
            elif c == "#":
                self.line_comment()
            elif c == "<" and self.i + 1 < self.n and t[self.i + 1] == "#":
                self.block_comment()
            elif c == "\n" and newlines:
                self.i += 1
            else:
                return

    def line_comment(self):
        start = self.i
        end = self.t.find("\n", start)
        end = self.n if end < 0 else end
        self.comments[start] = Comment(Span(start, end), self.t[start + 1:end])
        self.token(start, end, "comment")
        self.i = end

    def block_comment(self):
        start = self.i
        end = self.t.find("#>", start + 2)
        if end < 0:
            self.error("a block comment that does not close", start)
        self.comments[start] = Comment(Span(start, end + 2), self.t[start + 2:end], block=True)
        self.token(start, end + 2, "comment")
        self.i = end + 2

    def separators(self):
        while True:
            self.ws(newlines=True)
            if self.ch() == ";":
                self.take(";")
            else:
                return

    def script(self):
        block = self.script_block_body(start=0, closer="")
        if self.i < self.n:
            self.error("content after the end of the script")
        return Script(self.source, block, sorted(self.comments.values(), key=lambda c: c.span.start),
                      sorted(self.tokens.values()))

    def script_block_body(self, start, closer):
        usings, attributes = [], []
        self.separators()
        while self.keyword("using"):
            usings.append(self.using())
            self.separators()
        params = None
        save = (self.i, self.last_end)
        while self.ch() == "[":
            attributes.append(self.attribute())
            self.ws(newlines=True)
        if self.keyword("param") and self.after_word_is("("):
            params = self.param_block(attributes)
        elif attributes:
            self.rewind(*save)
            attributes = []
        blocks = {}
        self.separators()
        named = self.named_block_ahead()
        if named:
            while named:
                word_start = self.i
                self.take_word("keyword")
                self.ws(newlines=True)
                body = self.block()
                blocks[named] = Block(Span(word_start, body.span.end), body.statements)
                self.separators()
                named = self.named_block_ahead()
        else:
            statements = self.statements(closer)
            blocks["end"] = Block(Span(start, self.end()), statements)
        if closer and self.ch() != closer:
            self.error(f"expected {closer!r}")
        return ScriptBlock(Span(start, self.end()), params, blocks, usings)

    def named_block_ahead(self):
        w = self.word_at()
        if w in ("begin", "process", "end", "dynamicparam", "clean"):
            j = self.i + len(w)
            while j < self.n and self.t[j] in BLANK + "\n":
                j += 1
            if j < self.n and self.t[j] == "{":
                return w
        return None

    def after_word_is(self, c):
        j = self.i + len(self.word_at())
        while j < self.n and (self.t[j] in BLANK + "\n" or self.t.startswith("`\n", j)):
            j += 2 if self.t[j] == "`" else 1
        return j < self.n and self.t[j] == c

    def take_word(self, kind="word"):
        m = WORD.match(self.t, self.i)
        if not m:
            self.error("expected a word")
        self.token(self.i, m.end(), kind)
        self.i = m.end()
        return m.group(0)

    def using(self):
        start = self.i
        end = start
        while end < self.n and self.t[end] not in "\n;#":
            end += 1
        text = self.t[start:end].rstrip()
        self.token(start, start + len(text), "using")
        self.i = start + len(text)
        return Using(Span(start, self.end()), text)

    def statements(self, closer):
        out = []
        while True:
            self.separators()
            if self.i >= self.n or (closer and self.ch() == closer) or self.ch() in ")}" and closer != "":
                break
            if not closer and self.ch() in ")}":
                self.error(f"unexpected {self.ch()!r}")
            out.append(self.statement())
            self.ws()
            if self.ch() in "\n;":
                continue
            if self.i >= self.n or (closer and self.ch() == closer):
                break
            if self.ch() in ")}":
                break
            self.error(f"unexpected {self.ch()!r} after a statement")
        return out

    def block(self):
        start = self.i
        if self.ch() != "{":
            self.error("expected '{'")
        self.take("{")
        statements = self.statements("}")
        self.take("}")
        return Block(Span(start, self.end()), statements)

    def statement(self):
        start = self.i
        label = None
        m = LABEL.match(self.t, self.i + 1) if self.ch() == ":" else None
        if m and (self.t[m.end()] if m.end() < self.n else END) in BLANK + "\n" + END:
            label = m.group(0)
            self.token(self.i, m.end(), "label")
            self.i = m.end()
            self.ws(newlines=True)
        w = self.word_at()
        end_of_word = self.i + len(w)
        next_char = self.t[end_of_word] if end_of_word < self.n else ""
        if w and w in KEYWORDS and not (next_char and (next_char.isalnum() or next_char in "_-.\\/:")):
            node = self.keyword_statement(w, label, start)
            if node is not None:
                return node
        if label:
            self.error("a label must come before a loop or a switch")
        return self.chain()

    def keyword_statement(self, w, label, start):
        if w == "if":
            return self.if_statement(start)
        if w == "while":
            return self.while_statement(label, start)
        if w == "do":
            return self.do_statement(label, start)
        if w == "for":
            return self.for_statement(label, start)
        if w == "foreach":
            j = self.i + len(w)
            while j < self.n and self.t[j] in BLANK:
                j += 1
            if j < self.n and self.t[j] in "(-":
                return self.foreach_statement(label, start)
            return None
        if w == "switch":
            return self.switch_statement(label, start)
        if w == "try":
            return self.try_statement(start)
        if w == "trap":
            return self.trap_statement(start)
        if w in ("function", "filter", "workflow"):
            return self.function_statement(w, start)
        if w in ("return", "throw", "exit", "break", "continue"):
            return self.flow_statement(w, start)
        if w == "data":
            return self.data_statement(start)
        if w in ("class", "enum"):
            return self.type_definition(w, start)
        if w == "param":
            self.error("a param block is only allowed at the start of a script or script block")
        if w in ("using",):
            self.error("a using statement is only allowed at the start of a script")
        if w in ("configuration", "parallel", "sequence", "inlinescript"):
            self.error(f"the {w} keyword is not supported")
        if w in ("else", "elseif", "catch", "finally", "until", "begin", "process", "end", "in", "dynamicparam",
                 "hidden", "static", "var", "define", "from"):
            return None
        return None

    def paren_pipeline(self):
        self.ws()
        if self.ch() != "(":
            self.error("expected '('")
        self.take("(")
        self.ws(newlines=True)
        node = self.chain_or_statement()
        self.ws(newlines=True)
        self.take(")")
        return node

    def chain_or_statement(self):
        w = self.word_at()
        if w in ("if", "switch", "foreach", "for", "while", "do", "try"):
            return self.statement()
        return self.chain()

    def if_statement(self, start):
        clauses = []
        self.take_word("keyword")
        condition = self.paren_pipeline()
        self.ws(newlines=True)
        clauses.append((condition, self.block()))
        else_block = None
        while True:
            save = self.i
            self.ws(newlines=True)
            w = self.word_at()
            if w == "elseif":
                self.take_word("keyword")
                condition = self.paren_pipeline()
                self.ws(newlines=True)
                clauses.append((condition, self.block()))
            elif w == "else":
                self.take_word("keyword")
                self.ws(newlines=True)
                else_block = self.block()
                break
            else:
                self.i = save
                break
        return If(Span(start, self.end()), clauses, else_block)

    def while_statement(self, label, start):
        self.take_word("keyword")
        condition = self.paren_pipeline()
        self.ws(newlines=True)
        body = self.block()
        return While(Span(start, self.end()), label, condition, body)

    def do_statement(self, label, start):
        self.take_word("keyword")
        self.ws(newlines=True)
        body = self.block()
        self.ws(newlines=True)
        w = self.word_at()
        if w not in ("while", "until"):
            self.error("a do loop needs while or until")
        self.take_word("keyword")
        condition = self.paren_pipeline()
        return DoLoop(Span(start, self.end()), label, body, condition, w == "until")

    def for_statement(self, label, start):
        self.take_word("keyword")
        self.ws()
        self.take("(")
        parts = []
        for k in range(3):
            self.ws(newlines=True)
            if self.ch() in ";)":
                parts.append(None)
            else:
                parts.append(self.chain_or_statement())
            self.ws()
            if k < 2:
                if self.ch() == ";":
                    self.take(";")
                elif self.ch() == "\n":
                    self.i += 1
                elif self.ch() == ")":
                    parts += [None] * (2 - k)
                    break
                else:
                    self.error("expected ';' in a for loop")
        self.ws(newlines=True)
        self.take(")")
        self.ws(newlines=True)
        body = self.block()
        return For(Span(start, self.end()), label, *parts[:3], body)

    def foreach_statement(self, label, start):
        self.take_word("keyword")
        flags = []
        self.ws()
        while self.ch() in DASHES:
            flags.append(self.flag())
            self.ws()
            if flags[-1] == "throttlelimit":
                self.primary()
                self.ws()
        self.take("(")
        self.ws(newlines=True)
        variable = self.primary()
        if not isinstance(variable, Variable):
            self.error("a foreach loop needs a variable")
        self.ws(newlines=True)
        if self.word_at() != "in":
            self.error("expected 'in' in a foreach loop")
        self.take_word("keyword")
        self.ws(newlines=True)
        iterable = self.chain_or_statement()
        self.ws(newlines=True)
        self.take(")")
        self.ws(newlines=True)
        body = self.block()
        return Foreach(Span(start, self.end()), label, flags, variable, iterable, body)

    def flag(self):
        start = self.i
        m = WORD.match(self.t, self.i + 1)
        if not m:
            self.error("expected a flag name")
        self.token(start, m.end(), "parameter")
        self.i = m.end()
        return m.group(0).lower()

    def switch_statement(self, label, start):
        self.take_word("keyword")
        flags = []
        self.ws()
        condition = None
        while self.ch() in DASHES:
            flag = self.flag()
            flags.append(flag)
            self.ws()
            if "file".startswith(flag):
                condition = self.command_argument()
                self.ws()
        if condition is None:
            condition = self.paren_pipeline()
        self.ws(newlines=True)
        self.take("{")
        clauses, default = [], None
        while True:
            self.separators()
            if self.ch() == "}":
                break
            if self.keyword("default") and self.after_word_is("{"):
                self.take_word("keyword")
                self.ws(newlines=True)
                default = self.block()
                continue
            if self.ch() == "{":
                pattern = ScriptBlockExpression(Span(self.i, 0), self.script_block())
                pattern.span = Span(pattern.block.span.start, self.i)
            elif self.starts_expression():
                pattern = self.unary()
            else:
                pattern = self.bareword()
            self.ws(newlines=True)
            clauses.append((pattern, self.block()))
        self.take("}")
        return Switch(Span(start, self.end()), label, flags, condition, clauses, default)

    def try_statement(self, start):
        self.take_word("keyword")
        self.ws(newlines=True)
        body = self.block()
        catches, finally_block = [], None
        while True:
            save = self.i
            self.ws(newlines=True)
            w = self.word_at()
            if w == "catch":
                catch_start = self.i
                self.take_word("keyword")
                self.ws()
                types = []
                while self.ch() == "[":
                    types.append(self.type_name().name)
                    self.ws()
                    if self.ch() == ",":
                        self.take(",")
                        self.ws(newlines=True)
                self.ws(newlines=True)
                block = self.block()
                catches.append(Catch(Span(catch_start, self.end()), types, block))
            elif w == "finally":
                self.take_word("keyword")
                self.ws(newlines=True)
                finally_block = self.block()
                break
            else:
                self.i = save
                break
        if not catches and finally_block is None:
            self.error("a try needs a catch or a finally", start)
        return Try(Span(start, self.end()), body, catches, finally_block)

    def trap_statement(self, start):
        self.take_word("keyword")
        self.ws()
        type_ = self.type_name().name if self.ch() == "[" else None
        self.ws(newlines=True)
        body = self.block()
        return Trap(Span(start, self.end()), type_, body)

    def function_statement(self, kind, start):
        self.take_word("keyword")
        self.ws()
        name_start = self.i
        j = self.i
        while j < self.n and self.t[j] not in BLANK + "\n(){};":
            j += 1
        if j == name_start:
            self.error("a function without a name")
        name = self.t[name_start:j]
        self.token(name_start, j, "function-name")
        self.i = j
        self.ws()
        params = []
        if self.ch() == "(":
            params = self.param_list()
            self.ws(newlines=True)
        else:
            self.ws(newlines=True)
        if self.ch() != "{":
            self.error("expected '{' for the function body")
        body = self.script_block()
        return Function(Span(start, self.end()), name, kind, params, body)

    def script_block(self):
        start = self.i
        self.take("{")
        body = self.script_block_body(start, "}")
        self.take("}")
        body.span = Span(start, self.end())
        return body

    def flow_statement(self, kind, start):
        self.take_word("keyword")
        self.ws()
        value = None
        if not self.at_statement_end():
            if kind in ("break", "continue") and not self.starts_expression():
                value = self.bareword()
            else:
                value = self.chain()
        return Flow(Span(start, self.end()), kind, value)

    def at_statement_end(self):
        c = self.ch()
        return c in (END, "\n", ";", ")", "}") or (c == "|" and self.ch(1) == "|") or (c == "&" and self.ch(1) == "&")

    def data_statement(self, start):
        self.take_word("keyword")
        self.ws()
        name = None
        if self.ch() not in "{-":
            name = self.take_word("word")
            self.ws()
        while self.ch() in DASHES:
            self.flag()
            self.ws()
            self.command_argument()
            self.ws()
        self.ws(newlines=True)
        return DataSection(Span(start, self.end()), name, self.block())

    def type_definition(self, kind, start):
        self.take_word("keyword")
        self.ws()
        name = self.take_word("word")
        bases = []
        self.ws()
        if self.ch() == ":":
            self.take(":")
            while True:
                self.ws()
                bases.append(self.take_dotted())
                self.ws()
                if self.ch() == ",":
                    self.take(",")
                else:
                    break
        self.ws(newlines=True)
        self.take("{")
        members = []
        while True:
            self.separators()
            if self.ch() == "}":
                break
            members.append(self.enum_member() if kind == "enum" else self.class_member())
        self.take("}")
        return TypeDefinition(Span(start, self.end()), kind, name, bases, members)

    def take_dotted(self):
        m = re.compile(r"[\w.]+").match(self.t, self.i)
        if not m:
            self.error("expected a type name")
        self.token(self.i, m.end(), "type")
        self.i = m.end()
        return m.group(0)

    def enum_member(self):
        start = self.i
        name = self.take_word("word")
        self.ws()
        default = None
        if self.ch() == "=":
            self.take("=")
            self.ws()
            default = self.expression()
        return Property(Span(start, self.end()), name, default)

    def class_member(self):
        start = self.i
        static = False
        while self.word_at() in ("static", "hidden"):
            static = static or self.word_at() == "static"
            self.take_word("keyword")
            self.ws(newlines=True)
        while self.ch() == "[":
            self.attribute()
            self.ws(newlines=True)
        while self.word_at() in ("static", "hidden"):
            static = static or self.word_at() == "static"
            self.take_word("keyword")
            self.ws(newlines=True)
        if self.ch() == "$":
            variable = self.variable()
            self.ws()
            default = None
            if self.ch() == "=":
                self.take("=")
                self.ws(newlines=True)
                default = self.chain_or_statement()
            return Property(Span(start, self.end()), variable.name, default)
        name = self.take_word("word")
        self.ws()
        params = self.param_list()
        self.ws(newlines=True)
        if self.ch() == ":":
            self.take(":")
            self.ws()
            self.take_word("keyword")
            self.ws()
            self.method_arguments()
            self.ws(newlines=True)
        body = self.script_block()
        return Method(Span(start, self.end()), name, static, params, body)

    def param_block(self, attributes):
        start = attributes[0].span.start if attributes else self.i
        self.take_word("keyword")
        self.ws(newlines=True)
        params = self.param_list()
        return ParamBlock(Span(start, self.end()), attributes, params)

    def param_list(self):
        self.take("(")
        params = []
        while True:
            self.ws(newlines=True)
            if self.ch() == ")":
                break
            params.append(self.param())
            self.ws(newlines=True)
            if self.ch() == ",":
                self.take(",")
            elif self.ch() != ")":
                self.error("expected ',' or ')' in a parameter list")
        self.take(")")
        return params

    def param(self):
        start = self.i
        attributes = []
        while self.ch() == "[":
            attributes.append(self.attribute())
            self.ws(newlines=True)
        if self.ch() != "$":
            self.error("expected a parameter variable")
        variable = self.variable()
        self.ws()
        default = None
        if self.ch() == "=":
            self.take("=")
            self.ws(newlines=True)
            default = self.without_comma(self.expression)
        return Param(Span(start, self.end()), attributes, variable, default)

    def attribute(self):
        start = self.i
        self.take("[")
        self.ws()
        name = self.type_text()
        self.ws()
        arguments = []
        if self.ch() == "(":
            self.take("(")
            while True:
                self.ws(newlines=True)
                if self.ch() == ")":
                    break
                if WORD.match(self.t, self.i) and self.named_argument_ahead():
                    arg_start = self.i
                    key = self.take_word("word")
                    self.ws()
                    value = None
                    if self.ch() == "=":
                        self.take("=")
                        self.ws(newlines=True)
                        value = self.without_comma(self.expression)
                    arguments.append(Binary(Span(arg_start, self.end()), "=", Bareword(Span(arg_start, arg_start + len(key)), key), value))
                else:
                    arguments.append(self.without_comma(self.expression))
                self.ws(newlines=True)
                if self.ch() == ",":
                    self.take(",")
                elif self.ch() != ")":
                    self.error("expected ',' or ')' in an attribute")
            self.take(")")
            self.ws()
        self.take("]")
        return Attribute(Span(start, self.end()), name, arguments)

    def named_argument_ahead(self):
        m = WORD.match(self.t, self.i)
        j = m.end()
        while j < self.n and self.t[j] in BLANK:
            j += 1
        return j >= self.n or self.t[j] in "=,)\n"

    def type_text(self):
        start = self.i
        depth = 0
        while self.i < self.n:
            c = self.t[self.i]
            if c == "[":
                depth += 1
            elif c == "]":
                if depth == 0:
                    break
                depth -= 1
            elif c in "()\n" and depth == 0:
                break
            self.i += 1
        name = self.t[start:self.i].strip()
        if not name:
            self.error("expected a type name", start)
        self.token(start, self.i, "type")
        return name

    def type_name(self):
        start = self.i
        self.take("[")
        name = self.type_text()
        self.take("]")
        return TypeName(Span(start, self.end()), name)

    def chain(self):
        start = self.i
        left = self.pipeline()
        self.ws()
        while self.ch() in "&|" and self.ch(1) == self.ch():
            op = self.ch() * 2
            self.take(op)
            self.ws(newlines=True)
            right = self.pipeline()
            left = Chain(Span(start, self.end()), left, op, right)
            self.ws()
        return left

    def assignment_op(self):
        for op in ("??=", "+=", "-=", "*=", "/=", "%=", "="):
            if self.t.startswith(op, self.i) and not (op == "=" and self.ch(1) == "="):
                return op
        if self.ch() in DASHES[1:] and self.ch(1) == "=":
            return self.t[self.i:self.i + 2]
        return None

    def pipeline(self):
        start = self.i
        first = self.pipeline_element(first=True)
        if isinstance(first, ExpressionElement) and not first.redirections:
            self.ws()
            op = self.assignment_op()
            if op:
                self.take(op)
                self.ws(newlines=True)
                value = self.chain_or_statement()
                return Assign(Span(start, self.end()), first.expression, op, value)
        elements = [first]
        background = False
        while True:
            self.ws()
            if self.ch() == "|" and self.ch(1) != "|":
                self.take("|")
                self.ws(newlines=True)
                elements.append(self.pipeline_element(first=False))
            elif self.ch() == "&" and self.ch(1) != "&":
                self.take("&")
                background = True
                break
            else:
                break
        return Pipeline(Span(start, self.end()), elements, background)

    def starts_expression(self):
        c = self.ch()
        if c == END:
            return False
        if c in "$(" or c in SINGLE_QUOTES + DOUBLE_QUOTES or c == "[" or c == "{" or c == "!" or c == ",":
            return True
        if c == "@":
            return self.ch(1) in "({" or self.ch(1) in SINGLE_QUOTES + DOUBLE_QUOTES or bool(
                NAME_START.match(self.ch(1) or " "))
        if c in "+" and self.ch(1) in "+":
            return True
        if c in DASHES:
            nxt = self.ch(1)
            if nxt in DASHES:
                return True
            if nxt.isdigit() or nxt == ".":
                return True
            w = self.word_at(self.i + 1)
            return w in UNARY_WORDS
        if c.isdigit() or (c == "." and self.ch(1).isdigit()):
            return self.number_end(self.i) is not None
        return False

    def number_end(self, at):
        m = NUMBER.match(self.t, at)
        if not m:
            return None
        end = m.end()
        nxt = self.t[end] if end < self.n else ""
        if nxt and (nxt.isalnum() or nxt in "_\\:$"):
            return None
        if nxt == "." and not self.t.startswith("..", end):
            if end + 1 < self.n and (self.t[end + 1].isalpha() or self.t[end + 1] == "_"):
                return end
            return None
        return end

    def pipeline_element(self, first):
        self.ws()
        start = self.i
        c = self.ch()
        if c == END or c in "\n;)}|":
            self.error("an empty pipeline element")
        if c == "&" and self.ch(1) != "&" or (c == "." and self.dot_source_ahead()):
            return self.command()
        if self.starts_expression():
            if not first:
                self.error("an expression is only allowed as the first element of a pipeline")
            expression = self.expression()
            redirections = self.redirections()
            return ExpressionElement(Span(start, self.end()), expression, redirections)
        return self.command()

    def dot_source_ahead(self):
        return self.ch(1) in BLANK + "$({" + SINGLE_QUOTES + DOUBLE_QUOTES

    def redirections(self):
        out = []
        while True:
            save = self.i
            self.ws()
            m = REDIRECTION.match(self.t, self.i)
            if not m:
                self.i = save
                return out
            out.append(self.redirection(m))

    def redirection(self, m):
        start = self.i
        op = m.group(0)
        self.token(start, m.end(), "redirection")
        self.i = m.end()
        target = None
        if "&" not in op:
            self.ws()
            target = self.command_argument()
        return Redirection(Span(start, self.end()), op, target)

    def command(self):
        start = self.i
        invocation = None
        if self.ch() == "&" or self.ch() == "." and self.dot_source_ahead():
            invocation = self.ch()
            self.take(invocation)
            self.ws()
            if self.starts_expression() or self.ch() == "{":
                name_node = self.postfix(self.primary(), argument_mode=True)
            else:
                name_node = self.bareword()
        elif self.ch() in SINGLE_QUOTES + DOUBLE_QUOTES:
            name_node = self.string()
        else:
            name_node = self.bareword()
        name = name_node.text if isinstance(name_node, Bareword) else (
            name_node.value if isinstance(name_node, String) and not name_node.parts else None)
        elements, redirections = [], []
        while True:
            self.ws()
            if self.at_command_end():
                break
            m = REDIRECTION.match(self.t, self.i)
            if m and (self.ch() in "<>" or self.t[m.end() - 1] in ">&" or ">" in m.group(0)):
                redirections.append(self.redirection(m))
                continue
            if self.t.startswith("--%", self.i):
                raw_start = self.i
                end = raw_start + 3
                while end < self.n and self.t[end] not in "\n|":
                    end += 1
                self.token(raw_start, end, "verbatim")
                elements.append(Bareword(Span(raw_start, end), self.t[raw_start:end]))
                self.i = end
                break
            if self.ch() in DASHES and self.parameter_ahead():
                elements.append(self.parameter())
                continue
            elements.append(self.command_argument())
        return Command(Span(start, self.end()), name, name_node, invocation, elements, redirections)

    def at_command_end(self):
        c = self.ch()
        if c == END or c in "\n;)}":
            return True
        if c == "|":
            return True
        if c == "&":
            return True
        return False

    def parameter_ahead(self):
        nxt = self.ch(1)
        if nxt == END or nxt in BLANK + "\n;|)}":
            return False
        if nxt.isdigit() or nxt == ".":
            return self.number_end(self.i + 1) is None
        return nxt.isalpha() or nxt in "_?" + DASHES

    def parameter(self):
        start = self.i
        j = self.i + 1
        while j < self.n and self.t[j] not in BLANK + "\n;|&(){},:" + SINGLE_QUOTES + DOUBLE_QUOTES + "<>":
            if self.t[j] == "`":
                j += 2
                continue
            j += 1
        name = self.t[start + 1:j]
        self.token(start, j, "parameter")
        self.i = j
        argument = None
        if self.ch() == ":" and not (name.startswith(tuple(DASHES))):
            self.take(":")
            if self.ch() in BLANK:
                self.ws()
            argument = self.command_argument()
        return CommandParameter(Span(start, self.end()), name, argument)

    def command_argument(self):
        start = self.i
        item = self.single_argument()
        items = [item]
        while True:
            save = self.i
            self.ws()
            if self.ch() == ",":
                self.take(",")
                self.ws(newlines=True)
                items.append(self.single_argument())
            else:
                self.i = save
                break
        if len(items) == 1:
            return item
        return ArrayLiteral(Span(start, self.end()), items)

    def single_argument(self):
        c = self.ch()
        start = self.i
        if c in "$(" or c == "{" or (c == "@" and (self.ch(1) in "({" or self.ch(1) in SINGLE_QUOTES + DOUBLE_QUOTES
                                                    or NAME_START.match(self.ch(1) or " "))):
            node = self.postfix(self.primary(argument_mode=True), argument_mode=True)
            if self.i < self.n and self.t[self.i] not in BLANK + "\n;|&(){},<>" and not self.t.startswith("`\n", self.i):
                rest = self.bareword()
                return Bareword(Span(start, self.end()), self.t[start:self.i], [node, *rest.parts])
            return node
        if c in SINGLE_QUOTES + DOUBLE_QUOTES:
            node = self.postfix(self.string(), argument_mode=True)
            if self.i < self.n and self.t[self.i] not in BLANK + "\n;|&(){},<>" and not self.t.startswith("`\n", self.i):
                rest = self.bareword()
                return Bareword(Span(start, self.end()), self.t[start:self.i], [node, *rest.parts])
            return node
        if c.isdigit() or (c in DASHES + "." and (self.ch(1).isdigit() or self.ch(1) == ".")):
            j = self.i + (1 if c in DASHES else 0)
            end = self.number_end(j)
            if end is not None and (end >= self.n or self.t[end] in BLANK + "\n;|&)},<>"):
                self.token(start, end, "number")
                self.i = end
                return Number(Span(start, end), self.t[start:end])
        return self.bareword()

    def bareword(self):
        start, t = self.i, self.t
        parts = []
        j = segment = self.i
        while j < self.n:
            c = t[j]
            if c in BLANK + "\n;|&(){},":
                break
            if c in "<>" or (c in "123456*" and j + 1 < self.n and t[j + 1] == ">" and j == start):
                break
            if c == "`":
                if j + 1 < self.n and t[j + 1] == "\n":
                    break
                j += 2
                continue
            if c in SINGLE_QUOTES + DOUBLE_QUOTES:
                self.token(segment, j, "bareword")
                self.i = j
                parts.append(self.string())
                j = segment = self.i
                continue
            if c == "$" and j + 1 < self.n and (t[j + 1] in "({" or NAME_START.match(t[j + 1])):
                self.token(segment, j, "bareword")
                self.i = j
                parts.append(self.postfix(self.primary(argument_mode=True), argument_mode=True))
                j = segment = self.i
                continue
            j += 1
        if j == start and not parts:
            self.error(f"unexpected {t[start] if start < self.n else 'end'!r}")
        self.token(segment, j, "bareword")
        self.i = j
        return Bareword(Span(start, j), t[start:j], parts)

    def expression(self):
        start = self.i
        condition = self.binary(1)
        save = self.i
        self.ws()
        if self.ch() == "?" and self.ch(1) in BLANK + "\n":
            self.take("?")
            self.ws(newlines=True)
            then = self.expression()
            self.ws(newlines=True)
            self.take(":")
            self.ws(newlines=True)
            otherwise = self.expression()
            return Ternary(Span(start, self.end()), condition, then, otherwise)
        self.i = save
        return condition

    def binary_op_ahead(self):
        c = self.ch()
        if c in DASHES and self.ch(1) not in DASHES:
            w = self.word_at(self.i + 1)
            if w in BINARY_WORDS:
                end = self.i + 1 + len(w)
                if end >= self.n or not (self.t[end].isalnum() or self.t[end] == "_"):
                    return w, BINARY_WORDS[w], 1 + len(w)
        if c == "?" and self.ch(1) == "?" and self.ch(2) != "=":
            return "??", 7, 2
        if c == "." and self.ch(1) == ".":
            return "..", 8, 2
        if c in "*/%" and self.ch(1) != "=":
            return c, 5, 1
        if c == "+" and self.ch(1) not in "=+":
            return c, 4, 1
        if c in DASHES and self.ch(1) not in "=" + DASHES:
            return "-", 4, 1
        return None

    def binary(self, level):
        start = self.i
        left = self.array_literal() if level > 8 else self.binary(level + 1) if level < 8 else self.array_literal()
        while True:
            save = self.i
            self.ws()
            op = self.binary_op_ahead()
            if not op or op[1] != level:
                self.i = save
                return left
            name, _, size = op
            self.token(self.i, self.i + size, "operator")
            self.i += size
            self.ws(newlines=True)
            right = self.binary(level + 1) if level < 8 else self.array_literal()
            left = Binary(Span(start, self.end()), name, left, right)

    def without_comma(self, parse):
        saved, self.comma = self.comma, False
        try:
            return parse()
        finally:
            self.comma = saved

    def with_comma(self, parse):
        saved, self.comma = self.comma, True
        try:
            return parse()
        finally:
            self.comma = saved

    def array_literal(self):
        start = self.i
        first = self.unary()
        items = [first]
        while self.comma:
            save = self.i
            self.ws()
            if self.ch() == ",":
                self.take(",")
                self.ws(newlines=True)
                items.append(self.unary())
            else:
                self.i = save
                break
        if len(items) == 1:
            return first
        return ArrayLiteral(Span(start, self.end()), items)

    def unary(self):
        start = self.i
        c = self.ch()
        if c == "!":
            self.take("!")
            self.ws(newlines=True)
            operand = self.unary()
            return Unary(Span(start, self.end()), "!", operand)
        if c == ",":
            self.take(",")
            self.ws(newlines=True)
            operand = self.unary()
            return ArrayLiteral(Span(start, self.end()), [operand])
        if c in "+" and self.ch(1) == "+" or c in DASHES and self.ch(1) in DASHES:
            op = self.t[self.i:self.i + 2]
            self.take(op)
            self.ws()
            operand = self.unary()
            return Unary(Span(start, self.end()), op, operand)
        if c in DASHES:
            w = self.word_at(self.i + 1)
            end = self.i + 1 + len(w)
            if w in UNARY_WORDS and (end >= self.n or not (self.t[end].isalnum() or self.t[end] == "_")):
                self.token(self.i, end, "operator")
                self.i = end
                self.ws(newlines=True)
                operand = self.unary()
                return Unary(Span(start, self.end()), w, operand)
            if self.ch(1).isdigit() or self.ch(1) == ".":
                number_end = self.number_end(self.i + 1)
                if number_end is not None:
                    self.token(self.i, number_end, "number")
                    self.i = number_end
                    return self.postfix(Number(Span(start, number_end), self.t[start:number_end]))
            self.take(c)
            self.ws(newlines=True)
            operand = self.unary()
            return Unary(Span(start, self.end()), "-", operand)
        if c == "+":
            self.take("+")
            self.ws(newlines=True)
            operand = self.unary()
            return Unary(Span(start, self.end()), "+", operand)
        if c == "[":
            type_ = self.type_name()
            save = self.i
            if self.t.startswith("::", self.i) or self.ch() == ".":
                return self.postfix(type_)
            if self.ch() == "[":
                operand = self.unary()
                return Cast(Span(start, self.end()), type_, operand)
            self.ws()
            if self.starts_expression() or self.ch() in "$([" + SINGLE_QUOTES + DOUBLE_QUOTES:
                operand = self.unary()
                return Cast(Span(start, self.end()), type_, operand)
            self.i = save
            return self.postfix(type_)
        return self.postfix(self.primary())

    def primary(self, argument_mode=False):
        start = self.i
        c = self.ch()
        if c == "$":
            if self.ch(1) == "(":
                return self.subexpression("$(")
            return self.variable()
        if c == "@":
            nxt = self.ch(1)
            if nxt == "(":
                return self.subexpression("@(")
            if nxt == "{":
                return self.hashtable()
            if nxt in SINGLE_QUOTES + DOUBLE_QUOTES:
                return self.here_string()
            if NAME_START.match(nxt or " "):
                m = VARIABLE_NAME.match(self.t, self.i + 1)
                self.token(start, m.end(), "variable")
                self.i = m.end()
                return Variable(Span(start, self.end()), m.group(0), splat=True)
            self.error("unexpected '@'")
        if c in SINGLE_QUOTES + DOUBLE_QUOTES:
            return self.string()
        if c == "(":
            self.take("(")
            self.ws(newlines=True)
            if self.ch() == ")":
                self.error("an empty parenthesis")
            node = self.with_comma(self.chain_or_statement)
            self.ws(newlines=True)
            self.take(")")
            return Paren(Span(start, self.end()), node)
        if c == "{":
            block = self.with_comma(self.script_block)
            return ScriptBlockExpression(Span(start, self.end()), block)
        if c == "[":
            return self.type_name()
        if c.isdigit() or c == ".":
            end = self.number_end(self.i)
            if end is not None:
                self.token(start, end, "number")
                self.i = end
                return Number(Span(start, end), self.t[start:end])
        if argument_mode:
            return self.bareword()
        self.error(f"unexpected {c!r} in an expression" if c != END else "an expression that ends too soon")

    def variable(self):
        start = self.i
        if self.ch(1) == "{":
            end = start + 2
            while end < self.n and self.t[end] != "}":
                end += 2 if self.t[end] == "`" else 1
            if end >= self.n:
                self.error("a ${ variable that does not close")
            self.token(start, end + 1, "variable")
            self.i = end + 1
            return Variable(Span(start, self.end()), without_using(self.t[start + 2:end]))
        if self.ch(1) in "$?^":
            self.token(start, start + 2, "variable")
            self.i = start + 2
            return Variable(Span(start, self.end()), self.ch(-1))
        m = VARIABLE_NAME.match(self.t, start + 1)
        if not m:
            self.error("a '$' without a variable name")
        self.token(start, m.end(), "variable")
        self.i = m.end()
        return Variable(Span(start, self.end()), without_using(m.group(0)))

    def subexpression(self, kind):
        start = self.i
        self.take(kind)
        statements = self.with_comma(lambda: self.statements(")"))
        self.take(")")
        return SubExpression(Span(start, self.end()), kind, statements)

    def hashtable(self):
        start = self.i
        self.take("@{")
        pairs = []
        while True:
            self.separators()
            if self.ch() == "}":
                break
            key_start = self.i
            if self.starts_expression() and self.ch() not in "[":
                key = self.unary()
            else:
                j = self.i
                while j < self.n and self.t[j] not in BLANK + "\n=;}":
                    j += 1
                if j == key_start:
                    self.error("a hashtable entry without a key")
                self.token(key_start, j, "bareword")
                key = Bareword(Span(key_start, j), self.t[key_start:j])
                self.i = j
            self.ws()
            self.take("=")
            self.ws(newlines=True)
            value = self.with_comma(self.chain_or_statement)
            pairs.append((key, value))
            self.ws()
            if self.ch() not in "\n;}":
                self.error("expected a new line, ';' or '}' after a hashtable entry")
        self.take("}")
        return Hashtable(Span(start, self.end()), pairs)

    def postfix(self, node, argument_mode=False):
        start = node.span.start
        while True:
            c = self.ch()
            if c == "." and self.ch(1) != "." and (argument_mode is False or self.member_name_ahead(self.i + 1)):
                if not self.member_name_ahead(self.i + 1):
                    return node
                self.take(".")
                node = self.member(node, start, static=False, null_conditional=False)
            elif c == "?" and self.ch(1) == "." and not argument_mode:
                self.take("?.")
                node = self.member(node, start, static=False, null_conditional=True)
            elif self.t.startswith("::", self.i):
                self.take("::")
                node = self.member(node, start, static=True, null_conditional=False)
            elif c == "[" and (not argument_mode or isinstance(node, (Variable, SubExpression, Paren, Member,
                                                                       InvokeMember, Index))):
                self.take("[")
                self.ws(newlines=True)
                index = self.with_comma(self.chain_or_statement)
                self.ws(newlines=True)
                self.take("]")
                node = Index(Span(start, self.end()), node, index)
            elif c == "?" and self.ch(1) == "[" and not argument_mode:
                self.take("?[")
                self.ws(newlines=True)
                index = self.chain_or_statement()
                self.ws(newlines=True)
                self.take("]")
                node = Index(Span(start, self.end()), node, index, null_conditional=True)
            elif (c == "+" and self.ch(1) == "+" or c in DASHES and self.ch(1) in DASHES) and not argument_mode and \
                    isinstance(node, (Variable, Member, Index)):
                op = self.t[self.i:self.i + 2]
                self.take(op)
                node = Unary(Span(start, self.end()), op, node, postfix=True)
            else:
                return node

    def member_name_ahead(self, at):
        if at >= self.n:
            return False
        c = self.t[at]
        return c.isalpha() or c == "_" or c in "$(" + SINGLE_QUOTES + DOUBLE_QUOTES or c.isdigit()

    def member(self, target, start, static, null_conditional):
        c = self.ch()
        if c == "$":
            name = self.variable()
        elif c == "(":
            name = self.primary()
        elif c in SINGLE_QUOTES + DOUBLE_QUOTES:
            name = self.string()
        else:
            m = re.compile(r"[\w]+", re.UNICODE).match(self.t, self.i)
            if not m:
                self.error("expected a member name")
            self.token(self.i, m.end(), "member")
            name = Bareword(Span(self.i, m.end()), m.group(0))
            self.i = m.end()
        if self.ch() == "(":
            arguments = self.method_arguments()
            return InvokeMember(Span(start, self.end()), target, name, arguments, static, null_conditional)
        return Member(Span(start, self.end()), target, name, static, null_conditional)

    def method_arguments(self):
        self.take("(")
        arguments = []
        while True:
            self.ws(newlines=True)
            if self.ch() == ")":
                break
            arguments.append(self.without_comma(self.method_argument))
            self.ws(newlines=True)
            if self.ch() == ",":
                self.take(",")
            elif self.ch() != ")":
                self.error("expected ',' or ')' in a method call")
        self.take(")")
        return arguments

    def method_argument(self):
        start = self.i
        left = self.binary(1)
        save = self.i
        self.ws()
        if self.ch() == "?" and self.ch(1) in BLANK + "\n":
            self.i = save
            self.ws()
            self.take("?")
            self.ws(newlines=True)
            then = self.method_argument()
            self.ws(newlines=True)
            self.take(":")
            self.ws(newlines=True)
            otherwise = self.method_argument()
            return Ternary(Span(start, self.end()), left, then, otherwise)
        self.i = save
        return left

    def string(self):
        c = self.ch()
        if c in SINGLE_QUOTES:
            return self.single_quoted()
        return self.double_quoted()

    def single_quoted(self):
        start, t = self.i, self.t
        j = start + 1
        out = []
        while True:
            if j >= self.n:
                self.error("a string that does not close", start)
            c = t[j]
            if c in SINGLE_QUOTES:
                if j + 1 < self.n and t[j + 1] in SINGLE_QUOTES:
                    out.append(c)
                    j += 2
                    continue
                j += 1
                break
            out.append(c)
            j += 1
        self.token(start, j, "string")
        self.i = j
        return String(Span(start, j), "single", "".join(out))

    def double_quoted(self):
        start = self.i
        self.i += 1
        value, parts = self.expandable_body(lambda: self.ch() in DOUBLE_QUOTES and self.ch(1) not in DOUBLE_QUOTES,
                                           doubled=True, start=start)
        self.i += 1
        self.token(start, self.i, "string")
        return String(Span(start, self.end()), "double", value, parts)

    def expandable_body(self, at_end, doubled, start):
        t = self.t
        out, parts = [], []
        while True:
            if self.i >= self.n:
                self.error("a string that does not close", start)
            c = t[self.i]
            if doubled and c in DOUBLE_QUOTES and self.ch(1) in DOUBLE_QUOTES:
                out.append(c)
                self.i += 2
                continue
            if at_end():
                return "".join(out), parts
            if c == "`":
                if self.i + 1 >= self.n:
                    self.error("a string that does not close", start)
                out.append({"0": "\0", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "n": "\n", "r": "\r",
                            "t": "\t", "v": "\v"}.get(t[self.i + 1], t[self.i + 1]))
                self.i += 2
                continue
            if c == "$" and self.ch(1) == "(":
                saved = dict(self.tokens)
                node = self.subexpression("$(")
                self.tokens = saved
                parts.append(node)
                out.append(t[node.span.start:node.span.end])
                continue
            if c == "$" and (self.ch(1) == "{" or self.ch(1) in "$?^" or NAME_START.match(self.ch(1) or " ")):
                saved = dict(self.tokens)
                node = self.variable()
                self.tokens = saved
                parts.append(node)
                out.append(t[node.span.start:node.span.end])
                continue
            out.append(c)
            self.i += 1

    def here_string(self):
        start, t = self.i, self.t
        quote = t[self.i + 1]
        j = self.i + 2
        while j < self.n and t[j] in BLANK:
            j += 1
        if j >= self.n or t[j] != "\n":
            self.error("a here-string must end its first line after the quote", start)
        body_start = j + 1
        k = body_start
        close = None
        while k <= self.n:
            if k < self.n and t[k] in (SINGLE_QUOTES if quote in SINGLE_QUOTES else DOUBLE_QUOTES) and \
                    k + 1 < self.n and t[k + 1] == "@" and (k == body_start or t[k - 1] == "\n"):
                close = k
                break
            nl = t.find("\n", k)
            if nl < 0:
                break
            k = nl + 1
        if close is None:
            self.error("a here-string that does not close", start)
        body_end = close - 1 if close > body_start else body_start
        if quote in SINGLE_QUOTES:
            self.token(start, close + 2, "string")
            self.i = close + 2
            return String(Span(start, self.end()), "here-single", t[body_start:body_end])
        self.i = body_start
        value, parts = self.expandable_body(lambda: self.i >= body_end, doubled=False, start=start)
        self.i = close + 2
        self.token(start, self.i, "string")
        return String(Span(start, self.end()), "here-double", value, parts)


def without_using(name):
    return name[len("using:"):] if name.lower().startswith("using:") else name


def parse(text, name="<powershell>"):
    source = text if isinstance(text, Source) else Source(text, name)
    try:
        return _Parser(source).script()
    except RecursionError:
        raise PowerShellError(source, 0, "a nesting too deep to read") from None


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        if isinstance(current, (list, tuple)):
            stack += reversed(current)
            continue
        if isinstance(current, dict):
            stack += reversed(list(current.values()))
            continue
        if not isinstance(current, (Node, ScriptBlock, Script)):
            continue
        if isinstance(current, Script):
            stack.append(current.block)
            continue
        yield current
        for name in current.__dataclass_fields__:
            if name == "span":
                continue
            value = getattr(current, name)
            if isinstance(value, (Node, list, tuple, dict)):
                stack.append(value)

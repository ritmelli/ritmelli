import re
import unicodedata
from dataclasses import dataclass

from .text import Comment, Source, Span, SyntaxProblem

LINE_BREAKS = "\n\r  "
PUNCTUATORS = sorted(["{", "}", "(", ")", "[", "]", ";", ",", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^", "!", "~",
                      "?", ":", "=", ".", "@", "...", "===", "!==", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++",
                      "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", ">>>", "<<=", ">>=", ">>>=", "**",
                      "**=", "&&=", "||=", "??=", "=>"], key=len, reverse=True)
NUMBER = re.compile(r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*n?|0[oO][0-7](?:_?[0-7])*n?|0[bB][01](?:_?[01])*n?|0\d+"
                    r"|(?:(?:0|[1-9](?:_?\d)*)(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?n?")
RESERVED = {"break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete", "do", "else",
            "enum", "export", "extends", "false", "finally", "for", "function", "if", "import", "in", "instanceof",
            "new", "null", "return", "super", "switch", "this", "throw", "true", "try", "typeof", "var", "void",
            "while", "with"}
ASSIGNMENT = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>=", "**=", "&&=", "||=", "??="}
BINARY = {"??": 1, "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "===": 6, "!==": 6, "<": 7, ">": 7,
          "<=": 7, ">=": 7, "instanceof": 7, "in": 7, "<<": 8, ">>": 8, ">>>": 8, "+": 9, "-": 9, "*": 10, "/": 10,
          "%": 10, "**": 11}
LOGICAL = {"||", "&&", "??"}
UNARY = {"!", "~", "+", "-", "typeof", "void", "delete"}
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}


class JavaScriptError(SyntaxProblem):
    pass


class ModuleDeclaration(JavaScriptError):
    pass


class Node:
    def __init__(self, type, start, end, **fields):
        self.type, self.start, self.end = type, start, end
        self.__dict__.update(fields)

    @property
    def span(self):
        return Span(self.start, self.end)

    def __repr__(self):
        return f"{self.type}({self.start}, {self.end})"


@dataclass
class Token:
    kind: str
    value: str
    start: int
    end: int
    nl: bool


def blank(c):
    return c in " \t\v\f ﻿" or unicodedata.category(c) == "Zs"


def name_start(c):
    return c == "$" or c.isidentifier()


def name_part(c):
    return c in "$‌‍" or ("a" + c).isidentifier()


def cooked(raw):
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        d = raw[i + 1]
        i += 2
        if d in ESCAPES:
            out.append(ESCAPES[d])
        elif d == "x":
            out.append(chr(int(raw[i:i + 2], 16)))
            i += 2
        elif d == "u" and raw[i] == "{":
            end = raw.index("}", i)
            out.append(chr(int(raw[i + 1:end], 16)))
            i = end + 1
        elif d == "u":
            out.append(chr(int(raw[i:i + 4], 16)))
            i += 4
        elif d in "01234567":
            j = i
            while j < len(raw) and j < i + (2 if d in "0123" else 1) and raw[j] in "01234567":
                j += 1
            out.append(chr(int(d + raw[i:j], 8)))
            i = j
        elif d == "\r":
            i += raw[i:i + 1] == "\n"
        elif d in LINE_BREAKS:
            pass
        else:
            out.append(d)
    return "".join(out)


class Lexer:
    def __init__(self, source, comments):
        self.source, self.t, self.n = source, source.text, len(source.text)
        self.comments = comments

    def error(self, message, at):
        raise JavaScriptError(self.source, at, message)

    def after_blanks(self, i):
        nl = False
        while i < self.n:
            c = self.t[i]
            if c in LINE_BREAKS:
                nl = True
                i += 1
            elif blank(c):
                i += 1
            elif self.t.startswith("//", i):
                end = i
                while end < self.n and self.t[end] not in LINE_BREAKS:
                    end += 1
                self.comments[i] = Comment(Span(i, end), self.t[i + 2:end])
                i = end
            elif self.t.startswith("/*", i):
                end = self.t.find("*/", i + 2)
                if end < 0:
                    self.error("a block comment that is never closed", i)
                body = self.t[i + 2:end]
                nl = nl or any(b in body for b in LINE_BREAKS)
                self.comments[i] = Comment(Span(i, end + 2), body, block=True)
                i = end + 2
            elif i == 0 and self.t.startswith("#!"):
                while i < self.n and self.t[i] not in LINE_BREAKS:
                    i += 1
            else:
                break
        return i, nl

    def scan(self, pos):
        i, nl = self.after_blanks(pos)
        if i >= self.n:
            return Token("eof", "", self.n, self.n, nl)
        c = self.t[i]
        if name_start(c) or c == "\\":
            return self.name(i, nl, "name")
        if c == "#" and i + 1 < self.n and name_start(self.t[i + 1]):
            return self.name(i + 1, nl, "private", i)
        if c.isdigit() or c == "." and i + 1 < self.n and self.t[i + 1].isdigit():
            m = NUMBER.match(self.t, i)
            end = m.end()
            if end < self.n and (name_part(self.t[end]) or self.t[end] == "\\"):
                self.error("an identifier right after a number", end)
            return Token("num", m.group(0), i, end, nl)
        if c in "'\"":
            return self.string(i, nl)
        if c == "`":
            return self.template(i, nl)
        if self.t.startswith("?.", i) and not (i + 2 < self.n and self.t[i + 2].isdigit()):
            return Token("punct", "?.", i, i + 2, nl)
        for p in PUNCTUATORS:
            if p != "?." and self.t.startswith(p, i):
                return Token("punct", p, i, i + len(p), nl)
        self.error(f"unexpected character {c!r}", i)

    def name(self, i, nl, kind, start=None):
        j = i
        while j < self.n and (name_part(self.t[j]) or self.t[j] == "\\"):
            if self.t[j] == "\\":
                self.error("an escape inside an identifier", j)
            j += 1
        return Token(kind, self.t[i:j], i if start is None else start, j, nl)

    def string(self, i, nl):
        quote, j = self.t[i], i + 1
        while j < self.n and self.t[j] != quote:
            if self.t[j] == "\\":
                j += 2
                if self.t[j - 1:j + 1] == "\r\n":
                    j += 1
            elif self.t[j] in "\n\r":
                self.error("a string that runs into the end of the line", j)
            else:
                j += 1
        if j >= self.n:
            self.error("a string that is never closed", i)
        return Token("string", self.t[i + 1:j], i, j + 1, nl)

    def template(self, i, nl):
        j = i + 1
        while j < self.n:
            if self.t[j] == "\\":
                j += 2
            elif self.t[j] == "`":
                return Token("template", self.t[i + 1:j], i, j + 1, nl)
            elif self.t.startswith("${", j):
                return Token("template-head", self.t[i + 1:j], i, j + 2, nl)
            else:
                j += 1
        self.error("a template that is never closed", i)

    def regex(self, token):
        i, j, in_class = token.start, token.start + 1, False
        while True:
            if j >= self.n or self.t[j] in LINE_BREAKS:
                self.error("a regular expression that is never closed", i)
            c = self.t[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            j += 1
        k = j + 1
        while k < self.n and name_part(self.t[k]):
            k += 1
        return Token("regex", self.t[i:k], i, k, token.nl)


class _Parser:
    def __init__(self, text, name, module=False):
        self.source = Source(text, name)
        self.t = text
        self.module = module
        self.comments = {}
        self.lexer = Lexer(self.source, self.comments)
        self.prev_end = 0
        self.tok = self.lexer.scan(0)
        self.function = {"async": module, "generator": False, "inside": False}
        self.labels = []

    def error(self, message, at=None):
        raise JavaScriptError(self.source, self.tok.start if at is None else at, message)

    def node(self, type, start, **fields):
        return Node(type, start, self.prev_end, **fields)

    def next(self):
        self.prev_end = self.tok.end
        self.tok = self.lexer.scan(self.tok.end)

    def peek(self):
        return self.lexer.scan(self.tok.end)

    def at(self, value):
        return self.tok.kind in ("punct", "name") and self.tok.value == value

    def eat(self, value):
        if self.at(value):
            self.next()
            return True
        return False

    def expect(self, value):
        if not self.eat(value):
            self.error(f"expected {value!r}")

    def semicolon(self):
        if not self.eat(";") and not (self.at("}") or self.tok.kind == "eof" or self.tok.nl):
            self.error("expected ';'")

    def state(self):
        return self.tok, self.prev_end, dict(self.function), list(self.labels)

    def restore(self, state):
        self.tok, self.prev_end, self.function, self.labels = state[0], state[1], dict(state[2]), list(state[3])

    def identifier(self, allow_reserved=False):
        if self.tok.kind != "name" or (not allow_reserved and self.tok.value in RESERVED):
            self.error("expected a name")
        start, name = self.tok.start, self.tok.value
        self.next()
        return self.node("Identifier", start, name=name)

    def program(self):
        body = self.statements(top=True)
        if self.tok.kind != "eof":
            self.error("unexpected token")
        return Node("Program", 0, len(self.t), body=body, sourceType="module" if self.module else "script")

    def statements(self, top=False):
        out = []
        while not (self.tok.kind == "eof" or not top and self.at("}")):
            out.append(self.statement(top))
        return out

    def statement(self, top=False):
        start, tok = self.tok.start, self.tok
        if tok.kind == "punct":
            if tok.value == "{":
                return self.block()
            if tok.value == ";":
                self.next()
                return self.node("EmptyStatement", start)
        if tok.kind == "name":
            word = tok.value
            if word == "var" or word == "const" or word == "let" and self.let_declaration():
                declaration = self.variables(word)
                self.semicolon()
                declaration.end = self.prev_end
                return declaration
            if word == "function":
                return self.function_node("FunctionDeclaration", start)
            if word == "async" and self.async_function_ahead():
                self.next()
                return self.function_node("FunctionDeclaration", start, is_async=True)
            if word == "class":
                return self.class_node("ClassDeclaration")
            handler = getattr(self, f"statement_{word}", None)
            if handler is not None and word in RESERVED | {"debugger"}:
                return handler(start)
            if word not in RESERVED and self.peek_is(":"):
                label = self.identifier()
                self.expect(":")
                self.labels.append(label.name)
                body = self.statement()
                self.labels.pop()
                return self.node("LabeledStatement", start, label=label, body=body)
            if word in ("import", "export") and not self.peek_is("(") and not self.peek_is("."):
                if not self.module:
                    raise ModuleDeclaration(self.source, start, f"'{word}' declarations belong to modules")
                if not top:
                    self.error(f"an '{word}' declaration belongs to the top of the module")
                return self.module_import(start) if word == "import" else self.module_export(start)
        expression = self.expression()
        self.semicolon()
        return self.node("ExpressionStatement", start, expression=expression)

    def module_source(self):
        if self.tok.kind != "string":
            self.error("expected the name of a module")
        return self.literal()

    def export_name(self):
        return self.literal() if self.tok.kind == "string" else self.identifier(allow_reserved=True)

    def module_import(self, start):
        self.next()
        specifiers = []
        if self.tok.kind == "string":
            source = self.module_source()
        else:
            if self.tok.kind == "name" and not self.at("{"):
                local = self.identifier()
                specifiers.append(self.node("ImportDefaultSpecifier", local.start, local=local))
                if not self.eat(","):
                    self.expect("from")
                    source = self.module_source()
                    self.semicolon()
                    return self.node("ImportDeclaration", start, specifiers=specifiers, source=source)
            if self.at("*"):
                s_start = self.tok.start
                self.next()
                self.expect("as")
                specifiers.append(self.node("ImportNamespaceSpecifier", s_start, local=self.identifier()))
            else:
                self.expect("{")
                while not self.eat("}"):
                    s_start = self.tok.start
                    imported = self.export_name()
                    if self.eat("as"):
                        local = self.identifier()
                    elif imported.type == "Identifier" and imported.name not in RESERVED:
                        local = imported
                    else:
                        self.error("an import of this name needs 'as'")
                    specifiers.append(self.node("ImportSpecifier", s_start, imported=imported, local=local))
                    if not self.at("}"):
                        self.expect(",")
            self.expect("from")
            source = self.module_source()
        self.semicolon()
        return self.node("ImportDeclaration", start, specifiers=specifiers, source=source)

    def module_export(self, start):
        self.next()
        if self.eat("*"):
            exported = self.export_name() if self.eat("as") else None
            self.expect("from")
            source = self.module_source()
            self.semicolon()
            return self.node("ExportAllDeclaration", start, exported=exported, source=source)
        if self.eat("default"):
            d_start = self.tok.start
            if self.at("function"):
                declaration = self.function_node("FunctionDeclaration", d_start, named=False)
            elif self.at("async") and self.async_function_ahead():
                self.next()
                declaration = self.function_node("FunctionDeclaration", d_start, is_async=True, named=False)
            elif self.at("class"):
                declaration = self.class_node("ClassDeclaration", named=False)
            else:
                declaration = self.assign()
                self.semicolon()
            return self.node("ExportDefaultDeclaration", start, declaration=declaration)
        if self.eat("{"):
            specifiers = []
            while not self.eat("}"):
                s_start = self.tok.start
                local = self.export_name()
                exported = self.export_name() if self.eat("as") else local
                specifiers.append(self.node("ExportSpecifier", s_start, local=local, exported=exported))
                if not self.at("}"):
                    self.expect(",")
            source = self.module_source() if self.eat("from") else None
            self.semicolon()
            return self.node("ExportNamedDeclaration", start, declaration=None, specifiers=specifiers, source=source)
        declaration = self.statement()
        if declaration.type not in ("VariableDeclaration", "FunctionDeclaration", "ClassDeclaration"):
            self.error("an export needs a declaration", declaration.start)
        return self.node("ExportNamedDeclaration", start, declaration=declaration, specifiers=[], source=None)

    def peek_is(self, value):
        nxt = self.peek()
        return nxt.kind in ("punct", "name") and nxt.value == value

    def let_declaration(self):
        nxt = self.peek()
        return nxt.kind == "name" and nxt.value not in ("in", "instanceof") or \
            nxt.kind == "punct" and nxt.value in ("[", "{")

    def async_function_ahead(self):
        nxt = self.peek()
        return nxt.kind == "name" and nxt.value == "function" and not nxt.nl

    def block(self):
        start = self.tok.start
        self.expect("{")
        body = self.statements()
        self.expect("}")
        return self.node("BlockStatement", start, body=body)

    def variables(self, kind, no_in=False):
        start = self.tok.start
        self.next()
        declarations = []
        while True:
            d_start = self.tok.start
            target = self.binding_target()
            init = None
            if self.eat("="):
                init = self.assign(no_in)
            declarations.append(self.node("VariableDeclarator", d_start, id=target, init=init))
            if not self.eat(","):
                break
        return self.node("VariableDeclaration", start, declarations=declarations, kind=kind)

    def binding_target(self):
        if self.at("["):
            return self.array_pattern()
        if self.at("{"):
            return self.object_pattern()
        return self.identifier()

    def binding_element(self):
        start = self.tok.start
        target = self.binding_target()
        if self.eat("="):
            return self.node("AssignmentPattern", start, left=target, right=self.assign())
        return target

    def array_pattern(self):
        start = self.tok.start
        self.expect("[")
        elements = []
        while not self.at("]"):
            if self.at(","):
                self.next()
                elements.append(None)
                continue
            if self.at("..."):
                r_start = self.tok.start
                self.next()
                elements.append(self.node("RestElement", r_start, argument=self.binding_target()))
            else:
                elements.append(self.binding_element())
            if not self.at("]"):
                self.expect(",")
        self.expect("]")
        return self.node("ArrayPattern", start, elements=elements)

    def object_pattern(self):
        start = self.tok.start
        self.expect("{")
        properties = []
        while not self.at("}"):
            p_start = self.tok.start
            if self.at("..."):
                self.next()
                properties.append(self.node("RestElement", p_start, argument=self.identifier()))
            else:
                key, computed = self.property_key()
                if self.eat(":"):
                    value = self.binding_element()
                    properties.append(self.node("Property", p_start, key=key, value=value, kind="init", method=False,
                                                shorthand=False, computed=computed))
                else:
                    if computed or key.type != "Identifier":
                        self.error("a shorthand property needs a name")
                    value = key
                    if self.eat("="):
                        value = self.node("AssignmentPattern", p_start, left=key, right=self.assign())
                    properties.append(self.node("Property", p_start, key=key, value=value, kind="init", method=False,
                                                shorthand=True, computed=False))
            if not self.at("}"):
                self.expect(",")
        self.expect("}")
        return self.node("ObjectPattern", start, properties=properties)

    def statement_if(self, start):
        self.next()
        test = self.parenthesized()
        consequent = self.statement()
        alternate = self.statement() if self.eat("else") else None
        return self.node("IfStatement", start, test=test, consequent=consequent, alternate=alternate)

    def parenthesized(self):
        self.expect("(")
        expression = self.expression()
        self.expect(")")
        return expression

    def statement_while(self, start):
        self.next()
        test = self.parenthesized()
        return self.node("WhileStatement", start, test=test, body=self.loop_body())

    def loop_body(self):
        self.labels.append(None)
        body = self.statement()
        self.labels.pop()
        return body

    def statement_do(self, start):
        self.next()
        body = self.loop_body()
        self.expect("while")
        test = self.parenthesized()
        self.eat(";")
        return self.node("DoWhileStatement", start, body=body, test=test)

    def statement_for(self, start):
        self.next()
        is_await = False
        if self.at("await") and self.function["async"]:
            self.next()
            is_await = True
        self.expect("(")
        init = None
        if self.at(";"):
            pass
        elif self.at("var") or self.at("const") or self.at("let") and self.let_declaration():
            init = self.variables(self.tok.value, no_in=True)
        else:
            init_start = self.tok.start
            init = self.expression(no_in=True)
            if self.at("of") or self.at("in"):
                init = self.to_pattern(init, init_start)
        if init is not None and (self.at("of") or self.at("in")):
            kind = "ForOfStatement" if self.at("of") else "ForInStatement"
            self.next()
            right = self.assign() if kind == "ForOfStatement" else self.expression()
            self.expect(")")
            fields = {"await": is_await} if kind == "ForOfStatement" else {}
            return self.node(kind, start, left=init, right=right, body=self.loop_body(), **fields)
        self.expect(";")
        test = None if self.at(";") else self.expression()
        self.expect(";")
        update = None if self.at(")") else self.expression()
        self.expect(")")
        return self.node("ForStatement", start, init=init, test=test, update=update, body=self.loop_body())

    def statement_return(self, start):
        if not self.function["inside"]:
            self.error("return outside a function")
        self.next()
        argument = None
        if not (self.at(";") or self.at("}") or self.tok.kind == "eof" or self.tok.nl):
            argument = self.expression()
        self.semicolon()
        return self.node("ReturnStatement", start, argument=argument)

    def jump(self, start, kind):
        self.next()
        label = None
        if self.tok.kind == "name" and not self.tok.nl and self.tok.value not in RESERVED:
            label = self.identifier()
            if label.name not in self.labels:
                self.error(f"no label {label.name!r} around this {kind.lower()}", label.start)
        elif not self.labels:
            self.error(f"a {kind.lower()} outside a loop or a switch", start)
        self.semicolon()
        return self.node(f"{kind}Statement", start, label=label)

    def statement_break(self, start):
        return self.jump(start, "Break")

    def statement_continue(self, start):
        return self.jump(start, "Continue")

    def statement_throw(self, start):
        self.next()
        if self.tok.nl:
            self.error("a line break after throw")
        argument = self.expression()
        self.semicolon()
        return self.node("ThrowStatement", start, argument=argument)

    def statement_try(self, start):
        self.next()
        block = self.block()
        handler = finalizer = None
        if self.at("catch"):
            c_start = self.tok.start
            self.next()
            param = None
            if self.eat("("):
                param = self.binding_target()
                self.expect(")")
            handler = self.node("CatchClause", c_start, param=param, body=self.block())
        if self.eat("finally"):
            finalizer = self.block()
        if handler is None and finalizer is None:
            self.error("a try without catch or finally")
        return self.node("TryStatement", start, block=block, handler=handler, finalizer=finalizer)

    def statement_switch(self, start):
        self.next()
        discriminant = self.parenthesized()
        self.expect("{")
        cases = []
        self.labels.append(None)
        while not self.eat("}"):
            c_start = self.tok.start
            if self.eat("default"):
                test = None
            else:
                self.expect("case")
                test = self.expression()
            self.expect(":")
            consequent = []
            while not (self.at("case") or self.at("default") or self.at("}")):
                consequent.append(self.statement())
            cases.append(self.node("SwitchCase", c_start, test=test, consequent=consequent))
        self.labels.pop()
        return self.node("SwitchStatement", start, discriminant=discriminant, cases=cases)

    def statement_with(self, start):
        self.next()
        obj = self.parenthesized()
        return self.node("WithStatement", start, object=obj, body=self.statement())

    def statement_debugger(self, start):
        self.next()
        self.semicolon()
        return self.node("DebuggerStatement", start)

    def function_node(self, type, start, is_async=False, method=None, named=True):
        if method is None:
            self.expect("function")
        generator = method is None and self.eat("*")
        name = None
        if method is None and self.tok.kind == "name" and not self.at("("):
            name = self.identifier()
        if type == "FunctionDeclaration" and name is None and named:
            self.error("a function declaration needs a name")
        outer, labels = self.function, self.labels
        self.function = {"async": is_async, "generator": generator or method == "generator", "inside": True}
        self.labels = []
        params_start = self.tok.start
        params = self.params()
        body = self.block()
        self.function, self.labels = outer, labels
        return self.node(type, start if method is None else params_start, id=name, params=params, body=body,
                         generator=generator or method == "generator", expression=False, **{"async": is_async})

    def params(self):
        self.expect("(")
        out = []
        while not self.at(")"):
            if self.at("..."):
                r_start = self.tok.start
                self.next()
                out.append(self.node("RestElement", r_start, argument=self.binding_target()))
                break
            out.append(self.binding_element())
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        return out

    def class_node(self, type, named=True):
        start = self.tok.start
        self.expect("class")
        name = None
        if self.tok.kind == "name" and self.tok.value != "extends" and not self.at("{"):
            name = self.identifier()
        if type == "ClassDeclaration" and name is None and named:
            self.error("a class declaration needs a name")
        superclass = self.lhs() if self.eat("extends") else None
        b_start = self.tok.start
        self.expect("{")
        members = []
        while not self.eat("}"):
            if self.eat(";"):
                continue
            members.append(self.class_member())
        body = self.node("ClassBody", b_start, body=members)
        return self.node(type, start, id=name, superClass=superclass, body=body)

    def class_member(self):
        start = self.tok.start
        static = False
        if self.at("static") and not self.peek_is("(") and not self.peek_is("="):
            self.next()
            static = True
            if self.at("{"):
                b = self.block()
                return Node("StaticBlock", start, b.end, body=b.body)
        kind, is_async, generator = "method", False, False
        if self.at("async") and not self.peek_is("(") and not self.peek_is("=") and not self.peek().nl:
            self.next()
            is_async = True
        if self.eat("*"):
            generator = True
        if (self.at("get") or self.at("set")) and not self.peek_is("(") and not self.peek_is("=") and \
                not self.peek_is(";") and not self.peek_is("}"):
            kind = self.tok.value
            self.next()
        key, computed = self.property_key(private=True)
        if self.at("("):
            if not static and not computed and kind == "method" and self.key_name(key) == "constructor":
                kind = "constructor"
            value = self.function_node("FunctionExpression", start, is_async=is_async,
                                       method="generator" if generator else "method")
            return self.node("MethodDefinition", start, key=key, value=value, kind=kind, static=static,
                             computed=computed)
        value = None
        if self.eat("="):
            outer = self.function
            self.function = {"async": False, "generator": False, "inside": True}
            value = self.assign()
            self.function = outer
        self.semicolon()
        return self.node("PropertyDefinition", start, key=key, value=value, computed=computed, static=static)

    def key_name(self, key):
        return key.name if key.type == "Identifier" else key.value if key.type == "Literal" else None

    def property_key(self, private=False):
        tok = self.tok
        if tok.kind == "punct" and tok.value == "[":
            self.next()
            key = self.assign()
            self.expect("]")
            return key, True
        if tok.kind == "private" and private:
            self.next()
            return self.node("PrivateIdentifier", tok.start, name=tok.value), False
        if tok.kind == "name":
            self.next()
            return self.node("Identifier", tok.start, name=tok.value), False
        if tok.kind in ("string", "num"):
            return self.literal(), False
        self.error("expected a property name")

    def expression(self, no_in=False):
        start = self.tok.start
        first = self.assign(no_in)
        if not self.at(","):
            return first
        items = [first]
        while self.eat(","):
            items.append(self.assign(no_in))
        return self.node("SequenceExpression", start, expressions=items)

    def assign(self, no_in=False):
        start = self.tok.start
        if self.at("yield") and self.function["generator"]:
            return self.yield_expression(no_in)
        arrow = self.arrow(no_in)
        if arrow is not None:
            return arrow
        left = self.conditional(no_in)
        if self.tok.kind == "punct" and self.tok.value in ASSIGNMENT:
            operator = self.tok.value
            if operator == "=":
                left = self.to_pattern(left, start)
            elif left.type not in ("Identifier", "MemberExpression"):
                self.error("this can't be assigned to", start)
            self.next()
            right = self.assign(no_in)
            return self.node("AssignmentExpression", start, operator=operator, left=left, right=right)
        return left

    def yield_expression(self, no_in):
        start = self.tok.start
        self.next()
        delegate, argument = False, None
        if not self.tok.nl:
            delegate = self.eat("*")
            if delegate or not (self.at(")") or self.at("]") or self.at("}") or self.at(",") or self.at(";")
                                or self.at(":") or self.tok.kind == "eof" or self.at("in") and no_in):
                argument = self.assign(no_in)
        return self.node("YieldExpression", start, delegate=delegate, argument=argument)

    def arrow(self, no_in):
        start, is_async = self.tok.start, False
        saved = self.state()
        if self.at("async") and not self.peek().nl:
            nxt = self.peek()
            if nxt.kind == "name" and nxt.value not in RESERVED or nxt.kind == "punct" and nxt.value == "(":
                self.next()
                is_async = True
        if self.tok.kind == "name" and self.tok.value not in RESERVED and self.peek_is("=>") \
                and not self.peek().nl:
            params = [self.identifier()]
        elif self.at("("):
            try:
                params = self.params()
            except JavaScriptError:
                self.restore(saved)
                return None
            if not self.at("=>") or self.tok.nl:
                self.restore(saved)
                return None
        else:
            self.restore(saved)
            return None
        self.expect("=>")
        outer, labels = self.function, self.labels
        self.function = {"async": is_async, "generator": False, "inside": True}
        self.labels = []
        if self.at("{"):
            body, expression = self.block(), False
        else:
            body, expression = self.assign(no_in), True
        self.function, self.labels = outer, labels
        return self.node("ArrowFunctionExpression", start, id=None, params=params, body=body, expression=expression,
                         generator=False, **{"async": is_async})

    def conditional(self, no_in):
        start = self.tok.start
        test = self.binary(start, self.unary(), 0, no_in)
        if not self.eat("?"):
            return test
        consequent = self.assign()
        self.expect(":")
        alternate = self.assign(no_in)
        return self.node("ConditionalExpression", start, test=test, consequent=consequent, alternate=alternate)

    def operator(self, no_in):
        tok = self.tok
        if tok.kind == "punct" and tok.value in BINARY or tok.kind == "name" and tok.value in ("instanceof", "in"):
            if tok.value == "in" and no_in:
                return None
            return tok.value
        return None

    def binary(self, start, left, min_prec, no_in):
        while True:
            op = self.operator(no_in)
            if op is None or BINARY[op] <= min_prec and not (op == "**" and BINARY[op] == min_prec):
                return left
            prec = BINARY[op]
            self.next()
            r_start = self.tok.start
            right = self.binary(r_start, self.unary(), prec - 1 if op == "**" else prec, no_in)
            kind = "LogicalExpression" if op in LOGICAL else "BinaryExpression"
            left = self.node(kind, start, operator=op, left=left, right=right)

    def unary(self):
        start, tok = self.tok.start, self.tok
        if tok.kind in ("punct", "name") and tok.value in UNARY and not (tok.kind == "name" and self.peek_is("=>")):
            self.next()
            argument = self.unary()
            return self.node("UnaryExpression", start, operator=tok.value, prefix=True, argument=argument)
        if tok.kind == "punct" and tok.value in ("++", "--"):
            self.next()
            argument = self.unary()
            return self.node("UpdateExpression", start, operator=tok.value, prefix=True, argument=argument)
        if tok.kind == "name" and tok.value == "await" and self.function["async"]:
            self.next()
            return self.node("AwaitExpression", start, argument=self.unary())
        expression = self.lhs(call=True)
        if self.tok.kind == "punct" and self.tok.value in ("++", "--") and not self.tok.nl:
            operator = self.tok.value
            self.next()
            return self.node("UpdateExpression", start, operator=operator, prefix=False, argument=expression)
        return expression

    def lhs(self, call=True):
        start = self.tok.start
        if self.at("new"):
            expression = self.new_expression()
        else:
            expression = self.primary()
        return self.chain(start, expression, call)

    def new_expression(self):
        start = self.tok.start
        self.next()
        if self.eat("."):
            prop = self.identifier(allow_reserved=True)
            return self.node("MetaProperty", start, meta=Node("Identifier", start, start + 3, name="new"),
                             property=prop)
        c_start = self.tok.start
        callee = self.chain(c_start, self.new_expression() if self.at("new") else self.primary(), call=False)
        arguments = self.arguments() if self.at("(") else []
        return self.node("NewExpression", start, callee=callee, arguments=arguments)

    def chain(self, start, expression, call):
        optional_seen = False
        while True:
            if self.at("."):
                self.next()
                expression = self.member_name(start, expression, optional=False)
            elif self.at("?.") and call:
                optional_seen = True
                self.next()
                if self.at("("):
                    expression = self.node("CallExpression", start, callee=expression, arguments=self.arguments(),
                                           optional=True)
                elif self.at("["):
                    self.next()
                    prop = self.expression()
                    self.expect("]")
                    expression = self.node("MemberExpression", start, object=expression, property=prop,
                                           computed=True, optional=True)
                else:
                    expression = self.member_name(start, expression, optional=True)
            elif self.at("["):
                self.next()
                prop = self.expression()
                self.expect("]")
                expression = self.node("MemberExpression", start, object=expression, property=prop, computed=True,
                                       optional=False)
            elif self.at("(") and call:
                expression = self.node("CallExpression", start, callee=expression, arguments=self.arguments(),
                                       optional=False)
            elif self.tok.kind in ("template", "template-head"):
                if optional_seen:
                    self.error("a tagged template in an optional chain")
                quasi = self.template()
                expression = self.node("TaggedTemplateExpression", start, tag=expression, quasi=quasi)
            else:
                break
        if optional_seen:
            return Node("ChainExpression", start, expression.end, expression=expression)
        return expression

    def member_name(self, start, expression, optional):
        if self.tok.kind == "private":
            tok = self.tok
            self.next()
            prop = self.node("PrivateIdentifier", tok.start, name=tok.value)
        else:
            prop = self.identifier(allow_reserved=True)
        return self.node("MemberExpression", start, object=expression, property=prop, computed=False,
                         optional=optional)

    def arguments(self):
        self.expect("(")
        out = []
        while not self.at(")"):
            out.append(self.spread_or_assign())
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        return out

    def spread_or_assign(self):
        if self.at("..."):
            start = self.tok.start
            self.next()
            return self.node("SpreadElement", start, argument=self.assign())
        return self.assign()

    def literal(self):
        tok = self.tok
        self.next()
        if tok.kind == "string":
            try:
                value = cooked(tok.value)
            except (ValueError, IndexError):
                self.error("a string with an escape that is no escape", tok.start)
            return self.node("Literal", tok.start, value=value, raw=self.t[tok.start:tok.end])
        raw = tok.value
        return self.node("Literal", tok.start, value=raw, raw=raw, bigint=raw[:-1].replace("_", "")
                         if raw.endswith("n") else None)

    def primary(self):
        tok, start = self.tok, self.tok.start
        if tok.kind == "punct" and tok.value in ("/", "/="):
            self.tok = self.lexer.regex(tok)
            tok = self.tok
        kind, value = tok.kind, tok.value
        if kind in ("string", "num"):
            return self.literal()
        if kind == "regex":
            self.next()
            end = value.rindex("/")
            return self.node("Literal", start, value={}, raw=value,
                             regex={"pattern": value[1:end], "flags": value[end + 1:]})
        if kind in ("template", "template-head"):
            return self.template()
        if kind == "punct":
            if value == "(":
                self.next()
                expression = self.expression()
                self.expect(")")
                return expression
            if value == "[":
                return self.array_literal()
            if value == "{":
                return self.object_literal()
            self.error(f"unexpected {value!r}")
        if kind == "name":
            if value == "function":
                return self.function_node("FunctionExpression", start)
            if value == "async" and self.async_function_ahead():
                self.next()
                return self.function_node("FunctionExpression", start, is_async=True)
            if value == "class":
                return self.class_node("ClassExpression")
            if value == "this":
                self.next()
                return self.node("ThisExpression", start)
            if value == "super":
                self.next()
                return self.node("Super", start)
            if value in ("null", "true", "false"):
                self.next()
                return self.node("Literal", start, value={"null": None, "true": True, "false": False}[value],
                                 raw=value)
            if value == "import":
                self.next()
                if self.eat("."):
                    prop = self.identifier(allow_reserved=True)
                    return self.node("MetaProperty", start, meta=Node("Identifier", start, start + 6, name="import"),
                                     property=prop)
                self.expect("(")
                source = self.assign()
                self.expect(")")
                return self.node("ImportExpression", start, source=source)
            return self.identifier()
        self.error("unexpected end of the script" if kind == "eof" else "unexpected token")

    def template(self):
        start = self.tok.start
        quasis, expressions = [], []
        while True:
            tok = self.tok
            head = tok.kind == "template-head"
            q_start = tok.start + 1
            q_end = tok.end - (2 if head else 1)
            quasis.append(Node("TemplateElement", q_start, q_end, value={"raw": self.t[q_start:q_end]}, tail=not head))
            if not head:
                self.next()
                break
            self.next()
            expressions.append(self.expression())
            if not self.at("}"):
                self.error("expected '}' to close the template field")
            self.tok = self.lexer.template(self.tok.start, self.tok.nl)
        return self.node("TemplateLiteral", start, quasis=quasis, expressions=expressions)

    def array_literal(self):
        start = self.tok.start
        self.expect("[")
        elements = []
        while not self.at("]"):
            if self.at(","):
                self.next()
                elements.append(None)
                continue
            elements.append(self.spread_or_assign())
            if not self.at("]"):
                self.expect(",")
        self.expect("]")
        return self.node("ArrayExpression", start, elements=elements)

    def object_literal(self):
        start = self.tok.start
        self.expect("{")
        properties = []
        while not self.at("}"):
            properties.append(self.object_member())
            if not self.at("}"):
                self.expect(",")
        self.expect("}")
        return self.node("ObjectExpression", start, properties=properties)

    def object_member(self):
        start = self.tok.start
        if self.at("..."):
            self.next()
            return self.node("SpreadElement", start, argument=self.assign())
        is_async = generator = False
        kind = "init"
        nxt = self.peek()
        modifier = nxt.kind not in ("punct",) or nxt.value in ("[", "*") or nxt.kind == "punct" and False
        if self.at("async") and modifier and not nxt.nl and not (nxt.kind == "punct" and nxt.value in
                                                                  ("(", ":", ",", "}", "=")):
            self.next()
            is_async = True
        if self.eat("*"):
            generator = True
        nxt = self.peek()
        if (self.at("get") or self.at("set")) and not (nxt.kind == "punct" and nxt.value in ("(", ":", ",", "}", "=")):
            kind = self.tok.value
            self.next()
        key, computed = self.property_key()
        if self.at("("):
            value = self.function_node("FunctionExpression", start, is_async=is_async,
                                       method="generator" if generator else "method")
            return self.node("Property", start, key=key, value=value, kind=kind, method=kind == "init",
                             shorthand=False, computed=computed)
        if is_async or generator or kind != "init":
            self.error("expected '(' for the method")
        if self.eat(":"):
            value = self.assign()
            return self.node("Property", start, key=key, value=value, kind="init", method=False, shorthand=False,
                             computed=computed)
        if computed or key.type != "Identifier":
            self.error("a shorthand property needs a name")
        value = key
        if self.at("="):
            self.next()
            value = self.node("AssignmentPattern", start, left=key, right=self.assign())
        return self.node("Property", start, key=key, value=value, kind="init", method=False, shorthand=True,
                         computed=False)

    def to_pattern(self, node, start):
        kind = node.type
        if kind in ("Identifier", "MemberExpression", "ObjectPattern", "ArrayPattern", "AssignmentPattern"):
            return node
        if kind == "ArrayExpression":
            node.type = "ArrayPattern"
            for i, e in enumerate(node.elements):
                if e is None:
                    continue
                if e.type == "SpreadElement":
                    node.elements[i] = Node("RestElement", e.start, e.end, argument=self.to_pattern(e.argument,
                                                                                                    e.start))
                else:
                    node.elements[i] = self.to_pattern(e, e.start)
            return node
        if kind == "ObjectExpression":
            node.type = "ObjectPattern"
            for i, p in enumerate(node.properties):
                if p.type == "SpreadElement":
                    node.properties[i] = Node("RestElement", p.start, p.end,
                                              argument=self.to_pattern(p.argument, p.start))
                elif p.kind != "init" or p.method:
                    self.error("a method can't be assigned to", p.start)
                else:
                    p.value = self.to_pattern(p.value, p.value.start)
            return node
        if kind == "AssignmentExpression" and node.operator == "=":
            return Node("AssignmentPattern", node.start, node.end, left=self.to_pattern(node.left, node.left.start),
                        right=node.right)
        self.error("this can't be assigned to", start)


def _template_continuation(self, start, nl):
    j = start + 1
    while j < self.n:
        if self.t[j] == "\\":
            j += 2
        elif self.t[j] == "`":
            return Token("template", self.t[start + 1:j], start, j + 1, nl)
        elif self.t.startswith("${", j):
            return Token("template-head", self.t[start + 1:j], start, j + 2, nl)
        else:
            j += 1
    self.error("a template that is never closed", start)


Lexer.template_continuation = _template_continuation


class Script:
    def __init__(self, program, comments, source):
        self.program, self.comments, self.source = program, comments, source


def parse(text, name="<javascript>", function_body=False, module=None):
    if module is None:
        try:
            return parse(text, name, function_body, False)
        except ModuleDeclaration:
            return parse(text, name, function_body, True)
    parser = _Parser(text, name, module)
    parser.function["inside"] = function_body
    parser.lexer.template = _wrap_template(parser.lexer)
    try:
        program = parser.program()
    except RecursionError:
        raise JavaScriptError(parser.source, 0, "a nesting too deep to read") from None
    return Script(program, [parser.comments[k] for k in sorted(parser.comments)], parser.source)


def _wrap_template(lexer):
    first = Lexer.template.__get__(lexer)

    def scan_template(start, nl):
        if lexer.t[start] == "}":
            return lexer.template_continuation(start, nl)
        return first(start, nl)
    return scan_template


def children(node):
    for value in node.__dict__.values():
        if isinstance(value, Node):
            yield value
        elif isinstance(value, list):
            yield from (v for v in value if isinstance(v, Node))


def walk(node):
    yield node
    for child in children(node):
        yield from walk(child)

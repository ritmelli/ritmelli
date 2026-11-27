import ast
import re
from collections import deque
from dataclasses import dataclass, field

from . import javascript as js
from . import powershell as ps

PYTHON_BROAD = {"Exception", "BaseException"}
POWERSHELL_BROAD = {"exception", "system.exception"}
SLEEP_MODULES = {"time", "asyncio"}
PS_SLEEPS = {"start-sleep", "sleep"}
SCOPE = re.compile(r"^(?:global|script|local|private):", re.I)


@dataclass(eq=False)
class Node:
    line: int


@dataclass(eq=False)
class Block(Node):
    items: list = field(default_factory=list)


@dataclass(eq=False)
class Function(Node):
    name: str = ""
    body: Block = None


@dataclass(eq=False)
class Name(Node):
    name: str = ""


@dataclass(eq=False)
class Not(Node):
    operand: Node = None


@dataclass(eq=False)
class Condition(Node):
    parts: list = field(default_factory=list)
    opaque: bool = False


@dataclass(eq=False)
class Loop(Node):
    condition: Node = None
    body: Block = None
    attempts: bool = True


@dataclass(eq=False)
class If(Node):
    condition: Node = None
    then: Block = None
    otherwise: Block = None
    fails: bool = False


@dataclass(eq=False)
class Handler(Node):
    broad: bool = False
    body: Block = None


@dataclass(eq=False)
class Try(Node):
    body: Block = None
    handlers: list = field(default_factory=list)
    orelse: Block = None
    final: Block = None
    types: Node = None


@dataclass(eq=False)
class Call(Node):
    name: str = ""
    sleep: bool = False
    parts: list = field(default_factory=list)
    target: str = ""
    schedules: tuple = ()


@dataclass(eq=False)
class Leave(Node):
    kind: str = ""
    label: str = None


@dataclass(eq=False)
class Assign(Node):
    name: str = ""
    known: bool = False
    value: object = None


@dataclass(eq=False)
class Other(Node):
    parts: list = field(default_factory=list)


@dataclass(eq=False)
class Unit:
    language: str
    body: Block
    functions: dict = field(default_factory=dict)


def variable_name(name):
    return SCOPE.sub("", name).lower()


def children(node):
    if isinstance(node, Block):
        return list(node.items)
    if isinstance(node, Function):
        return [node.body]
    if isinstance(node, Loop):
        return [node.condition, node.body]
    if isinstance(node, If):
        return [node.condition, node.then, node.otherwise]
    if isinstance(node, Try):
        return [node.types, node.body, *node.handlers, node.orelse, node.final]
    if isinstance(node, Handler):
        return [node.body]
    if isinstance(node, (Call, Other, Condition)):
        return list(node.parts)
    if isinstance(node, Not):
        return [node.operand]
    return []


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        yield current
        stack += reversed(children(current))


def local(node):
    for child in children(node):
        if child is None:
            continue
        if isinstance(child, (Function, Loop)):
            continue
        yield child
        yield from local(child)


def names_of(node):
    return {n.name for n in walk(node) if isinstance(n, Name)}


def sleeps(unit):
    return [n.line for n in walk(unit.body) if isinstance(n, Call) and n.sleep]


def broad_handlers(unit):
    return [h.line for h in walk(unit.body) if isinstance(h, Handler) and h.broad]


def last_item(block):
    last = block.items[-1] if block is not None and block.items else None
    while isinstance(last, Block):
        last = last.items[-1] if last.items else None
    return last


def leaves(block, inside_helper=False):
    last = last_item(block)
    kinds = ("throw", "exit") if inside_helper else ("return", "throw", "break", "exit")
    return isinstance(last, Leave) and last.kind in kinds


def keeps_going(condition, name, value):
    if isinstance(condition, Name) and condition.name == name:
        return bool(value)
    if isinstance(condition, Not) and isinstance(condition.operand, Name) and condition.operand.name == name:
        return not value
    return False


def turns_off(conditions, body):
    assigned = [n for n in [body, *local(body)] if isinstance(n, Assign)]
    return any(a.name in names_of(c) and not (a.known and keeps_going(c, a.name, a.value))
               for c in conditions for a in assigned)


def inlined(node, functions, site=None, seen=()):
    out = []
    for child in local(node):
        out.append((child, site))
        if isinstance(child, Call) and child.target in functions and child.target not in seen:
            function = functions[child.target]
            here = site or child
            out.append((function.body, here))
            out += inlined(function.body, functions, here, (*seen, child.target))
    return out


def keeps_output(redirection):
    return redirection.operator[:1] in "23456" and not redirection.operator.endswith("&1")


def inside_switch(block, label):
    for n in [block, *local(block)] if block is not None else []:
        if isinstance(n, Leave) and n.kind in ("break", "continue") and n.label in (None, label):
            n.kind = "switch"
    return block


def leaves_loop(block):
    return any(isinstance(n, Leave) and n.kind in ("break", "return", "exit") for n in [block, *local(block)])


def polarities(node, site, names, negated=False):
    if node is None:
        return set()
    if node is site:
        return {not negated}
    if isinstance(node, Name) and node.name in names:
        return {names[node.name] != negated}
    if isinstance(node, Not):
        return polarities(node.operand, site, names, not negated)
    found = set()
    for child in children(node):
        found |= polarities(child, site, names, negated)
    if found and not (isinstance(node, Condition) and not node.opaque):
        return {None}
    return found


def ends_on(site, loop, own):
    names = {}
    for statement in own:
        if isinstance(statement, (Block, Condition)):
            found = {p for c in children(statement) if not isinstance(c, Assign) for p in polarities(c, site, {})}
            if found in ({True}, {False}):
                names.update({a.name: True in found for a in children(statement) if isinstance(a, Assign)})
    for n in own:
        if isinstance(n, If) and n.condition is not None and leaves_loop(n.then) and \
                polarities(n.condition, site, names) == {True}:
            return True
    return loop.condition is not None and polarities(loop.condition, site, names) == {False}


def retries(unit):
    found = []
    for loop in walk(unit.body):
        if not isinstance(loop, Loop):
            continue
        marked = inlined(loop, unit.functions)
        inner = [n for n, _ in marked]
        own = [n for n, site in marked if site is None]
        from_helper = {id(n) for n, site in marked if site is not None}
        if not any(isinstance(n, Call) and n.sleep for n in inner):
            continue
        handled = {id(x) for t in inner if isinstance(t, Try) for h in t.handlers for x in walk(h)}
        ends = any(isinstance(n, Leave) and n.kind in ("return", "break", "exit") and id(n) not in handled
                   and not (n.kind == "return" and id(n) in from_helper) for n in inner)
        guards = {id(s): n.condition for n in inner if isinstance(n, If) for s in n.then.items}
        for attempt, site in marked:
            if not isinstance(attempt, Try):
                continue
            helper_succeeds = site is not None and loop.attempts and ends_on(site, loop, own)
            if site is not None and not helper_succeeds:
                continue
            again = [h for h in attempt.handlers if not leaves(h.body, site is not None)]
            tried = [attempt.body, *([attempt.orelse] if attempt.orelse else [])]
            waits_on_failure = any(isinstance(n, Call) and n.sleep for h in again for n in local(h)) and not any(
                isinstance(n, Call) and n.sleep for b in tried for n in [b, *local(b)])
            conditions = [c for c in (guards.get(id(attempt)), loop.condition) if c is not None]
            stops_on_success = helper_succeeds or turns_off(conditions, attempt.body)
            if again and (waits_on_failure or ends or stops_on_success):
                found.append(loop.line)
                break
    return found


PYTHON_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
PYTHON_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def evaluated(nodes, postponed, in_function):
    queue = deque((node, in_function) for node in nodes)
    while queue:
        node, in_function = queue.popleft()
        yield node
        for name, value in ast.iter_fields(node):
            if name == "annotation" and (postponed or (in_function and isinstance(node, ast.AnnAssign))) or \
                    name == "returns" and postponed:
                continue
            inside = (in_function or name == "body" and isinstance(node, PYTHON_FUNCTIONS)) and \
                not (name == "body" and isinstance(node, ast.ClassDef))
            queue.extend((child, inside) for child in (value if isinstance(value, list) else [value])
                         if isinstance(child, ast.AST))


def postponed_annotations(tree):
    return any(isinstance(s, ast.ImportFrom) and s.module == "__future__" and
               any(a.name == "annotations" for a in s.names) for s in getattr(tree, "body", []))


class PythonLowering:
    def __init__(self, tree, line_of=None):
        self.tree = tree
        self.line_of = line_of or (lambda n: n)
        self.modules, self.sleep_names = set(SLEEP_MODULES), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.modules |= {a.asname for a in node.names if a.name in SLEEP_MODULES and a.asname}
            elif isinstance(node, ast.ImportFrom) and node.module in SLEEP_MODULES:
                self.sleep_names |= {a.asname or a.name for a in node.names if a.name == "sleep"}
        self.functions = {}
        self.classes = []
        self.in_class_body = False
        self.postponed = postponed_annotations(tree)
        self.in_function = False

    def unit(self):
        body = self.block(self.tree.body, 1)
        return Unit("python", body, self.functions)

    def line(self, node):
        return self.line_of(getattr(node, "lineno", 1))

    def block(self, statements, line):
        return Block(self.line_of(line) if statements is None else (self.line(statements[0]) if statements else
                                                                    self.line_of(line)),
                     [self.statement(s) for s in statements or []])

    def is_sleep(self, call):
        f = call.func
        return (isinstance(f, ast.Attribute) and f.attr == "sleep" and isinstance(f.value, ast.Name)
                and f.value.id in self.modules) or (isinstance(f, ast.Name) and f.id in self.sleep_names)

    def condition(self, test):
        if test is None:
            return None
        if isinstance(test, ast.Name):
            return Name(self.line(test), test.id)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return Not(self.line(test), self.condition(test.operand))
        if isinstance(test, ast.BoolOp):
            return Condition(self.line(test), [self.condition(v) for v in test.values])
        line = self.line(test)
        if isinstance(test, ast.Await):
            return self.condition(test.value)
        if isinstance(test, ast.NamedExpr):
            return self.walrus(test)
        return Condition(line, self.expression_calls(test), not isinstance(test, ast.Call))

    def walrus(self, named):
        known = isinstance(named.value, ast.Constant)
        line = self.line(named)
        return Condition(line, [self.condition(named.value),
                                Assign(line, named.target.id, known, named.value.value if known else None)])

    def expression_calls(self, expression):
        holder = ast.Expr(value=expression)
        return self.calls(holder)

    def calls(self, node):
        out = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(child, ast.Lambda):
                defaults = [*child.args.defaults, *(d for d in child.args.kw_defaults if d is not None)]
                out += [c for d in defaults for c in self.expression_calls(d)]
                out.append(Function(self.line(child), "<lambda>", Block(self.line(child), self.expression_calls(child.body))))
                continue
            if isinstance(child, ast.NamedExpr):
                out.append(self.walrus(child))
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if not (isinstance(node, ast.Call) and child is node.func):
                    out.append(Name(self.line(child), child.id))
            elif isinstance(child, ast.Call):
                name = self.call_name(child.func)
                out.append(Call(self.line(child), name, self.is_sleep(child), self.calls(child),
                                self.call_target(child.func)))
            else:
                out += self.calls(child)
        return out

    def call_name(self, f):
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
        return ""

    def call_target(self, f):
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self" and self.classes:
            return f"{self.classes[-1]}.{f.attr}"
        return ""

    def annotation_runs(self):
        return not self.in_function and not self.postponed

    def assignment_calls(self, s):
        if not isinstance(s, ast.AnnAssign):
            return self.calls(s)
        evaluated = [s.target, *([s.value] if s.value is not None else []),
                     *([s.annotation] if self.annotation_runs() else [])]
        return [c for e in evaluated for c in self.expression_calls(e)]

    def defined_now(self, s):
        expressions = list(s.decorator_list)
        if isinstance(s, ast.ClassDef):
            expressions += [*s.bases, *(k.value for k in s.keywords)]
        else:
            arguments = [*s.args.posonlyargs, *s.args.args, *s.args.kwonlyargs, s.args.vararg, s.args.kwarg]
            expressions += [*s.args.defaults, *(d for d in s.args.kw_defaults if d is not None)]
            if not self.postponed:
                expressions += [*(a.annotation for a in arguments if a is not None and a.annotation is not None),
                                *([s.returns] if s.returns is not None else [])]
        return Other(self.line(s), [c for e in expressions for c in self.expression_calls(e)])

    def statement(self, s):
        line = self.line(s)
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            direct, self.in_class_body = self.in_class_body, False
            outer, self.in_function = self.in_function, True
            function = Function(line, s.name, self.block(s.body, s.lineno))
            self.in_function = outer
            if not direct:
                self.functions.setdefault(s.name, function)
            return Block(line, [self.defined_now(s), function])
        if isinstance(s, ast.ClassDef):
            self.classes.append(s.name)
            items = [self.defined_now(s)]
            outer, self.in_function = self.in_function, False
            try:
                for x in s.body:
                    self.in_class_body = isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                    node = self.statement(x)
                    self.in_class_body = False
                    if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.functions.setdefault(f"{s.name}.{x.name}", node.items[-1])
                    items.append(node)
            finally:
                self.classes.pop()
                self.in_function = outer
            return Block(line, items)
        if isinstance(s, (ast.For, ast.AsyncFor)):
            loop = Loop(line, None, self.block(s.body, s.lineno), self.counts_attempts(s))
            return Block(line, [Other(line, self.expression_calls(s.iter)), loop,
                                *self.block(s.orelse, s.lineno).items])
        if isinstance(s, ast.While):
            loop = Loop(line, self.condition(s.test), self.block(s.body, s.lineno))
            return Block(line, [loop, *self.block(s.orelse, s.lineno).items])
        if isinstance(s, ast.If):
            return If(line, self.condition(s.test), self.block(s.body, s.lineno),
                      self.block(s.orelse, s.lineno) if s.orelse else None)
        if isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            handlers = [Handler(self.line(h), self.broad(h.type), self.block(h.body, h.lineno)) for h in s.handlers]
            types = Other(line, [c for h in s.handlers if h.type is not None for c in self.expression_calls(h.type)])
            return Try(line, self.block(s.body, s.lineno), handlers,
                       self.block(s.orelse, s.lineno) if s.orelse else None,
                       self.block(s.finalbody, s.lineno) if s.finalbody else None, types)
        if isinstance(s, (ast.With, ast.AsyncWith)):
            return Block(line, [Other(line, [c for item in s.items for c in self.calls(item)]),
                                *self.block(s.body, s.lineno).items])
        if isinstance(s, ast.Match):
            return Block(line, [Other(line, self.expression_calls(s.subject))] + [
                If(self.line(c.pattern), self.condition(c.guard), self.block(c.body, c.pattern.lineno), None)
                for c in s.cases])
        if isinstance(s, ast.Return):
            return Block(line, [Other(line, self.calls(s)), Leave(line, "return")])
        if isinstance(s, ast.Raise):
            return Block(line, [Other(line, self.calls(s)), Leave(line, "throw")])
        if isinstance(s, ast.Break):
            return Leave(line, "break")
        if isinstance(s, ast.Continue):
            return Leave(line, "continue")
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and self.exits(s.value):
            return Block(line, [Other(line, self.calls(s)), Leave(line, "exit")])
        if isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = s.targets if isinstance(s, ast.Assign) else [s.target]
            value = s.value
            plain = not isinstance(s, ast.AugAssign) and value is not None and len(targets) == 1 and \
                isinstance(targets[0], ast.Name)
            out = [self.condition(value) if plain else Other(line, self.assignment_calls(s))]
            if plain and isinstance(s, ast.AnnAssign) and self.annotation_runs():
                out.append(Other(line, self.expression_calls(s.annotation)))
            for target in targets:
                for t in ast.walk(target):
                    if isinstance(t, ast.Name):
                        known = isinstance(s, (ast.Assign, ast.AnnAssign)) and isinstance(value, ast.Constant)
                        out.append(Assign(line, t.id, known, value.value if known else None))
            return Block(line, out)
        return Block(line, [Other(line, self.calls(s))])

    def counts_attempts(self, loop):
        if isinstance(loop.iter, ast.Call) and isinstance(loop.iter.func, ast.Name) and loop.iter.func.id == "range":
            return True
        targets = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
        used = {n.id for s in loop.body for n in ast.walk(s) if isinstance(n, ast.Name) and n.id != "_"}
        return not targets & used and not ("_" in targets and reads_underscore(
            list(evaluated(loop.body, self.postponed, self.in_function))))

    def exits(self, call):
        f = call.func
        return (isinstance(f, ast.Attribute) and f.attr in ("exit", "_exit") and isinstance(f.value, ast.Name)
                and f.value.id in ("sys", "os")) or (isinstance(f, ast.Name) and f.id in ("exit", "quit"))

    def broad(self, node):
        if node is None:
            return True
        if isinstance(node, ast.Tuple):
            return any(self.broad(e) for e in node.elts)
        if isinstance(node, ast.Name):
            return node.id in PYTHON_BROAD
        return isinstance(node, ast.Attribute) and node.attr in PYTHON_BROAD


def reads_underscore(nodes):
    augmented = {id(n.target) for n in nodes if isinstance(n, ast.AugAssign)}
    declared = {id(n.target) for n in nodes if isinstance(n, ast.AnnAssign) and n.value is None}
    names = [n for n in nodes if isinstance(n, ast.Name) and n.id == "_"]
    reads = any(isinstance(n.ctx, ast.Load) or id(n) in augmented for n in names)
    rebinds = any(isinstance(n.ctx, ast.Store) and id(n) not in augmented | declared for n in names) or \
        any(bound_name(n) == "_" for n in nodes)
    return reads and not rebinds


def bound_name(node):
    if isinstance(node, ast.alias):
        return node.asname or node.name.split(".")[0]
    if isinstance(node, ast.arg):
        return node.arg
    return getattr(node, "name", None)


class PowerShellLowering:
    def __init__(self, script, line_of):
        self.script = script
        self.line_of = line_of
        self.functions = {}

    def line(self, node):
        return self.line_of(node.span.start)

    def unit(self):
        return Unit("powershell", self.script_block(self.script.block), self.functions)

    def script_block(self, block):
        items = [self.node(s) for s in block.statements]
        if block.params:
            items.insert(0, Other(self.line(block.params), self.parts(block.params)))
        return Block(self.line(block), items)

    def block(self, block):
        if block is None:
            return None
        return Block(self.line(block), [self.node(s) for s in block.statements])

    def unwrapped(self, node):
        while True:
            if isinstance(node, ps.Pipeline) and len(node.elements) == 1 and isinstance(
                    node.elements[0], ps.ExpressionElement) and not node.elements[0].redirections:
                node = node.elements[0].expression
            elif isinstance(node, ps.Paren):
                node = node.pipeline
            else:
                return node

    def flow_label(self, flow):
        if flow.kind not in ("break", "continue") or flow.value is None:
            return None
        value = self.unwrapped(flow.value)
        if isinstance(value, ps.Bareword):
            return value.text.lower()
        if isinstance(value, ps.String) and not value.parts:
            return value.value.lower()
        return "?"

    def truth(self, node):
        if isinstance(node, ps.Assign) and node.op == "=" and node.value is not None:
            target = node.target
            while isinstance(target, ps.Cast):
                target = target.operand
            if not isinstance(target, ps.Variable):
                return None
            return [self.condition(node.value), Assign(self.line(node), variable_name(target.name))]
        if isinstance(node, ps.Pipeline) and len(node.elements) == 1 and isinstance(node.elements[0], ps.Command) \
                and all(keeps_output(r) for r in node.elements[0].redirections):
            return [self.node(node.elements[0])]
        if isinstance(node, ps.Pipeline) and len(node.elements) == 1 and isinstance(node.elements[0], ps.ExpressionElement) \
                and all(keeps_output(r) for r in node.elements[0].redirections):
            element = node.elements[0]
            return [self.condition(element.expression), *(self.node(r) for r in element.redirections)]
        return None

    def condition(self, node):
        if node is None:
            return None
        inner = self.unwrapped(node)
        if isinstance(inner, ps.Variable):
            return Name(self.line(inner), variable_name(inner.name))
        if isinstance(inner, ps.Unary) and inner.op in ("!", "not"):
            return Not(self.line(inner), self.condition(inner.operand))
        if isinstance(inner, ps.Binary) and inner.op in ("and", "or"):
            return Condition(self.line(inner), [self.condition(inner.left), self.condition(inner.right)])
        truth = self.truth(inner)
        if truth is not None:
            return Condition(self.line(node), truth)
        return self.node(inner)

    def parts(self, node):
        out = []
        for child in self.direct_children(node):
            out.append(self.node(child))
        return out

    def direct_children(self, node):
        found = []
        for name in node.__dataclass_fields__:
            if name == "span":
                continue
            value = getattr(node, name)
            stack = [value]
            while stack:
                v = stack.pop()
                if isinstance(v, (list, tuple)):
                    stack += reversed(v)
                elif isinstance(v, dict):
                    stack += reversed(list(v.values()))
                elif isinstance(v, (ps.Node, ps.ScriptBlock)):
                    found.append(v)
        return found

    def node(self, n):
        line = self.line(n)
        if isinstance(n, ps.Function):
            function = Function(line, n.name.lower(), self.script_block(n.body))
            self.functions.setdefault(n.name.lower(), function)
            return function
        if isinstance(n, ps.Method):
            return Function(line, n.name.lower(), self.script_block(n.body))
        if isinstance(n, ps.While):
            return Loop(line, self.condition(n.condition), self.block(n.body))
        if isinstance(n, ps.DoLoop):
            condition = self.condition(n.condition)
            if n.until and condition is not None:
                condition = Not(line, condition)
            return Loop(line, condition, self.block(n.body))
        if isinstance(n, ps.For):
            body = [*self.block(n.body).items, *([self.node(n.iterator)] if n.iterator is not None else [])]
            loop = Loop(line, self.condition(n.condition), Block(line, body))
            return Block(line, [*([self.node(n.initializer)] if n.initializer is not None else []), loop])
        if isinstance(n, ps.Foreach):
            return Block(line, [self.node(n.iterable), Loop(line, None, self.block(n.body), self.counts_attempts(n))])
        if isinstance(n, ps.If):
            node = None
            for condition, block in reversed(n.clauses):
                otherwise = node if node is not None else self.block(n.else_block)
                node = If(self.line(condition), self.condition(condition), self.block(block),
                          Block(otherwise.line, [otherwise]) if isinstance(otherwise, If) else otherwise)
            return node
        if isinstance(n, ps.Switch):
            label = n.label.lower() if n.label else None
            clauses = [If(self.line(b), Condition(self.line(k), [self.node(k)], True),
                          inside_switch(self.block(b), label), None) for k, b in n.clauses]
            default = inside_switch(self.block(n.default), label) if n.default else None
            default = [If(self.line(n.default), None, default, None)] if n.default else []
            return Block(line, [self.node(n.condition), *clauses, *default])
        if isinstance(n, ps.Try):
            handlers = [Handler(self.line(c), self.broad(c.types), self.block(c.body)) for c in n.catches]
            return Try(line, self.block(n.body), handlers, None, self.block(n.finally_block))
        if isinstance(n, ps.Trap):
            return Try(line, Block(line, []), [Handler(line, self.broad([n.type] if n.type else []), self.block(n.body))])
        if isinstance(n, ps.Flow):
            inner = [self.node(n.value)] if n.value is not None and not isinstance(n.value, ps.Bareword) else []
            return Block(line, [*inner, Leave(line, n.kind, self.flow_label(n))])
        if isinstance(n, ps.Assign):
            target = n.target
            while isinstance(target, ps.Cast):
                target = target.operand
            targets = target.items if isinstance(target, ps.ArrayLiteral) else [target]
            plain = n.op == "=" and n.value is not None and len(targets) == 1 and isinstance(targets[0], ps.Variable)
            out = [self.condition(n.value) if plain else self.node(n.value)] if n.value is not None else []
            for t in targets:
                while isinstance(t, ps.Cast):
                    t = t.operand
                if isinstance(t, ps.Variable):
                    known, value = self.constant(n.value) if n.op == "=" else (False, None)
                    out.append(Assign(line, variable_name(t.name), known, value))
                else:
                    out.append(self.node(t))
            return Block(line, out)
        if isinstance(n, ps.Command):
            name = self.command_name(n)
            return Call(line, name, name in PS_SLEEPS, self.parts(n), name)
        if isinstance(n, ps.ScriptBlock):
            return self.script_block(n)
        if isinstance(n, ps.ScriptBlockExpression):
            return Function(line, "<scriptblock>", self.script_block(n.block))
        if isinstance(n, ps.InvokeMember):
            name_node = n.name
            name = name_node.text.lower() if isinstance(name_node, ps.Bareword) else ""
            target = n.target
            static_type = target.name.lower() if isinstance(target, ps.TypeName) else ""
            sleep = name == "sleep" and static_type in ("thread", "threading.thread", "system.threading.thread")
            return Call(line, name, sleep, self.parts(n))
        if isinstance(n, ps.Variable):
            return Name(line, variable_name(n.name))
        return Other(line, self.parts(n))

    def broad(self, types):
        return not types or any(t.lower().strip("[]") in POWERSHELL_BROAD for t in types)

    def command_name(self, command):
        name = (command.name or "").lower()
        module, _, bare = name.rpartition("\\")
        return bare if module == "microsoft.powershell.utility" else name

    def counts_attempts(self, loop):
        inner = loop.iterable
        while isinstance(inner, ps.Pipeline) and len(inner.elements) == 1 and isinstance(
                inner.elements[0], ps.ExpressionElement):
            inner = inner.elements[0].expression
        if isinstance(inner, ps.Binary) and inner.op == "..":
            return True
        name = variable_name(loop.variable.name)
        return not any(isinstance(v, ps.Variable) and variable_name(v.name) == name for v in ps.walk(loop.body))

    def constant(self, value):
        inner = value
        while isinstance(inner, ps.Pipeline) and len(inner.elements) == 1 and isinstance(
                inner.elements[0], ps.ExpressionElement):
            inner = inner.elements[0].expression
        if isinstance(inner, ps.Variable) and inner.name.lower() in ("true", "false", "null"):
            return True, {"true": True, "false": False, "null": None}[inner.name.lower()]
        if isinstance(inner, ps.Number):
            try:
                return True, int(inner.text) != 0
            except ValueError:
                return False, None
        return False, None


def python_unit(tree, line_of=None):
    return PythonLowering(tree, line_of).unit()


def powershell_unit(script, line_of):
    return PowerShellLowering(script, line_of).unit()


JS_FUNCTIONS = {"FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"}
JS_LOOPS = {"ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement"}
JS_RESCHEDULE = "setTimeout"
JS_REJECTION = {"catch", "aoFalhar"}
JS_ERROR_EVENTS = {"error", "unhandledrejection"}


def js_name(node):
    if node is None:
        return ""
    if node.type == "Identifier":
        return node.name
    if node.type == "Literal" and isinstance(node.value, str):
        return node.value
    return ""


def js_callee(node):
    return node.expression if node.type == "ChainExpression" else node


def js_does_nothing(node):
    if node.type == "BlockStatement":
        return all(js_does_nothing(s) for s in node.body)
    if node.type == "EmptyStatement":
        return True
    if node.type == "ExpressionStatement":
        return js_does_nothing(node.expression)
    if node.type == "UnaryExpression" and node.operator == "void":
        return node.argument.type in ("Identifier", "Literal")
    return node.type in ("Identifier", "Literal")


def js_swallows(callback):
    return callback is not None and callback.type in JS_FUNCTIONS and js_does_nothing(callback.body)


def reaches(functions):
    calls = {name: {c.target for c in walk(f.body) if isinstance(c, Call) and c.target} for name, f in functions.items()}
    found = {}
    for name in functions:
        seen, stack = set(), [name]
        while stack:
            for target in calls.get(stack.pop(), ()):
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
        found[name] = seen
    return found


def unconditional(node):
    for child in children(node):
        if child is None or isinstance(child, (Function, Loop, If, Try, Handler)):
            continue
        yield child
        yield from unconditional(child)


def reschedules(unit):
    reach, found = reaches(unit.functions), []

    def polled(function, name):
        return any(isinstance(n, Call) and name in n.schedules for n in unconditional(function.body))

    def visit(node, enclosing, failing):
        if node is None:
            return
        if isinstance(node, Call) and node.schedules and failing and enclosing:
            if any(any(s == e.name or e.name in reach.get(s, ()) for e in enclosing) and not polled(enclosing[-1], s)
                   for s in node.schedules):
                found.append(node.line)
        if isinstance(node, Function):
            enclosing = (*enclosing, node) if node.name else enclosing
        if isinstance(node, Handler):
            failing = True
        if isinstance(node, If):
            visit(node.condition, enclosing, failing)
            visit(node.then, enclosing, failing or node.fails and last_leave(node.then) == "return")
            visit(node.otherwise, enclosing, failing)
            return
        for child in children(node):
            visit(child, enclosing, failing)

    visit(unit.body, (), False)
    return found


def last_leave(block):
    last = last_item(block)
    return last.kind if isinstance(last, Leave) else None


def js_only_expression(body):
    if body.type != "BlockStatement":
        return body
    if len(body.body) == 1 and body.body[0].type in ("ExpressionStatement", "ReturnStatement"):
        statement = body.body[0]
        return statement.expression if statement.type == "ExpressionStatement" else statement.argument
    return None


def js_failure_test(test):
    if test.type == "UnaryExpression" and test.operator == "!":
        return True
    if test.type == "LogicalExpression":
        return js_failure_test(test.left) or js_failure_test(test.right)
    if test.type == "BinaryExpression" and test.operator in ("==", "==="):
        return any(js_absent(side) for side in (test.left, test.right))
    return False


def js_absent(node):
    if node.type == "Identifier":
        return node.name == "undefined"
    if node.type == "Literal":
        return node.value is None or node.value == "undefined"
    return node.type == "UnaryExpression" and node.operator == "void"


def js_references(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "Identifier":
            yield n.name
            continue
        for key, value in n.__dict__.items():
            if key == "property" and n.type == "MemberExpression" and not n.computed or \
                    key == "key" and n.type in ("Property", "MethodDefinition", "PropertyDefinition") \
                    and not n.computed and not getattr(n, "shorthand", False):
                continue
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, js.Node):
                    stack.append(child)


def calls_named(unit, names):
    return [n.line for n in walk(unit.body) if isinstance(n, Call) and n.name in names]


class JavaScriptLowering:
    def __init__(self, scripts):
        self.scripts = scripts
        self.functions = {}
        self.line_of = None

    def unit(self):
        items = []
        for script, line_of in self.scripts:
            self.line_of = line_of
            body = self.statements(script.program.body, script.program)
            items.append(body)
        return Unit("javascript", Block(items[0].line if items else 1, items), self.functions)

    def line(self, node):
        return self.line_of(node.start)

    def statements(self, nodes, at):
        return Block(self.line(nodes[0] if nodes else at), [self.statement(s) for s in nodes])

    def body(self, node):
        if node is None:
            return None
        if node.type == "BlockStatement":
            return self.statements(node.body, node)
        return Block(self.line(node), [self.statement(node)])

    def function(self, node, name="", register=False):
        if node.body.type == "BlockStatement":
            body = self.statements(node.body.body, node.body)
        else:
            body = Block(self.line(node.body), [Block(self.line(node.body), [*self.expression(node.body),
                                                                            Leave(self.line(node.body), "return")])])
        defaults = [c for p in node.params for c in self.expression(p)]
        if defaults:
            body.items.insert(0, Other(self.line(node), defaults))
        function = Function(self.line(node), name, body)
        if register and name:
            self.functions[name] = function
        return function

    def condition(self, test):
        if test is None:
            return None
        if test.type == "Identifier":
            return Name(self.line(test), test.name)
        if test.type == "UnaryExpression" and test.operator == "!":
            return Not(self.line(test), self.condition(test.argument))
        if test.type == "LogicalExpression" and test.operator in ("&&", "||"):
            return Condition(self.line(test), [self.condition(test.left), self.condition(test.right)])
        if test.type == "AwaitExpression":
            return self.condition(test.argument)
        if test.type == "AssignmentExpression" and test.operator == "=" and test.left.type == "Identifier":
            return Condition(self.line(test), [self.condition(test.right), self.assigned(test)])
        if test.type == "ChainExpression":
            return self.condition(test.expression)
        return Condition(self.line(test), self.expression(test), test.type not in ("CallExpression",))

    def assigned(self, node):
        value = node.right if node.type == "AssignmentExpression" else node.init
        known = value is not None and value.type == "Literal" and not isinstance(value.value, dict)
        target = node.left if node.type == "AssignmentExpression" else node.id
        return Assign(self.line(node), target.name, known, value.value if known else None)

    def statement(self, s):
        line, kind = self.line(s), s.type
        if kind == "BlockStatement":
            return self.statements(s.body, s)
        if kind == "FunctionDeclaration":
            return self.function(s, s.id.name if s.id else "", register=True)
        if kind == "VariableDeclaration":
            return Block(line, [Block(self.line(d), self.declarator(d)) for d in s.declarations])
        if kind in ("ClassDeclaration", "ClassExpression"):
            return Block(line, self.class_items(s))
        if kind == "IfStatement":
            return If(line, self.condition(s.test), self.body(s.consequent), self.body(s.alternate),
                      js_failure_test(s.test))
        if kind == "ForStatement":
            update = [Other(self.line(s.update), self.expression(s.update))] if s.update else []
            body = self.body(s.body)
            body.items += update
            prepare = [] if s.init is None else [self.statement(s.init) if s.init.type == "VariableDeclaration"
                                                 else Other(line, self.expression(s.init))]
            return Block(line, [*prepare, Loop(line, self.condition(s.test), body)])
        if kind in ("ForInStatement", "ForOfStatement"):
            return Block(line, [Other(line, self.expression(s.right)),
                                Loop(line, None, self.body(s.body), self.counts_attempts(s))])
        if kind in ("WhileStatement", "DoWhileStatement"):
            return Loop(line, self.condition(s.test), self.body(s.body))
        if kind == "TryStatement":
            handlers = []
            if s.handler is not None:
                handlers.append(Handler(self.line(s.handler), js_does_nothing(s.handler.body),
                                        self.statements(s.handler.body.body, s.handler.body)))
            return Try(line, self.statements(s.block.body, s.block), handlers, None,
                       self.statements(s.finalizer.body, s.finalizer) if s.finalizer else None, None)
        if kind == "ReturnStatement":
            return Block(line, [Other(line, self.expression(s.argument) if s.argument else []), Leave(line, "return")])
        if kind == "ThrowStatement":
            return Block(line, [Other(line, self.expression(s.argument)), Leave(line, "throw")])
        if kind in ("BreakStatement", "ContinueStatement"):
            return Leave(line, "break" if kind == "BreakStatement" else "continue", s.label.name if s.label else None)
        if kind == "SwitchStatement":
            return self.switch(s, None)
        if kind == "LabeledStatement":
            if s.body.type == "SwitchStatement":
                return self.switch(s.body, s.label.name)
            return self.body(s.body)
        if kind == "ExpressionStatement":
            if s.expression.type == "AssignmentExpression" and s.expression.operator == "=" and \
                    s.expression.left.type == "Identifier" and s.expression.right.type not in JS_FUNCTIONS:
                return Block(line, [self.condition(s.expression.right), self.assigned(s.expression)])
            return Block(line, [Other(line, self.expression(s.expression))])
        if kind in ("EmptyStatement", "DebuggerStatement", "ImportDeclaration", "ExportAllDeclaration"):
            return Block(line, [])
        if kind in ("ExportNamedDeclaration", "ExportDefaultDeclaration") and s.declaration is not None:
            if s.declaration.type in ("FunctionDeclaration", "ClassDeclaration", "VariableDeclaration"):
                return self.statement(s.declaration)
            return Block(line, [Other(line, self.expression(s.declaration))])
        if kind == "ExportNamedDeclaration":
            return Block(line, [])
        if kind == "WithStatement":
            return Block(line, [Other(line, self.expression(s.object)), self.body(s.body)])
        return Block(line, [Other(line, self.parts(s))])

    def switch(self, s, label):
        cases = []
        for case in s.cases:
            block = self.statements(case.consequent, case)
            for n in [block, *local(block)]:
                if isinstance(n, Leave) and n.kind == "break" and n.label in (None, label):
                    n.kind = "switch"
            test = Condition(self.line(case), self.expression(case.test), True) if case.test is not None else None
            cases.append(If(self.line(case), test, block, None))
        return Block(self.line(s), [Other(self.line(s), self.expression(s.discriminant)), *cases])

    def declarator(self, d):
        if d.init is None:
            return []
        if d.id.type == "Identifier" and d.init.type in JS_FUNCTIONS:
            return [self.function(d.init, d.id.name, register=True)]
        if d.id.type == "Identifier":
            return [self.condition(d.init), self.assigned(d)]
        return [Other(self.line(d), [*self.expression(d.id), *self.expression(d.init)])]

    def class_items(self, node):
        items = [Other(self.line(node), self.expression(node.superClass))] if node.superClass else []
        for member in node.body.body:
            if member.type == "MethodDefinition":
                key = [] if not member.computed else self.expression(member.key)
                items += [Other(self.line(member), key), self.function(member.value, js_name(member.key))]
            elif member.type == "PropertyDefinition":
                items.append(Other(self.line(member), [*(self.expression(member.key) if member.computed else []),
                                                        *(self.expression(member.value) if member.value else [])]))
            elif member.type == "StaticBlock":
                items.append(self.statements(member.body, member))
        return items

    def parts(self, node):
        return [n for child in js.children(node) for n in self.expression(child)]

    def expression(self, e):
        if e is None:
            return []
        kind = e.type
        if kind in JS_FUNCTIONS:
            return [self.function(e, e.id.name if getattr(e, "id", None) else "")]
        if kind in ("ClassDeclaration", "ClassExpression"):
            return [Other(self.line(e), self.class_items(e))]
        if kind == "Identifier":
            return [Name(self.line(e), e.name)]
        if kind in ("CallExpression", "NewExpression"):
            return [self.call(e)]
        if kind == "ChainExpression":
            return self.expression(e.expression)
        if kind == "MemberExpression":
            return [*self.expression(e.object), *(self.expression(e.property) if e.computed else [])]
        if kind == "Property":
            return [*(self.expression(e.key) if e.computed else []), *self.property_value(e)]
        if kind == "AssignmentExpression":
            return self.assignment(e)
        if kind == "TaggedTemplateExpression":
            return [Call(self.line(e), "", False, [*self.expression(e.tag), *self.expression(e.quasi)])]
        return self.parts(e)

    def property_value(self, e):
        if e.value.type in JS_FUNCTIONS:
            return [self.function(e.value, js_name(e.key) if not e.computed else "")]
        return self.expression(e.value)

    def assignment(self, e):
        target, value = e.left, e.right
        named = target.type == "Identifier"
        handler = target.type == "MemberExpression" and not target.computed and js_name(target.property) == "onerror" \
            or named and target.name == "onerror"
        if value.type in JS_FUNCTIONS:
            function = self.function(value, target.name if named else "", register=named and e.operator == "=")
            left = [] if named else self.expression(target)
            return [*left, Handler(self.line(value), False, Block(function.line, [function])) if handler else function]
        if named and e.operator == "=":
            return [Condition(self.line(e), [self.condition(value), self.assigned(e)])]
        out = [*([] if named else self.expression(target)), *self.expression(value)]
        if named:
            out.append(Assign(self.line(e), target.name))
        return out

    def call(self, e):
        callee = js_callee(e.callee)
        name = callee.name if callee.type == "Identifier" else \
            js_name(callee.property) if callee.type == "MemberExpression" and not callee.computed else ""
        line = self.line(callee.property if callee.type == "MemberExpression" and not callee.computed else callee)
        parts = [] if callee.type == "Identifier" else self.expression(callee)
        for k, argument in enumerate(e.arguments):
            lowered = self.expression(argument)
            rejection = callee.type == "MemberExpression" and (name in JS_REJECTION and k == 0 or name == "then" and k == 1)
            rejection = rejection or name == "addEventListener" and k == 1 and \
                js_name(e.arguments[0]) in JS_ERROR_EVENTS
            if rejection and argument.type in JS_FUNCTIONS:
                parts.append(Handler(line, name in ("catch", "then") and js_swallows(argument),
                                     Block(self.line(argument), lowered)))
            else:
                parts += lowered
        target = callee.name if callee.type == "Identifier" else ""
        schedules = self.scheduled(e) if name == JS_RESCHEDULE and e.type == "CallExpression" else ()
        return Call(line, name, self.is_wait(e), parts, target, schedules)

    def scheduled(self, e):
        callback = e.arguments[0] if e.arguments else None
        if callback is None:
            return ()
        if callback.type == "Identifier":
            return (callback.name,)
        if callback.type in JS_FUNCTIONS:
            return tuple(sorted({js_callee(n.callee).name for n in js.walk(callback.body)
                                 if n.type == "CallExpression" and js_callee(n.callee).type == "Identifier"}))
        return ()

    def is_wait(self, e):
        if e.type != "NewExpression" or e.callee.type != "Identifier" or e.callee.name != "Promise":
            return False
        executor = e.arguments[0] if e.arguments else None
        if executor is None or executor.type not in JS_FUNCTIONS or not executor.params:
            return False
        resolve = executor.params[0]
        body = js_only_expression(executor.body)
        if resolve.type != "Identifier" or body is None or body.type != "CallExpression" or \
                js_callee(body.callee).type != "Identifier" or js_callee(body.callee).name != JS_RESCHEDULE or \
                not body.arguments:
            return False
        callback = body.arguments[0]
        if callback.type == "Identifier":
            return callback.name == resolve.name
        inner = js_only_expression(callback.body) if callback.type in JS_FUNCTIONS else None
        return inner is not None and inner.type == "CallExpression" and js_callee(inner.callee).type == "Identifier" \
            and js_callee(inner.callee).name == resolve.name

    def counts_attempts(self, loop):
        targets = set(js_references(loop.left))
        used = set(js_references(loop.body))
        return not (targets - {"_"}) & used


def javascript_unit(scripts):
    return JavaScriptLowering(scripts).unit()

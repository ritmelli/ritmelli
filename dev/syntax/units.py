import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

from . import ir
from . import powershell as ps
from . import yaml
from .text import Source, SyntaxProblem

POWERSHELL_NAME = re.compile(r"powershell|pwsh", re.I)
COMMAND_FLAGS = {"-command", "-c"}
PIN = re.compile(r"@[0-9a-f]{40}$")
SILENT_TOKENS = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
FSTRING_START = getattr(tokenize, "FSTRING_START", None)
FSTRING_END = getattr(tokenize, "FSTRING_END", None)
LITERAL_START = re.compile(r"([A-Za-z]*)('''|\"\"\"|'|\")")
ESCAPE_START = "\n\\'\"abfnrtv01234567xuUN"
HEX_DIGITS = {"x": 2, "u": 4, "U": 8}
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)


@dataclass(eq=False)
class Piece:
    path: str
    language: str
    text: str
    line_of: object
    tree: object = None
    unit: ir.Unit = None
    comments: list = field(default_factory=list)
    strings: list = field(default_factory=list)
    code_lines: dict = field(default_factory=dict)
    shell: str = None
    problem: str = None
    test_lines: set = field(default_factory=set)
    pins: set = field(default_factory=set)
    continue_on_error: list = field(default_factory=list)
    run_line: int = None
    line_for: object = None


def offsets_line_of(source, offsets, fallback):
    def line_of(k):
        if not offsets:
            return fallback
        k = min(max(k, 0), len(offsets) - 1)
        return source.line(offsets[k])
    return line_of


def powershell_piece(path, text, line_of, shell=None):
    piece = Piece(path, "powershell", text, line_of, shell=shell)
    try:
        script = ps.parse(text, path)
    except SyntaxProblem as ex:
        piece.problem = f"{path}:{line_of(ex.offset)}: the PowerShell reader stops here: {ex.message}"
        return piece
    piece.tree = script
    for c in script.comments:
        first, last = line_of(c.span.start), line_of(max(c.span.start, c.span.end - 1))
        piece.comments.append((first, last, c.text, c.block))
    for start, end, kind in script.tokens:
        if kind not in ("comment", "continuation"):
            at = start
            for chunk in text[start:end].split("\n"):
                if chunk:
                    line = line_of(at)
                    piece.code_lines[line] = piece.code_lines.get(line, "") + chunk + " "
                at += len(chunk) + 1
    for node in ps.walk(script):
        if isinstance(node, ps.String):
            piece.strings.append((line_of(node.span.start), node.value))
    piece.unit = ir.powershell_unit(script, line_of)
    return piece


def python_piece(path, text, line_of=None, language="python", tokens=True):
    line_of = line_of or (lambda n: n)
    piece = Piece(path, language, text, line_of)
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline)) if tokens else []
    except (SyntaxError, tokenize.TokenError, IndentationError, ValueError) as ex:
        piece.problem = f"{path}:{line_of(getattr(ex, 'lineno', 1) or 1)}: the Python reader stops here: {ex}"
        return piece
    piece.tree = tree
    piece.line_for = line_of
    for t in tokens:
        if t.type == tokenize.COMMENT:
            line = line_of(t.start[0])
            piece.comments.append((line, line, t.string[1:], False))
        elif t.type not in SILENT_TOKENS:
            for k, chunk in enumerate(t.string.split("\n")):
                if chunk:
                    line = line_of(t.start[0] + k)
                    piece.code_lines[line] = piece.code_lines.get(line, "") + chunk + " "
    piece.unit = ir.python_unit(tree, line_of)
    return piece


def string_parts(tokens, text, start, end):
    starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]

    def offset(position):
        return starts[position[0] - 1] + position[1]
    out = []
    k = 0
    while k < len(tokens):
        t = tokens[k]
        if t.start < start or t.end > end:
            k += 1
            continue
        if t.type == tokenize.STRING:
            out.append((t.start[0], t.string))
            k += 1
        elif FSTRING_START is not None and t.type == FSTRING_START:
            depth, j = 0, k
            while j < len(tokens):
                if tokens[j].type == FSTRING_START:
                    depth += 1
                elif tokens[j].type == FSTRING_END:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append((t.start[0], text[offset(t.start):offset(tokens[j].end)]))
            k = j + 1
        else:
            k += 1
    return out


@dataclass(frozen=True)
class Field:
    spec: bool


def escape_end(raw, i):
    c = raw[i + 1]
    if c in "01234567":
        j = i + 2
        while j < i + 4 and raw[j] in "01234567":
            j += 1
        return j
    if c in HEX_DIGITS:
        return i + 2 + HEX_DIGITS[c]
    if c == "N":
        return raw.index("}", i) + 1
    return i + 2


def field_end(raw, i):
    depth, spec = 0, False
    while True:
        c = raw[i]
        if c in "'\"" and not spec:
            quote = raw[i:i + 3] if raw[i:i + 3] in ("'''", '"""') else c
            i += len(quote)
            while raw[i:i + len(quote)] != quote:
                i += 2 if raw[i] == "\\" else 1
            i += len(quote)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i, spec
            depth -= 1
        elif c == ":" and depth == 0:
            spec = True
        i += 1


def literal_chars(raw, line):
    m = LITERAL_START.match(raw)
    prefix = m.group(1).lower()
    if "b" in prefix:
        return None
    rows, row = [], line
    for c in raw:
        rows.append(row)
        row += c == "\n"
    out, i, end = [], m.end(), len(raw) - len(m.group(2))
    while i < end:
        c = raw[i]
        if c == "\\" and "r" not in prefix and raw[i + 1] in ESCAPE_START:
            j = escape_end(raw, i)
            out += [(d, rows[i]) for d in ast.literal_eval(f'"{raw[i:j]}"')]
            i = j
        elif c in "{}" and "f" in prefix:
            if raw[i + 1:i + 2] == c:
                out.append((c, rows[i]))
                i += 2
            else:
                j, spec = field_end(raw, i + 1)
                out.append((Field(spec), rows[i]))
                i = j + 1
        else:
            out.append((c, rows[i]))
            i += 1
    return out


def placeholder(before, spec):
    tail = before.rstrip(" \t")
    if spec or (tail and tail[-1] in "(,=+-*/%[<>"):
        return "1"
    return "x"


def char_column(physical, lineno, byte_column):
    line = physical[lineno - 1] if 0 < lineno <= len(physical) else ""
    return len(line.encode("utf-8")[:byte_column].decode("utf-8", errors="ignore"))


def powershell_script(tokens, source_text, expression):
    physical = source_text.split("\n")
    start = (expression.lineno, char_column(physical, expression.lineno, expression.col_offset))
    end = (expression.end_lineno, char_column(physical, expression.end_lineno, expression.end_col_offset))

    text, lines = [], []
    for line, raw in string_parts(tokens, source_text, start, end):
        chars = literal_chars(raw, line)
        if chars is None:
            return None
        for item, row in chars:
            chunk = placeholder("".join(text), item.spec) if isinstance(item, Field) else item
            text += chunk
            lines += [row] * len(chunk)
    if not text:
        return None
    return "".join(text), lines


def names_powershell(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and POWERSHELL_NAME.search(n.id):
            return True
        if isinstance(n, ast.Attribute) and POWERSHELL_NAME.search(n.attr):
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and POWERSHELL_NAME.search(n.value):
            return True
    return False


def position(node):
    return node.lineno, node.col_offset


def end_position(node):
    return node.end_lineno, node.end_col_offset


class Assignments:
    def __init__(self, tree):
        self.scope_of, self.bindings = {}, {}
        self.visit(tree, tree)

    def bind(self, scope, name, at, value):
        self.bindings.setdefault((id(scope), name), []).append((at, value))

    def visit(self, node, scope):
        for child in ast.iter_child_nodes(node):
            self.scope_of[id(child)] = scope
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
                plain = isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and targets == [child]
                at = end_position(node) if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) else \
                    position(child)
                self.bind(scope, child.id, at, node.value if plain else None)
            elif isinstance(child, ast.arg):
                self.bind(scope, child.arg, (0, 0), None)
            self.visit(child, child if isinstance(child, SCOPES) else scope)

    def value(self, expression, depth=0):
        if isinstance(expression, (ast.Constant, ast.JoinedStr)) or joined(expression):
            return expression
        if not isinstance(expression, ast.Name) or depth >= 5:
            return None
        scope, outer = self.scope_of.get(id(expression)), False
        while scope is not None:
            bound = None if outer and isinstance(scope, ast.ClassDef) else self.bindings.get((id(scope), expression.id))
            if bound:
                earlier = [b for b in bound if b[0] <= position(expression)]
                chosen = max(earlier, key=lambda b: b[0]) if earlier else bound[0] if outer and len(bound) == 1 else None
                return self.value(chosen[1], depth + 1) if chosen and chosen[1] is not None else None
            scope, outer = self.scope_of.get(id(scope)), True
        return None


def joined(expression):
    f = expression.func if isinstance(expression, ast.Call) else None
    return (isinstance(f, ast.Attribute) and f.attr == "join" and isinstance(f.value, ast.Constant)
            and isinstance(f.value.value, str) and len(expression.args) == 1
            and isinstance(expression.args[0], (ast.List, ast.Tuple)))


def joined_script(tokens, source_text, expression, names):
    separator, text, lines = expression.func.value.value, "", []
    for k, element in enumerate(expression.args[0].elts):
        value = names.value(element)
        if isinstance(value, ast.Constant) and value.value == "":
            built = ("", [])
        elif isinstance(value, (ast.Constant, ast.JoinedStr)):
            built = powershell_script(tokens, source_text, value)
        else:
            chunk = placeholder(text, False)
            built = (chunk, [element.lineno] * len(chunk))
        if built is None:
            return None
        if k:
            text, lines = text + separator, lines + [element.lineno] * len(separator)
        text, lines = text + built[0], lines + built[1]
    return (text, lines) if text else None


def command_lists(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elements = node.elts
            for k, e in enumerate(elements):
                if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.lower() in COMMAND_FLAGS and \
                        k + 1 < len(elements) and any(names_powershell(x) for x in elements[:k]):
                    yield node, elements[k + 1]


def embedded_powershell(path, tree, text, file_line=None):
    found = list(command_lists(tree))
    if not found:
        return []
    file_line = file_line or (lambda n: n)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    names = Assignments(tree)
    pieces, seen = [], set()
    for _, script_node in found:
        target = names.value(script_node)
        if target is not None and id(target) in seen:
            continue
        if target is None:
            built = None
        elif joined(target):
            built = joined_script(tokens, text, target, names)
        else:
            built = powershell_script(tokens, text, target)
        if built is None:
            line = file_line(script_node.lineno)
            pieces.append(Piece(path, "powershell", "", lambda _, line=line: line, problem=f"{path}:{line}: the "
                                f"PowerShell reader can't follow the script that Python passes after -Command"))
            continue
        seen.add(id(target))
        script, lines = built

        def line_of(offset, lines=lines):
            return file_line(lines[min(max(offset, 0), len(lines) - 1)])
        pieces.append(powershell_piece(path, script, line_of, shell="powershell"))
    return pieces


def shell_of(step, job_default):
    shell = yaml.scalar_text(step.node("shell"))
    return (shell or job_default or "bash").strip()


def language_of(shell):
    s = shell.lower()
    if s.startswith("python"):
        return "python"
    if "pwsh" in s or "powershell" in s:
        return "powershell"
    if s.startswith("cmd"):
        return "cmd"
    if s.startswith(("bash", "sh")):
        return "bash"
    return "unknown"


def job_default_shell(job, workflow_default):
    if not isinstance(job, yaml.Mapping):
        return workflow_default
    defaults = job.node("defaults")
    run = defaults.node("run") if isinstance(defaults, yaml.Mapping) else None
    shell = yaml.scalar_text(run.node("shell")) if isinstance(run, yaml.Mapping) else None
    if shell:
        return shell
    runs_on = job.node("runs-on")
    texts = [yaml.scalar_text(x) for x in (runs_on.items if isinstance(runs_on, yaml.Sequence) else [runs_on])]
    if any(t and "windows" in t for t in texts):
        return workflow_default or "pwsh"
    return workflow_default or None


def sequence_items(node):
    node = yaml.resolved(node)
    return node.items if isinstance(node, yaml.Sequence) else []


def mapping_value(node, key):
    node = yaml.resolved(node)
    return node.node(key) if isinstance(node, yaml.Mapping) else None


def steps_with_shells(root):
    run = mapping_value(mapping_value(root, "defaults"), "run")
    workflow_default = yaml.scalar_text(mapping_value(run, "shell"))
    jobs = yaml.resolved(mapping_value(root, "jobs"))
    groups = [(job, job_default_shell(yaml.resolved(job), workflow_default))
              for _, job in (jobs.pairs if isinstance(jobs, yaml.Mapping) else [])]
    groups.append((mapping_value(root, "runs"), workflow_default))
    found = []
    for owner, default in groups:
        for item in sequence_items(mapping_value(owner, "steps")):
            step = yaml.resolved(item)
            if isinstance(yaml.resolved(mapping_value(step, "run")), yaml.Scalar):
                found.append((item, step, default))
    return found


def without_expressions(value, offsets):
    text, kept, at = [], [], 0
    for m in EXPRESSION.finditer(value):
        text.append(value[at:m.start()])
        kept += offsets[at:m.start()]
        chunk = placeholder("".join(text), False)
        text.append(chunk)
        kept += [offsets[m.start()]] * len(chunk)
        at = m.end()
    text.append(value[at:])
    kept += offsets[at:]
    return "".join(text), kept


def lines_of_test_jobs(source, root, test_job):
    lines = set()
    jobs = root.node("jobs") if isinstance(root, yaml.Mapping) else None
    if isinstance(jobs, yaml.Mapping):
        for key, job in jobs.pairs:
            name = yaml.scalar_text(key)
            if name and test_job.match(name):
                lines |= set(source.lines_of(key.span.start, max(job.span.end, key.span.end)))
    return lines


def yaml_pieces(path, text, test_job):
    source = Source(text, path)
    piece = Piece(path, "yaml", text, source.line)
    try:
        stream = yaml.parse(source)
    except SyntaxProblem as ex:
        piece.problem = f"{path}:{source.line(ex.offset)}: the YAML reader stops here: {ex.message}"
        return [piece]
    piece.tree = stream
    cut = {}
    for c in stream.comments:
        line = source.line(c.span.start)
        piece.comments.append((line, line, c.text, False))
        cut[line] = source.column(c.span.start) - 1
    pieces = [piece]
    bodies = set()
    for document in stream.documents:
        root = document.root
        for node in yaml.walk(root):
            if isinstance(node, yaml.Mapping):
                for key, value in node.pairs:
                    k = yaml.scalar_text(key)
                    v = yaml.scalar_text(value)
                    if k == "uses" and v and PIN.search(v):
                        piece.pins.add(source.line(value.span.start))
                    if k == "continue-on-error" and not (v is not None and v.strip().lower() == "false"):
                        piece.continue_on_error.append(source.line(key.span.start))
        piece.test_lines |= lines_of_test_jobs(source, root, test_job)
        for item, step, default in steps_with_shells(root):
            written = step.node("run")
            run = yaml.resolved(written)
            used = next((n for n in (item, written) if isinstance(n, yaml.Alias)), None)
            if used is None:
                bodies |= set(source.lines_of(run.span.start, run.span.end)) - {source.line(run.span.start)}
            shell = shell_of(step, default)
            language = language_of(shell)
            value, offsets = run.value, run.offsets
            if language in ("powershell", "python"):
                value, offsets = without_expressions(value, offsets)
            if used is not None:
                def line_of(_, line=source.line(used.span.start)):
                    return line
            else:
                line_of = offsets_line_of(source, offsets, source.line(run.span.start))
            if language == "powershell":
                inner = [powershell_piece(path, value, line_of, shell=shell)]
            elif language == "python":
                inner = python_embedded(path, value, line_of)
            else:
                inner = [Piece(path, language, value, line_of, shell=shell)]
            inner[0].shell = shell
            for p in inner:
                p.run_line = source.line((used or run).span.start)
                p.test_lines = piece.test_lines
            pieces += inner
    for n, raw in enumerate(text.split("\n"), 1):
        if n not in bodies:
            code = raw[:cut[n]] if n in cut else raw
            if code.strip():
                piece.code_lines[n] = code
    return pieces


def python_embedded(path, text, line_of):
    starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]

    def by_line(n):
        return line_of(starts[min(max(n - 1, 0), len(starts) - 1)])
    piece = python_piece(path, text, by_line)
    piece.line_of = line_of
    if piece.tree is None:
        return [piece]
    return [piece, *embedded_powershell(path, piece.tree, text, by_line)]


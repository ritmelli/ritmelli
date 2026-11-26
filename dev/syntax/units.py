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
            for line in {line_of(start), line_of(max(start, end - 1))}:
                piece.code_lines[line] = piece.code_lines.get(line, "") + text[start:end] + " "
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
            for line in {line_of(t.start[0]), line_of(t.end[0])}:
                piece.code_lines[line] = piece.code_lines.get(line, "") + t.string + " "
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


def decoded_parts(raw):
    try:
        node = ast.parse(raw.strip(), mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value)
            else:
                parts.append(v)
        return parts
    return None


def placeholder(before, value):
    tail = before.rstrip(" \t")
    if getattr(value, "format_spec", None) is not None or (tail and tail[-1] in "(,=+-*/%[<>"):
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
        parts = decoded_parts(raw)
        if parts is None:
            return None
        for part in parts:
            chunk = part if isinstance(part, str) else placeholder("".join(text), part)
            row = line
            for c in chunk:
                text.append(c)
                lines.append(row)
                if c == "\n":
                    row += 1
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


def assignments(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, []).append(node)
    return out


def resolve(expression, assigned, before_line, depth=0):
    if isinstance(expression, ast.Name) and depth < 5:
        earlier = [a for a in assigned.get(expression.id, []) if a.lineno < before_line]
        if earlier:
            last = max(earlier, key=lambda a: a.lineno)
            return resolve(last.value, assigned, last.lineno, depth + 1)
        return None
    if isinstance(expression, (ast.Constant, ast.JoinedStr)):
        return expression
    return None


def command_lists(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elements = node.elts
            for k, e in enumerate(elements):
                if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.lower() in COMMAND_FLAGS and \
                        k + 1 < len(elements) and any(names_powershell(x) for x in elements[:k]):
                    yield node, elements[k + 1]


def embedded_powershell(path, tree, text):
    found = list(command_lists(tree))
    if not found:
        return []
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    assigned = assignments(tree)
    pieces, seen = [], set()
    for node, script_node in found:
        target = resolve(script_node, assigned, node.lineno)
        built = powershell_script(tokens, text, target) if target is not None and id(target) not in seen else None
        if built is None:
            continue
        seen.add(id(target))
        script, lines = built

        def line_of(offset, lines=lines):
            return lines[min(max(offset, 0), len(lines) - 1)]
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


def steps_with_shells(root):
    found = []
    workflow_default = None
    if isinstance(root, yaml.Mapping):
        defaults = root.node("defaults")
        run = defaults.node("run") if isinstance(defaults, yaml.Mapping) else None
        workflow_default = yaml.scalar_text(run.node("shell")) if isinstance(run, yaml.Mapping) else None
    jobs = root.node("jobs") if isinstance(root, yaml.Mapping) else None
    claimed = set()
    if isinstance(jobs, yaml.Mapping):
        for _, job in jobs.pairs:
            default = job_default_shell(job, workflow_default)
            for node in yaml.walk(job):
                if isinstance(node, yaml.Mapping) and isinstance(node.node("run"), yaml.Scalar):
                    found.append((node, default))
                    claimed.add(id(node))
    for node in yaml.walk(root):
        if isinstance(node, yaml.Mapping) and isinstance(node.node("run"), yaml.Scalar) and id(node) not in claimed:
            found.append((node, workflow_default))
    return found


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
        for step, default in steps_with_shells(root):
            run = step.node("run")
            if run.style in ("literal", "folded"):
                bodies |= set(source.lines_of(run.span.start, run.span.end)) - {source.line(run.span.start)}
            shell = shell_of(step, default)
            language = language_of(shell)
            line_of = offsets_line_of(source, run.offsets, source.line(run.span.start))
            if language == "powershell":
                inner = powershell_piece(path, run.value, line_of, shell=shell)
            elif language == "python":
                inner = python_embedded(path, run.value, line_of)
            else:
                inner = Piece(path, language, run.value, line_of, shell=shell)
            inner.shell = shell
            inner.run_line = source.line(run.span.start)
            inner.test_lines = piece.test_lines
            pieces.append(inner)
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
    return piece

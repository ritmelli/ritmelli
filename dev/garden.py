import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import workflow_yaml

CEILINGS = ROOT / "dev" / "garden.json"
USAGE = """The garden scoreboard: counts the weeds of the repo and holds each count to its ceiling in dev/garden.json.

    python dev/garden.py                   the counts against dev/garden.json and the base ($env:BASE)
    python dev/garden.py --list NAME       every item a counter counts, with its place
    python dev/garden.py --pr-description  the description of the PR of this run, read from the API

A count over its ceiling fails (weeds went in); under it, it fails too until the PR lowers the ceiling to the count.
A ceiling over the base's fails as well, so a PR can't raise it along with the weeds. Every counter that changed
against the base goes to the PR summary as a "-- summary:" line."""

COMMENT_EXTENSIONS = (".py", ".js", ".css", ".ps1", ".yml", ".cpp", ".h", ".iss", ".bat", ".html", ".rc", ".spec",
                      ".sh", ".toml", ".psd1", ".isl")
GARDEN_FILES = ("dev/garden.py", "dev/test_garden.py")
ISSUE = re.compile(r"#\d+\b|/issues/\d+\b")
BLOCK_MARKER = re.compile(r"^\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b")
KEPT_COMMENT = re.compile(r"^\s*(?:inline-script:|manual:|i18n-ok\b)")
ENCODING = re.compile(r"coding[:=]\s*[-\w.]+")
PIN = re.compile(r"@[0-9a-f]{40}\s*$")
PIN_VERSION = re.compile(r"^\s*v\d+(?:\.\d+)*\s*$")
SUPPRESSIONS_IN_COMMENTS = re.compile(r"\bnoqa\b|\btype:\s*ignore\b|\beslint-disable|\bpragma:\s*no\s*cover\b")
PRAGMA_DISABLE = re.compile(r"#\s*pragma\s+warning\s*\(\s*disable")
CONTINUE_ON_ERROR = re.compile(r"^\s*(?:-\s+)?continue-on-error\s*:")
SILENTLY_CONTINUE = re.compile(r"-ErrorAction\s+SilentlyContinue\b", re.I)
START_SLEEP = re.compile(r"\bStart-Sleep\b", re.I)
THEME_TIMER = re.compile(r"\b(?:setTimeout|setInterval|requestIdleCallback)\s*\(")
ANIMATION_FRAME = re.compile(r"\brequestAnimationFrame\s*\(")
TODO = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b")
PROSE = re.compile(r"risco aceito|accepted risk|sem prova|por enquanto|for now|known issue|sem teste|have no test yet"
                   r"|como antes", re.I)
LEFT_OUT = "ficou de fora"
SKIP_NAMES = {"skip", "skipIf", "skipUnless", "expectedFailure", "skipTest", "SkipTest", "xfail", "skipif"}
BROAD = {"Exception", "BaseException"}
SLEEP_MODULES = {"time", "asyncio"}
PS_LOOP = re.compile(r"\b(?:for|foreach|while|do)\b\s*(?:\([^{]*\))?\s*\{", re.I)
PROOF_LABEL = re.compile(r"^(?:how it was (?:proven|proved|tested)|proof\b|prova\b|como foi provado)", re.I)
PROOF_CONTENT = re.compile(r"`[^`]+`|https?://|!\[")
BIG_FILES = {"engine_py_lines": "engine.py", "server_py_lines": "server.py",
             "index_html_lines": "themes/ritmelli/index.html", "agents_md_lines": "AGENTS.md"}


@dataclass
class Comment:
    start: int
    end: int
    text: str


@dataclass
class Lexed:
    code: dict = field(default_factory=dict)
    comments: list = field(default_factory=list)
    strings: list = field(default_factory=list)

    def add_code(self, line, text):
        self.code[line] = self.code.get(line, "") + text


def lex_python(text):
    out = Lexed()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return lex_hash(text)
    lines = text.splitlines()
    comment_cols = {}
    for t in tokens:
        if t.type == tokenize.COMMENT:
            out.comments.append(Comment(t.start[0], t.start[0], t.string[1:]))
            comment_cols[t.start[0]] = t.start[1]
    for n, line in enumerate(lines, 1):
        out.code[n] = line[:comment_cols[n]] if n in comment_cols else line
    return out


def lex_hash(text, strings="\"'"):
    out = Lexed()
    for n, line in enumerate(text.splitlines(), 1):
        quote, i = None, 0
        while i < len(line):
            c = line[i]
            if quote:
                if c == "\\" and quote == '"':
                    i += 1
                elif c == quote:
                    quote = None
            elif c in strings:
                quote = c
            elif c == "#" and (i == 0 or line[i - 1] in " \t;|&(){}"):
                out.comments.append(Comment(n, n, line[i + 1:]))
                line = line[:i]
                break
            i += 1
        out.code[n] = line
    return out


class Scanner:
    def __init__(self, text):
        self.text, self.i, self.line = text, 0, 1
        self.out = Lexed()

    def peek(self, s):
        return self.text.startswith(s, self.i)

    def take(self, n, into=None):
        chunk = self.text[self.i:self.i + n]
        for c in chunk:
            if c == "\n":
                self.line += 1
            elif into is None:
                self.out.add_code(self.line, c)
            else:
                into.append((self.line, c))
        self.i += n
        return chunk

    def comment_until(self, end, keep_end=False):
        start, parts = self.line, []
        stop = self.text.find(end, self.i) if end != "\n" else self.text.find("\n", self.i)
        stop = len(self.text) if stop < 0 else stop
        body = self.text[self.i:stop]
        parts.append(body)
        for c in body:
            if c == "\n":
                self.line += 1
        self.i = stop + (len(end) if end != "\n" and stop < len(self.text) else 0)
        self.out.comments.append(Comment(start, self.line, "".join(parts)))
        self.out.code.setdefault(start, self.out.code.get(start, ""))

    def string(self, quote, escape="\\", doubled=False):
        start, line = self.i, self.line
        self._string(quote, escape, doubled)
        for k, part in enumerate(self.text[start:self.i].split("\n")):
            self.out.strings.append((line + k, part))

    def _string(self, quote, escape, doubled):
        self.take(1)
        while self.i < len(self.text):
            c = self.text[self.i]
            if escape and c == escape:
                self.take(2)
            elif c == quote and doubled and self.peek(quote * 2):
                self.take(2)
            elif c == quote:
                self.take(1)
                return
            elif c == "\n" and quote != "`" and not doubled:
                return
            else:
                self.take(1)


def lex_c(text, js=False, css=False, pascal=False):
    s = Scanner(text)
    last = ""
    while s.i < len(text):
        c = text[s.i]
        if not css and not pascal and s.peek("//"):
            s.i += 2
            s.comment_until("\n")
        elif pascal and s.peek("//"):
            s.i += 2
            s.comment_until("\n")
        elif not pascal and s.peek("/*"):
            s.i += 2
            s.comment_until("*/")
        elif pascal and s.peek("(*"):
            s.i += 2
            s.comment_until("*)")
        elif pascal and c == "{":
            s.i += 1
            s.comment_until("}")
        elif pascal and c == "'":
            s.string("'", escape=None, doubled=True)
            last = "'"
        elif not pascal and c in "\"'" or (js and c == "`"):
            s.string(c)
            last = c
        elif js and c == "/" and regex_can_start(s.out.code.get(s.line, ""), last):
            s.take(1)
            in_class = False
            while s.i < len(text) and text[s.i] != "\n":
                ch = text[s.i]
                if ch == "\\":
                    s.take(2)
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    s.take(1)
                    break
                s.take(1)
            last = "/"
        else:
            if not c.isspace():
                last = c
            s.take(1)
    return s.out


JS_KEYWORDS_BEFORE_REGEX = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                            "yield", "await"}


def regex_can_start(code_line, last):
    if not last or last in "(,=:[!&|?{};+-*%<>~^":
        return True
    word = re.search(r"([A-Za-z_$][\w$]*)\s*$", code_line)
    return bool(word) and word.group(1) in JS_KEYWORDS_BEFORE_REGEX and code_line.rstrip().endswith(word.group(1))


def lex_powershell(text):
    s = Scanner(text)
    while s.i < len(text):
        c = text[s.i]
        if s.peek("<#"):
            s.i += 2
            s.comment_until("#>")
        elif c == "#" and (s.i == 0 or text[s.i - 1] in " \t\n;|{}()"):
            s.i += 1
            s.comment_until("\n")
        elif s.peek("@'\n") or s.peek("@'\r\n") or s.peek('@"\n') or s.peek('@"\r\n'):
            close = "\n" + text[s.i + 1] + "@"
            stop = text.find(close, s.i + 2)
            stop = len(text) if stop < 0 else stop + len(close)
            s.take(stop - s.i)
        elif c == "'":
            s.string("'", escape=None, doubled=True)
        elif c == '"':
            s.string('"', escape="`")
        else:
            s.take(1)
    return s.out


def lex_bat(text):
    out = Lexed()
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(?:@?rem(?:\s|$)|::)(.*)$", line, re.I)
        if m:
            out.comments.append(Comment(n, n, m.group(1)))
            out.code[n] = ""
        else:
            out.code[n] = line
    return out


def lex_semicolon(text):
    out = Lexed()
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(";") or stripped.startswith("//"):
            out.comments.append(Comment(n, n, stripped.lstrip(";/")))
            out.code[n] = ""
        else:
            out.code[n] = line
    return out


def shift(lexed, offset, into):
    for n, code in lexed.code.items():
        into.add_code(n + offset, code)
    into.comments += [Comment(c.start + offset, c.end + offset, c.text) for c in lexed.comments]
    into.strings += [(n + offset, text) for n, text in lexed.strings]


def lex_iss(text):
    out = Lexed()
    lines = text.splitlines()
    code_at = next((i for i, line in enumerate(lines) if line.strip().lower() == "[code]"), len(lines))
    shift(lex_semicolon("\n".join(lines[:code_at + 1])), 0, out)
    if code_at < len(lines):
        shift(lex_c("\n".join(lines[code_at + 1:]), pascal=True), code_at + 1, out)
    return out


def lex_html(text):
    out = Lexed()
    for m in re.finditer(r"<!--(.*?)-->", text, re.S):
        start = text.count("\n", 0, m.start()) + 1
        out.comments.append(Comment(start, start + m.group(0).count("\n"), m.group(1)))
    for m in re.finditer(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", text, re.S | re.I):
        offset = text.count("\n", 0, m.start(2))
        body = m.group(2)
        lexed = lex_c(body, js=m.group(1).lower() == "script", css=m.group(1).lower() == "style")
        shift(lexed, offset, out)
    for n, line in enumerate(text.splitlines(), 1):
        out.code.setdefault(n, line)
    return out


BLOCK_SCALAR = re.compile(r"^(\s*)(-\s+)?([\w.-]+):\s*[|>][-+]?\s*$")


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def key_indent(line):
    stripped = line.lstrip(" ")
    return indent_of(line) + (len(stripped) - len(stripped[1:].lstrip(" ")) if stripped.startswith("-") else 0)


def yaml_shell(lines, at):
    indent = key_indent(lines[at])
    start = at
    while start > 0 and not (lines[start].lstrip(" ").startswith("-") and key_indent(lines[start]) == indent):
        start -= 1
    for k in range(start, len(lines)):
        line = lines[k]
        if k > start and line.strip() and (indent_of(line) < indent or lines[k].lstrip(" ").startswith("-")
                                           and indent_of(line) <= indent - 2):
            break
        m = re.match(r"^\s*(?:-\s+)?shell:\s*(.+?)\s*$", line)
        if m and key_indent(line) == indent:
            return m.group(1)
    runs_on = next((m.group(1) for line in reversed(lines[:at]) if (m := re.match(r"^\s+runs-on:\s*(.+)$", line))),
                   "")
    return "pwsh" if "windows" in runs_on else "bash"


def lexer_for_shell(shell):
    if shell.startswith("python"):
        return lex_python
    if "pwsh" in shell or "powershell" in shell:
        return lex_powershell
    return lex_bat if shell.startswith("cmd") else lex_hash


def lex_yaml(text):
    out = Lexed()
    lines = text.splitlines()
    n = 0
    while n < len(lines):
        line = lines[n]
        m = BLOCK_SCALAR.match(line)
        lexed = lex_hash(line)
        out.code[n + 1] = lexed.code.get(1, line)
        out.comments += [Comment(n + 1, n + 1, c.text) for c in lexed.comments]
        n += 1
        if not m:
            continue
        end = n
        while end < len(lines) and (not lines[end].strip() or indent_of(lines[end]) > indent_of(line)):
            end += 1
        body = lines[n:end]
        if m.group(3) == "run":
            indent = min((indent_of(b) for b in body if b.strip()), default=0)
            script = "\n".join(b[indent:] for b in body)
            shift(lexer_for_shell(yaml_shell(lines, n - 1))(script), n, out)
        else:
            for k, b in enumerate(body, n + 1):
                out.code[k] = b
        n = end
    return out


LEXERS = {".py": lex_python, ".spec": lex_python, ".js": lambda t: lex_c(t, js=True), ".css": lambda t: lex_c(t, css=True),
          ".cpp": lex_c, ".h": lex_c, ".rc": lex_c, ".ps1": lex_powershell, ".psd1": lex_powershell, ".yml": lex_yaml,
          ".iss": lex_iss, ".isl": lex_semicolon, ".bat": lex_bat, ".html": lex_html, ".sh": lex_hash,
          ".toml": lex_hash}


def suffix(path):
    return Path(path).suffix.lower()


def kept(path, lexed, comment):
    text = comment.text
    if BLOCK_MARKER.match(text) or KEPT_COMMENT.match(text):
        return True
    if comment.start == 1 and suffix(path) in (".py", ".sh", ".spec") and text.startswith("!"):
        return True
    if comment.start <= 2 and suffix(path) in (".py", ".spec") and ENCODING.search(text):
        return True
    return suffix(path) == ".yml" and bool(PIN.search(lexed.code.get(comment.start, "").rstrip())) and bool(
        PIN_VERSION.match(text))


class Tree:
    def __init__(self, files):
        self.files = files
        self._lexed, self._ast = {}, {}

    def lexed(self, path):
        if path not in self._lexed:
            self._lexed[path] = LEXERS[suffix(path)](self.files[path])
        return self._lexed[path]

    def tree(self, path):
        if path not in self._ast:
            try:
                self._ast[path] = ast.parse(self.files[path])
            except SyntaxError:
                self._ast[path] = None
        return self._ast[path]

    def paths(self, *suffixes):
        return sorted(p for p in self.files if suffix(p) in suffixes)


def comment_lines(t):
    items = []
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        lines = set()
        for c in lexed.comments:
            if not kept(p, lexed, c):
                lines |= set(range(c.start, c.end + 1))
        items += [(p, n) for n in sorted(lines)]
    return items


def docstrings(tree):
    for node in [tree, *ast.walk(tree)]:
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(
                    first.value.value, str):
                yield first


def docstring_lines(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            lines = set()
            for d in docstrings(tree):
                lines |= set(range(d.lineno, d.end_lineno + 1))
            items += [(p, n) for n in sorted(lines)]
    return items


def python_strings(t, path):
    tree = t.tree(path)
    if tree is None or path in GARDEN_FILES:
        return []
    out = []
    inside_f_strings = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside_f_strings:
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            out.append((node.lineno, "".join(v.value for v in node.values if isinstance(v, ast.Constant))))
    return out


def code_lines(t, path):
    if suffix(path) in (".py", ".spec"):
        return python_strings(t, path)
    return sorted(t.lexed(path).code.items())


def suppressions(t):
    items = []
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        items += [(p, c.start) for c in lexed.comments if SUPPRESSIONS_IN_COMMENTS.search(c.text)]
        for n, code in code_lines(t, p):
            hits = len(PRAGMA_DISABLE.findall(code)) + len(SILENTLY_CONTINUE.findall(code))
            if suffix(p) == ".yml" and CONTINUE_ON_ERROR.match(code):
                hits += 1
            items += [(p, n)] * hits
    return items


def sleep_aliases(tree):
    modules, functions = set(SLEEP_MODULES), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname for a in node.names if a.name in SLEEP_MODULES and a.asname}
        elif isinstance(node, ast.ImportFrom) and node.module in SLEEP_MODULES:
            functions |= {a.asname or a.name for a in node.names if a.name == "sleep"}
    return modules, functions


def is_sleep(node, aliases):
    modules, functions = aliases
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr == "sleep" and isinstance(f.value, ast.Name)
            and f.value.id in modules) or (isinstance(f, ast.Name) and f.id in functions)


def is_dev(path):
    name = Path(path).name
    return path.startswith(("dev/", ".github/")) or name.startswith(("testa", "test_", "teste_"))


def sleeps(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            aliases = sleep_aliases(tree)
            items += [(p, n.lineno) for n in ast.walk(tree) if is_sleep(n, aliases)]
    for p in t.paths(*COMMENT_EXTENSIONS):
        for n, code in code_lines(t, p):
            items += [(p, n)] * len(START_SLEEP.findall(code))
    return items


def sleeps_app(t):
    return [i for i in sleeps(t) if not is_dev(i[0])]


def sleeps_dev(t):
    return [i for i in sleeps(t) if is_dev(i[0])]


def theme_code(t, pattern):
    items = []
    for p in t.paths(".js", ".html"):
        if p.startswith("themes/"):
            lexed = t.lexed(p)
            in_strings = {}
            for n, text in lexed.strings:
                in_strings[n] = in_strings.get(n, 0) + len(pattern.findall(text))
            for n, code in sorted(lexed.code.items()):
                items += [(p, n)] * (len(pattern.findall(code)) - in_strings.get(n, 0))
    return items


def theme_timers(t):
    return theme_code(t, THEME_TIMER)


def theme_animation_frames(t):
    return theme_code(t, ANIMATION_FRAME)


LOOPS = (ast.For, ast.AsyncFor, ast.While)


def local_nodes(node):
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, *LOOPS)):
            yield child
            yield from local_nodes(child)


def leaves(body):
    last = body[-1] if body else None
    return isinstance(last, (ast.Return, ast.Raise, ast.Break))


def python_retries(tree):
    aliases = sleep_aliases(tree)
    found = []
    for loop in ast.walk(tree):
        if isinstance(loop, LOOPS):
            inner = list(local_nodes(loop))
            handlers = [h for n in inner if isinstance(n, ast.Try) for h in n.handlers]
            if any(is_sleep(n, aliases) for n in inner) and any(not leaves(h.body) for h in handlers):
                found.append(loop.lineno)
    return found


def braces(code, start):
    depth = 0
    for i in range(start, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[start:i + 1]
    return code[start:]


def powershell_retries(code):
    found = []
    for m in PS_LOOP.finditer(code):
        body = braces(code, m.end() - 1)
        if re.search(r"\btry\s*\{", body, re.I) and START_SLEEP.search(body):
            found.append(code.count("\n", 0, m.start()) + 1)
    return found


def joined_code(lexed):
    lines = lexed.code
    return "\n".join(lines.get(n, "") for n in range(1, max(lines, default=0) + 1))


def retries(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            items += [(p, n) for n in python_retries(tree)]
            items += [(p, n) for n, s in python_strings(t, p) if START_SLEEP.search(s) and powershell_retries(s)]
    for p in t.paths(".ps1", ".psd1", ".yml"):
        items += [(p, n) for n in powershell_retries(joined_code(t.lexed(p)))]
    return items


def is_broad(node):
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in BROAD
    if isinstance(node, ast.Attribute):
        return node.attr in BROAD
    if isinstance(node, ast.Tuple):
        return any(is_broad(e) for e in node.elts)
    return False


def broad_handlers(tree):
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and is_broad(n.type)]


def workflow_python(t, path):
    try:
        doc = workflow_yaml.loads(t.files[path], name=path)
    except workflow_yaml.YamlError:
        return []
    out = []
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    steps = [s for job in (jobs or {}).values() if isinstance(job, dict) for s in workflow_yaml.job_steps(job)]
    if isinstance(doc, dict) and isinstance(doc.get("runs"), dict):
        steps += [s for s in doc["runs"].get("steps") or [] if isinstance(s, dict)]
    for s in steps:
        if s.get("shell") == "python3 {0}" and isinstance(s.get("run"), str):
            out.append((s.get("name") or "", s["run"]))
    return out


def line_of(text, needle, line_in_block):
    lines = text.splitlines()
    first = needle.splitlines()[0].strip() if needle.strip() else ""
    for n, line in enumerate(lines, 1):
        if first and line.strip() == first:
            return n + line_in_block - 1
    return 0


def broad_excepts(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            items += [(p, n) for n in broad_handlers(tree)]
    for p in t.paths(".yml"):
        if p.startswith(".github/"):
            for _, run in workflow_python(t, p):
                try:
                    tree = ast.parse(run)
                except SyntaxError:
                    continue
                items += [(p, line_of(t.files[p], run, n)) for n in broad_handlers(tree)]
    for p in t.paths(".iss"):
        lexed = t.lexed(p)
        code_start = next((n for n, c in sorted(lexed.code.items()) if c.strip().lower() == "[code]"), None)
        if code_start is not None:
            items += [(p, n) for n, c in sorted(lexed.code.items())
                      if n > code_start and re.search(r"\bexcept\b", c, re.I)]
    return items


def marker_has_issue(t, path, node):
    source = "\n".join(t.files[path].splitlines()[node.lineno - 1:node.end_lineno])
    return bool(ISSUE.search(source))


def skip_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("unittest", "pytest"):
            names |= {a.asname or a.name for a in node.names if a.name in SKIP_NAMES}
    return names


def skipped_tests(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is None:
            continue
        imported = skip_names(tree)
        for node in ast.walk(tree):
            target = node.func if isinstance(node, ast.Call) else node
            hit = (isinstance(target, ast.Attribute) and target.attr in SKIP_NAMES) or (
                isinstance(target, ast.Name) and target.id in imported)
            if hit and isinstance(node, (ast.Call, ast.Attribute, ast.Name)) and not marker_has_issue(t, p, node):
                if isinstance(node, ast.Call) or not any(
                        isinstance(c, ast.Call) and c.func is node for c in ast.walk(tree)):
                    items.append((p, node.lineno))
        items += [(p, n) for n, s in python_strings(t, p) if s.startswith("--") and LEFT_OUT in s
                  and not ISSUE.search(s)]
    for p in t.paths(".yml", ".ps1", ".psd1"):
        items += [(p, n) for n, code in sorted(t.lexed(p).code.items()) if LEFT_OUT in code and not ISSUE.search(code)]
    return sorted(set(items))


def comment_texts(t):
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        for c in lexed.comments:
            for k, text in enumerate(c.text.splitlines() or [""]):
                yield p, c.start + k, text


def markdown_lines(t):
    for p in t.paths(".md"):
        for n, line in enumerate(t.files[p].splitlines(), 1):
            yield p, n, line


def docstring_texts(t):
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            for d in docstrings(tree):
                for k, text in enumerate(d.value.value.splitlines()):
                    yield p, d.lineno + k, text


def todo_markers(t):
    return [(p, n) for p, n, text in [*comment_texts(t), *markdown_lines(t)] if TODO.search(text)]


def prose_justifications(t):
    return sorted({(p, n) for p, n, text in [*comment_texts(t), *docstring_texts(t), *markdown_lines(t)]
                   if PROSE.search(text) and not ISSUE.search(text)})


def identifiers(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node, node.id
        elif isinstance(node, ast.Attribute):
            yield node, node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node, node.name
        elif isinstance(node, ast.arg):
            yield node, node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            yield node, node.arg
        elif isinstance(node, ast.alias):
            yield node, node.asname or node.name
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                yield node, name


def non_ascii_identifiers(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            items += [(p, getattr(n, "lineno", 0)) for n, name in identifiers(tree) if not name.isascii()]
    return items


def load_dev_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "dev" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hooks(t):
    return load_dev_module("testa_ganchos").counts(t.files)


def engine_hooks(t):
    return hooks(t)["engine_hooks"]


def out_of_repo_routes(t):
    return hooks(t)["out_of_repo_routes"]


def engine_reaches(t):
    return hooks(t)["engine_reaches"]


def app_reaches(t):
    return hooks(t)["app_reaches"]


def theme_inline_lines(t):
    html = t.files.get("themes/ritmelli/index.html", "")
    return load_dev_module("testa_i18n").inline_lines(html)


def file_lines(name):
    def count(t):
        return len(t.files.get(BIG_FILES[name], "").splitlines())
    count.__name__ = name
    return count


def verification_names():
    tudo = load_dev_module("testa_tudo")
    paths = [*tudo.STDLIB, *tudo.COMPLETO, *tudo.LONG_TESTS.values(), *tudo.MICROFONE, *tudo.TELA,
             *(p for p, *_ in tudo.PASSOS.values())]
    names = set()
    for p in paths:
        names |= {p, Path(p).name, Path(p).stem}
    return names


def workflow_jobs(t):
    text = t.files.get(".github/workflows/testa.yml")
    if text is None:
        return set()
    doc = workflow_yaml.loads(text, name="testa.yml")
    jobs = doc.get("jobs") or {}
    return set(jobs) | {j.get("name") for j in jobs.values() if isinstance(j, dict) and j.get("name")}


def agents_rules(text):
    rules, current = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith(("#", "|")):
            current = None
            continue
        if line.startswith("- ") or current is None:
            current = [n, line]
            rules.append(current)
        else:
            current[1] += " " + line.strip()
    return rules


def agents_rules_without_check(t):
    valid = verification_names() | workflow_jobs(t)
    items = []
    for n, rule in agents_rules(t.files.get("AGENTS.md", "")):
        cited = {name.replace("\\", "/") for c in re.findall(r"`([^`]+)`", rule) if c.split()
                 for name in (c.strip(), c.split()[0])}
        if not cited & valid:
            items.append(("AGENTS.md", n))
    return items


COUNTERS = {f.__name__: f for f in (
    comment_lines, docstring_lines, suppressions, sleeps_app, sleeps_dev, theme_timers, theme_animation_frames,
    retries, broad_excepts, skipped_tests, todo_markers, prose_justifications, non_ascii_identifiers, engine_hooks,
    out_of_repo_routes, engine_reaches, app_reaches, theme_inline_lines, *(file_lines(n) for n in BIG_FILES),
    agents_rules_without_check)}


def count_of(value):
    return value if isinstance(value, int) else len(value)


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def working_tree():
    _, out = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = {}
    for p in sorted(set(out.split("\0")) - {""}):
        path = ROOT / p
        if (suffix(p) in LEXERS or suffix(p) == ".md" or p in BIG_FILES.values()) and path.is_file():
            try:
                files[p] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return files


def base_commit():
    base = os.environ.get("BASE", "").strip()
    if base:
        return base
    code, out = git("merge-base", "HEAD", "origin/main")
    return out.strip() if code == 0 else ""


def base_ceilings(base):
    if not base:
        return None
    code, out = git("show", f"{base}:dev/garden.json")
    return json.loads(out) if code == 0 else None


def added_lines(base):
    if not base:
        return {}
    code, out = git("diff", "--unified=0", "--no-color", base, "--")
    added, path = {}, None
    for line in out.splitlines() if code == 0 else []:
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
            start, length = int(m.group(1)), int(m.group(2) or 1)
            added.setdefault(path, set()).update(range(start, start + length))
    return added


def new_items(items, added):
    return [i for i in items if i[1] in added.get(i[0], ())]


def check(counts, ceilings, base, added=None):
    failures, summary = [], []
    for name, value in counts.items():
        n = count_of(value)
        ceiling = ceilings.get(name)
        before = base.get(name) if base else None
        if before is None:
            summary.append(f"-- summary: garden {name}: {n} (new, no ceiling on the base)")
        elif n != before:
            summary.append(f"-- summary: garden {name}: {n} ({n - before:+d} against the base)")
        if ceiling is None:
            failures.append(f"{name}: {n}, with no ceiling in dev/garden.json: add \"{name}\": {n}")
            continue
        if before is not None and ceiling > before:
            failures.append(f"{name}: the ceiling went up from {before} to {ceiling} in dev/garden.json: a ceiling "
                            f"only goes down")
        if n > ceiling:
            where = new_items(value, added or {}) if isinstance(value, list) else []
            failures.append(f"{name}: {n}, over the ceiling of {ceiling} (+{n - ceiling}): remove what went in"
                            + "".join(f"\n        {p}:{line}" for p, line in where))
        elif n < ceiling:
            failures.append(f"{name}: {n}, under the ceiling of {ceiling}: lower \"{name}\" in dev/garden.json to {n}")
    failures += [f"{name}: a ceiling in dev/garden.json for no counter" for name in sorted(set(ceilings) - set(counts))]
    if base is not None and not summary:
        summary.append(f"-- summary: garden: no counter changed against the base ({len(counts)} counters)")
    return failures, summary


def scoreboard(files):
    t = Tree(files)
    return {name: f(t) for name, f in COUNTERS.items()}


def run():
    counts = scoreboard(working_tree())
    ceilings = json.loads(CEILINGS.read_text(encoding="utf-8"))
    base = base_commit()
    failures, summary = check(counts, ceilings, base_ceilings(base), added_lines(base))
    for name, value in counts.items():
        print(f"{'ok  ' if count_of(value) == ceilings.get(name) else 'FAIL'}  {name}: {count_of(value)} "
              f"(ceiling {ceilings.get(name)})")
    for line in summary:
        print(line)
    for f in failures:
        print(f"FAIL  {f}")
    return 1 if failures else 0


def list_counter(name):
    value = COUNTERS[name](Tree(working_tree()))
    if isinstance(value, int):
        print(value)
    else:
        for p, n in value:
            print(f"{p}:{n}")
    return 0


def pr_number(event_name, event):
    if event_name == "pull_request":
        return (event.get("pull_request") or {}).get("number")
    if event_name == "merge_group":
        m = re.search(r"/pr-(\d+)-", (event.get("merge_group") or {}).get("head_ref", ""))
        return int(m.group(1)) if m else None
    return None


def description_problems(body):
    lines = (body or "").splitlines()
    problems = []
    proof = None
    for i, line in enumerate(lines):
        label = re.sub(r"^[#*_\s]+", "", line)
        if PROOF_LABEL.match(label):
            section = [re.sub(r"^[^:]*:", "", label, count=1)]
            for nxt in lines[i + 1:]:
                if re.match(r"^\s*(#+\s|\*\*[^*]+\*\*\s*$)", nxt):
                    break
                section.append(nxt)
            proof = "\n".join(section)
            if PROOF_CONTENT.search(proof):
                break
    if proof is None:
        problems.append("no proof section (a heading or a bold line like \"How it was proven\" or \"Proof\")")
    elif not PROOF_CONTENT.search(proof):
        problems.append("the proof section has no run, test or screenshot (a `command`, a link or an image)")
    problems += [f"line {n}: \"{PROSE.search(line).group(0)}\" with no issue link: fix it, or link the issue that "
                 f"tracks it" for n, line in enumerate(lines, 1) if PROSE.search(line) and not ISSUE.search(line)]
    return problems


def fetch_description(repo, number):
    r = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".body // \"\""], capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh api failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def check_description():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    number = pr_number(event_name, event)
    if number is None:
        print(f"ok    no PR in this {event_name or 'run'}: no description to check")
        return 0
    try:
        body = fetch_description(os.environ["GITHUB_REPOSITORY"], number)
    except (RuntimeError, KeyError) as ex:
        print(f"FAIL  the description of PR #{number} could not be read: {ex}")
        return 1
    problems = description_problems(body)
    for p in problems:
        print(f"FAIL  PR #{number} description: {p}")
    if not problems:
        print(f"ok    the description of PR #{number} has its proof section and no prose without an issue")
    return 1 if problems else 0


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--pr-description"]:
        return check_description()
    if argv[:1] == ["--list"] and len(argv) == 2 and argv[1] in COUNTERS:
        return list_counter(argv[1])
    if argv:
        print(USAGE)
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

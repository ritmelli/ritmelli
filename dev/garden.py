import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tokenize
import types
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import workflow_yaml

USAGE = """The garden scoreboard: counts the weeds of the repo and holds each count to its ceiling in dev/garden.json.

    python dev/garden.py                   the counts against dev/garden.json and the base ($env:BASE)
    python dev/garden.py --list NAME       every item a counter counts, with its place
    python dev/garden.py --pr-description  the description of the PR of this run, read from the API

A count over its ceiling fails (weeds went in); under it, it fails too until the PR lowers the ceiling to the count.
A ceiling over the base's fails as well, so a PR can't raise it along with the weeds. Every counter that changed
against the base goes to the PR summary as a "-- summary:" line."""

COMMENT_EXTENSIONS = (".py", ".js", ".css", ".ps1", ".yml", ".yaml", ".cpp", ".h", ".iss", ".bat", ".html", ".rc", ".spec",
                      ".sh", ".toml", ".psd1", ".isl", ".properties")
GARDEN_FILES = ("dev/garden.py", "dev/test_garden.py")
ISSUE_URL = re.compile(r"(?<![\w./-])(?:https?://)?(?:www\.)?github\.com/[\w.-]+/[\w.-]+/issues/\d+(?![\w-])")
URL = re.compile(r"\b[a-z][a-z\d+.-]*://\S+|\bwww\.\S+", re.I)
SHORT_ISSUE = re.compile(r"(?<![^\s(\[{,;:])(?:[A-Za-z\d-]+/[\w.-]+)?#\d+\b")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
QUOTED = re.compile(r'"([^"\n]+)"')
RESULT = re.compile(r"\b(?:pass(?:es|ed)?|fail(?:s|ed)?|successfully|\d+ of \d+|\d+/\d+)\b", re.I)
OPEN_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[ \]\s")
CODE_SPAN = re.compile(r"(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\1(?!`)", re.S)
PARAGRAPH_START = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>)")
BLOCK_MARKER = re.compile(r"^\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b")
KEPT_COMMENT = re.compile(r"^\s*manual:|^\s*i18n-ok\s*$|^ inline-script: [\w-]+\.js $")
GENERATED_MARKERS = {"molduras:inicio (gravado pelo dev/molduras.py: o desenho mora la, nao editar aqui)"}
LICENSE = re.compile(r"SPDX-License-Identifier:|\bCopyright\b|\bLicensed under\b", re.I)
ENCODING = re.compile(r"coding[:=]\s*[-\w.]+")
PIN = re.compile(r"@[0-9a-f]{40}\s*$")
PIN_VERSION = re.compile(r"^\s*v\d+(?:\.\d+)*\s*$")
SUPPRESSIONS_IN_COMMENTS = re.compile(r"\bnoqa\b|\btype:\s*ignore\b|\beslint-disable|\bpragma:\s*no\s*cover\b")
PRAGMA_DISABLE = re.compile(r"#\s*pragma\s+warning\s*\(\s*disable")
CONTINUE_ON_ERROR = re.compile(r"^\s*(?:-\s+)?continue-on-error\s*:(?!\s*(?:false|'false'|\"false\")\s*$)")
SILENTLY_CONTINUE = re.compile(r"-ErrorAction\s+SilentlyContinue\b", re.I)
START_SLEEP = re.compile(r"\bStart-Sleep\b", re.I)
THEME_TIMER = re.compile(r"\b(?:setTimeout|setInterval|requestIdleCallback)\s*\(")
ANIMATION_FRAME = re.compile(r"\brequestAnimationFrame\s*\(")
TODO = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b")
PROSE = re.compile(r"\b(?:risco\s+aceito|accepted\s+risk|sem\s+prova|por\s+enquanto|for\s+now|known\s+issue)\b",
                   re.I)
LEFT_OUT = re.compile(r"^--\s.*ficou de fora", re.S)
KNOWN_FAILURE = re.compile(r"^\s*known failure", re.I)
LEFT_OUT_QUOTED = re.compile(r"[\"']--\s[^\"']*ficou de fora")
SKIP_NAMES = {"skip", "skipIf", "skipUnless", "expectedFailure", "skipTest", "SkipTest", "xfail", "skipif"}
BROAD = {"Exception", "BaseException"}
SLEEP_MODULES = {"time", "asyncio"}
PS_LOOP = re.compile(r"\b(?:for|foreach|while|do)\b", re.I)
PS_TRY = re.compile(r"\btry\s*\{", re.I)
PS_CATCH = re.compile(r"\bcatch\s*(?:\[[^\]]*\]\s*,?\s*)*\{", re.I)
PS_LEAVES = re.compile(r"\b(?:break|return|exit|throw)\b", re.I)
PS_EXITS = re.compile(r"\b(?:break|return|exit)\b", re.I)
PS_STRING = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"`]|`.)*\"", re.S)
PS_VARIABLE = re.compile(r"\$(\w+)")
PS_ASSIGNED = re.compile(r"\$(\w+)\s*=(?!=)")
PROOF_LABEL = re.compile(r"^(?:how it was (?:proven|proved|tested)|proof\b|prova\b|como foi provado|testing\b"
                         r"|test plan\b|test results\b|verification\b)", re.I)
SECTION_LABEL = re.compile(r"^\s*(?:#{1,6}\s+(?P<heading>[^:]+?)(?::\s*(?P<rest>.*))?\s*$"
                           r"|\*\*(?P<bold>[^*]+?):?\*\*:?\s*(?P<rest2>.*)$"
                           r"|(?P<plain>[A-Z][\w ,'/-]{1,40}):(?:\s+(?P<rest3>.*))?$)")
RUN_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/actions/runs/\d+")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\s|https://github\.com/user-attachments/assets/[\w-]+")
PROOF_COMMANDS = {"python", "py", "gh", "git", "pwsh", "powershell", "bash", "node", "npm", "ruff", "actionlint"}
RUNNER_NAMES = {"testa_tudo", "testa_tudo.py", "dev/testa_tudo.py"}
BLOCK_PROOF = re.compile(r"^[ \t]*(?:(?:\$|>|PS [^>\n]*>|[A-Z]:\\[^>\n]*>)[ \t]*)?"
                         r"(?:python|py|gh|git|pwsh|powershell|bash|node|npm|ruff|actionlint)[ \t]+\S"
                         r"|^[ \t]*(?:ok|FAIL|FALHA)[ \t]|^[ \t]*(?:=+[ \t]*)?\d+ (?:of|de) \d+\b"
                         r"|^[ \t]*(?:=+[ \t]*)?\d+ (?:passed|failed)\b|^[ \t]*exit(?: code)?[ \t]*[=:]?[ \t]*\d+\b"
                         r"|^Traceback \(most recent call last\)",
                         re.M)
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
    runs: list = field(default_factory=list)

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


def lex_properties(text):
    out = Lexed()
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("#", "!")):
            out.comments.append(Comment(n, n, line.lstrip()[1:]))
            out.code[n] = ""
        else:
            out.code[n] = line
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
    for m in re.finditer(r"<!--(.*?)-->|<(script|style)\b[^>]*>(.*?)</\2\s*>", text, re.S | re.I):
        if m.group(2) is None:
            start = text.count("\n", 0, m.start()) + 1
            out.comments.append(Comment(start, start + m.group(0).count("\n"), m.group(1)))
            continue
        offset = text.count("\n", 0, m.start(3))
        kind = m.group(2).lower()
        shift(lex_c(m.group(3), js=kind == "script", css=kind == "style"), offset, out)
    for n in range(1, text.count("\n") + 2):
        out.code.setdefault(n, "")
    return out


BLOCK_SCALAR = re.compile(r"^(\s*)(-\s+)?([\w.-]+):\s*[|>][-+]?\s*(?:#.*)?$")
INLINE_RUN = re.compile(r"^\s*(?:-\s+)?run:\s*([^\s|>].*?)\s*$")


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def key_indent(line):
    stripped = line.lstrip(" ")
    return indent_of(line) + (len(stripped) - len(stripped[1:].lstrip(" ")) if stripped.startswith("-") else 0)


def unquote(value):
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) > 1 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


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
        m = re.match(r"^\s*(?:-\s+)?shell:\s*(.+?)\s*$", lex_hash(line).code.get(1, line))
        if m and key_indent(line) == indent:
            return m.group(1).strip("'\"")
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
            inline = INLINE_RUN.match(out.code[n])
            if inline:
                shell, script = yaml_shell(lines, n - 1), unquote(inline.group(1))
                out.runs.append((n - 1, shell, script))
                run = lexer_for_shell(shell)(script)
                out.code[n] = out.code[n][:inline.start(1)] + " ".join(run.code.values())
                out.comments += [Comment(n, n, c.text) for c in run.comments]
                out.strings += [(n, text) for _, text in run.strings]
            continue
        end = n
        while end < len(lines) and (not lines[end].strip() or indent_of(lines[end]) > key_indent(line)):
            end += 1
        body = lines[n:end]
        if m.group(3) == "run":
            indent = min((indent_of(b) for b in body if b.strip()), default=0)
            script = "\n".join(b[indent:] for b in body)
            shell = yaml_shell(lines, n - 1)
            out.runs.append((n, shell, script))
            shift(lexer_for_shell(shell)(script), n, out)
        else:
            for k, b in enumerate(body, n + 1):
                out.code[k] = b
        n = end
    return out


LEXERS = {".py": lex_python, ".spec": lex_python, ".js": lambda t: lex_c(t, js=True), ".css": lambda t: lex_c(t, css=True),
          ".cpp": lex_c, ".h": lex_c, ".rc": lex_c, ".ps1": lex_powershell, ".psd1": lex_powershell, ".yml": lex_yaml, ".yaml": lex_yaml,
          ".iss": lex_iss, ".isl": lex_semicolon, ".bat": lex_bat, ".html": lex_html, ".sh": lex_hash,
          ".toml": lex_hash, ".properties": lex_properties}


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
    return suffix(path) in (".yml", ".yaml") and bool(PIN.search(lexed.code.get(comment.start, "").rstrip())) and bool(
        PIN_VERSION.match(text))


class Tree:
    def __init__(self, files):
        self.files = files
        self._lexed, self._ast, self._hooks = {}, {}, None

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

    def hooks(self):
        if self._hooks is None:
            self._hooks = load_dev_module("testa_ganchos").counts(self.files)
        return self._hooks


def license_header(lexed):
    by_line = {}
    for c in lexed.comments:
        for k, text in enumerate(c.text.splitlines() or [""]):
            by_line.setdefault(c.start + k, text)
    header, n, last = set(), 1, max([*lexed.code, *by_line], default=0)
    while n <= last and not lexed.code.get(n, "").strip(" \t*/#;<!->"):
        if LICENSE.search(by_line.get(n, "")):
            header.add(n)
        n += 1
    return header


def comment_lines(t):
    items = []
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        lines = set()
        for c in lexed.comments:
            if not kept(p, lexed, c):
                lines |= set(range(c.start, c.end + 1))
            else:
                if c.end > c.start and any(text.strip(" */") for text in c.text.splitlines()[1:]):
                    lines |= set(range(c.start + 1, c.end + 1))
                marker = BLOCK_MARKER.match(c.text)
                first = (c.text.splitlines() or [""])[0]
                if marker and first.strip() not in GENERATED_MARKERS and re.search(r"[^\W\d_]", first[marker.end():]):
                    lines.add(c.start)
        items += [(p, n) for n in sorted(lines - license_header(lexed))]
    return items


def docstrings(tree):
    for node in ast.walk(tree):
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
    for p in workflow_paths(t):
        for offset, tree, _ in workflow_python(t, p):
            items += [(p, offset + n) for d in docstrings(tree) for n in range(d.lineno, d.end_lineno + 1)]
    return items


def workflow_paths(t):
    return [p for p in t.paths(".yml", ".yaml") if p.startswith(".github/")]


def python_strings(t, path):
    tree = t.tree(path)
    if tree is None or path in GARDEN_FILES:
        return []
    out = []
    constants = {s.targets[0].id: s.value.value for s in tree.body if isinstance(s, ast.Assign)
                 and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name) and isinstance(s.value, ast.Constant)
                 and isinstance(s.value.value, str)}

    def part(v):
        if isinstance(v, ast.Constant):
            return str(v.value)
        if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
            return constants.get(v.value.id, "")
        return ""
    inside_f_strings = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside_f_strings:
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            out.append((node.lineno, "".join(part(v) for v in node.values)))
    return out


STRING_TOKENS = {tokenize.STRING, *(getattr(tokenize, n) for n in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
                                    if hasattr(tokenize, n))}


def python_string_lines(t, path):
    if t.tree(path) is None or path in GARDEN_FILES:
        return []
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(t.files[path]).readline):
        if tok.type in STRING_TOKENS:
            out += [(tok.start[0] + k, piece) for k, piece in enumerate(tok.string.split("\n"))]
    return out


def code_lines(t, path):
    if suffix(path) in (".py", ".spec"):
        return python_string_lines(t, path)
    return sorted(t.lexed(path).code.items())


def suppressions(t):
    items = []
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        items += [(p, c.start) for c in lexed.comments if SUPPRESSIONS_IN_COMMENTS.search(c.text)]
        for n, code in code_lines(t, p):
            hits = len(PRAGMA_DISABLE.findall(code)) + len(SILENTLY_CONTINUE.findall(code))
            if suffix(p) in (".yml", ".yaml") and CONTINUE_ON_ERROR.match(code):
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
    return path.startswith(("dev/", ".github/"))


def is_test(path):
    return testa_tudo().is_test(path)


def sleeps(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            aliases = sleep_aliases(tree)
            items += [(p, n.lineno) for n in ast.walk(tree) if is_sleep(n, aliases)]
    for p in t.paths(".yml", ".yaml"):
        if p.startswith(".github/"):
            for offset, tree, _ in workflow_python(t, p):
                aliases = sleep_aliases(tree)
                items += [(p, offset + n.lineno) for n in ast.walk(tree) if is_sleep(n, aliases)]
    for p in t.paths(*COMMENT_EXTENSIONS):
        for n, code in code_lines(t, p):
            items += [(p, n)] * len(START_SLEEP.findall(code))
    return items


TEST_JOB = re.compile(r"^(?:test|testa|teste)s?(?:[-_][\w-]+)?$")


def test_job_lines(text):
    lines, inside, test = set(), False, False
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\S", line):
            inside, test = line.rstrip() == "jobs:", False
            continue
        m = re.match(r"^  ([\w-]+):\s*$", line) if inside else None
        if m:
            test = bool(TEST_JOB.match(m.group(1)))
        if test:
            lines.add(n)
    return lines


def in_test(t, item):
    path, line = item
    if is_test(path):
        return True
    return path.startswith(".github/workflows/") and line in test_job_lines(t.files.get(path, ""))


def sleeps_app(t):
    return [i for i in sleeps(t) if not is_dev(i[0]) and not in_test(t, i)]


def sleeps_dev(t):
    return [i for i in sleeps(t) if is_dev(i[0]) and not in_test(t, i)]


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


def exits(node):
    call = node.value if isinstance(node, ast.Expr) else None
    if not isinstance(call, ast.Call):
        return False
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in ("exit", "_exit") and isinstance(f.value, ast.Name)
            and f.value.id in ("sys", "os")) or (isinstance(f, ast.Name) and f.id in ("exit", "quit"))


def leaves(body):
    last = body[-1] if body else None
    return isinstance(last, (ast.Return, ast.Raise, ast.Break)) or exits(last)


def test_names(test):
    return {n.id for n in ast.walk(test) if isinstance(n, ast.Name)}


def assignments(body):
    for s in body:
        for n in [s, *local_nodes(s)]:
            if isinstance(n, ast.Assign):
                pairs = [(target, n.value) for target in n.targets]
            elif isinstance(n, (ast.AnnAssign, ast.NamedExpr)):
                pairs = [(n.target, n.value)]
            elif isinstance(n, ast.AugAssign):
                pairs = [(n.target, None)]
            else:
                continue
            for target, value in pairs:
                yield from ((t.id, value) for t in ast.walk(target) if isinstance(t, ast.Name))


def keeps_going(test, name, value):
    if not isinstance(value, ast.Constant):
        return False
    if isinstance(test, ast.Name) and test.id == name:
        return bool(value.value)
    if (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name)
            and test.operand.id == name):
        return not value.value
    return False


def turns_off(tests, body):
    return any(name in test_names(test) and not keeps_going(test, name, value)
               for test in tests for name, value in assignments(body))


def python_retries(tree):
    aliases = sleep_aliases(tree)
    found = []
    for loop in ast.walk(tree):
        if isinstance(loop, LOOPS):
            inner = list(local_nodes(loop))
            if not any(is_sleep(n, aliases) for n in inner):
                continue
            handled = {id(x) for t in inner if isinstance(t, ast.Try) for h in t.handlers for x in ast.walk(h)}
            ends = any(isinstance(n, (ast.Return, ast.Break)) and id(n) not in handled for n in inner)
            guards = {id(s): n.test for n in inner if isinstance(n, ast.If) for s in n.body}
            for attempt in (n for n in inner if isinstance(n, ast.Try)):
                again = [h for h in attempt.handlers if not leaves(h.body)]
                waits_on_failure = any(is_sleep(n, aliases) for h in again for n in local_nodes(h)) and not any(
                    is_sleep(n, aliases) for s in attempt.body + attempt.orelse for n in [s, *local_nodes(s)])
                tests = [t for t in (guards.get(id(attempt)), loop.test if isinstance(loop, ast.While) else None) if t]
                stops_on_success = turns_off(tests, attempt.body)
                if again and (waits_on_failure or ends or stops_on_success):
                    found.append(loop.lineno)
                    break
    return found


def closing(code, start, opening, close):
    depth = 0
    for i in range(start, len(code)):
        if code[i] == opening:
            depth += 1
        elif code[i] == close:
            depth -= 1
            if depth == 0:
                return i
    return len(code) - 1


def powershell_loops(code):
    loops = []
    for m in PS_LOOP.finditer(code):
        i = m.end()
        while i < len(code) and code[i].isspace():
            i += 1
        if i < len(code) and code[i] == "(":
            i = closing(code, i, "(", ")") + 1
            while i < len(code) and code[i].isspace():
                i += 1
        if i < len(code) and code[i] == "{":
            loops.append((m.start(), i, closing(code, i, "{", "}")))
    return loops


def mask_ps_strings(code):
    return PS_STRING.sub(lambda m: m.group(0)[0] + re.sub(r"[^\n]", " ", m.group(0)[1:-1]) + m.group(0)[-1], code)


def powershell_retries(code):
    code = mask_ps_strings(code)
    loops = powershell_loops(code)
    found = []
    for start, body_start, body_end in loops:
        own, cut = [], body_start
        for inner_start, _, inner_end in loops:
            if body_start < inner_start and inner_end <= body_end and inner_start >= cut:
                own.append(code[cut:inner_start])
                cut = inner_end + 1
        own.append(code[cut:body_end + 1])
        body = "".join(own)
        if not (re.search(r"\btry\s*\{", body, re.I) and START_SLEEP.search(body)):
            continue
        again = [block for block in ps_blocks(body, PS_CATCH) if not PS_LEAVES.search(top_level(block))]
        if not again:
            continue
        tries = list(ps_blocks(body, PS_TRY))
        waits_on_failure = any(START_SLEEP.search(block) for block in again) and not any(
            START_SLEEP.search(block) for block in tries)
        ends = any(PS_EXITS.search(block) for block in tries)
        tried = {v.lower() for block in tries for v in PS_ASSIGNED.findall(block)}
        condition = code[start:body_start]
        after = re.match(r"\s*(?:while|until)\s*\(", code[body_end + 1:], re.I)
        if after and re.match(r"do\b", code[start:], re.I):
            open_at = body_end + after.end()
            condition += code[open_at:closing(code, open_at, "(", ")") + 1]
        stops_on_success = tried & {v.lower() for v in PS_VARIABLE.findall(condition)}
        if waits_on_failure or ends or stops_on_success:
            found.append(code.count("\n", 0, start) + 1)
    return found


def top_level(block):
    out, depth = [], 0
    for c in block[1:-1]:
        depth += (c == "{") - (c == "}")
        if depth == 0 and c != "}":
            out.append(c)
    return "".join(out)


def ps_blocks(code, opener):
    for m in opener.finditer(code):
        yield code[m.end() - 1:closing(code, m.end() - 1, "{", "}") + 1]


JS_HANDLER = re.compile(r"\bonerror\s*=\s*(?:function\b[^(]*\([^)]*\)\s*|(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*)"
                        r"|\bcatch\s*(?:\([^)]*\))?\s*(?=\{)|\.(?:catch|aoFalhar)\s*(?=\()")
JS_RESCHEDULE = re.compile(r"\bsetTimeout\s*\(\s*(?:(?P<name>[A-Za-z_$][\w$]*)\s*,"
                           r"|(?:\(\s*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{?\s*(?P<called>[A-Za-z_$][\w$]*)\s*\()")


def rescheduled(r):
    return r.group("name") or r.group("called")


def handler_body(code, start):
    i = start
    while i < len(code) and code[i].isspace():
        i += 1
    if i < len(code) and code[i] in "{(":
        end = closing(code, i, code[i], "}" if code[i] == "{" else ")")
        return i, code[i:end + 1]
    stop = min((p for p in (code.find(";", i), code.find("\n", i)) if p >= 0), default=len(code))
    return i, code[i:stop]


def mask_js_strings(code):
    out, quote, i = [], None, 0
    while i < len(code):
        c = code[i]
        if quote:
            if c == "\\" and i + 1 < len(code):
                out.append("  " if code[i + 1] != "\n" else " \n")
                i += 2
                continue
            if c == quote:
                quote = None
                out.append(c)
            else:
                out.append("\n" if c == "\n" else " ")
            if c == "\n" and quote != "`":
                quote = None
        else:
            if c in "'\"`":
                quote = c
            out.append(c)
        i += 1
    return "".join(out)


JS_FUNCTION = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?=\{)"
                         r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
                         r"(?:function\b[^{]*|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)\s*(?=\{)")


def js_functions(code):
    spans = []
    for m in JS_FUNCTION.finditer(code):
        start = m.end()
        spans.append((m.group(1) or m.group(2), start, closing(code, start, "{", "}")))
    return spans


JS_CATCH_BLOCK = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")
JS_CATCH_CALL = re.compile(r"\.catch\s*\(")
JS_EMPTY_CALLBACK = re.compile(r"^\s*(?:(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{\s*\}"
                               r"|(?:async\s+)?function\s*[\w$]*\s*\([^)]*\)\s*\{\s*\})\s*,?\s*$")


def js_swallowed(code):
    code = mask_js_strings(code)
    found = []
    for m in JS_CATCH_BLOCK.finditer(code):
        if not code[m.end():closing(code, m.end() - 1, "{", "}")].strip():
            found.append(code.count("\n", 0, m.start()) + 1)
    for m in JS_CATCH_CALL.finditer(code):
        if JS_EMPTY_CALLBACK.match(code[m.end():closing(code, m.end() - 1, "(", ")")]):
            found.append(code.count("\n", 0, m.start()) + 1)
    return found


def js_retries(code):
    found = []
    code = mask_js_strings(code)
    functions = js_functions(code)
    calls = {}
    for name, a, b in functions:
        body = code[a:b]
        calls.setdefault(name, set()).update(
            m.group(1) for m in re.finditer(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\(", body)
            if not body[:m.start()].rstrip().endswith("."))
    for m in JS_HANDLER.finditer(code):
        start, body = handler_body(code, m.end())
        around = [(a, b) for _, a, b in functions if a < m.start() < b]
        enclosing = {name for name, a, b in functions if a < m.start() < b}
        found += [code.count("\n", 0, start + r.start()) + 1 for r in JS_RESCHEDULE.finditer(body)
                  if (rescheduled(r) in enclosing or enclosing & calls.get(rescheduled(r), set()))
                  and not (around and rescheduled_anyway(code, max(around), rescheduled(r), (start, start + len(body))))]
    return found


def rescheduled_anyway(code, span, name, handler):
    a, b = span
    for r in JS_RESCHEDULE.finditer(code, a, b):
        if rescheduled(r) == name and not handler[0] <= r.start() < handler[1]:
            between = code[a:r.start()]
            if between.count("{") - between.count("}") == 1:
                return True
    return False


def joined_code(lexed):
    lines = lexed.code
    return "\n".join(lines.get(n, "") for n in range(1, max(lines, default=0) + 1))


def retries(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            items += [(p, n) for n in python_retries(tree)]
            items += [(p, n + k - 1) for n, s in python_strings(t, p) if START_SLEEP.search(s)
                      for k in powershell_retries(s)]
    for p in t.paths(".yml", ".yaml"):
        if p.startswith(".github/"):
            items += [(p, offset + n) for offset, tree, _ in workflow_python(t, p) for n in python_retries(tree)]
    for p in t.paths(".ps1", ".psd1", ".yml", ".yaml"):
        items += [(p, n) for n in powershell_retries(joined_code(t.lexed(p)))]
    for p in t.paths(".js", ".html"):
        items += [(p, n) for n in js_retries(joined_code(t.lexed(p)))]
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
    for offset, shell, script in t.lexed(path).runs:
        if shell.startswith("python"):
            try:
                yield offset, ast.parse(script), script
            except SyntaxError:
                continue


def broad_excepts(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is not None:
            items += [(p, n) for n in broad_handlers(tree)]
    for p in t.paths(".yml", ".yaml"):
        if p.startswith(".github/"):
            for offset, tree, _ in workflow_python(t, p):
                items += [(p, offset + n) for n in broad_handlers(tree)]
    for p in t.paths(".js", ".html"):
        items += [(p, n) for n in js_swallowed(joined_code(t.lexed(p)))]
    for p in t.paths(".iss"):
        lexed = t.lexed(p)
        code_start = next((n for n, c in sorted(lexed.code.items()) if c.strip().lower() == "[code]"), None)
        if code_start is not None:
            items += [(p, n) for n, c in sorted(lexed.code.items())
                      if n > code_start and re.search(r"\bexcept\b", c, re.I)]
    return items


def cites_issue(text):
    return bool(ISSUE_URL.search(text) or SHORT_ISSUE.search(URL.sub(" ", LINK_TARGET.sub("] ", text))))


def skip_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("unittest", "pytest"):
            names |= {a.asname or a.name for a in node.names if a.name in SKIP_NAMES}
    return names


def skip_markers(tree, lines):
    imported = skip_names(tree)
    called = {id(c.func) for c in ast.walk(tree) if isinstance(c, ast.Call)}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.Attribute, ast.Name)):
            continue
        target = node.func if isinstance(node, ast.Call) else node
        hit = (isinstance(target, ast.Attribute) and target.attr in SKIP_NAMES) or (
            isinstance(target, ast.Name) and target.id in imported)
        if hit and (isinstance(node, ast.Call) or id(node) not in called) and not cites_issue(
                "\n".join(lines[node.lineno - 1:node.end_lineno])):
            found.append(node.lineno)
    return found


def skipped_tests(t):
    items = []
    for p in workflow_paths(t):
        raw = t.files[p].splitlines()
        items += [(p, offset + n) for offset, tree, script in workflow_python(t, p)
                  for n in skip_markers(tree, script.splitlines()) if not cites_issue(raw[offset + n - 1])]
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is None:
            continue
        items += [(p, n) for n in skip_markers(tree, t.files[p].splitlines())]
        raw = t.files[p].splitlines()
        items += [(p, n) for n, s in python_strings(t, p) if (LEFT_OUT.match(s) or KNOWN_FAILURE.match(s))
                  and not cites_issue(s) and not cites_issue(raw[n - 1] if n <= len(raw) else "")]
    for p in t.paths(".yml", ".yaml", ".ps1", ".psd1"):
        raw = t.files[p].splitlines()
        items += [(p, n) for n, code in sorted(t.lexed(p).code.items())
                  if LEFT_OUT_QUOTED.search(code) and not cites_issue(raw[n - 1] if n <= len(raw) else code)]
    return sorted(set(items))


def comment_texts(t):
    for p in t.paths(*COMMENT_EXTENSIONS):
        lexed = t.lexed(p)
        for c in lexed.comments:
            for k, text in enumerate(c.text.splitlines() or [""]):
                yield p, c.start + k, text


def comment_blocks(t):
    for p in t.paths(*COMMENT_EXTENSIONS):
        code = t.lexed(p).code
        block = []
        for c in sorted(t.lexed(p).comments, key=lambda c: c.start):
            alone = not code.get(c.start, "").strip()
            if block and not (alone and c.start <= block[-1].end + 1 and not code.get(block[-1].end, "").strip()):
                yield p, block
                block = []
            block.append(c)
        if block:
            yield p, block


def prose_in_comments(t):
    for p, block in comment_blocks(t):
        lines = [(c.start + k, text) for c in block for k, text in enumerate(c.text.splitlines())]
        yield from ((p, n) for n in prose_lines(lines))


def mask_code(text):
    return CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", "x", m.group(0)), text)


def prose_lines(lines, code_spans=False):
    text = "\n".join(line for _, line in lines)
    masked = mask_code(text) if code_spans else text
    if cites_issue(masked):
        return []
    return [lines[text.count("\n", 0, m.start())][0] for m in PROSE.finditer(masked.replace("\n", " "))]


def markdown_lines(t):
    for p in t.paths(".md"):
        for n, line in enumerate(t.files[p].splitlines(), 1):
            yield p, n, line


def todo_markers(t):
    return [(p, n) for p, n, text in [*comment_texts(t), *markdown_lines(t)] if TODO.search(text)]


def prose_in_markdown(t):
    for p in t.paths(".md"):
        for chunk in paragraphs(t.files[p].splitlines()):
            yield from ((p, i + 1) for i in prose_lines(chunk, code_spans=True))


def prose_justifications(t):
    return sorted({*prose_in_comments(t), *prose_in_markdown(t)})


def non_ascii_identifiers(t):
    items = []
    for p in t.paths(".py", ".spec"):
        tree = t.tree(p)
        if tree is None:
            continue
        items += [(p, line) for line in non_ascii_names(t.files[p])]
    for p in workflow_paths(t):
        for offset, _, script in workflow_python(t, p):
            items += [(p, offset + line) for line in non_ascii_names(script)]
    return items


def non_ascii_names(source):
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [tok.start[0] for tok in tokens if tok.type == tokenize.NAME and not tok.string.isascii()]


LOADED = {}


def load_dev_module(name):
    if name not in LOADED:
        spec = importlib.util.spec_from_file_location(name, ROOT / "dev" / f"{name}.py")
        LOADED[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(LOADED[name])
    return LOADED[name]


def testa_tudo():
    return load_dev_module("testa_tudo")


def engine_hooks(t):
    return t.hooks()["engine_hooks"]


def out_of_repo_routes(t):
    return t.hooks()["out_of_repo_routes"]


def engine_reaches(t):
    return t.hooks()["engine_reaches"]


def app_reaches(t):
    return t.hooks()["app_reaches"]


def automatico_reaches(t):
    return t.hooks()["automatico_reaches"]


def library_reaches(t):
    return t.hooks()["library_reaches"]


def app_writes(t):
    return t.hooks()["app_writes"]


def engine_writes(t):
    return t.hooks()["engine_writes"]


def theme_inline_lines(t):
    html = t.files.get("themes/ritmelli/index.html", "")
    return load_dev_module("testa_i18n").inline_lines(html)


def file_lines(name):
    def count(t):
        return len(t.files.get(BIG_FILES[name], "").splitlines())
    count.__name__ = name
    return count


def measured_module(t, name):
    text = t.files.get(f"dev/{name}.py")
    path = ROOT / "dev" / f"{name}.py"
    if text is None or (path.is_file() and text == path.read_text(encoding="utf-8-sig")):
        return load_dev_module(name)
    module = types.ModuleType(f"measured_{name}")
    module.__file__ = str(path)
    exec(compile(text, str(path), "exec"), module.__dict__)
    return module


def verification_names(t=None):
    tudo = load_dev_module("testa_tudo") if t is None else measured_module(t, "testa_tudo")
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
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return set()
    return set(jobs) | {j.get("name") for j in jobs.values() if isinstance(j, dict) and j.get("name")}


def agents_rules(text):
    rules, current = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith(("#", "|")):
            current = None
            continue
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s", line) or current is None:
            current = [n, line]
            rules.append(current)
        else:
            current[1] += " " + line.strip()
    return rules


def agents_rules_without_check(t):
    valid = verification_names(t) | workflow_jobs(t)
    items = []
    for n, rule in agents_rules(t.files.get("AGENTS.md", "")):
        cited = {name.replace("\\", "/") for c in re.findall(r"`([^`]+)`", rule) if c.split()
                 for name in (c.strip(), c.split()[0])}
        cited |= set(QUOTED.findall(rule))
        if not cited & valid:
            items.append(("AGENTS.md", n))
    return items


COUNTERS = {f.__name__: f for f in (
    comment_lines, docstring_lines, suppressions, sleeps_app, sleeps_dev, theme_timers, theme_animation_frames,
    retries, broad_excepts, skipped_tests, todo_markers, prose_justifications, non_ascii_identifiers, engine_hooks,
    out_of_repo_routes, engine_reaches, app_reaches, automatico_reaches, library_reaches, app_writes, engine_writes,
    theme_inline_lines, *(file_lines(n) for n in BIG_FILES),
    agents_rules_without_check)}


def count_of(value):
    return value if isinstance(value, int) else len(value)


def git(*args, root=ROOT):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def working_tree(root=ROOT):
    _, out = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", root=root)
    files = {}
    for p in sorted(set(out.split("\0")) - {""}):
        path = root / p
        if (suffix(p) in LEXERS or suffix(p) == ".md" or p in BIG_FILES.values()) and path.is_file():
            try:
                files[p] = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
    return files


def base_tree(base, root=ROOT):
    _, out = git("ls-tree", "-r", "-z", "--name-only", base, root=root)
    paths = [p for p in out.split("\0") if p and (suffix(p) in LEXERS or suffix(p) == ".md" or p in BIG_FILES.values())]
    request = "".join(f"{base}:{p}\n" for p in paths).encode("utf-8")
    data = subprocess.run(["git", "cat-file", "--batch"], cwd=root, input=request, capture_output=True,
                          check=True).stdout
    files, i = {}, 0
    for p in paths:
        end = data.index(b"\n", i)
        header = data[i:end].split()
        i = end + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        try:
            files[p] = data[i:i + size].decode("utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError:
            pass
        i += size + 1
    return files


QUEUE_REF = re.compile(r"^refs/heads/gh-readonly-queue/.+/pr-\d+-([0-9a-f]{40})$")


def base_commit():
    if os.environ.get("GITHUB_EVENT_NAME") == "merge_group":
        m = QUEUE_REF.match(os.environ.get("GITHUB_REF", ""))
        if not m:
            raise BaseError(f"the queue entry's ref {os.environ.get('GITHUB_REF')!r} names no base commit")
        return m.group(1)
    base = os.environ.get("BASE", "").strip()
    if base:
        return base
    code, out = git("merge-base", "HEAD", "origin/main")
    return out.strip() if code == 0 else ""


class BaseError(Exception):
    pass


def base_ceilings(base, root=ROOT):
    if not base:
        return None
    if git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", root=root)[0] != 0:
        raise BaseError(f"the base {base} is not a commit here: its ceilings can't be read")
    if git("cat-file", "-e", f"{base}:dev/garden.json", root=root)[0] != 0:
        return None
    code, out = git("show", f"{base}:dev/garden.json", root=root)
    if code != 0:
        raise BaseError(f"the dev/garden.json of the base {base} can't be read")
    return json.loads(out)


def added_lines(base, root=ROOT):
    if not base:
        return {}
    code, out = git("diff", "--unified=0", "--no-color", base, "--", root=root)
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


def is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check(counts, ceilings, base, added=None):
    bad = [f"{name}: the ceiling {value!r} in {where} is not a whole number" for where, values in
           (("dev/garden.json", ceilings), ("the base's dev/garden.json", base or {}))
           for name, value in values.items() if not is_count(value)]
    if bad:
        return bad, []
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
    return failures, summary


def scoreboard(files):
    t = Tree(files)
    return {name: f(t) for name, f in COUNTERS.items()}


def run(root=ROOT):
    counts = scoreboard(working_tree(root))
    ceilings = json.loads((root / "dev" / "garden.json").read_text(encoding="utf-8"))
    try:
        base = base_commit()
        before = base_ceilings(base, root)
    except BaseError as ex:
        print(f"FAIL  {ex}")
        return 1
    measured = before is None and bool(base)
    if measured:
        before = {name: count_of(value) for name, value in scoreboard(base_tree(base, root)).items()}
    failures, summary = check(counts, ceilings, before, added_lines(base, root))
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


def proof_label(line):
    m = SECTION_LABEL.match(line)
    if not m:
        return None
    label = m.group("heading") or m.group("bold") or m.group("plain")
    if not PROOF_LABEL.match(label.strip()):
        return None
    return (m.group("rest") or m.group("rest2") or m.group("rest3") or "").strip()


def heading_level(line):
    m = re.match(r"^\s*(#{1,6})\s", line)
    return len(m.group(1)) if m else None


def ends_section(line, level):
    if level is not None:
        other = heading_level(line)
        return other is not None and other <= level
    return bool(SECTION_LABEL.match(line))


FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def fence_closes(line, fence):
    m = re.match(r"^\s{0,3}(`{3,}|~{3,})\s*$", line)
    return bool(m) and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)


def blocks(lines):
    out, fence, body = [], None, []
    for line in lines:
        if fence is None:
            m = FENCE_OPEN.match(line)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence, body = m.group(1), []
            else:
                out.append(("text", line))
        elif fence_closes(line, fence):
            out.append(("code", "\n".join(body)))
            fence = None
        else:
            body.append(line)
    return out


def without_open_items(lines):
    out, inside = [], None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if inside is not None and (not line.strip() or indent > inside):
            continue
        inside = indent if OPEN_ITEM.match(line) else None
        if inside is None:
            out.append(line)
    return out


def has_proof(text):
    parts = blocks(without_open_items(text.splitlines()))
    if any(kind == "code" and BLOCK_PROOF.search(body) for kind, body in parts):
        return True
    prose = "\n".join(body for kind, body in parts if kind == "text")
    outside_code = CODE_SPAN.sub("", prose)
    if RUN_LINK.search(outside_code) or IMAGE.search(outside_code):
        return True
    if any(proof_span(span) for span in re.findall(r"`([^`\n]+)`", prose)):
        return True
    return any(plain_proof(line) for line in outside_code.splitlines())


def plain_proof(line):
    if not RESULT.search(line):
        return False
    words = re.findall(r"[\w./\\-]+", line.replace("\\", "/"))
    return any((w in PROOF_COMMANDS and any(re.search(r"[./]|^-", a) for a in words[i + 1:i + 4]))
               or w.rstrip(".") in verification_names() for i, w in enumerate(words))


def proof_span(span):
    words = span.replace("\\", "/").split()
    if not words:
        return False
    if words[0] in PROOF_COMMANDS:
        return len(words) > 1
    return words[0] in verification_names() | RUNNER_NAMES


def fence_opens(line):
    m = FENCE_OPEN.match(line)
    return m.group(1) if m and not (m.group(1)[0] == "`" and "`" in m.group(2)) else None


def outside_fences(lines):
    fence = None
    for i, line in enumerate(lines):
        if fence is None:
            opened = fence_opens(line)
            if opened:
                fence = opened
            else:
                yield i, line
        elif fence_closes(line, fence):
            fence = None


def proof_sections(lines):
    for i, line in outside_fences(lines):
        rest = proof_label(line)
        if rest is not None:
            section, level, fence = [rest], heading_level(line), None
            for nxt in lines[i + 1:]:
                if fence is None and ends_section(nxt, level):
                    break
                if fence is None:
                    fence = fence_opens(nxt)
                elif fence_closes(nxt, fence):
                    fence = None
                section.append(nxt)
            yield "\n".join(section)


def description_problems(body):
    lines = re.sub(r"<!--.*?-->", "", body or "", flags=re.S).splitlines()
    problems = []
    sections = list(proof_sections(without_open_items(lines)))
    if not sections:
        problems.append("no proof section (a heading, a bold label or a line starting \"How it was proven:\" or "
                        "\"Proof:\")")
    elif not any(has_proof(s) for s in sections):
        problems.append("the proof section has no run, test or screenshot (a command or a test file in `code`, a code "
                        "block, a link to a run or an image)")
    for chunk in paragraphs(lines):
        text = mask_code("\n".join(line for _, line in chunk)).replace("\n", " ")
        phrase = PROSE.search(text)
        if phrase and not cites_issue(text):
            n = next((i for i, line in chunk if PROSE.search(line)), chunk[0][0]) + 1
            problems.append(f"line {n}: \"{phrase.group(0)}\" with no issue link: fix it, or link the issue that "
                            f"tracks it")
    return problems


def paragraphs(lines):
    chunk, previous = [], None
    for i, line in outside_fences(lines):
        if chunk and (not line.strip() or PARAGRAPH_START.match(line) or i != previous + 1):
            yield chunk
            chunk = []
        if line.strip():
            chunk.append((i, line))
        previous = i
    if chunk:
        yield chunk


def fetch_description(repo, number):
    r = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".body // \"\""], capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh api failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def check_description(fetch=fetch_description):
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    number = pr_number(event_name, event)
    if number is None and event_name in ("pull_request", "merge_group"):
        print(f"FAIL  this {event_name} event names no PR: its description can't be read")
        return 1
    if number is None:
        print(f"ok    no PR in this {event_name or 'run'}: no description to check")
        return 0
    try:
        body = fetch(os.environ["GITHUB_REPOSITORY"], number)
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

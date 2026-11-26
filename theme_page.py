import contextlib
import functools
import hashlib
import os
import re
import sys
from html import unescape
from html.entities import html5
from html.parser import HTMLParser
from pathlib import Path

import i18n

THEMES = Path(__file__).resolve().parent / "themes"
SCRIPT_TAG = re.compile(r'<script src="([^"]+)">')
SHEET_TAG = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
REFERENCE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*;)?")
CLOSES_ELEMENT = {"script": re.compile(r"</script|<!--", re.IGNORECASE), "style": re.compile(r"</style", re.IGNORECASE)}
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|(.))", re.DOTALL)
URL_START = re.compile(r"url\([ \t\r\n\f]*['\"]?", re.IGNORECASE)
NOT_PLAIN_OUTSIDE = re.compile(r"\\|image-set\(", re.IGNORECASE)
NOT_RELATIVE = re.compile(r"[ \t\r\n\f]*(?:https?://|(?!https?:)[a-z][a-z0-9+.-]*:|/|#)", re.IGNORECASE | re.ASCII)
TEXT_ONLY = ("textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript")
FOREIGN = ("svg", "math")
NOT_IN_FOREIGN = ("script", "style", "link", "foreignobject", "desc", "title", "annotation-xml", "mi", "mo", "mn", "ms",
                  "mtext")
PLAIN_TEXT = {tag: re.compile(rf"[^<]*</{tag}>", re.IGNORECASE) for tag in TEXT_ONLY}
SCRIPT_TYPES = ("", "text/javascript", "application/json")


def css_unescape(text):
    return CSS_ESCAPE.sub(lambda m: chr(min(int(m.group(1), 16), 0xFFFD)) if m.group(1) else m.group(2), text)


@functools.lru_cache(maxsize=256)
def sheet_problem(text, outside_page_folder):
    read = css_unescape(text)
    if "@import" in read.lower():
        return "@import, even escaped or in a comment or a string, which the browser could fetch outside the page"
    if not outside_page_folder:
        return None
    if found := NOT_PLAIN_OUTSIDE.search(text):
        return (f"{found.group(0)!r} outside the page's folder, where only a plain url() can be read for certain: the page "
                f"resolves its addresses from its own folder")
    if any(not NOT_RELATIVE.match(text, m.end()) for m in URL_START.finditer(text)):
        return "a relative url(), even in a comment or a string, which the page would resolve from its own folder"
    return None


class ThemePageError(Exception):
    pass


class FileTags(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html, self.found, self.foreign = html, [], []
        self.lines = [0] + [m.end() for m in re.finditer("\n", html)]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        line, column = self.getpos()
        at = self.lines[line - 1] + column
        body = at + len(raw)
        first = {}
        for name, value in attrs:
            first.setdefault(name, value)
        if self.foreign and tag in NOT_IN_FOREIGN:
            raise ThemePageError(f"the <{tag}> on line {line} is inside <{self.foreign[-1]}>, where the browser reads "
                                 f"what the build cannot follow: draw it with shapes and attributes only, and put its "
                                 f"CSS and code in the theme's files")
        if tag in FOREIGN:
            self.foreign.append(tag)
        elif tag in TEXT_ONLY:
            if not PLAIN_TEXT[tag].match(self.html, body):
                raise ThemePageError(f"the <{tag}> on line {line} holds a < or does not end in </{tag}>, which the "
                                     f"browser can read as markup")
            self.set_cdata_mode(tag)
        elif tag == "style":
            self.inline_style(line, body)
        elif tag == "script" and "src" not in first:
            self.inline_script(raw, line, body, first)
        elif tag == "script":
            self.file_tag(raw, at, SCRIPT_TAG, "script", "</script>")
        elif tag == "link":
            rel = (first.get("rel") or "").lower().split()
            if "modulepreload" in rel or "preload" in rel and (first.get("as") or "").strip().lower() in ("script", "style"):
                raise ThemePageError(f"the tag {raw!r} on line {line} preloads a script or a style sheet, which the "
                                     f"browser would fetch: write the file tag")
            if "stylesheet" in rel:
                self.file_tag(raw, at, SHEET_TAG, "style", "")

    def file_tag(self, raw, at, canonical, kind, end):
        written = canonical.fullmatch(raw)
        if not written or not self.html.startswith(end, at + len(raw)):
            raise ThemePageError(f"the tag {raw!r} is not <script src=\"...\"></script> or "
                                 f"<link rel=\"stylesheet\" href=\"...\">, the only file tags the page puts inline")
        value = written.group(1)
        if loose := [m.group(0) for m in REFERENCE.finditer(value) if m.group(0)[1:] not in html5]:
            raise ThemePageError(f"the tag {raw!r} has {loose[0]!r}, which is not a whole character reference the "
                                 f"browser reads the same way")
        self.found.append((at, at + len(raw) + len(end), kind, unescape(value)))

    def inline_style(self, line, body):
        end = CLOSES_ELEMENT["style"].search(self.html, body)
        if not end or self.html[end.start():end.start() + 8].lower() != "</style>":
            raise ThemePageError(f"the <style> on line {line} does not end in </style>, which the browser can read "
                                 f"differently")
        if problem := sheet_problem(self.html[body:end.start()], False):
            raise ThemePageError(f"the <style> on line {line} has {problem}")

    def inline_script(self, raw, line, body, attrs):
        if "href" in attrs or "xlink:href" in attrs:
            raise ThemePageError(f"the tag {raw!r} on line {line} fetches its href: write the file tag "
                                 f"<script src=\"file.js\"></script>")
        if (attrs.get("type") or "").strip(" \t\n\r\f").lower() not in SCRIPT_TYPES:
            raise ThemePageError(f"the tag {raw!r} on line {line} has a type the build does not read for certain (a "
                                 f"module can import files the page would fetch): write a <script> without the type, "
                                 f"with type=\"text/javascript\" or type=\"application/json\", or a file tag")
        end = CLOSES_ELEMENT["script"].search(self.html, body)
        if not end or self.html[end.start():end.start() + 9].lower() != "</script>":
            raise ThemePageError(f"the <script> on line {line} holds <!-- or does not end in </script>, which the "
                                 f"browser can read differently")

    def handle_endtag(self, tag):
        if tag in FOREIGN and self.foreign:
            if self.foreign[-1] != tag:
                raise ThemePageError(f"the </{tag}> on line {self.getpos()[0]} does not close the <{self.foreign[-1]}> "
                                     f"open there, which the browser keeps open: close it with </{self.foreign[-1]}>")
            self.foreign.pop()

    def handle_comment(self, data):
        if data.startswith((">", "->")) or "--!>" in data:
            raise ThemePageError(f"the comment {('<!--' + data)[:40]!r}... ends earlier in the browser, which would "
                                 f"then read what the build leaves as a comment")

    def parse_marked_section(self, i, report=1):
        raise ThemePageError(f"{self.rawdata[i:i + 40]!r}... is a bogus comment in the browser that ends at its "
                             f"first >, which the build cannot read for certain")


@functools.lru_cache(maxsize=16)
def file_tags(html):
    return tuple(FileTags(html).found)


def shown(path):
    root = THEMES.resolve().parent
    return path.resolve().relative_to(root).as_posix() if path.resolve().is_relative_to(root) else path.name


def theme_file(folder, name):
    inside = THEMES if name.startswith("/t/") else folder
    path = (inside / name.removeprefix("/t/")).resolve()
    if not path.is_relative_to(inside.resolve()):
        raise ThemePageError(f"{name} is outside {shown(inside)}")
    if not path.is_file():
        raise ThemePageError(f"{name} is missing from {shown(inside)}")
    return path, utf8_text(path, name)


def utf8_text(path, name):
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as ex:
        raise ThemePageError(f"{name} is not UTF-8 text (byte {ex.start}): save it as UTF-8") from ex


def inline_files(html, folder):
    parts, done = [], 0
    for start, end, tag, name in file_tags(html):
        path, text = theme_file(folder, name)
        if closes := CLOSES_ELEMENT[tag].search(text):
            raise ThemePageError(f"{name} has {closes.group(0)}, which its <{tag}> cannot hold")
        if tag == "style" and (problem := sheet_problem(text, path.parent != folder.resolve())):
            raise ThemePageError(f"{name} has {problem}")
        parts += [html[done:start], f"<{tag}>\n{text}</{tag}>"]
        done = end
    return "".join(parts) + html[done:]


def theme_of_template(rel):
    path = THEMES / rel
    if not path.is_relative_to(THEMES):
        return None
    with contextlib.suppress(OSError, ValueError):
        parts = path.resolve().relative_to(THEMES.resolve()).parts
        if len(parts) >= 2 and os.path.samefile(path, THEMES / parts[0] / "index.html"):
            return parts[0]
    return None


def build(page, texts, language):
    try:
        html = inline_files(i18n.injeta(utf8_text(page, page.name), texts, language), page.parent)
    except ThemePageError as ex:
        from aiohttp import web
        print(f"theme page: {shown(page)} was not built: {ex}", file=sys.stderr, flush=True)
        raise web.HTTPInternalServerError(text=f"{shown(page)} was not built: {ex}") from ex
    return html, f'"{hashlib.sha256(html.encode("utf-8")).hexdigest()[:32]}"'

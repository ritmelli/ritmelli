import contextlib
import functools
import hashlib
import os
import re
import sys
from html import unescape
from html.entities import html5
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
NOT_IN_PAGE = {"base": "changes where every address of the page points",
               "template": "holds markup the browser keeps inert, which the build would still read",
               "plaintext": "turns the rest of the page into text, where the build would still read tags"}
SCRIPT_TYPES = ("", "text/javascript", "application/json")
PLAIN_ATTRIBUTES = ("rel", "type", "as")
SPACE = "[ \t\n\f\r]"
ATTRIBUTE_NAME = "[A-Za-z_:@][-A-Za-z0-9_:.@]*"
VALUE = r"""(?:"[^"]*"|'[^']*'|[^ \t\n\f\r"'=<>`]+)"""
ATTRIBUTE = re.compile(rf"{SPACE}+({ATTRIBUTE_NAME})(?:{SPACE}*={SPACE}*({VALUE}))?")
GRAMMAR = {
    "text": re.compile(r"[^<]+"),
    "comment": re.compile(r"<!--(?![>-])(?:(?!--)[\s\S])*-->"),
    "doctype": re.compile(r"<!doctype html>", re.IGNORECASE),
    "end tag": re.compile(r"</([A-Za-z][A-Za-z0-9-]*)>"),
    "start tag": re.compile(rf"<([A-Za-z][A-Za-z0-9-]*)((?:{SPACE}+{ATTRIBUTE_NAME}(?:{SPACE}*={SPACE}*{VALUE})?)*)"
                            rf"{SPACE}*(/?)>"),
}
BODY = {tag: re.compile(rf"[^<]*</{tag}>", re.IGNORECASE) for tag in TEXT_ONLY}
BODY["style"] = re.compile(r"(?:(?!</style)[\s\S])*</style>", re.IGNORECASE)
BODY["script"] = re.compile(r"(?:(?!</script|<!--)[\s\S])*</script>", re.IGNORECASE)
EXPECTED = ("text without <, <name attribute=\"value\">, </name>, <!-- text without -- -->, or <!doctype html>")


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
    def __init__(self, message, at=None):
        super().__init__(message)
        self.at = at


def place(html, i):
    return html.count("\n", 0, i) + 1, i - html.rfind("\n", 0, i)


class Template:
    def __init__(self, html):
        self.html, self.found, self.elements, self.foreign = html, [], [], []
        i = 0
        while i < len(html):
            i = self.token(i)

    def refuse(self, i, message):
        raise ThemePageError(message, place(self.html, i))

    def token(self, i):
        for kind, form in GRAMMAR.items():
            if m := form.match(self.html, i):
                if kind == "start tag":
                    return self.start_tag(m, i)
                if kind == "end tag":
                    self.end_tag(m.group(1).lower(), i)
                return m.end()
        self.refuse(i, f"{self.html[i:i + 30]!r} is outside the forms the build reads: write {EXPECTED}")

    def start_tag(self, m, i):
        tag, raw, body = m.group(1).lower(), m.group(0), m.end()
        attrs = {}
        for name, value in ATTRIBUTE.findall(m.group(2)):
            attrs.setdefault(name.lower(), value[1:-1] if value[:1] in "\"'" and value else value)
        if self.foreign and tag in NOT_IN_FOREIGN:
            self.refuse(i, f"the <{tag}> is inside <{self.foreign[-1]}>, where the browser reads what the build "
                           f"cannot follow: draw it with shapes and attributes only, and put its CSS and code in the "
                           f"theme's files")
        if tag in NOT_IN_PAGE or "srcdoc" in attrs:
            why = NOT_IN_PAGE.get(tag, "writes a page in an attribute, whose files the browser would fetch")
            self.refuse(i, f"the tag {raw[:60]!r} {why}: leave it out")
        if loose := [a for a in PLAIN_ATTRIBUTES if "&" in attrs.get(a, "")]:
            self.refuse(i, f"the {loose[0]} of the tag {raw[:60]!r} has an &: write the value itself")
        if tag in FOREIGN:
            if not m.group(3):
                self.foreign.append(tag)
            return body
        if self.foreign:
            return body
        if tag == "script" and "src" in attrs:
            return self.file_tag(i, raw, SCRIPT_TAG, "script", "</script>", attrs)
        if tag == "link":
            return self.link(i, raw, attrs)
        if tag not in BODY:
            return body
        if tag == "script" and attrs.get("type", "").strip(" \t\n\r\f").lower() not in SCRIPT_TYPES:
            self.refuse(i, f"the tag {raw!r} has a type the build does not read for certain (a module can import "
                           f"files the page would fetch): write a <script> without the type, with "
                           f"type=\"text/javascript\" or type=\"application/json\", or a file tag")
        if not (text := BODY[tag].match(self.html, body)):
            holds = "<!-- or " if tag == "script" else "a < or " if tag in TEXT_ONLY else ""
            self.refuse(i, f"the <{tag}> holds {holds}does not end in </{tag}>, which the browser can read differently")
        if tag == "style" and (problem := sheet_problem(text.group(0)[:-8], False)):
            self.refuse(i, f"the <style> has {problem}")
        if tag in ("script", "style"):
            self.elements.append((tag, {a: unescape(attrs[a]) for a in ("src", "href", "rel", "type") if a in attrs}))
        return text.end()

    def link(self, i, raw, attrs):
        rel = attrs.get("rel", "").lower().split()
        if "modulepreload" in rel or "prefetch" in rel or "preload" in rel and attrs.get("as", "").strip().lower() in (
                "script", "style"):
            self.refuse(i, f"the tag {raw!r} preloads or prefetches a file, which the browser would fetch: write the "
                           f"file tag")
        if "stylesheet" in rel:
            return self.file_tag(i, raw, SHEET_TAG, "style", "", attrs)
        self.elements.append(("link", {a: unescape(attrs[a]) for a in ("src", "href", "rel", "type") if a in attrs}))
        return i + len(raw)

    def file_tag(self, i, raw, canonical, kind, end, attrs):
        written = canonical.fullmatch(raw)
        if not written or not self.html.startswith(end, i + len(raw)):
            self.refuse(i, f"the tag {raw!r} is not <script src=\"...\"></script> or <link rel=\"stylesheet\" "
                           f"href=\"...\">, the only file tags the page puts inline")
        value = written.group(1)
        if loose := [m.group(0) for m in REFERENCE.finditer(value) if m.group(0)[1:] not in html5]:
            self.refuse(i, f"the tag {raw!r} has {loose[0]!r}, which is not a whole character reference the browser "
                           f"reads the same way")
        self.found.append((i, i + len(raw) + len(end), kind, unescape(value)))
        self.elements.append(("script" if kind == "script" else "link",
                              {a: unescape(attrs[a]) for a in ("src", "href", "rel", "type") if a in attrs}))
        return i + len(raw) + len(end)

    def end_tag(self, tag, i):
        if tag in FOREIGN and self.foreign:
            if self.foreign[-1] != tag:
                self.refuse(i, f"the </{tag}> does not close the <{self.foreign[-1]}> open there, which the browser "
                               f"keeps open: close it with </{self.foreign[-1]}>")
            self.foreign.pop()


@functools.lru_cache(maxsize=16)
def template(html):
    return Template(html)


def file_tags(html):
    return tuple(template(html).found)


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
    except OSError as ex:
        raise ThemePageError(f"{name} could not be read ({ex.strerror or type(ex).__name__}): close what holds it, "
                             f"or let the app read it") from ex


def inline_files(html, folder):
    parts, done = [], 0
    for start, end, tag, name in file_tags(html):
        try:
            parts += [html[done:start], f"<{tag}>\n{file_text(folder, tag, name)}</{tag}>"]
        except ThemePageError as ex:
            raise ThemePageError(str(ex), place(html, start)) from ex
        done = end
    return "".join(parts) + html[done:]


def file_text(folder, tag, name):
    path, text = theme_file(folder, name)
    if tag == "script" and text.startswith("#!"):
        raise ThemePageError(f"{name} starts with #!, which only a script file read on its own allows: remove that "
                             f"line")
    if closes := CLOSES_ELEMENT[tag].search(text):
        raise ThemePageError(f"{name} has {closes.group(0)}, which its <{tag}> cannot hold")
    if tag == "style" and (problem := sheet_problem(text, path.parent != folder.resolve())):
        raise ThemePageError(f"{name} has {problem}")
    return text


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
        where = shown(page) + (f":{ex.at[0]}:{ex.at[1]}" if ex.at else "")
        print(f"theme page: {where} was not built: {ex}", file=sys.stderr, flush=True)
        raise web.HTTPInternalServerError(text=f"{where} was not built: {ex}") from ex
    return html, f'"{hashlib.sha256(html.encode("utf-8")).hexdigest()[:32]}"'

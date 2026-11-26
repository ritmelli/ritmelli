import contextlib
import functools
import hashlib
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import i18n

THEMES = Path(__file__).resolve().parent / "themes"
SCRIPT_TAG = re.compile(r'<script src="([^"]+)">')
SHEET_TAG = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
CLOSES_ELEMENT = {"script": re.compile(r"</script|<!--", re.IGNORECASE), "style": re.compile(r"</style", re.IGNORECASE)}
IMPORT_RULE = re.compile(r"@import\b", re.IGNORECASE)
CSS_COMMENT_OR_STRING = re.compile(r"""/\*.*?(?:\*/|$)"""
                                   r"""|"(?P<double>[^"\\\n]*(?:\\(?:\r\n|.)[^"\\\n]*)*)"?"""
                                   r"""|'(?P<single>[^'\\\n]*(?:\\(?:\r\n|.)[^'\\\n]*)*)'?""", re.DOTALL)
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|(.))", re.DOTALL)
STRING_MARK = "\ue000"
URL_VALUE = re.compile(r"url\(\s*(?:" + STRING_MARK + r"(\d+)" + STRING_MARK + r"|([^)\s]*))", re.IGNORECASE)
NOT_RELATIVE = re.compile(r"\s*(?:[a-z][a-z0-9+.-]*:|/|#)", re.IGNORECASE)


def css_unescape(text):
    return CSS_ESCAPE.sub(lambda m: chr(min(int(m.group(1), 16), 0xFFFD)) if m.group(1) else m.group(2), text)


@functools.lru_cache(maxsize=256)
def sheet_problem(text, outside_page_folder):
    strings = []

    def token(m):
        body = m.group("double") if m.group("double") is not None else m.group("single")
        if body is None:
            return " "
        strings.append(css_unescape(body))
        return f"{STRING_MARK}{len(strings) - 1}{STRING_MARK}"
    plain = css_unescape(CSS_COMMENT_OR_STRING.sub(token, text))
    if IMPORT_RULE.search(plain):
        return "an @import, which the browser would fetch outside the page"
    for m in URL_VALUE.finditer(plain) if outside_page_folder else ():
        value = strings[int(m.group(1))] if m.group(1) is not None else m.group(2)
        if value.strip() and not NOT_RELATIVE.match(value):
            return "a relative url(), which the page would resolve from its own folder"
    return None


class ThemePageError(Exception):
    pass


class FileTags(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html, self.found = html, []
        self.lines = [0] + [m.end() for m in re.finditer("\n", html)]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        first = {}
        for name, value in attrs:
            first.setdefault(name, value)
        if tag == "script" and "src" in first:
            canonical, kind, end = SCRIPT_TAG, "script", "</script>"
        elif tag == "link" and "stylesheet" in (first.get("rel") or "").lower().split():
            canonical, kind, end = SHEET_TAG, "style", ""
        else:
            return
        raw = self.get_starttag_text()
        line, column = self.getpos()
        at = self.lines[line - 1] + column
        written = canonical.fullmatch(raw)
        if not written or not self.html.startswith(end, at + len(raw)):
            raise ThemePageError(f"the tag {raw!r} is not <script src=\"...\"></script> or "
                                 f"<link rel=\"stylesheet\" href=\"...\">, the only file tags the page puts inline")
        self.found.append((at, at + len(raw) + len(end), kind, written.group(1)))


@functools.lru_cache(maxsize=16)
def file_tags(html):
    return tuple(FileTags(html).found)


def theme_file(folder, name):
    inside = THEMES if name.startswith("/t/") else folder
    path = (inside / name.removeprefix("/t/")).resolve()
    if not path.is_relative_to(inside.resolve()):
        raise ThemePageError(f"{name} is outside {inside}")
    if not path.is_file():
        raise ThemePageError(f"{name} is missing from {inside}")
    return path, path.read_text(encoding="utf-8")


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
    with contextlib.suppress(OSError, ValueError):
        parts = (THEMES / rel).resolve().relative_to(THEMES.resolve()).parts
        if len(parts) == 2 and os.path.samefile(THEMES / rel, THEMES / parts[0] / "index.html"):
            return parts[0]
    return None


def build(page, texts, language):
    html = inline_files(i18n.injeta(page.read_text(encoding="utf-8"), texts, language), page.parent)
    return html, f'"{hashlib.sha256(html.encode("utf-8")).hexdigest()[:32]}"'

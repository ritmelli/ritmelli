import importlib
import re
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

import tree_sitter
import tree_sitter_javascript

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
theme_page = importlib.import_module("theme_page")

THEME = RAIZ / "themes" / "ritmelli"
TRIVIAL = re.compile(r"[\s{}()\[\];,]*")
RUN = 8
SHORTEST_FUNCTION = 40
JAVASCRIPT = ("", "text/javascript")
FONT_LOAD = re.compile(r"document\.fonts\.load\(\s*'[^']*(\"[^\"]+\")")
PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_javascript.language()))


def theme_files(folder):
    return sorted(p for p in folder.rglob("*.js") if "gerado" not in p.relative_to(folder).parts)


def copies(folder):
    seen = {}
    for path in theme_files(folder):
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if not TRIVIAL.fullmatch(line)]
        for i in range(len(lines) - RUN + 1):
            seen.setdefault(tuple(lines[i:i + RUN]), set()).add(path.relative_to(folder).as_posix())
    return sorted({tuple(sorted(files)) for files in seen.values() if len(files) > 1}), sum(
        len(files) > 1 for files in seen.values())


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def literal(node):
    return node.text.decode("utf-8")[1:-1] if node is not None and node.type == "string" else None


def text_of(node):
    return node.text.decode("utf-8")


def pattern_names(node):
    if node is None:
        return set()
    if node.type in ("identifier", "shorthand_property_identifier_pattern"):
        return {text_of(node)}
    if node.type == "pair_pattern":
        return pattern_names(node.child_by_field_name("value"))
    if node.type == "assignment_pattern":
        return pattern_names(node.child_by_field_name("left"))
    return set().union(*(pattern_names(child) for child in node.named_children))


NAMED = {"variable_declarator": "name", "function_declaration": "name", "function_expression": "name",
         "generator_function_declaration": "name", "class_declaration": "name", "class": "name",
         "arrow_function": "parameter", "catch_clause": "parameter", "pair_pattern": "value",
         "assignment_pattern": "left", "for_in_statement": "left"}
FUNCTIONS = ("arrow_function", "function_expression", "function", "function_declaration", "generator_function",
             "generator_function_declaration", "class", "class_declaration")


def ancestors(node):
    while (node := node.parent) is not None:
        yield node


def binds(node):
    parent = node.parent
    return parent is not None and (
        NAMED.get(parent.type) is not None and parent.child_by_field_name(NAMED[parent.type]) == node
        and (parent.type != "for_in_statement" or parent.child_by_field_name("kind") is not None)
        or parent.type in ("formal_parameters", "array_pattern", "rest_pattern"))


def refers(node):
    parent = node.parent
    if parent is not None and parent.type == "export_specifier" and parent.child_by_field_name("alias") == node:
        return False
    return not any(a.type == "import_statement" or a.type == "export_statement" and a.child_by_field_name("source")
                   for a in ancestors(node))


def names_in(root):
    reads, bound = set(), {}
    for node in walk(root):
        if node.type in ("identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"):
            name = text_of(node)
            if node.type == "shorthand_property_identifier_pattern" or binds(node):
                bound.setdefault(name, node.start_point[0] + 1)
            elif refers(node):
                reads.add(name)
    return reads, bound


def imported_names(root):
    imported = set()
    for node in walk(root):
        if node.type == "import_specifier":
            imported.add(text_of(node.child_by_field_name("alias") or node.child_by_field_name("name")))
        elif node.type in ("import_clause", "namespace_import"):
            imported |= {text_of(child) for child in node.named_children if child.type == "identifier"}
    return imported


def declared(node):
    if node.type in ("lexical_declaration", "variable_declaration"):
        return {name: d.child_by_field_name("value") for d in node.named_children if d.type == "variable_declarator"
                for name in pattern_names(d.child_by_field_name("name"))}
    if node.type in FUNCTIONS and (named := node.child_by_field_name("name")) is not None:
        return {text_of(named): node}
    return {}


def normalized(function):
    return re.sub(r"\s+", " ", text_of(function).split("=>", 1)[-1] if function.type == "arrow_function" else
                  text_of(function.child_by_field_name("body") or function)).strip() + "|" + re.sub(
        r"\s+", " ", text_of(function.child_by_field_name("parameters") or function.child_by_field_name("parameter")
                             or function))


def file_facts(text):
    root = PARSER.parse(text.encode("utf-8")).root_node
    facts = types.SimpleNamespace(imports={}, exports=set(), stars=set(), problems=[], top=set(), values={},
                                  functions=[])
    for node in walk(root):
        if node.type in ("import_statement", "export_statement") and (source := node.child_by_field_name("source")):
            if (name := literal(source)) is None:
                facts.problems.append(f"an import from {text_of(source)!r}, which is not a plain string")
                continue
            used = facts.imports.setdefault(name, set())
            for part in walk(node):
                if part.type == "import_clause" and any(c.type == "identifier" for c in part.named_children):
                    used.add("default")
                elif part.type in ("import_specifier", "export_specifier"):
                    used.add(text_of(part.child_by_field_name("name")))
                elif part.type in ("namespace_import", "namespace_export") or (
                        part.type == "export_statement" and any(c.type == "*" for c in part.children)):
                    used.add("*")
            if node.type == "export_statement" and any(c.type == "*" for c in node.children) and not any(
                    c.type == "namespace_export" for c in node.children):
                facts.stars.add(name)
        elif node.type == "call_expression" and node.child_by_field_name("function").type == "import":
            facts.problems.append(f"a dynamic import() at line {node.start_point[0] + 1}, which the page's import map "
                                  f"does not hold for certain")
        if node.type in FUNCTIONS and len(normalized(node)) >= SHORTEST_FUNCTION:
            facts.functions.append((normalized(node), node.start_point[0] + 1))
        if node.type == "export_statement":
            if any(c.type == "default" for c in node.children):
                facts.exports.add("default")
            elif (declaration := node.child_by_field_name("declaration")) is not None:
                facts.values |= declared(declaration)
                facts.exports |= set(declared(declaration))
            for part in walk(node):
                if part.type == "export_specifier":
                    facts.exports.add(text_of(part.child_by_field_name("alias") or part.child_by_field_name("name")))
                elif part.type == "namespace_export":
                    facts.exports |= {text_of(c) for c in part.named_children if c.type == "identifier"}
    for node in root.named_children:
        facts.top |= set(declared(node.child_by_field_name("declaration") or node)
                         if node.type == "export_statement" else declared(node))
    imported = imported_names(root)
    facts.top |= imported
    facts.reads, bound = names_in(root)
    facts.bound = set(bound)
    facts.problems += [f"imports {name}, which it never uses" for name in sorted(imported - facts.reads - set(bound))]
    facts.problems += [f"declares {name} again at line {bound[name]}, over its import"
                       for name in sorted(imported & set(bound))]
    return facts


def provided(facts, name, seen=frozenset()):
    return facts[name].exports | set().union(*(provided(facts, star, seen | {name}) - {"default"}
                                               for star in facts[name].stars if star in facts and star not in seen))


def classic_texts(folder, read):
    inline = [attrs for tag, attrs in read.elements if tag in ("script", "style") and "src" not in attrs]
    texts = [(f"the inline script {n}", text) for n, ((tag, text), attrs) in enumerate(zip(read.texts, inline), 1)
             if tag == "script" and attrs.get("type", "").strip(" \t\n\r\f").lower() in JAVASCRIPT]
    return texts + [(name, theme_page.theme_file(folder, name)[1])
                    for _, _, kind, name in read.found if kind == "script"]


def data_problems(facts):
    problems = []
    for name, own in facts.items():
        if not any(value is not None and value.type in FUNCTIONS for value in own.values.values()):
            continue
        for export, value in sorted(own.values.items()):
            users = [other for other, theirs in facts.items() if other != name and export in theirs.imports.get(name, ())]
            if (value is None or value.type not in FUNCTIONS) and export not in own.reads and len(users) == 1:
                problems.append(f"{name}: exports {export}, data only {users[0]} uses: keep it in {users[0]}")
    return problems


def rewritten(folder, facts):
    exported = {text: (name, export) for name, own in facts.items() for export, value in own.values.items()
                if value is not None and value.type in FUNCTIONS for text in [normalized(value)]}
    problems = []
    for path in theme_files(folder):
        file = path.relative_to(folder).as_posix()
        for text, line in file_facts(path.read_text(encoding="utf-8-sig")).functions:
            if text in exported and exported[text][0] != file:
                problems.append(f"{file}:{line}: writes again {exported[text][1]}, which {exported[text][0]} exports: "
                                f"import it")
    return problems


def module_problems(folder, page):
    read, error = theme_page.strict(page)
    if error:
        return [f"index.html:{error[0]}:{error[1]}: {error[2]}"]
    names = [name for _, _, kind, name in read.found if kind == "module"]
    facts = {name: file_facts((folder / name).read_text(encoding="utf-8-sig")) for name in names}
    classics = [(name, file_facts(text)) for name, text in classic_texts(folder, read)]
    problems = [f"{name}: {problem}" for name, own in classics for problem in own.problems
                if "dynamic import()" in problem]
    problems += [f"{name}: {problem}" for name, own in facts.items() for problem in own.problems]
    problems += [f"{name}: imports {target}, which is not a module of the page" for name, own in facts.items()
                 for target in own.imports if target not in facts]
    problems += [f"{name}: imports {wanted} from {target}, which {target} does not export" for name, own in facts.items()
                 for target, wanted_names in own.imports.items() if target in facts
                 for wanted in sorted(wanted_names - provided(facts, target) - {"*"})]
    for name, own in facts.items():
        used = set().union(*(theirs.imports.get(name, set()) for other, theirs in facts.items() if other != name))
        problems += [f"{name}: exports {export}, which no other file of the theme imports"
                     for export in sorted(own.exports) if export not in used and "*" not in used]
    classic_top = set().union(*(own.top for _, own in classics))
    for name, own in classics:
        for read_name in sorted(own.reads - own.bound - classic_top):
            if owners := [module for module, theirs in facts.items() if read_name in theirs.top]:
                problems.append(f"{name}: reads {read_name}, which only the module {owners[0]} declares: a classic "
                                f"script does not see a module's names")
    return problems + data_problems(facts) + rewritten(folder, facts)


def engine_fonts(folder):
    engine = (folder / "pixel.js").read_text(encoding="utf-8")
    families = set(re.findall(r"fam: '(\"[^\"]+\")'", engine))
    return families, [f"{path.relative_to(folder).as_posix()}: loads {family}, which pixel.js's fontesProntas loads"
                      for path in theme_files(folder) if path.name != "pixel.js"
                      for family in FONT_LOAD.findall(path.read_text(encoding="utf-8")) if family in families]


def samples():
    results = []
    with tempfile.TemporaryDirectory(prefix="ritmelli-modules-") as t:
        folder = Path(t)
        block = "\n".join(f"const v{n} = paint({n});" for n in range(RUN))
        (folder / "a.js").write_text(f"{block}\n", encoding="utf-8")
        (folder / "b.js").write_text(f"start();\n  {block.replace(chr(10), chr(10) + '  ')}\n", encoding="utf-8")
        (folder / "c.js").write_text("{\n}\n" + "\n".join(f"other({n});" for n in range(RUN)) + "\n", encoding="utf-8")
        pairs, count = copies(folder)
        results.append((count == 1 and pairs == [("a.js", "b.js")],
                        f"a block of {RUN} lines in two files is found, even indented otherwise ({count}, {pairs})"))
        for name in ("a.js", "b.js", "c.js"):
            (folder / name).unlink()
        b = 'export const b = () => {};\n'
        body = "x => { return x * 2 + 1 + x * 3 + x * 4 + x * 5; }"
        long = f"export const f = {body};\n"
        cases = {
            "an import of a module the page does not tag": ('import { a } from "gone.js";\na();\n', "go();\n", "", "",
                                                            ["a.js: imports gone.js"]),
            "a dynamic import()": ('import("b.js").then(() => {});\n', "go();\n", "", "", ["a.js: a dynamic import()"]),
            "a dynamic import() in a classic script": ('import { b } from "b.js";\nb();\n', b, 'import("b.js");\n', "",
                                                        ["c.js: a dynamic import()"]),
            "an export no file imports": ('export const unused = 1;\nimport { b } from "b.js";\nb();\n', b, "", "",
                                          ["a.js: exports unused"]),
            "an import it never uses": ('import { b } from "b.js";\n', b, "", "", ["a.js: imports b, which it never uses"]),
            "an import declared again": ('import { b } from "b.js";\nconst f = b => b;\nf();\n', b, "", "",
                                         ["a.js: declares b again"]),
            "an import declared again in a pattern": ('import { b } from "b.js";\nconst f = ({ key: b }) => b;\nf();\n',
                                                      b, "", "", ["a.js: declares b again"]),
            "an import declared again in a for of": ('import { b } from "b.js";\nfor (const b of []) b();\n', b, "", "",
                                                     ["a.js: declares b again"]),
            "an import declared again as a class name": ('import { b } from "b.js";\nconst k = class b {};\nnew k();\n',
                                                         b, "", "", ["a.js: declares b again"]),
            "an import only exported again from another module": (
                'import { b } from "b.js";\nexport { b as y } from "b.js";\n', b, "", 'import { y } from "a.js";\ny();\n',
                ["a.js: imports b, which it never uses"]),
            "an import exported again by another name": ('import { b } from "b.js";\nexport { b as y };\n', b, "",
                                                         'import { y } from "a.js";\ny();\n', []),
            "a local name exported under an import's name": (
                'import { b } from "b.js";\nconst a = 1;\nexport { a as b };\n', b, "", 'import { b } from "a.js";\nb();\n',
                ["a.js: imports b, which it never uses"]),
            "an import of a name the module does not export": ('import { b, c } from "b.js";\nb(c);\n', b, "", "",
                                                               ["a.js: imports c from b.js, which b.js does not export"]),
            "a default import of a module without one": ('import f from "b.js";\nf();\n', b, "", "",
                                                         ["a.js: imports default from b.js", "b.js: exports b"]),
            "a name re-exported through export *": ('import { d } from "b.js";\nd();\n', 'export * from "d.js";\n', "",
                                                    'export const d = () => {};\n', []),
            "a name export * does not bring": ('import { e } from "b.js";\ne();\n', 'export * from "d.js";\n', "",
                                               'export const d = () => {};\n',
                                               ["a.js: imports e from b.js"]),
            "a default export, imported": ('import f from "b.js";\nf();\n', "export default function named() {}\n", "",
                                           "", []),
            "a default export no file imports": ("go();\n", "export default 1;\n", "", "", ["b.js: exports default"]),
            "a named re-export no file imports": ('export { b } from "b.js";\n', b, "", "", ["a.js: exports b"]),
            "a destructured export, imported": ('import { p, q } from "b.js";\np(q);\n',
                                                "const o = {};\nexport const { p, q } = o;\n", "", "", []),
            "a module of the page that imports and is imported": ('import { b } from "b.js";\nb();\n', b, "", "", []),
            "a classic script that reads a module's name": ('import { b } from "b.js";\nb();\n', b,
                                                            "function g() { return b; }\ng();\n", "",
                                                            ["c.js: reads b, which only the module"]),
            "a classic script with a name of its own like a module's": ('import { b } from "b.js";\nb();\n', b,
                                                                        "const b = 1;\ngo(b);\n", "", []),
            "data an engine exports for one file only": (
                'import { f, T } from "b.js";\nf(T);\n', 'export const f = () => {};\nexport const T = 1;\n', "", "",
                ["b.js: exports T, data only a.js uses: keep it in a.js"]),
            "data an engine exports and uses itself": ('import { f, T } from "b.js";\nf(T);\n',
                                                       'export const f = () => T;\nexport const T = 1;\n', "", "", []),
            "a function a module exports, written again": (
                f'import {{ f }} from "b.js";\nconst g = {body};\nf(g(1));\n', long, "", "",
                ["a.js:2: writes again f, which b.js exports"]),
        }
        page = ('<script src="c.js"></script>\n<script type="module" src="a.js"></script>\n'
                '<script type="module" src="b.js"></script>\n<script type="module" src="d.js"></script>\n')
        for what, (a_text, b_text, c_text, d_text, expected) in cases.items():
            for name, text in (("a.js", a_text), ("b.js", b_text), ("c.js", c_text or "go();\n"), ("d.js", d_text)):
                (folder / name).write_text(text, encoding="utf-8")
            found = module_problems(folder, page)
            results.append((len(found) == len(expected) and all(any(e in p for p in found) for e in expected),
                            f"{what}: {found or 'no problem'}"))
        (folder / "a.js").write_text('import { b } from "b.js";\nb();\n', encoding="utf-8")
        (folder / "b.js").write_text(b, encoding="utf-8")
        (folder / "d.js").write_text("", encoding="utf-8")
        (folder / "c.js").write_text("go();\n", encoding="utf-8")
        inline = module_problems(folder, '<script>import("b.js");</script>\n<script type="application/json">{"a": 1}'
                                         '</script>\n' + page)
        results.append((len(inline) == 1 and "the inline script 1: a dynamic import()" in inline[0],
                        f"a dynamic import() in an inline classic script, and none read in a data block: {inline}"))
        (folder / "other").mkdir()
        (folder / "other" / "x.js").write_text('import("b.js");\n', encoding="utf-8")
        with mock.patch.object(theme_page, "THEMES", folder):
            shared = module_problems(folder, '<script src="/t/other/x.js"></script>\n' + page)
        results.append((len(shared) == 1 and "/t/other/x.js: a dynamic import()" in shared[0],
                        f"a dynamic import() in a classic script of another theme's folder: {shared}"))
        (folder / "pixel.js").write_text("const FONTES = { j: { fam: '\"Jersey 10\"', S: 300 } };\n", encoding="utf-8")
        (folder / "c.js").write_text("document.fonts.load('300px \"Jersey 10\"');\n", encoding="utf-8")
        families, loads = engine_fonts(folder)
        results.append((families == {'"Jersey 10"'} and len(loads) == 1 and loads[0].startswith("c.js: loads"),
                        f"a font of the engine loaded outside it: {loads}"))
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = samples()
    pairs, count = copies(THEME)
    results.append((count == 0, f"no run of {RUN} equal lines is in two files of the theme ({count}; {pairs})"))
    problems = module_problems(THEME, (THEME / "index.html").read_text(encoding="utf-8"))
    results.append((not problems, f"each module of the theme imports only modules of the page and names they export, "
                                  f"uses each name it imports, has its exports imported by another file and keeps "
                                  f"data one file uses in that file; no classic script reads a module's name or calls "
                                  f"import(), and no file writes again a function a module exports "
                                  f"({problems or 'all of them'})"))
    families, loads = engine_fonts(THEME)
    results.append((families and not loads, f"the engine's fonts ({', '.join(sorted(families))}) are loaded by "
                                            f"pixel.js only ({loads or 'none elsewhere'})"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

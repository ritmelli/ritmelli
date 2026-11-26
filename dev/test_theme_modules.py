import importlib
import re
import sys
import tempfile
from pathlib import Path

import tree_sitter
import tree_sitter_javascript

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
theme_page = importlib.import_module("theme_page")

THEME = RAIZ / "themes" / "ritmelli"
TRIVIAL = re.compile(r"[\s{}()\[\];,]*")
RUN = 8
PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_javascript.language()))


def copies(folder):
    seen = {}
    for path in sorted(p for p in folder.rglob("*.js") if "gerado" not in p.relative_to(folder).parts):
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
         "class_declaration": "name", "arrow_function": "parameter", "catch_clause": "parameter"}


def ancestors(node):
    while (node := node.parent) is not None:
        yield node


def binds(node):
    parent = node.parent
    return parent is not None and (
        NAMED.get(parent.type) is not None and parent.child_by_field_name(NAMED[parent.type]) == node
        or parent.type in ("formal_parameters", "array_pattern", "rest_pattern")
        or parent.type == "assignment_pattern" and parent.child_by_field_name("left") == node)


def import_problems(root):
    imported = set()
    for node in walk(root):
        if node.type == "import_specifier":
            imported.add(text_of(node.child_by_field_name("alias") or node.child_by_field_name("name")))
        elif node.type in ("import_clause", "namespace_import"):
            imported |= {text_of(child) for child in node.named_children if child.type == "identifier"}
    used, bound = set(), {}
    for node in walk(root):
        if node.type in ("identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"):
            name = text_of(node)
            if node.type == "shorthand_property_identifier_pattern" or binds(node):
                bound.setdefault(name, node.start_point[0] + 1)
            elif not any(a.type == "import_statement" for a in ancestors(node)):
                used.add(name)
    return [f"imports {name}, which it never uses" for name in sorted(imported - used - set(bound))] + [
        f"declares {name} again at line {bound[name]}, over its import" for name in sorted(imported & set(bound))]


def module_facts(text):
    root = PARSER.parse(text.encode("utf-8")).root_node
    imports, exports, problems = {}, set(), []
    for node in walk(root):
        if node.type in ("import_statement", "export_statement") and (source := node.child_by_field_name("source")):
            if (name := literal(source)) is None:
                problems.append(f"an import from {text_of(source)!r}, which is not a plain string")
                continue
            used = imports.setdefault(name, set())
            for part in walk(node):
                if part.type == "import_clause" and any(c.type == "identifier" for c in part.named_children):
                    used.add("default")
                elif part.type in ("import_specifier", "export_specifier"):
                    used.add(text_of(part.child_by_field_name("name")))
                elif part.type in ("namespace_import", "namespace_export") or (
                        part.type == "export_statement" and any(c.type == "*" for c in part.children)):
                    used.add("*")
        elif node.type == "call_expression" and node.child_by_field_name("function").type == "import":
            problems.append(f"a dynamic import() at line {node.start_point[0] + 1}, which the page's import map does "
                            f"not hold for certain")
        if node.type == "export_statement":
            if any(c.type == "default" for c in node.children):
                exports.add("default")
            elif (declaration := node.child_by_field_name("declaration")) is not None:
                if declaration.type in ("lexical_declaration", "variable_declaration"):
                    for d in declaration.named_children:
                        if d.type == "variable_declarator":
                            exports |= pattern_names(d.child_by_field_name("name"))
                elif (named := declaration.child_by_field_name("name")) is not None:
                    exports.add(text_of(named))
            for part in walk(node):
                if part.type == "export_specifier":
                    exports.add(text_of(part.child_by_field_name("alias") or part.child_by_field_name("name")))
                elif part.type == "namespace_export":
                    exports |= {text_of(c) for c in part.named_children if c.type == "identifier"}
    return imports, exports, problems + import_problems(root)


def module_problems(folder, page):
    read, error = theme_page.strict(page)
    if error:
        return [f"index.html:{error[0]}:{error[1]}: {error[2]}"]
    scripts = [name for _, _, kind, name in read.found if kind == "script" and not name.startswith("/t/")]
    names = [name for _, _, kind, name in read.found if kind == "module"]
    facts = {name: module_facts((folder / name).read_text(encoding="utf-8-sig")) for name in names}
    problems = [f"{name}: {problem}" for name in scripts
                for problem in module_facts((folder / name).read_text(encoding="utf-8-sig"))[2]
                if "dynamic import()" in problem]
    problems += [f"{name}: {problem}" for name, (_, _, found) in facts.items() for problem in found]
    problems += [f"{name}: imports {target}, which is not a module of the page" for name, (imports, _, _) in
                 facts.items() for target in imports if target not in facts]
    for name, (_, exports, _) in facts.items():
        used = set().union(*(imports.get(name, set()) for other, (imports, _, _) in facts.items() if other != name))
        problems += [f"{name}: exports {export}, which no other file of the theme imports" for export in sorted(exports)
                     if export not in used and "*" not in used]
    return problems


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
        b = 'export const b = () => {};\n'
        cases = {
            "an import of a module the page does not tag": ('import { a } from "gone.js";\na();\n', "go();\n", "",
                                                            ["a.js: imports gone.js"]),
            "a dynamic import()": ('import("b.js").then(() => {});\n', "go();\n", "", ["a.js: a dynamic import()"]),
            "a dynamic import() in a classic script": ('import { b } from "b.js";\nb();\n', b, 'import("b.js");\n',
                                                        ["c.js: a dynamic import()"]),
            "an export no file imports": ('export const unused = 1;\nimport { b } from "b.js";\nb();\n', b, "",
                                          ["a.js: exports unused"]),
            "an import it never uses": ('import { b } from "b.js";\n', b, "", ["a.js: imports b, which it never uses"]),
            "an import declared again": ('import { b } from "b.js";\nconst f = b => b;\nf();\n', b, "",
                                         ["a.js: declares b again"]),
            "a default export, imported": ('import f from "b.js";\nf();\n', "export default function named() {}\n", "",
                                           []),
            "a default export no file imports": ("go();\n", "export default 1;\n", "", ["b.js: exports default"]),
            "a named re-export no file imports": ('export { b } from "b.js";\n', b, "", ["a.js: exports b"]),
            "a destructured export, imported": ('import { p, q } from "b.js";\np(q);\n',
                                                "const o = {};\nexport const { p, q } = o;\n", "", []),
            "a module of the page that imports and is imported": ('import { b } from "b.js";\nb();\n', b, "", []),
        }
        page = ('<script src="c.js"></script>\n<script type="module" src="a.js"></script>\n'
                '<script type="module" src="b.js"></script>\n')
        for what, (a_text, b_text, c_text, expected) in cases.items():
            for name, text in (("a.js", a_text), ("b.js", b_text), ("c.js", c_text or "go();\n")):
                (folder / name).write_text(text, encoding="utf-8")
            found = module_problems(folder, page)
            results.append((len(found) == len(expected) and all(any(e in p for p in found) for e in expected),
                            f"{what}: {found or 'no problem'}"))
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = samples()
    pairs, count = copies(THEME)
    results.append((count == 0, f"no run of {RUN} equal lines is in two files of the theme ({count}; {pairs})"))
    problems = module_problems(THEME, (THEME / "index.html").read_text(encoding="utf-8"))
    results.append((not problems, f"each module of the theme imports only modules of the page, by name, and each of "
                                  f"its exports is imported by another file ({problems or 'all of them'})"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

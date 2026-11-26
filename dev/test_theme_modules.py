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


def module_facts(text):
    tree = PARSER.parse(text.encode("utf-8"))
    imports, exports, problems = {}, set(), []
    for node in walk(tree.root_node):
        if node.type in ("import_statement", "export_statement") and (source := node.child_by_field_name("source")):
            if (name := literal(source)) is None:
                problems.append(f"an import from {source.text.decode('utf-8')!r}, which is not a plain string")
                continue
            used = imports.setdefault(name, set())
            for part in walk(node):
                if part.type == "import_specifier":
                    used.add(part.child_by_field_name("name").text.decode("utf-8"))
                elif part.type == "namespace_import" or part.type == "export_statement" and "*" in [
                        c.type for c in part.children]:
                    used.add("*")
                elif part.type == "export_specifier":
                    used.add(part.child_by_field_name("name").text.decode("utf-8"))
        elif node.type == "call_expression" and node.child_by_field_name("function").type == "import":
            problems.append(f"a dynamic import() at line {node.start_point[0] + 1}, which the page's import map does "
                            f"not hold for certain")
        if node.type == "export_statement" and node.child_by_field_name("source") is None:
            if (declaration := node.child_by_field_name("declaration")) is not None:
                if declaration.type in ("lexical_declaration", "variable_declaration"):
                    exports |= {d.child_by_field_name("name").text.decode("utf-8") for d in declaration.named_children
                                if d.type == "variable_declarator"}
                elif (named := declaration.child_by_field_name("name")) is not None:
                    exports.add(named.text.decode("utf-8"))
            exports |= {(s.child_by_field_name("alias") or s.child_by_field_name("name")).text.decode("utf-8")
                        for s in walk(node) if s.type == "export_specifier"}
    return imports, exports, problems


def module_problems(folder, page):
    read, error = theme_page.strict(page)
    if error:
        return [f"index.html:{error[0]}:{error[1]}: {error[2]}"]
    names = [name for _, _, kind, name in read.found if kind == "module"]
    facts = {name: module_facts((folder / name).read_text(encoding="utf-8")) for name in names}
    problems = [f"{name}: {problem}" for name, (_, _, found) in facts.items() for problem in found]
    problems += [f"{name}: imports {target}, which is not a module of the page" for name, (imports, _, _) in
                 facts.items() for target in imports if target not in facts]
    for name, (_, exports, _) in facts.items():
        used = set().union(*(imports.get(name, set()) for imports, _, _ in facts.values()))
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
        cases = {
            "an import of a module the page does not tag": ('import { a } from "gone.js";\n', ["imports gone.js"]),
            "a dynamic import()": ('import("b.js").then(() => {});\n', ["a dynamic import()"]),
            "an export no file imports": ("export const unused = 1;\n", ["exports unused"]),
            "a module of the page that imports and is imported": ('import { b } from "b.js";\nb();\n', []),
        }
        (folder / "b.js").write_text("export const b = () => {};\n", encoding="utf-8")
        page = '<script type="module" src="a.js"></script>\n<script type="module" src="b.js"></script>\n'
        for what, (text, expected) in cases.items():
            (folder / "a.js").write_text(text, encoding="utf-8")
            found = [p for p in module_problems(folder, page) if not p.startswith("b.js: exports b")]
            results.append((len(found) == len(expected) and all(e in p for e, p in zip(expected, found)),
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

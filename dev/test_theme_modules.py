import collections
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
FEWEST_KEYS = 3
JAVASCRIPT = ("", "text/javascript")
PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_javascript.language()))
DEFAULTS = ("assignment_pattern", "object_assignment_pattern")
PATTERNS = ("array_pattern", "object_pattern", "rest_pattern", "pair_pattern", *DEFAULTS)
FUNCTIONS = ("arrow_function", "function_expression", "function", "function_declaration", "generator_function",
             "generator_function_declaration", "class", "class_declaration")
NAMED = ("function_expression", "function", "function_declaration", "generator_function",
         "generator_function_declaration", "class", "class_declaration")
FUNCTION_SCOPES = ("program", "function_declaration", "function_expression", "function", "arrow_function",
                   "generator_function", "generator_function_declaration", "method_definition")
BLOCK_SCOPES = (*FUNCTION_SCOPES, "statement_block", "for_statement", "for_in_statement", "switch_body", "class_body",
                "catch_clause", "class", "class_declaration")
NAMES = ("identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern")
BOUND_LEAVES = ("identifier",)
WRITTEN_LEAVES = ("identifier", "member_expression", "subscript_expression")
PATTERN_KEYS = ("property_identifier", "string", "number")
PLAIN_NAME = re.compile(r"#?[A-Za-z_$][A-Za-z0-9_$]*")
NAME_NODES = ("identifier", "property_identifier", "shorthand_property_identifier",
              "shorthand_property_identifier_pattern", "statement_identifier", "private_property_identifier")


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


def key(node):
    return node.start_byte, node.end_byte, node.type


def ancestors(node):
    while (node := node.parent) is not None:
        yield node


def pattern_nodes(node):
    if node is None:
        return []
    if node.type in ("identifier", "shorthand_property_identifier_pattern"):
        return [node]
    if node.type == "pair_pattern":
        return pattern_nodes(node.child_by_field_name("value"))
    if node.type in DEFAULTS:
        return pattern_nodes(node.child_by_field_name("left"))
    if node.type in ("array_pattern", "object_pattern", "rest_pattern"):
        return [found for child in node.named_children for found in pattern_nodes(child)]
    return []


def pattern_names(node):
    return {text_of(found) for found in pattern_nodes(node)}


def owner(node):
    current = node
    while (parent := current.parent) is not None and parent.type in PATTERNS:
        if parent.type == "pair_pattern" and parent.child_by_field_name("value") != current:
            return None
        if parent.type in DEFAULTS and parent.child_by_field_name("left") != current:
            return None
        current = parent
    if parent is None:
        return None
    if parent.type == "variable_declarator":
        return parent if parent.child_by_field_name("name") == current else None
    if parent.type == "for_in_statement":
        return parent if parent.child_by_field_name("left") == current and parent.child_by_field_name("kind") else None
    if parent.type in ("catch_clause", "arrow_function"):
        return parent if parent.child_by_field_name("parameter") == current else None
    if parent.type == "formal_parameters":
        return parent
    if parent.type in NAMED and current == node:
        return parent if parent.child_by_field_name("name") == node else None
    return None


def nearest(node, kinds):
    return next(a for a in ancestors(node) if a.type in kinds)


def scope_of(own):
    if own.type == "variable_declarator":
        declaration = own.parent
        return nearest(declaration, FUNCTION_SCOPES if declaration.type == "variable_declaration" else BLOCK_SCOPES)
    if own.type == "formal_parameters":
        return own.parent
    if own.type in ("function_declaration", "generator_function_declaration", "class_declaration"):
        return nearest(own, BLOCK_SCOPES)
    if own.type == "for_in_statement" and text_of(own.child_by_field_name("kind")) == "var":
        return nearest(own, FUNCTION_SCOPES)
    return own


def refers(node):
    return not any(a.type == "import_statement" for a in ancestors(node))


def unallowed(node):
    parts = [c for c in node.children if c.type != "comment"]
    if node.type == "import_statement":
        if [c.type for c in parts] not in (["import", "import_clause", "from", "string"],
                                           ["import", "import_clause", "from", "string", ";"]):
            return next((c for c in parts if c.type not in ("import", "import_clause", "from", "string", ";")), node)
        clause = [c for c in parts[1].named_children if c.type != "comment"]
        if len(clause) != 1 or clause[0].type != "named_imports":
            return clause[0] if clause else parts[1]
        return next((s for s in clause[0].named_children if s.type != "comment" and (
            s.type != "import_specifier" or s.child_by_field_name("alias") is not None
            or s.child_by_field_name("name").type != "identifier")), None)
    declaration = node.child_by_field_name("declaration")
    if len(parts) != 2 or declaration is None:
        return next((c for c in parts[1:] if c != declaration), node)
    if declaration.type == "function_declaration":
        return None
    if declaration.type != "lexical_declaration" or declaration.children[0].type != "const":
        return declaration
    return next((d.child_by_field_name("name") for d in declaration.named_children if d.type == "variable_declarator"
                 and d.child_by_field_name("name").type != "identifier"), None)


def allowed_imports(root):
    return [(node, literal(node.child_by_field_name("source")),
             [s.child_by_field_name("name") for s in walk(node) if s.type == "import_specifier"])
            for node in walk(root) if node.type == "import_statement" and unallowed(node) is None]


def declared(node):
    if node.type in ("lexical_declaration", "variable_declaration"):
        return {name: d.child_by_field_name("value") for d in node.named_children if d.type == "variable_declarator"
                for name in pattern_names(d.child_by_field_name("name"))}
    if node.type in FUNCTIONS and (named := node.child_by_field_name("name")) is not None:
        return {text_of(named): node}
    return {}


def bindings(root):
    scopes, lines, references = collections.defaultdict(set), {}, []
    for node in walk(root):
        if node.type not in NAMES:
            continue
        own = owner(node) if node.type != "shorthand_property_identifier" else None
        if own is not None:
            scopes[text_of(node)].add(key(scope_of(own)))
            lines.setdefault(text_of(node), node.start_point[0] + 1)
        elif refers(node):
            references.append(node)
    return scopes, lines, references


def resolved(node, scopes):
    return next((key(a) for a in ancestors(node) if key(a) in scopes.get(text_of(node), ())), None)


def normalized(function):
    scopes, declared_at = collections.defaultdict(set), {}
    for node in walk(function):
        if node.type in NAMES and node.type != "shorthand_property_identifier" and (own := owner(node)) is not None:
            scopes[text_of(node)].add(where := key(scope_of(own)))
            declared_at[key(node)] = where
    names, leaves = {}, []
    for node in walk(function):
        if node.children or node.type == "comment":
            continue
        if node.type not in NAMES:
            leaves.append(text_of(node))
            continue
        name = text_of(node)
        where = declared_at.get(key(node)) or resolved(node, scopes)
        renamed = names.setdefault((name, where), f"${len(names)}") if where else name
        leaves.append(renamed if node.type == "identifier" else f"{name}:{renamed}")
    return " ".join(leaves)


def key_text(node):
    return literal(node) if node.type == "string" else text_of(node)


def object_keys(node):
    found = set()
    for child in node.named_children:
        if child.type == "comment":
            continue
        if child.type == "pair":
            found.add(key_text(child.child_by_field_name("key")))
        elif child.type == "shorthand_property_identifier":
            found.add(text_of(child))
        else:
            return None
    return frozenset(found) if len(found) >= FEWEST_KEYS else None


def object_values(node):
    found = {}
    for child in node.named_children:
        if child.type == "pair":
            value = child.child_by_field_name("value")
            found[key_text(child.child_by_field_name("key"))] = value if value.type == "identifier" else None
        elif child.type == "shorthand_property_identifier":
            found[text_of(child)] = child
    return {k: v for k, v in found.items() if v is not None}


def destructured_keys(pattern):
    found = []
    for part in pattern.named_children if pattern.type == "object_pattern" else []:
        if part.type == "shorthand_property_identifier_pattern":
            found.append((part, text_of(part)))
        elif part.type == "object_assignment_pattern" and (left := part.child_by_field_name("left")).type == \
                "shorthand_property_identifier_pattern":
            found.append((left, text_of(left)))
        elif part.type == "pair_pattern":
            value = part.child_by_field_name("value")
            while value.type in DEFAULTS:
                value = value.child_by_field_name("left")
            if value.type == "identifier":
                found.append((value, key_text(part.child_by_field_name("key"))))
    return found


STRICT_NAMES = frozenset({"arguments", "eval", "yield", "await", "let", "static", "implements", "interface", "package",
                          "private", "protected", "public"})


def module_only(root):
    bound = [n for what, node, _ in places(root) if what == "binding" for n in pattern_nodes(node)]
    bound += [name for _, _, names in allowed_imports(root) for name in names]
    found = [f"binds {text_of(n)} at line {n.start_point[0] + 1}, which a module, in strict mode, refuses"
             for n in bound if text_of(n) in STRICT_NAMES]
    found += [f"writes {text_of(n)} at line {n.start_point[0] + 1}, which a module, in strict mode, refuses"
              for what, node, _ in places(root) if what == "write"
              for n in pattern_nodes(node) if text_of(n) in ("arguments", "eval")]
    for node in walk(root):
        if (node.type == "await_expression" or node.type == "for_in_statement" and any(
                c.type == "await" for c in node.children)) and nearest(node, FUNCTION_SCOPES).type == "program":
            found.append(f"awaits at the top at line {node.start_point[0] + 1}, which the page's DOMContentLoaded "
                         f"does not wait for, so what comes after it misses the start: await inside a function")
        if node.type in FUNCTIONS and (name := node.child_by_field_name("name")) and text_of(name) in STRICT_NAMES:
            found.append(f"binds {text_of(name)} at line {name.start_point[0] + 1}, which a module, in strict mode, "
                         f"refuses")
        if node.type == "formal_parameters":
            names = [text_of(n) for part in node.named_children for n in pattern_nodes(part)]
            found += [f"has the parameter {n} twice at line {node.start_point[0] + 1}, which a module, in strict "
                      f"mode, refuses" for n in sorted({n for n in names if names.count(n) > 1})]
    return found


def returned_keys(function):
    body = function.child_by_field_name("body")
    if body is None:
        return []
    if body.type == "parenthesized_expression":
        objects = [c for c in body.named_children if c.type == "object"]
    elif body.type == "statement_block":
        objects = [value for c in body.named_children if c.type == "return_statement"
                   for value in [next((x for x in c.named_children if x.type != "comment"), None)]
                   if value is not None and value.type == "object"]
    else:
        objects = [body] if body.type == "object" else []
    return [keys for o in objects if (keys := object_keys(o))]


def unread(node, leaves):
    if node.type in leaves or node.type == "comment" or node.type == "shorthand_property_identifier_pattern":
        return None
    if node.type in ("object_pattern", "array_pattern", "rest_pattern"):
        parts = node.named_children
    elif node.type == "pair_pattern":
        if (named := node.child_by_field_name("key")).type not in PATTERN_KEYS:
            return named
        parts = [node.child_by_field_name("value")]
    elif node.type in DEFAULTS:
        parts = [node.child_by_field_name("left")]
    else:
        return node
    return next((bad for part in parts if (bad := unread(part, leaves)) is not None), None)


def places(root):
    for node in walk(root):
        if node.type == "variable_declarator":
            yield "binding", node.child_by_field_name("name"), BOUND_LEAVES
        elif node.type == "formal_parameters":
            yield from (("binding", part, BOUND_LEAVES) for part in node.named_children)
        elif node.type in ("arrow_function", "catch_clause") and node.child_by_field_name("parameter"):
            yield "binding", node.child_by_field_name("parameter"), BOUND_LEAVES
        elif node.type == "for_in_statement":
            kind = node.child_by_field_name("kind")
            yield ("binding", node.child_by_field_name("left"), BOUND_LEAVES) if kind else (
                "write", node.child_by_field_name("left"), WRITTEN_LEAVES)
        elif node.type == "assignment_expression":
            yield "write", node.child_by_field_name("left"), WRITTEN_LEAVES
        elif node.type in ("augmented_assignment_expression", "update_expression"):
            target = node.child_by_field_name("left" if node.type != "update_expression" else "argument")
            yield "write", target, WRITTEN_LEAVES if target.type in WRITTEN_LEAVES else ()


def declared_in(function):
    body = function.child_by_field_name("body")
    if body is None or body.type != "statement_block":
        return set()
    return {text_of(n) for n in walk(body) if n.type in NAMES and n.type != "shorthand_property_identifier"
            and (own := owner(n)) is not None and key(scope_of(own)) in (key(function), key(body))}


def early_defaults(root):
    for node in walk(root):
        if node.type != "formal_parameters":
            continue
        parts, inside = node.named_children, declared_in(node.parent)
        for i, part in enumerate(parts):
            later = inside | {name for after in parts[i + 1:] for name in pattern_names(after)}
            for default in (d for d in walk(part) if d.type in DEFAULTS):
                read = [n for n in walk(default.child_by_field_name("right")) if n.type == "identifier"]
                yield from (n for n in read if text_of(n) in later)


def unjudged(root):
    found = [f"has a {bad.type} at line {bad.start_point[0] + 1} where it {'binds' if what == 'binding' else 'writes'} "
             f"a name, which this check does not judge: write it in a form the check reads"
             for what, node, leaves in places(root) if (bad := unread(node, leaves)) is not None]
    found += [f"has a {bad.type} at line {bad.start_point[0] + 1} in an import or an export, which this check does "
              f"not judge: import {{ name }} from \"file.js\", export const or export function"
              for node in walk(root) if node.type in ("import_statement", "export_statement")
              and (bad := unallowed(node)) is not None]
    found += [f"has the name {text_of(n)!r} at line {n.start_point[0] + 1}, which this check does not judge: a "
              f"plain ASCII name" for n in walk(root) if n.type in NAME_NODES and not PLAIN_NAME.fullmatch(text_of(n))]
    found += [f"has a parameter default at line {n.start_point[0] + 1} that reads {text_of(n)}, which the function's "
              f"body or a later parameter declares, which this check does not judge: read it in the body"
              for n in early_defaults(root)]
    return found


def file_facts(text):
    root = PARSER.parse(text.encode("utf-8")).root_node
    facts = types.SimpleNamespace(imports={}, exports=set(), problems=[], top=set(), values={}, functions=[],
                                  objects=[], writes=set(), imported_from={}, called={})
    calls = []
    if root.has_error:
        broken = next(n for n in walk(root) if n.type == "ERROR" or n.is_missing)
        facts.problems.append(f"does not parse at line {broken.start_point[0] + 1}, so the rest of this check would "
                              f"read a broken tree")
    facts.problems += unjudged(root)
    for node, name, names in allowed_imports(root):
        for imported in names:
            if text_of(imported) in facts.imported_from:
                facts.problems.append(f"imports {text_of(imported)} twice, at line {imported.start_point[0] + 1}, which "
                                      f"a module refuses")
            facts.imported_from[text_of(imported)] = (name, text_of(imported))
            facts.imports.setdefault(name, set()).add(text_of(imported))
    for node in walk(root):
        if node.type == "call_expression" and node.child_by_field_name("function").type == "import":
            facts.problems.append(f"a dynamic import() at line {node.start_point[0] + 1}, which the page's import map "
                                  f"does not hold for certain")
        if node.type in FUNCTIONS and len(text := normalized(node)) >= SHORTEST_FUNCTION:
            facts.functions.append((text, node.start_point[0] + 1))
        if node.type == "object" and (keys := object_keys(node)):
            facts.objects.append((keys, node.start_point[0] + 1, object_values(node)))
        if node.type == "variable_declarator" and (call := node.child_by_field_name("value")) is not None and \
                call.type == "call_expression" and call.child_by_field_name("function").type == "identifier":
            calls.append((node, call.child_by_field_name("function")))
        if node.type == "export_statement" and unallowed(node) is None:
            for name, value in declared(node.child_by_field_name("declaration")).items():
                if name in facts.exports:
                    facts.problems.append(f"exports {name} twice, at line {node.start_point[0] + 1}, which a module "
                                          f"refuses")
                facts.exports.add(name)
                facts.values[name] = value
    imported = set(facts.imported_from)
    scopes, lines, references = bindings(root)
    program = key(root)
    for name in imported:
        scopes[name].add(program)
    facts.top = {name for name, where in scopes.items() if program in where}
    facts.module_only = module_only(root)
    for declarator, function in calls:
        for bound, from_key in destructured_keys(declarator.child_by_field_name("name")):
            facts.called[(text_of(bound), key(scope_of(declarator)))] = (resolved(function, scopes) == program
                                                                        and text_of(function), from_key)
    facts.objects = [(keys, line, {k: (text_of(n), resolved(n, scopes)) for k, n in values.items()})
                     for keys, line, values in facts.objects]
    facts.reads = {text_of(r) for r in references if resolved(r, scopes) == program}
    facts.free = {text_of(r) for r in references if resolved(r, scopes) is None}
    lefts = [n.child_by_field_name("left") for n in walk(root)
             if n.type in ("assignment_expression", "augmented_assignment_expression")
             or n.type == "for_in_statement" and n.child_by_field_name("kind") is None]
    lefts += [n.child_by_field_name("argument") for n in walk(root) if n.type == "update_expression"]
    for target in (found for left in lefts for found in pattern_nodes(left)):
        where = resolved(target, scopes)
        if where is None:
            facts.writes.add(text_of(target))
        elif where == program and text_of(target) in imported:
            facts.problems.append(f"writes its import {text_of(target)} at line {target.start_point[0] + 1}, "
                                  f"which throws")
    again = {name for name in imported if lines.get(name)}
    facts.problems += [f"imports {name}, which it never uses" for name in sorted(imported - facts.reads - again)]
    facts.problems += [f"declares {name} again at line {lines[name]}, over its import" for name in sorted(again)]
    return facts


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


def composed(own, values, shape, who):
    for wanted in shape:
        function, from_key = own.called.get(values.get(wanted), (None, None))
        if not function or from_key != wanted or own.imported_from.get(function) != who:
            return False
    return True


def rewritten(folder, facts):
    exported, shapes = {}, {}
    for name, own in facts.items():
        for export, value in own.values.items():
            if value is not None and value.type in FUNCTIONS:
                exported[normalized(value)] = (name, export)
                shapes.update({keys: (name, export) for keys in returned_keys(value)})
    problems = []
    for path in theme_files(folder):
        file = path.relative_to(folder).as_posix()
        own = file_facts(path.read_text(encoding="utf-8-sig"))
        problems += [f"{file}:{line}: writes again {exported[text][1]}, which {exported[text][0]} exports: import it"
                     for text, line in own.functions if text in exported and exported[text][0] != file]
        problems += [f"{file}:{line}: builds by hand what {who[1]} of {who[0]} returns: call {who[1]}"
                     for keys, line, values in own.objects for shape, who in shapes.items()
                     if keys >= shape and who[0] != file
                     and not composed(own, values, shape, who)]
    return problems


def module_problems(folder, page):
    read, error = theme_page.strict(page)
    if error:
        return [f"index.html:{error[0]}:{error[1]}: {error[2]}"]
    names = [name for _, _, kind, name in read.found if kind == "module"]
    facts = {name: file_facts((folder / name).read_text(encoding="utf-8-sig")) for name in names}
    classics = [(name, file_facts(text)) for name, text in classic_texts(folder, read)]
    problems = [f"{name}: {problem}" for name, own in classics for problem in own.problems
                if "dynamic import()" in problem or "does not parse" in problem or "does not judge" in problem]
    problems += [f"{name}: {problem}" for name, own in facts.items() for problem in own.problems + own.module_only]
    problems += [f"{name}: imports {target}, which is not a module of the page" for name, own in facts.items()
                 for target in own.imports if target not in facts]
    for name, own in facts.items():
        for target, wanted_names in sorted(own.imports.items()):
            if target not in facts:
                continue
            problems += [f"{name}: imports {wanted} from {target}, which {target} does not export"
                         for wanted in sorted(wanted_names - facts[target].exports)]
    for name, own in facts.items():
        used = set().union(*(theirs.imports.get(name, set()) for other, theirs in facts.items() if other != name))
        problems += [f"{name}: exports {export}, which no other file of the theme imports"
                     for export in sorted(own.exports) if export not in used]
    classic_top = set().union(*(own.top for _, own in classics))
    for name, own in [*classics, *facts.items()]:
        for used_name in sorted(own.free - classic_top):
            if owners := [module for module, theirs in facts.items() if module != name and used_name in theirs.top]:
                problems.append(f"{name}: uses {used_name}, which only the module {owners[0]} declares: "
                                + ("only an import reaches a module's name" if name in facts else
                                   "a classic script does not see a module's names"))
    problems += [f"{name}: writes {written}, which no file declares: a module is in strict mode, where that throws"
                 for name, own in facts.items() for written in sorted(own.writes - classic_top)]
    return problems + data_problems(facts) + rewritten(folder, facts)


def engine_fonts(folder):
    families = set(re.findall(r"fam: '\"([^\"]+)\"'", (folder / "pixel.js").read_text(encoding="utf-8")))
    loads = []
    for path in theme_files(folder):
        if path.name == "pixel.js":
            continue
        for node in walk(PARSER.parse(path.read_bytes()).root_node):
            if node.type != "call_expression" or text_of(node.child_by_field_name("function")) != "document.fonts.load":
                continue
            given = node.child_by_field_name("arguments")
            first = text_of(given.named_children[0]) if given is not None and given.named_children else ""
            loads += [f"{path.relative_to(folder).as_posix()}:{node.start_point[0] + 1}: loads {family}, which "
                      f"pixel.js's fontesProntas loads" for family in sorted(families)
                      if re.search(rf"(?<![\w-]){re.escape(family)}(?![\w-])", first)]
    return families, loads


def files(a, b="", c="go();\n", d="", e=""):
    return {"a.js": a, "b.js": b, "c.js": c, "d.js": d, "e.js": e}


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
        factory = "export function mk(w) { return { u: 1, w, h: 2 }; }\n"
        uses_b = 'import { b } from "b.js";\nb();\n'
        body = "x => { return x * 2 + 1 + x * 3 + x * 4 + x * 5; }"
        long = f"export const f = {body};\n"
        cases = {
            "an import of a module the page does not tag": (files('import { a } from "gone.js";\na();\n'),
                                                            ["a.js: imports gone.js"]),
            "a dynamic import()": (files('import("b.js").then(() => {});\n'), ["a.js: a dynamic import()"]),
            "a dynamic import() in a classic script": (files(uses_b, b, 'import("b.js");\n'),
                                                        ["c.js: a dynamic import()"]),
            "an export no file imports": (files('export const unused = 1;\n' + uses_b, b), ["a.js: exports unused"]),
            "an import it never uses": (files('import { b } from "b.js";\n', b), ["a.js: imports b, which it never uses"]),
            "an import declared again": (files('import { b } from "b.js";\nconst f = b => b;\nf();\n', b),
                                         ["a.js: declares b again"]),
            "an import declared again in a pattern": (
                files('import { b } from "b.js";\nconst f = ({ key: b }) => b;\nf();\n', b), ["a.js: declares b again"]),
            "an import declared again in a for of": (files('import { b } from "b.js";\nfor (const b of []) b();\n', b),
                                                     ["a.js: declares b again"]),
            "an import declared again as a class name": (
                files('import { b } from "b.js";\nconst k = class b {};\nnew k();\n', b), ["a.js: declares b again"]),
            "an import declared again as a generator name": (
                files('import { b } from "b.js";\nconst g = function* b() {};\ng();\n', b), ["a.js: declares b again"]),
            "an import of a name the module does not export": (files('import { b, c } from "b.js";\nb(c);\n', b),
                                                               ["a.js: imports c from b.js, which b.js does not export"]),
            "a module that awaits at the top": (files(uses_b + "await b();\n", b), ["a.js: awaits at the top at line 3"]),
            "a for await at the top": (files(uses_b + "for await (const q of []) go(q);\n", b),
                                       ["a.js: awaits at the top at line 3"]),
            "an await inside an async function": (files(uses_b + "async function f() { await b(); }\nf();\n", b), []),
            "a module that imports a name strict mode refuses": (
                files('import { arguments } from "b.js";\ngo(arguments);\n', "export const arguments = 1;\n"),
                ["a.js: binds arguments at line 1", "b.js: binds arguments at line 1"]),
            "a module that writes arguments, which a classic script declares": (
                files(uses_b + "arguments = 1;\n", b, "var arguments = 0;\n"), ["a.js: writes arguments at line 3"]),
            "a module that imports a name twice": (
                files('import { b } from "b.js";\nimport { b } from "d.js";\nb();\n', b, d=b), ["a.js: imports b twice"]),
            "a module that exports a name twice": (
                files(uses_b, "export const b = () => {};\nexport function b() {}\n"), ["b.js: exports b twice"]),
            "a name written with an escape": (files(uses_b + "go(deckGlyph\\u0073);\n", b), ["a.js: has the name"]),
            "a name out of ASCII, in a classic script": (files(uses_b, b, "const ação = 1;\ngo(ação);\n"),
                                                        ["c.js: has the name 'ação' at line 1",
                                                         "c.js: has the name 'ação' at line 2"]),
            "a parameter default that reads what the body declares": (
                files(uses_b + "function f(q = r) { var r; return q; }\nf();\n", b),
                ["a.js: has a parameter default at line 3 that reads r"]),
            "a parameter default that reads a later parameter": (
                files(uses_b + "function f(q = z, z) { return q + z; }\nf();\n", b),
                ["a.js: has a parameter default at line 3 that reads z"]),
            "a parameter default that reads an earlier parameter": (
                files(uses_b + "function f(a, q = a) { return q; }\nf();\n", b), []),
            "an object composed from the factory with a quoted key": (
                files('import { mk } from "b.js";\nconst { "u": u, w, h } = mk(1);\ngo({ u, w, h });\n', factory), []),
            "an object composed from the factory with a key written again after": (
                files('import { mk } from "b.js";\nconst { u, w, h } = mk(1);\ngo({ u, w, h, u: 42 });\n', factory),
                ["a.js:3: builds by hand what mk of b.js returns"]),
            "an object composed from a nested destructuring of the factory's call": (
                files('import { mk } from "b.js";\nconst { a: { u, w, h } } = mk(1);\ngo({ u, w, h });\n', factory),
                ["a.js:3: builds by hand what mk of b.js returns"]),
            "an object composed from a local function named like the factory": (
                files("const mk = () => ({ u: 1, w: 2, h: 3 });\nconst { u, w, h } = mk();\ngo({ u, w, h });\n", factory,
                      d='import { mk } from "b.js";\nmk(1);\n'),
                ["a.js:1: builds by hand what mk of b.js returns", "a.js:3: builds by hand what mk of b.js returns"]),
            "a module that binds yield": (files(uses_b + "const yield = 1;\ngo(yield);\n", b), ["a.js: binds yield"]),
            "a module that binds arguments in a function": (
                files(uses_b + "function f() { var arguments = 1; return arguments; }\nf();\n", b),
                ["a.js: binds arguments"]),
            "a module with a parameter twice": (files(uses_b + "function f(q, q) { return q; }\nf();\n", b),
                                                ["a.js: has the parameter q twice"]),
            "a classic script that binds yield and has a parameter twice, which it may": (
                files(uses_b, b, "const yield = 1;\nfunction f(q, q) { return q; }\nf(yield);\n"), []),
            "an object composed from the factory's values under each other's keys": (
                files('import { mk } from "b.js";\nconst { u: w, w: u, h } = mk(1);\ngo({ u, w, h });\n',
                      "export function mk(w) { return { u: 1, w, h: 2 }; }\n"),
                ["a.js:3: builds by hand what mk of b.js returns"]),
            "an object composed with a name the factory's value is shadowed by": (
                files('import { mk } from "b.js";\nconst { u, w, h } = mk(1);\ngo(u, w, h);\n'
                      'function g(h) { return { u, w, h }; }\ng(1);\n', "export function mk(w) { return { u: 1, w, h: 2 }; }\n"),
                ["a.js:4: builds by hand what mk of b.js returns"]),
            "an object composed from what the factory returns": (
                files('import { mk } from "b.js";\nconst { u, w, h } = mk(1);\ngo({ u, w, h, ready: true });\n',
                      "export function mk(w) { return { u: 1, w, h: 2 }; }\n"), []),
            "an import declared again in a pattern with a default": (
                files('import { b } from "b.js";\nconst f = ({ b = 1 }) => b;\nf({});\n', b), ["a.js: declares b again"]),
            "a classic parameter with a default, named like a module's name": (
                files(uses_b, b, "function f({ b = 1 }) { return b; }\nf({});\n"), []),
            "a module that writes its import by destructuring": (files('import { b } from "b.js";\n[b] = [1];\n', b),
                                                                 ["a.js: writes its import b"]),
            "a module that writes a name nobody declares in a for of": (files(uses_b + "for (zz of []) go();\n", b),
                                                                        ["a.js: writes zz, which no file declares"]),
            "a module that writes a name a for (var ...) of declared": (
                files(uses_b + "for (var v of []) go();\nv = 2;\n", b), []),
            "a module that reads another module's name without importing it": (
                files(uses_b, b, d="export const dd = 1;\nconst secret = 2;\n",
                      e='import { dd } from "d.js";\ngo(dd, secret);\n'),
                ["e.js: uses secret, which only the module d.js declares"]),
            "a module that does not parse": (files(uses_b + "const = ;\n", b), ["a.js: does not parse at line 3"]),
            "a module that writes through a parenthesized name, a form the check does not judge": (
                files(uses_b + "let zz = 0;\n(zz) = 1;\n", b),
                ["a.js: has a parenthesized_expression at line 4 where it writes a name, which this check does not "
                 "judge"]),
            "a module that binds by a computed key, a form the check does not judge": (
                files(uses_b + "const k = 'a';\nconst { [k]: v } = {};\ngo(v);\n", b),
                ["a.js: has a computed_property_name at line 4 where it binds a name"]),
            "a classic script with a form the check does not judge": (files(uses_b, b, "let zz = 0;\n(zz) = 1;\n"),
                                                                     ["c.js: has a parenthesized_expression"]),
            "a module of the page that imports and is imported": (files(uses_b, b), []),
            "a classic script that reads a module's name": (files(uses_b, b, "function g() { return b; }\ng();\n"),
                                                            ["c.js: uses b, which only the module"]),
            "a classic script that reads a module's name outside the function whose parameter has it": (
                files(uses_b, b, "function g(b) { return b; }\ng(b);\n"), ["c.js: uses b, which only the module"]),
            "a classic script that assigns a module's name by destructuring, which declares nothing": (
                files(uses_b, b, "const o = {};\n({ b } = o);\n"), ["c.js: uses b, which only the module"]),
            "a classic script with a name of its own like a module's": (files(uses_b, b, "const b = 1;\ngo(b);\n"), []),
            "data an engine exports for one file only": (
                files('import { f, T } from "b.js";\nf(T);\n', 'export const f = () => {};\nexport const T = 1;\n'),
                ["b.js: exports T, data only a.js uses: keep it in a.js"]),
            "data an engine exports and uses itself": (
                files('import { f, T } from "b.js";\nf(T);\n', 'export const f = () => T;\nexport const T = 1;\n'), []),
            "a function a module exports, written again": (
                files(f'import {{ f }} from "b.js";\nconst g = {body};\nf(g(1));\n', long),
                ["a.js:2: writes again f, which b.js exports"]),
            "a function a module exports, written again with other names": (
                files(f'import {{ f }} from "b.js";\nconst g = {body.replace("x", "y")};\nf(g(1));\n', long),
                ["a.js:2: writes again f, which b.js exports"]),
            "an object built by hand like the one a module's function returns": (
                files('import { mk } from "b.js";\nmk(1);\nconst o = { u: 2, w: 3, h: 4 };\ngo(o);\n',
                      "export function mk(w) { return { u: 1, w, h: 2 }; }\n"),
                ["a.js:3: builds by hand what mk of b.js returns"]),
            "an object built by hand with one key more and a comment": (
                files('import { mk } from "b.js";\nmk(1);\nconst o = { /* by hand */ u: 2, w: 3, h: 4, extra: 5 };\n'
                      'go(o);\n', "export function mk(w) { return /* the record */ { u: 1, w, h: 2 }; }\n"),
                ["a.js:3: builds by hand what mk of b.js returns"]),
            "a function a module exports, and one with the same shape and other free names": (
                files('import { f } from "b.js";\nconst g = () => { const inner = y => y * 2; return inner(1) + y + 3 + '
                      '4 + 5; };\nf(g());\n',
                      "export const f = () => { const inner = x => x * 2; return inner(1) + x + 3 + 4 + 5; };\n"), []),
            "a module that writes a name nobody declares": (files(uses_b + "x = 1;\n", b),
                                                            ["a.js: writes x, which no file declares"]),
            "a module that writes its import": (files('import { b } from "b.js";\nb = 1;\n', b),
                                                ["a.js: writes its import b"]),
            "a module that writes a classic script's global": (files(uses_b + "shared = 1;\n", b, "var shared = 0;\n"),
                                                               []),
        }
        page = "".join(f'<script type="module" src="{name}"></script>\n' for name in ("a.js", "b.js", "d.js", "e.js"))
        page = '<script src="c.js"></script>\n' + page
        for what, (texts, expected) in cases.items():
            for name, text in texts.items():
                (folder / name).write_text(text, encoding="utf-8")
            found = module_problems(folder, page)
            results.append((len(found) == len(expected) and all(any(e in p for p in found) for e in expected),
                            f"{what}: {found or 'no problem'}"))
        refused = {
            'import b from "b.js";\nb();\n': "identifier", 'import * as n from "b.js";\nn.b();\n': "namespace_import",
            'import { b as c } from "b.js";\nc();\n': "import_specifier",
            'import { "b" as c } from "b.js";\nc();\n': "import_specifier", 'import "b.js";\n': "import_statement",
            'import { b } from "b.js" with { type: "json" };\nb();\n': "import_attribute",
            'export default 1;\n' + uses_b: "default", "const q = 1;\nexport { q };\n" + uses_b: "export_clause",
            'export { b } from "b.js";\n': "export_clause", 'export * from "b.js";\n': "*",
            'export * as n from "b.js";\n': "namespace_export","export let q = 1;\n" + uses_b: "lexical_declaration",
            "export var q = 1;\n" + uses_b: "variable_declaration", "export class Q {}\n" + uses_b: "class_declaration",
            "const o = {};\nexport const { p } = o;\n" + uses_b: "object_pattern",
            "export function* g() {}\n" + uses_b: "generator_function_declaration",
        }
        for text, kind in refused.items():
            for name, source in files(text, b, d='import { b } from "b.js";\nb();\n').items():
                (folder / name).write_text(source, encoding="utf-8")
            found = module_problems(folder, page)
            results.append((any(p.startswith(f"a.js: has a {kind} at line ") and "does not judge" in p for p in found),
                            f"an import or export outside the rule, {text.splitlines()[0]!r}, is a form the check "
                            f"does not judge: {found}"))
        for name, text in files(uses_b, b).items():
            (folder / name).write_text(text, encoding="utf-8")
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
        (folder / "c.js").write_text('document.fonts.load(`300px "Jersey 10"`);\n// document.fonts.load("Jersey 10")\n',
                                     encoding="utf-8")
        families, loads = engine_fonts(folder)
        results.append((families == {"Jersey 10"} and len(loads) == 1 and loads[0].startswith("c.js:1: loads"),
                        f"a font of the engine loaded outside it, in a template, and none read in a comment: {loads}"))
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = samples()
    pairs, count = copies(THEME)
    results.append((count == 0, f"no run of {RUN} equal lines is in two files of the theme ({count}; {pairs})"))
    problems = module_problems(THEME, (THEME / "index.html").read_text(encoding="utf-8"))
    results.append((not problems, f"each module of the theme imports only modules of the page and names they export, "
                                  f"uses each name it imports, writes no name nobody declares, has its exports imported "
                                  f"by another file and keeps data one file uses in that file; no classic script uses "
                                  f"a module's name or calls import(), and no file writes again a function a module "
                                  f"exports or builds by hand what it returns ({problems or 'all of them'})"))
    families, loads = engine_fonts(THEME)
    results.append((families and not loads, f"the engine's fonts ({', '.join(sorted(families))}) are loaded by "
                                            f"pixel.js only ({loads or 'none elsewhere'})"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

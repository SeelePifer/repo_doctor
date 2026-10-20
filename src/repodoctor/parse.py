from pydantic import BaseModel, Field
from tree_sitter import Language, Parser

from repodoctor.errors import RepoDoctorError

_PARSERS: dict[str, Parser] = {}


class ParsedSymbol(BaseModel):
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str


class ParsedImport(BaseModel):
    module: str
    imported_name: str
    local_name: str
    line: int


class ParseResult(BaseModel):
    symbols: list[ParsedSymbol] = Field(default_factory=list)
    imports: list[ParsedImport] = Field(default_factory=list)


def parse_source(language_name: str, source: str) -> ParseResult:
    if language_name == "text":
        return ParseResult()
    return _parse_bytes(language_name, source.encode("utf-8"))


def _parse_bytes(language_name: str, source: bytes) -> ParseResult:
    parser = _parser_for(language_name)
    tree = parser.parse(source)
    symbols: list[ParsedSymbol] = []
    imports: list[ParsedImport] = []
    for node in _walk(tree.root_node):
        if language_name == "python":
            _collect_python(node, source, symbols, imports)
            continue
        _collect_script(node, source, symbols, imports)
    return ParseResult(symbols=symbols, imports=imports)


def _parser_for(language_name: str) -> Parser:
    cached = _PARSERS.get(language_name)
    if cached is not None:
        return cached
    language = _load_language(language_name)
    try:
        parser = Parser(language)
    except TypeError:
        parser = Parser()
        parser.language = language
    _PARSERS[language_name] = parser
    return parser


def _load_language(language_name: str) -> Language:
    if language_name == "python":
        import tree_sitter_python as tspython

        return Language(tspython.language())
    if language_name == "javascript":
        import tree_sitter_javascript as tsjavascript

        return Language(tsjavascript.language())
    if language_name == "typescript":
        import tree_sitter_typescript as tstypescript

        return Language(tstypescript.language_typescript())
    if language_name == "tsx":
        import tree_sitter_typescript as tstypescript

        return Language(tstypescript.language_tsx())
    raise RepoDoctorError(f"Unsupported language: {language_name}")


def _walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line_span(node) -> tuple[int, int]:
    start = node.start_point[0] + 1
    end_row, end_col = node.end_point
    end = end_row if end_col == 0 else end_row + 1
    if end < start:
        end = start
    return start, end


def _signature(source: bytes, node) -> str:
    target = node
    parent = node.parent
    if parent is not None and parent.type in {"decorated_definition", "export_statement"}:
        target = parent
    start = target.start_byte
    newline = source.find(b"\n", start)
    end = target.end_byte if newline == -1 else newline
    text = source[start:end].decode("utf-8", errors="replace").strip()
    return text[:200]


def _has_ancestor(node, type_name: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == type_name:
            return True
        parent = parent.parent
    return False


def _add_symbol(symbols: list[ParsedSymbol], source: bytes, node, name: str, kind: str) -> None:
    start_line, end_line = _line_span(node)
    symbols.append(
        ParsedSymbol(
            name=name,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
            signature=_signature(source, node),
        )
    )


def _collect_python(node, source: bytes, symbols: list[ParsedSymbol], imports: list[ParsedImport]) -> None:
    if node.type in {"function_definition", "class_definition"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _node_text(source, name_node)
        if node.type == "class_definition":
            _add_symbol(symbols, source, node, name, "class")
            return
        kind = "method" if _has_ancestor(node, "class_definition") else "function"
        _add_symbol(symbols, source, node, name, kind)
        return
    if node.type == "import_statement":
        imports.extend(_python_import(node, source))
        return
    if node.type == "import_from_statement":
        imports.extend(_python_from_import(node, source))


def _python_import(node, source: bytes) -> list[ParsedImport]:
    line = node.start_point[0] + 1
    found: list[ParsedImport] = []
    for child in node.children:
        if child.type == "dotted_name":
            module = _node_text(source, child)
            local = module.split(".")[-1]
            found.append(ParsedImport(module=module, imported_name=local, local_name=local, line=line))
            continue
        if child.type == "aliased_import":
            found.append(_aliased_module(child, source, line))
    return found


def _aliased_module(node, source: bytes, line: int) -> ParsedImport:
    name_node = node.child_by_field_name("name")
    alias_node = node.child_by_field_name("alias")
    module = _node_text(source, name_node) if name_node is not None else ""
    local = _node_text(source, alias_node) if alias_node is not None else module.split(".")[-1]
    return ParsedImport(module=module, imported_name=module.split(".")[-1], local_name=local, line=line)


def _python_from_import(node, source: bytes) -> list[ParsedImport]:
    module_node = node.child_by_field_name("module_name")
    module = _node_text(source, module_node) if module_node is not None else ""
    found: list[ParsedImport] = []
    for child in node.children:
        if child.type == "dotted_name" and child != module_node:
            imported = _node_text(source, child)
            local = imported.split(".")[-1]
            found.append(
                ParsedImport(
                    module=module,
                    imported_name=local,
                    local_name=local,
                    line=child.start_point[0] + 1,
                )
            )
            continue
        if child.type == "aliased_import":
            name_node = child.child_by_field_name("name")
            alias_node = child.child_by_field_name("alias")
            imported = _node_text(source, name_node) if name_node is not None else ""
            local_name = imported.split(".")[-1]
            local = _node_text(source, alias_node) if alias_node is not None else local_name
            found.append(
                ParsedImport(
                    module=module,
                    imported_name=local_name,
                    local_name=local,
                    line=child.start_point[0] + 1,
                )
            )
            continue
        if child.type in {"wildcard_import"} or _node_text(source, child) == "*":
            if child.type in {"wildcard_import", "identifier"}:
                found.append(ParsedImport(module=module, imported_name="*", local_name="*", line=child.start_point[0] + 1))
    return found


def _collect_script(node, source: bytes, symbols: list[ParsedSymbol], imports: list[ParsedImport]) -> None:
    if node.type in {"function_declaration", "class_declaration", "method_definition"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _node_text(source, name_node)
        if node.type == "class_declaration":
            kind = "class"
        elif node.type == "method_definition":
            kind = "method"
        else:
            kind = "function"
        _add_symbol(symbols, source, node, name, kind)
        return
    if node.type == "variable_declarator":
        _script_arrow(node, source, symbols)
        return
    if node.type == "import_statement":
        imports.extend(_script_import(node, source))


def _script_arrow(node, source: bytes, symbols: list[ParsedSymbol]) -> None:
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if name_node is None or name_node.type != "identifier" or value_node is None:
        return
    if value_node.type not in {"arrow_function", "function", "function_expression"}:
        return
    _add_symbol(symbols, source, node, _node_text(source, name_node), "function")


def _script_import(node, source: bytes) -> list[ParsedImport]:
    line = node.start_point[0] + 1
    module = ""
    clause = None
    for child in node.children:
        if child.type == "string":
            module = _node_text(source, child).strip().strip("'\"")
        if child.type == "import_clause":
            clause = child
    if clause is None:
        return [ParsedImport(module=module, imported_name="*", local_name="*", line=line)]
    found: list[ParsedImport] = []
    for child in clause.children:
        if child.type == "identifier":
            local = _node_text(source, child)
            found.append(ParsedImport(module=module, imported_name="default", local_name=local, line=line))
            continue
        if child.type == "namespace_import":
            alias = _first_identifier(child, source)
            found.append(ParsedImport(module=module, imported_name="*", local_name=alias or "*", line=line))
            continue
        if child.type != "named_imports":
            continue
        for specifier in child.children:
            if specifier.type != "import_specifier":
                continue
            name_node = specifier.child_by_field_name("name")
            alias_node = specifier.child_by_field_name("alias")
            imported = _node_text(source, name_node) if name_node is not None else ""
            local = _node_text(source, alias_node) if alias_node is not None else imported
            found.append(ParsedImport(module=module, imported_name=imported, local_name=local, line=line))
    return found


def _first_identifier(node, source: bytes) -> str:
    for child in _walk(node):
        if child.type == "identifier":
            return _node_text(source, child)
    return ""

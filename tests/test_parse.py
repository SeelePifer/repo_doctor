from repodoctor.parse import parse_source


def test_python_symbols_and_imports() -> None:
    source = """
from calc import add, multiply as product

def add(left, right):
    return left + right

class Box:
    def open(self):
        return 1
"""
    parsed = parse_source("python", source)
    names = {(item.name, item.kind) for item in parsed.symbols}
    assert ("add", "function") in names
    assert ("Box", "class") in names
    assert ("open", "method") in names
    imports = {(item.module, item.imported_name, item.local_name) for item in parsed.imports}
    assert ("calc", "add", "add") in imports
    assert ("calc", "multiply", "product") in imports


def test_typescript_function_and_import() -> None:
    source = """
import { greet as hello } from "./greet"

export function greet(name: string): string {
  return name
}

export const wave = (name: string) => name
"""
    parsed = parse_source("typescript", source)
    names = {(item.name, item.kind) for item in parsed.symbols}
    assert ("greet", "function") in names
    assert ("wave", "function") in names
    imports = {(item.module, item.imported_name, item.local_name) for item in parsed.imports}
    assert ("./greet", "greet", "hello") in imports

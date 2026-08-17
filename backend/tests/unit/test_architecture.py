import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

FORBIDDEN_ROUTER_IMPORTS = (
    "app.adapters",
    "app.ai",
    "app.db",
    "app.models",
    "app.repositories",
    "minio",
    "qdrant_client",
    "sqlalchemy",
)


def _imported_modules(tree: ast.AST, package: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            base_module = (
                resolve_name(f"{'.' * node.level}{module}", package) if node.level else module
            )
            if base_module:
                modules.append(base_module)
            modules.extend(
                f"{base_module}.{alias.name}" if base_module else alias.name
                for alias in node.names
                if alias.name != "*"
            )
    return modules


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("from app import db", "app.api.v1.endpoints"),
        ("from ...db import session", "app.api.v1"),
    ],
)
def test_import_parser_resolves_forbidden_alias_and_relative_imports(
    source: str,
    package: str,
) -> None:
    assert "app.db" in _imported_modules(ast.parse(source), package)


def test_routers_do_not_import_database_storage_or_model_layers() -> None:
    backend_root = Path(__file__).parents[2]
    api_root = backend_root / "app" / "api"
    violations: list[str] = []

    for path in sorted(api_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = ".".join(path.relative_to(backend_root).with_suffix("").parts[:-1])
        imports = _imported_modules(tree, package)
        for module in imports:
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_ROUTER_IMPORTS
            ):
                violations.append(f"{path.relative_to(api_root)} -> {module}")

    assert not violations, "Router 不得直接依赖数据库、存储或模型层：\n" + "\n".join(violations)

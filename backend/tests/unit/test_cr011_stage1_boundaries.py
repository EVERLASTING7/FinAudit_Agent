from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
PRODUCTION_MODULES = (
    BACKEND_ROOT / "app/ai/strict_json.py",
    BACKEND_ROOT / "app/ai/policy_companion.py",
    BACKEND_ROOT / "app/ai/policy_resolver.py",
    BACKEND_ROOT / "app/ai/network_policy.py",
    BACKEND_ROOT / "app/ai/retry_policy.py",
    BACKEND_ROOT / "app/ai/response_boundary.py",
    BACKEND_ROOT / "app/ai/events.py",
    BACKEND_ROOT / "app/ai/event_sink.py",
)
FORBIDDEN_IMPORTS = (
    "_socket",
    "asyncio",
    "celery",
    "ctypes",
    "http.client",
    "httpx",
    "multiprocessing",
    "psycopg",
    "redis",
    "requests",
    "socket",
    "sqlalchemy",
    "ssl",
    "subprocess",
    "urllib.request",
)
FORBIDDEN_CALLS = {"__import__", "compile", "eval", "exec", "open"}


def _module_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_stage1_modules_do_not_import_runtime_or_socket_stacks() -> None:
    for path in PRODUCTION_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _module_names(tree)
        forbidden = [
            name
            for name in imported
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORTS)
        ]
        assert forbidden == [], f"{path.name} imports forbidden Stage1 modules: {forbidden}"


def test_stage1_modules_have_no_dynamic_execution_or_implicit_file_entry() -> None:
    for path in PRODUCTION_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    violations.append(node.func.id)
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                violations.append("environ")
        assert violations == [], f"{path.name} has forbidden Stage1 entrypoints: {violations}"


def test_stage1_runner_cannot_claim_complete_gate_b() -> None:
    verifier = (PROJECT_ROOT / "scripts/verify-cr011-gate-b-stage1.ps1").read_text(encoding="utf-8")
    assert "CR011_GATE_B_STAGE1=PASS" in verifier
    assert "CR011_GATE_B=BLOCKED_DUAL_DRAFT202012_ENGINES" in verifier
    assert "CR011_GATE_B=PASS" not in verifier

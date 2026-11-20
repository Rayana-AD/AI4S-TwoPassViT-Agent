"""Run model-drafted auxiliary_metrics in a restricted namespace."""

from __future__ import annotations

import ast
import json
import re
from typing import Any


_FORBIDDEN_NAMES = frozenset(
    {
        "exec",
        "eval",
        "__import__",
        "compile",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "help",
        "memoryview",
    }
)


def extract_python_block(text: str) -> str:
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    stripped = text.lstrip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            return "\n".join(lines[1:]).strip()
    if "def auxiliary_metrics" in text:
        return text.strip()
    return ""


def lint_auxiliary_code(code: str, *, max_lines: int = 140) -> list[str]:
    """Pre-flight before calibrate; empty list means executable draft."""
    if not code or "def auxiliary_metrics" not in code:
        return ["missing auxiliary_metrics"]
    errs = _validate_ast(code)
    if errs:
        return errs
    if len(code.splitlines()) > max_lines:
        return [f"too_long: {len(code.splitlines())} lines > {max_lines}"]
    return []


def _validate_ast(code: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ("numpy", "PIL", "math", "json", "scipy"):
                    errors.append(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in ("numpy", "PIL", "math", "json", "scipy"):
                errors.append(f"import from not allowed: {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES:
                errors.append(f"call forbidden: {node.func.id}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "__builtins__":
                errors.append("no __builtins__ access")
    return errors


def run_auxiliary_metrics(
    code: str,
    image_path: str,
    label_obj: dict | None = None,
) -> dict[str, Any]:
    errs = _validate_ast(code)
    if errs:
        return {"error": "ast_validation", "details": errs}
    import numpy as np
    from PIL import Image

    import importlib

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".")[0]
        if root not in ("numpy", "PIL", "math", "json", "scipy"):
            raise ImportError(f"blocked import: {name}")
        return importlib.import_module(name)

    def _safe_open(file, mode="r", *args, **kwargs):  # noqa: ANN001
        if "w" in mode or "a" in mode or "+" in mode:
            raise PermissionError("auxiliary sandbox: read-only open")
        return open(file, mode, *args, **kwargs)

    safe_builtins = {
        "open": _safe_open,
        "abs": abs,
        "min": min,
        "max": max,
        "float": float,
        "int": int,
        "len": len,
        "range": range,
        "round": round,
        "sum": sum,
        "enumerate": enumerate,
        "zip": zip,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "bool": bool,
        "str": str,
        "isinstance": isinstance,
        "type": type,
        "sorted": sorted,
        "all": all,
        "any": any,
        "map": map,
        "filter": filter,
        "reversed": reversed,
        "next": next,
        "set": set,
        "frozenset": frozenset,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "__import__": _safe_import,
    }
    g: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "np": np,
        "numpy": np,
        "Image": Image,
        "json": json,
    }
    try:
        exec(compile(code, "<auxiliary_metrics>", "exec"), g, g)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        return {"error": "exec", "detail": str(exc)}
    fn = g.get("auxiliary_metrics")
    if not callable(fn):
        return {"error": "missing auxiliary_metrics()"}
    try:
        out = fn(image_path, label_obj)
    except TypeError:
        try:
            out = fn(image_path)
        except Exception as exc:  # noqa: BLE001
            return {"error": "runtime", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": "runtime", "detail": str(exc)}
    if not isinstance(out, dict):
        return {"error": "return_type", "detail": type(out).__name__}
    serializable: dict[str, Any] = {}
    for k, v in out.items():
        try:
            json.dumps(v)
            serializable[str(k)] = v
        except TypeError:
            serializable[str(k)] = str(v)
    return serializable
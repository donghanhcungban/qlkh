"""Fitness function hướng phụ thuộc cho QLKH (NFR-003, ADR-003).

Kiểm hai bất biến kiến trúc bằng AST, không cần chạy code:

1. `qlkh.domain` không import framework/ORM/HTTP.
2. Hướng phụ thuộc chỉ đi một chiều: infrastructure -> application -> domain.
   Mọi chiều ngược lại là vi phạm.

Dùng trong CI (job `fitness`) song song với import-linter; module này là bản
kiểm tối thiểu chạy được offline nên test đơn vị kiểm chứng được chính nó.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_IN_DOMAIN: frozenset[str] = frozenset(
    {
        "sqlalchemy",
        "django",
        "fastapi",
        "flask",
        "starlette",
        "requests",
        "httpx",
        "psycopg",
        "redis",
        "boto3",
    }
)

# layer -> các layer được phép import
ALLOWED_LAYER_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "application": frozenset({"domain"}),
    "infrastructure": frozenset({"domain", "application"}),
}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - chỉ để in ra CI
        return f"{self.file}:{self.line}: {self.message}"


def _imported_roots(tree: ast.AST) -> list[tuple[str, int]]:
    """Trả về (module gốc được import, số dòng) cho mọi import tuyệt đối."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # import tương đối (level > 0) luôn nằm trong cùng package -> bỏ qua
            if node.level == 0 and node.module:
                found.append((node.module, node.lineno))
    return found


def _layer_of(path: Path, package_root: Path) -> str | None:
    try:
        parts = path.relative_to(package_root).parts
    except ValueError:
        return None
    return parts[0] if parts and parts[0] in ALLOWED_LAYER_IMPORTS else None


def check_package(package_root: Path) -> list[Violation]:
    """Quét toàn bộ file .py trong package và trả danh sách vi phạm."""
    violations: list[Violation] = []
    for py_file in sorted(package_root.rglob("*.py")):
        layer = _layer_of(py_file, package_root)
        if layer is None:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        rel = str(py_file)
        for module, lineno in _imported_roots(tree):
            root = module.split(".")[0]
            if layer == "domain" and root in FORBIDDEN_IN_DOMAIN:
                violations.append(
                    Violation(rel, lineno, f"domain không được import framework/ORM/HTTP: '{module}'")
                )
            if root == package_root.name:
                target = module.split(".")[1] if module.count(".") >= 1 else None
                if target in ALLOWED_LAYER_IMPORTS and target != layer:
                    if target not in ALLOWED_LAYER_IMPORTS[layer]:
                        violations.append(
                            Violation(
                                rel,
                                lineno,
                                f"sai hướng phụ thuộc: '{layer}' không được import '{target}'",
                            )
                        )
    return violations


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent / "qlkh"
    violations = check_package(root)
    for violation in violations:
        print(f"VI PHẠM {violation}", file=sys.stderr)
    if violations:
        print(f"fitness: {len(violations)} vi phạm hướng phụ thuộc", file=sys.stderr)
        return 1
    print("fitness: hướng phụ thuộc hợp lệ")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

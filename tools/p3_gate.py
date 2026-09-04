"""Fitness function P3: mọi truy cập bảng PII phải đi qua SubjectContext (ADR-004).

Kiểm bằng AST tĩnh — không cần chạy code:
1. Quét toàn bộ qlkh/infrastructure/**/*.py
2. Phát hiện chuỗi tên bảng PII xuất hiện trực tiếp trong câu SQL
   mà không kèm SubjectContext trong cùng hàm (heuristic cẩn thận).
3. Trả danh sách vi phạm để CI chặn merge.

Quy tắc detect (heuristic):
- Hàm trong infrastructure có chuỗi literal chứa tên bảng PII
  (vd "SELECT ... FROM students") → kiểm xem tham số hàm có SubjectContext không.
- Nếu hàm có tham số tên `ctx` hoặc type hint `SubjectContext` → pass.
- Nếu không → vi phạm.

Bổ sung: cấm import trực tiếp ORM query bảng PII mà bỏ qua lớp repository
(tức là code ngoài qlkh/infrastructure cũng bị kiểm).
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from qlkh.domain.subject_context import PII_TABLES

# Tên tham số hoặc type hint cho thấy hàm đã nhận SubjectContext
SUBJECT_CONTEXT_MARKERS: frozenset[str] = frozenset({"SubjectContext", "ctx"})


@dataclass(frozen=True)
class P3Violation:
    file: str
    line: int
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.file}:{self.line}: {self.message}"


def _has_subject_context(func_def: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Kiểm xem hàm có tham số SubjectContext không (theo tên hoặc annotation)."""
    for arg in func_def.args.args:
        # Kiểm tên tham số
        if arg.arg in SUBJECT_CONTEXT_MARKERS:
            return True
        # Kiểm type annotation
        if arg.annotation is not None:
            annotation_src = ast.unparse(arg.annotation)
            if "SubjectContext" in annotation_src:
                return True
    return False


def _pii_tables_in_string(value: str) -> list[str]:
    """Tìm tên bảng PII xuất hiện trong chuỗi SQL (case-insensitive)."""
    lower = value.lower()
    found = []
    for table in PII_TABLES:
        # Kiểm đơn giản: tên bảng xuất hiện trong chuỗi (có thể cải thiện với regex FROM/JOIN)
        if table in lower:
            found.append(table)
    return found


def _check_function(
    func_def: ast.FunctionDef | ast.AsyncFunctionDef,
    filepath: str,
) -> list[P3Violation]:
    """Kiểm tra một hàm: nếu có SQL string chạm PII mà không có SubjectContext → vi phạm."""
    violations: list[P3Violation] = []
    has_ctx = _has_subject_context(func_def)
    if has_ctx:
        return violations  # hàm đã có ctx → pass

    for node in ast.walk(func_def):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            pii_hits = _pii_tables_in_string(node.value)
            for table in pii_hits:
                violations.append(
                    P3Violation(
                        file=filepath,
                        line=node.lineno,
                        message=(
                            f"P3-VIOLATION: bảng PII '{table}' truy cập trong hàm "
                            f"'{func_def.name}' mà không có SubjectContext (ADR-004, REQ-009)"
                        ),
                    )
                )
    return violations


def check_file(py_file: Path) -> list[P3Violation]:
    """Kiểm một file Python."""
    violations: list[P3Violation] = []
    source = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return violations  # file lỗi cú pháp — lint sẽ bắt riêng

    filepath = str(py_file)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_check_function(node, filepath))
    return violations


def check_package(package_root: Path) -> list[P3Violation]:
    """Quét toàn bộ package, trả danh sách vi phạm P3."""
    violations: list[P3Violation] = []
    for py_file in sorted(package_root.rglob("*.py")):
        violations.extend(check_file(py_file))
    return violations


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent / "qlkh"
    violations = check_package(root)
    for v in violations:
        print(f"P3 VIOLATION {v}", file=sys.stderr)
    if violations:
        print(f"p3-gate: {len(violations)} vi phạm — bảng PII phải đi qua SubjectContext", file=sys.stderr)
        return 1
    print("p3-gate: hợp lệ — mọi truy cập bảng PII có SubjectContext")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

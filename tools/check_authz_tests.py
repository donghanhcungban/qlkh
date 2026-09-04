"""Hook chuẩn bị NFR-001: endpoint trả PII phải có test uỷ quyền.

Đọc OpenAPI, lấy operationId của các path chạm dữ liệu cá nhân, đối chiếu với
tên test trong `tests/authz/`. Thiếu test → exit 1.

QLKH-001 chưa có endpoint nào nên job chạy ở chế độ cảnh báo; SD-01 yêu cầu bật
chặn cứng trong chính PR thêm endpoint PII đầu tiên.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

PII_PATH_MARKERS: tuple[str, ...] = (
    "students",
    "parents",
    "grades",
    "grade-history",
    "attendance",
    "materials",
    "consents",
    "erasure-requests",
)


def pii_operations(spec: dict[str, Any]) -> list[str]:
    """operationId của mọi operation nằm trên path chạm PII."""
    operations: list[str] = []
    for path, item in (spec.get("paths") or {}).items():
        if not any(marker in path for marker in PII_PATH_MARKERS):
            continue
        for method, operation in (item or {}).items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = (operation or {}).get("operationId")
            operations.append(operation_id or f"{method.upper()} {path}")
    return sorted(operations)


def missing_authz_tests(operations: list[str], test_sources: list[str]) -> list[str]:
    """operationId không xuất hiện trong bất kỳ tên test uỷ quyền nào."""
    covered: set[str] = set()
    blob = "\n".join(test_sources)
    names = set(re.findall(r"def (test_[A-Za-z0-9_]+)", blob))
    for operation in operations:
        key = re.sub(r"[^a-z0-9]+", "_", operation.lower()).strip("_")
        if any(key and key in name.lower() for name in names):
            covered.add(operation)
    return [operation for operation in operations if operation not in covered]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    spec_path = Path(argv[0]) if argv else Path("api/QLKH/openapi.yaml")
    tests_dir = Path(argv[1]) if len(argv) > 1 else Path("tests/authz")
    if not spec_path.exists():
        print(f"authz-gate: chưa có {spec_path} — bỏ qua", file=sys.stderr)
        return 0
    import yaml  # phụ thuộc chỉ cần khi thực sự đọc spec

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    sources = [p.read_text(encoding="utf-8") for p in sorted(tests_dir.glob("**/*.py"))]
    missing = missing_authz_tests(pii_operations(spec), sources)
    for operation in missing:
        print(f"authz-gate: thiếu test uỷ quyền cho '{operation}'", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

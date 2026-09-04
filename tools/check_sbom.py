"""Kiểm SBOM sinh ra đúng định dạng CycloneDX (tiêu chí chấp nhận 3 của QLKH-001)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MIN_SPEC_VERSION = "1.4"


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("bomFormat") != "CycloneDX":
        errors.append(f"bomFormat phải là 'CycloneDX', nhận '{document.get('bomFormat')}'")
    spec = str(document.get("specVersion", ""))
    if not spec:
        errors.append("thiếu specVersion")
    elif spec < MIN_SPEC_VERSION:
        errors.append(f"specVersion {spec} thấp hơn mức tối thiểu {MIN_SPEC_VERSION}")
    if "components" not in document:
        errors.append("thiếu danh sách components")
    return errors


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("dùng: check_sbom.py <sbom.cdx.json>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    if not path.exists():
        print(f"không sinh được SBOM: thiếu {path}", file=sys.stderr)
        return 1
    errors = validate(json.loads(path.read_text(encoding="utf-8")))
    for error in errors:
        print(f"SBOM không hợp lệ: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

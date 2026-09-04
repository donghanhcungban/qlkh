"""Cổng license đọc SBOM CycloneDX (SD-04).

Chặn: license nằm trong danh sách cấm, hoặc thành phần không khai báo license.
Ngoại lệ phải khai báo trong `policy/license-exceptions.json` kèm ADR và hạn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DENIED_PREFIXES: tuple[str, ...] = ("GPL", "AGPL", "LGPL", "SSPL", "BUSL", "CC-BY-NC")
EXCEPTIONS_FILE = Path("policy/license-exceptions.json")


def _licenses_of(component: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for entry in component.get("licenses", []) or []:
        node = entry.get("license") or {}
        value = node.get("id") or node.get("name") or entry.get("expression")
        if value:
            names.append(str(value))
    return names


def check(document: dict[str, Any], exceptions: set[str] | None = None) -> list[str]:
    exceptions = exceptions or set()
    problems: list[str] = []
    for component in document.get("components", []) or []:
        name = component.get("name", "<không tên>")
        if name in exceptions:
            continue
        licenses = _licenses_of(component)
        if not licenses:
            problems.append(f"{name}: không khai báo license")
            continue
        for license_name in licenses:
            if license_name.upper().startswith(DENIED_PREFIXES):
                problems.append(f"{name}: license bị cấm '{license_name}'")
    return problems


def _load_exceptions() -> set[str]:
    if not EXCEPTIONS_FILE.exists():
        return set()
    data = json.loads(EXCEPTIONS_FILE.read_text(encoding="utf-8"))
    return {item["component"] for item in data.get("exceptions", [])}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("dùng: check_licenses.py <sbom.cdx.json>", file=sys.stderr)
        return 2
    document = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    problems = check(document, _load_exceptions())
    for problem in problems:
        print(f"LICENSE {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

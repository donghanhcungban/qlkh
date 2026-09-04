"""Kiểm tra tĩnh schema QLKH (QLKH-002, REQ-002).

Không cần DB: đọc file SQL migration và metadata PII, kiểm các bất biến:

1. Mọi migration `*.up.sql` có `*.down.sql` tương ứng.
2. Migration idempotent: mọi CREATE/DROP dùng IF NOT EXISTS / IF EXISTS.
3. Down xóa đúng mọi bảng và index mà up tạo (rollback về trạng thái ban đầu).
4. Mọi cột PII khai báo trong metadata tồn tại thật và có đủ cơ sở pháp lý,
   mục đích, retention, danh sách vai được truy cập (T-11, NFR-006).

Là bản kiểm tối thiểu chạy offline nên chính nó được test đơn vị bao phủ.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_META_FIELDS = ("legal_basis", "purpose", "retention_days", "access_roles")
MAX_RETENTION_DAYS = 730  # NFR-007: lưu trữ tối đa 2 năm.

_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_CREATE_INDEX = re.compile(r"CREATE\s+INDEX\s+(IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_DROP_TABLE = re.compile(r"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_DROP_INDEX = re.compile(r"DROP\s+INDEX\s+(IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    message: str


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def parse_objects(sql: str) -> dict[str, list[str]]:
    """Trả về tên bảng/index được tạo và bị xóa, bỏ qua phần trong comment."""
    body = _strip_comments(sql)
    return {
        "tables_created": [m.group(2) for m in _CREATE_TABLE.finditer(body)],
        "indexes_created": [m.group(2) for m in _CREATE_INDEX.finditer(body)],
        "tables_dropped": [m.group(2) for m in _DROP_TABLE.finditer(body)],
        "indexes_dropped": [m.group(2) for m in _DROP_INDEX.finditer(body)],
    }


def parse_columns(sql: str) -> dict[str, set[str]]:
    """Ánh xạ bảng -> tập tên cột, đọc từ các câu CREATE TABLE."""
    body = _strip_comments(sql)
    result: dict[str, set[str]] = {}
    for match in _CREATE_TABLE.finditer(body):
        table = match.group(2)
        start = body.index("(", match.end())
        depth, i = 0, start
        while i < len(body):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        columns: set[str] = set()
        for raw in body[start + 1 : i].split(","):
            token = raw.strip().split()
            if token and token[0].upper() not in {"PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT", "FOREIGN"}:
                columns.add(token[0])
        result[table] = columns
    return result


def check_idempotent(sql: str) -> list[Violation]:
    body = _strip_comments(sql)
    violations = []
    for regex, label, guard in (
        (_CREATE_TABLE, "CREATE TABLE", "IF NOT EXISTS"),
        (_CREATE_INDEX, "CREATE INDEX", "IF NOT EXISTS"),
        (_DROP_TABLE, "DROP TABLE", "IF EXISTS"),
        (_DROP_INDEX, "DROP INDEX", "IF EXISTS"),
    ):
        for match in regex.finditer(body):
            if match.group(1) is None:
                violations.append(Violation(f"{label} {match.group(2)} thiếu {guard}: không idempotent"))
    return violations


def check_migration_pair(up_sql: str, down_sql: str) -> list[Violation]:
    up = parse_objects(up_sql)
    down = parse_objects(down_sql)
    violations = check_idempotent(up_sql) + check_idempotent(down_sql)
    for table in up["tables_created"]:
        if table not in down["tables_dropped"]:
            violations.append(Violation(f"rollback thiếu DROP TABLE cho '{table}'"))
    for index in up["indexes_created"]:
        if index not in down["indexes_dropped"]:
            violations.append(Violation(f"rollback thiếu DROP INDEX cho '{index}'"))
    for table in down["tables_dropped"]:
        if table not in up["tables_created"]:
            violations.append(Violation(f"rollback xóa '{table}' không do migration này tạo"))
    return violations


def check_pii_metadata(metadata: dict, columns_by_table: dict[str, set[str]]) -> list[Violation]:
    violations: list[Violation] = []
    seen: set[tuple[str, str]] = set()
    for entry in metadata.get("columns", []):
        table, column = entry.get("table", "?"), entry.get("column", "?")
        key = (table, column)
        if key in seen:
            violations.append(Violation(f"metadata trùng cho {table}.{column}"))
        seen.add(key)
        if column not in columns_by_table.get(table, set()):
            violations.append(Violation(f"metadata trỏ tới cột không tồn tại: {table}.{column}"))
        for field in REQUIRED_META_FIELDS:
            if not entry.get(field):
                violations.append(Violation(f"{table}.{column} thiếu '{field}'"))
        retention = entry.get("retention_days")
        if isinstance(retention, int) and retention > MAX_RETENTION_DAYS:
            violations.append(Violation(f"{table}.{column} retention {retention} ngày vượt {MAX_RETENTION_DAYS}"))
    return violations


def check_directory(db_dir: Path) -> list[Violation]:
    violations: list[Violation] = []
    columns: dict[str, set[str]] = {}
    ups = sorted((db_dir / "migrations").glob("*.up.sql"))
    if not ups:
        return [Violation("không tìm thấy migration nào")]
    for up_path in ups:
        down_path = up_path.with_name(up_path.name.replace(".up.sql", ".down.sql"))
        if not down_path.exists():
            violations.append(Violation(f"thiếu rollback cho {up_path.name}"))
            continue
        up_sql = up_path.read_text(encoding="utf-8")
        violations += check_migration_pair(up_sql, down_path.read_text(encoding="utf-8"))
        columns.update(parse_columns(up_sql))
    metadata = json.loads((db_dir / "pii_metadata.json").read_text(encoding="utf-8"))
    violations += check_pii_metadata(metadata, columns)
    return violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    db_dir = Path(args[0]) if args else Path("db")
    violations = check_directory(db_dir)
    for violation in violations:
        print(f"schema: {violation.message}")
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

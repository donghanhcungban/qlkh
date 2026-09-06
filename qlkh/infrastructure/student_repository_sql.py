"""Adapter SQL thật cho `StudentRepository` (P3) — đóng phần "repo DB thật"
của QLKH-005 (QLKH-T-02, CVSS 8.7).

Trước ticket này, `StudentService` chỉ có `FakeStudentRepo` trong test —
không có bằng chứng nào rằng bộ lọc `branch_id` được áp Ở TẦNG TRUY VẤN trên
một client SQL thật. Module này đóng khoảng trống đó theo đúng mẫu đã dùng
cho Redis (`qlkh.infrastructure.redis_counter_client`): KHÔNG import driver
DB cụ thể (không thêm phụ thuộc mới — SD-04/SD-13 vẫn đang mở ở platform),
client được TIÊM và chỉ cần thoả `SqlConnection` (psycopg/asyncpg đồng bộ
hoá đều thoả được chữ ký `execute`).

Bất biến bắt buộc (ADR-004, T-02):
- `branch_id` KHÔNG BAO GIỜ là tham số truy vấn lấy từ client; luôn lấy từ
  `ctx.allowed_branch_ids` / `ctx.role == "admin"`.
- Mọi câu SQL chạm bảng PII (`students`) tham số hoá 100% — không nối chuỗi
  giá trị người dùng vào SQL (OWASP ASVS L2, injection).
- `get_by_id`/`patch` lọc NGAY TRONG WHERE (không lọc sau khi đọc toàn bộ
  bảng) để không lộ sự tồn tại của bản ghi ngoài phạm vi (404 đồng nhất).

`tools/p3_gate.py` kiểm bằng AST rằng mọi hàm ở đây chạm chuỗi SQL có tên
bảng PII đều nhận `ctx: SubjectContext` — xem chữ ký các hàm dưới.
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.domain.subject_context import SubjectContext

# Cột trả cho client — khớp schema `Student` trong api-contract (không có
# parent_phone thô, chỉ bản đã che ở lớp trình bày; ở đây trả nguyên cột DB,
# việc che số điện thoại thuộc lớp serialize/HTTP, không thuộc repository).
_STUDENT_COLUMNS = "id, full_name, date_of_birth, branch_id, parent_phone"


class SqlRow(Protocol):
    def __getitem__(self, key: str) -> Any: ...


class SqlConnection(Protocol):
    """Tập lệnh tối thiểu cần từ client SQL đồng bộ (psycopg2/psycopg3 thoả sẵn).

    `execute` tham số hoá kiểu `%s`/`:name` tuỳ driver; ở đây dùng placeholder
    vị trí `%s` (chuẩn psycopg) — điều chỉnh khi chọn driver thật, nhưng CHỮ KÝ
    (sql, params) -> rows là hợp đồng adapter phải giữ.
    """

    def execute(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]: ...


def _branch_filter_clause(ctx: SubjectContext) -> tuple[str, tuple[Any, ...]]:
    """Mệnh đề WHERE áp phạm vi cơ sở từ ctx — KHÔNG BAO GIỜ từ tham số client.

    admin không bị giới hạn cơ sở (khớp `SubjectContext.can_access_branch`);
    vai trò khác giới hạn bằng `IN (...)` trên `allowed_branch_ids` của phiên.
    """
    if ctx.role == "admin":
        return "TRUE", ()
    if not ctx.allowed_branch_ids:
        # Phiên không có branch nào -> không thấy gì (không phải lỗi SQL).
        return "FALSE", ()
    placeholders = ", ".join(["%s"] * len(ctx.allowed_branch_ids))
    return f"branch_id IN ({placeholders})", tuple(ctx.allowed_branch_ids)


class SqlStudentRepository:
    """Hiện thực `StudentRepository` (application/repository_ports.py) trên SQL thật."""

    def __init__(self, conn: SqlConnection) -> None:
        self._conn = conn

    def get_by_id(self, ctx: SubjectContext, student_id: str) -> dict[str, Any] | None:
        branch_clause, branch_params = _branch_filter_clause(ctx)
        sql = (
            f"SELECT {_STUDENT_COLUMNS} FROM students "
            f"WHERE id = %s AND deleted_at IS NULL AND ({branch_clause})"
        )
        rows = self._conn.execute(sql, (student_id, *branch_params))
        if not rows:
            return None
        record = dict(rows[0])
        # staff/admin: OK theo branch. parent/teacher: still phải kiểm quan hệ
        # (related_student_ids) — branch một mình không đủ cho hai vai này.
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        branch_clause, branch_params = _branch_filter_clause(ctx)
        params: list[Any] = list(branch_params)
        cursor_clause = ""
        if cursor is not None:
            cursor_clause = "AND id > %s"
            params.append(cursor)
        # Lấy limit+1 để biết còn trang sau không, không đếm COUNT(*) riêng.
        params.append(limit + 1)
        sql = (
            f"SELECT {_STUDENT_COLUMNS} FROM students "
            f"WHERE deleted_at IS NULL AND ({branch_clause}) {cursor_clause} "
            f"ORDER BY id ASC LIMIT %s"
        )
        rows = [dict(r) for r in self._conn.execute(sql, tuple(params))]
        if ctx.role in ("parent", "teacher"):
            rows = [r for r in rows if r["id"] in ctx.related_student_ids]
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = page[-1]["id"] if has_more and page else None
        return page, next_cursor

    def create(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        # branch_id gán từ ctx — KHÔNG có tham số branch_id trong chữ ký hàm
        # này, nên tầng gọi (service) không có chỗ để truyền branch_id client.
        if ctx.role == "admin":
            raise ValueError("admin phải chỉ định cơ sở qua luồng quản trị riêng, không qua endpoint này")
        if not ctx.allowed_branch_ids:
            raise ValueError("phiên không có cơ sở nào để gán học viên mới")
        branch_id = ctx.allowed_branch_ids[0]
        sql = (
            f"INSERT INTO students (full_name, date_of_birth, branch_id, parent_phone) "
            f"VALUES (%s, %s, %s, %s) RETURNING {_STUDENT_COLUMNS}"
        )
        rows = self._conn.execute(sql, (full_name, date_of_birth, branch_id, parent_phone))
        return dict(rows[0])

    def patch(
        self,
        ctx: SubjectContext,
        student_id: str,
        *,
        full_name: str | None = None,
        parent_phone: str | None = None,
    ) -> dict[str, Any] | None:
        # Đọc trước qua get_by_id để tái dùng đúng một quy tắc kiểm quyền
        # (can_access_student) cho cả GET và PATCH — không viết lại logic.
        existing = self.get_by_id(ctx, student_id)
        if existing is None:
            return None
        sets: list[str] = []
        params: list[Any] = []
        if full_name is not None:
            sets.append("full_name = %s")
            params.append(full_name)
        if parent_phone is not None:
            sets.append("parent_phone = %s")
            params.append(parent_phone)
        if not sets:
            return existing
        params.append(student_id)
        sql = f"UPDATE students SET {', '.join(sets)} WHERE id = %s RETURNING {_STUDENT_COLUMNS}"
        rows = self._conn.execute(sql, tuple(params))
        if not rows:
            return None
        return dict(rows[0])

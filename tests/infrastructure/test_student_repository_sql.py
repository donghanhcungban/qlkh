"""Test adapter SQL thật của StudentRepository (QLKH-005, QLKH-T-02).

Không cần Postgres thật để kiểm bất biến quan trọng nhất: rằng branch_id áp ở
CÂU SQL (WHERE, tham số hoá), không lọc sau khi đọc toàn bảng.
`RecordingSqlConnection` giả lập một bảng trong RAM và diễn giải SQL/params đủ
để chứng minh: (1) branch_id không bao giờ là literal nối vào chuỗi SQL, luôn
là tham số bind; (2) kết quả trả về đã bị giới hạn theo branch ngay từ "store",
không phải do adapter lọc lại sau khi nhận toàn bộ dữ liệu.

Test tích hợp Postgres thật (EXPLAIN, index) thuộc SD-25 (đã ghi nợ ở schema
namespace) — cùng lô với Postgres CI service, ngoài phạm vi ticket này.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.domain.subject_context import SubjectContext
from qlkh.infrastructure.student_repository_sql import SqlStudentRepository

BRANCH_Q1 = "11111111-0000-0000-0000-000000000001"
BRANCH_THUDUC = "22222222-0000-0000-0000-000000000002"
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000020"


class RecordingSqlConnection:
    """Client SQL giả lập: thực thi trên bảng trong RAM và ghi lại mọi lệnh gọi."""

    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    @staticmethod
    def _is_admin_clause(sql_l: str) -> bool:
        return "(true)" in sql_l or "( true)" in sql_l

    def execute(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        sql_l = sql.lower()
        is_admin = self._is_admin_clause(sql_l)

        if sql_l.startswith("select") and "id = %s" in sql_l:
            student_id = params[0]
            branch_params = params[1:]
            row = self._rows.get(student_id)
            if row is None:
                return []
            if not is_admin and branch_params and row["branch_id"] not in branch_params:
                return []
            return [dict(row)]

        if sql_l.startswith("select") and "order by id" in sql_l:
            *rest, limit = params
            branch_params = tuple(rest)
            visible = [
                r
                for r in self._rows.values()
                if is_admin or not branch_params or r["branch_id"] in branch_params
            ]
            visible.sort(key=lambda r: r["id"])
            return [dict(r) for r in visible[: int(limit)]]

        if sql_l.startswith("insert"):
            full_name, dob, branch_id, phone = params
            new_id = f"new-{len(self._rows) + 1}"
            row = {
                "id": new_id,
                "full_name": full_name,
                "date_of_birth": dob,
                "branch_id": branch_id,
                "parent_phone": phone,
            }
            self._rows[new_id] = row
            return [dict(row)]

        if sql_l.startswith("update"):
            *set_params, student_id = params
            row = self._rows.get(student_id)
            if row is None:
                return []
            if "full_name = %s" in sql_l and "parent_phone = %s" in sql_l:
                row["full_name"], row["parent_phone"] = set_params
            elif "full_name = %s" in sql_l:
                (row["full_name"],) = set_params
            elif "parent_phone = %s" in sql_l:
                (row["parent_phone"],) = set_params
            return [dict(row)]

        raise AssertionError(f"SQL không mong đợi trong test double: {sql}")


@pytest.fixture()
def rows() -> dict[str, dict[str, Any]]:
    return {
        STUDENT_A: {
            "id": STUDENT_A,
            "full_name": "Bé A",
            "date_of_birth": "2018-01-01",
            "branch_id": BRANCH_Q1,
            "parent_phone": "+8490000000",
        },
        STUDENT_B: {
            "id": STUDENT_B,
            "full_name": "Bé B",
            "date_of_birth": "2019-01-01",
            "branch_id": BRANCH_THUDUC,
            "parent_phone": "+8490000001",
        },
    }


@pytest.fixture()
def conn(rows) -> RecordingSqlConnection:
    return RecordingSqlConnection(rows)


@pytest.fixture()
def repo(conn: RecordingSqlConnection) -> SqlStudentRepository:
    return SqlStudentRepository(conn)


def ctx_staff(branch_id: str) -> SubjectContext:
    return SubjectContext(user_id="staff-1", role="staff", allowed_branch_ids=(branch_id,))


class TestBranchIdKhongBaoGioTrongSqlLiteral:
    """QLKH-T-02: branch_id luôn là tham số bind, không nối chuỗi vào SQL."""

    def test_get_by_id_dung_param_khong_noi_chuoi(self, repo, conn):
        repo.get_by_id(ctx_staff(BRANCH_Q1), STUDENT_A)
        sql, params = conn.calls[-1]
        assert BRANCH_Q1 not in sql
        assert BRANCH_Q1 in params

    def test_list_for_branch_dung_param(self, repo, conn):
        repo.list_for_branch(ctx_staff(BRANCH_Q1), limit=50)
        sql, params = conn.calls[-1]
        assert BRANCH_Q1 not in sql
        assert BRANCH_Q1 in params


class TestLocGiuaCacCoSo:
    def test_get_by_id_khac_branch_tra_none(self, repo):
        result = repo.get_by_id(ctx_staff(BRANCH_THUDUC), STUDENT_A)
        assert result is None

    def test_get_by_id_cung_branch_tra_ban_ghi(self, repo):
        result = repo.get_by_id(ctx_staff(BRANCH_Q1), STUDENT_A)
        assert result is not None
        assert result["id"] == STUDENT_A

    def test_list_for_branch_chi_tra_hoc_vien_cung_branch(self, repo):
        page, next_cursor = repo.list_for_branch(ctx_staff(BRANCH_Q1), limit=50)
        assert [s["id"] for s in page] == [STUDENT_A]
        assert next_cursor is None

    def test_admin_thay_moi_co_so(self, repo):
        ctx_admin = SubjectContext(user_id="admin-1", role="admin")
        page, _ = repo.list_for_branch(ctx_admin, limit=50)
        assert {s["id"] for s in page} == {STUDENT_A, STUDENT_B}


class TestCreateGanBranchTuCtx:
    def test_create_gan_branch_id_tu_ctx_khong_nhan_tham_so(self, repo):
        record = repo.create(
            ctx_staff(BRANCH_Q1), full_name="Bé Mới", date_of_birth="2020-01-01"
        )
        assert record["branch_id"] == BRANCH_Q1

    def test_create_khong_co_tham_so_branch_id_trong_chu_ky(self):
        import inspect

        sig = inspect.signature(SqlStudentRepository.create)
        assert "branch_id" not in sig.parameters


class TestPatchTaiSuDungKiemQuyen:
    def test_patch_khac_branch_tra_none(self, repo):
        result = repo.patch(ctx_staff(BRANCH_THUDUC), STUDENT_A, full_name="X")
        assert result is None

    def test_patch_cung_branch_cap_nhat_thanh_cong(self, repo):
        result = repo.patch(ctx_staff(BRANCH_Q1), STUDENT_A, full_name="Bé A2")
        assert result is not None
        assert result["full_name"] == "Bé A2"

    def test_patch_khong_co_tham_so_branch_id_trong_chu_ky(self):
        import inspect

        sig = inspect.signature(SqlStudentRepository.patch)
        assert "branch_id" not in sig.parameters

"""Bộ test uỷ quyền dùng chung — P3 SubjectContext (QLKH-003, REQ-009).

Tiêu chí Gherkin:
  G1: Given repository truy vấn bảng PII không qua P3,
      When CI chạy, Then fail (kiểm bằng p3_gate.check_file / check_package).

  G2: Given ngữ cảnh phụ huynh A, When gọi lấy học viên B,
      Then trả 404 và không lộ tồn tại.

  G3: Given branch_id truyền từ tham số client,
      When xử lý, Then bị bỏ qua, chỉ dùng branch_id từ phiên.

Coverage bắt buộc: 100% logic uỷ quyền trong SubjectContext.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from qlkh.domain.subject_context import AccessDenied, SubjectContext

# ---------------------------------------------------------------------------
# Fixtures dùng chung
# ---------------------------------------------------------------------------

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
STUDENT_X = "xxxxxxxx-0000-0000-0000-000000000010"
STUDENT_Y = "yyyyyyyy-0000-0000-0000-000000000020"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
USER_PARENT_A = "00000000-0000-0000-0000-000000000001"
USER_TEACHER_B = "00000000-0000-0000-0000-000000000002"
USER_STAFF = "00000000-0000-0000-0000-000000000003"
USER_ADMIN = "00000000-0000-0000-0000-000000000004"


@pytest.fixture()
def ctx_parent_a() -> SubjectContext:
    """Phụ huynh A: chỉ có quyền xem STUDENT_X ở BRANCH_A."""
    return SubjectContext(
        user_id=USER_PARENT_A,
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_X,),
        related_class_ids=(),
    )


@pytest.fixture()
def ctx_teacher() -> SubjectContext:
    """Giáo viên phụ trách CLASS_1 ở BRANCH_A, thấy STUDENT_X."""
    return SubjectContext(
        user_id=USER_TEACHER_B,
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_X,),
        related_class_ids=(CLASS_1,),
    )


@pytest.fixture()
def ctx_staff() -> SubjectContext:
    """Staff ở BRANCH_A."""
    return SubjectContext(
        user_id=USER_STAFF,
        role="staff",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(),
        related_class_ids=(),
    )


@pytest.fixture()
def ctx_admin() -> SubjectContext:
    """Admin toàn hệ thống."""
    return SubjectContext(
        user_id=USER_ADMIN,
        role="admin",
        allowed_branch_ids=(),  # admin không cần khai báo branch
        related_student_ids=(),
        related_class_ids=(),
    )


# ---------------------------------------------------------------------------
# G1 — SubjectContext: kiểm tạo và validation
# ---------------------------------------------------------------------------


class TestSubjectContextValidation:
    def test_tao_thanh_cong_voi_du_truong(self):
        ctx = SubjectContext(
            user_id="u1",
            role="parent",
            allowed_branch_ids=(BRANCH_A,),
            related_student_ids=(STUDENT_X,),
            related_class_ids=(),
        )
        assert ctx.user_id == "u1"
        assert ctx.role == "parent"

    def test_user_id_rong_bi_tu_choi(self):
        with pytest.raises(ValueError, match="user_id"):
            SubjectContext(user_id="", role="parent")

    def test_role_khong_hop_le_bi_tu_choi(self):
        with pytest.raises(ValueError, match="role"):
            SubjectContext(user_id="u1", role="superuser")  # type: ignore[arg-type]

    def test_bat_bien_tuple_khong_thay_doi_duoc(self):
        ctx = SubjectContext(user_id="u1", role="staff", allowed_branch_ids=(BRANCH_A,))
        with pytest.raises((AttributeError, TypeError)):
            ctx.allowed_branch_ids = (BRANCH_B,)  # type: ignore[misc]

    def test_gia_tri_mac_dinh_la_tuple_rong(self):
        ctx = SubjectContext(user_id="u1", role="staff")
        assert ctx.allowed_branch_ids == ()
        assert ctx.related_student_ids == ()
        assert ctx.related_class_ids == ()


# ---------------------------------------------------------------------------
# G2 — Phụ huynh A không được xem học viên B (IDOR)
# Gherkin: Given ngữ cảnh phụ huynh A, When gọi lấy học viên B, Then 404
# ---------------------------------------------------------------------------


class TestParentCannotAccessOtherStudent:
    """G2 — Kiểm soát truy cập theo đối tượng cho phụ huynh."""

    def test_phu_huynh_a_xem_duoc_con_minh(self, ctx_parent_a: SubjectContext):
        # STUDENT_X là con của phụ huynh A, ở BRANCH_A
        assert ctx_parent_a.can_access_student(STUDENT_X, BRANCH_A) is True

    def test_phu_huynh_a_khong_xem_duoc_hoc_vien_khac(self, ctx_parent_a: SubjectContext):
        """G2 chính: phụ huynh A không xem được STUDENT_Y."""
        assert ctx_parent_a.can_access_student(STUDENT_Y, BRANCH_A) is False

    def test_phu_huynh_a_khong_xem_hoc_vien_co_so_khac(self, ctx_parent_a: SubjectContext):
        """G2 + T-02: phụ huynh A không xem học viên ở BRANCH_B dù là con mình."""
        # Trường hợp student được map sai branch_id → vẫn từ chối
        assert ctx_parent_a.can_access_student(STUDENT_X, BRANCH_B) is False

    def test_assert_student_access_nem_access_denied(self, ctx_parent_a: SubjectContext):
        """Repository gọi assert_student_access → nhận AccessDenied → trả None/404."""
        with pytest.raises(AccessDenied):
            ctx_parent_a.assert_student_access(STUDENT_Y, BRANCH_A)

    def test_assert_student_access_khong_nem_khi_co_quyen(self, ctx_parent_a: SubjectContext):
        # Không ném exception
        ctx_parent_a.assert_student_access(STUDENT_X, BRANCH_A)

    def test_access_denied_khong_lo_thong_tin_noi_bo(self, ctx_parent_a: SubjectContext):
        """Thông báo AccessDenied không chứa chi tiết nghiệp vụ nhạy cảm."""
        with pytest.raises(AccessDenied) as exc_info:
            ctx_parent_a.assert_student_access(STUDENT_Y, BRANCH_A)
        # Chỉ nên log trace_id, không nên chứa dữ liệu học viên
        msg = str(exc_info.value)
        assert "parent" in msg or "role" in msg  # chứa role để trace
        assert STUDENT_Y in msg  # id để trace
        # Không chứa full_name hay thông tin PII nào khác — đây là kiểm sơ bộ
        assert "full_name" not in msg
        assert "date_of_birth" not in msg


# ---------------------------------------------------------------------------
# G3 — branch_id từ client bị bỏ qua; chỉ dùng từ phiên
# Gherkin: Given branch_id truyền từ tham số client, When xử lý, Then bỏ qua
# ---------------------------------------------------------------------------


class TestBranchIdFromSessionOnly:
    """G3 — branch_id LUÔN lấy từ phiên, không từ tham số client (ADR-004, T-02)."""

    def test_staff_chi_duoc_branch_trong_phien(self, ctx_staff: SubjectContext):
        # BRANCH_A nằm trong phiên → được phép
        assert ctx_staff.can_access_branch(BRANCH_A) is True

    def test_staff_khong_duoc_branch_ngoai_phien(self, ctx_staff: SubjectContext):
        # BRANCH_B không có trong allowed_branch_ids của phiên → từ chối
        # Mô phỏng: client gửi branch_id=BRANCH_B nhưng ctx chỉ biết BRANCH_A
        assert ctx_staff.can_access_branch(BRANCH_B) is False

    def test_assert_branch_access_nem_khi_ngoai_phien(self, ctx_staff: SubjectContext):
        with pytest.raises(AccessDenied):
            ctx_staff.assert_branch_access(BRANCH_B)

    def test_assert_branch_access_pass_khi_trong_phien(self, ctx_staff: SubjectContext):
        ctx_staff.assert_branch_access(BRANCH_A)  # không ném

    def test_admin_duoc_moi_branch(self, ctx_admin: SubjectContext):
        """Admin không cần khai báo branch — được tất cả."""
        assert ctx_admin.can_access_branch(BRANCH_A) is True
        assert ctx_admin.can_access_branch(BRANCH_B) is True
        assert ctx_admin.can_access_branch("bất-kỳ-uuid-nào") is True

    def test_branch_id_client_bi_bo_qua_qua_ctx(self):
        """Kiểm tường minh: SubjectContext được tạo từ phiên, branch_id client bị bỏ.

        Giả lập handler nhận branch_id từ body client nhưng bỏ hoàn toàn,
        chỉ dùng ctx.allowed_branch_ids. Đây là bất biến kiến trúc ADR-004.
        """
        # Context từ phiên
        ctx = SubjectContext(
            user_id="u1",
            role="staff",
            allowed_branch_ids=(BRANCH_A,),
        )
        # branch_id từ client (kẻ tấn công gửi BRANCH_B)
        client_branch_id = BRANCH_B

        # Handler PHẢI bỏ qua client_branch_id, dùng ctx.allowed_branch_ids
        # Kiểm: truy cập theo client_branch_id bị từ chối
        assert ctx.can_access_branch(client_branch_id) is False
        # Truy cập theo branch từ phiên được cho phép
        assert ctx.can_access_branch(BRANCH_A) is True


# ---------------------------------------------------------------------------
# Các vai trò khác
# ---------------------------------------------------------------------------


class TestRoleBasedAccess:
    def test_teacher_xem_hoc_vien_lop_phu_trach(self, ctx_teacher: SubjectContext):
        assert ctx_teacher.can_access_student(STUDENT_X, BRANCH_A) is True

    def test_teacher_khong_xem_hoc_vien_ngoai_lop(self, ctx_teacher: SubjectContext):
        assert ctx_teacher.can_access_student(STUDENT_Y, BRANCH_A) is False

    def test_teacher_xem_lop_phu_trach(self, ctx_teacher: SubjectContext):
        assert ctx_teacher.can_access_class(CLASS_1, BRANCH_A) is True

    def test_teacher_khong_xem_lop_khac(self, ctx_teacher: SubjectContext):
        other_class = "dddddddd-0000-0000-0000-000000000200"
        assert ctx_teacher.can_access_class(other_class, BRANCH_A) is False

    def test_staff_xem_duoc_moi_hoc_vien_trong_branch(self, ctx_staff: SubjectContext):
        # staff không cần related_student_ids — chỉ cần đúng branch
        assert ctx_staff.can_access_student(STUDENT_X, BRANCH_A) is True
        assert ctx_staff.can_access_student(STUDENT_Y, BRANCH_A) is True

    def test_staff_khong_xem_hoc_vien_co_so_khac(self, ctx_staff: SubjectContext):
        assert ctx_staff.can_access_student(STUDENT_X, BRANCH_B) is False

    def test_admin_xem_duoc_tat_ca_hoc_vien(self, ctx_admin: SubjectContext):
        assert ctx_admin.can_access_student(STUDENT_X, BRANCH_A) is True
        assert ctx_admin.can_access_student(STUDENT_Y, BRANCH_B) is True

    def test_admin_xem_duoc_tat_ca_lop(self, ctx_admin: SubjectContext):
        assert ctx_admin.can_access_class(CLASS_1, BRANCH_A) is True
        assert ctx_admin.can_access_class("any", BRANCH_B) is True


# ---------------------------------------------------------------------------
# G1 — P3 fitness function: repository truy vấn thô bị chặn
# ---------------------------------------------------------------------------


class TestP3Gate:
    """G1 — Fitness function p3_gate phát hiện và chặn truy vấn thô bảng PII."""

    def test_p3_gate_chap_nhan_ham_co_ctx(self, tmp_path: Path):
        """Hàm có tham số ctx: SubjectContext → pass."""
        from tools.p3_gate import check_file

        py = tmp_path / "repo.py"
        py.write_text(
            textwrap.dedent("""\
                from qlkh.domain.subject_context import SubjectContext
                def get_student(ctx: SubjectContext, student_id: str):
                    sql = "SELECT * FROM students WHERE id = %s"
                    return sql
            """),
            encoding="utf-8",
        )
        assert check_file(py) == []

    def test_p3_gate_chap_nhan_ham_tham_so_ten_ctx(self, tmp_path: Path):
        """Hàm có tham số tên `ctx` (không cần annotation) → pass."""
        from tools.p3_gate import check_file

        py = tmp_path / "repo.py"
        py.write_text(
            textwrap.dedent("""\
                def list_students(ctx, branch_id: str):
                    sql = "SELECT * FROM students WHERE branch_id = %s"
                    return sql
            """),
            encoding="utf-8",
        )
        assert check_file(py) == []

    def test_p3_gate_chan_ham_khong_co_ctx(self, tmp_path: Path):
        """G1 chính: hàm truy vấn bảng PII mà không có SubjectContext → vi phạm."""
        from tools.p3_gate import check_file

        py = tmp_path / "bad_repo.py"
        py.write_text(
            textwrap.dedent("""\
                def get_student_raw(student_id: str):
                    sql = "SELECT * FROM students WHERE id = %s"
                    return sql
            """),
            encoding="utf-8",
        )
        violations = check_file(py)
        assert len(violations) >= 1
        assert any("students" in v.message for v in violations)
        assert any("SubjectContext" in v.message for v in violations)

    def test_p3_gate_chan_tat_ca_bang_pii(self, tmp_path: Path):
        """Tất cả bảng PII đều bị kiểm — không chỉ students."""
        from tools.p3_gate import check_file

        tables = ["parents", "parent_student", "teachers", "users", "consents"]
        for table in tables:
            py = tmp_path / f"bad_{table}.py"
            py.write_text(
                f'def fn(x: str):\n    sql = "SELECT * FROM {table}"\n    return sql\n',
                encoding="utf-8",
            )
            violations = check_file(py)
            assert any(table in v.message for v in violations), f"Không bắt được bảng PII: {table}"

    def test_p3_gate_bo_qua_ban_khong_pii(self, tmp_path: Path):
        """Bảng không phải PII (classes, enrollments) không bị kiểm."""
        from tools.p3_gate import check_file

        py = tmp_path / "ok.py"
        py.write_text(
            textwrap.dedent("""\
                def list_classes(branch_id: str):
                    sql = "SELECT * FROM classes WHERE branch_id = %s"
                    return sql
            """),
            encoding="utf-8",
        )
        assert check_file(py) == []

    def test_p3_gate_xanh_tren_repo_hien_tai(self):
        """Bất biến: repo hiện tại không vi phạm P3."""
        from tools.p3_gate import check_package

        repo_root = Path(__file__).resolve().parents[2]
        violations = check_package(repo_root / "qlkh")
        assert violations == [], "\n".join(str(v) for v in violations)

    def test_p3_gate_main_tra_exit_1_khi_co_vi_pham(self, tmp_path: Path):
        from tools.p3_gate import main

        py = tmp_path / "bad.py"
        py.write_text(
            'def fn(x): sql = "SELECT * FROM students"; return sql\n',
            encoding="utf-8",
        )
        assert main([str(tmp_path)]) == 1

    def test_p3_gate_main_tra_exit_0_khi_hop_le(self, tmp_path: Path):
        from tools.p3_gate import main

        py = tmp_path / "ok.py"
        py.write_text(
            'def fn(ctx, x): sql = "SELECT * FROM students"; return sql\n',
            encoding="utf-8",
        )
        assert main([str(tmp_path)]) == 0

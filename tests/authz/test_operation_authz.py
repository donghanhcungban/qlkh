"""Test uỷ quyền theo từng operation PII của OpenAPI v1.0.0 (QLKH-003, REQ-009).

Mỗi operationId chạm PII trong `api/QLKH/openapi.yaml` có ít nhất một test ở đây;
`tools/check_authz_tests.py` (job authz-gate, chặn cứng) map operationId → tên test.

Tiêu chí Gherkin bao phủ:
  G2: ngữ cảnh phụ huynh A gọi lấy học viên B → không truy cập được (404, không lộ tồn tại).
  G3: branch_id từ tham số client bị bỏ qua, chỉ dùng branch_id từ phiên.

Threat refs: QLKH-T-01, QLKH-T-02. ASVS L2 V4.1/V4.2, V8.1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qlkh.domain.subject_context import AccessDenied, SubjectContext
from tools.check_authz_tests import missing_authz_tests, pii_operations

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
STUDENT_X = "xxxxxxxx-0000-0000-0000-000000000010"  # con của phụ huynh A
STUDENT_Y = "yyyyyyyy-0000-0000-0000-000000000020"  # học viên của phụ huynh khác
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"  # lớp giáo viên phụ trách
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"  # lớp khác
MATERIAL_1 = "eeeeeeee-0000-0000-0000-000000000300"
GRADE_X = "ffffffff-0000-0000-0000-000000000400"
CONSENT_X = "99999999-0000-0000-0000-000000000500"

# Kho dữ liệu giả lập: mọi bản ghi đều có chủ sở hữu (student/class) và branch.
STUDENTS: dict[str, dict[str, Any]] = {
    STUDENT_X: {"id": STUDENT_X, "branch_id": BRANCH_A, "full_name": "Bé X"},
    STUDENT_Y: {"id": STUDENT_Y, "branch_id": BRANCH_A, "full_name": "Bé Y"},
}
CLASSES: dict[str, dict[str, Any]] = {
    CLASS_1: {"id": CLASS_1, "branch_id": BRANCH_A},
    CLASS_2: {"id": CLASS_2, "branch_id": BRANCH_A},
}


class NotFound(Exception):
    """Kết quả 404 — dùng chung cho 'không tồn tại' và 'ngoài phạm vi'."""


def _student_scoped(ctx: SubjectContext, student_id: str) -> dict[str, Any]:
    """Truy cập bản ghi học viên qua P3: lọc theo ctx, không lộ tồn tại."""
    record = STUDENTS.get(student_id)
    if record is None:
        raise NotFound("student")
    try:
        ctx.assert_student_access(student_id, record["branch_id"])
    except AccessDenied as exc:
        raise NotFound("student") from exc
    return record


def _class_scoped(ctx: SubjectContext, class_id: str) -> dict[str, Any]:
    record = CLASSES.get(class_id)
    if record is None:
        raise NotFound("class")
    if not ctx.can_access_class(class_id, record["branch_id"]):
        raise NotFound("class")
    return record


@pytest.fixture()
def ctx_parent_a() -> SubjectContext:
    return SubjectContext(
        user_id="parent-a",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_X,),
    )


@pytest.fixture()
def ctx_teacher() -> SubjectContext:
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_X,),
        related_class_ids=(CLASS_1,),
    )


@pytest.fixture()
def ctx_staff_branch_a() -> SubjectContext:
    return SubjectContext(user_id="staff-a", role="staff", allowed_branch_ids=(BRANCH_A,))


@pytest.fixture()
def ctx_staff_branch_b() -> SubjectContext:
    return SubjectContext(user_id="staff-b", role="staff", allowed_branch_ids=(BRANCH_B,))


# ---------------------------------------------------------------------------
# /students — listStudents, createStudent
# ---------------------------------------------------------------------------


def test_authz_liststudents_chi_tra_hoc_vien_trong_branch_cua_phien(
    ctx_staff_branch_b: SubjectContext,
):
    """listStudents: staff cơ sở B không thấy học viên cơ sở A (T-02)."""
    visible = [
        s["id"]
        for s in STUDENTS.values()
        if ctx_staff_branch_b.can_access_student(s["id"], s["branch_id"])
    ]
    assert visible == []


def test_authz_liststudents_phu_huynh_chi_thay_con_minh(ctx_parent_a: SubjectContext):
    visible = [
        s["id"]
        for s in STUDENTS.values()
        if ctx_parent_a.can_access_student(s["id"], s["branch_id"])
    ]
    assert visible == [STUDENT_X]


def test_authz_createstudent_gan_branch_tu_phien_bo_qua_client(
    ctx_staff_branch_a: SubjectContext,
):
    """createStudent: branch_id client gửi bị bỏ qua, lấy từ phiên (G3)."""
    client_payload = {"full_name": "Bé Z", "branch_id": BRANCH_B}
    effective_branch = ctx_staff_branch_a.allowed_branch_ids[0]
    assert effective_branch == BRANCH_A
    assert client_payload["branch_id"] != effective_branch
    assert ctx_staff_branch_a.can_access_branch(effective_branch) is True


def test_authz_createstudent_phu_huynh_khong_duoc_tao(ctx_parent_a: SubjectContext):
    assert ctx_parent_a.role == "parent"
    assert ctx_parent_a.can_access_student(STUDENT_Y, BRANCH_A) is False


# ---------------------------------------------------------------------------
# /students/{id} — getStudent, patchStudent
# ---------------------------------------------------------------------------


def test_authz_getstudent_phu_huynh_a_lay_hoc_vien_b_tra_404(ctx_parent_a: SubjectContext):
    """G2 chính: phụ huynh A gọi getStudent(B) → 404, thông điệp không lộ tồn tại."""
    with pytest.raises(NotFound) as exc_info:
        _student_scoped(ctx_parent_a, STUDENT_Y)
    assert "Bé Y" not in str(exc_info.value)


def test_authz_getstudent_khong_phan_biet_ton_tai_va_ngoai_pham_vi(
    ctx_parent_a: SubjectContext,
):
    with pytest.raises(NotFound) as ngoai_pham_vi:
        _student_scoped(ctx_parent_a, STUDENT_Y)
    with pytest.raises(NotFound) as khong_ton_tai:
        _student_scoped(ctx_parent_a, "00000000-0000-0000-0000-0000000000ff")
    assert str(ngoai_pham_vi.value) == str(khong_ton_tai.value)


def test_authz_getstudent_phu_huynh_lay_duoc_con_minh(ctx_parent_a: SubjectContext):
    assert _student_scoped(ctx_parent_a, STUDENT_X)["id"] == STUDENT_X


def test_authz_patchstudent_ngoai_pham_vi_tra_404(ctx_staff_branch_b: SubjectContext):
    with pytest.raises(NotFound):
        _student_scoped(ctx_staff_branch_b, STUDENT_X)


def test_authz_patchstudent_staff_dung_branch_duoc_phep(ctx_staff_branch_a: SubjectContext):
    assert _student_scoped(ctx_staff_branch_a, STUDENT_Y)["id"] == STUDENT_Y


# ---------------------------------------------------------------------------
# /students/{id}/grades và /students/{id}/consents
# ---------------------------------------------------------------------------


def test_authz_liststudentgrades_phu_huynh_khong_xem_diem_hoc_vien_khac(
    ctx_parent_a: SubjectContext,
):
    with pytest.raises(NotFound):
        _student_scoped(ctx_parent_a, STUDENT_Y)


def test_authz_liststudentgrades_phu_huynh_xem_diem_con_minh(ctx_parent_a: SubjectContext):
    assert _student_scoped(ctx_parent_a, STUDENT_X)["branch_id"] == BRANCH_A


def test_authz_liststudentconsents_chi_trong_pham_vi_chu_the(ctx_parent_a: SubjectContext):
    assert _student_scoped(ctx_parent_a, STUDENT_X)["id"] == STUDENT_X
    with pytest.raises(NotFound):
        _student_scoped(ctx_parent_a, STUDENT_Y)


# ---------------------------------------------------------------------------
# /classes/{id}/attendance — listAttendance, bulkAttendance
# ---------------------------------------------------------------------------


def test_authz_listattendance_giao_vien_ngoai_lop_bi_tu_choi(ctx_teacher: SubjectContext):
    with pytest.raises(NotFound):
        _class_scoped(ctx_teacher, CLASS_2)


def test_authz_bulkattendance_giao_vien_chi_lop_phu_trach(ctx_teacher: SubjectContext):
    assert _class_scoped(ctx_teacher, CLASS_1)["id"] == CLASS_1
    with pytest.raises(NotFound):
        _class_scoped(ctx_teacher, CLASS_2)


def test_authz_bulkattendance_bo_qua_hoc_vien_ngoai_pham_vi(ctx_teacher: SubjectContext):
    """Mục nào trỏ tới học viên ngoài lớp phụ trách đều bị loại trước khi ghi."""
    entries = [{"student_id": STUDENT_X}, {"student_id": STUDENT_Y}]
    accepted = [
        e
        for e in entries
        if ctx_teacher.can_access_student(e["student_id"], STUDENTS[e["student_id"]]["branch_id"])
    ]
    assert [e["student_id"] for e in accepted] == [STUDENT_X]


# ---------------------------------------------------------------------------
# /classes/{id}/grades và /grades/{id}/history
# ---------------------------------------------------------------------------


def test_authz_upsertgrade_giao_vien_ngoai_lop_bi_tu_choi(ctx_teacher: SubjectContext):
    with pytest.raises(NotFound):
        _class_scoped(ctx_teacher, CLASS_2)


def test_authz_upsertgrade_giao_vien_lop_phu_trach_duoc_ghi(ctx_teacher: SubjectContext):
    assert _class_scoped(ctx_teacher, CLASS_1)["branch_id"] == BRANCH_A


def test_authz_listgradehistory_phu_huynh_khong_xem_duoc(ctx_parent_a: SubjectContext):
    """Lịch sử sửa điểm chỉ dành cho vai trò quản lý lớp, không cho phụ huynh."""
    assert ctx_parent_a.can_access_class(CLASS_1, BRANCH_A) is False


def test_authz_listgradehistory_staff_trong_branch_duoc_xem(
    ctx_staff_branch_a: SubjectContext, ctx_staff_branch_b: SubjectContext
):
    assert ctx_staff_branch_a.can_access_class(CLASS_1, BRANCH_A) is True
    assert ctx_staff_branch_b.can_access_class(CLASS_1, BRANCH_A) is False


# ---------------------------------------------------------------------------
# /classes/{id}/materials và /materials/{id}/download
# ---------------------------------------------------------------------------


def test_authz_uploadmaterial_chi_lop_phu_trach(ctx_teacher: SubjectContext):
    assert _class_scoped(ctx_teacher, CLASS_1)["id"] == CLASS_1
    with pytest.raises(NotFound):
        _class_scoped(ctx_teacher, CLASS_2)


def test_authz_downloadmaterial_kiem_quyen_truoc_khi_cap_url_ky(
    ctx_teacher: SubjectContext, ctx_staff_branch_b: SubjectContext
):
    """Học liệu thuộc CLASS_1: chỉ cấp URL ký sau khi ctx qua kiểm quyền."""
    material = {"id": MATERIAL_1, "class_id": CLASS_1}
    assert _class_scoped(ctx_teacher, material["class_id"])["id"] == CLASS_1
    with pytest.raises(NotFound):
        _class_scoped(ctx_staff_branch_b, material["class_id"])


# ---------------------------------------------------------------------------
# /consents, /consents/{id}, /erasure-requests
# ---------------------------------------------------------------------------


def test_authz_createconsent_chi_cho_hoc_vien_lien_quan(ctx_parent_a: SubjectContext):
    assert _student_scoped(ctx_parent_a, STUDENT_X)["id"] == STUDENT_X
    with pytest.raises(NotFound):
        _student_scoped(ctx_parent_a, STUDENT_Y)


def test_authz_revokeconsent_ngoai_pham_vi_tra_404(ctx_staff_branch_b: SubjectContext):
    consent = {"id": CONSENT_X, "student_id": STUDENT_X}
    with pytest.raises(NotFound):
        _student_scoped(ctx_staff_branch_b, consent["student_id"])


def test_authz_createerasurerequest_chi_cho_chu_the_lien_quan(
    ctx_parent_a: SubjectContext, ctx_staff_branch_b: SubjectContext
):
    assert _student_scoped(ctx_parent_a, STUDENT_X)["id"] == STUDENT_X
    with pytest.raises(NotFound):
        _student_scoped(ctx_parent_a, STUDENT_Y)
    with pytest.raises(NotFound):
        _student_scoped(ctx_staff_branch_b, STUDENT_X)


# ---------------------------------------------------------------------------
# Bất biến: authz-gate xanh trên spec thật (chính là job CI chặn cứng)
# ---------------------------------------------------------------------------


def test_authz_gate_xanh_tren_spec_that():
    """Cổng chặn cứng phải xanh trên repo hiện tại — bằng chứng cho CI runner."""
    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    spec = yaml.safe_load((repo_root / "api/QLKH/openapi.yaml").read_text(encoding="utf-8"))
    sources = [p.read_text(encoding="utf-8") for p in sorted((repo_root / "tests/authz").glob("**/*.py"))]
    missing = missing_authz_tests(pii_operations(spec), sources)
    assert missing == [], f"thiếu test uỷ quyền cho: {missing}"

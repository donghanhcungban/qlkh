"""Test GradeService (QLKH-008, REQ-006).

Tiêu chí Gherkin (từ ticket):
  G1: Given phụ huynh A, When GET /students/B/grades (B không phải con A),
      Then 404 không lộ tồn tại.
  G2: Given giáo viên không phụ trách lớp, When POST grades, Then 403.
  G3: Given điểm chưa công bố, When phụ huynh xem, Then không thấy bản ghi.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.application.grade_service import (
    ClassNotFound,
    ClassPermissionDenied,
    GradeService,
    InvalidGradeInput,
    StudentNotFound,
)
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"  # giáo viên phụ trách
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"  # giáo viên KHÔNG phụ trách, cùng cơ sở
STUDENT_SON = "aaaaaaaa-0000-0000-0000-000000000010"  # con của phụ huynh A
STUDENT_OTHER = "bbbbbbbb-0000-0000-0000-000000000020"  # không phải con phụ huynh A


class FakeClassRepo:
    def __init__(self, classes: dict[str, dict[str, Any]]) -> None:
        self._classes = classes

    def get_by_id(self, ctx, class_id):
        record = self._classes.get(class_id)
        if record is None:
            return None
        if not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    # Không dùng ở test này nhưng Protocol yêu cầu đủ chữ ký nếu type-check
    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        return [], None

    def create(self, ctx, *, name, teacher_id=None):
        raise NotImplementedError

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):
        raise NotImplementedError

    def unenroll(self, ctx, class_id, student_id):
        raise NotImplementedError


class FakeGradeRepo:
    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students
        self._grades: dict[tuple[str, str], dict[str, Any]] = {}
        self._seq = 0

    def get_student_ref(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None:
            return None
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def get_existing(self, ctx, class_id, student_id):
        return self._grades.get((class_id, student_id))

    def upsert(self, ctx, class_id, *, student_id, score, publish, reason):
        self._seq += 1
        record = self._grades.get((class_id, student_id)) or {
            "id": f"grade-{self._seq}",
            "student_id": student_id,
            "class_id": class_id,
        }
        record = {**record, "score": score, "published": publish}
        self._grades[(class_id, student_id)] = record
        return record

    def list_for_student(self, ctx, student_id):
        return [r for r in self._grades.values() if r["student_id"] == student_id]

    def seed_grade(self, class_id, student_id, *, score, published):
        self._grades[(class_id, student_id)] = {
            "id": f"seed-{class_id}-{student_id}",
            "class_id": class_id,
            "student_id": student_id,
            "score": score,
            "published": published,
        }


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event, **fields):
        self.events.append({"event": event, **fields})


def make_classes() -> FakeClassRepo:
    return FakeClassRepo(
        {
            CLASS_1: {"id": CLASS_1, "name": "L1", "branch_id": BRANCH_A, "teacher_id": "t1"},
            CLASS_2: {"id": CLASS_2, "name": "L2", "branch_id": BRANCH_A, "teacher_id": "t2"},
        }
    )


def make_students() -> FakeGradeRepo:
    return FakeGradeRepo(
        {
            STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A},
            STUDENT_OTHER: {"id": STUDENT_OTHER, "branch_id": BRANCH_A},
        }
    )


def make_service(classes=None, grades=None) -> tuple[GradeService, RecordingAudit]:
    audit = RecordingAudit()
    service = GradeService(classes or make_classes(), grades or make_students(), audit)
    return service, audit


def teacher_ctx(
    related_class_ids=(CLASS_1,), related_student_ids=(STUDENT_SON,)
) -> SubjectContext:
    # `related_student_ids` mô phỏng dữ liệu nạp từ enrollments của lớp giáo
    # viên phụ trách khi build context thật (docstring SubjectContext).
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=related_class_ids,
        related_student_ids=related_student_ids,
    )


def parent_ctx(related_student_ids=(STUDENT_SON,)) -> SubjectContext:
    return SubjectContext(
        user_id="parent-a",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=related_student_ids,
    )


# ---------------------------------------------------------------------- #
# G1: phụ huynh A xem GET /students/B/grades (B không phải con A) -> 404
# ---------------------------------------------------------------------- #
def test_parent_viewing_other_student_grades_gets_not_found():
    service, _ = make_service()
    ctx = parent_ctx(related_student_ids=(STUDENT_SON,))

    with pytest.raises(StudentNotFound):
        service.list_student_grades(ctx, STUDENT_OTHER)


def test_parent_viewing_own_child_grades_succeeds():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _ = make_service(grades=grades)
    ctx = parent_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert len(records) == 1
    assert records[0]["student_id"] == STUDENT_SON


# ---------------------------------------------------------------------- #
# G2: giáo viên không phụ trách lớp -> POST grades -> 403
# ---------------------------------------------------------------------- #
def test_teacher_not_assigned_to_class_gets_forbidden():
    service, _ = make_service()
    ctx = teacher_ctx(related_class_ids=(CLASS_1,))  # không phụ trách CLASS_2

    with pytest.raises(ClassPermissionDenied):
        service.upsert_grade(ctx, CLASS_2, student_id=STUDENT_SON, score=8.0)


def test_teacher_assigned_to_class_can_post_grade():
    service, audit = make_service()
    ctx = teacher_ctx(related_class_ids=(CLASS_1,))

    record = service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=8.5)

    assert record["score"] == 8.5
    assert record["published"] is False
    assert audit.events[-1]["event"] == "grade.upserted"


def test_class_not_found_or_out_of_branch_is_404():
    service, _ = make_service()
    unknown_branch_ctx = SubjectContext(
        user_id="teacher-2", role="teacher", allowed_branch_ids=(BRANCH_B,)
    )

    with pytest.raises(ClassNotFound):
        service.upsert_grade(unknown_branch_ctx, CLASS_1, student_id=STUDENT_SON, score=7)


# ---------------------------------------------------------------------- #
# G3: điểm chưa công bố, phụ huynh xem -> không thấy bản ghi
# ---------------------------------------------------------------------- #
def test_unpublished_grade_hidden_from_parent():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=False)
    service, _ = make_service(grades=grades)
    ctx = parent_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert records == []


def test_unpublished_grade_visible_to_teacher():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=False)
    service, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert len(records) == 1


# ---------------------------------------------------------------------- #
# Đường lỗi khác
# ---------------------------------------------------------------------- #
def test_score_out_of_range_is_invalid():
    service, _ = make_service()
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=11)


def test_empty_student_id_is_invalid():
    service, _ = make_service()
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id="", score=5)


def test_editing_published_grade_without_reason_is_invalid():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=7.0)


def test_editing_published_grade_with_reason_succeeds():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    record = service.upsert_grade(
        ctx, CLASS_1, student_id=STUDENT_SON, score=7.0, reason="Sửa nhầm điểm"
    )

    assert record["score"] == 7.0


def test_parent_cannot_post_grade():
    service, _ = make_service()
    ctx = parent_ctx()

    with pytest.raises(ClassPermissionDenied):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=5)

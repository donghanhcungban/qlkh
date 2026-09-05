"""Test GradeHttpHandlers (QLKH-008, REQ-006) — mapping lỗi domain -> Problem Details."""

from __future__ import annotations

from typing import Any

from qlkh.application.grade_http import GradeHttpHandlers
from qlkh.application.grade_service import GradeService
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"
STUDENT_SON = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_OTHER = "bbbbbbbb-0000-0000-0000-000000000020"


class FakeClassRepo:
    def __init__(self):
        self._classes = {
            CLASS_1: {"id": CLASS_1, "branch_id": BRANCH_A},
            CLASS_2: {"id": CLASS_2, "branch_id": BRANCH_A},
        }

    def get_by_id(self, ctx, class_id):
        record = self._classes.get(class_id)
        if record is None or not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        return [], None

    def create(self, ctx, *, name, teacher_id=None):
        raise NotImplementedError

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):
        raise NotImplementedError

    def unenroll(self, ctx, class_id, student_id):
        raise NotImplementedError


class FakeGradeRepo:
    def __init__(self):
        self._students = {
            STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A},
            STUDENT_OTHER: {"id": STUDENT_OTHER, "branch_id": BRANCH_A},
        }
        self._grades: dict[tuple[str, str], dict[str, Any]] = {}

    def get_student_ref(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def get_existing(self, ctx, class_id, student_id):
        return self._grades.get((class_id, student_id))

    def upsert(self, ctx, class_id, *, student_id, score, publish, reason):
        record = {
            "id": "grade-1",
            "class_id": class_id,
            "student_id": student_id,
            "score": score,
            "published": publish,
        }
        self._grades[(class_id, student_id)] = record
        return record

    def list_for_student(self, ctx, student_id):
        return [r for r in self._grades.values() if r["student_id"] == student_id]


class NullAudit:
    def record(self, event, **fields):
        pass


def make_handlers() -> GradeHttpHandlers:
    service = GradeService(FakeClassRepo(), FakeGradeRepo(), NullAudit())
    return GradeHttpHandlers(service)


def teacher_ctx(related_class_ids=(CLASS_1,)) -> SubjectContext:
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=related_class_ids,
    )


def parent_ctx(related_student_ids=(STUDENT_SON,)) -> SubjectContext:
    return SubjectContext(
        user_id="parent-a",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=related_student_ids,
    )


def test_post_grade_forbidden_for_unassigned_teacher():
    handlers = make_handlers()
    ctx = teacher_ctx(related_class_ids=(CLASS_1,))

    result = handlers.upsert_grade(ctx, CLASS_2, {"student_id": STUDENT_SON, "score": 8})

    assert result.status == 403
    assert result.body["type"] == "https://qlkh/errors/forbidden"


def test_post_grade_success():
    handlers = make_handlers()
    ctx = teacher_ctx()

    result = handlers.upsert_grade(ctx, CLASS_1, {"student_id": STUDENT_SON, "score": 8})

    assert result.status == 201
    assert result.body["score"] == 8


def test_get_student_grades_not_found_for_other_parent():
    handlers = make_handlers()
    ctx = parent_ctx(related_student_ids=(STUDENT_SON,))

    result = handlers.list_student_grades(ctx, STUDENT_OTHER)

    assert result.status == 404
    assert result.body["type"] == "https://qlkh/errors/not-found"
    # Không lộ chi tiết nội bộ trong detail.
    assert "detail" not in result.body


def test_get_student_grades_hides_unpublished_for_parent():
    handlers = make_handlers()
    teacher = teacher_ctx()
    handlers.upsert_grade(teacher, CLASS_1, {"student_id": STUDENT_SON, "score": 9})

    parent = parent_ctx()
    result = handlers.list_student_grades(parent, STUDENT_SON)

    assert result.status == 200
    assert result.body["data"] == []

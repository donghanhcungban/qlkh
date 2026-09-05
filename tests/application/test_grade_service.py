"""Test GradeService (QLKH-008, REQ-006; QLKH-009, REQ-008).

Tiêu chí Gherkin (QLKH-008):
  G1: Given phụ huynh A, When GET /students/B/grades (B không phải con A),
      Then 404 không lộ tồn tại.
  G2: Given giáo viên không phụ trách lớp, When POST grades, Then 403.
  G3: Given điểm chưa công bố, When phụ huynh xem, Then không thấy bản ghi.

Tiêu chí Gherkin (QLKH-009):
  H1: Given giáo viên sửa điểm đã công bố không nêu lý do, When POST, Then 422.
  H2: Given điểm được sửa, When kiểm bảng lịch sử, Then có bản ghi cũ/mới
      kèm actor và thời điểm.
  H3: (DB-level, xem tests/schema — Protocol này không expose update/delete).
  Bổ sung: sửa điểm ĐÃ công bố -> notifier được gọi (thông báo phụ huynh).
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


class FakeGradeHistoryRepo:
    """`GradeHistoryRepository` append-only (QLKH-009): chỉ `record`/
    `list_for_grade`, không có phương thức update/delete."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._seq = 0

    def record(self, ctx, *, grade_id, old_score, new_score, actor_id, reason):
        self._seq += 1
        entry = {
            "id": f"hist-{self._seq}",
            "grade_id": grade_id,
            "old_score": old_score,
            "new_score": new_score,
            "actor_id": actor_id,
            "changed_at": f"t{self._seq}",
            "reason": reason,
        }
        self._entries.append(entry)
        return entry

    def list_for_grade(self, ctx, grade_id):
        return [e for e in self._entries if e["grade_id"] == grade_id]


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def notify_grade_revised(self, ctx, **fields):
        self.calls.append(fields)


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


def make_service(classes=None, grades=None, history=None, notifier=None):
    audit = RecordingAudit()
    history = history if history is not None else FakeGradeHistoryRepo()
    notifier = notifier if notifier is not None else RecordingNotifier()
    service = GradeService(
        classes or make_classes(), grades or make_students(), audit, history, notifier
    )
    return service, audit, history, notifier


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
    service, _, _, _ = make_service()
    ctx = parent_ctx(related_student_ids=(STUDENT_SON,))

    with pytest.raises(StudentNotFound):
        service.list_student_grades(ctx, STUDENT_OTHER)


def test_parent_viewing_own_child_grades_succeeds():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, _, _ = make_service(grades=grades)
    ctx = parent_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert len(records) == 1
    assert records[0]["student_id"] == STUDENT_SON


# ---------------------------------------------------------------------- #
# G2: giáo viên không phụ trách lớp -> POST grades -> 403
# ---------------------------------------------------------------------- #
def test_teacher_not_assigned_to_class_gets_forbidden():
    service, _, _, _ = make_service()
    ctx = teacher_ctx(related_class_ids=(CLASS_1,))  # không phụ trách CLASS_2

    with pytest.raises(ClassPermissionDenied):
        service.upsert_grade(ctx, CLASS_2, student_id=STUDENT_SON, score=8.0)


def test_teacher_assigned_to_class_can_post_grade():
    service, audit, _, _ = make_service()
    ctx = teacher_ctx(related_class_ids=(CLASS_1,))

    record = service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=8.5)

    assert record["score"] == 8.5
    assert record["published"] is False
    assert audit.events[-1]["event"] == "grade.upserted"


def test_class_not_found_or_out_of_branch_is_404():
    service, _, _, _ = make_service()
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
    service, _, _, _ = make_service(grades=grades)
    ctx = parent_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert records == []


def test_unpublished_grade_visible_to_teacher():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=False)
    service, _, _, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    records = service.list_student_grades(ctx, STUDENT_SON)

    assert len(records) == 1


# ---------------------------------------------------------------------- #
# Đường lỗi khác
# ---------------------------------------------------------------------- #
def test_score_out_of_range_is_invalid():
    service, _, _, _ = make_service()
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=11)


def test_empty_student_id_is_invalid():
    service, _, _, _ = make_service()
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id="", score=5)


def test_editing_published_grade_without_reason_is_invalid():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, _, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=7.0)


def test_editing_published_grade_with_reason_succeeds():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, _, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    record = service.upsert_grade(
        ctx, CLASS_1, student_id=STUDENT_SON, score=7.0, reason="Sửa nhầm điểm"
    )

    assert record["score"] == 7.0


def test_parent_cannot_post_grade():
    service, _, _, _ = make_service()
    ctx = parent_ctx()

    with pytest.raises(ClassPermissionDenied):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=5)


# ---------------------------------------------------------------------- #
# H1 (QLKH-009): sửa điểm đã công bố không nêu lý do -> 422
# (đã kiểm ở test_editing_published_grade_without_reason_is_invalid; giữ
# alias tường minh theo tên Gherkin để dễ truy vết requirement)
# ---------------------------------------------------------------------- #
def test_h1_editing_published_grade_without_reason_raises_422_equivalent():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, history, notifier = make_service(grades=grades)
    ctx = teacher_ctx()

    with pytest.raises(InvalidGradeInput):
        service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=7.0)

    # Không được ghi lịch sử hay gửi thông báo khi bị từ chối ở bước validate.
    assert history.list_for_grade(ctx, "seed-" + CLASS_1 + "-" + STUDENT_SON) == []
    assert notifier.calls == []


# ---------------------------------------------------------------------- #
# H2 (QLKH-009): điểm được sửa -> bảng lịch sử có bản ghi cũ/mới + actor +
# thời điểm.
# ---------------------------------------------------------------------- #
def test_h2_editing_grade_appends_history_entry_with_old_new_actor():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, history, _ = make_service(grades=grades)
    ctx = teacher_ctx()

    record = service.upsert_grade(
        ctx, CLASS_1, student_id=STUDENT_SON, score=7.0, reason="Sửa nhầm điểm"
    )

    entries = history.list_for_grade(ctx, record["id"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["old_score"] == 9.0
    assert entry["new_score"] == 7.0
    assert entry["actor_id"] == "teacher-1"
    assert entry["changed_at"]
    assert entry["reason"] == "Sửa nhầm điểm"


def test_editing_unpublished_grade_also_appends_history_but_no_notify():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=False)
    service, _, history, notifier = make_service(grades=grades)
    ctx = teacher_ctx()

    record = service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=6.0)

    entries = history.list_for_grade(ctx, record["id"])
    assert len(entries) == 1
    assert entries[0]["old_score"] == 9.0
    assert entries[0]["new_score"] == 6.0
    # Điểm chưa công bố bị sửa -> không cần báo phụ huynh.
    assert notifier.calls == []


def test_first_time_grading_does_not_append_history():
    service, _, history, _ = make_service()
    ctx = teacher_ctx()

    record = service.upsert_grade(ctx, CLASS_1, student_id=STUDENT_SON, score=8.0)

    assert history.list_for_grade(ctx, record["id"]) == []


# ---------------------------------------------------------------------- #
# Thông báo phụ huynh khi điểm ĐÃ CÔNG BỐ bị sửa (QLKH-009, scope)
# ---------------------------------------------------------------------- #
def test_editing_published_grade_notifies_parent():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, _, notifier = make_service(grades=grades)
    ctx = teacher_ctx()

    service.upsert_grade(
        ctx, CLASS_1, student_id=STUDENT_SON, score=7.0, reason="Sửa nhầm điểm"
    )

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["student_id"] == STUDENT_SON
    assert call["class_id"] == CLASS_1
    assert call["old_score"] == 9.0
    assert call["new_score"] == 7.0
    assert call["reason"] == "Sửa nhầm điểm"


# ---------------------------------------------------------------------- #
# GET /grades/{id}/history — quyền: chỉ giáo viên/nhân viên/quản trị
# ---------------------------------------------------------------------- #
def test_parent_cannot_list_grade_history():
    service, _, _, _ = make_service()
    ctx = parent_ctx()

    with pytest.raises(ClassPermissionDenied):
        service.list_grade_history(ctx, "grade-1")


def test_teacher_can_list_grade_history():
    grades = make_students()
    grades.seed_grade(CLASS_1, STUDENT_SON, score=9.0, published=True)
    service, _, history, _ = make_service(grades=grades)
    ctx = teacher_ctx()
    record = service.upsert_grade(
        ctx, CLASS_1, student_id=STUDENT_SON, score=7.0, reason="Sửa nhầm điểm"
    )

    entries = service.list_grade_history(ctx, record["id"])

    assert len(entries) == 1


def test_list_grade_history_out_of_scope_is_forbidden():
    class DenyingHistoryRepo(FakeGradeHistoryRepo):
        def list_for_grade(self, ctx, grade_id):
            return None

    service, _, _, _ = make_service(history=DenyingHistoryRepo())
    ctx = teacher_ctx()

    with pytest.raises(ClassPermissionDenied):
        service.list_grade_history(ctx, "grade-out-of-scope")

"""Kịch bản tải rút gọn cho AttendanceService (QLKH-007, REQ-005, NFR-004).

G2: Given 60 giáo viên điểm danh đồng thời, When chạy kịch bản tải,
    Then p95 đạt ngưỡng NFR-004.

QUAN TRỌNG — phạm vi thật của test này: đây là smoke test Ở TẦNG DOMAIN/
APPLICATION, chạy 60 luồng gọi đồng thời `AttendanceService.bulk_attendance`
với repository giả lập trong RAM (khoá đơn giản để mô phỏng ghi tuần tự an
toàn dưới tải). Nó KHÔNG đo được p95 thật của hệ thống (không có DB/mạng/HTTP
thật — kịch bản tải thật trên staging là trách nhiệm hạ tầng/observability,
xem `architecture` fitness function #4). Test này chỉ là hồi quy hai việc
nằm trong tầm với của backend:
  1. Domain layer không có tranh chấp/deadlock khi 60 luồng gọi đồng thời
     (không có state global không khoá bị ghi đè).
  2. Chi phí tính toán thuần Python của một lần gọi đủ nhỏ để không tự nó
     là nút thắt cổ chai trước khi tới lớp DB/HTTP thật.
Ngưỡng dùng ở đây (`_P95_BUDGET_SECONDS`) là ngân sách nội bộ rộng rãi cho
riêng phần domain, KHÔNG phải giá trị số của NFR-004 (blackboard hiện chưa
có con số NFR-004 tường minh) — không suy diễn số liệu đó ở đây.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from qlkh.application.attendance_service import AttendanceService
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
CONCURRENT_TEACHERS = 60
_P95_BUDGET_SECONDS = 0.2


class FakeClassRepo:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def get_by_id(self, ctx, class_id):
        if class_id != self._record["id"] or not ctx.can_access_branch(self._record["branch_id"]):
            return None
        return self._record

    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        raise NotImplementedError

    def create(self, ctx, *, name, teacher_id=None):
        raise NotImplementedError

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):
        raise NotImplementedError

    def unenroll(self, ctx, class_id, student_id):
        raise NotImplementedError


class ThreadSafeAttendanceRepo:
    """Repo giả lập có khoá — mô phỏng ràng buộc ghi tuần tự an toàn của DB
    thật dưới tải đồng thời, không phải để đo hiệu năng DB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self._seq = 0

    def bulk_insert(self, ctx, class_id, entries, *, attendance_at):
        out = []
        with self._lock:
            for entry in entries:
                self._seq += 1
                record = {
                    "id": f"att-{self._seq}",
                    "class_id": class_id,
                    "student_id": entry["student_id"],
                    "status": entry["status"],
                    "attendance_at": attendance_at,
                }
                self.records.append(record)
                out.append(record)
        return out

    def list_for_class(self, ctx, class_id, *, cursor=None, limit=50):
        with self._lock:
            visible = [r for r in self.records if r["class_id"] == class_id]
        return visible[:limit], None


class NullAudit:
    def record(self, event: str, **fields: Any) -> None:
        return None


def _teacher_ctx(index: int) -> SubjectContext:
    return SubjectContext(
        user_id=f"teacher-{index}",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


def test_60_giao_vien_diem_danh_dong_thoi_p95_trong_ngan_sach_domain():
    class_record = {"id": CLASS_1, "name": "Lớp 1", "branch_id": BRANCH_A, "teacher_id": "t"}
    service = AttendanceService(
        classes=FakeClassRepo(class_record),
        attendance=ThreadSafeAttendanceRepo(),
        audit=NullAudit(),
        clock=lambda: datetime.now(UTC),
    )

    latencies: list[float] = []
    latencies_lock = threading.Lock()

    def call(index: int) -> None:
        ctx = _teacher_ctx(index)
        entries = [{"student_id": f"student-{index}-{j}", "status": "present"} for j in range(5)]
        started = time.perf_counter()
        records = service.bulk_attendance(ctx, CLASS_1, entries)
        elapsed = time.perf_counter() - started
        assert len(records) == 5
        with latencies_lock:
            latencies.append(elapsed)

    with ThreadPoolExecutor(max_workers=CONCURRENT_TEACHERS) as pool:
        list(pool.map(call, range(CONCURRENT_TEACHERS)))

    assert len(latencies) == CONCURRENT_TEACHERS
    p95 = statistics.quantiles(latencies, n=100)[94]
    assert p95 < _P95_BUDGET_SECONDS, (
        f"p95 domain-layer ({p95:.4f}s) vượt ngân sách nội bộ "
        f"({_P95_BUDGET_SECONDS}s) — không phải NFR-004 thật, xem docstring."
    )

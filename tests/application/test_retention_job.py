"""Test RetentionJob (QLKH-012, REQ-011, NFR-006/007).

Tiêu chí Gherkin của ticket:
  G1: Given yêu cầu xóa, When job chạy trong 30 ngày, Then dữ liệu biến mất
      khỏi DB, log và lưu trữ lạnh.
  G2: Given dữ liệu quá 2 năm, When job chạy, Then chuyển sang lưu trữ lạnh
      và ghi báo cáo.
  G3: Given job hoàn tất, When kiểm release-check, Then có báo cáo số bản
      ghi kèm thời điểm.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from qlkh.application.retention_job import ARCHIVE_AFTER_DAYS, RetentionJob

FIXED_NOW = datetime(2026, 9, 6, tzinfo=UTC)
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000020"


class FakeRetentionSource:
    def __init__(self) -> None:
        self.overdue_by_table: dict[str, list[str]] = {}
        self.moved: dict[str, list[str]] = {}
        self.erase_calls: list[str] = []
        self.erase_result: dict[str, int] = {"students": 1, "consents": 2}

    def find_overdue(self, table, anchor_column, cutoff):
        return self.overdue_by_table.get(table, [])

    def move_to_cold(self, table, record_ids):
        self.moved[table] = record_ids
        return len(record_ids)

    def erase_subject(self, subject_student_id):
        self.erase_calls.append(subject_student_id)
        return dict(self.erase_result)


class FakeColdArchive:
    def __init__(self) -> None:
        self.erase_calls: list[str] = []

    def erase_subject(self, subject_student_id):
        self.erase_calls.append(subject_student_id)
        return 3


class FakeLogEraser:
    def __init__(self) -> None:
        self.erase_calls: list[str] = []

    def erase_subject(self, subject_student_id):
        self.erase_calls.append(subject_student_id)
        return 5


class FakeErasureRequests:
    def __init__(self, pending: list[dict[str, Any]]) -> None:
        self._pending = pending
        self.completed: list[str] = []

    def list_pending(self, *, as_of):
        return list(self._pending)

    def mark_completed(self, request_id, *, completed_at):
        self.completed.append(request_id)
        self._pending = [r for r in self._pending if r["id"] != request_id]


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event, **fields):
        self.events.append((event, fields))


def test_g1_run_erasure_lan_toi_db_log_va_luu_tru_lanh():
    pending = [
        {
            "id": "req-1",
            "subject_student_id": STUDENT_A,
            "due_at": (FIXED_NOW + timedelta(days=5)).isoformat(),
        }
    ]
    source = FakeRetentionSource()
    cold = FakeColdArchive()
    logs = FakeLogEraser()
    requests = FakeErasureRequests(pending)
    job = RetentionJob(
        retention_source=source,
        cold_archive=cold,
        log_eraser=logs,
        erasure_requests=requests,
        audit=RecordingAudit(),
        pii_tables={},
        now=lambda: FIXED_NOW,
    )

    report = job.run_erasure()

    assert source.erase_calls == [STUDENT_A]
    assert cold.erase_calls == [STUDENT_A]
    assert logs.erase_calls == [STUDENT_A]
    assert requests.completed == ["req-1"]
    assert report.completed_request_ids == ("req-1",)
    assert report.overdue_request_ids == ()
    assert report.total_erased == 1 + 2 + 5 + 3  # students+consents (source) + logs + cold
    assert report.run_at == FIXED_NOW


def test_g1_yeu_cau_qua_han_30_ngay_van_duoc_xu_ly_nhung_bao_cao_rieng():
    overdue_due_at = (FIXED_NOW - timedelta(days=1)).isoformat()
    pending = [{"id": "req-late", "subject_student_id": STUDENT_B, "due_at": overdue_due_at}]
    audit = RecordingAudit()
    requests = FakeErasureRequests(pending)
    job = RetentionJob(
        retention_source=FakeRetentionSource(),
        cold_archive=FakeColdArchive(),
        log_eraser=FakeLogEraser(),
        erasure_requests=requests,
        audit=audit,
        pii_tables={},
        now=lambda: FIXED_NOW,
    )

    report = job.run_erasure()

    assert report.overdue_request_ids == ("req-late",)
    assert report.completed_request_ids == ("req-late",)  # vẫn xóa, không bỏ sót
    assert requests.completed == ["req-late"]
    event_names = [name for name, _ in audit.events]
    assert "erasure_sla_breach" in event_names
    assert "erasure_completed" in event_names


def test_g2_du_lieu_qua_2_nam_chuyen_sang_luu_tru_lanh():
    source = FakeRetentionSource()
    source.overdue_by_table = {"students": ["s1", "s2"], "consents": []}
    audit = RecordingAudit()
    job = RetentionJob(
        retention_source=source,
        cold_archive=FakeColdArchive(),
        log_eraser=FakeLogEraser(),
        erasure_requests=FakeErasureRequests([]),
        audit=audit,
        pii_tables={"students": "created_at", "consents": "granted_at"},
        now=lambda: FIXED_NOW,
    )

    report = job.run_archive()

    assert source.moved["students"] == ["s1", "s2"]
    assert report.archived_counts == {"students": 2, "consents": 0}
    assert report.total_archived == 2
    assert report.run_at == FIXED_NOW
    event_names = [name for name, _ in audit.events]
    assert "retention_archived" in event_names


def test_g2_cutoff_dung_bang_2_nam():
    captured_cutoffs: dict[str, datetime] = {}

    class CapturingSource(FakeRetentionSource):
        def find_overdue(self, table, anchor_column, cutoff):
            captured_cutoffs[table] = cutoff
            return []

    job = RetentionJob(
        retention_source=CapturingSource(),
        cold_archive=FakeColdArchive(),
        log_eraser=FakeLogEraser(),
        erasure_requests=FakeErasureRequests([]),
        audit=RecordingAudit(),
        pii_tables={"students": "created_at"},
        now=lambda: FIXED_NOW,
    )

    job.run_archive()

    assert captured_cutoffs["students"] == FIXED_NOW - timedelta(days=ARCHIVE_AFTER_DAYS)


def test_g3_report_mang_so_ban_ghi_va_thoi_diem():
    pending = [
        {"id": "r1", "subject_student_id": STUDENT_A, "due_at": (FIXED_NOW + timedelta(days=1)).isoformat()},
        {"id": "r2", "subject_student_id": STUDENT_B, "due_at": (FIXED_NOW + timedelta(days=2)).isoformat()},
    ]
    job = RetentionJob(
        retention_source=FakeRetentionSource(),
        cold_archive=FakeColdArchive(),
        log_eraser=FakeLogEraser(),
        erasure_requests=FakeErasureRequests(pending),
        audit=RecordingAudit(),
        pii_tables={},
        now=lambda: FIXED_NOW,
    )

    report = job.run_erasure()

    assert report.run_at == FIXED_NOW
    assert len(report.completed_request_ids) == 2
    assert report.total_erased > 0

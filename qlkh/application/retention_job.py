"""Job retention/xóa (P4) — QLKH-012, REQ-011, NFR-006/007.

Hai trách nhiệm tách bạch (Gherkin của ticket):

- G1 (xóa thật): Given yêu cầu xóa, When job chạy trong 30 ngày, Then dữ
  liệu biến mất khỏi DB, log VÀ lưu trữ lạnh. `run_erasure` xử lý MỌI yêu
  cầu đang `pending`, lan xóa tới ba nơi qua ba Protocol tách biệt
  (`RetentionSource.erase_subject`, `LogEraser.erase_subject`,
  `ColdArchiveEraser.erase_subject`) rồi mới đánh dấu hoàn tất — không đánh
  dấu hoàn tất nếu một nhánh xóa nào ném lỗi (không xử lý âm thầm, RISK-8).
- G2 (lưu trữ lạnh): Given dữ liệu quá 2 năm (theo `retention_anchor` +
  `retention_days` khai báo trong `pii_metadata.json`, xem `schema`),
  When job chạy, Then CHUYỂN (không xóa) sang lưu trữ lạnh và ghi báo cáo.
- G3 (báo cáo): mỗi lần chạy (`run_archive`/`run_erasure`) trả về một report
  bất biến mang số bản ghi + thời điểm (`run_at`), và phát audit tương ứng
  để release-check kiểm tra được (REQ-011 tiêu chí 3).

Domain thuần: không import DB/HTTP/ORM (fitness function kiểm bằng AST).
Adapter hạ tầng (Postgres thật, cold storage thật, log sink thật) hiện thực
các Protocol port bên dưới; đây chỉ là orchestration logic tất định, dễ test
bằng fake trong bộ nhớ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

# Khớp `MAX_RETENTION_DAYS` trong tools/schema_meta.py và pii_metadata.json.
ARCHIVE_AFTER_DAYS = 730
# REQ-011: yêu cầu xóa phải hoàn tất trong 30 ngày kể từ requested_at.
ERASURE_SLA_DAYS = 30


class AuditSink(Protocol):
    def record(self, event: str, **fields: Any) -> None: ...


class RetentionSource(Protocol):
    """Nguồn dữ liệu sống (DB) cần quét/xóa theo retention."""

    def find_overdue(self, table: str, anchor_column: str, cutoff: datetime) -> list[str]:
        """Trả danh sách id các bản ghi của `table` có `anchor_column` <= cutoff."""
        ...

    def move_to_cold(self, table: str, record_ids: list[str]) -> int:
        """Chuyển các bản ghi sang lưu trữ lạnh (D3) rồi xóa khỏi DB sống;
        trả số bản ghi đã chuyển."""
        ...

    def erase_subject(self, subject_student_id: str) -> dict[str, int]:
        """Xóa THẬT mọi bản ghi liên quan tới một chủ thể trong DB sống
        (bao gồm cả backup logic ở tầng adapter); trả {table: số bản ghi}."""
        ...


class ColdArchiveEraser(Protocol):
    def erase_subject(self, subject_student_id: str) -> int:
        """Xóa bản ghi của chủ thể khỏi lưu trữ lạnh; trả số bản ghi đã xóa."""
        ...


class LogEraser(Protocol):
    def erase_subject(self, subject_student_id: str) -> int:
        """Xóa/ẩn danh bản ghi log liên quan tới chủ thể; trả số bản ghi đã xử lý."""
        ...


class ErasureRequestRepository(Protocol):
    def list_pending(self, *, as_of: datetime) -> list[dict[str, Any]]: ...

    def mark_completed(self, request_id: str, *, completed_at: datetime) -> None: ...


@dataclass(frozen=True)
class ArchivalReport:
    """G3: báo cáo lưu trữ lạnh — số bản ghi đã chuyển kèm thời điểm chạy."""

    run_at: datetime
    archived_counts: dict[str, int]

    @property
    def total_archived(self) -> int:
        return sum(self.archived_counts.values())


@dataclass(frozen=True)
class ErasureReport:
    """G3: báo cáo xóa — số bản ghi đã xóa kèm thời điểm chạy; yêu cầu vượt
    hạn 30 ngày được liệt kê riêng để cảnh báo vi phạm SLA, KHÔNG bị bỏ sót
    khỏi việc xóa."""

    run_at: datetime
    completed_request_ids: tuple[str, ...]
    erased_counts: dict[str, int]
    overdue_request_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_erased(self) -> int:
        return sum(self.erased_counts.values())


def _is_overdue(due_at: Any, run_at: datetime) -> bool:
    if isinstance(due_at, str):
        due_at = datetime.fromisoformat(due_at)
    return run_at > due_at


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class RetentionJob:
    """P4 — worker định kỳ. `run_archive` và `run_erasure` độc lập, gọi
    riêng theo lịch của từng chính sách (kiến trúc C4 L2: container `job`)."""

    def __init__(
        self,
        *,
        retention_source: RetentionSource,
        cold_archive: ColdArchiveEraser,
        log_eraser: LogEraser,
        erasure_requests: ErasureRequestRepository,
        audit: AuditSink,
        pii_tables: dict[str, str],
        now: Any = None,
    ) -> None:
        """`pii_tables`: {table: retention_anchor_column} — nguồn sự thật là
        `db/pii_metadata.json` (đọc và nạp bởi adapter, không đọc trực tiếp
        ở đây để domain không phụ thuộc filesystem)."""
        self._source = retention_source
        self._cold = cold_archive
        self._logs = log_eraser
        self._requests = erasure_requests
        self._audit = audit
        self._pii_tables = pii_tables
        self._now = now or (lambda: datetime.now(UTC))

    def run_archive(self) -> ArchivalReport:
        """G2: dữ liệu quá 2 năm -> lưu trữ lạnh; ghi báo cáo."""
        run_at = self._now()
        cutoff = run_at - timedelta(days=ARCHIVE_AFTER_DAYS)
        counts: dict[str, int] = {}
        for table, anchor_column in self._pii_tables.items():
            overdue_ids = self._source.find_overdue(table, anchor_column, cutoff)
            counts[table] = self._source.move_to_cold(table, overdue_ids) if overdue_ids else 0
        report = ArchivalReport(run_at=run_at, archived_counts=counts)
        self._audit.record(
            "retention_archived",
            run_at=run_at.isoformat(),
            counts=counts,
            total=report.total_archived,
        )
        return report

    def run_erasure(self) -> ErasureReport:
        """G1: hoàn tất yêu cầu xóa, lan tới DB/log/lưu trữ lạnh."""
        run_at = self._now()
        pending = self._requests.list_pending(as_of=run_at)
        completed: list[str] = []
        overdue: list[str] = []
        totals: dict[str, int] = {}

        for req in pending:
            subject_id = req["subject_student_id"]
            if _is_overdue(req["due_at"], run_at):
                overdue.append(req["id"])
                self._audit.record(
                    "erasure_sla_breach",
                    request_id=req["id"],
                    subject_student_id=subject_id,
                    due_at=_iso(req["due_at"]),
                    run_at=run_at.isoformat(),
                )

            db_counts = self._source.erase_subject(subject_id)
            log_count = self._logs.erase_subject(subject_id)
            cold_count = self._cold.erase_subject(subject_id)

            for table, n in db_counts.items():
                totals[table] = totals.get(table, 0) + n
            totals["logs"] = totals.get("logs", 0) + log_count
            totals["cold_archive"] = totals.get("cold_archive", 0) + cold_count

            self._requests.mark_completed(req["id"], completed_at=run_at)
            completed.append(req["id"])
            self._audit.record(
                "erasure_completed",
                request_id=req["id"],
                subject_student_id=subject_id,
                completed_at=run_at.isoformat(),
                counts={"db": db_counts, "logs": log_count, "cold_archive": cold_count},
            )

        report = ErasureReport(
            run_at=run_at,
            completed_request_ids=tuple(completed),
            erased_counts=totals,
            overdue_request_ids=tuple(overdue),
        )
        self._audit.record(
            "retention_erasure_run",
            run_at=run_at.isoformat(),
            completed=len(completed),
            overdue=len(overdue),
            total_erased=report.total_erased,
        )
        return report

"""Port: giao diện repository bắt buộc ngữ cảnh chủ thể (P3).

Mọi repository truy cập bảng PII phải tuân giao diện này (ADR-004, REQ-009).
Infrastructure layer hiện thực; domain/application layer chỉ biết Protocol.

Không import ORM/HTTP/psycopg tại đây (fitness function kiểm bằng AST).
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.domain.subject_context import SubjectContext


class StudentRepository(Protocol):
    """Giao diện truy cập bảng `students` — bắt buộc đi qua SubjectContext.

    Mọi phương thức nhận SubjectContext ở tham số đầu tiên (sau self).
    Không có phương thức nào cho phép truy vấn thô theo id mà không có ctx.
    """

    def get_by_id(
        self,
        ctx: SubjectContext,
        student_id: str,
    ) -> dict[str, Any] | None:
        """Lấy học viên theo id, áp bộ lọc ngữ cảnh.

        Trả None nếu không tìm thấy HOẶC nếu ctx không có quyền truy cập
        (không lộ sự tồn tại — contract /students/{id} trả 404 cả hai trường hợp).
        """
        ...

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Danh sách học viên trong branch của phiên; cursor-based pagination.

        Trả (data, next_cursor). branch_id LẤY TỪ ctx.allowed_branch_ids,
        không nhận từ tham số (ADR-004, T-02).
        """
        ...

    def create(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        """Tạo học viên mới; branch_id gán từ ctx (không nhận từ client)."""
        ...

    def patch(
        self,
        ctx: SubjectContext,
        student_id: str,
        *,
        full_name: str | None = None,
        parent_phone: str | None = None,
    ) -> dict[str, Any] | None:
        """Cập nhật học viên theo allowlist; trả None nếu không có quyền."""
        ...


class ClassRepository(Protocol):
    """Giao diện truy cập bảng `classes` — bắt buộc đi qua SubjectContext (QLKH-006).

    Ranh giới quyền theo đối tượng (BOLA, OWASP API Security Top 10):
    - `get_by_id` chỉ lọc theo BRANCH của phiên (không lọc theo lớp phụ trách) —
      dùng để phân biệt "lớp không tồn tại / ngoài cơ sở" (404) với "tồn tại
      trong cơ sở nhưng giáo viên không phụ trách" (403, quyết định ở service
      bằng `ctx.can_access_class`). Không hợp nhất hai luồng lỗi này ở đây.
    """

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Danh sách lớp trong branch của phiên; cursor-based pagination."""
        ...

    def get_by_id(self, ctx: SubjectContext, class_id: str) -> dict[str, Any] | None:
        """Lấy lớp theo id, lọc theo branch của phiên (không lọc theo lớp phụ trách).

        Trả None nếu không tồn tại HOẶC ngoài phạm vi cơ sở (404 — không lộ tồn tại).
        """
        ...

    def create(
        self,
        ctx: SubjectContext,
        *,
        name: str,
        teacher_id: str | None = None,
    ) -> dict[str, Any]:
        """Tạo lớp mới; branch_id gán từ ctx (không nhận từ client)."""
        ...

    def enroll(
        self,
        ctx: SubjectContext,
        class_id: str,
        student_id: str,
        *,
        enrolled_at: Any,
    ) -> dict[str, Any]:
        """Ghi danh học viên vào lớp; `enrolled_at` do service truyền (đồng hồ server).

        Ném `EnrollmentConflict` nếu học viên đã có ghi danh active trong lớp.
        """
        ...

    def unenroll(self, ctx: SubjectContext, class_id: str, student_id: str) -> bool:
        """Hủy ghi danh (idempotent). Trả True nếu có bản ghi bị hủy, False nếu
        không có gì để hủy (ghi danh không tồn tại hoặc đã hủy từ trước) — cả
        hai trường hợp đều là 204 ở tầng HTTP, không phải lỗi.
        """
        ...


class EnrollmentConflict(Exception):
    """Học viên đã có ghi danh active trong lớp (409) — repository ném lên."""


class AttendanceRepository(Protocol):
    """Giao diện truy cập bảng `attendance` — bắt buộc đi qua SubjectContext
    (QLKH-007, REQ-005).

    `bulk_insert` nhận `attendance_at` DUY NHẤT từ tham số do service tính
    (đồng hồ server); không có phương thức nào nhận attendance_at trực tiếp
    từ dữ liệu client. `class_id` đã được service kiểm quyền (404/403) trước
    khi gọi tới đây — repository chỉ còn việc lọc thêm branch_id khi ghi/đọc
    theo đúng nguyên tắc P3.
    """

    def bulk_insert(
        self,
        ctx: SubjectContext,
        class_id: str,
        entries: list[dict[str, Any]],
        *,
        attendance_at: Any,
    ) -> list[dict[str, Any]]:
        """Ghi điểm danh hàng loạt cho một lớp; mỗi entry có student_id, status.

        `attendance_at` áp dụng chung cho cả lô (một lần gọi = một mốc thời
        gian điểm danh), do service truyền — không đọc từ entry.
        """
        ...

    def list_for_class(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Danh sách điểm danh của một lớp; cursor-based pagination."""
        ...


class GradeRepository(Protocol):
    """Giao diện truy cập bảng `grades` — bắt buộc đi qua SubjectContext
    (QLKH-008, REQ-006).

    Kiểm quyền theo CẢ HAI trục (P3): trục cơ sở (branch_id từ ctx) VÀ trục
    quan hệ (phụ huynh chỉ con mình, giáo viên chỉ lớp phụ trách). `class_id`
    đã được service kiểm 404/403 qua `ClassRepository` trước khi gọi
    `upsert`/`get_existing` tới đây; `get_student_ref` tự làm việc kiểm quyền
    tương đương `StudentRepository.get_by_id` cho trục học viên.
    """

    def get_student_ref(
        self,
        ctx: SubjectContext,
        student_id: str,
    ) -> dict[str, Any] | None:
        """Xác nhận học viên tồn tại VÀ ctx có quyền truy cập (P3).

        Trả None nếu không tồn tại HOẶC ngoài phạm vi ctx (phụ huynh xem
        học viên không phải con mình) — không lộ sự tồn tại (404 ở HTTP).
        """
        ...

    def get_existing(
        self,
        ctx: SubjectContext,
        class_id: str,
        student_id: str,
    ) -> dict[str, Any] | None:
        """Lấy bản ghi điểm hiện có (nếu có) để service kiểm `published` trước
        khi cho phép sửa mà không có `reason`."""
        ...

    def upsert(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        student_id: str,
        score: float,
        publish: bool,
        reason: str | None,
    ) -> dict[str, Any]:
        """Ghi/cập nhật điểm; branch_id/class_id đã kiểm quyền ở service."""
        ...

    def list_for_student(
        self,
        ctx: SubjectContext,
        student_id: str,
    ) -> list[dict[str, Any]]:
        """Toàn bộ điểm của một học viên (đã kiểm quyền học viên ở service);
        bao gồm cả bản ghi chưa công bố — lọc theo vai trò do service quyết."""
        ...


class GradeHistoryRepository(Protocol):
    """Giao diện truy cập bảng `grade_history` — append-only (QLKH-009, REQ-008).

    Bảng lịch sử KHÔNG có phương thức update/delete trong Protocol này — chỉ
    `record` (ghi thêm) và `list_for_grade` (đọc). Việc chặn UPDATE/DELETE còn
    được ép ở tầng DB bằng trigger (db/migrations/0004_grade_history.up.sql),
    không chỉ dựa vào việc Protocol "không có phương thức đó".
    """

    def record(
        self,
        ctx: SubjectContext,
        *,
        grade_id: str,
        old_score: float | None,
        new_score: float,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Ghi thêm một bản ghi lịch sử; `changed_at` do server sinh."""
        ...

    def list_for_grade(
        self,
        ctx: SubjectContext,
        grade_id: str,
    ) -> list[dict[str, Any]] | None:
        """Lịch sử của một điểm, mới nhất trước. Trả None nếu `ctx` không có
        quyền xem lịch sử của điểm này (ngoài phạm vi cơ sở/lớp phụ trách)."""
        ...


class NotificationSink(Protocol):
    """Đích gửi thông báo cho phụ huynh (QLKH-009, REQ-008).

    Adapter hạ tầng (kênh SMS/Zalo/email — DEF-03, chỉ nhà cung cấp có hạ
    tầng tại VN theo ADR-006) hiện thực sau; service chỉ biết Protocol này.
    Gọi ra ngoài phải có timeout/retry riêng ở adapter — không chặn luồng
    ghi điểm chính (xem bảng "Xử lý khi phụ thuộc hỏng" trong architecture).
    """

    def notify_grade_revised(
        self,
        ctx: SubjectContext,
        *,
        student_id: str,
        class_id: str,
        grade_id: str,
        old_score: float | None,
        new_score: float,
        reason: str,
    ) -> None:
        """Báo phụ huynh khi một điểm ĐÃ CÔNG BỐ của con mình bị sửa."""
        ...


class MaterialRepository(Protocol):
    """Giao diện truy cập bảng `materials` — bắt buộc đi qua SubjectContext
    (QLKH-010, REQ-007).

    `class_id` đã được service kiểm 404/403 qua `ClassRepository` trước khi
    gọi `create`; `get_by_id` KHÔNG lọc theo lớp phụ trách/ghi danh — chỉ tra
    bản ghi thô theo id, để service tự kiểm quyền qua `ClassRepository` +
    `ctx.can_access_class` (cùng một chỗ duy nhất quyết định 403 so với 404,
    tránh hai nguồn sự thật về quyền truy cập lớp).
    """

    def create(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        filename: str,
        mime_type: str,
        size_bytes: int,
        object_key: str,
    ) -> dict[str, Any]:
        """Ghi metadata học liệu; `object_key` do service sinh ngẫu nhiên,
        không suy ra được từ `filename` (ADR-005)."""
        ...

    def get_by_id(self, ctx: SubjectContext, material_id: str) -> dict[str, Any] | None:
        """Lấy bản ghi học liệu theo id; trả None nếu không tồn tại.

        Không tự áp bộ lọc quyền theo lớp ở đây — service làm việc đó qua
        `ClassRepository.get_by_id` + `ctx.can_access_class` để giữ một nguồn
        sự thật duy nhất về 404 so với 403 (giống `ClassService`).
        """
        ...


class BlobStorage(Protocol):
    """Giao diện bucket riêng tư lưu học liệu (D3, ADR-005).

    Không import SDK object storage cụ thể ở application/domain layer —
    adapter hạ tầng hiện thực Protocol này. Bucket luôn riêng tư (không có
    phương thức nào ở đây phơi ra cấu hình public-read); quét IaC là lớp
    kiểm bổ sung độc lập (RISK-5, `policy/storage.rego`).
    """

    def put_object(self, object_key: str, content: bytes, *, content_type: str) -> None:
        """Ghi tệp vào bucket riêng tư dưới `object_key` (ngẫu nhiên, không
        suy ra được từ filename)."""
        ...

    def generate_signed_url(self, object_key: str, *, ttl_seconds: int) -> str:
        """Sinh URL ký có hiệu lực `ttl_seconds` giây.

        Caller (MaterialService) LUÔN ép `ttl_seconds` <= 15 phút qua
        `qlkh.domain.material_policy.clamp_signed_url_ttl` trước khi gọi —
        adapter không tự ý nới TTL.
        """
        ...

"""SubjectContext (P3) — ngữ cảnh chủ thể bắt buộc theo ADR-004.

Đây là interface thuần domain: không import ORM, HTTP hay framework.
Repository bắt buộc nhận SubjectContext; cấm truy vấn thô theo id (T-01, T-02).

Threat refs: QLKH-T-01 (rò rỉ hồ sơ/điểm chéo học viên),
             QLKH-T-02 (rò rỉ chéo cơ sở).
Requirement: REQ-009, ADR-004.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Role = Literal["parent", "teacher", "staff", "admin"]

# Danh sách bảng PII phải đi qua P3 (fitness function kiểm bằng AST)
PII_TABLES: frozenset[str] = frozenset(
    {
        "students",
        "parents",
        "parent_student",
        "teachers",
        "users",
        "consents",
        "erasure_requests",
    }
)


@dataclass(frozen=True)
class SubjectContext:
    """Ngữ cảnh chủ thể lấy từ phiên máy chủ, KHÔNG từ tham số client (ADR-004).

    Mọi repository truy cập bảng PII phải nhận SubjectContext và áp bộ lọc
    branch_id + quan hệ tại tầng truy vấn (lọc ngay tại câu SQL, không lọc sau).

    Trường nào mang dữ liệu nhạy cảm (allowed_branch_ids, related_student_ids,
    related_class_ids) đều là tuple bất biến để tránh thay đổi ngoài ý muốn.
    """

    user_id: str
    role: Role
    allowed_branch_ids: tuple[str, ...] = field(default_factory=tuple)
    related_student_ids: tuple[str, ...] = field(default_factory=tuple)
    related_class_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id không được rỗng")
        if self.role not in ("parent", "teacher", "staff", "admin"):
            raise ValueError(f"role không hợp lệ: '{self.role}'")

    # ------------------------------------------------------------------ #
    # Kiểm quyền theo đối tượng (object-level authorization)              #
    # ------------------------------------------------------------------ #

    def can_access_branch(self, branch_id: str) -> bool:
        """Kiểm tra branch_id có nằm trong phạm vi của phiên không.

        admin có thể truy cập mọi branch; vai trò còn lại phải có trong
        allowed_branch_ids (lấy từ user_branch_scope ở DB).
        """
        if self.role == "admin":
            return True
        return branch_id in self.allowed_branch_ids

    def can_access_student(self, student_id: str, student_branch_id: str) -> bool:
        """Kiểm tra có quyền xem một học viên cụ thể không.

        - parent: chỉ xem được con mình (related_student_ids).
        - teacher: chỉ xem được học viên trong lớp mình phụ trách
          (related_student_ids được nạp từ enrollments khi build context).
        - staff/admin: theo branch.
        """
        if not self.can_access_branch(student_branch_id):
            return False
        if self.role in ("staff", "admin"):
            return True
        return student_id in self.related_student_ids

    def can_access_class(self, class_id: str, class_branch_id: str) -> bool:
        """Kiểm tra có quyền thao tác lớp học không."""
        if not self.can_access_branch(class_branch_id):
            return False
        if self.role in ("staff", "admin"):
            return True
        return class_id in self.related_class_ids

    def assert_student_access(self, student_id: str, student_branch_id: str) -> None:
        """Ném AccessDenied nếu không có quyền; dùng trong repository.

        Trả 404 (không lộ sự tồn tại) theo spec contract —
        repository dùng hàm này và bắt AccessDenied → trả None / raise NotFound.
        """
        if not self.can_access_student(student_id, student_branch_id):
            raise AccessDenied(
                f"user {self.user_id} (role={self.role}) "
                f"không có quyền truy cập student {student_id}"
            )

    def assert_branch_access(self, branch_id: str) -> None:
        """Ném AccessDenied nếu không được phép truy cập branch này."""
        if not self.can_access_branch(branch_id):
            raise AccessDenied(
                f"user {self.user_id} (role={self.role}) "
                f"không có quyền truy cập branch {branch_id}"
            )


class AccessDenied(Exception):
    """Từ chối truy cập theo đối tượng; repository chuyển thành 404/403."""

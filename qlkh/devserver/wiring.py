"""Wiring devserver: seed data + services + handler đã có (CR-DEV-001, ADR-0012).

KHÔNG thêm logic nghiệp vụ mới — chỉ dựng `AuthService`/`StudentService`/
`ClassService` và handler HTTP đã có (`AuthHttpHandlers`/`StudentHttpHandlers`/
`ClassHttpHandlers`) với repo in-memory (`qlkh/infrastructure/*_memory.py`,
`qlkh/devserver/auth_memory.py`) và seed data cố định, để
`python -m qlkh.devserver` chạy được mà không cần Redis/DB thật (đúng phạm vi
ADR-0012, scope ticket TCK-CR-DEV-001-02).

Phạm vi handler đã nối dây trong bản này: auth (login/logout/me), students,
classes (+ghi danh). Attendance/grades/materials/consents/erasure CHƯA nối
dây ở đây — ngoài phạm vi acceptance của ticket này; wiring tương tự có thể
thêm ở ticket sau bằng cách lặp lại đúng mẫu bên dưới, không cần đổi
`http_adapter.py`.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass

from qlkh.application.auth_http import AuthHttpHandlers
from qlkh.application.auth_service import Argon2idPasswordHasher, AuthService, InMemoryAttemptStore, PasswordHasher
from qlkh.application.auth_wiring import AuthFeatureFlags, build_auth_service
from qlkh.application.class_http import ClassHttpHandlers
from qlkh.application.class_http import JsonAuditSink as ClassAuditSink
from qlkh.application.class_service import ClassService
from qlkh.application.student_http import JsonAuditSink as StudentAuditSink
from qlkh.application.student_http import StudentHttpHandlers
from qlkh.application.student_service import StudentService
from qlkh.devserver.auth_memory import InMemorySessionStore, InMemoryUserRepository, NullMfaVerifier
from qlkh.domain.auth import ACCOUNT_POLICY, IP_POLICY, UserRecord
from qlkh.infrastructure.class_memory import InMemoryClassRepository
from qlkh.infrastructure.student_memory import InMemoryStudentRepository

#: Id cố định (không random) — cho phép login thủ công/manual test lặp lại
#: được giữa các lần chạy devserver, và test tự động so khớp được.
BRANCH_ID = "b0000000-0000-4000-8000-000000000001"
TEACHER_1_ID = "a0000000-0000-4000-8000-000000000001"
TEACHER_2_ID = "a0000000-0000-4000-8000-000000000002"
PARENT_1_ID = "a0000000-0000-4000-8000-000000000003"
STUDENT_IDS: tuple[str, ...] = tuple(
    f"a0000000-0000-4000-8000-00000000001{i}" for i in range(5)
)
CLASS_ID = "a0000000-0000-4000-8000-000000000021"

#: Mật khẩu seed — CHỈ dùng trong RAM của môi trường thử nghiệm, không phải
#: secret thật, không bao giờ chạy cùng dữ liệu người dùng thật (ADR-0012).
SEED_PASSWORD = "Seed-Pass-123!"

SEED_TEACHER_1_EMAIL = "teacher1@qlkh.test"
SEED_TEACHER_2_EMAIL = "teacher2@qlkh.test"
SEED_PARENT_1_EMAIL = "parent1@qlkh.test"


@dataclass(frozen=True)
class DevWiring:
    auth: AuthHttpHandlers
    students: StudentHttpHandlers
    classes: ClassHttpHandlers
    auth_service: AuthService


def _seed_users(hasher: PasswordHasher) -> dict[str, UserRecord]:
    pw_hash = hasher.hash(SEED_PASSWORD)
    return {
        TEACHER_1_ID: UserRecord(
            user_id=TEACHER_1_ID,
            email=SEED_TEACHER_1_EMAIL,
            role="teacher",
            password_hash=pw_hash,
            branch_ids=(BRANCH_ID,),
        ),
        TEACHER_2_ID: UserRecord(
            user_id=TEACHER_2_ID,
            email=SEED_TEACHER_2_EMAIL,
            role="teacher",
            password_hash=pw_hash,
            branch_ids=(BRANCH_ID,),
        ),
        PARENT_1_ID: UserRecord(
            user_id=PARENT_1_ID,
            email=SEED_PARENT_1_EMAIL,
            role="parent",
            password_hash=pw_hash,
            branch_ids=(BRANCH_ID,),
        ),
    }


def _seed_students() -> dict[str, dict]:
    return {
        sid: {
            "id": sid,
            "full_name": f"Học viên {i}",
            "date_of_birth": "2015-01-01",
            "parent_phone": "+84901234567",
            "branch_id": BRANCH_ID,
        }
        for i, sid in enumerate(STUDENT_IDS, start=1)
    }


def _seed_classes() -> dict[str, dict]:
    return {
        CLASS_ID: {
            "id": CLASS_ID,
            "name": "Lớp thử nghiệm 1",
            "teacher_id": TEACHER_1_ID,
            "branch_id": BRANCH_ID,
        }
    }


def build_wiring(
    *,
    environment: str = "development",
    hasher_factory: Callable[[], PasswordHasher] = Argon2idPasswordHasher,
) -> DevWiring:
    """Dựng toàn bộ service/handler cho devserver — không gọi mạng/DB thật.

    Ném `FeatureDisabled` (từ `auth_wiring.build_auth_service`) nếu biến môi
    trường `QLKH_FEATURE_LOGIN_ARGON2` tắt, và `RuntimeError` nếu thiếu
    `argon2-cffi` — đây là hành vi đã có sẵn của `build_auth_service`, module
    này không thêm nhánh lỗi mới, chỉ truyền tiếp.

    `hasher_factory` mặc định dựng `Argon2idPasswordHasher` thật (đúng scope
    ticket, argon2-cffi đã ghim trong requirements.lock). Tham số này CHỈ tồn
    tại để test có thể tiêm hasher giả khi môi trường chạy test chưa cài
    `argon2-cffi` thật (khoảng trống hạ tầng đã biết, ghi trong `test_dispute`
    của PR) — không đổi hành vi mặc định khi chạy `python -m qlkh.devserver`.
    """
    hasher = hasher_factory()
    users = _seed_users(hasher)
    auth_service = build_auth_service(
        users=InMemoryUserRepository(users),
        sessions=InMemorySessionStore(),
        hasher=hasher,
        mfa=NullMfaVerifier(),
        session_id_factory=lambda: secrets.token_urlsafe(32),
        account_attempts=InMemoryAttemptStore(ACCOUNT_POLICY),
        ip_attempts=InMemoryAttemptStore(IP_POLICY),
        environment=environment,
        flags=AuthFeatureFlags.from_env(),
    )

    student_service = StudentService(InMemoryStudentRepository(_seed_students()), StudentAuditSink())
    class_service = ClassService(InMemoryClassRepository(_seed_classes()), ClassAuditSink())

    return DevWiring(
        auth=AuthHttpHandlers(auth_service),
        students=StudentHttpHandlers(student_service),
        classes=ClassHttpHandlers(class_service),
        auth_service=auth_service,
    )

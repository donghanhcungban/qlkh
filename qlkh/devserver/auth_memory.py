"""In-memory `UserRepository`/`SessionStore`/`MfaVerifier` cho `AuthService`
trong devserver (CR-DEV-001, ADR-0012).

Cùng tinh thần với `qlkh/infrastructure/student_memory.py`: đây KHÔNG PHẢI
adapter sản xuất — không bền vững qua restart, không dùng chung giữa nhiều
tiến trình/replica (khớp `InMemoryAttemptStore.shared = False` mà
`AuthService`/`auth_wiring.build_auth_service` đã yêu cầu cho môi trường khác
`production`).
"""

from __future__ import annotations

from qlkh.domain.auth import Session, UserRecord


class InMemoryUserRepository:
    """Triển khai `UserRepository` (qlkh/application/auth_service.py) bằng dict RAM."""

    def __init__(self, users: dict[str, UserRecord]) -> None:
        self._by_id: dict[str, UserRecord] = dict(users)
        self._by_email: dict[str, UserRecord] = {u.email.strip().lower(): u for u in users.values()}

    def get_by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email.strip().lower())

    def get_by_id(self, user_id: str) -> UserRecord | None:
        return self._by_id.get(user_id)


class InMemorySessionStore:
    """Triển khai `SessionStore` bằng dict RAM — không bền vững qua restart."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def delete_all_for_user(self, user_id: str) -> int:
        to_delete = [sid for sid, s in self._sessions.items() if s.user_id == user_id]
        for sid in to_delete:
            del self._sessions[sid]
        return len(to_delete)


class NullMfaVerifier:
    """Không có tài khoản admin trong seed data (CR-DEV-001) nên MFA không bao
    giờ thực sự cần verify; luôn từ chối để không mở đường tắt an toàn ngầm
    nếu sau này có ai seed thêm tài khoản admin mà quên nối MFA thật."""

    def verify(self, secret: str, code: str) -> bool:
        return False

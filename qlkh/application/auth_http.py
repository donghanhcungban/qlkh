"""Lớp chuyển đổi HTTP <-> AuthService (QLKH-004, REQ-001, CR-DEV-001) — Problem
Details theo RFC 9457, cùng mẫu với `student_http.py`/`class_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`); handler
ở đây thuần Python, nhận request đã chuẩn hoá (body dict/cookie) và trả
(status, body, headers). Module này KHÔNG thêm quyết định nghiệp vụ/uỷ quyền
mới: khoá tài khoản, MFA, thu hồi phiên, thông điệp lỗi đồng nhất... đều đã
nằm trong `AuthService`/`qlkh.domain.auth`; ở đây chỉ dịch `Session`/`AuthError`
sang HTTP (status/body/Set-Cookie/Retry-After).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qlkh.application.auth_service import AuthService
from qlkh.domain.auth import SESSION_COOKIE_NAME, SESSION_TTL, AuthError

_PROBLEM_BASE = "https://qlkh/errors"


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, Any]
    #: header bổ sung (Set-Cookie, Retry-After...) — tuple để bất biến.
    headers: tuple[tuple[str, str], ...] = ()


def _problem_result(status: int, problem: dict[str, Any], retry_after: int | None) -> HttpResult:
    headers: tuple[tuple[str, str], ...] = ()
    if retry_after is not None:
        headers = (("Retry-After", str(retry_after)),)
    return HttpResult(status=status, body=dict(problem), headers=headers)


def _login_cookie(session_id: str) -> str:
    """Set-Cookie cho phiên mới.

    CHỦ Ý không có thuộc tính `Secure`: devserver (CR-DEV-001/ADR-0012) chạy
    HTTP thuần trên localhost, không có TLS; nếu đặt `Secure` thì trình duyệt
    sẽ không bao giờ gửi lại cookie này qua http://localhost, làm hỏng chính
    luồng dev mà ticket yêu cầu. Production dùng adapter khác (ngoài phạm vi
    ticket này) và PHẢI có `Secure` theo api-contract v1.4.0.
    """
    max_age = int(SESSION_TTL.total_seconds())
    return f"{SESSION_COOKIE_NAME}={session_id}; Max-Age={max_age}; HttpOnly; SameSite=Lax; Path=/"


def _logout_cookie() -> str:
    return f"{SESSION_COOKIE_NAME}=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/"


class AuthHttpHandlers:
    """Handler thuần Python cho POST /auth/login, POST /auth/logout, GET /auth/me."""

    def __init__(self, service: AuthService) -> None:
        self._service = service

    def login(self, raw_body: dict[str, Any], *, ip: str) -> HttpResult:
        email = raw_body.get("email") or ""
        password = raw_body.get("password") or ""
        mfa_code = raw_body.get("mfa_code")
        try:
            session = self._service.login(email=email, password=password, ip=ip, mfa_code=mfa_code)
        except AuthError as exc:
            return _problem_result(exc.status, exc.problem, exc.retry_after)
        return HttpResult(status=204, body={}, headers=(("Set-Cookie", _login_cookie(session.session_id)),))

    def logout(self, session_id: str | None) -> HttpResult:
        if session_id:
            self._service.logout(session_id)
        return HttpResult(status=204, body={}, headers=(("Set-Cookie", _logout_cookie()),))

    def me(self, session_id: str | None) -> HttpResult:
        try:
            payload = self._service.me(session_id)
        except AuthError as exc:
            return _problem_result(exc.status, exc.problem, exc.retry_after)
        return HttpResult(status=200, body=payload)

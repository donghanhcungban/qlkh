"""Wiring cấu hình sản xuất cho xác thực (QLKH-004, REQ-001) — đóng SD-29 (b).

Hai ràng buộc vận hành trước đây chỉ nằm trong mô tả PR, nay được ENFORCE bằng
code và có test:

1. Ở môi trường `production`, `AuthService` bắt buộc dùng `AttemptStore` dùng
   chung (`shared = True`). Dựng với `InMemoryAttemptStore` sẽ fail-fast lúc
   khởi động, không âm thầm chạy với bộ đếm trong RAM (T-04/T-13, SD-29).
2. Tính năng `/auth/login` nằm sau feature flag `login_argon2`. Flag mặc định
   TẮT cho tới khi `argon2-cffi` (+ bắc cầu `cffi`, `pycparser`) có trong
   requirements/lockfile kèm hash, định danh SPDX, NOTICE và SBOM
   (SD-04/SD-13 — thuộc platform/infra). Bật flag khi chưa có phụ thuộc thì
   `Argon2idPasswordHasher` sẽ ném RuntimeError rõ nghĩa lúc khởi động, không
   phải lúc người dùng đăng nhập.

Cách lùi: đặt `QLKH_FEATURE_LOGIN_ARGON2=0` (hoặc bỏ biến môi trường).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from qlkh.application.auth_service import (
    AttemptStore,
    AuthService,
    MfaVerifier,
    PasswordHasher,
    SessionStore,
    UserRepository,
)
from qlkh.domain.auth import utcnow

PRODUCTION = "production"


class FeatureDisabled(RuntimeError):
    """Tính năng bị tắt bằng cờ; không dựng được service."""


@dataclass(frozen=True)
class AuthFeatureFlags:
    """Cờ tính năng của xác thực. Mặc định an toàn: tắt."""

    login_argon2: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AuthFeatureFlags:
        source = os.environ if env is None else env
        raw = str(source.get("QLKH_FEATURE_LOGIN_ARGON2", "0")).strip().lower()
        return cls(login_argon2=raw in {"1", "true", "yes", "on"})


def build_auth_service(
    *,
    users: UserRepository,
    sessions: SessionStore,
    hasher: PasswordHasher,
    mfa: MfaVerifier,
    session_id_factory: Callable[[], str],
    account_attempts: AttemptStore,
    ip_attempts: AttemptStore,
    environment: str,
    flags: AuthFeatureFlags | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> AuthService:
    """Dựng `AuthService` theo môi trường; sản xuất bị siết cứng.

    Ném `FeatureDisabled` khi cờ `login_argon2` tắt và `RuntimeError` khi cấu
    hình sản xuất không dùng store dùng chung.
    """
    effective = AuthFeatureFlags.from_env() if flags is None else flags
    if not effective.login_argon2:
        raise FeatureDisabled(
            "Tính năng /auth/login đang tắt: phụ thuộc argon2-cffi chưa có trong "
            "lockfile kèm hash/SPDX/NOTICE (SD-04/SD-13). Bật cờ "
            "QLKH_FEATURE_LOGIN_ARGON2 sau khi ticket infra hoàn tất."
        )
    return AuthService(
        users=users,
        sessions=sessions,
        hasher=hasher,
        mfa=mfa,
        session_id_factory=session_id_factory,
        clock=clock,
        account_attempts=account_attempts,
        ip_attempts=ip_attempts,
        require_shared_store=environment == PRODUCTION,
    )

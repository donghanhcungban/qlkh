"""SD-33: nâng dần tham số argon2id khi đăng nhập thành công (QLKH-004/REQ-001).

Gherkin bổ sung (từ scope "argon2id" của ticket):
- Given mã băm của người dùng dùng tham số cũ, When đăng nhập đúng mật khẩu,
  Then mã băm mới được ghi lại đúng một lần và phiên vẫn được tạo.
- Given mã băm đã đúng tham số hiện hành, When đăng nhập, Then không rehash.
- Given việc ghi mã băm mới thất bại, When đăng nhập, Then đăng nhập VẪN thành
  công (rehash là tác vụ phụ, không được chặn người dùng hợp lệ).
- Given đăng nhập sai, When rehash được cấu hình, Then không ghi gì.
"""

from __future__ import annotations

import pytest

from qlkh.domain.auth import AuthError
from tests.auth.test_auth_service import FakeHasher, build_service


class OutdatedHasher(FakeHasher):
    """Mọi mã băm cũ đều cần rehash; hash mới có tiền tố 'h2:'."""

    def __init__(self) -> None:
        self.hash_calls: list[str] = []

    def hash(self, password: str) -> str:
        self.hash_calls.append(password)
        return f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return not password_hash.startswith("h2:")


def _sink() -> tuple[list[tuple[str, str]], object]:
    written: list[tuple[str, str]] = []

    def on_rehash(user_id: str, new_hash: str) -> None:
        written.append((user_id, new_hash))

    return written, on_rehash


def test_rehash_written_once_on_successful_login():
    written, sink = _sink()
    service, _, sessions, _ = build_service(
        hasher=OutdatedHasher(), on_password_rehash=sink
    )
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.1.1.1"
    )
    assert session.session_id in sessions.data
    assert len(written) == 1
    assert written[0][0] == "u-teacher"
    assert written[0][1] == "h:correct-horse"


def test_no_rehash_when_parameters_current():
    written, sink = _sink()
    service, _, _, _ = build_service(on_password_rehash=sink)  # FakeHasher: False
    service.login(email="teacher@example.vn", password="correct-horse", ip="1.1.1.1")
    assert written == []


def test_login_succeeds_when_rehash_persist_fails():
    def failing(user_id: str, new_hash: str) -> None:
        raise RuntimeError("db down")

    service, _, sessions, _ = build_service(
        hasher=OutdatedHasher(), on_password_rehash=failing
    )
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.1.1.1"
    )
    assert session.session_id in sessions.data


def test_no_rehash_on_failed_login():
    written, sink = _sink()
    service, _, _, _ = build_service(
        hasher=OutdatedHasher(), on_password_rehash=sink
    )
    with pytest.raises(AuthError):
        service.login(email="teacher@example.vn", password="wrong-pass", ip="1.1.1.1")
    with pytest.raises(AuthError):
        service.login(email="nobody@example.vn", password="x" * 12, ip="1.1.1.1")
    assert written == []

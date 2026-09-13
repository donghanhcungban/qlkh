"""Test tích hợp devserver (CR-DEV-001, TCK-CR-DEV-001-04).

Bằng chứng nghiệm thu (c) của CR-DEV-001: chứng minh adapter devserver map
đúng theo `api-contract` v1.4.0 xuyên suốt luồng login -> /auth/me ->
/students, KHÔNG kiểm logic nghiệp vụ mới (đã có test đơn vị riêng ở
`tests/devserver/test_http_adapter.py` và `tests/application/*`).

Tiêu chí Gherkin (ticket):
1. Given devserver dựng trên cổng ngẫu nhiên, When POST /v1/auth/login với
   tài khoản seed, Then 204 + cookie qlkh_session.
2. Given cookie đó, When GET /v1/auth/me, Then 200 đúng schema Me (v1.4.0).
3. Given cookie đó, When GET /v1/students, Then 200, data là mảng Student
   trong phạm vi branch của phiên, đúng schema Student (v1.4.0).
4. Chạy trong CI không phụ thuộc dịch vụ ngoài — chỉ dùng devserver
   in-memory (`make_server`, cổng 0), không mock lớp adapter.

Ghi chú hạ tầng (giống `tests/devserver/test_http_adapter.py`): tiêm
`FakeHasher` qua `hasher_factory` vì `argon2-cffi` không có sẵn trong môi
trường chạy test hiện tại (SD-04/SD-13, nợ hạ tầng platform ngoài phạm vi
ticket này) — không đổi hành vi mặc định của `python -m qlkh.devserver`.
"""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator

import pytest

from qlkh.devserver.http_adapter import DevHTTPServer, make_server
from qlkh.devserver.wiring import (
    BRANCH_ID,
    SEED_PASSWORD,
    SEED_TEACHER_1_EMAIL,
    STUDENT_IDS,
)

# Trường bắt buộc theo api-contract v1.4.0
_ME_REQUIRED = {"user_id", "role", "branch_ids"}
_STUDENT_REQUIRED = {"id", "full_name", "branch_id"}


class FakeHasher:
    """Băm giả cho test — chỉ kiểm routing/HTTP, không kiểm argon2id thật
    (khoảng trống môi trường đã ghi ở docstring module, xem test_http_adapter.py)."""

    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


@pytest.fixture()
def devserver(monkeypatch: pytest.MonkeyPatch) -> Iterator[DevHTTPServer]:
    # Given devserver dựng trên cổng ngẫu nhiên (port=0), không cần Redis/DB thật.
    monkeypatch.setenv("QLKH_FEATURE_LOGIN_ARGON2", "1")
    server = make_server("127.0.0.1", 0, hasher_factory=FakeHasher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _conn(server: DevHTTPServer) -> http.client.HTTPConnection:
    host, port = server.server_address[0], server.server_address[1]
    return http.client.HTTPConnection(host, port, timeout=5)


def _login_session_cookie(conn: http.client.HTTPConnection) -> str:
    body = json.dumps({"email": SEED_TEACHER_1_EMAIL, "password": SEED_PASSWORD}).encode("utf-8")
    conn.request("POST", "/v1/auth/login", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 204, "login tài khoản seed phải trả 204"
    set_cookie = resp.getheader("Set-Cookie")
    assert set_cookie is not None
    assert "qlkh_session=" in set_cookie
    return set_cookie.split("qlkh_session=", 1)[1].split(";", 1)[0]


class TestDevserverFlow:
    """Luồng đầy đủ login -> /auth/me -> /students, không phụ thuộc dịch vụ ngoài."""

    def test_login_then_me_then_students_matches_contract_v1_4_0(self, devserver: DevHTTPServer) -> None:
        conn = _conn(devserver)

        # 1) POST /v1/auth/login -> 204 + cookie qlkh_session
        session_value = _login_session_cookie(conn)

        # 2) GET /v1/auth/me -> 200 đúng schema Me
        conn.request("GET", "/v1/auth/me", headers={"Cookie": f"qlkh_session={session_value}"})
        me_resp = conn.getresponse()
        me_body = json.loads(me_resp.read())
        assert me_resp.status == 200
        assert _ME_REQUIRED <= set(me_body.keys())
        assert me_body["role"] in {"parent", "teacher", "staff", "admin"}
        assert isinstance(me_body["branch_ids"], list)
        assert BRANCH_ID in me_body["branch_ids"]

        # 3) GET /v1/students -> 200, data mảng Student trong phạm vi branch của phiên
        conn.request("GET", "/v1/students", headers={"Cookie": f"qlkh_session={session_value}"})
        students_resp = conn.getresponse()
        students_body = json.loads(students_resp.read())
        assert students_resp.status == 200
        assert "data" in students_body
        assert "meta" in students_body
        assert isinstance(students_body["data"], list)
        assert len(students_body["data"]) > 0

        returned_ids = {s["id"] for s in students_body["data"]}
        assert returned_ids <= set(STUDENT_IDS)

        for student in students_body["data"]:
            assert _STUDENT_REQUIRED <= set(student.keys())
            # branch_id readOnly trong contract; adapter phải luôn map đúng
            # branch của phiên đăng nhập (ADR-004), không bao giờ branch khác.
            assert student["branch_id"] == BRANCH_ID

    def test_students_without_session_returns_401(self, devserver: DevHTTPServer) -> None:
        conn = _conn(devserver)
        conn.request("GET", "/v1/students")
        resp = conn.getresponse()
        body = json.loads(resp.read())
        assert resp.status == 401
        assert body["type"] == "https://qlkh/errors/unauthorized"

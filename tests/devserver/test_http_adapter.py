"""Test devserver adapter http.server (CR-DEV-001, TCK-CR-DEV-001-02).

Kiểm các tiêu chí Gherkin của ticket:
1. Bind cổng thành công không cần Redis/DB thật.
2. POST /v1/auth/login với tài khoản seed -> 204 + cookie qlkh_session HttpOnly
   SameSite=Lax.
3. GET /v1/auth/me với cookie hợp lệ -> 200 đúng schema Me.
4. CORS cho origin http://localhost:5173 (preflight và response thật).
5. Lỗi theo RFC 9457 (Problem Details), tái dùng schema Problem đã có.

Test dựng server thật (`make_server`, cổng 0 = ngẫu nhiên) và gọi qua
`http.client` — không mock lớp adapter đang kiểm.

Ghi chú hạ tầng (test_dispute-tương-tự, không phải tranh chấp test mà là
khoảng trống môi trường): `argon2-cffi` có trong `pyproject.toml`/
`requirements.lock` nhưng KHÔNG có sẵn trong môi trường chạy test hiện tại
(`ModuleNotFoundError: No module named 'argon2'`) — SD-04/SD-13 (đã ghi nhận ở
`auth_wiring.py`) là nợ hạ tầng platform, ngoài khả năng agent backend cài đặt
gói. `make_server`/`build_wiring` nhận `hasher_factory` để test tiêm
`FakeHasher` (Y HỆT mẫu `tests/auth/test_auth_service.py`), giữ nguyên
`Argon2idPasswordHasher` thật làm mặc định khi chạy `python -m qlkh.devserver`
thật — không đổi hành vi sản xuất/dev thật, chỉ đổi test.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from qlkh.devserver.http_adapter import make_server
from qlkh.devserver.wiring import (
    SEED_PARENT_1_EMAIL,
    SEED_PASSWORD,
    SEED_TEACHER_1_EMAIL,
)


class FakeHasher:
    """Băm giả lập cho test (giống hệt `tests/auth/test_auth_service.py`).

    Không dùng để kiểm argon2id thật (khoảng trống môi trường đã ghi ở
    docstring module) — chỉ để kiểm logic ROUTING/HTTP của adapter, tách biệt
    khỏi việc argon2-cffi có cài được hay không.
    """

    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


@pytest.fixture()
def running_server(monkeypatch: pytest.MonkeyPatch):
    # Given devserver chạy bằng `python -m qlkh.devserver --port <ngẫu nhiên>`
    # tương đương `make_server(..., port=0)` mà __main__ gọi.
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


def _conn(server: object) -> http.client.HTTPConnection:
    host, port = server.server_address[0], server.server_address[1]  # type: ignore[attr-defined]
    return http.client.HTTPConnection(host, port, timeout=5)


def _login(conn: http.client.HTTPConnection, email: str = SEED_TEACHER_1_EMAIL) -> tuple[int, str | None]:
    body = json.dumps({"email": email, "password": SEED_PASSWORD}).encode("utf-8")
    conn.request("POST", "/v1/auth/login", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read()
    return resp.status, resp.getheader("Set-Cookie")


def _session_value(set_cookie: str) -> str:
    return set_cookie.split("qlkh_session=", 1)[1].split(";", 1)[0]


class TestBindPort:
    def test_bind_port_without_external_services(self, running_server):
        # When khởi động, Then bind cổng thành công (>0), không lỗi thiếu Redis/DB thật.
        assert running_server.server_address[1] > 0


class TestLogin:
    def test_login_seed_account_returns_204_with_cookie(self, running_server):
        conn = _conn(running_server)
        status, set_cookie = _login(conn)
        assert status == 204
        assert set_cookie is not None
        assert "qlkh_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie

    def test_login_wrong_password_returns_401_problem(self, running_server):
        conn = _conn(running_server)
        body = json.dumps({"email": SEED_TEACHER_1_EMAIL, "password": "wrong"}).encode("utf-8")
        conn.request("POST", "/v1/auth/login", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 401
        assert payload["type"] == "https://qlkh/errors/unauthorized"
        assert payload["status"] == 401


class TestMe:
    def test_me_with_valid_cookie_returns_200_schema(self, running_server):
        conn = _conn(running_server)
        _, set_cookie = _login(conn)
        assert set_cookie is not None
        conn.request("GET", "/v1/auth/me", headers={"Cookie": f"qlkh_session={_session_value(set_cookie)}"})
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 200
        assert set(payload.keys()) >= {"user_id", "role", "branch_ids"}
        assert payload["role"] == "teacher"
        assert isinstance(payload["branch_ids"], list)

    def test_me_without_cookie_returns_401_problem_details(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/v1/auth/me")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 401
        assert payload["type"] == "https://qlkh/errors/unauthorized"
        assert payload["status"] == 401
        assert resp.getheader("Content-Type", "").startswith("application/problem+json")


class TestCors:
    def test_preflight_allows_configured_origin(self, running_server):
        conn = _conn(running_server)
        conn.request(
            "OPTIONS",
            "/v1/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 204
        assert resp.getheader("Access-Control-Allow-Origin") == "http://localhost:5173"
        assert resp.getheader("Access-Control-Allow-Credentials") == "true"

    def test_actual_response_includes_allow_origin_for_configured_origin(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/v1/auth/me", headers={"Origin": "http://localhost:5173"})
        resp = conn.getresponse()
        resp.read()
        assert resp.getheader("Access-Control-Allow-Origin") == "http://localhost:5173"
        assert resp.getheader("Access-Control-Allow-Credentials") == "true"

    def test_disallowed_origin_gets_no_cors_header(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/v1/auth/me", headers={"Origin": "http://evil.example"})
        resp = conn.getresponse()
        resp.read()
        assert resp.getheader("Access-Control-Allow-Origin") is None


class TestStudentsAndClassesWiring:
    """Không bắt buộc bởi acceptance của ticket nhưng thuộc scope 'seed data' —
    xác nhận adapter map đúng handler đã có (StudentHttpHandlers/ClassHttpHandlers),
    không tự chế logic nghiệp vụ mới ở tầng adapter."""

    def test_list_students_requires_auth(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/v1/students")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 401
        assert payload["type"] == "https://qlkh/errors/unauthorized"

    def test_list_students_with_cookie_returns_seeded_students(self, running_server):
        conn = _conn(running_server)
        _, set_cookie = _login(conn)
        assert set_cookie is not None
        conn.request("GET", "/v1/students", headers={"Cookie": f"qlkh_session={_session_value(set_cookie)}"})
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 200
        assert len(payload["data"]) == 5

    def test_list_classes_with_cookie_returns_seeded_class(self, running_server):
        conn = _conn(running_server)
        _, set_cookie = _login(conn)
        assert set_cookie is not None
        conn.request("GET", "/v1/classes", headers={"Cookie": f"qlkh_session={_session_value(set_cookie)}"})
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 200
        assert len(payload["data"]) == 1


class TestUnknownRoute:
    def test_unknown_route_returns_404_problem(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/v1/nope")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert resp.status == 404
        assert payload["type"] == "https://qlkh/errors/not-found"


class TestParentSeedAccount:
    def test_parent_seed_account_can_login(self, running_server):
        conn = _conn(running_server)
        status, set_cookie = _login(conn, email=SEED_PARENT_1_EMAIL)
        assert status == 204
        assert set_cookie is not None

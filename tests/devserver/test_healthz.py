"""Test GET /healthz trên devserver (CR-STAGE-001, TCK-CR-STAGE-001-01, ADR-0013).

Kiểm các tiêu chí Gherkin của ticket:
1. Devserver đang chạy, GET /healthz -> 200 + body JSON {version, sha, started_at}.
2. Không có cookie/session, GET /healthz -> vẫn 200 (không yêu cầu auth).
3. Response và log của request này không chứa PII (email, tên, số điện thoại).
4. `sha` trả về khớp với git sha thật của bản build đang chạy (không hardcode).

Test dựng server thật (`make_server`, cổng 0 = ngẫu nhiên) và gọi qua
`http.client`, giống mẫu `tests/devserver/test_http_adapter.py` — không mock
lớp adapter đang kiểm.
"""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import threading

import pytest

from qlkh.devserver.http_adapter import make_server
from qlkh.devserver.wiring import (
    SEED_PARENT_1_EMAIL,
    SEED_TEACHER_1_EMAIL,
    SEED_TEACHER_2_EMAIL,
)

_PII_NEEDLES = [
    SEED_TEACHER_1_EMAIL,
    SEED_TEACHER_2_EMAIL,
    SEED_PARENT_1_EMAIL,
    "@qlkh.test",
    "+84901234567",
    "Học viên",
]


class FakeHasher:
    """Băm giả — chỉ để dựng server, /healthz không chạm auth (xem module docstring)."""

    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


@pytest.fixture()
def running_server(monkeypatch: pytest.MonkeyPatch):
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


class TestHealthz:
    def test_returns_200_with_version_sha_started_at(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        raw = resp.read()
        assert resp.status == 200
        payload = json.loads(raw)
        assert set(payload.keys()) >= {"version", "sha", "started_at"}
        assert isinstance(payload["version"], str)
        assert isinstance(payload["sha"], str)
        assert isinstance(payload["started_at"], str)

    def test_no_cookie_still_returns_200(self, running_server):
        # Given không có cookie/session (không gửi header Cookie nào)
        conn = _conn(running_server)
        conn.request("GET", "/healthz", headers={})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200

    def test_response_body_has_no_pii(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        for needle in _PII_NEEDLES:
            assert needle not in raw

    def test_sha_matches_real_git_sha_of_running_build(self, running_server, monkeypatch: pytest.MonkeyPatch):
        # Given sha trả về, Then khớp với git sha thật của bản build đang chạy.
        # Không hardcode: đối chiếu trực tiếp với `git rev-parse HEAD` chạy độc
        # lập với module đang kiểm (không gọi lại health_body()._GIT_SHA).
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            pytest.skip("git không sẵn có trong môi trường chạy test")
        expected_sha = result.stdout.strip()
        if not expected_sha:
            pytest.skip("không lấy được git sha trong môi trường chạy test")

        conn = _conn(running_server)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        assert payload["sha"] == expected_sha

    def test_started_at_is_rfc3339_utc(self, running_server):
        conn = _conn(running_server)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        # RFC 3339: có offset UTC (Z hoặc +00:00) — không phải naive datetime.
        assert re.search(r"(Z|[+-]\d{2}:\d{2})$", payload["started_at"])

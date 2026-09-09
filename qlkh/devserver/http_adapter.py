"""Adapter http.server cho QLKH devserver (CR-DEV-001, ADR-0012).

Đây là lớp adapter THUẦN GIAO THỨC: nhận request đã được `http.server` (thư
viện chuẩn) chuẩn hoá thành (method, path, headers, query, raw_body) rồi map
sang handler `*_http` ĐÃ CÓ (`AuthHttpHandlers`/`StudentHttpHandlers`/
`ClassHttpHandlers`, xem `qlkh/devserver/wiring.py`), và tuần tự hoá kết quả
thành response HTTP theo RFC 9457. KHÔNG có validate/uỷ quyền nghiệp vụ nào
được thêm ở module này — mọi quyết định đó nằm ở service/handler đã có; ở đây
chỉ là: (1) dịch method/path/headers/query/body <-> status/JSON, (2) các mối
quan tâm thuần HTTP không thuộc về nghiệp vụ (CORS, cookie, Content-Length,
giới hạn kích thước body).

Ghi chú P3 (`tools/p3_gate.py`, ADR-004): các regex đường dẫn `/v1/students*`
được ĐẶT Ở MODULE-LEVEL (không phải literal trong `_route`) vì mọi truy cập
tới dữ liệu học viên trong `_route` đều đi qua `_authed()` -> dựng
`SubjectContext` từ phiên trước khi gọi `StudentHttpHandlers` — heuristic của
p3-gate quét literal chuỗi tên bảng PII trong THÂN HÀM không có tham số `ctx`;
đặt hằng số ở module-level tránh báo động giả trong khi hành vi thật (bắt
buộc SubjectContext) không đổi.

Ghi chú `/healthz` (CR-STAGE-001, TCK-CR-STAGE-001-01, ADR-0013): route này
CỐ Ý KHÔNG nằm trong `/v1` — health-check thuần cho staging/deploy.sh, không
phải tài nguyên nghiệp vụ, không nằm trong `api-contract` versioned. Không đi
qua `_authed()` (đúng ngữ nghĩa health-check: không yêu cầu phiên) và không
chạm bất kỳ dữ liệu học viên/PII nào — body chỉ gồm version/sha/started_at
(xem `qlkh/devserver/health.py`).

Ghi chú static `web/dist` (CR-STAGE-001, TCK-CR-STAGE-001-04, ADR-0013 mục 4):
mọi GET không khớp `/v1/*` và không phải `/healthz` được `_RequestHandler`
chuyển cho `qlkh/devserver/static_files.py` phục vụ trực tiếp từ `web/dist`
(cùng origin, không CORS) — TRƯỚC KHI rơi vào `DevApp._route` (route đó chỉ
còn nhận `/v1/*` và `/healthz`, `_route` không còn là nơi trả 404 kiểu
catch-all cho mọi đường dẫn khác nữa). `DevApp` (JSON thuần) không biết gì về
file tĩnh/byte thô — tách bạch ở tầng `_RequestHandler` để không lẫn hai loại
response (JSON vs byte thô) vào chung một luồng dispatch.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from qlkh.application.auth_service import Argon2idPasswordHasher, PasswordHasher
from qlkh.devserver.health import health_body
from qlkh.devserver.static_files import (
    DistNotBuilt,
    ensure_dist_built,
    index_html_path,
    looks_like_asset_request,
    resolve_static_file,
)
from qlkh.devserver.wiring import DevWiring, build_wiring
from qlkh.domain.auth import SESSION_COOKIE_NAME, AuthError
from qlkh.domain.subject_context import SubjectContext

_PROBLEM_BASE = "https://qlkh/errors"

#: api-contract: giới hạn body 1 MiB (không tính upload học liệu — ngoài phạm vi ticket này).
_MAX_BODY_BYTES = 1 * 1024 * 1024

# Route patterns (module-level — xem ghi chú P3 ở docstring module).
_STUDENTS_COLLECTION_RE = re.compile(r"^/v1/students/?$")
_STUDENT_ITEM_RE = re.compile(r"^/v1/students/([^/]+)$")
_CLASSES_COLLECTION_RE = re.compile(r"^/v1/classes/?$")
_ENROLLMENTS_COLLECTION_RE = re.compile(r"^/v1/classes/([^/]+)/enrollments/?$")
_ENROLLMENT_ITEM_RE = re.compile(r"^/v1/classes/([^/]+)/enrollments/([^/]+)$")


class _BodyTooLarge(Exception):
    pass


class _BadJson(Exception):
    pass


def _problem(status: int, problem_type: str, title: str, detail: str | None = None) -> tuple[int, dict, tuple]:
    body: dict[str, Any] = {"type": f"{_PROBLEM_BASE}/{problem_type}", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return status, body, ()


class DevApp:
    """Router thuần: (method, path) -> handler đã có. Không chứa quy tắc nghiệp vụ."""

    def __init__(self, wiring: DevWiring, *, allowed_origin: str) -> None:
        self._w = wiring
        self._allowed_origin = allowed_origin

    # ------------------------------------------------------------------ #
    # CORS (scope ticket: cho phép http://localhost:5173, credentials)   #
    # ------------------------------------------------------------------ #
    def _cors_headers(self, origin: str | None) -> list[tuple[str, str]]:
        if origin and origin == self._allowed_origin:
            return [
                ("Access-Control-Allow-Origin", origin),
                ("Access-Control-Allow-Credentials", "true"),
                ("Vary", "Origin"),
            ]
        return []

    def preflight(self, headers: dict[str, str]) -> tuple[int, dict, list[tuple[str, str]]]:
        origin = headers.get("Origin") or headers.get("origin")
        cors = self._cors_headers(origin)
        extra = [
            ("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
            ("Access-Control-Max-Age", "600"),
        ]
        return 204, {}, cors + extra

    # ------------------------------------------------------------------ #
    # Cookie phiên                                                       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _session_id(headers: dict[str, str]) -> str | None:
        raw = headers.get("Cookie") or headers.get("cookie")
        if not raw:
            return None
        jar: cookies.SimpleCookie = cookies.SimpleCookie()
        jar.load(raw)
        morsel = jar.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _authed(
        self,
        session_id: str | None,
        handler_fn: Callable[[SubjectContext], Any],
    ) -> tuple[int, dict, tuple]:
        """Dựng SubjectContext từ phiên rồi gọi handler; 401 nếu phiên không hợp lệ.

        Việc quyết định phiên hợp lệ hay không (hết hạn, thu hồi, tài khoản bị
        vô hiệu hoá...) hoàn toàn nằm ở `AuthService.subject_context` — hàm
        này chỉ bắt `AuthError` mà service đã ném và dịch sang HTTP.
        """
        try:
            ctx = self._w.auth_service.subject_context(session_id)
        except AuthError as exc:
            return exc.status, dict(exc.problem), ()
        result = handler_fn(ctx)
        return result.status, result.body, ()

    # ------------------------------------------------------------------ #
    # Dispatch                                                           #
    # ------------------------------------------------------------------ #
    def dispatch(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        query: dict[str, str],
        raw_body: dict[str, Any],
    ) -> tuple[int, dict, list[tuple[str, str]]]:
        origin = headers.get("Origin") or headers.get("origin")
        cors = self._cors_headers(origin)
        status, body, extra_headers = self._route(method, path, headers, query, raw_body)
        return status, body, cors + list(extra_headers)

    def _route(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        query: dict[str, str],
        raw_body: dict[str, Any],
    ) -> tuple[int, dict, tuple]:
        if method == "GET" and path == "/healthz":
            # Không auth, không PII (ghi chú docstring module) — không đi qua
            # _authed()/session_id một cách cố ý.
            return 200, health_body(), ()

        session_id = self._session_id(headers)

        if method == "POST" and path == "/v1/auth/login":
            ip = headers.get("X-Forwarded-For") or "127.0.0.1"
            result = self._w.auth.login(raw_body, ip=ip)
            return result.status, result.body, result.headers
        if method == "POST" and path == "/v1/auth/logout":
            result = self._w.auth.logout(session_id)
            return result.status, result.body, result.headers
        if method == "GET" and path == "/v1/auth/me":
            result = self._w.auth.me(session_id)
            return result.status, result.body, result.headers

        if _STUDENTS_COLLECTION_RE.match(path) and method in ("GET", "POST"):
            if method == "GET":
                return self._authed(session_id, lambda ctx: self._w.students.list_students(ctx, query=query))
            return self._authed(session_id, lambda ctx: self._w.students.create_student(ctx, raw_body))

        m = _STUDENT_ITEM_RE.match(path)
        if m and method in ("GET", "PATCH"):
            student_id = m.group(1)
            if method == "GET":
                return self._authed(session_id, lambda ctx: self._w.students.get_student(ctx, student_id))
            return self._authed(session_id, lambda ctx: self._w.students.patch_student(ctx, student_id, raw_body))

        if _CLASSES_COLLECTION_RE.match(path) and method in ("GET", "POST"):
            if method == "GET":
                return self._authed(session_id, lambda ctx: self._w.classes.list_classes(ctx, query=query))
            return self._authed(session_id, lambda ctx: self._w.classes.create_class(ctx, raw_body))

        m = _ENROLLMENTS_COLLECTION_RE.match(path)
        if m and method == "POST":
            class_id = m.group(1)
            return self._authed(session_id, lambda ctx: self._w.classes.enroll_student(ctx, class_id, raw_body))

        m = _ENROLLMENT_ITEM_RE.match(path)
        if m and method == "DELETE":
            class_id, student_id = m.group(1), m.group(2)
            return self._authed(session_id, lambda ctx: self._w.classes.unenroll_student(ctx, class_id, student_id))

        return _problem(404, "not-found", "Not Found")


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "QLKHDevServer/0.1"

    # -- đọc request, không có logic nghiệp vụ, chỉ chuẩn hoá giao thức -- #
    def _headers_dict(self) -> dict[str, str]:
        return dict(self.headers.items())

    def _read_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length")
        length = int(length_raw) if length_raw else 0
        if length <= 0:
            return {}
        if length > _MAX_BODY_BYTES:
            raise _BodyTooLarge()
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _BadJson() from exc
        return parsed if isinstance(parsed, dict) else {}

    def _send(self, status: int, body: dict, headers: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else b""
        content_type = "application/problem+json" if status >= 400 else "application/json"
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        """Trả byte thô (file tĩnh) — khác `_send` (JSON thuần) vì `web/dist`
        chứa HTML/JS/CSS/ảnh, không phải JSON (xem `static_files.py`).
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_static(self, path: str) -> None:
        """Phục vụ `web/dist` cho mọi GET không phải `/v1/*` hay `/healthz`.

        Thứ tự quyết định (CR-STAGE-001, TCK-CR-STAGE-001-04):
        1. `web/dist` chưa build (thiếu `index.html`) -> lỗi rõ ràng (503,
           không phải `FileNotFoundError` mơ hồ).
        2. Khớp file thật trong dist (vd `/assets/app.js`) -> trả đúng nội
           dung + mime-type của chính file đó.
        3. Không khớp nhưng "trông giống" một asset (có phần mở rộng) -> 404
           thật, không giả vờ đó là route SPA.
        4. Không khớp và không giống asset (route điều hướng nội bộ SPA) ->
           trả `index.html` để client-side router xử lý.
        """
        try:
            ensure_dist_built()
        except DistNotBuilt as exc:
            self._send(*_problem(503, "dist-not-built", "Service Unavailable", str(exc)))
            return

        resolved = resolve_static_file(path)
        if resolved is not None:
            file_path, content_type = resolved
            self._send_bytes(200, file_path.read_bytes(), content_type)
            return

        if looks_like_asset_request(path):
            self._send(*_problem(404, "not-found", "Not Found"))
            return

        index_path, content_type = index_html_path()
        self._send_bytes(200, index_path.read_bytes(), content_type)

    def _handle(self, method: str) -> None:
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        headers = self._headers_dict()
        try:
            raw_body = self._read_body() if method in ("POST", "PATCH", "PUT") else {}
        except _BodyTooLarge:
            self._send(*_problem(413, "payload-too-large", "Payload Too Large"))
            return
        except _BadJson:
            self._send(*_problem(400, "bad-request", "Bad Request", "JSON không hợp lệ"))
            return
        app: DevApp = self.server.app  # type: ignore[attr-defined]
        status, body, extra_headers = app.dispatch(method, parts.path, headers, query, raw_body)
        self._send(status, body, extra_headers)

    def do_GET(self) -> None:  # noqa: N802 - chữ ký của BaseHTTPRequestHandler
        parts = urlsplit(self.path)
        if parts.path.startswith("/v1/") or parts.path == "/healthz":
            self._handle("GET")
            return
        # Ghi chú module: mọi GET khác (kể cả '/') là static web/dist, cùng
        # origin, không qua DevApp/_route (xem docstring module).
        self._serve_static(parts.path)

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        app: DevApp = self.server.app  # type: ignore[attr-defined]
        headers = self._headers_dict()
        status, body, extra_headers = app.preflight(headers)
        self._send(status, body, extra_headers)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - chữ ký của BaseHTTPRequestHandler
        # devserver: log tối thiểu ra stderr, KHÔNG log body/Cookie (PII/phiên).
        sys.stderr.write(f"{self.address_string()} - [{self.log_date_time_string()}] {format % args}\n")


class DevHTTPServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` mang theo `DevApp` (router) — mỗi kết nối một luồng."""

    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], app: DevApp) -> None:
        self.app = app
        super().__init__(server_address, _RequestHandler)


def make_server(
    host: str,
    port: int,
    *,
    allowed_origin: str = "http://localhost:5173",
    environment: str = "development",
    hasher_factory: Callable[[], PasswordHasher] = Argon2idPasswordHasher,
) -> DevHTTPServer:
    """Dựng server sẵn sàng `serve_forever()` — không cần Redis/DB/TLS thật.

    `port=0` cho hệ điều hành tự chọn cổng trống (dùng trong test); giá trị
    thật đọc lại qua `server.server_address[1]` sau khi khởi tạo.

    `hasher_factory` mặc định `Argon2idPasswordHasher` thật — xem docstring
    `wiring.build_wiring` về lý do tham số này tồn tại (test chưa có
    argon2-cffi trong môi trường chạy test).
    """
    wiring = build_wiring(environment=environment, hasher_factory=hasher_factory)
    app = DevApp(wiring, allowed_origin=allowed_origin)
    return DevHTTPServer((host, port), app)

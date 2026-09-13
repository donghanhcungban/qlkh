"""Test devserver phục vụ `web/dist` tĩnh tại `/` (CR-STAGE-001,
TCK-CR-STAGE-001-04, ADR-0013 mục 4).

Kiểm các tiêu chí Gherkin của ticket:
1. devserver đang chạy, GET / -> phục vụ nội dung từ web/dist (cùng origin).
2. asset tĩnh (js/css) trong dist, GET đường dẫn asset -> đúng nội dung/mime-type.
3. web/dist chưa build -> thông báo lỗi rõ ràng thay vì lỗi mơ hồ.

Không đụng tới `npm run build` thật (ngoài khả năng của môi trường test này —
không có Node); test dựng một `dist_dir` giả tối thiểu (index.html + asset)
bằng `tmp_path`, tương đương hình dạng thật của `web/dist` sau build, để kiểm
đúng logic phục vụ file mà không phụ thuộc toolchain Node.

Test dựng server thật (`make_server`, cổng 0 = ngẫu nhiên) và gọi qua
`http.client`, cùng mẫu với `tests/devserver/test_healthz.py` — không mock
lớp adapter đang kiểm.
"""

from __future__ import annotations

import http.client
import threading
from pathlib import Path

import pytest

from qlkh.devserver import static_files
from qlkh.devserver.http_adapter import make_server
from qlkh.devserver.static_files import (
    DistNotBuilt,
    content_type_for,
    ensure_dist_built,
    index_html_path,
    looks_like_asset_request,
    resolve_static_file,
)


class FakeHasher:
    """Băm giả — chỉ để dựng server, static không chạm auth."""

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


@pytest.fixture()
def fake_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """dist_dir giả với index.html + asset JS/CSS, trỏ `static_files.DIST_DIR` về đây.

    `resolve_static_file`/`index_html_path`/`ensure_dist_built` tra `DIST_DIR`
    ở THÂN hàm (không bind làm default lúc định nghĩa) nên `monkeypatch.setattr`
    trên module có hiệu lực ngay cho các lệnh gọi tiếp theo, kể cả gọi từ
    `http_adapter.py` (module khác, cùng object hàm) — xem ghi chú cài đặt
    trong docstring `static_files.py`.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<!doctype html><html><body>root</body></html>", encoding="utf-8")
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (assets_dir / "app.css").write_text("body { margin: 0; }", encoding="utf-8")
    monkeypatch.setattr(static_files, "DIST_DIR", dist_dir)
    return dist_dir


class TestUnitStaticFiles:
    """Unit trực tiếp trên module (không qua HTTP) cho các nhánh logic thuần."""

    def test_ensure_dist_built_raises_clear_error_when_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "khong-ton-tai"
        with pytest.raises(DistNotBuilt) as excinfo:
            ensure_dist_built(missing)
        assert "npm run build" in str(excinfo.value)

    def test_ensure_dist_built_raises_when_dir_exists_but_no_index(self, tmp_path: Path) -> None:
        empty_dist = tmp_path / "dist"
        empty_dist.mkdir()
        with pytest.raises(DistNotBuilt):
            ensure_dist_built(empty_dist)

    def test_ensure_dist_built_passes_when_index_present(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        ensure_dist_built(dist_dir)  # không ném là đạt

    def test_resolve_static_file_returns_file_and_mime(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist"
        (dist_dir / "assets").mkdir(parents=True)
        (dist_dir / "assets" / "app.js").write_text("x", encoding="utf-8")
        result = resolve_static_file("/assets/app.js", dist_dir=dist_dir)
        assert result is not None
        path, content_type = result
        assert path == (dist_dir / "assets" / "app.js").resolve()
        assert "javascript" in content_type

    def test_resolve_static_file_blocks_path_traversal(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("bí mật", encoding="utf-8")
        result = resolve_static_file("/../secret.txt", dist_dir=dist_dir)
        assert result is None

    def test_resolve_static_file_none_when_not_found(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        assert resolve_static_file("/assets/khong-co.js", dist_dir=dist_dir) is None

    def test_looks_like_asset_request_true_for_extension(self) -> None:
        assert looks_like_asset_request("/assets/app-abc123.js") is True
        assert looks_like_asset_request("/favicon.ico") is True

    def test_looks_like_asset_request_false_for_spa_route(self) -> None:
        assert looks_like_asset_request("/") is False
        assert looks_like_asset_request("/lop-hoc/123") is False

    def test_content_type_for_html_has_charset(self, tmp_path: Path) -> None:
        html = tmp_path / "index.html"
        html.write_text("<html></html>", encoding="utf-8")
        assert content_type_for(html) == "text/html; charset=utf-8"

    def test_content_type_for_binary_has_no_charset(self, tmp_path: Path) -> None:
        png = tmp_path / "logo.png"
        png.write_bytes(b"\x89PNG")
        assert content_type_for(png) == "image/png"

    def test_index_html_path_uses_dist_dir(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        path, content_type = index_html_path(dist_dir=dist_dir)
        assert path == dist_dir / "index.html"
        assert content_type == "text/html; charset=utf-8"


class TestServeRootAndAssetsOverHttp:
    """Given devserver đang chạy — kiểm đủ 4 tiêu chí Gherkin qua HTTP thật."""

    def test_get_root_serves_index_html_from_dist(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/html; charset=utf-8"
        assert body == (fake_dist / "index.html").read_bytes()

    def test_get_js_asset_returns_correct_content_and_mime(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/assets/app.js")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        content_type = resp.getheader("Content-Type") or ""
        assert "javascript" in content_type
        assert body == (fake_dist / "assets" / "app.js").read_bytes()

    def test_get_css_asset_returns_correct_content_and_mime(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/assets/app.css")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/css; charset=utf-8"
        assert body == (fake_dist / "assets" / "app.css").read_bytes()

    def test_spa_route_without_extension_falls_back_to_index(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/lop-hoc/abc-123")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert body == (fake_dist / "index.html").read_bytes()

    def test_missing_asset_with_extension_returns_404_not_index(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/assets/khong-ton-tai.js")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404

    def test_api_routes_still_go_through_v1_dispatch_not_static(self, running_server, fake_dist: Path) -> None:
        # /v1/auth/me không có phiên -> 401 JSON (đi qua DevApp), không phải
        # index.html của static handler.
        conn = _conn(running_server)
        conn.request("GET", "/v1/auth/me")
        resp = conn.getresponse()
        raw = resp.read()
        assert resp.status == 401
        assert resp.getheader("Content-Type", "").startswith("application/problem+json")
        assert raw != (fake_dist / "index.html").read_bytes()

    def test_healthz_still_works_and_is_not_treated_as_static(self, running_server, fake_dist: Path) -> None:
        conn = _conn(running_server)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        raw = resp.read()
        assert resp.status == 200
        assert raw != (fake_dist / "index.html").read_bytes()

    def test_dist_not_built_gives_clear_error_not_generic_500(
        self, running_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given web/dist chưa build (thư mục rỗng, không index.html).
        empty_dir = tmp_path / "dist-rong"
        empty_dir.mkdir()
        monkeypatch.setattr(static_files, "DIST_DIR", empty_dir)

        conn = _conn(running_server)
        conn.request("GET", "/")
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        assert resp.status == 503
        assert "npm run build" in raw

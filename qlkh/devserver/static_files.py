"""Phục vụ `web/dist` tĩnh tại `/` (CR-STAGE-001, TCK-CR-STAGE-001-04, ADR-0013).

Cùng origin với `/v1` và `/healthz` trên devserver — ADR-0013 mục 4 yêu cầu
phục vụ nội dung từ `web/dist` tại `/` cùng origin, không cần cấu hình CORS
riêng cho staging. Adapter thuần giao thức: không có logic nghiệp vụ, chỉ đọc
file tĩnh sinh bởi `npm run build` (thư mục `web/`) và trả đúng nội
dung/mime-type.

SPA fallback: một GET không khớp file tĩnh thật NHƯNG "trông không giống" một
yêu cầu tài sản (không có phần mở rộng ở đoạn cuối đường dẫn, ví dụ điều
hướng nội bộ React Router như `/lop-hoc/123`) thì trả về `index.html` để
client-side router xử lý. Một GET "trông giống" tài sản (có phần mở rộng,
ví dụ `/assets/app-abc123.js`) nhưng không tồn tại thì trả 404 thật — không
che giấu lỗi thiếu asset bằng cách trả nhầm HTML.

Route API (`/v1/*`, `/healthz`) KHÔNG đi qua module này — `http_adapter.py`
xử lý các đường dẫn đó TRƯỚC khi rơi xuống static handler (xem `do_GET`).

Ghi chú cài đặt: các hàm public nhận `dist_dir: Path | None = None` (KHÔNG
bind `DIST_DIR` làm giá trị mặc định ngay lúc định nghĩa hàm) và tra `DIST_DIR`
ở THÂN hàm — default argument ràng buộc lúc định nghĩa module sẽ "đóng băng"
giá trị cũ, khiến test không thể trỏ `DIST_DIR` sang thư mục tạm bằng
monkeypatch. Tra động cho phép test cách ly hoàn toàn khỏi `web/dist` thật.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

#: repo_root/qlkh/devserver/static_files.py -> repo_root
_REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = _REPO_ROOT / "web" / "dist"

BUILD_HINT = (
    "web/dist chưa được build (hoặc thiếu index.html). "
    "Chạy `npm run build` trong thư mục web/ rồi khởi động lại devserver."
)

#: mime-type nào cần charset=utf-8 khi trả về (nội dung văn bản).
_TEXTUAL_MIME_TYPES = {"text/html", "text/css", "text/javascript", "application/javascript", "application/json"}


class DistNotBuilt(Exception):
    """`web/dist` không tồn tại hoặc thiếu `index.html`.

    Thông báo rõ nguyên nhân + lệnh cần chạy — theo tiêu chí nghiệm thu của
    ticket (tránh lỗi mơ hồ kiểu `FileNotFoundError` trần trụi khi devserver
    chưa build gì mà đã được gọi phục vụ giao diện).
    """

    def __init__(self, message: str = BUILD_HINT) -> None:
        super().__init__(message)


def _resolve_dist_dir(dist_dir: Path | None) -> Path:
    return dist_dir if dist_dir is not None else DIST_DIR


def ensure_dist_built(dist_dir: Path | None = None) -> None:
    """Kiểm `dist_dir` có `index.html`; ném `DistNotBuilt` với thông báo rõ nếu không.

    Gọi ở đầu mỗi request GET không phải API (rẻ: chỉ `stat()`, không đọc nội
    dung) để bảo đảm lỗi luôn rõ ràng bất kể devserver khởi động trước hay sau
    khi `npm run build` chạy.
    """
    resolved = _resolve_dist_dir(dist_dir)
    index = resolved / "index.html"
    if not resolved.is_dir() or not index.is_file():
        raise DistNotBuilt()


def looks_like_asset_request(request_path: str) -> bool:
    """True nếu đoạn cuối đường dẫn có phần mở rộng (vd `.js`, `.css`, `.png`).

    Dùng để quyết định giữa "asset thật thiếu -> 404" và "route SPA -> trả
    index.html" khi không tìm thấy file khớp trực tiếp.
    """
    last_segment = request_path.rsplit("/", 1)[-1]
    return "." in last_segment


def _safe_resolve(dist_dir: Path, request_path: str) -> Path | None:
    """Map `request_path` -> file thật bên trong `dist_dir`; chặn path traversal.

    Trả None nếu đường dẫn sau khi resolve nằm ngoài `dist_dir` (vd cố dùng
    `..` để đọc file ngoài thư mục dist).
    """
    rel = request_path.lstrip("/")
    resolved_dist = dist_dir.resolve()
    candidate = (resolved_dist / rel).resolve()
    try:
        candidate.relative_to(resolved_dist)
    except ValueError:
        return None
    return candidate


def content_type_for(path: Path) -> str:
    """Mime-type cho `path`, kèm `charset=utf-8` khi là nội dung văn bản."""
    guessed, _ = mimetypes.guess_type(str(path))
    mime = guessed or "application/octet-stream"
    if mime in _TEXTUAL_MIME_TYPES:
        return f"{mime}; charset=utf-8"
    return mime


def resolve_static_file(request_path: str, *, dist_dir: Path | None = None) -> tuple[Path, str] | None:
    """Trả `(đường_dẫn_file, content_type)` nếu `request_path` khớp file thật trong dist.

    Trả `None` nếu không khớp (caller tự quyết định 404 hay SPA fallback, xem
    `looks_like_asset_request`).
    """
    resolved_dist = _resolve_dist_dir(dist_dir)
    candidate = _safe_resolve(resolved_dist, request_path)
    if candidate is None or not candidate.is_file():
        return None
    return candidate, content_type_for(candidate)


def index_html_path(*, dist_dir: Path | None = None) -> tuple[Path, str]:
    """`(index.html, content_type)` cho `/` và SPA fallback."""
    resolved_dist = _resolve_dist_dir(dist_dir)
    index = resolved_dist / "index.html"
    return index, content_type_for(index)

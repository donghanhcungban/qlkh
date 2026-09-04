"""Xác minh nhị phân tải về trong CI trước khi chạy (SD-09, T-12).

Dùng:
    python tools/verify_download.py <đường-dẫn-file> <url> [--checksums-url URL]

Quy tắc (theo `ci/tool-checksums.txt`), fail-closed hoàn toàn:

1. URL không có mục nào trong file pin → fail.
2. Pin còn là `unpinned` → **fail**. Trước đây trường hợp này chỉ đối chiếu với tệp
   checksums do chính bản phát hành cung cấp và in cảnh báo; kẻ kiểm soát được
   release upstream (hoặc MITM) thay được cả hai tệp nên lớp kiểm đó không có giá
   trị bảo đảm. Nay là lỗi cứng.
3. Pin là SHA-256 → so khớp tuyệt đối; lệch là fail. `--checksums-url` (nếu có)
   được dùng như lớp kiểm bổ sung: digest phải xuất hiện trong tệp checksums.

Cách điền digest thật (chạy trên máy có mạng đáng tin cậy):
    curl -sSL -o f.tar.gz <url> && sha256sum f.tar.gz
rồi thay `unpinned` bằng giá trị đó trong `ci/tool-checksums.txt`.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

PINS_PATH = "ci/tool-checksums.txt"
UNPINNED = "unpinned"


def load_pins(text: str) -> dict[str, str]:
    """Đọc file pin dạng `<sha256|unpinned>  <url>`, bỏ comment và dòng trống."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"dòng pin sai định dạng: {line!r}")
        digest, url = parts
        pins[url] = digest.lower()
    return pins


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(digest: str, url: str, pins: dict[str, str], checksums_text: str | None) -> list[str]:
    """Trả về danh sách lỗi; rỗng nghĩa là đạt."""
    if url not in pins:
        return [f"{url}: chưa khai báo trong {PINS_PATH} (fail-closed)"]
    expected = pins[url]
    if expected == UNPINNED:
        return [
            f"{url}: pin còn '{UNPINNED}' trong {PINS_PATH} — cần ghim SHA-256 thật "
            f"(sha256sum) hoặc dùng mirror nội bộ đã ký (SD-09)"
        ]
    if digest != expected:
        return [f"{url}: sha256 {digest} khác giá trị ghim {expected}"]
    if checksums_text and digest not in checksums_text.lower():
        return [f"{url}: sha256 {digest} không có trong tệp checksums của bản phát hành"]
    return []


def _fetch(url: str) -> str:
    result = subprocess.run(  # noqa: S603 - URL do CI khai báo, không nhận từ người dùng
        ["curl", "-sSL", "--max-time", "60", url],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("dùng: verify_download.py <file> <url> [--checksums-url URL]", file=sys.stderr)
        return 2
    path, url = Path(argv[0]), argv[1]
    checksums_url = argv[3] if len(argv) > 3 and argv[2] == "--checksums-url" else None
    pins = load_pins(Path(PINS_PATH).read_text(encoding="utf-8"))
    checksums_text = _fetch(checksums_url) if checksums_url else None
    errors = verify(sha256_of(path), url, pins, checksums_text)
    for error in errors:
        print(f"verify-download: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

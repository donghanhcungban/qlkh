"""Xác minh nhị phân tải về trong CI trước khi chạy (SD-09, T-12).

Dùng:
    python tools/verify_download.py <đường-dẫn-file> <url> [--checksums-url URL]

Hai tầng kiểm, theo `ci/tool-checksums.txt`:

1. URL đã ghim SHA-256 trong repo → so khớp tuyệt đối; lệch là fail.
2. URL chưa ghim (giá trị `unpinned`) → bắt buộc phải có `--checksums-url` trỏ tới
   tệp checksums của chính bản phát hành đó; digest thật phải xuất hiện trong tệp
   này. Trường hợp này in cảnh báo vì pin trong repo vẫn là việc còn mở — nó phát
   hiện được nhị phân bị tráo lẻ nhưng không chống được kẻ đổi cả hai tệp.

Không có mục nào trong `ci/tool-checksums.txt` cho URL → fail-closed.
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
    if expected != UNPINNED:
        if digest != expected:
            return [f"{url}: sha256 {digest} khác giá trị ghim {expected}"]
        return []
    if not checksums_text:
        return [f"{url}: pin là '{UNPINNED}' nhưng thiếu --checksums-url"]
    if digest not in checksums_text.lower():
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
    if not errors and pins.get(url) == UNPINNED:
        print(f"verify-download: CẢNH BÁO {url} chưa ghim trong repo (SD-09)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

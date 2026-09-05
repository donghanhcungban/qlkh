"""Gắn nhãn phiên bản phát hành cho metric/trace (QLKH-013, scope mục 3).

Nhãn `release_version` cho phép so kết quả trước/sau một bản phát hành (xem
skill observability). Cardinality thấp: một giá trị cho mỗi lần deploy, không
theo từng request.
"""

from __future__ import annotations

import os
from typing import Any

_RELEASE_VERSION_ENV = "QLKH_RELEASE_VERSION"


def release_version() -> str:
    """Đọc phiên bản phát hành hiện hành từ env; 'unknown' nếu chưa cấu hình.

    Không có giá trị mặc định hardcode theo build — điền qua env để pipeline
    phát hành set đúng SemVer/commit khi deploy (Twelve-Factor: config qua env).
    """
    return os.environ.get(_RELEASE_VERSION_ENV, "unknown")


def with_release_label(labels: dict[str, Any]) -> dict[str, Any]:
    """Trả về bản sao của `labels` có thêm `release_version`, không ghi đè nếu đã có."""
    out = dict(labels)
    out.setdefault("release_version", release_version())
    return out

"""Health-check phi nghiệp vụ cho devserver (CR-STAGE-001, TCK-CR-STAGE-001-01, ADR-0013).

`GET /healthz` KHÔNG nằm trong `/v1` (api-contract) — đây là tín hiệu vận hành
thuần tuý cho `infra/staging/wsl/deploy.sh`/`smoke.sh` (ticket sau), không phải
tài nguyên nghiệp vụ. Không yêu cầu xác thực (đúng ngữ nghĩa health-check
chuẩn: script deploy/load balancer gọi trước khi có phiên nào, và trước khi
biết server có sẵn sàng phục vụ hay không).

`sha` LUÔN phản ánh git sha thật của bản build đang chạy, KHÔNG hardcode:
- Ưu tiên biến môi trường `QLKH_GIT_SHA` — deploy.sh (ticket -02) set giá trị
  này khi checkout một ref cụ thể; môi trường triển khai đóng gói dạng
  artifact tách khỏi lịch sử git (không có `.git`) vẫn cần biết đang chạy sha
  nào, đúng nguyên tắc Twelve-Factor: config qua env (giống `release_version`
  ở `qlkh/infrastructure/observability/metrics.py`).
- Nếu biến môi trường chưa set (chạy `python -m qlkh.devserver` trực tiếp từ
  working tree git khi phát triển), chạy `git rev-parse HEAD` MỘT LẦN lúc
  module được import (không phải mỗi request — tránh subprocess trong hot
  path) để đọc sha thật của working tree hiện tại.
- Nếu cả hai đều thất bại (không có `git`, không phải repo git, timeout),
  trả `"unknown"` — KHÔNG bịa giá trị.

`started_at` chốt một lần khi tiến trình import module này (thời điểm khởi
động devserver), theo UTC, định dạng RFC 3339 — không tính lại mỗi request.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime

from qlkh.infrastructure.observability.metrics import release_version

_GIT_SHA_ENV = "QLKH_GIT_SHA"
_GIT_SHA_TIMEOUT_SECONDS = 5


def _read_git_sha() -> str:
    env_sha = os.environ.get(_GIT_SHA_ENV)
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(  # noqa: S603, S607 - lệnh cố định, không nhận input động
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_SHA_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = result.stdout.strip()
    return sha if sha else "unknown"


#: Đọc/chốt một lần khi module được import (lúc devserver khởi động), không
#: phải mỗi request — subprocess `git` và đồng hồ hệ thống không nằm trong hot
#: path của GET /healthz.
_GIT_SHA = _read_git_sha()
_STARTED_AT = datetime.now(UTC).isoformat()


def health_body() -> dict[str, str]:
    """Body JSON cho `GET /healthz` — không chứa PII, không yêu cầu phiên."""
    return {
        "version": release_version(),
        "sha": _GIT_SHA,
        "started_at": _STARTED_AT,
    }

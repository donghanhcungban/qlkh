"""Fitness function cho chính workflow CI (SD-01, SD-09).

Ba bất biến được kiểm bằng test, không dựa vào trí nhớ của người review:

1. `authz-gate` chỉ được phép `continue-on-error: true` khi CHƯA có OpenAPI spec
   hoặc spec chưa có operation nào chạm PII. Endpoint PII đầu tiên xuất hiện thì
   cờ này phải biến mất, nếu không build đỏ (kiểm soát của T-01/T-02, RISK-3).
2. Mọi nhị phân tải bằng `curl` trong workflow phải đi qua
   `tools/verify_download.py` trước khi được chạy (SD-09) — kiểm trên văn bản.
3. Cùng bất biến (2) nhưng kiểm theo CẤU TRÚC từng step đã parse. Bản kiểm văn
   bản cắt chuỗi theo `- run:` nên một step viết dạng `- name: … / run: |` sẽ bị
   gộp vào step trước; nếu step trước có `verify_download.py` thì lệnh tải mới
   lọt cửa. Đây là false negative thật của SD-09, nên có thêm lớp kiểm thứ hai.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DOWNLOAD_URL = re.compile(r"https://\S+\.(?:tar\.gz|zip)")


def _authz_job(workflow: dict[str, Any]) -> dict[str, Any]:
    return (workflow.get("jobs") or {}).get("authz-gate") or {}


def authz_gate_violations(
    workflow: dict[str, Any],
    spec: dict[str, Any] | None,
    pii_operations: list[str],
) -> list[str]:
    """Lỗi khi authz-gate vẫn ở chế độ cảnh báo dù đã có endpoint PII."""
    job = _authz_job(workflow)
    if not job:
        return ["workflow thiếu job authz-gate"]
    if not job.get("continue-on-error"):
        return []
    if spec is None:
        return []
    if pii_operations:
        return [
            "authz-gate còn continue-on-error trong khi OpenAPI đã có "
            f"{len(pii_operations)} operation PII ({', '.join(pii_operations[:3])}…): "
            "phải bỏ cờ này (SD-01, RISK-3)"
        ]
    return []


def unverified_downloads(workflow_text: str) -> list[str]:
    """URL tải về mà không có bước verify_download.py trong cùng khối `run`."""
    problems: list[str] = []
    for block in workflow_text.split("- run:"):
        urls = DOWNLOAD_URL.findall(block)
        if not urls:
            continue
        if "verify_download.py" in block:
            continue
        problems.extend(f"{url}: tải về nhưng không xác minh checksum (SD-09)" for url in urls)
    return problems


def unverified_downloads_in_steps(workflow: dict[str, Any]) -> list[str]:
    """Như `unverified_downloads` nhưng duyệt từng step đã parse.

    Không phụ thuộc cách viết step (`- run:` hay `- name: … / run: |`), nên
    không bị gộp nhầm hai step liền nhau.
    """
    problems: list[str] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for index, step in enumerate(job.get("steps") or []):
            script = step.get("run")
            if not isinstance(script, str):
                continue
            urls = DOWNLOAD_URL.findall(script)
            if not urls or "verify_download.py" in script:
                continue
            label = step.get("name") or f"step #{index}"
            problems.extend(
                f"{job_name}/{label}: {url} tải về nhưng không xác minh checksum (SD-09)"
                for url in urls
            )
    return problems


def load_workflow(path: Path) -> tuple[dict[str, Any], str]:
    import yaml

    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}, text

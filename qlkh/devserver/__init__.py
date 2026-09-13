"""Devserver QLKH (CR-DEV-001, ADR-0012) — adapter http.server cho môi trường thử nghiệm.

Chạy: `python -m qlkh.devserver --port <cổng>`.

Không cần Redis/DB/TLS thật: mọi state (phiên, học viên, lớp...) nằm trong RAM
của tiến trình và mất khi tắt/khởi động lại. Mật khẩu băm bằng argon2id THẬT
(argon2-cffi đã có trong requirements.lock — SD-04/SD-13 đã đóng), cờ tính
năng `QLKH_FEATURE_LOGIN_ARGON2` bật mặc định khi chạy qua `__main__`.

KHÔNG dùng module này cho sản xuất — không có ràng buộc toàn vẹn, không có
TLS, không có store dùng chung giữa nhiều tiến trình (xem `InMemoryAttemptStore`,
`InMemorySessionStore`).
"""

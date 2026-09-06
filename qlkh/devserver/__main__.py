"""Entry point: `python -m qlkh.devserver --port <cổng>` (CR-DEV-001, ADR-0012).

Không cần Redis/DB/TLS thật — mọi state nằm trong RAM tiến trình, mất khi
tắt/khởi động lại. KHÔNG dùng cho sản xuất.
"""

from __future__ import annotations

import argparse
import os
import sys

from qlkh.application.auth_wiring import FeatureDisabled
from qlkh.devserver.http_adapter import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m qlkh.devserver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cors-origin", default="http://localhost:5173")
    args = parser.parse_args(argv)

    # Scope ticket: bật cờ argon2id mặc định cho devserver (chỉ khi caller
    # chưa tự đặt biến môi trường — không ghi đè lựa chọn tường minh của ai).
    os.environ.setdefault("QLKH_FEATURE_LOGIN_ARGON2", "1")

    try:
        server = make_server(args.host, args.port, allowed_origin=args.cors_origin)
    except FeatureDisabled as exc:
        print(f"devserver: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:  # argon2-cffi thiếu hoặc AttemptStore không hợp lệ
        print(f"devserver: lỗi khởi động: {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], server.server_address[1]
    print(f"qlkh devserver: http://{host}:{port} (CORS: {args.cors_origin})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

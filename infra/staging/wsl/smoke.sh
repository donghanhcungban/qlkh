#!/usr/bin/env bash
# infra/staging/wsl/smoke.sh — CR-STAGE-001 (ADR-0013), TCK-CR-STAGE-001-03.
#
# Bằng chứng khách quan DUY NHẤT cho "staging deployed" (hệ quả ADR-0013) —
# gọi TUẦN TỰ, trên một staging ĐÃ ĐANG CHẠY (sau infra/staging/wsl/deploy.sh):
#   1. GET  /healthz
#   2. POST /v1/auth/login   (tài khoản seed, qlkh/devserver/wiring.py)
#   3. GET  /v1/auth/me      (dùng cookie qlkh_session từ bước 2)
#   4. GET  /v1/students     (dùng cùng cookie)
#
# In ra method/path/mã HTTP của TỪNG bước. exit 0 chỉ khi cả 4 bước đúng mã
# VÀ đúng hình dạng response theo api-contract v1.4.0 (GET /healthz nằm
# ngoài /v1, xem qlkh/devserver/health.py — chỉ kiểm 200 + 3 trường). Sai
# mã hoặc sai hình dạng ở BẤT KỲ bước nào -> exit != 0 ngay tại bước đó.
#
# Script này KHÔNG deploy gì — chỉ gọi HTTP vào staging đã chạy sẵn, dùng
# SAU deploy.sh, không thay thế deploy.sh.
#
# Cách dùng:
#   infra/staging/wsl/smoke.sh
#
# Biến môi trường:
#   QLKH_STAGING_HOST    host để gọi (mặc định: 127.0.0.1)
#   QLKH_STAGING_PORT    port để gọi (mặc định: 8080, khớp deploy.sh)
#   QLKH_SMOKE_EMAIL     email tài khoản seed dùng để login (mặc định:
#                        teacher1@qlkh.test, khớp SEED_TEACHER_1_EMAIL trong
#                        qlkh/devserver/wiring.py)
#   QLKH_SMOKE_PASSWORD  mật khẩu tài khoản seed (mặc định: khớp SEED_PASSWORD
#                        cố định trong qlkh/devserver/wiring.py — KHÔNG phải
#                        bí mật thật, chỉ tồn tại trong RAM của devserver thử
#                        nghiệm, không đi kèm dữ liệu người dùng thật). Override
#                        qua env nếu wiring.py đổi seed sau này.
#
# AN TOÀN LOG (tiêu chí nghiệm thu của ticket): script này CHỈ in method,
# path và mã HTTP mỗi bước ra stderr — KHÔNG BAO GIỜ in request body, cookie
# giá trị đầy đủ, response body đầy đủ, hay QLKH_SMOKE_PASSWORD. Payload
# login được ghi ra một file trong thư mục tạm (mktemp -d, riêng của tiến
# trình, bị xoá qua `trap ... EXIT`) rồi gửi bằng `--data-binary @file` —
# KHÔNG truyền qua tham số dòng lệnh của curl (tránh lộ qua `ps`/log lệnh).
# TUYỆT ĐỐI không thêm `set -x` hay `curl -v/--trace` vào file này: cả hai
# đều sẽ in mật khẩu ra log.

set -euo pipefail

HOST="${QLKH_STAGING_HOST:-127.0.0.1}"
PORT="${QLKH_STAGING_PORT:-8080}"
BASE_URL="http://${HOST}:${PORT}"

EMAIL="${QLKH_SMOKE_EMAIL:-teacher1@qlkh.test}"
PASSWORD="${QLKH_SMOKE_PASSWORD:-Seed-Pass-123!}"

CURL_TIMEOUT="${QLKH_SMOKE_TIMEOUT:-5}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

log() { printf '[smoke.sh] %s\n' "$*" >&2; }
fail() {
  log "THẤT BẠI: $*"
  exit 1
}

validate_json() {
  # validate_json <file> <python-checker-heredoc-via-stdin>
  # Trả 0 nếu JSON hợp lệ và checker (đọc stdin) thoát 0; ngược lại 1.
  # Không in body ra log trong mọi trường hợp.
  local file="$1"
  python3 - "$file"
}

# 1) GET /healthz — ngoài /v1 (health-check thuần tuý, không thuộc api-contract).
healthz_body="$WORKDIR/healthz.json"
healthz_code="$(curl -sS -o "$healthz_body" -w '%{http_code}' --max-time "$CURL_TIMEOUT" \
  "$BASE_URL/healthz" || true)"
log "GET /healthz -> ${healthz_code:-000}"
[ "${healthz_code:-000}" = "200" ] || fail "GET /healthz mong 200, nhận ${healthz_code:-000}"
validate_json "$healthz_body" <<'PY' || fail "GET /healthz: body thiếu trường bắt buộc (version, sha, started_at)"
import json, sys
with open(sys.argv[1]) as f:
    body = json.load(f)
required = {"version", "sha", "started_at"}
if not required <= set(body.keys()):
    raise SystemExit(1)
PY

# 2) POST /v1/auth/login — tài khoản seed. Payload viết ra file tạm, gửi qua
# --data-binary @file để KHÔNG lộ qua tham số dòng lệnh của curl.
login_req="$WORKDIR/login_req.json"
printf '{"email":"%s","password":"%s"}' "$EMAIL" "$PASSWORD" >"$login_req"
login_resp="$WORKDIR/login_resp.json"
login_headers="$WORKDIR/login_headers.txt"
login_code="$(curl -sS -o "$login_resp" -D "$login_headers" -w '%{http_code}' --max-time "$CURL_TIMEOUT" \
  -X POST -H 'Content-Type: application/json' --data-binary "@${login_req}" \
  "$BASE_URL/v1/auth/login" || true)"
log "POST /v1/auth/login -> ${login_code:-000}"
[ "${login_code:-000}" = "204" ] || fail "POST /v1/auth/login mong 204, nhận ${login_code:-000}"

session_value="$(grep -i '^set-cookie:' "$login_headers" | grep -o 'qlkh_session=[^;[:space:]]*' | head -n1 | cut -d= -f2)"
[ -n "$session_value" ] || fail "POST /v1/auth/login: 204 nhưng thiếu cookie qlkh_session trong Set-Cookie"

# 3) GET /v1/auth/me — dùng cookie phiên từ bước 2.
me_body="$WORKDIR/me.json"
me_code="$(curl -sS -o "$me_body" -w '%{http_code}' --max-time "$CURL_TIMEOUT" \
  -H "Cookie: qlkh_session=${session_value}" "$BASE_URL/v1/auth/me" || true)"
log "GET /v1/auth/me -> ${me_code:-000}"
[ "${me_code:-000}" = "200" ] || fail "GET /v1/auth/me mong 200, nhận ${me_code:-000}"
validate_json "$me_body" <<'PY' || fail "GET /v1/auth/me: body không đúng schema Me (user_id, role, branch_ids)"
import json, sys
with open(sys.argv[1]) as f:
    body = json.load(f)
required = {"user_id", "role", "branch_ids"}
if not required <= set(body.keys()):
    raise SystemExit(1)
if not isinstance(body["branch_ids"], list):
    raise SystemExit(1)
if body["role"] not in {"parent", "teacher", "staff", "admin"}:
    raise SystemExit(1)
PY

# 4) GET /v1/students — dùng cùng cookie phiên.
students_body="$WORKDIR/students.json"
students_code="$(curl -sS -o "$students_body" -w '%{http_code}' --max-time "$CURL_TIMEOUT" \
  -H "Cookie: qlkh_session=${session_value}" "$BASE_URL/v1/students" || true)"
log "GET /v1/students -> ${students_code:-000}"
[ "${students_code:-000}" = "200" ] || fail "GET /v1/students mong 200, nhận ${students_code:-000}"
validate_json "$students_body" <<'PY' || fail "GET /v1/students: body không đúng schema (data mảng Student, meta)"
import json, sys
with open(sys.argv[1]) as f:
    body = json.load(f)
if "data" not in body or "meta" not in body:
    raise SystemExit(1)
if not isinstance(body["data"], list):
    raise SystemExit(1)
required = {"id", "full_name", "branch_id"}
for student in body["data"]:
    if not required <= set(student.keys()):
        raise SystemExit(1)
PY

log "PASS: healthz=200 login=204 me=200 students=200"
exit 0

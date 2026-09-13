#!/usr/bin/env bash
# tools/run_smoke.sh — "run smoke" THẬT cho QLKH devserver (ADR-0015,
# ADR-0031, TCK-CR-RUNTIME-01).
#
# Đọc runtime.yaml (nguồn sự thật DUY NHẤT cho lệnh khởi động/cổng/health),
# khởi động devserver, chờ health_path xanh, chạy
# infra/staging/wsl/smoke.sh (bằng chứng "staging deployed" theo ADR-0013)
# rồi luôn dừng tiến trình khi thoát — dùng bởi job CI `smoke`
# (.github/workflows/ci.yml) và bởi orchestrator để tạo evidence.run/smoke
# THẬT, đóng gap "luôn unverified" đã lặp 11 lần (REL-027..038).
#
# Cách dùng:
#   tools/run_smoke.sh
#
# Yêu cầu: bash, python3 (dependency requirements.lock đã cài — cần
# argon2-cffi cho auth), curl. KHÔNG cần PyYAML: runtime.yaml đọc bằng
# grep/cut (định dạng phẳng cố ý, xem comment trong file đó).
#
# Exit != 0 nếu: thiếu runtime.yaml, devserver thoát sớm, health không xanh
# trong health_timeout_seconds, hoặc smoke_command thất bại ở bất kỳ bước
# nào — kèm log devserver thật (không nuốt lỗi).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_FILE="$REPO_ROOT/runtime.yaml"

log() { printf '[run_smoke.sh] %s\n' "$*" >&2; }
fail() {
  log "THẤT BẠI: $*"
  exit 1
}

[ -f "$RUNTIME_FILE" ] || fail "thiếu $RUNTIME_FILE — chạy từ repo có khai báo runtime (ADR-0015)"

read_field() {
  local key="$1" value
  value="$(grep -E "^${key}:" "$RUNTIME_FILE" | head -n1 | cut -d: -f2- || true)"
  # trim khoảng trắng đầu/cuối
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  [ -n "$value" ] || fail "runtime.yaml thiếu trường bắt buộc '${key}'"
  printf '%s' "$value"
}

START_COMMAND="$(read_field start_command)"
PORT="$(read_field port)"
HEALTH_PATH="$(read_field health_path)"
HEALTH_TIMEOUT="$(read_field health_timeout_seconds)"
SMOKE_COMMAND="$(read_field smoke_command)"

WORKDIR="$(mktemp -d)"
LOG_FILE="$WORKDIR/devserver.log"
PID=""

cleanup() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    log "dừng devserver pid=$PID"
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

log "khởi động: $START_COMMAND (log: $LOG_FILE)"
cd "$REPO_ROOT"
# shellcheck disable=SC2086
nohup $START_COMMAND >"$LOG_FILE" 2>&1 &
PID=$!

log "chờ GET 127.0.0.1:${PORT}${HEALTH_PATH} xanh, tối đa ${HEALTH_TIMEOUT}s"
waited=0
until curl -sSf "http://127.0.0.1:${PORT}${HEALTH_PATH}" >/dev/null 2>&1; do
  if ! kill -0 "$PID" 2>/dev/null; then
    log "devserver đã thoát sớm — log thật:"
    cat "$LOG_FILE" >&2
    fail "start_command thoát trước khi health xanh"
  fi
  waited=$((waited + 1))
  if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
    log "log devserver (chưa xanh sau ${HEALTH_TIMEOUT}s):"
    cat "$LOG_FILE" >&2
    fail "health không xanh sau ${HEALTH_TIMEOUT}s"
  fi
  sleep 1
done
log "health xanh sau ${waited}s"

log "chạy smoke_command thật: ${SMOKE_COMMAND}"
set +e
QLKH_STAGING_HOST=127.0.0.1 QLKH_STAGING_PORT="$PORT" "$REPO_ROOT/${SMOKE_COMMAND}"
status=$?
set -e

if [ "$status" -eq 0 ]; then
  log "smoke PASS (evidence.run/smoke verified)"
else
  log "smoke THẤT BẠI (exit=${status}) — log devserver thật:"
  cat "$LOG_FILE" >&2
fi
exit "$status"

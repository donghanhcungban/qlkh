#!/usr/bin/env bash
# infra/staging/wsl/deploy.sh — CR-STAGE-001 (ADR-0013), TCK-CR-STAGE-001-02.
#
# Deploy idempotent một git-ref (tag hoặc sha) của QLKH lên môi trường staging
# THẬT trên máy WSL của chủ dự án. KHÔNG dùng Docker/systemd (xem "Phương án
# bị loại" trong ADR-0013) — chỉ nohup + pidfile, phù hợp một môi trường thử
# nghiệm một người dùng trên máy 4CPU/8GB/20GB.
#
# Cách dùng:
#   infra/staging/wsl/deploy.sh <git-ref>
#
# Biến môi trường tuỳ chỉnh (có giá trị mặc định hợp lý, không bắt buộc set):
#   QLKH_STAGING_DIR    thư mục staging (mặc định: $HOME/qlkh-staging)
#   QLKH_REPO_REMOTE    remote để clone lần đầu (mặc định: origin của repo
#                       chứa script này, hoặc chính đường dẫn repo đó nếu
#                       không có remote "origin" — ví dụ khi test cục bộ)
#   QLKH_STAGING_HOST   host bind devserver (mặc định: 0.0.0.0)
#   QLKH_STAGING_PORT   port bind devserver (mặc định: 8080)
#   QLKH_HEALTHZ_TIMEOUT  số giây chờ /healthz xanh (mặc định: 30)
#   QLKH_LOG_MAX_BYTES  ngưỡng xoay log, byte (mặc định: 10485760 = 10 MiB)
#   QLKH_LOG_KEEP       số file log cũ giữ lại sau khi xoay (mặc định: 5)
#
# Trạng thái ghi tại $QLKH_STAGING_DIR/var/:
#   devserver.pid       pid tiến trình devserver đang chạy
#   devserver.log[.N]   log devserver (nohup), xoay theo kích thước
#   current             sha đang chạy (ghi SAU KHI healthz xanh)
#   previous            sha chạy trước lần deploy gần nhất thành công gần đây
#                       nhất (ghi TRƯỚC khi ghi đè `current`) — rollback.sh
#                       đọc file này.
#
# QUAN TRỌNG: var/ nằm BÊN TRONG working tree của $STAGING_DIR nhưng KHÔNG
# được git track/ignore trong repo nguồn. `git clean -fd` mặc định sẽ coi
# toàn bộ var/ là "untracked" và XOÁ SẠCH (pidfile, current, previous, log) —
# phá vỡ idempotency và rollback ngay từ lần deploy thứ hai. Vì vậy:
#   1. fetch_ref() PHẢI loại trừ var/ khỏi git clean (`-e var`).
#   2. Sau khi checkout/clean, PHẢI mkdir -p lại VAR_DIR phòng trường hợp nó
#      chưa tồn tại (checkout lần đầu) trước khi bất kỳ ai đọc/ghi file
#      trạng thái bên trong.
#
# Idempotent: chạy lại với cùng ref không lỗi, không nhân đôi tiến trình —
# tiến trình cũ luôn bị dừng qua pidfile trước khi tiến trình mới được khởi
# động, bất kể ref có đổi hay không.

set -euo pipefail

REF="${1:?Cách dùng: deploy.sh <git-ref>}"

STAGING_DIR="${QLKH_STAGING_DIR:-$HOME/qlkh-staging}"
VAR_DIR="$STAGING_DIR/var"
PID_FILE="$VAR_DIR/devserver.pid"
LOG_FILE="$VAR_DIR/devserver.log"
CURRENT_FILE="$VAR_DIR/current"
PREVIOUS_FILE="$VAR_DIR/previous"

HOST="${QLKH_STAGING_HOST:-0.0.0.0}"
PORT="${QLKH_STAGING_PORT:-8080}"
HEALTHZ_URL="http://127.0.0.1:${PORT}/healthz"
HEALTHZ_TIMEOUT="${QLKH_HEALTHZ_TIMEOUT:-30}"
MAX_LOG_BYTES="${QLKH_LOG_MAX_BYTES:-10485760}"
LOG_KEEP="${QLKH_LOG_KEEP:-5}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# infra/staging/wsl/ -> gốc repo (3 cấp lên)
SOURCE_REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

log() { printf '[deploy.sh] %s\n' "$*" >&2; }

mkdir -p "$VAR_DIR"

rotate_log() {
  [ -f "$LOG_FILE" ] || return 0
  local size
  size=$(wc -c <"$LOG_FILE" 2>/dev/null || echo 0)
  if [ "${size:-0}" -ge "$MAX_LOG_BYTES" ]; then
    local i
    for ((i = LOG_KEEP - 1; i >= 1; i--)); do
      if [ -f "$LOG_FILE.$i" ]; then
        mv -f "$LOG_FILE.$i" "$LOG_FILE.$((i + 1))"
      fi
    done
    mv -f "$LOG_FILE" "$LOG_FILE.1"
    log "đã xoay log (>= ${MAX_LOG_BYTES} byte), giữ tối đa ${LOG_KEEP} bản cũ"
  fi
}

is_running() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

stop_old_process() {
  [ -f "$PID_FILE" ] || return 0
  local old_pid
  old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if is_running "$old_pid"; then
    log "dừng tiến trình cũ pid=$old_pid"
    kill "$old_pid" 2>/dev/null || true
    local waited=0
    while is_running "$old_pid" && [ "$waited" -lt 20 ]; do
      sleep 0.5
      waited=$((waited + 1))
    done
    if is_running "$old_pid"; then
      log "tiến trình cũ (pid=$old_pid) không dừng sau 10s — SIGKILL"
      kill -9 "$old_pid" 2>/dev/null || true
    fi
  else
    log "pidfile tồn tại nhưng tiến trình không còn chạy (stale) — bỏ qua"
  fi
  rm -f "$PID_FILE"
}

fetch_ref() {
  if [ ! -d "$STAGING_DIR/.git" ]; then
    local remote
    remote="${QLKH_REPO_REMOTE:-$(git -C "$SOURCE_REPO_ROOT" remote get-url origin 2>/dev/null || echo "$SOURCE_REPO_ROOT")}"
    log "chưa có checkout tại $STAGING_DIR — clone lần đầu từ $remote"
    git clone "$remote" "$STAGING_DIR"
  fi

  log "fetch ref=$REF"
  if git -C "$STAGING_DIR" fetch --tags --force origin "$REF" 2>/dev/null; then
    git -C "$STAGING_DIR" checkout --force --detach FETCH_HEAD
  else
    # Một số server git không cho fetch trực tiếp theo sha tuỳ ý
    # (uploadpack.allowReachableSHA1InWant tắt); fetch toàn bộ rồi checkout
    # theo tên (tag hoặc sha) như phương án dự phòng.
    log "fetch trực tiếp ref=$REF thất bại — fetch toàn bộ rồi checkout theo tên"
    git -C "$STAGING_DIR" fetch --tags --force origin
    git -C "$STAGING_DIR" checkout --force --detach "$REF"
  fi
  # KHÔNG được clean var/: nó không nằm trong git nhưng nằm trong working
  # tree — `git clean -fd` không loại trừ sẽ xoá pidfile/current/previous/log
  # (xem cảnh báo ở đầu file). "-e var" loại trừ đường dẫn var/ (và mọi thứ
  # bên trong nó) khỏi việc dọn untracked files.
  git -C "$STAGING_DIR" clean -fd -e var
  # Phòng trường hợp checkout lần đầu (VAR_DIR chưa từng được tạo bên trong
  # STAGING_DIR) — tái tạo ngay sau clean, trước khi main() đọc/ghi bất kỳ
  # file trạng thái nào.
  mkdir -p "$VAR_DIR"
}

wait_healthz() {
  local expected_sha="$1"
  local deadline=$((SECONDS + HEALTHZ_TIMEOUT))
  local body got_sha
  while [ "$SECONDS" -lt "$deadline" ]; do
    body="$(curl -fsS --max-time 2 "$HEALTHZ_URL" 2>/dev/null || true)"
    if [ -n "$body" ]; then
      got_sha="$(printf '%s' "$body" | grep -o '"sha"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -E 's/.*"sha"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/')"
      if [ "$got_sha" = "$expected_sha" ]; then
        log "healthz OK — 200, sha=$got_sha"
        return 0
      fi
    fi
    sleep 1
  done
  log "healthz KHÔNG đạt sau ${HEALTHZ_TIMEOUT}s (mong sha=$expected_sha, body cuối='${body:-}')"
  return 1
}

main() {
  fetch_ref

  local new_sha
  new_sha="$(git -C "$STAGING_DIR" rev-parse HEAD)"
  log "sha mục tiêu: $new_sha"

  (cd "$STAGING_DIR" && uv sync --frozen)

  # Ghi sha hiện tại (của lần deploy trước) vào previous TRƯỚC KHI ghi đè —
  # chỉ khi đã từng deploy thành công (current tồn tại).
  if [ -f "$CURRENT_FILE" ]; then
    cp -f "$CURRENT_FILE" "$PREVIOUS_FILE"
  fi

  stop_old_process
  rotate_log

  export QLKH_GIT_SHA="$new_sha"
  (
    cd "$STAGING_DIR"
    nohup uv run python -m qlkh.devserver --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
  )
  log "devserver khởi động, pid=$(cat "$PID_FILE") log=$LOG_FILE"

  if ! wait_healthz "$new_sha"; then
    log "TRIỂN KHAI THẤT BẠI: healthz không xanh trong ${HEALTHZ_TIMEOUT}s — không ghi var/current"
    exit 1
  fi

  printf '%s\n' "$new_sha" >"$CURRENT_FILE"
  log "deploy thành công: sha=$new_sha"
}

main "$@"

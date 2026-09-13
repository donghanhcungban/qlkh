#!/usr/bin/env bash
# infra/staging/wsl/rollback.sh — CR-STAGE-001 (ADR-0013), TCK-CR-STAGE-001-02.
#
# Rollback = redeploy sha đã chạy trước lần deploy gần nhất, đọc từ
# var/previous (do deploy.sh ghi). Tương đương gọi
# `deploy.sh <sha-trước>` — dùng lại toàn bộ logic idempotent + healthz-gate
# ≤30s của deploy.sh, không lặp lại logic ở đây.
#
# Cách dùng:
#   infra/staging/wsl/rollback.sh
#
# Cùng bộ biến môi trường tuỳ chỉnh với deploy.sh (QLKH_STAGING_DIR, v.v.) —
# xem deploy.sh.

set -euo pipefail

STAGING_DIR="${QLKH_STAGING_DIR:-$HOME/qlkh-staging}"
VAR_DIR="$STAGING_DIR/var"
PREVIOUS_FILE="$VAR_DIR/previous"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '[rollback.sh] %s\n' "$*" >&2; }

if [ ! -f "$PREVIOUS_FILE" ]; then
  log "không có $PREVIOUS_FILE — chưa có lần deploy thành công thứ hai trở lên nào để biết sha trước đó, không thể rollback"
  exit 1
fi

prev_sha="$(cat "$PREVIOUS_FILE")"
if [ -z "$prev_sha" ]; then
  log "$PREVIOUS_FILE rỗng — không thể rollback"
  exit 1
fi

log "rollback về sha=$prev_sha (đọc từ var/previous)"
exec "$SCRIPT_DIR/deploy.sh" "$prev_sha"

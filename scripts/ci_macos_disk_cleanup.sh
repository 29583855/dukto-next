#!/usr/bin/env bash

# 日期：2026-11-05；先保存业务退出码；仅清理本轮自建镜像，业务失败优先，清理失败单独保留。
dukto_macos_cleanup() {
    local primary_status="$1"
    local cleanup_status=0
    python -u -X utf8 scripts/macos_disk_cleanup.py \
        --mount "$2" --image "$3" --root "$RUNNER_TEMP" --report "$4" || cleanup_status=$?
    if test "$primary_status" -ne 0; then
        return "$primary_status"
    fi
    return "$cleanup_status"
}

#!/usr/bin/env bash
# 日期：2026-11-05；以只读精确源码和独立可写输出运行原生 musl 验证，不修改旧虚拟机输入。
set -euo pipefail

: "${GITHUB_WORKSPACE:?Missing checked-out source}"
: "${DUKTO_MUSL_WORK:?Missing isolated work directory}"
: "${DUKTO_MUSL_IMAGE:?Missing prepared musl image}"
: "${GITHUB_SHA:?Missing source identity}"
test "$#" -gt 0

exec docker run --rm --init --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=${GITHUB_WORKSPACE},target=/source,readonly" \
    --mount "type=bind,source=${DUKTO_MUSL_WORK},target=/work" \
    --workdir /source \
    --env GITHUB_SHA \
    --env QT_QPA_PLATFORM=offscreen \
    --env QT_QUICK_BACKEND=software \
    --env QT_OPENGL=software \
    --env LIBGL_ALWAYS_SOFTWARE=1 \
    "${DUKTO_MUSL_IMAGE}" "$@"

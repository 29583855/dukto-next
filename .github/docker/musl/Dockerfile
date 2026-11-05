# 日期：2026-11-05；原生 CPU 的 musl 验证镜像，记录实际基础镜像摘要和 apk 版本。
ARG ALPINE_IMAGE=alpine:3.24.1
FROM ${ALPINE_IMAGE}
ARG RUNNER_UID=1001
ARG RUNNER_GID=1001
RUN apk add --no-cache build-base cmake git openssl openssl-dev python3 py3-psutil \
    font-wqy-zenhei fontconfig qt5-qtbase qt5-qtbase-dev qt5-qtbase-x11 qt5-qtbase-sqlite \
    qt5-qtdeclarative qt5-qtdeclarative-dev qt5-qtquickcontrols2 qt5-qtquickcontrols2-dev \
    qt5-qtgraphicaleffects \
    && addgroup -g "${RUNNER_GID}" dukto \
    && adduser -D -u "${RUNNER_UID}" -G dukto dukto
# 日期：2026-11-05；普通用户执行权限/文件保护测试，禁止 root 绕过目标权限。
USER dukto
WORKDIR /source

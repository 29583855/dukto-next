#pragma once

#include <QString>

namespace dukto {
struct Endpoint {
    QString host;
    quint16 port;
};

// 日期：2026-11-04；解析主机名、IPv4、IPv6 及显式端口，拒绝端口截断和含混括号。
Endpoint parseEndpoint(const QString &input, int defaultPort);
} // namespace dukto

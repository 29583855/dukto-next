#include "endpoint.h"
#include "error.h"

#include <QHostAddress>
#include <QRegularExpression>

namespace dukto {
// 日期：2026-11-04；IPv6 附端口须用 [地址]:端口，普通 IPv6 使用单独的默认端口。
Endpoint parseEndpoint(const QString &input, int defaultPort) {
    if (defaultPort < 1 || defaultPort > 65535)
        throw Error(ExitCode::Config, QStringLiteral("端口须在 1–65535 范围内"), "arguments");
    const auto text = input.trimmed();
    QString host = text;
    int port = defaultPort;
    QString portText;
    if (text.startsWith('[')) {
        const auto end = text.indexOf(']');
        if (end < 0 || (!text.mid(end + 1).isEmpty() && text[end + 1] != ':'))
            throw Error(ExitCode::Config, QStringLiteral("IPv6 地址括号格式无效"), "arguments");
        host = text.mid(1, end - 1);
        if (QHostAddress(host).protocol() != QAbstractSocket::IPv6Protocol)
            throw Error(ExitCode::Config, QStringLiteral("括号内应为 IPv6 地址"), "arguments");
        if (end + 1 < text.size())
            portText = text.mid(end + 2);
    } else if (text.count(':') == 1) {
        host = text.section(':', 0, 0);
        portText = text.section(':', 1);
    } else if (text.contains(':') && QHostAddress(text).protocol() != QAbstractSocket::IPv6Protocol)
        throw Error(ExitCode::Config, QStringLiteral("IPv6 地址无效"), "arguments");
    const bool hasPort =
        (text.startsWith('[') && text.endsWith(']'))
            ? false
            : text.count(':') == 1 || (text.startsWith('[') && text.contains("]:"));
    if (hasPort) {
        bool valid = false;
        static const QRegularExpression digits("^[0-9]{1,5}$");
        port = portText.toInt(&valid);
        if (!valid || !digits.match(portText).hasMatch() || port < 1 || port > 65535)
            throw Error(ExitCode::Config, QStringLiteral("地址中的端口无效"), "arguments");
    }
    static const QRegularExpression invalid("[\\s/\\\\\\[\\]@?#]");
    if (host.isEmpty() || host.toUtf8().size() > 253 || invalid.match(host).hasMatch())
        throw Error(ExitCode::Config, QStringLiteral("目标 IP 或主机名无效"), "arguments");
    return {host, static_cast<quint16>(port)};
}
} // namespace dukto

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

// 日期：2026-11-06；IP Helper依赖Winsock/Windows基础类型，保持此包含顺序。
#include <iphlpapi.h>
#endif

#include "tcplistener.h"
#include <QNetworkInterface>
#include <QNetworkProxy>
#include <cstring>

namespace dukto {
#ifdef Q_OS_WIN
namespace {
class WinsockRuntime final {
  public:
    // 日期：2026-11-06；独立持有Winsock引用，既不依赖Qt私有初始化，也不在监听存活时提前清理。
    WinsockRuntime() {
        WSADATA data{};
        error = WSAStartup(MAKEWORD(2, 2), &data);
    }
    // 日期：2026-11-06；函数静态对象随进程收尾，成功初始化与清理严格配对。
    ~WinsockRuntime() {
        if (error == 0)
            WSACleanup();
    }
    int error = 0;
};

class NativeSocket final {
  public:
    // 日期：2026-11-06；原生描述符从创建即归守卫所有，绑定、选项或Qt接管失败都能关闭。
    explicit NativeSocket(SOCKET descriptor) : descriptor(descriptor) {
    }
    // 日期：2026-11-06；只有Qt明确接管成功才释放所有权；异常路径不泄露原生socket。
    ~NativeSocket() {
        if (descriptor != INVALID_SOCKET)
            closesocket(descriptor);
    }
    SOCKET descriptor;
};

// 日期：2026-11-06；旧程序的共享通配监听可能允许后来独占绑定；先后两次核对重叠端点，原表最多8MiB。
DWORD overlappingListeners(const QHostAddress &address, quint16 port, ULONG family, int &count) {
    DWORD size = 0;
    auto status =
        GetExtendedTcpTable(nullptr, &size, FALSE, family, TCP_TABLE_OWNER_PID_LISTENER, 0);
    for (int attempt = 0; attempt < 3 && status == ERROR_INSUFFICIENT_BUFFER; ++attempt) {
        if (size > 8 * 1024 * 1024)
            return ERROR_NOT_ENOUGH_MEMORY;
        QByteArray bytes(static_cast<int>(size), Qt::Uninitialized);
        status = GetExtendedTcpTable(bytes.data(), &size, FALSE, family,
                                     TCP_TABLE_OWNER_PID_LISTENER, 0);
        if (status != NO_ERROR)
            continue;
        if (family == AF_INET) {
            const auto table = reinterpret_cast<const MIB_TCPTABLE_OWNER_PID *>(bytes.constData());
            for (DWORD index = 0; index < table->dwNumEntries; ++index) {
                const auto &row = table->table[index];
                if (ntohs(static_cast<u_short>(row.dwLocalPort)) == port &&
                    (address == QHostAddress::Any || address == QHostAddress::AnyIPv4 ||
                     row.dwLocalAddr == INADDR_ANY ||
                     row.dwLocalAddr == htonl(address.toIPv4Address())))
                    ++count;
            }
        } else {
            const auto table = reinterpret_cast<const MIB_TCP6TABLE_OWNER_PID *>(bytes.constData());
            const auto requested = address.toIPv6Address();
            const Q_IPV6ADDR any{};
            for (DWORD index = 0; index < table->dwNumEntries; ++index) {
                const auto &row = table->table[index];
                const bool wildcard = std::memcmp(row.ucLocalAddr, any.c, 16) == 0;
                const bool same = std::memcmp(row.ucLocalAddr, requested.c, 16) == 0 &&
                                  (address.scopeId().isEmpty() ||
                                   row.dwLocalScopeId == address.scopeId().toUInt() ||
                                   row.dwLocalScopeId == QNetworkInterface::interfaceIndexFromName(
                                                             address.scopeId()));
                if (ntohs(static_cast<u_short>(row.dwLocalPort)) == port &&
                    (address == QHostAddress::Any || address == QHostAddress::AnyIPv6 || wildcard ||
                     same))
                    ++count;
            }
        }
        return NO_ERROR;
    }
    return status;
}
} // namespace
#endif

// 日期：2026-11-06；本地监听明确直连，不把服务端口交给用户系统代理。
TcpListener::TcpListener(QObject *parent) : QTcpServer(parent) {
    setProxy(QNetworkProxy::NoProxy);
}

// 日期：2026-11-06；Windows的通配/指定地址及IPv4/双栈重叠一律拒绝共享，避免连接进入错误协议。
bool TcpListener::listen(const QHostAddress &address, quint16 port) {
    if (isListening())
        return false;
    nativeError_.clear();
#ifdef Q_OS_WIN
    // 日期：2026-11-06；原生系统错误仅转为公开错误码；不重试共享绑定或静默更换请求端口。
    const auto fail = [this](int code) {
        nativeError_ = QStringLiteral("无法独占监听端口（Windows错误 %1）").arg(code);
        nativeCode_ = code == WSAEADDRINUSE      ? QAbstractSocket::AddressInUseError
                      : code == WSAEACCES        ? QAbstractSocket::SocketAccessError
                      : code == WSAEADDRNOTAVAIL ? QAbstractSocket::SocketAddressNotAvailableError
                                                 : QAbstractSocket::UnknownSocketError;
        return false;
    };
    static WinsockRuntime runtime;
    if (runtime.error != 0)
        return fail(runtime.error);
    const bool dual = address == QHostAddress::Any;
    if (!dual && address.protocol() != QAbstractSocket::IPv4Protocol &&
        address.protocol() != QAbstractSocket::IPv6Protocol)
        return fail(WSAEINVAL);
    // 日期：2026-11-06；端口0由系统分配，已有固定端口在创建前就拒绝，不劫持旧Qt共享监听。
    const auto overlaps = [&](quint16 selectedPort, int allowed) -> int {
        for (ULONG family : {ULONG(AF_INET), ULONG(AF_INET6)}) {
            if (!dual &&
                ((family == AF_INET) != (address.protocol() == QAbstractSocket::IPv4Protocol)))
                continue;
            int count = 0;
            const auto status = overlappingListeners(address, selectedPort, family, count);
            if (status != NO_ERROR)
                return static_cast<int>(status);
            if (count > allowed)
                return WSAEADDRINUSE;
        }
        return 0;
    };
    if (port != 0) {
        const auto conflict = overlaps(port, 0);
        if (conflict != 0)
            return fail(conflict);
    }
    int family = address.protocol() == QAbstractSocket::IPv4Protocol ? AF_INET : AF_INET6;
    auto descriptor = WSASocketW(family, SOCK_STREAM, IPPROTO_TCP, nullptr, 0,
                                 WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
    if (descriptor == INVALID_SOCKET && dual &&
        (WSAGetLastError() == WSAEAFNOSUPPORT || WSAGetLastError() == WSAEPROTONOSUPPORT)) {
        family = AF_INET;
        descriptor = WSASocketW(family, SOCK_STREAM, IPPROTO_TCP, nullptr, 0,
                                WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
    }
    if (descriptor == INVALID_SOCKET)
        return fail(WSAGetLastError());
    NativeSocket socket(descriptor);
    const BOOL exclusive = TRUE;
    if (setsockopt(descriptor, SOL_SOCKET, SO_EXCLUSIVEADDRUSE,
                   reinterpret_cast<const char *>(&exclusive), sizeof(exclusive)) == SOCKET_ERROR)
        return fail(WSAGetLastError());
    sockaddr_storage storage{};
    int length = 0;
    if (family == AF_INET6) {
        const DWORD ipv6Only = dual ? 0 : 1;
        if (setsockopt(descriptor, IPPROTO_IPV6, IPV6_V6ONLY,
                       reinterpret_cast<const char *>(&ipv6Only), sizeof(ipv6Only)) == SOCKET_ERROR)
            return fail(WSAGetLastError());
        auto &endpoint = reinterpret_cast<sockaddr_in6 &>(storage);
        endpoint.sin6_family = AF_INET6;
        endpoint.sin6_port = htons(port);
        const auto bytes = address.toIPv6Address();
        std::memcpy(&endpoint.sin6_addr, bytes.c, sizeof(endpoint.sin6_addr));
        if (!address.scopeId().isEmpty()) {
            bool numeric = false;
            endpoint.sin6_scope_id = address.scopeId().toUInt(&numeric);
            if (!numeric)
                endpoint.sin6_scope_id =
                    QNetworkInterface::interfaceIndexFromName(address.scopeId());
            if (endpoint.sin6_scope_id == 0)
                return fail(WSAEINVAL);
        }
        length = sizeof(endpoint);
    } else {
        auto &endpoint = reinterpret_cast<sockaddr_in &>(storage);
        endpoint.sin_family = AF_INET;
        endpoint.sin_port = htons(port);
        endpoint.sin_addr.s_addr = htonl(dual ? INADDR_ANY : address.toIPv4Address());
        length = sizeof(endpoint);
    }
    if (::bind(descriptor, reinterpret_cast<const sockaddr *>(&storage), length) == SOCKET_ERROR ||
        ::listen(descriptor, SOMAXCONN) == SOCKET_ERROR)
        return fail(WSAGetLastError());
    if (getsockname(descriptor, reinterpret_cast<sockaddr *>(&storage), &length) == SOCKET_ERROR)
        return fail(WSAGetLastError());
    const auto selectedPort =
        family == AF_INET ? ntohs(reinterpret_cast<const sockaddr_in &>(storage).sin_port)
                          : ntohs(reinterpret_cast<const sockaddr_in6 &>(storage).sin6_port);
    const auto conflict = overlaps(selectedPort, 1);
    if (conflict != 0)
        return fail(conflict);
    // 日期：2026-11-06；Qt接管描述符并管理初始化失败的清理，原生守卫不重复关闭。
    socket.descriptor = INVALID_SOCKET;
    return setSocketDescriptor(static_cast<qintptr>(descriptor));
#else
    return QTcpServer::listen(address, port);
#endif
}

// 日期：2026-11-06；Qt接管后的错误仍由Qt提供，绑定前的原生错误由同一监听器保存。
QString TcpListener::errorString() const {
    return nativeError_.isEmpty() ? QTcpServer::errorString() : nativeError_;
}

// 日期：2026-11-06；成功接管后恢复Qt错误分类，不把历史原生失败留给后续成功监听。
QAbstractSocket::SocketError TcpListener::serverError() const {
    return nativeError_.isEmpty() ? QTcpServer::serverError() : nativeCode_;
}

} // namespace dukto

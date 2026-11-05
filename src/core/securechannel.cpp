#include "securechannel.h"
#include "error.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QEventLoop>
#include <QSslCertificate>
#include <QSslError>
#include <QSslKey>
#include <QTimer>
#include <exception>

namespace dukto {
namespace next {
// 日期：2026-11-04；只对完全相同、自签且仍有效的叶证书选择性忽略 SelfSignedCertificate。
SecureChannel::SecureChannel(int timeoutMs, const std::atomic_bool *cancel)
    : timeoutMs_(timeoutMs), cancel_(cancel) {
    if (timeoutMs < 100 || timeoutMs > 3600000)
        throw Error(ExitCode::Config, QStringLiteral("安全通道超时必须在 100ms 到一小时之间"),
                    "tls");
    socket_.setReadBufferSize(FragmentLimit + DataHeaderBytes + HeaderBytes);
    QObject::connect(&socket_, QOverload<const QList<QSslError> &>::of(&QSslSocket::sslErrors),
                     &socket_, [this](const QList<QSslError> &errors) {
                         // 日期：2026-11-04；错误信号里不抛异常；未被明确允许的错误交由 VerifyPeer
                         // 中止握手。
                         sslErrors_ = true;
                         const auto certificate = socket_.peerCertificate();
                         const auto now = QDateTime::currentDateTimeUtc();
                         if (fingerprint_.size() != 32 ||
                             certificate.digest(QCryptographicHash::Sha256) != fingerprint_ ||
                             certificate.effectiveDate() > now || certificate.expiryDate() <= now)
                             return;
                         for (const auto &error : errors)
                             if (error.error() != QSslError::SelfSignedCertificate ||
                                 error.certificate() != certificate)
                                 return;
                         if (!errors.isEmpty()) {
                             socket_.ignoreSslErrors(errors);
                             sslErrors_ = false;
                         }
                     });
}

// 日期：2026-11-04；取消和错误路径均不等待对端继续发送；完成确认由业务任务状态机提供。
SecureChannel::~SecureChannel() {
    socket_.abort();
}

// 日期：2026-11-05；只转换已有授信，不重新建立 socket，不把同一 4 MiB 同时计入两类。
void SecureChannel::classifyAsData() {
    credit_.classifyAsData();
}

// 日期：2026-11-04；信任配置必须显式选定，禁止自动降级明文或在身份变化后重新配对。
void SecureChannel::connectTo(const QString &host, quint16 port, const QString &peerName,
                              const QSslConfiguration &configuration,
                              const QByteArray &fingerprint) {
    if (used_ || host.isEmpty() || !port || peerName.isEmpty() ||
        (!fingerprint.isEmpty() && fingerprint.size() != 32))
        throw Error(ExitCode::Config, QStringLiteral("安全通道配置无效或通道已使用"), "tls");
    used_ = true;
    fingerprint_ = fingerprint;
    auto policy = configuration;
    policy.setProtocol(QSsl::TlsV1_2OrLater);
    socket_.setSslConfiguration(policy);
    socket_.setPeerVerifyMode(QSslSocket::VerifyPeer);
    socket_.setPeerVerifyName(peerName);
    socket_.connectToHostEncrypted(host, port);
    socket_.setSocketOption(QAbstractSocket::LowDelayOption, 1);
    handshake();
}

// 日期：2026-11-04；接管的描述符从此只属于本通道；应用层随后必须执行能力协商和身份认证。
void SecureChannel::accept(qintptr descriptor, const QSslConfiguration &configuration) {
    if (used_)
        throw Error(ExitCode::Config, QStringLiteral("安全通道已使用"), "tls");
    used_ = true;
    if (!socket_.setSocketDescriptor(descriptor))
        throw Error(ExitCode::Network, QStringLiteral("无法接管安全连接描述符"), "tls");
    socket_.setSocketOption(QAbstractSocket::LowDelayOption, 1);
    if (configuration.localCertificate().isNull() || configuration.privateKey().isNull())
        throw Error(ExitCode::Config, QStringLiteral("服务 TLS 证书或私钥缺失"), "tls");
    auto policy = configuration;
    policy.setProtocol(QSsl::TlsV1_2OrLater);
    socket_.setSslConfiguration(policy);
    socket_.setPeerVerifyMode(QSslSocket::VerifyNone);
    socket_.startServerEncryption();
    handshake();
}

// 日期：2026-11-05；证书/TLS 握手永久失败优先分类为权限错误，不能被超时或断线归类后自动重试。
void SecureChannel::check(QElapsedTimer &elapsed, const QString &stage) const {
    if ((cancel_ && cancel_->load()) || (taskCancel_ && taskCancel_->load()))
        throw Error(ExitCode::Cancelled, QStringLiteral("安全连接操作已取消"), stage);
    if (!established_ &&
        (sslErrors_ || socket_.error() == QAbstractSocket::SslHandshakeFailedError))
        throw Error(ExitCode::Permission, QStringLiteral("TLS 证书、主机名或握手校验失败"), stage);
    if (elapsed.elapsed() >= timeoutMs_)
        throw Error(ExitCode::Network, QStringLiteral("安全连接操作超时"), stage);
}

// 日期：2026-11-04；信号回调只记录异常再退出局部事件循环，避免 C++ 异常穿过 Qt 分发栈。
void SecureChannel::waitUntil(const std::function<bool()> &ready, QElapsedTimer &elapsed,
                              const QString &stage) {
    std::exception_ptr failure;
    bool done = false;
    QEventLoop loop;
    const auto evaluate = [&]() {
        if (done || failure)
            return;
        // 日期：2026-11-04；完成谓词先于断开检查，允许读取对端发送完毕后留下的最后一帧。
        try {
            check(elapsed, stage);
            if (ready()) {
                done = true;
                loop.quit();
            } else if (socket_.state() == QAbstractSocket::UnconnectedState) {
                throw Error(sslErrors_ ? ExitCode::Permission : ExitCode::Network,
                            sslErrors_ ? QStringLiteral("TLS 证书或主机名校验失败")
                                       : QStringLiteral("安全连接已断开或无法连接"),
                            stage);
            }
        } catch (...) {
            failure = std::current_exception();
            loop.quit();
        }
    };
    QTimer timer;
    timer.setInterval(25);
    QObject::connect(&timer, &QTimer::timeout, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::readyRead, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::bytesWritten, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::encryptedBytesWritten, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::encrypted, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::stateChanged, &loop, evaluate);
    QObject::connect(&socket_, &QSslSocket::errorOccurred, &loop, evaluate);
    evaluate();
    if (!done && !failure) {
        timer.start();
        loop.exec(QEventLoop::ExcludeUserInputEvents);
    }
    if (failure)
        std::rethrow_exception(failure);
}

// 日期：2026-11-04；固定指纹必须在加密完成后再核对，防止 CA 信任的其他证书绕过 pin。
void SecureChannel::handshake() {
    try {
        if (!QSslSocket::supportsSsl())
            throw Error(ExitCode::Config, QStringLiteral("当前 TLS 运行库不可用"), "tls");
        QElapsedTimer elapsed;
        elapsed.start();
        waitUntil([this]() { return socket_.isEncrypted(); }, elapsed, "tls");
        peerFingerprint_ = socket_.peerCertificate().digest(QCryptographicHash::Sha256);
        if (!fingerprint_.isEmpty() && peerFingerprint() != fingerprint_)
            throw Error(ExitCode::Permission, QStringLiteral("服务器证书指纹不匹配"), "tls");
        established_ = true;
    } catch (...) {
        socket_.abort();
        throw;
    }
}

// 日期：2026-11-05；逐帧有界读取；进度帧仅交给当前已协商任务的观察者，不代替业务确认。
Frame SecureChannel::read() {
    try {
        if (!established_)
            throw Error(ExitCode::Network, QStringLiteral("安全连接尚未建立"), "protocol");
        for (;;) {
            QElapsedTimer elapsed;
            elapsed.start();
            Decoder decoder;
            while (decoder.requiredBytes() > 0) {
                waitUntil([this]() { return socket_.bytesAvailable() > 0; }, elapsed, "protocol");
                const auto bytes = socket_.read(decoder.requiredBytes());
                if (bytes.isEmpty())
                    throw Error(ExitCode::Network, QStringLiteral("安全连接正文读取失败"),
                                "protocol");
                decoder.append(bytes);
            }
            auto result = decoder.take();
            if (result.header.type != Type::Progress)
                return result;
            if (!progress_)
                throw Error(ExitCode::Config, QStringLiteral("未协商或阶段不允许字节进度帧"),
                            "progress");
            progress_(result);
        }
    } catch (...) {
        established_ = false;
        socket_.abort();
        throw;
    }
}

// 日期：2026-11-04；通道串行执行一帧，最大排队大小由已验证帧长度确定，写完才接受下一帧。
void SecureChannel::write(const Frame &frame) {
    try {
        if (!socket_.isEncrypted() || !socket_.isOpen() ||
            socket_.state() != QAbstractSocket::ConnectedState)
            throw Error(ExitCode::Network, QStringLiteral("安全连接尚未建立"), "protocol");
        const auto bytes = encodeFrame(frame);
        QElapsedTimer elapsed;
        elapsed.start();
        check(elapsed, "protocol");
        // 日期：2026-11-04；握手成功信号可能早于最后 TLS 记录排空，先等待既有队列归还。
        waitUntil(
            [this]() {
                return socket_.bytesToWrite() == 0 && socket_.encryptedBytesToWrite() == 0;
            },
            elapsed, "protocol");
        if (!socket_.isOpen() || socket_.state() != QAbstractSocket::ConnectedState)
            throw Error(ExitCode::Network, QStringLiteral("安全连接在写入前已断开"), "protocol");
        if (socket_.write(bytes) != bytes.size())
            throw Error(ExitCode::Network, QStringLiteral("安全连接写入失败或队列未归还"),
                        "protocol");
        waitUntil(
            [this]() {
                return socket_.bytesToWrite() == 0 && socket_.encryptedBytesToWrite() == 0;
            },
            elapsed, "protocol");
    } catch (...) {
        socket_.abort();
        throw;
    }
}

// 日期：2026-11-04；64 位整数的字段编码仍由调用方使用规范十进制字符串提供。
void SecureChannel::write(Type type, quint64 correlation, const QJsonObject &object) {
    const auto bytes = encodeControl(object);
    write({{type, correlation, static_cast<quint32>(bytes.size())}, bytes});
}

// 日期：2026-11-04；摘要针对实际握手叶证书的 DER，不针对易变化的 PEM 文本或公钥字符串。
QByteArray SecureChannel::peerFingerprint() const {
    return peerFingerprint_;
}

// 日期：2026-11-04；固定 TLS 读缓冲继续生效；只泵送本工作线程事件，不接受或吞掉业务请求。
void SecureChannel::checkpoint(const QString &stage) {
    QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
    if ((cancel_ && cancel_->load()) || (taskCancel_ && taskCancel_->load()))
        throw Error(ExitCode::Cancelled, QStringLiteral("安全连接操作已取消"), stage);
    if (!established_ || socket_.state() != QAbstractSocket::ConnectedState ||
        !socket_.isEncrypted())
        throw Error(ExitCode::Network, QStringLiteral("安全连接已断开"), stage);
}
// 日期：2026-11-04；调用方在线程内绑定会话取消源，不转移 socket 归属或清除原来的服务取消源。
void SecureChannel::observeCancellation(const std::atomic_bool *cancel) {
    taskCancel_ = cancel;
}
// 日期：2026-11-05；禁止嵌套覆盖活动观察者，异常析构可用空回调清除。
void SecureChannel::observeProgress(std::function<void(const Frame &)> handler) {
    if (handler && progress_)
        throw Error(ExitCode::Config, QStringLiteral("字节进度观察者已存在"), "progress");
    progress_ = std::move(handler);
}
} // namespace next
} // namespace dukto

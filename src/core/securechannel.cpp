#include "securechannel.h"
#include "error.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QEventLoop>
#include <QSslCertificate>
#include <QSslError>
#include <QSslKey>
#include <QThread>
#include <QTimer>
#include <exception>
#ifdef Q_OS_MACOS
#include <QHostAddress>
#include <memory>
#include <openssl/pem.h>
#include <openssl/x509v3.h>
#endif

namespace dukto {
namespace next {
#ifdef Q_OS_MACOS
namespace {
// 日期：2026-11-05；SecureTransport 合并信任错误；仅独立完成自签/用途/算法/日期/SAN
// 验证后允许固定叶证书。
bool validPinnedSelfSigned(const QSslCertificate &certificate, const QString &peerName) {
    const auto encoded = certificate.toDer();
    const auto *cursor = reinterpret_cast<const unsigned char *>(encoded.constData());
    std::unique_ptr<X509, decltype(&X509_free)> native(d2i_X509(nullptr, &cursor, encoded.size()),
                                                       X509_free);
    if (!native ||
        cursor != reinterpret_cast<const unsigned char *>(encoded.constData()) + encoded.size() ||
        X509_NAME_cmp(X509_get_subject_name(native.get()), X509_get_issuer_name(native.get())) != 0)
        return false;
    std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> key(X509_get_pubkey(native.get()),
                                                            EVP_PKEY_free);
    if (!key || X509_verify(native.get(), key.get()) != 1)
        return false;
    std::unique_ptr<X509_STORE, decltype(&X509_STORE_free)> store(X509_STORE_new(),
                                                                  X509_STORE_free);
    std::unique_ptr<X509_STORE_CTX, decltype(&X509_STORE_CTX_free)> context(X509_STORE_CTX_new(),
                                                                            X509_STORE_CTX_free);
    if (!store || !context || X509_STORE_add_cert(store.get(), native.get()) != 1 ||
        X509_STORE_CTX_init(context.get(), store.get(), native.get(), nullptr) != 1 ||
        X509_STORE_CTX_set_purpose(context.get(), X509_PURPOSE_SSL_SERVER) != 1)
        return false;
    auto parameters = X509_STORE_CTX_get0_param(context.get());
    X509_VERIFY_PARAM_set_auth_level(parameters, 2);
    X509_VERIFY_PARAM_set_hostflags(parameters, X509_CHECK_FLAG_NO_PARTIAL_WILDCARDS);
    QHostAddress address;
    const auto name = peerName.toUtf8();
    const int configured =
        address.setAddress(peerName)
            ? X509_VERIFY_PARAM_set1_ip_asc(parameters, name.constData())
            : X509_VERIFY_PARAM_set1_host(parameters, name.constData(), name.size());
    return configured == 1 && X509_verify_cert(context.get()) == 1;
}
} // namespace
#endif
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
                         for (const auto &error : errors) {
                             bool allowed = error.error() == QSslError::SelfSignedCertificate;
#ifdef Q_OS_MACOS
                             if (error.error() == QSslError::CertificateUntrusted)
                                 allowed = validPinnedSelfSigned(certificate, peerName_);
#endif
                             if (!allowed || error.certificate() != certificate)
                                 return;
                         }
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

// 日期：2026-11-05；只在业务发送期启用；绑定同一个请求序号，不跨任务读取或保留远端正文。
void SecureChannel::observePeerFailure(quint64 correlation) {
    failureCorrelation_ = correlation;
}

// 日期：2026-11-05；写等待期间远端可先拒绝正文；先处理完整失败帧再判断断线，固定四帧上限。
void SecureChannel::checkPeerFailure() {
    if (!failureCorrelation_ || !established_)
        return;
    for (int count = 0; count < 4; ++count) {
        if (socket_.bytesAvailable() < HeaderBytes)
            return;
        const auto header = decodeHeader(socket_.peek(HeaderBytes));
        if (header.correlation != failureCorrelation_)
            throw Error(ExitCode::Integrity, QStringLiteral("发送期响应请求序号不同"), "transfer");
        if (header.type != Type::Failure && header.type != Type::Progress &&
            header.type != Type::TaskState)
            return;
        if (socket_.bytesAvailable() < HeaderBytes + header.payloadBytes)
            return;
        socket_.read(HeaderBytes);
        Frame frame{header, socket_.read(header.payloadBytes)};
        const auto value = parseControl(frame.payload);
        if (header.type == Type::Failure) {
            const auto code = value["code"].toInt(-1);
            if (code < 1 || code > 7 || !value["message"].isString() || !value["stage"].isString())
                throw Error(ExitCode::Config, QStringLiteral("发送期错误响应无效"), "transfer");
            throw Error(static_cast<ExitCode>(code), value["message"].toString(),
                        value["stage"].toString());
        }
        if (header.type == Type::Progress) {
            if (!progress_)
                throw Error(ExitCode::Config, QStringLiteral("发送期未协商字节进度帧"), "progress");
            progress_(frame);
        } else if (value != QJsonObject{{"state", "busy"}}) {
            throw Error(ExitCode::Config, QStringLiteral("发送期忙心跳字段无效"), "transfer");
        }
    }
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
    peerName_ = peerName;
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

// 日期：2026-11-05；回调只记录异常；写等待先观察同请求失败，读等待不触碰正在解码的半帧。
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
            if (writing_)
                checkPeerFailure();
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

// 日期：2026-11-05；逐帧有界排空；发送期先保留已到达的远端失败，再处理后续断开。
void SecureChannel::write(const Frame &frame) {
    try {
        checkPeerFailure();
        writing_ = true;
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
        writing_ = false;
    } catch (...) {
        writing_ = false;
        socket_.abort();
        throw;
    }
}

// 日期：2026-11-04；64 位整数的字段编码仍由调用方使用规范十进制字符串提供。
void SecureChannel::write(Type type, quint64 correlation, const QJsonObject &object) {
    const auto bytes = encodeControl(object);
    write({{type, correlation, static_cast<quint32>(bytes.size())}, bytes});
}

// 日期：2026-11-05；错误响应后等待发送端观察并关闭；每次最多丢弃64KiB，固定一秒上限，不积累正文。
void SecureChannel::writeFailure(quint64 correlation, const QJsonObject &object) {
    write(Type::Failure, correlation, object);
    QElapsedTimer elapsed;
    elapsed.start();
    const auto budget = qMin(timeoutMs_, 1000);
    while (socket_.state() != QAbstractSocket::UnconnectedState && elapsed.elapsed() < budget) {
        if ((cancel_ && cancel_->load()) || (taskCancel_ && taskCancel_->load()))
            break;
        if (socket_.bytesAvailable() > 0)
            socket_.read(qMin<qint64>(socket_.bytesAvailable(), 64 * 1024));
        else
            QThread::msleep(5);
        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
    }
    socket_.disconnectFromHost();
}

// 日期：2026-11-04；摘要针对实际握手叶证书的 DER，不针对易变化的 PEM 文本或公钥字符串。
QByteArray SecureChannel::peerFingerprint() const {
    return peerFingerprint_;
}

// 日期：2026-11-05；固定读缓冲，帧边界先检查发送期远端失败，普通业务确认不被消费。
void SecureChannel::checkpoint(const QString &stage) {
    QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
    checkPeerFailure();
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

#include "core/legacy.h"
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSemaphore>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtEndian>
#include <atomic>
#include <functional>
#include <stdexcept>

namespace {
// 日期：2026-11-25；Release构建同样保留断言，失败输出明确原因。
void require(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

// 日期：2026-11-25；主线程继续处理监听及排队信号，等待时间有界。
bool spinUntil(const std::function<bool()> &condition, int timeout = 5000) {
    QElapsedTimer elapsed;
    elapsed.start();
    while (!condition() && elapsed.elapsed() < timeout)
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    return condition();
}

// 日期：2026-11-25；独立构造R6单文件帧，测试不调用生产序列化函数。
QByteArray frame(const QByteArray &content) {
    QByteArray bytes;
    for (const qint64 value : {qint64(1), qint64(content.size())}) {
        char integer[8];
        qToLittleEndian(value, reinterpret_cast<uchar *>(integer));
        bytes.append(integer, 8);
    }
    bytes.append("same.bin", 8);
    bytes.append('\0');
    char size[8];
    qToLittleEndian(qint64(content.size()), reinterpret_cast<uchar *>(size));
    bytes.append(size, 8);
    return bytes + content;
}

struct ReleaseWorker {
    QSemaphore &gate;
    // 日期：2026-11-25；任何断言异常都先释放测试阻塞点，避免监听器析构等待死锁。
    ~ReleaseWorker() {
        gate.release();
    }
};

// 日期：2026-11-25；强制旧工作线程在EOF后仍未退出，新批次不得被当成繁忙丢弃。
void verifyCompletionHandoff() {
    QTemporaryDir directory;
    require(directory.isValid(), "temporary directory");
    QSemaphore gate;
    std::atomic_bool finishing{false};
    dukto::LegacyListener listener(directory.path(), 5000, nullptr,
                                   directory.filePath("receipts.sqlite"));
    require(listener.listen(QHostAddress::LocalHost, 0), "listen");
    ReleaseWorker release{gate};
    QTcpSocket first;
    first.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    require(spinUntil([&]() { return listener.findChild<dukto::LegacyJob *>() != nullptr; }),
            "first worker created");
    auto *job = listener.findChild<dukto::LegacyJob *>();
    QObject::connect(
        job, &dukto::LegacyJob::result, job,
        [&](int, const dukto::LegacyResult &) {
            finishing.store(true);
            gate.acquire();
        },
        Qt::DirectConnection);
    first.write(frame("original"));
    require(spinUntil([&]() {
                return finishing.load() && first.state() == QAbstractSocket::UnconnectedState;
            }),
            "first EOF while worker finishing");
    QTcpSocket second;
    second.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    second.write(frame("replacement"));
    QElapsedTimer overlap;
    overlap.start();
    spinUntil([&]() { return overlap.elapsed() >= 250; });
    const bool rejectedWhileFinishing = second.state() == QAbstractSocket::UnconnectedState;
    gate.release();
    const bool received =
        spinUntil([&]() { return QFile::exists(directory.filePath("same (2).bin")); });
    require(!rejectedWhileFinishing, "next batch rejected after previous successful EOF");
    require(received, "queued batch not committed");
    QFile original(directory.filePath("same.bin"));
    QFile replacement(directory.filePath("same (2).bin"));
    require(original.open(QIODevice::ReadOnly) && original.readAll() == "original",
            "original overwritten");
    require(replacement.open(QIODevice::ReadOnly) && replacement.readAll() == "replacement",
            "replacement bytes");
    require(spinUntil([&]() { return listener.setOutput(directory.path()); }),
            "active slot not released");
}
// 日期：2026-11-25；阻塞收尾期间只容纳一个等待连接，取消或到期后均可继续收新批次。
void verifyPendingLimits(bool expire) {
    QTemporaryDir directory;
    require(directory.isValid(), "limits temporary directory");
    QSemaphore gate;
    std::atomic_bool finishing{false};
    dukto::LegacyListener listener(directory.path(), expire ? 800 : 5000, nullptr,
                                   directory.filePath("receipts.sqlite"));
    ReleaseWorker release{gate};
    require(listener.listen(QHostAddress::LocalHost, 0), "limits listen");
    QTcpSocket first;
    first.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    require(spinUntil([&]() { return listener.findChild<dukto::LegacyJob *>() != nullptr; }),
            "limits first worker");
    auto *job = listener.findChild<dukto::LegacyJob *>();
    QObject::connect(
        job, &dukto::LegacyJob::result, job,
        [&](int, const dukto::LegacyResult &) {
            finishing.store(true);
            gate.acquire();
        },
        Qt::DirectConnection);
    first.write(frame("original"));
    require(spinUntil([&]() {
                return finishing.load() && first.state() == QAbstractSocket::UnconnectedState;
            }),
            "limits first EOF");
    QTcpSocket waiting;
    waiting.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    require(spinUntil([&]() { return waiting.state() == QAbstractSocket::ConnectedState; }),
            "waiting connected");
    waiting.write(frame("discarded"));
    QElapsedTimer accepted;
    accepted.start();
    spinUntil([&]() { return accepted.elapsed() >= 100; });
    require(waiting.state() == QAbstractSocket::ConnectedState, "waiting rejected early");
    require(!listener.setOutput(directory.path()), "busy output changed");
    QTcpSocket third;
    bool thirdDisconnected = false;
    QObject::connect(&third, &QTcpSocket::disconnected, &third,
                     [&]() { thirdDisconnected = true; });
    third.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    require(spinUntil([&]() { return thirdDisconnected; }), "third connection not rejected");
    if (!expire)
        listener.cancel();
    require(spinUntil([&]() { return waiting.state() == QAbstractSocket::UnconnectedState; }),
            "pending connection not cleared");
    gate.release();
    require(spinUntil([&]() { return listener.setOutput(directory.path()); }),
            "limits active slot not released");
    require(!QFile::exists(directory.filePath("same (2).bin")), "cancelled pending committed");
    QTcpSocket recovery;
    recovery.connectToHost(QHostAddress::LocalHost, listener.serverPort());
    recovery.write(frame("recovery"));
    require(spinUntil([&]() { return QFile::exists(directory.filePath("same (2).bin")); }),
            "listener did not recover");
    QFile received(directory.filePath("same (2).bin"));
    require(received.open(QIODevice::ReadOnly) && received.readAll() == "recovery",
            "recovery bytes mismatch");
    require(spinUntil([&]() { return listener.setOutput(directory.path()); }),
            "recovery active slot not released");
}
} // namespace

// 日期：2026-11-25；独立进程输出机器可读收据，实测同一移动接收核心的线程交接。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName("DuktoMobileListenerTests");
    try {
        verifyCompletionHandoff();
        verifyPendingLimits(false);
        verifyPendingLimits(true);
        QTextStream(stdout) << QJsonDocument(QJsonObject{{"passed", true},
                                                         {"forcedEofBeforeWorkerExit", true},
                                                         {"sameNameCopyVerified", true},
                                                         {"senderRetries", 0},
                                                         {"pendingLimit", 1},
                                                         {"pendingCancelPassed", true},
                                                         {"pendingTimeoutPassed", true},
                                                         {"recoveryAfterCleanupPassed", true}})
                                   .toJson();
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}

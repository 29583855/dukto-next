#include "core/catalog.h"
#include "core/discovery.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/files.h"
#include "core/legacy.h"
#include "core/manifest.h"
#include "core/privatestore.h"
#include "core/sourcefile.h"
#include "core/tcplistener.h"

#include <QDir>
#include <QFile>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <QtEndian>
#include <QtTest>
#include <array>
#include <atomic>
#include <exception>
#include <limits>
#include <stdexcept>
#include <thread>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <sddl.h>
#endif
#ifndef Q_OS_WIN
#include <sys/stat.h>
#include <unistd.h>
#endif

Q_DECLARE_METATYPE(QHostAddress)

class CoreTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；Windows旧Qt允许IPv4头像与双栈传输复用端口；两种先后顺序均须拒绝。
    void exclusiveTcpBinding_data() {
        QTest::addColumn<QHostAddress>("firstAddress");
        QTest::addColumn<QHostAddress>("secondAddress");
        QTest::addColumn<bool>("firstUsesQt");
        for (bool firstQt : {false, true}) {
            const auto prefix = firstQt ? QByteArray("qt-first-") : QByteArray("exclusive-first-");
            QTest::newRow((prefix + "ipv4-then-dual").constData())
                << QHostAddress(QHostAddress::AnyIPv4) << QHostAddress(QHostAddress::Any)
                << firstQt;
            QTest::newRow((prefix + "dual-then-ipv4").constData())
                << QHostAddress(QHostAddress::Any) << QHostAddress(QHostAddress::AnyIPv4)
                << firstQt;
            QTest::newRow((prefix + "ipv4-wildcard-then-specific").constData())
                << QHostAddress(QHostAddress::AnyIPv4) << QHostAddress(QHostAddress::LocalHost)
                << firstQt;
            QTest::newRow((prefix + "ipv6-same").constData())
                << QHostAddress(QHostAddress::LocalHostIPv6)
                << QHostAddress(QHostAddress::LocalHostIPv6) << firstQt;
        }
    }

    // 日期：2026-11-06；拒绝后来者不影响原监听；关闭原监听后同地址端口可重新使用。
    void exclusiveTcpBinding() {
        QFETCH(QHostAddress, firstAddress);
        QFETCH(QHostAddress, secondAddress);
        QFETCH(bool, firstUsesQt);
        QTcpServer qtServer;
        dukto::TcpListener exclusiveServer;
        const bool firstBound = firstUsesQt ? qtServer.listen(firstAddress, 0)
                                            : exclusiveServer.listen(firstAddress, 0);
        QVERIFY(firstBound);
        QTcpServer *first = firstUsesQt ? &qtServer : &exclusiveServer;
        const auto port = first->serverPort();
        QVERIFY(port != 0);
        dukto::TcpListener second;
        QVERIFY2(!second.listen(secondAddress, port),
                 "two protocols acquired an overlapping TCP port");
        QVERIFY(!second.isListening());
        QVERIFY(!second.errorString().isEmpty());
        // 日期：2026-11-06；Windows外部旧Qt后来跨地址族复用是已留档系统边界；同族保护仍须通过。
        const bool crossFamilyShared = firstAddress.protocol() == QAbstractSocket::IPv4Protocol &&
                                       secondAddress == QHostAddress::Any;
        if (!firstUsesQt && !crossFamilyShared) {
            QTcpServer shared;
            QVERIFY2(!shared.listen(secondAddress, port),
                     "a same-family Qt shared listener bypassed the exclusive port");
        }
        QTcpSocket client;
        const auto loopback = firstAddress.protocol() == QAbstractSocket::IPv6Protocol
                                  ? QHostAddress::LocalHostIPv6
                                  : QHostAddress::LocalHost;
        client.connectToHost(loopback, port);
        QVERIFY(client.waitForConnected(2000));
        QTRY_VERIFY(first->hasPendingConnections());
        QScopedPointer<QTcpSocket> peer(first->nextPendingConnection());
        QVERIFY(peer);
        const QByteArray payload("original protocol remains reachable");
        QCOMPARE(client.write(payload), qint64(payload.size()));
        client.flush();
        QTRY_COMPARE(peer->bytesAvailable(), qint64(payload.size()));
        QCOMPARE(peer->readAll(), payload);
        client.abort();
        peer->abort();
        peer.reset();
        first->close();
        QVERIFY2(second.listen(secondAddress, port), qPrintable(second.errorString()));
        QCOMPARE(second.serverPort(), port);
    }

    // 日期：2026-11-06；显式IPv6监听不占用IPv4，双栈监听仍能同时接收两个地址族。
    void tcpAddressFamilies() {
        dukto::TcpListener ipv6;
        QVERIFY2(ipv6.listen(QHostAddress::AnyIPv6), qPrintable(ipv6.errorString()));
        dukto::TcpListener ipv4;
        QVERIFY2(ipv4.listen(QHostAddress::AnyIPv4, ipv6.serverPort()),
                 qPrintable(ipv4.errorString()));
        dukto::TcpListener dual;
        QVERIFY2(dual.listen(), qPrintable(dual.errorString()));
        for (const auto address : {QHostAddress::LocalHost, QHostAddress::LocalHostIPv6}) {
            QTcpSocket client;
            client.connectToHost(address, dual.serverPort());
            QVERIFY(client.waitForConnected(2000));
            QTRY_VERIFY(dual.hasPendingConnections());
            QScopedPointer<QTcpSocket> accepted(dual.nextPendingConnection());
            QVERIFY(accepted);
            client.abort();
            accepted->abort();
        }
    }

    // 日期：2026-11-04；状态根和文件实际核验原生权限，更新原子可读且非法键/超量读取明确拒绝。
    void privateStoreContracts() {
        QTemporaryDir temporary;
        const auto path = temporary.filePath("private");
        {
            dukto::PrivateStore store(path, true);
            QVERIFY(!store.exists("identity.json"));
            store.write("identity.json", "secret-first");
            QCOMPARE(store.read("identity.json"), QByteArray("secret-first"));
            store.write("identity.json", "secret-second");
            QCOMPARE(store.read("identity.json"), QByteArray("secret-second"));
            QVERIFY_EXCEPTION_THROWN(store.read("identity.json", 2), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.read("../outside"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.write("NUL", "forbidden"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.write("too-large", QByteArray(1024 * 1024 + 1, 'x')),
                                     dukto::Error);
        }
        dukto::PrivateStore reopened(path);
        QCOMPARE(reopened.read("identity.json"), QByteArray("secret-second"));
        QCOMPARE(QDir(path).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(), 0);
#ifdef Q_OS_WIN
        PSECURITY_DESCRIPTOR security = nullptr;
        QVERIFY(ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"D:P(A;;FA;;;WD)", SDDL_REVISION_1, &security, nullptr));
        const auto filePath = QDir::toNativeSeparators(path + "/identity.json");
        const bool applied = SetFileSecurityW(
            reinterpret_cast<LPCWSTR>(filePath.utf16()),
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION, security);
        LocalFree(security);
        QVERIFY(applied);
#else
        QVERIFY(::chmod(QFile::encodeName(path + "/identity.json").constData(), 0644) == 0);
#endif
        QVERIFY_EXCEPTION_THROWN(reopened.read("identity.json"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(reopened.write("identity.json", "must not replace unsafe file"),
                                 dukto::Error);
    }
#ifdef Q_OS_WIN
    // 日期：2026-11-06；私有配置读和数据库对象核验均覆盖瞬时、持续和重复DELETE句柄占用。
    void privateReadSharingContention_data() {
        QTest::addColumn<bool>("validateOnly");
        QTest::addColumn<bool>("persistent");
        QTest::addColumn<int>("rounds");
        QTest::newRow("read-release") << false << false << 1;
        QTest::newRow("read-persistent") << false << true << 1;
        QTest::newRow("read-repeated") << false << false << 8;
        QTest::newRow("validate-release") << true << false << 1;
        QTest::newRow("validate-persistent") << true << true << 1;
        QTest::newRow("validate-repeated") << true << false << 8;
    }

    // 日期：2026-11-06；原生DELETE访问模拟原子改配窗口，成功必须读到原文，永久占用保持明确错误及有界资源。
    void privateReadSharingContention() {
        QFETCH(bool, validateOnly);
        QFETCH(bool, persistent);
        QFETCH(int, rounds);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        store.write("policy.json", "original-state");
        const auto native = QDir::toNativeSeparators(temporary.filePath("private/policy.json"));
        DWORD before = 0;
        QVERIFY(GetProcessHandleCount(GetCurrentProcess(), &before));
        for (int index = 0; index < rounds; ++index) {
            const auto handle =
                CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), DELETE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                            OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            QVERIFY(handle != INVALID_HANDLE_VALUE);
            // 日期：2026-11-06；默认传输源不得继承私有配置重试，也不允许通过开放删除共享绕过占用。
            bool immediateRejected = false;
            try {
                dukto::SourceFile source(temporary.filePath("private/policy.json"));
            } catch (const dukto::Error &error) {
                immediateRejected = error.code == dukto::ExitCode::Disk && error.stage == "read";
            }
            std::atomic_bool closed{false};
            std::thread release;
            if (!persistent)
                release = std::thread([&]() {
                    // 日期：2026-11-06；只关闭测试已拥有的原生句柄，不能修改生产等待预算。
                    QThread::msleep(80);
                    closed.store(CloseHandle(handle));
                });
            dukto::ExitCode code = dukto::ExitCode::Success;
            QString stage;
            QByteArray observed;
            qint64 bytes = -1;
            std::exception_ptr unexpected;
            QElapsedTimer elapsed;
            elapsed.start();
            try {
                if (validateOnly)
                    bytes = store.validateFile("policy.json");
                else
                    observed = store.read("policy.json");
            } catch (const dukto::Error &error) {
                code = error.code;
                stage = error.stage;
            } catch (...) {
                unexpected = std::current_exception();
            }
            const auto milliseconds = elapsed.elapsed();
            if (release.joinable())
                release.join();
            else
                closed.store(CloseHandle(handle));
            QVERIFY(closed.load());
            QVERIFY(immediateRejected);
            QVERIFY(!unexpected);
            QVERIFY2(milliseconds < 3000, qPrintable(QString::number(milliseconds)));
            if (persistent) {
                QCOMPARE(code, dukto::ExitCode::Disk);
                QCOMPARE(stage, QString("read-busy"));
                QVERIFY(milliseconds >= 450);
            } else {
                QCOMPARE(code, dukto::ExitCode::Success);
                QVERIFY(milliseconds >= 50);
                if (validateOnly)
                    QCOMPARE(bytes, qint64(14));
                else
                    QCOMPARE(observed, QByteArray("original-state"));
            }
            QCOMPARE(store.read("policy.json"), QByteArray("original-state"));
            QCOMPARE(store.validateFile("policy.json"), qint64(14));
            QCOMPARE(
                QDir(store.directory()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(),
                0);
        }
        DWORD after = 0;
        QVERIFY(GetProcessHandleCount(GetCurrentProcess(), &after));
        QVERIFY2(after <= before + 2,
                 qPrintable(QString("handles %1 -> %2").arg(before).arg(after)));
    }

    // 日期：2026-11-06；真实原生读句柄覆盖短暂释放、持续占用及重复替换后的资源回收。
    void privateAtomicWriteContention_data() {
        QTest::addColumn<bool>("persistent");
        QTest::addColumn<int>("rounds");
        QTest::newRow("reader-release") << false << 1;
        QTest::newRow("persistent-reader") << true << 1;
        QTest::newRow("repeated-reader-release") << false << 16;
    }

    // 日期：2026-11-06；原读者不共享删除，写方须有界等待；失败保持旧内容且清理临时文件。
    void privateAtomicWriteContention() {
        QFETCH(bool, persistent);
        QFETCH(int, rounds);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto path = temporary.filePath("private/policy.json");
        const auto native = QDir::toNativeSeparators(path);
        store.write("policy.json", "original-state");
        DWORD before = 0;
        QVERIFY(GetProcessHandleCount(GetCurrentProcess(), &before));
        QByteArray previous("original-state");
        for (int index = 0; index < rounds; ++index) {
            const auto handle = CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), GENERIC_READ,
                                            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                                            OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            QVERIFY(handle != INVALID_HANDLE_VALUE);
            std::atomic_bool closed{false};
            std::thread release;
            if (!persistent)
                release = std::thread([&]() {
                    // 日期：2026-11-06；只释放本测试的读句柄，不用事件循环或修改生产超时门槛。
                    QThread::msleep(80);
                    closed.store(CloseHandle(handle));
                });
            dukto::ExitCode code = dukto::ExitCode::Success;
            QString stage;
            std::exception_ptr unexpected;
            QElapsedTimer elapsed;
            elapsed.start();
            const auto replacement = QByteArray("replacement-") + QByteArray::number(index);
            try {
                store.write("policy.json", replacement);
            } catch (const dukto::Error &error) {
                code = error.code;
                stage = error.stage;
            } catch (...) {
                unexpected = std::current_exception();
            }
            const auto milliseconds = elapsed.elapsed();
            if (release.joinable())
                release.join();
            else
                closed.store(CloseHandle(handle));
            QVERIFY(closed.load());
            QVERIFY(!unexpected);
            QVERIFY2(milliseconds < 3000, qPrintable(QString::number(milliseconds)));
            if (persistent) {
                QCOMPARE(code, dukto::ExitCode::Disk);
                QCOMPARE(stage, QString("identity-busy"));
                QVERIFY(milliseconds >= 450);
                QCOMPARE(store.read("policy.json"), previous);
                store.write("policy.json", replacement);
            } else {
                QCOMPARE(code, dukto::ExitCode::Success);
                QVERIFY(milliseconds >= 50);
            }
            QCOMPARE(store.read("policy.json"), replacement);
            QCOMPARE(
                QDir(store.directory()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(),
                0);
            previous = replacement;
        }
        DWORD after = 0;
        QVERIFY(GetProcessHandleCount(GetCurrentProcess(), &after));
        QVERIFY2(after <= before + 2,
                 qPrintable(QString("handles %1 -> %2").arg(before).arg(after)));
    }
#endif
    // 日期：2026-11-05；共享SQLite文件可并发原地写入，原生对象/权限核验不得把内容更新误报为替换。
    void privateMutableFileValidation() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        store.write("mutable.sqlite", "fixed-size");
        const auto path = temporary.filePath("private/mutable.sqlite");
        std::atomic_bool stop{false};
        std::atomic_bool ready{false};
        std::atomic_bool failed{false};
        std::atomic_int writes{0};
        std::thread writer([&]() {
            // 日期：2026-11-05；固定大小单字节更新反复推进mtime/ctime，不改变文件类型、归属或原生对象。
            QFile file(path);
            if (!file.open(QIODevice::ReadWrite)) {
                failed.store(true);
                ready.store(true);
                return;
            }
            char value = 'a';
            ready.store(true);
            while (!stop.load()) {
                if (!file.seek(0) || file.write(&value, 1) != 1 || !file.flush()) {
                    failed.store(true);
                    return;
                }
                value = value == 'a' ? 'b' : 'a';
                ++writes;
                QThread::yieldCurrentThread();
            }
        });
        QElapsedTimer startup;
        startup.start();
        while (!ready.load() && startup.elapsed() < 2000)
            QThread::msleep(1);
        const bool started = ready.load();
        std::exception_ptr failure;
        try {
            if (started && !failed.load())
                for (int index = 0; index < 1000; ++index)
                    if (store.validateFile("mutable.sqlite") != 10)
                        throw std::runtime_error("Mutable file size differs");
        } catch (...) {
            failure = std::current_exception();
        }
        stop.store(true);
        writer.join();
        QVERIFY(started);
        QVERIFY(!failed.load());
        QVERIFY(writes.load() > 0);
        if (failure) {
            try {
                std::rethrow_exception(failure);
            } catch (const std::exception &error) {
                QFAIL(error.what());
            }
        }
    }

    // 日期：2026-11-04；原生源读取固定普通文件；Windows 拒绝替换，POSIX
    // 替换后仍读原对象并拒绝成功。
    void sourceObjectPinned() {
        QTemporaryDir root;
        const auto path = root.filePath("source.bin");
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("original"), qint64(8));
        file.close();
        {
            dukto::SourceFile source(path);
            QCOMPARE(source.device().readAll(), QByteArray("original"));
            source.verify();
#ifdef Q_OS_WIN
            QVERIFY(!QFile::rename(path, root.filePath("moved.bin")));
#else
            QVERIFY(QFile::rename(path, root.filePath("moved.bin")));
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write("replaced"), qint64(8));
            file.close();
            QVERIFY(source.device().seek(0));
            QCOMPARE(source.device().readAll(), QByteArray("original"));
            QVERIFY_EXCEPTION_THROWN(source.verify(), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(source.verifyObject(), dukto::Error);
#endif
        }
        QVERIFY(QFile::remove(path));
        QVERIFY_EXCEPTION_THROWN(dukto::SourceFile directory(root.path()), dukto::Error);
    }
    // 日期：2026-11-04；持有源句柄时另一写入者改变大小，验证不得把已变化的源报告为完整成功。
    void sourceMutationRejected() {
        QTemporaryDir root;
        const auto path = root.filePath("source.bin");
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("before"), qint64(6));
        file.close();
        dukto::SourceFile source(path);
        QVERIFY(file.open(QIODevice::Append));
        QCOMPARE(file.write("after"), qint64(5));
        file.close();
        source.verifyObject();
        QVERIFY_EXCEPTION_THROWN(source.verify(), dukto::Error);
    }
#ifndef Q_OS_WIN
    // 日期：2026-11-06；元数据核验不跟随最后链接，非法名字不能越出固定父目录。
    void posixFileInformationRejectsUnsafeNames() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QFile ordinary(root.filePath("ordinary"));
        QVERIFY(ordinary.open(QIODevice::WriteOnly));
        QCOMPARE(ordinary.write("ordinary"), qint64(8));
        ordinary.close();
        dukto::PosixDirectory directory(root.path(), false);
        const auto observed = directory.fileInformation("ordinary");
        struct stat expected;
        QVERIFY(::lstat(QFile::encodeName(root.filePath("ordinary")).constData(), &expected) == 0);
        QCOMPARE(qulonglong(observed.st_ino), qulonglong(expected.st_ino));
        QCOMPARE(qulonglong(observed.st_dev), qulonglong(expected.st_dev));
        QCOMPARE(qlonglong(observed.st_size), qlonglong(8));
        for (const auto &name :
             {QString(), QString("."), QString(".."), QString("../ordinary"),
              QString("ordinary/child"), QString("/ordinary"), QString(1, QChar::Null)})
            QVERIFY_EXCEPTION_THROWN(directory.fileInformation(name), dukto::Error);
        QVERIFY(::symlink("ordinary", QFile::encodeName(root.filePath("link")).constData()) == 0);
        QVERIFY(::mkfifo(QFile::encodeName(root.filePath("fifo")).constData(), 0600) == 0);
        QVERIFY(QDir().mkdir(root.filePath("child")));
        for (const auto &name : {"link", "fifo", "child", "absent"})
            QVERIFY_EXCEPTION_THROWN(directory.fileInformation(name), dukto::Error);
        const auto moved = root.path() + "-moved";
        QVERIFY(QDir().rename(root.path(), moved));
        QVERIFY(QDir().mkdir(root.path()));
        bool rejected = false;
        try {
            directory.fileInformation("ordinary");
        } catch (const dukto::Error &error) {
            rejected = error.code == dukto::ExitCode::Permission && error.stage == "path";
        }
        // 日期：2026-11-06；先恢复夹具目录再断言，避免测试失败留下临时目录。
        QVERIFY(QDir().rmdir(root.path()));
        QVERIFY(QDir().rename(moved, root.path()));
        QVERIFY(rejected);
    }

    // 日期：2026-11-04；最后分量/父目录链接均拒绝，FIFO
    // 不能阻塞线程；父目录替换不重定向原句柄读取。
    void posixSafeSourcePaths() {
        QTemporaryDir root;
        const auto parent = root.filePath("parent");
        QVERIFY(QDir().mkdir(parent));
        QFile file(parent + "/source.bin");
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("held source"), qint64(11));
        file.close();
        const auto link = root.filePath("link");
        QVERIFY(::symlink(QFile::encodeName(parent).constData(),
                          QFile::encodeName(link).constData()) == 0);
        QVERIFY_EXCEPTION_THROWN(dukto::SourceFile indirect(link + "/source.bin"), dukto::Error);
        const auto fileLink = root.filePath("file-link");
        QVERIFY(::symlink(QFile::encodeName(parent + "/source.bin").constData(),
                          QFile::encodeName(fileLink).constData()) == 0);
        QVERIFY_EXCEPTION_THROWN(dukto::SourceFile indirect(fileLink), dukto::Error);
        const auto fifo = root.filePath("fifo");
        QVERIFY(::mkfifo(QFile::encodeName(fifo).constData(), 0600) == 0);
        QVERIFY_EXCEPTION_THROWN(dukto::SourceFile special(fifo), dukto::Error);
        dukto::SourceFile source(parent + "/source.bin");
        QVERIFY(QDir().rename(parent, root.filePath("moved")));
        QVERIFY(::symlink(QFile::encodeName(root.path()).constData(),
                          QFile::encodeName(parent).constData()) == 0);
        QCOMPARE(source.device().readAll(), QByteArray("held source"));
        QVERIFY_EXCEPTION_THROWN(source.verify(), dukto::Error);
    }
#endif
    // 日期：2026-11-05；真实盘预检拒绝超额声明；耗尽缓存使用饱和计量，避免两次查盘间外部写入竞争。
    void storageSpacePreflight() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        dukto::checkStorageSpace(root.path(), 0);
        QVERIFY_EXCEPTION_THROWN(
            dukto::checkStorageSpace(root.path(), std::numeric_limits<qint64>::max()),
            dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::checkStorageSpace(root.path(), -1), dukto::Error);
        dukto::StorageChecks storage;
        storage.check(root.path(), 0);
        storage.consumed(root.path(), std::numeric_limits<qint64>::max());
        QVERIFY_EXCEPTION_THROWN(storage.check(root.path(), 1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(storage.consumed(root.path(), -1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(storage.consumed(root.filePath("unchecked"), 1), dukto::Error);
    }
#ifdef Q_OS_WIN
    // 日期：2026-11-04；接收文件存在期间父目录不能被改名替换；任务析构后正常归还权限。
    void windowsParentDirectoryPinned() {
        QTemporaryDir root;
        const auto parent = root.filePath(QStringLiteral("父目录/child"));
        {
            dukto::IncomingFile incoming(parent + "/payload.bin");
            QVERIFY(
                !QDir().rename(root.filePath(QStringLiteral("父目录")), root.filePath("moved")));
            dukto::writeAll(incoming.device(), "pinned directory payload");
            QCOMPARE(incoming.commit(), parent + "/payload.bin");
            QVERIFY(!QDir().rename(parent, root.filePath("child-moved")));
        }
        QVERIFY(QDir().rename(root.filePath(QStringLiteral("父目录")), root.filePath("moved")));
    }
#endif
    // 日期：2026-11-04；POSIX 父目录改名并替换为外部符号链接后，提交拒绝且只清理原目录临时项。
#ifndef Q_OS_WIN
    void posixDirectoryReplacementRejected() {
        QTemporaryDir root;
        const auto parent = root.filePath("parent");
        const auto moved = root.filePath("moved");
        const auto outside = root.filePath("outside");
        QVERIFY(QDir().mkpath(outside));
        {
            dukto::IncomingFile incoming(parent + "/payload.bin");
            dukto::writeAll(incoming.device(), "before directory replacement");
            QVERIFY(QDir().rename(parent, moved));
            QVERIFY(::symlink(QFile::encodeName(outside).constData(),
                              QFile::encodeName(parent).constData()) == 0);
            dukto::writeAll(incoming.device(), "after directory replacement");
            QVERIFY_EXCEPTION_THROWN(incoming.commit(), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(dukto::IncomingFile redirected(parent + "/other.bin"),
                                     dukto::Error);
        }
        QCOMPARE(QDir(outside).entryList(QDir::Files | QDir::Hidden).size(), 0);
        QCOMPARE(QDir(moved).entryList(QDir::Files | QDir::Hidden).size(), 0);
    }
#endif
    // 日期：2026-11-04；第二连接不能抢占存活任务；所有者离开且未完成时必须显示中断未知。
    void catalogOwnershipAndInterruptedState() {
        QTemporaryDir root;
        const auto path = root.filePath("receipts.sqlite");
        QString task;
        {
            dukto::Catalog owner(path);
            task = owner.begin(100, 1, "127.0.0.1");
            dukto::Catalog observer(path);
            QCOMPARE(observer.task(task)["state"].toString(), QString("receiving"));
            QVERIFY_EXCEPTION_THROWN(observer.finish(task, "completed", 100), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(owner.begin(1, 1, "other"), dukto::Error);
        }
        dukto::Catalog restarted(path);
        QCOMPARE(restarted.task(task)["state"].toString(), QString("interrupted"));
        QVERIFY(restarted.task(task)["message"].toString().contains(QStringLiteral("未知")));
        const auto next = restarted.begin(0, 1, "new");
        restarted.finish(next, "completed", 0);
        QCOMPARE(restarted.task(next)["state"].toString(), QString("completed"));
    }

    // 日期：2026-11-04；明细分页覆盖事务边界，构造失败不能遗留 Qt 全局数据库连接。
    void catalogPersistenceAndPages() {
        QTemporaryDir root;
        QString task;
        const auto path = root.filePath("receipts.sqlite");
        {
            dukto::Catalog catalog(path);
            task = catalog.begin(260, 260, "127.0.0.1");
            for (int index = 1; index <= 260; ++index)
                catalog.append(task, index, QString::number(index),
                               root.filePath(QString::number(index)), 1, QByteArray(32, 'a'));
            catalog.finish(task, "completed", 260);
        }
        {
            dukto::Catalog catalog(path);
            QCOMPARE(catalog.task(task)["state"].toString(), QString("completed"));
            QCOMPARE(catalog.page(task).size(), 100);
            QCOMPARE(catalog.page(task, 100).first().toObject()["sequence"].toString(),
                     QString("101"));
            QCOMPARE(catalog.page(task, 200).size(), 60);
            QVERIFY(catalog.page(task, 300).isEmpty());
            QVERIFY_EXCEPTION_THROWN(catalog.task("missing"), dukto::Error);
        }
        const auto connections = QSqlDatabase::connectionNames().size();
        QVERIFY_EXCEPTION_THROWN(dukto::Catalog invalid(root.path()), dukto::Error);
        QCOMPARE(QSqlDatabase::connectionNames().size(), connections);
    }
    // 日期：2026-11-04；确认 IPv4/主机名/带括号 IPv6 和端口边界遵守相同解析规则。
    void endpointBoundaries() {
        QCOMPARE(dukto::parseEndpoint("host:123", 4644).port, quint16(123));
        QCOMPARE(dukto::parseEndpoint("[::1]:65535", 4644).host, QString("::1"));
        QCOMPARE(dukto::parseEndpoint("[::1]", 4644).port, quint16(4644));
        QCOMPARE(dukto::parseEndpoint("::1", 4644).host, QString("::1"));
        QCOMPARE(dukto::parseEndpoint("[fe80::1%12]:4644", 1).host, QString("fe80::1%12"));
        for (const auto &invalid :
             QStringList{"", "bad name", "http://host", "[::1", "[host]", "host:0", "host:65536",
                         "host:", "[::1]:", "[::1]extra", "host:abc", "a/b", "a\\b"})
            QVERIFY_EXCEPTION_THROWN(dukto::parseEndpoint(invalid, 4644), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::parseEndpoint("host", -1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::parseEndpoint("host", 65536), dukto::Error);
    }
    // 日期：2026-11-04；验证网络路径不能穿越根目录或携带 Windows 保留名称。
    void rejectsUnsafePaths() {
        for (const auto &path : QStringList{"../x", "/x", "C:/x", "a//b", "a/./b", "a\\b",
                                            "NUL.txt", "a ", "a:stream"})
            QVERIFY_EXCEPTION_THROWN(dukto::validateRelativePath(path), dukto::Error);
        QCOMPARE(dukto::validateRelativePath(QStringLiteral("目录/hello.txt")),
                 QStringLiteral("目录/hello.txt"));
        for (const auto &invalid :
             {QString(QChar(0xd800)), QString(QChar(0xdc00)), QString("a") + QChar(0xd800) + "x"})
            QVERIFY_EXCEPTION_THROWN(dukto::validateRelativePath(invalid), dukto::Error);
        const auto supplementary =
            QStringLiteral("目录/") + QString::fromUtf8("\xF0\x9F\x93\x81.txt");
        QCOMPARE(dukto::validateRelativePath(supplementary), supplementary);
    }
    // 日期：2026-11-04；确认同名提交保留原文件，未提交临时数据自动清理。
    void atomicConflictAndCleanup() {
        QTemporaryDir root;
        const auto target = root.filePath("sample.txt");
        QFile original(target);
        QVERIFY(original.open(QIODevice::WriteOnly));
        original.write("old");
        original.close();
        {
            dukto::IncomingFile incoming(target);
            dukto::writeAll(incoming.device(), "new");
            QCOMPARE(incoming.commit(), root.filePath("sample (2).txt"));
        }
        QVERIFY(original.open(QIODevice::ReadOnly));
        QCOMPARE(original.readAll(), QByteArray("old"));
        {
            dukto::IncomingFile partial(root.filePath("cancelled.bin"));
            dukto::writeAll(partial.device(), "partial");
        }
        QVERIFY(!QFileInfo::exists(root.filePath("cancelled.bin")));
        QCOMPARE(QDir(root.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(), 0);
    }
#ifdef Q_OS_WIN
    // 日期：2026-11-06；真实ACL拒绝创建覆盖短暂解除及持续拒绝，不能把权限错误当作普通锁竞争。
    void reservationCreatePermission_data() {
        QTest::addColumn<bool>("release");
        QTest::newRow("short-denial") << true;
        QTest::newRow("persistent-denial") << false;
    }

    // 日期：2026-11-06；只改自有临时目录FILE_ADD_FILE权限，恢复原ACL后才执行任何结果断言。
    void reservationCreatePermission() {
        QFETCH(bool, release);
        QTemporaryDir root;
        const auto native = QDir::toNativeSeparators(root.path());
        DWORD needed = 0;
        GetFileSecurityW(reinterpret_cast<LPCWSTR>(native.utf16()), DACL_SECURITY_INFORMATION,
                         nullptr, 0, &needed);
        QVERIFY(needed > 0 && needed < 65536);
        QByteArray original(static_cast<int>(needed), 0);
        QVERIFY(GetFileSecurityW(reinterpret_cast<LPCWSTR>(native.utf16()),
                                 DACL_SECURITY_INFORMATION, original.data(), needed, &needed));
        SECURITY_DESCRIPTOR_CONTROL control = 0;
        DWORD revision = 0;
        QVERIFY(GetSecurityDescriptorControl(
            reinterpret_cast<PSECURITY_DESCRIPTOR>(original.data()), &control, &revision));
        const auto restore = [&]() {
            // 日期：2026-11-06；只恢复本测试保存的DACL，保留原继承保护位，不修改父目录。
            const auto flags =
                DACL_SECURITY_INFORMATION |
                ((control & SE_DACL_PROTECTED) ? PROTECTED_DACL_SECURITY_INFORMATION
                                               : UNPROTECTED_DACL_SECURITY_INFORMATION);
            return bool(SetFileSecurityW(reinterpret_cast<LPCWSTR>(native.utf16()), flags,
                                         reinterpret_cast<PSECURITY_DESCRIPTOR>(original.data())));
        };
        PSECURITY_DESCRIPTOR denied = nullptr;
        QVERIFY(ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"D:P(D;;0x2;;;WD)(A;;FA;;;WD)", SDDL_REVISION_1, &denied, nullptr));
        const bool applied = SetFileSecurityW(
            reinterpret_cast<LPCWSTR>(native.utf16()),
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION, denied);
        LocalFree(denied);
        QVERIFY(applied);
        bool restoredByWorker = !release;
        QThread *worker = nullptr;
        if (release) {
            worker = QThread::create([&]() {
                // 日期：2026-11-06；真实拒绝持续40ms，生产预约必须在固定总预算中等待解除。
                QThread::msleep(40);
                restoredByWorker = restore();
            });
            worker->start();
        }
        bool acquired = false;
        int code = 0;
        QString stage;
        QElapsedTimer elapsed;
        elapsed.start();
        try {
            dukto::TargetReservation reservation(root.filePath("permission.bin"));
            acquired = reservation.acquired();
        } catch (const dukto::Error &error) {
            code = static_cast<int>(error.code);
            stage = error.stage;
        } catch (...) {
            code = -1;
        }
        const auto duration = elapsed.elapsed();
        if (worker) {
            worker->wait();
            delete worker;
        }
        const bool restored = restore();
        QVERIFY(restored && restoredByWorker);
        if (release) {
            QVERIFY2(
                acquired,
                qPrintable(QString("code=%1 stage=%2 ms=%3").arg(code).arg(stage).arg(duration)));
            QCOMPARE(code, 0);
            QVERIFY(duration >= 30);
        } else {
            QVERIFY(!acquired);
            QCOMPARE(code, 5);
            QCOMPARE(stage, QString("conflict"));
            QVERIFY(duration >= 90);
        }
        QVERIFY(duration < 2000);
        dukto::TargetReservation healthy(root.filePath("permission.bin"));
        QVERIFY(healthy.acquired());
    }
#endif

    // 日期：2026-11-06；八个工作线程同时独占提交同名文件，各自内容及唯一名称必须保留。
    void concurrentExclusiveCommits() {
        QTemporaryDir root;
        const auto target = root.filePath(QStringLiteral("并发.txt"));
        std::array<QString, 8> paths;
        std::array<std::exception_ptr, 8> errors;
        std::array<QString, 8> phases;
        std::array<QThread *, 8> workers;
        for (int index = 0; index < 8; ++index) {
            workers[index] = QThread::create([&, index]() {
                // 日期：2026-11-06；线程内捕获异常，所有线程结束后由测试主线程报告失败。
                try {
                    phases[index] = "create";
                    dukto::IncomingFile incoming(target);
                    phases[index] = "write";
                    dukto::writeAll(incoming.device(), QByteArray::number(index));
                    phases[index] = "commit";
                    paths[index] = incoming.commit();
                    phases[index] = "duplicate-commit";
                    try {
                        incoming.commit();
                        throw std::runtime_error("duplicate commit unexpectedly succeeded");
                    } catch (const dukto::Error &) {
                    }
                } catch (...) {
                    errors[index] = std::current_exception();
                }
            });
            workers[index]->start();
        }
        for (auto worker : workers) {
            worker->wait();
            delete worker;
        }
        QStringList failures;
        for (int index = 0; index < 8; ++index) {
            if (!errors[index])
                continue;
            QString detail;
            try {
                std::rethrow_exception(errors[index]);
            } catch (const dukto::Error &error) {
                detail = QString("code=%1 stage=%2 message=%3")
                             .arg(static_cast<int>(error.code))
                             .arg(error.stage, error.message.left(1024));
            } catch (const std::exception &error) {
                detail = QString::fromUtf8(error.what()).left(1024);
            } catch (...) {
                detail = "unknown exception";
            }
            failures.append(QString("worker=%1 phase=%2 %3").arg(index).arg(phases[index], detail));
        }
        QVERIFY2(failures.isEmpty(), qPrintable(failures.join('\n')));
        QSet<QString> names;
        for (int index = 0; index < 8; ++index) {
            names.insert(paths[index]);
            QFile file(paths[index]);
            QVERIFY(file.open(QIODevice::ReadOnly));
            QCOMPARE(file.readAll(), QByteArray::number(index));
        }
        QCOMPARE(names.size(), 8);
        QCOMPARE(QDir(root.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(), 0);
    }
    // 日期：2026-11-04；目标分量超过文件系统上限时必须失败并清理临时数据，不能复制出半文件。
    void nativeCommitFailureCleansTemporary() {
        QTemporaryDir root;
        const auto target = root.filePath(QString(300, 'x'));
        {
            dukto::IncomingFile incoming(target);
            dukto::writeAll(incoming.device(), "complete data before failed commit");
            QVERIFY_EXCEPTION_THROWN(incoming.commit(), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(incoming.device(), dukto::Error);
        }
        QCOMPARE(QDir(root.path()).entryList(QDir::Files | QDir::Hidden).size(), 0);
    }
    // 日期：2026-11-04；注入实际短写/写入失败，确认不会忽略磁盘错误或错误重试。
    void shortWritesAndDiskFailures() {
        class Device final : public QIODevice {
          public:
            QByteArray received;
            bool fail = false;
            // 日期：2026-11-04；模拟每次至多写入两个字节的设备。
            qint64 writeData(const char *data, qint64 count) override {
                if (fail) {
                    setErrorString(QStringLiteral("模拟磁盘满"));
                    return -1;
                }
                const auto bytes = qMin(qint64(2), count);
                received.append(data, static_cast<int>(bytes));
                return bytes;
            }
            // 日期：2026-11-04；本测试设备只用于写入。
            qint64 readData(char *, qint64) override {
                return -1;
            }
        } device;
        QVERIFY(device.open(QIODevice::WriteOnly));
        dukto::writeAll(device, "complete");
        QCOMPARE(device.received, QByteArray("complete"));
        device.fail = true;
        QVERIFY_EXCEPTION_THROWN(dukto::writeAll(device, "failed"), dukto::Error);
        QCOMPARE(device.received, QByteArray("complete"));
    }
    // 日期：2026-11-04；清单覆盖空目录、空文件与 Unicode 路径，不丢失零字节条目。
    void manifestRoundTrip() {
        QTemporaryDir root;
        QVERIFY(QDir(root.path()).mkpath(QStringLiteral("目录/empty")));
        QFile file(root.filePath(QStringLiteral("目录/zero")));
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.close();
        dukto::Manifest manifest;
        manifest.scan({root.filePath(QStringLiteral("目录"))});
        QCOMPARE(manifest.count, qint64(3));
        QCOMPARE(manifest.totalBytes, qint64(0));
        dukto::Entry entry;
        int count = 0;
        while (manifest.next(entry)) {
            ++count;
            QVERIFY(!entry.relative.isEmpty());
        }
        QCOMPARE(count, 3);
    }
    // 日期：2026-11-04；来自不同父目录的同名树必须保留独立根，不能静默合并。
    void uniqueManifestRoots() {
        QTemporaryDir root;
        QVERIFY(QDir(root.path()).mkpath("a/tree/first"));
        QVERIFY(QDir(root.path()).mkpath("b/tree/second"));
        dukto::Manifest manifest;
        manifest.scan({root.filePath("a/tree"), root.filePath("b/tree")});
        QSet<QString> names;
        dukto::Entry entry;
        while (manifest.next(entry))
            names.insert(entry.relative);
        QCOMPARE(names, QSet<QString>({"tree", "tree/first", "tree (2)", "tree (2)/second"}));
    }
    // 日期：2026-11-05；真实 UDP 连锁消息仍允许定时器前进，畸形退出包不能删除已发现设备。
    void discoveryYieldsAndRejectsMalformedGoodbye() {
        QUdpSocket reservation;
        QVERIFY(reservation.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const auto port = reservation.localPort();
        reservation.close();
        dukto::Discovery discovery;
        QVERIFY(discovery.start(port, "bounded-discovery-test"));
        QUdpSocket sender;
        QVERIFY(sender.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const QByteArray hello = QByteArray(1, '\x02') + "yield-probe at station (Linux)";
        const auto present = [&]() {
            // 日期：2026-11-05；只检查本测试签名，不把真实网络上的其他设备计入断言。
            for (const auto &value : discovery.peers())
                if (value.toObject()["name"] == "yield-probe")
                    return true;
            return false;
        };
        sender.writeDatagram(hello, QHostAddress::LocalHost, port);
        QTRY_VERIFY(present());
        sender.writeDatagram(QByteArray(1, '\x03') + "invalid-body", QHostAddress::LocalHost, port);
        QTest::qWait(20);
        QVERIFY(present());
        int changes = 0;
        int observedAtTimer = -1;
        bool previous = true;
        connect(&discovery, &dukto::Discovery::changed, this, [&]() {
            // 日期：2026-11-05；每个变更立即递交下一真实数据包，模拟持续有新消息的接收队列。
            const auto current = present();
            if (current == previous)
                return;
            previous = current;
            ++changes;
            if (changes == 1)
                QTimer::singleShot(0, &discovery, [&]() {
                    // 日期：2026-11-05；计时器应在连锁完全排空之前被事件循环处理。
                    observedAtTimer = changes;
                });
            if (changes < 5000)
                sender.writeDatagram(current ? QByteArray(1, '\x03') : hello,
                                     QHostAddress::LocalHost, port);
        });
        sender.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_VERIFY_WITH_TIMEOUT(observedAtTimer >= 0, 5000);
        QVERIFY(observedAtTimer < 5000);
        QTRY_COMPARE_WITH_TIMEOUT(changes, 5000, 10000);
    }

    // 日期：2026-11-04；用两个真实 UDP 地址模拟多网卡，退出其中一张网卡不能删除整台设备。
    void discoveryAggregatesAddresses() {
        QUdpSocket reserve;
        QVERIFY(reserve.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const auto port = reserve.localPort();
        reserve.close();
        dukto::Discovery discovery;
        QVERIFY(discovery.start(port, "test-self"));
        QUdpSocket first;
        QUdpSocket second;
        QVERIFY(first.bind(QHostAddress("127.0.0.1"), 0));
        QVERIFY(second.bind(QHostAddress("127.0.0.2"), 0));
        const QByteArray hello = QByteArray(1, '\x02') + "test at station (Linux)";
        first.writeDatagram(hello, QHostAddress::LocalHost, port);
        second.writeDatagram(hello, QHostAddress::LocalHost, port);
        // 日期：2026-11-04；真实局域网可能同时回包，仅检查此测试签名，避免环境干扰。
        const auto peer = [&discovery]() {
            for (const auto &value : discovery.peers())
                if (value.toObject()["name"] == "test")
                    return value.toObject();
            return QJsonObject();
        };
        QTRY_COMPARE(peer()["addresses"].toArray().size(), 2);
        first.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_COMPARE(peer()["addresses"].toArray().size(), 1);
        QCOMPARE(peer()["address"].toString(), QString("127.0.0.2"));
        second.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_VERIFY(peer().isEmpty());
    }
    // 日期：2026-11-04；取消等待数据的接收任务，清理临时文件后仍可接受下一连接。
    void cancelReceiveReleasesResources() {
        QTemporaryDir root;
        dukto::LegacyListener listener(root.path(), 5000, nullptr,
                                       root.filePath("receipts.sqlite"));
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&listener, &dukto::LegacyListener::result);
        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
        QVERIFY(client.waitForConnected(2000));
        // 日期：2026-11-04；独立构造一项超长声明，仅发送少量内容后触发取消。
        const auto number = [](qint64 value) {
            QByteArray bytes(8, '\0');
            qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
            return bytes;
        };
        client.write(number(1) + number(1024 * 1024) + QByteArray("cancel.bin\0", 11) +
                     number(1024 * 1024) + "partial");
        client.flush();
        QTRY_VERIFY(!QDir(root.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
        listener.cancel();
        QTRY_COMPARE(result.count(), 1);
        QCOMPARE(result[0][0].toInt(), static_cast<int>(dukto::ExitCode::Cancelled));
        QTRY_VERIFY(QDir(root.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
        QVERIFY(!QFileInfo::exists(root.filePath("cancel.bin")));
        client.abort();
        QTest::qWait(50);
        QTcpSocket next;
        next.connectToHost(QHostAddress::LocalHost, listener.serverPort());
        QVERIFY(next.waitForConnected(2000));
        next.write(number(1) + number(0) + QByteArray("after.bin\0", 10) + number(0));
        next.flush();
        QTRY_COMPARE(result.count(), 2);
        QCOMPARE(result[1][0].toInt(), 0);
        QVERIFY(QFileInfo::exists(root.filePath("after.bin")));
    }
};
QTEST_GUILESS_MAIN(CoreTests)
#include "core_tests.moc"

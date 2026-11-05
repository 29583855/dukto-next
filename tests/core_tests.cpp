#include "core/catalog.h"
#include "core/discovery.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/files.h"
#include "core/legacy.h"
#include "core/manifest.h"
#include "core/privatestore.h"
#include "core/sourcefile.h"

#include <QDir>
#include <QFile>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <QtEndian>
#include <QtTest>
#include <array>
#include <exception>
#include <limits>
#include <stdexcept>
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

class CoreTests final : public QObject {
    Q_OBJECT
  private slots:
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
        QVERIFY_EXCEPTION_THROWN(source.verify(), dukto::Error);
    }
#ifndef Q_OS_WIN
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
    // 日期：2026-11-04；八个工作线程同时独占提交同名文件，各自内容及唯一名称必须保留。
    void concurrentExclusiveCommits() {
        QTemporaryDir root;
        const auto target = root.filePath(QStringLiteral("并发.txt"));
        std::array<QString, 8> paths;
        std::array<std::exception_ptr, 8> errors;
        std::array<QThread *, 8> workers;
        for (int index = 0; index < 8; ++index) {
            workers[index] = QThread::create([&, index]() {
                // 日期：2026-11-04；线程内捕获异常，所有线程结束后由测试主线程报告失败。
                try {
                    dukto::IncomingFile incoming(target);
                    dukto::writeAll(incoming.device(), QByteArray::number(index));
                    paths[index] = incoming.commit();
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
        QSet<QString> names;
        for (int index = 0; index < 8; ++index) {
            QVERIFY(!errors[index]);
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

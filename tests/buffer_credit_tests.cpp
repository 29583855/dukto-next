#include "core/buffercredit.h"
#include "core/error.h"
#include "core/filecredit.h"
#include "core/files.h"
#include "core/legacy.h"
#include "core/service.h"
#include "core/sourcefile.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QSemaphore>
#include <QSqlDatabase>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <QtEndian>
#include <QtTest>
#include <atomic>
#include <memory>
#include <vector>

class BufferCreditTests final : public QObject {
    Q_OBJECT
  private slots:

    // 日期：2026-11-06；结果仍排队或由接收者保留时，工作线程退出及复制/删除中间值都不能提前归还。
    void legacyTextResultKeepsCreditUntilLastOwner() {
        QTemporaryDir root;
        dukto::LegacyListener listener(root.path(), 3000, nullptr,
                                       root.filePath("receipts.sqlite"));
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy results(&listener, &dukto::LegacyListener::result);
        const QByteArray body(1024 * 1024, 'x');
        const auto charge = qint64(body.size()) * 10 + 64 * 1024;
        for (int attempt = 0; attempt < 2; ++attempt) {
            QTcpSocket client;
            client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
            QVERIFY(client.waitForConnected(2000));
            QByteArray frame(16, '\0');
            qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(frame.data()));
            qToLittleEndian<qint64>(body.size(), reinterpret_cast<uchar *>(frame.data() + 8));
            frame.append("___DUKTO___TEXT___\0", 19);
            QByteArray size(8, '\0');
            qToLittleEndian<qint64>(body.size(), reinterpret_cast<uchar *>(size.data()));
            frame += size + body;
            QCOMPARE(client.write(frame), qint64(frame.size()));
            client.flush();
            QTRY_COMPARE_WITH_TIMEOUT(results.size(), attempt + 1, 5000);
            QTRY_VERIFY_WITH_TIMEOUT(listener.setOutput(root.path()), 3000);
            QCOMPARE(results.last()[0].toInt(), 0);
            const auto owned = results.last()[1].value<dukto::LegacyResult>();
            QCOMPARE(owned.json()["text"].toString().toUtf8(), body);
            QVERIFY(owned.textCredit());
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                     QString::number(charge * (attempt + 1)));
        }
        auto last = results[0][1].value<dukto::LegacyResult>();
        results.clear();
        QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), QString::number(charge));
        last = dukto::LegacyResult();
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-06；文本发送准入在启动线程前，满额保持原数据/计数且不能绕用控制保留额。
    void legacyTextSenderRejectsBeforeThreadStart() {
        dukto::BufferCredit saturated(120 * 1024 * 1024, true);
        dukto::LegacyRequest request;
        request.host = "127.0.0.1";
        request.textMode = true;
        request.text = "text-must-not-be-sent";
        bool rejected = false;
        try {
            dukto::LegacyJob job(request);
        } catch (const dukto::Error &error) {
            rejected = error.code == dukto::ExitCode::Permission && error.stage == "budget";
        }
        QVERIFY(rejected);
        QCOMPARE(request.text, QByteArray("text-must-not-be-sent"));
        QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                 QString::number(120 * 1024 * 1024));
    }

    // 日期：2026-11-06；声明的文本在首个正文分配前因共享额度拒绝，错误结果不保留无正文的授信。
    void legacyTextReceiverRejectsBeforeBody() {
        QTemporaryDir root;
        dukto::LegacyListener listener(root.path(), 3000, nullptr,
                                       root.filePath("receipts.sqlite"));
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy results(&listener, &dukto::LegacyListener::result);
        {
            dukto::BufferCredit saturated(110 * 1024 * 1024, true);
            QTcpSocket client;
            client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
            QVERIFY(client.waitForConnected(2000));
            QByteArray header(16, '\0');
            qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(header.data()));
            qToLittleEndian<qint64>(2 * 1024 * 1024, reinterpret_cast<uchar *>(header.data() + 8));
            header.append("___DUKTO___TEXT___\0", 19);
            QByteArray size(8, '\0');
            qToLittleEndian<qint64>(2 * 1024 * 1024, reinterpret_cast<uchar *>(size.data()));
            header += size;
            QCOMPARE(client.write(header), qint64(header.size()));
            client.flush();
            QTRY_COMPARE_WITH_TIMEOUT(results.size(), 1, 4000);
            QTRY_VERIFY_WITH_TIMEOUT(listener.setOutput(root.path()), 3000);
            QCOMPARE(results[0][0].toInt(), 4);
            const auto result = results[0][1].value<dukto::LegacyResult>();
            QCOMPARE(result.json()["stage"].toString(), QString("budget"));
            QVERIFY(!result.json().contains("text"));
            QVERIFY(!result.textCredit());
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                     QString::number(110 * 1024 * 1024));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }
    // 日期：2026-11-06；真实源和R6临时文件共享32额度；饱和不创建目录，私有状态仍可读，失败归还。
    void dataFilesShareAdmissionAndKeepPrivateReads() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        const auto path = root.filePath("source.bin");
        QFile fixture(path);
        QVERIFY(fixture.open(QIODevice::WriteOnly));
        QCOMPARE(fixture.write("source"), qint64(6));
        fixture.close();
        dukto::PrivateStore store(root.filePath("private"), true);
        store.write("config.json", "private-config");
        {
            std::vector<std::unique_ptr<dukto::SourceFile>> sources;
            std::vector<std::unique_ptr<dukto::IncomingFile>> incoming;
            for (int index = 0; index < 16; ++index) {
                sources.emplace_back(new dukto::SourceFile(path));
                incoming.emplace_back(new dukto::IncomingFile(root.filePath("target.bin")));
            }
            QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 32);
            bool rejected = false;
            try {
                dukto::SourceFile overflow(root.filePath("missing/source.bin"));
            } catch (const dukto::Error &error) {
                rejected =
                    error.code == dukto::ExitCode::Permission && error.stage == "file-budget";
            }
            QVERIFY(rejected);
            QVERIFY_EXCEPTION_THROWN(
                dukto::IncomingFile overflow(root.filePath("missing/target.bin")), dukto::Error);
            QVERIFY(!QFileInfo::exists(root.filePath("missing")));
            QCOMPARE(store.read("config.json"), QByteArray("private-config"));
            for (const auto &source : sources) {
                source->verify();
                source->verifyObject();
            }
#ifdef Q_OS_WIN
            QVERIFY_EXCEPTION_THROWN(
                dukto::replaceReceivedFile(path, root.filePath("replacement.bin"), "expected-id"),
                dukto::Error);
            QVERIFY(!QFileInfo::exists(root.filePath("replacement.bin")));
#endif
            QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 32);
            incoming.pop_back();
            QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 31);
            // 日期：2026-11-06；已取得令牌后真实打开失败也必须精确归还，不能吃掉最后一个名额。
            QVERIFY_EXCEPTION_THROWN(dukto::SourceFile missing(root.filePath("absent.bin")),
                                     dukto::Error);
            QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 31);
            dukto::SourceFile reused(path);
            QCOMPARE(reused.device().readAll(), QByteArray("source"));
            QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 32);
        }
        QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 0);
        QCOMPARE(QDir(root.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(), 0);
        QCOMPARE(dukto::hashFile(path),
                 QCryptographicHash::hash("source", QCryptographicHash::Sha256));
    }

    // 日期：2026-11-06；64线程同时竞争且持有到全部准入完成，验证32上限及异常归还而不依赖执行顺序。
    void concurrentDataFileAdmission() {
        QSemaphore arrived, release;
        std::atomic_int admitted{0}, rejected{0};
        QList<QThread *> workers;
        for (int index = 0; index < 64; ++index) {
            // 日期：2026-11-06；所有成功令牌保持到主线程观察，异常分类另记，线程不调用QtTest断言。
            auto worker = QThread::create([&]() {
                std::unique_ptr<dukto::DataFileCredit> credit;
                try {
                    credit.reset(new dukto::DataFileCredit);
                    ++admitted;
                } catch (const dukto::Error &error) {
                    if (error.code == dukto::ExitCode::Permission && error.stage == "file-budget")
                        ++rejected;
                }
                arrived.release();
                release.acquire();
            });
            workers.append(worker);
            worker->start();
        }
        const bool ready = arrived.tryAcquire(64, 10000);
        const auto usage = dukto::DataFileCredit::usage();
        release.release(64);
        for (auto worker : workers) {
            worker->wait();
            delete worker;
        }
        QVERIFY(ready);
        QCOMPARE(admitted.load(), 32);
        QCOMPARE(rejected.load(), 32);
        QCOMPARE(usage["used"].toInt(), 32);
        QCOMPARE(usage["peak"].toInt(), 32);
        QCOMPARE(dukto::DataFileCredit::usage()["used"].toInt(), 0);
    }

    // 日期：2026-11-06；R6发送在扫描和连接前取得共享数据额度，满额拒绝不占控制保留额。
    void legacySenderRespectsSharedSaturation() {
        {
            dukto::BufferCredit saturated(120 * 1024 * 1024, true);
            dukto::LegacyRequest request;
            request.host = "127.0.0.1";
            request.paths = QStringList{"missing-source-must-not-be-scanned"};
            dukto::LegacyJob job(request);
            QSignalSpy results(&job, &dukto::LegacyJob::result);
            job.start();
            QTRY_COMPARE_WITH_TIMEOUT(results.size(), 1, 3000);
            QVERIFY(job.wait(3000));
            QCOMPARE(results[0][0].toInt(), 4);
            QCOMPARE(results[0][1].value<dukto::LegacyResult>().json()["stage"].toString(),
                     QString("budget"));
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                     QString::number(120 * 1024 * 1024));
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(), QString("0"));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-06；分别耗尽socket、历史库和映射库额度，覆盖不同构造失败位置的真实接收。
    void legacyReceiverSaturation_data() {
        QTest::addColumn<int>("occupiedMiB");
        QTest::newRow("socket") << 120;
        QTest::newRow("catalog") << 118;
        QTest::newRow("mapping") << 115;
    }

    // 日期：2026-11-06；连续拒绝必须断开已接管的描述符、清空连接和授信，归还后同监听器仍可接收。
    void legacyReceiverSaturation() {
        QFETCH(int, occupiedMiB);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        dukto::LegacyListener listener(temporary.path(), 3000, nullptr,
                                       temporary.filePath("receipts.sqlite"));
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy results(&listener, &dukto::LegacyListener::result);
        auto baseline = QSqlDatabase::connectionNames();
        baseline.sort();
        {
            dukto::BufferCredit saturated(qint64(occupiedMiB) * 1024 * 1024, true);
            for (int attempt = 0; attempt < 12; ++attempt) {
                QTcpSocket client;
                client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
                QVERIFY(client.waitForConnected(2000));
                if (occupiedMiB < 120) {
                    QByteArray header(16, '\0');
                    qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(header.data()));
                    qToLittleEndian<qint64>(0, reinterpret_cast<uchar *>(header.data() + 8));
                    QCOMPARE(client.write(header), qint64(header.size()));
                    client.flush();
                }
                QTRY_COMPARE_WITH_TIMEOUT(results.size(), attempt + 1, 4000);
                QTRY_VERIFY_WITH_TIMEOUT(client.state() == QAbstractSocket::UnconnectedState, 3000);
                QTRY_VERIFY_WITH_TIMEOUT(listener.setOutput(temporary.path()), 3000);
                QCOMPARE(results.last()[0].toInt(), 4);
                QCOMPARE(results.last()[1].value<dukto::LegacyResult>().json()["stage"].toString(),
                         QString("budget"));
                QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                         QString::number(qint64(occupiedMiB) * 1024 * 1024));
                auto names = QSqlDatabase::connectionNames();
                names.sort();
                QCOMPARE(names, baseline);
            }
            dukto::BufferCredit control(8 * 1024 * 1024);
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(),
                     QString::number(8 * 1024 * 1024));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
        QVERIFY(client.waitForConnected(2000));
        QByteArray frame(16, '\0');
        qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(frame.data()));
        frame.append("empty.bin\0", 10);
        frame.append(QByteArray(8, '\0'));
        QCOMPARE(client.write(frame), qint64(frame.size()));
        client.flush();
        QTRY_COMPARE_WITH_TIMEOUT(results.size(), 13, 5000);
        QTRY_VERIFY_WITH_TIMEOUT(listener.setOutput(temporary.path()), 3000);
        QCOMPARE(results.last()[0].toInt(), 0);
        QCOMPARE(QFileInfo(temporary.filePath("empty.bin")).size(), qint64(0));
        QVERIFY(QFileInfo::exists(temporary.filePath("empty.bin")));
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-06；实际暂停在文件正文前，观察socket及两个SQLite缓存的合计额度，取消后清零。
    void legacyReceiveCountsMappingAndReleasesOnCancel() {
        QTemporaryDir temporary;
        dukto::LegacyListener listener(temporary.path(), 5000, nullptr,
                                       temporary.filePath("receipts.sqlite"));
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy results(&listener, &dukto::LegacyListener::result);
        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, listener.serverPort());
        QVERIFY(client.waitForConnected(2000));
        QTRY_COMPARE_WITH_TIMEOUT(dukto::BufferCredit::usage()["used"].toString(),
                                  QString::number(2 * 1024 * 1024), 3000);
        QByteArray frame(16, '\0');
        qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(frame.data()));
        qToLittleEndian<qint64>(1024, reinterpret_cast<uchar *>(frame.data() + 8));
        frame.append("pending.bin\0", 12);
        QByteArray size(8, '\0');
        qToLittleEndian<qint64>(1024, reinterpret_cast<uchar *>(size.data()));
        frame.append(size);
        QCOMPARE(client.write(frame), qint64(frame.size()));
        client.flush();
        QTRY_COMPARE_WITH_TIMEOUT(dukto::BufferCredit::usage()["dataUsed"].toString(),
                                  QString::number(qint64(2048 + 2112 + 2112) * 1024), 3000);
        QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(), QString("0"));
        listener.cancel();
        QTRY_COMPARE_WITH_TIMEOUT(results.size(), 1, 3000);
        QTRY_VERIFY_WITH_TIMEOUT(listener.setOutput(temporary.path()), 3000);
        QCOMPARE(results.last()[0].toInt(), 7);
        QVERIFY(!QFileInfo::exists(temporary.filePath("pending.bin")));
        QCOMPARE(QDir(temporary.path()).entryList({"*.part"}, QDir::Files | QDir::Hidden).size(),
                 0);
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-05；真实服务在缓冲满时重复拒绝连接并关闭 socket，归还后仍可配对与正常关闭。
    void saturatedServiceClosesUnclaimedSockets() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto identity = dukto::initializeIdentity(store, {"127.0.0.1"});
        dukto::ServiceListener listener(store.directory(), 2000);
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QSignalSpy events(&listener, &dukto::ServiceListener::event);
        {
            dukto::BufferCredit saturated(128 * 1024 * 1024);
            for (int attempt = 0; attempt < 24; ++attempt) {
                QTcpSocket socket;
                socket.connectToHost(QHostAddress::LocalHost, listener.serverPort());
                QVERIFY(socket.waitForConnected(2000));
                QTRY_VERIFY_WITH_TIMEOUT(events.size() == attempt + 1, 3000);
                QTRY_VERIFY_WITH_TIMEOUT(socket.state() == QAbstractSocket::UnconnectedState, 3000);
                const auto event = events.last().at(0).toJsonObject();
                QCOMPARE(event["stage"].toString(), QString("budget"));
                QCOMPARE(event["code"].toInt(), 4);
            }
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        const auto offer = dukto::AuthStore(store).issue({{"docs", true, false, false}});
        dukto::PrivateStore clients(temporary.filePath("clients"), true);
        auto profile =
            dukto::prepareProfile(clients, "test", "127.0.0.1", listener.serverPort(), "127.0.0.1",
                                  identity.certificate.digest(QCryptographicHash::Sha256));
        dukto::RemoteClient remote(profile, 3000);
        QVERIFY(!remote.pair(offer.credential).client.isNull());
        remote.close();
        listener.stop();
    }

    // 日期：2026-11-05；先保留控制再取得数据不会少算额度；转类失败和重复调用均维持精确计数。
    void classificationAndReservationOrder() {
        {
            dukto::BufferCredit control(8 * 1024 * 1024);
            dukto::BufferCredit data(120 * 1024 * 1024, true);
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                     QString::number(120 * 1024 * 1024));
            QVERIFY_EXCEPTION_THROWN(control.classifyAsData(), dukto::Error);
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(),
                     QString::number(8 * 1024 * 1024));
        }
        {
            dukto::BufferCredit tls(4 * 1024 * 1024);
            tls.classifyAsData();
            tls.classifyAsData();
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(),
                     QString::number(4 * 1024 * 1024));
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(),
                     QString::number(4 * 1024 * 1024));
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(), QString("0"));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), QString("0"));
    }

    // 日期：2026-11-04；异常路径精确归还，数据流不能拿走控制保留额，控制仍能取得最后额度。
    void reservationAndUnwind() {
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        {
            dukto::BufferCredit data(120 * 1024 * 1024, true);
            QVERIFY_EXCEPTION_THROWN(dukto::BufferCredit another(1, true), dukto::Error);
            dukto::BufferCredit control(8 * 1024 * 1024);
            QVERIFY_EXCEPTION_THROWN(dukto::BufferCredit overflow(1), dukto::Error);
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(),
                     QString::number(128 * 1024 * 1024));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        QVERIFY_EXCEPTION_THROWN(dukto::BufferCredit zero(0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::BufferCredit negative(-1), dukto::Error);
        try {
            dukto::BufferCredit data(64 * 1024 * 1024, true);
            throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
        } catch (const dukto::Error &) {
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-04；32 个真实工作线程同时竞争，最多 15 个数据额度且控制保留始终可分配。
    void concurrentAdmission() {
        QSemaphore arrived;
        QSemaphore release;
        std::atomic_int admitted{0};
        QList<QThread *> workers;
        for (int index = 0; index < 32; ++index) {
            auto worker = QThread::create([&]() {
                // 日期：2026-11-04；成功者持有额度直到主线程核对，无竞争者能靠提前释放掩盖超额。
                std::unique_ptr<dukto::BufferCredit> credit;
                try {
                    credit.reset(new dukto::BufferCredit(8 * 1024 * 1024, true));
                    ++admitted;
                } catch (const dukto::Error &) {
                }
                arrived.release();
                release.acquire();
            });
            workers.append(worker);
            worker->start();
        }
        const bool ready = arrived.tryAcquire(32, 10000);
        const auto usage = dukto::BufferCredit::usage();
        bool controlAdmitted = false;
        try {
            dukto::BufferCredit control(8 * 1024 * 1024);
            controlAdmitted = true;
        } catch (const dukto::Error &) {
        }
        release.release(32);
        for (auto worker : workers) {
            worker->wait();
            delete worker;
        }
        QVERIFY(ready);
        QCOMPARE(admitted.load(), 15);
        QCOMPARE(usage["used"].toString(), QString::number(120 * 1024 * 1024));
        QVERIFY(controlAdmitted);
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }
};

QTEST_GUILESS_MAIN(BufferCreditTests)
#include "buffer_credit_tests.moc"

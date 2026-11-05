#include "core/buffercredit.h"
#include "core/error.h"
#include "core/service.h"
#include <QCryptographicHash>
#include <QSemaphore>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <QtTest>
#include <atomic>
#include <memory>

class BufferCreditTests final : public QObject {
    Q_OBJECT
  private slots:
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

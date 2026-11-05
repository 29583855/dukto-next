#include "core/strongmanifest.h"
#include "core/transferoperation.h"
#include <QElapsedTimer>
#include <QFile>
#include <QTemporaryDir>
#include <QTimer>
#include <QtTest>
#include <vector>

class TransferOperationTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；严格范围及规范十进制，非法输入不能变成无限重试或无期限。
    void policyBounds() {
        QCOMPARE(dukto::checkedTransferPolicy("0", "1").retries, 0);
        QCOMPARE(dukto::checkedTransferPolicy("3", "604800").deadlineSeconds, 604800);
        for (const auto &value : {"-1", "4", "01", "+1", " 1", "1.0", "", "999999999999"})
            QVERIFY_EXCEPTION_THROWN(dukto::checkedTransferPolicy(value, "30"), dukto::Error);
        for (const auto &value : {"0", "604801", "01", "+1", " 1", "1.0", "", "999999999999"})
            QVERIFY_EXCEPTION_THROWN(dukto::checkedTransferPolicy("1", value), dukto::Error);
        const dukto::TransferPolicy invalid{4, 10};
        QVERIFY_EXCEPTION_THROWN(dukto::TransferOperation(invalid, nullptr), dukto::Error);
    }

    // 日期：2026-11-05；真实等待验证指数退避及跨阶段计数，不允许查询成功后重新获得三次预算。
    void sharedRetryBudget() {
        int attempts = 0;
        std::vector<QJsonObject> events;
        dukto::TransferOperation operation({3, 15}, nullptr, [&](const QJsonObject &event) {
            // 日期：2026-11-05；仅记录三个固定大小事件供断言，不模拟任何传输成功。
            events.push_back(event);
        });
        QElapsedTimer elapsed;
        elapsed.start();
        operation.run([&]() {
            // 日期：2026-11-05；第一阶段仅首次网络失败，成功后保留已消耗的计数。
            if (++attempts == 1)
                throw dukto::Error(dukto::ExitCode::Network, "test", "tls");
            return QJsonObject{};
        });
        try {
            operation.run([&]() -> QJsonObject {
                // 日期：2026-11-05；第二阶段持续断线，不能突破剩余两次重试。
                ++attempts;
                throw dukto::Error(dukto::ExitCode::Network, "test", "protocol");
            });
            QFAIL("unbounded failure accepted");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Network);
            QCOMPARE(error.stage, QString("protocol"));
        }
        QCOMPARE(attempts, 5);
        QCOMPARE(events.size(), std::size_t(3));
        for (int index = 0; index < 3; ++index) {
            QCOMPARE(events[index]["retry"].toInt(), index + 1);
            QCOMPARE(events[index]["delayMs"].toInt(), 250 * (1 << index));
            QCOMPARE(events[index]["maxRetries"].toInt(), 3);
        }
        QVERIFY(elapsed.elapsed() >= 1750);
    }

    // 日期：2026-11-05；重试状态携带同一任务/请求，拒绝另一个任务或请求污染 GUI 当前状态。
    void retryIdentity() {
        QJsonObject retry;
        dukto::TransferOperation operation({1, 10}, nullptr, [&](const QJsonObject &event) {
            // 日期：2026-11-05；只保存最后快照，与生产界面同样保持固定大小。
            retry = event;
        });
        const auto request = QUuid::createUuid();
        const auto task = QUuid::createUuid();
        operation.bindRequest(request);
        operation.report({{"taskId", task.toString(QUuid::WithoutBraces)},
                          {"requestId", request.toString(QUuid::WithoutBraces)},
                          {"state", "transferring"}});
        int attempts = 0;
        operation.run([&]() {
            // 日期：2026-11-05；首次断线后第二次成功，重试快照仍指向原任务。
            if (++attempts == 1)
                throw dukto::Error(dukto::ExitCode::Network, "test", "protocol");
            return QJsonObject{};
        });
        QCOMPARE(retry["state"].toString(), QString("retrying"));
        QCOMPARE(retry["taskId"].toString(), task.toString(QUuid::WithoutBraces));
        QCOMPARE(retry["requestId"].toString(), request.toString(QUuid::WithoutBraces));
        QVERIFY_EXCEPTION_THROWN(operation.bindRequest(QUuid::createUuid()), dukto::Error);
        const QJsonObject foreign{{"taskId", QUuid::createUuid().toString(QUuid::WithoutBraces)}};
        QVERIFY_EXCEPTION_THROWN(operation.report(foreign), dukto::Error);
    }

    // 日期：2026-11-05；配置、权限、磁盘、校验、运行异常、取消及显式期限失败均只有一次尝试。
    void permanentErrors() {
        for (auto code :
             {dukto::ExitCode::Runtime, dukto::ExitCode::Config, dukto::ExitCode::Permission,
              dukto::ExitCode::Disk, dukto::ExitCode::Integrity, dukto::ExitCode::Cancelled}) {
            dukto::TransferOperation operation({3, 10}, nullptr);
            int attempts = 0;
            QVERIFY_EXCEPTION_THROWN(operation.run([&]() -> QJsonObject {
                // 日期：2026-11-05；永久错误原样传播，不依据本地化说明文字猜测可恢复性。
                ++attempts;
                throw dukto::Error(code, "test", "transfer");
            }),
                                     dukto::Error);
            QCOMPARE(attempts, 1);
        }
        dukto::TransferOperation operation({3, 10}, nullptr);
        int attempts = 0;
        QVERIFY_EXCEPTION_THROWN(operation.run([&]() -> QJsonObject {
            // 日期：2026-11-05；总期限错误本身即使使用网络码也不得重试。
            ++attempts;
            throw dukto::Error(dukto::ExitCode::Network, "test", "deadline");
        }),
                                 dukto::Error);
        QCOMPARE(attempts, 1);
    }

    // 日期：2026-11-05；不运行 Qt 事件循环的本地工作也可观察总期限，底层取消规范化为 3/deadline。
    void deadlineWithoutEventLoop() {
        dukto::TransferOperation operation({3, 1}, nullptr);
        QElapsedTimer elapsed;
        elapsed.start();
        try {
            operation.run([&]() -> QJsonObject {
                // 日期：2026-11-05；按生产扫描的原子检查点等待，不用事件定时器触发期限。
                while (!operation.cancellation()->load())
                    std::this_thread::sleep_for(std::chrono::milliseconds(2));
                throw dukto::Error(dukto::ExitCode::Cancelled, "scan stopped", "manifest");
            });
            QFAIL("deadline not enforced");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Network);
            QCOMPARE(error.stage, QString("deadline"));
        }
        QVERIFY(elapsed.elapsed() >= 1000 && elapsed.elapsed() < 3000);
    }

    // 日期：2026-11-05；真实 StrongManifest 扫描的阻塞检查点返回后也遵守总期限，不启动网络或重扫。
    void deadlineDuringManifestScan() {
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        QFile source(directory.filePath("source.bin"));
        QVERIFY(source.open(QIODevice::WriteOnly));
        QCOMPARE(source.write(QByteArray(1024 * 1024, 's')), qint64(1024 * 1024));
        source.close();
        dukto::PrivateStore store(directory.filePath("state"), true);
        dukto::TemporaryManifest manifest(store);
        dukto::TransferOperation operation({3, 1}, nullptr);
        int checkpoints = 0;
        try {
            operation.run([&]() {
                // 日期：2026-11-05；只在测试的首个扫描检查点模拟慢文件系统，生产扫描和取消路径均实际执行。
                manifest.get().scan({source.fileName()}, operation.cancellation(), [&]() {
                    // 日期：2026-11-05；测试延迟固定且有界，后续扫描检查点必须看到监视线程的停止标志。
                    if (++checkpoints == 1)
                        std::this_thread::sleep_for(std::chrono::milliseconds(1100));
                });
                return QJsonObject{};
            });
            QFAIL("scan ignored total deadline");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Network);
            QCOMPARE(error.stage, QString("deadline"));
        }
        QCOMPARE(checkpoints, 1);
    }

    // 日期：2026-11-05；总期限包括全部退避，第三次退避未结束也必须退出，不重新开始预算。
    void deadlineDuringBackoff() {
        dukto::TransferOperation operation({3, 1}, nullptr);
        int attempts = 0;
        try {
            operation.run([&]() -> QJsonObject {
                // 日期：2026-11-05；持续网络失败，检查累计时间而非单次帧超时。
                ++attempts;
                throw dukto::Error(dukto::ExitCode::Network, "test", "tls");
            });
            QFAIL("deadline not enforced in backoff");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.stage, QString("deadline"));
        }
        QCOMPARE(attempts, 3);
    }

    // 日期：2026-11-05；退避仍处理主线程取消信号，监视线程及时合并并在析构立即归还。
    void cancellationAndCleanup() {
        std::atomic_bool cancel{false};
        QElapsedTimer elapsed;
        elapsed.start();
        {
            dukto::TransferOperation operation({3, 86400}, &cancel);
            int attempts = 0;
            QTimer::singleShot(25, [&]() {
                // 日期：2026-11-05；模拟 CLI 已收到信号后由 Qt 定时器写入的原子标志。
                cancel.store(true);
            });
            try {
                operation.run([&]() -> QJsonObject {
                    // 日期：2026-11-05；第一条网络错误进入退避后取消，不能再次发起连接。
                    ++attempts;
                    throw dukto::Error(dukto::ExitCode::Network, "test", "tls");
                });
                QFAIL("cancel ignored");
            } catch (const dukto::Error &error) {
                QCOMPARE(error.code, dukto::ExitCode::Cancelled);
            }
            QCOMPARE(attempts, 1);
        }
        QVERIFY(elapsed.elapsed() < 1000);
    }

    // 日期：2026-11-05；已经持久核验的完成结果不会因紧随其后的取消信号变成失败或产生重试。
    void confirmedSuccess() {
        std::atomic_bool cancel{false};
        dukto::TransferOperation operation({3, 10}, &cancel);
        const auto value = operation.run([&]() {
            // 日期：2026-11-05；业务已确认完成，随后用户取消会话清理仍应保留成功。
            cancel.store(true);
            return QJsonObject{{"state", "completed"}};
        });
        QCOMPARE(value["state"].toString(), QString("completed"));
    }
};

QTEST_GUILESS_MAIN(TransferOperationTests)
#include "transfer_operation_tests.moc"

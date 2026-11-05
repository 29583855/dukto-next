#include "core/error.h"
#include "core/transferscheduler.h"
#include <QtTest>
#include <atomic>
#include <memory>
#include <thread>
#include <vector>

class TransferSchedulerTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；同主体大量等待不能把后来其他主体压到队尾，仍保留同主体 FIFO 和非抢占语义。
    void ownerRoundRobin() {
        dukto::TransferScheduler scheduler(1, 100, 16);
        const auto a = QUuid::createUuid();
        const auto b = QUuid::createUuid();
        auto active = std::make_shared<dukto::TransferAdmission>(scheduler, "service", a,
                                                                 QUuid::createUuid(), 16, true);
        QVERIFY(active->tryStart());
        auto first = std::make_shared<dukto::TransferAdmission>(scheduler, "service", a,
                                                                QUuid::createUuid(), 16, true);
        auto second = std::make_shared<dukto::TransferAdmission>(scheduler, "service", a,
                                                                 QUuid::createUuid(), 16, true);
        auto foreign = std::make_shared<dukto::TransferAdmission>(scheduler, "service", b,
                                                                  QUuid::createUuid(), 16, true);
        QVERIFY(!foreign->tryStart());
        QVERIFY(!first->tryStart());
        active.reset();
        QVERIFY(!second->tryStart());
        QVERIFY(first->tryStart());
        first.reset();
        QVERIFY(!second->tryStart());
        QVERIFY(foreign->tryStart());
        foreign.reset();
        QVERIFY(second->tryStart());
        second.reset();
        QCOMPARE(scheduler.usage()["active"].toInt(), 0);
        QCOMPARE(scheduler.usage()["waiting"].toInt(), 0);
        QCOMPARE(scheduler.usage()["lanes"].toInt(), 0);
    }

    // 日期：2026-11-05；百项队列边界、满队列重试、旧对端繁忙拒绝和取消主体轮次回收均不泄漏额度。
    void boundedQueueAndCleanup() {
        dukto::TransferScheduler scheduler;
        const auto owner = QUuid::createUuid();
        auto active = std::make_shared<dukto::TransferAdmission>(scheduler, "service", owner,
                                                                 QUuid::createUuid(), 16, false);
        QCOMPARE(active->lanes(), 16);
        std::vector<std::unique_ptr<dukto::TransferAdmission>> queued;
        for (int index = 0; index < 100; ++index)
            queued.emplace_back(new dukto::TransferAdmission(scheduler, "service", owner,
                                                             QUuid::createUuid(), 4, true));
        QCOMPARE(scheduler.usage()["waiting"].toInt(), 100);
        QVERIFY_EXCEPTION_THROWN(dukto::TransferAdmission(scheduler, "service", QUuid::createUuid(),
                                                          QUuid::createUuid(), 4, true),
                                 dukto::Error);
        queued.clear();
        QVERIFY_EXCEPTION_THROWN(
            dukto::TransferAdmission(scheduler, "service", owner, QUuid::createUuid(), 4, false),
            dukto::Error);
        QCOMPARE(scheduler.usage()["waiting"].toInt(), 0);
        active.reset();
        dukto::TransferAdmission next(scheduler, "service", QUuid::createUuid(),
                                      QUuid::createUuid(), 16, true);
        QVERIFY(next.tryStart());
        QCOMPARE(next.lanes(), 16);
    }

    // 日期：2026-11-05；额度随最后一个数据引用归还；两个任务共享档位，第三任务即使还有通道也不能突破任务数。
    void sharedLifetimeAndCombinedLimits() {
        dukto::TransferScheduler scheduler;
        const auto owner = QUuid::createUuid();
        const auto task = QUuid::createUuid();
        auto first =
            std::make_shared<dukto::TransferAdmission>(scheduler, "service", owner, task, 8, false);
        QVERIFY_EXCEPTION_THROWN(
            dukto::TransferAdmission(scheduler, "service", owner, task, 1, true), dukto::Error);
        auto dataWorker = first;
        first.reset();
        auto second =
            std::make_shared<dukto::TransferAdmission>(scheduler, "other", owner, task, 16, false);
        QCOMPARE(second->lanes(), 8);
        auto third = std::make_shared<dukto::TransferAdmission>(scheduler, "service", owner,
                                                                QUuid::createUuid(), 1, true);
        QVERIFY(!third->tryStart());
        second.reset();
        QVERIFY(third->tryStart());
        QCOMPARE(scheduler.usage()["lanes"].toInt(), 9);
        dukto::TransferAdmission fourth(scheduler, "service", owner, QUuid::createUuid(), 4, true);
        QVERIFY(!fourth.tryStart());
        dataWorker.reset();
        QVERIFY(fourth.tryStart());
        QCOMPARE(scheduler.usage()["active"].toInt(), 2);
        QCOMPARE(scheduler.usage()["lanes"].toInt(), 5);
    }

    // 日期：2026-11-05；真实多线程轮询和退出，统一采样必须始终满足两个任务及十六通道上界。
    void concurrentAdmission() {
        dukto::TransferScheduler scheduler;
        std::atomic_bool failed{false};
        std::vector<std::thread> workers;
        for (int index = 0; index < 8; ++index) {
            workers.emplace_back([&]() {
                // 日期：2026-11-05；每个线程独立主体反复排队，完成后析构令牌，不靠测试专用旁路授权。
                const auto owner = QUuid::createUuid();
                for (int count = 0; count < 30; ++count) {
                    dukto::TransferAdmission admission(scheduler, "service", owner,
                                                       QUuid::createUuid(), 8, true);
                    while (!admission.tryStart())
                        std::this_thread::yield();
                    const auto usage = scheduler.usage();
                    if (usage["active"].toInt() > 2 || usage["lanes"].toInt() > 16 ||
                        admission.lanes() != 8)
                        failed.store(true);
                }
            });
        }
        for (auto &worker : workers)
            worker.join();
        QVERIFY(!failed.load());
        QCOMPARE(scheduler.usage()["active"].toInt(), 0);
        QCOMPARE(scheduler.usage()["waiting"].toInt(), 0);
        QCOMPARE(scheduler.usage()["lanes"].toInt(), 0);
    }
};
QTEST_GUILESS_MAIN(TransferSchedulerTests)
#include "transfer_scheduler_tests.moc"

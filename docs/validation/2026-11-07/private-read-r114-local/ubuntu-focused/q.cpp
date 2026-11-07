#include "core/privatestore.h"
#include "core/error.h"
#include <QTemporaryDir>
#include <QtTest>
#include <array>
#include <atomic>
#include <exception>
#include <thread>
class PrivateReadTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-07；真实原子配置写入与并发读取竞争，拒绝旧换代误报和拼接正文，持续争用须明确有界拒绝。
    void posixPrivateReadAtomicReplacement() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true);
        const QByteArray first(65536, 'a');
        const QByteArray second(65536, 'b');
        store.write("record.json", first);
        std::atomic_bool start{false}, writing{true};
        std::atomic_int ready{0}, accepted{0}, busy{0}, damaged{0}, duringWrites{0};
        std::array<QString, 2> failures;
        // 日期：2026-11-07；工作线程只记录独立错误，所有Qt断言在join后执行，避免异常遗留活动线程。
        auto reader = [&](int lane) {
            ++ready;
            try {
                dukto::PrivateStore independent(store.directory());
                while (!start.load())
                    std::this_thread::yield();
                for (int index = 0; index < 512; ++index) {
                    if (writing.load())
                        ++duringWrites;
                    try {
                        const auto bytes = independent.read("record.json", 65536);
                        if (bytes != first && bytes != second)
                            ++damaged;
                        ++accepted;
                    } catch (const dukto::Error &error) {
                        if (error.code == dukto::ExitCode::Integrity && error.stage == "read-busy")
                            ++busy;
                        else {
                            failures[lane] = error.stage + ": " + error.message;
                            return;
                        }
                    }
                }
            } catch (const std::exception &error) {
                failures[lane] = QString::fromUtf8(error.what());
            }
        };
        std::thread one(reader, 0), two(reader, 1);
        while (ready.load() != 2)
            std::this_thread::yield();
        start.store(true);
        std::exception_ptr writerFailure;
        try {
            for (int index = 0; index < 128; ++index)
                store.write("record.json", index % 2 ? first : second);
        } catch (...) {
            writerFailure = std::current_exception();
        }
        writing.store(false);
        one.join();
        two.join();
        QVERIFY(!writerFailure);
        for (const auto &failure : failures)
            QVERIFY2(failure.isEmpty(), qPrintable(failure));
        QVERIFY(duringWrites.load() > 0);
        QVERIFY(accepted.load() > 0);
        QCOMPARE(accepted.load() + busy.load(), 1024);
        QCOMPARE(damaged.load(), 0);
        QCOMPARE(store.read("record.json", 65536), first);
    }
};
QTEST_GUILESS_MAIN(PrivateReadTests)
#include "q.moc"

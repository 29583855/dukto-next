#include "core/catalog.h"
#include "core/durablereceive.h"
#include "core/error.h"
#include "core/manifest.h"
#include "core/sqlitecache.h"
#include "core/strongmanifest.h"
#include "core/taskstore.h"
#include <QDir>
#include <QFile>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>

class SqliteCacheTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；五类生产数据库实际打开后检查配置与合计授信，析构必须归还至零。
    void allProductionConnectionsAccounted() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto source = temporary.filePath("source.txt");
        QFile file(source);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("data"), qint64(4));
        file.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        const auto baseline = QSqlDatabase::connectionNames();
        {
            dukto::StrongManifest strong(store, "manifest.sqlite", true);
            strong.scan({source});
            dukto::Manifest legacy;
            dukto::Catalog catalog(temporary.filePath("catalog.sqlite"));
            dukto::TaskStore tasks(store);
            dukto::DurableReceive receiver(store, "receive.sqlite", QUuid::createUuid(), strong,
                                           temporary.filePath("output"));
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(),
                     QString::number(qint64(8512) * 1024));
            auto names = QSqlDatabase::connectionNames();
            for (const auto &name : baseline)
                names.removeAll(name);
            QCOMPARE(names.size(), 5);
            int small = 0;
            int large = 0;
            for (const auto &name : names) {
                QSqlQuery query(QSqlDatabase::database(name));
                QVERIFY(query.exec("PRAGMA main.cache_size"));
                QVERIFY(query.next());
                const auto size = query.value(0).toInt();
                small += size == -1024;
                large += size == -2048;
                QVERIFY(query.exec("PRAGMA temp.cache_size"));
                QVERIFY(query.next());
                QCOMPARE(query.value(0).toInt(), -64);
                QVERIFY(query.exec("PRAGMA mmap_size"));
                QVERIFY(query.next());
                QCOMPARE(query.value(0).toLongLong(), qint64(0));
                QVERIFY(query.exec("PRAGMA temp_store"));
                QVERIFY(query.next());
                QCOMPARE(query.value(0).toInt(), 1);
            }
            QCOMPARE(small, 2);
            QCOMPARE(large, 3);
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        {
            // 日期：2026-11-05；真实只读冻结清单必须同样采用已验证配置，不能遗漏数据发送线程路径。
            dukto::StrongManifest readonly(store, "manifest.sqlite", false);
            QCOMPARE(readonly.summary()["bytes"].toString(), QString("4"));
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(),
                     QString::number(qint64(2112) * 1024));
        }
        {
            // 日期：2026-11-05；数据线程 1 MiB 只读配置保持完整清单验证，不靠跳过校验适配额度。
            dukto::StrongManifest lane(store, "manifest.sqlite", false, {}, 1024);
            QCOMPARE(lane.summary()["bytes"].toString(), QString("4"));
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(),
                     QString::number(qint64(1088) * 1024));
        }
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }

    // 日期：2026-11-05；数据缓存满时禁止继续开库，控制任务库仍可查询；失败后连接与额度无泄漏。
    void saturationPreservesControlAndReturnsCredits() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto baseline = QSqlDatabase::connectionNames();
        {
            dukto::BufferCredit data(120 * 1024 * 1024, true);
            QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "refused.sqlite", true),
                                     dukto::Error);
            QVERIFY(!store.exists("refused.sqlite"));
            QCOMPARE(QSqlDatabase::connectionNames(), baseline);
            {
                dukto::TaskStore tasks(store);
                QVERIFY(tasks.page(QUuid::createUuid())["tasks"].toArray().isEmpty());
                QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(),
                         QString::number(qint64(1088) * 1024));
            }
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString(), QString("0"));
        }
        {
            // 日期：2026-11-05；已取得额度后遇到真实坏数据库，异常退栈也须回收并移除 Qt 连接。
            store.write("broken.sqlite", QByteArray(256, 'x'));
            QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "broken.sqlite", false),
                                     dukto::Error);
            QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
            QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::SqliteCacheCredit(0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::SqliteCacheCredit(4096), dukto::Error);
        QCOMPARE(dukto::BufferCredit::usage()["used"].toString(), QString("0"));
    }
};

QTEST_GUILESS_MAIN(SqliteCacheTests)
#include "sqlite_cache_tests.moc"

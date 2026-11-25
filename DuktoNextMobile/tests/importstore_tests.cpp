#include "importstore.h"
#include <QBuffer>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>

class ImportStoreTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-25；验证中文目录、空文件和二进制内容的实际提交结果。
    void commitContent() {
        QTemporaryDir root;
        ImportStore store(root.path(), ImportStore::Limits());
        QVERIFY(store.directory(QStringLiteral("中文")));
        QByteArray data("\0\1\2\xFF", 4);
        QBuffer source(&data);
        QVERIFY(source.open(QIODevice::ReadOnly));
        QVERIFY(store.copy(source, QStringLiteral("中文/data.bin"), data.size()));
        QByteArray empty;
        QBuffer zero(&empty);
        QVERIFY(zero.open(QIODevice::ReadOnly));
        QVERIFY(store.copy(zero, "empty", 0));
        QCOMPARE(store.bytes(), qint64(4));
        const auto path = store.commit();
        QVERIFY(!path.isEmpty());
        QFile result(QDir(path).filePath(QStringLiteral("中文/data.bin")));
        QVERIFY(result.open(QIODevice::ReadOnly));
        QCOMPARE(result.readAll(), data);
        QVERIFY(store.commit().isEmpty());
    }
    // 日期：2026-11-25；超额输入及文件长度变化不允许提交，析构清理部分文件。
    void rollbackOnLengthOrQuotaFailure() {
        for (int expected : {-1, 2, 8}) {
            QTemporaryDir root;
            {
                ImportStore::Limits limits;
                limits.bytes = expected == -1 ? 2 : 100;
                ImportStore store(root.path(), limits);
                QByteArray data("abc");
                QBuffer source(&data);
                QVERIFY(source.open(QIODevice::ReadOnly));
                QVERIFY(!store.copy(source, "file", expected));
                QVERIFY(!store.error().isEmpty());
                QVERIFY(store.commit().isEmpty());
            }
            QCOMPARE(QDir(root.path()).entryList(QDir::Dirs | QDir::NoDotAndDotDot).size(), 0);
        }
    }
    // 日期：2026-11-25；目录穿越、保留设备名称及绝对路径不能离开导入事务。
    void rejectsUnsafeNames_data() {
        QTest::addColumn<QString>("name");
        for (const auto &name : {"../escape", "/absolute", "a//b", "C:/drive", "a\\b", "CON.txt", "COM1", "x.", "x "})
            QTest::newRow(name) << QString::fromLatin1(name);
    }
    // 日期：2026-11-25；每个非法路径单独创建事务，确认错误状态不可提交。
    void rejectsUnsafeNames() {
        QFETCH(QString, name);
        QTemporaryDir root;
        ImportStore store(root.path(), ImportStore::Limits());
        QVERIFY(!store.directory(name));
        QVERIFY(store.commit().isEmpty());
    }
    // 日期：2026-11-25；提供器重名、条目超限和用户取消均拒绝部分成功。
    void collisionLimitAndCancellation() {
        QTemporaryDir root;
        ImportStore store(root.path(), ImportStore::Limits());
        QVERIFY(store.directory("Folder"));
        QVERIFY(!store.directory("folder"));
        QVERIFY(store.commit().isEmpty());
        ImportStore::Limits limits;
        limits.entries = 1;
        ImportStore bounded(root.path(), limits);
        QVERIFY(bounded.directory("one"));
        QVERIFY(!bounded.directory("two"));
        ImportStore cancelled(root.path(), ImportStore::Limits());
        QByteArray data("abc");
        QBuffer source(&data);
        QVERIFY(source.open(QIODevice::ReadOnly));
        QVERIFY(!cancelled.copy(source, "cancel", 3, [] { return true; }));
        QVERIFY(cancelled.commit().isEmpty());
    }
};
QTEST_GUILESS_MAIN(ImportStoreTests)
#include "importstore_tests.moc"

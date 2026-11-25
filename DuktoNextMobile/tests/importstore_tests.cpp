#include "importstore.h"
#include <QBuffer>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QStorageInfo>
#include <QTemporaryDir>
#include <QtTest>

class ImportStoreTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-25；真实复制4GiB加17字节，流式核验完整SHA256而非仅检查声明长度。
    void contentAboveFourGiB() {
        if (qEnvironmentVariable("DUKTO_TEST_LARGE_IMPORT") != "1")
            QSKIP("大文件门禁须显式设置DUKTO_TEST_LARGE_IMPORT=1");
        QTemporaryDir root;
        QVERIFY(root.isValid());
        const qint64 size = (qint64(4) << 30) + 17;
        QStorageInfo storage(root.path());
        QVERIFY2(storage.bytesAvailable() > size + (qint64(512) << 20),
                 "大文件门禁磁盘空间不足，不能冒充通过");
        QFile source(QDir(root.path()).filePath("large-source.bin"));
        QVERIFY(source.open(QIODevice::ReadWrite));
        const QByteArray marker("DuktoNext-4GiB-END", 17);
        QVERIFY(source.write("DuktoNext-head") == 14);
        QVERIFY(source.seek(size - marker.size()));
        QCOMPARE(source.write(marker), qint64(marker.size()));
        QVERIFY(source.flush());
        QCOMPARE(source.size(), size);
        QVERIFY(source.seek(0));
        ImportStore store(root.path(), ImportStore::Limits());
        QVERIFY2(store.copy(source, "large-copy.bin", size), qPrintable(store.error()));
        QCOMPARE(store.bytes(), size);
        const auto committed = store.commit();
        QVERIFY(!committed.isEmpty());
        QFile result(QDir(committed).filePath("large-copy.bin"));
        QVERIFY(result.open(QIODevice::ReadOnly));
        QCOMPARE(result.size(), size);
        QVERIFY(result.seek(size - marker.size()));
        QCOMPARE(result.read(marker.size()), marker);
        QVERIFY(source.seek(0));
        QVERIFY(result.seek(0));
        QCryptographicHash original(QCryptographicHash::Sha256), copied(QCryptographicHash::Sha256);
        QVERIFY(original.addData(&source));
        QVERIFY(copied.addData(&result));
        QCOMPARE(copied.result(), original.result());
        qInfo().noquote() << "large-import bytes=" << size << "sha256=" << copied.result().toHex();
    }
    // 日期：2026-11-25；已提交暂存跨事务计入预算，活动事务锁阻止并发超额导入。
    void retainedQuotaAndLock() {
        QTemporaryDir root;
        ImportStore::Limits limits;
        limits.bytes = 5;
        ImportStore first(root.path(), limits);
        ImportStore concurrent(root.path(), limits);
        QVERIFY(!concurrent.error().isEmpty());
        QByteArray data("abc");
        QBuffer one(&data);
        QVERIFY(one.open(QIODevice::ReadOnly));
        QVERIFY2(first.copy(one, "one", 3), qPrintable(first.error()));
        const auto retained = first.commit();
        QVERIFY(!retained.isEmpty());
        ImportStore second(root.path(), limits);
        QVERIFY(second.error().isEmpty());
        QBuffer two(&data);
        QVERIFY(two.open(QIODevice::ReadOnly));
        QVERIFY(!second.copy(two, "two", 3));
        QVERIFY(second.commit().isEmpty());
        QFile kept(QDir(retained).filePath("one"));
        QVERIFY(kept.open(QIODevice::ReadOnly));
        QCOMPARE(kept.readAll(), data);
    }
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
        for (const auto &name :
             {"../escape", "/absolute", "a//b", "C:/drive", "a\\b", "CON.txt", "COM1", "x.", "x "})
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

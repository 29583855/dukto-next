#include "importregistry.h"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLockFile>
#include <QTemporaryDir>
#include <QtTest>

namespace {
// 日期：2026-11-25；创建真实文件快照，失败返回空值令测试明确失败。
QString source(const QString &root, const QString &name) {
    const auto directory = QDir(root).filePath(name);
    if (!QDir().mkpath(directory))
        return {};
    QFile file(QDir(directory).filePath(QStringLiteral("中文文件.txt")));
    if (!file.open(QIODevice::WriteOnly) || file.write("original-content") != 16)
        return {};
    return file.fileName();
}
// 日期：2026-11-25；独立身份和目标用于检查绑定不能被覆盖。
QJsonObject binding() {
    return {{"server", "server-one"},
            {"client", "client-one"},
            {"share", "share-one"},
            {"path", "target"},
            {"conflict", "rename"}};
}
} // namespace

class ImportRegistryTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-25；重新构造协调器从磁盘恢复原路径，完成释放后才允许清理。
    void restartAndRetain() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        const auto first = source(root.path(), "import-ABC123");
        const auto unused = source(root.path(), "import-OLD123");
        QVERIFY(!first.isEmpty());
        QVERIFY(!unused.isEmpty());
        const auto request = QUuid::createUuid();
        QStringList paths{first};
        QString error;
        QVERIFY2(ImportRegistry(root.path()).resolve(request, binding(), paths, error),
                 qPrintable(error));
        ImportRegistry restarted(root.path());
        const auto eligible = restarted.existingBatches();
        QStringList restored;
        QVERIFY2(restarted.resolve(request, binding(), restored, error), qPrintable(error));
        QCOMPARE(restored, paths);
        const auto current = source(root.path(), "import-NEW123");
        QVERIFY(!current.isEmpty());
        int removed = -1;
        QVERIFY2(restarted.clean(eligible, removed, error), qPrintable(error));
        QCOMPARE(removed, 1);
        QVERIFY(QFileInfo::exists(first));
        QVERIFY(QFileInfo::exists(current));
        QVERIFY(!QFileInfo::exists(unused));
        QVERIFY(restarted.release(request, error));
        QVERIFY(restarted.clean(eligible, removed, error));
        QCOMPARE(removed, 1);
        QVERIFY(!QFileInfo::exists(first));
        QVERIFY(QFileInfo::exists(current));
    }
    // 日期：2026-11-25；同请求换目标、换源、源丢失及越界均被拒绝。
    void rejectsSubstitution() {
        QTemporaryDir root;
        QTemporaryDir outside;
        const auto first = source(root.path(), "import-ABC123");
        const auto second = source(root.path(), "import-DEF456");
        const auto external = source(outside.path(), "import-EXT123");
        QVERIFY(!first.isEmpty() && !second.isEmpty() && !external.isEmpty());
        const auto request = QUuid::createUuid();
        ImportRegistry registry(root.path());
        QStringList paths{first};
        QString error;
        QVERIFY(registry.resolve(request, binding(), paths, error));
        auto changed = binding();
        changed["server"] = "different-server";
        QStringList restored;
        QVERIFY(!registry.resolve(request, changed, restored, error));
        paths = QStringList{second};
        QVERIFY(!registry.resolve(request, binding(), paths, error));
        paths = QStringList{external};
        QVERIFY(!registry.resolve(QUuid::createUuid(), binding(), paths, error));
        QVERIFY(QFile::remove(first));
        QVERIFY(!registry.resolve(request, binding(), restored, error));
    }
    // 日期：2026-11-25；坏JSON和越界元数据不能触发清理，预算锁覆盖互斥。
    void refusesCorruptionAndBusy() {
        QTemporaryDir root;
        const auto file = source(root.path(), "import-ABC123");
        QVERIFY(!file.isEmpty());
        ImportRegistry registry(root.path());
        const auto eligible = registry.existingBatches();
        QString error;
        int removed = -1;
        QLockFile lock(QDir(root.path()).filePath(".import-budget.lock"));
        QVERIFY(lock.tryLock(0));
        QStringList paths{file};
        QVERIFY(!registry.resolve(QUuid::createUuid(), binding(), paths, error));
        QVERIFY(!registry.clean(eligible, removed, error));
        QCOMPARE(removed, 0);
        lock.unlock();
        QFile broken(QDir(root.path()).filePath(".upload-broken.json"));
        QVERIFY(broken.open(QIODevice::WriteOnly));
        broken.write("{broken");
        broken.close();
        QVERIFY(!registry.clean(eligible, removed, error));
        QVERIFY(QFileInfo::exists(file));
    }
    // 日期：2026-11-25；导入批次中的链接保留不删，外部目标必须完整存在。
    void refusesLinkedBatches() {
#ifndef Q_OS_WIN
        QTemporaryDir root;
        QTemporaryDir outside;
        const auto external = source(outside.path(), "import-EXT123");
        const auto file = source(root.path(), "import-ABC123");
        QVERIFY(!external.isEmpty() && !file.isEmpty());
        const auto link = QDir(root.path()).filePath("import-ABC123/escape");
        QVERIFY(QFile::link(outside.path(), link));
        ImportRegistry registry(root.path());
        QStringList paths{link + "/import-EXT123/中文文件.txt"};
        QString error;
        QVERIFY(!registry.resolve(QUuid::createUuid(), binding(), paths, error));
        int removed = -1;
        QVERIFY(registry.clean(registry.existingBatches(), removed, error));
        QCOMPARE(removed, 0);
        QVERIFY(QFileInfo::exists(external));
        QVERIFY(QFileInfo::exists(file));
#endif
    }
};
QTEST_GUILESS_MAIN(ImportRegistryTests)
#include "importregistry_tests.moc"

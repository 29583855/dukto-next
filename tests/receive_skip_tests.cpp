#include "core/dispositionjournal.h"
#include "core/durablereceive.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdlib>
#ifndef Q_OS_WIN
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
const QUuid Task("01111111-2222-4333-8444-555555555555");

// 日期：2026-11-05；测试正文摘要直接使用原字节，不依据接收结果生成期望值。
QByteArray sha(const QByteArray &bytes) {
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

// 日期：2026-11-05；样本写入失败立即报告，不能以空文件充当原件保护证据。
void write(const QString &path, const QByteArray &bytes) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
}

// 日期：2026-11-05；手动冻结包含新目录、同名文件、既有目录的不存在后代及顶层同名文件的清单。
void tree(dukto::StrongManifest &manifest) {
    manifest.append({1, "a-new", "", true, 0, {}});
    manifest.append({2, "a-new/fresh.bin", "", false, 3, sha("abc")});
    manifest.appendBlock(2, 0, 3, sha("abc"));
    manifest.append({3, "a-new/old.bin", "", false, 3, sha("abc")});
    manifest.appendBlock(3, 0, 3, sha("abc"));
    manifest.append({4, "b-existing", "", true, 0, {}});
    manifest.append({5, "b-existing/missing", "", true, 0, {}});
    manifest.append({6, "b-existing/missing/data", "", false, 3, sha("abc")});
    manifest.appendBlock(6, 0, 3, sha("abc"));
    manifest.append({7, "z-existing.bin", "", false, 3, sha("abc")});
    manifest.appendBlock(7, 0, 3, sha("abc"));
    manifest.seal();
}

// 日期：2026-11-05；独立只读连接观察真实提交，不依赖回调次数或实现内部布尔值。
bool persisted(const QString &path) {
    const auto connection = QUuid::createUuid().toString();
    bool found = false;
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setConnectOptions("QSQLITE_OPEN_READONLY");
        database.setDatabaseName(path);
        if (database.open()) {
            QSqlQuery query(database);
            found = query.exec("SELECT COUNT(*) FROM skip_decisions") && query.next() &&
                    query.value(0).toInt() == 1;
        }
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
    return found;
}

// 日期：2026-11-05；独立连接只修改测试自有日志，模拟持久字段损坏后重新启动。
bool alter(const QString &path, const QString &statement) {
    const auto connection = QUuid::createUuid().toString();
    bool success = false;
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setDatabaseName(path);
        if (database.open()) {
            QSqlQuery query(database);
            success = query.exec("PRAGMA ignore_check_constraints=ON") && query.exec(statement);
        }
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
    return success;
}

// 日期：2026-11-05；真实子进程在准备决定已COMMIT但未返回调用者时退出，不执行析构。
int crash(const QString &root) {
    dukto::PrivateStore store(root + "/private");
    dukto::StrongManifest manifest(store, "source.sqlite", false);
    dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, root + "/output",
                                   dukto::ConflictPolicy::Skip);
    receiver.prepareDisposition(1, [&]() {
        // 日期：2026-11-05；只依据另一连接可见的同步记录注入退出。
        if (persisted(root + "/private/receive.sqlite"))
            std::_Exit(29);
    });
    return 30;
}
} // namespace

class ReceiveSkipTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；真实创建/提交新正文，已有原件及目录后代保持；跳过项不能打开正文或冒充确认字节。
    void mixedTreeAndRestart() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output + "/b-existing"));
        write(output + "/b-existing/keep", "unrelated");
        write(output + "/z-existing.bin", "original");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        tree(manifest);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            dukto::DispositionJournal results(store, "outcome.sqlite", Task, manifest, "skip");
            QVERIFY_EXCEPTION_THROWN(receiver.prepare(1), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.open(2, "a-new/fresh.bin"), dukto::Error);
            const auto directory = receiver.prepareDisposition(1);
            QVERIFY(!directory.skipped);
            QVERIFY(QFileInfo(output + "/a-new").isDir());
            results.append(1, directory.path, "copied");
            const auto copied = receiver.prepareDisposition(2);
            QVERIFY(!copied.skipped);
            QCOMPARE(receiver.open(2, copied.path), quint64(0));
            receiver.write(0, 0, "abc");
            QCOMPARE(receiver.confirmed(), qint64(3));
            QCOMPARE(receiver.finish(), copied.path);
            receiver.closeCurrent();
            results.append(2, copied.path, "copied");
            write(output + "/a-new/old.bin", "old child");
            for (quint64 file = 3; file <= 7; ++file) {
                const auto value = receiver.prepareDisposition(file);
                QVERIFY(value.skipped);
                QCOMPARE(value.skippedRoot, file == 5 || file == 6 ? quint64(4) : file);
                results.append(file, value.path, "skipped", value.skippedRoot);
                QVERIFY_EXCEPTION_THROWN(receiver.open(file, value.path), dukto::Error);
            }
            QCOMPARE(dukto::hashFile(output + "/z-existing.bin"), sha("original"));
            QCOMPARE(dukto::hashFile(output + "/a-new/old.bin"), sha("old child"));
            QVERIFY(!QFileInfo::exists(output + "/b-existing/missing"));
            QCOMPARE(results.summary()["copiedBytes"].toString(), QString("3"));
            QCOMPARE(results.summary()["skippedBytes"].toString(), QString("9"));
            QCOMPARE(results.summary()["skippedEntries"].toString(), QString("5"));
        }
        QVERIFY(QFile::remove(output + "/z-existing.bin"));
        QVERIFY(QFile::remove(output + "/a-new/old.bin"));
        QVERIFY(QDir(output + "/b-existing").removeRecursively());
        {
            dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(!restored.prepareDisposition(1).skipped);
            const auto fresh = restored.prepareDisposition(2);
            QVERIFY(!fresh.skipped);
            restored.open(2, fresh.path);
            QCOMPARE(restored.state(), QString("completed"));
            QCOMPARE(restored.finish(), fresh.path);
            restored.closeCurrent();
            for (quint64 file = 3; file <= 7; ++file)
                QVERIFY(restored.prepareDisposition(file).skipped);
        }
        QVERIFY(!QFileInfo::exists(output + "/b-existing"));
        QVERIFY(!QFileInfo::exists(output + "/z-existing.bin"));
        QCOMPARE(dukto::hashFile(output + "/a-new/fresh.bin"), sha("abc"));
    }

    // 日期：2026-11-05；断电式退出后删除原目标，恢复仍返回原跳过且不创建临时正文。
    void processCrashAfterDecision() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        write(output + "/file", "original");
        {
            dukto::PrivateStore store(temporary.filePath("private"), true);
            dukto::StrongManifest manifest(store, "source.sqlite", true);
            manifest.append({1, "file", "", false, 3, sha("abc")});
            manifest.appendBlock(1, 0, 3, sha("abc"));
            manifest.seal();
        }
        QProcess child;
        child.setProgram(QCoreApplication::applicationFilePath());
        child.setArguments({"--skip-crash", temporary.path()});
        child.start();
        QVERIFY(child.waitForStarted(10000));
        QVERIFY(child.waitForFinished(15000));
        QCOMPARE(child.exitCode(), 29);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("original"));
        QVERIFY(QFile::remove(output + "/file"));
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY(restored.prepareDisposition(1).skipped);
        QVERIFY(!QFileInfo::exists(output + "/file"));
        const auto leftovers =
            QDir(output).entryList(QDir::Files | QDir::Hidden | QDir::NoDotAndDotDot);
        QCOMPARE(leftovers.size(), 1);
        const auto lock = ".dukto-target-" + QString::fromLatin1(sha("file").toHex()) + ".lock";
        QCOMPARE(leftovers.first(), lock);
        {
            dukto::TargetReservation reclaimed(output + "/file");
            QVERIFY(reclaimed.acquired());
        }
        QVERIFY(
            QDir(output).entryList(QDir::Files | QDir::Hidden | QDir::NoDotAndDotDot).isEmpty());
    }

    // 日期：2026-11-05；同名类型冲突和活动预约不能被当作普通跳过。
    void unsafeTargetsAndReservation() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output + "/file"));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 0, sha("")});
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY_EXCEPTION_THROWN(receiver.prepareDisposition(1), dukto::Error);
        QVERIFY(QDir().rmdir(output + "/file"));
        write(output + "/file", "original");
        {
            dukto::TargetReservation other(output + "/file");
            QVERIFY(other.acquired());
            QVERIFY_EXCEPTION_THROWN(receiver.prepareDisposition(1), dukto::Error);
        }
        QVERIFY(receiver.prepareDisposition(1).skipped);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("original"));
        QVERIFY_EXCEPTION_THROWN(dukto::checkedConflictPolicy("skip"), dukto::Error);
    }

    // 日期：2026-11-05；准备接收后并发出现目标，发布不得自动改名或覆盖；当前该边界保留显式冲突。
    void lateConflictPreservesTarget() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY(!receiver.prepareDisposition(1).skipped);
        receiver.open(1, "file");
        receiver.write(0, 0, "abc");
        write(output + "/file", "concurrent");
        QVERIFY_EXCEPTION_THROWN(receiver.finish(), dukto::Error);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("concurrent"));
        QVERIFY(!QFileInfo::exists(output + "/file (2)"));
    }

    // 日期：2026-11-05；文件和目录都必须保持到准备决定提交，不能在最后检查回调前提前释放句柄。
    void targetHeldThroughTransaction_data() {
        QTest::addColumn<bool>("directory");
        QTest::newRow("file") << false;
        QTest::newRow("directory") << true;
    }

    // 日期：2026-11-05；以真实SQLite回滚日志观察未提交写入，再尝试移动被选中的原生对象。
    void targetHeldThroughTransaction() {
        QFETCH(bool, directory);
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        const auto target = output + "/item";
        const auto moved = output + "/moved";
        QVERIFY(QDir().mkdir(output));
        if (directory)
            QVERIFY(QDir().mkdir(target));
        else
            write(target, "original");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "item", "", directory, 0, directory ? QByteArray() : sha("")});
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        bool observed = false, renamed = false, rejected = false, skipped = false;
        try {
            skipped = receiver
                          .prepareDisposition(
                              1,
                              [&]() {
                                  // 日期：2026-11-05；只在真实事务已写日志且原决定尚不可见时注入路径移动。
                                  if (!observed &&
                                      QFileInfo::exists(
                                          temporary.filePath("private/receive.sqlite-journal")) &&
                                      !persisted(temporary.filePath("private/receive.sqlite"))) {
                                      observed = true;
                                      renamed = directory ? QDir().rename(target, moved)
                                                          : QFile::rename(target, moved);
                                  }
                              })
                          .skipped;
        } catch (const dukto::Error &) {
            rejected = true;
        }
        QVERIFY(observed);
#ifdef Q_OS_WIN
        QVERIFY(!renamed);
        QVERIFY(!rejected);
        QVERIFY(skipped);
        QVERIFY(persisted(temporary.filePath("private/receive.sqlite")));
        QVERIFY(QFileInfo::exists(target));
#else
        QVERIFY(renamed);
        QVERIFY(rejected);
        QVERIFY(!skipped);
        QVERIFY(!persisted(temporary.filePath("private/receive.sqlite")));
        QVERIFY(QFileInfo::exists(moved));
        QVERIFY(QDir().rename(moved, target));
        QVERIFY(receiver.prepareDisposition(1).skipped);
#endif
        if (!directory)
            QCOMPARE(dukto::hashFile(target), sha("original"));
    }

    // 日期：2026-11-05；事务中取消必须回滚决定；删除旧目标后重试能够变为接收，不保留假跳过。
    void cancelBeforeCommitRollsBack() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        write(output + "/file", "original");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 0, sha("")});
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        bool cancelled = false;
        try {
            receiver.prepareDisposition(1, [&]() {
                // 日期：2026-11-05；依据磁盘事务状态取消，不能在准备开始前抛错冒充事务回滚测试。
                if (QFileInfo::exists(temporary.filePath("private/receive.sqlite-journal")))
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
            });
        } catch (const dukto::Error &error) {
            cancelled = error.code == dukto::ExitCode::Cancelled;
        }
        QVERIFY(cancelled);
        QVERIFY(!persisted(temporary.filePath("private/receive.sqlite")));
        QCOMPARE(dukto::hashFile(output + "/file"), sha("original"));
        QVERIFY(QFile::remove(output + "/file"));
        QVERIFY(!receiver.prepareDisposition(1).skipped);
        receiver.open(1, "file");
        QCOMPARE(receiver.finish(), QString("file"));
        QCOMPARE(dukto::hashFile(output + "/file"), sha(""));
    }

    // 日期：2026-11-05；跨越两页的历史子树逐项重验时可撤销授权，失败不改日志且下一执行者可继续。
    void restorePagesAndAuthorization() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output + "/bundle"));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "bundle", "", true, 0, {}});
        for (quint64 id = 2; id <= 205; ++id)
            manifest.append({id, "bundle/file-" + QString::number(id).rightJustified(4, '0'), "",
                             false, 0, sha("")});
        manifest.append({206, "fresh", "", false, 0, sha("")});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            for (quint64 id = 1; id <= 205; ++id) {
                const auto decision = receiver.prepareDisposition(id);
                QVERIFY(decision.skipped);
                QCOMPARE(decision.skippedRoot, quint64(1));
            }
        }
        const auto database = temporary.filePath("private/receive.sqlite");
        const auto before = dukto::hashFile(database);
        int checks = 0;
        bool revoked = false;
        try {
            dukto::DurableReceive denied(store, "receive.sqlite", Task, manifest, output,
                                         dukto::ConflictPolicy::Skip, [&]() {
                                             // 日期：2026-11-05；足够多的检查后撤销，以覆盖分页中途而非构造前的拒绝。
                                             if (++checks > 110)
                                                 throw dukto::Error(dukto::ExitCode::Permission,
                                                                    "revoked", "test");
                                         });
        } catch (const dukto::Error &error) {
            revoked = error.code == dukto::ExitCode::Permission;
        }
        QVERIFY(revoked);
        QCOMPARE(dukto::hashFile(database), before);
        QVERIFY(QDir().rmdir(output + "/bundle"));
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QCOMPARE(restored.prepareDisposition(205).skippedRoot, quint64(1));
        QVERIFY(!restored.prepareDisposition(206).skipped);
        restored.open(206, "fresh");
        QCOMPARE(restored.finish(), QString("fresh"));
        QVERIFY(!QFileInfo::exists(output + "/bundle"));
    }

    // 日期：2026-11-05；恢复不能更换任务、策略、完整清单或原生根对象，拒绝期间不改写旧证据。
    void bindingChangesRejected() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        write(output + "/file", "old");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 0, sha("")});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(receiver.prepareDisposition(1).skipped);
        }
        const auto database = temporary.filePath("private/receive.sqlite");
        const auto before = dukto::hashFile(database);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", QUuid::createUuid(),
                                                       manifest, output,
                                                       dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       output, dukto::ConflictPolicy::Rename),
                                 dukto::Error);
        dukto::StrongManifest other(store, "other.sqlite", true);
        other.append({1, "different", "", false, 0, sha("")});
        other.seal();
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, other, output,
                                                       dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QVERIFY(QDir().rename(output, temporary.filePath("moved")));
        QVERIFY(QDir().mkdir(output));
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       output, dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QCOMPARE(dukto::hashFile(database), before);
        QCOMPARE(dukto::hashFile(temporary.filePath("moved/file")), sha("old"));
    }

#ifndef Q_OS_WIN
    // 日期：2026-11-05；真实POSIX链接、断链与FIFO均拒绝，不能跟随链接或阻塞特殊对象。
    void posixUnsafeTargets() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        const auto outside = temporary.filePath("outside");
        write(outside, "protected");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 0, sha("")});
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        const auto target = QFile::encodeName(output + "/file");
        QVERIFY(::symlink(QFile::encodeName(outside).constData(), target.constData()) == 0);
        QVERIFY_EXCEPTION_THROWN(receiver.prepareDisposition(1), dukto::Error);
        QVERIFY(::unlink(target.constData()) == 0);
        QVERIFY(::symlink(QFile::encodeName(temporary.filePath("missing")).constData(),
                          target.constData()) == 0);
        QVERIFY_EXCEPTION_THROWN(receiver.prepareDisposition(1), dukto::Error);
        QVERIFY(::unlink(target.constData()) == 0);
        QVERIFY(::mkfifo(target.constData(), 0600) == 0);
        QVERIFY_EXCEPTION_THROWN(receiver.prepareDisposition(1), dukto::Error);
        QVERIFY(::unlink(target.constData()) == 0);
        QVERIFY(!receiver.prepareDisposition(1).skipped);
        QCOMPARE(dukto::hashFile(outside), sha("protected"));
    }
#endif

    // 日期：2026-11-05；损坏决定不能被静默重建，非法ID与超大字段同样拒绝。
    void corruptedDecision_data() {
        QTest::addColumn<QString>("statement");
        QTest::newRow("missing-table") << "DROP TABLE skip_decisions";
        QTest::newRow("nonpositive-id") << "UPDATE skip_decisions SET id=0";
        QTest::newRow("oversized") << "UPDATE skip_decisions SET spec=zeroblob(1048576)";
        QTest::newRow("source") << "UPDATE skip_decisions SET source='other'";
        QTest::newRow("unknown-field")
            << "UPDATE skip_decisions SET spec=CAST('{\"bad\":true}' AS BLOB)";
    }

    // 日期：2026-11-05；保持原目标与损坏证据，重新构造必须失败。
    void corruptedDecision() {
        QFETCH(QString, statement);
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        write(output + "/file", "old");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 0, sha("")});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(receiver.prepareDisposition(1).skipped);
        }
        const auto database = temporary.filePath("private/receive.sqlite");
        QVERIFY(alter(database, statement));
        const auto before = dukto::hashFile(database);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       output, dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QCOMPARE(dukto::hashFile(database), before);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("old"));
    }
};

// 日期：2026-11-05；测试主入口只为明确的子进程故障模式分流，正常路径运行完整QtTest。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    if (app.arguments().size() == 3 && app.arguments()[1] == "--skip-crash")
        return crash(app.arguments()[2]);
    ReceiveSkipTests tests;
    return QTest::qExec(&tests, argc, argv);
}
#include "receive_skip_tests.moc"

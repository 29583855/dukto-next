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

// 日期：2026-11-05；另一只读连接观察最终提交，对未提交事务不产生假阳性。
bool finalPersisted(const QString &path) {
    const auto connection = QUuid::createUuid().toString();
    bool found = false;
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setConnectOptions("QSQLITE_OPEN_READONLY");
        database.setDatabaseName(path);
        if (database.open()) {
            QSqlQuery query(database);
            found = query.exec("SELECT COUNT(*) FROM skip_final") && query.next() &&
                    query.value(0).toInt() == 1;
        }
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
    return found;
}

// 日期：2026-11-05；只列举测试私有目录内的本任务临时项，不把锁文件当作残留正文。
QStringList parts(const QString &output, bool directory = false) {
    return QDir(output).entryList({directory ? ".dukto-*.dir" : ".dukto-*.part"},
                                  QDir::Hidden | (directory ? QDir::Dirs : QDir::Files) |
                                      QDir::NoDotAndDotDot);
}

// 日期：2026-11-05；真实子进程分别在最终提交后、临时删除后或自身发布后退出而不执行析构。
int lateCrash(const QString &root, const QString &phase) {
    dukto::PrivateStore store(root + "/private");
    dukto::StrongManifest manifest(store, "source.sqlite", false);
    const auto output = root + "/output";
    dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                   dukto::ConflictPolicy::Skip);
    receiver.prepareDisposition(1);
    receiver.openDisposition(1, "file");
    receiver.write(0, 0, "abc");
    if (phase != "own-published")
        write(output + "/file", "outside");
    receiver.finishDisposition([&]() {
        // 日期：2026-11-05；依据真实SQLite可见记录或实际最终文件注入退出，不依赖回调次数。
        if (phase == "own-published" && QFileInfo::exists(output + "/file"))
            std::_Exit(43);
        if (finalPersisted(root + "/private/receive.sqlite")) {
            if (phase == "committed" && !parts(output).isEmpty())
                std::_Exit(41);
            if (phase == "deleted" && parts(output).isEmpty())
                std::_Exit(42);
        }
    });
    return 44;
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
            QCOMPARE(receiver.openDisposition(2, copied.path).nextBlock, quint64(0));
            receiver.write(0, 0, "abc");
            QCOMPARE(receiver.confirmed(), qint64(3));
            QCOMPARE(receiver.finishDisposition().path, copied.path);
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
            restored.openDisposition(2, fresh.path);
            QCOMPARE(restored.state(), QString("completed"));
            QCOMPARE(restored.finishDisposition().path, fresh.path);
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

    // 日期：2026-11-05；准备接收后并发出现目标，最终跳过持久化且原件保持；已收字节不冒充copied。
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
        receiver.openDisposition(1, "file");
        receiver.write(0, 0, "abc");
        write(output + "/file", "concurrent");
        QVERIFY_EXCEPTION_THROWN(receiver.finish(), dukto::Error);
        const auto final = receiver.finishDisposition();
        QVERIFY(final.skipped);
        QCOMPARE(final.skippedRoot, quint64(1));
        QCOMPARE(receiver.confirmed(), qint64(0));
        QCOMPARE(receiver.state(), QString("skipped"));
        receiver.closeCurrent();
        QVERIFY(receiver.prepareDisposition(1).skipped);
        dukto::DispositionJournal results(store, "outcome.sqlite", Task, manifest, "skip");
        results.append(1, final.path, "skipped", final.skippedRoot);
        QCOMPARE(results.summary()["copiedBytes"].toString(), QString("0"));
        QCOMPARE(results.summary()["skippedBytes"].toString(), QString("3"));
        QCOMPARE(dukto::hashFile(output + "/file"), sha("concurrent"));
        QVERIFY(!QFileInfo::exists(output + "/file (2)"));
    }

    // 日期：2026-11-05；准备后、打开前出现普通目标时不创建正文，后续删除目标也不重传。
    void conflictBeforeOpen() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(!receiver.prepareDisposition(1).skipped);
            write(output + "/file", "outside");
            QVERIFY_EXCEPTION_THROWN(receiver.open(1, "file"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.openSparse(1, "file"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.openConcurrent(1, "file"), dukto::Error);
            QVERIFY(receiver.openDisposition(1, "file").disposition.skipped);
            QCOMPARE(receiver.confirmed(), qint64(0));
            QVERIFY(parts(output).isEmpty());
            QVERIFY_EXCEPTION_THROWN(receiver.write(0, 0, "abc"), dukto::Error);
        }
        QVERIFY(QFile::remove(output + "/file"));
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY(restored.openDisposition(1, "file").disposition.skipped);
        QVERIFY(!QFileInfo::exists(output + "/file"));
        QVERIFY(parts(output).isEmpty());
    }

    // 日期：2026-11-05；目录发布前产生同名目录，整子树继承最终根且不遍历/创建后代。
    void directoryLateConflict() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "tree", "", true, 0, {}});
        manifest.append({2, "tree/sub", "", true, 0, {}});
        manifest.append({3, "tree/sub/file", "", false, 3, sha("abc")});
        manifest.appendBlock(3, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            bool injected = false;
            const auto final = receiver.prepareDisposition(1, [&]() {
                // 日期：2026-11-05；仅当自有临时目录真实存在时模拟外部同名创建。
                if (!injected && !parts(output, true).isEmpty()) {
                    injected = true;
                    if (!QDir().mkdir(output + "/tree"))
                        throw dukto::Error(dukto::ExitCode::Disk, "mkdir fixture", "test");
                    write(output + "/tree/keep", "outside");
                }
            });
            QVERIFY(injected);
            QVERIFY(final.skipped);
            QCOMPARE(final.skippedRoot, quint64(1));
            for (quint64 file = 2; file <= 3; ++file) {
                const auto child = receiver.prepareDisposition(file);
                QVERIFY(child.skipped);
                QCOMPARE(child.skippedRoot, quint64(1));
            }
            QCOMPARE(receiver.openDisposition(3, "tree/sub/file").disposition.skippedRoot,
                     quint64(1));
            QVERIFY(parts(output, true).isEmpty());
            QVERIFY(!QFileInfo::exists(output + "/tree/sub"));
        }
        QCOMPARE(dukto::hashFile(output + "/tree/keep"), sha("outside"));
        QVERIFY(QDir(output + "/tree").removeRecursively());
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        for (quint64 file = 1; file <= 3; ++file)
            QCOMPARE(restored.prepareDisposition(file).skippedRoot, quint64(1));
        QVERIFY(!QFileInfo::exists(output + "/tree"));
    }

    // 日期：2026-11-05；三个退出点分别验证最终提交/清理幂等与自身已发布结果不误判skip。
    void lateProcessCrash_data() {
        QTest::addColumn<QString>("phase");
        QTest::addColumn<int>("exit");
        QTest::newRow("final-committed") << "committed" << 41;
        QTest::newRow("temporary-deleted") << "deleted" << 42;
        QTest::newRow("own-published") << "own-published" << 43;
    }

    // 日期：2026-11-05；真实进程锁接管后重验原生对象，最终确认丢失不能引发第二次传输。
    void lateProcessCrash() {
        QFETCH(QString, phase);
        QFETCH(int, exit);
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        {
            dukto::PrivateStore store(temporary.filePath("private"), true);
            dukto::StrongManifest manifest(store, "source.sqlite", true);
            manifest.append({1, "file", "", false, 3, sha("abc")});
            manifest.appendBlock(1, 0, 3, sha("abc"));
            manifest.seal();
        }
        QProcess child;
        child.setProgram(QCoreApplication::applicationFilePath());
        child.setArguments({"--late-skip-crash", temporary.path(), phase});
        child.start();
        QVERIFY(child.waitForStarted(10000));
        QVERIFY(child.waitForFinished(15000));
        QCOMPARE(child.exitCode(), exit);
        if (phase != "own-published") {
            QCOMPARE(dukto::hashFile(output + "/file"), sha("outside"));
            QVERIFY(QFile::remove(output + "/file"));
        }
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        const auto prepared = restored.prepareDisposition(1);
        const auto opened = restored.openDisposition(1, "file");
        const auto final = restored.finishDisposition();
        QCOMPARE(prepared.skipped, phase != "own-published");
        QCOMPARE(opened.disposition.skipped, phase != "own-published");
        QCOMPARE(final.skipped, phase != "own-published");
        QCOMPARE(restored.confirmed(), phase == "own-published" ? qint64(3) : qint64(0));
        QVERIFY(parts(output).isEmpty());
        if (phase == "own-published")
            QCOMPARE(dukto::hashFile(output + "/file"), sha("abc"));
        else
            QVERIFY(!QFileInfo::exists(output + "/file"));
    }

    // 日期：2026-11-05；持久决定后临时项被替换必须保留；放回原native后才能继续清理。
    void replacedTemporaryPreserved() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            receiver.prepareDisposition(1);
            receiver.openDisposition(1, "file");
            receiver.write(0, 0, "abc");
            write(output + "/file", "outside");
            QVERIFY_EXCEPTION_THROWN(receiver.finishDisposition([&]() {
                // 日期：2026-11-05；只在最终决定已由另一连接看见后撤销，保留真实待清理证据。
                if (finalPersisted(temporary.filePath("private/receive.sqlite")))
                    throw dukto::Error(dukto::ExitCode::Cancelled, "fixture cancel", "test");
            }),
                                     dukto::Error);
        }
        QCOMPARE(parts(output).size(), 1);
        const auto part = output + '/' + parts(output).first();
        const auto held = output + "/saved";
        QVERIFY(QFile::rename(part, held));
        write(part, "replacement");
        {
            dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY_EXCEPTION_THROWN(restored.prepareDisposition(1), dukto::Error);
            QCOMPARE(dukto::hashFile(part), sha("replacement"));
            QCOMPARE(dukto::hashFile(held), sha("abc"));
            QCOMPARE(dukto::hashFile(output + "/file"), sha("outside"));
            QVERIFY(QFile::remove(part));
            QVERIFY(QFile::rename(held, part));
            QVERIFY(restored.prepareDisposition(1).skipped);
            QVERIFY(!QFileInfo::exists(part));
        }
    }

    // 日期：2026-11-05；旧v3在完整验证之后原子升级，未知/损坏v4缺表不能被补建。
    void legacyUpgrade() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        write(output + "/file", "outside");
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
        QVERIFY(alter(database, "DROP TABLE skip_final"));
        QVERIFY(alter(database,
                      "UPDATE binding SET spec=CAST(replace(CAST(spec AS TEXT),'\"version\":4',"
                      "'\"version\":3') AS BLOB)"));
        {
            dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(restored.prepareDisposition(1).skipped);
        }
        QVERIFY(alter(database, "DROP TABLE skip_final"));
        const auto before = dukto::hashFile(database);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       output, dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QCOMPARE(dukto::hashFile(database), before);
    }

    // 日期：2026-11-05；中途接收后重启发现目标，按原native清理半块而非继续请求正文。
    void resumedReceiveSkipsBody() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            receiver.prepareDisposition(1);
            receiver.openDisposition(1, "file");
            receiver.write(0, 0, "a");
            QCOMPARE(receiver.confirmed(), qint64(0));
        }
        write(output + "/file", "outside");
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY(restored.openDisposition(1, "file").disposition.skipped);
        QVERIFY(restored.finishDisposition().skipped);
        QVERIFY(parts(output).isEmpty());
        QCOMPARE(dukto::hashFile(output + "/file"), sha("outside"));
    }

    // 日期：2026-11-05；最终事务提交前取消必须回滚，随后移走冲突可继续原接收而非永久skip。
    void finalTransactionRollsBack() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        const auto database = temporary.filePath("private/receive.sqlite");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        receiver.prepareDisposition(1);
        receiver.openDisposition(1, "file");
        receiver.write(0, 0, "abc");
        write(output + "/file", "outside");
        bool cancelled = false;
        try {
            receiver.finishDisposition([&]() {
                // 日期：2026-11-05；只在SQLite已有真实未提交写入时撤销。
                if (QFileInfo::exists(database + "-journal") && !finalPersisted(database))
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
            });
        } catch (const dukto::Error &error) {
            cancelled = error.code == dukto::ExitCode::Cancelled;
        }
        QVERIFY(cancelled);
        QVERIFY(!finalPersisted(database));
        QCOMPARE(parts(output).size(), 1);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("outside"));
        QVERIFY(QFile::remove(output + "/file"));
        QVERIFY(!receiver.openDisposition(1, "file").disposition.skipped);
        QVERIFY(!receiver.finishDisposition().skipped);
        QCOMPARE(dukto::hashFile(output + "/file"), sha("abc"));
    }

    // 日期：2026-11-05；自有临时目录被外部写入时绝不递归删除，清理失败仍保留最终决定。
    void nonemptyTemporaryDirectoryPreserved() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "tree", "", true, 0, {}});
        manifest.seal();
        QString originalTemporary;
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            bool injected = false;
            QVERIFY_EXCEPTION_THROWN(
                receiver.prepareDisposition(
                    1,
                    [&]() {
                        // 日期：2026-11-05；先制造发布竞争，最终记录可见后写入临时目录以验证非递归边界。
                        if (!injected && !parts(output, true).isEmpty()) {
                            injected = true;
                            originalTemporary = output + '/' + parts(output, true).first();
                            if (!QDir().mkdir(output + "/tree"))
                                throw dukto::Error(dukto::ExitCode::Disk, "fixture mkdir", "test");
                        }
                        if (finalPersisted(temporary.filePath("private/receive.sqlite")))
                            write(originalTemporary + "/protected", "outside child");
                    }),
                dukto::Error);
            QVERIFY(injected);
        }
        QVERIFY(finalPersisted(temporary.filePath("private/receive.sqlite")));
        QCOMPARE(dukto::hashFile(originalTemporary + "/protected"), sha("outside child"));
        dukto::DurableReceive restored(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        QVERIFY_EXCEPTION_THROWN(restored.prepareDisposition(1), dukto::Error);
        QCOMPARE(dukto::hashFile(originalTemporary + "/protected"), sha("outside child"));
        QVERIFY(QFile::remove(originalTemporary + "/protected"));
        QVERIFY(restored.prepareDisposition(1).skipped);
        QVERIFY(!QFileInfo::exists(originalTemporary));
        QVERIFY(QFileInfo(output + "/tree").isDir());
    }

    // 日期：2026-11-05；真实16文件句柄窗口达到上限仍拒绝第17项；最终skip释放窗口且不虚增复制字节。
    void concurrentWindowFinalSkips() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        for (quint64 file = 1; file <= 17; ++file) {
            manifest.append({file, "file-" + QString::number(file).rightJustified(2, '0'), "",
                             false, 3, sha("abc")});
            manifest.appendBlock(file, 0, 3, sha("abc"));
        }
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                       dukto::ConflictPolicy::Skip);
        for (quint64 file = 1; file <= 17; ++file)
            QVERIFY(!receiver.prepareDisposition(file).skipped);
        for (quint64 file = 1; file <= 16; ++file) {
            const auto path = manifest.entry(file).relative;
            QVERIFY(!receiver.openConcurrentDisposition(file, path).disposition.skipped);
            receiver.write(0, 0, "abc");
            if (file % 2 == 0)
                write(output + '/' + path, "outside");
        }
        QVERIFY_EXCEPTION_THROWN(
            receiver.openConcurrentDisposition(17, manifest.entry(17).relative), dukto::Error);
        dukto::DispositionJournal results(store, "outcome.sqlite", Task, manifest, "skip");
        receiver.activate(1);
        const auto first = receiver.finishDisposition();
        QVERIFY(!first.skipped);
        receiver.closeCurrent();
        results.append(1, first.path, "copied");
        receiver.openConcurrentDisposition(17, manifest.entry(17).relative);
        receiver.write(0, 0, "abc");
        for (quint64 file = 2; file <= 17; ++file) {
            receiver.activate(file);
            const auto final = receiver.finishDisposition();
            QCOMPARE(final.skipped, file % 2 == 0);
            results.append(file, final.path, final.skipped ? "skipped" : "copied",
                           final.skippedRoot);
            receiver.closeCurrent();
        }
        QVERIFY(parts(output).isEmpty());
        QCOMPARE(results.summary()["copiedBytes"].toString(), QString("27"));
        QCOMPARE(results.summary()["skippedBytes"].toString(), QString("24"));
        for (quint64 file = 1; file <= 17; ++file)
            QCOMPARE(dukto::hashFile(output + '/' + manifest.entry(file).relative),
                     sha(file % 2 == 0 ? "outside" : "abc"));
    }

    // 日期：2026-11-05；最终表及清理字段损坏必须拒绝恢复，不能补表或删除尚未验证的临时项。
    void corruptedFinal_data() {
        QTest::addColumn<QString>("statement");
        QTest::newRow("missing-final") << "DROP TABLE skip_final";
        QTest::newRow("id-zero") << "UPDATE skip_final SET id=0";
        QTest::newRow("orphan") << "UPDATE skip_final SET id=2";
        QTest::newRow("oversized") << "UPDATE skip_final SET spec=zeroblob(1048576)";
        QTest::newRow("cleaned") << "UPDATE skip_final SET cleaned=2";
        QTest::newRow("completed-not-skipped") << "UPDATE files SET state='completed'";
    }

    // 日期：2026-11-05；构造后先核对损坏证据不变及原临时正文仍在，禁止推断恢复成功。
    void corruptedFinal() {
        QFETCH(QString, statement);
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        const auto database = temporary.filePath("private/receive.sqlite");
        QVERIFY(QDir().mkdir(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", "", false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            receiver.prepareDisposition(1);
            receiver.openDisposition(1, "file");
            receiver.write(0, 0, "abc");
            write(output + "/file", "outside");
            QVERIFY_EXCEPTION_THROWN(receiver.finishDisposition([&]() {
                // 日期：2026-11-05；最终决定已提交但临时清理尚未开始时中断。
                if (finalPersisted(database))
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
            }),
                                     dukto::Error);
        }
        QCOMPARE(parts(output).size(), 1);
        const auto part = output + '/' + parts(output).first();
        QVERIFY(alter(database, statement));
        const auto before = dukto::hashFile(database);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       output, dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        QCOMPARE(dukto::hashFile(database), before);
        QCOMPARE(dukto::hashFile(part), sha("abc"));
        QCOMPARE(dukto::hashFile(output + "/file"), sha("outside"));
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
        receiver.openDisposition(1, "file");
        QCOMPARE(receiver.finishDisposition().path, QString("file"));
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
        restored.openDisposition(206, "fresh");
        QCOMPARE(restored.finishDisposition().path, QString("fresh"));
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
    if (app.arguments().size() == 4 && app.arguments()[1] == "--late-skip-crash")
        return lateCrash(app.arguments()[2], app.arguments()[3]);
    ReceiveSkipTests tests;
    return QTest::qExec(&tests, argc, argv);
}
#include "receive_skip_tests.moc"

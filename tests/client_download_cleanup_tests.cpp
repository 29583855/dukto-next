#include "core/clientdownloadcleanup.h"
#include "core/durablereceive.h"
#include "core/error.h"
#include "core/files.h"
#include "core/strongmanifest.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QTemporaryFile>
#include <QtTest>

namespace {
// 日期：2026-11-07；测试仅使用独立临时状态根和目标目录，不访问用户真实下载位置。
void database(dukto::PrivateStore &store, const QString &name,
              const std::function<void(QSqlDatabase)> &callback) {
    const auto connection = QUuid::createUuid().toString();
    auto db = QSqlDatabase::addDatabase("QSQLITE", connection);
    db.setDatabaseName(QDir(store.directory()).filePath(name));
    if (!db.open())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture database open", "test");
    try {
        callback(db);
    } catch (...) {
        db.close();
        db = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection);
        throw;
    }
    db.close();
    db = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection);
}

// 日期：2026-11-07；以独立只读SQL读取测试临时路径，不依赖清理模块的预览结果。
QString receiveTemporary(dukto::PrivateStore &store, const QUuid &task, quint64 file) {
    QString result;
    database(store, "receive-" + task.toString(QUuid::WithoutBraces) + ".sqlite",
             [&](QSqlDatabase db) {
                 QSqlQuery query(db);
                 query.prepare("SELECT temporary FROM files WHERE id=?");
                 query.addBindValue(static_cast<qlonglong>(file));
                 if (!query.exec() || !query.next())
                     throw dukto::Error(dukto::ExitCode::Disk, "fixture temporary read", "test");
                 result = query.value(0).toString();
             });
    return result;
}

// 日期：2026-11-07；固定内存片段写入源文件，样本大小不影响测试辅助程序的峰值缓冲。
void writeSource(const QString &path, qint64 bytes) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture source open", "test");
    const QByteArray chunk(dukto::BufferSize, 'd');
    for (qint64 written = 0; written < bytes;) {
        const auto count = qMin<qint64>(chunk.size(), bytes - written);
        if (file.write(chunk.constData(), count) != count)
            throw dukto::Error(dukto::ExitCode::Disk, "fixture source write", "test");
        written += count;
    }
}

// 日期：2026-11-07；生成一个完整文件和一个带持久块及未确认片段的第二文件。
struct Fixture {
    QTemporaryDir root;
    const QUuid task = QUuid::createUuid();
    const QString stateDirectory = root.filePath("state");
    const QString state = QDir(stateDirectory).filePath("transfers");
    const QString output = root.filePath("output");
    const QString manifestName = "download-" + task.toString(QUuid::WithoutBraces) + ".sqlite";
    const QString receiveName = "receive-" + task.toString(QUuid::WithoutBraces) + ".sqlite";

    // 日期：2026-11-07；冻结真实强清单并留下可恢复的收件日志及一份已发布文件。
    Fixture() {
        if (!root.isValid() || !QDir().mkpath(output) || !QDir().mkpath(root.filePath("sources")))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture directory", "test");
        writeSource(root.filePath("sources/a.bin"), dukto::StrongBlockBytes);
        writeSource(root.filePath("sources/b.bin"), 2 * dukto::StrongBlockBytes);
        dukto::PrivateStore store(state, true);
        {
            dukto::StrongManifest manifest(store, manifestName, true);
            manifest.scan({root.filePath("sources/a.bin"), root.filePath("sources/b.bin")});
        }
        {
            dukto::StrongManifest manifest(store, manifestName, false);
            dukto::DurableReceive receiver(store, receiveName, task, manifest, output);
            receiver.openFile(1, "a.bin");
            for (qint64 offset = 0; offset < dukto::StrongBlockBytes; offset += dukto::BufferSize) {
                const auto count =
                    qMin<qint64>(dukto::BufferSize, dukto::StrongBlockBytes - offset);
                receiver.write(0, static_cast<quint32>(offset), QByteArray(count, 'd'));
            }
            receiver.finish();
            receiver.openFile(2, "b.bin");
            for (qint64 offset = 0; offset < dukto::StrongBlockBytes; offset += dukto::BufferSize) {
                const auto count =
                    qMin<qint64>(dukto::BufferSize, dukto::StrongBlockBytes - offset);
                receiver.write(0, static_cast<quint32>(offset), QByteArray(count, 'd'));
            }
            receiver.write(1, 0, QByteArray(65536, 'x'));
        }
    }

    // 日期：2026-11-07；从SQLite独立读取一条固定字段，断言接收检查点和状态确实已持久化。
    QJsonObject fileState(dukto::PrivateStore &store, quint64 id) const {
        QJsonObject result;
        database(store, receiveName, [&](QSqlDatabase db) {
            QSqlQuery query(db);
            query.prepare("SELECT state,confirmed,length(native) FROM files WHERE id=?");
            query.addBindValue(static_cast<qlonglong>(id));
            if (!query.exec() || !query.next())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture state read", "test");
            result = {{"state", query.value(0).toString()},
                      {"confirmed", query.value(1).toLongLong()},
                      {"nativeBytes", query.value(2).toInt()}};
        });
        return result;
    }

    // 日期：2026-11-07；直接统计指定文件检查点，确保回收不是只改显示状态。
    int blockCount(dukto::PrivateStore &store, quint64 id) const {
        int result = -1;
        database(store, receiveName, [&](QSqlDatabase db) {
            QSqlQuery query(db);
            query.prepare("SELECT COUNT(*) FROM blocks WHERE file=?");
            query.addBindValue(static_cast<qlonglong>(id));
            if (!query.exec() || !query.next())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture block count", "test");
            result = query.value(0).toInt();
        });
        return result;
    }
};
} // namespace

// 日期：2026-11-07；预览零修改、执行保留完成文件、清除旧块并允许同任务从零续传。
class ClientDownloadCleanupTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-07；预览确认文件路径和任务状态，随后执行并恢复相同清单中的未完成文件。
    void previewRunAndResume() {
        Fixture fixture;
        const auto temporary = [&]() {
            dukto::PrivateStore store(fixture.state);
            return receiveTemporary(store, fixture.task, 2);
        }();
        const auto temporaryPath = QDir(fixture.output).filePath(temporary);
        QVERIFY(QFileInfo::exists(temporaryPath));
        QVERIFY(QFileInfo::exists(QDir(fixture.output).filePath("a.bin")));
        {
            dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
            const auto preview = dukto::cleanupClientDownload(store, fixture.task, false);
            QCOMPARE(preview["entries"].toArray().size(), 2);
            QCOMPARE(preview["cleanedFiles"].toString(), QString("0"));
            QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
            QVERIFY(QFileInfo::exists(temporaryPath));
            const auto result = dukto::cleanupClientDownload(store, fixture.task, true);
            QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
            QCOMPARE(result["preservedFiles"].toString(), QString("1"));
            QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
            QCOMPARE(fixture.fileState(store, 2)["confirmed"].toInt(), 0);
            QCOMPARE(fixture.fileState(store, 2)["nativeBytes"].toInt(), 0);
            QCOMPARE(fixture.blockCount(store, 2), 0);
            QCOMPARE(fixture.blockCount(store, 1), 1);
            QVERIFY(!QFileInfo::exists(temporaryPath));
            QVERIFY(QFileInfo::exists(QDir(fixture.output).filePath("a.bin")));
            QVERIFY(!QFileInfo::exists(QDir(fixture.output).filePath("b.bin")));
        }
        {
            dukto::PrivateStore store(fixture.state);
            dukto::StrongManifest manifest(store, fixture.manifestName, false);
            dukto::DurableReceive receiver(store, fixture.receiveName, fixture.task, manifest,
                                           fixture.output);
            QCOMPARE(receiver.openFile(2, "b.bin"), quint64(0));
            QCOMPARE(receiver.confirmed(), qint64(0));
            QCOMPARE(receiver.state(), QString("receiving"));
        }
    }

    // 日期：2026-11-07；模拟unlink后进程退出，重跑能以缺失临时项为幂等完成条件。
    void missingTemporaryAfterCrash() {
        Fixture fixture;
        const auto path = [&]() {
            dukto::PrivateStore store(fixture.state);
            return QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        }();
        QVERIFY(QFile::remove(path));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto result = dukto::cleanupClientDownload(store, fixture.task, true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
    }

    // 日期：2026-11-07；原临时名被其他文件占用时按原生身份拒绝删除，并保留替换文件正文。
    void replacedTemporaryIsPreserved() {
        Fixture fixture;
        QString path;
        {
            dukto::PrivateStore store(fixture.state);
            path = QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        }
        QTemporaryFile replacement(fixture.output + "/replacement-XXXXXX");
        QVERIFY(replacement.open());
        QCOMPARE(replacement.write("keep", 4), qint64(4));
        replacement.close();
        QVERIFY(QFile::remove(path));
        QVERIFY(QFile::rename(replacement.fileName(), path));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(store, fixture.task, true),
                                 dukto::Error);
        QFile preserved(path);
        QVERIFY(preserved.open(QIODevice::ReadOnly));
        QCOMPARE(preserved.readAll(), QByteArray("keep"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
    }

    // 日期：2026-11-07；即使没有残留旁路文件，也必须从SQLite元数据拒绝WAL模式接收日志。
    void walModeIsRejectedWithoutSidecars() {
        Fixture fixture;
        {
            dukto::PrivateStore store(fixture.state);
            database(store, fixture.receiveName, [](QSqlDatabase db) {
                QSqlQuery query(db);
                if (!query.exec("PRAGMA journal_mode=WAL") || !query.next() ||
                    query.value(0).toString() != "wal")
                    throw dukto::Error(dukto::ExitCode::Disk, "fixture WAL mode", "test");
            });
            QVERIFY(
                !QFileInfo::exists(QDir(store.directory()).filePath(fixture.receiveName + "-wal")));
            QVERIFY(
                !QFileInfo::exists(QDir(store.directory()).filePath(fixture.receiveName + "-shm")));
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(store, fixture.task, false),
                                 dukto::Error);
    }

    // 日期：2026-11-07；真实CLI核对JSON预览、参数拒绝及复用任务ID执行后的接收状态。
    void commandLine() {
        Fixture fixture;
        QString temporary;
        {
            dukto::PrivateStore store(fixture.state);
            temporary = receiveTemporary(store, fixture.task, 2);
        }
        const auto cli = QDir(QCoreApplication::applicationDirPath())
                             .filePath(
#ifdef Q_OS_WIN
                                 "dukto-cli.exe"
#else
                                 "dukto-cli"
#endif
                             );
        const QStringList base{"--json",
                               "--state-directory",
                               fixture.stateDirectory,
                               "client",
                               "cleanup",
                               "preview",
                               "--task",
                               fixture.task.toString(QUuid::WithoutBraces)};
        const auto invoke = [&](const QStringList &args, int expected) {
            // 日期：2026-11-07；验证真实子进程终态和JSON，不以启动成功代替CLI契约通过。
            QProcess process;
            process.start(cli, args);
            if (!process.waitForFinished(30000) || process.exitCode() != expected)
                throw dukto::Error(dukto::ExitCode::Runtime, "CLI fixture exit", "test");
            const auto result = QJsonDocument::fromJson(process.readAllStandardOutput()).object();
            if (result.isEmpty())
                throw dukto::Error(dukto::ExitCode::Runtime, "CLI fixture JSON", "test");
            return result;
        };
        const auto preview = invoke(base, 0);
        QCOMPARE(preview["event"].toString(), QString("client-download-cleanup"));
        QCOMPARE(preview["entries"].toArray().size(), 2);
        QVERIFY(!preview["applied"].toBool());
        auto invalid = base;
        invalid.append({"--to", "127.0.0.1"});
        invoke(invalid, 2);
        auto run = base;
        run[5] = "run";
        auto cursor = run;
        cursor.append({"--after", "0"});
        invoke(cursor, 2);
        const auto result = invoke(run, 0);
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(QDir(fixture.output).filePath(temporary)));
        dukto::PrivateStore store(fixture.state);
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
    }
};

// 日期：2026-11-07；独立QtTest进程使状态锁、SQLite连接和临时目录生命周期可重复核验。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    ClientDownloadCleanupTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "client_download_cleanup_tests.moc"

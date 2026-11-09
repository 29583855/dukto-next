#include "core/clientdownloadcleanup.h"
#include "core/durablereceive.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/statecleanup.h"
#include "core/statesession.h"
#include "core/strongmanifest.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdlib>

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
    explicit Fixture(dukto::ConflictPolicy policy = dukto::ConflictPolicy::Rename,
                     int extraFiles = 0) {
        if (!root.isValid() || !QDir().mkpath(output) || !QDir().mkpath(stateDirectory) ||
            !QDir().mkpath(root.filePath("sources")))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture directory", "test");
        writeSource(root.filePath("sources/a.bin"), dukto::StrongBlockBytes);
        writeSource(root.filePath("sources/b.bin"), 2 * dukto::StrongBlockBytes);
        QStringList sources{root.filePath("sources/a.bin"), root.filePath("sources/b.bin")};
        for (int index = 0; index < extraFiles; ++index) {
            const auto path =
                root.filePath(QString("sources/c%1.bin").arg(index, 3, 10, QChar('0')));
            writeSource(path, 0);
            sources.append(path);
        }
        dukto::PrivateStore store(state, true);
        {
            dukto::StrongManifest manifest(store, manifestName, true);
            manifest.scan(sources);
        }
        {
            dukto::StrongManifest manifest(store, manifestName, false);
            dukto::DurableReceive receiver(store, receiveName, task, manifest, output, policy);
            receiver.prepareDisposition(1);
            receiver.openDisposition(1, "a.bin");
            for (qint64 offset = 0; offset < dukto::StrongBlockBytes; offset += dukto::BufferSize) {
                const auto count =
                    qMin<qint64>(dukto::BufferSize, dukto::StrongBlockBytes - offset);
                receiver.write(0, static_cast<quint32>(offset), QByteArray(count, 'd'));
            }
            receiver.finishDisposition();
            receiver.prepareDisposition(2);
            receiver.openDisposition(2, "b.bin");
            for (qint64 offset = 0; offset < dukto::StrongBlockBytes; offset += dukto::BufferSize) {
                const auto count =
                    qMin<qint64>(dukto::BufferSize, dukto::StrongBlockBytes - offset);
                receiver.write(0, static_cast<quint32>(offset), QByteArray(count, 'd'));
            }
            receiver.write(1, 0, QByteArray(65536, 'x'));
            for (int index = 0; index < extraFiles; ++index) {
                const auto id = static_cast<quint64>(3 + index);
                const auto path = QString("c%1.bin").arg(index, 3, 10, QChar('0'));
                receiver.prepareDisposition(id);
                receiver.openDisposition(id, path);
            }
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

    // 日期：2026-11-09；保留期凭据由产品入口生成，时钟注入不依赖修改文件时间。
    void note(dukto::PrivateStore &store, const QDateTime &now) const {
        dukto::StrongManifest manifest(store, manifestName, false);
        dukto::noteClientDownloadActivity(
            store, task, QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()),
            now);
    }

    // 日期：2026-11-09；只读测试自有凭据，用独立断言检查分页和活动刷新实际落盘。
    QString retentionName() const {
        return "download-retention-" + task.toString(QUuid::WithoutBraces) + ".json";
    }
};
} // namespace

// 日期：2026-11-07；预览零修改、执行保留完成文件、清除旧块并允许同任务从零续传。
class ClientDownloadCleanupTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-09；旧任务、七天内及采样宽限期保留；到期预览不修改正文或凭据。
    void retentionBoundaryAndPreview() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto now = QDateTime::fromString("2026-11-09T00:00:00.000Z", Qt::ISODateWithMs);
        QCOMPARE(dukto::cleanupExpiredClientDownload(store, fixture.task, now, true)["action"],
                 QJsonValue("no-retention-evidence"));
        fixture.note(store, now);
        const auto original = store.read(fixture.retentionName());
        const auto temporary =
            QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        for (const auto seconds : {qint64(0), qint64(7 * 86400), qint64(7 * 86400 + 59)}) {
            const auto result = dukto::cleanupExpiredClientDownload(store, fixture.task,
                                                                    now.addSecs(seconds), true);
            QVERIFY(!result["eligible"].toBool());
            QVERIFY(QFileInfo::exists(temporary));
            QCOMPARE(store.read(fixture.retentionName()), original);
        }
        const auto preview = dukto::cleanupExpiredClientDownload(store, fixture.task,
                                                                 now.addDays(7).addSecs(60), false);
        QVERIFY(preview["eligible"].toBool());
        QCOMPARE(preview["entries"].toArray().size(), 2);
        QCOMPARE(store.read(fixture.retentionName()), original);
        QVERIFY(QFileInfo::exists(temporary));
        QCOMPARE(fixture.blockCount(store, 2), 1);
    }

    // 日期：2026-11-09；执行每批最多一项，跨重开继续游标，完成文件和请求清单始终保留。
    void retentionBoundedPagesAndRenewal() {
        Fixture fixture;
        const auto now = QDateTime::fromString("2026-11-09T00:00:00.000Z", Qt::ISODateWithMs);
        {
            dukto::PrivateStore store(fixture.state);
            fixture.note(store, now.addDays(-8));
        }
        for (int batch = 0; batch < 2; ++batch) {
            dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
            const auto result =
                dukto::cleanupExpiredClientDownload(store, fixture.task, now, true, 1);
            QCOMPARE(result["visited"].toString(), QString("1"));
            QCOMPARE(result["more"].toBool(), batch == 0);
            QCOMPARE(result["cleanedFiles"].toString(), batch == 0 ? QString("0") : QString("1"));
            QVERIFY(QFileInfo::exists(QDir(fixture.output).filePath("a.bin")));
            QVERIFY(store.exists(fixture.manifestName));
            QCOMPARE(fixture.blockCount(store, 1), 1);
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QCOMPARE(dukto::cleanupExpiredClientDownload(store, fixture.task, now, true)["action"],
                 QJsonValue("already-cleaned"));
        {
            dukto::StrongManifest manifest(store, fixture.manifestName, false);
            dukto::DurableReceive receiver(store, fixture.receiveName, fixture.task, manifest,
                                           fixture.output);
            QCOMPARE(receiver.open(2, "b.bin"), quint64(0));
        }
        fixture.note(store, now);
        QVERIFY(!dukto::cleanupExpiredClientDownload(store, fixture.task, now.addDays(1),
                                                     true)["eligible"]
                     .toBool());
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
    }

    // 日期：2026-11-09；凭据的未来时间和实际时钟后退均不能缩短已有保留期。
    void retentionClockRollback() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto now = QDateTime::fromString("2026-11-09T00:00:00.000Z", Qt::ISODateWithMs);
        fixture.note(store, now.addDays(20));
        const auto original = store.read(fixture.retentionName());
        fixture.note(store, now);
        QCOMPARE(store.read(fixture.retentionName()), original);
        QVERIFY(!dukto::cleanupExpiredClientDownload(store, fixture.task, now, true)["eligible"]
                     .toBool());
        QCOMPARE(fixture.blockCount(store, 2), 1);
    }

    // 日期：2026-11-09；逐项损坏时间/版本/身份/摘要/游标都必须拒绝，不把损坏凭据重置。
    void retentionTampering_data() {
        QTest::addColumn<QString>("field");
        QTest::addColumn<QJsonValue>("value");
        QTest::newRow("version") << QString("version") << QJsonValue(2);
        QTest::newRow("root") << QString("root") << QJsonValue("abcd");
        QTest::newRow("receive") << QString("receive") << QJsonValue("abcd");
        QTest::newRow("manifest") << QString("manifest") << QJsonValue(QString(64, '0'));
        QTest::newRow("task") << QString("task") << QJsonValue(QUuid::createUuid().toString());
        QTest::newRow("negative-cursor") << QString("after") << QJsonValue("-1");
        QTest::newRow("numeric-cursor") << QString("after") << QJsonValue(0);
        QTest::newRow("noncanonical-time") << QString("updated") << QJsonValue("2026-11-01");
        QTest::newRow("extra-field") << QString("extra") << QJsonValue(true);
    }

    // 日期：2026-11-09；正文和检查点使用独立SQL/路径检查，不能仅相信清理返回值。
    void retentionTampering() {
        QFETCH(QString, field);
        QFETCH(QJsonValue, value);
        Fixture fixture;
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto now = QDateTime::fromString("2026-11-09T00:00:00.000Z", Qt::ISODateWithMs);
        fixture.note(store, now.addDays(-8));
        auto marker = dukto::next::parseControl(store.read(fixture.retentionName()));
        marker[field] = value;
        const auto corrupted = dukto::next::encodeControl(marker);
        store.write(fixture.retentionName(), corrupted);
        const auto temporary =
            QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupExpiredClientDownload(store, fixture.task, now, true), dukto::Error);
        QVERIFY(QFileInfo::exists(temporary));
        QCOMPARE(fixture.blockCount(store, 2), 1);
        QCOMPARE(store.read(fixture.retentionName()), corrupted);
    }

    // 日期：2026-11-09；同名接收库被真实复制替换，旧保留期不得用于新对象。
    void retentionReplacedReceive() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto now = QDateTime::fromString("2026-11-09T00:00:00.000Z", Qt::ISODateWithMs);
        fixture.note(store, now.addDays(-8));
        const auto path = QDir(fixture.state).filePath(fixture.receiveName);
        QVERIFY(QFile::rename(path, path + ".saved"));
        QVERIFY(QFile::copy(path + ".saved", path));
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupExpiredClientDownload(store, fixture.task, now, true), dukto::Error);
        QCOMPARE(fixture.blockCount(store, 2), 1);
    }

    // 日期：2026-11-09；状态维护实际枚举到期下载凭据，调用逐批清理并留下脱敏计数。
    void retentionStateMaintenance() {
        Fixture fixture;
        const auto now = QDateTime::currentDateTimeUtc();
        {
            dukto::PrivateStore store(fixture.state);
            fixture.note(store, now.addDays(-8));
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto result = dukto::cleanupState(store, now, true, {32, 256, 30000});
        QCOMPARE(result["errorCount"].toString(), QString("0"));
        QCOMPARE(result["downloadTasksVisited"].toString(), QString("1"));
        QCOMPARE(result["downloadFilesCleaned"].toString(), QString("1"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
        QVERIFY(QFileInfo::exists(QDir(fixture.output).filePath("a.bin")));
    }

    // 日期：2026-11-09；真实业务打开根之前会清理到期下载，共享占用期间相同维护必须让出。
    void retentionAutomaticOpenAndActiveGuard() {
        Fixture fixture;
        const auto now = QDateTime::currentDateTimeUtc();
        {
            auto active = dukto::StateSession::root(fixture.stateDirectory, "transfers", false);
            fixture.note(*active, now.addDays(-8));
            dukto::tryAutomaticStateCleanup(fixture.stateDirectory, "transfers");
            QCOMPARE(fixture.fileState(*active, 2)["state"].toString(), QString("receiving"));
        }
        auto reopened = dukto::StateSession::root(fixture.stateDirectory, "transfers", false);
        QCOMPARE(fixture.fileState(*reopened, 2)["state"].toString(), QString("planned"));
        QVERIFY(QFileInfo::exists(QDir(fixture.output).filePath("a.bin")));
    }

    // 日期：2026-11-09；自动回收在删除后直接退出，重开仍从原游标幂等解决检查点，不重复删除新文件。
    void retentionProcessExitAfterRemoval() {
        Fixture fixture;
        QString temporary;
        QByteArray marker;
        {
            dukto::PrivateStore store(fixture.state);
            fixture.note(store, QDateTime::currentDateTimeUtc().addDays(-8));
            temporary = QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
            marker = store.read(fixture.retentionName());
        }
        QProcess worker;
        worker.start(QCoreApplication::applicationFilePath(),
                     {"--crash-expired", fixture.state, fixture.task.toString(QUuid::WithoutBraces),
                      temporary});
        QVERIFY(worker.waitForFinished(30000));
        QCOMPARE(worker.exitCode(), 87);
        QVERIFY(!QFileInfo::exists(temporary));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QCOMPARE(store.read(fixture.retentionName()), marker);
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
        QCOMPARE(fixture.blockCount(store, 2), 1);
        const auto result = dukto::cleanupExpiredClientDownload(
            store, fixture.task, QDateTime::currentDateTimeUtc(), true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QCOMPARE(fixture.blockCount(store, 2), 0);
        QFile replacement(temporary);
        QVERIFY(replacement.open(QIODevice::WriteOnly));
        QCOMPARE(replacement.write("replacement"), qint64(11));
        replacement.close();
        QCOMPARE(dukto::cleanupExpiredClientDownload(
                     store, fixture.task, QDateTime::currentDateTimeUtc(), true)["action"],
                 QJsonValue("already-cleaned"));
        QVERIFY(replacement.open(QIODevice::ReadOnly));
        QCOMPARE(replacement.readAll(), QByteArray("replacement"));
    }

    // 日期：2026-11-09；跳过策略中未决接收由原契约保留，到期凭据也不能扩大删除范围。
    void retentionSkipPolicyPreserved() {
        Fixture fixture(dukto::ConflictPolicy::Skip);
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto now = QDateTime::currentDateTimeUtc();
        fixture.note(store, now.addDays(-8));
        const auto temporary =
            QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        const auto result = dukto::cleanupExpiredClientDownload(store, fixture.task, now, true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("0"));
        QVERIFY(QFileInfo::exists(temporary));
        QCOMPARE(fixture.blockCount(store, 2), 1);
    }

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
            QCOMPARE(receiver.open(2, "b.bin"), quint64(0));
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
        QVERIFY(QFile::rename(path, path + ".saved"));
        QFile replacement(path);
        QVERIFY(replacement.open(QIODevice::WriteOnly));
        QCOMPARE(replacement.write("keep", 4), qint64(4));
        replacement.close();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(store, fixture.task, true),
                                 dukto::Error);
        QFile preserved(path);
        QVERIFY(preserved.open(QIODevice::ReadOnly));
        QCOMPARE(preserved.readAll(), QByteArray("keep"));
        QVERIFY(QFileInfo::exists(path + ".saved"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
    }

    // 日期：2026-11-07；真实子进程在删除正文后退出，内核锁释放后同一任务可安全重新清理。
    void processExitAfterRemoval() {
        Fixture fixture;
        QString path;
        {
            dukto::PrivateStore store(fixture.state);
            path = QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        }
        QProcess worker;
        worker.start(
            QCoreApplication::applicationFilePath(),
            {"--crash-cleanup", fixture.state, fixture.task.toString(QUuid::WithoutBraces), path});
        QVERIFY(worker.waitForFinished(30000));
        QCOMPARE(worker.exitCode(), 87);
        QVERIFY(!QFileInfo::exists(path));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
        QCOMPARE(fixture.blockCount(store, 2), 1);
        const auto result = dukto::cleanupClientDownload(store, fixture.task, true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
        QCOMPARE(fixture.blockCount(store, 2), 0);
        QFile other(path);
        QVERIFY(other.open(QIODevice::WriteOnly));
        QCOMPARE(other.write("keep", 4), qint64(4));
        other.close();
        QCOMPARE(dukto::cleanupClientDownload(store, fixture.task, true)["cleanedFiles"].toString(),
                 QString("0"));
        QVERIFY(other.open(QIODevice::ReadOnly));
        QCOMPARE(other.readAll(), QByteArray("keep"));
    }

    // 日期：2026-11-07；在检查点及状态更新后取消会回滚整个事务，之后重跑仍能完成清理。
    void cancellationRollsBackCheckpointReset() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto path = QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        int afterRemoval = 0;
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupClientDownload(store, fixture.task, true, 0,
                                         [&]() {
                                             // 日期：2026-11-07；第二个删除后检查点位于FULL事务提交前，精确验证回滚边界。
                                             if (!QFileInfo::exists(path) && ++afterRemoval == 2)
                                                 throw dukto::Error(dukto::ExitCode::Cancelled,
                                                                    "fixture cancel", "test");
                                         }),
            dukto::Error);
        QCOMPARE(afterRemoval, 2);
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
        QCOMPARE(fixture.blockCount(store, 2), 1);
        QCOMPARE(dukto::cleanupClientDownload(store, fixture.task, true)["cleanedFiles"].toString(),
                 QString("1"));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("planned"));
        QCOMPARE(fixture.blockCount(store, 2), 0);
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

    // 日期：2026-11-07；100条分页游标须稳定前进，执行可处理整任务且重复执行不重复删除。
    void paginationAndRepeatedRun() {
        Fixture fixture(dukto::ConflictPolicy::Rename, 101);
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto first = dukto::cleanupClientDownload(store, fixture.task, false);
        QCOMPARE(first["entries"].toArray().size(), 100);
        QVERIFY(first["more"].toBool());
        QCOMPARE(first["after"].toString(), QString("100"));
        const auto second = dukto::cleanupClientDownload(store, fixture.task, false, 100);
        QCOMPARE(second["entries"].toArray().size(), 3);
        QVERIFY(!second["more"].toBool());
        QCOMPARE(second["after"].toString(), QString("103"));
        const auto result = dukto::cleanupClientDownload(store, fixture.task, true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("102"));
        QCOMPARE(result["preservedFiles"].toString(), QString("1"));
        QVERIFY(result["entries"].toArray().isEmpty());
        QCOMPARE(dukto::cleanupClientDownload(store, fixture.task, true)["cleanedFiles"].toString(),
                 QString("0"));
    }

    // 日期：2026-11-07；冲突策略绑定由真实接收器生成，所有策略均保留已发布目标。
    void policies_data() {
        QTest::addColumn<QString>("policy");
        for (const auto &policy : QStringList{"rename", "fail", "overwrite", "skip"})
            QTest::newRow(policy.toLatin1().constData()) << policy;
    }

    // 日期：2026-11-07；skip日志完全保留；其余策略仅复位未完成文件并保留原已完成文件摘要。
    void policies() {
        QFETCH(QString, policy);
        Fixture fixture(dukto::checkedConflictPolicy(policy));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto completed = dukto::hashFile(QDir(fixture.output).filePath("a.bin"));
        const auto path = QDir(fixture.output).filePath(receiveTemporary(store, fixture.task, 2));
        const auto result = dukto::cleanupClientDownload(store, fixture.task, true);
        const bool skipped = policy == "skip";
        QCOMPARE(result["cleanedFiles"].toString(), skipped ? QString("0") : QString("1"));
        QCOMPARE(QFileInfo::exists(path), skipped);
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(),
                 skipped ? QString("receiving") : QString("planned"));
        QCOMPARE(dukto::hashFile(QDir(fixture.output).filePath("a.bin")), completed);
    }

    // 日期：2026-11-07；目标根被替换后拒绝清理，保留原目录中仍可辨认的临时正文。
    void replacedRootIsRejected() {
        Fixture fixture;
        QString temporary;
        {
            dukto::PrivateStore store(fixture.state);
            temporary = receiveTemporary(store, fixture.task, 2);
        }
        const auto saved = fixture.root.filePath("saved-output");
        QVERIFY(QDir().rename(fixture.output, saved));
        QVERIFY(QDir().mkpath(fixture.output));
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(store, fixture.task, true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(QDir(saved).filePath(temporary)));
        QCOMPARE(fixture.fileState(store, 2)["state"].toString(), QString("receiving"));
    }

    // 日期：2026-11-07；共享状态对象不能维护；已有接收日志租约时预览和执行都立即拒绝。
    void maintenanceAndReceiveLeaseRequired() {
        Fixture fixture;
        {
            dukto::PrivateStore shared(fixture.state);
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(shared, fixture.task, true),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(
                dukto::PrivateStore(fixture.state, false, dukto::PrivateStore::Use::Maintenance),
                dukto::Error);
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        dukto::StrongManifest manifest(store, fixture.manifestName, false);
        dukto::DurableReceive receiver(store, fixture.receiveName, fixture.task, manifest,
                                       fixture.output);
        for (const bool apply : {false, true})
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupClientDownload(store, fixture.task, apply),
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
    const auto arguments = app.arguments();
    if (arguments.size() == 5 && arguments[1] == "--crash-expired") {
        dukto::PrivateStore store(arguments[2], false, dukto::PrivateStore::Use::Maintenance);
        dukto::cleanupExpiredClientDownload(store, QUuid(arguments[3]),
                                            QDateTime::currentDateTimeUtc(), true, 32, [&]() {
                                                // 日期：2026-11-09；退出位置在真实unlink之后、FULL检查点重置与游标保存之前。
                                                if (!QFileInfo::exists(arguments[4]))
                                                    std::_Exit(87);
                                            });
        return 88;
    }
    if (arguments.size() == 5 && arguments[1] == "--crash-cleanup") {
        dukto::PrivateStore store(arguments[2], false, dukto::PrivateStore::Use::Maintenance);
        dukto::cleanupClientDownload(store, QUuid(arguments[3]), true, 0, [&]() {
            // 日期：2026-11-07；跳过正常析构退出，验证原生占用锁和接收租约的真实崩溃恢复。
            if (!QFileInfo::exists(arguments[4]))
                std::_Exit(87);
        });
        return 88;
    }
    ClientDownloadCleanupTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "client_download_cleanup_tests.moc"

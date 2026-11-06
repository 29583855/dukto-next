#include "core/durablereceive.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/transferitems.h"
#include <QJsonDocument>

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdio>
#include <cstdlib>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace {
const QUuid Task("8bab691a-7f4c-430c-b43b-102614cd8fae");
constexpr qint64 SampleBytes = 2 * dukto::StrongBlockBytes + 37;
#ifdef Q_OS_WIN
// 日期：2026-11-06；测试从独立原生句柄取得预期ID，不从被测覆盖函数读取身份。
QByteArray overwriteIdentity(const QString &path) {
    const auto native = QDir::toNativeSeparators(path);
    const auto handle = CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), FILE_READ_ATTRIBUTES,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                    OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        throw dukto::Error(dukto::ExitCode::Disk, "fixture identity open", "test");
    BY_HANDLE_FILE_INFORMATION info;
    const bool read = GetFileInformationByHandle(handle, &info);
    CloseHandle(handle);
    if (!read)
        throw dukto::Error(dukto::ExitCode::Disk, "fixture identity read", "test");
    return QByteArray::number(static_cast<qulonglong>(info.dwVolumeSerialNumber)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexHigh)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexLow));
}
#endif

// 日期：2026-11-04；样本按绝对偏移生成，不使用接收端算法生成期望文件摘要。
QByteArray sample(qint64 offset, qint64 bytes) {
    QByteArray result(static_cast<int>(bytes), '\0');
    for (int index = 0; index < result.size(); ++index)
        result[index] = static_cast<char>((offset + index) * 31 % 251);
    return result;
}

// 日期：2026-11-04；创建真实源和强清单，子进程只重载同一冻结清单与私有日志。
void fixture(const QString &root) {
    if (!QDir().mkpath(root + "/output"))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture directory", "test");
    QFile file(root + "/sample.bin");
    if (!file.open(QIODevice::WriteOnly))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture file", "test");
    for (qint64 offset = 0; offset < SampleBytes; offset += dukto::BufferSize)
        dukto::writeAll(file, sample(offset, qMin(dukto::BufferSize, SampleBytes - offset)));
    file.close();
    dukto::PrivateStore store(root + "/private", true);
    dukto::StrongManifest manifest(store, "source.sqlite", true);
    manifest.scan({root + "/sample.bin"});
}

// 日期：2026-11-04；从恢复的连续块起流式发送，块和尾块均分成至多 256 KiB 片段。
void transmit(dukto::DurableReceive &receiver, quint64 first, qint64 limit = SampleBytes) {
    for (qint64 offset = static_cast<qint64>(first) * dukto::StrongBlockBytes; offset < limit;) {
        const auto length = qMin<qint64>(dukto::BufferSize, limit - offset);
        receiver.write(static_cast<quint64>(offset / dukto::StrongBlockBytes),
                       static_cast<quint32>(offset % dukto::StrongBlockBytes),
                       sample(offset, length));
        offset += length;
    }
}

// 日期：2026-11-04；按绝对块偏移生成片段，允许调用方指定任意块顺序和部分块故障点。
void transmitBlock(dukto::DurableReceive &receiver, quint64 block, qint64 limit = -1) {
    const auto base = static_cast<qint64>(block) * dukto::StrongBlockBytes;
    const auto length = limit < 0 ? qMin(dukto::StrongBlockBytes, SampleBytes - base) : limit;
    for (qint64 offset = 0; offset < length; offset += dukto::BufferSize) {
        const auto bytes = qMin(dukto::BufferSize, length - offset);
        receiver.write(block, static_cast<quint32>(offset), sample(base + offset, bytes));
    }
}

// 日期：2026-11-04；实际子进程在块中/命名前/命名后直接退出，跳过 C++ 析构测试磁盘恢复。
int crashWorker(const QString &root, const QString &mode) {
    dukto::PrivateStore store(root + "/private");
    dukto::StrongManifest manifest(store, "source.sqlite", false);
    dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, root + "/output",
                                   mode.startsWith("overwrite-") ? dukto::ConflictPolicy::Overwrite
                                                                 : dukto::ConflictPolicy::Rename);
    if (mode.startsWith("overwrite-")) {
        receiver.open(1, "sample.bin");
        if (mode == "overwrite-partial") {
            transmit(receiver, 0, dukto::StrongBlockBytes);
            std::_Exit(29);
        }
        transmit(receiver, 0);
        receiver.finish([&]() {
            // 日期：2026-11-05；覆盖前目标也存在，用冻结内容摘要区分原子发布两侧。
            if (receiver.state() != "committing")
                return;
            const auto published =
                dukto::hashFile(root + "/output/sample.bin") == manifest.entry(1).sha256;
            if (published == (mode == "overwrite-after"))
                std::_Exit(29);
        });
        return 30;
    }
    if (mode.startsWith("directory-")) {
        receiver.prepare(1, [&]() {
            // 日期：2026-11-04；目录临时项已存在且意图已保存后，在目录发布前后直接退出。
            const QDir output(root + "/output");
            const bool published = QFileInfo::exists(root + "/output/bundle");
            const bool pending = !output.entryList({"*.dir"}, QDir::Dirs | QDir::Hidden).isEmpty();
            if ((mode == "directory-after" && published) ||
                (mode == "directory-before" && !published && pending))
                std::_Exit(29);
        });
        return 30;
    }
    if (mode == "sparse-partial") {
        receiver.openSparse(1, "sample.bin");
        transmitBlock(receiver, 2);
        transmitBlock(receiver, 1);
        transmitBlock(receiver, 0, dukto::BufferSize);
        std::_Exit(29);
    }
    const auto first = receiver.open(1, "sample.bin");
    if (mode == "partial") {
        transmit(receiver, first, dukto::StrongBlockBytes + dukto::BufferSize);
        std::_Exit(29);
    }
    transmit(receiver, first);
    receiver.finish([&]() {
        // 日期：2026-11-04；摘要和命名前均会调用检查点，仅以日志状态与目录项判定注入时刻。
        if (receiver.state() == "committing" &&
            (QFileInfo::exists(root + "/output/sample.bin") == (mode == "after-rename")))
            std::_Exit(29);
    });
    return 30;
}
} // namespace

class DurableReceiveTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；核验以原接收日志和原生对象为准，不接受同名、同长度或同内容的外部替换。
    void completedReadOnlyVerification() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"));
            receiver.open(1, "sample.bin");
            transmit(receiver, 0);
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        const auto journal = root.filePath("private/receive.sqlite");
        const auto output = root.filePath("output/sample.bin");
        const auto before = dukto::hashFile(journal);
        int checks = 0;
        QString verified;
        dukto::DurableReceive::verifyCompleted(
            store, "receive.sqlite", Task, manifest, root.filePath("output"),
            dukto::ConflictPolicy::Rename,
            [&]() {
                // 日期：2026-11-06；正文重读必须每个固定缓冲调用检查，不能只检查每个文件。
                ++checks;
            },
            [&](quint64 id, const QString &target) {
                // 日期：2026-11-06；观察者只收到已经核对的实际发布路径。
                QCOMPARE(id, quint64(1));
                verified = target;
            });
        QVERIFY(checks > SampleBytes / dukto::BufferSize);
        QCOMPARE(verified, QString("sample.bin"));
        QCOMPARE(dukto::hashFile(journal), before);
        {
            QFile damaged(output);
            QVERIFY(damaged.open(QIODevice::ReadWrite));
            QCOMPARE(damaged.write("!", 1), qint64(1));
        }
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive::verifyCompleted(
                                     store, "receive.sqlite", Task, manifest,
                                     root.filePath("output"), dukto::ConflictPolicy::Rename),
                                 dukto::Error);
        {
            QFile restored(output);
            QVERIFY(restored.open(QIODevice::ReadWrite));
            QCOMPARE(restored.write(sample(0, 1)), qint64(1));
        }
        dukto::DurableReceive::verifyCompleted(store, "receive.sqlite", Task, manifest,
                                               root.filePath("output"),
                                               dukto::ConflictPolicy::Rename);
        const auto saved = root.filePath("output/original.bin");
        QVERIFY(QFile::rename(output, saved));
        QVERIFY(QFile::copy(saved, output));
        QCOMPARE(dukto::hashFile(output), manifest.entry(1).sha256);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive::verifyCompleted(
                                     store, "receive.sqlite", Task, manifest,
                                     root.filePath("output"), dukto::ConflictPolicy::Rename),
                                 dukto::Error);
        QVERIFY(QFile::remove(output));
        QVERIFY(QFile::rename(saved, output));
        QVERIFY(QFile::rename(journal, journal + ".hidden"));
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive::verifyCompleted(
                                     store, "receive.sqlite", Task, manifest,
                                     root.filePath("output"), dukto::ConflictPolicy::Rename),
                                 dukto::Error);
        QVERIFY(!QFile::exists(journal));
        QVERIFY(QFile::rename(journal + ".hidden", journal));
        QCOMPARE(dukto::hashFile(journal), before);
        const auto connections = QSqlDatabase::connectionNames().size();
        for (int iteration = 0; iteration < 8; ++iteration) {
            int checkpoints = 0;
            QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive::verifyCompleted(
                                         store, "receive.sqlite", Task, manifest,
                                         root.filePath("output"), dukto::ConflictPolicy::Rename,
                                         [&]() {
                                             // 日期：2026-11-06；实际进入正文读取后取消，验证异常退栈不遗留数据库连接。
                                             if (++checkpoints >= 5)
                                                 throw dukto::Error(dukto::ExitCode::Cancelled,
                                                                    "cancelled", "test");
                                         }),
                                     dukto::Error);
        }
        QCOMPARE(QSqlDatabase::connectionNames().size(), connections);
        QCOMPARE(dukto::hashFile(journal), before);
    }

    // 日期：2026-11-05；取消、网络与批次授权不归因到文件；冲突及恢复后再次校验失败均保留。
    void itemFailureRecoveryAndScopes() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::TransferTask task;
        task.id = Task;
        task.direction = "upload";
        task.state = "receiving";
        task.entries = 1;
        task.total = SampleBytes;
        task.conflict = dukto::ConflictPolicy::Fail;
        task.manifest = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        const auto journal = "receive-" + Task.toString(QUuid::WithoutBraces) + ".sqlite";
        const auto page = [&]() {
            // 日期：2026-11-05；每次重新建立只读快照，不借用接收器内存状态。
            return dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
        };
        {
            dukto::DurableReceive receiver(store, journal, Task, manifest, root.filePath("output"),
                                           task.conflict);
            for (const auto code : {dukto::ExitCode::Network, dukto::ExitCode::Cancelled,
                                    dukto::ExitCode::Permission}) {
                QVERIFY_EXCEPTION_THROWN(receiver.prepare(1,
                                                          [&]() {
                                                              // 日期：2026-11-05；模拟外部连接/取消/批次权限检查，不能误标成该文件损坏。
                                                              throw dukto::Error(
                                                                  code, "external check", "task");
                                                          }),
                                         dukto::Error);
                QVERIFY(page()["entries"].toArray().first().toObject()["lastFailure"].isNull());
            }
            {
                QFile original(root.filePath("output/sample.bin"));
                QVERIFY(original.open(QIODevice::WriteOnly));
                dukto::writeAll(original, "original");
            }
            QVERIFY_EXCEPTION_THROWN(receiver.open(1, "sample.bin"), dukto::Error);
            auto evidence = page();
            QVERIFY(evidence["failureEvidenceAvailable"].toBool());
            auto failure =
                evidence["entries"].toArray().first().toObject()["lastFailure"].toObject();
            QCOMPARE(failure["code"].toInt(), 4);
            QCOMPARE(failure["phase"].toString(), QString("open"));
            QCOMPARE(failure["stage"].toString(), QString("conflict"));
            QVERIFY(!failure["resolved"].toBool());
            QVERIFY(QFile::remove(root.filePath("output/sample.bin")));
            receiver.open(1, "sample.bin");
            transmit(receiver, 0);
            receiver.finish();
            auto item = page()["entries"].toArray().first().toObject();
            QCOMPARE(item["disposition"].toString(), QString("copied"));
            failure = item["lastFailure"].toObject();
            QVERIFY(failure["resolved"].toBool());
            QCOMPARE(failure["code"].toInt(), 4);
        }
        {
            QFile modified(root.filePath("output/sample.bin"));
            QVERIFY(modified.open(QIODevice::WriteOnly));
            dukto::writeAll(modified, "external change");
        }
        dukto::DurableReceive receiver(store, journal, Task, manifest, root.filePath("output"),
                                       task.conflict);
        QVERIFY_EXCEPTION_THROWN(receiver.open(1, "sample.bin"), dukto::Error);
        const auto failure =
            page()["entries"].toArray().first().toObject()["lastFailure"].toObject();
        QCOMPARE(failure["code"].toInt(), 6);
        QCOMPARE(failure["stage"].toString(), QString("commit"));
        QVERIFY(!failure["resolved"].toBool());
    }

    // 日期：2026-11-05；块摘要失败不确认字节，重开后恢复解决；旧日志只在执行者打开时迁移。
    void itemFailureWriteAndLegacy() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::TransferTask task;
        task.id = Task;
        task.direction = "upload";
        task.state = "receiving";
        task.entries = 1;
        task.total = SampleBytes;
        task.manifest = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        const auto journal = "receive-" + Task.toString(QUuid::WithoutBraces) + ".sqlite";
        {
            dukto::DurableReceive receiver(store, journal, Task, manifest, root.filePath("output"));
            receiver.open(1, "sample.bin");
            bool rejected = false;
            try {
                for (qint64 offset = 0; offset < dukto::StrongBlockBytes;
                     offset += dukto::BufferSize)
                    receiver.write(0, static_cast<quint32>(offset),
                                   QByteArray(dukto::BufferSize, 'x'));
            } catch (const dukto::Error &error) {
                rejected = error.code == dukto::ExitCode::Integrity;
            }
            QVERIFY(rejected);
            const auto page =
                dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
            const auto item = page["entries"].toArray().first().toObject();
            QCOMPARE(item["confirmedBytes"].toString(), QString("0"));
            QCOMPARE(item["lastFailure"].toObject()["phase"].toString(), QString("write"));
        }
        {
            dukto::DurableReceive receiver(store, journal, Task, manifest, root.filePath("output"));
            receiver.open(1, "sample.bin");
            transmit(receiver, 0);
            receiver.finish();
            const auto page =
                dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
            QVERIFY(page["entries"]
                        .toArray()
                        .first()
                        .toObject()["lastFailure"]
                        .toObject()["resolved"]
                        .toBool());
        }
        const auto connection = QUuid::createUuid().toString();
        {
            auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
            database.setDatabaseName(QDir(store.directory()).filePath(journal));
            QVERIFY(database.open());
            QSqlQuery query(database);
            QVERIFY(query.exec("DROP TABLE item_failures"));
            database.close();
        }
        QSqlDatabase::removeDatabase(connection);
        auto page = dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
        QVERIFY(!page["failureEvidenceAvailable"].toBool());
        dukto::DurableReceive receiver(store, journal, Task, manifest, root.filePath("output"));
        receiver.open(1, "sample.bin");
        page = dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
        QVERIFY(page["failureEvidenceAvailable"].toBool());
        QCOMPARE(page["entries"].toArray().first().toObject()["disposition"].toString(),
                 QString("copied"));
    }

    // 日期：2026-11-05；长名称使报文字节预算先于100项触发；查询只读且包含尚无接收记录的项目。
    void itemPageByteBudgetAndBinding() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        dukto::PrivateStore store(root.filePath("state"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const auto emptyHash = QCryptographicHash::hash({}, QCryptographicHash::Sha256);
        for (quint64 sequence = 1; sequence <= 220; ++sequence) {
            dukto::StrongEntry entry{
                sequence, QString::number(sequence).rightJustified(4, '0') + QString(1500, 'x'),
                {},       false,
                0,        emptyHash};
            manifest.append(entry);
        }
        manifest.seal();
        dukto::TransferTask task;
        task.id = Task;
        task.direction = "upload";
        task.state = "transferring";
        task.entries = 220;
        task.manifest = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        quint64 after = 0;
        int count = 0;
        do {
            const auto page =
                dukto::transferItems(store, task, "source.sqlite", root.path(), after);
            const auto entries = page["entries"].toArray();
            QVERIFY(page["available"].toBool());
            QVERIFY(!entries.isEmpty() && entries.size() < 100);
            QVERIFY(QJsonDocument(page).toJson(QJsonDocument::Compact).size() <
                    dukto::next::ControlLimit);
            QCOMPARE(entries.first().toObject()["disposition"].toString(), QString("not-executed"));
            QVERIFY(!page["currentContentVerified"].toBool());
            count += entries.size();
            const auto following = page["after"].toString().toULongLong();
            QVERIFY(following > after);
            after = following;
            if (!page["more"].toBool())
                break;
        } while (true);
        QCOMPARE(count, 220);
        QCOMPARE(after, quint64(220));
        QVERIFY(!dukto::transferItems(store, task, "source.sqlite", root.path(), after)["more"]
                     .toBool());
        QVERIFY_EXCEPTION_THROWN(
            dukto::transferItems(store, task, "source.sqlite", root.path(), 221), dukto::Error);
        task.manifest[0] = char(task.manifest[0] ^ 1);
        QVERIFY_EXCEPTION_THROWN(dukto::transferItems(store, task, "source.sqlite", root.path()),
                                 dukto::Error);
    }

    // 日期：2026-11-05；打开着的真实接收日志可只读查询；策略、任务和目标根不符均拒绝。
    void itemPageActiveAndCompleted() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::TransferTask task;
        task.id = Task;
        task.direction = "upload";
        task.state = "transferring";
        task.entries = 1;
        task.total = SampleBytes;
        task.manifest = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        dukto::DurableReceive receiver(store,
                                       "receive-" + Task.toString(QUuid::WithoutBraces) + ".sqlite",
                                       Task, manifest, root.filePath("output"));
        receiver.open(1, "sample.bin");
        transmit(receiver, 0, dukto::StrongBlockBytes);
        auto page = dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
        auto item = page["entries"].toArray().first().toObject();
        QCOMPARE(item["disposition"].toString(), QString("receiving"));
        QCOMPARE(item["confirmedBytes"].toString(), QString::number(dukto::StrongBlockBytes));
        transmit(receiver, 1);
        receiver.finish();
        page = dukto::transferItems(store, task, "source.sqlite", root.filePath("output"));
        item = page["entries"].toArray().first().toObject();
        QCOMPARE(item["disposition"].toString(), QString("copied"));
        QCOMPARE(item["target"].toString(), QString("sample.bin"));
        QCOMPARE(item["confirmedBytes"].toString(), QString::number(SampleBytes));
        QVERIFY_EXCEPTION_THROWN(dukto::transferItems(store, task, "source.sqlite", root.path()),
                                 dukto::Error);
        task.conflict = dukto::ConflictPolicy::Fail;
        QVERIFY_EXCEPTION_THROWN(
            dukto::transferItems(store, task, "source.sqlite", root.filePath("output")),
            dukto::Error);
    }

    // 日期：2026-11-06；四种公开策略严格解析；大小写及未知值不能隐式改变原选择。
    void conflictPolicyStrictDecode() {
        QVERIFY(dukto::checkedConflictPolicy("rename") == dukto::ConflictPolicy::Rename);
        QVERIFY(dukto::checkedConflictPolicy("fail") == dukto::ConflictPolicy::Fail);
        QVERIFY(dukto::checkedConflictPolicy("overwrite") == dukto::ConflictPolicy::Overwrite);
        QCOMPARE(dukto::checkedConflictPolicy("skip"), dukto::ConflictPolicy::Skip);
        QCOMPARE(dukto::conflictPolicyName(dukto::ConflictPolicy::Overwrite), QString("overwrite"));
        for (const auto &text : QStringList{"", "Fail", "Skip", "Overwrite", "keep-both"})
            QVERIFY_EXCEPTION_THROWN(dukto::checkedConflictPolicy(text), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::conflictPolicyName(static_cast<dukto::ConflictPolicy>(99)),
                                 dukto::Error);
    }

    // 日期：2026-11-05；真实进程退出保留原文件或发布结果，恢复必须幂等；发布后外部改动不能再覆盖。
    void overwriteCrash_data() {
        QTest::addColumn<QString>("mode");
        QTest::addColumn<bool>("externalChange");
        for (const auto &mode :
             QStringList{"overwrite-partial", "overwrite-before", "overwrite-after"})
            QTest::newRow(mode.toLatin1().constData()) << mode << false;
        QTest::newRow("changed-after-publication") << QString("overwrite-after") << true;
    }

    // 日期：2026-11-05；在独立进程中跳过析构，真实重新取得过期预约并重读持久块和原生身份。
    void overwriteCrash() {
        QFETCH(QString, mode);
        QFETCH(bool, externalChange);
        QTemporaryDir root;
        fixture(root.path());
        const auto target = root.filePath("output/sample.bin");
        {
            QFile original(target);
            QVERIFY(original.open(QIODevice::WriteOnly));
            dukto::writeAll(original, "original");
        }
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--crash-worker", root.path(), mode});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 29);
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        const auto expected = manifest.entry(1).sha256;
        QCOMPARE(dukto::hashFile(target),
                 mode == "overwrite-after"
                     ? expected
                     : QCryptographicHash::hash("original", QCryptographicHash::Sha256));
        if (externalChange) {
            QVERIFY(QFile::remove(target));
            QFile replacement(target);
            QVERIFY(replacement.open(QIODevice::WriteOnly));
            dukto::writeAll(replacement, "later-user-file");
        }
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            if (externalChange) {
                try {
                    receiver.open(1, "sample.bin");
                    QFAIL("must not overwrite later file on recovery");
                } catch (const dukto::Error &error) {
                    QVERIFY(error.code == dukto::ExitCode::Integrity);
                }
                QCOMPARE(dukto::hashFile(target),
                         QCryptographicHash::hash("later-user-file", QCryptographicHash::Sha256));
                return;
            }
            const auto first = receiver.open(1, "sample.bin");
            if (mode == "overwrite-partial")
                QCOMPARE(first, quint64(1));
            transmit(receiver, first);
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        QCOMPARE(dukto::hashFile(target), expected);
        {
            dukto::DurableReceive repeated(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            repeated.open(1, "sample.bin");
            QCOMPARE(repeated.finish(), QString("sample.bin"));
        }
        QCOMPARE(QDir(root.filePath("output")).entryList(QDir::Files | QDir::Hidden),
                 QStringList{"sample.bin"});
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive(store, "receive.sqlite", Task, manifest,
                                                       root.filePath("output"),
                                                       dukto::ConflictPolicy::Fail),
                                 dukto::Error);
    }

#ifdef Q_OS_WIN
    // 日期：2026-11-06；每行真实子进程保持一个读句柄，覆盖临时占用、永久占用及等待中的安全边界。
    void overwriteContention_data() {
        QTest::addColumn<QString>("mode");
        for (const auto &mode :
             {"release-target", "release-source", "persistent", "cancel", "readonly", "directory",
              "source-replaced", "source-write-protected", "target-removed"})
            QTest::newRow(mode) << QString(mode);
    }

    // 日期：2026-11-06；不改系统权限和外部进程，只操纵测试自有文件与读句柄；失败时原文件和临时证据均保留。
    void overwriteContention() {
        QFETCH(QString, mode);
        QTemporaryDir root;
        const auto source = root.filePath("incoming.tmp");
        const auto target = root.filePath("original.bin");
        const auto originalHeld = root.filePath("original-held.bin");
        const QByteArray data("new-synchronized-content");
        for (const auto &path : {source, target}) {
            QFile file(path);
            QVERIFY(file.open(QIODevice::WriteOnly));
            dukto::writeAll(file, path == source ? data : QByteArray("original-user-data"));
        }
        const auto identity = overwriteIdentity(source);
        QProcess holder;
        holder.start(QCoreApplication::applicationFilePath(),
                     {"--overwrite-read-lock", mode == "release-source" ? source : target});
        QVERIFY(holder.waitForStarted(3000));
        QVERIFY(holder.waitForReadyRead(3000));
        QCOMPARE(holder.readLine().trimmed(), QByteArray("locked"));
        QElapsedTimer elapsed;
        elapsed.start();
        bool injected = false, writeRefused = false;
        int callbacks = 0;
        dukto::ExitCode code = dukto::ExitCode::Success;
        try {
            dukto::replaceReceivedFile(source, target, identity, [&]() {
                // 日期：2026-11-06；前两次回调只观察；随后原子操作已经因子进程占用失败，才注入等待中的变化。
                ++callbacks;
                if (injected || mode == "persistent" || callbacks < 3 || elapsed.elapsed() < 80)
                    return;
                injected = true;
                if (mode == "cancel")
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel while waiting", "test");
                if (mode == "readonly") {
                    if (!QFile::setPermissions(target, QFile::ReadOwner | QFile::ReadUser))
                        throw dukto::Error(dukto::ExitCode::Disk, "readonly injection", "test");
                } else if (mode == "source-replaced") {
                    if (!QFile::rename(source, root.filePath("verified-source-held.tmp")))
                        throw dukto::Error(dukto::ExitCode::Disk, "source replacement injection",
                                           "test");
                    QFile replacement(source);
                    if (!replacement.open(QIODevice::WriteOnly))
                        throw dukto::Error(dukto::ExitCode::Disk, "replacement create", "test");
                    dukto::writeAll(replacement, "unverified-substitute");
                } else if (mode == "source-write-protected") {
                    const auto native = QDir::toNativeSeparators(source);
                    const auto writer =
                        CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), GENERIC_WRITE,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                    OPEN_EXISTING, 0, nullptr);
                    writeRefused = writer == INVALID_HANDLE_VALUE;
                    if (!writeRefused)
                        CloseHandle(writer);
                }
                holder.write("release\n");
                holder.closeWriteChannel();
                if (!holder.waitForFinished(3000))
                    throw dukto::Error(dukto::ExitCode::Disk, "holder release", "test");
                if (mode == "directory" || mode == "target-removed") {
                    if (!QFile::rename(target, originalHeld) ||
                        (mode == "directory" && !QDir().mkdir(target)))
                        throw dukto::Error(dukto::ExitCode::Disk, "target type injection", "test");
                }
            });
        } catch (const dukto::Error &error) {
            code = error.code;
        }
        const auto duration = elapsed.elapsed();
        if (holder.state() != QProcess::NotRunning) {
            holder.write("release\n");
            holder.closeWriteChannel();
            QVERIFY(holder.waitForFinished(3000));
        }
        QCOMPARE(holder.exitCode(), 0);
        if (mode == "readonly")
            QVERIFY(QFile::setPermissions(target, QFile::ReadOwner | QFile::WriteOwner |
                                                      QFile::ReadUser | QFile::WriteUser));
        QVERIFY2(callbacks > 2, qPrintable(mode));
        QVERIFY2(duration < 2000, qPrintable(QString("%1 took %2ms").arg(mode).arg(duration)));
        const bool success = mode.startsWith("release-") || mode == "source-write-protected" ||
                             mode == "target-removed";
        const auto expected = success                     ? dukto::ExitCode::Success
                              : mode == "cancel"          ? dukto::ExitCode::Cancelled
                              : mode == "source-replaced" ? dukto::ExitCode::Integrity
                              : (mode == "readonly" || mode == "directory")
                                  ? dukto::ExitCode::Permission
                                  : dukto::ExitCode::Disk;
        QCOMPARE(static_cast<int>(code), static_cast<int>(expected));
        if (success) {
            QVERIFY(!QFileInfo::exists(source));
            QCOMPARE(dukto::hashFile(target),
                     QCryptographicHash::hash(data, QCryptographicHash::Sha256));
            if (mode == "source-write-protected")
                QVERIFY(writeRefused);
        } else {
            QCOMPARE(dukto::hashFile(mode == "directory" ? originalHeld : target),
                     QCryptographicHash::hash("original-user-data", QCryptographicHash::Sha256));
            QCOMPARE(dukto::hashFile(mode == "source-replaced"
                                         ? root.filePath("verified-source-held.tmp")
                                         : source),
                     QCryptographicHash::hash(data, QCryptographicHash::Sha256));
            if (mode == "persistent") {
                QVERIFY(duration >= 450);
                // 日期：2026-11-06；永久占用超时仍保留源；释放后同一身份可以再次安全发布。
                dukto::replaceReceivedFile(source, target, identity);
                QCOMPARE(dukto::hashFile(target),
                         QCryptographicHash::hash(data, QCryptographicHash::Sha256));
            }
        }
    }

    // 日期：2026-11-06；集成接收日志验证永久占用返回磁盘错误、释放后重验同一临时文件恢复，不重新传正文。
    void overwriteBusyCommitRecovery() {
        QTemporaryDir root;
        fixture(root.path());
        const auto target = root.filePath("output/sample.bin");
        {
            QFile original(target);
            QVERIFY(original.open(QIODevice::WriteOnly));
            dukto::writeAll(original, "original");
        }
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        QProcess holder;
        holder.start(QCoreApplication::applicationFilePath(), {"--overwrite-read-lock", target});
        QVERIFY(holder.waitForStarted(3000));
        QVERIFY(holder.waitForReadyRead(3000));
        QCOMPARE(holder.readLine().trimmed(), QByteArray("locked"));
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            receiver.open(1, "sample.bin");
            transmit(receiver, 0);
            try {
                receiver.finish();
                QFAIL("persistent read lock must fail within its budget");
            } catch (const dukto::Error &error) {
                QCOMPARE(static_cast<int>(error.code), static_cast<int>(dukto::ExitCode::Disk));
                QCOMPARE(error.stage, QString("commit-busy"));
            }
            QCOMPARE(receiver.state(), QString("committing"));
        }
        QCOMPARE(dukto::hashFile(target),
                 QCryptographicHash::hash("original", QCryptographicHash::Sha256));
        holder.write("release\n");
        holder.closeWriteChannel();
        QVERIFY(holder.waitForFinished(3000));
        QCOMPARE(holder.exitCode(), 0);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            receiver.open(1, "sample.bin");
            QCOMPARE(receiver.state(), QString("completed"));
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        QCOMPARE(dukto::hashFile(target), manifest.entry(1).sha256);
    }
#endif

    // 日期：2026-11-05；提交前取消、目标变为只读或目录均不能覆盖原件，最后一次检查同样执行类型规则。
    void overwritePublicationFailure_data() {
        QTest::addColumn<QString>("mode");
        QTest::newRow("cancel") << QString("cancel");
        QTest::newRow("readonly") << QString("readonly");
        QTest::newRow("directory") << QString("directory");
    }

    // 日期：2026-11-05；完整正文已落临时文件后才注入故障，离线确认原内容和新出现目录均未被删除。
    void overwritePublicationFailure() {
        QFETCH(QString, mode);
        QTemporaryDir root;
        fixture(root.path());
        const auto target = root.filePath("output/sample.bin");
        {
            QFile original(target);
            QVERIFY(original.open(QIODevice::WriteOnly));
            dukto::writeAll(original, "original");
        }
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Overwrite);
        receiver.open(1, "sample.bin");
        transmit(receiver, 0);
        bool injected = false;
        try {
            receiver.finish([&]() {
                // 日期：2026-11-05；只在已持久记下提交意图且原子发布尚未发生时注入一次。
                if (receiver.state() != "committing" || injected)
                    return;
                injected = true;
                if (mode == "cancel")
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel before publication",
                                       "task");
                if (mode == "readonly") {
                    if (!QFile::setPermissions(target, QFile::ReadOwner | QFile::ReadUser))
                        throw dukto::Error(dukto::ExitCode::Disk, "cannot make readonly", "test");
                } else {
                    if (!QFile::rename(target, root.filePath("original-held")) ||
                        !QDir().mkdir(target))
                        throw dukto::Error(dukto::ExitCode::Disk, "cannot create type race",
                                           "test");
                }
            });
            QFAIL("unsafe overwrite publication succeeded");
        } catch (const dukto::Error &error) {
            QVERIFY(injected);
            QVERIFY(error.code ==
                    (mode == "cancel" ? dukto::ExitCode::Cancelled : dukto::ExitCode::Permission));
        }
        if (mode == "readonly")
            QVERIFY(QFile::setPermissions(target, QFile::ReadOwner | QFile::WriteOwner |
                                                      QFile::ReadUser | QFile::WriteUser));
        if (mode == "directory")
            QVERIFY(QFileInfo(target).isDir());
        QCOMPARE(dukto::hashFile(mode == "directory" ? root.filePath("original-held") : target),
                 QCryptographicHash::hash("original", QCryptographicHash::Sha256));
    }

    // 日期：2026-11-05；预约在两个真实进程间生效，旧接收与默认重命名也必须避开活动覆盖目标。
    void targetReservationAcrossProcesses() {
        QTemporaryDir root;
        fixture(root.path());
        const auto target = root.filePath("output/sample.bin");
        QProcess holder;
        holder.start(QCoreApplication::applicationFilePath(), {"--reservation-worker", target});
        QVERIFY(holder.waitForReadyRead(10000));
        QCOMPARE(holder.readLine().trimmed(), QByteArray("locked"));
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive overwrite(store, "blocked.sqlite", Task, manifest,
                                            root.filePath("output"),
                                            dukto::ConflictPolicy::Overwrite);
            QVERIFY_EXCEPTION_THROWN(overwrite.open(1, "sample.bin"), dukto::Error);
        }
        {
            dukto::DurableReceive fail(store, "fail.sqlite", Task, manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Fail);
            fail.open(1, "sample.bin");
            transmit(fail, 0);
            QVERIFY_EXCEPTION_THROWN(fail.finish(), dukto::Error);
        }
        {
            dukto::DurableReceive rename(store, "rename.sqlite", Task, manifest,
                                         root.filePath("output"));
            rename.open(1, "sample.bin");
            transmit(rename, 0);
            QCOMPARE(rename.finish(), QString("sample (2).bin"));
        }
        {
            dukto::IncomingFile legacy(target);
            dukto::writeAll(legacy.device(), "legacy");
            QCOMPARE(QFileInfo(legacy.commit()).fileName(), QString("sample (3).bin"));
        }
        QVERIFY(!QFileInfo::exists(target));
        holder.kill();
        QVERIFY(holder.waitForFinished(10000));
        {
            dukto::TargetReservation takeover(target);
            QVERIFY(takeover.acquired());
            dukto::TargetReservation alias(root.filePath("output/SAMPLE.BIN"));
            QVERIFY(!alias.acquired());
        }
        QCOMPARE(
            QDir(root.filePath("output")).entryList({"*.lock"}, QDir::Files | QDir::Hidden).size(),
            0);
        const auto key = QCryptographicHash::hash("sample.bin", QCryptographicHash::Sha256).toHex();
        const auto collision =
            root.filePath("output/.dukto-target-" + QString::fromLatin1(key) + ".lock");
        {
            QFile unrelated(collision);
            QVERIFY(unrelated.open(QIODevice::WriteOnly));
            dukto::writeAll(unrelated, "unrelated user file");
        }
        {
            dukto::TargetReservation blocked(target);
            QVERIFY(!blocked.acquired());
        }
        QCOMPARE(dukto::hashFile(collision),
                 QCryptographicHash::hash("unrelated user file", QCryptographicHash::Sha256));
    }

    // 日期：2026-11-05；目录复用保留无关项；空文件覆盖后重开保持同一结果，类型不同明确拒绝。
    void overwriteDirectoryAndTypes() {
        QTemporaryDir root;
        QVERIFY(QDir().mkpath(root.filePath("output/bundle/unrelated")));
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "bundle", "", true, 0, {}});
        manifest.append({2, "bundle/empty", "", true, 0, {}});
        manifest.append({3, "bundle/zero", "", false, 0,
                         QCryptographicHash::hash("", QCryptographicHash::Sha256)});
        manifest.seal();
        const auto target = root.filePath("output/bundle/zero");
        {
            QFile original(target);
            QVERIFY(original.open(QIODevice::WriteOnly));
            dukto::writeAll(original, "original");
        }
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            QCOMPARE(receiver.prepare(1), QString("bundle"));
            QCOMPARE(receiver.prepare(2), QString("bundle/empty"));
            receiver.open(3, receiver.prepare(3));
            QCOMPARE(QFileInfo(target).size(), qint64(8));
            QCOMPARE(receiver.finish(), QString("bundle/zero"));
            QCOMPARE(QFileInfo(target).size(), qint64(0));
        }
        {
            dukto::DurableReceive repeated(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            QCOMPARE(repeated.prepare(1), QString("bundle"));
            QCOMPARE(repeated.prepare(2), QString("bundle/empty"));
            repeated.open(3, "bundle/zero");
            QCOMPARE(repeated.finish(), QString("bundle/zero"));
        }
        QVERIFY(QDir(root.filePath("output/bundle/unrelated")).exists());
        QVERIFY(QFile::remove(target));
        QVERIFY(QDir().mkdir(target));
        {
            dukto::DurableReceive receiver(store, "different.sqlite", QUuid::createUuid(), manifest,
                                           root.filePath("output"),
                                           dukto::ConflictPolicy::Overwrite);
            receiver.prepare(1);
            QVERIFY_EXCEPTION_THROWN(receiver.open(3, "bundle/zero"), dukto::Error);
        }
        QVERIFY(QDir().rename(root.filePath("output/bundle"), root.filePath("output/held")));
        {
            QFile original(root.filePath("output/bundle"));
            QVERIFY(original.open(QIODevice::WriteOnly));
            dukto::writeAll(original, "original");
        }
        dukto::DurableReceive receiver(store, "types.sqlite", QUuid::createUuid(), manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Overwrite);
        QVERIFY_EXCEPTION_THROWN(receiver.prepare(1), dukto::Error);
    }

    // 日期：2026-11-05；同名普通文件和目录均在创建临时数据前失败，原内容及名称完整保留。
    void failExistingTarget() {
        for (const bool directory : {false, true}) {
            QTemporaryDir root;
            fixture(root.path());
            const auto target = root.filePath("output/sample.bin");
            if (directory)
                QVERIFY(QDir().mkdir(target));
            else {
                QFile original(target);
                QVERIFY(original.open(QIODevice::WriteOnly));
                dukto::writeAll(original, "original");
            }
            dukto::PrivateStore store(root.filePath("private"));
            dukto::StrongManifest manifest(store, "source.sqlite", false);
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"), dukto::ConflictPolicy::Fail);
            try {
                receiver.open(1, receiver.prepare(1));
                QFAIL("existing target accepted");
            } catch (const dukto::Error &error) {
                QVERIFY(error.code == dukto::ExitCode::Permission);
                QCOMPARE(error.stage, QString("conflict"));
            }
            QCOMPARE(QDir(root.filePath("output"))
                         .entryList(QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden),
                     QStringList{"sample.bin"});
            if (!directory) {
                QFile original(target);
                QVERIFY(original.open(QIODevice::ReadOnly));
                QCOMPARE(original.readAll(), QByteArray("original"));
            }
        }
    }

    // 日期：2026-11-05；非默认日志不能作为旧默认任务恢复；成功结果重开后仍为同一文件而非自身冲突。
    void failBindingAndCompletedRecovery() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"), dukto::ConflictPolicy::Fail);
            transmit(receiver, receiver.open(1, receiver.prepare(1)));
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        QVERIFY_EXCEPTION_THROWN(
            dukto::DurableReceive(store, "receive.sqlite", Task, manifest, root.filePath("output")),
            dukto::Error);
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Fail);
        receiver.openSparse(1, receiver.prepare(1));
        QCOMPARE(receiver.state(), QString("completed"));
        QCOMPARE(receiver.finish(), QString("sample.bin"));
        QCOMPARE(dukto::hashFile(root.filePath("output/sample.bin")), manifest.entry(1).sha256);
        QCOMPARE(QDir(root.filePath("output")).entryList(QDir::Files | QDir::Hidden),
                 QStringList{"sample.bin"});
    }

    // 日期：2026-11-05；在提交意图写入后真实创建竞争文件，原子不覆盖失败不得尝试带后缀提交。
    void failFilePublicationRace() {
        QTemporaryDir root;
        fixture(root.path());
        dukto::PrivateStore store(root.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Fail);
        transmit(receiver, receiver.open(1, receiver.prepare(1)));
        bool injected = false;
        try {
            receiver.finish([&]() {
                // 日期：2026-11-05；仅在持久提交意图之后插入竞争，确实经过原子发布裁决。
                if (!injected && receiver.state() == "committing") {
                    QFile competitor(root.filePath("output/sample.bin"));
                    if (!competitor.open(QIODevice::WriteOnly | QIODevice::NewOnly))
                        throw dukto::Error(dukto::ExitCode::Disk, "race fixture", "test");
                    dukto::writeAll(competitor, "competitor");
                    injected = true;
                }
            });
            QFAIL("publication conflict accepted");
        } catch (const dukto::Error &error) {
            QVERIFY(error.code == dukto::ExitCode::Permission);
            QCOMPARE(error.stage, QString("conflict"));
        }
        QVERIFY(injected);
        QFile competitor(root.filePath("output/sample.bin"));
        QVERIFY(competitor.open(QIODevice::ReadOnly));
        QCOMPARE(competitor.readAll(), QByteArray("competitor"));
        QVERIFY(!QFileInfo::exists(root.filePath("output/sample (2).bin")));
    }

    // 日期：2026-11-05；目录在准备时及发布竞争时均失败，不能合并已有目录或改用新后缀目录。
    void failDirectoryPublicationRace() {
        QTemporaryDir root;
        QVERIFY(QDir().mkdir(root.filePath("output")));
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "bundle", "", true, 0, {}});
        manifest.seal();
        bool injected = false;
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           root.filePath("output"), dukto::ConflictPolicy::Fail);
            try {
                receiver.prepare(1, [&]() {
                    // 日期：2026-11-05；临时目录存在才建立竞争者，防止测试只覆盖早期存在性判断。
                    if (!injected && !QDir(root.filePath("output"))
                                          .entryList({"*.dir"}, QDir::Dirs | QDir::Hidden)
                                          .isEmpty()) {
                        if (!QDir().mkpath(root.filePath("output/bundle/preserved")))
                            throw dukto::Error(dukto::ExitCode::Disk, "directory race fixture",
                                               "test");
                        injected = true;
                    }
                });
                QFAIL("directory conflict accepted");
            } catch (const dukto::Error &error) {
                QCOMPARE(error.stage, QString("conflict"));
            }
        }
        QVERIFY(injected);
        QVERIFY(QDir(root.filePath("output/bundle/preserved")).exists());
        QVERIFY(!QDir(root.filePath("output/bundle (2)")).exists());
        dukto::DurableReceive receiver(store, "fresh.sqlite", QUuid::createUuid(), manifest,
                                       root.filePath("output"), dukto::ConflictPolicy::Fail);
        QVERIFY_EXCEPTION_THROWN(receiver.prepare(1), dukto::Error);
    }

    // 日期：2026-11-04；16 文件共用日志交错写入，游标切换保留部分摘要，第 17 个句柄明确限流。
    void concurrentFilesAndWindow() {
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const qint64 bytes = 128 * 1024;
        for (quint64 id = 1; id <= 17; ++id) {
            const auto name = QString("item-%1").arg(id, 2, 10, QLatin1Char('0'));
            const auto sha = QCryptographicHash::hash(QByteArray(bytes, static_cast<char>(id)),
                                                      QCryptographicHash::Sha256);
            manifest.append({id, name, "", false, bytes, sha});
            manifest.appendBlock(id, 0, bytes, sha);
        }
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            for (quint64 id = 1; id <= 16; ++id) {
                receiver.openConcurrent(id, manifest.entry(id).relative);
                receiver.write(0, 0, QByteArray(bytes / 2, static_cast<char>(id)));
            }
            QVERIFY_EXCEPTION_THROWN(receiver.openConcurrent(17, manifest.entry(17).relative),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.closeCurrent(), dukto::Error);
            for (quint64 id = 1; id <= 16; ++id) {
                receiver.activate(id);
                receiver.write(0, bytes / 2, QByteArray(bytes / 2, static_cast<char>(id)));
                QCOMPARE(receiver.confirmed(), bytes);
            }
            receiver.activate(1);
            QCOMPARE(receiver.finish(), manifest.entry(1).relative);
            receiver.closeCurrent();
            receiver.openConcurrent(17, manifest.entry(17).relative);
            receiver.write(0, 0, QByteArray(bytes, 17));
            for (quint64 id = 17; id > 1; --id) {
                receiver.activate(id);
                QCOMPARE(receiver.finish(), manifest.entry(id).relative);
                receiver.closeCurrent();
            }
        }
        dukto::DurableReceive repeated(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        for (quint64 id = 1; id <= 17; ++id) {
            const auto entry = manifest.entry(id);
            QCOMPARE(repeated.openSparse(id, entry.relative), quint64(1));
            QCOMPARE(repeated.finish(), entry.relative);
            QCOMPARE(dukto::hashFile(temporary.filePath("output/" + entry.relative)), entry.sha256);
        }
        QCOMPARE(QDir(temporary.filePath("output")).entryList(QDir::Files).size(), 17);
    }

    // 日期：2026-11-04；非前缀块跨进程退出后独立重读，坏块只失去自身检查点，尾块继续保留。
    void sparseCrashAndRepair() {
        QTemporaryDir temporary;
        fixture(temporary.path());
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--crash-worker", temporary.path(), "sparse-partial"});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 29);
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.openSparse(1, "sample.bin"), quint64(0));
            QCOMPARE(receiver.confirmed(), dukto::StrongBlockBytes + 37);
            QVERIFY(!receiver.hasBlock(0));
            QVERIFY(receiver.hasBlock(1));
            QVERIFY(receiver.hasBlock(2));
            QVERIFY_EXCEPTION_THROWN(receiver.write(2, 0, sample(2 * dukto::StrongBlockBytes, 37)),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.finish(), dukto::Error);
        }
        const auto parts =
            QDir(temporary.filePath("output")).entryList({"*.part"}, QDir::Files | QDir::Hidden);
        QCOMPARE(parts.size(), 1);
        QFile damaged(temporary.filePath("output/" + parts[0]));
        QVERIFY(damaged.open(QIODevice::ReadWrite));
        QVERIFY(damaged.seek(dukto::StrongBlockBytes));
        QCOMPARE(damaged.write("broken"), qint64(6));
        damaged.close();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.openSparse(1, "sample.bin"), quint64(0));
            QCOMPARE(receiver.confirmed(), qint64(37));
            QVERIFY(!receiver.hasBlock(0));
            QVERIFY(!receiver.hasBlock(1));
            QVERIFY(receiver.hasBlock(2));
            // 日期：2026-11-04；两个块逐片交错，不能以聚合 confirmed 字节数作为写入文件偏移。
            for (qint64 offset = 0; offset < dukto::StrongBlockBytes; offset += dukto::BufferSize) {
                receiver.write(1, static_cast<quint32>(offset),
                               sample(dukto::StrongBlockBytes + offset, dukto::BufferSize));
                receiver.write(0, static_cast<quint32>(offset), sample(offset, dukto::BufferSize));
            }
            QCOMPARE(receiver.confirmed(), SampleBytes);
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        QCOMPARE(dukto::hashFile(temporary.filePath("output/sample.bin")),
                 manifest.entry(1).sha256);
        dukto::DurableReceive repeated(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        QCOMPARE(repeated.openSparse(1, "sample.bin"), quint64(3));
        QCOMPARE(repeated.finish(), QString("sample.bin"));
        QCOMPARE(QDir(temporary.filePath("output")).entryList(QDir::Files | QDir::Hidden),
                 QStringList{"sample.bin"});
    }

    // 日期：2026-11-04；16 个活动块仅保留增量哈希；第 17 个活动块及块内乱序必须明确拒绝。
    void sparsePartialLimit() {
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const auto sha = QCryptographicHash::hash("fixture", QCryptographicHash::Sha256);
        manifest.append({1, "large.bin", "", false, 17 * dukto::StrongBlockBytes, sha});
        for (quint64 block = 0; block < 17; ++block)
            manifest.appendBlock(1, block, dukto::StrongBlockBytes, sha);
        manifest.seal();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        receiver.openSparse(1, "large.bin");
        for (quint64 block = 0; block < 16; ++block)
            receiver.write(block, 0, "x");
        QVERIFY_EXCEPTION_THROWN(receiver.write(16, 0, "x"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(receiver.write(3, 0, "x"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(receiver.write(3, 2, "x"), dukto::Error);
        QCOMPARE(receiver.confirmed(), qint64(0));
        QVERIFY_EXCEPTION_THROWN(receiver.finish(), dukto::Error);
    }

    // 日期：2026-11-04；三个真实进程退出点均可恢复同一文件，重复确认不生成副本。
    void processCrash_data() {
        QTest::addColumn<QString>("mode");
        QTest::newRow("partial-block") << QString("partial");
        QTest::newRow("before-rename") << QString("before-rename");
        QTest::newRow("after-rename") << QString("after-rename");
    }

    // 日期：2026-11-04；恢复重读已确认块，提交恢复必须返回同一最终名称和完整摘要。
    void processCrash() {
        QFETCH(QString, mode);
        QTemporaryDir temporary;
        fixture(temporary.path());
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--crash-worker", temporary.path(), mode});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 29);
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            const auto first = receiver.open(1, "sample.bin");
            QCOMPARE(first, mode == "partial" ? quint64(1) : quint64(3));
            if (mode == "partial") {
                QCOMPARE(receiver.confirmed(), dukto::StrongBlockBytes);
                transmit(receiver, first);
            }
            QCOMPARE(receiver.finish(), QString("sample.bin"));
            QCOMPARE(receiver.state(), QString("completed"));
            QCOMPARE(receiver.confirmed(), SampleBytes);
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.open(1, "sample.bin"), quint64(3));
            QCOMPARE(receiver.finish(), QString("sample.bin"));
        }
        QCOMPARE(dukto::hashFile(temporary.filePath("output/sample.bin")),
                 manifest.entry(1).sha256);
        QCOMPARE(QDir(temporary.filePath("output")).entryList(QDir::Files | QDir::Hidden),
                 QStringList{"sample.bin"});
    }

    // 日期：2026-11-04；坏片段不能确认，错误检查点回退到首个损坏块且保留原文件。
    void corruptBlockAndKeepBoth() {
        QTemporaryDir temporary;
        fixture(temporary.path());
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.open(1, "sample.bin"), quint64(0));
            QVERIFY_EXCEPTION_THROWN(receiver.write(0, 1, "x"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.write(0, 0, QByteArray(dukto::BufferSize + 1, 'x')),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.finish(), dukto::Error);
            for (int index = 0; index < 15; ++index)
                receiver.write(0, index * dukto::BufferSize, QByteArray(dukto::BufferSize, 'z'));
            QVERIFY_EXCEPTION_THROWN(
                receiver.write(0, 15 * dukto::BufferSize, QByteArray(dukto::BufferSize, 'z')),
                dukto::Error);
            QCOMPARE(receiver.confirmed(), qint64(0));
            transmit(receiver, 0, dukto::StrongBlockBytes);
            QCOMPARE(receiver.confirmed(), dukto::StrongBlockBytes);
            QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive another(store, "receive.sqlite", Task,
                                                                   manifest,
                                                                   temporary.filePath("output")),
                                     dukto::Error);
        }
        const auto parts =
            QDir(temporary.filePath("output")).entryList({"*.part"}, QDir::Files | QDir::Hidden);
        QCOMPARE(parts.size(), 1);
        QFile damaged(temporary.filePath("output/" + parts[0]));
        QVERIFY(damaged.open(QIODevice::ReadWrite));
        QCOMPARE(damaged.write("bad", 3), qint64(3));
        damaged.close();
        QFile original(temporary.filePath("output/sample.bin"));
        QVERIFY(original.open(QIODevice::WriteOnly));
        QCOMPARE(original.write("original"), qint64(8));
        original.close();
        QString committed;
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.open(1, "sample.bin"), quint64(0));
            QCOMPARE(receiver.confirmed(), qint64(0));
            transmit(receiver, 0);
            committed = receiver.finish();
            QVERIFY(committed != "sample.bin");
        }
        QCOMPARE(dukto::hashFile(temporary.filePath("output/" + committed)),
                 manifest.entry(1).sha256);
        QVERIFY(original.open(QIODevice::ReadOnly));
        QCOMPARE(original.readAll(), QByteArray("original"));
        original.close();
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        receiver.open(1, "sample.bin");
        QCOMPARE(receiver.finish(), committed);
        QCOMPARE(QDir(temporary.filePath("output")).entryList(QDir::Files).size(), 2);
    }

    // 日期：2026-11-04；空文件仍执行强摘要、提交日志和幂等确认；不同任务/路径拒绝复用。
    void emptyAndBinding() {
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "empty.sqlite", true);
        manifest.append(
            {1, "empty", "", false, 0, QCryptographicHash::hash("", QCryptographicHash::Sha256)});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.open(1, QStringLiteral("目录/empty")), quint64(0));
            QCOMPARE(receiver.finish(), QStringLiteral("目录/empty"));
            QVERIFY_EXCEPTION_THROWN(receiver.write(0, 0, "x"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(receiver.open(1, "changed"), dukto::Error);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive receiver(store, "receive.sqlite",
                                                                QUuid::createUuid(), manifest,
                                                                temporary.filePath("output")),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::DurableReceive receiver(store, "../outside", Task, manifest,
                                                                temporary.filePath("output")),
                                 dukto::Error);
    }
    // 日期：2026-11-04；完成文件换成相同内容的新原生对象时仍拒绝，摘要不能冒认提交身份。
    void committedReplacement() {
        QTemporaryDir temporary;
        fixture(temporary.path());
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            receiver.open(1, "sample.bin");
            transmit(receiver, 0);
            receiver.finish();
        }
        const auto path = temporary.filePath("output/sample.bin");
        QVERIFY(QFile::rename(path, temporary.filePath("output/held-original.bin")));
        QVERIFY(QFile::copy(temporary.filePath("sample.bin"), path));
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        QVERIFY_EXCEPTION_THROWN(receiver.open(1, "sample.bin"), dukto::Error);
        QVERIFY(!QFile::exists(temporary.filePath("output/sample (2).bin")));
    }

    // 日期：2026-11-04；同一磁盘日志支持多文件和目录映射，各文件不互用检查点。
    void multipleFilesAndCancellation() {
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        const auto sha = QCryptographicHash::hash("abc", QCryptographicHash::Sha256);
        manifest.append({1, "bundle", "", true, 0, {}});
        manifest.append({2, "bundle/a", "", false, 3, sha});
        manifest.appendBlock(2, 0, 3, sha);
        manifest.append({3, "bundle/b", "", false, 0,
                         QCryptographicHash::hash("", QCryptographicHash::Sha256)});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QVERIFY_EXCEPTION_THROWN(receiver.open(1, "bundle"), dukto::Error);
            QCOMPARE(receiver.prepare(1), QString("bundle"));
            QCOMPARE(receiver.prepare(2), QString("bundle/a"));
            receiver.open(2, "bundle/a");
            QVERIFY_EXCEPTION_THROWN(
                receiver.write(0, 0, "abc",
                               []() {
                                   // 日期：2026-11-04；取消/授权检查失败必须先于写入和确认。
                                   throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
                               }),
                dukto::Error);
            QCOMPARE(receiver.confirmed(), qint64(0));
            receiver.write(0, 0, "abc");
            QCOMPARE(receiver.finish(), QString("bundle/a"));
            receiver.open(3, "bundle/b");
            QCOMPARE(receiver.finish(), QString("bundle/b"));
        }
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        QCOMPARE(receiver.prepare(1), QString("bundle"));
        QCOMPARE(receiver.prepare(3), QString("bundle/b"));
        receiver.open(2, "bundle/a");
        QCOMPARE(receiver.finish(), QString("bundle/a"));
        receiver.open(3, "bundle/b");
        QCOMPARE(receiver.finish(), QString("bundle/b"));
    }

    // 日期：2026-11-04；Windows 固定根拒绝改名；POSIX 改名后写入必须拒绝替换根。
    void rootReplacement() {
        QTemporaryDir temporary;
        fixture(temporary.path());
        dukto::PrivateStore store(temporary.filePath("private"));
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        receiver.open(1, "sample.bin");
#ifdef Q_OS_WIN
        QVERIFY(!QDir().rename(temporary.filePath("output"), temporary.filePath("moved")));
#else
        QVERIFY(QDir().rename(temporary.filePath("output"), temporary.filePath("moved")));
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        QVERIFY_EXCEPTION_THROWN(receiver.write(0, 0, sample(0, dukto::BufferSize)), dukto::Error);
        QVERIFY(QDir(temporary.filePath("output")).entryList(QDir::Files | QDir::Hidden).isEmpty());
#endif
    }

    // 日期：2026-11-04；真实进程退出后复用同一目录预约，不重新选择后缀或丢失空目录。
    void directoryCrash_data() {
        QTest::addColumn<QString>("mode");
        QTest::newRow("before") << QString("directory-before");
        QTest::newRow("after") << QString("directory-after");
    }

    // 日期：2026-11-04；目录发布前后进程退出均从持久原生身份恢复，同名原目录保留。
    void directoryCrash() {
        QFETCH(QString, mode);
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("bundle/empty")));
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        {
            dukto::StrongManifest manifest(store, "source.sqlite", true);
            manifest.scan({temporary.filePath("bundle")});
        }
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--crash-worker", temporary.path(), mode});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 29);
        dukto::StrongManifest manifest(store, "source.sqlite", false);
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.prepare(1), QString("bundle"));
            QCOMPARE(receiver.prepare(2), QString("bundle/empty"));
        }
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        QCOMPARE(receiver.prepare(1), QString("bundle"));
        QCOMPARE(receiver.prepare(2), QString("bundle/empty"));
        QVERIFY(QDir(temporary.filePath("output/bundle/empty")).exists());
        QCOMPARE(QDir(temporary.filePath("output"))
                     .entryList(QDir::Dirs | QDir::NoDotAndDotDot | QDir::Hidden),
                 QStringList{"bundle"});
    }

    // 日期：2026-11-04；冲突目录保留双方，子项跟随持久映射；目录内容增长不改变原生身份。
    void directoryConflictAndReplacement() {
        QTemporaryDir temporary;
        QVERIFY(QDir().mkpath(temporary.filePath("output/bundle/original")));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "bundle", "", true, 0, {}});
        manifest.append({2, "bundle/empty", "", true, 0, {}});
        manifest.seal();
        QString mapped;
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QVERIFY_EXCEPTION_THROWN(receiver.prepare(2), dukto::Error);
            mapped = receiver.prepare(1);
            QVERIFY(mapped != "bundle");
            QCOMPARE(receiver.prepare(2), mapped + "/empty");
            QCOMPARE(receiver.prepare(1), mapped);
        }
        QVERIFY(QDir(temporary.filePath("output/bundle/original")).exists());
        {
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                           temporary.filePath("output"));
            QCOMPARE(receiver.prepare(1), mapped);
            QCOMPARE(receiver.prepare(2), mapped + "/empty");
        }
        QVERIFY(QDir().rename(temporary.filePath("output/" + mapped),
                              temporary.filePath("output/held")));
        QVERIFY(QDir().mkpath(temporary.filePath("output/" + mapped)));
        dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                       temporary.filePath("output"));
        QVERIFY_EXCEPTION_THROWN(receiver.prepare(1), dukto::Error);
    }
};

// 日期：2026-11-04；同一测试二进制提供真实崩溃子进程模式，其余参数原样交给 QtTest。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto arguments = application.arguments();
#ifdef Q_OS_WIN
    if (arguments.size() == 3 && arguments[1] == "--overwrite-read-lock") {
        // 日期：2026-11-06；子进程真实持有普通文件读句柄，收到测试父进程的输入后才释放。
        const auto native = QDir::toNativeSeparators(arguments[2]);
        const auto handle =
            CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), GENERIC_READ, FILE_SHARE_READ,
                        nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (handle == INVALID_HANDLE_VALUE)
            return 35;
        std::printf("locked\n");
        std::fflush(stdout);
        std::getchar();
        return CloseHandle(handle) ? 0 : 36;
    }
#endif
    if (arguments.size() == 3 && arguments[1] == "--reservation-worker") {
        try {
            dukto::TargetReservation reservation(arguments[2]);
            if (!reservation.acquired())
                return 33;
            std::printf("locked\n");
            std::fflush(stdout);
            std::getchar();
            return 0;
        } catch (...) {
            return 34;
        }
    }
    if (arguments.size() == 4 && arguments[1] == "--crash-worker") {
        try {
            return crashWorker(arguments[2], arguments[3]);
        } catch (...) {
            return 31;
        }
    }
    DurableReceiveTests tests;
    try {
        return QTest::qExec(&tests, argc, argv);
    } catch (const dukto::Error &error) {
        const auto diagnostic = (error.stage + ": " + error.message).toUtf8();
        std::fprintf(stderr, "%s\n", diagnostic.constData());
        return 32;
    }
}

#include "durable_receive_tests.moc"

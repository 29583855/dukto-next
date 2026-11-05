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
#include <QTemporaryDir>
#include <QtTest>
#include <cstdio>
#include <cstdlib>

namespace {
const QUuid Task("8bab691a-7f4c-430c-b43b-102614cd8fae");
constexpr qint64 SampleBytes = 2 * dukto::StrongBlockBytes + 37;

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
    dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, root + "/output");
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

    // 日期：2026-11-05；未知值不能隐式保留双方，仍未开放的跳过/覆盖也明确报参数错误。
    void conflictPolicyStrictDecode() {
        QVERIFY(dukto::checkedConflictPolicy("rename") == dukto::ConflictPolicy::Rename);
        QVERIFY(dukto::checkedConflictPolicy("fail") == dukto::ConflictPolicy::Fail);
        for (const auto &text : QStringList{"", "Fail", "skip", "overwrite", "keep-both"})
            QVERIFY_EXCEPTION_THROWN(dukto::checkedConflictPolicy(text), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::conflictPolicyName(static_cast<dukto::ConflictPolicy>(99)),
                                 dukto::Error);
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

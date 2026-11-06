#include "core/durablereceive.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/transferitems.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>

namespace {
const QUuid Task("21111111-2222-4333-8444-555555555555");
const QString Journal = "receive-" + Task.toString(QUuid::WithoutBraces) + ".sqlite";

// 日期：2026-11-06；独立原字节摘要固定期望，不从查询或落盘结果反推答案。
QByteArray sha(const QByteArray &bytes) {
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

// 日期：2026-11-06；只写临时测试目录内的真实样本，写入失败不能作为空文件继续验收。
void write(const QString &path, const QByteArray &bytes) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
}

// 日期：2026-11-06；测试自有数据库的变更用绑定参数，不借助平台专有SQLite命令行工具。
void execute(QSqlDatabase database, const QString &sql, const QVariantList &values = {}) {
    QSqlQuery query(database);
    query.prepare(sql);
    for (const auto &value : values)
        query.addBindValue(value);
    if (!query.exec())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture SQL", "test");
}

// 日期：2026-11-06；独立连接修改测试私有日志并立即关闭，查询必须重新读取真实持久状态。
void change(const QString &path, const std::function<void(QSqlDatabase)> &operation) {
    const auto connection = QUuid::createUuid().toString();
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setDatabaseName(path);
        if (!database.open())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture database", "test");
        operation(database);
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
}

// 日期：2026-11-06；按原规范编码修改一个测试证据，避免用坏JSON掩盖字段绑定校验。
void changeSpec(QSqlDatabase database, const QString &table, quint64 id,
                const std::function<void(QJsonObject &)> &operation) {
    QSqlQuery query(database);
    const bool binding = table == "binding";
    query.prepare("SELECT spec FROM " + table + (binding ? "" : " WHERE id=?"));
    if (!binding)
        query.addBindValue(static_cast<qlonglong>(id));
    if (!query.exec() || !query.next())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture spec", "test");
    auto value = dukto::next::parseControl(query.value(0).toByteArray());
    query.finish();
    operation(value);
    QVariantList values{dukto::next::encodeControl(value)};
    if (!binding)
        values.append(static_cast<qlonglong>(id));
    execute(database, "UPDATE " + table + " SET spec=?" + (binding ? "" : " WHERE id=?"), values);
}

// 日期：2026-11-06；任务身份直接绑定已冻结清单，测试不依赖公开客户端参数。
dukto::TransferTask task(dukto::StrongManifest &manifest, const QString &state = "completed") {
    dukto::TransferTask value;
    value.id = Task;
    value.direction = "upload";
    value.state = state;
    value.conflict = dukto::ConflictPolicy::Skip;
    const auto info = manifest.summary();
    value.manifest = QByteArray::fromHex(info["sha256"].toString().toLatin1());
    value.entries = info["entries"].toString().toLongLong();
    value.total = info["bytes"].toString().toLongLong();
    return value;
}

// 日期：2026-11-06；真实接收生成复制、目录子树跳过、已有文件和晚期冲突，含空文件及未执行尾项。
void fixture(dukto::PrivateStore &store, dukto::StrongManifest &manifest, const QString &output,
             bool complete = true) {
    if (!QDir().mkpath(output + "/b-dir"))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture directory", "test");
    write(output + "/b-dir/keep", "original directory data");
    write(output + "/c-old", "original");
    const QStringList paths{"a-copy", "b-dir",    "b-dir/missing",  "b-dir/missing/leaf", "c-old",
                            "d-late", "e-newdir", "e-newdir/empty", "z-unexecuted"};
    for (int index = 0; index < paths.size(); ++index) {
        const bool directory = index == 1 || index == 2 || index == 6;
        const bool empty = index == 7;
        const auto id = static_cast<quint64>(index + 1);
        manifest.append({id,
                         paths[index],
                         {},
                         directory,
                         directory || empty ? 0 : 3,
                         directory ? QByteArray() : sha(empty ? QByteArray() : QByteArray("abc"))});
        if (!directory && !empty)
            manifest.appendBlock(id, 0, 3, sha("abc"));
    }
    manifest.seal();
    dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                   dukto::ConflictPolicy::Skip);
    for (quint64 id = 1; id <= static_cast<quint64>(complete ? 9 : 8); ++id) {
        const auto entry = manifest.entry(id);
        const auto prepared = receiver.prepareDisposition(id);
        if (prepared.skipped || entry.directory)
            continue;
        receiver.openDisposition(id, prepared.path);
        if (entry.bytes)
            receiver.write(0, 0, "abc");
        if (id == 6)
            write(output + "/d-late", "late original");
        const auto result = receiver.finishDisposition();
        if (result.skipped != (id == 6))
            throw dukto::Error(dukto::ExitCode::Integrity, "fixture disposition", "test");
        receiver.closeCurrent();
    }
}

// 日期：2026-11-06；从正式只读分页入口取得证据，确认查询不改变清单或接收日志原字节。
QJsonObject page(dukto::PrivateStore &store, dukto::StrongManifest &manifest, const QString &output,
                 const QString &state = "completed", quint64 after = 0) {
    const auto journal = QDir(store.directory()).filePath(Journal);
    const auto source = QDir(store.directory()).filePath("source.sqlite");
    const auto before = dukto::hashFile(journal);
    const auto sourceBefore = dukto::hashFile(source);
    const auto result =
        dukto::transferItems(store, task(manifest, state), "source.sqlite", output, after);
    quint64 expectedId = after;
    for (const auto &value : result["entries"].toArray()) {
        // 日期：2026-11-06；真实服务输出须通过共用客户端解析，不只逐字段核对测试期望。
        dukto::validateTransferItem(value.toObject(), dukto::ConflictPolicy::Skip, ++expectedId);
    }
    if (dukto::hashFile(journal) != before || dukto::hashFile(source) != sourceBefore)
        throw dukto::Error(dukto::ExitCode::Integrity, "query wrote evidence", "test");
    return result;
}
} // namespace

class TransferItemsTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；正常复制与显式skip结果可解码，跳过字节仍为零确认字节。
    void wireDisposition() {
        const auto copied = QJsonObject{{"id", "1"},
                                        {"path", "tree/copied"},
                                        {"type", "file"},
                                        {"bytes", "3"},
                                        {"sha256", QString::fromLatin1(sha("abc").toHex())},
                                        {"target", "tree/copied"},
                                        {"disposition", "copied"},
                                        {"confirmedBytes", "3"}};
        dukto::validateTransferItem(copied, dukto::ConflictPolicy::Rename, 1);
        auto skippedRoot = copied;
        skippedRoot["disposition"] = "skipped";
        skippedRoot["confirmedBytes"] = "0";
        skippedRoot["skippedRoot"] = "1";
        dukto::validateTransferItem(skippedRoot, dukto::ConflictPolicy::Skip, 1);
        auto child = skippedRoot;
        child["id"] = "2";
        child["path"] = "tree/child";
        child["target"] = "tree/child";
        child["skippedRoot"] = "1";
        dukto::validateTransferItem(child, dukto::ConflictPolicy::Skip, 2);
        QVERIFY_EXCEPTION_THROWN(
            dukto::validateTransferItem(skippedRoot, dukto::ConflictPolicy::Rename, 1),
            dukto::Error);
        auto alteredTarget = skippedRoot;
        alteredTarget["target"] = "other";
        QVERIFY_EXCEPTION_THROWN(
            dukto::validateTransferItem(alteredTarget, dukto::ConflictPolicy::Skip, 1),
            dukto::Error);
        auto alteredRoot = child;
        alteredRoot["skippedRoot"] = "3";
        QVERIFY_EXCEPTION_THROWN(
            dukto::validateTransferItem(alteredRoot, dukto::ConflictPolicy::Skip, 2), dukto::Error);
        auto forgedCopy = copied;
        forgedCopy["skippedRoot"] = "1";
        QVERIFY_EXCEPTION_THROWN(
            dukto::validateTransferItem(forgedCopy, dukto::ConflictPolicy::Skip, 1), dukto::Error);
    }

    // 日期：2026-11-06；删掉整个目标树后仍返回原处置，跳过字节不冒充已复制确认。
    void mixedDeletedHistory() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const auto output = temporary.filePath("output");
        fixture(store, manifest, output);
        QVERIFY(QDir(output).removeRecursively());
        const auto result = page(store, manifest, output);
        QVERIFY(result["available"].toBool());
        QCOMPARE(result["currentContentVerified"], QJsonValue(false));
        const auto entries = result["entries"].toArray();
        QCOMPARE(entries.size(), 9);
        const QList<int> skipped{2, 3, 4, 5, 6};
        for (int index = 0; index < entries.size(); ++index) {
            const auto item = entries[index].toObject();
            const auto entry = manifest.entry(static_cast<quint64>(index + 1));
            QCOMPARE(item["path"], QJsonValue(entry.relative));
            QCOMPARE(item["target"], item["path"]);
            if (skipped.contains(index + 1)) {
                QCOMPARE(item["disposition"], QJsonValue("skipped"));
                QCOMPARE(item["confirmedBytes"], QJsonValue("0"));
                QCOMPARE(item["skippedRoot"],
                         QJsonValue(QString::number(index < 4 ? 2 : index + 1)));
            } else {
                QCOMPARE(item["disposition"], QJsonValue("copied"));
                QCOMPARE(item["confirmedBytes"], QJsonValue(QString::number(entry.bytes)));
                QVERIFY(!item.contains("skippedRoot"));
            }
            QVERIFY(!item.contains("native"));
            QVERIFY(!item.contains("temporary"));
        }
        QVERIFY(!QFileInfo::exists(output));
        QCOMPARE(page(store, manifest, output), result);
    }

    // 日期：2026-11-06；未执行尾项保留空目标，不能因同批前项已完成就推断整个清单完成。
    void partialHistory() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const auto output = temporary.filePath("output");
        fixture(store, manifest, output, false);
        const auto entries = page(store, manifest, output, "interrupted")["entries"].toArray();
        QCOMPARE(entries.last().toObject()["disposition"], QJsonValue("not-executed"));
        QCOMPARE(entries.last().toObject()["target"], QJsonValue(""));
        QVERIFY_EXCEPTION_THROWN(page(store, manifest, output), dukto::Error);
    }

    // 日期：2026-11-06；已持久准备但尚未建临时正文时返回planned，并保持原有准备证据。
    void preparedWithoutBody() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", {}, false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY_EXCEPTION_THROWN(
                receiver.prepareDisposition(
                    1,
                    [&]() {
                        // 日期：2026-11-06；依据另一连接看到的真实提交注入取消，不按回调次数猜测。
                        const auto result =
                            page(store, manifest, output, "transferring")["entries"].toArray();
                        if (result[0].toObject()["disposition"] == "planned")
                            throw dukto::Error(dukto::ExitCode::Cancelled, "after decision",
                                               "test");
                    }),
                dukto::Error);
        }
        QCOMPARE(page(store, manifest, output, "interrupted")["entries"]
                     .toArray()[0]
                     .toObject()["disposition"],
                 QJsonValue("planned"));
        QVERIFY(!QFileInfo::exists(output + "/file"));
    }

    // 日期：2026-11-06；最终跳过已提交但临时清理未完成时不报告成功，查询不得代替执行者清理。
    void finalCleanupPending() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", {}, false, 3, sha("abc")});
        manifest.appendBlock(1, 0, 3, sha("abc"));
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            receiver.prepareDisposition(1);
            receiver.openDisposition(1, "file");
            receiver.write(0, 0, "abc");
            write(output + "/file", "original");
            QVERIFY_EXCEPTION_THROWN(receiver.finishDisposition([&]() {
                // 日期：2026-11-06；只在真实提交的最终决定可查询后中断，保留临时清理状态。
                bool committed = false;
                change(temporary.filePath("private/") + Journal, [&](QSqlDatabase database) {
                    // 日期：2026-11-06；独立只读SQL确认原最终记录已提交，不依赖公开字段。
                    QSqlQuery query(database);
                    if (!query.exec("SELECT cleaned FROM skip_final WHERE id=1"))
                        throw dukto::Error(dukto::ExitCode::Disk, "fixture final read", "test");
                    committed = query.next() && query.value(0).toInt() == 0;
                });
                if (committed)
                    throw dukto::Error(dukto::ExitCode::Cancelled, "before cleanup", "test");
            }),
                                     dukto::Error);
        }
        const auto item =
            page(store, manifest, output, "interrupted")["entries"].toArray()[0].toObject();
        QCOMPARE(item["disposition"], QJsonValue("committing"));
        QVERIFY(!item.contains("skippedRoot"));
        QCOMPARE(item["confirmedBytes"], QJsonValue("0"));
        QVERIFY_EXCEPTION_THROWN(page(store, manifest, output), dukto::Error);
        const auto parts = QDir(output).entryList({".dukto-*.part"}, QDir::Hidden | QDir::Files);
        QCOMPARE(parts.size(), 1);
        {
            dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(receiver.prepareDisposition(1).skipped);
        }
        QCOMPARE(page(store, manifest, output)["entries"].toArray()[0].toObject()["disposition"],
                 QJsonValue("skipped"));
        QVERIFY(QDir(output).entryList({".dukto-*.part"}, QDir::Hidden | QDir::Files).isEmpty());
    }

    // 日期：2026-11-06；旧v3仅含准备决定，查询保持原格式且不得新增最终表或迁移绑定。
    void oldVersionThree() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        write(output + "/file", "original");
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "file", {}, false, 0, sha({})});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            QVERIFY(receiver.prepareDisposition(1).skipped);
        }
        change(temporary.filePath("private/") + Journal, [](QSqlDatabase database) {
            // 日期：2026-11-06；真实旧版架构没有最终决定表，不能用v4空表冒充兼容。
            changeSpec(database, "binding", 0, [](QJsonObject &value) { value["version"] = 3; });
            execute(database, "DROP TABLE skip_final");
        });
        QCOMPARE(page(store, manifest, output)["entries"].toArray()[0].toObject()["disposition"],
                 QJsonValue("skipped"));
    }

    // 日期：2026-11-06；超过两页的子树在原目录被删除后跨页保留同一个跳过根。
    void pagedSubtree() {
        QTemporaryDir temporary;
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output + "/tree"));
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.append({1, "tree", {}, true, 0, {}});
        for (quint64 id = 2; id <= 207; ++id)
            manifest.append(
                {id, QString("tree/%1").arg(id, 4, 10, QChar('0')), {}, false, 0, sha({})});
        manifest.seal();
        {
            dukto::DurableReceive receiver(store, Journal, Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            for (quint64 id = 1; id <= 207; ++id)
                QVERIFY(receiver.prepareDisposition(id).skipped);
        }
        QVERIFY(QDir(output).removeRecursively());
        quint64 cursor = 0;
        int pages = 0;
        do {
            const auto result = page(store, manifest, output, "completed", cursor);
            const auto items = result["entries"].toArray();
            QCOMPARE(items.size(), pages < 2 ? 100 : 7);
            for (const auto &value : items) {
                const auto item = value.toObject();
                QCOMPARE(item["id"], QJsonValue(QString::number(++cursor)));
                QCOMPARE(item["disposition"], QJsonValue("skipped"));
                QCOMPARE(item["skippedRoot"], QJsonValue("1"));
                QCOMPARE(item["confirmedBytes"], QJsonValue("0"));
            }
            QCOMPARE(result["more"], QJsonValue(cursor < 207));
            ++pages;
        } while (cursor < 207);
        QCOMPARE(pages, 3);
        QVERIFY(page(store, manifest, output, "completed", cursor)["entries"].toArray().isEmpty());
    }

    // 日期：2026-11-06；为规范JSON字段、缺表和跨页祖先损坏分别建立独立测试，失败不可互相覆盖。
    void damagedEvidence_data() {
        QTest::addColumn<QString>("attack");
        for (const auto &attack :
             {"binding-version",   "binding-conflict",    "binding-task",
              "binding-root",      "binding-manifest",    "binding-native",
              "duplicate-binding", "missing-final-table", "missing-decisions-table",
              "missing-decision",  "decision-source",     "decision-path",
              "decision-action",   "decision-entry",      "child-root",
              "child-native",      "final-native",        "final-cleaned-type",
              "final-uncleaned",   "copy-target",         "copy-state"})
            QTest::newRow(attack) << QString(attack);
    }

    // 日期：2026-11-06；损坏证据明确拒绝且原件保持逐字节不变，不按当前目标重新猜测结果。
    void damagedEvidence() {
        QFETCH(QString, attack);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        const auto output = temporary.filePath("output");
        fixture(store, manifest, output);
        const auto journal = temporary.filePath("private/") + Journal;
        change(journal, [&](QSqlDatabase database) {
            // 日期：2026-11-06；每次仅改本测试一项契约，所有原始坏样本均由独立用例生成。
            execute(database, "PRAGMA ignore_check_constraints=ON");
            if (attack.startsWith("binding-")) {
                changeSpec(database, "binding", 0, [&](QJsonObject &value) {
                    // 日期：2026-11-06；分别破坏原绑定字段，仍以规范JSON保存。
                    if (attack == "binding-version")
                        value["version"] = 2;
                    if (attack == "binding-conflict")
                        value["conflict"] = "rename";
                    if (attack == "binding-task")
                        value["task"] = QUuid::createUuid().toString(QUuid::WithoutBraces);
                    if (attack == "binding-root")
                        value["root"] = output + "/other";
                    if (attack == "binding-manifest")
                        value["manifest"] = QString(64, QChar('a'));
                    if (attack == "binding-native")
                        value["rootIdentity"] = "";
                });
            } else if (attack == "duplicate-binding") {
                execute(database, "INSERT INTO binding SELECT * FROM binding");
            } else if (attack == "missing-final-table") {
                execute(database, "DROP TABLE skip_final");
            } else if (attack == "missing-decisions-table") {
                execute(database, "DROP TABLE skip_decisions");
            } else if (attack == "missing-decision") {
                execute(database, "DELETE FROM skip_decisions WHERE id=5");
            } else if (attack == "decision-source") {
                execute(database, "UPDATE skip_decisions SET source='wrong' WHERE id=5");
            } else if (attack == "decision-path" || attack == "decision-action" ||
                       attack == "decision-entry") {
                changeSpec(database, "skip_decisions", 5, [&](QJsonObject &value) {
                    // 日期：2026-11-06；改变原决定公开字段，不能被当作普通跳过解释。
                    if (attack == "decision-path")
                        value["path"] = "wrong";
                    if (attack == "decision-action")
                        value["action"] = "unknown";
                    if (attack == "decision-entry")
                        value["entry"] = manifest.entry(1).publicInfo();
                });
            } else if (attack == "child-root" || attack == "child-native") {
                changeSpec(database, "skip_decisions", 4, [&](QJsonObject &value) {
                    // 日期：2026-11-06；后代不能自选非祖先根或携带自己的冲突目标身份。
                    value[attack == "child-root" ? "skippedRoot" : "native"] =
                        attack == "child-root" ? "1" : "ab";
                });
            } else if (attack == "final-native") {
                changeSpec(database, "skip_final", 6, [](QJsonObject &value) {
                    // 日期：2026-11-06；最终记录不能改绑接收临时项原生身份。
                    value["temporaryNative"] = "ab";
                });
            } else if (attack == "final-cleaned-type") {
                execute(database, "UPDATE skip_final SET cleaned='bad' WHERE id=6");
            } else if (attack == "final-uncleaned") {
                execute(database, "UPDATE skip_final SET cleaned=0 WHERE id=6");
            } else if (attack == "copy-target") {
                execute(database, "UPDATE files SET target='wrong' WHERE id=1");
            } else if (attack == "copy-state") {
                execute(database, "UPDATE files SET state='receiving' WHERE id=1");
            }
        });
        const auto before = dukto::hashFile(journal);
        QVERIFY_EXCEPTION_THROWN(page(store, manifest, output), dukto::Error);
        QCOMPARE(dukto::hashFile(journal), before);
    }
};

QTEST_GUILESS_MAIN(TransferItemsTests)
#include "transfer_items_tests.moc"

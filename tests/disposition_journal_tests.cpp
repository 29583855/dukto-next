#include "core/dispositionjournal.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/transferdisposition.h"

#include <QCryptographicHash>
#include <QDir>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>

namespace {
// 日期：2026-11-05；只对样本原始正文计算SHA，独立于处置日志汇总实现。
QByteArray sha(const QByteArray &bytes) {
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

// 日期：2026-11-05；固定清单包含普通文件、两层目录和空文件，不访问实际传输目标。
void sample(dukto::StrongManifest &manifest, bool changed = false) {
    manifest.append({1, "bundle", "", true, 0, {}});
    manifest.append({2, "bundle/a", "", false, 3, sha(changed ? "xyz" : "abc")});
    manifest.appendBlock(2, 0, 3, sha(changed ? "xyz" : "abc"));
    manifest.append({3, "bundle/sub", "", true, 0, {}});
    manifest.append({4, "bundle/sub/b", "", false, 4, sha("defg")});
    manifest.appendBlock(4, 0, 4, sha("defg"));
    manifest.append({5, "z", "", false, 0, sha("")});
    manifest.seal();
}

// 日期：2026-11-05；关闭日志后使用独立连接模拟磁盘损坏，作用域保证查询先于连接销毁。
bool alter(const QString &path, const QString &statement) {
    const auto connection = QUuid::createUuid().toString();
    bool passed = false;
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setDatabaseName(path);
        if (database.open()) {
            QSqlQuery query(database);
            passed = query.exec("PRAGMA ignore_check_constraints=ON") && query.exec(statement);
        }
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
    return passed;
}
} // namespace

class DispositionJournalTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；独立改变真实复制源、原处置和授权映射，跳过源不存在不影响历史决定。
    void completedSourceHistory_data() {
        QTest::addColumn<QString>("scenario");
        for (const auto &name :
             {"unchanged", "changed-copy", "missing-copy", "directory-is-file", "missing-empty",
              "wrong-mapping", "cancel-read", "incomplete", "wrong-manifest", "skipped-now-file"})
            QTest::newRow(name) << QString::fromLatin1(name);
    }

    // 日期：2026-11-06；正文分片取消且不写原件，copied损坏必须失败；sourceForCopied绝不能解析skipped。
    void completedSourceHistory() {
        QFETCH(QString, scenario);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto bundle = temporary.filePath("a");
        QVERIFY(QDir().mkdir(bundle));
        const auto body = bundle + "/body";
        const auto empty = bundle + "/empty";
        const QByteArray bytes(dukto::BufferSize * 3 + 17, 'x');
        {
            QFile file(body);
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write(bytes), qint64(bytes.size()));
        }
        {
            QFile file(empty);
            QVERIFY(file.open(QIODevice::WriteOnly));
        }
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        manifest.append({1, "a", bundle, true, 0, {}});
        manifest.append({2, "a/body", body, false, bytes.size(), sha(bytes)});
        manifest.appendBlock(2, 0, bytes.size(), sha(bytes));
        manifest.append({3, "a/empty", empty, false, 0, sha("")});
        const auto skipped = temporary.filePath("z");
        manifest.append({4, "z", skipped, true, 0, {}});
        manifest.append({5, "z/sub", skipped + "/sub", true, 0, {}});
        manifest.append({6, "z/sub/gone", skipped + "/sub/gone", false, 3, sha("abc")});
        manifest.appendBlock(6, 0, 3, sha("abc"));
        manifest.seal();
        const auto task = QUuid::createUuid();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip");
            journal.append(1, "a", "copied");
            journal.append(2, "a/body", "copied");
            journal.append(3, "a/empty", "copied");
            journal.append(4, "z", "skipped", 4);
            journal.append(5, "z/sub", "skipped", 4);
            if (scenario != "incomplete")
                journal.append(6, "z/sub/gone", "skipped", 4);
        }
        if (scenario == "changed-copy") {
            QFile file(body);
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write(QByteArray(bytes.size(), 'y')), qint64(bytes.size()));
        } else if (scenario == "missing-copy") {
            QVERIFY(QFile::remove(body));
        } else if (scenario == "missing-empty") {
            QVERIFY(QFile::remove(empty));
        } else if (scenario == "directory-is-file") {
            QVERIFY(QDir(bundle).removeRecursively());
            QFile file(bundle);
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write("other"), qint64(5));
        } else if (scenario == "skipped-now-file") {
            QFile file(skipped);
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write("foreign"), qint64(7));
        }
        const auto before = dukto::hashFile(temporary.filePath("private/result.sqlite"));
        const auto sourceBefore = dukto::hashFile(temporary.filePath("private/manifest.sqlite"));
        const auto connections = QSqlDatabase::connectionNames();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip", {},
                                              true);
            int mapped = 0, readingChecks = 0;
            bool reading = false;
            const auto check = [&]() {
                // 日期：2026-11-06；仅在复制正文解析后计数，确保取消发生在固定片段重读期间。
                if (scenario == "cancel-read" && reading && ++readingChecks == 2)
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel-source-read",
                                       "completion");
            };
            const auto resolve = [&](const dukto::StrongEntry &entry) {
                // 日期：2026-11-06；skipped的现有类型或消失状态都不能触发当前源解析。
                if (entry.id > 3)
                    throw dukto::Error(dukto::ExitCode::Integrity, "resolved-skipped-source",
                                       "test");
                ++mapped;
                reading = entry.id == 2;
                return scenario == "wrong-mapping" ? empty : entry.source;
            };
            bool succeeded = false;
            try {
                if (scenario == "wrong-manifest") {
                    dukto::StrongManifest other(store, "other.sqlite", true);
                    other.append({1, "other", empty, false, 0, sha("")});
                    other.seal();
                    dukto::verifyCompletedSource(other, journal, check, resolve);
                } else {
                    const auto result =
                        dukto::verifyCompletedSource(manifest, journal, check, resolve);
                    QCOMPARE(result["copiedBytes"], QJsonValue(QString::number(bytes.size())));
                    QCOMPARE(result["skippedBytes"], QJsonValue("3"));
                    QCOMPARE(result["skippedEntries"], QJsonValue("3"));
                    QCOMPARE(mapped, 3);
                }
                succeeded = true;
            } catch (const dukto::Error &error) {
                QVERIFY2(error.message != "resolved-skipped-source", qPrintable(error.message));
                if (scenario == "cancel-read") {
                    QCOMPARE(error.code, dukto::ExitCode::Cancelled);
                    QCOMPARE(readingChecks, 2);
                } else if (scenario == "changed-copy" || scenario == "wrong-mapping" ||
                           scenario == "wrong-manifest" || scenario == "incomplete") {
                    QCOMPARE(error.code, dukto::ExitCode::Integrity);
                }
            }
            QCOMPARE(succeeded, scenario == "unchanged" || scenario == "skipped-now-file");
        }
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
        QCOMPARE(dukto::hashFile(temporary.filePath("private/result.sqlite")), before);
        QCOMPARE(dukto::hashFile(temporary.filePath("private/manifest.sqlite")), sourceBefore);
    }

    // 日期：2026-11-06；跨三页全跳过历史允许整个原目录删除；不解析任一源且反复取消不改变数据库。
    void completedAllSkippedSourceRemoved() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        const auto removed = temporary.filePath("gone");
        QVERIFY(QDir().mkdir(removed));
        manifest.append({1, "gone", removed, true, 0, {}});
        for (quint64 id = 2; id <= 206; ++id) {
            const auto name = QString("file-%1").arg(id, 4, 10, QChar('0'));
            manifest.append({id, "gone/" + name, removed + '/' + name, false, 0, sha("")});
        }
        manifest.seal();
        const auto task = QUuid::createUuid();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip");
            for (quint64 id = 1; id <= 206; ++id)
                journal.append(id, manifest.entry(id).relative, "skipped", 1);
        }
        QVERIFY(QDir().rmdir(removed));
        const auto before = dukto::hashFile(temporary.filePath("private/result.sqlite"));
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip", {},
                                              true);
            const auto resolve = [](const dukto::StrongEntry &) -> QString {
                // 日期：2026-11-06；全跳过不应访问已删除的原源路径。
                throw dukto::Error(dukto::ExitCode::Integrity, "resolved-skipped-source", "test");
            };
            for (int iteration = 0; iteration < 5; ++iteration) {
                int checks = 0;
                const auto cancel = [&]() {
                    // 日期：2026-11-06；在逐项历史核验中取消，不依赖源文件是否存在。
                    if (++checks == 117)
                        throw dukto::Error(dukto::ExitCode::Cancelled, "cancel-history",
                                           "completion");
                };
                QVERIFY_EXCEPTION_THROWN(
                    dukto::verifyCompletedSource(manifest, journal, cancel, resolve), dukto::Error);
            }
            const auto result = dukto::verifyCompletedSource(manifest, journal, {}, resolve);
            QCOMPARE(result["complete"], QJsonValue(true));
            QCOMPARE(result["skippedEntries"], QJsonValue("206"));
            QCOMPARE(result["copiedEntries"], QJsonValue("0"));
        }
        QCOMPARE(dukto::hashFile(temporary.filePath("private/result.sqlite")), before);
        QVERIFY(!QFileInfo::exists(removed));
    }

    // 日期：2026-11-06；核验只读重开原日志，拒绝追加和缺库，正文与持久头字节保持不变。
    void explicitReadOnlyHistory() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        sample(manifest);
        const auto task = QUuid::createUuid();
        QJsonObject expected;
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "rename");
            for (quint64 id = 1; id <= 5; ++id)
                journal.append(id, manifest.entry(id).relative, "copied");
            expected = journal.summary();
        }
        const auto before = dukto::hashFile(temporary.filePath("private/result.sqlite"));
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "rename", {},
                                              true);
            QCOMPARE(journal.summary(), expected);
            QVERIFY_EXCEPTION_THROWN(journal.append(1, "bundle", "copied"), dukto::Error);
        }
        QCOMPARE(dukto::hashFile(temporary.filePath("private/result.sqlite")), before);
        QVERIFY_EXCEPTION_THROWN(
            dukto::DispositionJournal(store, "missing.sqlite", task, manifest, "rename", {}, true),
            dukto::Error);
        QVERIFY(!store.exists("missing.sqlite"));
    }

    // 日期：2026-11-05；历史结果重启后完全相同，跳过字节与复制字节分开，未完成不能生成最终汇总。
    void restartAndIndependentSummary() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        sample(manifest);
        const QUuid task("11111111-2222-4333-8444-555555555555");
        QJsonObject expected;
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip");
            QCOMPARE(journal.summary(false)["processedEntries"].toString(), QString("0"));
            QVERIFY_EXCEPTION_THROWN(journal.summary(), dukto::Error);
            journal.append(1, "bundle (1)", "copied");
            journal.append(2, "bundle (1)/a", "copied");
            journal.append(3, "bundle (1)/sub", "skipped", 3);
            journal.append(4, "bundle (1)/sub/b", "skipped", 3);
            QVERIFY_EXCEPTION_THROWN(journal.summary(), dukto::Error);
            QCOMPARE(journal.summary(false)["unexecutedEntries"].toString(), QString("1"));
            journal.append(5, "z", "skipped", 5);
            expected = journal.summary();
            QCOMPARE(expected["copiedEntries"].toString(), QString("2"));
            QCOMPARE(expected["skippedEntries"].toString(), QString("3"));
            QCOMPARE(expected["copiedFiles"].toString(), QString("1"));
            QCOMPARE(expected["copiedDirectories"].toString(), QString("1"));
            QCOMPARE(expected["skippedFiles"].toString(), QString("2"));
            QCOMPARE(expected["skippedDirectories"].toString(), QString("1"));
            QCOMPARE(expected["copiedBytes"].toString(), QString("3"));
            QCOMPARE(expected["skippedBytes"].toString(), QString("4"));
            QCOMPARE(expected["totalBytes"].toString(), QString("7"));
            QVERIFY(expected["complete"].toBool());
            // 日期：2026-11-05；该固定向量由Python json/hashlib/struct独立编码计算。
            QCOMPARE(expected["sha256"].toString(),
                     QString("9e9febda73fb4fa903bfbc46faf785fee0750a1fc3ca00209f369540846347e9"));
            journal.append(3, "bundle (1)/sub", "skipped", 3);
            QVERIFY_EXCEPTION_THROWN(journal.append(3, "bundle (1)/other", "skipped", 3),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(journal.append(5, "z", "copied"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(journal.item(6), dukto::Error);
        }
        dukto::DispositionJournal restored(store, "result.sqlite", task, manifest, "skip");
        QCOMPARE(restored.summary(), expected);
        QCOMPARE(restored.item(4)["skippedRoot"].toString(), QString("3"));
        QCOMPARE(restored.item(2)["path"].toString(), QString("bundle (1)/a"));
        QVERIFY(store.validateFile("result.sqlite") <= dukto::MaxMetadataBytes);
    }

    // 日期：2026-11-05；跳过子树必须保持原根和映射，不允许后代被复制、跨树引用或跳过序号。
    void subtreeAndSequenceRules() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        sample(manifest);
        dukto::DispositionJournal journal(store, "result.sqlite", QUuid::createUuid(), manifest,
                                          "skip");
        QVERIFY_EXCEPTION_THROWN(journal.append(2, "bundle/a", "copied"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(0, "bundle", "copied"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(1, "../bundle", "skipped", 1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(1, "extra/bundle", "copied"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(1, "bundle", "skipped", 0), dukto::Error);
        journal.append(1, "bundle", "skipped", 1);
        QVERIFY_EXCEPTION_THROWN(journal.append(2, "bundle/a", "copied"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(2, "bundle/a", "skipped", 2), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(journal.append(2, "bundle/renamed", "skipped", 1), dukto::Error);
        journal.append(2, "bundle/a", "skipped", 1);
        journal.append(3, "bundle/sub", "skipped", 1);
        QVERIFY_EXCEPTION_THROWN(journal.append(4, "bundle/sub/b", "skipped", 3), dukto::Error);
        journal.append(4, "bundle/sub/b", "skipped", 1);
        QVERIFY_EXCEPTION_THROWN(journal.append(5, "z", "skipped", 1), dukto::Error);
        journal.append(5, "z", "copied");
        QCOMPARE(journal.summary()["skippedBytes"].toString(), QString("7"));
    }

    // 日期：2026-11-05；任务、内容或策略变化拒绝恢复；并发执行者和无效状态键不能创建旁路日志。
    void bindingOwnershipAndPolicy() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        dukto::StrongManifest changed(store, "changed.sqlite", true);
        sample(manifest);
        sample(changed, true);
        const auto task = QUuid::createUuid();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "rename");
            QVERIFY_EXCEPTION_THROWN(journal.append(1, "bundle", "skipped", 1), dukto::Error);
            journal.append(1, "bundle", "copied");
            QVERIFY_EXCEPTION_THROWN(
                dukto::DispositionJournal(store, "result.sqlite", task, manifest, "rename"),
                dukto::Error);
        }
        const auto before = QSqlDatabase::connectionNames();
        for (int attempt = 0; attempt < 12; ++attempt) {
            QVERIFY_EXCEPTION_THROWN(dukto::DispositionJournal(store, "result.sqlite",
                                                               QUuid::createUuid(), manifest,
                                                               "rename"),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(
                dukto::DispositionJournal(store, "result.sqlite", task, changed, "rename"),
                dukto::Error);
            QVERIFY_EXCEPTION_THROWN(
                dukto::DispositionJournal(store, "result.sqlite", task, manifest, "skip"),
                dukto::Error);
        }
        QCOMPARE(QSqlDatabase::connectionNames(), before);
        QVERIFY_EXCEPTION_THROWN(
            dukto::DispositionJournal(store, "invalid.sqlite", task, manifest, "unknown"),
            dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            dukto::DispositionJournal(store, "../escaped.sqlite", task, manifest, "skip"),
            dukto::Error);
        QVERIFY(!QFile::exists(temporary.filePath("escaped.sqlite.lock")));
        dukto::DispositionJournal restored(store, "result.sqlite", task, manifest, "rename");
        QCOMPARE(restored.summary(false)["processedEntries"].toString(), QString("1"));
    }

    // 日期：2026-11-05；关闭后的损坏分别验证，非法ID不能躲过分页，未知字段、索引与缺失架构都拒绝。
    void corruptHistory_data() {
        QTest::addColumn<QString>("statement");
        QTest::newRow("zero") << "INSERT INTO items VALUES(0,'bad',x'7b7d')";
        QTest::newRow("negative") << "INSERT INTO items VALUES(-1,'bad',x'7b7d')";
        QTest::newRow("gap") << "UPDATE items SET id=7 WHERE id=2";
        QTest::newRow("large-source") << "UPDATE items SET source=zeroblob(1048576) WHERE id=1";
        QTest::newRow("source-index") << "UPDATE items SET source='other' WHERE id=1";
        QTest::newRow("unknown-field")
            << "UPDATE items SET spec=CAST('{\"unknown\":true}' AS BLOB) WHERE id=2";
        QTest::newRow("large-row") << "UPDATE items SET spec=zeroblob(1048576) WHERE id=1";
        QTest::newRow("bad-version") << "PRAGMA user_version=2";
        QTest::newRow("duplicate-binding") << "INSERT INTO binding SELECT spec FROM binding";
        QTest::newRow("missing-table") << "DROP TABLE items";
    }

    // 日期：2026-11-05；重新打开必须失败且不自动修复或重建损坏证据。
    void corruptHistory() {
        QFETCH(QString, statement);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        sample(manifest);
        const auto task = QUuid::createUuid();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "rename");
            journal.append(1, "bundle", "copied");
            journal.append(2, "bundle/a", "copied");
        }
        const auto path = QDir(store.directory()).filePath("result.sqlite");
        QVERIFY(alter(path, statement));
        const auto before = dukto::hashFile(path);
        QVERIFY_EXCEPTION_THROWN(
            dukto::DispositionJournal(store, "result.sqlite", task, manifest, "rename"),
            dukto::Error);
        QCOMPARE(dukto::hashFile(path), before);
    }

    // 日期：2026-11-05；跨越100项分页仍全量验证，取消中止汇总不改变历史；重启后接续固定游标。
    void pagingCancellationAndResume() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        for (quint64 id = 1; id <= 205; ++id)
            manifest.append(
                {id, QString("file-%1").arg(id, 4, 10, QChar('0')), "", false, 0, sha("")});
        manifest.seal();
        const auto task = QUuid::createUuid();
        {
            dukto::DispositionJournal journal(store, "result.sqlite", task, manifest, "skip");
            for (quint64 id = 1; id <= 103; ++id)
                journal.append(id, QString("file-%1").arg(id, 4, 10, QChar('0')), "skipped", id);
            QCOMPARE(journal.summary(false)["processedEntries"].toString(), QString("103"));
            int observed = 0;
            QVERIFY_EXCEPTION_THROWN(journal.summary(false,
                                                     [&]() {
                                                         // 日期：2026-11-05；在第二页真实中止，不能生成部分最终摘要。
                                                         if (++observed == 101)
                                                             throw dukto::Error(
                                                                 dukto::ExitCode::Cancelled,
                                                                 "cancelled", "disposition");
                                                     }),
                                     dukto::Error);
            QCOMPARE(observed, 101);
        }
        dukto::DispositionJournal restored(store, "result.sqlite", task, manifest, "skip");
        for (quint64 id = 104; id <= 205; ++id)
            restored.append(id, QString("file-%1").arg(id, 4, 10, QChar('0')), "copied");
        QCOMPARE(restored.summary()["copiedFiles"].toString(), QString("102"));
        QCOMPARE(restored.summary()["skippedFiles"].toString(), QString("103"));
    }
};

QTEST_GUILESS_MAIN(DispositionJournalTests)
#include "disposition_journal_tests.moc"

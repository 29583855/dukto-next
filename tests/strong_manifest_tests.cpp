#include "core/dispositionjournal.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/service.h"
#include "core/strongmanifest.h"
#include "core/transferdisposition.h"
#include "core/uploadmanifest.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>

namespace {
// 日期：2026-11-04；独立测试摘要只对样本原字节使用标准 SHA-256，不复用强清单编码器。
QByteArray sha(const QByteArray &bytes) {
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

// 日期：2026-11-04；测试导入只使用真实公开字段，源路径故意与原数据库不同以核对身份边界。
dukto::StrongEntry imported(const QJsonObject &value) {
    return {dukto::next::decimal(value["id"], 10000000),
            value["path"].toString(),
            "",
            value["type"] == "directory",
            static_cast<qint64>(dukto::next::decimal(value["bytes"], 100000000)),
            QByteArray::fromHex(value["sha256"].toString().toLatin1())};
}
} // namespace

class StrongManifestTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-04；固定身份由独立 Python hashlib/struct 样本计算，包含 Unicode、目录和空文件。
    void independentCanonicalVector() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto expected =
            QByteArray::fromHex("6336657ba5ca0e8364a9ecd122e38b6cd9cddd5ff56b7e7885d45bb757099c8c");
        {
            dukto::StrongManifest manifest(store, "vector.sqlite", true);
            manifest.append({1, QStringLiteral("资料"), "", true, 0, {}});
            manifest.append(
                {2, QStringLiteral("资料/a.bin"), "not-transmitted", false, 3, sha("abc")});
            manifest.appendBlock(2, 0, 3, sha("abc"));
            manifest.append({3, QStringLiteral("资料/empty"), "", false, 0, sha("")});
            QCOMPARE(manifest.seal(expected), expected);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(2, 1, 3, sha("abc")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(), dukto::Error);
            QVERIFY(!dukto::next::encodeControl({{"entries", manifest.entries()}})
                         .contains("not-transmitted"));
        }
        dukto::StrongManifest restored(store, "vector.sqlite", false);
        QCOMPARE(restored.summary()["sha256"].toString().toLatin1(), expected.toHex());
        QCOMPARE(restored.summary()["entries"].toString(), QString("3"));
        QCOMPARE(restored.summary()["blocks"].toString(), QString("1"));
        QCOMPARE(restored.summary()["bytes"].toString(), QString("3"));
        QCOMPARE(restored.blocks(2).size(), 1);
        QVERIFY(restored.blocks(2, 1).isEmpty());
        QVERIFY_EXCEPTION_THROWN(restored.entry(4), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(restored.blocks(2, 2), dukto::Error);
    }

    // 日期：2026-11-04；真实扫描两整块加尾块，公开分页导入另一数据库后获得相同强内容身份。
    void scanBlocksAndRoundtrip() {
        QTemporaryDir temporary;
        const auto source = temporary.filePath("bundle");
        QVERIFY(QDir().mkpath(source + "/empty-directory"));
        QFile input(source + "/data.bin");
        QVERIFY(input.open(QIODevice::WriteOnly));
        const QByteArray fragment(256 * 1024, 'x');
        for (int index = 0; index < 32; ++index)
            QCOMPARE(input.write(fragment), qint64(fragment.size()));
        QCOMPARE(input.write("tail-of-final-block-37-bytes-0123456789", 37), qint64(37));
        input.close();
        QFile empty(source + "/empty-file");
        QVERIFY(empty.open(QIODevice::WriteOnly));
        empty.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.scan({source});
        QCOMPARE(manifest.summary()["entries"].toString(), QString("4"));
        QCOMPARE(manifest.summary()["blocks"].toString(), QString("3"));
        QCOMPARE(manifest.summary()["bytes"].toString(), QString::number(8 * 1024 * 1024 + 37));
        QCOMPARE(manifest.entry(2).sha256, dukto::hashFile(source + "/data.bin"));
        const auto list = manifest.blocks(2);
        QCOMPARE(list[0].toObject()["sha256"].toString().toLatin1(),
                 sha(QByteArray(4 * 1024 * 1024, 'x')).toHex());
        QCOMPARE(list[2].toObject()["bytes"].toString(), QString("37"));
        dukto::StrongManifest receiver(store, "received.sqlite", true);
        for (const auto &value : manifest.entries()) {
            const auto entry = imported(value.toObject());
            receiver.append(entry);
            for (const auto &block : manifest.blocks(entry.id)) {
                const auto object = block.toObject();
                receiver.appendBlock(entry.id, dukto::next::decimal(object["block"], 100),
                                     static_cast<qint64>(dukto::next::decimal(
                                         object["bytes"], dukto::StrongBlockBytes)),
                                     QByteArray::fromHex(object["sha256"].toString().toLatin1()));
            }
        }
        QCOMPARE(receiver.seal(),
                 QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()));
        QCOMPARE(receiver.summary(), manifest.summary());
        QCOMPARE(receiver.entry(2).source, QString(""));
        QVERIFY(store.validateFile("source.sqlite") <= dukto::MaxMetadataBytes);
    }

    // 日期：2026-11-04；缺块、坏身份、重复块、穿越和跨平台重名不能被当作有效强清单。
    void invalidAndIncompleteRecords() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        {
            dukto::StrongManifest manifest(store, "incomplete.sqlite", true);
            QVERIFY_EXCEPTION_THROWN(manifest.append({1, "../escape", "", false, 1, sha("x")}),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.append({1, "parent/child", "", false, 1, sha("x")}),
                                     dukto::Error);
            manifest.append({1, "A", "", false, 1, sha("x")});
            QVERIFY_EXCEPTION_THROWN(manifest.append({2, "a", "", false, 0, sha("")}),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 1, 1, sha("x")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 0, 2, sha("xx")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.summary(), dukto::Error);
            manifest.appendBlock(1, 0, 1, sha("x"));
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 0, 1, sha("x")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(QByteArray(32, 'z')), dukto::Error);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "incomplete.sqlite", false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "incomplete.sqlite", true),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "../escape.sqlite", true),
                                 dukto::Error);
        QVERIFY(!QFile::exists(temporary.filePath("escape.sqlite.lock")));
    }

    // 日期：2026-11-04；目录条目多时分页保持上限；取消后的数据库不能重载为完整清单。
    void pagingAndCancellation() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "pages.sqlite", true);
        for (int index = 0; index < 301; ++index)
            manifest.append({static_cast<quint64>(index + 1),
                             QString("item-%1").arg(index, 4, 10, QChar('0')), "", false, 0,
                             sha("")});
        manifest.seal();
        quint64 after = 0;
        int pages = 0;
        for (;;) {
            const auto page = manifest.entries(after);
            if (page.isEmpty())
                break;
            QVERIFY(page.size() <= 100);
            QVERIFY(QJsonDocument(page).toJson(QJsonDocument::Compact).size() <=
                    dukto::next::ControlLimit - 1024);
            after = dukto::next::decimal(page.last().toObject()["id"], 10000000);
            ++pages;
        }
        QCOMPARE(after, quint64(301));
        QCOMPARE(pages, 4);
        {
            dukto::StrongManifest cancelled(store, "cancelled.sqlite", true);
            std::atomic_bool cancel{true};
            QVERIFY_EXCEPTION_THROWN(cancelled.scan({temporary.path()}, &cancel), dukto::Error);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "cancelled.sqlite", false),
                                 dukto::Error);
        const auto source = temporary.filePath("scan-source");
        QVERIFY(QDir().mkdir(source));
        for (int index = 0; index < 20; ++index) {
            QFile file(source + QString("/sample-%1").arg(index));
            QVERIFY(file.open(QIODevice::WriteOnly));
        }
        int callbacks = 0;
        dukto::StrongManifest revoked(store, "revoked.sqlite", true);
        QVERIFY_EXCEPTION_THROWN(revoked.scan({source}, nullptr,
                                              [&]() {
                                                  // 日期：2026-11-04；真实目录枚举尚未完成时撤销，须停止扫描且不生成可发布强身份。
                                                  if (++callbacks >= 5)
                                                      throw dukto::Error(
                                                          dukto::ExitCode::Permission,
                                                          "authorization revoked", "auth");
                                              }),
                                 dukto::Error);
        QCOMPARE(callbacks, 5);
        QVERIFY_EXCEPTION_THROWN(revoked.summary(), dukto::Error);
    }

    // 日期：2026-11-04；已冻结数据库中块或全摘要被改变时，重载重算必须拒绝，不能只信任元数据摘要。
    void persistentTamperingRejected() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        {
            dukto::StrongManifest manifest(store, "changed.sqlite", true);
            manifest.append({1, "sample", "", false, 3, sha("abc")});
            manifest.appendBlock(1, 0, 3, sha("abc"));
            manifest.seal();
        }
        const auto name = QUuid::createUuid().toString();
        {
            auto database = QSqlDatabase::addDatabase("QSQLITE", name);
            database.setDatabaseName(QDir(store.directory()).filePath("changed.sqlite"));
            QVERIFY(database.open());
            {
                QSqlQuery change(database);
                QVERIFY(change.exec("UPDATE blocks SET sha=zeroblob(32) WHERE file=1 AND block=0"));
            }
            database.close();
        }
        QSqlDatabase::removeDatabase(name);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "changed.sqlite", false),
                                 dukto::Error);
    }
    // 日期：2026-11-06；206项冻结源跨进程重开后可删除，历史跳过免读，复制仍须真实源存在。
    void uploadFrozenHistorySurvivesSourceRemoval() {
        QTemporaryDir temporary;
        const auto source = temporary.filePath("bundle");
        QVERIFY(QDir().mkpath(source + "/空目录"));
        for (int index = 0; index < 204; ++index) {
            QFile file(source + QString("/item-%1").arg(index, 3, 10, QChar('0')));
            QVERIFY(file.open(QIODevice::WriteOnly));
            QCOMPARE(file.write("abc"), qint64(3));
        }
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::ClientProfile profile;
        profile.server = QUuid::createUuid();
        profile.client = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto task = QUuid::createUuid();
        const auto stem = "upload-source-" + request.toString(QUuid::WithoutBraces);
        QJsonObject expected;
        {
            dukto::UploadManifest upload(store, request, profile, "data", "",
                                         dukto::ConflictPolicy::Skip, {source});
            expected = upload.get().summary();
            QCOMPARE(expected["entries"].toString(), QString("206"));
            dukto::DispositionJournal outcomes(store, "outcomes.sqlite", task, upload.get(),
                                               "skip");
            for (quint64 id = 1; id <= 206; ++id)
                outcomes.append(id, upload.get().entry(id).relative, "skipped", 1);
        }
        const auto original = dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite"));
        const auto record = store.read(stem + ".json");
        QVERIFY(QDir(source).removeRecursively());
        const auto connections = QSqlDatabase::connectionNames();
        for (int attempt = 0; attempt < 3; ++attempt) {
            dukto::UploadManifest upload(store, request, profile, "data", "",
                                         dukto::ConflictPolicy::Skip, {source});
            QCOMPARE(upload.get().summary(), expected);
            dukto::DispositionJournal outcomes(store, "outcomes.sqlite", task, upload.get(),
                                               "skip");
            QCOMPARE(
                dukto::verifyCompletedSource(upload.get(), outcomes)["skippedEntries"].toString(),
                QString("206"));
        }
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
        QCOMPARE(dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite")), original);
        QCOMPARE(store.read(stem + ".json"), record);
        dukto::UploadManifest upload(store, request, profile, "data", "",
                                     dukto::ConflictPolicy::Skip, {source});
        dukto::DispositionJournal copied(store, "copied.sqlite", task, upload.get(), "skip");
        for (quint64 id = 1; id <= 206; ++id)
            copied.append(id, upload.get().entry(id).relative, "copied");
        QVERIFY_EXCEPTION_THROWN(dukto::verifyCompletedSource(upload.get(), copied), dukto::Error);
    }

    // 日期：2026-11-06；同请求并发、源根/主体/目标/策略变更必须拒绝，正常重开不改变原库。
    void uploadIdentityAndOwnership() {
        QTemporaryDir temporary;
        const auto source = temporary.filePath("sample");
        QFile file(source);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("abc"), qint64(3));
        file.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::ClientProfile profile;
        profile.server = QUuid::createUuid();
        profile.client = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto stem = "upload-source-" + request.toString(QUuid::WithoutBraces);
        {
            dukto::UploadManifest first(store, request, profile, "data", "",
                                        dukto::ConflictPolicy::Rename, {source});
            QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                           dukto::ConflictPolicy::Rename, {source}),
                                     dukto::Error);
        }
        const auto before = dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite"));
        auto other = profile;
        other.client = QUuid::createUuid();
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, other, "data", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        other = profile;
        other.server = QUuid::createUuid();
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, other, "data", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "other", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "other",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                       dukto::ConflictPolicy::Fail, {source}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                       dukto::ConflictPolicy::Rename,
                                                       {temporary.filePath("other")}),
                                 dukto::Error);
        const auto connections = QSqlDatabase::connectionNames();
        for (int attempt = 0; attempt < 3; ++attempt) {
            dukto::UploadManifest restored(store, request, profile, "data", "",
                                           dukto::ConflictPolicy::Rename, {source});
            QCOMPARE(restored.get().entry(1).sha256, sha("abc"));
        }
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
        QCOMPARE(dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite")), before);
    }

    // 日期：2026-11-06；取消扫描回收本次自建库；已有原件缺失、源映射被改及不完整库不得重建。
    void uploadCancellationAndCorruption() {
        QTemporaryDir temporary;
        const auto source = temporary.filePath("sample");
        QFile file(source);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("abc"), qint64(3));
        file.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::ClientProfile profile;
        profile.server = QUuid::createUuid();
        profile.client = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto stem = "upload-source-" + request.toString(QUuid::WithoutBraces);
        int checks = 0;
        QVERIFY_EXCEPTION_THROWN(
            dukto::UploadManifest(store, request, profile, "data", "",
                                  dukto::ConflictPolicy::Rename, {source}, nullptr,
                                  [&]() {
                                      // 日期：2026-11-06；在真实扫描检查点中止，验证异常路径不留下半份发布证据。
                                      if (++checks == 5)
                                          throw dukto::Error(dukto::ExitCode::Cancelled, "cancel",
                                                             "manifest");
                                  }),
            dukto::Error);
        QCOMPARE(checks, 5);
        QVERIFY(!store.exists(stem + ".sqlite"));
        QVERIFY(!store.exists(stem + ".json"));
        {
            dukto::UploadManifest upload(store, request, profile, "data", "",
                                         dukto::ConflictPolicy::Rename, {source});
        }
        const auto saved = store.read(stem + ".json");
        const auto baseline = QSqlDatabase::connectionNames();
        const auto connection = QUuid::createUuid().toString();
        {
            auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
            database.setDatabaseName(QDir(store.directory()).filePath(stem + ".sqlite"));
            QVERIFY(database.open());
            QSqlQuery query(database);
            query.prepare("UPDATE entries SET source=? WHERE id=1");
            query.addBindValue(temporary.filePath("foreign"));
            QVERIFY(query.exec());
            query.finish();
            database.close();
        }
        QSqlDatabase::removeDatabase(connection);
        const auto changed = dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite"));
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        QCOMPARE(dukto::hashFile(QDir(store.directory()).filePath(stem + ".sqlite")), changed);
        QCOMPARE(store.read(stem + ".json"), saved);
        store.remove(stem + ".json");
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QVERIFY(!store.exists(stem + ".json"));
        store.write(stem + ".json", saved);
        store.remove(stem + ".sqlite");
        QVERIFY_EXCEPTION_THROWN(dukto::UploadManifest(store, request, profile, "data", "",
                                                       dukto::ConflictPolicy::Rename, {source}),
                                 dukto::Error);
        QVERIFY(!store.exists(stem + ".sqlite"));
    }
};
QTEST_GUILESS_MAIN(StrongManifestTests)
#include "strong_manifest_tests.moc"

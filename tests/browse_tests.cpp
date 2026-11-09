#include "core/browse.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/sourcefile.h"
#include "core/statecleanup.h"
#include "core/statesession.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QProcess>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdio>
#include <cstdlib>

namespace {
// 日期：2026-11-04；每个样本在独立临时根建立文件，避免改动用户目录及参考软件。
void createFile(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write("sample") != 6)
        throw std::runtime_error("cannot create isolated browse fixture");
}
struct SnapshotFixture {
    QTemporaryDir root;
    QUuid id;
    QDateTime expiry;
    // 日期：2026-11-09；通过生产浏览入口建立真实快照和保留凭据，后续维护不伪造对象身份。
    SnapshotFixture() {
        if (!root.isValid() || !QDir().mkdir(root.filePath("data")))
            throw std::runtime_error("snapshot fixture directory");
        createFile(root.filePath("data/file.txt"));
        dukto::PrivateStore store(root.filePath("service"), true);
        dukto::Shares(store).set({{"docs", true, true, false}, root.filePath("data")});
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, false, false}}};
        id = QUuid(dukto::BrowseStore(store).list(principal, "docs", "")["snapshot"].toString());
        const auto value = dukto::next::parseControl(store.read(marker()));
        expiry = QDateTime::fromString(value["expires"].toString(), Qt::ISODate);
        if (id.isNull() || !expiry.isValid())
            throw std::runtime_error("snapshot fixture identity");
    }
    // 日期：2026-11-09；只为无时钟注入的真实浏览入口建立已到期样本，凭据绑定改写后的实际说明身份。
    void expireForBrowse(dukto::PrivateStore &store) {
        expiry = QDateTime::currentDateTimeUtc().addSecs(-1);
        auto metadata = dukto::next::parseControl(store.read(base() + ".json"));
        metadata["expires"] = expiry.toString(Qt::ISODate);
        store.write(base() + ".json", dukto::next::encodeControl(metadata));
        dukto::SourceFile file(store.directory() + '/' + base() + ".json");
        auto identity = file.objectIdentity();
        if (!identity.endsWith(':'))
            throw std::runtime_error("snapshot test native identity");
        identity.chop(1);
        auto proof = dukto::next::parseControl(store.read(marker()));
        proof["expires"] = expiry.toString(Qt::ISODate);
        proof["metadata"] = QString::fromLatin1(identity.toHex());
        store.write(marker(), dukto::next::encodeControl(proof));
    }
    // 日期：2026-11-09；仅拼接生产返回的规范UUID，不用文件名前缀授予删除资格。
    QString base() const {
        return "browse-" + id.toString(QUuid::WithoutBraces);
    }
    // 日期：2026-11-09；凭据与快照键分开，避免影响原有每主体快照数量上限。
    QString marker() const {
        return "snapshot-retention-" + id.toString(QUuid::WithoutBraces) + ".json";
    }
};
} // namespace

class BrowseTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-09；精确到期边界、只读预览和重复清理均核对实际文件及原始用户源保持。
    void snapshotRetentionBoundaryAndPreview() {
        SnapshotFixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto before = store.read(fixture.marker());
        const auto source = dukto::hashFile(fixture.root.filePath("data/file.txt"));
        QVERIFY(!dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry.addSecs(-1),
                                                     true)["eligible"]
                     .toBool());
        QCOMPARE(
            dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, false)["action"]
                .toString(),
            QString("expired-preview"));
        QCOMPARE(store.read(fixture.marker()), before);
        QVERIFY(store.exists(fixture.base() + ".data"));
        QCOMPARE(
            dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true)["action"]
                .toString(),
            QString("cleaned"));
        for (const auto &name :
             {fixture.marker(), fixture.base() + ".data", fixture.base() + ".json"})
            QVERIFY(!store.exists(name));
        QVERIFY(!dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry,
                                                     true)["eligible"]
                     .toBool());
        QCOMPARE(dukto::hashFile(fixture.root.filePath("data/file.txt")), source);
    }

    // 日期：2026-11-09；损坏版本、额外字段、无效/非UTC时间及非规范身份都保留全部原件。
    void snapshotRetentionRejectsCorruption() {
        for (const auto &field : {QString("version"), QString("extra"), QString("expires"),
                                  QString("offset"), QString("root"), QString("data"),
                                  QString("metadata"), QString("snapshot"), QString("phase")}) {
            SnapshotFixture fixture;
            dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                      dukto::PrivateStore::Use::Maintenance);
            auto value = dukto::next::parseControl(store.read(fixture.marker()));
            if (field == "version")
                value[field] = 2;
            else if (field == "expires")
                value[field] = "invalid";
            else if (field == "offset")
                value["expires"] = "2000-01-01T01:00:00+01:00";
            else if (field == "phase")
                value[field] = "unknown";
            else
                value[field] = "bad";
            store.write(fixture.marker(), dukto::next::encodeControl(value));
            const auto raw = store.read(fixture.marker());
            const auto data = store.read(fixture.base() + ".data");
            const auto metadata = store.read(fixture.base() + ".json");
            QVERIFY_EXCEPTION_THROWN(
                dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true),
                dukto::Error);
            QCOMPARE(store.read(fixture.marker()), raw);
            QCOMPARE(store.read(fixture.base() + ".data"), data);
            QCOMPARE(store.read(fixture.base() + ".json"), metadata);
        }
    }

    // 日期：2026-11-09；正文或说明在同名位置换代时，任何旧凭据都不能删除新对象或另一未换代项。
    void snapshotRetentionPreservesReplacement() {
        for (const auto &suffix : {QString(".data"), QString(".json")}) {
            SnapshotFixture fixture;
            dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                      dukto::PrivateStore::Use::Maintenance);
            const auto name = fixture.base() + suffix;
            QVERIFY(QFile::rename(store.directory() + '/' + name, store.directory() + "/saved"));
            store.write(name, "replacement");
            const auto marker = store.read(fixture.marker());
            QVERIFY_EXCEPTION_THROWN(
                dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true),
                dukto::Error);
            QCOMPARE(store.read(name), QByteArray("replacement"));
            QCOMPARE(store.read(fixture.marker()), marker);
            QVERIFY(store.exists(fixture.base() + ".data"));
            QVERIFY(store.exists(fixture.base() + ".json"));
        }
    }

    // 日期：2026-11-09；删除意图和正文删除后的取消可重入，原目标和未知项保持。
    void snapshotRetentionCancellationAndAutomaticBatch() {
        for (const bool afterDelete : {false, true}) {
            SnapshotFixture fixture;
            {
                dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                          dukto::PrivateStore::Use::Maintenance);
                store.write("unknown.part", "unknown");
                QVERIFY_EXCEPTION_THROWN(
                    dukto::cleanupExpiredBrowseSnapshot(
                        store, fixture.id, fixture.expiry, true,
                        [&]() {
                            // 日期：2026-11-09；以实际持久意图/正文消失作为边界，不以回调次数模拟删除成功。
                            const auto proof =
                                dukto::next::parseControl(store.read(fixture.marker()));
                            if (proof["phase"] == "deleting" &&
                                (!afterDelete || !store.exists(fixture.base() + ".data")))
                                throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "test");
                        }),
                    dukto::Error);
            }
            dukto::PrivateStore reopened(fixture.root.filePath("service"), false,
                                         dukto::PrivateStore::Use::Maintenance);
            // 日期：2026-11-09；已持久授权的删除意图在时钟回退后仍可继续，不把半清理任务遗留到未来。
            const auto result = dukto::cleanupState(reopened, fixture.expiry.addSecs(-1), true);
            QCOMPARE(result["browseSnapshotsCleaned"].toString(), QString("1"));
            QCOMPARE(result["errorCount"].toString(), QString("0"));
            QVERIFY(!reopened.exists(fixture.marker()));
            QCOMPARE(reopened.read("unknown.part"), QByteArray("unknown"));
        }
    }

    // 日期：2026-11-09；真实进程在正文删除后直接退出，下一次独占维护按原意图恢复完成。
    void snapshotRetentionCrashAndSharedGuard() {
        SnapshotFixture fixture;
        {
            dukto::PrivateStore shared(fixture.root.filePath("service"));
            QVERIFY_EXCEPTION_THROWN(
                dukto::cleanupExpiredBrowseSnapshot(shared, fixture.id, fixture.expiry, true),
                dukto::Error);
        }
        QProcess child;
        child.start(QCoreApplication::applicationFilePath(),
                    {"--snapshot-cleanup-crash", fixture.root.filePath("service"),
                     fixture.id.toString(QUuid::WithoutBraces),
                     fixture.expiry.toString(Qt::ISODate)});
        QVERIFY(child.waitForFinished(10000));
        QCOMPARE(child.exitCode(), 46);
        dukto::PrivateStore reopened(fixture.root.filePath("service"), false,
                                     dukto::PrivateStore::Use::Maintenance);
        QVERIFY(!reopened.exists(fixture.base() + ".data"));
        QVERIFY(reopened.exists(fixture.marker()));
        QCOMPARE(dukto::cleanupExpiredBrowseSnapshot(reopened, fixture.id, fixture.expiry,
                                                     true)["action"]
                     .toString(),
                 QString("cleaned"));
    }

    // 日期：2026-11-09；新浏览同样回收已到期凭据及两正文项，避免只清正文而无限累积旁路。
    void snapshotRetentionBrowseCollection() {
        SnapshotFixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("service"));
        fixture.expireForBrowse(store);
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, false, false}}};
        const auto page = dukto::BrowseStore(store).list(principal, "docs", "");
        QVERIFY(!page["snapshot"].toString().isEmpty());
        QVERIFY(!store.exists(fixture.marker()));
        QVERIFY(!store.exists(fixture.base() + ".data"));
        QVERIFY(!store.exists(fixture.base() + ".json"));
        const auto markers = QDir(store.directory()).entryList({"snapshot-retention-*.json"});
        QCOMPARE(markers.size(), 1);
    }

    // 日期：2026-11-09；没有证据的老快照不因时间或名称被自动认领，旧正文和说明原字节保持。
    void snapshotRetentionPreservesLegacy() {
        SnapshotFixture fixture;
        QByteArray data, metadata;
        {
            dukto::PrivateStore store(fixture.root.filePath("service"));
            fixture.expireForBrowse(store);
            store.remove(fixture.marker());
            data = store.read(fixture.base() + ".data");
            metadata = store.read(fixture.base() + ".json");
            const dukto::Principal principal{
                QUuid::createUuid(), 1, {{"docs", true, false, false}}};
            dukto::BrowseStore(store).list(principal, "docs", "");
            QCOMPARE(store.read(fixture.base() + ".data"), data);
            QCOMPARE(store.read(fixture.base() + ".json"), metadata);
        }
        dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        QCOMPARE(
            dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true)["action"]
                .toString(),
            QString("no-retention-evidence"));
        QCOMPARE(store.read(fixture.base() + ".data"), data);
        QCOMPARE(store.read(fixture.base() + ".json"), metadata);
    }

    // 日期：2026-11-09；把原凭据及正文复制到同名新根仍拒绝，根身份不能由目录名冒充。
    void snapshotRetentionPreservesReplacedRoot() {
        SnapshotFixture fixture;
        QByteArray data, metadata, marker;
        {
            dukto::PrivateStore store(fixture.root.filePath("service"));
            data = store.read(fixture.base() + ".data");
            metadata = store.read(fixture.base() + ".json");
            marker = store.read(fixture.marker());
        }
        QVERIFY(QDir(fixture.root.path()).rename("service", "previous-service"));
        dukto::PrivateStore store(fixture.root.filePath("service"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write(fixture.base() + ".data", data);
        store.write(fixture.base() + ".json", metadata);
        store.write(fixture.marker(), marker);
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true),
            dukto::Error);
        QCOMPARE(store.read(fixture.base() + ".data"), data);
        QCOMPARE(store.read(fixture.base() + ".json"), metadata);
        QCOMPARE(store.read(fixture.marker()), marker);
    }

    // 日期：2026-11-09；删除意图后出现同名新正文时不继续删除另一项，保留意图供人工核对。
    void snapshotRetentionReplacementAfterInterruptedDelete() {
        SnapshotFixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("service"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto metadata = store.read(fixture.base() + ".json");
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredBrowseSnapshot(
                                     store, fixture.id, fixture.expiry, true,
                                     [&]() {
                                         // 日期：2026-11-09；只在真实正文消失后中断，再建立独立的新对象模拟外部换代。
                                         if (!store.exists(fixture.base() + ".data"))
                                             throw dukto::Error(dukto::ExitCode::Cancelled,
                                                                "cancel", "test");
                                     }),
                                 dukto::Error);
        store.write(fixture.base() + ".data", "new-object");
        const auto marker = store.read(fixture.marker());
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupExpiredBrowseSnapshot(store, fixture.id, fixture.expiry, true),
            dukto::Error);
        QCOMPARE(store.read(fixture.base() + ".data"), QByteArray("new-object"));
        QCOMPARE(store.read(fixture.base() + ".json"), metadata);
        QCOMPARE(store.read(fixture.marker()), marker);
    }

    // 日期：2026-11-09；真实CLI预览/执行和生产状态根打开均接通快照回收，活动共享时明确拒绝。
    void snapshotRetentionProductionEntrypoints() {
        for (const bool commandLine : {false, true}) {
            SnapshotFixture fixture;
            QByteArray marker;
            {
                dukto::PrivateStore store(fixture.root.filePath("service"));
                fixture.expireForBrowse(store);
                marker = store.read(fixture.marker());
            }
            if (commandLine) {
                auto executable =
                    QDir(QCoreApplication::applicationDirPath()).filePath("dukto-cli");
#ifdef Q_OS_WIN
                executable += ".exe";
#endif
                QStringList args{
                    "state",        "gc",      "preview", "--state-directory", fixture.root.path(),
                    "--state-root", "service", "--json"};
                const auto invoke = [&](int expected) {
                    // 日期：2026-11-09；核对真实命令退出码与规范JSON，不以启动成功代替清理成功。
                    QProcess process;
                    process.start(executable, args);
                    if (!process.waitForFinished(30000) || process.exitCode() != expected)
                        throw dukto::Error(dukto::ExitCode::Runtime,
                                           QString::fromUtf8(process.readAllStandardError()),
                                           "test");
                    const auto result = dukto::next::parseControl(process.readAllStandardOutput());
                    return result;
                };
                QCOMPARE(invoke(0)["browseSnapshotsVisited"].toString(), QString("1"));
                {
                    dukto::PrivateStore store(fixture.root.filePath("service"));
                    QCOMPARE(store.read(fixture.marker()), marker);
                    QCOMPARE(invoke(int(dukto::ExitCode::Permission))["stage"].toString(),
                             QString("state-use"));
                }
                args[2] = "run";
                QCOMPARE(invoke(0)["browseSnapshotsCleaned"].toString(), QString("1"));
            } else {
                const auto active = dukto::StateSession::root(fixture.root.path(), "service");
                QVERIFY(!active->exists(fixture.marker()));
                QVERIFY(active->exists("gc-last.json"));
            }
            dukto::PrivateStore store(fixture.root.filePath("service"));
            QVERIFY(!store.exists(fixture.marker()));
            QVERIFY(!store.exists(fixture.base() + ".data"));
            QVERIFY(!store.exists(fixture.base() + ".json"));
            QVERIFY(QFileInfo::exists(fixture.root.filePath("data/file.txt")));
        }
    }

    // 日期：2026-11-04；扫描中撤销权限时不发布快照或返回列表，失败后归还临时文件和快照槽位。
    void authorizationRevokedDuringScan() {
        QTemporaryDir root;
        const auto data = root.filePath("data");
        QVERIFY(QDir().mkdir(data));
        createFile(data + "/sample");
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::Shares shares(store);
        shares.set({{"docs", true, true, false}, data});
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, false, false}}};
        int checks = 0;
        dukto::BrowseStore browser(store, nullptr, [&]() {
            // 日期：2026-11-04；在开始检查后缩减真实共享，发布前的同一生产回调必须重新检查。
            if (++checks >= 2)
                shares.set({{"docs", false, true, false}, data});
            shares.open(principal, "docs", dukto::Access::Browse);
        });
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", ""), dukto::Error);
        QVERIFY(checks >= 2);
        const QDir directory(store.directory());
        QVERIFY(
            directory
                .entryList({"browse-*.data", "browse-*.json", "*.part"}, QDir::Files | QDir::Hidden)
                .isEmpty());
    }
    // 日期：2026-11-04；301 个 Unicode 文件逐页去重覆盖，重复游标幂等，响应同时满足字节/条数上限。
    void pagesAndCursorBoundaries() {
        QTemporaryDir root;
        const auto data = root.filePath("data");
        QVERIFY(QDir().mkdir(data));
        for (int index = 0; index < 301; ++index)
            createFile(data + QStringLiteral("/文件-%1.txt").arg(index));
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::Shares shares(store);
        shares.set({{"docs", true, true, false}, data});
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, true, false}}};
        dukto::BrowseStore browser(store);
        auto page = browser.list(principal, "docs", "");
        QSet<QString> names;
        const auto firstCursor = page["cursor"].toString();
        QVERIFY(!firstCursor.isEmpty());
        QCOMPARE(browser.list(principal, "docs", "", firstCursor),
                 browser.list(principal, "docs", "", firstCursor));
        int pages = 0;
        while (true) {
            ++pages;
            const auto entries = page["entries"].toArray();
            QVERIFY(entries.size() <= 100);
            QVERIFY(dukto::next::encodeControl(page).size() <= dukto::next::ControlLimit);
            for (const auto &entry : entries) {
                const auto object = entry.toObject();
                QVERIFY(!names.contains(object["name"].toString()));
                names.insert(object["name"].toString());
                QCOMPARE(object["type"].toString(), QString("file"));
                QCOMPARE(object["bytes"].toString(), QString("6"));
            }
            const auto cursor = page["cursor"].toString();
            if (cursor.isEmpty())
                break;
            page = browser.list(principal, "docs", "", cursor);
        }
        QCOMPARE(pages, 4);
        QCOMPARE(names.size(), 301);
        auto other = principal;
        other.client = QUuid::createUuid();
        QVERIFY_EXCEPTION_THROWN(browser.list(other, "docs", "", firstCursor), dukto::Error);
        auto tampered = firstCursor;
        tampered[tampered.size() - 1] = tampered.endsWith('0') ? '1' : '0';
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "", tampered), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "../x"), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "other", "", firstCursor), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "sub", firstCursor), dukto::Error);
        shares.set({{"docs", false, true, false}, data});
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "", firstCursor), dukto::Error);
    }
    // 日期：2026-11-04；目录新增项后旧游标拒绝，空目录仍正确返回空页，新快照有固定数量上限。
    void directoryChangesAndQuota() {
        QTemporaryDir root;
        const auto data = root.filePath("data");
        QVERIFY(QDir().mkdir(data));
        for (int index = 0; index < 101; ++index)
            createFile(data + QString("/sample-%1").arg(index));
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::Shares shares(store);
        shares.set({{"docs", true, true, false}, data});
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, false, false}}};
        dukto::BrowseStore browser(store);
        const auto first = browser.list(principal, "docs", "");
        const auto cursor = first["cursor"].toString();
        QVERIFY(!cursor.isEmpty());
        QTest::qWait(10);
        createFile(data + "/new-file");
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "", cursor), dukto::Error);
        QVERIFY(QDir().mkdir(data + "/empty"));
        const auto empty = browser.list(principal, "docs", "empty");
        QVERIFY(empty["entries"].toArray().isEmpty());
        QVERIFY(empty["cursor"].toString().isEmpty());
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", ""), dukto::Error);
        std::atomic_bool cancel{true};
        dukto::BrowseStore cancelled(store, &cancel);
        QVERIFY_EXCEPTION_THROWN(cancelled.list(principal, "docs", "empty"), dukto::Error);
        const auto meta = root.filePath("private/browse-" + first["snapshot"].toString() + ".json");
        QFile metadata(meta);
        QVERIFY(metadata.open(QIODevice::ReadOnly));
        auto object = dukto::next::parseControl(metadata.readAll());
        metadata.close();
        object["expires"] = "2000-01-01T00:00:00Z";
        store.write(QFileInfo(meta).fileName(), dukto::next::encodeControl(object));
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", "", cursor), dukto::Error);
        // 日期：2026-11-09；说明已由原子替换换代，旧凭据不能因伪造到期时间删除新对象。
        QVERIFY_EXCEPTION_THROWN(browser.list(principal, "docs", ""), dukto::Error);
        QVERIFY(QFile::exists(meta));
        QVERIFY(store.exists("browse-" + first["snapshot"].toString() + ".data"));
    }
#ifdef Q_OS_WIN
    // 日期：2026-11-04；NTFS 的长 Unicode 分量产生大项，必须在 100 项之前按 64 KiB 正文预算切页。
    void longNamesRespectSerializedBudget() {
        QTemporaryDir root;
        const auto data = root.filePath("data");
        QVERIFY(QDir().mkdir(data));
        for (int index = 0; index < 100; ++index)
            createFile(data + '/' + QString(240, QChar(0x4e2d)) + QString::number(index));
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::Shares(store).set({{"docs", true, true, false}, data});
        const dukto::Principal principal{QUuid::createUuid(), 1, {{"docs", true, true, false}}};
        dukto::BrowseStore browser(store);
        const auto page = browser.list(principal, "docs", "");
        QVERIFY(page["entries"].toArray().size() < 100);
        QVERIFY(!page["cursor"].toString().isEmpty());
        QVERIFY(dukto::next::encodeControl(page).size() <= dukto::next::ControlLimit);
        const auto second = browser.list(principal, "docs", "", page["cursor"].toString());
        QCOMPARE(page["entries"].toArray().size() + second["entries"].toArray().size(), 100);
    }
#endif
};
// 日期：2026-11-09；子进程只操作自有样本，正常入口仍运行完整QtTest并保存真实原件。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    if (args.size() == 5 && args[1] == "--snapshot-cleanup-crash") {
        dukto::PrivateStore store(args[2], false, dukto::PrivateStore::Use::Maintenance);
        const auto id = QUuid(args[3]);
        dukto::cleanupExpiredBrowseSnapshot(store, id, QDateTime::fromString(args[4], Qt::ISODate),
                                            true, [&]() {
                                                // 日期：2026-11-09；正文真实消失后跳过析构退出，保留已同步的删除意图。
                                                if (!store.exists("browse-" + args[3] + ".data"))
                                                    std::_Exit(46);
                                            });
        return 47;
    }
    try {
        BrowseTests tests;
        return QTest::qExec(&tests, argc, argv);
    } catch (const dukto::Error &error) {
        std::fprintf(stderr, "browse fixture error: %s [%s]\n", error.message.toUtf8().constData(),
                     error.stage.toUtf8().constData());
        return 1;
    }
}
#include "browse_tests.moc"

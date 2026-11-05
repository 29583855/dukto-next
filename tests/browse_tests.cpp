#include "core/browse.h"
#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QTemporaryDir>
#include <QtTest>

namespace {
// 日期：2026-11-04；每个样本在独立临时根建立文件，避免改动用户目录及参考软件。
void createFile(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write("sample") != 6)
        throw std::runtime_error("cannot create isolated browse fixture");
}
} // namespace

class BrowseTests final : public QObject {
    Q_OBJECT
  private slots:
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
        browser.list(principal, "docs", "");
        QVERIFY(!QFile::exists(meta));
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
QTEST_GUILESS_MAIN(BrowseTests)
#include "browse_tests.moc"

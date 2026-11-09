#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/service.h"
#include "core/statecleanup.h"
#include "core/statesession.h"
#include "core/uploadmanifest.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdlib>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <aclapi.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace {
// 日期：2026-11-07；测试只在自建目录中写源文件，真实上传扫描由子进程运行。
struct Fixture {
    QTemporaryDir root;
    const QString parent = root.filePath("client");
    const QString state = parent + "/transfers";
    const QUuid request = QUuid::createUuid();
    dukto::ClientProfile profile;

    // 日期：2026-11-07；固定主体及请求传给真实子进程，不使用网络、用户配置或测试专用生产分支。
    Fixture() {
        profile.server = QUuid::createUuid();
        profile.client = QUuid::createUuid();
        if (!root.isValid() || !QDir().mkpath(parent))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture directory", "test");
        QFile source(root.filePath("source.bin"));
        if (!source.open(QIODevice::WriteOnly) || source.write("abc") != 3)
            throw dukto::Error(dukto::ExitCode::Disk, "fixture source", "test");
    }

    // 日期：2026-11-07；键由生产规范请求ID唯一推导，所有文件检查独立于清理返回结果。
    QString stem() const {
        return "upload-source-" + request.toString(QUuid::WithoutBraces);
    }

    // 日期：2026-11-07；子进程以_Exit跳过Qt和SQLite析构，保存真实扫描/回滚日志。
    void abandon(const QString &phase) const {
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--abandon-scan", root.path(), request.toString(QUuid::WithoutBraces),
                       profile.server.toString(QUuid::WithoutBraces),
                       profile.client.toString(QUuid::WithoutBraces), phase});
        if (!process.waitForFinished(30000) || process.exitCode() != 47)
            throw dukto::Error(dukto::ExitCode::Runtime, "fixture abandoned scan", "test");
    }

    // 日期：2026-11-07；只修改自有测试时钟字段，避免实际等待七天；产品使用真实UTC时间。
    void age() const {
        dukto::PrivateStore store(state);
        auto value = dukto::next::parseControl(store.read(stem() + ".scan.json"));
        value["created"] = QString::number(QDateTime::currentSecsSinceEpoch() - 8 * 86400);
        store.write(stem() + ".scan.json", dukto::next::encodeControl(value));
    }
};

// 日期：2026-11-07；在真实库创建小缓存未提交事务，物理溢写产生可由SQLite自身恢复的热日志。
void leaveHotJournal(const QString &path) {
    auto database = QSqlDatabase::addDatabase("QSQLITE", "crash-scan");
    database.setDatabaseName(path);
    if (!database.open())
        std::_Exit(91);
    QSqlQuery query(database);
    for (const auto &sql : {"PRAGMA cache_size=8", "PRAGMA cache_spill=ON", "BEGIN IMMEDIATE"})
        if (!query.exec(sql))
            std::_Exit(92);
    for (int index = 1; index <= 64; ++index) {
        query.prepare("INSERT INTO entries VALUES(?,?,zeroblob(65536),0,0,x'',?)");
        query.addBindValue(index);
        query.addBindValue(QString::number(index));
        query.addBindValue(QString::number(index));
        if (!query.exec())
            std::_Exit(93);
    }
    QFile journal(path + "-journal");
    if (!journal.open(QIODevice::ReadOnly) || journal.read(8).toHex() != "d9d505f920a163d7")
        std::_Exit(94);
    std::_Exit(47);
}
} // namespace

class UploadScanCleanupTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；真实直接退出遗留扫描在业务打开前自动清理，源文件和未知同名普通项保持。
    void automaticAbandonedScanCleanup() {
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        const auto source = dukto::hashFile(fixture.root.filePath("source.bin"));
        {
            dukto::PrivateStore store(fixture.state);
            store.write("unknown.part", "preserve-me");
        }
        const auto store = dukto::StateSession::root(fixture.parent, "transfers");
        QVERIFY(!store->exists(fixture.stem() + ".sqlite"));
        QVERIFY(!store->exists(fixture.stem() + ".scan.json"));
        QCOMPARE(store->read("unknown.part"), QByteArray("preserve-me"));
        QCOMPARE(dukto::hashFile(fixture.root.filePath("source.bin")), source);
    }

    // 日期：2026-11-08；目录扫描分批继续，预览不落进度且新鲜扫描不因开启自动维护而提前删除。
    void batchScanCursorAndRetention() {
        Fixture fixture;
        fixture.abandon("before");
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        dukto::StateCleanupLimits limits;
        limits.directoryEntries = 1;
        limits.milliseconds = 30000;
        const auto now = QDateTime::currentDateTimeUtc();
        const auto preview = dukto::cleanupState(store, now, false, limits);
        QVERIFY(preview["more"].toBool());
        QVERIFY(!store.exists("gc-cursor.json"));
        bool wrapped = false;
        for (int pass = 0; pass < 32; ++pass) {
            const auto result = dukto::cleanupState(store, now, true, limits);
            QCOMPARE(result["errorCount"].toString(), QString("0"));
            QVERIFY(store.exists(fixture.stem() + ".sqlite"));
            if (!result["more"].toBool()) {
                wrapped = true;
                break;
            }
        }
        QVERIFY(wrapped);
        auto marker = dukto::next::parseControl(store.read(fixture.stem() + ".scan.json"));
        marker["created"] = QString::number(now.toSecsSinceEpoch() - 8 * 86400);
        store.write(fixture.stem() + ".scan.json", dukto::next::encodeControl(marker));
        for (int pass = 0; pass < 32 && store.exists(fixture.stem() + ".sqlite"); ++pass)
            dukto::cleanupState(store, now, true, limits);
        QVERIFY(!store.exists(fixture.stem() + ".sqlite"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("source.bin")));
    }

    // 日期：2026-11-07；空闲已建库和真实热回滚库均需按相同持久身份恢复。
    void retainedPreviewAndCleanup_data() {
        QTest::addColumn<QString>("phase");
        QTest::newRow("before-scan") << QString("before");
        QTest::newRow("hot-journal") << QString("hot");
    }

    // 日期：2026-11-07；未到期不删，预览不改任何原字节；执行删除后原源内容和再次扫描均正确。
    void retainedPreviewAndCleanup() {
        QFETCH(QString, phase);
        Fixture fixture;
        fixture.abandon(phase);
        const auto databasePath = fixture.state + "/" + fixture.stem() + ".sqlite";
        const auto before = dukto::hashFile(databasePath);
        const auto journalPath = databasePath + "-journal";
        const auto journal =
            QFileInfo::exists(journalPath) ? dukto::hashFile(journalPath) : QByteArray();
        {
            dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
            const auto result = dukto::cleanupUploadScan(store, fixture.request,
                                                         QDateTime::currentDateTimeUtc(), true);
            QCOMPARE(result["action"].toString(), QString("retained"));
        }
        fixture.age();
        {
            dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
            const auto marker = store.read(fixture.stem() + ".scan.json");
            const auto result = dukto::cleanupUploadScan(store, fixture.request,
                                                         QDateTime::currentDateTimeUtc(), false);
            QCOMPARE(result["action"].toString(), QString("pending-cleanup"));
            QCOMPARE(dukto::hashFile(databasePath), before);
            QCOMPARE(store.read(fixture.stem() + ".scan.json"), marker);
            if (!journal.isEmpty())
                QCOMPARE(dukto::hashFile(journalPath), journal);
            const auto baseline = QSqlDatabase::connectionNames();
            QCOMPARE(dukto::cleanupUploadScan(store, fixture.request,
                                              QDateTime::currentDateTimeUtc(), true)["action"]
                         .toString(),
                     QString("cleaned"));
            QCOMPARE(QSqlDatabase::connectionNames(), baseline);
            QVERIFY(!store.exists(fixture.stem() + ".sqlite"));
            QVERIFY(!store.exists(fixture.stem() + ".scan.json"));
            QVERIFY(!QFileInfo::exists(journalPath));
            QCOMPARE(dukto::cleanupUploadScan(store, fixture.request,
                                              QDateTime::currentDateTimeUtc(), true)["action"]
                         .toString(),
                     QString("absent"));
        }
        dukto::PrivateStore store(fixture.state);
        dukto::UploadManifest restarted(store, fixture.request, fixture.profile, "data", "",
                                        dukto::ConflictPolicy::Rename,
                                        {fixture.root.filePath("source.bin")});
        QCOMPARE(restarted.get().summary()["bytes"].toString(), QString("3"));
        QCOMPARE(restarted.get().entry(1).sha256,
                 QCryptographicHash::hash("abc", QCryptographicHash::Sha256));
        QVERIFY(!store.exists(fixture.stem() + ".scan.json"));
    }

    // 日期：2026-11-07；两个真实清理进程退出窗口均须可重入，同名新对象另作拒绝验证。
    void interruptedCleanup_data() {
        QTest::addColumn<QString>("phase");
        QTest::newRow("before-delete") << QString("before-delete");
        QTest::newRow("after-delete") << QString("after-delete");
        QTest::newRow("after-delete-replaced") << QString("replaced");
    }

    // 日期：2026-11-07；删除意图FULL持久，崩溃后不重复删除同名新对象，原任务ID可安全续做。
    void interruptedCleanup() {
        QFETCH(QString, phase);
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--cleanup-crash", fixture.state,
                       fixture.request.toString(QUuid::WithoutBraces),
                       phase == "before-delete" ? "before-delete" : "after-delete"});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 48);
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        if (phase == "replaced") {
            store.write(fixture.stem() + ".sqlite", "replacement");
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                              QDateTime::currentDateTimeUtc(),
                                                              true),
                                     dukto::Error);
            QCOMPARE(store.read(fixture.stem() + ".sqlite"), QByteArray("replacement"));
            QVERIFY(store.exists(fixture.stem() + ".scan.json"));
        } else {
            QCOMPARE(dukto::cleanupUploadScan(store, fixture.request,
                                              QDateTime::currentDateTimeUtc(), true)["action"]
                         .toString(),
                     QString("cleaned"));
            QVERIFY(!store.exists(fixture.stem() + ".sqlite"));
        }
    }

    // 日期：2026-11-07；损坏的证明不得降低为缺失或自动重建，未知旧库同样保留。
    void damagedEvidence_data() {
        QTest::addColumn<QString>("field");
        for (const auto &field : {"native", "rootIdentity", "request", "version", "created",
                                  "phase", "extra", "missing"})
            QTest::newRow(field) << QString(field);
        QTest::newRow("binding-identity") << QString("binding");
    }

    // 日期：2026-11-07；逐项独立破坏证据后要求库原字节保持，不仅检查返回了错误。
    void damagedEvidence() {
        QFETCH(QString, field);
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        auto proof = dukto::next::parseControl(store.read(fixture.stem() + ".scan.json"));
        const auto before = dukto::hashFile(fixture.state + "/" + fixture.stem() + ".sqlite");
        if (field == "missing") {
            store.remove(fixture.stem() + ".scan.json");
            QCOMPARE(dukto::cleanupUploadScan(store, fixture.request,
                                              QDateTime::currentDateTimeUtc(), true)["action"]
                         .toString(),
                     QString("preserved-unknown"));
        } else {
            if (field == "binding") {
                auto binding = proof[field].toObject();
                binding["server"] = "invalid";
                proof[field] = binding;
            } else
                proof[field] = field == "version" ? QJsonValue(2) : QJsonValue("invalid");
            store.write(fixture.stem() + ".scan.json", dukto::next::encodeControl(proof));
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                              QDateTime::currentDateTimeUtc(),
                                                              true),
                                     dukto::Error);
        }
        QCOMPARE(dukto::hashFile(fixture.state + "/" + fixture.stem() + ".sqlite"), before);
    }

    // 日期：2026-11-07；已发布冻结或已创建请求均优先保留，即使残留扫描记录已经过期。
    void publishedAndLocks() {
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        {
            dukto::PrivateStore shared(fixture.state);
            QVERIFY_EXCEPTION_THROWN(
                dukto::PrivateStore(fixture.state, false, dukto::PrivateStore::Use::Maintenance),
                dukto::Error);
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(shared, fixture.request,
                                                              QDateTime::currentDateTimeUtc(),
                                                              true),
                                     dukto::Error);
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QLockFile held(fixture.state + "/" + fixture.stem() + ".lock");
        held.setStaleLockTime(0);
        QVERIFY(held.tryLock(0));
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(), true),
            dukto::Error);
        held.unlock();
        for (const auto &name :
             {fixture.stem() + ".json",
              "upload-request-" + fixture.request.toString(QUuid::WithoutBraces) + ".json"}) {
            store.write(name, "{}");
            QCOMPARE(dukto::cleanupUploadScan(store, fixture.request,
                                              QDateTime::currentDateTimeUtc(), true)["action"]
                         .toString(),
                     QString("preserved-published"));
            QVERIFY(store.exists(fixture.stem() + ".sqlite"));
            store.remove(name);
        }
    }

    // 日期：2026-11-07；WAL、未知旁路及原生替换拒绝时保留数据库、证明和用户原文件。
    void unsafeObjects_data() {
        QTest::addColumn<QString>("kind");
        QTest::newRow("wal") << QString("wal");
        QTest::newRow("shm") << QString("shm");
        QTest::newRow("replacement") << QString("replacement");
        QTest::newRow("symbolic-link") << QString("link");
    }

    // 日期：2026-11-07；清理必须实际核对对象身份和不跟随链接，不能仅接受规范缓存文件名。
    void unsafeObjects() {
        QFETCH(QString, kind);
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto name = fixture.stem() + ".sqlite";
        const auto path = fixture.state + "/" + name;
        const auto proof = store.read(fixture.stem() + ".scan.json");
        if (kind == "wal" || kind == "shm") {
            store.write(name + "-" + kind, "preserve-sidecar");
        } else {
            QVERIFY(QFile::rename(path, path + ".old"));
            if (kind == "link") {
#ifdef Q_OS_WIN
                const auto target = QDir::toNativeSeparators(fixture.root.filePath("source.bin"));
                const auto link = QDir::toNativeSeparators(path);
                if (!CreateSymbolicLinkW(reinterpret_cast<LPCWSTR>(link.utf16()),
                                         reinterpret_cast<LPCWSTR>(target.utf16()), 2) &&
                    !CreateSymbolicLinkW(reinterpret_cast<LPCWSTR>(link.utf16()),
                                         reinterpret_cast<LPCWSTR>(target.utf16()), 0))
                    QSKIP("Windows account cannot create a native symbolic link");
#else
                QVERIFY(QFile::link(fixture.root.filePath("source.bin"), path));
#endif
            } else
                store.write(name, "replacement");
        }
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                          QDateTime::currentDateTimeUtc(), false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(), true),
            dukto::Error);
        QCOMPARE(store.read(fixture.stem() + ".scan.json"), proof);
        if (kind == "wal" || kind == "shm")
            QCOMPARE(store.read(name + "-" + kind), QByteArray("preserve-sidecar"));
        if (kind == "replacement")
            QCOMPARE(store.read(name), QByteArray("replacement"));
        QFile source(fixture.root.filePath("source.bin"));
        QVERIFY(source.open(QIODevice::ReadOnly));
        QCOMPARE(source.readAll(), QByteArray("abc"));
    }

    // 日期：2026-11-07；专门校验只能在独占维护下用于规范journal，普通文件所有者规则仍严格。
    void journalAccessBoundary() {
        Fixture fixture;
        fixture.abandon("hot");
        const auto name = fixture.stem() + ".sqlite-journal";
        const auto path = fixture.state + "/" + name;
        const auto before = dukto::hashFile(path);
        {
            dukto::PrivateStore shared(fixture.state);
            QVERIFY_EXCEPTION_THROWN(shared.validateSqliteJournal(name), dukto::Error);
        }
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        QVERIFY(store.validateSqliteJournal(name) > 0);
        for (const auto &invalid : {fixture.stem() + ".sqlite", name + "-wal", name + "-shm",
                                    "../" + name, QString("state-use.lock")})
            QVERIFY_EXCEPTION_THROWN(store.validateSqliteJournal(invalid), dukto::Error);
#ifdef Q_OS_WIN
        const auto native = QDir::toNativeSeparators(path);
        PSID owner = nullptr;
        PSECURITY_DESCRIPTOR security = nullptr;
        QCOMPARE(GetNamedSecurityInfoW(
                     const_cast<LPWSTR>(reinterpret_cast<LPCWSTR>(native.utf16())), SE_FILE_OBJECT,
                     OWNER_SECURITY_INFORMATION, &owner, nullptr, nullptr, nullptr, &security),
                 DWORD(ERROR_SUCCESS));
        const bool defaultAdmin = IsWellKnownSid(owner, WinBuiltinAdministratorsSid);
        LocalFree(security);
        if (defaultAdmin) {
            QVERIFY_EXCEPTION_THROWN(store.validateFile(name), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.read(name), dukto::Error);
        } else
            QCOMPARE(store.validateFile(name), QFileInfo(path).size());
#else
        QCOMPARE(store.validateFile(name), QFileInfo(path).size());
#endif
        QCOMPARE(dukto::hashFile(path), before);
    }

    // 日期：2026-11-07；真实热日志一旦向其他主体开放读取，预览与执行都必须拒绝且不恢复或删除原件。
    void unsafeJournalPermissions() {
        Fixture fixture;
        fixture.abandon("hot");
        fixture.age();
        const auto database = fixture.state + "/" + fixture.stem() + ".sqlite";
        const auto journal = database + "-journal";
        const auto before = dukto::hashFile(database);
        const auto journalBefore = dukto::hashFile(journal);
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto marker = store.read(fixture.stem() + ".scan.json");
#ifdef Q_OS_WIN
        const auto native = QDir::toNativeSeparators(journal);
        auto name = const_cast<LPWSTR>(reinterpret_cast<LPCWSTR>(native.utf16()));
        PACL original = nullptr;
        PSECURITY_DESCRIPTOR security = nullptr;
        QCOMPARE(GetNamedSecurityInfoW(name, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr,
                                       nullptr, &original, nullptr, &security),
                 DWORD(ERROR_SUCCESS));
        BYTE everyone[SECURITY_MAX_SID_SIZE];
        DWORD length = sizeof(everyone);
        QVERIFY(CreateWellKnownSid(WinWorldSid, nullptr, everyone, &length));
        EXPLICIT_ACCESSW entry{};
        entry.grfAccessPermissions = FILE_GENERIC_READ;
        entry.grfAccessMode = GRANT_ACCESS;
        entry.grfInheritance = NO_INHERITANCE;
        BuildTrusteeWithSidW(&entry.Trustee, everyone);
        PACL widened = nullptr;
        const auto result = SetEntriesInAclW(1, &entry, original, &widened);
        LocalFree(security);
        QCOMPARE(result, DWORD(ERROR_SUCCESS));
        const auto applied = SetNamedSecurityInfoW(name, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                                   nullptr, nullptr, widened, nullptr);
        LocalFree(widened);
        QCOMPARE(applied, DWORD(ERROR_SUCCESS));
#else
        QVERIFY(
            QFile::setPermissions(journal, QFile::permissions(journal) | QFileDevice::ReadOther));
#endif
        for (const bool apply : {false, true}) {
            bool rejected = false;
            try {
                dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(),
                                         apply);
            } catch (const dukto::Error &error) {
                QCOMPARE(error.code, dukto::ExitCode::Permission);
                QCOMPARE(error.stage, QString("identity"));
                rejected = true;
            }
            QVERIFY(rejected);
            QCOMPARE(dukto::hashFile(database), before);
            QCOMPARE(dukto::hashFile(journal), journalBefore);
            QCOMPARE(store.read(fixture.stem() + ".scan.json"), marker);
        }
    }

    // 日期：2026-11-07；回滚日志的硬链接和符号链接均不能借用专门所有者规则进入SQLite恢复。
    void unsafeJournalLinks_data() {
        QTest::addColumn<bool>("symbolic");
        QTest::newRow("hard-link") << false;
        QTest::newRow("symbolic-link") << true;
    }

    // 日期：2026-11-07；替换为指向外部原日志的真实链接，拒绝后外部日志/数据库/清理凭据保持原字节。
    void unsafeJournalLinks() {
        QFETCH(bool, symbolic);
        Fixture fixture;
        fixture.abandon("hot");
        fixture.age();
        const auto database = fixture.state + "/" + fixture.stem() + ".sqlite";
        const auto path = database + "-journal";
        const auto target = fixture.root.filePath("outside-journal");
        const auto before = dukto::hashFile(database);
        const auto journalBefore = dukto::hashFile(path);
        QVERIFY(QFile::rename(path, target));
#ifdef Q_OS_WIN
        const auto native = QDir::toNativeSeparators(path);
        const auto destination = QDir::toNativeSeparators(target);
        const auto link = reinterpret_cast<LPCWSTR>(native.utf16());
        const auto source = reinterpret_cast<LPCWSTR>(destination.utf16());
        if (symbolic) {
            if (!CreateSymbolicLinkW(link, source, 2) && !CreateSymbolicLinkW(link, source, 0))
                QSKIP("Windows account cannot create a native symbolic link");
        } else
            QVERIFY(CreateHardLinkW(link, source, nullptr));
#else
        if (symbolic)
            QVERIFY(QFile::link(target, path));
        else
            QCOMPARE(
                ::link(QFile::encodeName(target).constData(), QFile::encodeName(path).constData()),
                0);
#endif
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto marker = store.read(fixture.stem() + ".scan.json");
        for (const bool apply : {false, true}) {
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                              QDateTime::currentDateTimeUtc(),
                                                              apply),
                                     dukto::Error);
            QCOMPARE(dukto::hashFile(database), before);
            QCOMPARE(dukto::hashFile(target), journalBefore);
            QCOMPARE(store.read(fixture.stem() + ".scan.json"), marker);
        }
    }

    // 日期：2026-11-07；持久删除后正常取消必须留下意图供恢复，不能只在进程崩溃时才可重入。
    void cancelledCleanup() {
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto cancel = [&]() {
            // 日期：2026-11-07；观察真实删除而非回调计数，保证覆盖已删除但尚未确认的取消窗口。
            if (!store.exists(fixture.stem() + ".sqlite"))
                throw dukto::Error(dukto::ExitCode::Cancelled, "cancel", "cleanup");
        };
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                          QDateTime::currentDateTimeUtc(), true,
                                                          cancel),
                                 dukto::Error);
        QVERIFY(store.exists(fixture.stem() + ".scan.json"));
        QCOMPARE(dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(),
                                          true)["action"]
                     .toString(),
                 QString("cleaned"));
    }

    // 日期：2026-11-07；数据库对象内容被外部破坏后拒绝删除，连接和共享缓存配额均应归还。
    void corruptDatabase() {
        Fixture fixture;
        fixture.abandon("before");
        fixture.age();
        const auto path = fixture.state + "/" + fixture.stem() + ".sqlite";
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
        QCOMPARE(file.write("corrupted database"), qint64(18));
        file.close();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto baseline = QSqlDatabase::connectionNames();
        const auto usage = dukto::BufferCredit::usage().value("used");
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(), true),
            dukto::Error);
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        QCOMPARE(dukto::BufferCredit::usage().value("used"), usage);
        QCOMPARE(store.read(fixture.stem() + ".sqlite"), QByteArray("corrupted database"));
        QVERIFY(store.exists(fixture.stem() + ".scan.json"));
    }

    // 日期：2026-11-07；缓存额度耗尽时不得遗留Qt连接或改动原库，额度归还后同请求可重试。
    void exhaustedCacheCredit() {
        Fixture fixture;
        fixture.abandon("hot");
        fixture.age();
        dukto::PrivateStore store(fixture.state, false, dukto::PrivateStore::Use::Maintenance);
        const auto name = fixture.stem() + ".sqlite";
        const auto before = dukto::hashFile(fixture.state + "/" + name);
        const auto journal = dukto::hashFile(fixture.state + "/" + name + "-journal");
        const auto marker = store.read(fixture.stem() + ".scan.json");
        const auto baseline = QSqlDatabase::connectionNames();
        const auto usage = dukto::BufferCredit::usage();
        {
            dukto::BufferCredit occupied(usage.value("limit").toString().toLongLong() -
                                         usage.value("used").toString().toLongLong());
            for (int attempt = 0; attempt < 3; ++attempt) {
                QVERIFY_EXCEPTION_THROWN(dukto::cleanupUploadScan(store, fixture.request,
                                                                  QDateTime::currentDateTimeUtc(),
                                                                  true),
                                         dukto::Error);
                QCOMPARE(QSqlDatabase::connectionNames(), baseline);
                QCOMPARE(dukto::hashFile(fixture.state + "/" + name), before);
                QCOMPARE(dukto::hashFile(fixture.state + "/" + name + "-journal"), journal);
                QCOMPARE(store.read(fixture.stem() + ".scan.json"), marker);
            }
        }
        QCOMPARE(dukto::BufferCredit::usage().value("used"), usage.value("used"));
        QCOMPARE(dukto::cleanupUploadScan(store, fixture.request, QDateTime::currentDateTimeUtc(),
                                          true)["action"]
                     .toString(),
                 QString("cleaned"));
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        QCOMPARE(dukto::BufferCredit::usage().value("used"), usage.value("used"));
    }

    // 日期：2026-11-07；实际CLI按请求执行同一核心，命令不依赖GUI，非法选项不能进入删除。
    void realCli() {
        Fixture fixture;
        fixture.abandon("hot");
        fixture.age();
        auto cli = QDir(QCoreApplication::applicationDirPath()).filePath("dukto-cli");
#ifdef Q_OS_WIN
        cli += ".exe";
#endif
        QProcess invalid;
        invalid.start(cli, {"--json", "--state-directory", fixture.parent, "client", "scan-cleanup",
                            "run", "--request-id", fixture.request.toString(QUuid::WithoutBraces),
                            "--after", "0"});
        QVERIFY(invalid.waitForFinished(30000));
        QCOMPARE(invalid.exitCode(), 2);
        QVERIFY(QFileInfo::exists(fixture.state + "/" + fixture.stem() + ".sqlite"));
        for (const auto &action : {"preview", "run"}) {
            QProcess process;
            process.start(cli,
                          {"--json", "--state-directory", fixture.parent, "client", "scan-cleanup",
                           action, "--request-id", fixture.request.toString(QUuid::WithoutBraces)});
            QVERIFY(process.waitForFinished(30000));
            QCOMPARE(process.exitCode(), 0);
            const auto value = QJsonDocument::fromJson(process.readAllStandardOutput()).object();
            QCOMPARE(value["event"].toString(), QString("upload-scan-cleanup"));
            QCOMPARE(value["action"].toString(), action == QString("preview")
                                                     ? QString("pending-cleanup")
                                                     : QString("cleaned"));
        }
    }
};

// 日期：2026-11-07；真实进程退出留原件，其余调用交给QtTest，测试生产代码无需专用环境开关。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto args = application.arguments();
    if (args.size() == 7 && args[1] == "--abandon-scan") {
        dukto::PrivateStore store(args[2] + "/client/transfers", true);
        dukto::ClientProfile profile;
        profile.server = QUuid(args[4]);
        profile.client = QUuid(args[5]);
        const auto stem = "upload-source-" + args[3];
        dukto::UploadManifest upload(
            store, QUuid(args[3]), profile, "data", "", dukto::ConflictPolicy::Rename,
            {args[2] + "/source.bin"}, nullptr, [&]() {
                // 日期：2026-11-07；必须真实观察到生产持久身份记录，才制造析构无法处理的进程中断。
                if (store.exists(stem + ".scan.json")) {
                    if (args[6] == "hot")
                        leaveHotJournal(store.directory() + "/" + stem + ".sqlite");
                    std::_Exit(47);
                }
            });
        return 95;
    }
    if (args.size() == 5 && args[1] == "--cleanup-crash") {
        dukto::PrivateStore store(args[2], false, dukto::PrivateStore::Use::Maintenance);
        dukto::cleanupUploadScan(
            store, QUuid(args[3]), QDateTime::currentDateTimeUtc(), true, [&]() {
                // 日期：2026-11-07；根据实际删除意图或文件消失退出，不将回调计数当成崩溃证明。
                const auto stem = "upload-source-" + args[3];
                const auto proof = dukto::next::parseControl(store.read(stem + ".scan.json"));
                if ((args[4] == "before-delete" && proof["phase"] == "cleaning") ||
                    (args[4] == "after-delete" && !store.exists(stem + ".sqlite")))
                    std::_Exit(48);
            });
        return 96;
    }
    UploadScanCleanupTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "upload_scan_cleanup_tests.moc"

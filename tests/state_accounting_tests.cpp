#include "core/error.h"
#include "core/statedomain.h"
#include "core/statesession.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QProcess>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdlib>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
using Store = dukto::PrivateStore;
using Domain = dukto::StateDomain;
using Budget = dukto::StateBudget;
constexpr auto Maintenance = Store::Use::Maintenance;

// 日期：2026-11-08；真实文件测试有独立额度，超额反例可单独缩小未知类别。
Budget::Limits limits(qint64 unknown = 16 * 1024 * 1024) {
    return {Budget::FileBytes + 32 * 1024 * 1024,
            {{1024 * 1024, Budget::FileBytes + 1024 * 1024, 1024 * 1024, unknown}}};
}

// 日期：2026-11-08；只读取测试自有小文件核对原件，产品观察从不读取正文。
QByteArray bytes(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture read", "test");
    return file.readAll();
}

// 日期：2026-11-08；通过公开原生观察核对同名对象确实换代，测试不复用计量键生成器。
QByteArray identity(const Store &store, const QString &name) {
    QByteArray result;
    store.visitStorageEntries([&](const dukto::NativeDirectoryEntry &entry) {
        // 日期：2026-11-08；只保留一个目标身份，不按文件数量积累内存。
        if (entry.name == name)
            result = QByteArray(reinterpret_cast<const char *>(entry.identity.data()),
                                int(entry.identity.size()));
    });
    return result;
}

class Process final : public QProcess {
  public:
    // 日期：2026-11-08；断言失败也回收本测试启动的进程，不遗留维护锁。
    ~Process() override {
        if (state() != NotRunning) {
            kill();
            waitForFinished(10000);
        }
    }
};

// 日期：2026-11-08；运行同目录真实CLI，核对退出码、错误流和JSON，不吞掉权限/完整性失败。
QJsonObject cli(QStringList arguments, int expected = 0) {
    auto executable = QCoreApplication::applicationDirPath() + "/dukto-cli";
#ifdef Q_OS_WIN
    executable += ".exe";
#endif
    Process process;
    process.start(executable, arguments);
    if (!process.waitForStarted(10000) || !process.waitForFinished(30000))
        throw dukto::Error(dukto::ExitCode::Runtime, "CLI timeout", "test");
    const auto output = process.readAllStandardOutput();
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != expected ||
        !process.readAllStandardError().isEmpty())
        throw dukto::Error(dukto::ExitCode::Runtime,
                           QString("CLI expected %1 got %2: %3")
                               .arg(expected)
                               .arg(process.exitCode())
                               .arg(QString::fromUtf8(output)),
                           "test");
    if (!arguments.contains("--json"))
        return {{"text", QString::fromUtf8(output)}};
    QJsonParseError error;
    const auto value = QJsonDocument::fromJson(output, &error);
    if (error.error != QJsonParseError::NoError || !value.isObject())
        throw dukto::Error(dukto::ExitCode::Runtime, "CLI JSON", "test");
    return value.object();
}

// 日期：2026-11-08；子进程确认首次真实未知占用落盘后立即退出，不执行析构或修改业务文件。
int child(const QStringList &arguments) {
    try {
        Store coordinator(arguments[2] + "/budget", false, Maintenance);
        Store member(arguments[2] + "/clients", false, Maintenance);
        Domain observed(coordinator);
        Budget probe(coordinator, observed.root(coordinator).domain);
        const auto before = probe.usage().totalCommitted;
        bool armed = false;
        Domain domain(coordinator, [&] {
            // 日期：2026-11-08；回调在预算锁外观察，只有持久增加后才触发直接退出。
            if (armed && probe.usage().totalCommitted > before)
                std::_Exit(72);
        });
        armed = true;
        domain.accountUnknown(member);
        return 90;
    } catch (const dukto::Error &) {
        return 91;
    }
}
} // namespace

class StateAccountingTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；真实文件、控制标记增量和重复观察持久化，重开不能重复扣款。
    void persistentObservationAndRepeat() {
        QTemporaryDir directory;
        qint64 committed = 0;
        {
            Store central(directory.filePath("budget"), true, Maintenance);
            Store member(directory.filePath("clients"), true, Maintenance);
            Domain::initialize(central, limits());
            Domain domain(central);
            domain.bind(member);
            member.write("alpha.json", QByteArray(65537, 'a'));
            const auto before = domain.usage();
            const auto report = domain.accountUnknown(member);
            const auto after = domain.usage();
            QVERIFY(after.committed[3] >= 65537);
            QCOMPARE(report["newlyChargedBytes"].toString().toLongLong(),
                     after.totalCommitted - before.totalCommitted);
            QCOMPARE(report["alreadyChargedControlBytes"].toString(),
                     QString::number(Domain::MarkerBytes));
            QVERIFY(report["allDirectEntriesRegular"].toBool());
            QVERIFY(!report["automaticDeletionAllowed"].toBool());
            QVERIFY(!report["wholeDomainAccounted"].toBool());
            const auto revision = after.revision;
            QCOMPARE(domain.accountUnknown(member)["newlyChargedBytes"].toString(), QString("0"));
            QCOMPARE(domain.usage().revision, revision);
            committed = after.totalCommitted;
        }
        Store central(directory.filePath("budget"), false, Maintenance);
        Store member(directory.filePath("clients"), false, Maintenance);
        Domain domain(central);
        QCOMPARE(domain.usage().totalCommitted, committed);
        QCOMPARE(domain.accountUnknown(member)["newlyChargedBytes"].toString(), QString("0"));
        QCOMPARE(bytes(directory.filePath("clients/alpha.json")), QByteArray(65537, 'a'));
    }

    // 日期：2026-11-08；同对象缩小、消失不减少未知记录，原地增长只提高既有高水位。
    void shrinkMissingAndGrowthRetainHighWater() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        domain.bind(member);
        member.write("payload.bin", QByteArray(65537, 'x'));
        domain.accountUnknown(member);
        const auto before = domain.usage().totalCommitted;
        QFile file(directory.filePath("clients/payload.bin"));
        QVERIFY(file.open(QIODevice::ReadWrite));
        QVERIFY(file.resize(1));
        file.close();
        domain.accountUnknown(member);
        QCOMPARE(domain.usage().totalCommitted, before);
        QVERIFY(file.open(QIODevice::ReadWrite));
        QVERIFY(file.resize(131073));
        file.close();
        domain.accountUnknown(member);
        const auto grown = domain.usage().totalCommitted;
        QVERIFY(grown > before);
        QVERIFY(file.remove());
        domain.accountUnknown(member);
        QCOMPARE(domain.usage().totalCommitted, grown);
    }

    // 日期：2026-11-08；同名同长度新原生对象与改名均另计，旧未知占用不因路径推断而退款。
    void replacementAndRenameKeepPreviousCharge() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        domain.bind(member);
        member.write("same.bin", QByteArray(8193, 'a'));
        const auto firstIdentity = identity(member, "same.bin");
        domain.accountUnknown(member);
        const auto first = domain.usage().totalCommitted;
        member.write("same.bin", QByteArray(8193, 'b'));
        QVERIFY(identity(member, "same.bin") != firstIdentity);
        domain.accountUnknown(member);
        const auto second = domain.usage().totalCommitted;
        QVERIFY(second >= first + 8193);
        QVERIFY(QFile::rename(directory.filePath("clients/same.bin"),
                              directory.filePath("clients/renamed.bin")));
        domain.accountUnknown(member);
        QVERIFY(domain.usage().totalCommitted >= second + 8193);
        QCOMPARE(bytes(directory.filePath("clients/renamed.bin")), QByteArray(8193, 'b'));
    }

    // 日期：2026-11-08；真实已存在文件超出未知额仍登记透支，下一份新准入被拒绝，原内容保持。
    void existingOverdrawnDoesNotHideData() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits(1));
        Domain domain(central);
        domain.bind(member);
        member.write("existing.bin", QByteArray(8193, 'x'));
        domain.accountUnknown(member);
        QVERIFY(domain.usage().overdrawn);
        QVERIFY(domain.usage().committed[3] >= 8193);
        Budget budget(central, domain.root(central).domain);
        const auto key = QCryptographicHash::hash("new-admission", QCryptographicHash::Sha256);
        QVERIFY_EXCEPTION_THROWN(budget.enroll(key, Budget::Category::Unknown, 1), dukto::Error);
        QCOMPARE(bytes(directory.filePath("clients/existing.bin")), QByteArray(8193, 'x'));
    }

    // 日期：2026-11-08；未决授信及已知类别不能被未知观察覆盖，重复较小观察不改修订或退款。
    void pendingAndKnownCategoriesProtected() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        Budget budget(central, domain.root(central).domain);
        const auto key = QCryptographicHash::hash("unknown", QCryptographicHash::Sha256);
        const auto known = QCryptographicHash::hash("known", QCryptographicHash::Sha256);
        auto record = budget.accountExisting(key, 64);
        QCOMPARE(budget.accountExisting(key, 1).revision, record.revision);
        const auto pending = budget.reserve(record, 128);
        const auto before = budget.usage();
        QVERIFY_EXCEPTION_THROWN(budget.accountExisting(key, 256), dukto::Error);
        QCOMPARE(budget.usage().totalReserved, before.totalReserved);
        record = budget.settle(pending, 128);
        QCOMPARE(budget.accountExisting(key, 256).committed, qint64(256));
        budget.enroll(known, Budget::Category::Metadata, 2);
        QVERIFY_EXCEPTION_THROWN(budget.accountExisting(known, 9), dukto::Error);
    }

    // 日期：2026-11-08；64位已观察占用只写固定账本，负数拒绝；不分配对应大小内存或伪造真实大文件资格。
    void largeObservedAmountsAndInvalidInput() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        Budget budget(central, domain.root(central).domain);
        const auto key = QCryptographicHash::hash("large-observation", QCryptographicHash::Sha256);
        const qint64 amount = (qint64(1) << 40) + 123;
        QCOMPARE(budget.accountExisting(key, amount).committed, amount);
        QCOMPARE(budget.usage().committed[3], amount);
        QVERIFY(budget.usage().overdrawn);
        QVERIFY_EXCEPTION_THROWN(budget.accountExisting(key, -1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.accountExisting(QByteArray(31, 'x'), 0), dukto::Error);
    }

    // 日期：2026-11-08；目录和POSIX链接/FIFO保持原位并显式列出未覆盖数，不能当作整个域完整计量。
    void nonRegularEntriesRemainUnaccounted() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        domain.bind(member);
        QVERIFY(QDir().mkdir(directory.filePath("clients/nested")));
#ifndef Q_OS_WIN
        const auto link = QFile::encodeName(directory.filePath("clients/link"));
        const auto fifo = QFile::encodeName(directory.filePath("clients/pipe"));
        QCOMPARE(::symlink("missing", link.constData()), 0);
        QCOMPARE(::mkfifo(fifo.constData(), 0600), 0);
#endif
        const auto report = domain.accountUnknown(member);
        QCOMPARE(report["directoriesUnaccounted"].toString(), QString("1"));
        QVERIFY(!report["allDirectEntriesRegular"].toBool());
        QVERIFY(QFileInfo::exists(directory.filePath("clients/nested")));
#ifndef Q_OS_WIN
        QCOMPARE(report["linksUnaccounted"].toString(), QString("1"));
        QCOMPARE(report["otherUnaccounted"].toString(), QString("1"));
        QVERIFY(QFileInfo(directory.filePath("clients/link")).isSymLink());
#endif
    }

    // 日期：2026-11-08；硬链接的两个名称保守计量，未知文件仍保持内容及真实链接关系。
    void hardLinkedNamesConservativelyCounted() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain domain(central);
        domain.bind(member);
        member.write("first.bin", QByteArray(8193, 'h'));
        const auto source = directory.filePath("clients/first.bin");
        const auto destination = directory.filePath("clients/second.bin");
#ifdef Q_OS_WIN
        QVERIFY(CreateHardLinkW(reinterpret_cast<LPCWSTR>(destination.utf16()),
                                reinterpret_cast<LPCWSTR>(source.utf16()), nullptr));
#else
        QCOMPARE(::link(QFile::encodeName(source).constData(),
                        QFile::encodeName(destination).constData()),
                 0);
#endif
        const auto report = domain.accountUnknown(member);
        QCOMPARE(report["hardLinkedNames"].toString(), QString("2"));
        QVERIFY(domain.usage().committed[3] >= 2 * 8193);
        QCOMPARE(identity(member, "first.bin"), identity(member, "second.bin"));
        QCOMPARE(bytes(destination), QByteArray(8193, 'h'));
    }

    // 日期：2026-11-08；取消发生在已有部分记账之后，原记录不退款，下一次独占维护可继续并幂等。
    void cancellationKeepsPartialAccounting() {
        QTemporaryDir directory;
        Store central(directory.filePath("budget"), true, Maintenance);
        Store member(directory.filePath("clients"), true, Maintenance);
        Domain::initialize(central, limits());
        Domain ordinary(central);
        ordinary.bind(member);
        member.write("alpha.bin", QByteArray(8193, 'a'));
        member.write("beta.bin", QByteArray(16385, 'b'));
        Budget probe(central, ordinary.root(central).domain);
        const auto before = probe.usage().totalCommitted;
        bool armed = false;
        Domain cancelled(central, [&] {
            // 日期：2026-11-08；真实持久占用增加后取消，不依赖枚举名称顺序。
            if (armed && probe.usage().totalCommitted > before)
                throw dukto::Error(dukto::ExitCode::Cancelled, "fixture cancellation", "test");
        });
        armed = true;
        QVERIFY_EXCEPTION_THROWN(cancelled.accountUnknown(member), dukto::Error);
        QVERIFY(probe.usage().totalCommitted > before);
        ordinary.accountUnknown(member);
        QVERIFY(probe.usage().committed[3] >= 8193 + 16385);
        QCOMPARE(ordinary.accountUnknown(member)["newlyChargedBytes"].toString(), QString("0"));
    }

    // 日期：2026-11-08；双根维护均须真实取得，普通共享调用和协调区自计量拒绝且不变账本。
    void maintenanceAndCoordinatorBoundaries() {
        QTemporaryDir directory;
        {
            Store central(directory.filePath("budget"), true, Maintenance);
            Store member(directory.filePath("clients"), true, Maintenance);
            Domain::initialize(central, limits());
            Domain domain(central);
            domain.bind(member);
            QVERIFY_EXCEPTION_THROWN(domain.accountUnknown(central), dukto::Error);
        }
        {
            Store central(directory.filePath("budget"));
            Store member(directory.filePath("clients"), false, Maintenance);
            Domain domain(central);
            const auto before = domain.usage().revision;
            QVERIFY_EXCEPTION_THROWN(domain.accountUnknown(member), dukto::Error);
            QCOMPARE(domain.usage().revision, before);
        }
        Store central(directory.filePath("budget"), false, Maintenance);
        Store member(directory.filePath("clients"));
        Domain domain(central);
        QVERIFY_EXCEPTION_THROWN(domain.accountUnknown(member), dukto::Error);
    }

    // 日期：2026-11-08；真实三平台CLI计量须让出活动共享根，重复/错误参数拒绝，JSON及人类报告不暴露名称或身份。
    void realCliMaintenanceAndReports() {
        QTemporaryDir directory(QStringLiteral("dukto-account 中文 空格-XXXXXX"));
        auto member = dukto::StateSession::root(directory.path(), "clients", true);
        member->write("private-name.json", QByteArray(8193, 'x'));
        const QStringList arguments{
            "state",          "root",         "account", "--state-directory",
            directory.path(), "--state-root", "clients", "--json"};
        QCOMPARE(cli(arguments, 4)["event"].toString(), QString("error"));
        member.reset();
        const auto result = cli(arguments);
        QCOMPARE(result["event"].toString(), QString("state-root"));
        QCOMPARE(result["operation"].toString(), QString("account"));
        QVERIFY(result["inventory"].toObject()["newlyChargedBytes"].toString().toLongLong() >=
                8193);
        QVERIFY(!QJsonDocument(result).toJson().contains("private-name"));
        QCOMPARE(cli(arguments)["inventory"].toObject()["newlyChargedBytes"].toString(),
                 QString("0"));
        auto human = arguments;
        human.removeLast();
        QVERIFY(cli(human)["text"].toString().contains("allocatedBytes="));
        auto duplicate = arguments;
        duplicate << "--state-root" << "clients";
        cli(duplicate, 2);
        auto missing = arguments;
        missing[missing.indexOf("clients")] = "service";
        cli(missing, 5);
        QVERIFY(!QFileInfo::exists(directory.filePath("service")));
    }

    // 日期：2026-11-08；真实子进程记账后直接退出，内核锁释放，重开保留占用且可继续，不删除原数据。
    void directExitPreservesChargesAndCanContinue() {
        QTemporaryDir directory;
        {
            auto member = dukto::StateSession::root(directory.path(), "clients", true);
            member->write("persist.bin", QByteArray(8193, 'x'));
        }
        Process process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--account-exit", directory.path()});
        QVERIFY(process.waitForStarted(10000));
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 72);
        Store central(directory.filePath("budget"), false, Maintenance);
        Store member(directory.filePath("clients"), false, Maintenance);
        Domain domain(central);
        QVERIFY(domain.usage().committed[3] > 0);
        domain.accountUnknown(member);
        QVERIFY(domain.usage().committed[3] >= 8193);
        QCOMPARE(domain.accountUnknown(member)["newlyChargedBytes"].toString(), QString("0"));
        QCOMPARE(bytes(directory.filePath("clients/persist.bin")), QByteArray(8193, 'x'));
    }
};

// 日期：2026-11-08；直接退出子进程模式与常规QtTest分开，只有普通执行才运行完整测试集。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto arguments = application.arguments();
    if (arguments.size() == 3 && arguments[1] == "--account-exit")
        return child(arguments);
    StateAccountingTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "state_accounting_tests.moc"

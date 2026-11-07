#include "core/buffercredit.h"
#include "core/error.h"
#include "core/privatestore.h"
#include "core/statedomain.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QProcess>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtEndian>
#include <QtTest>
#include <cstdlib>
#include <limits>

namespace {
using Store = dukto::PrivateStore;
using Budget = dukto::StateBudget;
using Domain = dukto::StateDomain;
constexpr auto Maintenance = Store::Use::Maintenance;

// 日期：2026-11-08；测试只给控制区之外8192字节，便于真实触达配置与预留边界。
Budget::Limits limits(qint64 extra = 8192) {
    return {Budget::FileBytes + extra, {{extra, Budget::FileBytes + extra, extra, extra}}};
}

// 日期：2026-11-08；仅夹具读取固定1MiB账本原件，产品仍按固定槽访问。
QByteArray bytes(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture read", "test");
    return file.readAll();
}

// 日期：2026-11-08；原地注入测试自有文件，不替换权限或原生身份。
void replace(const QString &path, const QByteArray &value) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate) ||
        file.write(value) != value.size() || !file.flush())
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture write", "test");
}

// 日期：2026-11-08；独立编码恢复夹具，整数固定小端，不复用产品日志序列化器。
void number(QByteArray &value, int offset, quint64 integer) {
    qToLittleEndian(integer, reinterpret_cast<uchar *>(value.data() + offset));
}

// 日期：2026-11-08；故障布局的SHA仅封装公开固定格式，实际结果另用公开接口验证。
QByteArray sealed(QByteArray value) {
    value.replace(
        value.size() - 32, 32,
        QCryptographicHash::hash(value.left(value.size() - 32), QCryptographicHash::Sha256));
    return value;
}

// 日期：2026-11-08；从两份真实提交原件构造头配置意图，全部对象槽区保持零保留，不借槽记录配置。
QByteArray intent(const QByteArray &before, const QByteArray &after) {
    QByteArray value(4096, '\0');
    value.replace(0, 8, QByteArray("DKBUDCF1", 8));
    number(value, 8, 1);
    number(value, 16,
           qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(before.constData() + 72)));
    number(value, 24,
           qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(after.constData() + 72)));
    value.replace(40, 512, before.left(512));
    value.replace(552, 512, after.left(512));
    return sealed(value);
}

class Process final : public QProcess {
  public:
    // 日期：2026-11-08；夹具断言失败也结束并收取本测试的子进程，不遗留根锁。
    ~Process() override {
        if (state() != NotRunning) {
            kill();
            waitForFinished(10000);
        }
    }
};

// 日期：2026-11-08；真实三平台CLI使用同目录构建程序，显式保存退出码与UTF-8输出，超时不当作通过。
QJsonObject cli(const QStringList &arguments, int expected = 0) {
    auto executable = QCoreApplication::applicationDirPath() + "/dukto-cli";
#ifdef Q_OS_WIN
    executable += ".exe";
#endif
    Process process;
    process.start(executable, arguments);
    if (!process.waitForStarted(10000) || !process.waitForFinished(30000))
        throw dukto::Error(dukto::ExitCode::Runtime, "CLI did not finish", "test");
    const auto output = process.readAllStandardOutput();
    const auto error = process.readAllStandardError();
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != expected ||
        !error.isEmpty())
        throw dukto::Error(dukto::ExitCode::Runtime,
                           QString("CLI expected %1 got %2: %3 %4")
                               .arg(expected)
                               .arg(process.exitCode())
                               .arg(QString::fromUtf8(output), QString::fromUtf8(error)),
                           "test");
    if (!arguments.contains("--json"))
        return {{"text", QString::fromUtf8(output)}};
    QJsonParseError parse;
    const auto document = QJsonDocument::fromJson(output.trimmed(), &parse);
    if (parse.error != QJsonParseError::NoError || !document.isObject())
        throw dukto::Error(dukto::ExitCode::Runtime, "CLI did not return one JSON object", "test");
    return document.object();
}

// 日期：2026-11-08；CLI额度全部显式给定，不让默认值掩盖配置未生效。
QStringList options(qint64 extra = 8192) {
    const auto value = limits(extra);
    return {"--budget-total",    QString::number(value.total),
            "--budget-history",  QString::number(value.categories[0]),
            "--budget-metadata", QString::number(value.categories[1]),
            "--budget-body",     QString::number(value.categories[2]),
            "--budget-unknown",  QString::number(value.categories[3])};
}

// 日期：2026-11-08；真实独立进程持有共享根或配置后直接退出，用于验证原生资格及无析构持久性。
int child(const QStringList &arguments) {
    try {
        if (arguments[1] == "--hold-root") {
            Store store(arguments[2]);
            QTextStream(stdout) << "ready" << Qt::endl;
            std::getchar();
            return 0;
        }
        Store store(arguments[2], false, Maintenance);
        Domain domain(store);
        const auto before = domain.usage();
        auto changed = before.limits;
        changed.total += 4096;
        changed.categories[2] += 4096;
        domain.configure(before.revision, changed);
        std::_Exit(71);
    } catch (const dukto::Error &error) {
        QTextStream(stderr) << error.stage << ':' << error.message << Qt::endl;
        return 90;
    }
}
} // namespace

class BudgetConfigurationTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；修改后真实重开，全部占用、预留、登记与原生根代数保持，固定长度不增加。
    void persistentLimitsAndUnchangedRecords() {
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        Domain domain(store);
        const auto binding = domain.root(store);
        Budget budget(store, binding.domain);
        const auto key = QCryptographicHash::hash("actual-object", QCryptographicHash::Sha256);
        const auto pending = budget.reserve(budget.enroll(key, Budget::Category::Body, 100), 2048);
        const auto path = store.directory() + "/state-budget.bin";
        const auto original = bytes(path);
        const auto before = domain.usage();
        const auto changed = domain.configure(before.revision, limits(16384));
        QCOMPARE(changed.revision, before.revision + 1);
        QCOMPARE(changed.totalCommitted, before.totalCommitted);
        QCOMPARE(changed.totalReserved, before.totalReserved);
        QCOMPARE(bytes(path).mid(8192), original.mid(8192));
        QCOMPARE(domain.root(store).generation, binding.generation);
        QCOMPARE(Budget(store, binding.domain).usage().limits.total, limits(16384).total);
        QCOMPARE(budget.lookup(key).operation, pending.operation);
        QCOMPARE(budget.settle(pending, 1500).committed, qint64(1500));
        QCOMPARE(QFileInfo(path).size(), Budget::FileBytes);
    }

    // 日期：2026-11-08；相同配置不写盘，旧修订不能覆盖较新修改或新增对象带来的修订。
    void noOpAndStaleRevision() {
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        Domain domain(store);
        const auto path = store.directory() + "/state-budget.bin";
        const auto before = domain.usage();
        const auto original = bytes(path);
        QCOMPARE(domain.configure(before.revision, before.limits).revision, before.revision);
        QCOMPARE(bytes(path), original);
        const auto changed = domain.configure(before.revision, limits(16384));
        const auto latest = bytes(path);
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, before.limits), dukto::Error);
        QCOMPARE(bytes(path), latest);
        QCOMPARE(domain.usage().revision, changed.revision);
    }

    // 日期：2026-11-08；不能降低到实际合计或未决保留以下；任何非法输入均不改原账本。
    void refusalPreservesReservations() {
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        Domain domain(store);
        Budget budget(store, domain.usage().domain);
        const auto key = QCryptographicHash::hash("pending", QCryptographicHash::Sha256);
        budget.reserve(budget.enroll(key, Budget::Category::Body, 100), 2048);
        const auto before = domain.usage();
        const auto path = store.directory() + "/state-budget.bin";
        const auto original = bytes(path);
        auto changed = before.limits;
        changed.categories[2] = 2047;
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, changed), dukto::Error);
        changed = before.limits;
        changed.total = before.totalCommitted + before.totalReserved - 1;
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, changed), dukto::Error);
        changed = before.limits;
        changed.categories[3] = -1;
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, changed), dukto::Error);
        changed = before.limits;
        changed.categories[1] = Budget::FileBytes - 1;
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, changed), dukto::Error);
        QCOMPARE(bytes(path), original);
        QCOMPARE(domain.usage().totalReserved, qint64(1948));
    }

    // 日期：2026-11-08；实际超预期占用如实保留；提高到足够额度才能解除透支，64位额度不截断。
    void overdrawnCorrectionAnd64BitLimits() {
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        Domain domain(store);
        Budget budget(store, domain.usage().domain);
        const auto key = QCryptographicHash::hash("overdrawn", QCryptographicHash::Sha256);
        const auto reserved = budget.reserve(budget.enroll(key, Budget::Category::Body, 0), 1024);
        budget.settle(reserved, 16384);
        const auto before = domain.usage();
        QVERIFY(before.overdrawn);
        QVERIFY_EXCEPTION_THROWN(domain.configure(before.revision, limits(10000)), dukto::Error);
        auto changed = before.limits;
        changed.total = std::numeric_limits<qint64>::max();
        changed.categories[2] = std::numeric_limits<qint64>::max();
        const auto after = domain.configure(before.revision, changed);
        QVERIFY(!after.overdrawn);
        QCOMPARE(after.totalCommitted, before.totalCommitted);
        QCOMPARE(after.limits.total, std::numeric_limits<qint64>::max());
        QCOMPARE(Domain(store).usage().limits.categories[2], std::numeric_limits<qint64>::max());
        QCOMPARE(budget.lookup(key).committed, qint64(16384));
    }

    // 日期：2026-11-08；独立五种落盘边界向前重放到同一配置，不重写对象槽；每次重开结果幂等。
    void configurationRecovery_data() {
        QTest::addColumn<int>("layout");
        for (int value = 0; value < 5; ++value)
            QTest::newRow(QByteArray::number(value)) << value;
    }

    // 日期：2026-11-08；布局涵盖仅意图、已写新头、头撕裂、清零前及旧头半写，原生文件实际重开。
    void configurationRecovery() {
        QFETCH(int, layout);
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray before, after;
        QUuid id;
        {
            Domain domain(store);
            id = domain.usage().domain;
            before = bytes(path);
            domain.configure(domain.usage().revision, limits(16384));
            after = bytes(path);
        }
        auto interrupted = layout == 1 || layout == 3 ? after : before;
        interrupted.replace(4096, 4096, intent(before, after));
        if (layout == 2)
            interrupted.replace(0, 137, after.left(137));
        if (layout == 4)
            interrupted.replace(0, 137, QByteArray(137, '\x7f'));
        replace(path, interrupted);
        QCOMPARE(Budget(store, id).usage().limits.total, limits(16384).total);
        QCOMPARE(bytes(path), after);
        QCOMPARE(Budget(store, id).usage().limits.total, limits(16384).total);
        QCOMPARE(bytes(path), after);
    }

    // 日期：2026-11-08；配置日志撕裂、未知版本、隐藏改槽和旧意图重放均拒绝，原字节保持。
    void corruptAndStaleConfigurationIntent() {
        QTemporaryDir root;
        Store store(root.filePath("state"), true, Maintenance);
        Domain::initialize(store, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray before, after, latest;
        QUuid id;
        {
            Domain domain(store);
            id = domain.usage().domain;
            before = bytes(path);
            const auto changed = domain.configure(domain.usage().revision, limits(16384));
            after = bytes(path);
            domain.configure(changed.revision, limits(32768));
            latest = bytes(path);
        }
        for (int kind = 0; kind < 6; ++kind) {
            auto journal = intent(before, after);
            auto corrupted = kind == 4 ? latest : before;
            if (kind == 0)
                journal[100] = char(journal[100] ^ 1);
            if (kind == 1) {
                number(journal, 8, 2);
                journal = sealed(journal);
            }
            if (kind == 2) {
                journal[1064] = 1;
                journal = sealed(journal);
            }
            if (kind == 3)
                journal.replace(2000, 2096, QByteArray(2096, '\0'));
            if (kind == 5) {
                auto header = journal.mid(552, 512);
                number(header, 128, 1);
                journal.replace(552, 512, sealed(header));
                journal = sealed(journal);
            }
            corrupted.replace(4096, 4096, journal);
            replace(path, corrupted);
            QVERIFY_EXCEPTION_THROWN((Budget(store, id)), dukto::Error);
            QCOMPARE(bytes(path), corrupted);
        }
    }

    // 日期：2026-11-08；共享使用无权改额度；实际跨进程根占用阻止维护，强退后原生锁释放且数据保留。
    void processMaintenanceBoundary() {
        QTemporaryDir root;
        const auto path = root.filePath("state");
        {
            Store store(path, true, Maintenance);
            Domain::initialize(store, limits());
        }
        {
            Store ordinary(path);
            Domain domain(ordinary);
            QVERIFY_EXCEPTION_THROWN(domain.configure(domain.usage().revision, limits(16384)),
                                     dukto::Error);
        }
        Process process;
        process.start(QCoreApplication::applicationFilePath(), {"--hold-root", path});
        QVERIFY(process.waitForStarted(10000));
        QVERIFY(process.waitForReadyRead(30000));
        QCOMPARE(process.readLine().trimmed(), QByteArray("ready"));
        QVERIFY_EXCEPTION_THROWN((Store(path, false, Maintenance)), dukto::Error);
        process.kill();
        QVERIFY(process.waitForFinished(10000));
        Store maintenance(path, false, Maintenance);
        Domain domain(maintenance);
        QCOMPARE(domain.configure(domain.usage().revision, limits(16384)).limits.total,
                 limits(16384).total);
    }

    // 日期：2026-11-08；配置成功后真实直接退出绕过析构，父进程重开仍看到新额度和原标记。
    void directExitKeepsConfiguration() {
        QTemporaryDir root;
        const auto path = root.filePath("state");
        {
            Store store(path, true, Maintenance);
            Domain::initialize(store, limits());
        }
        Process process;
        process.start(QCoreApplication::applicationFilePath(), {"--configure-and-exit", path});
        QVERIFY(process.waitForStarted(10000));
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitStatus(), QProcess::NormalExit);
        QCOMPARE(process.exitCode(), 71);
        QCOMPARE(process.readAllStandardError(), QByteArray());
        Store store(path);
        Domain domain(store);
        QCOMPARE(domain.usage().limits.total, limits().total + 4096);
        QCOMPARE(domain.usage().limits.categories[2], limits().categories[2] + 4096);
    }

    // 日期：2026-11-08；真实CLI初始化/查询/按修订修改/成员登记均互读；原普通父目录中的旧历史完整保留。
    void realCliLifecycleAndRootBinding() {
        QTemporaryDir root;
        const auto parent = root.filePath(QStringLiteral("中文 状态"));
        QVERIFY(QDir().mkpath(parent));
        const auto oldHistory = parent + "/history.sqlite";
        replace(oldHistory, "existing history must stay");
        const QStringList common{"--state-directory", parent, "--json", "--non-interactive"};
        const auto initialized = cli(QStringList{"state", "budget", "init"} + options() + common);
        QCOMPARE(initialized["event"].toString(), QString("state-budget"));
        QCOMPARE(initialized["productionQuotaEnforced"].toBool(true), false);
        const auto before = cli(QStringList{"state", "budget", "show"} + common);
        QCOMPARE(before["revision"], initialized["revision"]);
        const auto changed = cli(QStringList{"state", "budget", "set", "--budget-revision",
                                             before["revision"].toString()} +
                                 options(16384) + common);
        QCOMPARE(changed["limit"].toString(), QString::number(limits(16384).total));
        for (const auto &name : {"service", "clients", "transfers", "history"}) {
            const auto bound =
                cli(QStringList{"state", "root", "bind", "--state-root", name} + common);
            const auto observed =
                cli(QStringList{"state", "root", "show", "--state-root", name} + common);
            QCOMPARE(observed["rootGeneration"], bound["rootGeneration"]);
            QCOMPARE(observed["domain"], initialized["domain"]);
            QCOMPARE(observed["bound"].toBool(), true);
            const auto repeated =
                cli(QStringList{"state", "root", "bind", "--state-root", name} + common);
            QCOMPARE(repeated["revision"], observed["revision"]);
        }
        QCOMPARE(bytes(oldHistory), QByteArray("existing history must stay"));
        const auto human =
            cli({"state", "budget", "show", "--state-directory", parent})["text"].toString();
        QVERIFY(human.contains("productionQuotaEnforced=false"));
        QVERIFY(human.contains("revision="));
        QVERIFY(human.contains(QString::number(limits(16384).total)));
        QCOMPARE(cli(QStringList{"state", "budget", "init"} + options() + common,
                     int(dukto::ExitCode::Integrity))["stage"]
                     .toString(),
                 QString("state-domain"));
    }

    // 日期：2026-11-08；无效/重复/溢出参数在创建路径前拒绝，缺失查询不建库；旧修订不覆盖新配置。
    void realCliRefusalsHaveNoSideEffects() {
        QTemporaryDir root;
        const auto absent = root.filePath("absent");
        const QStringList common{"--state-directory", absent, "--json"};
        for (const auto &wrong : {"-1", "01", "+1", "1e9", "9223372036854775808"}) {
            auto invalid = options();
            invalid[1] = wrong;
            cli(QStringList{"state", "budget", "init"} + invalid + common,
                int(dukto::ExitCode::Config));
            QVERIFY(!QFileInfo::exists(absent));
        }
        cli(QStringList{"state", "budget", "init"} + options() + common +
                QStringList{"--budget-total", "9"},
            int(dukto::ExitCode::Config));
        QVERIFY(!QFileInfo::exists(absent));
        cli(QStringList{"state", "budget", "show"} + common, int(dukto::ExitCode::Disk));
        QVERIFY(!QFileInfo::exists(absent));
        auto tooMuchHistory = options();
        tooMuchHistory[3] = "268435457";
        cli(QStringList{"state", "budget", "init"} + tooMuchHistory + common,
            int(dukto::ExitCode::Config));
        QVERIFY(!QFileInfo::exists(absent));
        const auto initialized = cli(QStringList{"state", "budget", "init"} + options() + common);
        const auto ledger = absent + "/budget/state-budget.bin";
        const auto before = bytes(ledger);
        cli(QStringList{"state", "budget", "set", "--budget-revision", "1"} + options(16384) +
                common,
            int(dukto::ExitCode::Integrity));
        QCOMPARE(bytes(ledger), before);
        cli(QStringList{"state", "root", "bind", "--state-root", "../outside"} + common,
            int(dukto::ExitCode::Config));
        QCOMPARE(bytes(ledger), before);
        cli(QStringList{"state", "budget", "show", "--budget-body", "1"} + common,
            int(dukto::ExitCode::Config));
        QCOMPARE(bytes(ledger), before);
        QCOMPARE(cli(QStringList{"state", "budget", "show"} + common)["domain"],
                 initialized["domain"]);
    }
};

// 日期：2026-11-08；仅显式夹具参数启动子进程模式，其余均进入标准QtTest并保留原生诊断。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto arguments = app.arguments();
    if (arguments.size() == 3 &&
        (arguments[1] == "--hold-root" || arguments[1] == "--configure-and-exit"))
        return child(arguments);
    BudgetConfigurationTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "budget_configuration_tests.moc"

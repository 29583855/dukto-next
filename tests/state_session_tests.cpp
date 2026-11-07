#include "core/error.h"
#include "core/service.h"
#include "core/statesession.h"
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QProcess>
#include <QTcpServer>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtTest>
#include <cstdlib>

namespace {
using Store = dukto::PrivateStore;
using Session = dukto::StateSession;
using Domain = dukto::StateDomain;
using Budget = dukto::StateBudget;
constexpr auto Maintenance = Store::Use::Maintenance;

class Process final : public QProcess {
  public:
    // 日期：2026-11-08；断言失败也回收夹具自身启动的进程，不遗留业务根或端口占用。
    ~Process() override {
        if (state() != NotRunning) {
            kill();
            waitForFinished(10000);
        }
    }
};

// 日期：2026-11-08；原件比较只读测试自有的小文件，不将用户正文或凭据输出到报告。
QByteArray bytes(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture read failed", "test");
    return file.readAll();
}

// 日期：2026-11-08；只构造本测试的普通父目录文件或损坏残片，产品不使用该写入器。
void write(const QString &path, const QByteArray &value) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write(value) != value.size() || !file.flush())
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture write failed", "test");
}

// 日期：2026-11-08；分段收取真实进程一行握手，三平台CRLF/LF均接受，超时和提前退出不算通过。
QByteArray line(Process &process) {
    QElapsedTimer timer;
    timer.start();
    while (!process.canReadLine() && timer.elapsed() < 15000) {
        process.waitForReadyRead(50);
        if (process.state() == QProcess::NotRunning && !process.canReadLine())
            break;
    }
    if (!process.canReadLine())
        throw dukto::Error(dukto::ExitCode::Runtime,
                           "process handshake failed: " + QString::fromUtf8(process.readAll()),
                           "test");
    return process.readLine().trimmed();
}

// 日期：2026-11-08；新状态管理CLI五额度完整提供，不通过缺省参数掩盖配置维护未被正确阻止。
QStringList limits(const Budget::Limits &value) {
    return {"--budget-total",    QString::number(value.total),
            "--budget-history",  QString::number(value.categories[0]),
            "--budget-metadata", QString::number(value.categories[1]),
            "--budget-body",     QString::number(value.categories[2]),
            "--budget-unknown",  QString::number(value.categories[3])};
}

// 日期：2026-11-08；同一构建目录的真实CLI必须正常退出并输出单个JSON对象，stderr保留失败信息。
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
    QJsonParseError parse;
    const auto document = QJsonDocument::fromJson(output.trimmed(), &parse);
    if (parse.error != QJsonParseError::NoError || !document.isObject())
        throw dukto::Error(dukto::ExitCode::Runtime, "CLI JSON object missing", "test");
    return document.object();
}

// 日期：2026-11-08；持有真实共享协调/成员锁或不运行析构直接退出，禁止以模拟PID代替原生资格。
int child(const QStringList &arguments) {
    try {
        if (arguments[1] == "--bootstrap") {
            QTextStream(stdout) << "waiting" << Qt::endl;
            std::getchar();
        }
        auto root = Session::root(arguments[2], "clients", true);
        if (arguments[1] == "--exit-session") {
            root->write("session-test.json", "persistent business data");
            std::_Exit(71);
        }
        QTextStream(stdout) << "ready" << Qt::endl;
        std::getchar();
        return 0;
    } catch (const dukto::Error &error) {
        QTextStream(stderr) << error.stage << ':' << error.message << Qt::endl;
        return 90;
    }
}
} // namespace

class StateSessionTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；临时会话工厂退出后，返回根及其副本持续阻止中央配置，最后关闭才归还。
    void retainedLifetimeAndStableBinding() {
        QTemporaryDir temporary;
        auto root = Session::root(temporary.path(), "clients", true);
        root->write("profile.json", "original");
        const auto directory = root->directory();
        const auto originalMarker = bytes(directory + "/state-domain.bin");
        auto copy = root;
        root.reset();
        QVERIFY_EXCEPTION_THROWN(Store(temporary.filePath("budget"), false, Maintenance),
                                 dukto::Error);
        QCOMPARE(copy->read("profile.json"), QByteArray("original"));
        {
            auto session = Session::open(temporary.path());
            const auto usage = session->usage();
            QCOMPARE(usage.totalCommitted, qint64(Budget::FileBytes + 2 * Domain::MarkerBytes));
            QCOMPARE(usage.limits.total, Session::defaults().total);
            QCOMPARE(usage.limits.categories[0], qint64(256 * 1024 * 1024));
        }
        copy.reset();
        {
            Store coordinator(temporary.filePath("budget"), false, Maintenance);
            Domain domain(coordinator);
            auto changed = domain.usage().limits;
            changed.total += 4096;
            domain.configure(domain.usage().revision, changed);
        }
        root = Session::root(temporary.path(), "clients");
        QCOMPARE(bytes(directory + "/state-domain.bin"), originalMarker);
        QCOMPARE(root->read("profile.json"), QByteArray("original"));
        QCOMPARE(Session::open(temporary.path())->usage().limits.total,
                 Session::defaults().total + 4096);
    }

    // 日期：2026-11-08；旧私有根的只读统计不新建域/成员标记，加入已有域后的观察也不改变控制原件。
    void observationPreservesLegacyAndControls() {
        QTemporaryDir temporary;
        {
            Store legacy(temporary.filePath("transfers"), true);
            legacy.write("legacy.json", "unchanged");
        }
        {
            auto observed = Session::observe(temporary.path(), "transfers", Maintenance);
            QCOMPARE(observed->read("legacy.json"), QByteArray("unchanged"));
            QVERIFY(!QFileInfo::exists(temporary.filePath("budget")));
            QVERIFY(!QFileInfo::exists(temporary.filePath("transfers/state-domain.bin")));
        }
        {
            auto enrolled = Session::root(temporary.path(), "transfers");
        }
        const auto before = bytes(temporary.filePath("budget/state-budget.bin"));
        const auto marker = bytes(temporary.filePath("transfers/state-domain.bin"));
        {
            auto observed = Session::observe(temporary.path(), "transfers", Maintenance);
            QVERIFY_EXCEPTION_THROWN(Store(temporary.filePath("budget"), false, Maintenance),
                                     dukto::Error);
            QCOMPARE(observed->read("legacy.json"), QByteArray("unchanged"));
        }
        QCOMPARE(bytes(temporary.filePath("budget/state-budget.bin")), before);
        QCOMPARE(bytes(temporary.filePath("transfers/state-domain.bin")), marker);
    }

    // 日期：2026-11-08；维护遇到活动成员立即让出，不能借初始化重试把维护改成等待或升级共享锁。
    void maintenanceDoesNotWaitForBusiness() {
        QTemporaryDir temporary;
        auto root = Session::root(temporary.path(), "service", true);
        QElapsedTimer timer;
        timer.start();
        QVERIFY_EXCEPTION_THROWN(Session::root(temporary.path(), "service", false, Maintenance),
                                 dukto::Error);
        QVERIFY(timer.elapsed() < 1000);
        QCOMPARE(root->directory(), temporary.filePath("service"));
    }

    // 日期：2026-11-08；既有额度沿用不重置，新成员标记申请不足时保留旧域和已绑定业务文件。
    void configuredAdmissionAndNoDefaultReset() {
        QTemporaryDir temporary;
        const qint64 maximum = Budget::FileBytes + 2 * Domain::MarkerBytes;
        {
            Store coordinator(temporary.filePath("budget"), true, Maintenance);
            Domain::initialize(coordinator, {maximum, {{256, maximum, 256, 256}}});
        }
        auto clients = Session::root(temporary.path(), "clients", true);
        clients->write("profile.json", "business bytes are not yet quota enforced");
        const auto before = bytes(temporary.filePath("budget/state-budget.bin"));
        QVERIFY_EXCEPTION_THROWN(Session::root(temporary.path(), "transfers", true), dukto::Error);
        QVERIFY(!QFileInfo::exists(temporary.filePath("transfers/state-domain.bin")));
        QCOMPARE(bytes(temporary.filePath("budget/state-budget.bin")), before);
        QCOMPARE(Session::open(temporary.path())->usage().limits.total, maximum);
        QCOMPARE(clients->read("profile.json"),
                 QByteArray("business bytes are not yet quota enforced"));
    }

    // 日期：2026-11-08；未知/不完整中央现场不重建、不覆盖；复制到另一原生根的标记亦不能被认领。
    void damagedAndCopiedBindingsRetained() {
        QTemporaryDir temporary;
        {
            Store coordinator(temporary.filePath("budget"), true, Maintenance);
        }
        write(temporary.filePath("budget/state-domain.bin"), "partial-unknown");
        QVERIFY_EXCEPTION_THROWN(Session::root(temporary.path(), "clients", true), dukto::Error);
        QCOMPARE(bytes(temporary.filePath("budget/state-domain.bin")),
                 QByteArray("partial-unknown"));
        QVERIFY(!QFileInfo::exists(temporary.filePath("budget/state-budget.bin")));
        QTemporaryDir first;
        QTemporaryDir second;
        auto original = Session::root(first.path(), "clients", true);
        {
            Store target(second.filePath("clients"), true);
        }
        const auto marker = bytes(first.filePath("clients/state-domain.bin"));
        write(second.filePath("clients/state-domain.bin"), marker);
        QVERIFY_EXCEPTION_THROWN(Session::root(second.path(), "clients"), dukto::Error);
        QCOMPARE(bytes(second.filePath("clients/state-domain.bin")), marker);
        QCOMPARE(bytes(first.filePath("clients/state-domain.bin")), marker);
    }

    // 日期：2026-11-08；取消及非法根在建立目录之前拒绝，损坏不进入只读观察的无域兼容分支。
    void cancellationAndInvalidLocations() {
        QTemporaryDir temporary;
        const auto absent = temporary.filePath(QStringLiteral("中文 空格/state"));
        QVERIFY_EXCEPTION_THROWN(Session::root(absent, "clients", true, Store::Use::Shared,
                                               []() {
                                                   // 日期：2026-11-08；模拟真实取消检查点，不注入任何产品I/O结果。
                                                   throw dukto::Error(dukto::ExitCode::Cancelled,
                                                                      "cancelled", "test");
                                               }),
                                 dukto::Error);
        QVERIFY(!QFileInfo::exists(absent));
        for (const auto &name :
             QStringList{"../clients", "/service", "unknown", "remote/../service"})
            QVERIFY_EXCEPTION_THROWN(Session::root(absent, name, true), dukto::Error);
        QVERIFY(!QFileInfo::exists(absent));
    }

    // 日期：2026-11-08；旧共享使用者尚未退场时，首次登记在锁外响应取消，保留旧业务及未绑定状态。
    void cancellationDuringMemberRegistration() {
        QTemporaryDir temporary;
        {
            auto initialized = Session::open(temporary.path());
        }
        auto legacy = std::unique_ptr<Store>(new Store(temporary.filePath("clients"), true));
        legacy->write("old-profile.json", "unchanged");
        QElapsedTimer timer;
        timer.start();
        bool cancelled = false;
        try {
            Session::root(temporary.path(), "clients", false, Store::Use::Shared, [&timer]() {
                // 日期：2026-11-08；真实锁冲突期间发出取消，不通过故障注入改变原生锁结果。
                if (timer.elapsed() >= 80)
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancelled", "test");
            });
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Cancelled);
            cancelled = true;
        }
        QVERIFY(cancelled);
        QVERIFY(timer.elapsed() < 1000);
        QVERIFY(!QFileInfo::exists(temporary.filePath("clients/state-domain.bin")));
        QCOMPARE(legacy->read("old-profile.json"), QByteArray("unchanged"));
        QCOMPARE(Session::open(temporary.path())->usage().totalCommitted,
                 qint64(Budget::FileBytes + Domain::MarkerBytes));
        legacy.reset();
        auto bound = Session::root(temporary.path(), "clients");
        QCOMPARE(bound->read("old-profile.json"), QByteArray("unchanged"));
    }

    // 日期：2026-11-08；两个真实进程同时首次登记同一根，各自持有共享资格且标记只计一次。
    void simultaneousProcessesAndFinalRelease() {
        QTemporaryDir temporary;
        Process first;
        Process second;
        for (auto process : {&first, &second}) {
            process->start(QCoreApplication::applicationFilePath(),
                           {"--bootstrap", temporary.path()});
            QVERIFY(process->waitForStarted(10000));
            QCOMPARE(line(*process), QByteArray("waiting"));
        }
        for (auto process : {&first, &second}) {
            QCOMPARE(process->write("g", 1), qint64(1));
            QVERIFY(process->waitForBytesWritten(10000));
        }
        QCOMPARE(line(first), QByteArray("ready"));
        QCOMPARE(line(second), QByteArray("ready"));
        QCOMPARE(Session::open(temporary.path())->usage().totalCommitted,
                 qint64(Budget::FileBytes + 2 * Domain::MarkerBytes));
        QVERIFY_EXCEPTION_THROWN(Store(temporary.filePath("budget"), false, Maintenance),
                                 dukto::Error);
        QCOMPARE(first.write("x", 1), qint64(1));
        QVERIFY(first.waitForFinished(10000));
        QCOMPARE(first.exitCode(), 0);
        QVERIFY_EXCEPTION_THROWN(Store(temporary.filePath("budget"), false, Maintenance),
                                 dukto::Error);
        QCOMPARE(second.write("x", 1), qint64(1));
        QVERIFY(second.waitForFinished(10000));
        QCOMPARE(second.exitCode(), 0);
        Store coordinator(temporary.filePath("budget"), false, Maintenance);
        QCOMPARE(Domain(coordinator).usage().totalCommitted,
                 qint64(Budget::FileBytes + 2 * Domain::MarkerBytes));
    }

    // 日期：2026-11-08；真实进程直接退出仍保留已登记标记和业务文件；内核归还共享锁，绝不靠PID退款。
    void directExitPreservesBusinessAndRegistration() {
        QTemporaryDir temporary;
        Process process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--exit-session", temporary.path()});
        QVERIFY(process.waitForStarted(10000));
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitStatus(), QProcess::NormalExit);
        QCOMPARE(process.exitCode(), 71);
        Store coordinator(temporary.filePath("budget"), false, Maintenance);
        Domain domain(coordinator);
        QCOMPARE(domain.usage().totalCommitted,
                 qint64(Budget::FileBytes + 2 * Domain::MarkerBytes));
        QCOMPARE(bytes(temporary.filePath("clients/session-test.json")),
                 QByteArray("persistent business data"));
    }

    // 日期：2026-11-08；真实客户端命令使用现有资料时进入同一域，普通父目录历史/明细及资料原件保持。
    void realCliClientUsesExistingState() {
        QTemporaryDir temporary(QDir::tempPath() + QStringLiteral("/dukto-中文 空格-XXXXXX"));
        QVERIFY(temporary.isValid());
        {
            Store clients(temporary.filePath("clients"), true);
            dukto::prepareProfile(clients, "local-profile", "localhost", 4646, "localhost",
                                  QByteArray(32, 'P'));
        }
        const auto profile = bytes(temporary.filePath("clients/profile-local-profile.json"));
        write(temporary.filePath("history.sqlite"), "legacy history preserved");
        write(temporary.filePath("receipts.sqlite"), "legacy receipts preserved");
        const auto info = cli({"profile-info", "--profile", "local-profile", "--state-directory",
                               temporary.path(), "--json"});
        QCOMPARE(info["profile"].toString(), QString("local-profile"));
        QCOMPARE(bytes(temporary.filePath("clients/profile-local-profile.json")), profile);
        QCOMPARE(bytes(temporary.filePath("history.sqlite")),
                 QByteArray("legacy history preserved"));
        QCOMPARE(bytes(temporary.filePath("receipts.sqlite")),
                 QByteArray("legacy receipts preserved"));
        const auto budget =
            cli({"state", "budget", "show", "--state-directory", temporary.path(), "--json"});
        QCOMPARE(budget["committed"].toString(),
                 QString::number(Budget::FileBytes + 2 * Domain::MarkerBytes));
        QVERIFY(!budget["productionQuotaEnforced"].toBool());
    }

    // 日期：2026-11-08；真实CLI空闲监听持有协调资格；进程被强制结束后内核归还锁，原域可配置。
    void realCliListenerBlocksConfiguration() {
        QTemporaryDir temporary;
        cli({"serve", "init", "--state-directory", temporary.path(), "--server-name", "localhost",
             "--json"});
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        auto executable = QCoreApplication::applicationDirPath() + "/dukto-cli";
#ifdef Q_OS_WIN
        executable += ".exe";
#endif
        Process server;
        server.start(executable, {"serve", "start", "--state-directory", temporary.path(), "--port",
                                  QString::number(port), "--bind", "127.0.0.1", "--json"});
        QVERIFY(server.waitForStarted(10000));
        const auto event = QJsonDocument::fromJson(line(server)).object();
        QCOMPARE(event["event"].toString(), QString("service-listening"));
        const auto budget =
            cli({"state", "budget", "show", "--state-directory", temporary.path(), "--json"});
        auto set = QStringList{"state",
                               "budget",
                               "set",
                               "--state-directory",
                               temporary.path(),
                               "--budget-revision",
                               budget["revision"].toString(),
                               "--json"};
        set += limits(Session::defaults());
        const auto refused = cli(set, static_cast<int>(dukto::ExitCode::Permission));
        QCOMPARE(refused["stage"].toString(), QString("state-use"));
        server.kill();
        QVERIFY(server.waitForFinished(30000));
        QCOMPARE(cli(set)["domain"].toString(), budget["domain"].toString());
    }
};

// 日期：2026-11-08；同一原生测试程序兼任真实子进程，普通入口输出原始Qt Test报告。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto arguments = application.arguments();
    if (arguments.size() == 3 &&
        (arguments[1] == "--bootstrap" || arguments[1] == "--exit-session"))
        return child(arguments);
    StateSessionTests tests;
    return QTest::qExec(&tests, argc, argv);
}
#include "state_session_tests.moc"

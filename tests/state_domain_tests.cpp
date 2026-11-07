#include "core/error.h"
#include "core/files.h"
#include "core/privatestore.h"
#include "core/statedomain.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtTest>
#include <atomic>
#include <cstdlib>
#include <thread>
#include <vector>

namespace {
using Store = dukto::PrivateStore;
using Domain = dukto::StateDomain;
using Budget = dukto::StateBudget;
constexpr auto Maintenance = Store::Use::Maintenance;

// 日期：2026-11-08；测试额度只额外容纳少量固定标记，实际业务数据库不以本夹具授予配额资格。
Budget::Limits limits(int markers = 64) {
    const auto maximum = Budget::FileBytes + qint64(markers) * Domain::MarkerBytes;
    return {maximum, {{0, maximum, 0, 0}}};
}

// 日期：2026-11-08；仅在测试自有控制文件上注入同对象损坏，不改变生产序列化器或权限检查。
void corrupt(const QString &path, bool truncate = false) {
    QFile file(path);
    if (!file.open(QIODevice::ReadWrite) ||
        (truncate ? !file.resize(70) : (!file.seek(200) || file.write("x", 1) != 1)) ||
        !file.flush())
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture corruption", "test");
}

// 日期：2026-11-08；从真实文件读取固定标记，不累积整个目录或数据库内容。
QByteArray marker(const Store &store) {
    QFile file(store.directory() + "/state-domain.bin");
    if (!file.open(QIODevice::ReadOnly) || file.size() != Domain::MarkerBytes)
        throw dukto::Error(dukto::ExitCode::Runtime, "fixture marker", "test");
    return file.read(Domain::MarkerBytes);
}

// 日期：2026-11-08；子进程在成员预扣后直接退出，证明跨文件中断不会隐式退款或授予不存在的绑定。
int child(const QStringList &arguments) {
    try {
        Store coordinator(arguments[2]);
        Store member(arguments[3], true, Maintenance);
        Domain ordinary(coordinator);
        const auto binding = ordinary.root(coordinator);
        Budget probe(coordinator, binding.domain);
        const auto before = probe.usage().totalCommitted;
        if (arguments[1] == "--orphan") {
            Domain domain(coordinator, [&probe, before] {
                // 日期：2026-11-08；检查回调发生在未持账本锁时，独立观察确认预扣真实落盘才退出。
                if (probe.usage().totalCommitted > before)
                    std::_Exit(71);
            });
            domain.bind(member);
            return 90;
        }
        ordinary.bind(member);
        QTextStream(stdout) << "ready" << Qt::endl;
        std::getchar();
        return 0;
    } catch (const dukto::Error &) {
        return 91;
    }
}

class Child final : public QProcess {
  public:
    // 日期：2026-11-08；测试断言提前退出时始终回收本测试启动的进程，避免遗留维护占用。
    ~Child() override {
        if (state() != NotRunning) {
            kill();
            waitForFinished(10000);
        }
    }
};
} // namespace

class StateDomainTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；自动生成域持久重开，中央标记确实扣款，普通接口无法改写保留键。
    void persistentCoordinatorAndReservedNames() {
        QTemporaryDir directory;
        Domain::Binding original;
        {
            Store store(directory.filePath("domain"), true, Maintenance);
            Domain::initialize(store, limits());
            Domain domain(store);
            original = domain.root(store);
            QVERIFY(original.coordinatorRoot);
            QCOMPARE(domain.usage().totalCommitted, Budget::FileBytes + Domain::MarkerBytes);
            QCOMPARE(marker(store).size(), Domain::MarkerBytes);
            QVERIFY_EXCEPTION_THROWN(store.read("state-domain.bin"), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.write("STATE-DOMAIN.BIN", {}), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(store.remove("State-Domain.Bin"), dukto::Error);
            const auto before = dukto::hashFile(store.directory() + "/state-budget.bin");
            QVERIFY_EXCEPTION_THROWN(Domain::initialize(store, limits()), dukto::Error);
            QCOMPARE(dukto::hashFile(store.directory() + "/state-budget.bin"), before);
        }
        Store store(directory.filePath("domain"));
        Domain reopened(store);
        reopened.verify(store, original);
        QCOMPARE(reopened.usage().domain, original.domain);
        QVERIFY_EXCEPTION_THROWN(reopened.bind(store), dukto::Error);
    }

    // 日期：2026-11-08；多层GUI/remote式目录显式关联同一域，路径点别名保持唯一登记和固定额度。
    void multipleRootsAndAliases() {
        QTemporaryDir directory;
        Store coordinator(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(coordinator, limits());
        Domain domain(coordinator);
        Store history(directory.filePath("history"), true, Maintenance);
        Store service(directory.filePath("remote-service"), true, Maintenance);
        const auto first = domain.bind(history);
        const auto second = domain.bind(service);
        QVERIFY(first.generation != second.generation);
        QCOMPARE(first.domain, second.domain);
        QCOMPARE(first.coordinator, second.coordinator);
        const auto before = domain.usage().totalCommitted;
        const auto original = marker(history);
        QCOMPARE(domain.bind(history).registration, first.registration);
        QCOMPARE(marker(history), original);
        QCOMPARE(domain.usage().totalCommitted, before);
        QCOMPARE(before, Budget::FileBytes + 3 * Domain::MarkerBytes);
        domain.verify(history, first);
        QVERIFY_EXCEPTION_THROWN(domain.verify(service, first), dukto::Error);
        // 日期：2026-11-08；维护实例释放后以路径别名取得普通共享根，不能并持独占/共享同一根。
        const auto sharedPath = directory.filePath("shared");
        Domain::Binding observed;
        {
            Store store(sharedPath, true, Maintenance);
            observed = domain.bind(store);
        }
        Store alias(sharedPath + "/.");
        domain.verify(alias, observed);
        QCOMPARE(domain.usage().totalCommitted, before + Domain::MarkerBytes);
    }

    // 日期：2026-11-08；未知根共享使用不创建标记，跨域绑定拒绝且两账本及原标记均保持。
    void foreignDomainAndUnregisteredRoot() {
        QTemporaryDir directory;
        Store first(directory.filePath("one"), true, Maintenance);
        Store second(directory.filePath("two"), true, Maintenance);
        Domain::initialize(first, limits());
        Domain::initialize(second, limits());
        Domain one(first), two(second);
        Store member(directory.filePath("member"), true, Maintenance);
        QVERIFY_EXCEPTION_THROWN(one.root(member), dukto::Error);
        QVERIFY(!QFileInfo::exists(member.directory() + "/state-domain.bin"));
        const auto binding = one.bind(member);
        const auto before = marker(member);
        const auto charge = two.usage().totalCommitted;
        QVERIFY_EXCEPTION_THROWN(two.bind(member), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(two.root(member), dukto::Error);
        QCOMPARE(marker(member), before);
        QCOMPARE(two.usage().totalCommitted, charge);
        one.verify(member, binding);
    }

    // 日期：2026-11-08；复制成员标记或整个中央控制区均因新目录原生身份不同拒绝，绝不覆盖原件。
    void copiedMarkersAndCoordinatorAreRejected() {
        QTemporaryDir directory;
        Store source(directory.filePath("source"), true, Maintenance);
        Domain::initialize(source, limits());
        Domain domain(source);
        Store member(directory.filePath("member"), true, Maintenance);
        domain.bind(member);
        Store copy(directory.filePath("copy"), true, Maintenance);
        QVERIFY(QFile::copy(member.directory() + "/state-domain.bin",
                            copy.directory() + "/state-domain.bin"));
        QVERIFY_EXCEPTION_THROWN(domain.root(copy), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(domain.bind(copy), dukto::Error);
        Store duplicate(directory.filePath("duplicate"), true, Maintenance);
        for (const auto &name : {"state-domain.bin", "state-budget.bin"})
            QVERIFY(
                QFile::copy(source.directory() + '/' + name, duplicate.directory() + '/' + name));
        QVERIFY_EXCEPTION_THROWN(Domain{duplicate}, dukto::Error);
        QVERIFY_EXCEPTION_THROWN(Domain::initialize(duplicate, limits()), dukto::Error);
    }

    // 日期：2026-11-08；中央已退役登记不能凭本地旧标记重新认领；损坏/截断标记不自动修复。
    void retiredRegistrationAndCorruption() {
        QTemporaryDir directory;
        Store coordinator(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(coordinator, limits());
        Domain domain(coordinator);
        Store member(directory.filePath("member"), true, Maintenance);
        const auto binding = domain.bind(member);
        Budget budget(coordinator, binding.domain);
        budget.retire(budget.lookup(binding.key));
        const auto before = domain.usage().totalCommitted;
        QVERIFY_EXCEPTION_THROWN(domain.root(member), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(domain.bind(member), dukto::Error);
        QCOMPARE(domain.usage().totalCommitted, before);
        Store damaged(directory.filePath("damaged"), true, Maintenance);
        domain.bind(damaged);
        corrupt(damaged.directory() + "/state-domain.bin");
        QVERIFY_EXCEPTION_THROWN(domain.root(damaged), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(domain.bind(damaged), dukto::Error);
        Store truncated(directory.filePath("truncated"), true, Maintenance);
        domain.bind(truncated);
        corrupt(truncated.directory() + "/state-domain.bin", true);
        QVERIFY_EXCEPTION_THROWN(domain.root(truncated), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(domain.bind(truncated), dukto::Error);
    }

    // 日期：2026-11-08；中央标记同对象损坏立即使已有域实例失效，不授予已缓存成员资格。
    void coordinatorMutationInvalidatesExistingDomain() {
        QTemporaryDir directory;
        Store coordinator(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(coordinator, limits());
        Domain domain(coordinator);
        Store member(directory.filePath("member"), true, Maintenance);
        const auto binding = domain.bind(member);
        corrupt(coordinator.directory() + "/state-domain.bin");
        QVERIFY_EXCEPTION_THROWN(domain.verify(member, binding), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(domain.usage(), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(Domain{coordinator}, dukto::Error);
    }

    // 日期：2026-11-08；额度不足在创建成员控制文件之前拒绝，不发生未计量固定文件增长。
    void admissionPrecedesMarkerCreation() {
        QTemporaryDir directory;
        Store coordinator(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(coordinator, limits(1));
        Domain domain(coordinator);
        Store member(directory.filePath("member"), true, Maintenance);
        const auto before = domain.usage().totalCommitted;
        QVERIFY_EXCEPTION_THROWN(domain.bind(member), dukto::Error);
        QVERIFY(!QFileInfo::exists(member.directory() + "/state-domain.bin"));
        QCOMPARE(domain.usage().totalCommitted, before);
        Store tooSmall(directory.filePath("small"), true, Maintenance);
        QVERIFY_EXCEPTION_THROWN(Domain::initialize(tooSmall, limits(0)), dukto::Error);
        QVERIFY(!QFileInfo::exists(tooSmall.directory() + "/state-budget.bin"));
        QVERIFY(!QFileInfo::exists(tooSmall.directory() + "/state-domain.bin"));
    }

    // 日期：2026-11-08；真实进程持有成员维护占用时拒绝其他登记者，强退后正常重开复用同一绑定。
    void processMaintenanceAndReopen() {
        QTemporaryDir directory;
        const auto central = directory.filePath("budget");
        const auto member = directory.filePath("member");
        {
            Store store(central, true, Maintenance);
            Domain::initialize(store, limits());
        }
        Child process;
        process.start(QCoreApplication::applicationFilePath(), {"--hold", central, member});
        QVERIFY(process.waitForStarted(10000));
        QElapsedTimer elapsed;
        elapsed.start();
        while (!process.canReadLine() && process.state() != QProcess::NotRunning &&
               elapsed.elapsed() < 30000)
            process.waitForReadyRead(100);
        const auto line = process.readLine();
        QVERIFY2(line == "ready\n" || line == "ready\r\n", line.constData());
        QVERIFY_EXCEPTION_THROWN((Store{member, false, Maintenance}), dukto::Error);
        process.kill();
        QVERIFY(process.waitForFinished(10000));
        Store store(central);
        Store target(member, false, Maintenance);
        Domain reopened(store);
        const auto before = reopened.usage().totalCommitted;
        const auto binding = reopened.root(target);
        QCOMPARE(reopened.bind(target).generation, binding.generation);
        QCOMPARE(reopened.usage().totalCommitted, before);
    }

    // 日期：2026-11-08；扣款后标记创建前直接退出保留占用；下一次新生命周期额外计量且旧观察失效。
    void exitBeforeMarkerRetainsCharge() {
        QTemporaryDir directory;
        const auto central = directory.filePath("budget");
        const auto member = directory.filePath("member");
        {
            Store store(central, true, Maintenance);
            Domain::initialize(store, limits());
        }
        Child process;
        process.start(QCoreApplication::applicationFilePath(), {"--orphan", central, member});
        QVERIFY(process.waitForStarted(10000));
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 71);
        QVERIFY(!QFileInfo::exists(member + "/state-domain.bin"));
        Store store(central);
        Store target(member, false, Maintenance);
        Domain domain(store);
        QCOMPARE(domain.usage().totalCommitted, Budget::FileBytes + 2 * Domain::MarkerBytes);
        const auto first = domain.bind(target);
        QCOMPARE(domain.usage().totalCommitted, Budget::FileBytes + 3 * Domain::MarkerBytes);
        QVERIFY(QFile::remove(member + "/state-domain.bin"));
        const auto second = domain.bind(target);
        QVERIFY(first.generation != second.generation);
        QCOMPARE(domain.usage().totalCommitted, Budget::FileBytes + 4 * Domain::MarkerBytes);
        QVERIFY_EXCEPTION_THROWN(domain.verify(target, first), dukto::Error);
    }

    // 日期：2026-11-08；四线程共用域和中央账本登记不同根；无缓存名称全集，每个根只扣固定标记一次。
    void threadsShareOneDomain() {
        QTemporaryDir directory;
        Store coordinator(directory.filePath("budget"), true, Maintenance);
        Domain::initialize(coordinator, limits());
        Domain domain(coordinator);
        std::atomic<int> passed{0};
        std::vector<std::thread> workers;
        for (int index = 0; index < 4; ++index) {
            const auto path = directory.filePath(QString::number(index));
            workers.emplace_back([&domain, &passed, path] {
                // 日期：2026-11-08；线程异常以独立计数报告，不让测试进程因未捕获异常直接终止。
                try {
                    Store root(path, true, Maintenance);
                    const auto binding = domain.bind(root);
                    domain.verify(root, binding);
                    if (domain.bind(root).registration == binding.registration)
                        ++passed;
                } catch (const dukto::Error &) {
                }
            });
        }
        for (auto &worker : workers)
            worker.join();
        QCOMPARE(passed.load(), 4);
        QCOMPARE(domain.usage().totalCommitted, Budget::FileBytes + 5 * Domain::MarkerBytes);
    }
};

// 日期：2026-11-08；专用子进程模式不运行QtTest；普通执行完整原生故障和关联回归。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto arguments = application.arguments();
    if (arguments.size() == 4 && (arguments[1] == "--hold" || arguments[1] == "--orphan"))
        return child(arguments);
    StateDomainTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "state_domain_tests.moc"

#include "statesession.h"
#include "error.h"
#include "files.h"
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QThread>

namespace dukto {
namespace {
constexpr int BootstrapMs = 5000;

// 日期：2026-11-08；只允许应用明确传入的七个业务位置，不从任意目录名称推断删除或计量归属。
QString memberPath(const QString &parent, const QString &relative) {
    if (parent.isEmpty() || !QStringList{"service", "clients", "transfers", "history",
                                         "remote/service", "remote/clients", "remote/transfers"}
                                 .contains(relative))
        throw Error(ExitCode::Config, QStringLiteral("状态根位置无效"), "state-session");
    return QDir(parent).absoluteFilePath(relative);
}

// 日期：2026-11-08；链接与损坏控制文件都视为存在，后续原生校验必须拒绝，不能重新初始化。
bool present(const PrivateStore &store, const QString &name) {
    const auto path = QDir(store.directory()).filePath(name);
    return QFileInfo::exists(path) || isLinkedPath(path);
}

// 日期：2026-11-08；初始化/登记前后目录必须保持同一原生对象，重开不能悄悄接管同名新根。
void sameRoot(const PrivateStore &store, QByteArray &identity) {
    const auto current = store.identity();
    if (!identity.isEmpty() && identity != current)
        throw Error(ExitCode::Integrity, QStringLiteral("状态根在建立关联期间已换代"),
                    "state-session");
    identity = current;
}

// 日期：2026-11-08；仅原生根占用冲突允许短暂重试，ACL错误和其他故障立即保留原错误。
bool contention(const Error &error) {
    return error.code == ExitCode::Permission && error.stage == "state-use";
}
} // namespace

// 日期：2026-11-08；检查器只在预算锁外调用，不持有网络/SQLite对象或等待外部输入。
StateSession::StateSession(std::function<void()> check) : check_(std::move(check)) {
}

// 日期：2026-11-08；成员按声明逆序关闭，账本/标记先于协调根共享资格析构。
StateSession::~StateSession() = default;

// 日期：2026-11-08；默认20GiB合计、256MiB历史、1GiB元数据、16GiB正文和256MiB未知额。
StateBudget::Limits StateSession::defaults() {
    constexpr qint64 MiB = 1024 * 1024;
    return {20 * 1024 * MiB, {{256 * MiB, 1024 * MiB, 16 * 1024 * MiB, 256 * MiB}}};
}

// 日期：2026-11-08；取消不清除控制文件、未决登记或已有占用。
void StateSession::checkpoint() const {
    if (check_)
        check_();
}

// 日期：2026-11-08；首次初始化取得独占资格后再次核对；释放独占再以共享重开，不原地升级。
void StateSession::attach(const QString &parent, bool initialize) {
    if (parent.isEmpty() || !QFileInfo(parent).isDir())
        throw Error(ExitCode::Disk, QStringLiteral("状态父目录不存在"), "state-session");
    const auto path = QDir(parent).filePath("budget");
    QElapsedTimer timer;
    timer.start();
    QByteArray identity;
    for (;;) {
        checkpoint();
        try {
            auto store = std::unique_ptr<PrivateStore>(new PrivateStore(path, initialize));
            sameRoot(*store, identity);
            if (present(*store, "state-domain.bin") || present(*store, "state-budget.bin")) {
                auto domain = std::unique_ptr<StateDomain>(new StateDomain(*store, check_));
                coordinator_ = std::move(store);
                domain_ = std::move(domain);
                return;
            }
            if (!initialize)
                throw Error(ExitCode::Integrity, QStringLiteral("已有预算协调根缺少完整控制文件"),
                            "state-session");
            store.reset();
            {
                PrivateStore exclusive(path, false, PrivateStore::Use::Maintenance);
                sameRoot(exclusive, identity);
                if (present(exclusive, "state-domain.bin") ||
                    present(exclusive, "state-budget.bin"))
                    StateDomain existing(exclusive, check_);
                else
                    StateDomain::initialize(exclusive, defaults());
            }
        } catch (const Error &error) {
            if (!contention(error) || timer.elapsed() >= BootstrapMs)
                throw;
            checkpoint();
            QThread::msleep(20);
        }
    }
}

// 日期：2026-11-08；业务调用显式选状态父目录，私有协调根独立于普通父目录和旧历史文件。
std::shared_ptr<StateSession> StateSession::open(const QString &parent,
                                                 std::function<void()> check) {
    auto result = std::shared_ptr<StateSession>(new StateSession(std::move(check)));
    result->attach(parent, true);
    return result;
}

// 日期：2026-11-08；共享指针的删除器保留协调会话，最后一个业务根关闭后才能配置维护。
std::shared_ptr<PrivateStore> StateSession::retain(std::unique_ptr<PrivateStore> store) {
    return std::shared_ptr<PrivateStore>(store.release(),
                                         [session = shared_from_this()](PrivateStore *value) {
                                             // 日期：2026-11-08；删除成员根时仍持有会话，避免先归还协调资格再关闭业务句柄。
                                             Q_UNUSED(session)
                                             delete value;
                                         });
}

// 日期：2026-11-08；既有共享根只核对，首次成员登记另取独占；全部返回对象保留域共享占用。
std::shared_ptr<PrivateStore> StateSession::root(const QString &parent, const QString &relative,
                                                 bool create, PrivateStore::Use use,
                                                 std::function<void()> check) {
    const auto path = memberPath(parent, relative);
    if (check)
        check();
    if (create && !QDir().mkpath(QFileInfo(path).absolutePath()))
        throw Error(ExitCode::Disk, QStringLiteral("无法准备业务状态父目录"), "state-session");
    // 日期：2026-11-08；先核对实际业务根权限，失败不建立无关的预算域或覆盖已有文件。
    QElapsedTimer timer;
    timer.start();
    std::unique_ptr<PrivateStore> store;
    for (;;) {
        if (check)
            check();
        try {
            store.reset(new PrivateStore(path, create, use));
            break;
        } catch (const Error &error) {
            if (use == PrivateStore::Use::Maintenance || !contention(error) ||
                timer.elapsed() >= BootstrapMs)
                throw;
            QThread::msleep(20);
        }
    }
    QByteArray identity;
    sameRoot(*store, identity);
    auto session = open(parent, std::move(check));
    for (;;) {
        session->checkpoint();
        try {
            if (!store)
                store.reset(new PrivateStore(path, false, use));
            sameRoot(*store, identity);
            if (present(*store, "state-domain.bin")) {
                session->domain_->root(*store);
                return session->retain(std::move(store));
            }
            if (use == PrivateStore::Use::Maintenance) {
                session->domain_->bind(*store);
                return session->retain(std::move(store));
            }
            store.reset();
            {
                PrivateStore exclusive(path, false, PrivateStore::Use::Maintenance);
                sameRoot(exclusive, identity);
                session->domain_->bind(exclusive);
            }
        } catch (const Error &error) {
            store.reset();
            if (use == PrivateStore::Use::Maintenance || !contention(error) ||
                timer.elapsed() >= BootstrapMs)
                throw;
            session->checkpoint();
            QThread::msleep(20);
        }
    }
}

// 日期：2026-11-08；只读观察不建立域/标记；发现已有关联则必须由真实中央登记核对，残片拒绝。
std::shared_ptr<PrivateStore> StateSession::observe(const QString &parent, const QString &relative,
                                                    PrivateStore::Use use,
                                                    std::function<void()> check) {
    const auto path = memberPath(parent, relative);
    auto store = std::unique_ptr<PrivateStore>(new PrivateStore(path, false, use));
    if (check)
        check();
    const auto budget = QDir(parent).filePath("budget");
    if (!QFileInfo::exists(budget) && !isLinkedPath(budget) && !present(*store, "state-domain.bin"))
        return std::shared_ptr<PrivateStore>(store.release());
    auto session = std::shared_ptr<StateSession>(new StateSession(std::move(check)));
    session->attach(parent, false);
    if (present(*store, "state-domain.bin"))
        session->domain_->root(*store);
    return session->retain(std::move(store));
}

// 日期：2026-11-08；只报告固定账本范围，不将根关联误报为生产SQLite/正文已经受总额限制。
StateBudget::Usage StateSession::usage() {
    return domain_->usage();
}
} // namespace dukto

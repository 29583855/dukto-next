#pragma once
#include "budgetfile.h"
#include <QByteArray>
#include <QUuid>
#include <array>
#include <functional>

namespace dukto {
class PrivateStore;
class StateBudget final {
  public:
    enum class Category : quint32 { History = 0, Metadata = 1, Body = 2, Unknown = 3 };
    static constexpr int SlotCount = 4096;
    static constexpr qint64 FileBytes = 8192 + qint64(SlotCount) * 256;
    struct Limits {
        qint64 total = 0;
        std::array<qint64, 4> categories{};
    };
    struct Record {
        int slot = -1;
        QByteArray key;
        QUuid registration;
        QUuid operation;
        QUuid actor;
        quint64 revision = 0;
        Category category = Category::Unknown;
        qint64 committed = 0;
        qint64 reserved = 0;
        bool pending = false;
    };
    struct Usage {
        QUuid domain;
        quint64 revision = 0;
        std::array<qint64, 4> committed{};
        std::array<qint64, 4> reserved{};
        qint64 totalCommitted = 0;
        qint64 totalReserved = 0;
        bool overdrawn = false;
    };
    // 日期：2026-11-08；独占维护显式初始化固定1MiB记录区及日志，已有账本绝不覆盖或重置为零。
    static void initialize(const PrivateStore &store, const QUuid &domain, const Limits &limits);
    // 日期：2026-11-08；打开已有域并验证所有固定槽及合计；日志只向前重放，不回滚已发放预留。
    StateBudget(const PrivateStore &store, const QUuid &domain, std::function<void()> check = {},
                int timeoutMs = 1000);
    // 日期：2026-11-08；关闭账本不自动释放对象或未决操作的持久占用。
    ~StateBudget();
    StateBudget(const StateBudget &) = delete;
    StateBudget &operator=(const StateBudget &) = delete;
    // 日期：2026-11-08；登记调用方已证明的对象生命周期键；同键不重复扣款，槽耗尽受控拒绝。
    Record enroll(const QByteArray &key, Category category, qint64 committed);
    // 日期：2026-11-08；固定内存逐槽查找，返回真实修订和未决预留；不按PID自动恢复额度。
    Record lookup(const QByteArray &key);
    // 日期：2026-11-08；以登记代数和修订协调同一对象；先持久化绝对占用上界才允许调用方I/O。
    Record reserve(const Record &expected, qint64 maximumCharge);
    // 日期：2026-11-08；调用方须取得真实I/O后观察；部分失败不能退款，超预期真实占用记为透支并阻止新准入。
    Record settle(const Record &reservation, qint64 actualCharge);
    // 日期：2026-11-08；仅独占维护在已证明对象释放后注销；墓碑防止重复退款及槽复用ABA。
    void retire(const Record &expected);
    // 日期：2026-11-08；独占维护在取得对象/生命周期证据后解决遗留未决授信，不把进程消失当作文件消失。
    Record reconcile(const Record &expected, qint64 actualCharge);
    // 日期：2026-11-08；返回固定类别合计与透支状态，账本自身固定长度计入元数据占用。
    Usage usage();

  private:
    struct Header;
    struct Slot;
    // 日期：2026-11-08；先重放有校验的意图，再核对域和固定长度；不完整/未知格式拒绝增长。
    Header load();
    // 日期：2026-11-08；构造时完整审计固定4096槽，内存保持常量，合计必须与持久头一致。
    void audit(const Header &header);
    // 日期：2026-11-08；单槽与头以固定写前日志提交，意图/数据/清日志分别同步，失败保留未知结果。
    void commit(const Header &before, const Header &after, int index, const QByteArray &oldSlot,
                const QByteArray &newSlot);
    // 日期：2026-11-08；检查登记生命周期、修订及调用方记录，过期观察不能覆盖新的预留或同名新对象。
    Slot checked(const Record &record, const Header &header);
    // 日期：2026-11-08；由同一槽的旧/新值计算合计，检查64位溢出与额度；归还不绕开持久事务。
    Header adjusted(const Header &before, const Slot &oldSlot, const Slot &newSlot,
                    bool admission) const;
    const PrivateStore &store_;
    BudgetFile file_;
    QUuid domain_;
    QByteArray root_;
    QUuid actor_ = QUuid::createUuid();
    std::function<void()> check_;
    int timeoutMs_;
};
} // namespace dukto

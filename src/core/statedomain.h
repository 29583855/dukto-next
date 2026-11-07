#pragma once
#include "budgetfile.h"
#include "statebudget.h"
#include <memory>

namespace dukto {
class PrivateStore;
class StateDomain final {
  public:
    static constexpr int MarkerBytes = 256;
    struct Binding {
        QUuid domain;
        QUuid coordinator;
        QUuid generation;
        QUuid registration;
        QByteArray nativeCoordinator;
        QByteArray nativeRoot;
        QByteArray key;
        bool coordinatorRoot = false;
    };
    // 日期：2026-11-08；独占维护显式建立新域；任一控制文件已存在均拒绝，失败不重置账本。
    static void initialize(const PrivateStore &coordinator, const StateBudget::Limits &limits);
    // 日期：2026-11-08；从受保护标记发现持久域，核对协调根原生身份及账本登记，不按路径推断。
    explicit StateDomain(const PrivateStore &coordinator, std::function<void()> check = {},
                         int timeoutMs = 1000);
    // 日期：2026-11-08；关闭域不删除根标记、不注销登记、不退款。
    ~StateDomain();
    StateDomain(const StateDomain &) = delete;
    StateDomain &operator=(const StateDomain &) = delete;
    // 日期：2026-11-08；目标根须独占维护；先持久计量固定标记，再独占创建，已有绑定只核对不改写。
    Binding bind(const PrivateStore &root);
    // 日期：2026-11-08；普通共享使用只打开已有标记并交叉核对中央登记；不隐式认领新根。
    Binding root(const PrivateStore &store);
    // 日期：2026-11-08；调用方保留生命周期观察，后续操作前拒绝同名目录/标记换代及旧登记。
    void verify(const PrivateStore &store, const Binding &expected);
    // 日期：2026-11-08；只报告该域账本已有登记，尚不代表全部生产写入已纳入总预算。
    StateBudget::Usage usage();

  private:
    // 日期：2026-11-08；重验协调标记及其登记；局部目录有效不能掩盖中央域换代。
    void verifyCoordinator();
    // 日期：2026-11-08；中央记录必须是同一登记代数、Metadata类别和固定标记占用。
    void verifyRegistration(const Binding &binding);
    const PrivateStore &store_;
    BudgetFile marker_;
    Binding coordinator_;
    std::unique_ptr<StateBudget> budget_;
    std::function<void()> check_;
    int timeoutMs_;
};
} // namespace dukto

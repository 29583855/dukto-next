#pragma once

#include "privatestore.h"
#include "statedomain.h"
#include <memory>

namespace dukto {
class StateSession final : public std::enable_shared_from_this<StateSession> {
  public:
    // 日期：2026-11-08；首次业务使用按默认额度建立域，后续仅共享核对；残片及损坏不重置。
    static std::shared_ptr<StateSession> open(const QString &parent,
                                              std::function<void()> check = {});
    // 日期：2026-11-08；业务根仅接受固定直接/旧GUI位置；返回对象持续持有协调根共享资格。
    static std::shared_ptr<PrivateStore> root(const QString &parent, const QString &relative,
                                              bool create = false,
                                              PrivateStore::Use use = PrivateStore::Use::Shared,
                                              std::function<void()> check = {});
    // 日期：2026-11-08；诊断/占用查询不建立预算或根标记；已有域和标记仍须核对并持有共享资格。
    static std::shared_ptr<PrivateStore> observe(const QString &parent, const QString &relative,
                                                 PrivateStore::Use use = PrivateStore::Use::Shared,
                                                 std::function<void()> check = {});
    // 日期：2026-11-08；默认额度可通过既有CLI持久修改；额度不是预分配、可用空间或无限承诺。
    static StateBudget::Limits defaults();
    // 日期：2026-11-08；仅查询该持久账本已登记对象，业务正文和SQLite尚未自动进入合计。
    StateBudget::Usage usage();
    // 日期：2026-11-08；先关闭域的原生文件，再归还协调根共享占用；不删除或退款。
    ~StateSession();

  private:
    // 日期：2026-11-08；创建仅由静态工厂调用，成员根的返回所有权保留同一会话寿命。
    explicit StateSession(std::function<void()> check);
    // 日期：2026-11-08；在未持预算锁时响应取消，初始化竞争最多等待五秒。
    void checkpoint() const;
    // 日期：2026-11-08；只等待原生占用竞争，不因权限、损坏或未知格式自动修复现场。
    void attach(const QString &parent, bool initialize);
    // 日期：2026-11-08；成员先析构，再释放捕获的会话，配置维护不能穿过活动业务生命周期。
    std::shared_ptr<PrivateStore> retain(std::unique_ptr<PrivateStore> store);
    std::function<void()> check_;
    std::unique_ptr<PrivateStore> coordinator_;
    std::unique_ptr<StateDomain> domain_;
};
} // namespace dukto

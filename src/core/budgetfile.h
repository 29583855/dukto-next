#pragma once
#include <QByteArray>
#include <functional>
#include <memory>

namespace dukto {
class PrivateStore;
class BudgetFile final {
  public:
    enum class Kind { Ledger, Domain };
    // 日期：2026-11-08；只打开永久账本单项；创建要求独占维护，绝不截断或替换已有账本。
    BudgetFile(const PrivateStore &store, bool create, Kind kind = Kind::Ledger);
    // 日期：2026-11-08；关闭本实例描述符，账本名称永久保留，退出不隐式退款。
    ~BudgetFile();
    BudgetFile(const BudgetFile &) = delete;
    BudgetFile &operator=(const BudgetFile &) = delete;
    class Lock final {
      public:
        // 日期：2026-11-08；进程内互斥和原生跨进程锁共用取消/超时，回调只在未持原生锁时执行。
        Lock(BudgetFile &file, const std::function<void()> &check, int timeoutMs);
        // 日期：2026-11-08；正常和异常均先归还原生锁，再归还本实例互斥。
        ~Lock();
        Lock(const Lock &) = delete;
        Lock &operator=(const Lock &) = delete;

      private:
        BudgetFile &file_;
    };
    // 日期：2026-11-08；仅锁内访问固定有界片段；短读不能被补零掩盖为有效账本。
    QByteArray read(qint64 offset, int bytes);
    // 日期：2026-11-08；仅锁内写入固定片段；短写/磁盘错误明确失败，日志保留供下次核对。
    void write(qint64 offset, const QByteArray &bytes);
    // 日期：2026-11-08；同步真实文件及创建后的目录，不经过PrivateStore原子写入而递归申请预算。
    void synchronize();
    // 日期：2026-11-08；只返回固定目录身份摘要的输入，不读任何业务正文。
    QByteArray rootIdentity() const;
    // 日期：2026-11-08；核对根、原生文件权限及当前路径身份；不能对换代后的同名文件继续操作。
    void verify() const;
    // 日期：2026-11-08；返回当前文件真实长度，固定格式调用方必须精确核对。
    qint64 size() const;

  private:
    // 日期：2026-11-08；有界重试独占锁，任何错误/取消均释放已取得的互斥。
    void lock(const std::function<void()> &check, int timeoutMs);
    // 日期：2026-11-08；析构路径不抛异常，文件句柄的关闭仍由实例生命周期保证。
    void unlock() noexcept;
    struct Implementation;
    std::unique_ptr<Implementation> implementation_;
};
} // namespace dukto

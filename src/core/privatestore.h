#pragma once

#include "nativecommit.h"
#include <QByteArray>
#include <QJsonObject>
#include <QString>
#include <functional>
#include <memory>

class QIODevice;

namespace dukto {
class StateUseGuard;
class PrivateStore final {
  public:
    enum class Use { Shared, Maintenance };
    // 日期：2026-11-07；普通使用共享原生锁，维护独占且不等待；已有根权限不安全时拒绝。
    explicit PrivateStore(const QString &directory, bool create = false, Use use = Use::Shared);
    // 日期：2026-11-04；关闭本状态根持有的原生目录句柄。
    ~PrivateStore();
    // 日期：2026-11-04；核对目录及文件访问控制后有界读取，缺失/错误均明确报告。
    QByteArray read(const QString &name, qint64 maximum = 65536) const;
    // 日期：2026-11-04；大状态数据库仅核对原生权限和普通文件身份，不把整个数据库读入内存。
    qint64 validateFile(const QString &name) const;
    // 日期：2026-11-07；独占维护只校验规范SQLite回滚日志，保留私有DACL与独立普通对象要求。
    qint64 validateSqliteJournal(const QString &name) const;
    // 日期：2026-11-04；在受保护根内写入、同步并原子替换，内容不进入日志或命令行。
    void write(const QString &name, const QByteArray &bytes) const;
    // 日期：2026-11-09；从创建时设置私有所有者/权限，有界流式写入并独占发布，不覆盖已有键。
    void create(const QString &name, qint64 maximum,
                const std::function<void(QIODevice &)> &writer) const;
    // 日期：2026-11-04；仅查询固定根的单个合法文件名，不解析客户端路径。
    bool exists(const QString &name) const;
    // 日期：2026-11-04；仅删除固定私有根内的单个合法键，不递归遍历或跟随目标链接。
    void remove(const QString &name) const;
    // 日期：2026-11-04；返回受保护状态根，调用方仍须通过本类访问秘密文件。
    QString directory() const;
    // 日期：2026-11-08；重验固定根后返回不含路径/修改时间的原生身份，仅供持久域关联。
    QByteArray identity() const;
    // 日期：2026-11-07；维护调用方显式核对独占模式，普通状态实例不能冒充维护所有者。
    bool maintenance() const;
    // 日期：2026-11-08；独占维护按后缀汇总直接普通文件的逻辑/分配量，不读取正文或授予删除资格。
    QJsonObject storageUsage(const std::function<void()> &check = {}) const;
    // 日期：2026-11-08；独占维护时逐项访问原生观察，调用方不得据瞬时身份删除对象或累积无界名称。
    void visitStorageEntries(const std::function<void(const NativeDirectoryEntry &)> &visitor,
                             const std::function<void()> &check = {}) const;

  private:
    friend class BudgetFile;
    // 日期：2026-11-07；内部共用原生对象核验，普通调用不能选择日志所有者策略。
    qint64 validateFileObject(const QString &name, bool sqliteJournal) const;
    // 日期：2026-11-04；重复核对根权限，防止启动后无意放宽状态目录访问控制仍继续写秘密。
    void verify() const;
    // 日期：2026-11-04；状态键只允许固定 ASCII 名称，不能通过它穿越根目录或打开数据流。
    QString path(const QString &name) const;
    QString directory_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> root_;
#else
    std::unique_ptr<PosixDirectory> root_;
#endif
    std::unique_ptr<StateUseGuard> use_;
};
} // namespace dukto

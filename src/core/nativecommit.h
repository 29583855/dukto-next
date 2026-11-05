#pragma once

#include <QByteArray>
#include <QLockFile>
#include <QString>
#include <QtGlobal>
#include <memory>
#ifdef Q_OS_WIN
#include <vector>
#endif

namespace dukto {
#ifdef Q_OS_WIN
class NativeDirectoryLock final {
  public:
    // 日期：2026-11-04；逐层打开并固定 Windows 目录，拒绝重解析点和删除/替换竞争。
    NativeDirectoryLock(const QString &directory, bool createMissing);
    // 日期：2026-11-04；按子目录到根目录的顺序释放原生目录句柄。
    ~NativeDirectoryLock();
    // 日期：2026-11-04；返回原生目录身份和修改时间，分页快照用它检测目录变化。
    QByteArray stamp() const;
    // 日期：2026-11-04；只返回卷/文件 ID，不含会随目录内容变化的时间戳，供持久目录预约。
    QByteArray identity() const;
    NativeDirectoryLock(const NativeDirectoryLock &) = delete;
    NativeDirectoryLock &operator=(const NativeDirectoryLock &) = delete;

  private:
    // 日期：2026-11-04；构造异常与正常析构共用清理，避免部分父目录句柄泄漏。
    void release();
    std::vector<void *> handles_;
};
#else
class PosixDirectory final {
  public:
    // 日期：2026-11-04；逐层以 O_NOFOLLOW 打开目录，后续创建/提交仅使用固定的目录描述符。
    PosixDirectory(const QString &directory, bool createMissing);
    // 日期：2026-11-04；关闭当前任务独占的目录描述符。
    ~PosixDirectory();
    PosixDirectory(const PosixDirectory &) = delete;
    PosixDirectory &operator=(const PosixDirectory &) = delete;
    // 日期：2026-11-04；重新安全遍历原路径并核对 inode，已被移动/替换时拒绝发布完成名称。
    void verify() const;
    // 日期：2026-11-04；以固定描述符读取 dev/inode 和纳秒修改/状态时间，不重新跟随路径。
    QByteArray stamp() const;
    // 日期：2026-11-04；只返回设备/inode，供恢复时核对本任务已创建的目录对象。
    QByteArray identity() const;
    // 日期：2026-11-04；相对固定父目录打开普通源文件，不跟随最后分量链接，也不阻塞在 FIFO。
    int openRead(const QString &name) const;
    // 日期：2026-11-04；持久接收以独占创建或不跟随链接方式重开普通文件，不隐式截断已有数据。
    int openUpdate(const QString &name, bool create) const;
    // 日期：2026-11-04；发布名称后同步固定父目录，失败报告提交持久性未知。
    void synchronize() const;
    // 日期：2026-11-04；私有状态根必须属于当前有效用户且禁止其他用户读取/写入/遍历。
    void verifyPrivate() const;
    // 日期：2026-11-04；私有状态更新使用同目录原子替换，随后同步目录；不用于普通接收的同名策略。
    void replaceTemporary(const QString &name, const QString &destination) const;
    // 日期：2026-11-04；生成不可预测名称并以独占、禁止跟随链接的方式创建 0600 临时文件。
    int createTemporary(QString &name) const;
    // 日期：2026-11-04；在同一固定目录内不覆盖提交，目标存在返回 false，不允许复制回退。
    bool commitTemporary(const QString &name, const QString &destination) const;
    // 日期：2026-11-05；普通接收的同目录原子替换，拒绝目录/链接/特殊项，不允许复制回退。
    void replaceReceived(const QString &name, const QString &destination) const;
    // 日期：2026-11-04；异常或取消只删除固定目录中的本任务临时项，不通过被替换的路径清理。
    void removeTemporary(const QString &name) const;
    // 日期：2026-11-04；显式状态清理检查 unlinkat 结果，除不存在外的错误必须报告。
    void removeEntry(const QString &name) const;
    // 日期：2026-11-04；独占创建单层子目录，已有同名项返回 false，其余错误明确失败。
    bool createChild(const QString &name) const;

  private:
    QString path_;
    int descriptor_ = -1;
};
#endif
#ifdef Q_OS_WIN
// 日期：2026-11-04；Qt5 的 isSymLink 不覆盖所有 junction，使用原生属性拒绝任何重解析点。
bool isNativeReparsePoint(const QString &path);
// 日期：2026-11-04；Windows 同文件系统独占提交；目标已存在返回 false，其余失败抛错。
bool renameNoReplace(const QString &source, const QString &destination, bool durable = false);
#endif

#ifdef Q_OS_WIN
// 日期：2026-11-05；固定父目录后原子替换同名普通文件；原文件在发布之前保持完整。
void replaceReceivedFile(const QString &source, const QString &destination);
#endif

// 预约文件位于目标父目录；仅协调本程序的新执行者，不宣称文件系统具有路径 CAS。
class TargetReservation final {
  public:
    // 日期：2026-11-05；固定父目录，按规范文件名预约一个目标；不等待活动执行者。
    explicit TargetReservation(const QString &destination);
    // 日期：2026-11-05；先移除本任务锁文件，再释放父目录；死进程由 QLockFile 身份检测接管。
    ~TargetReservation();
    // 日期：2026-11-05；返回是否成功预约，调用者按 rename/fail/overwrite 分别裁决。
    bool acquired() const;
    TargetReservation(const TargetReservation &) = delete;
    TargetReservation &operator=(const TargetReservation &) = delete;

  private:
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> parent_;
#else
    std::unique_ptr<PosixDirectory> parent_;
#endif
    std::unique_ptr<QLockFile> lock_;
    bool acquired_ = false;
};
} // namespace dukto

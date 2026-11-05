#pragma once

#include "nativecommit.h"
#include <QElapsedTimer>
#include <QFile>
#include <QStorageInfo>
#include <QTemporaryFile>
#include <atomic>
#include <list>
#include <memory>

namespace dukto {
enum class ConflictPolicy { Rename, Fail, Overwrite, Skip };
// 日期：2026-11-05；仅接受已实现的策略，未知值和未完成策略不能静默回退。
ConflictPolicy checkedConflictPolicy(const QString &value);
// 日期：2026-11-05；内部枚举转公开名称，非法枚举同样拒绝。
QString conflictPolicyName(ConflictPolicy policy);
constexpr qint64 BufferSize = 256 * 1024;
constexpr qint64 MaxMetadataBytes = 256LL * 1024 * 1024;
constexpr qint64 MaxPathBytes = 4096;
constexpr qint64 MaxTextBytes = 8 * 1024 * 1024;

// 日期：2026-11-04；统一识别 POSIX 符号链接与 Windows 全部重解析点，不跟随 junction 扫描。
bool isLinkedPath(const QString &path);

// 日期：2026-11-04；验证相对路径，拒绝穿越、绝对路径及跨平台非法名称。
QString validateRelativePath(const QString &relative);
// 日期：2026-11-04；在共享根内解析路径并拒绝经过符号链接或重解析点。
QString resolveInside(const QString &root, const QString &relative, bool allowMissing = true);
// 日期：2026-11-04；流式计算文件摘要，取消与 I/O 失败使用统一错误。
QByteArray hashFile(const QString &path, const std::atomic_bool *cancel = nullptr);
// 日期：2026-11-04；完整写入数据并检测短写，不能把磁盘满报告为成功。
void writeAll(QIODevice &device, const QByteArray &bytes);
// 日期：2026-11-04；预检目标盘可用空间和已知 FAT 单文件限制，写入期间仍须处理真实 I/O 失败。
void checkStorageSpace(const QString &directory, qint64 bytes, bool singleFile = false);
class StorageChecks final {
  public:
    // 日期：2026-11-04；每任务最多缓存 16 个目录，磁盘信息至多复用一秒，避免小文件系统查询风暴。
    StorageChecks();
    // 日期：2026-11-04；按批次剩余量/单文件大小预检，命中缓存仍执行容量与文件系统规则。
    void check(const QString &directory, qint64 bytes, bool singleFile = false);
    // 日期：2026-11-04；成功写入后扣除同一卷缓存的可用量，刷新前也不能重复使用本任务空间。
    void consumed(const QString &directory, qint64 bytes);

  private:
    struct Probe {
        QString path;
        QStorageInfo storage;
        QByteArray volume;
        QByteArray format;
        bool ready = false;
        bool readOnly = false;
        qint64 refreshed = 0;
        qint64 available = -1;
    };
    // 日期：2026-11-05；macOS 直接查询目标路径所在 APFS 卷，其他平台保留 Qt 磁盘接口。
    void refresh(Probe &probe, qint64 now);
    QElapsedTimer clock_;
    std::list<Probe> probes_;
};
// 日期：2026-11-04；为同名文件构造保留扩展名的候选名称。
QString renamedPath(const QString &path, int index);

class IncomingFile final {
  public:
    // 日期：2026-11-04；在最终目录内创建自动清理的临时文件，不触碰原文件。
    explicit IncomingFile(const QString &destination);
    // 日期：2026-11-04；释放文件后按固定目录句柄清理 POSIX 未提交项，Windows 由 Qt 自动清理。
    ~IncomingFile();
    // 日期：2026-11-04；返回受当前任务独占的临时文件。
    QFile &device();
    // 日期：2026-11-04；关闭原生句柄后独占命名，处理并发同名竞争，禁止复制回退。
    QString commit();

  private:
    QString destination_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> directoryLock_;
    std::unique_ptr<QTemporaryFile> temporary_;
#else
    std::unique_ptr<PosixDirectory> directoryLock_;
    QString temporaryName_;
    std::unique_ptr<QFile> temporary_;
#endif
};
} // namespace dukto

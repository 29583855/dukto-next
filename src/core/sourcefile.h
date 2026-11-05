#pragma once

#include "nativecommit.h"
#include <QFile>
#include <memory>

namespace dukto {
class SourceFile final {
  public:
    // 日期：2026-11-04；固定父目录并原生打开普通文件；后续读操作不再解析绝对路径。
    explicit SourceFile(const QString &path);
    // 日期：2026-11-04；先关闭文件再释放目录句柄，异常退出同样归还所有原生资源。
    ~SourceFile();
    SourceFile(const SourceFile &) = delete;
    SourceFile &operator=(const SourceFile &) = delete;
    // 日期：2026-11-04；返回当前线程独占的只读文件，支持有界读取和分块定位。
    QFile &device();
    // 日期：2026-11-04；核对打开对象的身份、大小、原生修改时间及 POSIX 路径身份。
    void verify() const;
    // 日期：2026-11-05；仅供共享可变状态库核验原生对象；传输源应使用严格verify。
    void verifyObject() const;

  private:
    // 日期：2026-11-05；普通文件和路径身份始终验证，内容元数据只在严格源读取时要求稳定。
    void verifyIdentity(bool contents) const;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> parent_;
#else
    std::unique_ptr<PosixDirectory> parent_;
    QString name_;
#endif
    QFile file_;
    QByteArray identity_;
    QByteArray objectIdentity_;
};
} // namespace dukto

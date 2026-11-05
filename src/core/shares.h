#pragma once

#include "auth.h"
#include <memory>

namespace dukto {
enum class Access { Browse, Download, Upload };
struct Share {
    Grant permissions;
    QString root;
};

class SharedRoot final {
  public:
    // 日期：2026-11-04；授权通过后固定共享根的原生目录身份，不能沿链接访问其他目录。
    explicit SharedRoot(Share share);
    // 日期：2026-11-04；释放本操作固定的共享根句柄，不隐式创建或删除用户目录。
    ~SharedRoot();
    // 日期：2026-11-04；空路径仅表示共享根；其他值必须经过统一相对路径边界检查。
    QString resolve(const QString &relative, bool allowMissing = false) const;
    // 日期：2026-11-04；POSIX 重新核对根 inode，发布浏览/源内容前须调用。
    void verify() const;
    // 日期：2026-11-04；只返回固定的共享名称与路径值，不能当作绕过授权的全局配置缓存。
    Share share() const;

  private:
    Share share_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> lock_;
#else
    std::unique_ptr<PosixDirectory> lock_;
#endif
};

class Shares final {
  public:
    // 日期：2026-11-04；共享配置与身份共用受保护根，每次操作重新读取，不永久缓存旧授权。
    explicit Shares(PrivateStore &store);
    // 日期：2026-11-04；本地管理接口配置最多 16 个明确根与权限，拒绝分享私有凭据根或其祖先。
    void set(const Share &share);
    // 日期：2026-11-04；删除共享后新操作立即拒绝，即使客户端仍有旧授权记录。
    void remove(const QString &name);
    // 日期：2026-11-04；本地管理查询返回有上限的全部配置，不发送本机根路径给远程客户端。
    QList<Share> all() const;
    // 日期：2026-11-04；服务颁发配对权限不能超出已配置共享权限。
    void validate(const QList<Grant> &grants) const;
    // 日期：2026-11-04；交集检查主体与当前共享权限，返回之前已固定根目录的操作上下文。
    std::unique_ptr<SharedRoot> open(const Principal &principal, const QString &name,
                                     Access access) const;

  private:
    // 日期：2026-11-04；原子保存规范配置，根路径只保存在服务端受保护文件。
    void save(const QList<Share> &shares);
    PrivateStore &store_;
};
} // namespace dukto

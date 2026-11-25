#include "shares.h"
#include "error.h"
#include "files.h"
#include "protocol.h"

#include <QDir>
#include <QFileInfo>
#include <QLockFile>

namespace dukto {
namespace {
// 日期：2026-11-04；所有权限分别检查；可浏览/下载不能隐式获得写入权限。
bool permitted(const Grant &grant, Access access) {
    switch (access) {
    case Access::Browse:
        return grant.browse;
    case Access::Download:
        return grant.download;
    case Access::Upload:
        return grant.upload;
    }
    return false;
}
} // namespace

// 日期：2026-11-04；构造时不先 canonicalize，确保链接或 junction 根本身也会被拒绝。
SharedRoot::SharedRoot(Share share) : share_(std::move(share)) {
#ifdef Q_OS_WIN
    lock_.reset(new NativeDirectoryLock(share_.root, false));
#else
    lock_.reset(new PosixDirectory(share_.root, false));
#endif
}

// 日期：2026-11-04；目录句柄只在当前操作/任务存活期间保留，避免常驻句柄随文件数量增长。
SharedRoot::~SharedRoot() = default;

// 日期：2026-11-04；目录浏览和下载解析遵循与上传相同的共享根边界，不接收原生绝对路径。
QString SharedRoot::resolve(const QString &relative, bool allowMissing) const {
    verify();
    return relative.isEmpty() ? share_.root : resolveInside(share_.root, relative, allowMissing);
}

// 日期：2026-11-04；Windows 固定目录不共享删除；POSIX 需要显式重新核对已持有身份。
void SharedRoot::verify() const {
#ifndef Q_OS_WIN
    lock_->verify();
#endif
}

// 日期：2026-11-04；返回值不拥有授权，后续调用仍需持有 SharedRoot 并重新验证主体权限。
Share SharedRoot::share() const {
    return share_;
}

// 日期：2026-11-04；配置读取和写入都经过同一个 PrivateStore 的原生权限边界。
Shares::Shares(PrivateStore &store) : store_(store) {
}

// 日期：2026-11-04；无配置时表示没有开放共享，文件损坏则明确报错，不能回退开放整个目录。
QList<Share> Shares::all() const {
    if (!store_.exists("shares.json"))
        return {};
    const auto object = next::parseControl(store_.read("shares.json"));
    if (object["version"] != 1 || !object["shares"].isArray())
        throw Error(ExitCode::Config, QStringLiteral("共享配置格式无效"), "shares");
    const auto array = object["shares"].toArray();
    if (array.size() > 16)
        throw Error(ExitCode::Config, QStringLiteral("共享配置数量超过上限"), "shares");
    QList<Share> result;
    QList<Grant> grants;
    for (const auto &value : array) {
        if (!value.isObject())
            throw Error(ExitCode::Config, QStringLiteral("共享配置条目无效"), "shares");
        const auto entry = value.toObject();
        if (entry.size() != 2 || !entry["root"].isString() || !entry["permissions"].isObject() ||
            !QDir::isAbsolutePath(entry["root"].toString()))
            throw Error(ExitCode::Config, QStringLiteral("共享根配置无效"), "shares");
        const auto grant = decodeGrants({entry["permissions"]}).first();
        grants.append(grant);
        result.append({grant, entry["root"].toString()});
    }
    if (!grants.isEmpty())
        encodeGrants(grants);
    return result;
}

// 日期：2026-11-04；空列表也可持久化，表示本地管理员显式关闭所有共享。
void Shares::save(const QList<Share> &shares) {
    QJsonArray array;
    for (const auto &share : shares)
        array.append(QJsonObject{{"root", share.root},
                                 {"permissions", encodeGrants({share.permissions})[0]}});
    store_.write("shares.json", next::encodeControl({{"version", 1}, {"shares", array}}));
}

// 日期：2026-11-04；管理员配置更改串行落盘，子目录链接由实际操作时逐层再核对。
void Shares::set(const Share &share) {
    encodeGrants({share.permissions});
    const auto absolute = QDir::cleanPath(QFileInfo(share.root).absoluteFilePath());
    SharedRoot held({share.permissions, absolute});
    const auto canonical = QFileInfo(absolute).canonicalFilePath();
    const auto privatePath = QFileInfo(store_.directory()).canonicalFilePath();
#ifdef Q_OS_WIN
    const auto sensitivity = Qt::CaseInsensitive;
#else
    const auto sensitivity = Qt::CaseSensitive;
#endif
    if (canonical.isEmpty() || canonical.compare(privatePath, sensitivity) == 0 ||
        privatePath.startsWith(canonical.endsWith('/') ? canonical : canonical + '/', sensitivity))
        throw Error(ExitCode::Permission, QStringLiteral("共享范围包含服务私有凭据目录，拒绝开放"),
                    "shares");
    QLockFile lock(store_.directory() + "/shares.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("共享配置正在修改，请重试"), "shares");
    auto shares = all();
    bool replaced = false;
    for (auto &item : shares)
        if (item.permissions.share == share.permissions.share) {
            item = {share.permissions, absolute};
            replaced = true;
        }
    if (!replaced) {
        if (shares.size() == 16)
            throw Error(ExitCode::Config, QStringLiteral("共享数量已达 16 个上限"), "shares");
        shares.append({share.permissions, absolute});
    }
    held.verify();
    save(shares);
}

// 日期：2026-11-04；删除不存在名称也明确失败，避免管理员误以为拼错的名称已撤销。
void Shares::remove(const QString &name) {
    validateShareName(name);
    QLockFile lock(store_.directory() + "/shares.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("共享配置正在修改，请重试"), "shares");
    auto shares = all();
    bool removed = false;
    for (auto iterator = shares.begin(); iterator != shares.end(); ++iterator)
        if (iterator->permissions.share == name) {
            shares.erase(iterator);
            removed = true;
            break;
        }
    if (!removed)
        throw Error(ExitCode::Config, QStringLiteral("共享名称不存在"), "shares");
    save(shares);
}

// 日期：2026-11-04；颁发和每次操作都取权限交集，删除/缩减共享不依赖客户端主动刷新。
void Shares::validate(const QList<Grant> &grants) const {
    encodeGrants(grants);
    const auto shares = all();
    for (const auto &grant : grants) {
        bool found = false;
        for (const auto &share : shares)
            if (share.permissions.share == grant.share) {
                found = true;
                if ((grant.browse && !share.permissions.browse) ||
                    (grant.download && !share.permissions.download) ||
                    (grant.upload && !share.permissions.upload))
                    throw Error(ExitCode::Permission, QStringLiteral("配对权限超出当前共享设置"),
                                "shares");
            }
        if (!found)
            throw Error(ExitCode::Permission, QStringLiteral("配对指定了未开放的共享"), "shares");
    }
}

// 日期：2026-11-04；只返回本次操作有权使用的固定根，错误不泄露服务端本地绝对路径。
std::unique_ptr<SharedRoot> Shares::open(const Principal &principal, const QString &name,
                                         Access access) const {
    validateShareName(name);
    bool allowed = false;
    for (const auto &grant : principal.grants)
        if (grant.share == name && permitted(grant, access))
            allowed = true;
    if (allowed)
        for (const auto &share : all())
            if (share.permissions.share == name && permitted(share.permissions, access))
                return std::unique_ptr<SharedRoot>(new SharedRoot(share));
    throw Error(ExitCode::Permission, QStringLiteral("共享或操作未获授权"), "shares");
}
} // namespace dukto

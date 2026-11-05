#include "files.h"
#include "error.h"
#include "nativecommit.h"
#include "sourcefile.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QStorageInfo>
#include <algorithm>
#include <limits>
#ifdef Q_OS_MACOS
#include <sys/mount.h>
#endif
#ifndef Q_OS_WIN
#include <unistd.h>
#endif

namespace dukto {
// 日期：2026-11-05；已开放的保留双方、失败与覆盖共用严格解码，其他策略返回参数错误。
ConflictPolicy checkedConflictPolicy(const QString &value) {
    if (value == "rename")
        return ConflictPolicy::Rename;
    if (value == "fail")
        return ConflictPolicy::Fail;
    if (value == "overwrite")
        return ConflictPolicy::Overwrite;
    throw Error(ExitCode::Config, QStringLiteral("冲突策略当前支持 rename、fail 或 overwrite"),
                "arguments");
}

// 日期：2026-11-05；任务摘要、接收日志和 CLI 使用同一规范名称，非法枚举不能进入持久状态。
QString conflictPolicyName(ConflictPolicy policy) {
    switch (policy) {
    case ConflictPolicy::Rename:
        return "rename";
    case ConflictPolicy::Fail:
        return "fail";
    case ConflictPolicy::Overwrite:
        return "overwrite";
    case ConflictPolicy::Skip:
        return "skip";
    }
    throw Error(ExitCode::Config, QStringLiteral("冲突策略枚举无效"), "arguments");
}

// 日期：2026-11-04；Qt 符号链接判断与 Windows 原生重解析点属性共同执行默认不跟随策略。
bool isLinkedPath(const QString &path) {
    return QFileInfo(path).isSymLink()
#ifdef Q_OS_WIN
           || isNativeReparsePoint(path)
#endif
        ;
}

// 日期：2026-11-04；网络路径采用 UTF-8 与斜杠，平台差异不能导致目录逃逸。
QString validateRelativePath(const QString &relative) {
    if (relative.isEmpty() || relative.toUtf8().size() > MaxPathBytes ||
        relative.contains(QChar::Null) || relative.contains('\\') || QDir::isAbsolutePath(relative))
        throw Error(ExitCode::Permission, QStringLiteral("无效或过长的相对路径"), "path");
    const auto parts = relative.split('/');
    static const QRegularExpression reserved("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\..*)?$",
                                             QRegularExpression::CaseInsensitiveOption);
    for (const auto &part : parts) {
        if (part.isEmpty() || part == "." || part == ".." || part.endsWith('.') ||
            part.endsWith(' ') || reserved.match(part).hasMatch())
            throw Error(ExitCode::Permission, QStringLiteral("路径包含不安全的名称"), "path");
        for (int index = 0; index < part.size(); ++index) {
            const QChar c = part[index];
            if (c.unicode() < 32 || QStringLiteral(":*?\"<>|").contains(c))
                throw Error(ExitCode::Permission, QStringLiteral("路径含跨平台非法字符"), "path");
            // 日期：2026-11-04；拒绝未配对 UTF-16 代理项，避免路径和强身份在 UTF-8 转换时被替换。
            if (c.isHighSurrogate()) {
                if (index + 1 >= part.size() || !part[index + 1].isLowSurrogate())
                    throw Error(ExitCode::Permission, QStringLiteral("路径含无效 Unicode"), "path");
                ++index;
            } else if (c.isLowSurrogate()) {
                throw Error(ExitCode::Permission, QStringLiteral("路径含无效 Unicode"), "path");
            }
        }
    }
    return relative;
}

// 日期：2026-11-04；逐层检查已存在的父目录，避免远程文件越过授权根。
QString resolveInside(const QString &root, const QString &relative, bool allowMissing) {
    validateRelativePath(relative);
    QFileInfo rootInfo(root);
    const QString canonicalRoot = rootInfo.canonicalFilePath();
    if (!rootInfo.isDir() || canonicalRoot.isEmpty())
        throw Error(ExitCode::Disk, QStringLiteral("接收或共享根目录不存在"), "path");
    QString cursor = canonicalRoot;
    for (const auto &part : relative.split('/')) {
        cursor = QDir(cursor).filePath(part);
        const QFileInfo info(cursor);
        if (isLinkedPath(cursor))
            throw Error(ExitCode::Permission, QStringLiteral("路径经过符号链接"), "path");
        if (!info.exists()) {
            if (!allowMissing)
                throw Error(ExitCode::Disk, QStringLiteral("源路径不存在"), "path");
            continue;
        }
        const auto canonical = info.canonicalFilePath();
#ifdef Q_OS_WIN
        const auto sensitivity = Qt::CaseInsensitive;
#else
        const auto sensitivity = Qt::CaseSensitive;
#endif
        if (!canonical.startsWith(canonicalRoot + '/', sensitivity))
            throw Error(ExitCode::Permission, QStringLiteral("路径超出授权目录"), "path");
    }
    return cursor;
}

// 日期：2026-11-04；摘要内存与文件大小无关，每次仅读取固定大小片段。
QByteArray hashFile(const QString &path, const std::atomic_bool *cancel) {
    SourceFile source(path);
    auto &file = source.device();
    QCryptographicHash hash(QCryptographicHash::Sha256);
    while (!file.atEnd()) {
        if (cancel && cancel->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("已取消校验"), "hash");
        const auto data = file.read(BufferSize);
        if (data.isEmpty() && file.error() != QFileDevice::NoError)
            throw Error(ExitCode::Disk, file.errorString(), "hash");
        hash.addData(data);
    }
    source.verify();
    return hash.result();
}

// 日期：2026-11-04；检查每次写入的实际字节数，失败立即中止。
void writeAll(QIODevice &device, const QByteArray &bytes) {
    qint64 offset = 0;
    while (offset < bytes.size()) {
        const auto n = device.write(bytes.constData() + offset, bytes.size() - offset);
        if (n <= 0)
            throw Error(ExitCode::Disk, device.errorString(), "write");
        offset += n;
    }
}

// 日期：2026-11-04；按声明的完整未压缩字节估算；预检不预约空间，也不取代中途磁盘满处理。
void checkStorageSpace(const QString &directory, qint64 bytes, bool singleFile) {
    StorageChecks checks;
    checks.check(directory, bytes, singleFile);
}

// 日期：2026-11-04；缓存只属于一个传输线程/任务，不跨任务保留过期的盘符状态。
StorageChecks::StorageChecks() {
    clock_.start();
}

// 日期：2026-11-05；APFS 的 Data 卷可通过 firmlink 访问，Qt5 挂载前缀匹配可能误选只读系统卷。
void StorageChecks::refresh(Probe &probe, qint64 now) {
    probe.ready = false;
#ifdef Q_OS_MACOS
    struct statfs information;
    const auto native = QFile::encodeName(probe.path);
    if (::statfs(native.constData(), &information) != 0 || information.f_bsize == 0)
        throw Error(ExitCode::Disk, QStringLiteral("无法取得接收盘原生空间信息"), "space");
    const auto blocks = static_cast<quint64>(information.f_bavail);
    const auto size = static_cast<quint64>(information.f_bsize);
    const auto maximum = std::numeric_limits<qint64>::max();
    probe.available = blocks > static_cast<quint64>(maximum) / size
                          ? maximum
                          : static_cast<qint64>(blocks * size);
    probe.volume = QByteArray::number(information.f_fsid.val[0]) + ':' +
                   QByteArray::number(information.f_fsid.val[1]);
    probe.format = QByteArray(information.f_fstypename).toLower();
    probe.readOnly = (information.f_flags & MNT_RDONLY) != 0;
    probe.ready = true;
#else
    probe.storage.setPath(probe.path);
    probe.storage.refresh();
    probe.available = probe.storage.bytesAvailable();
    probe.volume = probe.storage.device() + '\0' + probe.storage.rootPath().toUtf8();
    probe.format = probe.storage.fileSystemType().toLower();
    probe.readOnly = probe.storage.isReadOnly();
    probe.ready = probe.storage.isValid() && probe.storage.isReady() && probe.available >= 0;
#endif
    probe.refreshed = now;
}

// 日期：2026-11-05；新目录首次查盘；缓存目录每秒刷新，写入失败仍由实际 I/O 路径处理。
void StorageChecks::check(const QString &directory, qint64 bytes, bool singleFile) {
    if (bytes < 0)
        throw Error(ExitCode::Config, QStringLiteral("磁盘空间估算长度无效"), "space");
    const auto path = QDir::cleanPath(QFileInfo(directory).absoluteFilePath());
    auto found = std::find_if(probes_.begin(), probes_.end(),
                              [&path](const Probe &probe) { return probe.path == path; });
    const auto now = clock_.elapsed();
    if (found == probes_.end()) {
        if (probes_.size() == 16)
            probes_.pop_back();
        Probe probe;
        probe.path = path;
        refresh(probe, now);
        probes_.push_front(std::move(probe));
    } else {
        probes_.splice(probes_.begin(), probes_, found);
        if (now - probes_.front().refreshed >= 1000) {
            refresh(probes_.front(), now);
        }
    }
    const auto &probe = probes_.front();
    if (!probe.ready)
        throw Error(ExitCode::Disk, QStringLiteral("无法取得接收盘可用空间"), "space");
    if (probe.readOnly)
        throw Error(ExitCode::Disk, QStringLiteral("接收文件系统为只读"), "space");
    const auto &format = probe.format;
    if (singleFile && bytes > 4294967295LL &&
        (format == "fat32" || format == "vfat" || format == "msdos" || format == "fat"))
        throw Error(ExitCode::Disk,
                    QStringLiteral("接收文件系统为 FAT，单文件大小不能超过 4 GiB 减 1 字节"),
                    "space");
    if (bytes > probe.available)
        throw Error(ExitCode::Disk,
                    QStringLiteral("接收盘可用空间不足：需要 %1 字节，可用 %2 字节")
                        .arg(bytes)
                        .arg(probe.available),
                    "space");
}

// 日期：2026-11-04；只扣同设备/挂载根，不能把其他卷的数据量错误算到当前磁盘。
void StorageChecks::consumed(const QString &directory, qint64 bytes) {
    if (bytes < 0)
        throw Error(ExitCode::Config, QStringLiteral("磁盘写入计量无效"), "space");
    const auto path = QDir::cleanPath(QFileInfo(directory).absoluteFilePath());
    const auto found = std::find_if(probes_.begin(), probes_.end(),
                                    [&path](const Probe &probe) { return probe.path == path; });
    if (found == probes_.end())
        throw Error(ExitCode::Config, QStringLiteral("写入前缺少磁盘预检"), "space");
    for (auto &probe : probes_)
        if (probe.volume == found->volume)
            probe.available = bytes >= probe.available ? 0 : probe.available - bytes;
}

// 日期：2026-11-04；第一个候选保持原名，后续使用数字后缀。
QString renamedPath(const QString &path, int index) {
    if (index == 0)
        return path;
    const QFileInfo info(path);
    const auto suffix = info.completeSuffix();
    const auto filename = info.completeBaseName() + QString(" (%1)").arg(index + 1) +
                          (suffix.isEmpty() ? QString() : '.' + suffix);
    return info.dir().filePath(filename);
}

// 日期：2026-11-04；临时文件与目标位于同一文件系统，析构自动清理未提交数据。
IncomingFile::IncomingFile(const QString &destination) : destination_(destination) {
    const auto parent = QFileInfo(destination).absolutePath();
#ifdef Q_OS_WIN
    directoryLock_.reset(new NativeDirectoryLock(parent, true));
    temporary_.reset(new QTemporaryFile(QDir(parent).filePath(".dukto-XXXXXX.part")));
    if (!temporary_->open())
        throw Error(ExitCode::Disk, temporary_->errorString(), "write");
    // 日期：2026-11-04；显式取得临时名称，供中断记录、最终命名与清理识别。
    if (temporary_->fileName().isEmpty())
        throw Error(ExitCode::Disk, QStringLiteral("无法为接收临时文件建立目录项"), "write");
#else
    directoryLock_.reset(new PosixDirectory(parent, true));
    temporary_.reset(new QFile);
    const int descriptor = directoryLock_->createTemporary(temporaryName_);
    if (!temporary_->open(descriptor, QIODevice::WriteOnly, QFileDevice::AutoCloseHandle)) {
        ::close(descriptor);
        directoryLock_->removeTemporary(temporaryName_);
        throw Error(ExitCode::Disk, temporary_->errorString(), "write");
    }
#endif
}

// 日期：2026-11-04；POSIX 清理只引用原目录句柄，外部替换父目录后也不会删除另一个目录的文件。
IncomingFile::~IncomingFile() {
#ifndef Q_OS_WIN
    temporary_.reset();
    directoryLock_->removeTemporary(temporaryName_);
#endif
}

// 日期：2026-11-04；所有读写只允许在创建任务的工作线程执行。
QFile &IncomingFile::device() {
    if (!temporary_)
        throw Error(ExitCode::Config, QStringLiteral("接收临时文件已提交或关闭"), "write");
    return *temporary_;
}

// 日期：2026-11-04；先释放 Qt 保留的临时句柄，再原生独占命名，失败时清理且绝不复制回退。
QString IncomingFile::commit() {
    if (!temporary_)
        throw Error(ExitCode::Config, QStringLiteral("接收临时文件已提交或关闭"), "commit");
    if (!temporary_->flush())
        throw Error(ExitCode::Disk, temporary_->errorString(), "commit");
#ifdef Q_OS_WIN
    struct TemporaryGuard {
        QString path;
        // 日期：2026-11-04；原生提交失败也只删除本次临时文件，不触碰任何候选目标。
        ~TemporaryGuard() {
            if (!path.isEmpty())
                QFile::remove(path);
        }
    } guard{temporary_->fileName()};
    temporary_->setAutoRemove(false);
    temporary_.reset();
#else
    temporary_.reset();
#endif
    for (int index = 0; index < 100000; ++index) {
        const QString target = renamedPath(destination_, index);
        TargetReservation reservation(target);
        if (!reservation.acquired())
            continue;
#ifdef Q_OS_WIN
        if (renameNoReplace(guard.path, target)) {
            guard.path.clear();
#else
        if (directoryLock_->commitTemporary(temporaryName_, QFileInfo(target).fileName())) {
            temporaryName_.clear();
#endif
            return target;
        }
    }
    throw Error(ExitCode::Disk, QStringLiteral("同名文件数量超过限制"), "commit");
}
} // namespace dukto

#include "importstore.h"

#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QStorageInfo>
#include <algorithm>

// 日期：2026-11-25；导入根必须已由应用创建，拒绝符号链接及无效预算。
ImportStore::ImportStore(const QString &root, Limits limits) : limits_(limits) {
    const QFileInfo info(root);
    if (!info.isDir() || info.isSymLink() || limits.bytes < 0 || limits.reserve < 0 ||
        limits.entries < 1 || limits.depth < 1) {
        fail(QStringLiteral("导入根目录或预算无效"));
        return;
    }
    // 日期：2026-11-25；锁覆盖整次事务，既有暂存计入总配额，重启不能绕过磁盘预算。
    const auto lockPath = QDir(root).filePath(QStringLiteral(".import-budget.lock"));
    budgetLock_.reset(new QLockFile(lockPath));
    if (!budgetLock_->tryLock(0)) {
        fail(QStringLiteral("另一个导入或清理正在运行，请稍后重试"));
        return;
    }
    qint64 used = 0;
    int count = 0;
    QDirIterator retained(root, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden,
                          QDirIterator::Subdirectories);
    while (retained.hasNext()) {
        retained.next();
        const auto entry = retained.fileInfo();
        if (entry.absoluteFilePath() == lockPath)
            continue;
        if (++count > 65536 || entry.isSymLink() || (!entry.isDir() && !entry.isFile())) {
            fail(QStringLiteral("暂存条目超限或类型无效，请管理导入暂存"));
            return;
        }
        if (entry.isFile()) {
            if (entry.size() > limits_.bytes - used) {
                fail(QStringLiteral("已有暂存已占满导入总预算，请先清理不再需要的暂存"));
                return;
            }
            used += entry.size();
        }
    }
    limits_.bytes -= used;
    temporary_.reset(new QTemporaryDir(QDir(root).filePath(QStringLiteral("import-XXXXXX"))));
    if (!temporary_->isValid())
        fail(QStringLiteral("无法创建导入暂存目录"));
}

// 日期：2026-11-25；禁止覆盖同名条目，大小写折叠使导入结果可在不同桌面文件系统互通。
bool ImportStore::validate(const QString &relative) {
    if (!error_.isEmpty() || committed_)
        return false;
    if (relative.isEmpty() || relative.size() > 1024 || QDir::isAbsolutePath(relative) ||
        relative.contains('\\'))
        return fail(QStringLiteral("不安全的导入路径"));
    const auto parts = relative.split('/');
    if (parts.size() > limits_.depth)
        return fail(QStringLiteral("目录层级超过导入限制"));
    for (const auto &part : parts) {
        if (part.isEmpty() || part == "." || part == ".." || part.size() > 240 ||
            part.endsWith('.') || part.endsWith(' '))
            return fail(QStringLiteral("文件名或目录名不受支持"));
        for (const auto character : part) {
            if (character.unicode() < 32 || QStringLiteral(":*?\"<>|").contains(character))
                return fail(QStringLiteral("文件名含控制字符或跨平台非法字符"));
        }
        const auto base = part.section('.', 0, 0).toUpper();
        if (base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" ||
            (base.size() == 4 && (base.startsWith("COM") || base.startsWith("LPT")) &&
             base.at(3) >= QChar('1') && base.at(3) <= QChar('9')))
            return fail(QStringLiteral("文件名是Windows保留名称"));
    }
    const auto key = relative.normalized(QString::NormalizationForm_C).toCaseFolded();
    if (entries_.contains(key))
        return fail(QStringLiteral("导入名称重复或大小写冲突"));
    if (entries_.size() >= limits_.entries)
        return fail(QStringLiteral("导入条目超过限制"));
    entries_.insert(key);
    return true;
}

// 日期：2026-11-25；父目录须由同一事务先创建，不遍历文档提供器的任意路径。
bool ImportStore::directory(const QString &relative) {
    if (!validate(relative))
        return false;
    if (!QDir(temporary_->path()).mkdir(relative))
        return fail(QStringLiteral("无法创建导入子目录，请检查目录顺序"));
    return true;
}

// 日期：2026-11-25；每次只分配64KiB，并在读写边界检查取消和剩余配额。
bool ImportStore::copy(QIODevice &source, const QString &relative, qint64 expected,
                       const std::function<bool()> &cancelled) {
    if (!validate(relative))
        return false;
    if (!source.isOpen() || !source.isReadable() || expected < -1 ||
        (expected >= 0 && expected > limits_.bytes - bytes_))
        return fail(QStringLiteral("文件不可读或超过导入容量"));
    QFile output(QDir(temporary_->path()).filePath(relative));
    if (!output.open(QIODevice::WriteOnly | QIODevice::NewOnly))
        return fail(QStringLiteral("无法创建导入文件"));
    if (!output.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner))
        return fail(QStringLiteral("无法设置导入文件私有权限"));
    char buffer[64 * 1024];
    qint64 copied = 0;
    while (true) {
        if (cancelled && cancelled())
            return fail(QStringLiteral("已取消导入"));
        const auto count = source.read(buffer, sizeof(buffer));
        if (count < 0)
            return fail(QStringLiteral("读取文档提供器失败：") + source.errorString());
        if (count == 0) {
            if (!source.atEnd())
                return fail(QStringLiteral("提供器暂未返回数据，请下载文件后重试"));
            break;
        }
        if (count > limits_.bytes - bytes_ || (expected >= 0 && count > expected - copied))
            return fail(QStringLiteral("文件内容超出声明长度或导入容量"));
        QStorageInfo storage(temporary_->path());
        if (!storage.isValid() || !storage.isReady() ||
            storage.bytesAvailable() < limits_.reserve ||
            count > storage.bytesAvailable() - limits_.reserve)
            return fail(QStringLiteral("沙箱剩余空间不足"));
        if (output.write(buffer, count) != count)
            return fail(QStringLiteral("写入导入文件失败：") + output.errorString());
        bytes_ += count;
        copied += count;
    }
    if (expected >= 0 && copied != expected)
        return fail(QStringLiteral("提供器文件长度已变化，请重新选择"));
    if (!output.flush())
        return fail(QStringLiteral("无法完成导入文件写入"));
    output.close();
    return true;
}

// 日期：2026-11-25；有错或空事务均不交给发送核心，未提交的暂存由RAII清理。
QString ImportStore::commit() {
    if (!error_.isEmpty() || !temporary_ || entries_.isEmpty() || committed_)
        return QString();
    committed_ = true;
    temporary_->setAutoRemove(false);
    budgetLock_.reset();
    return temporary_->path();
}

// 日期：2026-11-25；返回首错以免后续连带失败覆盖真正原因。
QString ImportStore::error() const {
    return error_;
}

// 日期：2026-11-25；只统计已经成功写入的字节。
qint64 ImportStore::bytes() const {
    return bytes_;
}

// 日期：2026-11-25；出错后所有新增操作均被拒绝。
bool ImportStore::fail(const QString &message) {
    if (error_.isEmpty())
        error_ = message;
    budgetLock_.reset();
    return false;
}

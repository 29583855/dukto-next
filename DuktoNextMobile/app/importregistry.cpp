#include "importregistry.h"

#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLockFile>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>

namespace {
// 日期：2026-11-25；记录不含凭据，只允许有限源列表及明确错误。
bool fail(QString &error, const QString &message) {
    error = message;
    return false;
}
} // namespace

// 日期：2026-11-25；保留规范根，原路径含链接时拒绝后续操作。
ImportRegistry::ImportRegistry(QString root) {
    const QFileInfo info(root);
    if (info.isDir() && !info.isSymLink()) {
        root_ = info.canonicalFilePath();
        inputRoot_ = info.absoluteFilePath();
    }
}

// 日期：2026-11-25；逐段检查，不能借目录链接将清理或续传导向认证目录。
QString ImportRegistry::batch(const QString &path, bool requireExists) const {
    if (root_.isEmpty() || !QDir::isAbsolutePath(path) || QDir::cleanPath(path) != path)
        return {};
    // 日期：2026-11-25；接受系统沙箱根的别名（例如iOS的/var），根以下仍逐段拒绝链接。
    auto normalized = path;
    if (normalized.startsWith(inputRoot_ + '/'))
        normalized = root_ + normalized.mid(inputRoot_.size());
    if (!normalized.startsWith(root_ + '/'))
        return {};
    const auto relative = normalized.mid(root_.size() + 1);
    const auto parts = relative.split('/');
    static const QRegularExpression pattern(QStringLiteral("\\Aimport-[A-Za-z0-9]{6}\\z"));
    if (parts.isEmpty() || !pattern.match(parts.first()).hasMatch())
        return {};
    QString current = root_;
    for (const auto &part : parts) {
        if (part.isEmpty() || part == "." || part == "..")
            return {};
        current += '/' + part;
        const QFileInfo info(current);
        if (info.isSymLink() || (info.exists() && !info.isFile() && !info.isDir()) ||
            (requireExists && !info.exists()))
            return {};
    }
    return parts.first();
}

// 日期：2026-11-25；有限读取阻止损坏引用导致内存无界增长，格式错误不能当作无引用。
bool ImportRegistry::read(const QString &path, QJsonObject &value, QString &error) const {
    const QFileInfo info(path);
    QFile file(path);
    if (!info.isFile() || info.isSymLink() || info.size() > 262144 ||
        !file.open(QIODevice::ReadOnly))
        return fail(error, QStringLiteral("上传引用文件无法安全读取"));
    QJsonParseError parse;
    const auto document = QJsonDocument::fromJson(file.readAll(), &parse);
    if (parse.error != QJsonParseError::NoError || !document.isObject())
        return fail(error, QStringLiteral("上传引用损坏，停止清理以保护原文件"));
    value = document.object();
    if (value.value("version").toInt() != 1 || !value.value("binding").isObject() ||
        !value.value("paths").isArray() || value.value("paths").toArray().isEmpty() ||
        value.value("paths").toArray().size() > 512)
        return fail(error, QStringLiteral("上传引用格式无效"));
    return true;
}

// 日期：2026-11-25；同一预算锁串行化导入、固定路径与清理，原子提交先于网络传输。
bool ImportRegistry::resolve(const QUuid &request, const QJsonObject &binding, QStringList &paths,
                             QString &error) const {
    if (root_.isEmpty() || request.isNull() || binding.isEmpty())
        return fail(error, QStringLiteral("上传暂存根或请求绑定无效"));
    QLockFile lock(QDir(root_).filePath(".import-budget.lock"));
    if (!lock.tryLock(0))
        return fail(error, QStringLiteral("导入暂存正在使用，请稍后重试"));
    const auto name = ".upload-" + request.toString(QUuid::WithoutBraces) + ".json";
    const auto path = QDir(root_).filePath(name);
    const QFileInfo info(path);
    if (info.exists() || info.isSymLink()) {
        QJsonObject record;
        if (!read(path, record, error))
            return false;
        if (record.value("binding").toObject() != binding)
            return fail(error, QStringLiteral("原请求的服务器、客户端或目标已改变"));
        QStringList original;
        for (const auto &entry : record.value("paths").toArray()) {
            const auto source = entry.toString();
            if (batch(source, true).isEmpty())
                return fail(error, QStringLiteral("原上传暂存缺失或不安全，不能以新文件替换"));
            original.append(source);
        }
        if (!paths.isEmpty() && paths != original)
            return fail(error, QStringLiteral("原请求必须使用原上传快照，请勿重新选择文件"));
        paths = original;
        return true;
    }
    if (paths.isEmpty() || paths.size() > 512)
        return fail(error, QStringLiteral("没有找到原上传暂存，请为新任务选择文件"));
    if (QDir(root_).entryList({".upload-*.json"}, QDir::Files | QDir::Hidden).size() >= 4096)
        return fail(error, QStringLiteral("保留上传请求已达上限"));
    QJsonArray sources;
    for (const auto &source : paths) {
        if (batch(source, true).isEmpty())
            return fail(error, QStringLiteral("上传源必须来自本应用系统选择器的导入快照"));
        sources.append(source);
    }
    QSaveFile output(path);
    if (!output.open(QIODevice::WriteOnly))
        return fail(error, QStringLiteral("无法保存上传引用"));
    output.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    const auto bytes =
        QJsonDocument(QJsonObject{{"version", 1}, {"binding", binding}, {"paths", sources}})
            .toJson(QJsonDocument::Compact);
    if (bytes.size() > 262144 || output.write(bytes) != bytes.size() || !output.commit())
        return fail(error, QStringLiteral("上传引用保存失败"));
    return true;
}

// 日期：2026-11-25；仅删除请求元数据，所有数据文件仍保持原位置。
bool ImportRegistry::release(const QUuid &request, QString &error) const {
    if (root_.isEmpty() || request.isNull())
        return fail(error, QStringLiteral("上传引用根或请求无效"));
    QLockFile lock(QDir(root_).filePath(".import-budget.lock"));
    if (!lock.tryLock(0))
        return fail(error, QStringLiteral("导入暂存正在使用"));
    const auto path =
        QDir(root_).filePath(".upload-" + request.toString(QUuid::WithoutBraces) + ".json");
    if (QFileInfo(path).isSymLink())
        return fail(error, QStringLiteral("拒绝删除链接引用"));
    return !QFileInfo::exists(path) || QFile::remove(path) ||
           fail(error, QStringLiteral("无法释放上传引用"));
}

// 日期：2026-11-25；启动快照只保存有限批次名称，不递归展开文件列表。
QStringList ImportRegistry::existingBatches() const {
    if (root_.isEmpty())
        return {};
    QStringList result;
    QDirIterator it(root_, {"import-*"}, QDir::Dirs | QDir::NoDotAndDotDot);
    while (it.hasNext() && result.size() < 65536) {
        const auto path = it.next();
        if (!batch(path, true).isEmpty())
            result.append(QFileInfo(path).fileName());
    }
    return result;
}

// 日期：2026-11-25；先完整验证引用，再删除未引用批次；符号链接或异常类型一律保留。
bool ImportRegistry::clean(const QStringList &eligible, int &removed, QString &error) const {
    removed = 0;
    if (root_.isEmpty())
        return fail(error, QStringLiteral("导入根无效"));
    QLockFile lock(QDir(root_).filePath(".import-budget.lock"));
    if (!lock.tryLock(0))
        return fail(error, QStringLiteral("导入暂存正在使用，请稍后清理"));
    QSet<QString> retained;
    QDirIterator refs(root_, {".upload-*.json"}, QDir::AllEntries | QDir::Hidden);
    int count = 0;
    while (refs.hasNext()) {
        if (++count > 4096)
            return fail(error, QStringLiteral("上传引用超限，停止清理"));
        QJsonObject value;
        if (!read(refs.next(), value, error))
            return false;
        for (const auto &entry : value.value("paths").toArray()) {
            const auto name = batch(entry.toString(), false);
            if (name.isEmpty())
                return fail(error, QStringLiteral("上传引用越界，停止清理"));
            retained.insert(name);
        }
    }
    for (const auto &name : eligible) {
        const auto path = QDir(root_).filePath(name);
        if (retained.contains(name) || batch(path, true) != name)
            continue;
        bool safe = true;
        int entries = 0;
        QDirIterator it(path, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden,
                        QDirIterator::Subdirectories);
        while (it.hasNext()) {
            it.next();
            const auto info = it.fileInfo();
            if (++entries > 65536 || info.isSymLink() || (!info.isFile() && !info.isDir())) {
                safe = false;
                break;
            }
        }
        if (safe && QFileInfo(path).canonicalFilePath() == path && QDir(path).removeRecursively())
            ++removed;
    }
    return true;
}

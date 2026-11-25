#include "mobilefiles.h"
#include "importregistry.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFileInfo>
#include <QMap>
#include <QPointer>
#include <QStandardPaths>
#include <QTimer>
#include <QUuid>
#include <iterator>
#include <memory>

MobileFiles *MobileFiles::instance_ = nullptr;

// 日期：2026-11-25；同一宿主只创建一个选择协调器，公开目录与私有配置隔离。
MobileFiles::MobileFiles(QObject *parent) : QObject(parent) {
    instance_ = this;
    imports_ = QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                   .filePath(QStringLiteral("imports"));
    if (QDir().mkpath(imports_))
        startupBatches_ = ImportRegistry(imports_).existingBatches();
#ifdef Q_OS_IOS
    documents_ = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
#else
    documents_ = QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                     .filePath(QStringLiteral("Documents"));
#endif
    connect(QCoreApplication::instance(), &QCoreApplication::aboutToQuit, this,
            &MobileFiles::cancelOperation);
    if (!QDir().mkpath(documents_))
        message_ = QStringLiteral("无法创建应用文件目录");
}

// 日期：2026-11-25；返回移动宿主所持有的唯一实例。
MobileFiles *MobileFiles::instance() {
    return instance_;
}

// 日期：2026-11-25；供QML禁用重复操作。
bool MobileFiles::busy() const {
    return busy_;
}

// 日期：2026-11-25；状态包含提供器返回的具体原因。
QString MobileFiles::message() const {
    return message_;
}

// 日期：2026-11-25；用户文件和下载统一位于可导出目录。
QString MobileFiles::documents() const {
    return documents_;
}

// 日期：2026-11-25；原生调用可能同步失败，用排队启动保证等待循环已准备。
QStringList MobileFiles::select(bool folder) {
    if (busy_) {
        message_ = QStringLiteral("请等待文件操作结束");
        emit changed();
        return {};
    }
    busy_ = true;
    message_ = QStringLiteral("请选择文档，选择后会复制到应用沙箱；请保持应用在前台");
    emit changed();
    QEventLoop loop;
    nativeWaiter_ = &loop;
    auto paths = std::make_shared<QStringList>();
    QPointer<QEventLoop> waiter(&loop);
    QPointer<MobileFiles> guard(this);
    QTimer::singleShot(0, this, [guard, folder, paths, waiter] {
        if (!guard || !waiter)
            return;
        mobile::selectDocuments(folder, [guard, paths, waiter](QStringList selected,
                                                               QString error) {
            if (!guard || !waiter)
                return;
            *paths = selected;
            guard->message_ = error.isEmpty() ? (paths->isEmpty() ? QStringLiteral("已取消选择")
                                                                  : QStringLiteral("文件导入完成"))
                                              : error;
            waiter->quit();
        });
    });
    loop.exec();
    nativeWaiter_ = nullptr;
    mobile::cancelDocumentPicker();
    busy_ = false;
    emit changed();
    return *paths;
}

// 日期：2026-11-25；多文件选择仅返回已完整暂存的本地路径。
QStringList MobileFiles::importFiles() {
    return select(false);
}

// 日期：2026-11-25；目录根必须唯一，子项枚举由平台适配器执行并受导入预算约束。
QString MobileFiles::importFolder() {
    const auto paths = select(true);
    return paths.size() == 1 ? paths.first() : QString();
}

// 日期：2026-11-25；配对与头像入口不隐式丢弃用户选中的其余文件。
QString MobileFiles::importSingle() {
    const auto paths = select(false);
    if (paths.size() > 1) {
        message_ = QStringLiteral("此操作只允许选择一个文件，请重新选择");
        emit changed();
    }
    return paths.size() == 1 ? paths.first() : QString();
}

// 日期：2026-11-25；规范路径比较阻止通过软链接或前缀相似目录访问私有文件。
bool MobileFiles::insideDocuments(const QString &path) const {
    const auto canonical = QFileInfo(path).canonicalFilePath();
    const auto root = QFileInfo(documents_).canonicalFilePath();
    return !canonical.isEmpty() && !root.isEmpty() &&
           (canonical == root || canonical.startsWith(root + '/'));
}

// 日期：2026-11-25；有界名称排序加游标覆盖全部条目，翻页不累计旧页面模型。
QVariantMap MobileFiles::entries(const QString &directory, const QString &after) const {
    QVariantList rows;
    if (!insideDocuments(directory))
        return {{"rows", rows}, {"next", QString()}};
    QMap<QString, QFileInfo> candidates;
    QDirIterator values(directory,
                        QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot | QDir::NoSymLinks);
    while (values.hasNext()) {
        values.next();
        const auto info = values.fileInfo();
        if (info.fileName() <= after)
            continue;
        candidates.insert(info.fileName(), info);
        if (candidates.size() > 513)
            candidates.erase(std::prev(candidates.end()));
    }
    const bool more = candidates.size() > 512;
    if (more)
        candidates.erase(std::prev(candidates.end()));
    for (const auto &info : candidates)
        rows.append(QVariantMap{{"name", info.fileName()},
                                {"path", info.absoluteFilePath()},
                                {"directory", info.isDir()}});
    return {{"rows", rows}, {"next", more ? candidates.lastKey() : QString()}};
}

// 日期：2026-11-25；目录对话框异步出现，仍与既有控制器的同步入口兼容。
QString MobileFiles::chooseDirectory(const QString &title) {
    if (busy_)
        return QString();
    busy_ = true;
    selectedDirectory_.clear();
    QEventLoop loop;
    directoryWaiter_ = &loop;
    QTimer::singleShot(0, this, [this, title] { emit directoryRequested(title); });
    emit changed();
    loop.exec();
    directoryWaiter_ = nullptr;
    busy_ = false;
    emit changed();
    return selectedDirectory_;
}

// 日期：2026-11-25；取消返回空路径，非法路径保留对话框等待用户重新选择。
void MobileFiles::finishDirectory(const QString &path) {
    if (!directoryWaiter_)
        return;
    if (!path.isEmpty() && (!insideDocuments(path) || !QFileInfo(path).isDir())) {
        message_ = QStringLiteral("请选择应用文件目录内的文件夹");
        emit changed();
        return;
    }
    selectedDirectory_ = path;
    directoryWaiter_->quit();
}

// 日期：2026-11-25；诊断目录单独保存，唯一文件名避免覆盖现有报告。
QString MobileFiles::diagnosticPath() const {
    const auto directory = QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                               .filePath(QStringLiteral("exports"));
    if (!QDir().mkpath(directory))
        return QString();
    return QDir(directory).filePath(QStringLiteral("Dukto-diagnostic-") +
                                    QUuid::createUuid().toString(QUuid::WithoutBraces) +
                                    QStringLiteral(".json"));
}

// 日期：2026-11-25；冲突条目明确失败，不覆盖用户已保存的文件。
void MobileFiles::importIntoDocuments(bool folder) {
    const auto paths = select(folder);
    int imported = 0;
    for (const auto &path : paths) {
        const auto target = QDir(documents_).filePath(QFileInfo(path).fileName());
        if (QFileInfo::exists(target) || !QDir().rename(path, target)) {
            message_ = QStringLiteral("导入到应用文件夹失败：同名文件已存在或无法移动；已完成%1项")
                           .arg(imported);
            emit changed();
            return;
        }
        ++imported;
    }
    if (imported)
        message_ = QStringLiteral("已导入%1项到应用文件目录").arg(imported);
    emit changed();
}

// 日期：2026-11-25；只导出用户文件或本地生成的诊断报告，不允许导出认证私钥。
void MobileFiles::exportPath(const QString &path) {
    if (busy_)
        return;
    const auto canonical = QFileInfo(path).canonicalFilePath();
    const auto exports =
        QFileInfo(QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                      .filePath(QStringLiteral("exports")))
            .canonicalFilePath();
    if (!insideDocuments(path) && (exports.isEmpty() || !canonical.startsWith(exports + '/'))) {
        message_ = QStringLiteral("仅支持导出已收文件和诊断报告");
        emit changed();
        return;
    }
    busy_ = true;
    emit changed();
    QPointer<MobileFiles> guard(this);
    mobile::exportDocument(path, [guard](QStringList paths, QString error) {
        if (!guard)
            return;
        guard->busy_ = false;
        guard->message_ = error.isEmpty() ? (paths.isEmpty() ? QStringLiteral("已取消导出")
                                                             : QStringLiteral("已完成系统导出"))
                                          : error;
        emit guard->changed();
    });
}

// 日期：2026-11-25；名称仅允许一个普通段，创建后还需位于用户文档目录。
bool MobileFiles::createDirectory(const QString &parent, const QString &name) {
    if (!insideDocuments(parent) || name.isEmpty() || name == "." || name == ".." ||
        name.contains('/') || name.contains('\\') || name.contains(':') || name.startsWith('.'))
        return false;
    return QDir(parent).mkdir(name);
}

// 日期：2026-11-25；交给QML触屏色板，不依赖桌面Widgets颜色对话框。
void MobileFiles::chooseColor() {
    emit colorRequested();
}

// 日期：2026-11-25；退出时停止原生选择及复制，晚到回调不访问已经返回的等待栈。
void MobileFiles::cancelOperation() {
    mobile::cancelDocumentPicker();
    if (nativeWaiter_)
        nativeWaiter_->quit();
    if (directoryWaiter_)
        directoryWaiter_->quit();
}

// 日期：2026-11-25；不动当前会话导入、上传引用或用户文档，损坏元数据时停止清理。
void MobileFiles::cleanUnusedImports() {
    if (busy_)
        return;
    int removed = 0;
    QString error;
    if (ImportRegistry(imports_).clean(startupBatches_, removed, error))
        message_ =
            QStringLiteral("已清理%1个旧暂存批次；本次导入和可续传任务继续保留").arg(removed);
    else
        message_ = error;
    emit changed();
}

// 日期：2026-11-25；仅解除私有引用，实际文件由无引用旧批次清理另行回收。
void MobileFiles::discardUpload(const QString &request) {
    if (busy_)
        return;
    const QUuid id(request);
    QString error;
    if (id.isNull() || request.size() != 36)
        message_ = QStringLiteral("请填写有效的原上传请求UUID");
    else if (!ImportRegistry(imports_).release(id, error))
        message_ = error;
    else
        message_ = QStringLiteral("已放弃该请求的本地续传；如需终止远端任务，请另行取消并查询状态");
    emit changed();
}

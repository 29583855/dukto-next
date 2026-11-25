#include "platformfiles.h"
#include "core/functionthread.h"
#include "importstore.h"

#include <QAndroidActivityResultReceiver>
#include <QAndroidJniEnvironment>
#include <QAndroidJniObject>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QThread>
#include <QtAndroid>
#include <atomic>
#include <memory>
#include <unistd.h>

namespace {
constexpr int RequestCode = 46440;
std::shared_ptr<std::atomic_bool> importCancellation;

// 日期：2026-11-25；将Java异常转换为可读错误并清除JNI异常状态，不继续使用无效返回值。
QString javaError() {
    QAndroidJniEnvironment environment;
    if (!environment->ExceptionCheck())
        return QString();
    auto exception = environment->ExceptionOccurred();
    environment->ExceptionClear();
    QAndroidJniObject object(exception);
    const auto text = object.callObjectMethod("toString", "()Ljava/lang/String;").toString();
    environment->DeleteLocalRef(exception);
    if (environment->ExceptionCheck())
        environment->ExceptionClear();
    return text.isEmpty() ? QStringLiteral("Android文档提供器操作失败") : text;
}

// 日期：2026-11-25；工作线程结果投递到主线程，避免跨线程修改QML模型。
void deliver(mobile::FileResult done, QStringList paths, QString error) {
    QMetaObject::invokeMethod(
        QCoreApplication::instance(), [done, paths, error] { done(paths, error); },
        Qt::QueuedConnection);
}

// 日期：2026-11-25；只通过SAF授权描述符导入，所有路径都由有界事务生成。
void stage(const QAndroidJniObject &intent, bool folder, mobile::FileResult done) {
    importCancellation = std::make_shared<std::atomic_bool>(false);
    const auto cancellation = importCancellation;
    auto worker = new dukto::FunctionThread([intent, folder, done, cancellation] {
        const auto context = QtAndroid::androidContext();
        auto json = QAndroidJniObject::callStaticObjectMethod(
            "org/duktonext/mobile/Documents", "scan",
            "(Landroid/content/Context;Landroid/content/Intent;Z)Ljava/lang/String;",
            context.object(), intent.object(), jboolean(folder));
        auto error = javaError();
        if (!error.isEmpty()) {
            deliver(done, {}, error);
            return;
        }
        QJsonParseError parse;
        const auto document = QJsonDocument::fromJson(json.toString().toUtf8(), &parse);
        if (parse.error != QJsonParseError::NoError || !document.isArray() ||
            document.array().isEmpty()) {
            deliver(done, {}, QStringLiteral("文档提供器没有返回有效文件列表"));
            return;
        }
        const auto imports = QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                                 .filePath(QStringLiteral("imports"));
        if (!QDir().mkpath(imports)) {
            deliver(done, {}, QStringLiteral("无法创建私有导入目录"));
            return;
        }
        ImportStore store(imports, ImportStore::Limits());
        QStringList roots;
        for (const auto &value : document.array()) {
            if (cancellation->load()) {
                error = QStringLiteral("已取消导入");
                break;
            }
            const auto item = value.toObject();
            const auto name = item.value("relative").toString();
            if (!name.contains('/'))
                roots.append(name);
            if (item.value("directory").toBool()) {
                if (!store.directory(name)) {
                    error = store.error();
                    break;
                }
                continue;
            }
            const auto uri = QAndroidJniObject::fromString(item.value("uri").toString());
            const auto descriptor = QAndroidJniObject::callStaticMethod<jint>(
                "org/duktonext/mobile/Documents", "openRead",
                "(Landroid/content/Context;Ljava/lang/String;)I", context.object(), uri.object());
            error = javaError();
            if (!error.isEmpty())
                break;
            QFile source;
            if (descriptor < 0 ||
                !source.open(descriptor, QIODevice::ReadOnly, QFileDevice::AutoCloseHandle)) {
                if (descriptor >= 0)
                    ::close(descriptor);
                error = QStringLiteral("无法读取已授权的文件描述符");
                break;
            }
            const auto expected = static_cast<qint64>(item.value("size").toDouble(-1));
            if (!store.copy(source, name, expected,
                            [cancellation] { return cancellation->load(); })) {
                error = store.error();
                break;
            }
            const auto signature = QAndroidJniObject::callStaticObjectMethod(
                "org/duktonext/mobile/Documents", "signature",
                "(Landroid/content/Context;Ljava/lang/String;)Ljava/lang/String;", context.object(),
                uri.object());
            error = javaError();
            if (!error.isEmpty())
                break;
            if (signature.toString() != item.value("signature").toString()) {
                error = QStringLiteral("导入期间源文件发生变化，请重新选择");
                break;
            }
        }
        const auto path = error.isEmpty() ? store.commit() : QString();
        if (path.isEmpty()) {
            deliver(done, {}, error.isEmpty() ? store.error() : error);
            return;
        }
        QStringList paths;
        for (const auto &root : roots)
            paths.append(QDir(path).filePath(root));
        deliver(done, paths, QString());
    });
    QObject::connect(worker, &QThread::finished, worker, &QObject::deleteLater);
    worker->start();
}

class Picker final : public QAndroidActivityResultReceiver {
  public:
    mobile::FileResult done;
    bool folder = false;
    QString exportPath;
    // 日期：2026-11-25；用户取消不会启动导入，选择完成才在线程中读取文档提供器。
    void handleActivityResult(int, int resultCode, const QAndroidJniObject &data) override {
        auto callback = done;
        done = {};
        if (!callback)
            return;
        if (resultCode != -1 || !data.isValid()) {
            callback({}, QString());
            return;
        }
        if (exportPath.isEmpty()) {
            stage(data, folder, callback);
            return;
        }
        const auto path = exportPath;
        exportPath.clear();
        auto worker = new dukto::FunctionThread([data, path, callback] {
            const auto uri = data.callObjectMethod("getData", "()Landroid/net/Uri;")
                                 .callObjectMethod("toString", "()Ljava/lang/String;");
            const auto context = QtAndroid::androidContext();
            const auto filename = QAndroidJniObject::fromString(path);
            const char *method = QFileInfo(path).isDir() ? "exportTree" : "export";
            QAndroidJniObject::callStaticMethod<void>(
                "org/duktonext/mobile/Documents", method,
                "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;)V",
                context.object(), filename.object(), uri.object());
            const auto error = javaError();
            deliver(callback, error.isEmpty() ? QStringList{path} : QStringList(), error);
        });
        QObject::connect(worker, &QThread::finished, worker, &QObject::deleteLater);
        worker->start();
    }
};
Picker picker;
} // namespace

// 日期：2026-11-25；ACTION_OPEN_DOCUMENT/TREE由系统授予所选范围，无需READ_EXTERNAL_STORAGE。
void mobile::selectDocuments(bool folder, FileResult done) {
    if (picker.done) {
        done({}, QStringLiteral("已有文件选择器打开"));
        return;
    }
    picker.done = done;
    picker.folder = folder;
    picker.exportPath.clear();
    auto action = QAndroidJniObject::fromString(folder ? "android.intent.action.OPEN_DOCUMENT_TREE"
                                                       : "android.intent.action.OPEN_DOCUMENT");
    QAndroidJniObject intent("android/content/Intent", "(Ljava/lang/String;)V", action.object());
    if (!folder) {
        intent.callObjectMethod("setType", "(Ljava/lang/String;)Landroid/content/Intent;",
                                QAndroidJniObject::fromString("*/*").object());
        intent.callObjectMethod(
            "putExtra", "(Ljava/lang/String;Z)Landroid/content/Intent;",
            QAndroidJniObject::fromString("android.intent.extra.ALLOW_MULTIPLE").object(),
            jboolean(true));
        intent.callObjectMethod(
            "addCategory", "(Ljava/lang/String;)Landroid/content/Intent;",
            QAndroidJniObject::fromString("android.intent.category.OPENABLE").object());
    }
    intent.callObjectMethod("addFlags", "(I)Landroid/content/Intent;", jint(1));
    QtAndroid::startActivity(intent, RequestCode, &picker);
}

// 日期：2026-11-25；文件使用创建文档，目录选择目标树后复制，明确拒绝同名根目录。
void mobile::exportDocument(const QString &path, FileResult done) {
    if (!QFileInfo::exists(path) || QFileInfo(path).isSymLink() || picker.done) {
        done({}, QStringLiteral("文件不存在、为符号链接或已有选择器打开"));
        return;
    }
    picker.done = done;
    picker.exportPath = path;
    QAndroidJniObject intent(
        "android/content/Intent", "(Ljava/lang/String;)V",
        QAndroidJniObject::fromString(QFileInfo(path).isDir()
                                          ? "android.intent.action.OPEN_DOCUMENT_TREE"
                                          : "android.intent.action.CREATE_DOCUMENT")
            .object());
    intent.callObjectMethod("setType", "(Ljava/lang/String;)Landroid/content/Intent;",
                            QAndroidJniObject::fromString("application/octet-stream").object());
    intent.callObjectMethod("putExtra",
                            "(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;",
                            QAndroidJniObject::fromString("android.intent.extra.TITLE").object(),
                            QAndroidJniObject::fromString(QFileInfo(path).fileName()).object());
    intent.callObjectMethod("addFlags", "(I)Landroid/content/Intent;", jint(3));
    QtAndroid::startActivity(intent, RequestCode, &picker);
}

// 日期：2026-11-25；关闭选择器并丢弃其迟到结果，复制线程由调用方等候完成。
void mobile::cancelDocumentPicker() {
    if (importCancellation)
        importCancellation->store(true);
    picker.done = {};
    QtAndroid::androidActivity().callMethod<void>("finishActivity", "(I)V", jint(RequestCode));
}

// 日期：2026-11-25；只在活动传输期间申请Android前台资格，捕获JNI错误供策略回退。
bool mobile::setBackgroundTransfer(bool active) {
    const auto context = QtAndroid::androidContext();
    const auto result = QAndroidJniObject::callStaticMethod<jboolean>(
        "org/duktonext/mobile/TransferService", "setActive", "(Landroid/content/Context;Z)Z",
        context.object(), jboolean(active));
    const auto error = javaError();
    if (active && result && error.isEmpty())
        QtAndroid::runOnAndroidThread([] {
            QtAndroid::androidActivity().callMethod<void>("requestTransferNotifications", "()V");
        });
    return active && result && error.isEmpty();
}
// 日期：2026-11-25；系统终止服务时不得继续假定后台网络可用。
bool mobile::backgroundTransferAlive() {
    const bool result = QAndroidJniObject::callStaticMethod<jboolean>(
        "org/duktonext/mobile/TransferService", "alive", "()Z");
    return javaError().isEmpty() && result;
}
// 日期：2026-11-25；通知取消、额度超时和意外服务销毁统一为Qt取消请求。
bool mobile::takeBackgroundStop() {
    const bool result = QAndroidJniObject::callStaticMethod<jboolean>(
        "org/duktonext/mobile/TransferService", "takeStop", "()Z");
    return !javaError().isEmpty() || result;
}
// 日期：2026-11-25；Android使用前台服务，不使用iOS收尾接口。
void mobile::beginBackgroundCleanup() {
}
// 日期：2026-11-25；Android收尾由传输服务状态负责。
void mobile::endBackgroundCleanup() {
}

// 日期：2026-11-25；JNI只读取有限JSON，不将content URI交给QML。
QVariantMap mobile::sharedDocuments() {
    const auto json = QAndroidJniObject::callStaticObjectMethod(
        "org/duktonext/mobile/IncomingShare", "info", "()Ljava/lang/String;");
    const auto error = javaError();
    return error.isEmpty()
               ? QJsonDocument::fromJson(json.toString().toUtf8()).object().toVariantMap()
               : QVariantMap{{"error", error}};
}
// 日期：2026-11-25；系统授予的流在用户明确发送后才导入，失败不会发送空任务。
void mobile::importSharedDocuments(FileResult done) {
    const auto intent = QAndroidJniObject::callStaticObjectMethod(
        "org/duktonext/mobile/IncomingShare", "takeFiles", "()Landroid/content/Intent;");
    const auto error = javaError();
    if (!error.isEmpty() || !intent.isValid()) {
        done({}, error.isEmpty() ? QStringLiteral("没有待处理分享文件，请重新从系统分享") : error);
        return;
    }
    stage(intent, false, done);
}
// 日期：2026-11-25；释放单槽待处理分享，文件原件完全由系统提供器管理。
void mobile::discardSharedDocuments(bool textOnly) {
    QAndroidJniObject::callStaticMethod<void>("org/duktonext/mobile/IncomingShare",
                                              textOnly ? "clearText" : "clear", "()V");
    javaError();
}
// 日期：2026-11-25；Android由受限ACTION_SEND入口接收，拒绝另行传入file URL。
bool mobile::acceptSharedUrl(const QUrl &) {
    return false;
}

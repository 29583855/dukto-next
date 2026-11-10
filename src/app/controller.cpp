#include "controller.h"
#include "boundedfiledialog.h"
#include "core/buffercredit.h"
#include "core/catalog.h"
#include "core/diagnostics.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/files.h"
#include "core/historystate.h"
#include "core/sqlitecache.h"
#include "core/sqliteruntime.h"

#include <QApplication>
#include <QClipboard>
#include <QColorDialog>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFileDialog>
#include <QJsonDocument>
#include <QNetworkInterface>
#include <QScreen>
#include <QSqlError>
#include <QSqlQuery>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>

struct Controller::HistoryConnection final {
    dukto::SqliteCacheCredit cache{2048, true};
    const QString name = "gui-history-" + QUuid::createUuid().toString(QUuid::WithoutBraces);
    std::shared_ptr<dukto::HistoryState> state;
    QString parent;
    QSqlDatabase database;

    // 日期：2026-11-09；先取得共用控制额度再开库，各实例拥有独立注册名；配置须真实回读确认。
    explicit HistoryConnection(const QString &directory) {
        // 日期：2026-11-09；历史写入只使用私有根，迁移保留旧文件并在整个连接寿命阻止旧库提交。
        state = dukto::HistoryState::open(directory, "history.sqlite");
        parent = directory;
        database = dukto::addSqliteDatabase(name, state->policy());
        try {
            database.setDatabaseName(state->path());
            if (!database.open())
                throw dukto::Error(dukto::ExitCode::Disk, database.lastError().text(), "history");
            state->validate(database);
            cache.configure(database);
            QSqlQuery query(database);
            for (const auto sql :
                 {"PRAGMA max_page_count=65536",
                  "CREATE TABLE IF NOT EXISTS history(time TEXT, path TEXT, bytes TEXT, message "
                  "TEXT)",
                  "CREATE TABLE IF NOT EXISTS text_history(record INTEGER PRIMARY KEY, content "
                  "TEXT)",
                  "CREATE TABLE IF NOT EXISTS history_peers(record INTEGER PRIMARY KEY, peer TEXT)",
                  "CREATE TABLE IF NOT EXISTS history_receipts(record INTEGER PRIMARY KEY, catalog "
                  "TEXT, "
                  "task TEXT, entries INTEGER)"})
                if (!query.exec(sql))
                    throw dukto::Error(dukto::ExitCode::Disk, query.lastError().text(), "history");
        } catch (...) {
            close();
            throw;
        }
    }

    // 日期：2026-11-09；构造失败或控制器后续初始化失败同样先关闭/移除连接，再归还页缓存目标额度。
    ~HistoryConnection() {
        close();
    }

    // 日期：2026-11-09；先销毁本实例数据库引用，按唯一名称注销，不影响仍存活的其他窗口实例。
    void close() {
        database.close();
        database = QSqlDatabase();
        QSqlDatabase::removeDatabase(name);
    }
};

// 日期：2026-11-10；初始化独立设置和历史，按实际TCP端口启动共享广播与独占回复入口。
Controller::Controller(quint16 port, QObject *parent, const QString &storageDirectory,
                       bool automaticPort)
    : QObject(parent),
      settings_(QSettings::defaultFormat(), QSettings::UserScope, "DuktoNext", "Desktop"),
      server_(QDir(storageDirectory.isEmpty()
                       ? QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)
                       : storageDirectory)
                  .filePath("remote"),
              this),
      discovery_(this) {
    diagnosticPort_ = port;
    const auto dataDirectory =
        storageDirectory.isEmpty()
            ? QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)
            : storageDirectory;
    if (!QDir().mkpath(dataDirectory))
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法创建应用数据目录"));
    historyConnection_.reset(new HistoryConnection(dataDirectory));
    loadHistory();
    connect(QApplication::clipboard(), &QClipboard::dataChanged, this,
            &Controller::refreshClipboardAvailability);
    refreshClipboardAvailability();
    // 日期：2026-11-04；版本检查状态独立于传输状态，失败不干扰局域网收发。
    connect(&updates_, &dukto::Updates::completed, this,
            [this](bool available, const QString &, const QUrl &page, const QString &message) {
                updatePage_ = available ? page : QUrl();
                updateMessage_ = message;
                emit stateChanged();
            });
    avatars_.setLocalImage(settings_.value("avatar").toByteArray());
    connect(&avatars_, &Avatars::changed, this, &Controller::peersChanged);
    // 日期：2026-11-04；头像缓存跟随有限发现列表，在线/离线变化不累积旧设备图像。
    connect(&discovery_, &dukto::Discovery::changed, this, [this]() {
        avatars_.synchronize(discovery_.peers());
        emit peersChanged();
    });
    const auto receiveDirectory = outputDirectory();
    if (!settings_.contains("output") && !receiveDirectory.isEmpty() &&
        !QFileInfo::exists(receiveDirectory))
        QDir().mkpath(receiveDirectory);
    listener_ = new dukto::LegacyListener(receiveDirectory, 30000, this,
                                          QDir(dataDirectory).filePath("receipts.sqlite"));
    connect(listener_, &dukto::LegacyListener::event, this, &Controller::onEvent);
    // 日期：2026-11-04；发送结果不能清除同时进行的接收状态。
    connect(listener_, &dukto::LegacyListener::result, this,
            [this](int code, const dukto::LegacyResult &result) {
                receiving_ = false;
                onResult(code, result);
            });
    bool listening = listener_->listen(QHostAddress::Any, port);
    bool discovered = false;
    QString startupError = listener_->errorString();
    // 日期：2026-11-10；仅桌面默认4644冲突时尝试16组备用端口，避开TLS默认4646，显式指定端口保持严格失败。
    if (!listening && automaticPort && port == 4644 &&
        listener_->serverError() == QAbstractSocket::AddressInUseError) {
        for (quint16 candidate = 4648; candidate <= 4678; candidate += 2) {
            if (!listener_->listen(QHostAddress::Any, candidate)) {
                startupError = listener_->errorString();
                continue;
            }
            discovered = discovery_.start(candidate, username());
            if (discovered) {
                listening = true;
                break;
            }
            startupError = QStringLiteral("发现端口绑定失败：") + discovery_.errorString();
            listener_->close();
        }
    }
    if (!listening) {
        status_ = QStringLiteral("接收端口不可用：") + startupError;
        return;
    }
    diagnosticPort_ = listener_->serverPort();
    if (!discovered)
        discovered = discovery_.start(diagnosticPort_, username());
    if (!discovered)
        status_ = QStringLiteral("接收端口 %1 已监听；发现端口绑定失败：").arg(diagnosticPort_) +
                  discovery_.errorString();
    else if (!QFileInfo(receiveDirectory).isDir())
        status_ = QStringLiteral("接收端口 %1 已监听；接收目录不可用，请在设置选择目录")
                      .arg(diagnosticPort_);
    else if (port == 4644 && diagnosticPort_ != port)
        status_ = QStringLiteral("就绪 · 4644被占用，已使用接收端口 %1 · 自动发现已启用")
                      .arg(diagnosticPort_);
    else
        status_ = QStringLiteral("就绪 · 接收端口 %1").arg(diagnosticPort_);
    if (!avatars_.listen(diagnosticPort_))
        status_ += QStringLiteral(" · 头像端口不可用，使用默认图标");
}

// 日期：2026-11-07；仅检查当前实例设置、数据/接收目录与已存在监听，不暂停正在执行的任务。
QVariantMap Controller::diagnostics() {
    try {
        dukto::DiagnosticOptions options;
        options.stateDirectory = historyConnection_->parent;
        options.outputDirectory = outputDirectory();
        options.requireStateDirectory = true;
        options.requireOutputDirectory = true;
        options.listenerActive = listener_ && listener_->isListening();
        options.port = diagnosticPort_;
        options.checkPort = !options.listenerActive;
        return dukto::collectDiagnostics(settings_, options).toVariantMap();
    } catch (const dukto::Error &error) {
        return QJsonObject{{"eventVersion", 1},
                           {"event", "doctor"},
                           {"reportVersion", 1},
                           {"passed", false},
                           {"exitCode", static_cast<int>(error.code)},
                           {"message", QStringLiteral("诊断资源暂不可用，请稍后重试")}}
            .toVariantMap();
    }
}

// 日期：2026-11-07；只接受本地文件URL，使用同一白名单报告，拒绝覆盖并保留失败可见状态。
bool Controller::exportDiagnosticsTo(const QUrl &destination) {
    try {
        if (!destination.isLocalFile())
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("请选择本地JSON报告文件"),
                               "doctor");
        dukto::exportDiagnostics(QJsonObject::fromVariantMap(diagnostics()),
                                 destination.toLocalFile());
        status_ = QStringLiteral("诊断报告已保存到本地；未上传");
        emit stateChanged();
        return true;
    } catch (const dukto::Error &) {
        status_ = QStringLiteral("诊断导出失败：请检查目录权限/剩余空间，并选择未存在的新文件名称");
        emit stateChanged();
        return false;
    }
}

// 日期：2026-11-07；跨平台原生保存选择器只选择目标，已有文件由核心再次严格拒绝覆盖。
void Controller::chooseDiagnosticReport() {
    const auto destination = QFileDialog::getSaveFileName(
        nullptr, QStringLiteral("导出本地诊断"),
        QDir(outputDirectory())
            .filePath("Dukto-diagnostic-" +
                      QDateTime::currentDateTimeUtc().toString("yyyyMMdd-HHmmss") + ".json"),
        QStringLiteral("JSON诊断报告 (*.json)"), nullptr, QFileDialog::DontConfirmOverwrite);
    if (!destination.isEmpty())
        exportDiagnosticsTo(QUrl::fromLocalFile(destination));
}

// 日期：2026-11-04；明确等待发送与接收线程，避免退出后继续写文件。
Controller::~Controller() {
    if (sender_) {
        sender_->cancel();
        sender_->wait();
        delete sender_;
    }
    delete listener_;
    historyConnection_.reset();
}

// 日期：2026-11-04；发现列表最多 256 个设备。
QVariantList Controller::peers() const {
    QVariantList result;
    for (const auto &value : discovery_.peers()) {
        auto peer = value.toObject();
        peer["avatar"] = avatars_.image(peer["id"].toString());
        result.append(peer.toVariantMap());
    }
    return result;
}

// 日期：2026-11-04；QML 只得到公开面板属性，不接触服务私钥和访问令牌。
QObject *Controller::server() const {
    return const_cast<ServerPanel *>(&server_);
}
// 日期：2026-11-04；只返回最近一页数据。
QVariantList Controller::history() const {
    return history_;
}
// 日期：2026-11-04；状态文本始终来源于实际事件。
QString Controller::status() const {
    return status_;
}
// 日期：2026-11-04；平台默认目录通过 Qt 标准路径获取。
QString Controller::outputDirectory() const {
    return settings_
        .value("output", QStandardPaths::writableLocation(QStandardPaths::DownloadLocation))
        .toString();
}
// 日期：2026-11-04；默认绿色接近参考程序主题。
QString Controller::themeColor() const {
    return settings_.value("theme", "#268600").toString();
}
// 日期：2026-11-04；优先使用已保存用户名，再回退系统账户名。
QString Controller::username() const {
    return settings_
        .value("username", qEnvironmentVariable("USERNAME", qEnvironmentVariable("USER", "User")))
        .toString();
}

// 日期：2026-11-04；本机默认或自选头像均以有界 PNG 数据提供。
QString Controller::localAvatar() const {
    return avatars_.localImage();
}

// 日期：2026-11-04；仅显式选择的 PNG/JPEG 进入配置，失败保留旧头像。
void Controller::chooseAvatar() {
    const auto path = QFileDialog::getOpenFileName(nullptr, QStringLiteral("选择头像"), QString(),
                                                   QStringLiteral("图片 (*.png *.jpg *.jpeg)"));
    if (path.isEmpty())
        return;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly) || !avatars_.setLocalImage(file.read(128 * 1024 + 1))) {
        status_ = QStringLiteral("头像须为不超过 128 KiB、1024×1024 像素的有效 PNG/JPEG");
        emit stateChanged();
        return;
    }
    settings_.setValue("avatar", avatars_.localPng());
    status_ = QStringLiteral("头像已保存");
    emit stateChanged();
}
// 日期：2026-11-04；按已启用网卡输出 IPv4/IPv6，保留链路本地 IPv6 的作用域。
QString Controller::addresses() const {
    QStringList result;
    for (const auto &interface : QNetworkInterface::allInterfaces()) {
        if (!(interface.flags() & QNetworkInterface::IsUp))
            continue;
        QStringList addresses;
        for (const auto &entry : interface.addressEntries()) {
            const auto address = entry.ip();
            if (address.isNull() || address.isMulticast())
                continue;
            const auto family =
                address.protocol() == QAbstractSocket::IPv6Protocol ? "IPv6" : "IPv4";
            const auto line = family + QString("  ") + address.toString();
            if (!addresses.contains(line))
                addresses.append(line);
        }
        if (!addresses.isEmpty())
            result.append(interface.humanReadableName() + '\n' + addresses.join('\n'));
    }
    return result.join("\n\n");
}
// 日期：2026-11-04；发送线程及活动接收都会阻止重复操作。
bool Controller::busy() const {
    return sender_ || receiving_ || capturePending_;
}
// 日期：2026-11-04；进度取值被限制为 0 到 1。
double Controller::progress() const {
    return progress_;
}
// 日期：2026-11-04；默认首次展示使用范围与项目归属说明。
bool Controller::termsAccepted() const {
    return settings_.value("terms", false).toBool();
}

// 日期：2026-11-07；只返回缓存可用状态，传输进度刷新不再读取剪贴板正文。
bool Controller::clipboardAvailable() const {
    return clipboardAvailable_;
}

// 日期：2026-11-07；仅实际变化时读取一次正文；只保存布尔值，显式发送仍重新读取最新文本。
void Controller::refreshClipboardAvailability() {
    const bool available = !QApplication::clipboard()->text().isEmpty();
    if (available == clipboardAvailable_)
        return;
    clipboardAvailable_ = available;
    emit clipboardAvailabilityChanged();
}

// 日期：2026-11-04；更新地址独立存储，不继承 Dukto 历史 HTTP 站点。
QString Controller::updateEndpoint() const {
    return settings_.value("updateEndpoint").toString();
}
// 日期：2026-11-04；未检查时说明当前配置状态。
QString Controller::updateMessage() const {
    return updateMessage_.isEmpty() ? QStringLiteral("可配置发布源后手动检查版本") : updateMessage_;
}
// 日期：2026-11-04；发布链接只来自验证成功的较新版本描述。
bool Controller::updateAvailable() const {
    return !updatePage_.isEmpty();
}
// 日期：2026-11-04；不会自动安装、重启或向历史站点发送统计信息。
void Controller::checkUpdates(const QString &endpoint) {
    settings_.setValue("updateEndpoint", endpoint.trimmed());
    updateMessage_ = QStringLiteral("正在检查版本…");
    updatePage_.clear();
    emit stateChanged();
    updates_.check(QUrl(endpoint.trimmed()));
}
// 日期：2026-11-04；系统浏览器打开失败时保留可读错误。
void Controller::openUpdatePage() {
    if (!updatePage_.isEmpty() && !QDesktopServices::openUrl(updatePage_)) {
        updateMessage_ = QStringLiteral("无法打开发布页面");
        emit stateChanged();
    }
}
// 日期：2026-11-04；用户确认后才持久保存，不在后台接受外部服务条款。
void Controller::acceptTerms() {
    settings_.setValue("terms", true);
    emit stateChanged();
}

// 日期：2026-11-04；原生选择器返回空列表时不创建任务。
void Controller::sendFiles(const QString &host, int port) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return;
    const auto files = chooseFilesBounded(nullptr, QStringLiteral("选择发送文件"));
    if (files.isEmpty())
        return;
    request.paths = files;
    start(request);
}

// 日期：2026-11-04；文件夹枚举在工作线程执行，不阻塞界面。
void Controller::sendFolder(const QString &host, int port) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return;
    const auto folder =
        QFileDialog::getExistingDirectory(nullptr, QStringLiteral("选择发送文件夹"));
    if (folder.isEmpty())
        return;
    request.paths = QStringList{folder};
    start(request);
}

// 日期：2026-11-07；无分配计算Qt UTF-8字节数，孤立代理码元按Qt默认问号编码，超过原上限立即拒绝。
static qint64 outgoingTextBytes(const QString &text) {
    if (text.size() > dukto::MaxTextBytes)
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("文本超过 8 MiB 限制，请作为文件发送"), "scan");
    qint64 bytes = 0;
    for (int index = 0; index < text.size(); ++index) {
        const auto ch = text.at(index);
        if (ch.isHighSurrogate() && index + 1 < text.size() &&
            text.at(index + 1).isLowSurrogate()) {
            bytes += 4;
            ++index;
        } else if (ch.isSurrogate() || ch.unicode() < 0x80)
            ++bytes;
        else
            bytes += ch.unicode() < 0x800 ? 2 : 3;
        if (bytes > dukto::MaxTextBytes)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("文本超过 8 MiB 限制，请作为文件发送"), "scan");
    }
    return bytes;
}

// 日期：2026-11-07；先核对上限和编码临时额度；令牌先于请求声明，异常反馈后也先释放正文再归还额度。
bool Controller::sendText(const QString &host, int port, const QString &text) {
    std::unique_ptr<dukto::BufferCredit> conversion;
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return false;
    try {
        const auto bytes = outgoingTextBytes(text);
        conversion.reset(new dukto::BufferCredit(qint64(text.size()) * 3 + 64 * 1024, true));
        request.textMode = true;
        request.text = text.toUtf8();
        if (request.text.size() != bytes)
            throw dukto::Error(dukto::ExitCode::Runtime,
                               QStringLiteral("文本编码长度校验失败，未开始发送"), "scan");
        start(std::move(request));
        return sender_ != nullptr;
    } catch (const dukto::Error &error) {
        status_ = error.message;
        emit stateChanged();
        return false;
    }
}

// 日期：2026-11-07；显式发送只读取一次系统剪贴板，复用转换前字节检查；系统读取本身另行验收。
void Controller::sendClipboard(const QString &host, int port) {
    const auto text = QApplication::clipboard()->text();
    if (!text.isEmpty())
        sendText(host, port, text);
}

// 日期：2026-11-04；复制操作仅影响用户明确选择的文本。
void Controller::copyText(const QString &text) {
    QApplication::clipboard()->setText(text);
}

// 日期：2026-11-04；等待窗口隐藏生效后捕获主屏，权限失败时明确报告。
void Controller::sendScreenshot(const QString &host, int port) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return;
    capturePending_ = true;
    emit captureVisibility(false);
    // 日期：2026-11-04；临时 JPEG 保留至发送线程结束，取消或失败也会清理。
    QTimer::singleShot(300, this, [this, request]() mutable {
        capturePending_ = false;
        captureDirectory_.reset(new QTemporaryDir);
        const auto file = captureDirectory_->filePath("Screenshot.jpg");
        auto screen = QGuiApplication::primaryScreen();
        const auto capture = screen ? screen->grabWindow(0) : QPixmap();
        emit captureVisibility(true);
        if (!captureDirectory_->isValid() || capture.isNull() || !capture.save(file, "JPG", 90)) {
            status_ = QStringLiteral("截图不可用，请检查系统屏幕录制权限或显示环境");
            captureDirectory_.reset();
            emit stateChanged();
            return;
        }
        request.paths = QStringList{file};
        start(request);
        if (!sender_)
            captureDirectory_.reset();
    });
}

// 日期：2026-11-04；拖放仅接受本机 URL，远程链接不隐式下载。
bool Controller::sendDropped(const QString &host, int port, const QList<QUrl> &urls) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return false;
    for (const auto &url : urls) {
        if (!url.isLocalFile()) {
            status_ = QStringLiteral("仅支持拖入本地文件或目录");
            emit stateChanged();
            return false;
        }
        request.paths.append(url.toLocalFile());
    }
    if (request.paths.isEmpty())
        return false;
    start(request);
    return sender_ != nullptr;
}

// 日期：2026-11-04；配置变更不影响活动接收任务，空闲监听器原位切换接收目录。
void Controller::chooseOutputDirectory() {
    if (busy()) {
        status_ = QStringLiteral("请等待当前任务结束后更换接收目录");
        emit stateChanged();
        return;
    }
    const auto path = QFileDialog::getExistingDirectory(nullptr, QStringLiteral("选择接收目录"),
                                                        outputDirectory());
    if (path.isEmpty())
        return;
    QTemporaryFile test(QDir(path).filePath(".dukto-write-XXXXXX"));
    if (!test.open()) {
        status_ = QStringLiteral("目标目录不可写：") + test.errorString();
        emit stateChanged();
        return;
    }
    if (!listener_->setOutput(path))
        status_ = QStringLiteral("接收任务正在收尾，请稍后重试");
    else {
        settings_.setValue("output", path);
        settings_.sync();
        status_ = settings_.status() == QSettings::NoError
                      ? QStringLiteral("接收目录已更新")
                      : QStringLiteral("目录已切换，但设置保存失败");
    }
    emit stateChanged();
}

// 日期：2026-11-04；不可访问的历史路径不伪装打开成功。
void Controller::openPath(const QString &path) {
    if (!QFileInfo::exists(path) || !QDesktopServices::openUrl(QUrl::fromLocalFile(path))) {
        status_ = QStringLiteral("无法打开，文件可能已移动或删除：") + path;
        emit stateChanged();
    }
}

// 日期：2026-11-04；只保存有效 RGB 颜色。
void Controller::setThemeColor(const QString &color) {
    const QColor value(color);
    if (!value.isValid())
        return;
    settings_.setValue("theme", value.name());
    emit stateChanged();
}

// 日期：2026-11-04；原生颜色选择器取消时保留原设置。
void Controller::chooseThemeColor() {
    const auto color =
        QColorDialog::getColor(QColor(themeColor()), nullptr, QStringLiteral("主题颜色"));
    if (color.isValid())
        setThemeColor(color.name());
}

// 日期：2026-11-04；避免签名含换行或分隔符歧义，保存后立即公告。
void Controller::setUsername(const QString &name) {
    const auto value = name.trimmed().left(128);
    if (value.isEmpty() || value.contains('\n') || value.contains('\r'))
        return;
    settings_.setValue("username", value);
    discovery_.setUsername(value);
    emit stateChanged();
}

// 日期：2026-11-04；当前发送任务取消通过原子标记实现。
void Controller::cancel() {
    if (sender_)
        sender_->cancel();
    listener_->cancel();
}

// 日期：2026-11-04；显式广播后通知地址显示更新。
void Controller::refresh() {
    discovery_.announce();
    avatars_.synchronize(discovery_.peers(), true);
    emit peersChanged();
    emit stateChanged();
}

// 日期：2026-11-04；无目标、端口非法或正在传输时拒绝创建任务。
void Controller::start(dukto::LegacyRequest request) {
    if (busy() || request.host.trimmed().isEmpty() || request.port == 0) {
        status_ = busy() ? QStringLiteral("已有活动任务，请等待或取消")
                         : QStringLiteral("请填写目标地址和端口");
        emit stateChanged();
        return;
    }
    try {
        sender_ = new dukto::LegacyJob(std::move(request), this);
    } catch (const dukto::Error &error) {
        status_ = error.message;
        emit stateChanged();
        return;
    }
    connect(sender_, &dukto::LegacyJob::event, this, &Controller::onEvent);
    connect(sender_, &dukto::LegacyJob::result, this, &Controller::onResult);
    // 日期：2026-11-04；线程退出后才归还任务槽位及截图临时目录。
    connect(sender_, &QThread::finished, this, [this]() {
        sender_->deleteLater();
        sender_ = nullptr;
        captureDirectory_.reset();
        emit stateChanged();
    });
    status_ = QStringLiteral("正在准备发送");
    progress_ = 0;
    emit stateChanged();
    sender_->start();
}

// 日期：2026-11-04；防止 QML 调用把负数或大于 65535 的端口截断为有效端口。
bool Controller::prepareRequest(dukto::LegacyRequest &request, const QString &host, int port) {
    try {
        if (busy())
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("已有活动任务，请等待或取消"));
        const auto endpoint = dukto::parseEndpoint(host, port);
        request.host = endpoint.host;
        request.port = endpoint.port;
        return true;
    } catch (const dukto::Error &error) {
        status_ = error.message;
        emit stateChanged();
        return false;
    }
}

// 日期：2026-11-04；进度更新不保存正文，只解析十进制 64 位计数。
void Controller::onEvent(const QJsonObject &event) {
    if (event.value("event") != "progress")
        return;
    const auto stage = event.value("stage").toString();
    if (stage == "receive")
        receiving_ = true;
    const auto bytes = event.value("bytes").toString().toLongLong();
    const auto total = event.value("total").toString().toLongLong();
    if (total > 0)
        progress_ = qBound(0.0, static_cast<double>(bytes) / total, 1.0);
    const auto elapsed = event.value("elapsedMs").toString().toLongLong();
    status_ = stage == "scan"
                  ? QStringLiteral("正在扫描文件清单")
                  : QStringLiteral("%1 · %2 / %3 MiB · %4 MiB/s")
                        .arg(stage == "receive" ? QStringLiteral("接收") : QStringLiteral("发送"))
                        .arg(bytes / 1048576.0, 0, 'f', 1)
                        .arg(total / 1048576.0, 0, 'f', 1)
                        .arg(elapsed > 0 ? bytes * 1000.0 / elapsed / 1048576 : 0, 0, 'f', 1);
    if (total > 0)
        status_ += QStringLiteral(" · %1%").arg(progress_ * 100, 0, 'f', 1);
    const auto object = event.value("object").toString();
    if (!object.isEmpty())
        status_ += " · " + QFileInfo(object).fileName().left(120);
    emit stateChanged();
}

// 日期：2026-11-06；结果值持有正文额度直到历史写入与显示接管完成，数据库失败也不提前释放显示正文。
void Controller::onResult(int code, const dukto::LegacyResult &ownedResult) {
    const auto &result = ownedResult.json();
    status_ = code ? result.value("message").toString()
                   : (result.value("stage") == "sent" ? result.value("message").toString()
                                                      : QStringLiteral("接收完成"));
    progress_ = code ? 0 : 1;
    if (!code)
        status_ +=
            QStringLiteral(" · 用时 %1 秒 · %2 MiB/s")
                .arg(result.value("elapsedMs").toString().toLongLong() / 1000.0, 0, 'f', 2)
                .arg(result.value("rateBytesPerSecond").toString().toDouble() / 1048576, 0, 'f', 1);
    {
        QSqlQuery query(historyConnection_->database);
        bool saved = historyConnection_->database.transaction();
        query.prepare("INSERT INTO history VALUES (?, ?, ?, ?)");
        query.addBindValue(QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
        query.addBindValue(result.value("path").toString());
        query.addBindValue(result.value("bytes").toString());
        query.addBindValue(status_);
        saved = saved && query.exec();
        const auto historyId = query.lastInsertId();
        if (saved) {
            query.prepare("INSERT INTO history_peers VALUES (?, ?)");
            query.addBindValue(historyId);
            query.addBindValue(result.value("peer").toString());
            saved = query.exec();
        }
        if (saved && result.contains("text")) {
            query.prepare("INSERT INTO text_history VALUES (?, ?)");
            query.addBindValue(historyId);
            query.addBindValue(result.value("text").toString());
            saved = query.exec();
        }
        if (saved && result.contains("taskId")) {
            query.prepare("INSERT INTO history_receipts VALUES (?, ?, ?, ?)");
            query.addBindValue(historyId);
            query.addBindValue(result.value("catalog").toString());
            query.addBindValue(result.value("taskId").toString());
            query.addBindValue(result.value("entries").toString());
            saved = query.exec();
        }
        saved =
            saved &&
            query.exec(
                "DELETE FROM history WHERE rowid NOT IN (SELECT rowid FROM history ORDER BY rowid "
                "DESC LIMIT 10000) OR julianday(time) < julianday('now', '-30 days')") &&
            query.exec(
                "DELETE FROM text_history WHERE record NOT IN (SELECT rowid FROM history)") &&
            query.exec(
                "DELETE FROM history_peers WHERE record NOT IN (SELECT rowid FROM history)") &&
            query.exec(
                "DELETE FROM history_receipts WHERE record NOT IN (SELECT rowid FROM history)");
        const auto failure = query.lastError().isValid()
                                 ? query.lastError().text()
                                 : historyConnection_->database.lastError().text();
        if (!saved || !historyConnection_->database.commit()) {
            historyConnection_->database.rollback();
            status_ += QStringLiteral("；历史保存失败：") + failure;
        }
        loadHistory();
        if (result.contains("text")) {
            displayReceivedText(result.value("text").toString(), ownedResult.textCredit());
        }
    }
    emit stateChanged();
}

// 日期：2026-11-04；界面模型只持有一页，扫描和历史总数量不能放大内存。
void Controller::loadHistory() {
    history_.clear();
    QSqlQuery query(historyConnection_->database);
    if (!query.exec("SELECT time, path, bytes, message, rowid, EXISTS(SELECT 1 FROM text_history "
                    "WHERE record=history.rowid), (SELECT peer FROM history_peers WHERE "
                    "record=history.rowid) FROM history ORDER BY rowid DESC LIMIT 100")) {
        status_ = QStringLiteral("历史读取失败：") + query.lastError().text();
        emit stateChanged();
        return;
    }
    while (query.next())
        history_.append(QVariantMap{{"time", query.value(0)},
                                    {"path", query.value(1)},
                                    {"bytes", query.value(2)},
                                    {"message", query.value(3)},
                                    {"id", query.value(4).toString()},
                                    {"peer", query.value(6).toString()},
                                    {"hasText", query.value(5).toBool()}});
    emit historyChanged();
}

// 日期：2026-11-06；界面先清空正文再调用；先销毁完整正文和页索引，再归还共享令牌。
void Controller::releaseReceivedText() {
    displayedText_.clear();
    displayedTextPages_.clear();
    displayedTextPage_ = 0;
    emit receivedTextPageChanged();
    displayedTextCredit_.reset();
}

// 日期：2026-11-06；只生成当前页的有界字符串；空正文和关闭后的页面均返回空串。
QString Controller::receivedTextPage() const {
    if (displayedTextPages_.isEmpty())
        return {};
    const int begin = displayedTextPages_[displayedTextPage_];
    return displayedText_.mid(begin, displayedTextPages_[displayedTextPage_ + 1] - begin);
}

// 日期：2026-11-06；页码不涉及编码细节，普通短文本不显示分页导航。
QString Controller::receivedTextPosition() const {
    return displayedTextPages_.isEmpty() ? QString()
                                         : QStringLiteral("第 %1 / %2 页")
                                               .arg(displayedTextPage_ + 1)
                                               .arg(displayedTextPages_.size() - 1);
}

// 日期：2026-11-06；是否能够后退由已校验的当前索引决定。
bool Controller::receivedTextHasPrevious() const {
    return displayedTextPage_ > 0;
}

// 日期：2026-11-06；尾页哨兵不作为实际显示页。
bool Controller::receivedTextHasNext() const {
    return displayedTextPage_ + 2 < displayedTextPages_.size();
}

// 日期：2026-11-06；至少两个显示页才需要额外导航控件。
bool Controller::receivedTextPaged() const {
    return displayedTextPages_.size() > 2;
}

// 日期：2026-11-06；返回实际页数，空正文仍占一页，关闭后不保留页面。
int Controller::receivedTextPageCount() const {
    return qMax(0, displayedTextPages_.size() - 1);
}

// 日期：2026-11-06；扩大类型后检查页码，避免极端QML入参溢出或跳出索引。
void Controller::changeReceivedTextPage(int delta) {
    const auto page = qint64(displayedTextPage_) + delta;
    if (page < 0 || page + 1 >= displayedTextPages_.size())
        return;
    displayedTextPage_ = static_cast<int>(page);
    emit receivedTextPageChanged();
}

// 日期：2026-11-06；复制保持原正文而非QTextDocument规范化/分页后的字符串，不丢失NUL或换行。
void Controller::copyReceivedText(const QString &selection) {
    copyText(selection.isEmpty() ? displayedText_ : selection);
}

// 日期：2026-11-06；同时限制字符和段落；位置索引最多约16385项，全部正文仍受8MiB协议和共享额度约束。
void Controller::displayReceivedText(QString text, std::shared_ptr<dukto::BufferCredit> credit) {
    QVector<int> pages;
    pages.append(0);
    for (int begin = 0; begin < text.size();) {
        int end = begin;
        int breaks = 0;
        while (end < text.size() && end - begin < 16384) {
            const auto value = text[end++].unicode();
            if ((value == '\r' || value == '\n' || value == 0x2028 || value == 0x2029) &&
                ++breaks == 512)
                break;
        }
        if (end < text.size() && text.at(end - 1).isHighSurrogate() &&
            text.at(end).isLowSurrogate())
            --end;
        pages.append(end);
        begin = end;
    }
    if (text.isEmpty())
        pages.append(0);
    auto previousCredit = std::move(displayedTextCredit_);
    auto previousText = std::move(displayedText_);
    auto previousPages = std::move(displayedTextPages_);
    displayedTextCredit_ = std::move(credit);
    displayedText_ = std::move(text);
    displayedTextPages_ = std::move(pages);
    displayedTextPage_ = 0;
    emit receivedTextPageChanged();
    emit receivedTextOpened();
    // 日期：2026-11-06；保留C++完成通知兼容性；QML只监听无正文通知，避免建立完整JS/文档副本。
    emit textReceived(displayedText_);
}

// 日期：2026-11-06；按需打开历史文本前核对UTF-8长度并授信，旧显示在新文本替换完成前仍有额度。
void Controller::openHistory(const QString &id) {
    QSqlQuery query(historyConnection_->database);
    query.prepare("SELECT catalog, task, entries FROM history_receipts WHERE record=?");
    query.addBindValue(id);
    if (!query.exec()) {
        status_ = QStringLiteral("无法读取接收任务明细索引");
        emit stateChanged();
        return;
    }
    if (query.next() && query.value(2).toLongLong() != 1) {
        batchCatalog_ = query.value(0).toString();
        batchTask_ = query.value(1).toString();
        changeBatchPage(0);
        emit batchOpened();
        return;
    }
    query.prepare(
        "SELECT path, EXISTS(SELECT 1 FROM text_history WHERE record=history.rowid), (SELECT "
        "length(CAST(content AS BLOB)) FROM text_history WHERE record=history.rowid) FROM history "
        "WHERE rowid=?");
    query.addBindValue(id);
    if (!query.exec() || !query.next()) {
        status_ = QStringLiteral("历史记录不存在或不可读取");
        emit stateChanged();
        return;
    }
    if (query.value(1).toBool()) {
        try {
            auto credit = dukto::legacyTextCredit(query.value(2).toLongLong());
            query.prepare("SELECT content FROM text_history WHERE record=?");
            query.addBindValue(id);
            if (!query.exec() || !query.next())
                throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("历史文本读取失败"),
                                   "history");
            displayReceivedText(query.value(0).toString(), std::move(credit));
        } catch (const dukto::Error &error) {
            status_ = error.message;
            emit stateChanged();
        }
    } else if (!query.value(0).toString().isEmpty())
        openPath(query.value(0).toString());
    else {
        status_ = QStringLiteral("此发送记录没有可打开的接收文件");
        emit stateChanged();
    }
}

// 日期：2026-11-04；返回已限制为一页的批次明细。
QVariantList Controller::batchFiles() const {
    return batchFiles_;
}
// 日期：2026-11-04；页码仅用于本地查询，避免累积已看过的页。
int Controller::batchPage() const {
    return batchPage_;
}
// 日期：2026-11-04；读取实际记录后确定是否还存在下一页。
bool Controller::batchHasNext() const {
    return batchHasNext_;
}
// 日期：2026-11-04；每次连接只读取最多 101 项，任务明细不整体进入 QML 模型。
void Controller::changeBatchPage(int page) {
    if (page < 0 || page > 100000 || batchTask_.isEmpty())
        return;
    try {
        dukto::Catalog catalog(batchCatalog_);
        catalog.task(batchTask_);
        const auto rows = catalog.page(batchTask_, static_cast<qint64>(page) * 100);
        batchFiles_ = rows.toVariantList();
        batchPage_ = page;
        batchHasNext_ = !rows.isEmpty() &&
                        !catalog.page(batchTask_, static_cast<qint64>(page + 1) * 100).isEmpty();
        emit batchChanged();
    } catch (const dukto::Error &error) {
        status_ = error.message;
        emit stateChanged();
    }
}

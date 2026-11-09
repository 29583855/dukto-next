#pragma once

#include "avatars.h"
#include "core/discovery.h"
#include "core/legacy.h"
#include "core/updates.h"
#include "serverpanel.h"

#include <QJsonObject>
#include <QObject>
#include <QSettings>
#include <QSqlDatabase>
#include <QTemporaryDir>
#include <QUrl>
#include <QVariantList>
#include <QVector>

class Controller final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantList peers READ peers NOTIFY peersChanged)
    Q_PROPERTY(QVariantList history READ history NOTIFY historyChanged)
    Q_PROPERTY(QString status READ status NOTIFY stateChanged)
    Q_PROPERTY(QString outputDirectory READ outputDirectory NOTIFY stateChanged)
    Q_PROPERTY(QString themeColor READ themeColor NOTIFY stateChanged)
    Q_PROPERTY(QString username READ username NOTIFY stateChanged)
    Q_PROPERTY(QString addresses READ addresses NOTIFY stateChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY stateChanged)
    Q_PROPERTY(double progress READ progress NOTIFY stateChanged)
    Q_PROPERTY(bool termsAccepted READ termsAccepted NOTIFY stateChanged)
    Q_PROPERTY(bool clipboardAvailable READ clipboardAvailable NOTIFY clipboardAvailabilityChanged)
    Q_PROPERTY(QString updateEndpoint READ updateEndpoint NOTIFY stateChanged)
    Q_PROPERTY(QString updateMessage READ updateMessage NOTIFY stateChanged)
    Q_PROPERTY(bool updateAvailable READ updateAvailable NOTIFY stateChanged)
    Q_PROPERTY(QVariantList batchFiles READ batchFiles NOTIFY batchChanged)
    Q_PROPERTY(int batchPage READ batchPage NOTIFY batchChanged)
    Q_PROPERTY(bool batchHasNext READ batchHasNext NOTIFY batchChanged)
    Q_PROPERTY(QString localAvatar READ localAvatar NOTIFY peersChanged)
    Q_PROPERTY(QObject *server READ server CONSTANT)
    Q_PROPERTY(QString receivedTextPage READ receivedTextPage NOTIFY receivedTextPageChanged)
    Q_PROPERTY(
        QString receivedTextPosition READ receivedTextPosition NOTIFY receivedTextPageChanged)
    Q_PROPERTY(
        bool receivedTextHasPrevious READ receivedTextHasPrevious NOTIFY receivedTextPageChanged)
    Q_PROPERTY(bool receivedTextHasNext READ receivedTextHasNext NOTIFY receivedTextPageChanged)
    Q_PROPERTY(bool receivedTextPaged READ receivedTextPaged NOTIFY receivedTextPageChanged)
    Q_PROPERTY(int receivedTextPageCount READ receivedTextPageCount NOTIFY receivedTextPageChanged)
  public:
    // 日期：2026-11-07；初始化独立设置/历史与发现接收入口，并读取剪贴板初始可用状态。
    Controller(quint16 port, QObject *parent = nullptr,
               const QString &storageDirectory = QString());
    // 日期：2026-11-04；等待工作线程收尾后关闭历史连接。
    ~Controller() override;
    // 日期：2026-11-04；返回有界设备列表。
    QVariantList peers() const;
    // 日期：2026-11-04；独立服务器页面使用共用生产核心，保留旧版设备页排版与状态。
    QObject *server() const;
    // 日期：2026-11-04；仅加载最近 100 条记录，历史数据存磁盘。
    QVariantList history() const;
    // 日期：2026-11-04；返回当前用户可见状态。
    QString status() const;
    // 日期：2026-11-04；使用平台标准下载目录或已保存设置。
    QString outputDirectory() const;
    // 日期：2026-11-04；返回已保存主题色。
    QString themeColor() const;
    // 日期：2026-11-04；返回用户名称，默认使用系统环境。
    QString username() const;
    // 日期：2026-11-04；读取已规范化的本机头像，避免 QML 解码任意文件。
    QString localAvatar() const;
    // 日期：2026-11-04；选择并保存有限大小的头像，三平台使用相同图像检查。
    Q_INVOKABLE void chooseAvatar();
    // 日期：2026-11-04；按网卡枚举 IPv4/IPv6 地址及作用域供用户手动连接。
    QString addresses() const;
    // 日期：2026-11-04；反映实际活动工作线程，防止重复发送。
    bool busy() const;
    // 日期：2026-11-04；返回实际字节进度。
    double progress() const;
    // 日期：2026-11-04；首次说明由独立配置控制，不修改原版设置。
    bool termsAccepted() const;
    // 日期：2026-11-07；返回缓存的空值状态，频繁进度查询不读取系统剪贴板正文。
    bool clipboardAvailable() const;
    // 日期：2026-11-04；读取独立保存的更新源，默认不请求外部站点。
    QString updateEndpoint() const;
    // 日期：2026-11-04；返回版本检查的实际结果或错误。
    QString updateMessage() const;
    // 日期：2026-11-04；只有经有效描述确认较新版本时允许打开发布页。
    bool updateAvailable() const;
    // 日期：2026-11-04；保存用户输入并异步检查受限版本描述。
    Q_INVOKABLE void checkUpdates(const QString &endpoint);
    // 日期：2026-11-04；用户显式打开经验证的 HTTPS 发布页面。
    Q_INVOKABLE void openUpdatePage();
    // 日期：2026-11-04；批次明细只保留当前 100 项，按序号翻页。
    QVariantList batchFiles() const;
    // 日期：2026-11-04；返回当前明细页的零基页码。
    int batchPage() const;
    // 日期：2026-11-04；明细不足一页时禁用下一页。
    bool batchHasNext() const;
    // 日期：2026-11-04；读取指定页，数据库异常显示错误并保持可恢复状态。
    Q_INVOKABLE void changeBatchPage(int page);
    // 日期：2026-11-04；按记录 ID 按需读取文本，避免把历史正文全部载入 QML。
    Q_INVOKABLE void openHistory(const QString &id);
    // 日期：2026-11-04；保存首次说明确认状态。
    Q_INVOKABLE void acceptTerms();
    // 日期：2026-11-04；弹出原生文件选择器并发送用户选定文件。
    Q_INVOKABLE void sendFiles(const QString &host, int port);
    // 日期：2026-11-04；弹出目录选择器并流式发送文件夹。
    Q_INVOKABLE void sendFolder(const QString &host, int port);
    // 日期：2026-11-07；转换前核对UTF-8上限及临时授信，返回是否实际启动，失败保留编辑草稿。
    Q_INVOKABLE bool sendText(const QString &host, int port, const QString &text);
    // 日期：2026-11-04；获取当前剪贴板文本并复用文本发送。
    Q_INVOKABLE void sendClipboard(const QString &host, int port);
    // 日期：2026-11-04；用户显式复制收到的文本。
    Q_INVOKABLE void copyText(const QString &text);
    // 日期：2026-11-06；只在QML清空只读文本后释放显示正文额度，关闭窗口和取消均可调用。
    Q_INVOKABLE void releaseReceivedText();
    // 日期：2026-11-06；每页至多16384码元/512换行，不把完整正文交给Qt文档布局。
    QString receivedTextPage() const;
    // 日期：2026-11-06；面向用户返回当前页/总页数，完整内容始终可翻阅和复制。
    QString receivedTextPosition() const;
    // 日期：2026-11-06；当前页有前一页时允许后退。
    bool receivedTextHasPrevious() const;
    // 日期：2026-11-06；当前页有后一页时允许前进。
    bool receivedTextHasNext() const;
    // 日期：2026-11-06；仅多页正文显示分页导航，普通短文本保持原排版。
    bool receivedTextPaged() const;
    // 日期：2026-11-06；实际显示页数，不含结束位置哨兵；关闭后为0。
    int receivedTextPageCount() const;
    // 日期：2026-11-06；按相对页偏移移动，越界请求拒绝且不改变当前文本。
    Q_INVOKABLE void changeReceivedTextPage(int delta);
    // 日期：2026-11-06；有选区复制本页选区，否则复制完整原文，包含未显示的所有页。
    Q_INVOKABLE void copyReceivedText(const QString &selection = QString());
    // 日期：2026-11-04；隐藏主窗口后捕获屏幕，保存为任务临时 JPEG 并发送。
    Q_INVOKABLE void sendScreenshot(const QString &host, int port);
    // 日期：2026-11-04；从 QML DropArea 提取本地文件，不接受远程 URL。
    Q_INVOKABLE bool sendDropped(const QString &host, int port, const QList<QUrl> &urls);
    // 日期：2026-11-04；仅在空闲时切换接收目录，保留现有数据。
    Q_INVOKABLE void chooseOutputDirectory();
    // 日期：2026-11-07；返回当前实例本地白名单诊断，不读取用户正文或主动连接对端。
    Q_INVOKABLE QVariantMap diagnostics();
    // 日期：2026-11-07；共用原子导出供测试与原生选择器使用，失败保留已有文件并显示建议。
    Q_INVOKABLE bool exportDiagnosticsTo(const QUrl &destination);
    // 日期：2026-11-07；用户选择新JSON文件后才执行本地导出，不自动上传。
    Q_INVOKABLE void chooseDiagnosticReport();
    // 日期：2026-11-04；打开存在的文件或目录，失败显示可操作的状态。
    Q_INVOKABLE void openPath(const QString &path);
    // 日期：2026-11-04；保存有效主题色，并立即更新界面。
    Q_INVOKABLE void setThemeColor(const QString &color);
    // 日期：2026-11-04；通过原生颜色选择器选择自定义主题色。
    Q_INVOKABLE void chooseThemeColor();
    // 日期：2026-11-04；限制并保存用户名，同时重新发布发现签名。
    Q_INVOKABLE void setUsername(const QString &name);
    // 日期：2026-11-04；取消本窗口的发送或接收任务。
    Q_INVOKABLE void cancel();
    // 日期：2026-11-04；刷新广播发现与地址列表。
    Q_INVOKABLE void refresh();
  signals:
    void stateChanged();
    // 日期：2026-11-07；正文是否为空改变时单独通知，不复用传输进度通知。
    void clipboardAvailabilityChanged();
    void peersChanged();
    void historyChanged();
    void textReceived(const QString &text);
    void receivedTextOpened();
    void receivedTextPageChanged();
    void captureVisibility(bool visible);
    void batchChanged();
    void batchOpened();

  private:
    // 日期：2026-11-07；仅初始化或实际剪贴板变化时读取一次正文，只保留布尔状态。
    void refreshClipboardAvailability();
    // 日期：2026-11-04；在唯一发送任务槽位中启动工作线程。
    void start(dukto::LegacyRequest request);
    // 日期：2026-11-04；根据工作线程事件更新界面，不在主线程读取文件正文。
    void onEvent(const QJsonObject &event);
    // 日期：2026-11-04；持久化真实完成结果并刷新最近记录。
    void onResult(int code, const dukto::LegacyResult &result);
    // 日期：2026-11-04；从数据库重新加载一页历史，限制内存模型规模。
    void loadHistory();
    // 日期：2026-11-06；扫描有界正文建立分页位置，不拆Unicode代理对；接管共享额度后同步通知显示。
    void displayReceivedText(QString text, std::shared_ptr<dukto::BufferCredit> credit);
    // 日期：2026-11-04；在端口转换前统一验证地址，错误直接反馈给界面。
    bool prepareRequest(dukto::LegacyRequest &request, const QString &host, int port);
    quint16 diagnosticPort_ = 4644;
    QSettings settings_;
    ServerPanel server_;
    dukto::Discovery discovery_;
    Avatars avatars_;
    dukto::Updates updates_;
    QString updateMessage_;
    QUrl updatePage_;
    QString batchCatalog_;
    QString batchTask_;
    QVariantList batchFiles_;
    int batchPage_ = 0;
    bool batchHasNext_ = false;
    dukto::LegacyListener *listener_ = nullptr;
    dukto::LegacyJob *sender_ = nullptr;
    struct HistoryConnection;
    std::unique_ptr<HistoryConnection> historyConnection_;
    QVariantList history_;
    std::shared_ptr<dukto::BufferCredit> displayedTextCredit_;
    QString displayedText_;
    QVector<int> displayedTextPages_;
    int displayedTextPage_ = 0;
    QString status_;
    double progress_ = 0;
    bool receiving_ = false;
    bool capturePending_ = false;
    bool clipboardAvailable_ = false;
    std::unique_ptr<QTemporaryDir> captureDirectory_;
};

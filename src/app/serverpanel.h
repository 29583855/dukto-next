#pragma once

#include "core/service.h"
#include <QJsonObject>
#include <QMutex>
#include <QObject>
#include <QThread>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

class ServerAction final : public QThread {
    Q_OBJECT
  public:
    // 日期：2026-11-04；后台操作仅持有不可变参数，TLS/数据库在其工作线程中创建和销毁。
    ServerAction(QString directory, QString operation, QVariantMap options, QObject *parent);
    // 日期：2026-11-04；退出时只设置取消原子量，资源由所属线程清理。
    void cancel();
    // 日期：2026-11-04；最多保留一条进度快照，十万文件不能堆积 Qt 跨线程事件。
    QJsonObject takeProgress();
    // 日期：2026-11-04；完成后等待线程同步，读取一次最终结果和真实退出码。
    QJsonObject result() const;
    // 日期：2026-11-04；完成后返回规范退出码，查询成功不代表文件任务完成。
    int code() const;
    // 日期：2026-11-04；析构等待本操作清理，不遗留后台文件或网络对象。
    ~ServerAction() override;

  protected:
    // 日期：2026-11-04；GUI 直接调用与 CLI 相同的身份/授权/传输核心，不启动隐藏 CLI 子进程。
    void run() override;

  private:
    // 日期：2026-11-04；主线程定时取走单槽进度；绝不保留凭据或整个文件结果数组。
    void progress(const QJsonObject &event);
    QString directory_;
    QString operation_;
    QVariantMap options_;
    std::atomic_bool cancelled_{false};
    QMutex mutex_;
    QJsonObject progress_;
    QJsonObject result_;
    int code_ = 0;
};

class ServerPanel final : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool controlBusy READ controlBusy NOTIFY changed)
    Q_PROPERTY(bool serving READ serving NOTIFY changed)
    Q_PROPERTY(QString status READ status NOTIFY changed)
    Q_PROPERTY(QString directory READ directory CONSTANT)
    Q_PROPERTY(QVariantMap identity READ identity NOTIFY changed)
    Q_PROPERTY(QVariantMap task READ task NOTIFY changed)
    Q_PROPERTY(QVariantList entries READ entries NOTIFY changed)
    Q_PROPERTY(QString listingKind READ listingKind NOTIFY changed)
    Q_PROPERTY(QVariantMap outcome READ outcome NOTIFY changed)
    Q_PROPERTY(QVariantList tasks READ tasks NOTIFY changed)
    Q_PROPERTY(QString tasksAfter READ tasksAfter NOTIFY changed)
    Q_PROPERTY(bool tasksMore READ tasksMore NOTIFY changed)
    Q_PROPERTY(QString cursor READ cursor NOTIFY changed)
    Q_PROPERTY(QVariantList clients READ clients NOTIFY changed)
    Q_PROPERTY(QString clientsAfter READ clientsAfter NOTIFY changed)
    Q_PROPERTY(bool clientsMore READ clientsMore NOTIFY changed)
    Q_PROPERTY(int sessionSeconds READ sessionSeconds NOTIFY changed)
    Q_PROPERTY(QVariantMap itemPage READ itemPage NOTIFY changed)
  public:
    // 日期：2026-11-04；独立保存服务器资料/接收日志，保留原版设备页与接收配置。
    explicit ServerPanel(const QString &directory, QObject *parent = nullptr);
    // 日期：2026-11-04；统一取消操作、停止监听并等待资源释放后才允许 GUI 退出。
    ~ServerPanel() override;
    // 日期：2026-11-04；反映实际数据/配置工作线程，不含独立控制请求槽位。
    bool busy() const;
    // 日期：2026-11-04；暂停/取消/查询使用独立有界槽位，数据忙时仍可操作。
    bool controlBusy() const;
    // 日期：2026-11-04；返回当前本地 TLS 监听器是否正在监听。
    bool serving() const;
    // 日期：2026-11-04；显示最后实际操作事件或错误，不根据按钮点击推断完成。
    QString status() const;
    // 日期：2026-11-04；本机 CLI 可用同一状态目录访问 GUI 保存的服务和资料。
    QString directory() const;
    // 日期：2026-11-04；仅公开服务器 UUID/证书指纹，不把私钥或令牌放入 QML。
    QVariantMap identity() const;
    // 日期：2026-11-04；保留最近实际任务状态，原请求/任务 UUID 可供继续操作。
    QVariantMap task() const;
    // 日期：2026-11-04；只保留一页至多 100 项远程目录或本地共享配置。
    QVariantList entries() const;
    // 日期：2026-11-04；区分远程目录与本机共享，防止旧列表被另一页面误当作可下载内容。
    QString listingKind() const;
    // 日期：2026-11-04；保留最后公开结果供界面选择，不包含配对秘密。
    QVariantMap outcome() const;
    // 日期：2026-11-04；只保留当前任务页，重启后重新认证向服务器找回记录。
    QVariantList tasks() const;
    // 日期：2026-11-04；返回任务下一页起始序号，不与目录浏览游标混用。
    QString tasksAfter() const;
    // 日期：2026-11-04；只有服务器明确还有记录时启用任务下一页。
    bool tasksMore() const;
    // 日期：2026-11-04；下一页游标绑定当前授权目录，交由核心校验。
    QString cursor() const;
    // 日期：2026-11-05；本机服务主体独立一页，不与远程目录/共享列表互相覆盖。
    QVariantList clients() const;
    // 日期：2026-11-05；本地主体下一页使用规范 UUID 游标。
    QString clientsAfter() const;
    // 日期：2026-11-05；是否还能读取本机主体下一页，由核心明确返回。
    bool clientsMore() const;
    // 日期：2026-11-05；本机新认证连接的会话时长，收到实际策略事件后才更新。
    int sessionSeconds() const;
    // 日期：2026-11-05；只保留一页逐项证据及其任务/资料身份，不随翻页累积结果。
    QVariantMap itemPage() const;
    // 日期：2026-11-04；执行显式用户动作，额外控制槽使活动传输可被暂停/取消。
    Q_INVOKABLE void execute(const QString &operation, const QVariantMap &options);
    // 日期：2026-11-04；启动/停止本机 TLS 服务，不自动共享用户目录或开放 R6 接收。
    Q_INVOKABLE void setServing(bool enabled, const QString &address, int port);
    // 日期：2026-11-04；打开原生选择器，GUI 操作取消时不启动传输。
    Q_INVOKABLE void chooseUpload(const QVariantMap &options, bool folder);
    // 日期：2026-11-04；返回用户显式选择的目录，取消返回空字符串。
    Q_INVOKABLE QString chooseDirectory();
    // 日期：2026-11-04；选择受保护配对文件，仅把文件路径展示给用户。
    Q_INVOKABLE QString chooseCredential();
    // 日期：2026-11-04；主动断开当前操作保留可恢复检查点，不等同于服务任务取消。
    Q_INVOKABLE void disconnectTransfer();
  signals:
    void changed();

  private:
    // 日期：2026-11-04；主线程合并实际快照，界面只显示最后一页/状态，不累计逐文件列表。
    void accept(const QJsonObject &event, int code = 0);
    QString directory_;
    QString status_;
    QJsonObject identity_;
    QJsonObject task_;
    QJsonArray entries_;
    QString listingKind_;
    QJsonObject outcome_;
    QJsonArray tasks_;
    QString tasksAfter_ = "0";
    bool tasksMore_ = false;
    QString cursor_;
    QJsonArray clients_;
    QString clientsAfter_;
    bool clientsMore_ = false;
    int sessionSeconds_ = 86400;
    QJsonObject itemPage_;
    ServerAction *action_ = nullptr;
    ServerAction *control_ = nullptr;
    // 日期：2026-11-08；析构体先停止监听器及工作线程，成员随后才归还同域共享资格。
    std::shared_ptr<dukto::PrivateStore> listenerState_;
    dukto::ServiceListener *listener_ = nullptr;
    QTimer timer_;
};

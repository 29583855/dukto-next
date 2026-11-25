#pragma once
#include <QObject>
#include <QTimer>
class Controller;
class ServerPanel;
// 日期：2026-11-25；根据实际任务管理限时后台资格，空闲后台立即关闭网络。
class MobileLifecycle final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString message READ message NOTIFY changed)
  public:
    // 日期：2026-11-25；只在前台启动Android服务，iOS仅申请有限收尾时间。
    explicit MobileLifecycle(Controller &controller, QObject *parent = nullptr);
    // 日期：2026-11-25；向界面公开实际系统服务或收尾状态。
    QString message() const;
    // 日期：2026-11-25；退出时解除服务、系统任务和所有网络活动。
    ~MobileLifecycle() override;
  signals:
    void changed();

  private:
    // 日期：2026-11-25；轮询系统停止请求，收尾后及时结束后台资格。
    void update();
    Controller &controller_;
    ServerPanel *server_;
    QTimer timer_;
    bool foreground_ = true;
    bool started_ = false;
    bool updating_ = false;
    bool hiddenCleanupRequested_ = false;
    bool serviceSuppressed_ = false;
    QString message_;
};

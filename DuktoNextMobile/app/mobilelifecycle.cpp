#include "mobilelifecycle.h"
#include "controller.h"
#include "platformfiles.h"
#include "serverpanel.h"
#include <QGuiApplication>
#include <QScopedValueRollback>

// 日期：2026-11-25；Qt活动状态由一个协调器处理，选择器导致的Inactive不算隐藏。
MobileLifecycle::MobileLifecycle(Controller &controller, QObject *parent)
    : QObject(parent), controller_(controller),
      server_(qobject_cast<ServerPanel *>(controller.server())) {
    connect(qGuiApp, &QGuiApplication::applicationStateChanged, this,
            [this](Qt::ApplicationState state) {
                if (state == Qt::ApplicationActive)
                    foreground_ = true;
                else if (state == Qt::ApplicationHidden || state == Qt::ApplicationSuspended)
                    foreground_ = false;
                update();
            });
    connect(&controller_, &Controller::stateChanged, this, &MobileLifecycle::update);
    connect(server_, &ServerPanel::changed, this, &MobileLifecycle::update);
    timer_.setInterval(250);
    connect(&timer_, &QTimer::timeout, this, &MobileLifecycle::update);
    timer_.start();
}
// 日期：2026-11-25；返回实际策略提示，不能将后台资格当作任务成功。
QString MobileLifecycle::message() const {
    return message_;
}
// 日期：2026-11-25；宿主销毁前先关闭网络，避免后台服务独立空转。
MobileLifecycle::~MobileLifecycle() {
    timer_.stop();
    controller_.setForeground(false);
    mobile::setBackgroundTransfer(false);
    mobile::endBackgroundCleanup();
}
// 日期：2026-11-25；Android仅为既有活动任务保活，iOS取消任务并利用有限时间保存状态。
void MobileLifecycle::update() {
    if (updating_)
        return;
    QScopedValueRollback<bool> guard(updating_, true);
    const auto old = message_;
    bool working = controller_.busy() || (server_ && server_->networkBusy());
#ifdef Q_OS_ANDROID
    if (mobile::takeBackgroundStop()) {
        controller_.setForeground(false);
        started_ = false;
        serviceSuppressed_ = true;
        message_ = QStringLiteral("后台传输服务已停止；Next任务请查询后恢复，R6请重试");
        if (foreground_)
            controller_.setForeground(true);
        working = false;
    }
    if (!working)
        serviceSuppressed_ = false;
    if (foreground_) {
        controller_.setForeground(true);
        if (working && !started_ && !serviceSuppressed_) {
            started_ = mobile::setBackgroundTransfer(true);
            message_ = started_ ? QStringLiteral("活动传输已申请通知服务；后台最长30分钟")
                                : QStringLiteral("系统拒绝后台服务，请保持应用前台传输");
        }
    } else if (!(working && started_ && mobile::backgroundTransferAlive())) {
        controller_.setForeground(false);
    }
    if (!working && started_) {
        mobile::setBackgroundTransfer(false);
        started_ = false;
        message_ = foreground_ ? QString() : QStringLiteral("后台无活动任务，已停止监听和服务");
    }
#else
    if (foreground_)
        hiddenCleanupRequested_ = false;
    if (!foreground_ && !hiddenCleanupRequested_) {
        hiddenCleanupRequested_ = true;
        mobile::beginBackgroundCleanup();
        started_ = true;
    }
    controller_.setForeground(foreground_);
    if (started_ && (foreground_ || !(controller_.busy() || (server_ && server_->networkBusy())))) {
        mobile::endBackgroundCleanup();
        started_ = false;
    }
    message_ = foreground_ ? QString() : QStringLiteral("应用进入后台，传输已停止并保留可恢复状态");
#endif
    if (old != message_)
        emit changed();
}

#pragma once

#include <QTcpServer>

namespace dukto {
class TcpListener : public QTcpServer {
  public:
    // 日期：2026-11-06；同一适配器用于传输、TLS服务和头像，Windows在绑定前申请端口独占。
    explicit TcpListener(QObject *parent = nullptr);
    // 日期：2026-11-06；冲突必须失败；Any保留双栈，其余平台使用Qt已有的监听实现。
    bool listen(const QHostAddress &address = QHostAddress::Any, quint16 port = 0);
    // 日期：2026-11-06；原生绑定失败也保留具体系统错误，不返回Qt尚未执行listen的旧状态。
    QString errorString() const;
    // 日期：2026-11-06；公开原生失败类别，与errorString及listen返回值保持一致。
    QAbstractSocket::SocketError serverError() const;

  private:
    QString nativeError_;
    QAbstractSocket::SocketError nativeCode_ = QAbstractSocket::UnknownSocketError;
};
} // namespace dukto

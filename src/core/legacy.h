#pragma once

#include "tcplistener.h"
#include <QElapsedTimer>
#include <QJsonObject>
#include <QThread>
#include <atomic>
#include <memory>

namespace dukto {
class Catalog;
class BufferCredit;

// 日期：2026-11-06；正文、校验和JSON输出共用进程数据额度；超限或繁忙在文本分配前拒绝。
std::shared_ptr<BufferCredit> legacyTextCredit(qint64 bytes);

class LegacyResult final {
  public:
    // 日期：2026-11-06；空结果供Qt元类型默认构造，不包含正文或额度。
    LegacyResult() = default;
    // 日期：2026-11-06；复制先取得同一令牌，再共享JSON；不新增额度或深拷贝正文。
    LegacyResult(const LegacyResult &) = default;
    // 日期：2026-11-06；交换后旧JSON和旧令牌在临时对象中一起析构，赋值不提前归还额度。
    LegacyResult &operator=(LegacyResult other);
    // 日期：2026-11-06；只读业务结果；调用方的跨事件保存须同时保留本值对象或textCredit。
    const QJsonObject &json() const;
    // 日期：2026-11-06；GUI保存显示正文时保留同一令牌，复制值对象不重复申请额度。
    std::shared_ptr<BufferCredit> textCredit() const;

  private:
    friend class LegacyJob;
    // 日期：2026-11-06；结果和额度组成不可拆开的排队信号值，最后一个所有者释放时归还。
    LegacyResult(QJsonObject json, std::shared_ptr<BufferCredit> credit);
    std::shared_ptr<BufferCredit> credit_;
    QJsonObject json_;
};

struct LegacyRequest {
    QString host;
    quint16 port = 4644;
    QStringList paths;
    QByteArray text;
    bool textMode = false;
    QString output;
    qintptr descriptor = -1;
    int timeoutMs = 30000;
    QString catalogPath;
};

class LegacyJob final : public QThread {
    Q_OBJECT
  public:
    // 日期：2026-11-04；请求只含值类型，网络与文件对象在工作线程创建并释放。
    explicit LegacyJob(LegacyRequest request, QObject *parent = nullptr);
    // 日期：2026-11-04；取消并等候固定轮询周期收尾，防止销毁运行中的线程。
    ~LegacyJob() override;
    // 日期：2026-11-04；原子取消不跨线程操作 socket。
    void cancel();
  signals:
    void event(const QJsonObject &event);
    void result(int exitCode, const dukto::LegacyResult &result);

  protected:
    // 日期：2026-11-04；选择兼容发送/接收流程并统一报告所有异常。
    void run() override;

  private:
    // 日期：2026-11-04；发送 R6 单连接帧，不添加不兼容的摘要或确认消息。
    QJsonObject send();
    // 日期：2026-11-04；按声明数量接收并校验长度，使用临时文件避免截断原文件。
    QJsonObject receive();
    LegacyRequest request_;
    std::atomic_bool cancelled_{false};
    std::unique_ptr<Catalog> catalog_;
    QString taskId_;
    std::shared_ptr<BufferCredit> textCredit_;
    qint64 receivedBytes_ = 0;
    QElapsedTimer elapsed_;
};

class LegacyListener final : public TcpListener {
    Q_OBJECT
  public:
    // 日期：2026-11-04；使用显式接收目录与有限活动任务数。
    LegacyListener(QString output, int timeoutMs, QObject *parent = nullptr,
                   const QString &catalogPath = QString());
    // 日期：2026-11-04；停止接收并等待现有任务完成取消，不能泄露工作线程。
    ~LegacyListener() override;
    // 日期：2026-11-04；转发取消请求到活动接收任务，保持监听端口可复用。
    void cancel();
    // 日期：2026-11-04；仅空闲监听器可修改接收目录，保持已绑定端口不变。
    bool setOutput(const QString &output);
  signals:
    void event(const QJsonObject &event);
    void result(int exitCode, const dukto::LegacyResult &result);

  protected:
    // 日期：2026-11-04；将描述符交给工作线程，不在 GUI/监听线程阻塞读取。
    void incomingConnection(qintptr descriptor) override;

  private:
    QString output_;
    int timeoutMs_;
    QString catalogPath_;
    LegacyJob *active_ = nullptr;
};
} // namespace dukto

Q_DECLARE_METATYPE(dukto::LegacyResult)

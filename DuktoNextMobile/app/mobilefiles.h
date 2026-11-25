#pragma once

#include "platformfiles.h"
#include <QEventLoop>
#include <QObject>
#include <QVariantList>
#include <QVariantMap>

// 日期：2026-11-25；协调原生提供器与应用沙箱选择器，复用控制器时阻止重入。
class MobileFiles final : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(QString message READ message NOTIFY changed)
    Q_PROPERTY(QString documents READ documents CONSTANT)
  public:
    // 日期：2026-11-25；创建应用可见文件目录，认证与状态数据库仍留私有AppData目录。
    explicit MobileFiles(QObject *parent = nullptr);
    // 日期：2026-11-25；全局入口仅由移动宿主在控制器之前创建。
    static MobileFiles *instance();
    // 日期：2026-11-25；读取当前导入/导出状态供触屏界面显示。
    bool busy() const;
    // 日期：2026-11-25；返回最新提供器错误或实际完成消息。
    QString message() const;
    // 日期：2026-11-25；仅公开用户文件目录，不向QML公开认证资料目录。
    QString documents() const;
    // 日期：2026-11-25；导入文件返回独立沙箱副本，调用方在传输完成前持有路径。
    QStringList importFiles();
    // 日期：2026-11-25；目录通过系统授权后复制，当前共享的是该次快照。
    QString importFolder();
    // 日期：2026-11-25；头像或配对文件必须恰好选择一项。
    QString importSingle();
    // 日期：2026-11-25；在应用文档目录内选择可读写路径，不授予任意私有状态目录。
    QString chooseDirectory(const QString &title);
    // 日期：2026-11-25；诊断先写入沙箱，再使用系统导出选择器。
    QString diagnosticPath() const;
    // 日期：2026-11-25；按名称游标分页，最多保留513个候选，目录规模不决定内存用量。
    Q_INVOKABLE QVariantMap entries(const QString &directory,
                                    const QString &after = QString()) const;
    // 日期：2026-11-25；目录选择完成后验证规范路径，再解除调用者等待。
    Q_INVOKABLE void finishDirectory(const QString &path);
    // 日期：2026-11-25；将系统文件导入用户目录，冲突失败而不覆盖原件。
    Q_INVOKABLE void importIntoDocuments(bool folder);
    // 日期：2026-11-25；显式导出已收文件；路径必须属于用户文档或诊断导出目录。
    Q_INVOKABLE void exportPath(const QString &path);
    // 日期：2026-11-25；仅在所选用户目录创建一个普通子目录，拒绝非法名称。
    Q_INVOKABLE bool createDirectory(const QString &parent, const QString &name);
    // 日期：2026-11-25；移动主题通过可触摸预设色板选择。
    void chooseColor();
    // 日期：2026-11-25；系统退出时撤销选择器并解除目录等待。
    void cancelOperation();
  signals:
    void changed();
    void directoryRequested(const QString &title);
    void colorRequested();

  private:
    // 日期：2026-11-25；单次选择操作的事件循环允许界面刷新，禁止再次打开选择器。
    QStringList select(bool folder);
    // 日期：2026-11-25；校验用户可见路径的真实归属，拒绝符号链接逃逸。
    bool insideDocuments(const QString &path) const;
    static MobileFiles *instance_;
    QString documents_;
    QString message_;
    bool busy_ = false;
    QEventLoop *directoryWaiter_ = nullptr;
    QString selectedDirectory_;
};

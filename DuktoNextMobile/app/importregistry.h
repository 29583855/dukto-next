#pragma once

#include <QJsonObject>
#include <QStringList>
#include <QUuid>

// 日期：2026-11-25；将移动上传的沙箱源与请求持久绑定，清理与导入共用预算锁。
class ImportRegistry final {
  public:
    // 日期：2026-11-25；仅接受已存在且非符号链接的私有导入根。
    explicit ImportRegistry(QString root);
    // 日期：2026-11-25；首次保存原路径，重试恢复同一绑定，拒绝改换来源或目标。
    bool resolve(const QUuid &request, const QJsonObject &binding, QStringList &paths,
                 QString &error) const;
    // 日期：2026-11-25；服务确认完成后释放引用，文件由后续显式清理回收。
    bool release(const QUuid &request, QString &error) const;
    // 日期：2026-11-25；记录本次启动前已有的批次，本次会话新导入的文件不能被清理。
    QStringList existingBatches() const;
    // 日期：2026-11-25；只清理启动前且无上传引用的直接子批次，遇损坏引用即停止。
    bool clean(const QStringList &eligible, int &removed, QString &error) const;

  private:
    // 日期：2026-11-25；拒绝链接、特殊文件与越界路径，返回所归属的导入批次。
    QString batch(const QString &path, bool requireExists) const;
    // 日期：2026-11-25；安全读取有限JSON，拒绝链接和超限元数据。
    bool read(const QString &path, QJsonObject &value, QString &error) const;
    QString root_;
    QString inputRoot_;
};

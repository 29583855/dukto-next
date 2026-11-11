#pragma once

#include <QFileDialog>
#include <QSet>

class QItemSelectionModel;
class QItemSelection;

// 日期：2026-11-08；预算不足时撤销本次新增选择，避免界面保存无界路径列表。
bool constrainTransferSelection(QItemSelectionModel *selection, const QItemSelection &added,
                                const QString &directory);

// 日期：2026-11-08；以有限选择预算保留常见的文件多选工作流。
class BoundedFileDialog final : public QFileDialog {
  public:
    // 日期：2026-11-08；使用 Qt 文件视图，以便在产生超量选择时即时拒绝新增项。
    explicit BoundedFileDialog(QWidget *parent, const QString &title);
    // 日期：2026-11-11；成员销毁前断开模型回调，防止基类删除子对象时访问已释放的选择集合。
    ~BoundedFileDialog() override;

  protected:
    // 日期：2026-11-08；接受前再次按核心预算核对文件列表，避免其他输入路径绕过选择信号。
    void accept() override;

  private:
    // 日期：2026-11-08；连接当前文件视图并在用户导航后补充连接新模型。
    void observeSelectionModels();
    // 日期：2026-11-08；用户首次超过硬限制时给出明确说明。
    void showLimitWarning();
    QSet<QItemSelectionModel *> observed_;
    bool warned_ = false;
};

// 日期：2026-11-08；取消返回空列表，接受结果受对话框与核心两处同一预算约束。
QStringList chooseFilesBounded(QWidget *parent, const QString &title);

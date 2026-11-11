#include "boundedfiledialog.h"
#include "core/error.h"
#include "core/files.h"

#include <QAbstractItemView>
#include <QDir>
#include <QItemSelectionModel>
#include <QMessageBox>
#include <QTimer>

// 日期：2026-11-08；非原生对话框通过 Qt 选择模型执行有界多选。
BoundedFileDialog::BoundedFileDialog(QWidget *parent, const QString &title)
    : QFileDialog(parent, title) {
    setOption(QFileDialog::DontUseNativeDialog, true);
    setFileMode(QFileDialog::ExistingFiles);
    setAcceptMode(QFileDialog::AcceptOpen);
    QTimer::singleShot(0, this, [this]() { observeSelectionModels(); });
    connect(this, &QFileDialog::directoryEntered, this,
            [this](const QString &) { observeSelectionModels(); });
}

// 日期：2026-11-11；QFileDialog在基类析构时才删除模型，必须趁选择集合仍存活先解除其回调。
BoundedFileDialog::~BoundedFileDialog() {
    for (auto selection : observed_)
        QObject::disconnect(selection, nullptr, this, nullptr);
}

// 日期：2026-11-08；范围超限在枚举选中行或构造路径字符串前撤销本次新增选择。
bool constrainTransferSelection(QItemSelectionModel *selection, const QItemSelection &added,
                                const QString &directory) {
    qint64 count = 0;
    for (const auto &range : selection->selection()) {
        if (range.height() > dukto::MaxTransferRoots - count) {
            selection->select(added, QItemSelectionModel::Deselect);
            return false;
        }
        count += range.height();
    }
    const auto rows = selection->selectedRows(0);
    if (rows.size() > dukto::MaxTransferRoots) {
        selection->select(added, QItemSelectionModel::Deselect);
        return false;
    }
    qint64 characters = 0;
    for (const auto &row : rows) {
        const auto path = QDir(directory).absoluteFilePath(row.data().toString());
        if (path.size() > dukto::MaxTransferRootCharacters - characters) {
            selection->select(added, QItemSelectionModel::Deselect);
            return false;
        }
        characters += path.size();
    }
    return true;
}

// 日期：2026-11-08；多个 Qt 视图共享或替换选择模型时只保留有效连接。
void BoundedFileDialog::observeSelectionModels() {
    const auto views = findChildren<QAbstractItemView *>();
    for (auto view : views) {
        auto selection = view->selectionModel();
        if (!selection || observed_.contains(selection))
            continue;
        observed_.insert(selection);
        connect(selection, &QItemSelectionModel::selectionChanged, this,
                [this, selection](const QItemSelection &selected, const QItemSelection &) {
                    if (selected.isEmpty() ||
                        constrainTransferSelection(selection, selected, directory().path()))
                        return;
                    showLimitWarning();
                });
        connect(selection, &QObject::destroyed, this,
                [this, selection]() { observed_.remove(selection); });
    }
}

// 日期：2026-11-08；选择被拒绝时解释固定上限及改用目录扫描的方式。
void BoundedFileDialog::showLimitWarning() {
    if (warned_)
        return;
    warned_ = true;
    QMessageBox::warning(
        this, QStringLiteral("选择数量超过限制"),
        QStringLiteral(
            "单次最多选择 %1 个路径，路径总长度不超过 %2 个字符。请减少选择数量或改为选择目录。")
            .arg(dukto::MaxTransferRoots)
            .arg(dukto::MaxTransferRootCharacters));
}

// 日期：2026-11-08；接受前用核心校验再次限制文件名编辑框等非视图路径。
void BoundedFileDialog::accept() {
    const auto paths = selectedFiles();
    if (!paths.isEmpty()) {
        try {
            dukto::validateTransferRoots(paths);
        } catch (const dukto::Error &) {
            showLimitWarning();
            return;
        }
    }
    QFileDialog::accept();
}

// 日期：2026-11-08；保持调用方原有取消语义并避免任何未受限的静态多选 API。
QStringList chooseFilesBounded(QWidget *parent, const QString &title) {
    BoundedFileDialog dialog(parent, title);
    if (dialog.exec() != QDialog::Accepted)
        return {};
    return dialog.selectedFiles();
}

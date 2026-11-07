#include "core/error.h"
#include "core/taskstore.h"

#include <QCoreApplication>
#include <QDir>
#include <QJsonDocument>
#include <QLockFile>
#include <QTextStream>
#include <QTimer>

namespace {
// 日期：2026-11-04；测试探针只输出公开任务字段或规范错误，不接收凭据或文件正文。
void output(const QJsonObject &object) {
    QTextStream stream(stdout);
    stream.setCodec("UTF-8");
    stream << QJsonDocument(object).toJson(QJsonDocument::Compact) << '\n';
    stream.flush();
}
} // namespace

// 日期：2026-11-07；独立进程验证目录占用/任务所有权，所有锁均在普通退出或强制退出后释放。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    if (args.size() != 6 || (args[1] != "create" && args[1] != "hold" && args[1] != "init-lock" &&
                             args[1] != "state-shared" && args[1] != "state-exclusive" &&
                             args[1] != "state-shared-once" && args[1] != "state-exclusive-once"))
        return 2;
    try {
        const bool state = args[1].startsWith("state-");
        const bool exclusive = args[1].startsWith("state-exclusive");
        dukto::PrivateStore store(args[2], true,
                                  exclusive ? dukto::PrivateStore::Use::Maintenance
                                            : dukto::PrivateStore::Use::Shared);
        if (state) {
            output({{"maintenanceHeld", store.maintenance()}, {"stateHeld", true}});
            if (args[1].endsWith("-once"))
                return 0;
            QTimer::singleShot(30000, &app, &QCoreApplication::quit);
            return app.exec();
        }
        if (args[1] == "init-lock") {
            // 日期：2026-11-05；真实持有初始化锁，供多个进程同时等待后释放；不改生产锁和等待期限。
            QLockFile initialization(QDir(store.directory()).filePath("tasks-init.lock"));
            initialization.setStaleLockTime(0);
            if (!initialization.tryLock(0))
                return 4;
            output({{"initializationHeld", true}});
            QTimer::singleShot(30000, &app, &QCoreApplication::quit);
            return app.exec();
        }
        dukto::TaskStore tasks(store);
        const auto task =
            tasks.create(QUuid(args[3]), QUuid(args[4]), "download", "docs", "sample.bin", args[5]);
        if (args[1] == "create") {
            output(task.publicInfo());
            return 0;
        }
        const auto lease = tasks.acquire(task.owner, task.id);
        auto result = task.publicInfo();
        result["executionOwner"] = true;
        output(result);
        QTimer::singleShot(30000, &app, &QCoreApplication::quit);
        return app.exec();
    } catch (const dukto::Error &error) {
        output(error.json());
        return static_cast<int>(error.code);
    }
}

#include "core/error.h"
#include "core/taskstore.h"

#include <QCoreApplication>
#include <QJsonDocument>
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

// 日期：2026-11-04；独立进程测试原生私有目录、幂等竞争和进程崩溃后的任务所有权释放。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    if (args.size() != 6 || (args[1] != "create" && args[1] != "hold"))
        return 2;
    try {
        dukto::PrivateStore store(args[2], true);
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

#include "core/error.h"
#include "core/privatestore.h"

#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <atomic>
#include <iostream>
#include <thread>

// 日期：2026-11-07；隔离诊断真实私有配置原子替换与读取竞争，不触及运行中的服务状态。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    QTemporaryDir root;
    dukto::PrivateStore initial(root.filePath("state"), true);
    const QByteArray first(65536, 'a');
    const QByteArray second(65536, 'b');
    initial.write("record.json", first);
    std::atomic_bool start{false};
    std::atomic_int accepted{0}, readChanged{0}, writerChanged{0}, otherErrors{0}, invalidBytes{0};
    // 日期：2026-11-07；每个线程持有独立真实存储实例，开始信号只同步竞争窗口，不修改产品代码。
    auto reader = [&] {
        dukto::PrivateStore store(initial.directory());
        while (!start.load())
            std::this_thread::yield();
        for (int index = 0; index < 2000; ++index) {
            try {
                const auto bytes = store.read("record.json", 65536);
                if (bytes != first && bytes != second)
                    ++invalidBytes;
                ++accepted;
            } catch (const dukto::Error &error) {
                if (error.code == dukto::ExitCode::Integrity && error.stage == "read")
                    ++readChanged;
                else
                    ++otherErrors;
            }
        }
    };
    std::thread one(reader), two(reader), three(reader), four(reader);
    start.store(true);
    for (int index = 0; index < 500; ++index) {
        try {
            initial.write("record.json", index % 2 ? first : second);
        } catch (const dukto::Error &error) {
            if (error.code == dukto::ExitCode::Integrity && error.stage == "read")
                ++writerChanged;
            else
                ++otherErrors;
        }
    }
    one.join();
    two.join();
    three.join();
    four.join();
    const QJsonObject result{{"acceptedReads", accepted.load()},
                             {"replacedPrivateReadRefusals", readChanged.load()},
                             {"writerReadRefusals", writerChanged.load()},
                             {"otherErrors", otherErrors.load()},
                             {"invalidBytes", invalidBytes.load()}};
    std::cout << QJsonDocument(result).toJson(QJsonDocument::Compact).constData() << std::endl;
    return otherErrors.load() || invalidBytes.load() ? 1 : 0;
}

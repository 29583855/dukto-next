#include "core/error.h"
#include "core/privatestore.h"
#include "core/sourcefile.h"

#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <atomic>
#include <iostream>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

// 日期：2026-11-07；验证有界配置重读及严格传输源不退化，隔离目录不触及运行服务。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    QTemporaryDir root;
    dukto::PrivateStore initial(root.filePath("state"), true);
    const QByteArray first(65536, 'a');
    const QByteArray second(65536, 'b');
    initial.write("record.json", first);
    std::atomic_bool start{false};
    std::atomic_int accepted{0}, readChanged{0}, writerChanged{0}, busyReads{0}, otherErrors{0},
        invalidBytes{0};
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
                else if (error.code == dukto::ExitCode::Integrity && error.stage == "read-busy")
                    ++busyReads;
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
    // 日期：2026-11-07；普通传输源被替换或原地修改仍拒绝，不把配置重读推广到用户文件。
    int negativeChecks = 0;
    for (bool replace : {false, true}) {
        dukto::SourceFile source(initial.directory() + "/record.json");
        if (replace) {
            if (!QFile::rename(initial.directory() + "/record.json",
                               initial.directory() + "/held.json"))
                return 2;
            initial.write("record.json", first);
        } else {
            QFile changed(initial.directory() + "/record.json");
            if (!changed.open(QIODevice::Append) || changed.write("changed") != 7)
                return 2;
            changed.close();
        }
        try {
            source.verify();
        } catch (const dukto::Error &error) {
            if (error.code == dukto::ExitCode::Integrity && error.stage == "read")
                ++negativeChecks;
        }
    }
    // 日期：2026-11-07；宽权限和符号链接不属于可重试换代，必须立即拒绝。
    const auto filePath = QFile::encodeName(initial.directory() + "/record.json");
    if (::chmod(filePath.constData(), 0644) != 0)
        return 2;
    try {
        initial.read("record.json");
    } catch (const dukto::Error &error) {
        if (error.code == dukto::ExitCode::Permission)
            ++negativeChecks;
    }
    if (::chmod(filePath.constData(), 0600) != 0 ||
        !QFile::remove(initial.directory() + "/held.json") ||
        !QFile::rename(initial.directory() + "/record.json", initial.directory() + "/held.json") ||
        ::symlink("held.json", filePath.constData()) != 0)
        return 2;
    try {
        initial.read("record.json");
    } catch (const dukto::Error &error) {
        if (error.code == dukto::ExitCode::Permission)
            ++negativeChecks;
    }
    const QJsonObject result{{"acceptedReads", accepted.load()},
                             {"negativeChecksPassed", negativeChecks},
                             {"replacedPrivateReadRefusals", readChanged.load()},
                             {"writerReadRefusals", writerChanged.load()},
                             {"boundedBusyReads", busyReads.load()},
                             {"otherErrors", otherErrors.load()},
                             {"invalidBytes", invalidBytes.load()}};
    std::cout << QJsonDocument(result).toJson(QJsonDocument::Compact).constData() << std::endl;
    return otherErrors.load() || invalidBytes.load() || readChanged.load() || negativeChecks != 4
               ? 1
               : 0;
}

#include "core/error.h"
#include "core/protocol.h"
#include "core/service.h"
#include <QCoreApplication>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLockFile>
#include <QTemporaryDir>
#include <QTextStream>
#include <functional>
#include <stdexcept>

namespace {
// 日期：2026-11-26；合同不输出秘密，失败只返回固定断言说明。
void require(bool value, const char *message) {
    if (!value)
        throw std::runtime_error(message);
}
// 日期：2026-11-26；负例必须由生产边界明确拒绝，不接受静默成功。
void refuses(const std::function<void()> &action) {
    bool rejected = false;
    try {
        action();
    } catch (const dukto::Error &) {
        rejected = true;
    }
    require(rejected, "expected rejection");
}
} // namespace

// 日期：2026-11-26；直接验证原子删除、迟到配对拒绝、有界分页、取消及待轮换保护。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
        QTemporaryDir temporary;
        require(temporary.isValid(), "temporary root");
        dukto::PrivateStore store(temporary.path() + "/clients", true);
        require(dukto::listProfiles(store)["entries"].toArray().isEmpty(), "empty list");
        auto profile = dukto::prepareProfile(store, "default", "127.0.0.1", 4646, "localhost",
                                             QByteArray(32, 'x'));
        profile.paired = true;
        profile.server = QUuid::createUuid();
        dukto::saveProfile(store, profile);
        const auto raw = store.read("profile-default.json");
        const auto page = dukto::listProfiles(store);
        const auto encoded = QJsonDocument(page).toJson();
        require(page["entries"].toArray().size() == 1 && !page["more"].toBool(), "one page");
        require(!encoded.contains(profile.credential.toHex()) && !encoded.contains("credential") &&
                    !encoded.contains("pendingCredential"),
                "public whitelist");
        {
            QLockFile held(store.directory() + "/profile-default.json.lock");
            held.setStaleLockTime(0);
            require(held.tryLock(0), "hold alias lock");
            refuses([&]() { dukto::removeProfile(store, "default"); });
            refuses([&]() {
                dukto::updateProfileEndpoint(store, "default", "127.0.0.1", 4647, "localhost", 50);
            });
            require(store.read("profile-default.json") == raw, "lock preserves bytes");
        }
        auto pending = dukto::next::parseControl(raw);
        pending["pendingCredential"] = QString::fromLatin1(QByteArray(32, 'y').toHex());
        store.write("profile-default.json", dukto::next::encodeControl(pending));
        const auto pendingBytes = store.read("profile-default.json");
        refuses([&]() { dukto::removeProfile(store, "default"); });
        refuses([&]() {
            dukto::updateProfileEndpoint(store, "default", "127.0.0.1", 4647, "localhost", 50);
        });
        require(store.read("profile-default.json") == pendingBytes, "pending preserved");
        store.write("profile-default.json", raw);
        const auto removed = dukto::removeProfile(store, "default");
        require(removed["event"] == "profile-deleted" && !removed["serverRevoked"].toBool() &&
                    !store.exists("profile-default.json"),
                "local delete only");
        refuses([&]() { dukto::saveProfile(store, profile); });
        require(!store.exists("profile-default.json"), "late pair cannot resurrect");
        auto replacement = dukto::prepareProfile(store, "default", "127.0.0.1", 4646, "localhost",
                                                 QByteArray(32, 'x'));
        refuses([&]() { dukto::saveProfile(store, profile); });
        require(dukto::loadProfile(store, "default").client == replacement.client,
                "late pair cannot overwrite new record");
        dukto::removeProfile(store, "default");
        for (int index = 200; index >= 0; --index)
            dukto::prepareProfile(store, QString("p%1").arg(index, 3, 10, QChar('0')), "127.0.0.1",
                                  4646, "localhost", QByteArray(32, 'x'));
        QJsonArray all;
        QString after;
        int pages = 0;
        do {
            const auto result = dukto::listProfiles(store, after);
            const auto entries = result["entries"].toArray();
            require(entries.size() <= 100 && !entries.isEmpty(), "bounded nonempty page");
            for (const auto &item : entries) {
                const auto alias = item.toObject()["profile"].toString();
                require(alias > after, "strict ordered cursor");
                after = alias;
                all.append(item);
            }
            require(result["after"].toString() == after, "cursor matches page");
            ++pages;
            if (!result["more"].toBool())
                break;
            require(pages < 4, "pagination terminates");
        } while (true);
        require(all.size() == 201 && pages == 3, "all records exactly once");
        require(dukto::listProfiles(store, "p200")["entries"].toArray().isEmpty(), "last cursor");
        refuses([&]() { dukto::listProfiles(store, "../escape"); });
        refuses([&]() { dukto::removeProfile(store, "../escape"); });
        std::atomic_bool cancelled{true};
        refuses([&]() { dukto::listProfiles(store, {}, &cancelled); });
        // 日期：2026-11-26；无关文件同样计入扫描预算，不能借筛选绕过有界遍历。
        for (int index = 0; index < 4097; ++index)
            store.write(QString("unrelated-%1.json").arg(index), "{}");
        refuses([&]() { dukto::listProfiles(store); });
        QTextStream(stdout) << "{\"passed\":true,\"records\":201,\"pages\":3,"
                               "\"publicWhitelist\":true,\"aliasLock\":true,"
                               "\"pendingRotationProtected\":true,\"latePairRejected\":true,"
                               "\"cancelledQueryRejected\":true,\"scanBudgetEnforced\":true}\n";
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}

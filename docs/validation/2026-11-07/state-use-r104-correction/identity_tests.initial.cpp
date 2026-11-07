#include "core/auth.h"
#include "core/error.h"
#include "core/identity.h"
#include "core/protocol.h"
#include "core/service.h"
#include "core/sessionpolicy.h"

#include <QDir>
#include <QJsonDocument>
#include <QLockFile>
#include <QTemporaryDir>
#include <QtTest>

class IdentityTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-07；同进程共享/独占互斥、异常后释放及保留锁键保护，不改变真实任务或用户文件。
    void stateDirectoryUseGuard() {
        QTemporaryDir root;
        const auto directory = root.filePath("state");
        {
            dukto::PrivateStore first(directory, true);
            first.write("record.json", "preserve");
            QVERIFY(!first.maintenance());
            dukto::PrivateStore second(directory);
            QCOMPARE(second.read("record.json"), QByteArray("preserve"));
            QVERIFY_EXCEPTION_THROWN(
                dukto::PrivateStore(directory, false, dukto::PrivateStore::Use::Maintenance),
                dukto::Error);
            for (const auto &key : {QString("state-use.lock"), QString("STATE-USE.LOCK")}) {
                QVERIFY_EXCEPTION_THROWN(first.read(key), dukto::Error);
                QVERIFY_EXCEPTION_THROWN(first.write(key, ""), dukto::Error);
                QVERIFY_EXCEPTION_THROWN(first.remove(key), dukto::Error);
                QVERIFY_EXCEPTION_THROWN(first.exists(key), dukto::Error);
                QVERIFY_EXCEPTION_THROWN(first.validateFile(key), dukto::Error);
            }
            QCOMPARE(first.read("record.json"), QByteArray("preserve"));
        }
        {
            dukto::PrivateStore exclusive(directory, false, dukto::PrivateStore::Use::Maintenance);
            QVERIFY(exclusive.maintenance());
            QVERIFY_EXCEPTION_THROWN(dukto::PrivateStore(directory), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(
                dukto::PrivateStore(directory, false, dukto::PrivateStore::Use::Maintenance),
                dukto::Error);
            QCOMPARE(exclusive.read("record.json"), QByteArray("preserve"));
        }
        dukto::PrivateStore restored(directory);
        QCOMPARE(restored.read("record.json"), QByteArray("preserve"));
        QCOMPARE(QFileInfo(directory + "/state-use.lock").size(), qint64(0));
    }
    // 日期：2026-11-05；错误确认/非法期限/锁占用/损坏材料不得覆盖身份，成功续期保留UUID和名称。
    void certificateRenewal() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("service"), true);
        const auto identity =
            dukto::initializeIdentity(store, {"localhost", "127.0.0.1", "::1"}, 1);
        const auto fingerprint = identity.certificate.digest(QCryptographicHash::Sha256);
        const auto original = store.read("identity.json");
        const auto info = dukto::inspectIdentity(store);
        QCOMPARE(info["certificateStatus"].toString(), QString("valid"));
        QVERIFY(info["expiringSoon"].toBool());
        QCOMPARE(info["certificateSource"].toString(), QString("stored"));
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, dukto::randomCredential()),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint.left(31)), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint, {}, 0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint, {}, 826), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint, {"*.example.com"}),
                                 dukto::Error);
        QCOMPARE(store.read("identity.json"), original);
        {
            QLockFile lock(store.directory() + "/identity.lock");
            QVERIFY(lock.tryLock());
            QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint), dukto::Error);
            QCOMPARE(store.read("identity.json"), original);
        }
        dukto::ServiceListener listener(store.directory(), 1000);
        const auto renewed = dukto::renewIdentity(store, fingerprint, {}, 825);
        const auto loaded = dukto::loadIdentity(store);
        QCOMPARE(loaded.id, identity.id);
        QVERIFY(loaded.key != identity.key);
        QVERIFY(loaded.certificate != identity.certificate);
        QCOMPARE(loaded.key.length(), 3072);
        for (const auto kind : {QSsl::DnsEntry, QSsl::IpAddressEntry}) {
            auto actual = loaded.certificate.subjectAlternativeNames().values(kind);
            auto expected = identity.certificate.subjectAlternativeNames().values(kind);
            actual.sort();
            expected.sort();
            QCOMPARE(actual, expected);
        }
        QCOMPARE(renewed["previousFingerprint"], info["fingerprint"]);
        QCOMPARE(renewed["certificateStatus"].toString(), QString("valid"));
        QVERIFY(!renewed["expiringSoon"].toBool());
        QVERIFY(renewed["restartRequired"].toBool());
        QCOMPARE(listener.publicInfo()["fingerprint"], info["fingerprint"]);
        QCOMPARE(listener.publicInfo()["storedFingerprint"], renewed["fingerprint"]);
        QVERIFY(listener.publicInfo()["restartRequired"].toBool());
        dukto::ServiceListener restarted(store.directory(), 1000);
        QCOMPARE(restarted.publicInfo()["fingerprint"], renewed["fingerprint"]);
        QVERIFY(!restarted.publicInfo()["restartRequired"].toBool());
        const auto saved = store.read("identity.json");
        QVERIFY_EXCEPTION_THROWN(dukto::renewIdentity(store, fingerprint), dukto::Error);
        QCOMPARE(store.read("identity.json"), saved);
        const auto publicBytes = dukto::next::encodeControl(renewed);
        QVERIFY(!publicBytes.contains("privateKey"));
        QVERIFY(!publicBytes.contains("PRIVATE KEY"));
        QVERIFY(!publicBytes.contains(loaded.key.toPem().mid(60, 60)));
        auto corrupted = dukto::next::parseControl(saved);
        corrupted["privateKey"] = "damaged";
        store.write("identity.json", dukto::next::encodeControl(corrupted));
        const auto damaged = store.read("identity.json");
        QVERIFY_EXCEPTION_THROWN(dukto::inspectIdentity(store), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            dukto::renewIdentity(store, loaded.certificate.digest(QCryptographicHash::Sha256)),
            dukto::Error);
        QCOMPARE(store.read("identity.json"), damaged);
    }
    // 日期：2026-11-05；真实私有存储持久读取、严格字段和数值边界，非法写入不得覆盖已保存策略。
    void sessionPolicy() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("session"), true);
        QCOMPARE(dukto::loadSessionSeconds(store), 86400);
        dukto::setSessionSeconds(store, "7");
        const auto saved = store.read("session-policy.json");
        QCOMPARE(dukto::loadSessionSeconds(dukto::PrivateStore(store.directory())), 7);
        QCOMPARE(dukto::sessionPolicyInfo(store)["seconds"].toString(), QString("7"));
        for (const auto &invalid : QList<QJsonValue>{
                 QJsonValue(), QJsonValue(1), QJsonValue(true), QJsonValue(""), QJsonValue("0"),
                 QJsonValue("01"), QJsonValue("+1"), QJsonValue("-1"), QJsonValue("1.0"),
                 QJsonValue("86401"), QJsonValue(" 1"), QJsonValue("18446744073709551616")}) {
            QVERIFY_EXCEPTION_THROWN(dukto::setSessionSeconds(store, invalid), dukto::Error);
            QCOMPARE(store.read("session-policy.json"), saved);
        }
        for (const auto &bad :
             QList<QJsonObject>{{{"version", 2}, {"seconds", "7"}},
                                {{"seconds", "7"}},
                                {{"version", 1}, {"seconds", "0"}},
                                {{"version", 1}, {"seconds", "7"}, {"extra", true}}}) {
            store.write("session-policy.json", dukto::next::encodeControl(bad));
            QVERIFY_EXCEPTION_THROWN(dukto::loadSessionSeconds(store), dukto::Error);
        }
        store.write("session-policy.json", "{");
        QVERIFY_EXCEPTION_THROWN(dukto::loadSessionSeconds(store), dukto::Error);
        dukto::setSessionSeconds(store, "86400");
        QCOMPARE(dukto::loadSessionSeconds(store), 86400);
    }
    // 日期：2026-11-05；真实经过单调时钟截止，多次检查不续命，到期错误须允许上层识别并保留检查点。
    void monotonicSessionExpiry() {
        dukto::AuthenticatedSession session(1);
        session.check();
        QTest::qWait(1100);
        try {
            session.check();
            QFAIL("expired authenticated session accepted");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Permission);
            QCOMPARE(error.stage, QString("session"));
        }
        QVERIFY_EXCEPTION_THROWN(session.check(), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::AuthenticatedSession(0), dukto::Error);
    }
    // 日期：2026-11-05；真实配对及撤销记录分页，公开身份不泄漏秘密，损坏记录和非法游标明确拒绝。
    void clientPages() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("auth"), true);
        dukto::AuthStore auth(store);
        const auto token = dukto::randomCredential();
        QStringList ids;
        for (int index = 0; index < 105; ++index) {
            const auto text =
                QString("00000000-0000-0000-0000-%1").arg(index + 1, 12, 16, QChar('0'));
            ids.append(text);
            const auto offer = auth.issue({{"docs", true, false, true}});
            auth.pair(offer.credential, QUuid(text), token);
        }
        auth.revoke(QUuid(ids[3]));
        auth.setGrants(QUuid(ids.last()), {{"docs", true, true, false}});
        const auto first = auth.clients();
        const auto entries = first["entries"].toArray();
        QCOMPARE(entries.size(), 100);
        QCOMPARE(first["after"].toString(), ids[99]);
        QVERIFY(first["more"].toBool());
        QVERIFY(entries[3].toObject()["revoked"].toBool());
        QCOMPARE(entries[3].toObject()["revision"].toString(), QString("2"));
        const auto second = auth.clients(first["after"].toString());
        QCOMPARE(second["entries"].toArray().size(), 5);
        QVERIFY(!second["more"].toBool());
        QCOMPARE(second["after"].toString(), ids.last());
        for (int index = 0; index < entries.size(); ++index)
            QCOMPARE(entries[index].toObject()["client"].toString(), ids[index]);
        const auto publicBytes = dukto::next::encodeControl(first);
        QVERIFY(!publicBytes.contains("credential"));
        QVERIFY(!publicBytes.contains("pairing"));
        QVERIFY(!publicBytes.contains(token.toHex()));
        QCOMPARE(auth.clients(ids.last())["entries"].toArray().size(), 0);
        for (const auto &bad :
             QStringList{"../auth", "bad", "{00000000-0000-0000-0000-000000000001}"})
            QVERIFY_EXCEPTION_THROWN(auth.clients(bad), dukto::Error);
        const auto key = "client-" + ids.first() + ".json";
        const auto original = store.read(key);
        auto damaged = dukto::next::parseControl(original);
        damaged["revoked"] = "false";
        store.write(key, dukto::next::encodeControl(damaged));
        QVERIFY_EXCEPTION_THROWN(auth.clients(), dukto::Error);
        store.write(key, original);
        store.write("client-malformed.json", "{}");
        QVERIFY_EXCEPTION_THROWN(auth.clients(), dukto::Error);
    }
    // 日期：2026-11-05；每主体最大授权大小使百项超过帧长，分页仍前进且每页始终小于 64 KiB。
    void clientPagesByteLimit() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("auth"), true);
        dukto::AuthStore auth(store);
        QList<dukto::Grant> grants;
        for (int index = 0; index < 16; ++index)
            grants.append({QString(62, QChar('a')) + QString::number(index).rightJustified(2, '0'),
                           true, true, true});
        const auto token = dukto::randomCredential();
        const auto client = QUuid::createUuid();
        auth.pair(auth.issue(grants).credential, client, token);
        const auto saved = dukto::next::parseControl(
            store.read("client-" + client.toString(QUuid::WithoutBraces) + ".json"));
        for (int index = 0; index < 104; ++index) {
            auto record = saved;
            const auto id = QUuid::createUuid().toString(QUuid::WithoutBraces);
            record["client"] = id;
            store.write("client-" + id + ".json", dukto::next::encodeControl(record));
        }
        int total = 0;
        QString after;
        for (;;) {
            const auto page = auth.clients(after);
            QVERIFY(dukto::next::encodeControl(page).size() <= dukto::next::ControlLimit);
            const auto entries = page["entries"].toArray();
            QVERIFY(!entries.isEmpty() && entries.size() < 100);
            total += entries.size();
            QVERIFY(page["after"].toString() > after);
            after = page["after"].toString();
            if (!page["more"].toBool())
                break;
            QVERIFY(total < 105);
        }
        QCOMPARE(total, 105);
    }
    // 日期：2026-11-05；轮换只更新摘要和修订号，旧令牌/配对票据不能复活身份或覆盖撤销。
    void credentialRotation() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("auth"), true);
        dukto::AuthStore auth(store);
        const auto offer = auth.issue({{"data", true, true, false}});
        const auto client = QUuid::createUuid();
        const auto old = dukto::randomCredential();
        const auto replacement = dukto::randomCredential();
        auth.pair(offer.credential, client, old);
        const auto key = "client-" + client.toString(QUuid::WithoutBraces) + ".json";
        const auto before = store.read(key);
        QVERIFY_EXCEPTION_THROWN(auth.rotate(client, old, old), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.rotate(client, old, replacement.left(31)), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.rotate(client, dukto::randomCredential(), replacement),
                                 dukto::Error);
        QCOMPARE(store.read(key), before);
        const auto rotated = auth.rotate(client, old, replacement);
        QCOMPARE(rotated.client, client);
        QCOMPARE(rotated.revision, quint64(2));
        QCOMPARE(dukto::encodeGrants(rotated.grants),
                 dukto::encodeGrants({{"data", true, true, false}}));
        QCOMPARE(auth.authenticate(client, replacement).revision, quint64(2));
        QVERIFY_EXCEPTION_THROWN(auth.authenticate(client, old), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.rotate(client, old, dukto::randomCredential()), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, client, old), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, client, replacement), dukto::Error);
        QVERIFY(!store.read(key).contains(old.toHex()));
        QVERIFY(!store.read(key).contains(replacement.toHex()));
        auth.setGrants(client, {{"data", true, false, false}});
        QCOMPARE(auth.authenticate(client, replacement).revision, quint64(3));
        auth.revoke(client);
        QVERIFY_EXCEPTION_THROWN(auth.rotate(client, replacement, dukto::randomCredential()),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.authenticate(client, replacement), dukto::Error);
    }
    // 日期：2026-11-05；原格式兼容读取，待轮换秘密严格校验，迟到的配对保存不能抹去轮换检查点。
    void pendingRotationProfileProtection() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("profiles"), true);
        auto profile = dukto::prepareProfile(store, "default", "127.0.0.1", 4646, "localhost",
                                             dukto::randomCredential());
        QVERIFY(profile.pendingCredential.isEmpty());
        profile.paired = true;
        profile.server = QUuid::createUuid();
        dukto::saveProfile(store, profile);
        const auto original = store.read("profile-default.json");
        auto record = dukto::next::parseControl(original);
        const auto replacement = dukto::randomCredential();
        record["pendingCredential"] = QString::fromLatin1(replacement.toHex());
        store.write("profile-default.json", dukto::next::encodeControl(record));
        QCOMPARE(dukto::loadProfile(store, "default").pendingCredential, replacement);
        QVERIFY_EXCEPTION_THROWN(dukto::saveProfile(store, profile), dukto::Error);
        QCOMPARE(dukto::loadProfile(store, "default").pendingCredential, replacement);
        for (const auto &invalid :
             QList<QJsonValue>{QJsonValue(), QJsonValue(1), QJsonValue(""),
                               QJsonValue(QString::fromLatin1(profile.credential.toHex()))}) {
            record["pendingCredential"] = invalid;
            store.write("profile-default.json", dukto::next::encodeControl(record));
            QVERIFY_EXCEPTION_THROWN(dukto::loadProfile(store, "default"), dukto::Error);
        }
        store.write("profile-default.json", original);
        auto stale = profile;
        stale.credential = replacement;
        QVERIFY_EXCEPTION_THROWN(dukto::saveProfile(store, stale), dukto::Error);
        QCOMPARE(store.read("profile-default.json"), original);
    }
    // 日期：2026-11-04；一次性配对不可换身份/令牌重用；确认丢失重试、权限更新与撤销均持久生效。
    void pairingAndRevocation() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("auth"), true);
        dukto::AuthStore auth(store);
        const auto offer =
            auth.issue({{"readonly", true, true, false}, {"incoming", false, false, true}});
        const auto client = QUuid::createUuid();
        const auto token = dukto::randomCredential();
        const auto account = auth.pair(offer.credential, client, token);
        QCOMPARE(account.client, client);
        QCOMPARE(account.grants.size(), 2);
        QVERIFY(account.grants[0].download);
        QVERIFY(!account.grants[0].upload);
        QVERIFY(account.grants[1].upload);
        QCOMPARE(auth.authenticate(client, token).revision, quint64(1));
        QCOMPARE(auth.pair(offer.credential, client, token).revision, quint64(1));
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, QUuid::createUuid(), token),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, client, dukto::randomCredential()),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.authenticate(client, dukto::randomCredential()),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.authenticate(QUuid::createUuid(), token), dukto::Error);
        auth.setGrants(client, {{"readonly", true, false, false}});
        QCOMPARE(auth.authenticate(client, token).revision, quint64(2));
        QCOMPARE(auth.authenticate(client, token).grants.size(), 1);
        QVERIFY(!auth.authenticate(client, token).grants[0].download);
        QCOMPARE(auth.pair(offer.credential, client, token).revision, quint64(2));
        const auto info = QJsonDocument(auth.authenticate(client, token).publicInfo()).toJson();
        QVERIFY(!info.contains("credential"));
        QVERIFY(!info.contains(token.toHex()));
        QVERIFY(!store.read("client-" + client.toString(QUuid::WithoutBraces) + ".json")
                     .contains(token.toHex()));
        auth.revoke(client);
        auth.revoke(client);
        QVERIFY_EXCEPTION_THROWN(auth.authenticate(client, token), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, client, token), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.setGrants(client, {{"readonly", true, true, true}}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            auth.pair(auth.issue({{"x", true, false, false}}).credential, client, token),
            dukto::Error);
    }
    // 日期：2026-11-04；模拟票据绑定已落盘而客户端文件尚未创建的崩溃，只有原身份和令牌可重试。
    void repairsBoundPairingAndRejectsExpired() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("auth"), true);
        dukto::AuthStore auth(store);
        const auto offer = auth.issue({{"data", true, true, false}});
        const auto ticket =
            "pair-" +
            QString::fromLatin1(
                QCryptographicHash::hash(offer.credential, QCryptographicHash::Sha256).toHex()) +
            ".json";
        const auto client = QUuid::createUuid();
        const auto token = dukto::randomCredential();
        auto record = dukto::next::parseControl(store.read(ticket));
        record["expires"] = "2000-01-01T00:00:00Z";
        store.write(ticket, dukto::next::encodeControl(record));
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, client, token), dukto::Error);
        record["state"] = "bound";
        record["client"] = client.toString(QUuid::WithoutBraces);
        record["credentialHash"] = QString::fromLatin1(
            QCryptographicHash::hash(token, QCryptographicHash::Sha256).toHex());
        store.write(ticket, dukto::next::encodeControl(record));
        QVERIFY_EXCEPTION_THROWN(auth.pair(offer.credential, QUuid::createUuid(), token),
                                 dukto::Error);
        QCOMPARE(auth.pair(offer.credential, client, token).client, client);
        QCOMPARE(auth.authenticate(client, token).revision, quint64(1));
        QVERIFY_EXCEPTION_THROWN(auth.issue({}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.issue({{"a", false, false, false}}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.issue({{"a", true, false, false}, {"a", false, true, false}}),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.issue({{"../x", true, true, true}}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(auth.issue({{"x", true, true, true}}, 601), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            dukto::decodeGrants({QJsonObject{
                {"share", "x"}, {"browse", "true"}, {"download", false}, {"upload", false}}}),
            dukto::Error);
    }
    // 日期：2026-11-04；真实生成并重载身份，RSA3072、SAN、期限与公钥/私钥匹配都必须成立。
    void persistsStrongIdentity() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("service"), true);
        const auto identity = dukto::initializeIdentity(store, {"localhost", "127.0.0.1", "::1"});
        QCOMPARE(identity.key.length(), 3072);
        QCOMPARE(identity.key.algorithm(), QSsl::Rsa);
        QCOMPARE(identity.certificate.subjectInfo(QSslCertificate::CommonName),
                 identity.certificate.issuerInfo(QSslCertificate::CommonName));
        QVERIFY(identity.certificate.subjectAlternativeNames()
                    .values(QSsl::DnsEntry)
                    .contains("localhost"));
        QVERIFY(identity.certificate.subjectAlternativeNames()
                    .values(QSsl::IpAddressEntry)
                    .contains("127.0.0.1"));
        QCOMPARE(identity.publicInfo()["fingerprint"].toString().size(), 64);
        QCOMPARE(identity.configuration().localCertificate(), identity.certificate);
        QCOMPARE(identity.configuration().privateKey(), identity.key);
        QCOMPARE(dukto::loadIdentity(store).id, identity.id);
        QCOMPARE(dukto::loadIdentity(store).certificate, identity.certificate);
        QCOMPARE(dukto::loadIdentity(store).key, identity.key);
        QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(store, {"localhost"}), dukto::Error);
        QCOMPARE(dukto::loadIdentity(store).id, identity.id);
        const auto info = QJsonDocument(identity.publicInfo()).toJson();
        QVERIFY(!info.contains("PRIVATE KEY"));
        QVERIFY(!info.contains("privateKey"));
        QVERIFY(!info.contains(identity.key.toPem().mid(60, 60)));
        const auto random = dukto::randomCredential();
        QCOMPARE(random.size(), 32);
        QVERIFY(dukto::secureEqual(random, random));
        QVERIFY(!dukto::secureEqual(random, dukto::randomCredential()));
        QVERIFY(!dukto::secureEqual(random, random.left(31)));
        const auto saved = store.read("identity.json");
        auto object = dukto::next::parseControl(saved);
        object["privateKey"] = "not a private key";
        store.write("identity.json", dukto::next::encodeControl(object));
        QVERIFY_EXCEPTION_THROWN(dukto::loadIdentity(store), dukto::Error);
        store.write("identity.json", saved);
        QCOMPARE(dukto::loadIdentity(store).id, identity.id);
    }
    // 日期：2026-11-04；服务器名不能注入 OpenSSL 扩展或通配符，拒绝无身份启动和无效有效期。
    void rejectsUnsafeInitialization() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("service"), true);
        QVERIFY_EXCEPTION_THROWN(dukto::loadIdentity(store), dukto::Error);
        for (const auto &value : QStringList{"", "*.example.com", "host,IP:192.168.1.1", "a\nb",
                                             "a/b", "a..b", "-a", "a-", "x:", "fe80::1%eth0"})
            QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(store, {value}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(store, {}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(store, {"localhost"}, 0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(store, {"localhost"}, 826),
                                 dukto::Error);
        QVERIFY(!store.exists("identity.json"));
    }
    // 日期：2026-11-04；两台服务器私钥不能混用，服务身份损坏不得自动生成一个新身份。
    void rejectsMismatchedKey() {
        QTemporaryDir root;
        dukto::PrivateStore first(root.filePath("first"), true);
        dukto::PrivateStore second(root.filePath("second"), true);
        const auto identity = dukto::initializeIdentity(first, {"localhost"});
        const auto other = dukto::initializeIdentity(second, {"localhost"});
        QVERIFY(identity.id != other.id);
        auto record = dukto::next::parseControl(first.read("identity.json"));
        record["privateKey"] = QString::fromLatin1(other.key.toPem());
        first.write("identity.json", dukto::next::encodeControl(record));
        QVERIFY_EXCEPTION_THROWN(dukto::loadIdentity(first), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::initializeIdentity(first, {"localhost"}), dukto::Error);
    }
};
QTEST_GUILESS_MAIN(IdentityTests)
#include "identity_tests.moc"

#include "identity.h"
#include "error.h"
#include "protocol.h"

#include <QDateTime>
#include <QHostAddress>
#include <QJsonArray>
#include <QLockFile>
#include <QRegularExpression>
#include <QUrl>
#include <memory>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/rsa.h>
#include <openssl/x509.h>
#include <openssl/x509v3.h>

namespace dukto {
namespace {
using Key = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using Certificate = std::unique_ptr<X509, decltype(&X509_free)>;
using Bio = std::unique_ptr<BIO, decltype(&BIO_free)>;

// 日期：2026-11-04；密码学错误不输出 OpenSSL 错误堆栈或私钥输入，只报告操作失败。
void ensure(bool valid) {
    if (!valid)
        throw Error(ExitCode::Runtime, QStringLiteral("服务身份密码学操作失败"), "identity");
}

// 日期：2026-11-04；SAN 只允许规范 IP 或有效 ASCII DNS 标签，拒绝通配符和扩展配置分隔符。
QString canonicalName(const QString &value) {
    QHostAddress address;
    if (address.setAddress(value) && address.scopeId().isEmpty())
        return "IP:" + address.toString();
    const auto name = QString::fromLatin1(QUrl::toAce(value)).toLower();
    if (name.isEmpty() || name.size() > 253 || name.endsWith('.'))
        throw Error(ExitCode::Config, QStringLiteral("证书服务器名无效"), "identity");
    static const QRegularExpression label("\\A[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\z");
    for (const auto &part : name.split('.'))
        if (!label.match(part).hasMatch())
            throw Error(ExitCode::Config, QStringLiteral("证书服务器名含无效 DNS 标签"),
                        "identity");
    return "DNS:" + name;
}

// 日期：2026-11-04；添加明确的 X509 扩展；扩展内容仅由本地校验后的固定模板构成。
void extension(X509 *certificate, int nid, const QByteArray &value) {
    X509V3_CTX context;
    X509V3_set_ctx(&context, certificate, certificate, nullptr, nullptr, 0);
    std::unique_ptr<X509_EXTENSION, decltype(&X509_EXTENSION_free)> item(
        X509V3_EXT_conf_nid(nullptr, &context, nid, value.constData()), X509_EXTENSION_free);
    ensure(item && X509_add_ext(certificate, item.get(), -1) == 1);
}

// 日期：2026-11-04；BIO 输出有固定材料上限，避免错误产生无界私钥/证书文本。
QByteArray bytes(BIO *bio) {
    char *data = nullptr;
    const auto size = BIO_get_mem_data(bio, &data);
    ensure(size > 0 && size <= 16384 && data);
    return QByteArray(data, static_cast<int>(size));
}

// 日期：2026-11-04；Qt 加载与 OpenSSL 匹配验证均须通过，公钥/私钥不匹配不能等待握手才发现。
ServiceIdentity decodeIdentity(const QJsonObject &object) {
    if (object["version"] != 1 || !object["id"].isString() || !object["certificate"].isString() ||
        !object["privateKey"].isString() || object.size() != 4)
        throw Error(ExitCode::Config, QStringLiteral("服务身份记录格式无效"), "identity");
    const auto certificateBytes = object["certificate"].toString().toLatin1();
    const auto keyBytes = object["privateKey"].toString().toLatin1();
    ServiceIdentity identity{QUuid(object["id"].toString()), QSslCertificate(certificateBytes),
                             QSslKey(keyBytes, QSsl::Rsa)};
    const auto now = QDateTime::currentDateTimeUtc();
    if (identity.id.isNull() || identity.certificate.isNull() || identity.key.isNull() ||
        identity.certificate.effectiveDate() > now || identity.certificate.expiryDate() <= now)
        throw Error(ExitCode::Permission, QStringLiteral("服务身份缺失、损坏或证书不在有效期内"),
                    "identity");
    Bio certBio(BIO_new_mem_buf(certificateBytes.constData(), certificateBytes.size()), BIO_free);
    Bio keyBio(BIO_new_mem_buf(keyBytes.constData(), keyBytes.size()), BIO_free);
    ensure(certBio && keyBio);
    Certificate certificate(PEM_read_bio_X509(certBio.get(), nullptr, nullptr, nullptr), X509_free);
    Key key(PEM_read_bio_PrivateKey(keyBio.get(), nullptr, nullptr, nullptr), EVP_PKEY_free);
    if (!certificate || !key || X509_check_private_key(certificate.get(), key.get()) != 1)
        throw Error(ExitCode::Permission, QStringLiteral("服务证书与私钥不匹配"), "identity");
    return identity;
}
} // namespace

// 日期：2026-11-04；凭据与配对票据使用独立随机值，不由服务器 ID、时间戳或普通伪随机派生。
QByteArray randomCredential() {
    QByteArray result(32, '\0');
    ensure(RAND_bytes(reinterpret_cast<unsigned char *>(result.data()), result.size()) == 1);
    return result;
}

// 日期：2026-11-04；公开的长度不匹配可以直接拒绝，等长秘密使用 OpenSSL 常量时间比较。
bool secureEqual(const QByteArray &first, const QByteArray &second) {
    return first.size() == second.size() && CRYPTO_memcmp(first.constData(), second.constData(),
                                                          static_cast<size_t>(first.size())) == 0;
}

// 日期：2026-11-04；初始化锁保护跨进程的存在检查/发布，不能并发覆盖一个刚建立的服务身份。
ServiceIdentity initializeIdentity(PrivateStore &store, const QStringList &names, int validDays) {
    QLockFile lock(store.directory() + "/identity.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("服务身份初始化已被另一个进程占用"),
                    "identity");
    if (store.exists("identity.json"))
        throw Error(ExitCode::Config, QStringLiteral("服务身份已存在，拒绝覆盖"), "identity");
    if (names.isEmpty() || names.size() > 16 || validDays < 1 || validDays > 825)
        throw Error(ExitCode::Config, QStringLiteral("服务器名数量或证书有效期无效"), "identity");
    QStringList canonical;
    for (const auto &name : names) {
        const auto normalized = canonicalName(name);
        if (!canonical.contains(normalized))
            canonical.append(normalized);
    }
    if (canonical.join(',').toUtf8().size() > 1800)
        throw Error(ExitCode::Config, QStringLiteral("证书服务器名总长度超过预算"), "identity");
    std::unique_ptr<EVP_PKEY_CTX, decltype(&EVP_PKEY_CTX_free)> context(
        EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, nullptr), EVP_PKEY_CTX_free);
    ensure(context && EVP_PKEY_keygen_init(context.get()) == 1 &&
           EVP_PKEY_CTX_set_rsa_keygen_bits(context.get(), 3072) == 1);
    EVP_PKEY *rawKey = nullptr;
    ensure(EVP_PKEY_keygen(context.get(), &rawKey) == 1);
    Key key(rawKey, EVP_PKEY_free);
    Certificate certificate(X509_new(), X509_free);
    ensure(certificate && X509_set_version(certificate.get(), 2) == 1);
    const auto serialBytes = randomCredential().left(16).toHex();
    BIGNUM *number = nullptr;
    ensure(BN_hex2bn(&number, serialBytes.constData()) > 0);
    std::unique_ptr<BIGNUM, decltype(&BN_free)> serial(number, BN_free);
    ensure(BN_to_ASN1_INTEGER(serial.get(), X509_get_serialNumber(certificate.get())));
    ensure(X509_gmtime_adj(X509_getm_notBefore(certificate.get()), -300));
    ensure(X509_gmtime_adj(X509_getm_notAfter(certificate.get()),
                           static_cast<long>(validDays) * 86400));
    const auto id = QUuid::createUuid();
    const auto commonName = "Dukto " + id.toString(QUuid::WithoutBraces).toUtf8();
    auto subject = X509_get_subject_name(certificate.get());
    ensure(
        X509_NAME_add_entry_by_txt(subject, "CN", MBSTRING_ASC,
                                   reinterpret_cast<const unsigned char *>(commonName.constData()),
                                   commonName.size(), -1, 0) == 1);
    ensure(X509_set_issuer_name(certificate.get(), subject) == 1 &&
           X509_set_pubkey(certificate.get(), key.get()) == 1);
    extension(certificate.get(), NID_basic_constraints, "critical,CA:FALSE");
    extension(certificate.get(), NID_key_usage, "critical,digitalSignature,keyEncipherment");
    extension(certificate.get(), NID_ext_key_usage, "serverAuth");
    extension(certificate.get(), NID_subject_key_identifier, "hash");
    extension(certificate.get(), NID_authority_key_identifier, "keyid:always");
    extension(certificate.get(), NID_subject_alt_name, canonical.join(',').toLatin1());
    ensure(X509_sign(certificate.get(), key.get(), EVP_sha256()) > 0);
    Bio certBio(BIO_new(BIO_s_mem()), BIO_free);
    Bio keyBio(BIO_new(BIO_s_mem()), BIO_free);
    ensure(certBio && keyBio && PEM_write_bio_X509(certBio.get(), certificate.get()) == 1 &&
           PEM_write_bio_PrivateKey(keyBio.get(), key.get(), nullptr, nullptr, 0, nullptr,
                                    nullptr) == 1);
    const QJsonObject object{{"version", 1},
                             {"id", id.toString(QUuid::WithoutBraces)},
                             {"certificate", QString::fromLatin1(bytes(certBio.get()))},
                             {"privateKey", QString::fromLatin1(bytes(keyBio.get()))}};
    const auto identity = decodeIdentity(object);
    store.write("identity.json", next::encodeControl(object));
    return identity;
}

// 日期：2026-11-04；读取失败不重新初始化，避免丢失身份后让既有客户端静默信任另一台服务器。
ServiceIdentity loadIdentity(const PrivateStore &store) {
    return decodeIdentity(next::parseControl(store.read("identity.json")));
}

// 日期：2026-11-04；服务端 TLS 协商只使用持久化证书，应用层认证在后续控制状态机执行。
QSslConfiguration ServiceIdentity::configuration() const {
    auto result = QSslConfiguration::defaultConfiguration();
    result.setLocalCertificate(certificate);
    result.setPrivateKey(key);
    result.setProtocol(QSsl::TlsV1_2OrLater);
    return result;
}

// 日期：2026-11-04；完整 SHA256 指纹可供人工核对，私钥不出现在 GUI、JSON 事件或日志中。
QJsonObject ServiceIdentity::publicInfo() const {
    QJsonArray names;
    const auto alternatives = certificate.subjectAlternativeNames();
    for (const auto &value : alternatives.values(QSsl::DnsEntry))
        names.append(value);
    for (const auto &value : alternatives.values(QSsl::IpAddressEntry))
        names.append(value);
    return {{"serverId", id.toString(QUuid::WithoutBraces)},
            {"fingerprint",
             QString::fromLatin1(certificate.digest(QCryptographicHash::Sha256).toHex())},
            {"expiresUtc", certificate.expiryDate().toUTC().toString(Qt::ISODate)},
            {"names", names}};
}
} // namespace dukto

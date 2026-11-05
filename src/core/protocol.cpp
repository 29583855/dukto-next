#include "protocol.h"
#include "error.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSet>
#include <QtEndian>
#include <cstring>

namespace dukto {
namespace next {
namespace {
// 日期：2026-11-04；报错仅说明协议边界，不拼接可能包含凭据的远端正文。
[[noreturn]] void invalid(const QString &reason) {
    throw Error(ExitCode::Config, reason, "protocol");
}

// 日期：2026-11-05；显式枚举已定义类型，未分配类型不能被误认为普通控制请求。
bool knownType(Type type) {
    switch (type) {
    case Type::Hello:
    case Type::HelloAck:
    case Type::Authenticate:
    case Type::Authenticated:
    case Type::Pair:
    case Type::Paired:
    case Type::Failure:
    case Type::Close:
    case Type::Closed:
    case Type::RotateCredential:
    case Type::CredentialRotated:
    case Type::List:
    case Type::Listing:
    case Type::CreateUpload:
    case Type::CreateDownload:
    case Type::Task:
    case Type::Manifest:
    case Type::ManifestAck:
    case Type::ChannelTicket:
    case Type::Attach:
    case Type::Attached:
    case Type::Data:
    case Type::BlockDone:
    case Type::BlockAck:
    case Type::Finish:
    case Type::Completed:
    case Type::TaskQuery:
    case Type::TaskState:
    case Type::Cancel:
    case Type::Pause:
    case Type::Resume:
    case Type::TaskAdmitted:
    case Type::Progress:
        return true;
    }
    return false;
}

// 日期：2026-11-04；头部校验必须先于正文申请，数据与控制使用各自的长度上限。
void validateHeader(const Header &header) {
    if (!knownType(header.type) || header.correlation == 0)
        invalid(QStringLiteral("未知消息类型或无效请求序号"));
    const bool data = header.type == Type::Data;
    if (header.payloadBytes < (data ? DataHeaderBytes + 1U : 2U) ||
        header.payloadBytes >
            static_cast<quint32>(data ? FragmentLimit + DataHeaderBytes : ControlLimit))
        invalid(QStringLiteral("帧正文长度超出限制"));
}

class JsonGuard final {
  public:
    // 日期：2026-11-04；输入已受 64 KiB 限制；扫描器先拒绝重复键，再交给 Qt 语法解析。
    explicit JsonGuard(const QByteArray &bytes) : bytes_(bytes) {
    }
    // 日期：2026-11-04；根必须为对象且正文只允许一个 JSON 值，不能接受尾随正文。
    void check() {
        space();
        if (atEnd() || bytes_[position_] != '{')
            invalid(QStringLiteral("控制正文必须是 JSON 对象"));
        value(0);
        space();
        if (!atEnd())
            invalid(QStringLiteral("控制正文含尾随数据"));
    }

  private:
    // 日期：2026-11-04；所有查看字符的操作先检查此边界，截断输入不会读出缓冲之外。
    bool atEnd() const {
        return position_ >= bytes_.size();
    }
    // 日期：2026-11-04；只接受 JSON 定义的四种空白字符。
    void space() {
        while (!atEnd() && (bytes_[position_] == ' ' || bytes_[position_] == '\t' ||
                            bytes_[position_] == '\r' || bytes_[position_] == '\n'))
            ++position_;
    }
    // 日期：2026-11-04；消耗一个必需分隔符，异常信息不带源正文。
    void expect(char character) {
        space();
        if (atEnd() || bytes_[position_++] != character)
            invalid(QStringLiteral("控制正文分隔符无效或被截断"));
    }
    // 日期：2026-11-04；显式检查转义及控制字符，解码后比较键，a 与 \u0061 不能覆盖同一字段。
    QString string() {
        const auto start = position_;
        expect('"');
        bool closed = false;
        while (!atEnd()) {
            const auto character = bytes_[position_++];
            if (character == '\\') {
                if (atEnd())
                    break;
                const auto escape = bytes_[position_++];
                if (escape == 'u') {
                    for (int index = 0; index < 4; ++index) {
                        if (atEnd())
                            invalid(QStringLiteral("Unicode 转义被截断"));
                        const auto hex = bytes_[position_++];
                        if (!((hex >= '0' && hex <= '9') || (hex >= 'a' && hex <= 'f') ||
                              (hex >= 'A' && hex <= 'F')))
                            invalid(QStringLiteral("Unicode 转义含非十六进制字符"));
                    }
                } else if (!QByteArray("\"\\/bfnrt").contains(escape)) {
                    invalid(QStringLiteral("控制字符串含非法转义"));
                }
            } else if (character == '"') {
                closed = true;
                break;
            } else if (static_cast<uchar>(character) < 0x20) {
                invalid(QStringLiteral("控制字符串含未转义控制字符"));
            }
        }
        if (!closed)
            invalid(QStringLiteral("控制字符串未结束"));
        const auto document =
            QJsonDocument::fromJson('[' + bytes_.mid(start, position_ - start) + ']');
        if (!document.isArray() || document.array().size() != 1 || !document.array()[0].isString())
            invalid(QStringLiteral("控制字符串转义无效"));
        const auto result = document.array()[0].toString();
        if (result.toUtf8().size() > 4096 || result.contains(QChar::Null) ||
            QString::fromUtf8(result.toUtf8()) != result)
            invalid(QStringLiteral("控制字符串过长或含无效 Unicode"));
        return result;
    }
    // 日期：2026-11-04；限制集合深度、每集合元素及总节点，内存不随远端目录规模无限增长。
    void value(int depth) {
        space();
        if (atEnd() || depth > 16 || ++nodes_ > 4096)
            invalid(QStringLiteral("控制正文截断、过深或节点过多"));
        const auto character = bytes_[position_];
        if (character == '"') {
            string();
            return;
        }
        if (character == '{' || character == '[') {
            const bool object = character == '{';
            const char end = object ? '}' : ']';
            ++position_;
            QSet<QString> keys;
            int count = 0;
            space();
            if (!atEnd() && bytes_[position_] == end) {
                ++position_;
                return;
            }
            while (true) {
                if (++count > (object ? 32 : 100))
                    invalid(QStringLiteral("控制对象字段或数组元素过多"));
                if (object) {
                    const auto key = string();
                    if (key.isEmpty() || key.toUtf8().size() > 64 || keys.contains(key))
                        invalid(QStringLiteral("控制对象字段重复或名称无效"));
                    keys.insert(key);
                    expect(':');
                }
                value(depth + 1);
                space();
                if (!atEnd() && bytes_[position_] == end) {
                    ++position_;
                    return;
                }
                expect(',');
                space();
            }
        }
        const auto start = position_;
        while (!atEnd() && bytes_[position_] != ',' && bytes_[position_] != '}' &&
               bytes_[position_] != ']' && bytes_[position_] != ' ' && bytes_[position_] != '\t' &&
               bytes_[position_] != '\r' && bytes_[position_] != '\n')
            ++position_;
        if (position_ == start)
            invalid(QStringLiteral("控制正文值无效"));
        const auto token = bytes_.mid(start, position_ - start);
        static const QRegularExpression number(
            "\\A-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\\z");
        if (token != "true" && token != "false" && token != "null" &&
            !number.match(QString::fromLatin1(token)).hasMatch())
            invalid(QStringLiteral("控制正文原子值语法无效"));
    }
    const QByteArray &bytes_;
    int position_ = 0;
    int nodes_ = 0;
};

// 日期：2026-11-04；片段范围只描述一块，文件长度、块摘要和任务权限由传输状态机另行校验。
void validateFragment(const Fragment &fragment) {
    if (fragment.task.isNull() || fragment.file == 0 || fragment.bytes.isEmpty() ||
        fragment.bytes.size() > FragmentLimit || fragment.offset >= BlockLimit ||
        static_cast<quint32>(fragment.bytes.size()) > BlockLimit - fragment.offset)
        invalid(QStringLiteral("数据片段身份、长度或块内范围无效"));
}

// 日期：2026-11-04；控制及数据共用同一入站/出站正文校验，不能只检查帧头长度。
void validateFrame(const Frame &frame) {
    validateHeader(frame.header);
    if (frame.header.payloadBytes != static_cast<quint32>(frame.payload.size()))
        invalid(QStringLiteral("帧声明与实际正文长度不一致"));
    if (frame.header.type == Type::Data)
        decodeFragment(frame.payload);
    else
        parseControl(frame.payload);
}
} // namespace

// 日期：2026-11-04；重复键检查先于 Qt 的覆盖行为，非法 UTF-8 与 UTF-8 BOM 均明确拒绝。
QJsonObject parseControl(const QByteArray &bytes) {
    if (bytes.size() < 2 || bytes.size() > ControlLimit ||
        QString::fromUtf8(bytes).toUtf8() != bytes)
        invalid(QStringLiteral("控制正文长度或 UTF-8 编码无效"));
    JsonGuard(bytes).check();
    const auto document = QJsonDocument::fromJson(bytes);
    if (!document.isObject())
        invalid(QStringLiteral("控制正文 JSON 语法无效"));
    return document.object();
}

// 日期：2026-11-04；输出固定紧凑格式，但不依赖 JSON 对象顺序作为任务内容身份。
QByteArray encodeControl(const QJsonObject &object) {
    const auto bytes = QJsonDocument(object).toJson(QJsonDocument::Compact);
    parseControl(bytes);
    return bytes;
}

// 日期：2026-11-04；上限可为完整 u64，乘加前验证，避免 JSON double 的 53 位精度丢失。
quint64 decimal(const QJsonValue &value, quint64 maximum) {
    if (!value.isString())
        invalid(QStringLiteral("64 位整数字段必须为十进制字符串"));
    const auto text = value.toString();
    if (text.isEmpty() || text.size() > 20 || (text.size() > 1 && text[0] == '0'))
        invalid(QStringLiteral("十进制整数字段格式无效"));
    quint64 result = 0;
    for (const auto character : text) {
        const auto digit = character.unicode() - ushort('0');
        if (digit < 0 || digit > 9 || static_cast<quint64>(digit) > maximum ||
            result > (maximum - static_cast<quint64>(digit)) / 10)
            invalid(QStringLiteral("十进制整数字段越界"));
        result = result * 10 + static_cast<quint64>(digit);
    }
    return result;
}

// 日期：2026-11-04；首版固定 1.0/零保留位，所有整数逐字段编码为大端。
QByteArray encodeHeader(const Header &header) {
    validateHeader(header);
    QByteArray bytes(HeaderBytes, '\0');
    std::memcpy(bytes.data(), "DKTNEXT1", 8);
    auto data = reinterpret_cast<uchar *>(bytes.data());
    qToBigEndian(quint16(1), data + 8);
    qToBigEndian(static_cast<quint16>(header.type), data + 12);
    qToBigEndian(header.correlation, data + 16);
    qToBigEndian(header.payloadBytes, data + 24);
    return bytes;
}

// 日期：2026-11-04；不接受未协商的次版本；后续版本必须通过明确能力升级扩展。
Header decodeHeader(const QByteArray &bytes) {
    if (bytes.size() != HeaderBytes || bytes.left(8) != "DKTNEXT1")
        invalid(QStringLiteral("帧头长度或协议签名无效"));
    const auto data = reinterpret_cast<const uchar *>(bytes.constData());
    if (qFromBigEndian<quint16>(data + 8) != 1 || qFromBigEndian<quint16>(data + 10) != 0 ||
        qFromBigEndian<quint16>(data + 14) != 0 || qFromBigEndian<quint32>(data + 28) != 0)
        invalid(QStringLiteral("协议版本、标志或保留字段不受支持"));
    Header header{static_cast<Type>(qFromBigEndian<quint16>(data + 12)),
                  qFromBigEndian<quint64>(data + 16), qFromBigEndian<quint32>(data + 24)};
    validateHeader(header);
    return header;
}

// 日期：2026-11-04；帧总长度始终有界；网络层还必须限制 Qt 排队写缓冲。
QByteArray encodeFrame(const Frame &frame) {
    validateFrame(frame);
    return encodeHeader(frame.header) + frame.payload;
}

// 日期：2026-11-04；UUID 采用 RFC4122 的 16 字节网络形式，数字采用大端。
QByteArray encodeFragment(const Fragment &fragment) {
    validateFragment(fragment);
    QByteArray bytes(DataHeaderBytes, '\0');
    std::memcpy(bytes.data(), fragment.task.toRfc4122().constData(), 16);
    auto data = reinterpret_cast<uchar *>(bytes.data());
    qToBigEndian(fragment.file, data + 16);
    qToBigEndian(fragment.block, data + 24);
    qToBigEndian(fragment.offset, data + 32);
    qToBigEndian(static_cast<quint32>(fragment.bytes.size()), data + 36);
    return bytes + fragment.bytes;
}

// 日期：2026-11-04；先检查正文上限和精确长度，才生成应用层片段对象。
Fragment decodeFragment(const QByteArray &bytes) {
    if (bytes.size() <= DataHeaderBytes || bytes.size() > FragmentLimit + DataHeaderBytes)
        invalid(QStringLiteral("数据正文长度无效"));
    const auto data = reinterpret_cast<const uchar *>(bytes.constData());
    if (qFromBigEndian<quint32>(data + 36) != static_cast<quint32>(bytes.size() - DataHeaderBytes))
        invalid(QStringLiteral("数据片段声明与正文不一致"));
    Fragment fragment{QUuid::fromRfc4122(bytes.left(16)), qFromBigEndian<quint64>(data + 16),
                      qFromBigEndian<quint64>(data + 24), qFromBigEndian<quint32>(data + 32),
                      bytes.mid(DataHeaderBytes)};
    validateFragment(fragment);
    return fragment;
}

// 日期：2026-11-04；一个解码器最多保留一个 256 KiB 片段及 72 字节固定头，不能堆积完整目录。
int Decoder::requiredBytes() const {
    if (failed_)
        invalid(QStringLiteral("帧解码器已因协议错误关闭"));
    return hasHeader_ ? static_cast<int>(frame_.header.payloadBytes) - frame_.payload.size()
                      : HeaderBytes - headerBytes_.size();
}

// 日期：2026-11-04；socket 应仅读 requiredBytes；不接受跨帧大块缓存，以便资源预算提前生效。
void Decoder::append(const QByteArray &bytes) {
    try {
        if (requiredBytes() == 0 || bytes.isEmpty() || bytes.size() > requiredBytes())
            invalid(QStringLiteral("解码输入超过当前帧所需长度"));
        if (!hasHeader_) {
            headerBytes_.append(bytes);
            if (headerBytes_.size() == HeaderBytes) {
                frame_.header = decodeHeader(headerBytes_);
                hasHeader_ = true;
            }
        } else {
            frame_.payload.append(bytes);
        }
    } catch (...) {
        failed_ = true;
        throw;
    }
}

// 日期：2026-11-04；正文验证失败后也封闭解码器，不能继续执行后续授权请求。
Frame Decoder::take() {
    try {
        if (!hasHeader_ || requiredBytes() != 0)
            invalid(QStringLiteral("读取了尚未完成的帧"));
        validateFrame(frame_);
        auto result = std::move(frame_);
        frame_ = Frame();
        headerBytes_.clear();
        hasHeader_ = false;
        return result;
    } catch (...) {
        failed_ = true;
        throw;
    }
}

// 日期：2026-11-04；即使头已完整而正文一字节未到，也属于连接截断。
void Decoder::finish() const {
    if (failed_ || hasHeader_ || !headerBytes_.isEmpty())
        invalid(QStringLiteral("连接结束时仍有坏帧或未完成帧"));
}
} // namespace next
} // namespace dukto

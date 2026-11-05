#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QUuid>
#include <QtGlobal>

namespace dukto {
namespace next {
constexpr int HeaderBytes = 32;
constexpr int ControlLimit = 64 * 1024;
constexpr int FragmentLimit = 256 * 1024;
constexpr int DataHeaderBytes = 40;
constexpr quint32 BlockLimit = 8 * 1024 * 1024;

enum class Type : quint16 {
    Hello = 1,
    HelloAck = 2,
    Authenticate = 3,
    Authenticated = 4,
    Pair = 5,
    Paired = 6,
    Failure = 7,
    Close = 8,
    Closed = 9,
    RotateCredential = 10,
    CredentialRotated = 11,
    List = 16,
    Listing = 17,
    CreateUpload = 32,
    CreateDownload = 33,
    Task = 34,
    Manifest = 35,
    ManifestAck = 36,
    ChannelTicket = 37,
    Attach = 38,
    Attached = 39,
    Data = 40,
    BlockDone = 41,
    BlockAck = 42,
    Finish = 43,
    Completed = 44,
    TaskQuery = 45,
    TaskState = 46,
    Cancel = 47,
    Pause = 48,
    Resume = 49,
    Progress = 50,
    TaskAdmitted = 51,
    DispositionSummary = 52,
    DispositionAck = 53
};

struct Header {
    Type type = Type::Hello;
    quint64 correlation = 1;
    quint32 payloadBytes = 0;
};
struct Frame {
    Header header;
    QByteArray payload;
};
struct Fragment {
    QUuid task;
    quint64 file = 1;
    quint64 block = 0;
    quint32 offset = 0;
    QByteArray bytes;
};

// 日期：2026-11-04；严格解析有界控制对象，拒绝重复键、畸形 UTF-8、过深嵌套和超量集合。
QJsonObject parseControl(const QByteArray &bytes);
// 日期：2026-11-04；序列化后也执行同一边界检查，发送方不能绕过控制帧限制。
QByteArray encodeControl(const QJsonObject &object);
// 日期：2026-11-04；只接受规范十进制字符串表示的无符号整数，逐位检查溢出及字段上限。
quint64 decimal(const QJsonValue &value, quint64 maximum);
// 日期：2026-11-04；显式大端编码固定头，不传输 C++ 结构体内存或本机字节序。
QByteArray encodeHeader(const Header &header);
// 日期：2026-11-04；在接收正文前核对 magic/版本/类型/保留字段/长度与请求序号。
Header decodeHeader(const QByteArray &bytes);
// 日期：2026-11-04；构造帧前核对声明长度及控制/数据正文，禁止未检查的出站帧。
QByteArray encodeFrame(const Frame &frame);
// 日期：2026-11-04；数据正文固定为 UUID、文件/块序号、片段偏移/长度和至多 256 KiB 数据。
QByteArray encodeFragment(const Fragment &fragment);
// 日期：2026-11-04；检查固定头与实际正文一致、块内范围及非空任务身份，之后才能进入写入调度。
Fragment decodeFragment(const QByteArray &bytes);

class Decoder final {
  public:
    // 日期：2026-11-04；只报告当前头/正文尚缺的长度，调用方据此限制 socket.read 的申请。
    int requiredBytes() const;
    // 日期：2026-11-04；每次仅追加当前帧缺少的字节；错误后该解码器永久拒绝继续使用。
    void append(const QByteArray &bytes);
    // 日期：2026-11-04；只有帧完整且正文验证通过才交给处理器，立即释放解码器的上一帧引用。
    Frame take();
    // 日期：2026-11-04；连接结束必须检查残留帧，不能把截断或坏帧当作正常 EOF。
    void finish() const;

  private:
    QByteArray headerBytes_;
    Frame frame_;
    bool hasHeader_ = false;
    bool failed_ = false;
};
} // namespace next
} // namespace dukto

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QHostInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <cstdio>

// 日期：2026-11-05；独立测量收包旧路径的主机名查询成本，不以该诊断取代 UDP 原门槛。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    constexpr int iterations = 2500;
    QElapsedTimer elapsed;
    elapsed.start();
    qint64 encodedBytes = 0;
    for (int index = 0; index < iterations; ++index)
        encodedBytes += (QStringLiteral("probe at ") + QHostInfo::localHostName() +
                         QStringLiteral(" (Macintosh)"))
                            .toUtf8()
                            .size();
    const auto uncachedNanoseconds = elapsed.nsecsElapsed();
    elapsed.restart();
    const auto signature =
        (QStringLiteral("probe at ") + QHostInfo::localHostName() + QStringLiteral(" (Macintosh)"))
            .toUtf8();
    qint64 cachedBytes = 0;
    for (int index = 0; index < iterations; ++index)
        cachedBytes += signature.size();
    const QJsonObject report{{"diagnosticOnly", true},
                             {"iterations", iterations},
                             {"uncachedNanoseconds", QString::number(uncachedNanoseconds)},
                             {"cachedNanoseconds", QString::number(elapsed.nsecsElapsed())},
                             {"sameEncodedBytes", encodedBytes == cachedBytes}};
    const auto data = QJsonDocument(report).toJson(QJsonDocument::Compact) + '\n';
    return std::fwrite(data.constData(), 1, static_cast<size_t>(data.size()), stdout) ==
                   static_cast<size_t>(data.size())
               ? 0
               : 1;
}

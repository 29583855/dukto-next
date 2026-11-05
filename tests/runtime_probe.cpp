#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSqlDatabase>
#include <QSqlError>
#include <QSqlQuery>
#include <QSslSocket>
#include <QTextStream>

// 日期：2026-11-04；验证无 GUI 下 Qt、SQLite 读写与 TLS 后端加载，缺失依赖返回失败。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    auto database = QSqlDatabase::addDatabase("QSQLITE");
    database.setDatabaseName(":memory:");
    bool sqlite = database.open();
    QSqlQuery query(database);
    sqlite = sqlite && query.exec("CREATE TABLE probe(value TEXT)") &&
             query.exec("INSERT INTO probe VALUES('中文 C++14')") &&
             query.exec("SELECT value FROM probe") && query.next() &&
             query.value(0).toString() == QStringLiteral("中文 C++14");
    const bool tls = QSslSocket::supportsSsl();
    const QJsonObject result{{"qt", qVersion()},
                             {"cxx", 14},
                             {"sqliteReadWrite", sqlite},
                             {"tls", tls},
                             {"tlsRuntime", QSslSocket::sslLibraryVersionString()}};
    QTextStream(stdout) << QJsonDocument(result).toJson(QJsonDocument::Compact) << '\n';
    return sqlite && tls ? 0 : 1;
}

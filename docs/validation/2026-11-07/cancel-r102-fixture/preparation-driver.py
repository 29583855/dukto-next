"""日期：2026-11-07；修正独立慢接收测试的接管时序，保留产品取消及EOF原五秒门槛。"""
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；只修改测试夹具并保留原编码和换行，不改变任何传输核心实现。
def main():
    root = Path.cwd()
    update = runpy.run_path('.cache/finalize-skip-items-r84.py')['update']
    path = root / 'tests/ui_tests.cpp'
    formatter = root / '.tools/python/Scripts/clang-format.exe'
    assert formatter.is_file()

    # 日期：2026-11-07；在套接字首次进入事件循环之前限制读取，防止回环先收完整文件再进入测试取消点。
    def transform(text):
        marker = 'class UiTests final : public QObject {'
        assert text.count(marker) == 1
        fixture = '''// 日期：2026-11-07；独立慢接收端从接管原生描述符之前即限制Qt预读，避免平台事件时序抢先收完。
class CancellationPeer final : public QTcpServer {
  protected:
    // 日期：2026-11-07；先设64KiB读取上限再发布连接；父对象管理失败连接和待接管套接字。
    void incomingConnection(qintptr descriptor) override {
        auto socket = new QTcpSocket(this);
        socket->setReadBufferSize(64 * 1024);
        if (!socket->setSocketDescriptor(descriptor)) {
            socket->deleteLater();
            return;
        }
        addPendingConnection(socket);
    }
};

'''
        text = text.replace(marker, fixture + marker, 1)
        before = '        QTcpServer slow;\n        QVERIFY(slow.listen(QHostAddress::LocalHost, 0));'
        assert text.count(before) == 1
        text = text.replace(before, before.replace('QTcpServer slow;', 'CancellationPeer slow;'), 1)
        assert text.count('            peer->setReadBufferSize(4096);') == 1
        text = text.replace('            peer->setReadBufferSize(4096);\n', '', 1)
        before = '            QObject::connect(peer.get(), &QTcpSocket::readyRead, peer.get(),'
        assert text.count(before) == 1
        text = text.replace(before,
            '            peer->setReadBufferSize(256 * 1024);\n' + before, 1)
        before = '            observed = 16;'
        assert text.count(before) == 1
        text = text.replace(before,
            '            QVERIFY(peer->bytesAvailable() <= 64 * 1024);\n' + before, 1)
        return text

    update(path, transform)
    raw = path.read_bytes()
    result = subprocess.run([str(formatter), str(path)], capture_output=True, check=True).stdout
    text = result.decode('utf-8-sig').replace('\r\n', '\n')
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    path.write_bytes(bom + text.replace('\n', newline).encode('utf-8'))
    subprocess.run([str(formatter), '--dry-run', '--Werror', str(path)], check=True)
    print('Only ui_tests.cpp fixture changed; cancellation and EOF limits remain 5000ms')


if __name__ == '__main__':
    main()

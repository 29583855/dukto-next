"""日期：2026-11-07；为原版Windows中止对照提供有界独立R6对端，只传输自建测试文件。"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import time

ROOT = Path.cwd() / '.cache/original-r6-cancel-20261107'
OUTPUT = Path.cwd() / 'docs/validation/2026-11-07/original-r6-cancel'
NAME = 'dukto-r6-cancel-20261107-85f7.bin'
RECOVERY = 'dukto-r6-after-cancel-20261107-85f7.txt'
SIZE = 128 * 1024**2
PORT = 24367


# 日期：2026-11-07；读取固定有界字段，EOF明确返回中止，不能静默补齐协议元数据。
def exact(connection, count):
    value = bytearray()
    while len(value) < count:
        part = connection.recv(count - len(value))
        if not part:
            raise EOFError('Original sender closed before complete header')
        value.extend(part)
    return bytes(value)


# 日期：2026-11-07；生成新目录内测试文件，逐块写入和散列，不读取或修改任何用户文件。
def prepare():
    assert not ROOT.exists() and not OUTPUT.exists()
    ROOT.mkdir()
    OUTPUT.mkdir(parents=True)
    block = bytes(range(256)) * 4096
    digest = hashlib.sha256()
    with (ROOT / NAME).open('xb') as stream:
        for unused in range(SIZE // len(block)):
            stream.write(block)
            digest.update(block)
    payload = '原版中止后继续接收验证\nDukto R6 recovery café\n'.encode('utf-8')
    (ROOT / RECOVERY).write_bytes(payload)
    value = {'date': '2026-11-07', 'fileName': NAME, 'bytes': SIZE, 'sha256': digest.hexdigest(),
             'recoveryFileName': RECOVERY, 'recoveryBytes': len(payload),
             'recoverySha256': hashlib.sha256(payload).hexdigest(), 'onlyGeneratedTestData': True,
             'referenceSha256': hashlib.sha256(Path('Dukto/dukto.exe').read_bytes()).hexdigest(),
             'actualExecutableSha256': hashlib.sha256(Path('D:/Program Files (x86)/Dukto/dukto.exe').read_bytes()).hexdigest()}
    assert value['referenceSha256'] == value['actualExecutableSha256']
    (OUTPUT / 'input-manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'prepared': True, 'file': str(ROOT / NAME), 'port': PORT}), flush=True)


# 日期：2026-11-07；独立慢读原版发送，记录真实断开及部分正文长度，不以窗口提示代替网络证据。
def receive():
    report = OUTPUT / 'original-send-cancel-peer.json'
    assert not report.exists()
    with socket.socket() as server:
        server.bind(('127.0.0.1', PORT))
        server.listen(1)
        server.settimeout(300)
        print(json.dumps({'event': 'listening', 'port': PORT}), flush=True)
        with server.accept()[0] as connection:
            connection.settimeout(30)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
            count, total = struct.unpack('<qq', exact(connection, 16))
            name = bytearray()
            while True:
                byte = exact(connection, 1)
                if byte == b'\0':
                    break
                name.extend(byte)
                assert len(name) <= 1024
            length, = struct.unpack('<q', exact(connection, 8))
            assert count == 1 and total == length == SIZE and name.decode('utf-8') == NAME
            print(json.dumps({'event': 'body-started', 'declaredBytes': length}), flush=True)
            received, ending = 0, None
            digest = hashlib.sha256()
            started = time.monotonic()
            while time.monotonic() - started < 240:
                try:
                    block = connection.recv(8192)
                except ConnectionResetError:
                    ending = 'connection-reset'
                    break
                if not block:
                    ending = 'eof'
                    break
                digest.update(block)
                received += len(block)
                assert received <= SIZE
                time.sleep(0.03)
            value = {'date': '2026-11-07', 'direction': 'original-send', 'declaredBytes': length,
                     'receivedBytes': received, 'ending': ending, 'receivedPrefixSha256': digest.hexdigest(),
                     'seconds': round(time.monotonic() - started, 3),
                     'partialBodyThenDisconnected': ending in ('eof', 'connection-reset') and 0 < received < length,
                     'nativeCancelClickQualified': False, 'wholeF18Qualified': False}
            report.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
            print(json.dumps(value), flush=True)
            assert value['partialBodyThenDisconnected']


# 日期：2026-11-07；原版中止后以同一目标端口接收新任务，完整内容必须与输入摘要一致。
def recovery():
    report = OUTPUT / 'original-send-after-cancel-peer.json'
    assert not report.exists()
    expected = (ROOT / RECOVERY).read_bytes()
    with socket.socket() as server:
        server.bind(('127.0.0.1', PORT))
        server.listen(1)
        server.settimeout(300)
        print(json.dumps({'event': 'listening', 'port': PORT, 'case': 'after-cancel'}), flush=True)
        with server.accept()[0] as connection:
            connection.settimeout(30)
            count, total = struct.unpack('<qq', exact(connection, 16))
            name = bytearray()
            while (byte := exact(connection, 1)) != b'\0':
                name.extend(byte)
                assert len(name) <= 1024
            length, = struct.unpack('<q', exact(connection, 8))
            assert count == 1 and total == length == len(expected) and name.decode('utf-8') == RECOVERY
            assert exact(connection, length) == expected and connection.recv(1) == b''
    value = {'date': '2026-11-07', 'direction': 'original-send', 'receivedBytes': len(expected),
             'sha256': hashlib.sha256(expected).hexdigest(), 'sameDestinationPort': PORT,
             'contentVerified': True, 'nativeCompletionObserved': False}
    report.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


# 日期：2026-11-07；每项独立新原件且失败保留，只驱动本次明确选择的测试阶段。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'receive', 'recovery'))
    arguments = parser.parse_args()
    {'prepare': prepare, 'receive': receive, 'recovery': recovery}[arguments.mode]()


if __name__ == '__main__':
    main()

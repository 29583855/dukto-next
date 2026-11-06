"""日期：2026-11-07；独立慢速R6发送器，核对原版实际接收中止和下一批完整接收。"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import time

OUTPUT = Path.cwd() / 'docs/validation/2026-11-07/original-r6-cancel'
NAME = 'dukto-r6-receive-cancel-20261107-85f7.bin'
RECOVERY = 'dukto-r6-receive-recovery-20261107-85f7.txt'
SIZE = 128 * 1024**2
DESTINATION = Path('E:/software')


# 日期：2026-11-07；只接触唯一生成文件名，正文逐8KiB发送；真实断开与最后文件状态分开记录。
def cancel():
    report = OUTPUT / 'original-receive-cancel-peer.json'
    assert not report.exists() and DESTINATION.is_dir() and not (DESTINATION / NAME).exists()
    block = bytes(range(256)) * 32
    sent, error = 0, None
    started = time.monotonic()
    with socket.create_connection(('127.0.0.1', 4644), timeout=20) as connection:
        connection.settimeout(10)
        connection.sendall(struct.pack('<qq', 1, SIZE) + NAME.encode('utf-8') + b'\0' + struct.pack('<q', SIZE))
        print(json.dumps({'event': 'body-started', 'declaredBytes': SIZE, 'fileName': NAME}), flush=True)
        while sent < SIZE and time.monotonic() - started < 240:
            try:
                connection.sendall(block)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exception:
                error = type(exception).__name__
                break
            sent += len(block)
            time.sleep(0.03)
    time.sleep(0.5)
    target = DESTINATION / NAME
    value = {'date': '2026-11-07', 'direction': 'original-receive', 'declaredBytes': SIZE,
             'bytesSubmittedToSocket': sent, 'disconnect': error,
             'seconds': round(time.monotonic() - started, 3), 'fileName': NAME,
             'targetExistsAfterDisconnect': target.exists(),
             'targetBytesAfterDisconnect': target.stat().st_size if target.exists() else None,
             'peerDisconnectBeforeComplete': error is not None and 0 < sent < SIZE,
             'nativeCancelClickQualified': False, 'wholeF18Qualified': False}
    report.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    assert value['peerDisconnectBeforeComplete']


# 日期：2026-11-07；在同一原版实例和端口发送新唯一文件，完整落盘字节必须与独立输入一致。
def recovery():
    report = OUTPUT / 'original-receive-after-cancel-peer.json'
    target = DESTINATION / RECOVERY
    assert not report.exists() and not target.exists()
    payload = '原版接收中止后新批次\nRecovery café\n'.encode('utf-8')
    with socket.create_connection(('127.0.0.1', 4644), timeout=10) as connection:
        connection.sendall(struct.pack('<qq', 1, len(payload)) + RECOVERY.encode('utf-8') + b'\0' + struct.pack('<q', len(payload)) + payload)
        connection.shutdown(socket.SHUT_WR)
        connection.settimeout(10)
        assert connection.recv(1) == b''
    deadline = time.monotonic() + 10
    while not target.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert target.read_bytes() == payload
    value = {'date': '2026-11-07', 'direction': 'original-receive', 'fileName': RECOVERY,
             'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
             'contentVerified': True, 'originalPort': 4644, 'nativeCompletionObserved': False}
    report.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


# 日期：2026-11-07；单个阶段仅生成新原件，任何原断言失败均保留，不重命名为产品通过。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('cancel', 'recovery'))
    arguments = parser.parse_args()
    {'cancel': cancel, 'recovery': recovery}[arguments.mode]()


if __name__ == '__main__':
    main()

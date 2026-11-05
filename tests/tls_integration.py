"""日期：2026-11-04；真实 TLS 握手、数据回传及主机名错误拒绝测试。"""

import argparse
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading


# 日期：2026-11-04；服务仅在本机回环监听，证书和私钥在测试结束自动清理。
def serve(listener, context):
    try:
        with listener.accept()[0] as client:
            with context.wrap_socket(client, server_side=True) as secure:
                secure.sendall(secure.recv(1024))
    except ssl.SSLError:
        pass
    finally:
        listener.close()


# 日期：2026-11-04；使用临时自签证书为正反两种校验用例建立独立 TLS 服务。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--report")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="dukto-tls-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run([args.openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                        "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True, timeout=30)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        for hostname, result in [("localhost", "accept"), ("wrong.invalid", "reject")]:
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)
            port = listener.getsockname()[1]
            thread = threading.Thread(target=serve, args=(listener, context), daemon=True)
            thread.start()
            run = subprocess.run([args.executable, str(cert), str(port), hostname, result],
                                 capture_output=True, text=True, encoding="utf-8", timeout=15)
            thread.join(timeout=10)
            assert run.returncode == 0, (run.stdout, run.stderr)
            results.append(json.loads(run.stdout))
    report = json.dumps(results, ensure_ascii=False, indent=2)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

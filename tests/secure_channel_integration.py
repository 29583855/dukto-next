"""日期：2026-11-04；独立 Python TLS 线样本验证生产安全通道，证书和密钥仅存临时目录。"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time


# 日期：2026-11-04；测试不复用生产 codec，按协议偏移单独构造固定大端头。
def frame(kind, payload, length=None):
    return struct.pack(">8sHHHHQII", b"DKTNEXT1", 1, 0, kind, 0, 7,
                       len(payload) if length is None else length, 0) + payload


# 日期：2026-11-04；精确读取单帧，独立核对客户端发出的能力帧和 64 位字符串。
def exact(stream, length):
    result = bytearray()
    while len(result) < length:
        data = stream.recv(length - len(result))
        if not data:
            raise EOFError("peer disconnected before complete test frame")
        result.extend(data)
    return bytes(result)


# 日期：2026-11-05；证书显式声明服务器用途/密钥用法，覆盖有效期/主机名，不更改系统信任或时间。
def certificates(root, openssl):
    cert, key, csr = root / "valid.pem", root / "key.pem", root / "request.pem"
    # 日期：2026-11-05；隔离系统req扩展；OpenSSL1.1的默认v3_ca与-addext会重复basicConstraints。
    request_config = root / "request.cnf"
    request_config.write_text("[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=localhost\n", encoding="ascii")
    common = [openssl, "req", "-config", str(request_config), "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
              "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
              "-addext", "basicConstraints=critical,CA:FALSE",
              "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
              "-addext", "extendedKeyUsage=serverAuth", "-keyout", str(key)]
    subprocess.run(common + ["-x509", "-days", "1", "-out", str(cert)],
                   capture_output=True, check=True, timeout=30)
    subprocess.run([openssl, "req", "-config", str(request_config), "-new", "-key", str(key), "-subj", "/CN=localhost", "-out", str(csr)],
                   capture_output=True, check=True, timeout=30)
    (root / "index").touch()
    (root / "serial").write_text("1000\n", encoding="ascii")
    config = root / "ca.cnf"
    config.write_text("[ca]\ndefault_ca=test\n[test]\ndatabase=" + (root / "index").as_posix() +
                      "\nserial=" + (root / "serial").as_posix() + "\nnew_certs_dir=" + root.as_posix() +
                      "\ndefault_md=sha256\npolicy=policy\nx509_extensions=extensions\nunique_subject=no\n"
                      "[policy]\ncommonName=supplied\n[extensions]\n"
                      "subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\n"
                      "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n",
                      encoding="ascii")
    results = {"valid": cert}
    for name, start, end in [("expired", "20000101000000Z", "20010101000000Z"),
                             ("future", "20990101000000Z", "21000101000000Z")]:
        target = root / (name + ".pem")
        subprocess.run([openssl, "ca", "-batch", "-selfsign", "-keyfile", str(key), "-in", str(csr),
                        "-out", str(target), "-config", str(config), "-startdate", start, "-enddate", end],
                       capture_output=True, check=True, timeout=30)
        results[name] = target
    purpose = root / "client-only.cnf"
    purpose.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n"
                       "basicConstraints=critical,CA:FALSE\n"
                       "keyUsage=critical,digitalSignature,keyEncipherment\n"
                       "extendedKeyUsage=clientAuth\n", encoding="ascii")
    target = root / "client-only.pem"
    subprocess.run([openssl, "x509", "-req", "-in", str(csr), "-signkey", str(key), "-days", "1",
                    "-extfile", str(purpose), "-out", str(target)], capture_output=True, check=True, timeout=30)
    results["clientOnly"] = target
    return results, key


# 日期：2026-11-07；独立TLS监听覆盖连续缓冲/断连尾帧/缓冲中取消及原分片/发送失败边界。
def run_client(executable, certificate, key, hostname, ca, pin, mode, expected, payload=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    errors = []

    # 日期：2026-11-07；连续帧使用独立编码与单次TLS发送，故意断连仅影响本例，意外异常使测试失败。
    def serve():
        try:
            with listener.accept()[0] as raw:
                raw.settimeout(4)
                with context.wrap_socket(raw, server_side=True) as secure:
                    header = struct.unpack(">8sHHHHQII", exact(secure, 32))
                    assert header == (b"DKTNEXT1", 1, 0, 1, 0, 7, header[6], 0), header
                    request = json.loads(exact(secure, header[6]))
                    assert request == {"test": "independent-client", "size": "9007199254740993"}, request
                    if mode.startswith("burst-"):
                        data = b"".join(frame(2, json.dumps({"sequence": str(index)}).encode("ascii"))
                                        for index in range(512))
                        secure.sendall(data)
                        if mode == "burst-close":
                            secure.shutdown(socket.SHUT_WR)
                        else:
                            time.sleep(0.1)
                    elif mode.startswith("write-"):
                        # 日期：2026-11-05；先核对真实首片段再发送原始失败，失败正文跨多次TLS写入时也不得误解码半帧。
                        data_header = struct.unpack(">8sHHHHQII", exact(secure, 32))
                        assert data_header[:6] == (b"DKTNEXT1", 1, 0, 40, 0, 7)
                        assert 40 < data_header[6] <= 256 * 1024 + 40
                        exact(secure, data_header[6])
                        if mode == "write-abrupt":
                            return
                        body = b'{"code":5,"stage":"receive","message":"independent disk failure"}'
                        if mode == "write-invalid-failure":
                            body = b'{"code":99,"stage":"receive","message":"invalid code"}'
                        response = frame(7, body)
                        if mode == "write-wrong-correlation":
                            response = response[:16] + struct.pack(">Q", 8) + response[24:]
                        if mode in ("write-fragmented-failure", "write-fragmented-failure-close"):
                            for start, end in ((0, 13), (13, 35), (35, 47), (47, len(response))):
                                secure.sendall(response[start:end])
                                time.sleep(0.01)
                        else:
                            secure.sendall(response)
                        if mode.endswith("-close"):
                            secure.shutdown(socket.SHUT_WR)
                            while secure.recv(64 * 1024):
                                pass
                        else:
                            time.sleep(0.1)
                    elif mode in ("cancel", "checkpoint-cancel"):
                        time.sleep(0.5)
                    elif mode == "checkpoint-disconnect":
                        pass
                    elif mode == "timeout":
                        data = frame(2, b'{"test":"server-accepted"}')
                        for byte in data:
                            secure.sendall(bytes([byte]))
                            time.sleep(0.05)
                    else:
                        data = payload if payload is not None else frame(2, b'{"test":"server-accepted"}')
                        for offset in range(0, len(data), 7):
                            secure.sendall(data[offset:offset + 7])
        except (ssl.SSLError, ConnectionError, EOFError):
            if expected == 0:
                errors.append("successful case disconnected")
        except BaseException as error:
            errors.append(repr(error))
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    result = subprocess.run([executable, "client", str(ca), str(listener.getsockname()[1]), hostname,
                             pin, mode], capture_output=True, encoding="utf-8", timeout=8)
    thread.join(timeout=6)
    assert not thread.is_alive() and not errors, (mode, expected, errors, result.stdout, result.stderr)
    assert result.returncode == expected and not result.stderr, (result.returncode, result.stdout, result.stderr)
    event = json.loads(result.stdout)
    if mode in ("burst-open", "burst-close"):
        assert event["passed"] and event["frames"] == 512, event
    if mode in ("write-failure", "write-fragmented-failure", "write-failure-close", "write-fragmented-failure-close"):
        assert event["code"] == 5 and event["stage"] == "receive", event
    if mode in ("timeout", "cancel"):
        assert event["elapsedMs"] < 1500, event
    return {"passed": True, "exitCode": result.returncode, "elapsedMs": event["elapsedMs"],
            "stage": event.get("stage", "encrypted-frame-exchange")}


# 日期：2026-11-04；独立 Python 客户端使用正常 CA 验证，检验生产服务端 TLS 和同连接返回行为。
def server_case(executable, certificate, key):
    process = subprocess.Popen([executable, "server", str(certificate), str(key)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    try:
        listening = json.loads(process.stdout.readline())
        context = ssl.create_default_context(cafile=str(certificate))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection(("127.0.0.1", listening["port"]), timeout=4) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as secure:
                secure.sendall(frame(1, b'{"test":"independent-client"}'))
                header = exact(secure, 32)
                expected = frame(2, b'{"test":"server-accepted"}')
                assert header + exact(secure, len(expected) - 32) == expected
        out, err = process.communicate(timeout=5)
        assert process.returncode == 0 and not err and json.loads(out)["passed"], (out, err)
        return {"passed": True, "exitCode": 0}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


# 日期：2026-11-07；连续帧、缓冲取消与原信任/期限/发送失败实际执行，失败保留原报告。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    results = {}
    with tempfile.TemporaryDirectory(prefix="dukto-secure-channel-") as temporary:
        root = Path(temporary).resolve()
        certs, key = certificates(root, args.openssl)
        pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certs["valid"].read_text())).hexdigest()
        cases = [("trustedCa", "valid", "localhost", certs["valid"], "none", "ok", 0, None),
                 ("wrongHostnameCa", "valid", "wrong.invalid", certs["valid"], "none", "ok", 4, None),
                 ("pinnedSelfSigned", "valid", "localhost", "none", pin, "ok", 0, None),
                 ("untrustedNoPin", "valid", "localhost", "none", "none", "ok", 4, None),
                 ("wrongPin", "valid", "localhost", "none", "11" * 32, "ok", 4, None),
                 ("wrongPinTrustedCa", "valid", "localhost", certs["valid"], "11" * 32, "ok", 4, None),
                 ("wrongHostnamePinned", "valid", "wrong.invalid", "none", pin, "ok", 4, None),
                 ("duplicateJson", "valid", "localhost", certs["valid"], "none", "ok", 2,
                  frame(2, b'{"a":1,"a":2}')),
                 ("oversizeHeader", "valid", "localhost", certs["valid"], "none", "ok", 2,
                  frame(2, b"", 65537)),
                 ("truncatedBody", "valid", "localhost", certs["valid"], "none", "ok", 3,
                  frame(2, b"{", 2)),
                 ("absoluteFrameTimeout", "valid", "localhost", certs["valid"], "none", "timeout", 3, None),
                 ("atomicCancellation", "valid", "localhost", certs["valid"], "none", "cancel", 7, None),
                 ("scanDisconnection", "valid", "localhost", certs["valid"], "none", "checkpoint-disconnect", 3, None),
                 ("scanCancellation", "valid", "localhost", certs["valid"], "none", "checkpoint-cancel", 7, None)]
        cases.append(("observerFragmentedNormalResponse", "valid", "localhost", certs["valid"], "none",
                      "observe-ok", 0, frame(2, b'{"test":"server-accepted","padding":"' + b"x" * 256 + b'"}')))
        for name, mode, code in (("bufferedBurst", "burst-open", 0),
                                  ("bufferedBurstAfterDisconnect", "burst-close", 0),
                                  ("bufferedBurstCancellation", "burst-cancel", 7)):
            cases.append((name, "valid", "localhost", certs["valid"], "none", mode, code, None))
        for mode, expected_code in (("write-failure", 5), ("write-fragmented-failure", 5),
                                    ("write-wrong-correlation", 6), ("write-invalid-failure", 2),
                                    ("write-abrupt", 3), ("write-failure-close", 5), ("write-fragmented-failure-close", 5)):
            cases.append((mode, "valid", "localhost", certs["valid"], "none", mode, expected_code, None))
        for label in ("expired", "future", "clientOnly"):
            certificate_text = certs[label].read_text()
            certificate_text = certificate_text[certificate_text.index("-----BEGIN CERTIFICATE-----"):]
            value = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate_text)).hexdigest()
            cases.append((label + "Pinned", label, "localhost", "none", value, "ok", 4, None))
        for name, cert, hostname, ca, value, mode, expected, payload in cases:
            try:
                results[name] = run_client(executable, certs[cert], key, hostname, ca, value, mode, expected, payload)
            except BaseException as error:
                Path(args.report).write_text(json.dumps({"date": "2026-11-05", "passed": False,
                    "failedCase": name, "failureType": type(error).__name__, "cases": results},
                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                raise AssertionError("independent TLS case failed: " + name) from error
        results["productionServer"] = server_case(executable, certs["valid"], key)
        identity_dir = root / "generated-identity"
        generated = subprocess.run([executable, "identity", str(identity_dir)], capture_output=True,
                                   encoding="utf-8", timeout=60)
        assert generated.returncode == 0 and not generated.stderr, (generated.stdout, generated.stderr)
        info = json.loads(generated.stdout)
        record = json.loads((identity_dir / "identity.json").read_text(encoding="utf-8"))
        generated_cert, generated_key = root / "generated-cert.pem", root / "generated-key.pem"
        generated_cert.write_text(record["certificate"], encoding="ascii")
        generated_key.write_text(record["privateKey"], encoding="ascii")
        results["generatedIdentityPinned"] = run_client(
            executable, generated_cert, generated_key, "localhost", "none", info["fingerprint"], "ok", 0)
        results["generatedIdentityServer"] = server_case(executable, generated_cert, generated_key)
    report = {"date": "2026-11-04", "passed": True, "scope": "production SecureChannel; independent TLS endpoints",
              "cases": results}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

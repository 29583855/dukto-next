"""日期：2026-11-05；经已有 SSH 测试环境验证 Windows/Linux 新版 TLS 五档双向互传。"""

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

from service_integration import free_port


FIXTURE = """from pathlib import Path
import sys
p=Path(sys.argv[1]); (p/'中文目录'/'空目录').mkdir(parents=True)
(p/'中文目录'/'empty.txt').touch()
(p/'中文目录'/'文本.txt').write_text('跨系统 café 🙂\\n',encoding='utf-8')
for name,size in [('large.bin',8*1024*1024+37),('second.bin',4*1024*1024+19)]:
    with (p/name).open('wb') as f:
        remaining=size
        block=bytes(range(256))*1024
        while remaining:
            part=block[:min(remaining,len(block))]; f.write(part); remaining-=len(part)
for i in range(37): (p/f'window-{i:02}.dat').write_bytes(bytes([i])*(i*131))
"""

INVENTORY = """from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1]); result=[]
for q in sorted(p.rglob('*')):
    item={'path':q.relative_to(p).as_posix(),'directory':q.is_dir()}
    if q.is_file():
        h=hashlib.sha256()
        with q.open('rb') as f:
            while part:=f.read(256*1024): h.update(part)
        item.update(bytes=q.stat().st_size,sha256=h.hexdigest())
    result.append(item)
print(json.dumps(result,ensure_ascii=False))
"""


class Side:
    # 日期：2026-11-05；远端参数统一 shlex 转义；SSH 密钥/主机校验沿用专用环境且不关闭验证。
    def __init__(self, executable, python, ssh=None):
        self.executable = executable
        self.python = python
        self.ssh = ssh

    # 日期：2026-11-05；本地命令不经过 shell，远端只执行显式列出的参数。
    def command(self, arguments, forwarding=None):
        if arguments and arguments[0] == self.python:
            arguments = [arguments[0], "-X", "utf8", *arguments[1:]]
        if self.ssh:
            prefix = self.ssh[:-1]
            if forwarding:
                prefix += ["-o", "ExitOnForwardFailure=yes", "-L", forwarding]
            return [*prefix, self.ssh[-1], "exec " + shlex.join(arguments)]
        assert not forwarding
        return arguments

    # 日期：2026-11-05；标准输出捕获在内存，凭据复制不回显；失败诊断只包括命令退出码和标准错误。
    def execute(self, arguments, data=None, timeout=180):
        result = subprocess.run(self.command(arguments), input=data, capture_output=True, timeout=timeout)
        assert result.returncode == 0 and not result.stderr, (result.returncode, result.stderr.decode("utf-8", "replace"),
                                                              result.stdout.decode("utf-8", "replace") if arguments[0] == self.executable else "")
        return result.stdout

    # 日期：2026-11-05；所有 CLI 操作读取真实 JSONL，完成事件/错误不能被 SSH 成功退出掩盖。
    def cli(self, state, arguments):
        output = self.execute([self.executable, *arguments, "--state-directory", str(state), "--json"])
        return [json.loads(line) for line in output.decode("utf-8").splitlines()]

    # 日期：2026-11-05；仅创建测试持有目录，远端路径作为独立参数传入 Python。
    def mkdir(self, path):
        self.execute([self.python, "-c", "from pathlib import Path;import sys;Path(sys.argv[1]).mkdir(parents=True)", str(path)])

    # 日期：2026-11-05；逐文件流式摘要并登记空目录，避免应用自身成功状态替代文件验证。
    def inventory(self, path):
        return json.loads(self.execute([self.python, "-c", INVENTORY, str(path)]))

    # 日期：2026-11-05；秘密只用 stdin 进入已由生产 PrivateStore 创建的根，POSIX 新文件固定 0600。
    def write_private(self, path, data):
        script = """import os,sys
p=sys.argv[1]
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f: f.write(sys.stdin.buffer.read())
"""
        self.execute([self.python, "-c", script, str(path)], data)


class QmpForward:
    # 日期：2026-11-05；仅操作显式指定的本机 QEMU 测试监控口，转发也只监听 Windows 回环。
    def __init__(self, qmp_port, local_port, remote_port):
        self.qmp_port = qmp_port
        self.rule = f"tcp:127.0.0.1:{local_port}"
        self.destination = f"-:{remote_port}"

    # 日期：2026-11-05；QMP 返回 ID 必须匹配，忽略独立异步事件而不把事件当作命令确认。
    def request(self, command, expected=""):
        with socket.create_connection(("127.0.0.1", self.qmp_port), timeout=10) as connection:
            stream = connection.makefile("rwb")
            assert "QMP" in json.loads(stream.readline())
            for index, operation in enumerate([{"execute": "qmp_capabilities"},
                                               {"execute": "human-monitor-command", "arguments": {"command-line": command}}]):
                stream.write(json.dumps({**operation, "id": index}).encode() + b"\n")
                stream.flush()
                while True:
                    response = json.loads(stream.readline())
                    if response.get("id") == index:
                        break
                assert "return" in response, response
            assert response["return"].strip() == expected, response

    # 日期：2026-11-05；实时添加一条独立回环映射，不重启 VM、不更改 SSH 转发策略。
    def __enter__(self):
        self.request("hostfwd_add " + self.rule + self.destination)
        return self

    # 日期：2026-11-05；成功/失败均移除本测试创建的映射，不修改已有 SSH 或 R6 映射。
    def __exit__(self, kind, value, traceback):
        self.request("hostfwd_remove " + self.rule, "host forwarding rule for " + self.rule + " removed")


# 日期：2026-11-05；启动的是生产常驻服务；独立读取就绪，剩余诊断写自有临时文件以免管道阻塞。
def start_service(side, state, port, output, error, forwarding=None, bind="127.0.0.1"):
    arguments = [side.executable, "serve", "start", "--bind", bind, "--port", str(port),
                 "--state-directory", str(state), "--timeout", "30", "--json"]
    process = subprocess.Popen(side.command(arguments, forwarding), stdout=output, stderr=error)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        output.flush()
        with open(output.name, "rb") as source:
            first = source.readline()
        if first.endswith(b"\n"):
            value = json.loads(first)
            assert value["event"] == "service-listening" and value["port"] == port, value
            return process
        assert process.poll() is None, "service exited before listening"
        time.sleep(0.1)
    process.kill()
    process.wait(10)
    raise AssertionError("service readiness deadline")


# 日期：2026-11-05；一方向为一个客户端 OS/服务端 OS 组合，每档真实上传/下载并重试相同请求。
def exercise(client, server, client_root, server_root, logs, label, qmp_port):
    client_state = str(client_root) + "/client"
    server_state = str(server_root) + "/server"
    shared = str(server_root) + "/shared"
    source = str(client_root) + "/样本"
    server.mkdir(shared)
    client.execute([client.python, "-c", FIXTURE, source])
    expected = client.inventory(source)
    info = server.cli(server_state, ["serve", "init", "--server-name", "127.0.0.1", "--server-name", "10.0.2.2"])[0]
    permissions = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
    server.cli(server_state, ["serve", "share", "add", "--path", shared, *permissions])
    offer = server.cli(server_state, ["serve", "pairing", *permissions])[0]
    credential = server.execute([server.python, "-c", "from pathlib import Path;import sys;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())", offer["credentialFile"]])
    inbox_state = str(client_root) + "/mailbox"
    client.cli(inbox_state, ["serve", "init", "--server-name", "127.0.0.1"])
    inbox = inbox_state + "/service/incoming.json"
    client.write_private(inbox, credential)
    del credential
    local_port = free_port()
    remote_port = free_port() if server.ssh else None
    port = remote_port or local_port
    forwarding = f"127.0.0.1:{local_port}:127.0.0.1:{port}" if server.ssh and not qmp_port else None
    route = QmpForward(qmp_port, local_port, port) if server.ssh and qmp_port else nullcontext()
    bind = "0.0.0.0" if server.ssh and qmp_port else "127.0.0.1"
    address = f"127.0.0.1:{local_port}" if server.ssh else f"10.0.2.2:{port}"
    result = []
    with route, open(logs / (label + ".stdout"), "w+b") as output, open(logs / (label + ".stderr"), "w+b") as error:
        service = start_service(server, server_state, port, output, error, forwarding, bind)
        # 日期：2026-11-05；退出时按唯一状态目录定位测试服务，不影响其它服务和长时接收进程。
        try:
            client.cli(client_state, ["pair", "--to", address, "--fingerprint", info["fingerprint"], "--credential-file", inbox])
            for lanes in (1, 2, 4, 8, 16):
                directory = shared + f"/run-{lanes}"
                server.mkdir(directory)
                upload = ["upload", "--share", "data", "--remote-path", f"run-{lanes}",
                          "--path", source, "--threads", str(lanes), "--request-id", str(uuid.uuid4())]
                started = time.monotonic()
                sent = client.cli(client_state, upload)[-1]
                upload_seconds = time.monotonic() - started
                assert sent["event"] == "transfer-completed" and sent["state"] == "completed" and sent["bytes"] == sent["total"], sent
                assert sent["channels"] == str(lanes), sent
                assert server.inventory(directory + "/样本") == expected
                repeated = client.cli(client_state, upload)[-1]
                assert repeated["taskId"] == sent["taskId"] and repeated["state"] == "completed", repeated
                assert server.execute([server.python, "-c", "from pathlib import Path;import json,sys;print(json.dumps(sorted(p.name for p in Path(sys.argv[1]).iterdir()),ensure_ascii=False))", directory]).decode("utf-8").strip() == '["样本"]'
                destination = str(client_root) + f"/download-{lanes}"
                client.mkdir(destination + "/样本/keep")
                download = ["download", "--share", "data", "--remote-path", f"run-{lanes}/样本",
                            "--output", destination, "--threads", str(lanes), "--request-id", str(uuid.uuid4())]
                started = time.monotonic()
                received = client.cli(client_state, download)[-1]
                download_seconds = time.monotonic() - started
                assert received["event"] == "transfer-completed" and received["state"] == "completed" and received["bytes"] == received["total"], received
                assert received["channels"] == str(lanes), received
                assert client.inventory(destination + "/样本 (2)") == expected
                again = client.cli(client_state, download)[-1]
                assert again["taskId"] == received["taskId"] and again["state"] == "completed", again
                names = json.loads(client.execute([client.python, "-c", "from pathlib import Path;import json,sys;print(json.dumps(sorted(p.name for p in Path(sys.argv[1]).iterdir()),ensure_ascii=False))", destination]))
                assert names == ["样本", "样本 (2)"], names
                result.append({"channels": lanes, "uploadSeconds": round(upload_seconds, 3),
                               "downloadSeconds": round(download_seconds, 3), "bytes": sent["total"],
                               "uploadTask": sent["taskId"], "downloadTask": received["taskId"],
                               "allHashesMatch": True, "idempotentRetries": True, "keepBoth": True})
                print(json.dumps({"pair": label, **result[-1]}, ensure_ascii=False), flush=True)
        finally:
            if server.ssh:
                # 日期：2026-11-05；精确比对 executable 与本次 state 参数，不影响其它服务或长时测试。
                stop = """from pathlib import Path
import os,signal,sys
for p in Path('/proc').iterdir():
    if not p.name.isdigit(): continue
    try: args=(p/'cmdline').read_bytes().split(b'\\0')
    except (FileNotFoundError,PermissionError,ProcessLookupError): continue
    expected=[v.encode() for v in sys.argv[1:]]
    if args and args[0]==expected[0] and b'serve' in args and b'start' in args and expected[1] in args:
        os.kill(int(p.name),signal.SIGTERM)
"""
                server.execute([server.python, "-c", stop, server.executable, server_state])
            elif service.poll() is None:
                service.kill()
            service.wait(30)
            error.seek(0)
            diagnostic = error.read().decode("utf-8", "replace")
            assert not diagnostic, diagnostic
    return {"runs": result, "inventory": expected}


# 日期：2026-11-05；临时状态、凭据和样本全部自有；远端删除前验证刚创建目录和固定父目录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("windows_executable")
    parser.add_argument("--remote-executable", required=True)
    parser.add_argument("--ssh-host", default="dukto@127.0.0.1")
    parser.add_argument("--ssh-port", default="22024")
    parser.add_argument("--ssh-key", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--qmp-port", type=int, help="Existing local QEMU monitor, if SSH forwarding is disabled")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    assert os.name == "nt", "driver must run on the Windows test host"
    ssh = ["C:/Windows/System32/OpenSSH/ssh.exe", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
           "-o", "UserKnownHostsFile=" + str(Path(args.known_hosts).resolve()), "-i", str(Path(args.ssh_key).resolve()),
           "-p", args.ssh_port, args.ssh_host]
    import sys
    windows = Side(str(Path(args.windows_executable).resolve()), sys.executable)
    linux = Side(args.remote_executable, "python3", ssh)
    remote_root = linux.execute(["mktemp", "-d", "/home/dukto/next-interop-XXXXXX"]).decode().strip()
    assert remote_root.startswith("/home/dukto/next-interop-") and "\n" not in remote_root
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-cross-os-") as temporary:
            root = Path(temporary)
            local_exe = root / "dukto-cli.exe"
            shutil.copyfile(windows.executable, local_exe)
            windows.executable = str(local_exe)
            results = {"windowsClientLinuxServer": exercise(windows, linux, root / "a", remote_root + "/a", root, "windows-client", args.qmp_port),
                       "linuxClientWindowsServer": exercise(linux, windows, remote_root + "/b", root / "b", root, "linux-client", args.qmp_port)}
            report = {"date": "2026-11-05", "passed": True, "results": results,
                      "scope": "Windows x64 and Alpine Linux x64, production TLS/CLI upload and download, five channel levels and both client/server orientations; QEMU NAT/SSH forwarding, not physical LAN throughput or macOS validation"}
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        cleanup = """from pathlib import Path
import shutil,sys
p=Path(sys.argv[1])
assert p.parent==Path('/home/dukto') and p.name.startswith('next-interop-') and not p.is_symlink()
shutil.rmtree(p)
"""
        linux.execute([linux.python, "-c", cleanup, remote_root])


if __name__ == "__main__":
    main()

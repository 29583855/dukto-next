"""日期：2026-11-05；真实 TLS 配对后的本机主体列表、权限/撤销/轮换状态及有界 CLI 分页。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import uuid

from service_integration import free_port, run


# 日期：2026-11-05；同时验证人类输出与 JSONL；标准错误或非预期退出不能作为空页处理。
def invoke(executable, state, arguments, human=False, expected=0):
    result = subprocess.run([executable, *arguments, "--state-directory", str(state),
                             *([] if human else ["--json"])], capture_output=True,
                            encoding="utf-8", timeout=60)
    assert result.returncode == expected and not result.stderr, (result.returncode, result.stderr, result.stdout[-65536:])
    return result.stdout if human else [json.loads(line) for line in result.stdout.splitlines()]


# 日期：2026-11-05；公开页严格限定字段，不能用未命中固定秘密字符串代替结构检查。
def check_page(page):
    assert set(page) == {"eventVersion", "event", "entries", "after", "more", "message"}
    assert page["eventVersion"] == 1 and page["event"] == "clients"
    assert len(page["entries"]) <= 100
    assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 65536
    for entry in page["entries"]:
        assert set(entry) == {"client", "revision", "grants", "revoked"}
        assert str(uuid.UUID(entry["client"])) == entry["client"]
        assert type(entry["revoked"]) is bool and int(entry["revision"]) > 0


# 日期：2026-11-05；两真实客户证明状态来源，其后合法私有测试主体只用于条数及字节边界压力。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    original = Path(args.executable).resolve()
    binary_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    page_sizes = []
    with tempfile.TemporaryDirectory(prefix="dukto-clients-") as temporary:
        root = Path(temporary)
        executable = str(original)
        # 日期：2026-11-05；开发构建复制自有 EXE；独立发布目录保留相邻 DLL 的正常加载关系。
        if os.name == "nt" and not (original.parent / "Qt5Core.dll").is_file():
            local = root / original.name
            shutil.copyfile(original, local)
            executable = str(local)
        state = root / "server"
        shared = root / "shared"
        shared.mkdir()
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, state, ["serve", "share", "add", "--share", "docs", "--path", str(shared),
                                "--allow-browse", "--allow-download", "--allow-upload"])
        empty = invoke(executable, state, ["serve", "clients"])[0]
        check_page(empty)
        assert not empty["entries"] and not empty["more"] and empty["after"] == ""
        port = free_port()
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        clients = []
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            for index in range(2):
                offer, _ = run(executable, state, ["serve", "pairing", "--share", "docs",
                                                   "--allow-browse", "--allow-download"])
                paired, _ = run(executable, root / f"client-{index}", [
                    "pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                    "--credential-file", offer["credentialFile"]])
                clients.append(paired["client"])
            run(executable, state, ["serve", "grant", "--client", clients[0], "--share", "docs", "--allow-browse"])
            run(executable, root / "client-0", ["rotate"])
            run(executable, state, ["serve", "revoke", "--client", clients[1]])
            pages = invoke(executable, state, ["serve", "clients"])
            assert len(pages) == 1
            check_page(pages[0])
            records = {entry["client"]: entry for entry in pages[0]["entries"]}
            assert records[clients[0]]["revision"] == "3" and not records[clients[0]]["revoked"]
            assert records[clients[0]]["grants"] == [{"share": "docs", "browse": True, "download": False, "upload": False}]
            assert records[clients[1]]["revision"] == "2" and records[clients[1]]["revoked"]
            run(executable, root / "client-0", ["auth"])
            run(executable, root / "client-1", ["auth"], 4)
            human = invoke(executable, state, ["serve", "clients"], human=True)
            assert all(client in human for client in clients)
            assert "已撤销" in human and "浏览" in human and "修订" in human
        finally:
            if server.poll() is None:
                server.terminate() if os.name == "nt" else server.send_signal(signal.SIGINT)
            _, error = server.communicate(timeout=30)
            assert not error
        # 日期：2026-11-05；仅生成本测试私有记录；最长 16 共享迫使每页先达到字节上限。
        service = state / "service"
        template = json.loads((service / f"client-{clients[0]}.json").read_text(encoding="utf-8"))
        template["grants"] = [{"share": f"s{index:02d}" + "x" * 61, "browse": True,
                                "download": True, "upload": True} for index in range(16)]
        generated = []
        for index in range(105):
            client = str(uuid.UUID(int=index + 1))
            generated.append(client)
            record = dict(template, client=client)
            # 日期：2026-11-05；POSIX 的默认 0644 会被生产私有库正确拒绝，测试资料必须从创建起即为 0600。
            target = service / f"client-{client}.json"
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as output:
                output.write(json.dumps(record))
            if os.name != "nt":
                assert target.stat().st_mode & 0o777 == 0o600
        expected = sorted(clients + generated)
        pages = invoke(executable, state, ["serve", "clients", "--all"])
        seen = []
        cursor = ""
        for page in pages:
            check_page(page)
            assert page["after"] > cursor
            cursor = page["after"]
            page_sizes.append(len(page["entries"]))
            seen.extend(entry["client"] for entry in page["entries"])
        assert seen == expected and not pages[-1]["more"] and len(pages) > 2
        assert 0 < page_sizes[0] < 100
        first = invoke(executable, state, ["serve", "clients"])[0]
        second = invoke(executable, state, ["serve", "clients", "--cursor", first["after"]])[0]
        assert first == pages[0] and second == pages[1]
        human = invoke(executable, state, ["serve", "clients"], human=True)
        assert "cursor=" + first["after"] in human
        final = invoke(executable, state, ["serve", "clients", "--cursor", expected[-1]])[0]
        check_page(final)
        assert not final["entries"] and not final["more"]
        for cursor in ("../escape", "00000000-0000-0000-0000-000000000000", "{" + expected[0] + "}"):
            error = invoke(executable, state, ["serve", "clients", "--cursor", cursor], expected=2)
            assert error[-1]["event"] == "error"
        # 日期：2026-11-05；全页输出只含公开字段，逐秘密核对涵盖票据、轮换后凭据与服务端摘要。
        public = json.dumps(pages) + human
        for directory in (service, root / "client-0/clients", root / "client-1/clients"):
            for path in directory.glob("*.json"):
                private = json.loads(path.read_text(encoding="utf-8"))
                for key in ("credential", "pendingCredential", "credentialHash", "privateKey", "pairing"):
                    if private.get(key):
                        assert private[key] not in public
    report = {"date": "2026-11-05", "passed": True, "binarySha256": binary_hash,
              "scriptSha256": script_hash,
              "pageSizes": page_sizes, "checks": ["two real TLS paired clients", "grant/rotation/revocation revisions",
              "revoked client authentication refused", "human permissions and UUID selection data",
              "107 identities bounded by 100 records and 64KiB", "manual/all pagination and empty tail",
              "invalid cursors refused", "public schema and no private values"],
              "scope": "local administrator enumeration; pages read current atomic records, not a fixed snapshot"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

# 日期：2026-11-08；固定当前工作树输入，在独立 glibc 虚机完成全新构建及图形/部署验证。
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile


root = Path.cwd()
vm = root / ".tools" / "linux-glibc-vm"
tag = "completion-r134"
destination = root / "docs" / "validation" / "2026-11-08" / f"{tag}-linux-glibc"
if destination.exists():
    raise SystemExit(f"Refusing to overwrite existing evidence: {destination}")
destination.mkdir(parents=True)

ssh = [
    "C:/Windows/System32/OpenSSH/ssh.exe",
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    f"UserKnownHostsFile={vm / 'known_hosts'}",
    "-i",
    str(root / ".tools" / "linux-vm" / "id_ed25519"),
    "-p",
    "22026",
    "dukto@127.0.0.1",
]

files = [root / "CMakeLists.txt", root / ".clang-format", root / "LICENSE", root / "README.md"]
for folder in ("src", "ui", "resources", "tests", "scripts", "third-party", ".github"):
    files.extend(
        path
        for path in (root / folder).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
files = sorted(set(files))
archive = vm / f"source-{tag}.tar.gz"
with tarfile.open(archive, "w:gz") as output:
    for path in files:
        output.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)

manifest = {
    "date": "2026-11-08",
    "tag": tag,
    "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "sourceCommit": None,
    "files": [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ],
}
(destination / "source-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

remote = f"/home/dukto/project-{tag}"
subprocess.run(ssh + [f"test ! -e {remote} && mkdir {remote}"], check=True, timeout=30)
with archive.open("rb") as source:
    subprocess.run(ssh + [f"tar xzf - -C {remote}"], stdin=source, check=True, timeout=180)

command = f"""set -eu
cd {remote}
mkdir -p validation /tmp/runtime-dukto
chmod 700 /tmp/runtime-dukto
export XDG_RUNTIME_DIR=/tmp/runtime-dukto QT_QPA_PLATFORM=offscreen
{{ cat /etc/os-release; uname -a; qmake -query QT_VERSION; g++ --version; openssl version -a; ldd --version; }} > validation/environment.log 2>&1
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > validation/configure.log 2>&1
cmake --build build --parallel 2 > validation/build.log 2>&1
ctest --test-dir build --output-on-failure > validation/ctest.log 2>&1
python3 tests/transfer_integration.py build/dukto-cli --threads 16 --report validation/transfer-16.json > validation/transfer-16.log 2>&1
python3 tests/posix_path_integration.py build/dukto-cli --report validation/posix-path.json > validation/posix-path.log 2>&1
python3 tests/service_integration.py build/dukto-cli --report validation/service.json > validation/service.log 2>&1
QT_QPA_PLATFORM=xcb xvfb-run -a build/ui-tests -o validation/ui-x11.log,txt -o validation/ui-x11.xml,junitxml
QT_QPA_PLATFORM=xcb xvfb-run -a build/server-panel-tests -o validation/server-panel-x11.log,txt -o validation/server-panel-x11.xml,junitxml
weston --backend=headless-backend.so --use-pixman --socket=dukto-wayland-r134 --idle-time=0 --width=1280 --height=900 > validation/weston.log 2>&1 &
weston_pid=$!
trap 'kill "$weston_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 50); do test -S "$XDG_RUNTIME_DIR/dukto-wayland-r134" && break; sleep 0.1; done
export QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=dukto-wayland-r134
build/ui-tests -o validation/ui-wayland.log,txt -o validation/ui-wayland.xml,junitxml
build/server-panel-tests -o validation/server-panel-wayland.log,txt -o validation/server-panel-wayland.xml,junitxml
"""

with (vm / f"{tag}-driver.log").open("wb") as output:
    result = subprocess.run(ssh + ["sh -s"], input=command.encode(), stdout=output, stderr=subprocess.STDOUT, timeout=7200)

results = vm / f"results-{tag}.tar.gz"
with results.open("wb") as output:
    subprocess.run(ssh + [f"cd {remote} && tar czf - validation build/Testing/QtTest"], stdout=output, check=True, timeout=180)
with tarfile.open(results) as source:
    for item in source.getmembers():
        target = (destination / item.name).resolve()
        if not target.is_relative_to(destination.resolve()) or item.issym() or item.islnk():
            raise RuntimeError(f"Unsafe validation artifact path: {item.name}")
        if item.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(item).read())

print(f"glibc validation exit: {result.returncode}")
raise SystemExit(result.returncode)

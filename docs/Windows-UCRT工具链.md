# Windows UCRT64 / Qt5 工具链

更新日期：2026-11-05。此环境已通过本机原生构建与部分运行验收，正式发布包、干净系统、完整平台验收仍在主计划内。

## 已安装及验证版本

| 组件 | 实际版本 |
| --- | --- |
| MSYS2 基础包 | 2026-09-27，x86_64 |
| GCC / libstdc++ | 16.2.0-4，UCRT64 |
| Qt5 base | 5.15.19+kde+r96-1 |
| Qt5 declarative | 5.15.19+kde+r23-1 |
| Qt5 quickcontrols2 | 5.15.19+kde+r5-1 |
| OpenSSL | 3.6.4-1 |
| CMake / Ninja | 4.4.3-3 / 1.13.2-1 |
| C++ 标准 | C++14，扩展关闭 |

77 个 UCRT 依赖包的完整版本、许可证、下载 URL、归档 SHA-256、签名 SHA-256、pacman 签名验证标记及运行探针见 [环境记录](validation/2026-11-04/environment-windows-ucrt.json)。该记录固定了本次验证环境；日后直接更新软件仓库可能取得其他版本，不能用本报告替代新版本测试。

## 来源与安装

基础包来自 [MSYS2 官方仓库](https://repo.msys2.org/distrib/x86_64/msys2-base-x86_64-20260927.tar.xz)，SHA-256 为 `ea2f31a0b6ade63914ce441ffb022f0f6aa96982bfefa2326460a26d5fb01322`，与 [官方发布](https://github.com/msys2/msys2-installer/releases/tag/2026-09-27) 的 asset digest 核对一致。独立解压到项目 `.tools/msys64`，未混用 Dukto 原版 Qt4 或旧 MSVC Qt。

在 `MSYSTEM=UCRT64` 的 MSYS2 login shell 中执行完整更新，再安装：

```sh
pacman -Syu --noconfirm
pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-gcc \
  mingw-w64-ucrt-x86_64-qt5-base mingw-w64-ucrt-x86_64-qt5-declarative \
  mingw-w64-ucrt-x86_64-qt5-quickcontrols2 mingw-w64-ucrt-x86_64-openssl \
  mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-cmake
```

下载过程中 GCC 单包在默认镜像停滞，改从 MSYS2 配置已列出的 BFSU 镜像取得同版本包，随后由 pacman 校验包签名并安装。没有关闭签名校验或更改系统证书信任。安装日志保存在 `.tools/downloads/msys2-install-qt5-r3.log`；归档、签名、安装数据库及许可文件保留在独立工具目录。

## 构建与运行

```powershell
./scripts/build-ucrt.ps1
./scripts/verify.ps1 -Ucrt
$env:PATH="$PWD/.tools/msys64/ucrt64/bin;$env:PATH"
./build/windows-ucrt/dukto-cli.exe --help
./build/windows-ucrt/dukto-gui.exe
```

构建脚本显式指定 GCC、Ninja、Qt 和 OpenSSL 的同一个 UCRT 前缀。`CMakeLists.txt` 的旧 Windows OpenSSL 默认目录只服务于早期 MSVC 环境，新脚本显式覆盖它，避免 MinGW 链接 MSVC import library。新构建产物单独位于 `build/windows-ucrt`；MSVC 环境和结果继续保留。

Qt 工具名带后缀，例如 `qmake-qt5.exe`、`qmlformat-qt5.exe`。运行时探针实际报告 Qt 5.15.19、OpenSSL 3.6.4、C++14 和 SQLite 读写通过。

## 已取得证据与边界

- [15/15 CTest](validation/2026-11-04/ctest-windows-ucrt.log) 含生产 GUI/QML 及恢复点击；[TLS 正反例](validation/2026-11-04/secure-channel-ucrt.json) 和 [CLI 输入/超时](validation/2026-11-04/cli-contracts-ucrt.json) 通过。
- [Windows/Alpine TLS 矩阵](validation/2026-11-04/windows-linux-tls-matrix-ucrt.json)：双方轮流作客户端/服务器，1/2/4/8/16 档全部上传下载、逐文件 SHA、重复请求和同名保留通过。QEMU NAT 只验证跨系统互通，不能据其判断物理网络提速。
- [双主体竞争与资源回落](validation/2026-11-04/parallel-isolation-ucrt.json) 通过。全部缓存总预算、公平排队、长时测试和磁盘清理继续；不把短测资源稳定当成完整内存验收。
- 构建发现并修复 CLI 标准输入取消对 `std::thread::native_handle_type` 的 Windows HANDLE 假定；现在由读取线程复制真实原生句柄，MSVC/MinGW 共用实现。进程退出/超时后关闭该句柄。

Qt 许可证位于 `.tools/msys64/ucrt64/share/licenses/qt5-base`、`qt5-declarative`、`qt5-quickcontrols2`，OpenSSL/GCC 及传递依赖许可也在同一 `share/licenses` 下。发布时仍须生成实际打包依赖清单、附带适用许可与对应源码/修改信息，并验证 CLI、GUI 在干净系统可独立运行；安装工具链不等于完成这些发布义务。

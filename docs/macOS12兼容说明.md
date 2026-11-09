# macOS 12 兼容与安装说明

更新日期：2026-11-09。

本次兼容目标为 macOS 12.0 Monterey 及更新版本，包括截图中的 macOS 12.7.6；分别提供 Intel（x86_64）和 Apple Silicon（arm64）包。在“苹果菜单 → 关于本机”查看“处理器”或“芯片”：Intel 选择 Intel 包，Apple M 系列选择 Apple Silicon 包。无需安装 Qt、OpenSSL 或 Homebrew。

## 旧包无法打开的原因

2026-11-09 的 R158 Mac 包在 macOS 15 构建，GUI、CLI 和所带 OpenSSL 的 Mach-O 加载命令实际要求 macOS 15.0，旧文档也只授予 macOS 15 运行资格。因此在 macOS 12.7.6 上会出现“该应用程序要求 macOS 15.0 或更高版本”的提示。这是最低系统版本问题，与权限设置、网络连接或处理器架构不匹配是不同问题。

兼容构建将应用、Qt 5.15.19 和 OpenSSL 3.6.4 一起按 macOS 12.0 从源码构建，保留 C++14。应用 Info.plist 显式声明最低版本；打包器逐一检查所有框架、插件和动态库及通用二进制的每个切片，高于基线的任一载荷都会使打包失败。不能仅修改 Info.plist 或二进制版本字段来冒充兼容。

## 安装与首次启动

1. 下载注明 macOS 12 兼容的对应架构包，核对随包 SHA256SUMS；不要继续使用旧 R158 Mac 运行包。
2. 使用 macOS 自带归档工具或 `tar -xzf <包名>.tar.gz` 解压，保留整个目录。将里面的 `Dukto Next.app` 拖到“应用程序”，再打开。
3. 当前为 adhoc 签名开发预览，未作 Developer ID 签名和 Apple 公证。首次运行如提示“无法验证开发者”，核对下载来源后按住 Control 点按应用，选择“打开”；macOS 12 也可在“系统偏好设置 → 安全性与隐私 → 通用”查看“仍要打开”。这不能解决系统版本不兼容提示，出现后者应核对是否拿到了旧包。
4. 首次联网时允许软件通信。自动发现需要处于相同可达 IPv4 广播域并允许 UDP 4644；无线网络的 AP 隔离或防火墙规则可能影响发现。CLI 可直接运行解压目录的 `./dukto-cli --help`。

## 兼容构建与验证边界

GitHub Actions 的 Intel 和 Apple Silicon 构建机使用 macOS 15；构建机系统版本与交付程序的最低系统版本分别记录。工作流固定 `MACOSX_DEPLOYMENT_TARGET=12.0` 和 CMake 部署目标，并以相同目标源码编译 Qt/OpenSSL，避免继承 Homebrew 最新二进制库的系统要求。

自动验证包括全部原生核心、Cocoa 主窗口导航、所有原生载荷的最低系统版本、代码签名、中文空格目录迁移、仅系统 PATH 启动 GUI/CLI、16 通道传输、冲突覆盖和断点恢复。打包回执同时记录 `minimumMacOS` 和实际测试机的 `runtimeHostMacOS`。macOS 12.7.6 客户机器的真实运行结果须现场确认，macOS 15 的运行结果不能写成已在 macOS 12 实测；更早于 macOS 12 的系统不在本次兼容目标内。

构建入口：[macos-package.yml](../.github/workflows/macos-package.yml)。依赖来源与固定摘要：[macos_dependencies.json](../scripts/macos_dependencies.json)。版本审计器：[macos_compatibility.py](../scripts/macos_compatibility.py)。当前下载包和实际验收回执随项目 `dist/` 交付，并在 GitHub Release 记录。

本机复现构建时，在 macOS 上安装 Xcode Command Line Tools、CMake、Python 3.12 及构建测试所需的 psutil，然后依次运行：

```bash
python3 scripts/build_macos_dependencies.py --prefix "$PWD/.tools/macos12" --work build-dependencies
export MACOSX_DEPLOYMENT_TARGET=12.0
export CMAKE_PREFIX_PATH="$PWD/.tools/macos12/qt"
export OPENSSL_ROOT_DIR="$PWD/.tools/macos12/openssl"
export PATH="$CMAKE_PREFIX_PATH/bin:$OPENSSL_ROOT_DIR/bin:$PATH"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0
cmake --build build --parallel 3
python3 scripts/package_macos.py --output package-output --minimum-macos 12.0 \
  --dependency-root "$CMAKE_PREFIX_PATH" --dependency-root "$OPENSSL_ROOT_DIR" \
  --dependency-manifest "$PWD/.tools/macos12/dependency-manifest.json"
```

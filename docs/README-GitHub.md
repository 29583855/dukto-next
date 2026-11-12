# Dukto Next

**支持 Windows、macOS、Linux 的局域网与服务器文件传输工具。**

Dukto Next 参考 Dukto R6 的使用体验与协议开发，提供局域网设备发现、文件与文字收发，以及服务器共享、上传下载、多通道传输和任务恢复功能。图形界面与独立命令行工具共用传输核心。

[下载预览版](https://github.com/29583855/dukto-next/releases/tag/preview-gui-memory-20261111) · [查看源码](https://github.com/29583855/dukto-next/tree/codex/macos12-compatibility) · [使用教程](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/服务器上传下载使用说明.md) · [反馈问题](https://github.com/29583855/dukto-next/issues)

更新日期：2026-11-12。当前推荐版本：`preview-gui-memory-20261111`，开发预览版。

## 主要功能

### 局域网收发

- **自动发现设备**：同一可达 IPv4 广播网络中的设备，运行软件后可相互发现。
- **发送文件与文件夹**：支持选择本地内容，也支持拖入发送区域。
- **发送文字与剪贴板文本**：在电脑之间传递链接、代码片段和文字资料。
- **指定地址发送**：通过 IP 或主机名连接目标设备。
- **接收与历史查看**：设置接收目录，查看最近传输及接收批次明细。

设备之间直接传输，无需先上传到公有网盘；没有互联网时，只要本地网络互通，仍可使用。

### 服务器上传下载

- **本机共享**：将已有文件夹配置为共享，分别设置浏览、下载、上传权限。
- **首次配对**：核对服务器证书指纹，通过一次性配对文件建立客户端身份。
- **保存连接资料**：后续使用资料别名连接，无需每次重新配对。
- **远程浏览**：分页查看授权共享内的文件和目录。
- **主动上传与下载**：上传本地文件或文件夹，下载服务器上的文件或文件夹。
- **客户端管理**：管理访问授权、撤销客户端，以及处理证书续期与指纹迁移。
- **独立服务端**：支持通过 CLI 启动服务，适合无桌面服务器和脚本使用。

### 传输与任务管理

- **可选并发档位**：1 / 2 / 4 / 8 / 16，支持多文件并行与大文件分块传输。
- **任务控制**：查询、暂停、取消和继续新版服务器任务。
- **断点恢复**：符合恢复条件的任务可利用持久记录继续，支持已实现恢复路径中的跨重启恢复。
- **同名处理**：默认保留双方、自动重命名；可选择冲突停止、覆盖同名普通文件或跳过。
- **重试与时限**：按任务设置重试和总时限，查看执行状态与结果。
- **命令行与诊断**：提供独立 CLI、JSON 输出及本地诊断入口，方便脚本集成和问题排查。

多通道、任务恢复和远程浏览等扩展能力需要双方使用支持对应功能的 Dukto Next。实际传输速度取决于网络、磁盘、文件组成与两端设备。

## 两种使用模式

| 项目 | 首页局域网收发 | 服务器上传下载 |
| --- | --- | --- |
| 适用场景 | 可信局域网内临时交换文件和文字 | 固定电脑或服务器上的授权共享 |
| 操作入口 | 设备列表或“IP 连接” | “服务器·上传/下载” |
| 连接方式 | 自动发现，或指定 IP / 主机名 | 指定服务器地址，首次配对后使用保存资料 |
| 文件访问 | 向对端主动发送 | 浏览、上传、主动下载 |
| 身份与连接保护 | R6 兼容模式，无 TLS 与配对认证 | TLS、证书指纹核对、客户端授权 |
| 默认端口 | TCP / UDP 4644；头像 TCP 4645 | TCP 4646 |

服务器页面连接的是 Dukto Next 服务，不是 FTP、SFTP、普通网盘或原版 Dukto。首页 R6 兼容模式应在可信局域网中使用。

## 下载与平台支持

所有运行包、对应源码、发行说明和校验文件均在 [GitHub Release](https://github.com/29583855/dukto-next/releases/tag/preview-gui-memory-20261111) 提供。

| 平台 | 架构与范围 | 下载 |
| --- | --- | --- |
| Windows | x64，当前客户端在 Windows 11 实测 | [Windows ZIP](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/DuktoNext-windows-x64-preview.zip) |
| Linux | x86_64，Ubuntu 24.04 及更新版本 | [Linux tar.gz](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/DuktoNext-linux-glibc-x64-preview.tar.gz) |
| macOS · Apple Silicon | arm64，最低构建目标 macOS 12.0 | [Mac arm64 tar.gz](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/DuktoNext-macos-arm64-preview.tar.gz) |
| macOS · Intel | x86_64，最低构建目标 macOS 12.0 | [Mac Intel tar.gz](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/DuktoNext-macos-x86_64-preview.tar.gz) |
| 对应源码 | 包含修复、测试和文档 | [Source tar.gz](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/DuktoNext-source-gui-memory-fix-20261111.tar.gz) |

Mac 两架构已完成原生构建、macOS 15 环境运行检查及全部原生镜像的最低版本审计；macOS 12 客户现场复测仍待确认。当前为 adhoc 签名预览，尚未进行 Developer ID 签名与 Apple 公证，详见 [Mac 安装与兼容说明](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/macOS12兼容说明.md)。

### 解压运行

- **Windows**：解压 ZIP，运行 `dukto-gui.exe`。保留整个目录，所需 DLL、插件和资源均随包附带。
- **Linux**：解压归档，在包目录运行 `./dukto-gui`；命令行使用 `./dukto-cli`。使用包顶层启动脚本，以便加载随包依赖。
- **macOS**：按芯片选择对应包，解压后打开 `Dukto Next.app`。命令行使用包内提供的 `./dukto-cli` 入口，首次打开流程见安装说明。

升级时先退出旧版，再将新包解压到新目录，避免混用旧 DLL 或插件。现有配对资料可继续使用。[SHA256SUMS](https://github.com/29583855/dukto-next/releases/download/preview-gui-memory-20261111/SHA256SUMS) 用于核对下载文件；其中子目录表示本地分类目录，GitHub 附件使用对应文件名。

## 快速上手

### 方式一：两台电脑临时互传

1. 两台电脑运行 Dukto Next，确认处于可互通的局域网，并允许应用联网。
2. 在“设备”页等待对端出现；需要时点击“刷新设备”。
3. 选择目标设备，发送文字、剪贴板文本、文件或文件夹。
4. 在接收端查看接收结果，也可在设置中修改接收目录。

对端未出现在列表中时，可以使用“IP 连接”填写实际 IP 或主机名。直接连接仍要求目标接收端口可达。

**同机使用前先退出原版 Dukto或其他占用端口的实例。**默认沿用原版端口，不会自动切换备用端口；同一 TCP 接收端口无法被两个实例独占监听。

### 方式二：访问服务器共享

**服务端准备：**

1. 打开“服务器·上传/下载” → “本机共享”。
2. 使用客户端将要连接的实际 IP 或主机名建立服务器身份，保存界面显示的 SHA-256 指纹。
3. 设置共享名称，例如 `docs`，选择本地共享文件夹，勾选所需权限并保存共享。
4. 启动本机 TLS 服务，默认端口 `4646`。
5. 点击“颁发本共享的配对文件”，通过可信方式将 `pairing-export-` 开头的 JSON 配对文件交给客户端使用者，并让其核对服务器指纹。

**客户端连接：**

1. 在“连接与文件”页填写本地资料别名，例如 `office-server`。
2. 展开首次配对设置，填写服务器实际 `IP:端口`、完整指纹和配对文件路径。
3. 点击“配对并保存资料”。以后使用相同别名，点击“连接”即可。
4. 共享名称填写服务端配置的名称，例如 `docs`。

资料别名由客户端自行命名，方便区分连接；共享名称由服务端配置。`127.0.0.1` 表示本机，另一台电脑应使用服务器的实际地址。

**上传与下载：**

- **浏览**：相对路径留空表示共享根，点击“浏览”。点击列表条目会更新路径，再次点击“浏览”查看目录内容。
- **上传**：相对路径指向共享内已有的目标目录，或留空上传到根目录，再点击“上传文件”或“上传目录”。
- **下载**：选择远程文件或目录，指定一个已存在的本地保存目录，再点击“下载”。
- **任务**：在“任务”页查看状态；恢复任务时，按界面提示提供原文件或本地路径。

完整配置、权限与错误处理见 [服务器上传下载使用说明](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/服务器上传下载使用说明.md)。

## 命令行示例

Windows 使用 `dukto-cli.exe`；macOS / Linux 在运行包目录使用 `./dukto-cli`。以下示例中的地址、路径和资料名需替换为实际值。

```text
# 查看帮助与本地运行环境
dukto-cli --help
dukto-cli doctor --json

# 局域网接收与发送
dukto-cli receive --output <已有接收目录> --port 4644 --json
dukto-cli send --to 192.168.1.20:4644 --path <本地文件或目录> --json
dukto-cli send-text --to 192.168.1.20 --file <UTF-8文本文件> --json

# 使用已经完成配对的客户端资料
dukto-cli list --state-directory <客户端状态目录> --profile office --share docs --all --json
dukto-cli upload --state-directory <客户端状态目录> --profile office --share docs --path <本地文件或目录> --json
dukto-cli download --state-directory <客户端状态目录> --profile office --share docs --remote-path reports/example.pdf --output <已有保存目录> --json
```

上传示例省略 `--remote-path`，目标为共享根目录。GUI 与 CLI 应使用各自明确的状态目录和资料；同机并行接收时需要避免端口冲突。

脚本应检查整个任务的最终状态；单个文件完成事件不能代表整个批次完成。R6 协议不提供远端校验完成确认，不能把其发送结束等同于接收端已完成内容校验。

## 网络与常见问题

| 现象 | 处理方法 |
| --- | --- |
| 自动发现不到设备 | 确认处于同一可达 IPv4 广播网络，允许 UDP 4644；检查防火墙、访客 Wi-Fi、AP 隔离和跨网段限制。 |
| 提示端口占用、Windows 10048 或 Mac 48 | 退出同机原版 Dukto 或其他占用程序，再启动 Next。 |
| 服务器连接失败 | 确认服务已启动，客户端使用实际地址和 TCP 4646，网络与防火墙允许访问。 |
| 能连接但不能上传或下载 | 共享本身和客户端授权均需具备对应权限，并核对共享名称。 |
| 上传目标路径错误 | 上传目标应为共享内已有目录；上传到根目录时清空相对路径，避免保留刚选中的文件路径。 |
| 下载按钮不可用 | 先填写或选择一个已存在的本地保存目录。 |
| “现有资料目标或指纹不同，拒绝覆盖信任” | 核对原资料绑定的地址与指纹；连接另一台服务器时使用新别名，正常证书变更按指纹迁移流程处理。 |
| “私有状态所有者或继承策略不安全” | 按 Windows 配对导入说明，将配对文件放入当前账户的专用私有目录。 |
| 配对文件过期 | 在服务端重新颁发配对文件，核对指纹后再次操作。 |

[端口与发现说明](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/局域网发现与原版共存.md) · [Windows 配对权限处理](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/Windows配对权限错误处理.md) · [本地诊断](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/本地诊断.md)

## 当前版本与验证范围

当前推荐的内存修复预览版包含：

- 局域网直连发送受到代理设置影响的问题修复。
- 上传文件选择器关闭时的释放后访问修复。
- Qt5 滚动条辅助功能重复连接导致内存持续增长的问题修复。

**已完成验证：**

- Windows x64、Linux x64、Mac Intel / Apple Silicon 原生构建，各 36 项完整 CTest 通过；每平台 35 份 Qt 报告核对通过，零失败、零跳过。
- 最终包迁移运行与传输检查通过，Linux 同时覆盖 X11 和 Wayland。
- Windows 11 实际 GUI 连接用户的 Windows Server 2012 服务端，完成 1 MiB 文件上传、目录确认和下载，逐字节比较一致。
- Windows 最终程序持续观测 900.6 秒，私有提交内存为 67.65–96.32 MiB，传输与界面操作完成后的稳定区间为 95.98–96.19 MiB。

**仍待扩大验证：**24 小时长测、客户物理 Windows → Mac 现场复测、实际 macOS 12 客户环境，以及更完整的网络、规模和故障组合。已有短时与原生构建结果分别记录，当前仍为开发预览版。

[修复说明](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/界面内存增长修复-20261111.md) · [机器可读验收报告](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/gui-memory-fix-verification-20261111.json)

## 源码与构建

主要技术栈：**C++14、Qt 5.15、QML、CMake、OpenSSL、SQLite**。

| 目录 | 内容 |
| --- | --- |
| `src/core/` | 共用传输、服务、权限与持久状态核心 |
| `src/app/` | 桌面应用控制与平台界面接入 |
| `src/cli/` | 独立命令行入口 |
| `ui/`、`resources/` | QML 页面、局部样式与应用资源 |
| `tests/` | 核心、界面、协议、故障与运行包测试 |
| `scripts/` | 构建、打包、依赖与审计脚本 |
| `.github/workflows/` | 原生多平台构建与验证工作流 |
| `docs/` | 使用说明、设计、修复与验证文档 |

从 [源码分支](https://github.com/29583855/dukto-next/tree/codex/macos12-compatibility) 或 Release 对应源码包获取代码。源码构建需要匹配的 Qt 5.15 开发环境、私有开发头、QML 模块、OpenSSL 开发库和 C++14 编译器；私有头须与实际使用的 Qt 版本匹配。

依赖环境准备完成后，通用构建入口为：

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel 4
ctest --test-dir build -C Release --output-on-failure
```

图形测试需要桌面显示环境，Linux CI 使用 Xvfb；构建目录中的程序与含依赖运行包分别验收。直接运行推荐使用 Release 运行包。

平台配置和打包流程见 [Windows UCRT 工具链](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/Windows-UCRT工具链.md)、[Linux 预览包说明](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/Linux独立预览包.md)、[macOS 构建与验收](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/docs/macOS构建与验收.md)。

## 反馈与许可证

通过 [GitHub Issues](https://github.com/29583855/dukto-next/issues) 提交问题，建议附上系统与架构、Release 标签、操作步骤和错误信息。截图或日志请隐去配对凭据、私钥、访问令牌及个人资料。

项目许可见 [GPLv3 LICENSE](https://github.com/29583855/dukto-next/blob/codex/macos12-compatibility/LICENSE)。第三方依赖保留各自许可证，运行包包含相应许可文件。

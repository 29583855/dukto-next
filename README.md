# Dukto 功能复现与跨平台传输项目

更新日期：2026-11-07

项目以 `Dukto/` 内的 Dukto R6 为功能参考，开发 Windows、macOS、Linux 共用内核的桌面应用和独立命令行程序，增加服务器上传/下载、多线程提速及可靠恢复能力。

当前已建立 C++14 共用核心、Qt Quick 2 桌面端和独立 CLI。Windows 已验证与原版文件/目录/文本双向互传、超过 4 GiB、10 万文件、100 轮接收，以及首次说明/设置/截图/单实例和有界头像模块。完整原版交互、服务器、多线程、恢复和跨平台验收继续按计划推进。原版目录保留用于对照。

公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R108[过期上传临时文件维护CLI](docs/过期任务临时文件清理.md)通过双Windows和独立Ubuntu专项；新四平台CI继续。R107 ARM完整故障测试有精确断言失败并保留，GUI/CLI编译结果不变；[含依赖双Mac预览](docs/macOS独立预览包.md)仍为R105。完整状态见[计划](开发计划与进度.md)和[本轮证据](docs/ci-verification-20261107-r108.json)。

新增[b9d9b78上传发送端确认](docs/decisions/0022-上传发送端持久处置与证据恢复.md)已通过本机专项；原CI终态failure保留：四平台临时库glob误判，另Windows并发隔离空闲线程5/基线3的原因未确认。旧运行不再视为进行中，完整历史见主计划v0.64。

新增[3fbec42覆盖占用修正](docs/decisions/0023-Windows覆盖共享占用与同任务恢复.md)已包含于当前Mac包。其完整四runner终态failure：各21核心通过，协议154/155，Windows改共享根时私有配置替换失败；Ubuntu/双Mac各38、Alpine另38协议通过。新[私有状态修复](docs/decisions/0024-私有状态原子替换与读者竞争.md)按7772151单独复验。

R104已增加状态目录共享使用/独占维护保护，四原生核心与双Windows多进程子项已验，完整协议继续；过期回收及全局配额仍待实现。R102的188协议及R103的192协议四平台完整终态success均已严格收验。详见[状态维护边界](docs/状态目录维护保护.md)和[本轮回执](docs/validation/2026-11-07/state-use-r104-qualified/receipt.json)。

R105只修正逐项查询测试对永久占用锁的假设，双Windows定向复验通过；R104 Ubuntu完整协议原失败及独立Ubuntu上传超时均保留，新原生验证继续。[修正与证据](docs/ci-verification-20261107-r105.json)。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [实施进度](docs/执行进度.md) | 逐项勾选、验证证据、修复记录与剩余工作 |
| [开发计划与进度](开发计划与进度.md) | 功能范围、阶段、状态、预算和交付验收的总入口 |
| [本地诊断](docs/本地诊断.md) | doctor、GUI本地导出、端口/目录/配置检查及已配对能力检查 |
| [补充需求与关键设计](docs/补充需求与关键设计.md) | 大文件恢复、文件冲突、落盘、配额及协议边界的具体规则，包含 R01–R12 |
| [首轮开发任务清单](docs/首轮开发任务清单.md) | 从当前状态进入 P0/P1 的可执行任务、依赖、交付证据和完成标准 |
| [第三方对应源码进度](docs/第三方对应源码进度.md) | 精确依赖签名、构建配方、上游源码和发布附件的实际完成状态 |
| [逐项失败证据](docs/decisions/0012-逐项接收失败证据.md) | 接收本地错误、恢复解决、GUI/CLI及旧日志边界 |
| [证书续期与指纹迁移](docs/decisions/0015-证书续期与显式信任迁移.md) | 期限查看/预警、保留身份续期、服务重启及客户端明确核对迁移 |
| [网络期限与通道加入](docs/decisions/0011-网络期限与多通道加入确认.md) | R6无进展期限、已到达数据读取及多通道加入顺序 |
| [macOS 构建与验收](docs/macOS构建与验收.md) | Intel/Apple Silicon CI、原生 Cocoa 检查、结果归档与待验收范围 |

## 已确定的范围

- 保留 Dukto 相近排版及原版功能，新增服务器页、任务中心和上传/下载并发设置。
- 支持 Windows x64、macOS arm64/x86_64、Linux x86_64；三系统均交付完整 CLI。
- 客户端输入服务器地址后可上传、浏览授权共享目录及主动下载，服务端支持无桌面运行。
- 可选 1/2/4/8/16 并发档位，多文件并行、大文件分块传输；用双端校验完成的总耗时衡量提速。
- 全局有界缓冲、流式目录、失败隔离、任务排队；新版扩展支持暂停/继续及跨重启断点续传。
- 旧版 R6 按其已验证协议兼容；新增远程浏览、恢复和多通道能力需双方支持相应扩展。

## 开发要求

语言为 C++14，框架方案为 Qt 5.15，使用 CMake；具体工具链与依赖版本需先通过三平台可行性验证。新增或修改函数写中文注释并加日期，统一格式化，修改已有文件时保持编码、BOM 和换行格式。三平台 GUI 与 CLI 共用传输核心，CLI 不依赖 GUI 正在运行。

如开发环境缺少 Qt5 或已有版本不兼容，由开发助手自行下载、安装、配置并完成 C++14 构建验证，同时补齐所需配套工具链，记录来源、版本、校验值和安装路径；不要求用户预先安装 Qt5。该工作纳入 P1 / T03，具体步骤见主计划5.7节；Windows、两种Linux以及macOS两架构已完成实际安装/构建，完整平台验收见当前记录。

实施顺序为原版基线核实与工具链验证 → 全功能复现 → 服务器访问 → 多线程提速 → 持久恢复 → 稳定性和发布。基础资源限制、文件保护和必要测试随各阶段实现，不能全部留到发布前。

按 [首轮开发任务清单](docs/首轮开发任务清单.md) 推进；只有取得实际构建、互传、校验和资源测试证据，才把对应功能标为完成。

## 当前开发构建

Windows 工具已独立安装在被 Git 忽略的 `.tools/`。在本目录执行：

现代 Windows 环境已验证 Qt5.15.19、OpenSSL3.6.4 和 GCC16.2，保持 C++14；使用 `./scripts/build-ucrt.ps1` 和 `./scripts/verify.ps1 -Ucrt`，产物在 `build/windows-ucrt`。版本、来源、签名和完整命令见 [UCRT 工具链](docs/Windows-UCRT工具链.md)。下方早期 MSVC 命令继续用于复现已有结果。

```powershell
./scripts/build.ps1
./scripts/verify.ps1
$env:PATH="$PWD/.tools/Qt/5.15.2/msvc2019_64/bin;$PWD/.tools/openssl/Library/bin;$env:PATH"
./build/windows/Release/dukto-gui.exe
./build/windows/Release/dukto-cli.exe --help
```

GUI 可用 `--data-directory <目录> --port <端口>` 隔离开发配置/历史/接收明细与实例锁；不指定时使用平台默认位置。CLI 用 `--config-file <INI>` 和 `--state-directory <目录>` 隔离配置及明细，适合脚本和测试。

当前可用命令为 `discover`、`send`、`send-text`、`receive`、`receipts show`、`config show/set`、`doctor`、`help`，以及新增的服务身份/共享管理、配对和认证命令（示例见下文）。例如：

```text
dukto-cli receive --output <接收目录> --port 4644 --json
dukto-cli send --to 192.168.1.20:4644 --path <文件或目录> --json
dukto-cli send-text --to 192.168.1.20 --file <UTF-8文本文件> --json
dukto-cli receipts show --task <接收任务ID> --state-directory <明细目录> --json
```

旧版 R6 发送结束不包含远端校验确认，JSON 明确输出 `receiverVerified:false`。Windows/Alpine Linux 公共单通道、任务查询/暂停/取消/继续及 GUI 面板子项已实测；Windows 真实多通道和 GUI 并发设置已接通。完整平台/故障矩阵仍在验收。大文件/海量文件专项脚本见 `tests/large_transfer.py`、`tests/stability_integration.py`，会建立真实测试文件，结果存 `docs/validation/`；源码审计使用 `scripts/audit.py --report <报告路径>`。

崩溃专项 `tests/crash_integration.py` 已接入验证脚本：进程失去所有权后，旧接收记录显示 `interrupted` 和结果未知；查询退出 0 仅表示查询成功，脚本应检查任务 `state`。中断遗留临时文件须核对，当前不自动恢复或删除。

长时基础验证使用 `tests/soak_transfer.py <CLI> --duration 86400 --interval 30 --report <新目录>/summary.json`，依赖 psutil，须配置 Qt 运行库路径。脚本逐轮校验并删除自身副本、保留同名原文件，持续写 CSV；Windows 使用独立 EXE 副本，报告在结束前始终为 running。早期已启动的 Windows/Linux 24 小时 R6 基线测试按原输入保留，详见实施进度；本轮没有查询其运行状态，也不作为当前源码、新版多通道或全阶段通过。

当前 Qt 5.15.2 / OpenSSL 1.1.1w 是本机早期开发组合，发布前仍须替换和验证可维护依赖。Alpine Linux x64 已完成 GUI/CLI 实际构建、12 个 CTest（接收核心快照）、IPv6/CLI/崩溃及 OpenSSL 3.5.9 握手验证。此处12项为早期核心快照；三平台实际构建和开发预览包的最新资格见当前验证索引，完整GUI、干净系统及正式发布验收仍未完成。

2026-11-05 增量：Windows UCRT 已通过 15/15 CTest、TLS/CLI 输入和双主体隔离，Windows↔Alpine 新版公共 TLS 两种客户端/服务器组合、五档共 20 次上传下载及摘要/重试/同名保护通过，见 [矩阵](docs/validation/2026-11-04/windows-linux-tls-matrix-ucrt.json)。Alpine 多通道前一快照 15/15 CTest 通过；最新授信/GUI 快照继续验证。上述互通使用 QEMU NAT，不能据此判断物理 LAN 提速。

服务管理、配对和分页浏览已在Windows/Linux及macOS两架构真实验证；完整业务与发布验收仍在继续。新版服务独立使用 TLS 4646，不会同时开启 R6 无认证接收。构建现在需要与运行库匹配的 OpenSSL Crypto 开发包（Windows 独立目录、Linux openssl-dev/libssl-dev、macOS openssl@3）。例如：

```text
dukto-cli serve init --state-directory <服务状态目录> --server-name <服务器IP> --server-name <主机名> --json
dukto-cli serve share add --state-directory <服务状态目录> --share docs --path <共享目录> --allow-browse --allow-download --json
dukto-cli serve pairing --state-directory <服务状态目录> --share docs --allow-browse --allow-download --json
dukto-cli serve start --state-directory <服务状态目录> --port 4646 --json
dukto-cli pair --state-directory <客户状态目录> --to <服务器IP>:4646 --fingerprint <人工核对的64位公开指纹> --credential-file <受保护的一次性配对文件> --profile office --json
dukto-cli auth --state-directory <客户状态目录> --profile office --json
dukto-cli list --state-directory <客户状态目录> --profile office --share docs --all --json
dukto-cli serve revoke --state-directory <服务状态目录> --client <客户端UUID> --json
```

`serve pairing` 只输出凭据文件位置和期限，原始配对秘密不出现在参数或 JSON 事件中。文件须经安全方式交付，并保存在只有当前账户能访问的目录/文件中；三平台均检查原生权限。客户端先保存待配对身份，确认丢失可用同一资料重试，一次性票据不能改绑其他身份。撤销后旧访问令牌与旧票据均拒绝。`serve share add` 与 `serve grant` 的 `--allow-browse/--allow-download/--allow-upload` 均须显式指定；浏览在扫描期间及回包前重新检查授权、共享根和连接状态。实际单通道数据命令也持续执行权限检查。上传需在共享及客户端授权两处显式添加 --allow-upload。

Windows 与 Alpine Linux 单通道目录/文件上传下载已通过实际独立进程验证。客户端均主动连接服务器，示例：

```text
dukto-cli upload --state-directory <客户状态目录> --profile office --share docs --path <本地文件或目录> --remote-path <服务器内已有相对目录> --json
dukto-cli download --state-directory <客户状态目录> --profile office --share docs --remote-path <服务器文件或目录> --output <本地已有目录> --json
```

`--remote-path` 省略表示共享根；上传的 `--path` 可重复。传输开始事件输出 requestId，中断后以同一 `--request-id <UUID>`、同一资料/共享/路径重试；下载还绑定同一保存目录。传输成功必须检查最后 `transfer-completed` 和 `state=completed`，单个 `file-completed` 不表示整个批次成功。连续块恢复已在核心通过进程退出测试，公共服务首个 4 MiB 块后的暂停/客户进程退出/服务重启/取消已在 Windows 与 Alpine Linux 通过，其他故障偏移和确认丢失仍继续验收。GUI 服务器面板已接共用核心并完成真实文件上传/下载专项，多通道和三平台版本尚未全部交付。

新版 upload/download/resume 支持 `--retries 0..3`（默认 0，手动恢复）及 `--deadline-seconds 1..604800`（默认 86400 秒）。总时限覆盖扫描、恢复查询、排队、传输、校验及退避；只有网络错误有限重试，依次等待 250/500/1000ms，证书/权限、磁盘、路径、源变化、校验失败和取消均直接结束。所有尝试沿用同一请求与检查点，重连不重新扫描上传清单。到期为退出码 3、阶段 deadline，用户取消为 7。GUI 在连接与文件页展开“传输重试和总时限”设置，三平台共用核心，实际平台结果分别登记。详见[重试与时限契约](docs/decisions/0008-有限重试与任务总时限.md)。

```text
dukto-cli download --profile office --share docs --remote-path backup.bin --output <本地已有目录> --threads 8 --retries 3 --deadline-seconds 7200 --json
```

公共任务控制（各平台验收范围见实施进度）：

```text
dukto-cli tasks --state-directory <客户状态目录> --profile office --all --json

dukto-cli task --state-directory <客户状态目录> --profile office --task <任务UUID> --json
dukto-cli pause --state-directory <客户状态目录> --profile office --task <任务UUID> --json
dukto-cli cancel --state-directory <客户状态目录> --profile office --task <任务UUID> --json
dukto-cli resume --state-directory <客户状态目录> --profile office --task <上传任务UUID> --path <原本地文件或目录> --json
dukto-cli resume --state-directory <客户状态目录> --profile office --task <下载任务UUID> --output <原本地保存目录> --json
```

暂停/取消响应区分 state、desired 和 executionActive；收到停止请求不等于已经停止，脚本应继续查询到 paused/cancelled 且 executionActive=false。resume 读取原任务固定参数，上传仍须提供原内容（--path 可重复），下载必须提供原保存目录。取消是终态，目前保留未完成临时数据与检查点，不自动删除；已完成文件保留。独立进程八组故障测试见 transfer-recovery.json。

GUI 设备页的“服务器 · 上传 / 下载”打开服务器面板。连接与文件页可选择已保存资料、浏览、上传和下载；首次配对设置默认折叠。本机共享页管理独立服务身份、显式共享权限和监听；任务页可分页找回所属任务、选择任务后查询/暂停/取消/继续。后台进度使用单个最新快照，任务和目录只保存当前页，避免大量文件持续增加界面事件和内存。Windows 生产 QML 的暂停、面板重建后找回/继续及取消实际点击已通过；原生对话框、进程级 GUI 重启与其他平台桌面另验。

任务分页每页最多 100 项且不超过 64 KiB，已撤权或共享根改配的记录不展示；`--all` 为逐页输出。上传源扫描库在正常结束或异常退栈后关闭并回收；进程强退遗留项的安全管理尚在实施。

Windows 新版上传、下载和恢复可附加 `--threads 1/2/4/8/16`；默认 1，返回 `channels` 是实际授予通道数。大文件分块并行，多文件在至多 16 项窗口内轮转分配块；接收逐片写盘和校验，不缓存整个文件。恢复时允许调整通道数，内容身份和请求不变。GUI 连接与文件页提供相同档位，恢复继续使用所选值。R6 `send` 不支持扩展并发，显式设置非 1 档会拒绝，避免静默忽略。

首版五档提速、4→8 通道公共恢复已在 Windows 验证；多文件新版已通过接收/交换/GUI 专项及三窗口逐文件 SHA，完整性能和故障复验持续记录在[执行进度](docs/执行进度.md)。本机限速代理的提速不能代替物理网络结论；公平调度、完整全局资源预算、保留清理及三平台交付仍未完成。
2026-11-05 字节进度增量：双方协商 `byte-progress-v1` 后，上传、下载和恢复的 GUI/CLI 实时展示实际接收量、已校验落盘量及本轮重验恢复量；JSON 事件为 `byte-progress`，bytes 为已同步确认量，receivedBytes 为实际接收/重验量，restoredBytes 单列，bytesPerSecond 排除恢复量，etaSeconds 可为 null。最多每 250ms 一次；进度到达总量后仍等待最终校验和提交确认。Windows 1/4/16 双向、4→8 恢复与最新 MSVC/UCRT 15/15 CTest 已通过，完整平台范围继续。Ubuntu glibc 依赖已安装并进入独立构建，不作为已通过的 Linux 桌面验收。

Windows 独立开发预览包已加入生成及迁移运行验证，参见 [生成与使用](docs/Windows独立预览包.md)。GUI、独立 CLI、SQLite/TLS 和 16 通道双向传输已在移除开发路径后通过；完整发布、干净系统和第三方对应源码分发验收继续。

2026-11-05 后续验证：Windows UCRT/MSVC 均通过 16/16 CTest，完成确认在三个阶段绑定冻结清单总量及摘要，1/4/16 通道最终确认丢失重试通过。生产服务器面板在两个独立进程中通过真实按钮完成 4→8 通道断点恢复，Windows 原生窗口双工具链均通过；该测试不覆盖完整主窗口或原生文件选择器。Ubuntu glibc 已通过真实中途磁盘满双向与释放空间恢复、较早固定快照 X11/Wayland；最新零字节/SQLite/完成确认源码固定快照在两 Linux 重建中。三平台完整交付继续按[计划](开发计划与进度.md)逐项验收，尚未宣告完成。

Linux x86_64 glibc 独立包的构建、运行基线及迁移验收流程见 [Linux 预览包说明](docs/Linux独立预览包.md)，最新包验证尚在执行。

2026-11-05 凭据轮换：`dukto-cli rotate --state-directory <客户状态目录> --profile office --json`，GUI 在服务器“连接与文件”页点击“轮换凭据”。本机先持久保存待确认秘密，网络失败或进程中断后使用同一命令/按钮继续核对；旧凭据不能访问，原任务可用新凭据恢复。Windows 双工具链实际故障与 QML 点击通过，见[使用和协议规则](docs/decisions/0004-访问凭据轮换.md)。十万文件新版 16 通道双向及重试已结束并通过，较早快照和最新源码的范围在[计划](开发计划与进度.md)中分列。


2026-11-05 客户端管理：在服务器本机运行 `dukto-cli serve clients --state-directory <服务状态目录> --all --json`，可逐页查看有效及已撤销客户端、修订与共享权限；单页查询可用 `--cursor <上一页after>`。GUI“本机共享”点击“刷新客户端”，选择条目填入授权/撤销用 UUID。每页最多 100 项并受 64 KiB 限制，分页期间可变化，新增身份请刷新第一页。详情见[本机客户端管理](docs/decisions/0005-本机客户端管理.md)。Windows 双工具链验证通过，完整三平台验收继续；包 r7 早于此项。


上一版 Windows 开发预览 r8，包含本机客户端管理；ZIP 的 SHA-256 为 `d3c952382a54c54acb5ad9092055e043796fccfbd6e04d160f6da53c7710c3ed`。仅系统 PATH 迁移测试已通过，仍不具备正式发布资格，使用方式见[Windows 独立预览包](docs/Windows独立预览包.md)。两 Linux 固定完成确认快照均通过 16/16 CTest 和直接 16 通道双向；不透明代理五档测试的 16 档超过 120 秒，单列诊断与原失败，详情见计划 v0.21。


2026-11-05 定向通知增量：多通道普通队列只唤醒对应数据线程或控制线程，停止/失败仍广播。Windows UCRT/MSVC 均通过 16/16 CTest 和五档双向；256 MiB 四文件在实际约 68–72 MiB 同步后进行 16→8 暂停/进程退出/服务重启/取消及恢复，逐文件摘要和任务保持通过。两 Linux 已安装相同 151 文件固定快照开始重建，低核环境是否改善须等实测，不能把局部通知优化算作全局公平调度完成。计划当前为 v0.22。


当前 Windows 开发预览为 r9，包含本机客户端管理和多通道定向唤醒，位置 `dist/windows-preview-20261105-r9/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `3862cebe918fcfca6f992e3bb2ba785a49db1cadb9149841e79feac2cdef4376`。[仅系统 PATH 迁移测试](docs/validation/2026-11-05/package-windows-runtime-r9.json)已通过 GUI、独立 CLI、16 通道双向与客户端管理专项，仍是开发预览，完整三平台、干净系统和正式发布要求继续。


2026-11-05 v0.23：认证会话默认 24 小时，本机用 serve session show / serve session set --session-seconds N 或“本机共享”折叠设置管理。更改对新连接生效；到期保留检查点，使用相同资料重新连接并继续原任务，心跳/轮换不续期。Windows 双工具链 16/16 CTest、各六组到期恢复和独立原生面板通过，见[期限规则](docs/decisions/0006-认证会话期限.md)及[进度](docs/执行进度.md)。包 r9 早于此项，Linux/macOS 按新快照验收。


Windows 最新预览包为 r10，含会话期限设置，[迁移验证](docs/validation/2026-11-05/package-windows-runtime-r10-recheck.json)通过，包含同包 CLI 的四通道到期后原任务恢复。SHA-256：6319b7170d61b0846f8d967e3aa4d2316d93f966214836e58af5aa9bcd52789b。仍属开发预览，完整交付要求继续按计划执行。

2026-11-05 v0.24：Windows 同进程新版服务增加有限公平等待（2 活动任务、100 等待结构项、16 数据通道），同主体 FIFO、不同主体轮转启动，活动任务不抢占。自动协商等待，CLI 输出实际授信档位，生产服务器任务页中文显示排队并可查询/暂停/继续/取消。双工具链各 17/17 CTest、双向及混合真实 TLS 六组与原生独立面板控制通过，关键恢复回归通过；[契约与边界](docs/decisions/0007-有限任务排队与公平授信.md)。当前预览包 r11 已包含本次排队，迁移及包内混合等待/恢复验证通过。较早固定轮换版本十万文件双向/重试已完成，不冒充当前版本规模验收；全部预算/回收、物理 LAN、macOS、原版完整基线和正式发布继续。


## v0.26 当前迁移与失败状态（2026-11-05）

Windows r12 预览包已包含有限重试、总时限及远程暂停保护，并通过仅系统 PATH 的 GUI/CLI/16 通道、混合排队、十四组重试及六组自动最终确认恢复。见[包说明](docs/Windows独立预览包.md)与[实际迁移报告](docs/validation/2026-11-05/package-windows-runtime-r12-recheck.json)。仍为开发预览，尚未通过干净系统或完整发布验收。

Linux 160 文件固定业务驱动均已结束并保留失败；会话 90 秒超时有持续正文进度证据，正在独立诊断。glibc 包的 OpenSSL 无版本库名导致系统依赖混入，部署修复另行验证。新重试版本不能借用旧快照的通过项。四冲突策略按[逐项完成契约](docs/decisions/0009-文件冲突与逐项完成契约.md)继续实现，完整进度以主计划 v0.26 为准。

2026-11-05 v0.27 状态：Windows r12 已通过实际迁移及重试；两 Linux 最新 166 源码验证运行中。旧 160 二进制隔离已通过，较长会话诊断仍与默认门槛区分。Linux r6 X11 包通过、Wayland 部署探针通过，r7 实际包待验；宿主图形驱动为运行前提。第三方来源见上述进度入口。旧 Alpine R6 长测已因权限错误结束，Windows 三项长测继续；完整交付尚未完成。

Windows r12现另有[对应源码输入预览附件](docs/产物存放与可用性.md)，23份精确配方覆盖24部署包，621个条目流式重读通过；[源码进度](docs/第三方对应源码进度.md)区分输入验证与尚未完成的独立重建/最终发布。Alpine最新166源码18/18 CTest、16通道、最终确认及四文件恢复通过，重试120秒/会话90秒仍失败。Linux r7实际界面与装饰检查通过后正文超时，整包尚未通过，原失败保留。

## v0.28 当前状态（2026-11-05）

当前源码的新版上传和下载支持 `--on-conflict rename|fail|overwrite`，默认 rename。overwrite 在完整校验/同步后原子替换同名普通文件，安全合并目录并保留无关项；fail 返回 4/conflict 并保留原目标。GUI 在“传输选项”选择，恢复沿用原任务策略。Windows 两套工具链各19/19 CTest、双向1/4/16覆盖及八组4→8恢复通过；新实现的Linux/macOS和实际包资格待验。Windows r23实际包已含overwrite并通过迁移/覆盖/恢复；Mac/Linux当前下载仍为f230f3d，不含overwrite，新包资格继续CI。skip及完整处置确认继续实施，见[覆盖说明](docs/decisions/0016-显式覆盖与目标预约.md)和[冲突契约](docs/decisions/0009-文件冲突与逐项完成契约.md)。

公开仓库已使用29583855账号创建并上传，macOS Intel/Apple Silicon原生编译、完整CI及独立预览包迁移已完成。当前下载、SHA与范围见[构建验证摘要](docs/构建验证摘要.md)，完整交付仍按[计划v0.51](开发计划与进度.md)推进；历史包和失败证据保留。

## 公开源码与原生 CI

用户授权的新公开仓库为 [29583855/dukto-next](https://github.com/29583855/dukto-next)，共用源码保持 C++14/Qt5。macOS Intel/Apple Silicon 原生编译、Cocoa 主窗口渲染与进程恢复见[构建与验收](docs/macOS构建与验收.md)，实际状态以对应提交的 GitHub Actions 为准。

文档中的 docs/validation 链接为本机累积的验收记录，未随公开源码上传；原版参考二进制、大型依赖附件、凭据和工具缓存也不进入源码仓库。远端产生的新日志/截图/编译输出由 Actions artifacts 保存。现有本机预览包与全部历史记录保持原件，完整功能与正式发布仍按计划验收。

## 当前 macOS 编译结果（2026-11-05，源码 9198cb5）

已使用用户授权的 [29583855/dukto-next](https://github.com/29583855/dukto-next) 上传源码，并在 [GitHub Actions](https://github.com/29583855/dukto-next/actions/runs/41954110035) 完成原生 Apple Silicon 与 Intel 编译。Qt5/OpenSSL 由工作流自动安装，保持 C++14；两架构均生成实际 GUI .app 和独立 CLI。

| 架构 | 编译产物 | 已通过的原生子项 |
| --- | --- | --- |
| Apple Silicon / arm64 | [macos-compiled-ARM64](https://github.com/29583855/dukto-next/actions/runs/41954110035/artifacts/13381379149) | 18/18 CTest、20项TLS、Cocoa主入口及面板进程恢复 |
| Intel / x86_64 | [macos-compiled-X64](https://github.com/29583855/dukto-next/actions/runs/41954110035/artifacts/13381359525) | 18/18 CTest、20项TLS、Cocoa主入口及面板进程恢复 |

完整业务仍失败：两Mac短会话到期未取得已持久检查点，Ubuntu16通道fail冲突错误传播不符；保留原时限及失败日志。上述附件是依赖匹配Qt5/OpenSSL的开发编译输出，自包含部署、签名公证、干净系统和完整产品验收仍开放。源码提交、SHA、已通过项及剩余工作见[macOS构建与验收](docs/macOS构建与验收.md)和[计划](开发计划与进度.md)。

当前附件可用性补充（2026-11-05）：历史Windows/Linux预览包及源码输入ZIP目前缺失，旧验证记录继续保留；本轮Mac输出已校验并保存到持久目录。详见[产物存放与可用性](docs/产物存放与可用性.md)，历史SHA不代表当前还能取得文件；重新建立其他平台候选包仍未完成。

2026-11-05 v0.30：并行控制线程先保留原始错误，持久暂停/取消返回7；Windows UCRT真实TLS四组根因专项与十四组重试通过。Mac短会话测试增加有界时序和失败JSON，原时限保持；跨平台结果及完整范围见计划。

2026-11-05 Mac独立开发预览：Intel与Apple Silicon的GUI/CLI已在原生CI编译并通过包内依赖迁移、16通道双向及4→8恢复；两架构另通过56组会话/故障/字节进度专项。[下载、校验和运行](docs/macOS独立预览包.md)。Windows新r17包含初始化轮询修复并通过实际ZIP迁移；完整项目仍按计划逐项验收。

## 新版任务逐项查询

新版构建提供 `dukto-cli task-items --profile office --task <UUID> --state-directory <原客户状态目录> --all --json`。每页最多100项，`--after`可单独继续；普通终端也逐项显示。GUI的服务器“任务”页可查看逐项明细。上传读取服务器的接收证据，下载须在原下载机器保留本机记录；缺失记录会明确显示不可用。查询不重新校验或重写当前文件。详细语义及实际支持边界见[接收证据分页](docs/decisions/0010-任务逐项接收证据分页.md)。

当前Mac/Windows覆盖预览包已按精确c3fc781源码核验，支持GUI和CLI选择同名普通文件覆盖、目录合并。Mac ARM/Intel原生核心各19/19，实际包迁移、双向1/4/16覆盖和已有文件恢复通过；Linux新覆盖包仍在CI。最新下载与SHA见[构建验证摘要](docs/构建验证摘要.md)，新增故障/盘满资格继续记录，完整交付尚未结束。

Linux覆盖实际包已验证并更新；当前三平台c3fc781预览包早于发送期错误修复0017。新增原生盘满单通道发现错误分类缺陷，修复已通过Windows两套26TLS/19核心及业务回归，原生真实盘满和新部署包继续验收。

R86 macOS下载已更新至06089a5：双架构GUI/CLI、各290源码、五业务原报告及截图已验，详见[下载说明](docs/macOS独立预览包.md)。完整原生协议与正式交付继续。

R87 macOS下载已更新到409a73b：Intel/Apple Silicon的GUI和独立CLI、各293源码、五业务原报告及四截图通过；包含公开skip，完整新原生协议独立验收。见[下载说明](docs/macOS独立预览包.md)。


2026-11-06 R92：发现UDP空通知后的接收恢复已通过双Windows核心/R6/CLI及Alpine原用例对照，完整原生验收继续。当前Mac下载保持已验R90；见[计划](开发计划与进度.md)和[R92回执](docs/ci-verification-20261106-r92.json)。


2026-11-07 R98：双Mac原生运行42264789875已收验，各23核心及四种退出状态/原16组通过，明确保留Darwin平台预期失败。可下载双Mac包保持已验R96；当前Windows完整核心及Linux新部署包继续，完整项目未完成。


2026-11-07：Linux独立预览包已更新为R98（b2e4659），23核心及X11/Wayland迁移和传输原件已验；下载与精确范围见[Linux预览包](docs/Linux独立预览包.md)。R99 GUI修复及完整项目继续验收。


2026-11-07 R99：最新a316e4a的Apple Silicon/Intel GUI及独立CLI编译产物均已核验，附件见[macOS构建与下载](docs/macOS独立预览包.md)。完整原生测试及长期验证继续，整体未完成。


2026-11-07 R100：传输进度刷新不再反复读取剪贴板正文，双Windows实际QML及相关GUI回归通过；R98独立Ubuntu干净编译与23核心/退出专项通过。新GUI原生回归及整体交付继续，当前下载包身份不变。

2026-11-07 R108：过期服务器上传临时正文清理预览/执行CLI已通过双Windows与独立Ubuntu专项。源码已上传[公开仓库](https://github.com/29583855/dukto-next)，Apple Silicon和Intel的GUI/独立CLI原生编译归档已核验；R108含依赖预览部署与完整四平台回归继续运行。编译归档不等于可运行安装包，当前可运行macOS预览仍为R105。完整进度和范围见[计划](开发计划与进度.md)及[macOS下载说明](docs/macOS独立预览包.md)。

## R100公开上传、双Mac编译与Linux长测启动（2026-11-07）

- [x] 138份显式文件严格暂存/编码/换行核验后提交，`ed4f5cf08c96f04671e49e5138eda8ce1790ead3`整树及远端main逐SHA确认。复用自动触发的四平台运行42282812778，210构建输入与Git对象逐件一致，没有重复派发。
- [x] Apple Silicon和Intel实际GUI/独立CLI均编译成功；附件13535778206/13535669142下载后按ZIP摘要、内部tar摘要、源码提交、Mach-O架构和执行权限核验。最新下载见macOS文档；编译输出要求匹配Qt5/OpenSSL，含依赖部署包仍为R96。
- [x] 独立Ubuntu的冻结R98 CLI完成资源采样自检和20轮16通道双向原长测短验；71份冻结文件与25份实际系统动态依赖前后启动核验一致。已实际进入86400秒阶段，只公开不可变启动快照。
- [ ] R100完整四平台回归和新部署包、R99原完整运行终态、Windows/Linux真实24小时终态及资源趋势仍待收验。Linux本轮只绑定R98 CLI，不授予R100 GUI、任意增长或磁盘GC资格；完整R6/编辑器及系统剪贴板预算/物理LAN与3×3/各平台长期/第三方源码重建/正式发布继续。

## R100四平台完整核心与Windows当前部署包（2026-11-07）

- [x] 精确ed4f5cf的Windows、Ubuntu、macOS Apple Silicon/Intel各23核心通过；四份原CTest、88份Qt XML逐件收验，剪贴板进度不重读、草稿拒绝恢复及拖放/复制生产QML方法均实际PASS，发送8组编码边界均通过。双Mac各一条精确已知Darwin端口共享XFAIL明确保留，其余失败/跳过一律拒绝。
- [x] 新Windows实际ZIP含338份精确Git源码和GUI/独立CLI，构建绑定无工作重编译且程序字节未变；本机此前4个相关GUI回归/19个既有相同核心二进制范围保持，另有四平台CI各23核心原件。系统PATH/中文空格路径迁移、16通道双向、会话/排队/重试/最终确认/fail/overwrite及4→8恢复均通过，实际首次说明截图已查看。
- [x] 新包24个未变依赖的364部署文件和53许可逐件匹配公开摘要固定的验签原件；缓存归档/配方摘要重新核对，本次没有重新验签。当前Windows包和源码身份已更新，R98旧包及运行中的冻结24h输入保持原件。
- [x] 四平台核心通过后按精确ed4f5cf分别单次派发Mac/Linux部署流程；固定package-r100-20261107标签、210构建输入与真实运行身份已记录。采用已验核心作为并行构建门槛，部署迁移和完整协议结论分别保留，当前包下载不提前替换。
- [ ] 完整R99/R100协议终态仍按各自精确提交收验；Mac/Linux新部署包、Windows/Linux真实86400秒终态及完整资源趋势、完整编辑器/OS剪贴板预算、全部R6/原生交互、物理LAN/3×3、各平台长期、第三方对应源码独立重建和正式发布仍未完成。

## R100三平台当前部署包收验（2026-11-07）

- [x] 双Mac含依赖部署包更新至精确ed4f5cf：每包338份应用源码全集逐Git blob一致；全部载荷、各71框架链接、Mach-O架构和执行权限逐件核验。系统PATH/中文空格目录迁移、独立CLI、16通道双向、1/4/16覆盖和两组4→8恢复均通过，每包5份原业务报告与父摘要一致。
- [x] Cocoa原生及150%/200%导航逐帧摘要/中文覆盖通过；双架构首次启动和服务器导航4张原生截图已查看，中文和主要控件正常。当前仍为adhoc开发预览。
- [x] Linux含依赖包更新至同一ed4f5cf：338源码、708部署文件、2链接和132 ELF核验；23核心、剪贴板/草稿实际QML、四种退出状态及原16组通过。X11/Wayland各3业务通过，两张实际启动截图已查看。
- [x] 本轮204份维护源码审计零TODO/FIXME/未实现或简化标记，C++14配置和clang-format检查通过；审计零标记不代替完整功能验收。审计脚本内历史缺项文本按原件保留，当前状态以主计划快照为准。
- [x] R99精确a316e4a四平台完整原运行终态success，各23核心、合计188协议及发送8组/草稿恢复原件逐件通过；双Mac共2条精确Darwin XFAIL继续保留，不授予内核端口独占资格。
- [ ] R100完整协议仍单独按真实终态收验；Windows/Linux真实86400秒、完整编辑器/系统剪贴板预算、全部R6/原生交互和选择器、全部资源预算/公平性/安全GC、物理LAN/3×3、各平台长期、依赖源码独立重建及正式签名发布继续未完成。

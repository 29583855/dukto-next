# Linux 独立预览包

更新日期：2026-11-07。当前包源码为`b2e4659b347c65eef24c8e568e07e96a2d6ff2d7`（R98），包含GUI和可独立运行的CLI，采用C++14、Qt5和CMake。目标为Ubuntu24.04或更新的x86_64 glibc环境，要求glibc2.39起及系统CJK字体。

## 当前可下载包（2026-11-07）

[下载x86_64 glibc预览包](https://github.com/29583855/dukto-next/actions/runs/42266702018/artifacts/13532504491)（GitHub附件可能需要登录）。ZIP内含tar.gz、SHA及原始证据。内部tar.gz SHA-256：`3abe49bf08c653ab7c7c10fe66fd898d4fe95e060f500b4e061145dc6d80bd7e`。

333份应用源码全集逐字节匹配精确Git提交，708文件、2链接和132 ELF均已核验；23项核心测试、四种退出状态和原16组并行处置通过。实际Xvfb/X11、Weston/Wayland迁移各自通过16通道双向、1/4/16覆盖和4→8恢复，双显示各三份业务报告均已核验。两张包首次启动截图已查看，中文说明和控件正常。

[包资格回执](validation/2026-11-07/exit-state-r98-linux-package-terminal/qualified-receipt.json)绑定原始报告、截图和程序摘要。本机归档：`dist/linux-preview-20261107-r98-exit-state`。GUI需系统CJK字体，例如fonts-wqy-zenhei。

该包为R98，尚未包含R99发送文本预检及拒绝保留草稿修复。Xvfb/Weston迁移通过不替代物理桌面、干净系统、完整第三方源码或正式发布验收；完整项目继续未完成。

## 构建依赖

开发助手负责安装和记录 Qt5 工具链。已准备的 Ubuntu 环境使用 Qt 5.15.13、GCC 13.3、CMake/Ninja、OpenSSL 3.0.13 及发行版安全补丁，并安装 SQLite、Qt Quick Controls 2、Qt QML/Models/WorkerScript、Qt Graphical Effects 和 Qt Wayland 模块。

QML 模块属于运行依赖。`qmlimportscanner` 若报告缺失模块，打包立即失败；不得忽略该项。前一轮实际因缺少 `qml-module-qtgraphicaleffects` 而失败，现已从 Ubuntu 官方签名仓库安装，并补入 Linux CI 依赖列表。安装记录与后续包测试分别保存。

## 生成

必须在固定源码快照安装成功、Qt5 GUI/CLI 编译和对应测试结束后打包。首次快照安装刷新所有输入文件时间，不能用保留旧 mtime 的 tar 覆盖来证明增量构建正确。

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 scripts/package_linux.py --output dist/linux-preview-<唯一名称>
```

输出目录必须不存在。脚本部署 GUI、独立 CLI、实际 QML 导入、Qt 平台/SQLite 插件以及递归 ELF 依赖，并逐文件记录 SHA-256、来源和发行版包版本。系统 glibc 及列明的基础系统库由目标系统提供，不将宿主动态加载器混入包中。

产物包括 `DuktoNext-linux-glibc-x64-preview.tar.gz`、摘要清单及展开目录。`package-manifest.json` 和 `dependency-packages.json` 记录实际内容；许可和本工程对应源码随包保存。第三方准确对应源码、补丁及构建配方的完整分发仍在实施。

## 运行

解压到用户可访问的目录后，使用顶层启动器：

```sh
./dukto-gui
./dukto-cli --help
./dukto-cli doctor --json
```

启动器配置包内依赖搜索路径。GUI 需要 X11 或 Wayland 会话及适合显示中文的系统字体；CLI 可以在 SSH 和无桌面服务器独立运行。服务器初始化、共享、配对、上传、下载和恢复命令见项目 README。

## 迁移验证与当前状态

测试须解压实际 tar 包到包含中文和空格的新目录，在移除开发环境路径后执行：

```sh
python3 tests/linux_package_integration.py <tar包> --platform xcb --report <X11结果.json>
python3 tests/linux_package_integration.py <tar包> --platform wayland --report <Wayland结果.json>
```

调用方分别提供真实 X11/Wayland 会话。测试核对依赖实际从迁移目录加载、CLI 不加载图形模块、GUI 原生平台插件与渲染、SQLite/TLS、16 通道双向及幂等重试。Xvfb/Weston 的结果属于虚拟显示环境，不替代物理桌面、物理局域网或干净系统验收。

2026-11-05当时记录：固定源码正在 Ubuntu 重建，完成后顺序执行大于虚拟机内存的文件专项、打包及两种显示会话迁移验证；结果结束前不标记打包通过。较早源码的 X11/Wayland 面板验证与最新包验收分别记录在主计划。


2026-11-05 会话/公平排队 160 文件固定快照已完成构建及 17/17 CTest，完整业务驱动已结束归档，但会话/隔离/256 MiB 恢复失败仍开放。r5 包生成成功后，X11/Wayland 迁移都捕获 OpenSSL 实际来自系统路径，因此尚不能作为通过的独立包。

[动态加载器记录](validation/2026-11-05/linux-glibc-package-loader-r1.log)显示 Qt 首先请求 libcrypto.so/libssl.so，而原包只有 libcrypto.so.3/libssl.so.3。打包器补同目录相对别名，避免单独复制两份 ELF；包测试只允许这两个准确的相对链接，继续拒绝其他符号/硬链接，并要求仅有包内一份 crypto/ssl 映射。修复的实际 X11/Wayland 验证按独立隔离快照继续，不将脚本修改本身标为包验收通过。

2026-11-05 当前部署增量：r6 OpenSSL 别名包 X11 实际迁移通过；Wayland 的 EGL/装饰错误保留。临时副本补 wayland-decoration-client 插件并默认软件 EGL 的探针已通过，截图已核对；正式脚本已纳入这两项，r7 实际归档包验证仍运行。GUI 启动器默认 LIBGL_ALWAYS_SOFTWARE=1，可由用户显式设为 0；CLI 不设置该图形选项。Wayland 需要目标系统兼容的 Mesa/EGL 及驱动依赖，不能把宿主图形驱动宣称为包内依赖。最新 166 源码两 Linux 的构建/专项驱动独立进行，不把旧二进制包作为最新重试版。

r7归档已生成，SHA c4212ec28875737815d64c2b0ed0ac20ebf7ed37eca500dd7b5d7284a11e6ab3。实际X11/Wayland界面/装饰/依赖断言及截图通过后，双会话后续16通道上传均在原90秒超时，整包仍失败，见[完整终态](validation/2026-11-05/linux-glibc-package-wayland-runtime-r3/driver-result.json)。截图已核对。原包只含160生产源码；同包在前置负载退出归档后再独立复验，不能用较长诊断替代默认门槛。新测试在业务失败时写入passed=false的部分报告，保留实际运行模块而不伪装为完整包通过。

## v0.28 同包独立复验（2026-11-05）

同一 r7 tar（SHA c4212ec28875737815d64c2b0ed0ac20ebf7ed37eca500dd7b5d7284a11e6ab3）在前置驱动退出归档后[实际独立复验](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/driver-result.json)通过。[X11](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/results/x11.json)与 [Wayland](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/results/wayland.json)各核对 705 清单文件、真实 GUI/装饰/依赖来源/空标准错误和原 90 秒 16 通道业务，截图已检查，runtimeChecksPassed/transferChecksPassed/passed 均 true。原负载下超时保留，此结果不证明超时原因已修复。包仍含旧 160 生产二进制，早于新重试和 fail；干净系统/正式发布及最新源码包仍未验收。


v0.42当前1842009生产代码的独立原生CPU打包工作流linux-package.yml已接入，使用Ubuntu24.04/C++14/Qt5，先执行19项核心测试，再生成真实tar并分别在Xvfb和Weston会话迁移验证。包清单增加精确Git提交和原始GUI/CLI摘要；仅记录元数据，不改变应用代码。实际结果、摘要和下载地址待运行完成后填写。旧r7包及原失败不替换、不冒充新构建。


v0.43当前Linux包首轮终态：41998140793在Ubuntu24.04实际编译、19项核心和打包通过；tar SHA f3fd661d111dd7af1c21ee5b6d2533582fe5797e3e48a4fd311ea4ce0734376c。已实际下载，708清单文件、2同目录OpenSSL链接、132 ELF和204应用输入/精确0a38ceb树核对。Wayland完整迁移/双向16通道通过；X11在GUI映射采样得到空列表时失败，未完成整包资格，原始附件/日志/包保留于github-evidence-r43-linux-native-initial及dist/linux-preview-20261105-r43-linux-native-initial。

映射采样修正只处理可确认的退出竞争：遇到空映射最多等待100ms确认进程已经退出，才转为既有NoSuchProcess退出路径；活动进程空映射仍失败。GUI最终退出码、无标准错误、真实平台插件/依赖来源、截图和原90秒16通道断言均保留，未获得模块证据仍不能通过。新增实际活进程/已退出进程四边界自检，同时确认外部Qt和CLI图形模块仍拒绝；Windows本机自检及163文件0标记/C++14/格式通过。首次自检开发时的Windows模拟映射路径改为POSIX规范路径后通过，不涉及应用代码。独立新原生包复验继续；原VM、Mac和Windows冻结输入均不改。


2026-11-05 v0.46版本范围补记：上方已验收的实际包早于证书续期/指纹迁移功能，不含serve renew、profile-info及trust；新源码和新包的资格分别记录，新包实际下载校验结束后再更换入口。


v0.47：当前下载入口已更新为d4626d0证书版。此前v0.46范围补记指当时旧包，旧记录保留。


v0.48字体补记：Linux桌面需系统中文字库，例如Ubuntu的fonts-wqy-zenhei（Alpine为font-wqy-zenhei）；现有包构建/迁移环境已安装并由发行版管理，包未内嵌CJK字体。纯CLI无桌面/字体依赖。本轮Ubuntu22通用CI漏装导致中文方框，已保留原图，补齐依赖并增加真实Qt字形门槛，新门槛四runner原生/150%/200%和各19核心均已通过，原始附件已归档；不能用原导航通过替代中文显示验收。


v0.48完整协议补记：f230f3d的Ubuntu22 job及原生Alpine均已31/31终态success，原附件/job日志/逐份报告摘要已归档；两次四平台矩阵仍等待其余runner，不作完整矩阵通过或物理LAN结论。


v0.51：本页当前包双向1/4/16覆盖与已有文件4→8恢复通过；旧f230f3d包保留。新增真实盘满单通道上传暴露远端5/磁盘错误被3/网络错误遮盖，本包尚未包含0017修复；新源码和新包资格分别验收。


## 31f3db3下载记录（历史，2026-11-05）

[下载x86_64 glibc预览包](https://github.com/29583855/dukto-next/actions/runs/42030410632/artifacts/13415898193)（GitHub附件下载可能需要登录）。ZIP内含tar、SHA清单和迁移证据。内部tar SHA-256：

```text
184402a446c14d99b9918c1bcbe961a28d4170a1e2dfb45654704b9a3c401dcf
```

源码31f3db3，Ubuntu24.04/glibc2.39起，x86_64，GUI和独立CLI。实际Xvfb/X11和Weston/Wayland迁移、16通道双向、1/4/16覆盖及4→8恢复均通过；两个显示报告的内部业务结果已逐项核对。708文件、2链接、132 ELF及213应用输入与精确Git树匹配，两实际截图已查看，中文显示正常。GUI需系统CJK字体，例如fonts-wqy-zenhei。

[完整回执](validation/2026-11-05/github-evidence-r52-peer-close-linux-terminal/receipt.json)。原31f3db3完整矩阵和Alpine完整协议有会话到期日志观察失败，保留原failure；本机两种Linux独立64MiB tmpfs五报告/九故障方向均通过，不代替完整协议或完整原生桌面资格。干净系统、物理桌面、第三方对应源码/重建及正式发布继续未完成。


### v0.69 新源码资格说明（2026-11-06）

最新生产源码4da0b12增加双端处置摘要确认，双Windows核心与协议专项通过；精确新提交的原生CI及双Mac部署包已启动，终态和原附件待核验。本页下载仍为已验db8c774生产输入，不声称包含新协议。上一db8c774五环境各21核心、四runner159及Alpine39协议原报告SHA均已核验。见[本轮回执](ci-verification-20261106-r69.json)。


## R98替换前的下载入口（历史）

当前5857073包与db8c774生产输入相同，包含历史完成任务只读重验、逐项处置及确认恢复；GUI与独立CLI均已实际迁移验证。

更新日期：2026-11-06。目标为Ubuntu24.04或更新的x86_64 glibc环境，要求glibc2.39起及系统CJK字体。正式发布资格仍为false。


## 当前可下载包（2026-11-06）

[下载x86_64 glibc预览包](https://github.com/29583855/dukto-next/actions/runs/42111269030/artifacts/13455131861)（GitHub附件可能需要登录）。ZIP内含tar、SHA及原始证据。内部tar SHA-256：a05fe6ad7434cf3e77d9fab68abbd817055c31e3a4ffcaf59c75366d3daf4556。

包源5857073，生产输入与db8c774相同。242份应用源码与精确Git树全集一致，708文件、2链接和132 ELF核验通过；21核心及主窗口导航通过。实际Xvfb/X11、Weston/Wayland迁移各自通过16通道双向、1/4/16覆盖及4→8恢复，三份内嵌业务报告均已读。两张实际截图已查看，中文/控件正常。GUI需系统CJK字体，例如fonts-wqy-zenhei。

[公开回执](ci-verification-20261106-r68.json)分别绑定ELF和启动器摘要；覆盖/恢复子报告记录启动器摘要，transfer子报告未提供程序摘要，身份范围由实际归档及已验测试输入绑定。原附件持久保存在dist/linux-preview-20261106-r67-completed-history-terminal。Xvfb/Weston不替代物理桌面、干净系统、完整第三方源码或正式发布验收。

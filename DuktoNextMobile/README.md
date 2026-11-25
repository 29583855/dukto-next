# Dukto Next Mobile

创建日期：2026-11-25。独立移动项目，C++14，目标Android 10+ arm64、iOS/iPadOS 15+ arm64（均待真机验收）。

当前为开发版本，尚未完成移动端功能和安装验收，不作为客户发行版。

- `shared/`：从桌面提交a548b6ca复制的协议、传输、SQL及界面源码；仅修改移动副本。
- `app/`：移动宿主与触屏界面。
- `platform/`：Android与iOS平台集成。
- `scripts/`：固定依赖与可复现构建。
- `evidence/`：快照摘要、失败记录及验收证据。
- `docs/`：本项目实施进度和使用说明。

原始桌面项目和`Dukto/`参考目录不改。完整任务范围见上级`docs/iOS与Android开发计划与进度.md`。
iOS签名、组播能力与真机验收需要有效Apple开发团队配置；未签名.app不能直接提供客户安装。

使用和验收步骤见`docs/移动端使用与验收说明.md`；工具链、源码来源及分发约束见`docs/构建与许可证说明.md`。

2026-11-25：Android完整调试APK及iOS含分享扩展的未签名设备归档已在GitHub编译、验包并下载复核；位于`release/development/android/`和`release/development/ios/`。包摘要与实际测试范围见`docs/开发包与验收交接-20261125.md`及`evidence/`。这些包尚无真机安装和互通验收；iOS归档不能直接安装。

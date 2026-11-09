# macOS独立预览包

更新日期：2026-11-09。当前已验预览版本R153，源码 `3d5a0fead47e31a28cd3994a549d25d23c256f55`。

Apple Silicon与Intel分别提供原生包。Cocoa迁移、导航/DPI、五项业务和截图已验；仅adhoc签名，尚未Developer ID签名或公证。

- macOS Apple Silicon：[归档](../dist/macos-arm64-r153-20261109/DuktoNext-macos-arm64-preview.tar.gz)；启动 `Dukto Next.app；./dukto-cli`。SHA-256：`4c951f9e1c15916095a200829fd5051fc785ec2c730b9d8f38f5a7487de195ff`。
- macOS Intel：[归档](../dist/macos-x86_64-r153-20261109/DuktoNext-macos-x86_64-preview.tar.gz)；启动 `Dukto Next.app；./dukto-cli`。SHA-256：`5df810c35e365f58dbc5863fece8a040e6391557622cfaaa53aeab788331a67e`。

每包484份应用源码和133份编译输入均与精确提交核对。请保留完整依赖目录；Mac/Linux在目标系统解包以保留权限和链接。

[统一当前入口](../dist/当前已验程序-20261109.md) · [当前验证](current-validation.json) · [此前文档原件](history/before-r155-20261109/docs/macOS独立预览包.md)

本页只授予已述验包范围，完整功能、物理互通、最终长测与正式发布以主计划逐项实证为准。

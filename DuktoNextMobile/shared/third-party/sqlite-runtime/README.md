# 本项目 SQLite 运行时

日期：2026-11-07。

Qt SQLite驱动取自官方qtbase v5.15.2，原文件字节保持。构建时只用宏将四个内部类改名为DuktoSQLite对应名称，作为内部驱动DUKTO_SQLITE注册；保留Qt的完整结果、绑定、事务、查询缓存和通知实现。依赖当前Qt5实际安装的Sql/Core私有头和对应库，必须在每个目标Qt补丁版本分别编译验证。

SQLite取自官方3.53.4 amalgamation ZIP，原归档保持；CMake核对固定SHA256后解压，仅编译sqlite3.c，不编译shell。SQLite源码顶部包含其公共领域声明，Qt文件保留原版权与许可，许可证原文随本目录提供；本项目GPLv3许可继续有效。

provenance.json记录官方HTTPS地址、原大小和本地固定SHA256。这证明下载后内容固定，不宣称已取得上游签名。

目的为提供各平台一致且可调用的VFS接口，避免依赖系统Qt插件隐藏的SQLite导出；不将驱动适配本身记作全局磁盘配额或自动GC完成。后续写入前拦截、跨进程账本和崩溃恢复按主计划另验。

构建保持C++14，SQLite作为C依赖编译。Windows依赖现有Qt5开发包；Debian/Ubuntu还需qtbase5-private-dev；macOS使用brew Qt5完整开发包；Alpine使用其Qt5开发头。运行时不需要这些开发头或外部sqlite3命令。

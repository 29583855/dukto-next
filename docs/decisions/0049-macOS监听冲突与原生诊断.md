# macOS监听冲突与原生诊断

日期：2026-11-06。状态：原失败已收件，原生诊断待运行，尚未证明根因或提交生产修复。

R94生产/测试源码为`dec40621cce2d223e46b343e0d3d345a67b80523`。双架构开发预览包的编译、Cocoa导航、依赖部署、迁移和各五项业务已通过；同源码完整原生运行42235469581另发现核心失败。两种资格分别保留。

两架构的`CoreTests::exclusiveTcpBinding(exclusive-first-ipv4-then-dual)`均失败：先绑定IPv4后，另一个请求Any双栈的监听仍返回成功。其余组合和`tcpAddressFamilies`结果见原XML。不能据此直接判定内核实际地址族、数据路由或Qt回退行为；需读取socket选项并实际连接。

Intel另有`FileExchangeTests::parallelDispositions(download-4-2)`失败：已完成数据/关闭报文阶段后，测试子进程未在原10秒等待内退出。原测试其他并行处置行通过，原因仍未证明。不得增加原时限或删除迟到冲突场景来获得通过。

独立`tests/listener_probe`工程使用C++14，直接编译当前`TcpListener`，记录Qt与产品监听的实际SO_REUSEADDR、SO_REUSEPORT、IPV6_V6ONLY、绑定地址及IPv4/IPv6连接去向；另对照新建原生双栈socket的复用开关。每组使用本进程独立临时端口，只关闭自己创建的描述符。探针仅输出诊断数据，不作为修复或正式验收。

新工作流`macos-listener-diagnostics.yml`在Apple Silicon/Intel分别构建探针与原`core-tests`、`file-exchange-tests`，核对生产及两份原测试与R94字节一致；原监听用例和原`download-4-2`各使用三个独立进程，保留断言和时限，任一次失败仍使对应步骤失败。

本机Alpine Qt5.15.18已完成探针独立构建和八组运行，第二监听均被拒绝；该结果只说明Linux对照行为，不授予Mac资格。原失败、原包和新诊断分别归档，下载说明明确完整回归尚未通过。

若后续考虑调整macOS原生绑定选项，还必须验证活动监听冲突、IPv4/IPv6、双栈可达、失败清理、原连接继续收发和关闭后重启；关闭地址复用可能影响TIME_WAIT下的快速重启，不能仅凭一次冲突拒绝采用该方案。

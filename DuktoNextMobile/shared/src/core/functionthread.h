#pragma once

#include <QThread>
#include <functional>
#include <utility>

namespace dukto {
// 日期：2026-11-25；兼容未提供QThread::create的Qt5移动构建，线程持有可复制的C++14任务。
class FunctionThread final : public QThread {
  public:
    // 日期：2026-11-25；创建后仍由调用者连接finished并启动，保持既有生命周期语义。
    explicit FunctionThread(std::function<void()> function) : function_(std::move(function)) {
    }

  protected:
    // 日期：2026-11-25；工作函数自行处理业务异常，线程只负责按既有约定执行一次。
    void run() override {
        function_();
    }

  private:
    std::function<void()> function_;
};
} // namespace dukto

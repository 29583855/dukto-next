package org.duktonext.validation;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;
import android.util.Log;

/** 日期：2026-11-25；验收辅助服务，只保持系统无障碍状态，不读写产品业务数据。 */
public final class ValidationAccessibility extends AccessibilityService {
    /** 日期：2026-11-26；记录系统实际绑定回调，不能将写入设置当作服务已启用。 */
    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        Log.i("DuktoValidation", "accessibility-bound");
    }

    /** 日期：2026-11-25；无需消费事件，操作及证据仍由UIAutomator获取。 */
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {}

    /** 日期：2026-11-25；中断不触发产品操作。 */
    @Override
    public void onInterrupt() {}
}

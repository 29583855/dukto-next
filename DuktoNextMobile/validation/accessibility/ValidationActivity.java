package org.duktonext.validation;

import android.app.Activity;
import android.os.Bundle;

/** 日期：2026-11-26；仅启动辅助包并立即退出，让系统解除首次安装的停止状态。 */
public final class ValidationActivity extends Activity {
    /** 日期：2026-11-26；不请求业务权限，不访问产品数据。 */
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        finish();
    }
}

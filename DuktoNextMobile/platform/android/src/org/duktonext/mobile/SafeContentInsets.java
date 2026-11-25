package org.duktonext.mobile;

import android.app.Activity;
import android.graphics.Insets;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;

final class SafeContentInsets {
    // 日期：2026-11-25；工具类只通过安装入口设置系统安全边距。
    private SafeContentInsets() {
    }

    // 日期：2026-11-25；Android15起为Qt内容预留系统栏与刘海区域，旧系统继续由窗口装饰处理。
    static void install(Activity activity) {
        if (Build.VERSION.SDK_INT < 35)
            return;
        View content = activity.findViewById(android.R.id.content);
        if (content == null)
            return;
        final int left = content.getPaddingLeft();
        final int top = content.getPaddingTop();
        final int right = content.getPaddingRight();
        final int bottom = content.getPaddingBottom();
        content.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            // 日期：2026-11-25；以原始边距叠加最新系统区域，旋转和重复分发不累计，输入法边距继续下传。
            @Override
            public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                int handled = WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout();
                Insets safe = insets.getInsets(handled);
                view.setPadding(left + safe.left, top + safe.top, right + safe.right,
                                bottom + safe.bottom);
                return new WindowInsets.Builder(insets)
                    .setInsets(handled, Insets.NONE)
                    .setInsetsIgnoringVisibility(handled, Insets.NONE)
                    .setDisplayCutout(null)
                    .build();
            }
        });
        content.requestApplyInsets();
    }
}

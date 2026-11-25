package org.duktonext.mobile;

import static org.junit.Assert.*;

import android.app.Activity;
import android.graphics.Insets;
import android.view.View;
import android.view.WindowInsets;
import android.widget.FrameLayout;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 35)
public class SafeContentInsetsTest {
    // 日期：2026-11-25；使用真实Activity内容容器，观察Qt同类满尺寸子视图的最终可见区域。
    @Test
    public void barsLeaveChildInsideUsableAreaWithoutAccumulation() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        FrameLayout content = activity.findViewById(android.R.id.content);
        content.setPadding(3, 5, 7, 11);
        View child = new View(activity);
        activity.setContentView(child);
        SafeContentInsets.install(activity);
        WindowInsets insets =
            new WindowInsets.Builder()
                .setInsets(WindowInsets.Type.statusBars(), Insets.of(0, 24, 0, 0))
                .setInsets(WindowInsets.Type.navigationBars(), Insets.of(0, 0, 0, 48))
                .build();
        content.dispatchApplyWindowInsets(insets);
        content.dispatchApplyWindowInsets(insets);
        content.measure(View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY),
                        View.MeasureSpec.makeMeasureSpec(1920, View.MeasureSpec.EXACTLY));
        content.layout(0, 0, 1080, 1920);
        assertEquals(3, child.getLeft());
        assertEquals(29, child.getTop());
        assertEquals(1073, child.getRight());
        assertEquals(1861, child.getBottom());
    }

    // 日期：2026-11-25；横竖屏切换按各方向最大安全区更新，已处理区域不再传给子项，键盘区域保留。
    @Test
    public void rotationCutoutAndKeyboardAreHandledIndependently() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        View content = activity.findViewById(android.R.id.content);
        SafeContentInsets.install(activity);
        content.dispatchApplyWindowInsets(
            new WindowInsets.Builder()
                .setInsets(WindowInsets.Type.systemBars(), Insets.of(0, 24, 0, 48))
                .build());
        WindowInsets remaining = content.dispatchApplyWindowInsets(
            new WindowInsets.Builder()
                .setInsets(WindowInsets.Type.systemBars(), Insets.of(0, 0, 48, 0))
                .setInsets(WindowInsets.Type.displayCutout(), Insets.of(80, 0, 0, 0))
                .setInsets(WindowInsets.Type.ime(), Insets.of(0, 0, 0, 500))
                .build());
        assertEquals(80, content.getPaddingLeft());
        assertEquals(0, content.getPaddingTop());
        assertEquals(48, content.getPaddingRight());
        assertEquals(0, content.getPaddingBottom());
        assertEquals(Insets.NONE, remaining.getInsets(WindowInsets.Type.systemBars() |
                                                      WindowInsets.Type.displayCutout()));
        assertEquals(500, remaining.getInsets(WindowInsets.Type.ime()).bottom);
    }

    // 日期：2026-11-25；Android10由已有窗口装饰留白，安装入口不得再增加一次边距。
    @Config(sdk = 29)
    @Test
    public void olderDecorRetainsItsPadding() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        View content = activity.findViewById(android.R.id.content);
        content.setPadding(1, 2, 3, 4);
        SafeContentInsets.install(activity);
        content.dispatchApplyWindowInsets(
            new WindowInsets.Builder().setSystemWindowInsets(Insets.of(0, 24, 0, 48)).build());
        assertEquals(1, content.getPaddingLeft());
        assertEquals(2, content.getPaddingTop());
        assertEquals(3, content.getPaddingRight());
        assertEquals(4, content.getPaddingBottom());
    }
}

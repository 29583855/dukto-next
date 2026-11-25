package org.duktonext.mobile;

import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Looper;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ServiceController;
import org.robolectric.annotation.Config;
import java.time.Duration;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = {29, 35})
public class TransferServiceTest {
    private Context context;
    // 日期：2026-11-25；隔离静态状态，不将上一个取消信号带入新任务。
    @Before public void reset() {
        context = RuntimeEnvironment.getApplication();
        TransferService.setActive(context, false);
        TransferService.takeStop();
    }
    // 日期：2026-11-25；按生产入口启动请求，再执行实际服务创建与前台通知。
    private ServiceController<TransferService> start() {
        assertTrue(TransferService.setActive(context, true));
        ServiceController<TransferService> controller = Robolectric.buildService(TransferService.class).create();
        controller.get().onStartCommand(new Intent(context, TransferService.class), 0, 1);
        assertTrue(TransferService.alive());
        return controller;
    }
    // 日期：2026-11-25；正常任务完成停止服务时不能报告意外取消。
    @Test public void ordinaryCompletionDoesNotCancel() {
        ServiceController<TransferService> controller = start();
        TransferService.setActive(context, false);
        controller.destroy();
        assertFalse(TransferService.alive());
        assertFalse(TransferService.takeStop());
    }
    // 日期：2026-11-25；通知按钮取消仅发一次停止信号且不自动重启。
    @Test public void notificationCancelsOnce() {
        ServiceController<TransferService> controller = start();
        controller.get().onStartCommand(new Intent(context, TransferService.class).setAction("org.duktonext.mobile.CANCEL_TRANSFER"), 0, 2);
        assertFalse(TransferService.alive());
        assertTrue(TransferService.takeStop());
        assertFalse(TransferService.takeStop());
        controller.destroy();
        assertFalse(TransferService.takeStop());
    }
    // 日期：2026-11-25；系统额度回调立即停止，服务意外销毁也能触发Qt取消。
    @Test public void systemTimeoutAndUnexpectedDestroy() {
        ServiceController<TransferService> controller = start();
        controller.get().onTimeout(1, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        assertFalse(TransferService.alive());
        assertTrue(TransferService.takeStop());
        controller.destroy();
        controller = start();
        controller.destroy();
        assertFalse(TransferService.alive());
        assertTrue(TransferService.takeStop());
    }
    // 日期：2026-11-25；推进主线程时钟验证30分钟应用期限，即使系统没有额度回调也停止。
    @Test public void applicationDeadlineStopsTransfer() {
        ServiceController<TransferService> controller = start();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMinutes(31));
        assertFalse(TransferService.alive());
        assertTrue(TransferService.takeStop());
        controller.destroy();
    }
}

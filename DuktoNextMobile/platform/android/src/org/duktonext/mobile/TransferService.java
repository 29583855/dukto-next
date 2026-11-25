package org.duktonext.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import java.util.concurrent.atomic.AtomicBoolean;

public final class TransferService extends Service {
    private static final String CHANNEL = "dukto-transfers";
    private static final String IDLE = "org.duktonext.mobile.TRANSFER_IDLE";
    private static final String CANCEL = "org.duktonext.mobile.CANCEL_TRANSFER";
    private static final AtomicBoolean requested = new AtomicBoolean(false);
    private static final AtomicBoolean stopped = new AtomicBoolean(false);
    private static final long MAX_MILLIS = 30L * 60L * 1000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private boolean finishing;
    private int latestStartId;
    private final Runnable idleStop = this::stopIfIdle;
    private final Runnable deadline = () -> finishTransfer(true);

    // 日期：2026-11-26；结束请求排队交给服务，禁止外部stopService抢先销毁待提升的前台启动。
    public static synchronized boolean setActive(Context context, boolean active) {
        try {
            if (active) {
                stopped.set(false);
                if (!requested.getAndSet(true))
                    context.startForegroundService(new Intent(context, TransferService.class));
            } else if (requested.getAndSet(false)) {
                context.startService(new Intent(context, TransferService.class).setAction(IDLE));
            }
            return active;
        } catch (RuntimeException error) {
            requested.set(false);
            Log.w("DuktoNext", "Transfer foreground service unavailable", error);
            return false;
        }
    }
    // 日期：2026-11-25；同时反映启动请求与实际系统停止状态。
    public static boolean alive() {
        return requested.get() && !stopped.get();
    }
    // 日期：2026-11-25；Qt定时器取走一次停止事件，避免重复取消新任务。
    public static boolean takeStop() {
        return stopped.getAndSet(false);
    }
    // 日期：2026-11-26；创建即上报通知，避免Qt快速结束任务时跳过系统前台启动义务。
    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(
            new NotificationChannel(CHANNEL, "文件传输", NotificationManager.IMPORTANCE_LOW));
        try {
            promoteForeground();
        } catch (RuntimeException error) {
            Log.w("DuktoNext", "Cannot promote transfer foreground service", error);
            finishTransfer(true);
        }
    }
    // 日期：2026-11-26；每个系统启动回调先完成前台提升，即使短批次已结束也必须履约。
    private void promoteForeground() {
        PendingIntent cancel = PendingIntent.getService(
            this, 1, new Intent(this, TransferService.class).setAction(CANCEL),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent open = PendingIntent.getActivity(
            this, 2,
            new Intent(this, DuktoActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification =
            new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_upload)
                .setContentTitle("Dukto Next 正在传输")
                .setContentText("后台最长30分钟；点击返回，或停止传输")
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, "停止传输", cancel).build())
                .build();
        startForeground(4644, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
    }
    // 日期：2026-11-26；取消及过期启动也先履行前台提升，再收尾；长任务才取得限时系统锁。
    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        handler.removeCallbacks(idleStop);
        try {
            promoteForeground();
            if (intent != null && CANCEL.equals(intent.getAction())) {
                finishTransfer(true);
                return START_NOT_STICKY;
            }
            if (!requested.get()) {
                handler.postDelayed(idleStop, 750L);
                return START_NOT_STICKY;
            }
            finishing = false;
            if (wakeLock == null) {
                PowerManager power = getSystemService(PowerManager.class);
                wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DuktoNext:Transfer");
                wakeLock.setReferenceCounted(false);
                wakeLock.acquire(MAX_MILLIS);
                WifiManager wifi =
                    (WifiManager)getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                if (wifi != null) {
                    wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                                                   "DuktoNextTransfer");
                    wifiLock.setReferenceCounted(false);
                    wifiLock.acquire();
                }
                handler.postDelayed(deadline, MAX_MILLIS);
            }
        } catch (RuntimeException error) {
            Log.w("DuktoNext", "Cannot hold transfer foreground service", error);
            finishTransfer(true);
        }
        return START_NOT_STICKY;
    }
    // 日期：2026-11-25；Android15数据同步额度到期后立即停止并通知Qt保存可恢复状态。
    @Override
    public void onTimeout(int startId, int foregroundServiceType) {
        finishTransfer(true);
    }
    // 日期：2026-11-25；用户从最近任务移除应用时停止既有任务，不保留隐形服务。
    @Override
    public void onTaskRemoved(Intent rootIntent) {
        finishTransfer(true);
    }
    // 日期：2026-11-25；所有退出路径释放系统锁，意外销毁报告停止事件。
    @Override
    public void onDestroy() {
        boolean unexpected = requested.getAndSet(false);
        if (unexpected)
            stopped.set(true);
        handler.removeCallbacks(deadline);
        handler.removeCallbacks(idleStop);
        if (wifiLock != null && wifiLock.isHeld())
            wifiLock.release();
        if (wakeLock != null && wakeLock.isHeld())
            wakeLock.release();
        super.onDestroy();
    }
    // 日期：2026-11-25；该服务不提供外部绑定入口。
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
    // 日期：2026-11-26；合并短批次结束并按最新启动编号停止，排队的新任务不能被旧收尾截断。
    private void stopIfIdle() {
        synchronized (TransferService.class) {
            if (requested.get())
                return;
            if (stopSelfResult(latestStartId)) {
                finishing = true;
                stopForeground(STOP_FOREGROUND_REMOVE);
            }
        }
    }
    // 日期：2026-11-25；先记录取消，再移除通知与服务，Qt在250毫秒轮询中收尾。
    private void finishTransfer(boolean signal) {
        if (!finishing) {
            finishing = true;
            requested.set(false);
            if (signal)
                stopped.set(true);
        }
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }
}

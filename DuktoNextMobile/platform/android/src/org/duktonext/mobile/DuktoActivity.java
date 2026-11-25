package org.duktonext.mobile;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.util.Log;
import org.qtproject.qt5.android.bindings.QtActivity;

public class DuktoActivity extends QtActivity {
    private WifiManager.MulticastLock discoveryLock;
    private boolean notificationAsked;

    // 日期：2026-11-25；首次实际传输才请求通知；拒绝后仍按系统前台服务规则处理。
    public void requestTransferNotifications() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && !notificationAsked &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationAsked = true;
            requestPermissions(new String[] {android.Manifest.permission.POST_NOTIFICATIONS}, 4645);
        }
    }

    // 日期：2026-11-25；冷启动保留系统分享，等待用户选择发送目标。
    @Override public void onCreate(android.os.Bundle state) {
        super.onCreate(state);
        if (state == null) IncomingShare.accept(getIntent());
    }
    // 日期：2026-11-25；已运行应用接受新分享，单槽保护未处理的旧内容。
    @Override public void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        IncomingShare.accept(intent);
    }

    // 日期：2026-11-25；只在可见期间持锁，系统拒绝时记录具体原因供局域网诊断。
    @Override public void onResume() {
        super.onResume();
        try {
            WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifi != null) {
                if (discoveryLock == null) {
                    discoveryLock = wifi.createMulticastLock("DuktoNextDiscovery");
                    discoveryLock.setReferenceCounted(false);
                }
                if (!discoveryLock.isHeld()) discoveryLock.acquire();
            }
        } catch (RuntimeException error) {
            Log.w("DuktoNext", "Wi-Fi discovery lock unavailable", error);
        }
    }

    // 日期：2026-11-25；暂停时释放锁，不让闲置应用长期占用无线电资源。
    @Override public void onPause() {
        if (discoveryLock != null && discoveryLock.isHeld()) discoveryLock.release();
        super.onPause();
    }
}

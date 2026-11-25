package org.duktonext.mobile;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.util.Log;
import org.qtproject.qt5.android.bindings.QtActivity;

public class DuktoActivity extends QtActivity {
    private WifiManager.MulticastLock discoveryLock;

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

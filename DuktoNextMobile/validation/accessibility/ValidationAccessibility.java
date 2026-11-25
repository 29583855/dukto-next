package org.duktonext.validation;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Rect;
import android.os.Build;
import android.util.Log;
import android.util.Xml;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.File;
import java.io.FileOutputStream;
import org.xmlpull.v1.XmlSerializer;

/** 日期：2026-11-26；独立验收包持续读取真实系统控件树，不访问产品业务接口。 */
public final class ValidationAccessibility extends AccessibilityService {
    private boolean registered;
    private final BroadcastReceiver snapshotReceiver = new BroadcastReceiver() {
        /** 日期：2026-11-26；仅持有系统DUMP权限的发送者可请求快照，用随机标记拒绝旧树。 */
        @Override
        public void onReceive(Context context, Intent intent) {
            String token = intent.getStringExtra("token");
            if (token == null || !token.matches("[a-f0-9]{32}")) {
                return;
            }
            writeSnapshot(token);
        }
    };

    /** 日期：2026-11-26；记录实际绑定，持续服务避免临时UiAutomation改变Qt无障碍状态。 */
    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        AccessibilityServiceInfo info = getServiceInfo();
        info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS |
                      AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        setServiceInfo(info);
        // 日期：2026-11-26；读取实时Qt虚拟树，避免系统缓存保留弹窗打开前的旧页面。
        if (Build.VERSION.SDK_INT >= 33) {
            setCacheEnabled(false);
        }
        if (!registered) {
            registerReceiver(snapshotReceiver,
                             new IntentFilter("org.duktonext.validation.SNAPSHOT"),
                             "android.permission.DUMP", null, Context.RECEIVER_EXPORTED);
            registered = true;
        }
        Log.i("DuktoValidation", "accessibility-bound");
    }

    /** 日期：2026-11-26；系统节点写入辅助包私有目录，验收通过run-as读取并验证标记。 */
    private void writeSnapshot(String token) {
        File temporary = new File(getFilesDir(), "tree.pending");
        File target = new File(getFilesDir(), "tree.xml");
        AccessibilityNodeInfo root = getRootInActiveWindow();
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            XmlSerializer xml = Xml.newSerializer();
            xml.setOutput(output, "UTF-8");
            xml.startDocument("UTF-8", true);
            xml.startTag(null, "hierarchy");
            xml.attribute(null, "token", token);
            if (root != null) {
                writeNode(xml, root, 0, 0);
            }
            xml.endTag(null, "hierarchy");
            xml.endDocument();
            output.getFD().sync();
            if (!temporary.renameTo(target)) {
                throw new java.io.IOException("Cannot publish accessibility snapshot");
            }
        } catch (Exception error) {
            Log.e("DuktoValidation", "snapshot-failed", error);
        } finally {
            if (root != null) {
                root.recycle();
            }
        }
    }

    /** 日期：2026-11-26；导出系统给出的文字、控件状态和屏幕矩形，不伪造产品节点。 */
    private void writeNode(XmlSerializer xml, AccessibilityNodeInfo node, int index, int depth)
        throws java.io.IOException {
        if (depth > 100) {
            throw new java.io.IOException("Accessibility tree exceeds depth limit");
        }
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        xml.startTag(null, "node");
        xml.attribute(null, "index", Integer.toString(index));
        xml.attribute(null, "text", value(node.getText()));
        xml.attribute(null, "content-desc", value(node.getContentDescription()));
        xml.attribute(null, "resource-id", value(node.getViewIdResourceName()));
        xml.attribute(null, "class", value(node.getClassName()));
        xml.attribute(null, "package", value(node.getPackageName()));
        xml.attribute(null, "enabled", Boolean.toString(node.isEnabled()));
        xml.attribute(null, "editable", Boolean.toString(node.isEditable()));
        xml.attribute(null, "focused", Boolean.toString(node.isFocused()));
        xml.attribute(null, "clickable", Boolean.toString(node.isClickable()));
        xml.attribute(null, "scrollable", Boolean.toString(node.isScrollable()));
        xml.attribute(null, "visible-to-user", Boolean.toString(node.isVisibleToUser()));
        xml.attribute(null, "bounds",
                      "[" + bounds.left + "," + bounds.top + "][" + bounds.right + "," +
                          bounds.bottom + "]");
        for (int childIndex = 0; childIndex < node.getChildCount(); childIndex++) {
            AccessibilityNodeInfo child = node.getChild(childIndex);
            if (child != null) {
                try {
                    writeNode(xml, child, childIndex, depth + 1);
                } finally {
                    child.recycle();
                }
            }
        }
        xml.endTag(null, "node");
    }

    /** 日期：2026-11-26；缺省字段为空字符串，保持XML属性可解析。 */
    private static String value(CharSequence text) {
        return text == null ? "" : text.toString();
    }

    /** 日期：2026-11-26；事件由系统维护，产品操作仍从可见节点矩形执行。 */
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
    }

    /** 日期：2026-11-26；中断不触发产品操作。 */
    @Override
    public void onInterrupt() {
    }

    /** 日期：2026-11-26；卸载辅助包前清除临时系统广播接收器。 */
    @Override
    public void onDestroy() {
        if (registered) {
            unregisterReceiver(snapshotReceiver);
            registered = false;
        }
        super.onDestroy();
    }
}

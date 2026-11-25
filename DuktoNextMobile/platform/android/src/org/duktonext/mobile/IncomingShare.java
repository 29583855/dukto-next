package org.duktonext.mobile;

import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;

public final class IncomingShare {
    private static Intent pending;
    private static String text = "";
    private static String error = "";
    private static int files;

    // 日期：2026-11-25；仅接受有界文本和content授权URI；已有待处理分享时明确拒绝替换。
    public static synchronized void accept(Intent source) {
        if (source == null || !(Intent.ACTION_SEND.equals(source.getAction()) || Intent.ACTION_SEND_MULTIPLE.equals(source.getAction()))) return;
        if (pending != null || !text.isEmpty()) {
            error = "已有待处理分享，请先发送或丢弃，再重新分享";
            return;
        }
        try {
            CharSequence value = source.getCharSequenceExtra(Intent.EXTRA_TEXT);
            String body = "";
            if (value != null) {
                if (value.length() > 262144) throw new IllegalArgumentException("分享文本超过256KiB限制");
                body = value.toString();
                if (body.getBytes(StandardCharsets.UTF_8).length > 262144) throw new IllegalArgumentException("UTF-8分享文本超过256KiB限制");
            }
            ArrayList<Uri> selected = new ArrayList<>();
            if (Intent.ACTION_SEND_MULTIPLE.equals(source.getAction())) {
                ArrayList<Uri> streams = source.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                if (streams != null) selected.addAll(streams);
            } else {
                Uri stream = source.getParcelableExtra(Intent.EXTRA_STREAM);
                if (stream != null) selected.add(stream);
            }
            if (selected.isEmpty() && source.getClipData() != null) {
                ClipData clip = source.getClipData();
                if (clip.getItemCount() > 512) throw new IllegalArgumentException("分享文件超过512项");
                for (int i = 0; i < clip.getItemCount(); ++i) {
                    Uri uri = clip.getItemAt(i).getUri();
                    if (uri != null) selected.add(uri);
                }
            }
            if (selected.size() > 512) throw new IllegalArgumentException("分享文件超过512项");
            HashSet<String> unique = new HashSet<>();
            ClipData clip = null;
            for (Uri uri : selected) {
                if (uri == null || !"content".equals(uri.getScheme())) throw new IllegalArgumentException("仅接受系统授权的content文档");
                if (!unique.add(uri.toString())) continue;
                if (clip == null) clip = ClipData.newRawUri("Dukto shared documents", uri);
                else clip.addItem(new ClipData.Item(uri));
            }
            if (clip == null && body.isEmpty()) throw new IllegalArgumentException("分享内容为空");
            files = clip == null ? 0 : clip.getItemCount();
            pending = null;
            if (clip != null) {
                pending = new Intent().addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                pending.setClipData(clip);
            }
            text = body;
            error = "";
        } catch (RuntimeException failure) {
            error = "分享未接收：" + failure.getMessage();
        }
    }
    // 日期：2026-11-25；界面只获得计数和有限文本，不公开提供器URI或认证资料。
    public static synchronized String info() {
        try { return new JSONObject().put("files", files).put("text", text).put("error", error).toString(); }
        catch (Exception failure) { return "{}"; }
    }
    // 日期：2026-11-25；用户明确选择发送后才取得文档并复制，失败需重新系统分享。
    public static synchronized Intent takeFiles() {
        Intent result = pending;
        pending = null;
        files = 0;
        return result;
    }
    // 日期：2026-11-25；文本成功交给传输任务后释放正文，文件分享仍可单独处理。
    public static synchronized void clearText() { text = ""; }
    // 日期：2026-11-25；显式丢弃授权引用，不访问或删除系统源文档。
    public static synchronized void clear() { pending = null; files = 0; text = ""; error = ""; }
}

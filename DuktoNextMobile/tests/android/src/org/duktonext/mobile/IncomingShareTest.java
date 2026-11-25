package org.duktonext.mobile;

import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import java.util.ArrayList;
import java.util.Collections;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = {29, 35})
public class IncomingShareTest {
    // 日期：2026-11-25；每个场景从空分享槽开始。
    @Before public void clear() { IncomingShare.clear(); }
    // 日期：2026-11-25；通过公开JSON接口观察用户可见结果。
    private JSONObject info() throws Exception { return new JSONObject(IncomingShare.info()); }
    // 日期：2026-11-25；构造真实Android系统分享对象。
    private Intent text(String value) { return new Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_TEXT, value); }
    // 日期：2026-11-25；多字节文本超限不得误按UTF16长度放行，失败后仍可接受下一次合法分享。
    @Test public void utf8BudgetAndRecovery() throws Exception {
        IncomingShare.accept(text(String.join("", Collections.nCopies(90000, "中"))));
        assertFalse(info().getString("error").isEmpty());
        assertEquals("", info().getString("text"));
        IncomingShare.accept(text("中文😀"));
        assertEquals("中文😀", info().getString("text"));
        assertEquals("", info().getString("error"));
    }
    // 日期：2026-11-25；精确边界可接收，已有内容不被另一个来源覆盖。
    @Test public void boundedSlotRefusesReplacement() throws Exception {
        String body = String.join("", Collections.nCopies(262144, "a"));
        IncomingShare.accept(text(body));
        IncomingShare.accept(text("replacement"));
        assertEquals(body, info().getString("text"));
        assertFalse(info().getString("error").isEmpty());
        IncomingShare.clear();
        IncomingShare.accept(text("accepted"));
        assertEquals("accepted", info().getString("text"));
    }
    // 日期：2026-11-25；混合分享保留文字，文档去重后仅消费一次且不向JSON公开URI。
    @Test public void mixedShareConsumedOnce() throws Exception {
        ArrayList<Uri> paths = new ArrayList<>();
        paths.add(Uri.parse("content://provider/secret-document"));
        paths.add(paths.get(0));
        paths.add(Uri.parse("content://provider/second"));
        Intent source = new Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, paths).putExtra(Intent.EXTRA_TEXT, "说明");
        IncomingShare.accept(source);
        assertEquals(2, info().getInt("files"));
        assertFalse(IncomingShare.info().contains("provider"));
        IncomingShare.clearText();
        assertEquals(2, info().getInt("files"));
        Intent files = IncomingShare.takeFiles();
        assertEquals(2, files.getClipData().getItemCount());
        assertEquals("", info().getString("text"));
        assertNull(IncomingShare.takeFiles());
        assertEquals(0, info().getInt("files"));
    }
    // 日期：2026-11-25；拒绝file/http等未经系统content授权的输入，不能部分保留合法前项。
    @Test public void unsafeUriRejectsWholeBatch() throws Exception {
        ClipData clip = ClipData.newRawUri("test", Uri.parse("content://provider/good"));
        clip.addItem(new ClipData.Item(Uri.parse("file:///data/private")));
        IncomingShare.accept(new Intent(Intent.ACTION_SEND_MULTIPLE).setClipData(clip));
        assertEquals(0, info().getInt("files"));
        assertNull(IncomingShare.takeFiles());
        assertFalse(info().getString("error").isEmpty());
    }
    // 日期：2026-11-25；过量文件批次明确拒绝而非截断发送。
    @Test public void tooManyFilesRejectsBatch() throws Exception {
        ArrayList<Uri> paths = new ArrayList<>();
        for (int index = 0; index < 513; index++) paths.add(Uri.parse("content://provider/" + index));
        IncomingShare.accept(new Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, paths));
        assertEquals(0, info().getInt("files"));
        assertFalse(info().getString("error").isEmpty());
    }
    // 日期：2026-11-25；非分享启动与空内容不产生伪待发送任务。
    @Test public void ignoresLauncherAndEmptyShare() throws Exception {
        IncomingShare.accept(new Intent(Intent.ACTION_MAIN).putExtra(Intent.EXTRA_TEXT, "ignored"));
        assertEquals("", info().getString("text"));
        IncomingShare.accept(text(""));
        assertFalse(info().getString("error").isEmpty());
        assertNull(IncomingShare.takeFiles());
    }
}

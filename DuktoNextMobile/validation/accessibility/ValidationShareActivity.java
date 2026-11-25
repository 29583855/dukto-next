package org.duktonext.validation;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import java.util.ArrayList;

/** 日期：2026-11-26；模拟来源应用经系统授权分享文件，不调用产品内部接口。 */
public final class ValidationShareActivity extends Activity {
    /** 日期：2026-11-26；明确向原始产品Activity发送两份只读文件，来源不具备网络权限。 */
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        ArrayList<Uri> files = new ArrayList<>();
        files.add(Uri.parse("content://org.duktonext.validation.files/sample"));
        files.add(Uri.parse("content://org.duktonext.validation.files/empty"));
        ClipData clip = ClipData.newRawUri("Dukto validation files", files.get(0));
        clip.addItem(new ClipData.Item(files.get(1)));
        Intent share = new Intent(Intent.ACTION_SEND_MULTIPLE);
        share.setClassName("org.duktonext.mobile", "org.duktonext.mobile.DuktoActivity");
        share.setType("application/octet-stream");
        share.putParcelableArrayListExtra(Intent.EXTRA_STREAM, files);
        share.setClipData(clip);
        share.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        startActivity(share);
        finish();
    }
}

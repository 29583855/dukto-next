package org.duktonext.mobile;

import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashSet;

public final class Documents {
    // 日期：2026-11-25；查询提供器元数据，虚拟文件需转换格式，当前明确拒绝而非读取错误内容。
    private static JSONObject metadata(Context context, Uri uri) throws Exception {
        String[] columns = {DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_FLAGS};
        try (Cursor cursor = context.getContentResolver().query(uri, columns, null, null, null)) {
            if (cursor == null || !cursor.moveToFirst()) {
                throw new IOException("文档提供器未返回文件信息");
            }
            JSONObject value = new JSONObject();
            value.put("uri", uri.toString());
            value.put("name", cursor.getString(0));
            value.put("size", cursor.isNull(1) ? -1 : cursor.getLong(1));
            value.put("modified", cursor.isNull(2) ? -1 : cursor.getLong(2));
            value.put("directory", DocumentsContract.Document.MIME_TYPE_DIR.equals(cursor.getString(3)));
            if (!cursor.isNull(4) && (cursor.getLong(4) & DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT) != 0) {
                throw new IOException("请先将虚拟文档导出为普通文件");
            }
            return value;
        }
    }

    // 日期：2026-11-25；文件复制前后核对同一提供器元数据，授权撤回与文件变化均会失败。
    public static String signature(Context context, String uri) throws Exception {
        return metadata(context, Uri.parse(uri)).toString();
    }

    // 日期：2026-11-25；目录递归有条目、深度和循环限制，不在界面线程枚举。
    private static void walk(Context context, Uri tree, Uri document, String parent, int depth,
                             JSONArray entries, HashSet<String> seen) throws Exception {
        if (depth > 32 || entries.length() >= 512 || !seen.add(document.toString())) {
            throw new IOException("目录条目、层级超限或提供器目录循环");
        }
        JSONObject item = metadata(context, document);
        String name = item.getString("name");
        if (name.isEmpty() || name.contains("/") || name.contains("\\")) {
            throw new IOException("提供器返回了不安全的文件名称");
        }
        String relative = parent.isEmpty() ? name : parent + "/" + name;
        item.put("relative", relative);
        item.put("signature", metadata(context, document).toString());
        entries.put(item);
        if (item.getBoolean("directory")) {
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree,
                DocumentsContract.getDocumentId(document));
            try (Cursor cursor = context.getContentResolver().query(children,
                new String[] {DocumentsContract.Document.COLUMN_DOCUMENT_ID}, null, null, null)) {
                if (cursor == null) {
                    throw new IOException("无法读取目录，授权可能已撤销");
                }
                while (cursor.moveToNext()) {
                    Uri child = DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0));
                    walk(context, tree, child, relative, depth + 1, entries, seen);
                }
            }
        }
    }

    // 日期：2026-11-25；SAF URI保持原样，C++只通过授权文件描述符读取，不解析真实路径。
    public static String scan(Context context, Intent intent, boolean folder) throws Exception {
        JSONArray entries = new JSONArray();
        if (folder) {
            Uri tree = intent.getData();
            if (tree == null) {
                throw new IOException("未选择文件夹");
            }
            Uri document = DocumentsContract.buildDocumentUriUsingTree(tree,
                DocumentsContract.getTreeDocumentId(tree));
            walk(context, tree, document, "", 0, entries, new HashSet<String>());
        } else {
            ClipData clip = intent.getClipData();
            int count = clip == null ? 1 : clip.getItemCount();
            if (count > 512) {
                throw new IOException("最多一次导入512项");
            }
            for (int index = 0; index < count; ++index) {
                Uri uri = clip == null ? intent.getData() : clip.getItemAt(index).getUri();
                if (uri == null) {
                    throw new IOException("选择器未返回有效文档");
                }
                JSONObject item = metadata(context, uri);
                if (item.getBoolean("directory")) {
                    throw new IOException("请选择普通文件，目录请使用发送文件夹");
                }
                item.put("relative", item.getString("name"));
                item.put("signature", metadata(context, uri).toString());
                entries.put(item);
            }
        }
        return entries.toString();
    }

    // 日期：2026-11-25；描述符所有权交给QFile，Java层不再持有已分离句柄。
    public static int openRead(Context context, String uri) throws Exception {
        try (ParcelFileDescriptor descriptor = context.getContentResolver()
                .openFileDescriptor(Uri.parse(uri), "r")) {
            if (descriptor == null) {
                throw new IOException("无法打开文档，请确认云端文件已下载");
            }
            return descriptor.detachFd();
        }
    }

    // 日期：2026-11-25；向ACTION_CREATE_DOCUMENT授予的目标流式导出，不申请整个外部存储权限。
    public static void export(Context context, String path, String uri) throws Exception {
        try (InputStream input = new FileInputStream(new File(path));
             OutputStream output = context.getContentResolver().openOutputStream(Uri.parse(uri), "wt")) {
            if (output == null) {
                throw new IOException("无法写入导出目标");
            }
            byte[] buffer = new byte[65536];
            int size;
            while ((size = input.read(buffer)) != -1) {
                output.write(buffer, 0, size);
            }
            output.flush();
        }
    }
}

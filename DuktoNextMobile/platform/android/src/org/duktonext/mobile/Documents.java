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
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;

public final class Documents {
    // 日期：2026-11-25；查询提供器元数据，虚拟文件需转换格式，当前明确拒绝而非读取错误内容。
    private static JSONObject metadata(Context context, Uri uri) throws Exception {
        if (uri == null || !"content".equals(uri.getScheme())) throw new IOException("拒绝未授权的非content文档");
        // 日期：2026-11-25；系统分享提供器未必实现DocumentsContract，按OpenableColumns查询。
        if (!DocumentsContract.isDocumentUri(context, uri)) {
            try (Cursor cursor = context.getContentResolver().query(uri,
                new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                if (cursor == null || !cursor.moveToFirst()) throw new IOException("分享提供器未返回文件信息");
                String name = cursor.getString(0);
                if (name == null || name.isEmpty() || name.contains("/") || name.contains("\\")) throw new IOException("分享文件名不安全");
                return new JSONObject().put("uri", uri.toString()).put("name", name)
                    .put("size", cursor.isNull(1) ? -1 : cursor.getLong(1)).put("modified", -1).put("directory", false);
            }
        }
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

    // 日期：2026-11-25；只允许普通子项，规范路径不一致意味着符号链接或目录越界。
    private static void validateSource(File source, String root) throws IOException {
        String canonical = source.getCanonicalPath();
        if (!canonical.equals(source.getAbsolutePath()) ||
            !(canonical.equals(root) || canonical.startsWith(root + File.separator)) ||
            (!source.isFile() && !source.isDirectory())) {
            throw new IOException("源文件不存在、为符号链接或超出导出目录");
        }
    }

    // 日期：2026-11-25；目标树禁止同名项，不覆盖用户已有内容，枚举与复制均有数量上限。
    private static Uri createNew(Context context, Uri parent, String mime, String name) throws Exception {
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(parent,
            DocumentsContract.getDocumentId(parent));
        int count = 0;
        try (Cursor cursor = context.getContentResolver().query(children,
                new String[] {DocumentsContract.Document.COLUMN_DISPLAY_NAME}, null, null, null)) {
            if (cursor == null) throw new IOException("无法读取导出目标目录");
            while (cursor.moveToNext()) {
                if (++count > 65536) throw new IOException("导出目标目录条目过多");
                if (name.equalsIgnoreCase(cursor.getString(0)))
                    throw new IOException("目标已存在同名条目：" + name);
            }
        }
        Uri result = DocumentsContract.createDocument(context.getContentResolver(), parent, mime, name);
        if (result == null) throw new IOException("无法创建导出目标：" + name);
        return result;
    }

    // 日期：2026-11-25；流式枚举且最多32层/65536项，逐项核对目标名称，拒绝提供器静默改名。
    private static void copyDirectory(Context context, File source, Uri target, String root,
                                      int depth, int[] count) throws Exception {
        validateSource(source, root);
        if (depth > 32) throw new IOException("导出目录层级超限");
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(source.toPath())) {
            HashSet<String> names = new HashSet<>();
            for (Path childPath : stream) {
                File child = childPath.toFile();
                validateSource(child, root);
                if (++count[0] > 65536) throw new IOException("导出条目超限");
                String name = child.getName();
                if (!names.add(java.text.Normalizer.normalize(name, java.text.Normalizer.Form.NFC)
                        .toLowerCase(java.util.Locale.ROOT)))
                    throw new IOException("存在跨平台同名文件：" + name);
                Uri created = DocumentsContract.createDocument(context.getContentResolver(), target,
                    child.isDirectory() ? DocumentsContract.Document.MIME_TYPE_DIR
                                        : "application/octet-stream", name);
                if (created == null || !name.equals(metadata(context, created).getString("name")))
                    throw new IOException("提供器创建失败或修改了文件名称：" + name);
                if (child.isDirectory()) copyDirectory(context, child, created, root, depth + 1, count);
                else export(context, child.getPath(), created.toString());
            }
        }
    }

    // 日期：2026-11-25；用户授权目标树后复制完整目录，失败仅尝试回滚本次新建的根目录。
    public static void exportTree(Context context, String path, String treeUri) throws Exception {
        File source = new File(path);
        String root = source.getCanonicalPath();
        validateSource(source, root);
        if (!source.isDirectory()) throw new IOException("请选择普通目录");
        Uri tree = Uri.parse(treeUri);
        Uri parent = DocumentsContract.buildDocumentUriUsingTree(tree,
            DocumentsContract.getTreeDocumentId(tree));
        Uri created = null;
        try {
            created = createNew(context, parent, DocumentsContract.Document.MIME_TYPE_DIR, source.getName());
            copyDirectory(context, source, created, root, 0, new int[] {1});
        } catch (Exception error) {
            if (created != null) {
                try {
                    if (!DocumentsContract.deleteDocument(context.getContentResolver(), created))
                        throw new IOException("提供器拒绝清理");
                } catch (Exception cleanup) {
                    throw new IOException("导出失败，目标可能留有本次创建的部分目录，请手动清理：" + source.getName(), error);
                }
            }
            throw error;
        }
    }

    // 日期：2026-11-25；向ACTION_CREATE_DOCUMENT授予的目标流式导出，不申请整个外部存储权限。
    public static void export(Context context, String path, String uri) throws Exception {
        File source = new File(path);
        String canonical = source.getCanonicalPath();
        validateSource(source, canonical);
        long expected = source.length(), modified = source.lastModified(), copied = 0;
        try (InputStream input = new FileInputStream(source);
             OutputStream output = context.getContentResolver().openOutputStream(Uri.parse(uri), "wt")) {
            if (output == null) {
                throw new IOException("无法写入导出目标");
            }
            byte[] buffer = new byte[65536];
            int size;
            while ((size = input.read(buffer)) != -1) {
                if (size > expected - copied) throw new IOException("导出期间源文件增长");
                output.write(buffer, 0, size);
                copied += size;
            }
            output.flush();
        }
        validateSource(source, canonical);
        if (copied != expected || source.length() != expected || source.lastModified() != modified)
            throw new IOException("导出期间源文件发生变化，目标可能保留部分文件");
    }
}

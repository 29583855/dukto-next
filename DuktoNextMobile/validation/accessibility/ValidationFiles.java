package org.duktonext.validation;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.FileOutputStream;

/** 日期：2026-11-26；验收专用只读提供器，覆盖真实跨包content授权和产品文件导入。 */
public final class ValidationFiles extends ContentProvider {
    /** 日期：2026-11-26；将两份固定验收资产复制到辅助包私有缓存，不访问产品沙箱。 */
    @Override
    public boolean onCreate() {
        for (String name : new String[]{"sample", "empty"}) {
            File target = new File(getContext().getCacheDir(), name);
            try (InputStream source = getContext().getAssets().open(name);
                 OutputStream output = new FileOutputStream(target)) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = source.read(buffer)) != -1) output.write(buffer, 0, count);
            } catch (IOException failure) {
                throw new IllegalStateException("Cannot prepare validation fixture", failure);
            }
        }
        return true;
    }

    /** 日期：2026-11-26；只接受两条固定URI，不允许路径遍历或任意文件读取。 */
    private File selected(Uri uri) {
        String path = uri.getPath();
        if (!"content".equals(uri.getScheme()) ||
            !"org.duktonext.validation.files".equals(uri.getAuthority()) ||
            !("/sample".equals(path) || "/empty".equals(path))) {
            throw new IllegalArgumentException("Unknown fixture URI");
        }
        return new File(getContext().getCacheDir(), path.substring(1));
    }

    /** 日期：2026-11-26；返回真实文件名与大小，使用标准OpenableColumns接口。 */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        File file = selected(uri);
        String[] columns = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME,
            OpenableColumns.SIZE} : projection;
        MatrixCursor result = new MatrixCursor(columns);
        Object[] row = new Object[columns.length];
        for (int index = 0; index < columns.length; ++index) {
            if (OpenableColumns.DISPLAY_NAME.equals(columns[index])) {
                row[index] = "sample".equals(file.getName()) ? "中文 sample.bin" : "empty zero.bin";
            } else if (OpenableColumns.SIZE.equals(columns[index])) {
                row[index] = file.length();
            }
        }
        result.addRow(row);
        return result;
    }

    /** 日期：2026-11-26；二进制样本和空文件均以普通文件共享。 */
    @Override
    public String getType(Uri uri) {
        selected(uri);
        return "application/octet-stream";
    }

    /** 日期：2026-11-26；仅允许系统授权的只读打开，不接受写入或截断模式。 */
    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read-only fixture");
        return ParcelFileDescriptor.open(selected(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    /** 日期：2026-11-26；验收资产禁止插入。 */
    @Override
    public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }

    /** 日期：2026-11-26；验收资产禁止删除。 */
    @Override
    public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }

    /** 日期：2026-11-26；验收资产禁止修改。 */
    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        throw new UnsupportedOperationException();
    }
}

"""从游戏 exe 提取图标 → `tools/assets/th06nc.ico`

为什么需要：控制台窗口的标题栏与任务栏图标要与游戏一致，而 exe 里的图标不是独立文件。
做法：`ExtractIconExW` 拿 HICON → `GetDIBits` 取 32bpp 像素 → 按 ICO 格式封装
（纯 ctypes + struct，不需要 Pillow；ICO 内部的 BMP 是 bottom-up，与 GetDIBits 的正高度一致）。

用法:
  py tools\\make_icon.py            生成 tools/assets/th06nc.ico（已存在则跳过）
  py tools\\make_icon.py --force    重新生成
控制台启动时缺图标会自动调用 `build()`；失败只保持 Tk 默认图标，不影响界面。
"""
import argparse
import ctypes
import os
import struct
import sys
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import env  # noqa: E402

ICON_PATH = os.path.join(HERE, 'assets', 'th06nc.ico')

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)   # ExtractIconEx 在 shell32，不在 user32


class ICONINFO(ctypes.Structure):
    _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD),
                ('yHotspot', wintypes.DWORD), ('hbmMask', wintypes.HBITMAP),
                ('hbmColor', wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [('bmType', wintypes.LONG), ('bmWidth', wintypes.LONG),
                ('bmHeight', wintypes.LONG), ('bmWidthBytes', wintypes.LONG),
                ('bmPlanes', wintypes.WORD), ('bmBitsPixel', wintypes.WORD),
                ('bmBits', ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]


shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HICON),
                                   ctypes.POINTER(wintypes.HICON), wintypes.UINT]
shell32.ExtractIconExW.restype = wintypes.UINT
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.DestroyIcon.argtypes = [wintypes.HICON]
gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]


def _pixels(hicon):
    """HICON → (宽, 高, bottom-up 的 BGRA 字节)，同时释放 GDI 位图"""
    info = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        raise OSError(f'GetIconInfo 失败：{ctypes.get_last_error()}')
    try:
        bm = BITMAP()
        if not gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            raise OSError('GetObject 读不到位图尺寸')
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        hdc = user32.GetDC(None)
        try:
            bi = BITMAPINFO()
            bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.bmiHeader.biWidth = w
            bi.bmiHeader.biHeight = h      # 正值 = bottom-up，正是 ICO 内部要求的顺序
            bi.bmiHeader.biPlanes = 1
            bi.bmiHeader.biBitCount = 32
            bi.bmiHeader.biCompression = 0  # BI_RGB
            buf = (ctypes.c_ubyte * (w * h * 4))()
            if not gdi32.GetDIBits(hdc, info.hbmColor, 0, h, buf, ctypes.byref(bi), 0):
                raise OSError('GetDIBits 取不到像素')
            return w, h, bytes(buf)
        finally:
            user32.ReleaseDC(None, hdc)
    finally:
        for handle in (info.hbmColor, info.hbmMask):
            if handle:
                gdi32.DeleteObject(handle)


def _ico_bytes(w, h, bgra):
    """单图像 ICO：ICONDIR + ICONDIRENTRY + BITMAPINFOHEADER(高×2) + XOR 像素 + 全零 AND 掩码"""
    mask = bytes(((w + 31) // 32) * 4 * h)      # 32bpp 图标的 AND 掩码按 alpha 忽略，留全零
    header = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0, len(bgra) + len(mask),
                         0, 0, 0, 0)
    image = header + bgra + mask
    return (struct.pack('<HHH', 0, 1, 1)                        # ICONDIR：1 个图标
            + struct.pack('<BBBBHHII', w % 256, h % 256, 0, 0, 1, 32, len(image), 22)
            + image)


def build(path=ICON_PATH, force=False, log=print):
    """提取游戏图标到 `path`；已存在且未 force 时直接返回。失败抛异常，由调用方决定是否致命"""
    if os.path.isfile(path) and not force:
        return path
    gdir, src = env.game_dir()
    exe = os.path.join(gdir, env.GAME_EXE) if gdir else None
    if not exe or not os.path.isfile(exe):
        raise FileNotFoundError(f'定位不到 {env.GAME_EXE}（{src}）')
    large, small = wintypes.HICON(), wintypes.HICON()
    n = shell32.ExtractIconExW(exe, 0, ctypes.byref(large), ctypes.byref(small), 1)
    if n < 1 or not (large or small):
        raise OSError(f'{exe} 里没有图标资源')
    try:
        w, h, bgra = _pixels(large or small)
    finally:
        for handle in (large, small):
            if handle:
                user32.DestroyIcon(handle)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(_ico_bytes(w, h, bgra))
    log(f'✓ 已提取游戏图标 {w}×{h} → {os.path.relpath(path, os.path.dirname(HERE))}')
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='已存在也重新提取')
    args = ap.parse_args()
    try:
        path = build(force=args.force)
    except Exception as e:
        print(f'✗ {type(e).__name__}: {e}')
        return 1
    print(f'图标就绪：{path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

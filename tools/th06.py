"""
th06nc 综合工具库：输入模拟 + 内存扫描
- SendInput 用扫描码发送，兼容 GetAsyncKeyState / RawInput
"""
import ctypes
from ctypes import wintypes
import struct
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winmem import (find_pids, Process, find_windows, set_foreground,
                    PAGE_READWRITE, PAGE_EXECUTE_READWRITE, PAGE_WRITECOPY,
                    PAGE_EXECUTE_WRITECOPY, MEM_PRIVATE, MEM_IMAGE, MEM_MAPPED)

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# ---------------- SendInput ----------------
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# 注入键的标记（'th06d'）——写在 KEYBDINPUT.dwExtraInfo 上。
# 低级键盘钩子那边既看 LLKHF_INJECTED 位、也看这个标记，双判据认出「脚本自己发的键」，
# 免得玩家让位机制被自己的按键触发。改这里等于改「哪些键不算人按的」。
INJECT_TAG = 0x74683664


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_void_p)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                ('wParamH', wintypes.WORD)]


class _INPUTunion(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _INPUTunion)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

# 扫描码表 (Set 1)
SCAN = {
    'esc': 0x01, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05, '5': 0x06,
    '6': 0x07, '7': 0x08, '8': 0x09, '9': 0x0A, '0': 0x0B,
    'q': 0x10, 'w': 0x11, 'e': 0x12, 'r': 0x13, 't': 0x14, 'y': 0x15,
    'u': 0x16, 'i': 0x17, 'o': 0x18, 'p': 0x19,
    'a': 0x1E, 's': 0x1F, 'd': 0x20, 'f': 0x21, 'g': 0x22, 'h': 0x23,
    'j': 0x24, 'k': 0x25, 'l': 0x26,
    'z': 0x2C, 'x': 0x2D, 'c': 0x2E, 'v': 0x2F, 'b': 0x30, 'n': 0x31,
    'm': 0x32,
    'enter': 0x1C, 'space': 0x39, 'shift': 0x2A, 'ctrl': 0x1D, 'alt': 0x38,
    'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D,
    'tab': 0x0F, 'backspace': 0x0E,
}
EXTENDED = {'up', 'down', 'left', 'right'}


def _make_input(scan, up=False, extended=False):
    ki = KEYBDINPUT()
    ki.wVk = 0
    ki.wScan = scan
    ki.dwFlags = KEYEVENTF_SCANCODE
    if extended:
        ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    if up:
        ki.dwFlags |= KEYEVENTF_KEYUP
    ki.time = 0
    ki.dwExtraInfo = INJECT_TAG
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki = ki
    return inp


def key_down(name):
    s = SCAN[name]
    inp = _make_input(s, up=False, extended=name in EXTENDED)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_up(name):
    s = SCAN[name]
    inp = _make_input(s, up=True, extended=name in EXTENDED)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap(name, ms=60):
    """按一下"""
    key_down(name)
    time.sleep(ms / 1000.0)
    key_up(name)


def _focus_game(pid):
    w = find_windows(pid=pid, title_sub='Embodiment')
    if w:
        set_foreground(w[0][0])
        return w[0][0]
    return None


def game_input(pid, actions):
    """actions: [('down','left'), ('sleep',0.5), ('up','left'), ('tap','z')]"""
    _focus_game(pid)
    time.sleep(0.05)
    for a in actions:
        if a[0] == 'down':
            key_down(a[1])
        elif a[0] == 'up':
            key_up(a[1])
        elif a[0] == 'tap':
            tap(a[1], a[2] if len(a) > 2 else 60)
        elif a[0] == 'sleep':
            time.sleep(a[1])


# ---------------- 内存扫描 ----------------
def get_proc(write=False):
    pids = find_pids('th06nc')
    if not pids:
        raise RuntimeError('游戏未运行')
    return Process(pids[0], write=write), pids[0]


def data_regions(p, include_heap=True, include_image=True):
    """返回候选扫描区域 [(base, size)]"""
    out = []
    for base, size, prot, typ in p.regions(min_size=0x1000, include_image=True):
        if prot not in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                        PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY):
            continue
        if typ == MEM_MAPPED:
            continue
        out.append((base, size, typ))
    if not include_image:
        out = [r for r in out if r[2] != MEM_IMAGE]
    if not include_heap:
        out = [r for r in out if r[2] == MEM_IMAGE]
    return out


def scan_floats(p, regions, lo, hi, align=4):
    """扫描区域内的 float，返回 {addr: value}（值在 [lo, hi]）"""
    hits = {}
    for base, size, typ in regions:
        chunk = 0x100000
        off = 0
        while off < size:
            n = min(chunk, size - off)
            data = p.read(base + off, n)
            if data is None:
                off += n
                continue
            m = len(data) // 4
            vals = struct.unpack('<%df' % m, data[:m * 4])
            for i, v in enumerate(vals):
                if lo <= v <= hi:
                    hits[base + off + i * 4] = v
            off += n
    return hits


imm32 = ctypes.WinDLL('imm32', use_last_error=True)
imm32.ImmAssociateContext.argtypes = [wintypes.HWND, ctypes.c_void_p]
imm32.ImmAssociateContext.restype = ctypes.c_void_p


class ime_disabled:
    """临时禁用目标窗口的 IME。

    游戏用 DirectInput 读扫描码，IME 不拦游戏；
    但中文输入法会弹候选框挡住画面，长按字母键时尤其明显。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.old = None

    def __enter__(self):
        self.old = imm32.ImmAssociateContext(self.hwnd, None)
        return self

    def __exit__(self, *exc):
        if self.old:
            imm32.ImmAssociateContext(self.hwnd, self.old)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'info'
    p, pid = get_proc()
    if cmd == 'info':
        w = find_windows(pid=pid)
        for x in w:
            print(x)
    elif cmd == 'focus':
        print('focus ->', _focus_game(pid))
    elif cmd == 'tap':
        _focus_game(pid)
        time.sleep(0.1)
        tap(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60)
        print('tapped', sys.argv[2])
    p.close()

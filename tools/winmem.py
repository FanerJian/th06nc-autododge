"""
Win32 内存读写基础库 (Python ctypes, 无第三方依赖)
用于对 th06nc.exe 做外部内存分析与输入模拟。
"""
import ctypes
from ctypes import wintypes
import struct
import sys
import threading

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)

# ---- 访问权限 ----
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020

MEM_COMMIT = 0x1000
MEM_IMAGE = 0x1000000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000

PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80

TH32CS_SNAPPROCESS = 0x00000002

READABLE = (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
            PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.c_ulonglong),
        ('AllocationBase', ctypes.c_ulonglong),
        ('AllocationProtect', wintypes.DWORD),
        ('__alignment1', wintypes.DWORD),
        ('RegionSize', ctypes.c_ulonglong),
        ('State', wintypes.DWORD),
        ('Protect', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('__alignment2', wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),
    ]


kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def find_pids(name):
    """按进程名查找 PID（不区分大小写，可省略 .exe）"""
    name = name.lower()
    if not name.endswith('.exe'):
        name += '.exe'
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        pids = []
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name:
                pids.append(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return pids
    finally:
        kernel32.CloseHandle(snap)


class MemoryReadError(RuntimeError):
    """目标内存读不到：进程已退出 / 页面不可访问 / 短读

    `read()` 只返回"恰好 size 字节"或 None，调用者不必自己判长度；
    读到的是 None 还是合法的 (0, 0)，必须分得清 —— 否则躲避会拿 (0,0) 当自机位置。
    """


class Process:
    def __init__(self, pid, write=False):
        self.pid = pid
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if write:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self.handle = kernel32.OpenProcess(access, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'OpenProcess 失败 (需要与游戏同权限运行)')
        self._buf = ctypes.create_string_buffer(0x100000)  # 1MB 复用缓冲
        self._lock = threading.Lock()                      # 缓冲是共享状态，理由见 read()

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read(self, addr, size):
        """读取内存：**只返回恰好 size 字节，或 None**

        两条硬约束，改这里之前先读 `PITFALLS.md`：
        1. **必须加锁**：`_buf` 是复用的共享缓冲，GUI 主线程（状态刷新）与躲避线程
           用同一个 Process，不加锁实测 33% 长度错位。
        2. **短读一律判失败**：把残缺字节交给调用者，上层就崩在 `struct.unpack` 上
           （实战症状：`unpack requires a buffer of 4 bytes`）。
        """
        with self._lock:
            buf = self._buf if size <= len(self._buf) else ctypes.create_string_buffer(size)
            n = ctypes.c_size_t(0)
            if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr),
                                              buf, size, ctypes.byref(n)):
                return None
            if n.value != size:
                return None
            return buf.raw[:size]

    def write(self, addr, data):
        n = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr),
                                         data, len(data), ctypes.byref(n))
        return bool(ok)

    def read_f32(self, addr):
        d = self.read(addr, 4)
        return struct.unpack('<f', d)[0] if d and len(d) == 4 else None

    def read_f64(self, addr):
        d = self.read(addr, 8)
        return struct.unpack('<d', d)[0] if d and len(d) == 8 else None

    def read_u32(self, addr):
        d = self.read(addr, 4)
        return struct.unpack('<I', d)[0] if d and len(d) == 4 else None

    def read_u64(self, addr):
        d = self.read(addr, 8)
        return struct.unpack('<Q', d)[0] if d and len(d) == 8 else None

    def regions(self, min_size=0x1000, include_image=True):
        """枚举所有已提交且可读的内存区域 -> [(base, size, protect, type)]"""
        out = []
        mbi = MEMORY_BASIC_INFORMATION64()
        addr = 0
        max_addr = 0x7FFFFFFF0000
        while addr < max_addr:
            r = kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr),
                                        ctypes.byref(mbi), ctypes.sizeof(mbi))
            if r == 0:
                break
            base = mbi.BaseAddress
            size = mbi.RegionSize
            if size == 0:
                break
            if (mbi.State == MEM_COMMIT and (mbi.Protect & READABLE)
                    and not (mbi.Protect & PAGE_GUARD) and size >= min_size):
                if include_image or mbi.Type != MEM_IMAGE:
                    out.append((base, size, mbi.Protect, mbi.Type))
            addr = base + size
        return out

    def modules(self):
        """枚举模块 -> {name: (base, size)}  需要 psutil 或手工解析 PEB，这里用简单办法"""
        raise NotImplementedError


def module_base(pid, dllname):
    """取模块基址：用 CreateToolhelp32Snapshot 的 module 快照"""
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('th32ModuleID', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('GlblcntUsage', wintypes.DWORD),
            ('ProclntUsage', wintypes.DWORD),
            ('modBaseAddr', ctypes.c_void_p),
            ('modBaseSize', wintypes.DWORD),
            ('hModule', wintypes.HMODULE),
            ('szModule', ctypes.c_wchar * 256),
            ('szExePath', ctypes.c_wchar * 260),
        ]
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == -1:
        return None
    try:
        me = MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            if me.szModule.lower() == dllname.lower():
                return (me.modBaseAddr or 0, me.modBaseSize)
            ok = kernel32.Module32NextW(snap, ctypes.byref(me))
        return None
    finally:
        kernel32.CloseHandle(snap)


def process_path(pid):
    """取进程 exe 的完整路径（定位游戏目录用）；失败返回 None

    用 QUERY_LIMITED_INFORMATION：比 Process 的 QUERY_INFORMATION 更容易拿到，
    不需要读内存权限。
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(h)


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def find_windows(pid=None, title_sub=None, visible_only=True):
    """枚举顶层窗口 -> [(hwnd, pid, title, class, rect)]"""
    out = []

    def cb(hwnd, lparam):
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if pid is not None and wpid.value != pid:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if title_sub and title_sub.lower() not in buf.value.lower():
            return True
        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        out.append((hwnd, wpid.value, buf.value, cls.value,
                    (rc.left, rc.top, rc.right, rc.bottom)))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def game_window(pid, title_sub='Embodiment'):
    """找到游戏主窗口 hwnd"""
    ws = find_windows(pid=pid, title_sub=title_sub)
    if not ws:
        ws = [w for w in find_windows(pid=pid) if w[3] != 'ConsoleWindowClass']
    return ws[0] if ws else None


def set_foreground(hwnd):
    """尽量把窗口切到前台（绕过前台锁）"""
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True
    # 备用：附加到前台线程的输入队列
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.AttachThreadInput(cur_tid, tgt_tid, True)
    ok = user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_tid, fg_tid, False)
    user32.AttachThreadInput(cur_tid, tgt_tid, False)
    return bool(ok)


def move_window(hwnd, x, y, w, h):
    """移动/缩放窗口"""
    SWP_NOZORDER = 0x0004
    SWP_SHOWWINDOW = 0x0040
    return bool(user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW))


if __name__ == '__main__':
    import time
    pids = find_pids('th06nc')
    print('th06nc PID:', pids)
    if not pids:
        sys.exit(1)
    with Process(pids[0], write=False) as p:
        regs = p.regions(include_image=True)
        total = sum(r[1] for r in regs)
        print(f'可读内存区域: {len(regs)}, 合计 {total/1024/1024:.1f} MB')
        for base, size, prot, typ in regs[:10]:
            print(f'  0x{base:012X} size=0x{size:<9X} prot=0x{prot:02X} type=0x{typ:X}')
        print('  ...')
        print('主模块基址:', hex(module_base(pids[0], 'th06nc.exe')[0]))
        print('窗口:', find_windows(pids[0]))

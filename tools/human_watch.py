"""玩家操作检测 —— 低级键盘钩子，只认「真实硬件按键」

为什么非要用钩子：`SendInput` 注入的按键同样会进系统键状态表，`GetAsyncKeyState`
分不出「脚本按的」和「人按的」。低级键盘钩子的 `KBDLLHOOKSTRUCT.flags` 带
`LLKHF_INJECTED` 位 —— 注入键有这个位、真实按键没有。这是唯一可靠的区分点，
让位机制（人一上手，脚本就停手）全靠它。

边界：只在**本进程**装钩子做只读监听，不注入、不改游戏文件、不屏蔽任何按键
（回调末尾照常 `CallNextHookEx` 放行）。

用法:
  py tools\\human_watch.py --seconds 8     # 自测：8 秒内打印真实按键；
                                           # 它自己发的 key_down 必须不出现在列表里
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06  # 键名表复用发键一侧的 SCAN，两边别各写一份

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
LLKHF_INJECTED = 0x10
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

SCAN_TO_NAME = {v: k for k, v in th06.SCAN.items()}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_void_p)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                     wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
# 不设 restype 的话句柄会被当 c_int 截成 32 位 —— SetWindowsHookExW 收到无效 hMod 直接失败
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class HumanWatch:
    """在后台线程装 WH_KEYBOARD_LL，记录「人按了键」这件事

    对外两个判据：
      · `active(idle)`  —— 最近 idle 秒内有真实按键（人刚动过手）
      · `physical()`    —— 此刻仍被物理按住的键（人还按着不放）
    让位条件是「二者之一」：只看时间窗的话，人一直按着方向键时脚本会在几秒后
    把手柄抢回来 —— 那正是最不该抢的时刻。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0                 # 最后一次真实按键的单调时刻（0 = 还没动过手）
        self._down = set()               # 人此刻按住的键名（只记 th06.SCAN 认识的键）
        self._count = 0                  # 累计真实按键次数（诊断用）
        self._injected = 0               # 累计被判为注入的按键事件（诊断用）
        self._hook = None
        self._tid = 0
        self._proc = HOOKPROC(self._callback)   # 必须留引用：回调被 GC 会当场崩
        self._thread = None
        self.error = None

    # ---------- 生命周期 ----------
    def start(self, timeout=1.5):
        """装钩子；返回是否装成功（失败不致命 —— 让位功能失效而已，躲避照跑）"""
        if self._thread is not None:
            return self._hook is not None
        self._thread = threading.Thread(target=self._loop, name='human-watch', daemon=True)
        self._thread.start()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if self._hook or self.error:
                break
            time.sleep(0.01)
        return self._hook is not None

    def stop(self):
        hook, tid = self._hook, self._tid
        self._hook = None
        if hook:
            user32.UnhookWindowsHookEx(hook)      # 钩子一撤，GetMessage 循环随即退出
        if tid:
            user32.PostThreadMessageW(tid, 0x0012, 0, 0)   # WM_QUIT
        self._thread = None

    def _loop(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                              kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self.error = ctypes.get_last_error()
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _callback(self, n_code, w_param, l_param):
        """钩子回调：只做几个赋值就放行 —— 超时（默认 300ms）会被系统摘掉钩子"""
        if n_code == HC_ACTION:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # 双判据认注入键：系统给的 LLKHF_INJECTED 位 + 我们自己写的 dwExtraInfo 标记
            injected = bool(kb.flags & LLKHF_INJECTED) or (kb.dwExtraInfo or 0) == th06.INJECT_TAG
            down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            with self._lock:
                if injected:
                    # 也数一遍：自测靠它证明「钩子确实在收事件」——
                    # 否则「注入键没被算成真实按键」既可能是过滤对了，也可能是钩子压根没工作
                    self._injected += 1
                else:
                    self._last = time.perf_counter()
                    self._count += 1
                    name = SCAN_TO_NAME.get(kb.scanCode & 0xFF)
                    if name:
                        self._down.add(name) if down else self._down.discard(name)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    # ---------- 判据 ----------
    def active(self, idle=2.0):
        with self._lock:
            return self._last > 0.0 and (time.perf_counter() - self._last) < idle

    def physical(self):
        with self._lock:
            return set(self._down)

    def yielding(self, idle=2.0):
        """该让位吗 —— 刚动过手，或此刻还按着键"""
        with self._lock:
            if self._down:
                return True
            return self._last > 0.0 and (time.perf_counter() - self._last) < idle

    def snapshot(self):
        with self._lock:
            return self._count, self._last, set(self._down)

    def injected_count(self):
        with self._lock:
            return self._injected


def main():
    seconds = 8.0
    if '--seconds' in sys.argv:
        seconds = float(sys.argv[sys.argv.index('--seconds') + 1])
    w = HumanWatch()
    if not w.start():
        print(f'✗ 钩子安装失败（err={w.error}）—— 让位功能不可用')
        return 1
    print(f'已装键盘钩子，观察 {seconds:.0f} 秒。')
    print('请按键（方向 / Z / X …）。')
    # 注入测试：脚本自己发的键绝不能被算成「人按的」，否则让位会被自己触发。
    # 只发方向键 —— 万一前台不是游戏，方向键不会往别人窗口里打字。
    time.sleep(0.8)
    n0 = w.snapshot()[0]
    th06.key_down('right')
    time.sleep(0.25)
    th06.key_up('right')
    time.sleep(0.25)
    n1 = w.snapshot()[0]
    inj = w.injected_count()
    bad = False
    if inj == 0:
        print('✗ 钩子一个键盘事件都没收到（连脚本自己发的都没收到）—— 钩子没在工作，'
              '让位永远不会触发')
        bad = True
    elif n1 != n0:
        print(f'✗ 注入测试失败：脚本自己发的键被算成了「人按的」（{n0} → {n1}）'
              '—— 让位会被自己触发，必须修')
        bad = True
    else:
        print(f'✓ 钩子在工作（收到 {inj} 个注入事件、0 个真实按键）：'
              '脚本自己发的键不会被算成「人按的」')
    t0 = time.perf_counter()
    last = n1
    while time.perf_counter() - t0 < seconds:
        n, _, down = w.snapshot()
        if n != last:
            last = n
            print(f'  [{time.perf_counter() - t0:5.1f}s] 真实按键累计 {n} 次，'
                  f'此刻按住 {sorted(down) or "无"}，让位中={w.yielding(2.0)}')
        time.sleep(0.1)
    n, _, down = w.snapshot()
    print(f'合计真实按键 {n} 次；此刻仍按住 {sorted(down) or "无"}')
    if n == n1:
        print('（观察期内没读到真实按键 —— 钩子链路已由上面的注入事件证明；'
              '若你刚才确实按了键，那就是没读到，让位会失效）')
    else:
        print(f'✓ 钩子收到了 {n - n1} 次真实按键，让位可用')
    w.stop()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

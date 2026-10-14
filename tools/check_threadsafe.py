"""并发读取回归检查 —— 多线程同时读同一个 Process 必须零失败

为什么留着：GUI 的主线程（refresh_status）与躲避线程共用同一个 Process。
`Process.read` 复用一块 1MB 缓冲**和返回长度**，不加锁时实测 33% 长度错位 ——
上层表现为 `SCENE_None` / 「读取失败」，实战中自机全程不动被打死。
改动 `winmem.py` 的读取路径后跑一遍。

用法:
  py tools\\check_threadsafe.py      # 需游戏在运行（只读，不发按键）
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06  # noqa: E402
from offsets import BM_RVA, BULLETS_OFF, BULLET_BLOCK, CUR_STATE  # noqa: E402
from winmem import module_base  # noqa: E402

BLOCK = BULLET_BLOCK         # 1,003,520 B < 1MB 复用缓冲 -> 走共享路径

p, pid = th06.get_proc()
mb = module_base(pid, 'th06nc.exe')[0]
print(f'PID {pid}  基址 0x{mb:X}  （只读实验，不发任何按键）')

errors = []
small_n = big_n = 0
lock = threading.Lock()

SMALL_ITERS, BIG_ITERS = 4000, 800


def reader_small():
    global small_n
    for _ in range(SMALL_ITERS):
        d = p.read(mb + CUR_STATE, 4)
        with lock:
            small_n += 1
            if not d or len(d) != 4:
                errors.append(('小读(cur_state, 4B)', None if d is None else len(d)))


def reader_big():
    global big_n
    for _ in range(BIG_ITERS):
        d = p.read(mb + BM_RVA + BULLETS_OFF, BLOCK)
        with lock:
            big_n += 1
            if not d or len(d) != BLOCK:
                errors.append(('大读(子弹池, %d B)' % BLOCK, None if d is None else len(d)))


t1 = threading.Thread(target=reader_small)
t2 = threading.Thread(target=reader_big)
t1.start(); t2.start()
t1.join(); t2.join()

total = small_n + big_n
print(f'小读 {small_n} 次 / 大读 {big_n} 次，合计 {total}')
print(f'长度异常 {len(errors)} 次  =  {len(errors) / total * 100:.2f}%')
for tag, got in errors[:6]:
    print(f'  失败 {tag} -> 实际 {got}')
print('\n判定：' + ('线程安全 通过' if not errors else '存在竞争 失败'))
p.close()
sys.exit(0 if not errors else 1)

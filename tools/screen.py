"""读取 th06nc 当前所在画面 —— 比 Scene 细的判据（全部本机实测）

为什么需要：`Scene` 区分不了画面 —— `1` 覆盖标题/主菜单/难度/角色/御札/模式
全部菜单，`2` 同时覆盖"关卡中"和"Continue 画面"。只按 Scene 判态会导致脚本
在 Continue 画面上发方向键，把「是」拨到「否」，一局直接作废。

地址依据见 `项目文档/02-内存布局/相关-游戏内存映射-MEMMAP.md` §7。
`STAGE_SWITCH`（curState=3）是关卡之间的过渡态，依据见 MEMMAP §8。

用法:
  py tools\\screen.py            # 打印一次
  py tools\\screen.py 10         # 连续打印 10 次（看画面切换）
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BOMBS, CALC_COUNT, CUR_STATE, DEATHS, DYING, LIVES, RETRY,
                     WANT_STATE)
from winmem import module_base

# 地址全部集中在 offsets.py（本文件对应 MEMMAP §7/§8 的判据）

SCENE = {0: 'INIT', 1: 'MAINMENU', 2: 'GAMEMANAGER', 3: 'GAMEMANAGER_REINIT',
         4: 'EXITSUCCESS', 5: 'EXITERROR', 6: 'RESULTSCREEN',
         7: 'RESULTSCREEN_FROMGAME', 8: 'MAINMENU_REPLAY', 9: 'MUSICROOM',
         10: 'ENDING'}


def _i32(p, mb, a):
    d = p.read(mb + a, 4)
    return struct.unpack('<i', d)[0] if d and len(d) == 4 else None


def _u8(p, mb, a):
    d = p.read(mb + a, 1)
    return d[0] if d else None


def read_state(p, mb):
    return {
        'cur_state': _i32(p, mb, CUR_STATE),
        'wanted_state': _i32(p, mb, WANT_STATE),
        'calc_count': _u8(p, mb, CALC_COUNT),
        'lives': _u8(p, mb, LIVES),
        'bombs': _u8(p, mb, BOMBS),
        'retry': _u8(p, mb, RETRY),
        'deaths': _i32(p, mb, DEATHS),
        'dying': _u8(p, mb, DYING),
    }


def is_running(p, mb, gap=0.12):
    """帧计数是否在走 —— 暂停/最小化时游戏逻辑冻结，这个计数器不动"""
    a = _u8(p, mb, CALC_COUNT)
    time.sleep(gap)
    b = _u8(p, mb, CALC_COUNT)
    return a is not None and b is not None and b != a


def screen_of(s, running=None):
    """返回 (代号, 中文说明, 能否安全发方向键)"""
    cs = s['cur_state']
    if cs == 2:
        if s['retry'] == 0xFF:
            # isInRetryMenu：Player__OnUpdate 里 `mov byte [0x549D42], 0xff`（RVA 0x6A430，
            # 原版 Player.cpp:247）。**两种菜单共用这一位** —— 普通关卡的 Continue，
            # 与符卡练习失败后的 "Failed..."（返回符卡选择 / 保存Replay / 重试）。
            # 两者都不能发方向键（会把光标拨走），区别只在按 Z 之后发生什么。
            return 'CONTINUE', '失败菜单（Continue 或符卡失败）：绝不能发送方向键', False
        if s['dying']:
            return 'DYING', '关卡中，自机死亡中', False
        if running is False:
            return 'PAUSED', '关卡中，已暂停（游戏逻辑冻结）', False
        if s['lives'] == 0:
            # 残机是**备用命**：0 只表示没有后备，最后一条命还在打 —— 照常避弹，不是退出条件。
            # 安全靠两处保证：死亡中判 DYING（结算完就松键退出）、Continue 画面判 CONTINUE。
            # 顺序要紧：dying 必须在它前面，否则残机 0 时被打中会连死亡炸弹窗口一起丢掉。
            return 'NO_LIVES', '关卡中，残机 0（最后一条命）：照常避弹', True
        return 'IN_GAME', '关卡进行中', True
    if cs == 3:
        # 关卡结束 → 下一关的过渡态（原版 Gui.cpp MSG_OPCODE_STAGEEND 把 curState 设成
        # SUPERVISOR_STATE_GAMEMANAGER_REINIT，GameManager::AddedCallback 里 currentStage++）。
        # 这段是**自动**推进的，不需要按键 —— 脚本只要别在这里退出、也别按键。
        return 'STAGE_SWITCH', '关卡切换中（正在载入下一关）：等待，不发送按键', False
    if cs == 1:
        return 'MENU', '主菜单系（标题、难度、角色、御札、模式无法再区分）', False
    if cs in (0, 12):
        # 0 = 原版枚举的 INIT，12 = 新典自加的（原版枚举止于 10）—— 两者都是
        # 「重开一张符卡 / 载入下一个场景」的中间态，实测各只持续 1~2 帧。
        # 判成未知场景会让脚本每重试一次就退出：先在 12 上踩了一次，
        # 补完 12 又在 0 上踩（同一局连踩两次，见 PITFALLS）。
        return 'RELOAD', '场景重载中（重开符卡或载入）：等待，不发送按键', False
    if cs in (6, 7):
        return 'RESULT', '结算画面', False
    return f'SCENE_{cs}', SCENE.get(cs, '未知场景'), False


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}')
    for k in range(n):
        s = read_state(p, mb)
        running = is_running(p, mb)
        code, desc, ok = screen_of(s, running)
        print(f'\n[{k}] {code:<9} {desc}')
        print(f'     curState={s["cur_state"]}({SCENE.get(s["cur_state"], "?")}) '
              f'wanted={s["wanted_state"]}  帧计数={s["calc_count"]} '
              f'运行中={"是" if running else "否"}')
        print(f'     Lives={s["lives"]} Bombs={s["bombs"]} 0x4FF0F2={s["retry"]} '
              f'deaths={s["deaths"]} dying={s["dying"]}  发方向键={"可以" if ok else "禁止"}')
        if n > 1:
            time.sleep(0.4)
    p.close()


if __name__ == '__main__':
    main()

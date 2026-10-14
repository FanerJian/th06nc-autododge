"""按游戏构建解析内存地址 —— 游戏更新后不必再改源码

为什么要这一层：`offsets.py` 把全局变量地址写死在源码里，Steam 每次更新游戏
它们全部失效（2026-09-24 那次就让整套避弹报废）。但实测多次更新对比证明：
**结构偏移、池 stride、槽数从来没变过**，变的只是全局变量的位置。
所以地址可以从源码里搬出来，按 exe MD5 存在缓存里，由本模块在 import 时套用。

用法（offsets.py 末尾自动调用，其它模块不用管）：
    import addr
    addr.apply_overrides(globals())      # 只在缓存命中时改值，否则保持基线

状态查询：
    py tools\\addr.py            # 打印当前构建的解析情况
"""
import hashlib
import json
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths  # noqa: E402

# 读：exe 旁的副本优先（autofix 更新的是它），缺失时回退包内基线；写：永远写外部副本
CACHE, CACHE_WRITE = paths.external_first('addr_cache.json', 'tools', 'addr_cache.json')

BASE_MD5 = 'b0cc28ec904e9efce2439ad857c938b5'   # offsets.py 里地址所依据的构建

# 只覆盖这些**随构建变**的全局地址；结构偏移 / stride / 场地几何一律不动
ADDR_NAMES = (
    'PLAYER_BASE', 'PLAYER_X', 'PLAYER_Y', 'PLAYER_HITBOX',
    'LIVES', 'BOMBS', 'RETRY', 'POWER', 'DEATHS', 'DYING', 'NATIVE_TIME',
    'INPUT', 'GUI', 'CUR_STATE', 'WANT_STATE', 'CALC_COUNT',
    'BM_RVA', 'EM_RVA', 'IM_RVA', 'ITEM_NEXT_IDX',
)

_md5_cache = None
_resolved = None          # 缓存里当前构建的条目；None = 还没查过


def game_md5():
    """当前游戏 exe 的 MD5；找不到游戏时返回 None（不抛异常，诊断脚本也要能跑）"""
    global _md5_cache
    if _md5_cache is not None:
        return _md5_cache
    path = None
    env_dir = os.environ.get('TH06NC_DIR')
    if env_dir:
        cand = os.path.join(env_dir, 'th06nc.exe')
        if os.path.isfile(cand):
            path = cand
    if path is None:
        try:
            from winmem import find_pids, process_path
            for pid in find_pids('th06nc.exe'):
                p = process_path(pid)
                if p and os.path.isfile(p):
                    path = p
                    break
        except Exception:
            pass
    if path is None:
        try:
            import env
            d, _ = env.game_dir()
            if d:
                cand = os.path.join(d, 'th06nc.exe')
                if os.path.isfile(cand):
                    path = cand
        except Exception:
            pass
    if path is None:
        _md5_cache = ''
        return None
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    _md5_cache = h.hexdigest()
    return _md5_cache


def load_cache():
    """读 addr_cache.json -> dict；缺失或损坏时返回 {}（绝不因此让主程序起不来）"""
    try:
        with open(CACHE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def entries_for(md5):
    """取该构建的地址条目 {名字: {'rva': int, ...}}；没有则 None"""
    if not md5:
        return None
    node = load_cache().get(md5)
    if not isinstance(node, dict):
        return None
    out = {}
    for name, rec in (node.get('entries') or {}).items():
        try:
            out[name] = dict(rec, rva=int(str(rec['rva']), 0))
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def resolve():
    """返回 (md5, entries)，entries 为 None 表示该构建还没适配过"""
    global _resolved
    if _resolved is None:
        md5 = game_md5()
        _resolved = (md5, entries_for(md5))
    return _resolved


def apply_overrides(ns):
    """把缓存里当前构建的地址套进命名空间（通常是 offsets 模块的 globals()）

    只覆盖 ADDR_NAMES 里、且缓存里确实有记录的项；其余保持基线值。
    返回实际改动的 {名字: (旧值, 新值)}，供调用方打印/自检。
    """
    _, entries = resolve()
    if not entries:
        return {}
    changed = {}
    for name, rec in entries.items():
        if name not in ADDR_NAMES or name not in ns:
            continue
        old, new = ns.get(name), rec['rva']
        if isinstance(old, int) and old != new:
            ns[name] = new
            changed[name] = (old, new)
        elif old is None:
            ns[name] = new
            changed[name] = (None, new)
    return changed


def status():
    """给 env.check / launcher 用的一行状态"""
    md5, entries = resolve()
    if not md5:
        return 'warn', '找不到 th06nc.exe —— 无法确认地址是否适配当前构建'
    if entries is None:
        if md5 == BASE_MD5:
            return 'ok', f'构建 {md5[:12]}… 与 offsets.py 基线一致'
        return 'bad', (f'构建 {md5[:12]}… 未适配（基线 {BASE_MD5[:12]}…）'
                       ' —— 地址会读错内存；跑 py tools\\autofix.py 自动重定位')
    n = len(entries)
    unver = [k for k, v in entries.items() if v.get('confidence') != 'verified']
    if unver:
        return 'warn', (f'构建 {md5[:12]}… 已适配 {n} 个地址，'
                        f'其中 {len(unver)} 个未经运行时验证：{", ".join(unver[:6])}')
    return 'ok', f'构建 {md5[:12]}… 已适配并验证 {n} 个地址'


def main():
    md5, entries = resolve()
    print(f'addr_cache: {CACHE}')
    print(f'基线构建  : {BASE_MD5}')
    print(f'当前构建  : {md5 or "（找不到游戏 exe）"}')
    level, text = status()
    print(f'状态      : [{level}] {text}\n')
    if not entries:
        return 0
    print(f'{"变量":<16}{"RVA":>12}  {"置信度":<10} 依据')
    print('-' * 78)
    for name in ADDR_NAMES:
        rec = entries.get(name)
        if not rec:
            print(f'{name:<16}{"—":>12}  {"缺失":<10} 缓存里没有，用基线值（多半已失效）')
            continue
        print(f'{name:<16}0x{rec["rva"]:08X}  {rec.get("confidence", "?"):<10} '
              f'{rec.get("how", "")}')
    return 0


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    sys.exit(main())

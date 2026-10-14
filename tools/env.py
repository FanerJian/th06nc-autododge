"""外部环境定位与自检 —— 换设备后只有这里需要重新解析

为什么单独一个文件：Steam 装在哪、游戏装在哪、游戏是哪个构建 —— 三者都随设备变。
写死在代码里换台机器就废；集中在这里探测，其余模块只 import 结果。

探测顺序（前一个失败才试下一个）：
  Steam  ：环境变量 TH06NC_STEAM → 注册表 → 常见安装路径
  游戏目录：环境变量 TH06NC_DIR → 运行中的进程路径 → Steam 库扫描

覆盖方式（自动探测失败时）：
  set TH06NC_STEAM=D:\\steam\\steam.exe
  set TH06NC_DIR=D:\\steam\\steamapps\\common\\th06nc

用法:
  py tools\\env.py            # 打印环境自检清单
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winmem import find_pids, process_path  # noqa: E402

APPID = '4659620'                    # Steam AppID，游戏标识，不随设备变
GAME_EXE = 'th06nc.exe'
GAME_DIR_NAME = 'th06nc'
# 地址与结构偏移（offsets.py / MEMMAP）只对这个构建有效。
# 游戏一更新它就对不上 —— 但**别急着重新逆向**：实测两次构建变更对比证明，
# 结构定义（池 stride / 槽数 / 结构内字段偏移）从来没变过，变的只是全局变量的位置，
# 所以 `py tools\relocate.py` 按特征就能重新定位。完整步骤见 main() 的告警文案。
KNOWN_MD5 = 'b0cc28ec904e9efce2439ad857c938b5'
MIN_PY = (3, 8)

_COMMON_STEAM = [
    r'C:\Program Files (x86)\Steam\steam.exe', r'C:\Program Files\Steam\steam.exe',
    r'C:\Steam\steam.exe', r'D:\steam\steam.exe', r'D:\Steam\steam.exe',
    r'E:\steam\steam.exe',
]

_steam_cache = None
_game_cache = None


def _registry_steam():
    """注册表里的 Steam 位置；注册表用的是正斜杠（d:/steam）"""
    import winreg
    keys = [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamExe'),
            (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')]
    out = []
    for root, key, value in keys:
        try:
            with winreg.OpenKey(root, key) as k:
                v = os.path.normpath(str(winreg.QueryValueEx(k, value)[0]))
        except OSError:
            continue
        out.append(v if v.lower().endswith('.exe') else os.path.join(v, 'steam.exe'))
    return out


def steam_exe():
    """返回 (steam.exe 路径, 来源说明)；找不到时路径为 None"""
    global _steam_cache
    if _steam_cache is not None:
        return _steam_cache
    cands = [(os.environ.get('TH06NC_STEAM'), '环境变量 TH06NC_STEAM')]
    cands += [(p, '注册表') for p in _registry_steam()]
    cands += [(p, '常见安装路径') for p in _COMMON_STEAM]
    for path, src in cands:
        if path and os.path.isfile(path):
            _steam_cache = (path, src)
            return _steam_cache
    _steam_cache = (None, '未找到（设 TH06NC_STEAM 指定）')
    return _steam_cache


def _steam_libraries(steam_root):
    """解析 steamapps/libraryfolders.vdf 得到所有库根目录"""
    vdf = os.path.join(steam_root, 'steamapps', 'libraryfolders.vdf')
    try:
        text = open(vdf, encoding='utf-8', errors='ignore').read()
    except OSError:
        return []
    return [m.replace('\\\\', '\\') for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def game_dir():
    """返回 (游戏安装目录, 来源说明)；找不到时目录为 None"""
    global _game_cache
    if _game_cache is not None:
        return _game_cache
    env = os.environ.get('TH06NC_DIR')
    if env and os.path.isfile(os.path.join(env, GAME_EXE)):
        _game_cache = (os.path.normpath(env), '环境变量 TH06NC_DIR')
        return _game_cache
    for pid in find_pids(GAME_EXE):
        path = process_path(pid)
        if path and os.path.isfile(path):
            _game_cache = (os.path.dirname(path), f'运行中的进程 {pid}')
            return _game_cache
    steam, _ = steam_exe()
    roots = []
    if steam:
        sr = os.path.dirname(steam)
        roots = [sr] + _steam_libraries(sr)
    for r in roots:
        cand = os.path.join(r, 'steamapps', 'common', GAME_DIR_NAME)
        if os.path.isfile(os.path.join(cand, GAME_EXE)):
            _game_cache = (cand, 'Steam 库扫描')
            return _game_cache
    _game_cache = (None, '未找到（设 TH06NC_DIR 指定，或先启动游戏）')
    return _game_cache


def game_data_dir():
    """游戏的 data 目录（解包工具用）"""
    d, src = game_dir()
    if not d:
        return None, src
    data = os.path.join(d, 'data')
    return (data, src) if os.path.isdir(data) else (None, f'{d} 下没有 data 目录')


def exe_md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def check():
    """环境自检清单 -> [(级别, 文本)]

    级别：'bad' 必须修才能跑；'warn' 可能影响但不拦；'ok' 正常。
    """
    out = []
    v = sys.version_info
    out.append(('ok' if v >= MIN_PY else 'bad',
                f'Python {v.major}.{v.minor}.{v.micro}（需 ≥ {MIN_PY[0]}.{MIN_PY[1]}）'))
    for mod, need in (('numpy', True), ('tkinter', True), ('capstone', False)):
        try:
            m = __import__(mod)
            out.append(('ok', f'{mod} {getattr(m, "__version__", "")}'.rstrip()))
        except ImportError:
            out.append(('bad' if need else 'warn',
                        f'缺 {mod}' + ('' if need else '（只有反汇编诊断工具用，可跳过）')))
    steam, ssrc = steam_exe()
    out.append(('ok' if steam else 'warn', f'Steam：{steam or ssrc}'))
    gdir, gsrc = game_dir()
    out.append(('ok' if gdir else 'warn', f'游戏目录：{gdir or gsrc}'))
    if gdir:
        md5 = exe_md5(os.path.join(gdir, GAME_EXE))
        if md5 == KNOWN_MD5:
            out.append(('ok', f'游戏构建 {md5[:12]}… 与 offsets.py 基线一致'))
        else:
            # 构建变了 **不等于** 不能用：地址可能已被 addr_cache 适配过。
            # 到底是「已适配」还是「未适配、要跑 autofix」，由 addr.status() 判定。
            try:
                import addr
                out.append(addr.status())
            except Exception as e:                       # noqa: BLE001
                out.append(('bad', f'游戏构建变了：{md5} ≠ 基线 {KNOWN_MD5}\n'
                                   f'      └ 且地址状态查询失败（{type(e).__name__}: {e}）'
                                   ' —— 所有地址失效，跑 py tools\\autofix.py 自动重定位'))
    pids = find_pids(GAME_EXE)
    out.append(('ok', f'游戏进程：{pids[0] if pids else "未运行"}'))
    return out


def main():
    print(f'th06nc 环境自检（项目根 {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}）')
    bad = 0
    for level, text in check():
        mark = {'ok': '✓', 'warn': '!', 'bad': '✗'}[level]
        bad += level == 'bad'
        print(f'  {mark} {text}')
    print('不可用：先修上面标 ✗ 的项' if bad else '可以启动')


if __name__ == '__main__':
    main()

"""地址集中护栏 —— 活跃代码里不该出现裸的游戏地址字面量

为什么留着：同一个地址曾散在多处（curState 5 个文件、BulletManager 5 个、Lives 4 个），
改一处必漏几处。新增读取代码或改 `offsets.py` 后跑一遍。

用法:
  py tools\\check_offsets.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import offsets  # noqa: E402

# 实验遗留（盲扫路线，见 STRUCTURE §2.3）：不在维护范围
LEGACY = {'analyze.py', 'locate.py', 'locate2.py', 'locate3.py', 'find_bullets.py',
          'find_bullet2.py', 'scan_bullets.py', 'scan_state.py', 'find_pool.py',
          'find_pool2.py', 'find_moving.py', 'probe_bullets.py'}
# offsets.py 是唯一允许写地址的地方；disasm.py 的观察点是函数内部偏移，不是结构地址
ALLOW = {'offsets.py', 'disasm.py'}
# Win32 API 常量（winmem.py 自己定义）
API = {0x1000, 0x10000, 0x100000, 0x20000, 0x40000, 0x1000000}
# 落在地址区间但不是地址：测试桩 hwnd、打印区间、缓冲与扫描长度
NON_ADDR = {0x1234, 0x7700, 0x7780, 0x8000}


def main():
    hits = []
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(('.py', '.pyw')) or name in LEGACY or name in ALLOW:
            continue
        tree = ast.parse(open(os.path.join(HERE, name), encoding='utf-8').read())
        for node in ast.walk(tree):
            v = getattr(node, 'value', None)
            if isinstance(v, int) and 0x1000 < v < 0xC30000 \
                    and v not in API and v not in NON_ADDR:
                hits.append(f'{name}:{node.lineno}  0x{v:X}')

    addrs = sorted(v for k, v in vars(offsets).items()
                   if not k.startswith('_') and isinstance(v, int)
                   and 0x1000 < v < 0xC30000 and v not in API)
    print(f'offsets.py 定义 {len(addrs)} 个地址 / 结构常量 '
          f'（0x{addrs[0]:X} .. 0x{addrs[-1]:X}）')
    if hits:
        print(f'\n✗ 裸地址残留 {len(hits)} 处 —— 改成 from offsets import：')
        for h in hits:
            print(f'  {h}')
        return 1
    print('✓ 活跃代码没有裸地址，全部来自 offsets.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())

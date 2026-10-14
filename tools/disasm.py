"""反汇编指定 RVA 处的 x64 代码"""
import sys
import os
import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import FN_COLLISION, FN_LASER_COLLISION
from winmem import module_base

SITES = {
    FN_COLLISION: 'CollisionRva (子弹碰撞检测)',
    0x6AA97: 'SignatureRva',
    FN_LASER_COLLISION: 'LaserCollisionRva',
    0x1087F: 'bullets 钩子',       # 以下均为函数内部偏移，非结构地址
    0x6882D: 'player 钩子',
    0x373B0: 'enemy 钩子',
    0x69774: 'shots 钩子',
    0x69B98: 'fire 钩子',
}


def dis(p, mb, rva, size=0x200, label=''):
    print(f'\n{"="*90}')
    print(f'=== RVA 0x{rva:X}  {label} ===')
    print(f'{"="*90}')
    code = p.read(mb + rva, size)
    if not code:
        print('  读取失败')
        return
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    n = 0
    for insn in md.disasm(code, mb + rva):
        mark = '  <<<' if insn.address - mb == rva else ''
        print(f'  0x{insn.address - mb:06X}  {insn.mnemonic:<8} {insn.op_str}{mark}')
        n += 1
        if n > 70:
            print('  ...')
            break


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid} 模块基址 0x{mb:X}')

    which = sys.argv[1:] or ['collision']
    named = {
        'collision': (FN_COLLISION, 0x180, '子弹碰撞检测 CollisionRva'),
        'laser': (FN_LASER_COLLISION, 0x180, '激光碰撞 LaserCollisionRva'),
        'bullets': (0x1087F, 0x120, 'bullets 钩子 (RCX=BulletManager)'),
        'player': (0x6882D, 0x120, 'player 钩子'),
        'caller': (0x11380, 0x1C0, '子弹碰撞调用者循环 (0x11418)'),
        'caller2': (0x37A00, 0x120, '敌人碰撞调用者 (0x37A6C)'),
    }
    for w in which:
        if w in named:
            rva, size, lab = named[w]
            dis(p, mb, rva, size, lab)
        else:
            try:
                rva = int(w, 16)
            except ValueError:
                continue
            dis(p, mb, rva, 0x400, f'自定义 0x{rva:X}')
    p.close()


if __name__ == '__main__':
    main()

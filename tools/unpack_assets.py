"""从 th06nc 的 PKGL 档案中按需解包子集（只读游戏文件）

格式与解密由第三方只读参考 ref-th06nc-re/tools/pkgl.py 实现，此处只做筛选与落盘。
默认子集 = ECL 弹幕脚本 + ANM 动画 + 文本数据，跳过 DDS 纹理（含 4K，体积上 GB）。

注意：本脚本有父脚本 pkgl.py 的 shebang 问题 —— 用 `py -3` 调用，别用 `py`。

用法:
  py -3 tools\\unpack_assets.py --list                     # 只列名字
  py -3 tools\\unpack_assets.py --out _tmp\\unpacked        # 解默认子集
  py -3 tools\\unpack_assets.py --out DIR --ext ecl,anm
  py -3 tools\\unpack_assets.py --out DIR --all             # 全部（含 4K 纹理，谨慎）
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKGL_DIR = os.path.join(ROOT, '项目文档', '09-依据', 'ref-th06nc-re', 'tools')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKGL_DIR)
import pkgl  # noqa: E402
from env import game_data_dir  # noqa: E402

DEFAULT_EXT = ('.ecl', '.anm', '.std', '.end', '.txt', '.msgpack', '.pos', '.dat', '.json')


def pick(entries, exts, include_4k):
    out = []
    for e in entries:
        name = e.name.lower()
        if name.endswith('.dds') and not include_4k:
            continue
        if exts and not name.endswith(exts):
            continue
        if not include_4k and '_4k' in name:
            continue
        out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '_tmp', 'unpacked'))
    ap.add_argument('--ext', default=','.join(DEFAULT_EXT),
                    help='逗号分隔扩展名，空字符串 = 不过滤')
    ap.add_argument('--all', action='store_true', help='解全部成员（含 4K 纹理）')
    ap.add_argument('--include-4k', action='store_true')
    ap.add_argument('--list', action='store_true', help='只列名字，不解包')
    ap.add_argument('--data', help='游戏 data 目录；默认按 env.py 自动探测')
    args = ap.parse_args()

    data_dir = args.data
    if not data_dir:
        data_dir, src = game_data_dir()
        if not data_dir:
            print(f'失败 定位不到游戏 data 目录：{src}')
            return 1
        print(f'data 目录：{data_dir}（{src}）')
    exts = () if args.all else tuple(
        x.strip() if x.strip().startswith('.') else '.' + x.strip()
        for x in args.ext.split(',') if x.strip())
    arcs = pkgl.load_all(data_dir)

    total_n = total_b = 0
    t0 = time.perf_counter()
    for stem, arc in arcs.items():
        sel = pick(arc.entries, exts, args.all or args.include_4k)
        if args.list:
            for e in sel:
                print(f'{stem}/{e.name}  real={e.real} stored={e.stored}')
            total_n += len(sel)
            continue
        sub = os.path.join(args.out, stem)
        os.makedirs(sub, exist_ok=True)
        for e in sel:
            data = arc.final_payload(e)
            dst = os.path.join(sub, e.name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
            total_n += 1
            total_b += len(data)
        print(f'{stem}: {len(sel)} 个')
    dt = time.perf_counter() - t0
    if args.list:
        print(f'\n共 {total_n} 个成员')
    else:
        print(f'\n解出 {total_n} 个文件，{total_b/1048576:.2f} MB → {args.out}  ({dt:.1f}s)')


if __name__ == '__main__':
    sys.exit(main())

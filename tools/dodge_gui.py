"""th06nc 自动避弹控制台（GUI）

复用 dodge.run_session —— CLI 与 GUI 共用同一套安全闸，策略不重复实现。
窗口只做三件事：显示状态、收集参数、启停后台躲避线程；按键仍全部由 dodge 发出。

用法:
  py tools\\dodge_gui.py
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib_speed
import death_recorder
import dodge
import env
import paths
import th06
from offsets import PLAYER_SPEED
from read_bullets import read_lives
from screen import read_state, screen_of
from winmem import find_windows, module_base, set_foreground

FONT = ('Microsoft YaHei UI', 9)
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
ICON_PATH = paths.res('tools', 'assets', 'th06nc.ico')


def _set_icon(win):
    """窗口与任务栏图标 = 游戏图标；缺图标时静默生成一次，仍失败就保持 Tk 默认图标

    打包版图标随包发布（只读），不再尝试生成 —— `make_icon` 要往 `assets/` 写文件。
    """
    try:
        if not os.path.isfile(ICON_PATH) and not paths.FROZEN:
            import make_icon
            make_icon.build(log=lambda *_: None)
        win.iconbitmap(ICON_PATH)
    except Exception:
        pass

NUM_PARAMS = [
    ('horizon', '弹道外推帧数（horizon）', 5, 90, 1),
    ('speed', '自机速度（px/帧）', 1.0, 12.0, 0.1),
    ('safe', '额外安全裕度（px）', 0.0, 12.0, 0.5),
    ('edge', '贴边惩罚权重', 0.0, 30.0, 1.0),
    ('attack', '进攻吸引权重（0 为不追）', 0.0, 60.0, 2.0),
    ('standoff', '输出保持距离（px）', 0.0, 200.0, 8.0),
    ('item', '道具吸引权重（0 为不捡）', 0.0, 100.0, 2.0),
    ('item_wait', '道具等待窗口（帧）', 0.0, 120.0, 5.0),
    ('poc_min', '道具线触发价值', 0.0, 20.0, 1.0),
    ('risk', '同等安全容差（px）', 0.0, 4.0, 0.5),
    ('warn', '弹幕预警窗口（帧）', 0.0, 60.0, 2.0),
    ('warn_dist', '预警危险半径（px）', 0.0, 150.0, 10.0),
    ('inertia', '同向惯性奖励', 0.0, 3.0, 0.1),
    ('comfort', '安全分数线（px）', 0.0, 30.0, 1.0),
    ('margin', '安全余量权重', 0.0, 30.0, 1.0),
    ('clear', '空旷区吸引权重', 0.0, 60.0, 2.0),
    ('clear_r', '空旷度评价半径（px）', 20.0, 200.0, 5.0),
    ('center', '自动回中权重', 0.0, 300.0, 2.0),
    ('center_r', '回中自由半径（px）', 5.0, 250.0, 5.0),
    ('center_y', '待机锚点纵坐标（数值增大靠下）', 16.0, 432.0, 4.0),
    ('switch', '方向切换门槛', 0.0, 3.0, 0.1),
    ('react', '安全时反应延迟（帧）', 0.0, 20.0, 1.0),
    ('bomb_pre', '必死预判提前（帧）', 0.0, 8.0, 1.0),
    ('human_idle', '让位静默时长（秒）', 0.2, 10.0, 0.2),
    ('focus_slack', '低速门槛余量（px）', 0.0, 60.0, 2.0),
]

# 滑条范围即设计有效区间。Spinbox 只限制上下箭头，**不挡键入** —— 手输超范围值
# 会原样进 cfg。超范围不等于「更强」：clear_r = 999 时九向空旷度同时饱和到 1.0，
# 该项恒为常数、决策差异率 0.0%（实测），表现就是「这个功能没生效」。
NUM_LIMITS = {k: (lo, hi) for k, _label, lo, hi, _step in NUM_PARAMS}

# 悬浮说明：面向「调它会发生什么」。完整版见 项目文档/04-调参/相关-参数速查-TUNING.md，
# 设计原因见 tools/dodge.py 顶部常量区与 项目文档/01-规范/必读-防回退清单-DO_NOT_REVERT.md。
PARAM_HELP = {
    'speed': '实测标定值，不要手工填写；换设备或游戏版本后跑「校准速度」。',
    'poc_min': '满火力且场上掉落总价值不低于此值时才冲收集线；0 为条件满足即冲。',
    'risk': '紧张档的同等安全容差；0 为退回纯避弹。',
    'warn': '按倒计时预测发弹时机，不预测弹幕形状；0 为关闭。',
    'comfort': '安全分数线：存在间隙不低于此值的方向时才进入宽裕档。',
    'clear': '只在够安全的方向间排序，不覆盖安全判断。',
    'clear_r': '上限约 150px：半径覆盖全场时九向空旷度同时饱和，本项完全失效。',
    'center_y': '上下出口不等价（上方端点紧邻 BOSS），下移锚点即偏好向下待机。',
    'switch': '抑制逐帧横跳；上限 0.5，超过会滞留在应切换的方向。',
    'bomb_pre': '九向全部重叠时提前按 X；0 为关闭预判。',
    'focus_slack': '原地间隙不低于分数线加此值时才切半速；0 为不差于分数线即切。',
}


class Tooltip:
    """轻量悬浮说明 —— tkinter 没有内置 tooltip"""

    def __init__(self, widget, text, delay=400):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self.after_id = None
        widget.bind('<Enter>', self._schedule)
        widget.bind('<Leave>', self._hide)
        widget.bind('<ButtonPress>', self._hide)

    def _schedule(self, _=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f'+{x}+{self.widget.winfo_rooty()}')
        tk.Label(self.tip, text=self.text, justify='left', font=FONT,
                 background='#ffffe0', relief='solid', borderwidth=1,
                 wraplength=340, padx=8, pady=6).pack()

    def _hide(self, _=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root, auto_connect=False):
        self.root = root
        root.title('th06nc 自动避弹控制台')
        _set_icon(root)

        self.p = None
        self.pid = None
        self.mb = None
        self.hwnd = None
        self.thread = None
        self.stop_flag = threading.Event()
        self.q = queue.Queue()
        self.bbox = None                   # 死亡黑匣子实例（勾选后由 start() 创建，跑在躲避线程里）
        self.cfg = {}
        self.range_warned = set()          # 超范围告警去重：同一组值只报一次
        self.saved_n, self.saved_err = self.load_defaults()
        self.num_vars = {}
        self.bool_vars = {}
        self.win_adv = None
        self.win_log = None
        self._adv_placed = False
        self._log_placed = False
        self._build()
        self._build_controls()
        self._build_advanced()
        self._build_log()
        root.update_idletasks()
        root.geometry(f'{max(660, root.winfo_reqwidth())}x{root.winfo_reqheight()}')
        root.resizable(False, False)          # 内容固定，别让拉伸拉出空白
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.after(100, self.pump)
        root.after(700, self.refresh_status)
        self.log('就绪：连接游戏，进入关卡后开始。')
        if self.saved_err:
            self.log(f'{self.saved_err}；本次使用出厂默认值。')
        elif self.saved_n:
            self.log(f'已载入保存的默认值 {self.saved_n} 项。')
        self.check_ranges()        # 载入的值也可能超范围（Spinbox 不挡键入）
        if auto_connect:
            root.after(400, self.connect)

    # ---------- 默认值 ----------
    def load_defaults(self):
        """出厂默认 ← dodge.default_params()，再叠加控制台保存过的值；返回 (采用项数, 错误)"""
        cfg = dict(dodge.default_params())
        cfg.update(dry=False, frames=0, period=1 / 60.0, resume=False, restore=True)
        saved, n, err = dodge.load_saved()
        cfg.update(saved)
        self.cfg = cfg
        return n, err

    def update_saved_label(self):
        self.lbl_saved.configure(
            text=f'当前默认值：{"出厂" if not self.saved_n else f"已保存 {self.saved_n} 项"}')

    def save_defaults(self):
        """把界面上这组值固化为下次启动的默认值（写 dodge_params.json）"""
        self.sync_cfg()
        ok, msg = dodge.save_saved(self.cfg)
        self.log(msg)
        if ok:
            self.saved_n = len(dodge.default_params())
            self.update_saved_label()
            self.log('  下次打开控制台将自动载入这组值；存放位置见 dodge.SAVED_PATH。')

    def reset_defaults(self):
        """删掉保存的默认值，并把界面立即拨回出厂默认"""
        ok, msg = dodge.clear_saved()
        self.log(msg)
        if not ok:
            return
        base = dodge.default_params()
        for key, var in self.num_vars.items():
            if key in base:
                var.set(f'{base[key]:g}')
        for key, var in self.bool_vars.items():
            if key in base:
                var.set(bool(base[key]))
        self.cfg.update(base)          # 勾选框变化不会走 sync_cfg，这里直接补上
        self.sync_cfg()
        self.saved_n = 0
        self.update_saved_label()

    # ---------- 界面 ----------
    def _build(self):
        pad = dict(padx=10, pady=(6, 0))

        # 连接状态
        box1 = ttk.LabelFrame(self.root, text=' 连接 ')
        box1.pack(fill='x', **pad)
        self.lbl_conn = ttk.Label(box1, text='未连接', font=FONT_B, foreground='#b00')
        self.lbl_conn.grid(row=0, column=0, sticky='w', padx=8, pady=4)
        self.lbl_screen = ttk.Label(box1, text='画面：无　　前台：无', font=FONT)
        self.lbl_screen.grid(row=0, column=1, sticky='w', padx=8)
        bf = ttk.Frame(box1)
        bf.grid(row=1, column=0, columnspan=2, sticky='w', padx=6, pady=(0, 6))
        ttk.Button(bf, text='连接游戏', command=self.connect).pack(side='left', padx=3)
        ttk.Button(bf, text='启动游戏', command=self.launch_game).pack(side='left', padx=3)
        ttk.Button(bf, text='校准速度', command=self.calibrate).pack(side='left', padx=3)

        # 运行数据
        box2 = ttk.LabelFrame(self.root, text=' 运行数据 ')
        box2.pack(fill='x', **pad)
        self.lbl_run = ttk.Label(box2, text='未运行', font=FONT_B)
        self.lbl_run.grid(row=0, column=0, sticky='w', padx=8, pady=4)
        self.lbl_data = ttk.Label(box2, text='弹 无　　敌 无　　激光 无　　自机（无）　　方向 无', font=FONT)
        self.lbl_data.grid(row=1, column=0, sticky='w', padx=8)
        self.lbl_extra = ttk.Label(box2, text='残机 无　　炸弹 无　　道具 无　　方向评分 无', font=FONT)
        self.lbl_extra.grid(row=2, column=0, sticky='w', padx=8, pady=(0, 6))

    # ---------- 高级设置窗口 ----------
    def _build_advanced(self):
        """参数 / 勾选 / 默认值按钮全收在这个窗口 —— 主窗口因此只占一屏，日志不被挤走"""
        win = tk.Toplevel(self.root)
        win.title('th06nc 自动避弹（高级设置）')
        _set_icon(win)
        win.withdraw()
        win.minsize(600, 0)                # 两列排布需要的最小宽度
        win.protocol('WM_DELETE_WINDOW', self.hide_advanced)
        self.win_adv = win

        # 参数
        box3 = ttk.LabelFrame(win, text=' 参数（运行中改动即时生效，悬停 0.4 秒显示说明） ')
        box3.pack(fill='x', padx=10, pady=(8, 6))
        box3.columnconfigure(1, weight=1)  # 两列各吸收一半余量，标签右对齐成一条线
        box3.columnconfigure(3, weight=1)
        rows = (len(NUM_PARAMS) + 1) // 2          # 两列排布：窗口矮一半，参数更好扫
        for i, (key, label, lo, hi, step) in enumerate(NUM_PARAMS):
            col, row = divmod(i, rows)
            lb = ttk.Label(box3, text=label, font=FONT)
            lb.grid(row=row, column=col * 2, sticky='e', padx=(10, 4), pady=2)
            var = tk.StringVar(value=f'{self.cfg[key]:g}')
            self.num_vars[key] = var
            sp = ttk.Spinbox(box3, from_=lo, to=hi, increment=step, textvariable=var,
                             width=8, font=FONT, command=lambda k=key: self.sync_cfg())
            sp.grid(row=row, column=col * 2 + 1, sticky='w', padx=(0, 16))
            sp.bind('<KeyRelease>', lambda e: self.sync_cfg())
            sp.bind('<FocusOut>', lambda e: self.sync_cfg())
            if key in PARAM_HELP:                     # 悬停 0.4s 出说明
                Tooltip(lb, PARAM_HELP[key])
                Tooltip(sp, PARAM_HELP[key])
        checks = [('autofire', '自动射击（持续按住 Z）'), ('bomb', '自动灵击（按 X 保命）'),
                  ('use_enemy', '纳入敌人本体'),
                  ('use_laser', '纳入激光'), ('unpause', '开场按 Z 解除暂停'),
                  ('keep_going_on_death', '掉命后继续（默认启用）'),
                  ('resume', '失败菜单按 Z 继续'),
                  ('focus', '低速模式（宽裕时半速）'),
                  ('poc', '智能道具线（满火力时冲收集线）'),
                  ('advance', '自动进下一关'), ('human_yield', '玩家操作时让位'),
                  ('blackbox', '死亡黑匣子（掉命时保存现场）')]
        for i in range(0, len(checks), 3):
            cf = ttk.Frame(box3)
            cf.grid(row=rows + i // 3, column=0, columnspan=4,
                    sticky='w', padx=6, pady=(8, 3) if i == 0 else 3)
            for key, label in checks[i:i + 3]:
                v = tk.BooleanVar(value=self.cfg[key])
                self.bool_vars[key] = v
                cb = ttk.Checkbutton(cf, text=label, variable=v, command=self.sync_cfg)
                cb.pack(side='left', padx=4)
                if key == 'bomb':
                    Tooltip(cb, '被击中后 8 帧内按 X 取消死亡；九向必死时提前炸。\n'
                                '无炸弹、无敌中不触发。')
                elif key == 'focus':
                    Tooltip(cb, '原地间隙不低于安全分数线加「低速门槛余量」时才切半速；\n'
                                '必须躲避时立即回高速。')
                elif key == 'poc':
                    Tooltip(cb, '满火力且掉落价值不低于「道具线触发价值」时冲收集线一次；\n'
                                '上方被封锁时冲不上去，限时 5 秒。')
                elif key == 'blackbox':
                    Tooltip(cb, '掉命时把前 4 秒现场落盘至 _tmp\\death_*.npz，\n'
                                '供 py tools\\death_report.py 事后解剖。')
                elif key == 'advance':
                    Tooltip(cb, '关卡过渡不退出；开场对话按节奏轻点 Z。\n'
                                '进入 Continue 画面立即停手。')
                elif key == 'resume':
                    Tooltip(cb, '停在失败菜单时按一次 Z。\n'
                                '普通关卡会消耗续关次数，不需要时关闭。')
                elif key == 'keep_going_on_death':
                    Tooltip(cb, '掉命后继续运行（含最后一条命）；关闭则掉命即退出。')
                elif key == 'human_yield':
                    Tooltip(cb, '检测到真人按键即让位，不发送任何按键；\n'
                                '玩家停手数秒后恢复接管。')
        # 把界面上这组值固化为下次启动的默认值
        pf = ttk.Frame(box3)
        pf.grid(row=rows + (len(checks) + 2) // 3, column=0, columnspan=4,
                sticky='w', padx=6, pady=(8, 2))
        ttk.Button(pf, text='保存为默认值',
                   command=self.save_defaults).pack(side='left', padx=4)
        ttk.Button(pf, text='恢复出厂默认',
                   command=self.reset_defaults).pack(side='left', padx=4)
        self.lbl_saved = ttk.Label(pf, text='', font=FONT)
        self.lbl_saved.pack(side='left', padx=8)
        self.update_saved_label()

    def show_advanced(self):
        """打开（或重新前置）高级设置窗口；首次打开时贴着主窗口定位"""
        win = self.win_adv
        win.deiconify()
        win.lift()
        if not self._adv_placed:
            self._place_near(win, self.root.winfo_reqwidth() + 8, 0)
            self._adv_placed = True

    def show_log(self):
        """打开（或重新前置）日志窗口；首次打开时摆到主窗口下方"""
        win = self.win_log
        win.deiconify()
        win.lift()
        if not self._log_placed:
            self._place_near(win, 0, self.root.winfo_reqheight() + 8, size=(640, 400))
            self._log_placed = True

    def hide_log(self):
        self.win_log.withdraw()

    def _place_near(self, win, dx, dy, size=None):
        """把浮动窗口摆到主窗口附近；越出屏幕就夹回屏内（只按主屏算）

        size 明确给出尺寸：`withdraw` 期间设的 geometry 尺寸会被 Tk 按请求尺寸覆盖，
        在这里一并设掉才稳（日志窗口曾因此被压成 134px 高）。
        """
        win.update_idletasks()
        x = min(self.root.winfo_rootx() + dx,
                win.winfo_screenwidth() - win.winfo_reqwidth() - 8)
        y = min(self.root.winfo_rooty() + dy,
                win.winfo_screenheight() - win.winfo_reqheight() - 48)
        geo = f'+{max(0, x)}+{max(0, y)}'
        if size:
            geo = f'{size[0]}x{size[1]}{geo}'
        win.geometry(geo)

    def hide_advanced(self):
        """关窗只隐藏（状态留住）；隐藏前把正在编辑的值落进 cfg"""
        self.sync_cfg()
        self.win_adv.withdraw()

    # ---------- 主窗口下半：启停 ----------
    def _build_controls(self):
        pad = dict(padx=10, pady=(6, 0))

        # 控制
        box4 = ttk.Frame(self.root)
        box4.pack(fill='x', **pad)
        self.btn_start = ttk.Button(box4, text='开始避弹', command=self.start)
        self.btn_start.pack(side='left', padx=(0, 6))
        self.btn_stop = ttk.Button(box4, text='停止', command=self.stop, state='disabled')
        self.btn_stop.pack(side='left')
        ttk.Button(box4, text='高级设置',
                   command=self.show_advanced).pack(side='right')
        ttk.Button(box4, text='日志', command=self.show_log).pack(side='right', padx=6)

    # ---------- 日志窗口 ----------
    def _build_log(self):
        """日志也收进独立窗口 —— 主窗口因此只剩「连接 / 运行数据 / 启停」三行"""
        win = tk.Toplevel(self.root)
        win.title('th06nc 自动避弹（日志）')
        _set_icon(win)
        win.withdraw()
        win.minsize(640, 400)              # 日志窗口固定尺寸：geometry 会被 Tk 按内容覆盖
        win.protocol('WM_DELETE_WINDOW', self.hide_log)
        self.win_log = win

        box = ttk.LabelFrame(win, text=' 日志 ')
        box.pack(fill='both', expand=True, padx=10, pady=(8, 4))
        self.txt = tk.Text(box, height=16, font=('Consolas', 9), wrap='none',
                           background='#111', foreground='#ddd', insertbackground='#ddd')
        sb = ttk.Scrollbar(box, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.txt.configure(state='disabled')

        bf = ttk.Frame(win)
        bf.pack(fill='x', padx=10, pady=(0, 8))
        ttk.Button(bf, text='清空日志', command=self.clear_log).pack(side='left')

    # ---------- 参数 ----------
    def check_ranges(self):
        """载入的参数超范围就告警 —— 只在启动时扫一遍（后续输入走 sync_cfg 同一套判据）"""
        for key, (lo, hi) in NUM_LIMITS.items():
            v = self.cfg.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not lo <= v <= hi:
                self.warn_range(key, v, lo, hi)

    def warn_range(self, key, v, lo, hi):
        """超范围告警（同一组值只报一次）：范围外的值有的是「更强」，有的直接退化"""
        if (key, v) in self.range_warned:
            return
        self.range_warned.add((key, v))
        hint = {'clear_r': '半径过大时九向空旷度同时饱和到 1.0，本项恒为常数、完全失效'
                           '（999px 实测决策差异率 0.0%）。建议 110，上限约 150',
                'clear': '空旷吸引过强会为正空旷让出安全余量（权重 100 时最差单帧 −5.7px）；'
                         '默认 25 为零代价标定点，上限 60'}.get(
                    key, '值仍生效，但已超出推荐区间；部分参数越界不等于更强，可能直接退化')
        self.log(f'{key} = {v:g} 超出滑条范围 [{lo:g}, {hi:g}]。{hint}。')

    def sync_cfg(self):
        for key, var in self.num_vars.items():
            try:
                v = float(var.get())
            except ValueError:
                continue
            lo, hi = NUM_LIMITS.get(key, (None, None))
            if lo is not None and not lo <= v <= hi:
                self.warn_range(key, v, lo, hi)
            self.cfg[key] = v
        for key, var in self.bool_vars.items():
            self.cfg[key] = bool(var.get())

    # ---------- 日志 ----------
    def log(self, msg):
        self.q.put(('log', f'{msg}'))

    def clear_log(self):
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.configure(state='disabled')

    # ---------- 连接 ----------
    def connect(self):
        if self.thread and self.thread.is_alive():
            self.log('躲避运行中，请先停止再重新连接（重连会关闭躲避线程正在使用的句柄）。')
            return
        try:
            if self.p is not None:
                self.p.close()
        except Exception:
            pass
        self.p = None
        try:
            self.p, self.pid = th06.get_proc()
            self.mb = module_base(self.pid, 'th06nc.exe')[0]
            self.hwnd = find_windows(pid=self.pid)[0][0]
        except Exception as e:
            self.lbl_conn.configure(text='未连接', foreground='#b00')
            self.lbl_screen.configure(text='画面：无　　前台：无')
            self.log(f'连接失败：{e}。游戏未运行时请先点「启动游戏」。')
            return
        self.lbl_conn.configure(text=f'已连接　PID {self.pid}　基址 0x{self.mb:X}',
                                foreground='#080')
        self.log(f'已连接 PID {self.pid}，基址 0x{self.mb:X}，hwnd 0x{self.hwnd:X}。')
        gdir, _ = env.game_dir()
        if gdir:
            md5 = env.exe_md5(os.path.join(gdir, env.GAME_EXE))
            if md5 != env.KNOWN_MD5:
                self.log(f'游戏构建 {md5[:12]}… 与依据 {env.KNOWN_MD5[:12]}… 不一致，'
                         '地址与结构偏移可能已失效，请先核对 MEMMAP。')
        self.refresh_status()

    def launch_game(self):
        steam, src = env.steam_exe()
        if not steam:
            self.log(f'{src}；也可手动启动游戏后再点「连接游戏」。')
            return
        subprocess.Popen([steam, '-applaunch', env.APPID])
        self.log(f'已请求 Steam 启动 th06nc（{src}）。请等待数秒后点「连接游戏」。')

    def calibrate(self):
        if self.p is None:
            self.log('请先连接游戏。')
            return
        if self.thread and self.thread.is_alive():
            self.log('躲避运行中，请先停止。')
            return

        def work():
            def put(m):
                self.q.put(('log', m))
            try:
                set_foreground(self.hwnd)
                time.sleep(0.4)
                if th06.user32.GetForegroundWindow() != self.hwnd:
                    put('游戏未取得前台焦点，未发送任何按键，以免按键发送至其他程序。')
                    return
                th06.tap('z', 60)
                time.sleep(0.4)
                out = calib_speed.calibrate(self.p, self.mb, self.hwnd, 40, log=put)
                calib_speed.report(out, log=put)
                if out['ok']:
                    self.q.put(('num', ('speed', round(out['speed'], 2))))
                    put(f'已将「自机速度」填为 {out["speed"]:.2f}，可直接点「开始避弹」。')
                    if out['normalized'] is False:
                        put('斜向判定为「分轴独立」：DIRS 的斜向分量须从 0.70711 改为 ±1，'
                            '否则斜向躲避的预测会偏。请将以上输出交维护者落盘。')
                    else:
                        put('斜向已归一化，与 DIRS 现有定义一致，无需修改代码。')
            except Exception as e:
                put(f'校准失败：{e}')

        threading.Thread(target=work, daemon=True).start()
        self.log('校准中：8 向、每向 40 帧，先归中（须已进入关卡）。')

    # ---------- 状态刷新 ----------
    def refresh_status(self):
        if self.p is not None:
            try:
                st = read_state(self.p, self.mb)
                code, desc, ok = screen_of(st)
                fg = self.hwnd is not None and th06.user32.GetForegroundWindow() == self.hwnd
                self.lbl_screen.configure(
                    text=f'画面：{code}（{desc[:30]}）　　前台：{"是" if fg else "否"}')
            except Exception:
                self.lbl_screen.configure(text='画面：读取失败（进程可能已退出）')
        self.root.after(700, self.refresh_status)

    def pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'log':
                    self.txt.configure(state='normal')
                    self.txt.insert('end', payload + '\n')
                    self.txt.see('end')
                    self.txt.configure(state='disabled')
                elif kind == 'num':            # 后台线程不能直接改 tk 变量，走队列回主线程
                    k, v = payload
                    self.cfg[k] = v
                    self.num_vars[k].set(f'{v:g}')
                elif kind == 'frame':
                    s = payload
                    tgt = s.get('target')
                    aim = f'　　射击目标（{tgt[0]:.0f}, {tgt[1]:.0f}）' if tgt else ''
                    if s.get('yield'):
                        mode = '玩家接管，脚本让位'
                    else:
                        mode = '射击中' if s.get('firing') else '未射击'
                    sw = s.get('switches', 0)
                    bb = s.get('bb')
                    bbt = (f'　　黑匣子 {bb[0]} 帧'
                           + (f'，已存 {bb[1]} 例' if bb[1] else '') if bb else '')
                    self.lbl_run.configure(
                        text=f'运行中　{s["frame"]} 帧　{s["fps"]:.1f} fps　{mode}'
                             + (f'　　关卡过渡 {sw} 次' if sw else '') + bbt)
                    self.lbl_data.configure(
                        text=f'弹 {s["bullets"]:3d}　　敌 {s["enemies"]:2d}　　'
                             f'激光 {s["lasers"]:2d}　　'
                             f'自机（{s["px"]:6.1f}, {s["py"]:6.1f}）　　'
                             f'方向 {self._dir_text(s)}'
                             f'{"　低速" if s.get("focus") else ""}{aim}')
                    top = '　'.join(f'{n}={v:.1f}' for n, v in s['top'])
                    wn = s.get('warn', -1)
                    bm = s.get('bombs', -1)
                    bf = s.get('bombs_fired', 0)
                    bt = (f'炸弹 {bm}{"，灵击中" if s.get("bomb_use") else ""}'
                          + (f'（已放 {bf}）' if bf else '')) if bm >= 0 else '炸弹 无'
                    pcs = s.get('poc', 'idle')
                    pt = (f'冲线第 {s.get("poc_t", 0)} 帧' if pcs == 'charging'
                          else ('冲线冷却中' if pcs == 'cooldown'
                                else f'可转化 {s.get("poc_val", 0.0):.1f}'))
                    if s.get('poc_trips', 0) or s.get('poc_gives', 0):
                        pt += f'（成 {s.get("poc_trips", 0)} 弃 {s.get("poc_gives", 0)}）'
                    lv = s['lives']
                    self.lbl_extra.configure(
                        text=f'残机 {lv}{"（最后一条命）" if lv == 0 else ""}　　{bt}　　'
                             f'道具 {s["items"]:2d}　　{pt}　　'
                             f'预警 {wn if wn >= 0 else "无":>3} 帧　　方向评分：{top}')
                elif kind == 'done':
                    self.lbl_run.configure(text=f'已停止（{payload}）')
                    self.btn_start.configure(state='normal')
                    self.btn_stop.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(120, self.pump)

    # ---------- 启停 ----------
    def start(self):
        if self.p is None:
            self.connect()
            if self.p is None:
                return
        if self.thread and self.thread.is_alive():
            self.log('已在运行中。')
            return
        self.sync_cfg()
        self.stop_flag = threading.Event()
        # 死亡黑匣子：勾选才建。喂的是主循环**已经读到**的世界（on_world 钩子），
        # 所以不额外占 2MB/帧 的读取带宽 —— 另起进程录会把主循环挤到掉帧。
        self.bbox = None
        if self.cfg.get('blackbox'):
            self.bbox = death_recorder.BlackBox(
                self.p, self.mb, pre=240, post=24, max_saves=8,
                log=lambda m: self.q.put(('log', m)), params=self.cfg)
            self.log(f'死亡黑匣子已启用：掉命时落盘至 {self.bbox.out_dir}\\death_*.npz。')
        self.btn_start.configure(state='disabled')
        self.btn_stop.configure(state='normal')
        self.log('开始避弹。')

        def work():
            try:
                frame, el, reason = dodge.run_session(
                    self.p, self.mb, self.hwnd, self.cfg,
                    on_frame=self.on_frame,
                    on_world=self.on_world,
                    stop_flag=self.stop_flag,
                    log=lambda m: self.q.put(('log', m)))
                tail = f'{frame} 帧 / {el:.1f}s = {frame/el:.1f} fps' if frame else '未产生帧'
                self.q.put(('log', f'结束：{reason}（{tail}）。'))
                self.q.put(('done', reason))
            except Exception as e:
                self.q.put(('log', f'运行异常：{e}'))
                self.q.put(('done', f'异常 {e}'))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    @staticmethod
    def _dir_text(s):
        """方向显示：等待延迟时标出「延迟几帧后切往哪个方向」—— 人类化闸门在工作"""
        w = s.get('wait', 0)
        plan = s.get('plan', s['dir'])
        return f'{s["dir"]}（延迟 {w} 帧切至 {plan}）' if w else s['dir']

    def on_frame(self, s):
        """躲避线程回调：降频入队，避免 UI 刷新拖慢 60 Hz 闭环

        实测每帧实际只需 2.8 ms（读 2.36 + 算 0.43），跑不满 60 fps 全是 tkinter
        主循环抢 GIL 所致 —— 入队越密，躲避线程被抢占越久。
        """
        if s['frame'] % 10 == 0:
            if self.bbox is not None:
                s['bb'] = (self.bbox.n, self.bbox.saves)   # 状态栏显示用（只读两个整数）
            self.q.put(('frame', s))
        return not self.stop_flag.is_set()

    def on_world(self, w, st, ps):
        """死亡黑匣子钩子：躲避线程每帧调用

        喂的是主循环这一帧**已经读到**的世界，本方法只补 3 个小读（focus / 输入位图 /
        火力）；落盘与日志都在 BlackBox 内完成。**绝不在这里碰 tkinter** —— 它在躲避线程里。
        """
        if self.bbox is not None:
            self.bbox.feed(w, st, ps)

    def stop(self):
        self.stop_flag.set()
        self.log('已请求停止。')

    def on_close(self):
        self.stop_flag.set()
        try:
            if self.p is not None:
                self.p.close()
        except Exception:
            pass
        self.root.destroy()


def main(auto_connect=False):
    root = tk.Tk()
    try:
        ttk.Style().theme_use('vista')
    except tk.TclError:
        pass
    App(root, auto_connect=auto_connect)
    root.mainloop()


if __name__ == '__main__':
    main()

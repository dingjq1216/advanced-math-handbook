# -*- coding: utf-8 -*-
"""
ASCII 图生成 / 校准工具
====================================================
终端与浏览器里的等宽字体中，CJK 字符占 2 格、拉丁与制表符占 1 格。
手写的框图极易因这个差异错位。本工具用程序精确控制每个框图的宽度，
生成后直接替换 chapters/*.md 中指定序号的代码块。

用法：修改下面的 MODE 变量后运行
    python gen_figs.py
"""

from __future__ import annotations

import math
import re
import pathlib
import unicodedata

# ======================================================================
# 运行模式：
#   "check" —— 校验 chapters/*.md 里的图形是否与生成器同步（只读）
#   "apply" —— 生成并写回 chapters/*.md
# ======================================================================
# ⚠ 纪律：md 与生成器一旦漂移，md 视为权威 —— 不要直接 apply 回退，
#   先用 C:\temp\wbverify\diff_figs_all.py 看差异，再用 sync_figs.py
#   这类「精确替换 + md 反向生成」脚本把生成器同步到 md（2026-09-18
#   曾一次同步 24 处漂移，见 C:\temp\wbverify\sync_figs.py）。
# ======================================================================
MODE = "check"

ROOT = pathlib.Path(__file__).resolve().parent
CH_DIR = ROOT / "chapters"


# ----------------------------------------------------------------------
# 宽度计算与绘图原语
# ----------------------------------------------------------------------
def w(s: str) -> int:
    """按终端显示宽度计算字符串长度（CJK 全角 = 2）。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - w(s))


def box(rows, inner: int, indent: int = 0, bullet: str = "") -> list[str]:
    """生成一个内容宽度为 inner 的方框；bullet 为左外侧的步骤标签。"""
    pre = " " * indent
    out = []
    if bullet:
        out.append(pre + bullet + "┌" + "─" * inner + "┐")
    else:
        out.append(pre + "┌" + "─" * inner + "┐")
    for r in rows:
        out.append(pre + bullet + "│ " + pad(r, inner - 2) + " │")
    out.append(pre + bullet + "└" + "─" * inner + "┘")
    return out


def arrow_down(width: int, indent: int = 0, bullet: str = "") -> str:
    pre = " " * indent
    if bullet:
        return pre + " " * w(bullet) + " " * (2 + width // 2 - 1) + "▼"
    return pre + " " * (2 + width // 2 - 1) + "▼"


def center(s: str, width: int) -> str:
    left = (width - w(s)) // 2
    return " " * max(0, left) + s


class Canvas:
    """按「显示列」对齐的字符画布。

    几何图形（围道）无法靠手工排版对齐，故用一个显式坐标的网格：
    所有坐标都是显示列号（CJK 占 2 列），render() 时统一补齐空格。
    """

    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        self.cells: list[dict[int, str]] = [{} for _ in range(rows)]
        self.taken: list[set[int]] = [set() for _ in range(rows)]

    def put(self, r: int, c: int, s: str) -> None:
        if not (0 <= r < self.rows):
            return
        for ch in s:
            cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if ch != " " and c not in self.taken[r] and not (cw == 2 and c + 1 in self.taken[r]):
                self.cells[r][c] = ch
                self.taken[r].add(c)
                if cw == 2:
                    self.taken[r].add(c + 1)
            c += cw

    def hline(self, r: int, c0: int, c1: int, ch: str = "─") -> None:
        for c in range(c0, c1 + 1):
            self.put(r, c, ch)

    def vline(self, c: int, r0: int, r1: int, ch: str = "│") -> None:
        for r in range(r0, r1 + 1):
            self.put(r, c, ch)

    def text(self, r: int, c: int, s: str) -> None:
        self.put(r, c, s)

    def dot(self, r: float, c: float, ch: str = "·") -> None:
        self.put(int(round(r)), int(round(c)), ch)

    def render(self) -> list[str]:
        out = []
        for r in range(self.rows):
            line, cur = "", 0
            for c in sorted(self.cells[r]):
                if c < cur:
                    continue
                if c > cur:
                    line += " " * (c - cur)
                ch = self.cells[r][c]
                line += ch
                cur = c + (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
            out.append(line.rstrip())
        return out


# ======================================================================
# 各图定义
# ======================================================================

# ---------- ch00 block0：全书层级依赖图 ----------
def fig_layers() -> list[str]:
    """五层依赖图。三处「层级」各由一个专门的视觉载体承担：

    ① 每层一个方框 —— 框线就是这一层的边界，条目落在框内（包含关系）；
    ② 框与框之间用中轴 ┬ │ ▼ ┴ 串成一条链 —— 从 L4 贯到 L0，
       而不是五段各自顶着一条长横线的平行条目（这正是旧版"扁平"的来源）；
    ③ 右侧两个大括号把上面两层（应用 / 结构）与下面三层（地基）分开 ——
       括号标签「应用与结构」「全书的地基」都取自各层自身的职责描述，
       不引入图外未定义的说法；两个标签等宽，右缘天然对齐。

    宽度口径：方框上/下边框共 INNER 格横线，整行宽 INNER + 4 = 76 列；
    中轴落在第 J 列，必须在边框的横线格（3 … 3+INNER-1）之内，
    且要躲开写在边框上的层标题（最长 25 列）。
    """
    IND = "  "          # 整图左缩进
    INNER = 72          # 方框上/下边框的横线格数
    FIELD = INNER - 2   # 框内可用显示列
    J = 38              # 中轴（┬ │ ▼ ┴）所在显示列
    BRACE = 77          # 右侧大括号所在显示列
    KEY_W = 16          # 条目名对齐宽度

    layers = [
        ("L4  应用层", "第二至第五卷 · 把下面三层的结论装成可用的方法", [
            ("信号与变换", "傅里叶 · 采样 · 小波 · 框架"),
            ("控制与决策", "经典 · 现代 · 鲁棒 · 最优 · 随机 · 非线性"),
            ("学习与泛化", "优化 · NTK · 泛化界 · 生成模型"),
            ("随机与统计", "随机过程 · 估计 · 信息论"),
        ]),
        ("L3  结构层", "第二至第五卷 · 各门类共用的一套结构语言", [
            ("变换与系统", "傅里叶 · 拉普拉斯 · Z · 状态空间"),
            ("概率与随机", "条件期望 · 鞅 · SDE · 滤波"),
            ("优化与控制", "凸分析 · 变分法 · HJB · Riccati"),
        ]),
        ("L2  基础层", "第一卷 · 全书的地基，上层处处回头引用", [
            ("测度与积分", "第 3 章"),
            ("分布与弱导数", "第 4 章"),
            ("复变与留数", "第 5 章   ← 全书复用最频繁的一章"),
            ("泛函与 RKHS", "第 6 章"),
        ]),
        ("L1  分析基础", "第一卷 · 先把工具磨利，再谈别的", [
            ("微积分进阶", "第 1 章"),
            ("黎曼与反常积分", "第 2 章"),
        ]),
        ("L0  前置", "读者已有，本书不重复", [
            ("基础", "初等微积分 · 线性代数 · 初等概率 · 实数完备性"),
        ]),
    ]

    def border(left: str, right: str, joint: str | None, label: str = "") -> str:
        """上/下边框。joint（┬ 或 ┴）落在中轴列 J 上。

        层标题含 CJK，必须按**显示宽度**占格：一个全角字吃掉 2 格横线
        （第二格置空）。按「1 字符 = 1 格」写会让整行多出 3 列，
        于是带标题的边框与光边框右缘不齐、右侧大括号也错位。
        """
        cells = ["─"] * INNER
        col = 0
        for ch in label:
            if col >= INNER:
                break
            span = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            cells[col] = ch
            for k in range(1, span):
                if col + k < INNER:
                    cells[col + k] = ""
            col += span
        if joint:
            cells[J - 3] = joint
        return IND + left + "".join(cells) + right

    def row(text: str) -> str:
        return IND + "│ " + pad(text, FIELD) + " │"

    lines: list[str] = []
    top_at: list[int] = []
    bot_at: list[int] = []
    for i, (name, role, items) in enumerate(layers):
        top_at.append(len(lines))
        lines.append(border("┌", "┐", "┴" if i else None, "─ " + name + " "))
        lines.append(row("  " + role))
        for k, (key, val) in enumerate(items):
            br = "└─" if k == len(items) - 1 else "├─"
            lines.append(row("    " + br + " " + pad(key, KEY_W) + val))
        bot_at.append(len(lines))
        lines.append(border("└", "┘", "┬" if i < len(layers) - 1 else None))
        if i < len(layers) - 1:
            lines.append(" " * J + "│")
            lines.append(" " * J + "▼")

    def brace(group: str, a: int, b: int) -> None:
        for i in range(a, b + 1):
            gap = " " * (BRACE - w(lines[i]))
            if i == a:
                lines[i] += gap + "╭─ " + group
            elif i == b:
                lines[i] += gap + "╰──"
            else:
                lines[i] += gap + "│"

    brace("应用与结构", top_at[0], bot_at[1])   # L4 + L3
    brace("全书的地基", top_at[2], bot_at[4])   # L2 + L1 + L0
    return lines


# ---------- ch00 block1：控制线与鲁棒性对照 ----------
def fig_control_split() -> list[str]:
    L = [center("模型精确 ←──────────────────────────→ 模型有不确定性", 72), ""]
    left = box(["LQR / LQG", "MPC", "极点配置"], 26)
    right = box(["H∞ / μ / 小增益", "鲁棒 MPC", "LMI 综合"], 26)
    gap = " " * 16
    mid = "  ←── 折中 ──→  "
    for i in range(5):
        g = mid if i == 2 else gap
        L.append("      " + left[i] + g + right[i])
    L.append("")
    L.append(" " * 20 + "↑" + " " * 44 + "↑")
    L.append(" " * 15 + "最优性理论" + " " * 34 + "鲁棒性理论")
    L.append(" " * 13 + "(变分法 / HJB)" + " " * 25 + "(算子范数 / 频域不等式)")
    return L


# ---------- ch00 block2：每章统一结构 ----------
def fig_chapter_skeleton() -> list[str]:
    items = [
        ("① 核心概念", "是什么、为什么需要它、它排除掉了什么"),
        ("② 关键方法", "怎么算、有哪几条路线、何时用哪条"),
        ("③ 重要公式", "结论的精确陈述 + 成立条件"),
        ("④ 典型应用", "在信号 / 控制 / 学习中的具体落点"),
    ]
    inner = 66
    out = ["┌" + "─" * inner + "┐"]
    for i, (a, b) in enumerate(items):
        out.append("│ " + pad(a + "   " + b, inner - 2) + " │")
        if i < len(items) - 1:
            out.append("├" + "─" * inner + "┤")
    out.append("└" + "─" * inner + "┘")
    return out


# ---------- ch01 block0：六种积分武器的战术顺序 ----------
def fig_weapons() -> list[str]:
    def row(tag, items):
        return "  " + pad(tag, 26) + "  →  ".join(items)
    return [
        row("前三招（多数情况够用）", ["① 化简查表", "② 对称性", "③ 换元"]),
        row("后三招（需要技巧）", ["④ 分部", "⑤ 部分分式", "⑥ 参数化"]),
        "  " + "─" * 68,
        "  六招全部失败时，转入第 1.5 节的决策树后半段：",
        "  " + pad("", 4) + "特殊函数 (1.3) → 级数展开 (第 5 章 5.4 / 第 31 章 31.7) → 留数围道 (5/30 章)",
        "  " + pad("", 4) + "→ 数值积分 (第 32 章) → 渐近与界估计 (第 30、33 章)",
    ]


# ---------- ch01 block1：费曼技巧操作步骤 ----------
def fig_feynman() -> list[str]:
    return [
        "  ① 找出被积函数里那个「碍事的常数」 a",
        "  ② 把它升级为参数 t：  I(a) → I(t)",
        "  ③ 对 t 求导，让最复杂的因子被微分掉",
        "  ④ 算出 I'(t)（此时积分通常已变简单）",
        "  ⑤ 对 t 积分回去，用某个已知的 t 值定常数",
    ]


# ---------- ch01 block2：特殊函数的产生逻辑 ----------
def fig_special_fn() -> list[str]:
    return [
        "  一个积分算不出来",
        "        │",
        "        ▼",
        "  给它起个名字（Gamma / erf / Si / Bessel / 椭圆积分 …）",
        "        │",
        "        ▼",
        "  研究它的性质：递推关系 · 渐近展开 · 特殊值 · 与初等函数的联系",
        "        │",
        "        ▼",
        "  性质足够多之后，它就成了一件可以反复使用的工具",
    ]


# ---------- ch01 block3：积分决策树 ----------
def fig_decision_tree() -> list[str]:
    steps = [
        ("第 0 步", "收敛性检查", "两类反常积分 / 拼接原则 / p 标尺（第 2 章）"),
        ("第 1 步", "化简与查表", "代数化简 · 三角恒等 · 拆项 · 提常数"),
        ("第 2 步", "对称性", "奇偶 · 区间反射 · 周期性 · 配对 x→1/x, x→a-x"),
        ("第 3 步", "换元", "三角/双曲代换 · t=e^x · 雅可比 · 反代换 t=1/x"),
        ("第 4 步", "分部", "LIATE 原则 · 振荡消去 · 造递推关系"),
        ("第 5 步", "部分分式", "有理函数必定可解；配平方读出衰减振荡"),
        ("第 6 步", "参数化 / 费曼", "把难积分嵌入一个可解的微分方程"),
        ("第 7 步", "特殊函数登记", "Gamma · Beta · erf · Si/Ci/Ei · Bessel · 椭圆"),
        ("第 8 步", "级数展开", "逐项积分后求和（小参数、局部行为，第 5 章 5.4 / 31.7）"),
        ("第 9 步", "留数围道", "有理式 / 三角有理式 / 含 e^{iax}（第 5、30 章）"),
        ("第10 步", "数值积分", "Gauss–Legendre · 自适应 · Monte Carlo（第 32 章）"),
        ("第11 步", "渐近与界估计", "Laplace 方法 · 鞍点法 · 集中不等式（第 30、33 章）"),
    ]
    inner = 70
    out = []
    out.append("                      ┌" + "─" * 34 + "┐")
    out.append("                      │ " + pad("拿到积分 I = ∫ f(x) dx", 32) + " │")
    out.append("                      └" + "─" * 34 + "┘")
    out.append("                                      ▼")
    for i, (tag, name, desc) in enumerate(steps):
        out.append("  " + pad(tag, 9) + "┌" + "─" * inner + "┐")
        out.append("  " + " " * 9 + "│ " + pad(name + "：" + desc, inner - 2) + " │")
        out.append("  " + " " * 9 + "└" + "─" * inner + "┘")
        if i < len(steps) - 1:
            out.append("  " + " " * 9 + " " * (2 + (inner - 2) // 2) + "▼")
    out.append("")
    out.append("  注：第 0 步若判出发散，直接终止——问题本身无意义，不必继续。")
    return out


# ---------- ch02 block0：反常积分求解流程 ----------
def fig_improper_flow() -> list[str]:
    return [
        "  ① 找奇点",
        "       不同区间的端点、内部奇点、无穷远点，一个都不能漏",
        "       │",
        "       ▼",
        "  ② 拼接分段",
        "       每个奇点单独处理：∫_a^c  +  ∫_c^b，任一段发散则整体发散",
        "       │",
        "       ▼",
        "  ③ 局部展开",
        "       在奇点附近做渐近展开  f(x) ~ C·|x-c|^{-α}",
        "       │",
        "       ▼",
        "  ④ 套标尺",
        "       端点奇点：α < 1 收敛；无穷远：α > 1 收敛",
        "       │",
        "       ▼",
        "  ⑤ 全段收敛  当且仅当  每一段都收敛",
    ]


# ---------- ch05 block0：模板一 · 半圆围道 ----------
def fig_contour_semicircle() -> list[str]:
    ROWS, COLS = 14, 58
    cv = Canvas(ROWS, COLS)
    cx, ay, R, RV = 18, 11, 16, 9

    # 坐标轴：交点先画，线后画，避免覆盖
    cv.put(ay, cx, "┼")
    cv.put(0, cx, "↑")
    cv.vline(cx, 0, ROWS - 1)
    cv.hline(ay, 0, COLS - 2)
    cv.text(0, cx + 2, "Im z")
    cv.put(ay, COLS - 1, "→")
    cv.text(ay + 1, cx + 2, "Re z")

    # 上半大圆弧：逐行解圆方程取左右端点，保证严格对称
    for y in range(ay - RV, ay):
        d = (ay - y) / RV
        half = R * math.sqrt(max(0.0, 1 - d * d))
        cv.dot(y, cx - half, "·")
        cv.dot(y, cx + half, "·")

    cv.put(8, 11, "×"); cv.text(8, 12, "z1")
    cv.put(7, 24, "×"); cv.text(7, 25, "z2")

    cv.text(ay + 1, 1, "−R")
    cv.text(ay + 1, 34, "+R")
    cv.text(3, 33, "CR")
    cv.text(4, 33, "|z| = R")
    return cv.render() + [
        "",
        "  走向：沿实轴 −R → +R，再沿上半大圆弧 CR 回到 −R（逆时针）。",
        "  圆弧上 |f| 按 R 的负幂衰减、弧长按 R 增长，故需要 n > 1 才归零。",
    ]


# ---------- ch05 block1：模板二 · 矩形围道 ----------
def fig_contour_rect() -> list[str]:
    ROWS, COLS = 15, 62
    cv = Canvas(ROWS, COLS)
    L, Rt, TOP, AY = 14, 48, 3, 12

    cv.put(TOP, L, "┌"); cv.put(TOP, Rt, "┐")
    cv.hline(TOP, L + 1, Rt - 1)
    cv.vline(L, TOP + 1, AY - 1)
    cv.vline(Rt, TOP + 1, AY - 1)
    cv.put(AY, L, "┴"); cv.put(AY, Rt, "┴")
    cv.hline(AY, 0, COLS - 2)
    cv.put(AY, COLS - 1, "→")

    cv.text(2, 18, "上边  z = x + iY")
    cv.text(7, 0, "z = −R + iy")
    cv.text(7, 50, "z = R + iy")
    cv.text(AY + 1, 18, "下边（实轴）")

    cv.put(9, 22, "×"); cv.text(9, 23, "z1")
    cv.put(7, 36, "×"); cv.text(7, 37, "z2")

    return cv.render() + [
        "",
        "  走向：下边 −R → +R → 右边 → 上边 z = x + iY → 左边 → 回到 −R。",
        "  上边上函数是否衰减，取决于 e^{iaz} 的模 e^{−aY}：a > 0 时须取 Y > 0。",
        "  矩形围道专治「实轴上有极点」与「e^{iaz} 型积分上限为无穷」两类问题。",
    ]


# ---------- ch05 block2：模板三 · 扇形围道 ----------
def fig_contour_sector() -> list[str]:
    ROWS, COLS = 14, 60
    cv = Canvas(ROWS, COLS)
    ox, oy, R, K = 10, 11, 24, 0.45       # K：纵向压缩系数（字符格高宽比约 2:1）
    th = math.radians(60)

    cv.hline(oy, ox, COLS - 2)
    cv.put(oy, COLS - 1, "→")
    cv.text(oy + 1, 22, "沿正实轴进入")

    for c in range(ox + 1, 23):           # 射线 θ = 2π/n
        cv.dot(oy - (c - ox) * 0.75, c, "·")
    for i in range(81):                    # 半径 R 的圆弧
        t = th * i / 80
        cv.dot(oy - R * math.sin(t) * K, ox + R * math.cos(t), "·")

    cv.put(7, 26, "×"); cv.text(7, 27, "z0")
    cv.text(4, 0, "θ = 2π/n")
    cv.text(3, 37, "大圆弧  z = R e^{iθ}")
    return cv.render() + [
        "",
        "  走向：正实轴 O → R，再沿半径 R 的弧逆时针转 2π/n，最后沿射线 θ = 2π/n 回到 O。",
        "  适用：被积函数含 x^{a−1} / log x 等多值因子，必须靠「角度开缝」把多值性锁住。",
    ]


# ---------- ch05 block3：模板四 · 钥匙孔围道 ----------
def fig_contour_keyhole() -> list[str]:
    ROWS, COLS = 14, 60
    cv = Canvas(ROWS, COLS)
    ox, oy, R, RV, re, rv = 18, 8, 16, 8, 4, 2
    d = 0.35                               # 外圆在正实轴处留出的缝

    for i in range(161):                   # 外圆 CR（正实轴处开口）
        t = d + (2 * math.pi - 2 * d) * i / 160
        cv.dot(oy - RV * math.sin(t), ox + R * math.cos(t), "·")
    for i in range(49):                    # 内圆 Cε（同样开口）
        t = d + (2 * math.pi - 2 * d) * i / 48
        cv.dot(oy - rv * math.sin(t), ox + re * math.cos(t), "·")

    for c in range(2, COLS - 1):           # 实轴
        cv.dot(oy, c, "·")
    cv.put(oy, COLS - 1, "→")
    cv.hline(oy - 1, ox + re, ox + R - 3, "─")     # L+（上半割缝）
    cv.hline(oy + 1, ox + re, ox + R - 3, "─")     # L−（下半割缝）

    cv.text(0, 25, "CR")
    cv.text(11, 12, "Cε（半径 ε）")
    cv.text(6, 25, "L+")
    cv.text(10, 25, "L−")
    return cv.render() + [
        "",
        "  走向：L+ 由 ε 走到 R（向右）→ CR 逆时针一整圈 → L− 由 R 回到 ε（向左）。",
        "  上下两条割缝上的积分并不抵消：因为 f 多值，z = x + i0⁺ 与 z = x − i0⁻ 相差一个因子。",
    ]


# ---------- ch05 block4：模板五 · 缩进围道 ----------
def fig_contour_indent() -> list[str]:
    ROWS, COLS = 12, 58
    cv = Canvas(ROWS, COLS)
    ox, oy, R, RV, eps = 20, 9, 17, 7, 4

    for y in range(oy - RV, oy):           # 上半大圆弧
        d = (oy - y) / RV
        half = R * math.sqrt(max(0.0, 1 - d * d))
        cv.dot(y, ox - half, "·")
        cv.dot(y, ox + half, "·")

    cv.hline(oy, ox - R, ox - eps, "─")    # 左侧实轴段
    cv.hline(oy, ox + eps, ox + R, "─")    # 右侧实轴段
    for i in range(61):                    # 绕过奇点的小半圆（下凹）
        t = math.pi * i / 60
        cv.dot(oy + 2 * math.sin(t), ox - eps * math.cos(t), "·")

    cv.put(oy, ox, "×")
    cv.text(oy + 1, ox - 7, "−ε")
    cv.text(oy + 1, ox + 5, "+ε")
    cv.text(oy + 1, ox - R + 1, "−R")
    cv.text(oy + 1, ox + R - 1, "+R")
    cv.text(2, 30, "大圆弧 CR")
    return cv.render() + [
        "",
        "  走向：沿实轴 −R → −ε → 绕奇点走半径 ε 的小半圆（下凹）→ 实轴 +ε → +R → 大圆弧回 −R。",
        "  × 是落在实轴上的奇点；小半圆上的积分不趋于零，而是贡献 ±iπ·Res（半留数）。",
    ]


# ======================================================================
# ch06：泛函分析
# ======================================================================

def _frame(cv, r0, c0, r1, c1):
    """在画布上画一个方框；先落四角，再连边（避免角点被边线占用）。"""
    cv.put(r0, c0, "┌"); cv.put(r0, c1, "┐")
    cv.put(r1, c0, "└"); cv.put(r1, c1, "┘")
    cv.hline(r0, c0 + 1, c1 - 1)
    cv.hline(r1, c0 + 1, c1 - 1)
    cv.vline(c0, r0 + 1, r1 - 1)
    cv.vline(c1, r0 + 1, r1 - 1)


# ---------- ch06 block0：三层结构（度量 ⊃ 赋范 ⊃ 内积） ----------
def fig_space_hierarchy() -> list[str]:
    ROWS, COLS = 17, 74
    cv = Canvas(ROWS, COLS)
    for r0, c0, r1, c1 in ((0, 0, 16, 71), (4, 4, 15, 67), (8, 8, 13, 63)):
        _frame(cv, r0, c0, r1, c1)

    cv.text(1, 3, "度量空间 (X, d)")
    cv.text(2, 3, "有距离 d(x,y)  →  能谈收敛、Cauchy 列、完备性、紧性")
    cv.text(5, 7, "赋范空间 (X, ‖·‖)")
    cv.text(6, 7, "d(x,y)=‖x−y‖  →  能谈有界算子、算子范数、对偶空间")
    cv.text(9, 11, "内积空间 (X, 〈·,·〉)")
    cv.text(10, 11, "‖x‖=√〈x,x〉  →  能谈正交、投影、基、伴随算子")
    cv.text(12, 11, "再加完备性  →  希尔伯特空间 H")
    cv.text(14, 7, "再加完备性  →  巴拿赫空间")
    return cv.render()


# ---------- ch06 block1：投影定理 ----------
def fig_projection() -> list[str]:
    ROWS, COLS = 13, 64
    cv = Canvas(ROWS, COLS)
    ax, ay = 10, 8

    cv.text(0, 2, "H（希尔伯特空间）")
    cv.put(2, ax, "●")
    cv.text(2, ax + 3, "x 属于 H")
    cv.vline(ax, 3, ay - 1, "┆")
    cv.text(4, ax + 4, "x − y0 与 M 垂直")

    cv.put(ay, ax, "●")                 # 先落交点
    cv.hline(ay, 0, 48)                 # 后画子空间轴线（自动跳过交点）
    cv.text(ay, 50, "M（闭子空间）")
    cv.text(ay + 1, ax, "y0 = P_M x   ← 最佳逼近元（垂足）")

    cv.text(10, 2, "几何：y0 是 x 在 M 上的垂足")
    cv.text(11, 2, "代数：〈x − y0, m〉 = 0   对一切 m 属于 M")
    cv.text(12, 2, "变分：‖x − y0‖ = min ‖x − y‖")
    return cv.render()


# ---------- ch06 block2：截断误差 ----------
def fig_truncation() -> list[str]:
    ROWS, COLS = 11, 64
    cv = Canvas(ROWS, COLS)
    ax, ay = 8, 6

    cv.put(0, ax, "●")
    cv.text(0, ax + 3, "x 属于 H")
    cv.vline(ax, 1, ay - 1, "┆")
    cv.text(1, ax + 4, "残差 = ‖x − x_N‖")

    cv.put(ay, ax, "●")
    cv.hline(ay, 0, 30)
    cv.text(ay, 32, "M = span{e1,…,e_N}")
    cv.text(ay + 1, ax - 4, "x_N = P_M x")

    cv.text(8, 2, "截断误差：‖x − x_N‖² = Σ_{n>N} |〈x,e_n〉|²  （单调递减 → 0）")
    return cv.render()


# ---------- ch06 block3：紧算子把无限维拉回有限维 ----------
def fig_compact() -> list[str]:
    ROWS, COLS = 7, 68
    cv = Canvas(ROWS, COLS)
    panels = [
        (0, "有限维世界", ["单位球紧", "有收敛子列", "谱定理成立"]),
        (18, "紧算子 T", ["有界集 →", "相对紧集", "谱可数离散"]),
        (36, "无限维世界", ["单位球不紧", "无收敛子列", "谱可能连续"]),
    ]
    for c0, title, items in panels:
        cv.text(0, c0 + 1 + (10 - w(title)) // 2, title)
        _frame(cv, 1, c0, 5, c0 + 11)
        for i, it in enumerate(items):
            cv.text(2 + i, c0 + 1, it)
    for c in (14, 32):
        cv.text(3, c, "←")
    return cv.render()


# ---------- ch06 block4：强弱收敛 ----------
def fig_convergence() -> list[str]:
    ROWS, COLS = 10, 72
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "① 强收敛")
    cv.text(0, 11, "──→")
    cv.text(0, 15, "② 弱收敛")
    cv.text(0, 24, "──→")
    cv.text(0, 28, "③ 弱*收敛")

    c1, c2 = 6, 19
    cv.put(1, c1, "↑"); cv.put(1, c2, "↑")
    cv.put(2, c1, "│"); cv.put(2, c2, "│")
    cv.text(2, c2 + 4, "升级路径（需额外条件）")
    cv.put(3, c1, "└"); cv.put(3, c2, "┘")
    cv.hline(3, c1 + 1, c2 - 1)

    cv.text(4, c1 + 1, "② + ‖x_n‖ → ‖x‖   →   ①")
    cv.text(5, c1 + 1, "有限维时  ① 与 ② 等价")
    cv.text(7, 2, "反例（ℓ²）：e_n 弱收敛于 0（属于 ②），但 ‖e_n‖ = 1 不趋于 0，")
    cv.text(8, 2, "所以 e_n 不收敛于 0 —— ① 不成立。弱收敛推不出强收敛。")
    return cv.render()


# ---------- ch06 block5：有限维 vs 无限维谱定理 ----------
def fig_spectrum() -> list[str]:
    ROWS, COLS = 8, 80
    cv = Canvas(ROWS, COLS)
    L, R = 2, 36

    cv.text(0, L, "有限维  A = A^T")
    cv.text(0, R, "无限维  T = T*（紧）")
    cv.hline(1, L, 64)

    cv.text(2, L, "A = Σ_i λ_i u_i u_i^T")
    cv.text(2, R, "T = Σ_n λ_n〈·,e_n〉e_n")
    cv.text(3, L, "λ_i 至多 n 个，可任意大")
    cv.text(3, R, "λ_n → 0（必须趋于 0！）")
    cv.text(4, L, "特征向量构成 R^n 的基")
    cv.text(4, R, "{e_n} 构成 H 的规范正交基")
    cv.text(5, L, "谱半径 = ‖A‖")
    cv.text(5, R, "‖T‖ = max|λ_n|")

    for r in range(2, 6):
        cv.text(r, 30, "→")
    return cv.render()


# ---------- ch06 block6：正定核的 Gram 矩阵 ----------
def fig_kernel_matrix() -> list[str]:
    ROWS, COLS = 6, 66
    cv = Canvas(ROWS, COLS)
    sub = "₀₁₂₃₄₅₆₇₈₉"

    cv.text(0, 2, "核矩阵视角（工程最常用）：")
    labels = ["x₁", "x₂", "x₃"]
    for j, lb in enumerate(labels):
        cv.text(2, 13 + 8 * j, lb)
    for i, lb in enumerate(labels):
        cv.text(3 + i, 4, lb)
        cv.put(3 + i, 9, "[")
        cv.put(3 + i, 31, "]")
        for j in range(3):
            cv.text(3 + i, 11 + 8 * j, "K" + sub[i + 1] + sub[j + 1])

    return cv.render() + [
        "  →  所有这样的矩阵都必须半正定 —— 这是「相似度函数」的合法性门槛：",
        "     核不能乱选，它必须处处满足这一条（Moore–Aronszajn 保证它有对应的希尔伯特空间）。",
    ]


# ======================================================================
# ch07 —— 概率论进阶与条件期望
# ======================================================================

# ---------- ch07 block0：条件期望 = L² 投影 ----------
def fig_cond_exp_proj() -> list[str]:
    ROWS, COLS = 13, 76
    cv = Canvas(ROWS, COLS)
    ax, ay = 22, 8

    cv.text(0, 2, "H = L²（全体平方可积的随机变量）")
    cv.put(2, ax, "●")
    cv.text(2, ax + 3, "X（真实未知量，待估计）")
    cv.vline(ax, 3, ay - 1, "┆")
    cv.text(4, ax + 4, "残差 X − E[X|G]  与子空间 M 整体垂直")

    cv.put(ay, ax, "●")                 # 先落交点
    cv.hline(ay, 4, 58)                 # 后画子空间轴线（自动跳过交点）
    cv.text(ay, 60, "M = L²(G)")

    cv.text(ay + 2, ax - 10, "E[X|G] = P_M X   最佳均方预测（垂足）")

    cv.text(11, 2, "几何：E[X|G] 是 X 在 M 上的垂足")
    cv.text(12, 2, "代数：E[(X − E[X|G])·g] = 0   对一切 G-可测的有界 g")
    return cv.render() + [
        "  变分：E[X|G] = arg min E[(X − g)²]   约束 g 只能依赖 G 的信息",
        "  三种写法等价；几何用于理解，积分形式（代数）用于证明，并可放宽到 X 只 L¹。",
    ]


# ---------- ch07 block1：四种收敛模式 ----------
def fig_conv_modes() -> list[str]:
    ROWS, COLS = 12, 80
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "① 几乎必然 a.s.")
    cv.hline(0, 18, 24)
    cv.put(0, 25, "┐")

    cv.put(1, 25, "├")
    cv.hline(1, 26, 27)
    cv.put(1, 28, "→")
    cv.text(1, 30, "③ 依概率 P")
    cv.hline(1, 41, 44)
    cv.put(1, 45, "→")
    cv.text(1, 47, "④ 依分布 d")

    cv.text(2, 2, "② L^p（均方）")
    cv.hline(2, 16, 24)
    cv.put(2, 25, "┘")

    cv.text(4, 2, "逐条看「为什么」：")
    cv.text(5, 4, "② → ③    Markov 不等式：P(|X_n − X| > eps) <= E|X_n − X|^p / eps^p")
    cv.text(6, 4, "① → ③    截断 P(并集) <= 求和 P(单个)，再令 n → 无穷")
    cv.text(7, 4, "③ → ①    取子列即可；整个序列须 Borel–Cantelli：求和 P(|X_n−X|>eps) 有限")
    cv.text(8, 4, "③ → ②    需「一致可积」（Vitali 定理）；① + 可积控制也算（控制收敛定理）")
    cv.text(9, 4, "③ → ④    恒成立。反过来不成立：X 与 −X 同分布满足 ④，但 2|X| 不收敛")
    cv.text(10, 4, "① 推不出 ②   反例 X_n = n·1_(0,1/n)：a.s. 收敛到 0，但 E|X_n| = 1 不趋于 0")
    return cv.render()


# ---------- ch07 block2：过滤族与鞅 ----------
def fig_filtration() -> list[str]:
    ROWS, COLS = 12, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "信息随时间单调增加（过滤族 F_0 ─→ F_1 ─→ … ─→ F）：")
    cv.text(1, 4, "F_0")
    cv.text(1, 10, "──→")
    cv.text(1, 14, "F_1")
    cv.text(1, 20, "──→")
    cv.text(1, 24, "F_2")
    cv.text(1, 30, "──→")
    cv.text(1, 34, "...")
    cv.text(1, 40, "──→")
    cv.text(1, 44, "F")

    for c in (5, 15, 25, 44):
        cv.put(2, c, "│")

    cv.text(3, 1, "E[X|F_0]")
    cv.text(3, 11, "E[X|F_1]")
    cv.text(3, 21, "E[X|F_2]")
    cv.text(3, 44, "X")
    cv.text(4, 2, "（粗）")
    cv.text(4, 12, "（中）")
    cv.text(4, 22, "（细）")
    cv.text(4, 44, "（全）")

    cv.text(6, 2, "塔性质：E[ E[X|F_2] | F_1 ] = E[X|F_1]")
    cv.text(7, 2, "粗信息推不出细信息的内容 —— 信息只会丢，不会凭空产生。")
    cv.text(8, 2, "（递归估计与动态规划的共同技术核心：不能让粗糙的信息层「倒推」出细节。）")

    cv.text(10, 2, "鞅：    E[ M_t | F_s ] = M_s   （s <= t）      投影回自身 —— 公平赌博")
    cv.text(11, 2, "鞅差：  E[ e_t | F_{t-1} ] = 0                 投影落到 0 —— 不可预测的增量")
    return cv.render() + [
        "",
        "  Doob 不等式把「某时刻超界」升级为「所有时刻的最大值超界」，是鞅型集中不等式的起点。",
    ]


# ---------- ch07 block3：全方差公式拆成树 ----------
def fig_total_var() -> list[str]:
    ROWS, COLS = 11, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 20, "Var(X)")
    cv.text(1, 20, "总方差")
    cv.put(2, 22, "│")
    cv.put(3, 8, "┌")
    cv.hline(3, 9, 21)
    cv.put(3, 22, "┴")
    cv.hline(3, 23, 35)
    cv.put(3, 36, "┐")

    cv.text(4, 2, "E[ Var(X|G) ]")
    cv.text(4, 30, "Var( E[X|G] )")
    cv.text(5, 4, "组内方差")
    cv.text(5, 32, "组间方差")
    cv.text(6, 1, "不可消除的噪声")
    cv.text(6, 28, "模型能抓住的部分")

    cv.text(8, 2, "落地（取 G = 训练集）：E[(Y − f(X))²] = E[Var(Y|X)] + 偏差² + 方差")
    cv.text(9, 2, "第一项与 f 无关 —— 它就是任何模型都无法突破的误差下界（贝叶斯误差）。")
    cv.text(10, 2, "Rao–Blackwell：Var( E[θ|T] ) <= Var(θ) —— 换成条件期望，方差只会降。")
    return cv.render()


# ======================================================================
# ch08 —— 高维概率与集中不等式
# ======================================================================

# ---------- ch08 block0：三种界的数值对照 ----------
def fig_tail_compare() -> list[str]:
    ROWS, COLS = 12, 74
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "n = 10000，X_k 独立且落在 [0,1] 内，真实方差 0.01")
    cv.text(1, 2, "（Hoeffding 用的等效方差是 0.25，比真实方差大 25 倍）")

    cv.text(3, 4, "eps")
    cv.text(3, 12, "Chebyshev")
    cv.text(3, 26, "Hoeffding")
    cv.text(3, 40, "Bernstein")
    cv.hline(4, 3, 48)
    for i, (a, b, c, d) in enumerate([
        ("0.05", "4.0e-04", "3.9e-22", "1.0e-204"),
        ("0.02", "2.5e-03", "6.7e-04", "1.0e-52"),
        ("0.01", "1.0e-02", "2.7e-01", "5.0e-17"),
    ]):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 12, b)
        cv.text(r, 26, c)
        cv.text(r, 40, d)
    cv.hline(8, 3, 48)

    cv.text(9, 2, "读法：Chebyshev 几乎不提供信息（因为只用了方差，丢掉了指数衰减）；")
    cv.text(10, 2, "Hoeffding 在偏差小时失效（它把 [0,1] 当成最坏分布）；")
    return cv.render() + [
        "  Bernstein 全程可用 —— 因为分母里的 n·sigma^2 用的是真实方差（低方差时优势极大）。",
    ]


# ---------- ch08 block1：薄壳现象 ----------
def fig_thin_shell() -> list[str]:
    ROWS, COLS = 13, 74
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "单位球体积的分布：内层 (1 − eps) 球占总体积的比例 = (1 − eps)^n")
    cv.text(2, 4, "维数 n")
    cv.text(2, 16, "(0.9)^n")
    cv.text(2, 32, "结论")
    cv.hline(3, 3, 62)
    for i, (a, b, c) in enumerate([
        ("3", "0.729", "外层 10% 只占 27%"),
        ("10", "0.349", "外层 10% 占 65%"),
        ("100", "2.7e-05", "外层 10% 占 99.997%"),
        ("1000", "1.7e-46", "内层几乎无体积"),
    ]):
        r = 4 + i
        cv.text(r, 5, a)
        cv.text(r, 16, b)
        cv.text(r, 32, c)
    cv.hline(8, 3, 62)

    cv.text(10, 2, "结论：高维球的体积几乎全在外层薄壳上 —— 这就是「薄壳现象」。")
    cv.text(11, 2, "另一面：随机点的长度是 sqrt(n) 量级，绝对波动只有 O(1)、相对波动只有 1/sqrt(n)。")
    return cv.render()


# ---------- ch08 block2：Johnson–Lindenstrauss 随机投影 ----------
def fig_jl_projection() -> list[str]:
    ROWS, COLS = 12, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "R^d（原始维数，d 可以极大）")
    cv.text(0, 40, "R^m（m 约等于 8·log N / eps^2，与 d 无关）")

    cv.put(2, 6, "●");  cv.text(2, 8, "x1")
    cv.put(4, 2, "●");  cv.text(4, 4, "x2")
    cv.put(5, 12, "●"); cv.text(5, 14, "x3")
    cv.put(7, 6, "●");  cv.text(7, 8, "x4")

    cv.text(4, 24, "── A ──→")

    cv.put(2, 48, "●"); cv.text(2, 50, "A x1")
    cv.put(4, 44, "●"); cv.text(4, 46, "A x2")
    cv.put(5, 54, "●"); cv.text(5, 56, "A x3")
    cv.put(7, 48, "●"); cv.text(7, 50, "A x4")

    cv.text(9, 2, "A = (1/sqrt(m))·G，G 是随机矩阵（高斯或 Rademacher），以高概率满足：")
    cv.text(10, 2, "对一切 i, j：(1 − eps)|xi − xj|^2 <= |A xi − A xj|^2 <= (1 + eps)|xi − xj|^2")
    return cv.render() + [
        "  证明要点：|A x|^2 = (1/m)·求和_k 〈g_k, x〉^2 —— m 项独立，相对误差 O(1/sqrt(m))；",
        "  再对 C(N,2) 个点对取 union bound，于是多出因子 log N。",
    ]


# ---------- ch08 block3：三种复杂度度量 ----------
def fig_complexity_measures() -> list[str]:
    ROWS, COLS = 11, 78
    cv = Canvas(ROWS, COLS)

    for r0, c0, r1, c1 in ((0, 2, 3, 15), (0, 20, 3, 33), (0, 38, 3, 55)):
        _frame(cv, r0, c0, r1, c1)

    cv.text(1, 6, "覆盖数")
    cv.text(2, 6, "N(eps)")
    cv.text(1, 23, "高斯宽度")
    cv.text(2, 25, "w(T)")
    cv.text(1, 42, "Rademacher")
    cv.text(2, 40, "复杂度 R_n(F)")

    cv.text(4, 3, "几何、直观")
    cv.text(4, 21, "上界工具多")
    cv.text(4, 39, "数据依赖、可加")

    cv.text(6, 6, "Sudakov 给下界、Dudley 给上界、Lipschitz 比较打通统计侧")
    cv.text(7, 6, "三者同阶 —— 哪个好算就用哪个（这一点是选择度量的全部依据）")

    cv.text(9, 12, "泛化界：eps <= 2 R_n(F) + sqrt( 2 log(1/delta) / n )")
    return cv.render()


# ---------- ch08 block4：泛化界的三步装配 ----------
def fig_gen_bound_pipeline() -> list[str]:
    ROWS, COLS = 13, 78
    cv = Canvas(ROWS, COLS)

    _frame(cv, 0, 2, 8, 68)
    for r in (3, 6):
        cv.put(r, 2, "├")
        cv.put(r, 68, "┤")
        cv.hline(r, 3, 67)

    cv.text(1, 4, "① 对称化   经验风险 − 真实风险  →  两份独立样本之差")
    cv.text(2, 4, "再引入 Rademacher 变量（用到第 7 章的独立性与对称性）")
    cv.text(4, 4, "② 集中      n 项平均 + Hoeffding / McDiarmid → exp(−nt^2/2)")
    cv.text(7, 4, "③ 复杂度    R_n(F) ← 覆盖数 / 高斯宽度 / VC 维")

    cv.put(10, 35, "↓")
    cv.text(11, 10, "泛化界：R(f) <= R_hat(f) + 2 R_n(F) + sqrt( 2 log(1/delta) / n )")
    return cv.render() + [
        "  左边两项来源不同：复杂度项与 delta 无关（改模型才能降），",
        "  置信项与假设空间无关（加样本即可降，代价只有 log）。",
    ]


# ======================================================================
# ch09：随机过程与随机分析
# ======================================================================

def _frame_cols(cv, r0, c0, r1, c1, col_xs=(), div_rows=()):
    """带「竖直分列」与「横分隔」的表框。

    顺序很重要：先落交点（┼ ├ ┤），再画横线，再画竖线，最后落边框 ——
    Canvas.put 遇已占用格会静默跳过，因此这个顺序才能得到正确的连接符。
    """
    for r in div_rows:
        for x in col_xs:
            cv.put(r, x, "┼")
        cv.put(r, c0, "├")
        cv.put(r, c1, "┤")
        cv.hline(r, c0 + 1, c1 - 1)
    for x in col_xs:
        cv.vline(x, r0 + 1, r1 - 1)
    cv.put(r0, c0, "┌"); cv.put(r0, c1, "┐")
    cv.put(r1, c0, "└"); cv.put(r1, c1, "┘")
    cv.hline(r0, c0 + 1, c1 - 1)
    cv.hline(r1, c0 + 1, c1 - 1)
    cv.vline(c0, r0 + 1, r1 - 1)
    cv.vline(c1, r0 + 1, r1 - 1)


# ---------- ch09 block0：二次变差 ----------
def fig_quad_variation() -> list[str]:
    ROWS, COLS = 13, 74
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "把 [0,1] 上的布朗路径切成 n 段，看二次变差的和 S_n = sum (dB_i)^2：")
    _frame(cv, 2, 2, 9, 70)
    cv.text(3, 4, "n")
    cv.text(3, 12, "E[S_n]")
    cv.text(3, 24, "Var[S_n] = 2t^2/n")
    cv.text(3, 48, "sd[S_n]")
    cv.text(3, 58, "E[sum|dB|]")
    cv.hline(4, 3, 69)
    rows = [("10",   "1.000", "0.2",   "0.447",   "2.52"),
            ("100",  "1.000", "0.02",  "0.141",   "7.98"),
            ("10^4", "1.000", "2e-04", "0.0141",  "79.8"),
            ("10^6", "1.000", "2e-06", "0.00141", "798")]
    for i, (a, b, c, d, e) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 12, b)
        cv.text(r, 24, c)
        cv.text(r, 48, d)
        cv.text(r, 58, e)

    cv.text(10, 2, "二阶量：期望恒为 t（与 n 无关），方差按 2t^2/n 收缩，故 S_n 收敛到确定值 t；")
    cv.text(11, 2, "一阶量：E[sum|dB|] = sqrt(2n/pi) 随 n 发散 —— 布朗路径不是有界变差函数。")
    return cv.render() + [
        "  结论：二次变差有限、一次变差无穷 —— 布朗运动卡在「可积分」与「不可积分」之间，",
        "  这正是 Itô 积分可以定义、而逐路径的 Riemann-Stieltjes 积分不能定义的原因（9.4.1 节）。",
    ]


# ---------- ch09 block1：Donsker 尺度 ----------
def fig_donsker_scaling() -> list[str]:
    ROWS, COLS = 14, 74
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "随机游走 S_n 的波动尺度随 n 的变化（单步标准差为 1）：")
    _frame(cv, 2, 2, 8, 72)
    cv.text(3, 4, "n")
    cv.text(3, 14, "sd[S_n] = sqrt(n)")
    cv.text(3, 36, "sd[S_n / n]")
    cv.text(3, 54, "sd[S_n / sqrt(n)]")
    cv.hline(4, 3, 71)
    rows = [("100",  "10",   "0.1",   "1"),
            ("10^4", "100",  "0.01",  "1"),
            ("10^6", "1000", "0.001", "1")]
    for i, (a, b, c, d) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 14, b)
        cv.text(r, 36, c)
        cv.text(r, 54, d)

    cv.text(10, 2, "除以 n：波动趋于 0（大数定律）。")
    cv.text(11, 2, "不归一化：波动发散到无穷。")
    cv.text(12, 2, "除以 sqrt(n)：波动锁定在 1 —— 唯一「有限且非零」的标度，故而能收敛。")
    return cv.render() + [
        "  极限过程的波动尺度天然是 sqrt(时间)，这就是 Donsker 不变原理的 1/2 指数。",
        "  同一个 1/2 反复出现：CLT、集中不等式、OU 的相关、分数布朗运动（9.8.5 节）。",
    ]


# ---------- ch09 block2：Itô 乘法表与修正项 ----------
def fig_ito_correction() -> list[str]:
    ROWS, COLS = 12, 74
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Itô 乘法表")
    _frame_cols(cv, 1, 2, 5, 26, col_xs=(), div_rows=(3,))
    cv.text(2, 5, "x       dt       dB")
    cv.text(4, 5, "dt       0        0")
    cv.text(5, 5, "dB       0       dt")

    cv.text(0, 30, "它带来的差额")
    _frame_cols(cv, 1, 30, 5, 72, col_xs=(), div_rows=(3,))
    cv.text(2, 32, "经典（错）  int B dB = B^2 / 2")
    cv.text(4, 32, "Ito（对）   int B dB = (B^2 - t) / 2")
    cv.text(5, 32, "差额        t / 2")

    cv.text(7, 2, "差额 t/2 恰好等于 (1/2) sum (dB)^2 的极限 —— 这就是 Itô 修正项。")
    cv.text(8, 2, "一般形式：Ito 公式 = 经典链式法则 + (1/2) f'' (dB)^2，而 (dB)^2 -> dt。")
    cv.text(10, 2, "三条推论：漂移项多出 (1/2) sig^2 f''；")
    return cv.render() + [
        "  乘积法则多出协变差项 d[X,Y]；分部积分多出 [X,Y]。",
        "  三处「多出来」的东西全都是二次（协）变差 —— 记住这一条，不必分别背三个公式。",
    ]


# ---------- ch09 block3：SDE 家族表 ----------
def fig_sde_zoo() -> list[str]:
    ROWS, COLS = 12, 76
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "工程上最常用的四族 SDE（sig = sigma，th = theta，s2 = sigma^2）：")
    _frame_cols(cv, 1, 2, 8, 74, col_xs=(13, 41), div_rows=(3,))
    cv.text(2, 4, "名称")
    cv.text(2, 15, "SDE")
    cv.text(2, 43, "解 / 特点")
    rows = [("几何布朗", "dX = mu X dt + sig X dB",   "X0 exp((mu - s2/2) t + sig B)"),
            ("OU 过程",  "dX = -th X dt + sig dB",    "均值回复；Var -> s2/(2th)"),
            ("Langevin", "dX = -U'(X)dt + sq(2T)dB",  "稳态 p -> exp(-U/T)"),
            ("跳扩散",   "dX = b dt + sig dB + g dN", "尾部变厚；市场不完全")]
    for i, (a, b, c) in enumerate(rows):
        r = 4 + i
        cv.text(r, 4, a)
        cv.text(r, 15, b)
        cv.text(r, 43, c)

    cv.text(10, 2, "共同点：Girsanov 可以搬走漂移，Itô 公式可以求解；前两族有闭式解，后两族没有。")
    return cv.render() + [
        "  Langevin 是全书的枢纽：第 26 章的 SGLD 与第 29 章的扩散模型都是它的离散化或变形。",
    ]


# ---------- ch09 block4：生成元三角 ----------
def fig_gen_flow() -> list[str]:
    ROWS, COLS = 17, 76
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "生成元 L 是「随机过程」与「分析」之间的字典：")

    _frame_cols(cv, 1, 2, 3, 74)
    cv.text(2, 26, "SDE:  dX = b(X) dt + sig(X) dB")

    cv.put(3, 39, "┬")
    cv.put(4, 39, "│")
    cv.text(4, 42, "Ito 公式：取出漂移部分")
    cv.put(5, 39, "v")

    _frame_cols(cv, 6, 2, 8, 74)
    cv.text(7, 12, "生成元  L f = b f' + (1/2) a f''      （a = sig sig^T）")

    cv.put(8, 39, "┬")
    cv.put(9, 14, "┌"); cv.put(9, 63, "┐"); cv.put(9, 39, "┼")
    cv.hline(9, 15, 62)
    for x in (14, 39, 63):
        cv.put(10, x, "v")

    _frame_cols(cv, 11, 2, 15, 26)
    cv.text(12, 4, "① L f = 0")
    cv.text(13, 4, "f(X) 是鞅")
    cv.text(14, 4, "（漂移为零）")

    _frame_cols(cv, 11, 28, 15, 50)
    cv.text(12, 30, "② Dynkin 公式")
    cv.text(13, 30, "E[f(X_t)] = f(x)")
    cv.text(14, 30, "  + E[int Lf ds]")

    _frame_cols(cv, 11, 52, 15, 74)
    cv.text(12, 54, "③ 形式伴随 L*")
    cv.text(13, 54, "d_t p = L* p")
    cv.text(14, 54, "稳态 exp(-U/T)")

    cv.text(16, 2, "用法：判鞅与 Lyapunov（①）；算期望与首达时间（②）；算分布演化（③）。")
    return cv.render() + [
        "  ② 与 ③ 是同一个方程的两个方向：② 是倒向（终值条件），③ 是前向（初值条件）。",
        "  第 21 章给 ② 加一个 min 运算符，就得到 HJB 方程 —— 随机控制的全部骨架。",
    ]


# ---------- ch10 block0：估计量四大流派 ----------
def fig_est_zoo() -> list[str]:
    ROWS, COLS = 13, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "四条路线，四种「最优」的定义：")
    _frame_cols(cv, 1, 2, 8, 76, col_xs=(22, 50), div_rows=(3,))
    cv.text(2, 4, "路线")
    cv.text(2, 24, "最优性判据")
    cv.text(2, 52, "代表结论")
    rows = [
        ("无偏 · 精确", "方差最小（UMVUE）", "指数族 + 充分完备"),
        ("渐近 · 通用", "n 大时达到 CRLB", "MLE（Taylor + CLT）"),
        ("有偏 · 收缩", "MSE 最小（允许偏差）", "岭回归 / Lasso"),
        ("贝叶斯", "后验风险最小", "MAP = 先验 + 似然"),
    ]
    for i, (a, b, c) in enumerate(rows):
        r = 4 + i
        cv.text(r, 4, a)
        cv.text(r, 24, b)
        cv.text(r, 52, c)

    cv.text(10, 2, "偏差-方差：MSE = 偏差^2 + 方差。无偏把偏差锁死，CRLB 给出方差地板；")
    cv.text(11, 2, "放弃无偏 -> 按 lambda/(lambda+mu) 收缩，MSE 可以严格小于 OLS。")
    return cv.render()


# ---------- ch10 block1：Fisher 信息的三重身份 ----------
def fig_info_identity() -> list[str]:
    ROWS, COLS = 18, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Fisher 信息 I(theta) 的三个等价面孔（正则条件下）：")
    items = [
        ("1) 曲率      I = -E[ d^2 log p / dtheta^2 ]",
         "似然面在真值附近越陡 -> 参数被数据钉得越紧 -> 信息越多"),
        ("2) 得分方差  I = Var[ d log p / dtheta ]",
         "得分的波动幅度：单次观测平均能提供多少信息"),
        ("3) 局部 KL   KL(p+d , p) = (1/2) I d^2 + o(d^2)",
         "二阶展开的系数：给出估计精度的一个「距离尺度」"),
    ]
    for i, (head, note) in enumerate(items):
        r0 = 2 + 5 * i
        _frame(cv, r0, 2, r0 + 3, 76)
        cv.text(r0 + 1, 4, head)
        cv.text(r0 + 2, 4, note)

    cv.text(17, 2, "可加性：I_n = n I_1 -> 一切 sqrt(n) 收敛律的来源。")
    return cv.render()


# ---------- ch10 block2：岭回归的收缩路径 ----------
def fig_bias_variance() -> list[str]:
    ROWS, COLS = 13, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "岭回归：按特征方向收缩，因子 s = lambda / (lambda + mu)")
    _frame_cols(cv, 1, 2, 8, 74, col_xs=(24, 36, 48, 60), div_rows=(3,))
    cv.text(2, 4, "特征值 lambda")
    cv.text(2, 25, "mu = 0")
    cv.text(2, 37, "mu = 1")
    cv.text(2, 49, "mu = 10")
    cv.text(2, 61, "mu = 100")
    rows = [
        ("100", "1.000", "0.990", "0.909", "0.500"),
        ("10", "1.000", "0.909", "0.500", "0.091"),
        ("1", "1.000", "0.500", "0.091", "0.010"),
        ("0.01", "1.000", "0.0099", "0.00098", "0.0001"),
    ]
    for i, t in enumerate(rows):
        r = 4 + i
        cv.text(r, 4, t[0])
        for j in range(4):
            cv.text(r, 25 + 12 * j, t[j + 1])

    cv.text(10, 2, "大特征值（信号强）：几乎不动；小特征值（几乎不可辨识）：压向 0。")
    cv.text(11, 2, "mu 增大 -> 偏差增大、方差减小；最优 mu 处总 MSE 严格小于 OLS。")
    cv.text(12, 2, "与第 6 章伪逆 sigma/(sigma^2+mu) 同源：同一件事的两种坐标写法。")
    return cv.render()


# ---------- ch10 block3：系统辨识流程与模型族 ----------
def fig_sysid_flow() -> list[str]:
    ROWS, COLS = 19, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "系统辨识的闭环流程：")
    boxes = ["1 数据", "2 模型集", "3 判据", "4 优化", "5 诊断"]
    for i, b in enumerate(boxes):
        c = 2 + 15 * i
        _frame(cv, 2, c, 4, c + 11)
        cv.text(3, c + 1, b)
        if i < len(boxes) - 1:
            cv.text(3, c + 12, "->")

    cv.text(6, 2, "5 若不通过 -> 回到 2（改阶数 / 改结构 / 改激励），这是一个迭代过程。")

    _frame_cols(cv, 8, 2, 15, 76, col_xs=(18, 40, 60), div_rows=(10,))
    cv.text(9, 4, "模型")
    cv.text(9, 20, "结构")
    cv.text(9, 42, "噪声")
    cv.text(9, 62, "方法")
    rows = [
        ("ARX", "A y = B u + e", "白噪声", "LS / IV"),
        ("ARMAX", "A y = B u + C e", "C 可建模", "非线性 LS"),
        ("OE", "y = (B/A) u + e", "只在输出端", "非线性优化"),
        ("SS", "x+ = A x + B u", "一般", "n4sid 子空间"),
    ]
    for i, t in enumerate(rows):
        r = 11 + i
        cv.text(r, 4, t[0])
        cv.text(r, 20, t[1])
        cv.text(r, 42, t[2])
        cv.text(r, 62, t[3])

    cv.text(17, 2, "诊断三问：1) 残差自相关 -> 噪声模型阶数不够；")
    cv.text(18, 2, "2) 残差与输入相关 -> 参数有偏，需 IV；3) 条件数过大 -> 激励不够（PE）。")
    return cv.render()


# ---------- ch10 block4：EM 的下界提升 ----------
def fig_em_lower_bound() -> list[str]:
    ROWS, COLS = 18, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "EM 迭代：抬高下界必然抬高原函数")
    _frame(cv, 1, 2, 6, 74)
    cv.text(2, 4, "下界 L 在 theta_k 处与 ell 相切，且处处 L <= ell。")
    cv.text(3, 4, "M 步把 L 抬到最高 -> 由 L <= ell，原函数也必须上升：")
    cv.text(4, 4, "ell(k+1) >= L(k+1|k) >= L(k|k) = ell(k)     （k 简写 theta_k）")
    cv.text(5, 4, "这就是单调不降的全部证明（KL 非负 -> 下界合法）。")

    _frame_cols(cv, 8, 2, 16, 74, col_xs=(20, 46), div_rows=(10,))
    cv.text(9, 4, "迭代 k")
    cv.text(9, 22, "log p(x ; theta_k)")
    cv.text(9, 48, "相邻差")
    rows = [
        ("0", "-5.8000", "(首轮)"),
        ("1", "-5.1200", "0.6800"),
        ("2", "-4.8600", "0.2600"),
        ("3", "-4.7800", "0.0800"),
        ("5", "-4.7600", "0.0200"),
    ]
    for i, t in enumerate(rows):
        r = 11 + i
        cv.text(r, 4, t[0])
        cv.text(r, 22, t[1])
        cv.text(r, 48, t[2])

    cv.text(17, 2, "收敛率 rho = 缺失信息 / 观测信息；rho 接近 1 时迭代几乎不动。")
    return cv.render()


# ======================================================================
# ch11 —— 信息论与统计推断
# ======================================================================

# ---------- ch11 block0：熵的三种读法 ----------
def fig_entropy_zoo() -> list[str]:
    ROWS, COLS = 17, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "同一个 H(X)，三种读法 —— 三种场景各用其中一种：")
    items = [
        ("1) 平均惊讶   H = E[ -log p(X) ]",
         "事件越稀有，信息越大；熵是它的期望 -> 熵 = 0 表示确定，不提供信息"),
        ("2) 最少比特   H = 无损压缩的下界",
         "n 长序列里只有约 2^(nH) 个典型序列，其余在概率上根本不会出现"),
        ("3) 最坏猜测   H <= log|X|，等号在均匀分布",
         "均匀分布最难猜；给定期望与方差时最大熵分布是高斯的（11.1.4）"),
    ]
    for i, (head, note) in enumerate(items):
        r0 = 2 + 5 * i
        _frame(cv, r0, 2, r0 + 3, 76)
        cv.text(r0 + 1, 4, head)
        cv.text(r0 + 2, 4, note)

    cv.text(16, 2, "读法 1 用于理解，读法 2 用于压缩（11.4.2），读法 3 用于先验选择（11.1.4）。")
    return cv.render()


# ---------- ch11 block1：KL 的不对称性 ----------
def fig_kl_asymmetry() -> list[str]:
    ROWS, COLS = 17, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "KL 不对称：两个方向惩罚的东西不同，因此行为完全不同。")

    _frame(cv, 2, 2, 8, 38)
    _frame(cv, 2, 40, 8, 76)
    cv.text(3, 4, "前向 KL   D(p || q)")
    cv.text(4, 4, "-> 只要 p>0，必须 q>0")
    cv.text(5, 4, "-> 重罚「漏掉支撑」")
    cv.text(6, 4, "-> 结果是均值匹配")
    cv.text(7, 4, "-> 变分推断 / ELBO 用这个")

    cv.text(3, 42, "反向 KL   D(q || p)")
    cv.text(4, 42, "-> 只在 p 的峰附近放质量")
    cv.text(5, 42, "-> 重罚「铺得太开」")
    cv.text(6, 42, "-> 结果是模式寻找")
    cv.text(7, 42, "-> 期望传播 / GAN 的训练侧")

    cv.text(10, 2, "数值感受：p = N(0,1) 与 q = N(0, sigma^2)，取 sigma^2 = 4")
    cv.text(11, 4, "D(p || q) = 0.5(log sigma^2 + 1/sigma^2 - 1) = 0.32")
    cv.text(12, 4, "D(q || p) = 0.5(sigma^2 - 1 - log sigma^2) = 0.81")

    cv.text(14, 2, "同一个错配，两个方向的代价不同 -> KL 不是距离（不满足对称与三角不等式）。")
    cv.text(15, 2, "支撑不一致时，只要「分子非零而分母为零」取向的那个方向就是 +inf。")
    return cv.render()


# ---------- ch11 block2：Fisher 度量下的统计流形 ----------
def fig_fisher_geometry() -> list[str]:
    ROWS, COLS = 19, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "统计流形：每个 theta 对应一个分布，Fisher 信息是流形上的局部尺子。")

    # 钟形弧：先落两个端点标记，再补其余的点，最后写标签（避免撞格）
    pts = [(8, 4), (7, 9), (6, 14), (5, 19), (4, 24), (4, 29), (5, 34), (6, 39),
           (7, 44), (8, 49)]
    for r, c in pts:
        if (r, c) not in ((4, 24), (4, 29)):
            cv.put(r, c, ".")
    cv.put(4, 24, "*")
    cv.put(4, 29, "*")
    cv.text(2, 20, "p_theta")
    cv.text(2, 29, "p_(theta+d)")

    cv.text(11, 2, "弧长 ds = sqrt(I(theta)) d(theta)；局部 KL 就是 ds^2 / 2。")

    cv.text(13, 2, "同一个 I(theta) 的四张面孔（互相等价）：")
    cv.text(14, 4, "1) 局部 KL    KL(p_th || p_th+d) = 0.5 I(theta) d^2 + o(d^2)")
    cv.text(15, 4, "2) 估计下界   Var(hat theta) >= 1 / (n I(theta))        CRLB")
    cv.text(16, 4, "3) 自然梯度   theta <- theta - eta I^-1 grad L         每步等 KL")
    cv.text(17, 4, "4) 熵的导数   d h(X_t)/dt = 0.5 I(X_t)               de Bruijn")
    cv.text(18, 2, "指数族特例最干净：I(theta) = Cov[T(X)] —— 信息就是充分统计量的波动。")
    return cv.render()


# ---------- ch11 block3：信息论三大极限 ----------
def fig_info_limits() -> list[str]:
    ROWS, COLS = 13, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "信息论的三大极限：问题不同，但目标函数全是熵或互信息。")

    _frame_cols(cv, 2, 2, 8, 76, col_xs=(16, 40, 58), div_rows=(4,))
    cv.text(3, 4, "问题")
    cv.text(3, 18, "极限量")
    cv.text(3, 42, "对谁优化")
    cv.text(3, 60, "工程含义")

    rows = [
        ("无损压缩", "H(X)", "不优化", "H = 最少比特"),
        ("可靠传输", "max I(X;Y)", "输入分布", "C = 最高速率"),
        ("有损压缩", "min I(X;Xhat)", "条件分布", "R(D) = 最少比特"),
    ]
    for i, (a, b, c, d) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 18, b)
        cv.text(r, 42, c)
        cv.text(r, 60, d)

    cv.text(10, 2, "高斯情形下三者同形：(1/2) log(1 + SNR) 与 (1/2) log(sigma^2 / D)。")
    cv.text(11, 2, "这不是巧合：传输与压缩是对偶的，都受同一枚「互信息硬币」支配。")
    return cv.render()


# ---------- ch11 block4：ELBO 的两种拆法 ----------
def fig_elbo_decomp() -> list[str]:
    ROWS, COLS = 15, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "log p(x) 拆成「可优化的下界」+「必须小的间隙」：")

    _frame(cv, 2, 2, 6, 76)
    cv.text(3, 4, "log p(x)  =  ELBO(q)  +  KL( q(z) || p(z|x) )")
    cv.text(4, 4, "ELBO 是要最大化的下界；间隙 >= 0，为 0 当且仅当 q = 真实后验")
    cv.text(5, 4, "于是「推断」被翻译成「优化」—— 这就是变分推断的全部内容")

    cv.text(8, 2, "第二种拆法（用生成视角 p(x,z) = p(x|z) p(z)）：")
    cv.text(9, 4, "ELBO = E_q[ log p(x|z) ]  -  KL( q(z) || p(z) )")
    cv.text(10, 11, "重构项（拟合数据）")
    cv.text(10, 34, "正则项（贴住先验）")

    cv.text(12, 2, "与 AIC 同构：ELBO = 似然 - 复杂性惩罚（都是「拟合 + 惩罚」的形状）。")
    cv.text(13, 2, "优化方向是前向 KL -> 系统性低估后验方差，这是变分推断的固有偏差。")
    return cv.render()


# ======================================================================
# ch12 —— 傅里叶分析、采样与小波
# ======================================================================

# ---------- ch12 block0：三种基与系数衰减 ----------
def fig_fourier_family() -> list[str]:
    ROWS, COLS = 16, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "同一个框架：换一组正交基看信号（左：基，右：系数的含义）。")

    _frame_cols(cv, 2, 2, 8, 76, col_xs=(22, 50), div_rows=(4,))
    cv.text(3, 4, "对象 / 空间")
    cv.text(3, 24, "正交基")
    cv.text(3, 52, "系数含义")

    rows = [
        ("周期函数 L^2[0,T]", "e^(i n w0 t)", "第 n 次谐波的复振幅"),
        ("非周期 L^2(R)", "e^(i w t) (连续统)", "频谱密度"),
        ("有限序列 C^N", "e^(i 2 pi k n / N)", "DFT 第 k 个频点"),
    ]
    for i, (a, b, c) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 24, b)
        cv.text(r, 52, c)

    cv.text(10, 2, "光滑度 <-> 系数衰减（这一条决定「能不能压缩」）：")
    cv.text(11, 4, "有跳跃      |c_n| ~ 1/n        方波 / 白噪声：不可压")
    cv.text(12, 4, "一阶导跳跃  |c_n| ~ 1/n^2      三角波")
    cv.text(13, 4, "m 阶导跳跃  |c_n| ~ 1/n^(m+1)  越光滑越可压")
    cv.text(15, 2, "两端极限：T -> 无穷 时级数变变换；连续频谱取样成 DFT。")
    return cv.render()


# ---------- ch12 block1：卷积定理连接时域与频域 ----------
def fig_conv_theorem() -> list[str]:
    ROWS, COLS = 15, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "LTI 系统的两种等价描述 —— 卷积定理把它们连起来：")

    _frame(cv, 2, 2, 6, 38)
    cv.text(3, 4, "时域：  y = h * x")
    cv.text(4, 4, "卷积，代价 O(N^2)")
    cv.text(5, 4, "适合短序列 / 推导")

    _frame(cv, 2, 40, 6, 76)
    cv.text(3, 42, "频域：  Y = H(w) X(w)")
    cv.text(4, 42, "逐点乘法，代价 O(N)")
    cv.text(5, 42, "适合长序列 / 设计")

    cv.text(8, 2, "三条推论（这就是信号处理学科的技术核心）：")
    cv.text(9, 4, "1) 微分方程 -> 代数方程：d/dt 变成乘 i w（第 13 章）")
    cv.text(10, 4, "2) 滤波器设计 = 设计一条 |H(w)| 曲线")
    cv.text(11, 4, "3) 因果性 / 稳定性 = H 的极点位置（第 13 章）")
    cv.text(13, 2, "理想低通 h = sinc 不是因果的 -> 物理不可实现，只能近似 + 延迟。")
    cv.text(14, 2, "e^(i w t) 是 d/dt 的特征函数 —— 这是「频域好算」的全部原因。")
    return cv.render()


# ---------- ch12 block2：采样三步链 ----------
def fig_sampling_chain() -> list[str]:
    ROWS, COLS = 17, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "采样三步：乘冲激串 -> 频谱周期化 -> 低通切回原谱。")

    _frame(cv, 2, 2, 6, 24)
    cv.text(3, 4, "1) 采样")
    cv.text(4, 4, "乘冲激串")
    cv.text(5, 4, "-> 频谱周期化")

    _frame(cv, 2, 28, 6, 50)
    cv.text(3, 30, "2) 判断")
    cv.text(4, 30, "fs > 2B ?")
    cv.text(5, 30, "副本不重叠")

    _frame(cv, 2, 54, 6, 76)
    cv.text(3, 56, "3) 重建")
    cv.text(4, 56, "理想低通切回")
    cv.text(5, 56, "-> 精确还原")

    cv.text(4, 25, "->")
    cv.text(4, 51, "->")

    cv.text(8, 2, "频谱示意（低通信号，fs > 2B 时副本不重叠）：")
    cv.text(9, 4, "原始谱 :          [===W===]              支撑 |w| < W")
    cv.text(10, 4, "周期化 :   [===]  [===W===]  [===]       副本间距 = ws")
    cv.text(11, 4, "                   <-- ws -->")
    cv.text(12, 4, "重建   : 用低通 |w| < ws/2 取出中间那份，与原谱完全相同")

    cv.text(14, 2, "若 fs < 2B：副本重叠，高频折叠进低频 = 混叠，信息永久丢失。")
    cv.text(15, 2, "自由度计数：时长 T、带宽 B 的信号只有约 2BT 个自由度。")
    cv.text(16, 2, "所以「样本数 = 自由度 = 维数」—— 采样定理其实是维数定理。")
    return cv.render()


# ---------- ch12 block3：窗函数与谱估计的两条折衷 ----------
def fig_window_tradeoff() -> list[str]:
    ROWS, COLS = 16, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "窗与谱估计：两条折衷，都是不确定性原理的化身。")

    _frame_cols(cv, 2, 2, 10, 76, col_xs=(22, 42, 58), div_rows=(4,))
    cv.text(3, 4, "窗")
    cv.text(3, 24, "主瓣(bin)")
    cv.text(3, 44, "最高旁瓣")
    cv.text(3, 60, "典型用途")

    rows = [
        ("矩形", "1", "-13 dB", "整周期 / 瞬态"),
        ("Hann", "2", "-31 dB", "通用谱分析"),
        ("Hamming", "2", "-43 dB", "语音"),
        ("Blackman", "3", "-58 dB", "需要低泄漏"),
        ("平顶", "4", "-90 dB", "精确测幅值"),
    ]
    for i, (a, b, c, d) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 24, b)
        cv.text(r, 44, c)
        cv.text(r, 60, d)

    cv.text(12, 2, "折衷 1：主瓣越窄，旁瓣越高（没有又窄又低的窗）")
    cv.text(13, 2, "折衷 2：频率分辨率 x 方差 ~ 常数（分段平均降方差必牺牲分辨率）")
    cv.text(15, 2, "关键：补零只加密频域格点，不提高分辨率 —— 分辨率由观测时长决定。")
    return cv.render()


# ---------- ch12 block4：STFT 与小波对照 ----------
def fig_tf_tiling() -> list[str]:
    ROWS, COLS = 16, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "STFT 与小波：格子怎么摆，决定它适合什么信号。")

    _frame_cols(cv, 2, 2, 9, 76, col_xs=(26, 50), div_rows=(4,))
    cv.text(3, 4, "对比项")
    cv.text(3, 28, "STFT")
    cv.text(3, 52, "小波")

    rows = [
        ("窗宽", "固定", "随尺度 a 变化"),
        ("时频格子", "均匀", "低频宽、高频窄"),
        ("不变量", "时移", "时移 + 伸缩"),
        ("适合", "平稳 / 准平稳", "非平稳 / 瞬态"),
    ]
    for i, (a, b, c) in enumerate(rows):
        r = 5 + i
        cv.text(r, 4, a)
        cv.text(r, 28, b)
        cv.text(r, 52, c)

    cv.text(10, 2, "恒 Q 的含义：小波的相对带宽 dw/w 恒定 —— 低频用长窗，高频用短窗。")
    cv.text(11, 2, "这恰好匹配 1/f 型信号的统计结构（图像、ECG、湍流、地震波）。")
    cv.text(13, 2, "一句话：STFT 用固定尺子量所有尺度，小波用对数尺子量所有尺度。")
    cv.text(14, 2, "两者都受 dt*dw >= 1/2 约束，差别只在「格子怎么摆」。")
    return cv.render()


# ---------- ch13 block0：s 平面上的收敛域 ----------
def fig_roc_plane() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "收敛域 ROC：s 平面上的竖条带，边界必穿过极点，内部绝不含极点。")

    cv.text(2, 9, "jw")
    cv.text(2, 32, "x = 极点")
    cv.text(3, 10, "^")
    cv.text(4, 2, "x")
    cv.text(4, 18, "x")
    cv.text(5, 2, "--------+----------------------------------> sigma")
    cv.text(6, 10, "x")
    cv.text(6, 22, "实部 = 增长 / 衰减速率")

    cv.text(8, 2, "三种信号类型对应的 ROC：")
    cv.text(9, 4, "因果（右边）      ===================>|      sigma > s_max  最右极点之右")
    cv.text(10, 4, "反因果（左边）    |<===================      sigma < s_min  最左极点之左")
    cv.text(11, 4, "双边（条带）      |<===[  ROC  ]====>|        s_min < sigma < s_max")
    cv.text(12, 4, "有限长            全平面               发散：空集（超指数增长）")

    cv.text(14, 2, "三条判据：")
    cv.text(15, 4, "因果       <=>  ROC 含半平面 sigma > s_max")
    cv.text(16, 4, "稳定       <=>  ROC 含 jw 轴（虚轴可取 => 傅里叶变换存在）")
    cv.text(17, 4, "因果且稳定 <=>  全部极点都在左半开平面（s_max < 0）")

    cv.text(19, 2, "同一个式子、两个信号（ROC 才含因果信息）：")
    cv.text(20, 4, "1/(s+a) 配 Re s > -a  =>  e^(-at)u(t)     因果")
    cv.text(21, 4, "1/(s+a) 配 Re s < -a  =>  -e^(-at)u(-t)   反因果")
    return cv.render()


# ---------- ch13 block1：s 平面到 z 平面的映射 ----------
def fig_laplace_zmap() -> list[str]:
    ROWS, COLS = 19, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "z = e^(sT)：竖线变圆，左半平面变单位圆内。")

    cv.text(2, 8, "s 平面（连续）")
    cv.text(2, 40, "z 平面（离散）")
    cv.text(3, 13, "jw")
    cv.text(3, 47, "Im")
    cv.text(4, 14, "^")
    cv.text(4, 48, "^")
    cv.text(5, 4, "x")
    cv.text(5, 18, "x")
    cv.text(5, 40, ",-----------.")
    cv.text(6, 2, "------------+----------------> sigma")
    cv.text(6, 40, "|  x     x  |")
    cv.text(6, 56, "|z| = 1（单位圆）")
    cv.text(7, 19, "x")
    cv.text(7, 40, "`-----------'")
    cv.text(7, 56, "左半 -> 圆内，虚轴 -> 圆周")

    cv.text(9, 2, "映射规律：")
    cv.text(10, 4, "竖直线 Re s = sigma  -->  圆 |z| = e^(sigma T)")
    cv.text(11, 4, "左半平面 sigma < 0   -->  单位圆内 |z| < 1（稳定域统一）")
    cv.text(12, 4, "虚轴 s = jw          -->  单位圆 |z| = 1（频率轴）")

    cv.text(14, 2, "最要紧的一条：jw 轴每走 2 pi/T，z 绕单位圆整整一圈")
    cv.text(15, 4, "=> s 平面的整条竖带被「卷」到同一个 z 环上")
    cv.text(16, 4, "=> 离散时间频谱天生以 2 pi/T 为周期（第 12 章混叠的根源）")

    cv.text(18, 2, "一句话：连续看左半平面，离散看单位圆内。")
    return cv.render()


# ---------- ch13 block2：极点位置 -> 响应模态 ----------
def fig_lti_zoo() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "极点位置读出冲激响应的模态（读极点图 = 读波形）。")

    cv.text(2, 4, "s 平面（连续）")
    cv.text(3, 9, "jw")
    cv.text(4, 10, "^")
    cv.text(5, 2, "x")
    cv.text(5, 15, "x")
    cv.text(6, 2, "--------+----------------> sigma")
    cv.text(7, 10, "x")

    cv.text(5, 38, "e^(-at)            单调衰减（实根）")
    cv.text(6, 38, "e^(-at)cos(wt)     衰减振荡（共轭根）")
    cv.text(7, 38, "cos(wt)            等幅振荡（虚轴）")

    cv.text(9, 2, "左半平面：衰减    虚轴：等幅    右半平面：增长")

    cv.text(11, 2, "对照表（连续 / 离散 / 波形 / 名称）：")
    cv.text(12, 4, "负实轴        圆内实轴    e^(-at)           过阻尼")
    cv.text(13, 4, "左半共轭对    圆内共轭对  衰减振荡          欠阻尼")
    cv.text(14, 4, "左半重实根    圆内重根    t e^(-at)         临界阻尼")
    cv.text(15, 4, "虚轴共轭对    单位圆上    等幅振荡          临界稳定")
    cv.text(16, 4, "右半平面      单位圆外    指数增长          不稳定")
    cv.text(17, 4, "原点 s = 0    z = 1       阶跃（积分器）    直流")

    cv.text(19, 2, "二阶标准型：极点 = -zeta wn +/- i wn sqrt(1 - zeta^2)")
    cv.text(20, 4, "到虚轴距离 zeta wn = 衰减率    到原点距离 wn = 振荡频率")
    cv.text(21, 2, "零点不产生新模态，只调节各模态幅度；零点与极点重合时该模态消失。")
    return cv.render()


# ---------- ch13 block3：双线性变换的频率畸变 ----------
def fig_bilinear_warp() -> list[str]:
    ROWS, COLS = 19, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "双线性变换的频率畸变：整条模拟频率轴被压进 (-pi, pi)。")

    cv.text(2, 6, "w（数字频率）")
    cv.text(3, 4, "pi")
    cv.text(3, 7, "┤")
    cv.text(3, 34, ".--------------  Omega -> 无穷 时 w -> pi")
    cv.text(4, 7, "│")
    cv.text(4, 26, ".-----'")
    cv.text(5, 7, "│")
    cv.text(5, 18, ".-----'")
    cv.text(6, 7, "│")
    cv.text(6, 11, ".-----'")
    cv.text(7, 7, "│")
    cv.text(7, 8, ".-'")
    cv.text(8, 4, "0")
    cv.text(8, 7, "┼--------------------------------------> Omega（模拟频率）")
    cv.text(9, 8, "低频处 w 约等于 Omega T（近似线性）；高频处严重压缩")

    cv.text(11, 2, "预畸变（pre-warping）：在模拟指标上做反向映射")
    cv.text(12, 4, "期望的数字截止 wc  ->  设计用的模拟截止 Omega_c = (2/T) tan(wc/2)")
    cv.text(13, 4, "这样在 wc 处特性完全对上，通带 / 阻带边界准确。")

    cv.text(15, 2, "两种离散化的取舍（互斥）：")
    cv.text(16, 4, "冲激响应不变法：时域保真，频域周期化 -> 有混叠")
    cv.text(17, 4, "双线性变换：    无混叠、无条件稳定，但有频率畸变 -> 必须预畸变")
    return cv.render()


# ---------- ch13 block4：四种低通原型对比 ----------
def fig_filter_approx() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "四种低通原型的幅频特性（纵轴 |H|，横轴归一化频率 w/wc）。")

    cv.text(2, 4, "|H|")
    cv.text(3, 3, "1.0")
    cv.text(3, 7, "┤")
    cv.text(3, 8, "======================")
    cv.text(3, 31, "Butterworth：最大平坦")
    cv.text(4, 7, "│")
    cv.text(4, 29, "\\")
    cv.text(5, 7, "│")
    cv.text(5, 30, "\\")
    cv.text(5, 32, "Chebyshev I：通带等波纹")
    cv.text(6, 1, "0.707")
    cv.text(6, 7, "┤")
    cv.text(6, 8, "-  -  -  -3dB -  -  -  -")
    cv.text(6, 32, "\\")
    cv.text(7, 7, "│")
    cv.text(7, 34, "\\")
    cv.text(7, 36, "椭圆：过渡带最窄")
    cv.text(8, 3, "0.0")
    cv.text(8, 7, "┤")
    cv.text(8, 34, "\\______________")
    cv.text(8, 49, "阻带")
    cv.text(9, 7, "+----------------------------------------> w/wc")
    cv.text(10, 8, "通带 wp")
    cv.text(10, 40, "阻带 ws")

    cv.text(12, 2, "同阶数下过渡带由宽到窄（陡峭度）：")
    cv.text(13, 4, "Bessel  <  Butterworth  <  Chebyshev  <  椭圆（Cauer）")
    cv.text(14, 2, "相位 / 群延迟平坦度正好反序（Bessel 最好，椭圆最差）。")

    cv.text(16, 2, "「陡 vs 平」取舍定理：过渡带越陡 => 相位非线性越强、拖尾越长；")
    cv.text(17, 2, "要又陡又线性相位 => 只能放弃因果性（零相位滤波 filtfilt 前向 + 反向）。")

    cv.text(19, 2, "Butterworth 极点（唯一需要背的公式）：")
    cv.text(20, 4, "|H|^2 = 1 / (1 + (w/wc)^(2N))  =>  极点均布在半径 wc 的左半圆上")
    cv.text(21, 4, "p_k = wc * exp( i * pi * (2k + N - 1) / (2N) ),  k = 1 .. N")
    return cv.render()


# ---------- ch14 block0：状态空间框图 ----------
def fig_statespace_flow() -> list[str]:
    ROWS, COLS = 18, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "状态空间模型：把高阶方程拆成一阶向量方程，内部状态 x 显式可见。")

    cv.text(3, 2, "u(t) -->[ B ]--> (+) -->[ 积分 ]--> x(t) -->[ C ]--> (+) --> y(t)")
    cv.text(4, 20, "^")
    cv.text(4, 53, "^")
    cv.text(5, 20, "|")
    cv.text(5, 53, "|")
    cv.text(6, 20, "+--- A x    （状态反馈路径）")
    cv.text(6, 53, "+--- D u    （直通）")

    cv.text(8, 2, "四个矩阵的分工（各自负责一件事）：")
    cv.text(9, 4, "A (n x n)  状态怎么自己演化  ->  稳定性 = A 的特征值")
    cv.text(10, 4, "B (n x m)  输入怎么推动状态  ->  能控性 = rank[ B, AB, ..., A^(n-1)B ]")
    cv.text(11, 4, "C (p x n)  状态怎么被观测    ->  能观性 = rank[ C; CA; ...; CA^(n-1) ]")
    cv.text(12, 4, "D (p x m)  输入直接漏到输出  ->  高频直通，通常为 0")

    cv.text(14, 2, "从状态空间到传递函数：  H(s) = C (sI - A)^(-1) B + D")
    cv.text(15, 4, "其中 (sI-A)^(-1) = adj(sI-A) / det(sI-A)")
    cv.text(16, 4, "=> det(sI-A) 是 A 的特征多项式，H(s) 的极点 = A 的特征值")
    cv.text(17, 4, "   但只有「既能控又能观」的模态才留在 H(s) 里（其余被相消）")
    return cv.render()


# ---------- ch14 block1：e^(At) 的四种形状 ----------
def fig_matrix_exp_zoo() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "e^(At) 的形状完全由 A 的特征值决定（看谱即知轨线）。")

    cv.text(2, 4, "特征值情形               e^(At) 的形状                 轨线")
    cv.text(3, 2, "-----------------------------------------------------------------")
    cv.text(4, 4, "实、负、互异           diag( e^(l1 t), e^(l2 t) )       直趋原点")
    cv.text(5, 4, "实、负、重根           e^(lt) [ 1  t ; 0  1 ]           出现 t e^(lt)")
    cv.text(6, 4, "复、负实部             e^(at) [ cos wt  sin wt ; ... ]   螺旋收敛")
    cv.text(7, 4, "纯虚（a = 0）          [ cos wt  sin wt ; ... ]         闭合椭圆")
    cv.text(8, 4, "实部为正               指数增长                        发散")

    cv.text(10, 2, "三条计算路径（任选一条，各有适用场合）：")
    cv.text(11, 4, "对角化：e^(At) = V diag(e^(l_i t)) V^(-1) = sum_i e^(l_i t) v_i w_i^T")
    cv.text(12, 4, "Jordan：e^(Jt) = e^(lt) * [ 1  t  t^2/2 ... ; 0  1  t ... ; ... ]")
    cv.text(13, 4, "Cayley-Hamilton + 插值：e^(At) = sum_{k=0}^{n-1} a_k(t) A^k")

    cv.text(15, 2, "两条必须记住的谱结论（它们决定连续与离散的稳定域）：")
    cv.text(16, 4, "sigma( e^A ) = e^( sigma(A) )        谱映射")
    cv.text(17, 4, "Re(lambda) < 0  <=>  e^(At) -> 0      连续稳定")
    cv.text(18, 4, "|lambda| < 1    <=>  A^k  -> 0         离散稳定")
    cv.text(20, 2, "注意：e^(A+B) != e^A e^B，除非 AB = BA（有 Lie 括号修正项）")
    return cv.render()


# ---------- ch14 block2：Kalman 能控能观分解 ----------
_fig_ctrb_obsv_MD = r'''  Kalman 分解：状态空间分四块，只有「能控且能观」那块出现在 H(s) 里。

      能控                       不能控
   ----------------------------------------------------------------
    能观     A11 (co)    出现在 H(s)   A33 (c-ob)  能观测但推不动
             极小实现的核心（阶数最低）              （反馈无效）
   ----------------------------------------------------------------
    不能观   A22 (cb-o)  能控但观测不到  A44 (cb-ob) 两个都不
             反馈/极点配置有效           完全隐藏：内部失稳也看不见
             （但不能做观测器）          （既推不动也看不见）
   ----------------------------------------------------------------


  两条秩判据（秩满则完全能控 / 完全能观）：
    能控：rank[ B, AB, A^2B, ..., A^(n-1)B ] = n   （PBH：w^T B != 0）
    能观：rank[ C; CA; CA^2; ..., CA^(n-1) ] = n   （PBH：C v != 0）

  对偶原理：(A,B) 能控  <=>  (A^T, B^T) 能观
    控制与估计是同一个问题的转置 —— 学一个，得两个。

  工程警告：不可控 / 不可观的模态仍然留在系统里！
    H(s) 稳定 不代表 内部稳定（隐藏的不稳定模态照样发散、烧硬件）
    判据：稳定性必须看全部 sigma(A)，不能只看 H(s) 的极点。'''


def fig_ctrb_obsv() -> list[str]:
    """2026-09-18 从 chapters/ch14.md block2 反向同步（md 为权威，原文手工修正过碰撞/行差，故整体返回 md 文本）。"""
    return _fig_ctrb_obsv_MD.split("\n")


# ---------- ch14 block3：Lyapunov 函数的几何 ----------
def fig_lyapunov_geom() -> list[str]:
    ROWS, COLS = 21, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Lyapunov 方法：不解积分，只找一个「能量」函数 V(x) = x^T P x。")

    cv.text(2, 10, ",-----------------.")
    cv.text(3, 8, ",'                   `.")
    cv.text(4, 7, "/    ,-----------.    \\")
    cv.text(5, 6, "|    /             \\    |")
    cv.text(6, 6, "|   |       *       |   |")
    cv.text(7, 6, "|    \\             /    |")
    cv.text(8, 7, "\\    `-----------'    /")
    cv.text(9, 8, "`.                   ,'")
    cv.text(10, 10, "`-----------------'")
    cv.text(5, 36, "<-- 轨线永远从外层椭球穿入内层")
    cv.text(9, 36, "外层 V = c2，内层 V = c1")

    cv.text(12, 2, "V(x) = x^T P x > 0            （正定 = 能量非负；1/sqrt(lam_i(P)) 是椭球轴长）")
    cv.text(13, 2, "dV/dt = x^T (A^T P + P A) x = - x^T Q x < 0   （沿轨线能量严格递减）")
    cv.text(14, 2, "=> 轨线被夹在嵌套椭球之间，必然趋于原点（不需要解 x(t)！）")

    cv.text(16, 2, "核心方程（Lyapunov 方程）：  A^T P + P A = - Q")
    cv.text(17, 4, "唯一解  <=>  lambda_i + lambda_j != 0 对一切 i, j")
    cv.text(18, 4, "P > 0   <=>  A 是 Hurwitz（全部特征值在左半开平面）")

    cv.text(20, 2, "三种等价的稳定性判据：时域 h 绝对可积 <-> Re(lambda) < 0 <-> 存在 P > 0")
    return cv.render()


# ---------- ch14 block4：Kalman 滤波循环 ----------
def fig_kalman_cycle() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Kalman 滤波：预测 -> 校正 的循环（P 的递推不依赖数据，可离线预算）。")

    cv.text(2, 4, "初始化  x0, P0")

    inner = 20
    top = "+" + "-" * inner + "+"

    def row(s: str) -> str:
        return "| " + pad(s, inner - 2) + " |"

    cv.text(4, 4, top)
    cv.text(5, 4, row("预测（时间更新）"))
    cv.text(5, 30, "x = A x + B u")
    cv.text(6, 4, row(""))
    cv.text(6, 30, "P = A P A^T + Xi     （Xi：过程噪声）")
    cv.text(7, 4, top)
    cv.text(8, 14, "|")
    cv.text(9, 4, top)
    cv.text(10, 4, row("增益计算"))
    cv.text(10, 30, "L = P C^T ( C P C^T + Theta )^(-1)")
    cv.text(11, 4, row(""))
    cv.text(11, 30, "（Theta：量测噪声）")
    cv.text(12, 4, top)
    cv.text(13, 14, "|")
    cv.text(14, 4, top)
    cv.text(15, 4, row("校正（量测更新）"))
    cv.text(15, 30, "x = x + L ( y - C x )   <- 新息 innovation")
    cv.text(16, 4, row(""))
    cv.text(16, 30, "P = ( I - L C ) P")
    cv.text(17, 4, top)
    cv.text(18, 14, "|")
    cv.text(19, 14, "+----> 回到预测（下一时刻）")

    cv.text(20, 2, "调参本质：只调 Xi / Theta 这一个比例（信模型 vs 信测量）")
    cv.text(21, 2, "稳态：P -> P_inf 满足离散 Riccati 方程（DARE），增益变为常数")
    return cv.render()


# ---------- ch15 block0：正交基 vs 框架 ----------
def fig_basis_vs_frame() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "正交基（M = n，无冗余）与框架（M > n，冗余）的对比。")

    cv.text(2, 6, "对比项        正交基                    框架（冗余）")
    cv.text(3, 2, "-------------------------------------------------------------------")
    cv.text(4, 6, "个数          M = n（刚好）             M > n（多出来）")
    cv.text(5, 6, "线性无关      是                        否（必然相关）")
    cv.text(6, 6, "展开系数      唯一                      不唯一（无穷多组）")
    cv.text(7, 6, "分析系数      c_k = <x, f_k>            c_k = <x, f_k>（一样）")
    cv.text(8, 6, "重构          x = sum c_k f_k           x = sum c_k f_tilde_k")
    cv.text(9, 6, "                                      其中 f_tilde = S^(-1) f")
    cv.text(10, 6, "紧框架        A = B = 1（Parseval）     A = B 时仍可简单重构")
    cv.text(11, 6, "                                       x = (1/A) sum <x,f_k> f_k")
    cv.text(12, 6, "稳健性        丢一个系数 = 丢一个方向    丢几个系数仍可重构（冗余）")
    cv.text(13, 6, "条件数        1（最优）                  cond(S) = B / A")

    cv.text(15, 2, "框架条件的两边各管一件事：")
    cv.text(16, 4, "下界 A > 0：没有一个方向是看不见的  =>  信息不丢（可完全重构）")
    cv.text(17, 4, "上界 B < 无穷：没有方向被反复计数    =>  信息不炸（分析算子有界）")

    cv.text(19, 2, "一句话：紧框架下重构公式与正交基完全同形，只差一个常数 1/A。")
    return cv.render()


# ---------- ch15 block1：l1 为什么给稀疏解 ----------
def fig_l1_geometry() -> list[str]:
    ROWS, COLS = 21, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "为什么 l1 给稀疏解：约束球与可行集的切点位置（二维示意）。")

    cv.text(2, 6, "l2 球（圆）            l1 球（菱形）          l0 球（十字，非凸）")
    cv.text(3, 6, "  ,---.                   /\\                      |")
    cv.text(4, 6, " /     \\                 /  \\                     |")
    cv.text(5, 6, "|   *   |               <  * >                    +----")
    cv.text(6, 6, " \\     /                 \\  /                     |")
    cv.text(7, 6, "  `---'                   \\/                      |")
    cv.text(8, 6, "切点一般不在轴上        顶点在坐标轴上          只在坐标轴上")
    cv.text(9, 6, "解全非零                切点易落在顶点          最稀疏，但 NP 难")

    cv.text(11, 2, "三种等价的解释（同一件事的三种语言）：")
    cv.text(12, 4, "几何：l1 球的顶点就是稀疏点，仿射子空间先碰到顶点")
    cv.text(13, 4, "概率：l1 正则 = 拉普拉斯先验（在 0 处有尖峰）的 MAP")
    cv.text(14, 4, "分析：l1 在 0 处的次梯度是 [-1, 1]，KKT 允许解停在 0 上")

    cv.text(16, 2, "一维显式解（正交字典下）：min (1/2)(z - c)^2 + lam |c|")
    cv.text(17, 4, "=> c = S_lam(z) = sgn(z) * max( |z| - lam, 0 )     （软阈值）")

    cv.text(19, 2, "对照：l2 的 KKT 是 c = z/(1+2lam)，只要 z 不为 0 解就不为 0；")
    cv.text(20, 2, "      l0 给出硬阈值 H_lam(z) = z * 1{|z| > lam}，在 lam 处跳变。")
    return cv.render()


# ---------- ch15 block2：RIP 与随机测量 ----------
def fig_rip_sketch() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "RIP：测量矩阵 Phi 只在「稀疏方向」上近似保距。")

    cv.text(2, 4, "全空间 R^n（n 维）                     稀疏方向（k 稀疏的锥）")
    cv.text(3, 4, "+------------------+")
    cv.text(4, 4, "|                  |                   z 满足 |z|_0 <= k")
    cv.text(5, 4, "|    Phi 是矮胖     |                            |")
    cv.text(6, 4, "|    不可能全局保距  |                            v")
    cv.text(7, 4, "|    （零空间非空）  |               (1-d_k)|z|^2 <= |Phi z|^2")
    cv.text(8, 4, "|                  |                             <= (1+d_k)|z|^2")
    cv.text(9, 4, "+------------------+")
    cv.text(10, 4, "  m 行 n 列，m << n                   即在稀疏方向上近似正交投影")

    cv.text(12, 2, "随机矩阵为什么好（普适性）：")
    cv.text(13, 4, "高斯 / Rademacher 矩阵：m >= C d^(-2) k log(n/k) 即高概率满足 RIP")
    cv.text(14, 4, "证明三步：固定支撑集（JL 引理，集中不等式）")
    cv.text(15, 4, "          -> 并集界（C(n,k) <= (en/k)^k）")
    cv.text(16, 4, "          -> 令失败概率趋于 0")

    cv.text(18, 2, "确定性矩阵不行吗？Welch 界限制了最小相干度，确定性构造的保证弱得多。")
    return cv.render()


# ---------- ch15 block3：压缩感知相变 ----------
def fig_cs_phase() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "压缩感知的相变：在 (m/n, k/m) 平面上恢复成功与否骤然切换。")

    cv.text(2, 5, "k/m")
    cv.text(2, 30, "（稀疏率，纵轴）")
    cv.text(3, 6, "^")
    cv.text(3, 30, "横轴 m/n（测量率），纵轴 k/m（稀疏率）")
    cv.text(4, 6, "|XXXXXXXXXXXXXXXXXXXXXXX   失败区（信息不足，l1 必错）")
    cv.text(5, 6, "|XXXXXXXXXXXXXXXXXXXXXXXXX")
    cv.text(6, 6, "|---------____              <- 相变曲线 k/m = rho(m/n)")
    cv.text(7, 6, "|...          `------___")
    cv.text(8, 6, "|...                    `----___   成功区（l1 精确恢复）")
    cv.text(9, 6, "+-------------------------------> m/n")
    cv.text(10, 6, "0                                 1")
    cv.text(11, 8, "小（测量很少）              大（测量接近满）")

    cv.text(13, 2, "相变曲线的三点性质（它决定了该采多少）：")
    cv.text(14, 4, "曲线下方：l1 恢复成功概率 -> 1（n -> 无穷）")
    cv.text(15, 4, "曲线上方：恢复成功概率 -> 0")
    cv.text(16, 4, "过渡带宽度：O(1/sqrt(n)) -> 0，越来越陡")
    cv.text(17, 4, "阈值 rho 可由「零空间与稀疏锥相交」的面积计算")

    cv.text(19, 2, "对照：OMP 的阈值约为 l1 的一半；l0（穷举）阈值接近 1，但 NP 难。")
    return cv.render()


# ---------- ch15 block4：ISTA / FISTA 迭代 ----------
def fig_ista_flow() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "ISTA / FISTA：近端梯度 = 「梯度一步 + 软阈值一步」。")

    inner = 26
    top = "+" + "-" * inner + "+"

    def row(s: str) -> str:
        return "| " + pad(s, inner - 2) + " |"

    cv.text(2, 4, "输入 c_0，步长 eta < 1 / ||D^T D||")
    cv.text(3, 18, "|")
    cv.text(3, 32, "第 t 轮：先对光滑部分（最小二乘）走一步")
    cv.text(4, 4, top)
    cv.text(5, 4, row("梯度步（最小二乘的梯度）"))
    cv.text(6, 4, row("g = D^T ( D c - y )"))
    cv.text(7, 4, row("v = c - eta g"))
    cv.text(8, 4, top)
    cv.text(9, 18, "|")
    cv.text(9, 32, "再对非光滑部分（l1）做一次软阈值")
    cv.text(10, 4, top)
    cv.text(11, 4, row("近端步（软阈值）"))
    cv.text(12, 4, row("c = S_(eta lam)(v)"))
    cv.text(13, 4, row("= sgn(v) max(|v|-t, 0)"))
    cv.text(14, 4, top)
    cv.text(15, 18, "|")
    cv.text(16, 18, "+--> 未收敛则回到梯度步")
    cv.text(16, 50, "（ISTA 就是这两步的交替）")

    cv.text(18, 2, "收敛速率与适用场合（三种算法的分工）：")
    cv.text(19, 4, "ISTA（近端梯度）   O(1/t)     每步两次矩阵乘 + 一次软阈值")
    cv.text(20, 4, "FISTA（加速）      O(1/t^2)   加 Nesterov 动量：z = c + ((t-1)/(t+2))(c - c_prev)")
    cv.text(21, 4, "ADMM（分裂）       每轮解线性系统（D^T D + rho I 可预分解），适合大规模")
    cv.text(23, 2, "软阈值就是 l1 的 prox 算子；换成 l2 的 prox 就退化为岭回归的闭式解。")
    return cv.render()


# ======================================================================
# ch16 —— 经典控制数学
# ======================================================================

# ---------- ch16 block0：反馈回路与四个灵敏度函数 ----------
def fig_feedback_loop() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "反馈回路与四个灵敏度函数：S + T = 1 是逐频率的铁律。")

    cv.text(2, 2, "反馈回路：r -> (+) -> [C] -> u -> [P] -> (+) -> y")
    cv.text(3, 18, "^")
    cv.text(3, 44, "|")
    cv.text(4, 18, "|")
    cv.text(4, 24, "（下路为负反馈）")
    cv.text(4, 44, "|")
    cv.text(5, 18, "+" + "-" * 25 + "+")

    cv.text(7, 2, "四个灵敏度函数（L = C P 是回路传递函数）：")
    cv.text(8, 4, pad("函数", 10) + pad("表达式", 14) + pad("通路", 12) + "含义")
    cv.text(9, 4, pad("S", 10) + pad("1/(1+L)", 14) + pad("r->e, d->y", 12) + "灵敏度：抗扰能力")
    cv.text(10, 4, pad("T", 10) + pad("L/(1+L)", 14) + pad("r->y", 12) + "补灵敏度：跟踪能力")
    cv.text(11, 4, pad("CS", 10) + pad("C/(1+L)", 14) + pad("r,d->u", 12) + "控制代价（执行器负荷）")
    cv.text(12, 4, pad("PS", 10) + pad("P/(1+L)", 14) + pad("n->y", 12) + "量测噪声放大")

    cv.text(14, 2, "两条恒等式（一切换算都从它们出发，没有任何例外）：")
    cv.text(15, 4, "S + T = 1            任何频率都不可能同时缩小 |S| 与 |T|")
    cv.text(16, 4, "L = T / S            回路 = 「跟踪能力 / 抗扰能力」")

    cv.text(18, 2, "频段分工（这是全部设计的骨架）：")
    cv.text(19, 4, "低频 |L| >> 1   S 约 0，T 约 1     抗扰好、跟踪好（靠高增益）")
    cv.text(20, 4, "穿越 |L| 约 1   S、T 均约 0.7      两者都一般，PM 在此定义")
    cv.text(21, 4, "高频 |L| << 1   S 约 1，T 约 0     抗扰失效（低增益防噪声）")
    return cv.render()


# ---------- ch16 block1：根轨迹的辐角与幅值条件 ----------
def fig_root_locus() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "根轨迹：辐角条件定形状，幅值条件定增益刻度（两者完全分离）。")

    cv.text(2, 2, "辐角条件（只与位置有关，与 K 无关）——它决定轨迹的形状：")
    cv.text(3, 4, "angle(s-z1) - angle(s-p1) - angle(s-p2) = +/-180 度")
    cv.text(4, 2, "幅值条件（只决定 K 的刻度）：")
    cv.text(5, 4, "|s-z1| / ( |s-p1| * |s-p2| ) = 1 / K")

    cv.text(7, 2, "例：L = K / [ s (s+a) ]，开环极点 0 与 -a，水平方向 1 单位 = 12 列")

    cv.put(9, 31, "*")
    cv.put(9, 37, "*")
    cv.put(10, 32, "*")
    cv.put(10, 36, "*")
    cv.put(11, 33, "*")
    cv.put(11, 35, "*")
    cv.put(12, 34, "*")
    cv.vline(34, 13, 14, "|")
    cv.text(9, 44, "K 增大 -> 两支上下分开")
    cv.text(10, 44, "渐近线角度 +/-90 度")

    cv.put(15, 28, "x")
    cv.put(15, 34, "●")
    cv.put(15, 40, "x")
    cv.hline(15, 28, 40, "=")
    cv.hline(15, 2, 62, "-")
    cv.put(15, 28, "x")
    cv.put(15, 34, "●")
    cv.put(15, 40, "x")
    cv.text(15, 64, "sigma")
    cv.put(13, 40, "^")
    cv.vline(40, 14, 14, "|")
    cv.text(13, 42, "jw")

    cv.text(16, 28, "-a")
    cv.text(16, 32, "分离点 -a/2")
    cv.text(16, 40, "0")

    cv.text(18, 2, "实轴段判据：该点右侧的实极点 + 实零点个数为奇数（此处即 -a 到 0 段）")
    cv.text(19, 2, "分离点：解 d/ds [ D(s)/N(s) ] = 0  =>  2s + a = 0  =>  s = -a/2")
    cv.text(20, 2, "根和不变：两支的实部和恒等于 -a，故分离后垂直升降（对称）")

    cv.text(22, 2, "数值实现：A0 v = -K A1 v 是广义特征值问题，比展开多项式求根稳定得多。")
    return cv.render()


# ---------- ch16 block2：Nyquist 围道与绕数 ----------
def fig_nyquist_encircle() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Nyquist 判据：围道围住右半平面，像曲线绕 -1 的圈数决定闭环是否稳定。")

    cv.text(2, 4, "s 平面：围道 D（顺时针）")
    cv.text(3, 9, "jw")
    cv.put(3, 12, "^")
    cv.text(4, 12, "|")
    cv.text(5, 4, "--------+-------------------> sigma")
    cv.text(6, 12, "|")
    cv.text(7, 4, "（右半圆以无穷大半径闭合）")

    cv.text(2, 42, "L 平面：像曲线 L(D)")
    cv.text(3, 47, "Im")
    cv.put(3, 50, "^")
    cv.text(4, 50, "|")
    cv.text(5, 42, "--------+------(-1)--------> Re")
    cv.text(6, 50, "|")
    cv.text(7, 42, "（绕 (-1) 的圈数就是 N）")

    cv.text(9, 2, "辐角原理（第 30 章 30.3）：绕 (f'/f) 积分 = Z - P，左边就是像曲线绕原点圈数。")
    cv.text(10, 2, "取 f = 1 + L：零点 = 闭环极点，极点 = 开环极点，原点对应 -1 点。")

    cv.text(12, 4, "Z = P + N            （零点 = 极点 + 绕数）")
    cv.text(13, 4, "Z：闭环右半极点数   P：开环右半极点数   N：顺时针绕 -1 的圈数")

    cv.text(15, 2, "三种情形（稳定性要求 Z = 0，即 N = -P）：")
    cv.text(16, 4, "P = 0（开环稳定）  不绕 -1 就稳定 —— 最常用，但不是判据本身")
    cv.text(17, 4, "P = 1（开环不稳定）必须逆时针绕 1 圈，才把右半极点「换」回来")
    cv.text(18, 4, "P = 2              必须逆时针绕 2 圈")

    cv.text(20, 2, "时滞 e^(-s tau)：幅值恒为 1、相位 -w*tau 无界下降 => 像曲线绕原点无限旋转，")
    cv.text(21, 2, "故稳态增益存在有限上限，且稳定域可能是不连续的多段区间。")
    return cv.render()


# ---------- ch16 block3：Bode 图与两个裕度 ----------
def fig_bode_margin() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "Bode 图：幅频管性能、相频管稳定，而两者被斜率-相位关系强制锁在一起。")

    cv.text(2, 2, "幅频 |L| (dB)（横轴为对数频率，每个十倍频程等距）")
    cv.text(3, 4, " 40 |                    （纵轴为 dB，横轴为对数频率）")
    cv.text(4, 4, " 20 |===..___                     （折线为渐近近似）")
    cv.text(5, 4, "  0 |       `---..___              <- 穿越频率 wgc：|L| = 0 dB")
    cv.text(6, 4, "-20 |               `---..___")
    cv.text(7, 4, "-40 |                       `---..._____")
    cv.text(8, 8, "+-----+-----+-----+-----+-----+----> w")
    cv.text(9, 8, "0.1    1    10   100  1000")

    cv.text(11, 2, "相频 angle L (度)（幅相两条曲线不能独立选择）")
    cv.text(12, 4, "  0 |==..___                 <- 相位从这里开始下降")
    cv.text(13, 4, "-90 |      `---..___                    （斜率决定相位）")
    cv.text(14, 4, "-180|              `----..___      <- 相位穿越 wpc：angle = -180 度")
    cv.text(15, 8, "+-----+-----+-----+-----+-----+----> w")

    cv.text(17, 2, "两个裕度（都是几何距离）：")
    cv.text(18, 4, "GM = 1 / |L(j wpc)|     沿实轴到 -1 的距离（倍率），dB 取负号")
    cv.text(19, 4, "PM = 180 度 + angle L(j wgc)   绕原点还要转多少度才碰上 -1")

    cv.text(21, 2, "斜率-相位换算（最小相位系统，穿越点附近）：")
    cv.text(22, 4, "-20 dB/dec  ->  -90 度（剩余裕度约 90 度，稳）")
    cv.text(23, 2, "-40 dB/dec  ->  -180 度（临界振荡）；-60 dB/dec -> -270 度（必不稳定）")
    return cv.render()


# ---------- ch16 block4：PID 三项的频域分工 ----------
def fig_pid_geometry() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "PID 的三项 = 三个频段：把回路焊成 -20 dB/dec 的最小完备工具。")

    cv.text(2, 2, "        |C| (dB)          （横轴为对数频率，斜线为渐近斜率）")
    cv.text(3, 2, "        |                 D 项：+20 dB/dec，+90 度（补相位）")
    cv.text(4, 2, "        |                /           （零点清掉多余的 -20 段）")
    cv.text(5, 2, "        |               /            （斜率 +20 与 I 项的 -20 反向）")
    cv.text(6, 2, "        |              /             （高频抬增益：放大量测噪声）")
    cv.text(7, 2, "        |             /              （实际必须配低通 Tf = Td/N）")
    cv.text(8, 2, "        |------o-----/--------------  P 项：0 dB/dec，0 度（定穿越点）")
    cv.text(9, 2, "        |     /                      （P 决定带宽与快慢）")
    cv.text(10, 2, "        |    /       I 项：-20 dB/dec，-90 度（提低频增益）")
    cv.text(11, 2, "        |   /               （让低频更陡：阶跃无静差、抗扰好）")
    cv.text(12, 2, "        +--+-------------------------> w（对数轴）")

    cv.text(14, 2, "分工表（三个旋钮各管一段，互不越界）：")
    cv.text(15, 4, pad("P", 8) + pad("水平线", 10) + pad("0 度", 10) + "管穿越频率（带宽、快慢）")
    cv.text(16, 4, pad("I", 8) + pad("下降", 10) + pad("-90 度", 10) + "管低频增益（静差、抗扰）")
    cv.text(17, 4, pad("D", 8) + pad("上升", 10) + pad("+90 度", 10) + "管高频相位（阻尼、裕度）")

    cv.text(19, 2, "三条工程要点（与 Ziegler-Nichols 整定对接）：")
    cv.text(20, 2, "1) D 项的零点清掉对象多余的 -20 dB/dec，把穿越点拉回 -20（PM 变好）")
    cv.text(21, 2, "2) D 项必须配一阶低通 Tf = Td/N（N 取 8~20），否则高频噪声被无限放大")
    return cv.render()


# ======================================================================
# ch17 —— 现代控制：状态空间与线性系统
# ======================================================================

# ---------- ch17 block0：两条设计路的对照 ----------
def fig_ctrl_two_paths() -> list[str]:
    ROWS, COLS = 18, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "两条设计路：问法不同、目标一致；现代流程 = 状态空间设计 + 频域验收。")

    cv.text(2, 4, pad("频域路（第 16 章）", 30) + "状态空间路（本章）")
    cv.text(3, 4, pad("-" * 20, 30) + "-" * 24)

    rows = [
        ("指标：PM / GM / |S|", "指标：二次代价 J 或 |T_zw|"),
        ("自由度：零极点位置", "自由度：矩阵 K（一次定好）"),
        ("内环：黑箱（不可见）", "内环：状态 x 全部可见"),
        ("擅长：SISO、时滞、频域", "擅长：MIMO、多目标、扩展"),
        ("短板：MIMO 时幅值失效", "短板：需全状态（-> 观测器）"),
    ]
    for i, (a, b) in enumerate(rows):
        cv.text(4 + i, 4, pad(a, 30) + b)

    cv.text(10, 2, "两套语言的字典（这就是 17.3 的全部内容）：")
    cv.text(11, 4, "LQR 给出 PM >= 60 度       <- 状态空间到频域的免费鲁棒性")
    cv.text(12, 4, "H_2 范数 = LQG 的最优       <- 二次代价就是「平均能量」")
    cv.text(13, 4, "H_inf 范数 = |S| 的峰值    <- 最坏增益（第 20 章的主角）")

    cv.text(15, 2, "一句话：左边管「形状」，右边管「矩阵」；两者不能互相替代，只能互相翻译。")
    return cv.render()


# ---------- ch17 block1：LQR 的三条路与免费鲁棒性 ----------
def fig_lqr_geometry() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "LQR：把「无穷多个可行的 K」排序成唯一的一个（Riccati 方程就是排序机）。")

    cv.text(2, 2, "配方法（一行验算，最直观的一条路）：")
    cv.text(3, 4, "取 u = -K x，则  x^T Q x + u^T R u = -d/dt(x^T P x) + 完全平方项")
    cv.text(4, 4, "=>  J = x0^T P x0（与 u 无关，取下界即最优）=>  K = R^-1 B^T P")

    cv.text(6, 2, "Bryson 规则（把 Q、R 的未知个数降到 1，工程上必用）：")
    cv.text(7, 4, "Q_ii = 1 / (x_i_max)^2      R_jj = 1 / (u_j_max)^2")
    cv.text(8, 4, "=> 每个分量在「允许的最大偏差」处贡献相同的惩罚 1")
    cv.text(9, 4, "=> 再整体乘一个标量 rho：rho 是唯一需要调的旋钮")

    cv.text(11, 2, "惊人结论（SISO 且 R = 1）：| 1 + L(jw) | >= 1，对所有 w 成立")
    cv.text(12, 4, "几何：Nyquist 曲线永远落在以 -1 为圆心、1 为半径的圆之外")
    cv.text(13, 4, "=> PM >= 60 度，GM = 无穷 —— 这就是 LQR「免费的鲁棒性」")

    cv.text(15, 2, "但要付代价：一旦加上观测器（LQG），这份免费鲁棒性可能全部丢失")
    cv.text(16, 4, "H_2 指标是「平均」的，可以把误差堆在极窄的频段上而不被发现")
    cv.text(17, 4, "=> Doyle 反例（1978）=> Zames 提出 H_inf（1981）")
    return cv.render()


# ---------- ch17 block2：H2 与 H∞ 的几何 ----------
def fig_h2_hinf_ball() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "H_2 与 H_inf：同一个公式的两个极端（平均能量 vs 最坏增益）。")

    cv.text(2, 2, "输入单位球                    输出（放大倍数）")
    cv.text(3, 4, "|G|_2：L2 单位球（无限维）      总能量最大放大   —— 面积型指标")
    cv.text(4, 4, "|G|_inf：单一频率正弦            最大半径         —— 峰值型指标")

    cv.text(6, 2, "对比例子：G_2 在 w 约 1/eps 处有一个极窄的谐振峰")
    cv.text(7, 4, "|G_2|_2   约等于 |G_1|_2          窄峰对积分贡献极小（eps 越小越无关）")
    cv.text(8, 4, "|G_2|_inf 约等于 1/(2 zeta)       峰高只由阻尼决定，与 eps 无关")
    cv.text(9, 4, "=> 「H_2 最优」不等于「好用」—— 这就是 Doyle 反例的频域解剖")

    cv.text(11, 2, "小增益定理（把模型不确定性接进来的唯一入口）：")
    cv.text(12, 4, "| Delta M |_inf < 1   =>  闭环稳定（对所有 |Delta|_inf <= 1 成立）")
    cv.text(13, 4, "MIMO 时读作 bar_sigma( M(jw) ) < 1 对所有 w 成立")

    cv.text(15, 2, "乘性误差版（最常用）：| W_m(jw) T(jw) | < 1 对所有 w")
    cv.text(16, 2, "读法：|T| 在哪段频域大，就要求模型在那段频域准（|W_m| 小）——")
    cv.text(17, 2, "      这与 16.1.3 的水床效应呼应：T 的峰值决定模型精度的要求。")
    return cv.render()


# ---------- ch17 block3：Gramian 椭球与平衡截断 ----------
def fig_gramian_balance() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "平衡截断：把两个椭球对齐后，坐标轴半轴长就是 Hankel 奇异值。")

    cv.text(2, 2, "原始坐标（两个椭球方向错开，无法直接比较）：")
    cv.text(3, 8, ",--.")
    cv.text(4, 6, ",'    `.")
    cv.text(4, 28, "（两个椭球的主轴方向一般不重合）")
    cv.text(5, 5, "/   /\\   \\")
    cv.text(6, 5, "\\  /  \\  /")
    cv.text(6, 28, "（所以不能直接删掉某个椭球短轴上的状态）")
    cv.text(7, 6, "`-..-'")
    cv.text(3, 28, "能控椭球：单位能量输入能到达的状态集合")
    cv.text(5, 28, "能观椭球：初始状态产生的输出能量")
    cv.text(7, 28, "方向不一致 => 「难到达」可能同时「很显眼」")

    cv.text(9, 2, "平衡坐标（把两者对齐，同时对角化）：")
    cv.text(10, 8, "|\\")
    cv.text(11, 8, "| \\")
    cv.text(12, 8, "|  \\")
    cv.text(12, 28, "（轴长按大小排序：sigma_1 最大）")
    cv.text(13, 8, "|   \\")
    cv.text(10, 28, "Wc = Wo = diag(sigma_1, sigma_2, ...)")
    cv.text(11, 28, "半轴长 sigma_1 >= sigma_2 >= ... > 0")
    cv.text(13, 28, "每个方向的可达性与显眼度完全相同")

    cv.text(15, 2, "截断（丢掉 sigma 很小的那些轴，得到 r 阶模型）：")
    cv.text(16, 4, "|| G - G_r ||_inf  <=  2 * sum_{i > r} sigma_i       上界（Glover）")
    cv.text(17, 4, "min over 任何 r 阶模型 >= sigma_{r+1}             下界（内禀极限）")

    cv.text(19, 2, "经验规律：sigma_i 断崖式下跌的系统最适合降阶")
    cv.text(20, 2, "（少数主导模态 + 大量快而不显眼的模态：热传导、柔性结构、电网）")
    return cv.render()


# ---------- ch17 block4：数字回路的相位损失 ----------
def fig_sampled_phase() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "数字回路的相位损失：采样率由相位裕度决定，不由 Nyquist 决定。")

    cv.text(2, 2, "y -->[抗混叠]-->[A/D]-->[计算延迟一拍]-->[D/A + ZOH]--> u")

    cv.text(4, 2, pad("环节", 20) + pad("相频（低频近似）", 22) + "在 wgc 处的损失")
    cv.text(5, 2, "-" * 68)
    cv.text(6, 2, pad("采样平均", 20) + pad("-wT/2", 22) + "-wgc*T/2")
    cv.text(7, 2, pad("计算延迟", 20) + pad("-wT", 22) + "-wgc*T        <- 最致命")
    cv.text(8, 2, pad("ZOH", 20) + pad("-wT/2", 22) + "-wgc*T/2")
    cv.text(9, 2, "-" * 68)
    cv.text(10, 2, pad("合计", 20) + pad("-2wT", 22) + "-2*wgc*T")

    cv.text(12, 2, "例：wgc = 5 rad/s，设计目标 PM = 60 度")
    cv.text(13, 4, "T = 0.02 s（50 Hz，ws/wgc = 63）  dPM = -11.5 度   PM -> 48.5  可用")
    cv.text(14, 4, "T = 0.05 s（20 Hz，ws/wgc = 25）  dPM = -28.6 度   PM -> 31    振荡")

    cv.text(16, 2, "三条修法（按推荐顺序）：")
    cv.text(17, 4, "1) 设计时预先扣除：按 PM = 71 度 设计，落地后正好落到 60 度")
    cv.text(18, 4, "2) 提高采样率：最直接，但要付量化噪声与计算量的代价")
    cv.text(19, 4, "3) 用预测型结构：把延迟挪到「已知」的位置（第 19 章 19.7 MPC 的思路）")
    return cv.render()


# ======================================================================
# ch18 —— 稳定性理论
# ======================================================================

# ---------- ch18 block0：六种稳定性的几何 ----------
def fig_stability_zoo() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "六种稳定性：从「一直近」到「一直近且最终到」，再到「有多快」。")

    cv.text(2, 4, pad("Lyapunov 稳定", 18) + pad("渐近稳定", 18) + pad("指数稳定", 18) + "不稳定")
    cv.text(3, 4, pad("  .--.", 18) + pad("   ,--.", 18) + pad("   ,--.", 18) + "  \\   /")
    cv.text(4, 4, pad(" (    )", 18) + pad("  (    )", 18) + pad("  (    )", 18) + "   \\ /")
    cv.text(5, 4, pad("  `--'", 18) + pad("   `--'", 18) + pad("   `--'", 18) + "    X")
    cv.text(6, 4, pad("一直近", 18) + pad("一直近 + 最终到", 18) + pad("有速率", 18) + "跑远")

    cv.text(8, 2, "层次关系（箭头单向，反向全部不成立）：")
    cv.text(9, 4, "指数稳定  ==>  渐近稳定  ==>  Lyapunov 稳定")
    cv.text(10, 4, "全局渐近 GAS  ==>  渐近稳定（吸引域定义为全空间）")

    cv.text(12, 2, "三个必须记住的反例（线性化全是 A = 0，结论完全不同）：")
    cv.text(13, 4, "x' = -x^3    渐近稳定但非指数（代数衰减 x ~ t^(-1/2)）")
    cv.text(14, 4, "x' = 0       稳定但不渐近（轨线原地不动）")
    cv.text(15, 4, "x' = x^3     不稳定（线性化完全看不出）")
    cv.text(16, 4, "x'' + x = 0  涡旋：dV/dt = 0，稳定但不渐近（闭合轨道）")

    cv.text(18, 2, "结论：Lyapunov 稳定本身很弱（x' = 0 也满足），工程上真正要的是")
    cv.text(19, 2, "渐近稳定，而验收时最关心的是「吸引域有多大」。")
    return cv.render()


# ---------- ch18 block1：LaSalle 不变原理 ----------
def fig_lasalle() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "LaSalle：dV/dt <= 0 时，轨线趋于「dV/dt = 0 的最大不变集」。")

    cv.text(2, 6, ".-------------------.")
    cv.text(3, 4, "/   ,-----------,     \\")
    cv.text(4, 3, "|   /             \\     |")
    cv.text(5, 3, "|  |       M       |    |")
    cv.text(6, 3, "|   \\             /     |")
    cv.text(7, 4, "\\   `-----------'     /")
    cv.text(8, 6, "`-------------------'")
    cv.text(2, 30, "外层：V = c3（等高线）")
    cv.text(4, 30, "内层：M = 最大不变集")
    cv.text(6, 30, "dV/dt < 0 处轨线一律向内穿")
    cv.text(8, 30, "（不能穿过等高线向外）")

    cv.text(10, 2, "零集 E = { dV/dt = 0 } 的三种形态，决定三种结论：")
    cv.text(11, 4, "E = 平行的直线         ->  M 可能只是原点  =>  渐近稳定")
    cv.text(12, 4, "E = 一条闭轨           ->  M 就是该闭轨    =>  收敛到极限环")
    cv.text(13, 4, "E = 整个不变子空间     ->  M 非平凡        =>  只稳定，不渐近")

    cv.text(15, 2, "阻尼摆（LaSalle 的典型用法）：")
    cv.text(16, 4, "V = w^2/2 + (1 - cos th) >= 0        dV/dt = -w^2 <= 0（不是负定！）")
    cv.text(17, 4, "零集是 w = 0 轴；但轴上除平衡点外 dw/dt = -sin th != 0")
    cv.text(18, 4, "=> 轨线不能在零集上停留 => 最大不变集 = {(0,0)} => 渐近稳定")

    cv.text(20, 2, "与线性理论的关系（这条最重要）：")
    cv.text(21, 2, "dV/dt = -x^T Q x 时，最大不变集 = {0} 当且仅当 (Q, A) 能观。")
    cv.text(22, 2, "=> 「能观性」在非线性里的对应物就是「零集里没有非平凡不变集」。")
    return cv.render()


# ---------- ch18 block2：ISS 与增益函数 ----------
def fig_iss_gain() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "ISS：输入小则状态最终小 —— 第一项记忆初始条件，第二项由输入决定。")

    cv.text(2, 2, "|x(t)|                      （纵轴：状态范数；横轴：时间）")
    cv.text(3, 4, "*                                beta(|x0|, t)：初始条件的记忆，衰减")
    cv.text(4, 6, "*___                            （这一段的下降形状由 beta 决定）")
    cv.text(5, 10, "`-----..___________________________")
    cv.text(6, 50, "<- 渐近高度 = gamma(|u|)")
    cv.text(7, 2, "-" * 70 + "> t")
    cv.text(8, 8, "稳态带的高度由 gamma(|u|) 决定，它不随时间消失")

    cv.text(11, 2, "两个函数类：beta 属于 KL（对 t 递减到 0），gamma 属于 K（严格递增）")
    cv.text(12, 2, "=> u = 0 时退化为「原点 GAS」，故 ISS 强于 GAS（GAS 不含 ISS）")

    cv.text(14, 2, "小增益定理（ISS 版）：gamma1( gamma2(r) ) < r  对所有 r > 0")
    cv.text(15, 4, "线性时退化为 |G1|_inf * |G2|_inf < 1（与第 17 章完全一致）")
    cv.text(16, 4, "非线性必须写成「函数复合」：函数会饱和 => 复合自动有界 => 易满足")

    cv.text(18, 2, "四个只在非线性出现的现象：")
    cv.text(19, 4, "1) 零输入 GAS，但任意小的持续输入就发散（x' = -x + x^2 u）")
    cv.text(20, 4, "2) 有限逃逸时间（x' = 1 + x^2 的解 tan t，t -> pi/2 时发散）")
    cv.text(21, 2, "3) 增益依赖工作点；4) 吸引域随输入幅值被挤小。")
    return cv.render()


# ---------- ch18 block3：圆判据与 Popov ----------
def fig_circle_popov() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "绝对稳定性：一个线性系统 + 一个扇形非线性，对扇形内所有非线性都稳定。")

    cv.text(2, 8, "Im                （Nyquist 复平面）")
    cv.text(3, 10, "^                 （纵轴：虚部）")
    cv.text(4, 10, "|                 （横轴：实部）")
    cv.text(5, 4, "--------+-----------------------------> Re")
    cv.text(6, 10, "|                 （Nyquist 曲线画在这张图上）")
    cv.text(7, 2, "  -1/k2        -1/k1        （两个扇形边界的倒数，都在负实轴上）")

    cv.text(9, 20, ".-----------------.")
    cv.text(10, 18, "/                   \\")
    cv.text(11, 17, "|     圆心 c          |")
    cv.text(12, 18, "\\                   /")
    cv.text(13, 20, "`-----------------'")
    cv.text(10, 42, "圆盘 D(k1,k2)：由扇形界算出")
    cv.text(11, 42, "Nyquist 曲线完全落在圆盘外")
    cv.text(12, 42, "=> 闭环绝对稳定")

    cv.text(15, 2, "k1 = 0 的退化（饱和、死区都属于这一类）：圆盘退化为半平面")
    cv.text(16, 4, "判据变成：Re G(jw) > -1/k2 对所有 w             （最常用的一行！）")

    cv.text(18, 2, "Popov：再引入参数 eta >= 0（利用了「时不变」这一额外信息）")
    cv.text(19, 4, "修正频率响应 G*(jw) = Re G + j w Im G          （把虚部乘 w 倍）")
    cv.text(20, 4, "=> 判据变成 G* 曲线位于直线 Re = -1/k 的右侧")

    cv.text(21, 2, "保守性排序（用的信息越来越多）：小增益 > 圆判据 > Popov")
    return cv.render()


# ---------- ch18 block4：分岔与极限环 ----------
def fig_bifurcation() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "分岔：参数连续变化，稳定性突然翻脸（线性系统永远不会这样）。")

    cv.text(2, 2, "鞍结：x' = mu - x^2                   叉式：x' = mu x - x^3")
    cv.text(3, 2, "  x                                    x")
    cv.text(4, 2, "  ^  \\    /                            ^        /  |  \\")
    cv.text(5, 2, "  |   \\  /                             |       /   |   \\")
    cv.text(6, 2, "  |    \\/                              |      /    |    \\")
    cv.text(7, 2, "  +----X--------> mu                   +-----X-----X-----> mu")
    cv.text(8, 2, "  mu<0 无；mu=0 一个（半稳定）；        mu<0 一个稳定 0；")
    cv.text(9, 2, "  mu>0 一对（一稳一不稳）              mu>0 0 变不稳 + 两侧一对稳定")

    cv.text(11, 2, "Hopf：一对共轭特征值穿过虚轴 => 平衡点生极限环")
    cv.text(12, 4, "极限环幅值 ~ sqrt(mu - mu_c)      <- 平方根依赖是 Hopf 的签名")
    cv.text(13, 4, "亚临界 Hopf（l1 > 0）伴随滞后与双稳态 => 突然失稳的常见机制")

    cv.text(15, 2, "极限环的两条存在性判据（二维独有）：")
    cv.text(16, 4, "Poincare-Bendixson：有界闭区域内无平衡点 => 必有闭轨")
    cv.text(17, 4, "Bendixson 排除法：散度 div f 不变号且不恒为零 => 区域内无闭轨")
    cv.text(18, 4, "   线性情形 div(Ax) = tr A，故 tr A != 0 时线性系统无闭轨")

    cv.text(20, 2, "Van der Pol 的能量机制（自持振荡的本质）：")
    cv.text(21, 2, "|x| < 1 时负阻尼注入能量 -> 振幅增大；|x| > 1 时正阻尼耗散 -> 缩小")
    return cv.render()


# ---------- ch19 block0：三条解法路线 ----------
def fig_opt_three_routes() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "三条解法路线：同一个问题的三种写法，差别只在「对什么求极值」。")

    C1, C2, CW = 2, 28, 24
    cv.text(2, C1, pad("变分法(古典)", CW) + pad("PMT(1956)", CW) + "HJB(Bellman 1957)")
    cv.text(3, C1, pad("对轨线求导", CW) + pad("对 H 逐点求极小", CW) + "对值函数解 PDE")
    cv.text(4, C1, pad("dH/du = 0", CW) + pad("min_u H", CW) + "-dV/dt = min{ L+gradV.f }")
    cv.text(5, C1, pad("-" * 10, CW) + pad("-" * 10, CW) + "-" * 10)
    cv.text(6, C1, pad("必要条件", CW) + pad("必要条件", CW) + "充分条件(全局)")
    cv.text(7, C1, pad("要可微 + 解在内点", CW) + pad("只要 U 是紧集", CW) + "直接给出反馈律")
    cv.text(8, C1, pad("控制受约束就失效", CW) + pad("能处理 bang-bang", CW) + "代价: 解不动的 PDE")
    cv.text(9, C1, pad("实用: 弱", CW) + pad("实用: 强(打靶法)", CW) + "实用: 弱(维度诅咒)")

    cv.text(11, 2, "三者的关系（记成一张图，而不是三条并列的路）：")
    cv.text(12, 10, "\\                       |                        /")
    cv.text(13, 12, "+-- 变分法是共同祖先 ---+--- 桥梁 lambda = grad V ---+")
    cv.text(14, 26, "=>  PMT 就是 HJB 的特征线方程")

    cv.text(16, 2, "为什么会有三条路：历史上分别独立发现（1696 变分法 / 1956 PMT / 1957 HJB），")
    cv.text(17, 2, "其中只有 PMT 允许控制受限，只有 HJB 直接给反馈律，只有变分法最古老。")
    cv.text(19, 2, "共同祖先的传播路径：古典变分法 -> 引入协态 -> 逐点极小化  =  PMT")
    cv.text(20, 2, "                                          -> 最优性原理  =  HJB")
    return cv.render()


# ---------- ch19 block1：极小值原理与 H 对 u 的三种形状 ----------
def fig_pmp_geometry() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "极小值原理：把「求导为零」换成「逐点取极小」，控制约束就不再是障碍。")

    C1, C2, CW = 2, 26, 22
    cv.text(2, C1, pad("凸二次", CW) + pad("线性", CW) + "线性且系数恒零")
    cv.text(3, C1, pad("  H", CW) + pad("  H", CW) + "  H")
    cv.text(4, C1, pad("  |  \\        /", CW) + pad("  |          /", CW) + "  |")
    cv.text(5, C1, pad("  |   \\      /", CW) + pad("  |         /", CW) + "  |")
    cv.text(6, C1, pad("  |    \\    /", CW) + pad("  |        /", CW) + "  |")
    cv.text(7, C1, pad("  |     \\__/", CW) + pad("  |       /", CW) + "  |=========")
    cv.text(8, C1, pad("  +----------- u", CW) + pad("  +-------+-- u", CW) + "  +-------+-- u")
    cv.text(9, C1, pad("   极小在内部", CW) + pad("   极小在端点", CW) + "   min 无解")

    cv.text(11, 2, "三种形状决定三类解（拿到一个问题，先看 H 对 u 的形状）：")
    cv.text(12, 4, "凸二次        ->  LQR / 最小能量：控制连续、鲁棒、易实现")
    cv.text(13, 4, "线性          ->  最小时间 / 最小燃料：全有或全无，切换次数 <= n-1")
    cv.text(14, 4, "线性且恒零    ->  奇异弧：最省的阶段，需 Kelley 条件验二阶最优")

    cv.text(16, 2, "切换函数 b(t) = lambda^T B 的读法（单输入、U = [u_min, u_max] 时）：")
    cv.text(17, 4, "b(t) > 0  取 u_min      （极小化 b*u，所以取使 b*u 更小的那个端点）")
    cv.text(18, 4, "b(t) < 0  取 u_max")
    cv.text(19, 4, "b 在一段区间上恒零  ->  奇异弧（min 条件失效，需逐阶求导才能定 u）")
    return cv.render()


# ---------- ch19 block2：HJB 与 PMT 的缝合 ----------
def fig_hjb_flow() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "HJB 与 PMT 是同一件事的两面，桥梁是 lambda(t) = grad V(x*(t), t)。")

    L, CW = 4, 34
    cv.text(2, L, pad("HJB（全局）", CW) + "PMT（沿一条轨线）")
    cv.text(3, L, pad("-" * 16, CW) + "-" * 16)
    cv.text(4, L, pad("求 V(x,t)：所有初值的代价", CW) + "求 lambda(t)：一条轨线的协态")
    cv.text(5, L, pad("一阶非线性 PDE", CW) + "常微分方程（可数值积分）")
    cv.text(6, L, pad("充分条件（解出即全局最优）", CW) + "必要条件（可能是鞍点）")
    cv.text(7, L, pad("直接给反馈律 kappa(x,t)", CW) + "只给开环 u(t)")
    cv.text(8, L, pad("难点：解 PDE（维度诅咒）", CW) + "难点：两点边值（正向积分发散）")

    cv.text(10, L + 14, "\\                     /")
    cv.text(11, L + 16, "沿最优轨线： lambda = grad V")
    cv.text(12, L + 14, "/                     \\")

    cv.text(14, L, "对 HJB 求 grad_x，用包络定理  =>  协态方程 d lambda/dt = -dH/dx")
    cv.text(16, L, "证明三步：① min 的一阶条件 = 控制方程；② 对 HJB 求 grad_x = 协态方程；")
    cv.text(17, L, "          ③ 由 V(x,T) = Phi 求 grad_x = 横截条件。")
    cv.text(19, L, "分歧点：V 不可微处（bang-bang 的切换点）lambda = grad V 断裂")
    cv.text(20, L, "  => HJB 要靠粘性解；PMT 只需「几乎处处」成立，因此更耐用。")
    return cv.render()


# ---------- ch19 block3：双积分器相平面与切换曲线 ----------
def fig_bangbang_phase() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "双积分器时间最优：切换曲线 x1 = x2*|x2|/2，闭环律在曲线上跳变。")

    cv.text(2, 17, "x2 ^")
    cv.text(3, 20, "|")
    cv.text(3, 44, "（纵轴：速度 x2）")
    cv.text(4, 34, ",'")
    cv.text(4, 44, "u = -1 区（切换曲线上方）")
    cv.text(5, 29, ",-'")
    cv.text(5, 44, "先减速，直到撞上切换曲线")
    cv.text(6, 25, ",-")
    cv.text(6, 44, "切换曲线：x1 = + x2^2 / 2")
    cv.text(7, 22, ",")
    cv.text(7, 44, "（x2 > 0 分支）")
    cv.text(8, 2, "-" * 18 + "*" + "-" * 40 + "> x1")
    cv.text(9, 18, ",")
    cv.text(9, 44, "（横轴：位置 x1）")
    cv.text(10, 15, ",'")
    cv.text(10, 44, "u = +1 区（切换曲线下方）")
    cv.text(11, 11, ",'")
    cv.text(11, 44, "先加速，直到撞上切换曲线")
    cv.text(12, 7, ",'")
    cv.text(12, 44, "切换曲线：x1 = - x2^2 / 2")
    cv.text(13, 44, "（x2 < 0 分支）")

    cv.text(15, 2, "闭环读法：先用常值 u 沿一族抛物线前进，撞上切换曲线后立即换号，")
    cv.text(16, 2, "          再沿另一族抛物线直达原点 —— 最多切换一次（n = 2 的上界）。")
    cv.text(18, 2, "注意：闭环律在切换曲线上不连续 —— 这是「最优 vs 光滑」的固有冲突，")
    cv.text(19, 2, "      工程上必须用滞环/边界层把它变成可实现的准时间最优。")
    return cv.render()


# ---------- ch19 block4：MPC 滚动时域 ----------
def fig_mpc_recede() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "MPC 的三步循环：预测 -> 只执行第一步 -> 滚动，每个采样时刻重解优化。")

    cv.text(2, 4, "< 已执行 >                <        预 测 窗 口        >")
    cv.text(3, 4, "==========|=============================================> t")
    cv.text(4, 15, "^ k")
    cv.text(5, 15, "当前状态 x_k")
    cv.text(4, 58, "k+N")
    cv.text(5, 54, "终端代价 Phi(x_{k+N})")

    cv.text(7, 4, "[1  预测]  以 x_k 为初值，在 [k, k+N] 上解一个带约束的优化：")
    cv.text(8, 14, "min  sum_{i=0}^{N-1} L(x_i, u_i) + Phi(x_{k+N})")
    cv.text(9, 14, "s.t. x_{i+1} = f(x_i, u_i),   u in U,   x in X")
    cv.text(10, 4, "[2  执行]  只把最优序列的第一个 u_k 施加到系统（其余丢掉）")
    cv.text(11, 4, "[3  滚动]  k <- k+1，用新的测量 x_{k+1} 重解 —— 反馈藏在这个「重解」里")

    cv.text(13, 4, "为什么 MPC 能处理约束：U 与 X 就是优化的显式约束（变分法做不到）")
    cv.text(14, 4, "稳定性的三件套（否则「每步最优」不保证闭环稳定）：")
    cv.text(15, 6, "(a) 终端等式 x_{k+N} = 0                          最严格、最保守")
    cv.text(16, 6, "(b) 终端代价 Phi = x^T P x（P 解 ARE）+ 终端不变集    标准做法")
    cv.text(17, 6, "(c) 准无限时域（N 取很大）                        理论保证最弱、实践最常用")

    cv.text(19, 4, "与 LQR 的关系：去掉约束 + N -> 无穷 + 线性模型 + 二次代价  =  LQR")
    cv.text(20, 4, "（此时「只执行第一步」与「执行全部」完全一样，无需重解）")
    return cv.render()


# ---------- ch20 block1：不确定性分类总览 ----------
def fig_uncertainty_zoo() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "不确定性的三种描述：先问「我知道多少」，再决定「用什么工具」。")

    C1, C2, CW = 4, 26, 20
    cv.text(2, C1, pad("非结构（范数球）", CW) + pad("结构（块对角）", CW) + "参数（区间）")
    cv.text(3, C1, pad("-" * 16, CW) + pad("-" * 16, CW) + "-" * 12)
    cv.text(4, C1, pad("只知道误差多大", CW) + pad("知道哪些块在变", CW) + "知道哪个物理参数")
    cv.text(5, C1, pad("小增益定理", CW) + pad("mu / 主回路定理", CW) + "Kharitonov 定理")
    cv.text(6, C1, pad("||W_m T||_inf < 1", CW) + pad("mu(w) < 1", CW) + "四个多项式稳定")
    cv.text(7, C1, pad("保守可达 sqrt(n) 倍", CW) + pad("紧（总块数 <= 3）", CW) + "紧（系数独立）")
    cv.text(8, C1, pad("适用：说不清来源", CW) + pad("适用：能列出块", CW) + "适用：能写区间")

    cv.text(10, 2, "三种回路位置：同一个物理误差挂在不同支路，判据的形式完全不同。")
    cv.text(11, 4, "加性     P = P0 + W_a D         -> 判据含 K S     只管高频")
    cv.text(12, 4, "乘性     P = (I + W_m D) P0     -> 判据含 T       高频误差首选")
    cv.text(13, 4, "互质因子 P = (N+dN)(M+dM)^-1    -> 判据含 S       唯一管零点漂移")

    cv.text(15, 2, "选择顺序（能用结构就别用非结构：保守度最多差 sqrt(n) 倍）：")
    cv.text(16, 4, "能列出参数与区间  ->  20.5 的代数工具（最快、最精确）")
    cv.text(17, 4, "能列出块结构      ->  20.3 的 mu（主回路定理）")
    cv.text(18, 4, "只有误差量级      ->  20.2 的小增益（最保守，也最省事）")

    cv.text(20, 2, "记住：不确定性描述得越细，结论就越不保守 —— 整章的技巧全在这句话里。")
    return cv.render()


# ---------- ch20 block3：标准 P-K-Delta 结构 ----------
def fig_lft_standard() -> list[str]:
    ROWS, COLS = 23, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "标准 P-K-Delta 结构：一切鲁棒问题的通用外形（LFT 互联）。")

    cv.text(2, 4, "  w --->+----> [    Delta    ] ---->+----> z")
    cv.text(3, 4, "        |                           |")
    cv.text(4, 4, "        +----> [ N = F_l(M,K) ] ----+")
    cv.text(5, 4, "                   ^        |")
    cv.text(6, 4, "                   |        v")
    cv.text(7, 4, "        u ---------+        +------ y -----> [   K   ]")

    cv.text(9, 2, "两个层次（分开才能交替迭代 —— 这是 D-K 能工作的结构性前提）：")
    cv.text(10, 4, "[下层] 把 K 折进 M：N = F_l(M, K)              <- H-infinity 综合")
    cv.text(11, 4, "[上层] 把 Delta 折进 N：det(I - N Delta) != 0  <- mu 分析（鲁棒性）")

    cv.text(13, 2, "三种经典扰动模型都是它的特例（Delta 只是挂在 M 的不同支路上）：")
    cv.text(14, 4, "加性     P = P0 + W_a Delta       -> 判据 || W_a K S || < 1")
    cv.text(15, 4, "乘性     P = (I + W_m Delta) P0   -> 判据 || W_m T ||   < 1")
    cv.text(16, 4, "反馈     P = (N+dN)(M+dM)^-1      -> 判据含 S（唯一管零点漂移）")

    cv.text(18, 2, "混合灵敏度：把「性能要求」也变成一个虚拟满块 Delta_P（20.1.4）：")
    cv.text(19, 4, "z = [ W1 S w ;  W2 K S w ;  W3 T w ]，要求 || z ||_2 / || w ||_2 < 1")
    cv.text(20, 4, "W1 管 S（低频性能）   W2 管 K S（控制量）   W3 管 T（高频鲁棒）")

    cv.text(22, 2, "顺序不能反：先组 M、再折 K、最后折 Delta —— 反了维数一定对不上。")
    return cv.render()


# ---------- ch20 block4：性能与鲁棒的两条边界 ----------
def fig_robust_two_bounds() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "性能与鲁棒的两条边界线：|S| 要压下去、|T| 也要压下去，两者互相顶住。")

    cv.text(2, 3, "  40 |  1/|W1|")
    cv.text(2, 44, "性能上界（|S| 必须在它下方）")
    cv.text(3, 3, "     |    \\")
    cv.text(3, 44, "W1 的拐点由「带宽下限」定")
    cv.text(4, 3, "  20 |     \\")
    cv.text(4, 44, "低频压 |S| = 好的追踪与抗扰")
    cv.text(5, 3, "     |      \\       ~~~~~")
    cv.text(5, 44, "|T| 实际形状（峰值受 W3 约束）")
    cv.text(6, 3, "   0 |-------+---=====~~~~~------ 0 dB")
    cv.text(7, 3, "     |       |  #         #")
    cv.text(7, 44, "S 与 T 在此频段完成交接")
    cv.text(8, 3, " -20 |       | #           \\")
    cv.text(8, 44, "1/|Wm|：高频必须放宽")
    cv.text(9, 3, "     |       |#             \\")
    cv.text(9, 44, "（高频的模型本来就不可信）")
    cv.text(10, 3, " -40 |      #                \\")
    cv.text(11, 3, "     +------+------------------\\--> w")

    cv.text(13, 2, "可行的硬条件（交叠频段必须满足，否则问题无解 —— 不是算法问题）：")
    cv.text(14, 4, "1 / |W1(jw)|  +  1 / |Wm(jw)|  >=  1          对所有 w")
    cv.text(15, 2, "因为 |S| + |T| >= |S + T| = 1，两条上界的和小于 1 就自相矛盾。")

    cv.text(17, 2, "两个分界点决定一切：|S| 与 1/|W1| 的交点给带宽下限，")
    cv.text(18, 2, "|T| 与 1/|Wm| 的交点给带宽上限 —— 两者都存在才叫「可行」。")
    cv.text(20, 2, "不满足时唯一正解：放宽 W1（承认性能要求过高），而不是加大迭代次数。")
    return cv.render()


# ---------- ch20 block5：mu 与 sigma 的几何 ----------
def fig_mu_geometry() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "mu 与 sigma 的几何差别：外接球（sigma）vs 最小外接盒（mu）。")

    cv.text(2, 2, "无结构（范数球）：Delta 可以指向任意方向")
    cv.text(3, 8, "\\\\     |     /")
    cv.text(3, 30, "外接圆的半径 = bar_sigma(M)")
    cv.text(4, 9, "\\\\    |    /")
    cv.text(4, 30, "取 max 的方向可能实际达不到")
    cv.text(5, 10, "--(    M    )--")
    cv.text(5, 30, "=> 保守：把「不可能」也当可能")
    cv.text(6, 9, "//    |    \\\\")
    cv.text(6, 30, "保守因子最多 sqrt(n) 倍")
    cv.text(7, 8, "//     |     \\\\")
    cv.text(7, 30, "（无结构 = 全空间，只能给上界）")

    cv.text(9, 2, "结构化（块对角）：只能沿各个坐标轴缩放")
    cv.text(10, 8, "+-----+-----+")
    cv.text(10, 30, "最小外接盒的半宽 = mu(M)")
    cv.text(11, 8, "| d1  |     |")
    cv.text(11, 30, "只在 Delta 允许的方向上取最坏")
    cv.text(12, 8, "+-----+-----+")
    cv.text(12, 30, "块结构 = 物理知识的载体")
    cv.text(13, 8, "|     | d2  |")
    cv.text(13, 30, "实块最难（NP 难）；复块有凸上界")
    cv.text(14, 8, "+-----+-----+")
    cv.text(14, 30, "总块数 <= 3 时上下界相等")

    cv.text(16, 2, "读数（三条）：rho(M) <= mu(M) <= bar_sigma(M)")
    cv.text(17, 2, "mu = bar_sigma 当且仅当「单个满块」或「方向均衡」—— 此时没有保守")
    cv.text(18, 2, "最大差距 = sqrt(n) 倍：n 个通道必须「同时」被攻击才能破坏稳定性")

    cv.text(20, 2, "结论：信息越多（结构越具体），mu 就越小 —— mu 的全部价值就在这句。")
    return cv.render()


# ---------- ch20 block8：D-K 迭代 ----------
def fig_dk_loop() -> list[str]:
    ROWS, COLS = 25, 78
    cv = Canvas(ROWS, COLS)

    cv.text(0, 2, "D-K 迭代：两个凸问题交替 —— 各自好解，合起来不保证全局最优。")

    _frame(cv, 2, 3, 5, 54)
    cv.text(3, 5, "K 步：固定 D，解 H-infinity 问题")
    cv.text(4, 5, "   min_K  ||  D F_l(P,K) D^-1  ||_inf")

    cv.text(6, 24, "|")
    cv.text(6, 30, "得到 K_k 与 gamma_k")
    cv.text(7, 24, "v")
    cv.text(7, 30, "（gamma_k 单调不增、有下界 => 必有极限）")

    _frame(cv, 8, 3, 12, 54)
    cv.text(9, 5, "D 步：固定 K，逐频率解 LMI")
    cv.text(10, 5, "   min_D  sigma_bar( D M D^-1 )")
    cv.text(11, 5, "   再用「稳定且最小相位」的有理函数拟合 D(w)")

    cv.text(13, 24, "|")
    cv.text(13, 30, "得到 D_k")
    cv.text(14, 24, "v")
    cv.text(14, 30, "（拟合质量直接决定下一次 K 步的好坏）")

    cv.text(15, 3, "+--- gamma_k 是否 < 1 ? ---+")
    cv.text(15, 32, "唯一的分支点：成功即停手")
    cv.text(16, 5, "是  ->  停手（成功，输出 K_k 与 mu 上界）")
    cv.text(17, 5, "否  ->  回 K 步，带上新的 D_k（迭代继续）")

    cv.text(19, 2, "停手判据：gamma < 1，或连续两次改善 < 2%（此时已进入局部最优）。")
    cv.text(20, 2, "卡住时先查权重相容性（1/|W1| + 1/|W3| >= 1），再换初值，最后才改块结构。")
    cv.text(22, 2, "为什么两个凸问题合起来不凸：D 步的最优 D 依赖于 K，K 步的最优 K 又依赖于 D，")
    cv.text(23, 2, "这个耦合没有全局结构 —— 所以 D-K 只是在「联合驻点」上停下，而非全局最优。")
    return cv.render()


# ======================================================================
# 第 21 章：随机控制与估计
# ======================================================================

# ---------- ch21 block0：三种不确定性哲学 ----------
def fig_uncertainty_philosophy() -> list[str]:
    ROWS, COLS = 20, 76
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "不确定性的三种描述哲学：信息需求递减，保证强度递减，各自代价不同。")
    cv.text(2, 4, "[集合]  第 20 章：只知道误差的界")
    cv.text(3, 12, "用最坏情况（worst-case）；保证对集合里每个元素都成立")
    cv.text(4, 12, "保守度最大；工具是小增益与 mu；适合单次、致命、不可重复的场景")
    cv.text(6, 4, "[分布]  第 21 章：知道分布的形状")
    cv.text(7, 12, "用期望（expectation）；保证以高概率成立")
    cv.text(8, 12, "保守度最小；工具是随机 HJB 与 Riccati；适合大量重复的场景")
    cv.text(10, 4, "[在线辨识]  第 22 章：两样都不知道")
    cv.text(11, 12, "边学边控（自适应）；保证需要激励才成立")
    cv.text(12, 12, "保守度取决于激励质量；工具是 MRAC 与 STR；适合参数慢漂移")
    cv.text(14, 2, "选型判据：先问「这个不确定性会不会被平均掉」，再决定用哪一列。")
    cv.text(15, 6, "会            ->  用期望（本章）")
    cv.text(16, 6, "不会          ->  用最坏情况（第 20 章）")
    cv.text(17, 6, "测不到但能学  ->  用自适应（第 22 章）")
    cv.text(18, 6, "两者都有      ->  分层组合：快变交给鲁棒，慢变交给自适应")
    return cv.render()


# ---------- ch21 block1：本章地图 ----------
def fig_ch21_map() -> list[str]:
    ROWS, COLS = 18, 76
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "本章地图：从「分布」这一列往深处走，每一步都在问「能不能递推」。")
    cv.text(2, 4, "21.1  代价结构置换        期望 / 风险度量 / 可递推性")
    cv.text(3, 8, "|")
    cv.text(4, 4, "21.2  LQG 与分离原理      交叉项为零 = 信息与代价可加")
    cv.text(5, 8, "|")
    cv.text(6, 4, "21.3  随机 HJB            多一个二阶项；风险敏感 = H-infinity")
    cv.text(7, 8, "|")
    cv.text(8, 4, "21.4  对偶效应            控制影响不确定性 -> 分离崩溃")
    cv.text(9, 8, "|")
    cv.text(10, 4, "21.5  滤波实现            稳定性 / 一致性 / NIS / 非线性近似")
    cv.text(11, 8, "|")
    cv.text(12, 4, "21.6  随机稳定性          均方 vs 几乎必然（临界点差 sigma^2）")
    cv.text(13, 8, "|")
    cv.text(14, 4, "21.7  跳变与丢包          Markov 跳变、耦合 Riccati、两个门槛")
    cv.text(15, 8, "|")
    cv.text(16, 4, "21.8  应用六条线          估计 / 随机 MPC / 金融 / 分布式 / RL")
    return cv.render()


# ---------- ch21 block2：对偶效应 ----------
def fig_dual_effect() -> list[str]:
    ROWS, COLS = 22, 76
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "对偶效应：控制同时做两件事，而这两件事的最优方向常常相反。")
    cv.text(2, 4, "作用一：驱动状态（直接影响当前代价的大小）")
    cv.text(3, 4, "作用二：改变信息结构（影响未来估计的精度与代价）")
    _frame(cv, 5, 4, 9, 36)
    cv.text(6, 6, "谨慎 caution")
    cv.text(7, 6, "因为不确定 -> 用力小")
    cv.text(8, 6, "怕把参数误差放大成失稳")
    _frame(cv, 5, 40, 9, 73)
    cv.text(6, 42, "探测 probing")
    cv.text(7, 42, "因为不确定 -> 用力大")
    cv.text(8, 42, "想把未知参数问出来")
    cv.text(11, 4, "谨慎的后果：当下代价低，但参数一直糊着（永远学不出来）")
    cv.text(12, 4, "探测的后果：未来辨识准，但当下代价高、甚至可能失稳")
    cv.text(14, 4, "线性高斯二次的奇迹：协方差递推不含 u -> 对偶效应为零 -> 分离成立")
    cv.text(16, 4, "出现对偶效应的四个入口（任何一个都会破坏分离）：")
    cv.text(17, 8, "控制影响量测 / 乘性噪声或随机参数 / 非线性（P 依赖轨迹）/ 约束")
    cv.text(19, 4, "工程结论：不是求最优，而是往信号里加一点激励（dither、丰富参考信号）")
    return cv.render()


# ---------- ch21 block3：三种稳定性 ----------
def fig_stability_three() -> list[str]:
    ROWS, COLS = 21, 76
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "三种稳定性不是一回事：对 dx = a x dt + sigma x dw，临界点差 sigma^2。")
    cv.text(2, 4, "几乎必然稳定（样本路径收敛）      要求  a < +sigma^2 / 2")
    cv.text(3, 4, "均方稳定（二阶矩收敛）            要求  a < -sigma^2 / 2")
    cv.text(4, 4, "依概率稳定（弱收敛）              由上面两者之一推出即可")
    cv.text(6, 4, "a < -sigma^2/2 : 均方稳定（显然样本路径也稳定）")
    cv.text(7, 4, "-sigma^2/2 < a < 0 : 样本路径稳定，二阶矩发散")
    cv.text(8, 4, "0 < a < +sigma^2/2 : 样本路径稳定，二阶矩发散，且确定性系统不稳定")
    cv.text(9, 4, "a > +sigma^2/2 : 连样本路径都不稳定")
    cv.text(11, 4, "中间地带为什么会出现：极小概率的巨大上冲把二阶矩拉走了（第 8 章大偏差）")
    cv.text(13, 4, "三者的逻辑关系（i.i.d. 乘性噪声下）：")
    cv.text(14, 8, "均方稳定          =>  几乎必然稳定      （Jensen：E log a <= 0.5 log E a^2）")
    cv.text(15, 8, "几乎必然稳定      =/=> 均方稳定          （反例：a 取 1.9 与 0.1 各半）")
    cv.text(16, 8, "两者 均 => 依概率稳定（Chebyshev / 依概率收敛）")
    cv.text(18, 4, "工程判据：性能指标都是二阶矩（RMS、方差），所以可用门槛由均方条件决定；")
    cv.text(19, 4, "          而「会不会长期跑飞」由几乎必然条件决定。两个都要算、分开写。")
    return cv.render()


# ---------- ch21 block4：丢包两个门槛 ----------
def fig_packet_loss() -> list[str]:
    ROWS, COLS = 20, 76
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "丢包率的两个门槛：均方门槛比几乎必然门槛严得多（本例差三倍以上）。")
    cv.text(2, 4, "模型：x(k+1) = (a - alpha_k b K) x(k)，a = 2，b = 1，K = 1.9")
    cv.text(3, 4, "      alpha_k = 1 的概率为 p（控制送达），为 0 的概率 1 - p（丢包）")
    cv.text(4, 4, "      成功时闭环增益 0.1，丢包时闭环增益 2.0（开环不稳定）")
    cv.text(6, 4, "均方稳定：p(0.01) + (1-p)(4) < 1   =>  p > 0.7519  =>  丢包率 < 24.8%")
    cv.text(7, 4, "几乎必然：p log0.1 + (1-p) log2 < 0  =>  p > 0.2314  =>  丢包率 < 76.9%")
    cv.text(9, 2, "0%           24.8%                         76.9%                100%")
    cv.text(10, 2, "|--------------|-----------------------------|--------------------|")
    cv.text(11, 2, "0%             24.8%                           76.9%               100%")
    cv.text(12, 4, "|<---- 两稳 ---->|<---- 路径稳、方差散 ---------->|<---- 都不稳 ----->|")
    cv.text(14, 4, "读数一：工程上性能指标几乎都是二阶矩（RMS、方差、能量），用 24.8%")
    cv.text(15, 4, "读数二：只关心「会不会长期跑飞」（安全裕度），用 76.9%")
    cv.text(16, 4, "读数三：最优临界值由 a 决定，近似 p_min = 1 - 1 / a^2（本例 0.75）")
    cv.text(18, 4, "一句话：系统越难控（a 越大），路径与矩的分裂就越严重。")
    return cv.render()


# ======================================================================
# 第 22 章：非线性与自适应控制
# ======================================================================

# ---------- ch22 block0：四种哲学 ----------
def fig_nonlinear_four() -> list[str]:
    ROWS, COLS = 21, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "四种处理非线性的哲学：不确定性没有被消除，只是被转移到了别处。")
    cv.text(2, 4, "1 局部线性化     依赖：工作点 + 线性设计")
    cv.text(3, 8, "动作：在工作点求 Jacobian，用线性控制器")
    cv.text(4, 8, "扔给：小范围（吸引域）        保证：局部有效")
    cv.text(5, 8, "代价：出了范围就失效，而且你无法预知范围到底多大")
    cv.text(7, 4, "2 反馈线性化     依赖：精确的结构与参数")
    cv.text(8, 8, "动作：坐标变换 + 反馈精确对消非线性项")
    cv.text(9, 8, "扔给：模型精度                保证：全局（若无内动态问题）")
    cv.text(10, 8, "代价：对消误差直接进系统；内动态可能不稳定且没人看管")
    cv.text(12, 4, "3 滑模           依赖：匹配条件 + 高频开关能力")
    cv.text(13, 8, "动作：把状态逼到一个低维面上，并对该面以上免疫")
    cv.text(14, 8, "扔给：高频开关                保证：有限时间 + 滑模上精确")
    cv.text(15, 8, "代价：抖振与执行器磨损；只在匹配条件下才完全有效")
    cv.text(17, 4, "4 自适应         依赖：线性参数化 + 持续激励")
    cv.text(18, 8, "动作：用在线数据估计未知参数，边学边控")
    cv.text(19, 8, "扔给：数据（需要激励）        保证：误差收敛（参数不一定收敛）")
    cv.text(20, 4, "（自适应的代价见 22.6：参数漂移、未建模动态、闭环激励消失）")
    return cv.render()


# ---------- ch22 block1：方法选择流程 ----------
def fig_choice_flow() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "方法选择流程：先问「不确定性是哪一类」，再问「哪种代价我付得起」。")
    cv.text(2, 4, "不确定性来自哪里？")
    cv.text(4, 8, "+-- 参数未知但结构已知（可线性参数化）")
    cv.text(5, 12, "+-- 有持续激励 ----------> 自适应（MRAC / STR）")
    cv.text(6, 12, "+-- 激励不可靠 ----------> 自适应 + 投影或 sigma 修正，或只用鲁棒")
    cv.text(8, 8, "+-- 结构强非线性（模型精确）")
    cv.text(9, 12, "+-- 相对阶 = 状态维数 ---> 反馈线性化（无内动态）")
    cv.text(10, 12, "+-- 相对阶 < 状态维数 ---> 先算零动态：稳定才可用，否则改反步法")
    cv.text(12, 8, "+-- 扰动有界且匹配 -------> 滑模（能承受高频开关时）或高阶滑模")
    cv.text(14, 8, "+-- 变化可测且慢变 -------> 增益调度 / LPV（有全范围证明）")
    cv.text(16, 8, "+-- 只有一个工作点 -------> 局部线性化（不要过度设计）")
    cv.text(18, 4, "补充：以上很少单独使用，工业上最常见是「分层组合」")
    cv.text(19, 4, "      反馈线性化（内环对消）+ 鲁棒或自适应（外环兜底）")
    cv.text(20, 4, "      增益调度（管已知大范围）+ 自适应（管未知慢漂移）")
    return cv.render()


# ---------- ch22 block2：坐标变换与零动态 ----------
def fig_zero_dynamics() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "反馈线性化把状态分成两块：xi（外部，被输出管）与 eta（内部，没人管）。")
    _frame(cv, 2, 6, 7, 33)
    cv.text(3, 8, "原坐标 x")
    cv.text(4, 8, "x' = f(x) + g(x) u")
    cv.text(5, 8, "y  = h(x)")
    cv.text(6, 8, "（非线性，耦合）")
    cv.text(4, 36, "== 坐标变换 ==>")
    _frame(cv, 2, 52, 7, 76)
    cv.text(3, 54, "新坐标 (xi, eta)")
    cv.text(4, 54, "xi: r 维积分链")
    cv.text(5, 54, "eta: n-r 维自由发展")
    cv.text(6, 54, "y = xi_1")
    cv.text(9, 4, "xi 链：xi_1' = xi_2, ..., xi_(r-1)' = xi_r, xi_r' = a + b u")
    cv.text(10, 4, "       用 u 对消 a 即可得到纯积分链（这就是「线性化」）")
    cv.text(12, 4, "零动态 = 令 xi = 0（输出及其前 r-1 阶导全为零）后 eta 的动力学")
    cv.text(13, 4, "         几何上：它是「零输出不变子流形 Z*」上的向量场")
    cv.text(15, 4, "两种命运（区别完全在内动态，与线性化本身无关）：")
    cv.text(16, 8, "零动态稳定（最小相位）  ->  eta 收敛，整体收敛（ISS 级联论证）")
    cv.text(17, 8, "零动态不稳定            ->  输出漂亮地跟踪，而 eta 沿发散流冲出去")
    cv.text(19, 4, "三行的反例：x1' = u，x2' = x1 + x2^2，y = x1")
    cv.text(20, 4, "            令 y -> 0 得 x2' = x2^2  ->  有限时间爆破（而输出一切正常）")
    return cv.render()


# ---------- ch22 block3：滑模两阶段 ----------
_fig_sliding_mode_MD = r'''  滑模控制的两个阶段：先有限时间到达，再在低维面上运动（n = 2 情形）。

    相平面（横轴 e，纵轴 e'；滑模面 s = e' + lambda e = 0 是一条直线）
         e'
        ^           \
        |             \                       s < 0 区域：到达阶段把 s 压到 0
        |               \                     到达时间 <= |s(0)| / eta'
        |                 \
        |                   \
        |                     \
        |                       \
        |                         \
        |                           \
        |                     滑模面 s = 0
        |                               \
        |               s > 0 区域        \
        |                                   \
    滑模段：系统活在 s = 0 上，阶数从 n 降到 n - 1
        |     动力学与「匹配」扰动无关（扰动被翻成等效控制的一部分）
        |                                         \
        +──────────────────────────────────────────────────────────────
                                                                  e
    边界层 phi：小则精度高（误差 ~ phi）但抖振强；大则平滑但只有最终界保证。
    高阶滑模（super-twisting）让 u 连续，同时保留有限时间收敛。'''


def fig_sliding_mode() -> list[str]:
    """2026-09-18 从 chapters/ch22.md block3 反向同步（md 为权威，原文手工修正过碰撞/行差，故整体返回 md 文本）。"""
    return _fig_sliding_mode_MD.split("\n")


# ---------- ch22 block4：自适应三大问题 ----------
def fig_adapt_issues() -> list[str]:
    ROWS, COLS = 23, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "自适应控制的三个致命问题与四味药（药方按性价比排序）。")
    cv.text(2, 4, "问题 1  参数漂移（纯积分自适应律的必然结果）")
    cv.text(3, 8, "症状：跟踪误差趋于零，参数却缓慢漂移（hat_theta ~ -(3 gamma d^2 t)^(1/3)）")
    cv.text(4, 8, "根因：自适应律是纯积分，只要 e 不严格为零，参数就一直在动")
    cv.text(5, 8, "药方：投影（最干净）> 死区 > sigma 修正 > e 修正")
    cv.text(7, 4, "问题 2  未建模高频动态（Rohrs 反例，1982）")
    cv.text(8, 8, "症状：按降阶模型设计后闭环发散，减小 gamma 只是延后发散")
    cv.text(9, 8, "根因：自适应回路的穿越频率撞上高频极点，相位裕度变成负的")
    cv.text(10, 8, "药方：归一化、前置低通、限制带宽（自适应带宽 <= 快极点频率 / 3）")
    cv.text(12, 4, "问题 3  闭环 PE 失效（控制得太好反而学不到）")
    cv.text(13, 8, "症状：控制得很好，参数却停在错误值；工况一变就失稳")
    cv.text(14, 8, "根因：控制消灭了激励，回归矩阵条件数恶化（控制得太好反而学不到）")
    cv.text(15, 8, "药方：丰富参考信号、加抖动、复合自适应（用历史数据换激励）")
    cv.text(17, 4, "共同底线（三条，换任何模型、任何算法都逃不掉）：")
    cv.text(18, 8, "参数必须有界      -> 投影（等价于权重裁剪、权重衰减）")
    cv.text(19, 8, "方向必须有激励    -> PE 条件（等价于探索充分性）")
    cv.text(20, 8, "带宽必须够低      -> gamma 小（等价于学习率不能太大）")
    cv.text(22, 4, "一句话：先保证有界，再保证带宽，最后才谈性能。")
    return cv.render()


# ======================================================================
# 第 23 章：几何控制
# ======================================================================

# ---------- ch23 block0：几何对象层级 ----------
def fig_geom_layers() -> list[str]:
    ROWS, COLS = 20, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "几何对象的层级：从「点」到「方向集合」，逐层加上结构。")
    cv.text(2, 4, "层 1   流形 M              局部像 R^n；例子：R^3、S^2、SO(3)")
    cv.text(3, 4, "层 2   切空间 T_x M        在点 x 处所有可能的运动方向（n 维线性空间）")
    cv.text(4, 4, "层 3   向量场 f(x)         每点指派一个切向量；动力学 x' = f(x)")
    cv.text(5, 4, "层 4   Lie 括号 [f, g]     两条路径不交换的净位移（仍是一个向量场）")
    cv.text(6, 4, "层 5   分布 Delta(x)       每点指派一个子空间 span{f_1, ..., f_k}")
    cv.text(7, 4, "层 6   对合性             [f_i, f_j] 仍在 Delta 内（括号不产生新方向）")
    cv.text(9, 4, "枢纽：Frobenius 定理（本章唯一的存在性定理）")
    cv.text(10, 8, "Delta 对合  <=>  Delta 可积  <=>  存在坐标使 Delta = span{d/dz_1,...,d/dz_k}")
    cv.text(11, 8, "翻译：对合 = 「这些方向能整齐地排成一层层曲面」，于是可以拆块")
    cv.text(13, 4, "这个判据决定了一件事：能不能把系统干净地拆成「外部（可控）+ 内部（不可控）」")
    cv.text(15, 4, "三个具体收获（几何方法到底换来了什么）：")
    cv.text(16, 8, "判据的坐标无关性（不依赖你选了哪组坐标）")
    cv.text(17, 8, "存在性定理（什么时候「一定」能做、什么时候「一定」不能做）")
    cv.text(18, 8, "处理本质上是流形的状态空间（SO(3)、SE(3)）")
    return cv.render()


# ---------- ch23 block1：零动态子流形 ----------
def fig_zero_manifold() -> list[str]:
    ROWS, COLS = 21, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "零动态的几何面貌：它不是凭空写的，而是子流形上的一个向量场。")
    _frame(cv, 2, 6, 11, 72)
    _frame(cv, 3, 10, 8, 68)
    cv.text(4, 14, "零输出不变子流形 Z*（n-r 维）")
    cv.text(5, 14, "h = L_f h = ... = L_f^(r-1) h = 0")
    cv.text(6, 14, "轨迹被约束在这里，其上的动力学就是零动态")
    cv.text(9, 12, "输出回路把状态拽回 Z* 附近；进入后沿 Z* 上的流演化")
    cv.text(13, 4, "三句话（几何解释、稳定性、以及后果）：")
    cv.text(14, 8, "零动态     = 限制在 Z* 上的动力学（一个向量场）")
    cv.text(15, 8, "最小相位   = Z* 上的流渐近稳定（局部指数收敛）")
    cv.text(16, 8, "非最小相位 = Z* 上有发散流，而输出对这个方向完全免疫")
    cv.text(18, 4, "与线性系统的对应：零动态的线性化就是传递函数的零点")
    cv.text(19, 4, "右半平面零点 <=> 非最小相位 <=> 内蕴性质，换任何坐标都消不掉")
    return cv.render()


# ---------- ch23 block2：非完整性与 Lie 括号 ----------
def fig_nonholonomic() -> list[str]:
    ROWS, COLS = 22, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "非完整性：能控，但不能用光滑反馈点镇定 —— 平行泊车就是它。")
    cv.text(2, 4, "车辆运动学：状态 (x, y, theta)，控制 (v, phi)")
    cv.text(3, 8, "x' = v cos(theta)，y' = v sin(theta)，theta' = (v / L) tan(phi)")
    cv.text(5, 4, "g_1 = (cos th, sin th, 0)         推「前进」方向")
    cv.text(6, 4, "g_2 = (0, 0, 1)                   推「转向率 omega = theta'」方向")
    cv.text(7, 4, "[g_1, g_2] = (sin th, -cos th, 0) 侧向：不能直接推，只能靠交替动作做到")
    cv.text(9, 4, "三个向量线性无关  ->  Lie 代数张满 R^3  ->  小时间局部能控（Chow 定理）")
    cv.text(10, 4, "但 span{g_1, g_2} 不对合（括号跑出去了）  ->  非完整系统")
    cv.text(12, 4, "于是两条结论（能控性来自括号，而镇定受拓扑限制）：")
    cv.text(13, 8, "能控        : 是（缺的方向由 Lie 括号补上）")
    cv.text(14, 8, "光滑点镇定  : 不能（Brockett 必要条件：像集不含原点的邻域）")
    cv.text(16, 4, "三条出路（按工程可维护性从低到高排序）：")
    cv.text(17, 8, "1  时变控制（控制器里加振荡项）      收敛慢，但光滑")
    cv.text(18, 8, "2  分段 / 不连续控制（状态机）       有切换，需处理抖振与死区")
    cv.text(19, 8, "3  做路径跟踪而不是点镇定            工程上最常用（跟踪是可光滑镇定的）")
    cv.text(21, 4, "一句话：能不能动看 Lie 代数秩条件，能不能光滑停住看 Brockett。")
    return cv.render()


# ---------- ch23 block3：指数映射 ----------
def fig_exp_map() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "SO(3) 与 Lie 代数：指数映射把「角速度」积分成「旋转」。")
    _frame(cv, 2, 4, 7, 34)
    cv.text(3, 6, "Lie 代数 so(3)")
    cv.text(4, 6, "反对称矩阵（3 维）")
    cv.text(5, 6, "hat(w) x = w 叉乘 x")
    cv.text(6, 6, "hat(w) = [[0,-w3,w2],...]")
    cv.text(4, 37, "--- exp --->")
    _frame(cv, 2, 50, 7, 76)
    cv.text(3, 52, "Lie 群 SO(3)")
    cv.text(4, 52, "旋转矩阵（3 维紧流形）")
    cv.text(5, 52, "R^T R = I，det R = 1")
    cv.text(6, 52, "exp 是多对一（非单射）")
    cv.text(9, 4, "Rodrigues 公式（单位轴 w，转角 theta，最常用的姿态操作）：")
    cv.text(10, 8, "exp(theta hat(w)) = I + sin(theta) hat(w) + (1 - cos(theta)) hat(w)^2")
    cv.text(12, 4, "两条用途相反的通道（exp 与 log 方向恰好相反）：")
    cv.text(13, 8, "exp : 轴角 -> 旋转矩阵（姿态更新、积分）")
    cv.text(14, 8, "log : 旋转矩阵 -> 轴角（误差提取、微扰线性化，EKF 的基础）")
    cv.text(16, 4, "两个坐标系必须分清（混用是最常见的 bug）：")
    cv.text(17, 8, "R' = R hat(w_b)   体坐标（左不变；惯量矩阵常值；用于动力学）")
    cv.text(18, 8, "R' = hat(w_s) R   空间坐标（右不变；用于误差定义与滤波）")
    cv.text(20, 4, "拓扑必然（三个、四个、九个参数不可兼得）：")
    cv.text(21, 8, "3 个参数（欧拉角）   -> 必然有万向节锁")
    cv.text(22, 8, "4 个参数（四元数）   -> 必然有双覆盖（q 与 -q 表示同一姿态）")
    cv.text(23, 4, "9 个参数（旋转矩阵） -> 无奇异无歧义，但有冗余，需要正交化")
    return cv.render()


# ---------- ch23 block4：端口 Hamilton 与能量整形 ----------
def fig_phs_shaping() -> list[str]:
    ROWS, COLS = 24, 78
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "端口 Hamilton 系统：把无源性从「判据」变成「设计工具」。")
    cv.text(2, 4, "x' = [ J(x) - R(x) ] grad H(x) + G(x) u")
    cv.text(3, 4, "y  = G(x)^T grad H(x)")
    cv.text(5, 6, "H   总能量（动能 + 势能）")
    cv.text(6, 6, "J   互连矩阵：反对称，只搬运能量，不产生也不消耗")
    cv.text(7, 6, "R   耗散矩阵：对称半正定（阻尼、电阻）")
    cv.text(9, 4, "功率平衡（一行推出无源性）：")
    cv.text(10, 8, "dH/dt = grad H^T J grad H - grad H^T R grad H + y^T u")
    cv.text(11, 8, "        = 0（反对称项）    <= 0（耗散项）")
    cv.text(12, 8, "=  dH/dt <= y^T u      这就是无源性不等式（H 是储存函数）")
    cv.text(14, 4, "能量整形：不控制状态，而是搬走「最低能量点」")
    cv.text(15, 8, "找反馈 u 与附加能量 H_a，使 H_d = H + H_a 在目标点有严格极小")
    cv.text(17, 4, "例：机器人「PD + 重力补偿」（用了三十年的经验做法）")
    cv.text(18, 8, "u = -K_p (q - q_d) - K_d q' + g(q)")
    cv.text(19, 8, "势能变成 V_new = V(q) - V(q_d) + 0.5 (q - q_d)^T K_p (q - q_d)")
    cv.text(20, 8, "于是 H_d 在 (q_d, 0) 处有严格极小，加阻尼后单调下降")
    cv.text(22, 4, "一句话：K_p 不是一个「增益」，而是给目标位形加了一根弹簧。")
    cv.text(23, 4, "推广（IDAPBC）：J 与 R 也可一起整形，代价是要解一组匹配方程。")
    return cv.render()



# ---------- ch24 block0：学习控制的位置与地图 ----------
def fig_rl_landscape() -> list[str]:
    ROWS, COLS = 24, 80
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "学习控制的位置：三层信息假设，一条不确定性递减链。")
    cv.text(2, 4, "层次 1  模型完全已知   f, g, Q, R 都写得出来      ->  PMT / HJB / MPC / LQR")
    cv.text(3, 4, "层次 2  结构已知、参数未知   A(theta), B(theta)     ->  系统辨识 / 自适应控制")
    cv.text(4, 4, "层次 3  只有交互样本   (s, a, r, s') 序列          ->  强化学习（本章）")
    cv.text(6, 4, "不确定性一共搬了三次家，每搬一次都要重新买三样东西：")
    cv.text(7, 8, "收敛性    靠 Bellman 算子的压缩性（24.2 的一行不等式）")
    cv.text(8, 8, "稳定性    靠 Lyapunov 函数与安全集的可微约束（24.6）")
    cv.text(9, 8, "数据      靠主动探索；这一步在前二十三章根本不存在（24.5）")
    cv.text(11, 4, "本章六节：各自拿掉一个假设，各自接回前面某一章。")
    cv.text(12, 6, "24.2  算子视角   已知模型，把「解方程」换成「求不动点」   接 19.8.4 的值迭代")
    cv.text(13, 6, "24.3  时序差分   拿掉转移概率 P，只用样本                接 22.6 的自适应三大问题")
    cv.text(14, 6, "24.4  策略优化   拿掉值函数的显式表示                    接 11.3.3 的 Fisher 信息几何")
    cv.text(15, 6, "24.5  探索遗憾   拿掉「数据是白给的」                    接 21.4 的对偶效应")
    cv.text(16, 6, "24.6  稳定安全   把「逐路径、逐时刻」的保证买回来        接 18.2 的 Lyapunov 理论")
    cv.text(17, 6, "24.7  逆向最优   拿掉「奖励是给定的」                      接 19.8.5 的逆向最优控制")
    cv.text(19, 4, "四个真难点（判断一个 RL 结果可信不可信，就问这四条）：")
    cv.text(20, 8, "样本复杂度（24.2.6、24.5.5）   探索（24.5）")
    cv.text(21, 8, "稳定性（24.3.3、24.6）         分布偏移（24.6.4、24.8）")
    cv.text(23, 4, "一句话：RL 不是「另一种控制」，而是把控制器与辨识器同时交给一个梯度回路。")
    return cv.render()


# ---------- ch24 block1：Bellman 算子的压缩性与两个视角 ----------
def fig_bellman_operator() -> list[str]:
    ROWS, COLS = 26, 80
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Bellman 算子：一行不等式推出动态规划的全部收敛性。")
    cv.text(2, 4, "T 的定义     (T V)(s) = max_a { r(s,a) + gamma * sum_s' P(s'|s,a) V(s') }")
    cv.text(3, 4, "压缩性       || T V - T U ||_inf  <=  gamma * || V - U ||_inf")
    cv.text(4, 4, "来源只有一条  max 与 min 都是 1-Lipschitz 的（无扩张），配上 gamma < 1")
    cv.text(6, 4, "压缩性这一个不等式，就给出下面三件事，不需要分别证明：")
    cv.text(7, 8, "1  不动点唯一            Banach 不动点定理")
    cv.text(8, 8, "2  值迭代几何收敛        速率恰好是 gamma")
    cv.text(9, 8, "3  迭代次数与状态数无关   k >= log(...) / log(1/gamma)，里头没有 |S|")
    cv.text(11, 4, "维度诅咒藏在哪里（最常见的误解在这里被纠正）：")
    cv.text(12, 8, "迭代次数    ~ (1/(1-gamma)) * log(1/eps)     与 |S| 无关")
    cv.text(13, 8, "每步代价    ~ |S|^2 * |A|                     指数爆炸在这一项")
    cv.text(14, 8, "于是「用采样代替求和」直接命中要害：它省的是每步代价，不是迭代次数")
    cv.text(16, 4, "两条路线的性格对比（同一条压缩性，两种代价结构）：")
    cv.text(17, 8, "值迭代    每步便宜（一次回代）      步数多      类比：梯度下降")
    cv.text(18, 8, "策略迭代  每步昂贵（解线性系统）    步数少      类比：牛顿法")
    cv.text(19, 8, "折中      截断策略迭代：评估只做 m 次回代；m = 1 退化成值迭代")
    cv.text(21, 4, "误差放大：值函数差 eps，策略损失差 2*gamma*eps/(1-gamma)")
    cv.text(22, 8, "gamma = 0.99 时放大因子约 198：想把策略差压到 1%，值函数要准到 0.05%")
    cv.text(24, 4, "第三个视角（LP 对偶，通向第 25 章）：对偶变量是占用测度 d(s,a)，")
    cv.text(25, 4, "目标对 d 线性而可行集非凸；确定性策略 = 多面体顶点，策略迭代 ~ 单纯形法。")
    return cv.render()


# ---------- ch24 block2：TD 的三方对照与致命三角 ----------
def fig_td_anatomy() -> list[str]:
    ROWS, COLS = 26, 80
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "时序差分：DP 的采样版，也是 MC 的自举版 —— 三方对照。")
    cv.text(2, 4, "方法   目标                      要模型   要完整轨迹   偏置   方差")
    cv.text(3, 4, "DP     r + gamma * sum_s' P V     要       不要         无     零")
    cv.text(4, 4, "MC     G_t = sum gamma^k r        不要     要（到终止）  无     大")
    cv.text(5, 4, "TD     r + gamma * V(s')          不要     不要（在线）  有     小")
    cv.text(7, 4, "TD 误差 delta = r + gamma V(s') - V(s)：Bellman 残差的采样观测。")
    cv.text(8, 8, "在 V = V_pi 时 E[delta | F_t] = 0，它就是「预期与实际之差」")
    cv.text(9, 8, "与 18.2 的 Lyapunov 差分 V(s') - V(s) 长得几乎一样")
    cv.text(10, 8, "差别：TD 只压误差、不管参数 -> 参数可以漂移（22.6.1 的老病）")
    cv.text(12, 4, "致命三角：逼近 + 自举 + 离策略，三者同时可以发散（两两组合都安全）。")
    cv.text(13, 8, "逼近 + 自举      半梯度 TD、DQN          在策略下安全")
    cv.text(14, 8, "逼近 + 离策略    LSTD、最小二乘 MC       目标无偏，安全")
    cv.text(15, 8, "自举 + 离策略    表格 Q-learning         表格下投影是恒等，安全")
    cv.text(17, 4, "根因（一句话）：Bellman 是 ||.||_inf 下的 gamma-压缩，而投影是")
    cv.text(18, 8, "||.||_2 下的非扩张、在 ||.||_inf 下可放大 sqrt(|S|) 倍 —— 两个")
    cv.text(19, 8, "「各自的收缩」不在同一个范数里，乘积的范数就可以大于 1。")
    cv.text(20, 8, "与 22.6.2 的 Rohrs 现象同构：每块都对，整体发散。")
    cv.text(22, 4, "四味药（与 22.6.4 的自适应四味药逐条一一对应）：")
    cv.text(23, 8, "目标网络      给「追自己」的回路加一个慢时间尺度    ~ sigma 修正 / 漏泄")
    cv.text(24, 8, "在策略化      限制新旧策略的距离（TRPO / PPO）      ~ 归一化 / 小增益")
    cv.text(25, 8, "裁剪与归一化  给参数、更新、数值范围加上界          ~ 投影 / 归一化")
    return cv.render()


# ---------- ch24 block3：策略优化的景观 ----------
_fig_pg_landscape_MD = r'''  策略优化：关键不是梯度方向，而是「这一步走多远」。

    梯度方向的来源（对数导数技巧，四行推完）：
        grad J = E[ grad log pi(a|s) * G_t ]      这就是 REINFORCE
        轨迹概率的对数里，模型项 log P(s'|s,a) 与 theta 无关 -> 导数消失
        这一步就是「无模型」的全部合法性来源：不需要 P 的导数

    方差约减：减去与动作无关的基线 b(s)，期望不变
        E[grad log pi * b(s)] = b(s) * grad sum_a pi = 0
        取 b = V_pi 最优（因为 A = Q - V 关于动作的条件均值为零）
        GAE(lambda) = sum (gamma*lambda)^l * delta_{t+l}，就是优势上的 TD(lambda)

    为什么必须限制步长（性能差引理与它的分布错配）：
        eta(pi') - eta(pi) = 1/(1-gamma) * E_{s ~ d^pi'}[ A^pi ]
        右端是新策略自己的分布 d^pi'，不可知；换成旧分布的误差 ~ (1-gamma)^-2
        gamma = 0.99 时惩罚系数 (1-gamma)^-2 约 10000，比收益项系数 1/(1-gamma) = 100
        还大两个数量级 —— 步子大一点、惩罚就大两个数量级

    两种步长控制（都取自上面那条引理）：TRPO 与 PPO
        TRPO  在 KL 球上解约束，d_theta = sqrt(2*delta/(g^T F g)) * F^-1 grad J
              严格有理论；代价是逆 Fisher（工程上用共轭梯度近似）
        PPO   把重要性比率裁剪到 [1-eps, 1+eps]，越界即把梯度关掉
              单侧刹车、无保证，但工程上极其稳健（与 22.6.1 的 sigma 修正同族）

    两种度量：欧氏梯度（换参数就变）vs 自然梯度 F^-1 grad（对参数化不变）
        F 就是 11.3.3 的 Fisher 信息矩阵；F^-1 是策略空间里的「归一化」

    LQR 这个特例（控制视角的礼物）：所有驻点都是全局最优，
    且 ||grad J||^2 >= mu*(J - J*) -> 策略梯度线性收敛到全局最优。'''


def fig_pg_landscape() -> list[str]:
    """2026-09-18 从 chapters/ch24.md block3 反向同步（md 为权威，原文手工修正过碰撞/行差，故整体返回 md 文本）。"""
    return _fig_pg_landscape_MD.split("\n")


# ---------- ch24 block4：探索与安全 ----------
def fig_explore_safe() -> list[str]:
    ROWS, COLS = 28, 80
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "探索与安全：一个在最坏情况上取上界去进攻，一个取上界去防御。")
    cv.text(2, 4, "bandit 的遗憾与它的下界（对数遗憾才是最优的）：")
    cv.text(3, 8, "Reg(T) = T*mu* - E[sum r] = sum_a Delta_a * E[n_a(T)]")
    cv.text(4, 8, "结构读法：遗憾 = 间隙 * 被选次数（不是「多久找到最优臂」）")
    cv.text(5, 8, "Lai-Robbins：Reg >= sum_a Delta_a / KL(nu_a || nu*) * log T")
    cv.text(6, 8, "信息量在分母，与 10.2.3 的 Cramer-Rao 同源：可分性决定代价")
    cv.text(8, 4, "两条主流路线（都靠「不确定性」提供探索动力）：")
    cv.text(9, 8, "UCB       取置信上界 argmax{ mu_hat + sqrt(2 log t / n_a) }")
    cv.text(10, 8, "          没试过的臂自动获得大 bonus，探索是贪心的副产品")
    cv.text(11, 8, "Thompson  从后验采一个参数，再对它取贪心 ——「后验就是策略」")
    cv.text(13, 4, "同一个「上界」，两个方向（这一对照最值得记住）：")
    cv.text(14, 8, "鲁棒控制   sup_Delta 取最坏   ->  防御（性能保证，20.3）")
    cv.text(15, 8, "UCB        sup_theta 取最好   ->  进攻（把注意力引向未知，24.5.3）")
    cv.text(16, 8, "一个系统里最危险的东西，在另一个系统里是最有价值的东西。")
    cv.text(18, 4, "探索充分性 = PE 条件：数据协方差的最小特征值不能太小。")
    cv.text(19, 8, "自适应控制叫 PE，RL 叫覆盖，深度学习叫特征不塌缩 —— 一个条件。")
    cv.text(21, 4, "安全的三层强度（对应 21.3.5 的「机会约束不能递推」）：")
    cv.text(22, 8, "期望约束     拉格朗日乘子    平均违规不超预算，可被零违规平均掉")
    cv.text(23, 8, "信任域约束   CPO             每一步的约束增量有界 -> 可以递推")
    cv.text(24, 8, "逐时刻约束   CBF + QP 投影   每一时刻都成立，与概率无关（要模型）")
    cv.text(26, 4, "最常用的工程架构是两层：RL 建议、QP 把关 ——")
    cv.text(27, 4, "与 16.7 的抗饱和同一种哲学：上层给想要的，下层负责做得到的。")
    return cv.render()



# ---------- ch25 block0：凸性的三层来源与它失去什么 ----------
def fig_convex_geometry() -> list[str]:
    ROWS, COLS = 27, 88
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "凸性：一句话、三层来源、以及非凸会失去什么。")
    cv.text(2, 4, "几何层   凸集 = 线段封闭        ->  外面的点能被超平面切开（分离定理）")
    cv.text(3, 4, "分析层   凸函数 = 弦在图上      ->  切线是全局下界（一阶判据）")
    cv.text(4, 4, "代数层   二阶判据 Hessian >= 0  ->  只用来「计算」，不用来「证明」")
    cv.text(6, 4, "一阶判据（全章全部内容的来源）：")
    cv.text(7, 8, "f(y) >= f(x) + grad f(x)^T (y - x)   切线永远在函数下方")
    cv.text(9, 4, "三个推论，一次给出：")
    cv.text(10, 8, "推论 1   grad f(x*) = 0  ==>  x* 是全局最小点（不需要附加条件）")
    cv.text(11, 8, "推论 2   ||grad f|| 小  ==>  真的接近最优（停机准则才有意义）")
    cv.text(12, 8, "推论 3   没有坏的局部极小（这一条在非凸时全部失效）")
    cv.text(14, 4, "非凸会失去什么（第 26 章的清单，先记在这里）：")
    cv.text(15, 8, "鞍点       梯度为零但曲率有正有负，既不是极小也不是极大")
    cv.text(16, 8, "坏局部极小 梯度为零且是极小，但目标值远高于全局最优")
    cv.text(17, 8, "平台悬崖   梯度极小或极大，步长失效，结果与初始化强相关")
    cv.text(18, 8, "尺度依赖   收敛速率依赖坐标系（条件数 kappa = L / mu）")
    cv.text(20, 4, "同一句「局部到全局」在本书别处的化身：")
    cv.text(21, 8, "Lyapunov   局部能量下降 ==> 全局稳定（18 章，需要正定性）")
    cv.text(22, 8, "自适应     局部 PE 条件 ==> 参数收敛（22 章，需要持续激励）")
    cv.text(23, 8, "强化学习   占有测度凸 而 策略参数非凸（24 章，同一个二分）")
    cv.text(24, 8, "泛化理论   均匀收敛 ==> 一致泛化界（28 章，同一套推理）")
    return cv.render()


# ---------- ch25 block1：共轭函数的六张脸 ----------
def fig_conjugate_web() -> list[str]:
    ROWS, COLS = 34, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "共轭 f*(y) = sup_x { y^T x - f(x) }：把任何函数变成凸函数的机器。")
    cv.text(2, 4, "永远凸         因为它是「一族仿射函数的上确界」，与 f 是否凸无关")
    cv.text(3, 4, "Fenchel-Moreau f** = f  <=>  f 闭凸    （所以这是可逆变换）")
    cv.text(4, 4, "可微时的样子   y = grad f(x) 且 x = grad f*(y)，两边 Hessian 互逆")
    cv.text(6, 2, "它的六张脸（同一个定义，六个学科各起一个名字）：")
    cv.text(7, 4, "信息论 / 统计   Legendre 变换：对数矩母函数 A  与  率函数 I = A*")
    cv.text(8, 4, "大偏差（8 章）  Cramer 定理「A 凸、A* = I」就是 Fenchel-Moreau")
    cv.text(9, 4, "最优控制（19 章）Hamilton 函数 H(x,u,p) = p^T f - L「就是 L 的共轭」")
    cv.text(10, 4, "凸分析（本章）  支撑函数 = 示性函数的共轭")
    cv.text(11, 20, "sigma_C(y) = sup_{x in C} y^T x")
    cv.text(12, 4, "统计物理        内能 U(S) 与 Helmholtz 自由能 F(T)：温度与熵互为共轭")
    cv.text(13, 4, "信息几何（11 章）自然参数 theta 与期望参数 mu：对数配分函数与负熵互为共轭")
    cv.text(15, 2, "必须背下的共轭对偶表（它就是共轭运算的乘法表）：")
    cv.text(16, 4, "(1/2)||x||^2      <->  (1/2)||y||^2          自共轭")
    cv.text(17, 4, "(1/2) x^T A x     <->  (1/2) y^T A^{-1} y    二次型的对偶仍是二次型")
    cv.text(18, 4, "||x||_p           <->  ||y||_q <= 1，1/p + 1/q = 1（对偶范数球）")
    cv.text(19, 4, "核范数 ||X||_*    <->  谱范数球 ||Y||_2 <= 1（秩的凸包）")
    cv.text(20, 4, "sum_i exp(x_i)    <->  负熵 sum_i y_i log y_i - y_i")
    cv.text(21, 4, "示性函数 I_C      <->  支撑函数 sigma_C（集合的支撑超平面）")
    cv.text(23, 2, "两条立刻可用的推论（它们在后文反复出现，值得单独记住）：")
    cv.text(24, 4, "Fenchel 不等式：f(x) + f*(y) >= x^T y，取等 <=> y 属于 subgrad f(x)")
    cv.text(25, 4, "把 exp 那一行代进去、整理，得到的正是 Gibbs 不等式 KL(q||p) >= 0")
    cv.text(27, 2, "Moreau 分解（prox 的全部直觉）：x = prox_f(x) + prox_{f*}(x)")
    cv.text(28, 4, "f = 示性函数 I_C   ->  prox 就是投影       （第 6 章投影定理）")
    cv.text(29, 4, "f = lambda ||.||_1 ->  prox 就是软阈值     （15.4.2 LASSO）")
    cv.text(30, 4, "f = lambda ||.||_* ->  prox 就是奇异值软阈值（15.5 矩阵情形）")
    cv.text(31, 4, "投影是 prox 的特例；软阈值也是；这条路通向 25.5.3 的加速。")
    return cv.render()


# ---------- ch25 block2：对偶的图景 ----------
def fig_duality_picture() -> list[str]:
    ROWS, COLS = 47, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "对偶：把「约束」翻译成「价格」，于是 min-max 与 max-min 可以交换。")
    cv.text(2, 4, "原始问题   min f0(x)   s.t.  fi(x) <= 0,  hj(x) = 0")
    cv.text(3, 4, "Lagrange   L(x, lam, nu) = f0(x) + sum_i lam_i fi(x) + sum_j nu_j hj(x)")
    cv.text(4, 4, "对偶函数   g(lam, nu) = inf_x L    —— 永远是凹函数（一族仿射函数的下确界）")
    cv.text(5, 4, "弱对偶     d* = sup g  <=  p*      —— 一行可证，不需要任何凸性")
    cv.text(7, 2, "弱对偶为什么「一行就能证」（这一行是本节的骨架）：")
    cv.text(8, 4, "对任意可行 x 与 lam >= 0，两项惩罚都 <= 0，于是 L(x,lam,nu) <= f0(x)")
    cv.text(9, 4, "先对 x 取 inf、再对 (lam,nu) 取 sup：d* <= p*。完。")
    cv.text(11, 2, "几何（在值空间里看：对偶就是找支撑超平面）：")
    cv.text(12, 4, "把 (u,t) = (f1(x), f0(x)) 全体画成集合 G，则")
    cv.text(13, 6, "p* = 集合 G 中满足 u <= 0 的那部分的最低高度")
    cv.text(14, 6, "g(lam) = 用斜率 -lam 的直线从下方托 G 能托到的最高截距")
    cv.text(15, 4, "G 凸  ->  直线能贴住它，托到的就是 p*：强对偶")
    cv.text(16, 4, "G 非凸 ->  直线只能贴到 conv(G)，中间的凹陷高度就是「对偶间隙」")
    cv.text(18, 4, "结论（本章最该带走的那句诊断学，请记住）：")
    cv.text(19, 6, "间隙不是数值误差，它是「原问题非凸程度」的度量，不会随迭代变小")
    cv.text(20, 6, "离散 / 整数变量是最常见的间隙来源（凸化必然要填坑）")
    cv.text(22, 2, "强对偶的三个条件（三选一，工程上最常见的是 Slater）：")
    cv.text(23, 4, "凸问题 + 存在严格可行点（fi(x) < 0 而 hj(x) = 0） ->  d* = p* 且乘子存在")
    cv.text(24, 4, "鞍点判据：若 (x*,lam*,nu*) 使 L 对 x 取最小、对乘子取最大，则 d* = p*")
    cv.text(25, 4, "反过来：没有内点时，d* = p* 可能成立，但乘子可能不存在或为无穷")
    cv.text(27, 2, "KKT 的四个条件，以及它的一句话读法（务必记住）：")
    cv.text(28, 4, "(1) 平稳性        grad f0 + sum lam_i grad fi + sum nu_j grad hj = 0")
    cv.text(29, 4, "(2) 原始可行      fi(x) <= 0,  hj(x) = 0")
    cv.text(30, 4, "(3) 对偶可行      lam_i >= 0（这是唯一的符号条件）")
    cv.text(31, 4, "(4) 互补松弛      lam_i * fi(x) = 0")
    cv.text(32, 4, "读法：不紧的约束价格为 0；价格为正的约束一定紧（免费物品没有价格）")
    cv.text(34, 2, "影子价格（对偶变量的三重身份，最实用的一段）：")
    cv.text(35, 4, "lam_i* = - d p*(u) / d u_i     （非负，符号约定要对齐）")
    cv.text(36, 6, "价格      多给一单位资源，目标改善多少")
    cv.text(37, 6, "敏感度    约束松紧一单位，最优值动多少（问「公差再紧要付多少」）")
    cv.text(38, 6, "权重      哪条约束最咬人，是该优先放松的对象")
    cv.text(39, 4, "同一句话：对偶变量 = 约束的价格 = 松弛的代价 = 目标的敏感度")
    cv.text(41, 2, "对偶的八张脸（同一个对象的八个名字，认出来就通了）：")
    cv.text(42, 4, "凸优化   对偶变量 = 影子价格        线性规划   对偶变量 = 资源的边际价值")
    cv.text(43, 4, "大偏差   率函数 = 矩母函数的共轭   统计物理   温度与熵互为共轭变量")
    cv.text(44, 4, "最优控制 协态 p = 状态的影子价格  强化学习   占用测度 = 长期时间份额")
    cv.text(45, 4, "最优传输 对偶变量 = 势函数        信息论     自然参数与期望参数互为共轭")
    return cv.render()


# ---------- ch25 block3：锥规划阶梯 ----------
def fig_cone_ladder() -> list[str]:
    ROWS, COLS = 43, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "锥规划：一个语法，吃掉大半个工程——LP 到 SOCP 到 SDP 的阶梯。")
    cv.text(2, 4, "层次        约束的锥            约束的样子                复杂度")
    cv.text(3, 4, "LP          非负象限 Rn+        x >= 0                    多项式")
    cv.text(4, 4, "SOCP        二阶锥 Qn           ||Ax+b||_2 <= c^T x + d   多项式")
    cv.text(5, 4, "SDP         半正定锥 Sn+        sum y_i A_i <= B（LMI）   多项式")
    cv.text(7, 4, "包含关系（指的是「能表达的问题类」，注意方向）：")
    cv.text(8, 6, "LP 真包含于 SOCP 真包含于 SDP（作为能表达的问题类）")
    cv.text(9, 4, "LP 表达不了 SOCP：||x||_2 <= t 的边界是曲面，多面体的边界是平的")
    cv.text(10, 4, "SOCP 表达不了 SDP：2x2 的 det >= 0 是二阶锥，3x3 及以上就不是")
    cv.text(12, 4, "判一条约束属于哪一层，只问一句话（很灵的判据）：")
    cv.text(13, 6, "约束里的「平方」含不含变量之间的乘积？这就是全部判据。")
    cv.text(14, 8, "不含（x^T Q x，Q 给定）  ->  SOCP 能解")
    cv.text(15, 8, "含（x y，X Y）            ->  非凸，需要松弛（第 26 章）")
    cv.text(17, 4, "弱对偶在锥上「一字不改」（这是锥这个语言的全部价值）：")
    cv.text(18, 6, "min <c,x> s.t. Ax = b, x >=_K 0      max <b,y> s.t. A^T y + s = c, s >=_K* 0")
    cv.text(19, 6, "证明：<c,x> = <A^T y + s, x> = <b,y> + <s,x> >= <b,y>")
    cv.text(20, 6, "从 LP 到 SDP 只有两处改动：内积换成迹内积，x >= 0 换成 x 属于 K")
    cv.text(22, 4, "三个自对偶锥（所以原始与对偶形状对称，内点法能同时走两条路）：")
    cv.text(23, 6, "非负象限 Rn+、二阶锥 Qn、半正定锥 Sn+   全部满足 K* = K")
    cv.text(25, 4, "建模语法速查（见到什么就写什么，这才是真手艺）：")
    cv.text(26, 6, "线性不等式 a^T x <= b                    LP")
    cv.text(27, 6, "最小化 ||Ax - b||_2                      SOCP（min t s.t. ||Ax-b|| <= t）")
    cv.text(28, 6, "数据不确定 ||A - Ahat|| <= rho           SOCP（||Ahat x-b|| + rho||x|| <= t）")
    cv.text(29, 6, "分式目标（分母正）                       透视函数 -> SOCP / LP")
    cv.text(30, 6, "lambda_max(A(x)) <= 0，即 A(x) <= 0      SDP（LMI）")
    cv.text(31, 6, "双线性：A^T P + P A 中的变量乘积          非凸（除非能变量替换救回来）")
    cv.text(33, 4, "S-procedure（S-lemma）：为什么它能给 LMI")
    cv.text(34, 6, "x^T A1 x <= 0   ==>   x^T A0 x <= 0     （二次型蕴含）")
    cv.text(35, 6, "充分条件：存在 tau >= 0 使 A0 - tau A1 <= 0")
    cv.text(36, 6, "证明一行：A0 = (A0 - tau A1) + tau A1，两项都 <= 0")
    cv.text(37, 6, "但反向一般不成立（n=2 时成立，n>=3 失效）")
    cv.text(38, 6, "—— 凸充分条件必然保守：这就是 mu 分析与 LMI 综合里保守性的根源")
    cv.text(40, 4, "三条路都通向同一个结论（第 26 章从这里接着讲）：")
    cv.text(41, 6, "写进这个语法就能解；写不进去，就只剩松弛与近似（第 26 章）")
    return cv.render()


# ---------- ch25 block4：一阶方法的收敛率阶梯 ----------
def fig_firstorder_rates() -> list[str]:
    ROWS, COLS = 34, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "收敛率：一阶法的一切由三个数决定——曲率上界 L、曲率下界 mu、结构。")
    cv.text(2, 4, "凸 + L-光滑            梯度下降        O(L D^2 / eps)")
    cv.text(3, 4, "mu-强凸 + L-光滑       梯度下降        O((L/mu) log(1/eps))")
    cv.text(4, 4, "凸 + L-光滑            Nesterov        O(D sqrt(L/eps))")
    cv.text(5, 4, "mu-强凸 + L-光滑       Nesterov        O(sqrt(L/mu) log(1/eps))")
    cv.text(6, 4, "非光滑（梯度界 G）     次梯度法        O(G^2 D^2 / eps^2)")
    cv.text(7, 4, "光滑 + 有 prox         ISTA / FISTA    O(1/eps) / O(1/sqrt(eps))")
    cv.text(8, 4, "一般凸（锥规划）       内点法          O(sqrt(m) log(1/eps))")
    cv.text(9, 43, "每步代价 O(n^3)，它是唯一的天花板")
    cv.text(11, 4, "横着读这张表，其实只有两个结论（都很实用）：")
    cv.text(12, 6, "从 O(1/eps) 到 O(log(1/eps))，代价是每步从 O(n) 变成 O(n^3)")
    cv.text(13, 6, "大问题低精度用一阶法；小问题高精度用内点法——没有第三条路")
    cv.text(15, 4, "加速的全部红利只有一句话：把条件数 kappa = L / mu 换成它的平方根。")
    cv.text(16, 6, "kappa = 10^4 时，迭代数从 10^4 量级降到 10^2 量级，而每步代价不变。")
    cv.text(18, 4, "加速的三个代价与限制（不能只记它的好处）：")
    cv.text(19, 6, "不单调       目标值会短暂上升，早停与回退逻辑必须改写")
    cv.text(20, 6, "必须光滑     非光滑问题加速失效（下界卡在 O(1/sqrt(k))）")
    cv.text(21, 6, "只对一阶     一旦用 Hessian 就是内点法的地盘，不是一阶方法了")
    cv.text(23, 4, "非光滑的出路只有「结构」这一条（没有别的办法）：")
    cv.text(24, 6, "次梯度法（黑箱）        O(1/sqrt(k))   有下界，任何一阶方法都过不去")
    cv.text(25, 6, "近端梯度（用 prox）     O(1/k)         结构把速率换回来了")
    cv.text(26, 6, "FISTA（prox + 动量）    O(1/k^2)       与光滑情形同等")
    cv.text(27, 6, "prox 的闭式来自哪：软阈值（l1）、奇异值软阈值（核范数）、投影（示性函数）")
    cv.text(29, 4, "这就是「结构换性能」最定量的一次呈现（值得单独记一行）：")
    cv.text(30, 6, "通用方法有普适下界，突破必须靠结构——这句话本书反复用")
    cv.text(31, 6, "—— 15 章（稀疏）、24 章（RL 的保证）、28 章（泛化）都是同一个道理")
    return cv.render()


# ---------- ch26 block0：非凸景观的地形图 ----------
def fig_nonconvex_landscape() -> list[str]:
    ROWS, COLS = 36, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "非凸优化：失去的只有一件事——一阶条件不再充分。剩下的靠四样东西。")
    cv.text(2, 4, "凸（第 25 章）                非凸（本章）")
    cv.text(3, 4, "梯度为零即是全局最优      梯度为零可能是极小、鞍点、极大")
    cv.text(4, 4, "切线是全局下界            切线只是局部线性化")
    cv.text(5, 4, "对偶间隙为零（Slater）    对偶间隙是度量（松弛的代价）")
    cv.text(6, 4, "收敛率只依赖 mu 与 L      收敛率依赖「到达了哪个盆地」")
    cv.text(8, 2, "三层最优性条件，以及「算法能不能到达」（这张表是重点）：")
    cv.text(9, 4, "一阶必要   grad f = 0                        能   O(1/eps^2)")
    cv.text(10, 4, "二阶必要   grad f = 0 且 Hessian >= 0         能   加扰动，约 O(1/eps^2)")
    cv.text(11, 4, "二阶充分   Hessian > 0                        能   同上，局部")
    cv.text(12, 4, "全局最优   还要求 f(x*) = f*                 不能 NP-hard")
    cv.text(14, 2, "非凸景观上的四种地形（哪一种才是真正的困难）：")
    cv.text(15, 4, "局部极小   所有方向都上升      没有免费信号，逃不出去（真正的困难）")
    cv.text(16, 4, "鞍点       有正有负的曲率      沿负曲率走一步就下降（二阶小量）")
    cv.text(17, 4, "平台       梯度极小            步长失效，靠噪声或动量")
    cv.text(18, 4, "悬崖       梯度极大            需要裁剪，否则一步跳飞")
    cv.text(20, 2, "高维几何：为什么鞍点是常态（这条是深度学习能优化的前提）：")
    cv.text(21, 4, "随机驻点处的 Hessian 就是一个随机对称矩阵")
    cv.text(22, 4, "特征值全正的概率随维数指数下降：P(全正) ~ exp(-c n)")
    cv.text(23, 4, "于是「随机驻点几乎必然有逃逸方向」—— 这是可优化性的几何前提")
    cv.text(25, 2, "逃出鞍点的三段式（扰动梯度下降，本节的招牌）")
    cv.text(26, 4, "第 1 段  梯度大           普通下降        每步降 eps^2/(2L)，计数")
    cv.text(27, 4, "第 2 段  梯度小且有负曲率 小球内均匀扰动  成功概率是常数，常数次尝试")
    cv.text(28, 4, "第 3 段  逃出后进入正曲率区 局部强凸收敛  第 25 章的一切都可以用了")
    cv.text(30, 2, "四样东西撑起了「非凸也能优化」（本章余下部分逐条展开）：")
    cv.text(31, 4, "隐式偏差   算法自己偏爱最小范数 / 最大间隔 / 低频    26.2")
    cv.text(32, 4, "噪声       温度 T ~ eta / B，逃逸、探索、选择平坦    26.3")
    cv.text(33, 4, "结构       反向传播、初始化、归一化、残差             26.5")
    cv.text(34, 4, "耦合       双层与极小极大的时间尺度必须拉开           26.4、26.6")
    return cv.render()


# ---------- ch26 block1：隐式偏差 ----------
def fig_implicit_bias() -> list[str]:
    ROWS, COLS = 34, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "隐式偏差：损失函数没规定的东西，由算法决定。")
    cv.text(2, 2, "例 1  欠定最小二乘（n > N 时有无穷多组解）")
    cv.text(3, 4, "min (1/2)||Ax - y||^2，用梯度流，初值 x(0) = 0")
    cv.text(4, 4, "结论   x(t) -> A^T (A A^T)^{-1} y，即最小 l2 范数解")
    cv.text(5, 4, "原因   梯度永远落在 range(A^T) 里，而 null(A) 里的分量永远为零")
    cv.text(6, 4, "工程读法  零初始化 = 一个「最小范数」先验；换初值就换解")
    cv.text(8, 2, "例 2  可分数据上的逻辑回归（不加任何正则项）")
    cv.text(9, 4, "min sum log(1 + exp(-y_i w^T x_i)) 在可分数据上无有限最优")
    cv.text(10, 4, "结论   ||w(t)|| -> 无穷，但方向收敛到最大间隔方向（即 SVM 解）")
    cv.text(11, 4, "工程读法  「训练越久」不是原地打转，而是沿方向移动：过训练会极端化")
    cv.text(13, 2, "例 3  谱截断：梯度流按奇异值从大到小依次拟合")
    cv.text(14, 4, "第 i 个方向的收敛速率  exp(-sigma_i^2 t)")
    cv.text(15, 4, "时刻 t 的「有效秩」   #{i : sigma_i 大于 1/sqrt(t)}")
    cv.text(16, 4, "工程读法  提前停止 = 谱正则化；与 15 章「先取大系数」同一种顺序策略")
    cv.text(18, 2, "三条共同的结论（合起来就是「过参数化能泛化」的第一把钥匙）：")
    cv.text(19, 4, "损失在 null 空间上完全平坦 -> 那些自由度由算法（初值、步长、迭代数）决定")
    cv.text(20, 4, "隐式偏差通常是 l2 型（偏好扩散 / 小范数），不是 l1 型（不偏好稀疏）")
    cv.text(21, 4, "于是「过参数化为什么不违反经典界」有了第一把钥匙")
    cv.text(23, 2, "与显式正则的关系（这是两条不能混为一谈的路）：")
    cv.text(24, 4, "显式 l2 正则   目标里加 (lam/2)||x||^2，强度固定，与迭代次数无关")
    cv.text(25, 4, "隐式偏差       算法自动产生，强度随迭代时间增大，最终趋于零")
    cv.text(26, 4, "所以「早停」和「加正则」可以互相替代，但不能同时当作两件事来算")
    cv.text(28, 2, "频率原理（非线性网络里的对应现象，由 NTK 解释）：")
    cv.text(29, 4, "训练时低频成分先被拟合、高频成分后被拟合（先粗后细）")
    cv.text(30, 4, "顺序由 NTK 的特征值决定，而 NTK 特征值随频率指数衰减（第 27 章）")
    cv.text(32, 4, "一句话  梯度流是一台「按谱从大到小依次学习」的机器。")
    return cv.render()


# ---------- ch26 block2：逃出鞍点与温度 ----------
def fig_saddle_escape() -> list[str]:
    ROWS, COLS = 36, 92
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "逃出鞍点与噪声的三个角色：一个二阶问题，一台带温度的机器。")
    cv.text(2, 2, "为什么「跟着梯度走」到不了鞍点以外的任何地方（一阶信息为零）：")
    cv.text(3, 4, "鞍点处 grad f = 0，一阶信息完全为零（没有任何方向感）")
    cv.text(4, 4, "沿最小特征方向 v 走 t：f(x + t v) ~ f(x) + (t^2/2) * lambda_min")
    cv.text(5, 4, "下降是「二阶小量」——必须有人告诉你「往哪拐」")
    cv.text(7, 2, "高维为什么帮了忙（一个只依赖「维数大」的论证）：")
    cv.text(8, 4, "均匀随机扰动在某指定方向的分量小于 r/sqrt(n) 的概率是常数")
    cv.text(9, 4, "于是「扰动一次就成功逃出」的概率不随维数衰减")
    cv.text(10, 4, "这正是「鞍点廉价」的另一面：逃逸通道永远是打开的")
    cv.text(12, 2, "扰动梯度下降的三段式（几何描述，也是证明骨架）：")
    cv.text(13, 4, "在鞍点附近：梯度为零，算法在球内随机探一下，找到负曲率方向")
    cv.text(14, 4, "逃出之后：梯度立刻非零，接着就是普通的下降")
    cv.text(15, 4, "走进正曲率邻域：局部强凸，第 25 章的线性收敛接管")
    cv.text(16, 4, "总代价约 O(1/eps^2)，与「只找一阶稳定点」同阶——顺带就做到了")
    cv.text(18, 2, "噪声的三个角色（三种机制的层次不同，不要混着说）：")
    cv.text(19, 4, "逃逸   单步事件的概率    噪声落到负曲率方向，离开鞍点        中期")
    cv.text(20, 4, "探索   长期稳态分布      可以跨过小势垒，不至于困在局部盆地    全程")
    cv.text(21, 4, "选择   稳态的概率质量    质量正比于 det(H)^{-1/2}，偏好平坦    末期")
    cv.text(23, 2, "温度：三个角色最终统一到同一个参数上（这是最实用的一条）：")
    cv.text(24, 4, "T 正比于 eta / B（学习率除以批量大小，单位：噪声 / 曲率）")
    cv.text(25, 4, "稳态分布 rho(theta) 正比于 exp(-f(theta)/T)")
    cv.text(26, 4, "低温度  指数项 e^{-f/T} 压倒体积项 det^{-1/2} -> 选损失最低的盆地")
    cv.text(27, 4, "高温度  体积项相对重要 -> 偏好「宽」的盆地，也不迷信低损失")
    cv.text(29, 2, "三个工程推论（每一条都能在 26.6.2 里对上）：")
    cv.text(30, 4, "大学习率泛化更好    温度高，长期停更平坦的盆地")
    cv.text(31, 4, "小批量泛化更好      批量小则温度高，与上一条同源")
    cv.text(32, 4, "学习率退火          末期降温，锁定最终盆地")
    cv.text(34, 4, "辨析  温度解释的是「落在哪个盆地」，不是「为什么这个解能泛化」")
    return cv.render()


# ---------- ch26 block3：反向传播 = 协态方程 ----------
def fig_backprop_adjoint() -> list[str]:
    ROWS, COLS = 29, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "反向传播不是「深度学习的新技巧」，它就是最优控制的协态方程。")
    cv.text(2, 4, "最优控制")
    cv.text(2, 40, "神经网络")
    cv.text(2, 70, "含义")
    cv.text(3, 4, "-" * 32)
    cv.text(3, 40, "-" * 26)
    cv.text(3, 70, "-" * 18)
    TAB = [
        ("状态   x_k", "激活   z_k", "逐层传递的量"),
        ("控制   u_k", "权重   W_k", "要优化的参数"),
        ("前向 x_{k+1} = f(x_k,u_k)", "前向 z_{k+1} = W_{k+1}a_k", "层 = 时间步"),
        ("代价 sum_k c_k(x_k,u_k)", "损失 L(z_N, y)", "终端代价"),
        ("协态   p_k", "误差   delta_k", "反向传播的量"),
        ("递推 p_k = dc/dx + (df/dx)^T p", "delta_k = (W^T delta)*phi'", "同一条链式法则"),
        ("梯度 dJ/du = (df/du)^T p", "dL/dW_k = delta_k a_{k-1}^T", "协态 乘 状态"),
    ]
    for i, (a, b, c) in enumerate(TAB):
        cv.text(4 + i, 4, a)
        cv.text(4 + i, 40, b)
        cv.text(4 + i, 70, c)
    cv.text(12, 4, "认出这个同构以后，四件事立刻「免费」：")
    cv.text(13, 4, "1  复杂度    反向时间 = 前向的常数倍；空间 = O(深度)（必须存整条状态轨迹）")
    cv.text(14, 17, "这正是第 19 章里协态方程的可解性代价")
    cv.text(15, 4, "2  检查点    梯度检查点 = 多重打靶法：只存若干检查点，其余重算")
    cv.text(16, 17, "以时间换空间 —— 1960 年代的技术用在 2020 年代的大模型上")
    cv.text(17, 4, "3  权重共享  RNN / CNN 的梯度 = 各时间步贡献之和（时不变系统的伴随）")
    cv.text(18, 17, "得到「沿时间平均」的降噪好处，也带来爆炸与消失的风险")
    cv.text(19, 4, "4  消失爆炸  delta_k = prod_{j>=k}(W_{j+1}^T * phi')，一个线性时变系统")
    cv.text(20, 17, "谱半径小于 1 指数衰减，大于 1 指数增长，约等于 1 才能传深")
    cv.text(22, 4, "一句话对应表（本章最省力的记忆法，值得抄下来）：")
    cv.text(23, 6, "梯度检查点  <-  多重打靶         梯度裁剪  <-  控制限幅（抗饱和）")
    cv.text(24, 6, "梯度消失    <-  Lyapunov 指数     权重共享  <-  时不变伴随方程求和")
    cv.text(25, 6, "早停        <-  有限时域的最优截断")
    cv.text(27, 4, "所以：训练一个深度网络 = 解一个离散最优控制问题，只是规模大得多。")
    return cv.render()


# ---------- ch26 block4：结构三件套 ----------
def fig_normalization_map() -> list[str]:
    ROWS, COLS = 37, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "结构三件套：初始化让信号传得远，归一化让尺度不敏感，残差让梯度传得深。")
    cv.text(2, 2, "一、初始化：让信号的方差有一个稳定的不动点（否则指数衰减）")
    cv.text(3, 4, "前向方差递推     q_{l+1} = sigma_w^2 * E[phi(z)^2]，  z ~ N(0, q_l)")
    cv.text(4, 4, "ReLU            E[phi(z)^2] = q/2，故临界值 sigma_w^2 = 2（He 初始化）")
    cv.text(5, 4, "tanh            低于临界值信号消失，高于临界值信号饱和（信息同样消失）")
    cv.text(6, 4, "要求「全部奇异值接近 1」，而不是「平均为 1」：")
    cv.text(7, 6, "梯度是 prod J_l，乘积由最小的那些奇异值决定（谱范数的次乘性）")
    cv.text(8, 6, "所以真正要控制的是「谱的集中」——这叫动力等距")
    cv.text(10, 2, "二、归一化：同一个公式，四种取法（区别只在统计范围）")
    cv.text(11, 4, "Norm(x) = gamma * (x - mu_S) / sqrt(var_S + eps) + beta")
    cv.text(12, 4, "取哪些下标组成集合 S，就得到哪一种归一化：")
    cv.text(13, 6, "BatchNorm    同通道、跨样本与空间     统计量来自批量（训练）/ 滑动平均（推理）")
    cv.text(14, 6, "LayerNorm    同样本、跨特征           单样本内，训练与推理一致")
    cv.text(15, 6, "InstanceNorm 同样本同通道             风格迁移常用")
    cv.text(16, 6, "GroupNorm    通道分组内               小批量友好的折中")
    cv.text(18, 2, "归一化为什么有用（三个机制里，前两个才是主因）：")
    cv.text(19, 4, "机制 1  消除尺度自由度：W -> cW 时输出不变，故 grad 正交于 W")
    cv.text(20, 12, "这相当于把优化限制在「权重方向的球面」上（投影 / 流形优化）")
    cv.text(21, 4, "机制 2  压低损失函数的 Lipschitz 常数 L，于是步长上限 1/L 变大")
    cv.text(22, 12, "这就是「加了 BN 就能调大学习率」的数学原因")
    cv.text(23, 4, "机制 3  原始论文说的「内部协变量偏移」已被证伪为主因（但仍是好故事）")
    cv.text(25, 2, "三、残差连接：动力等距的一个免费实现（不需要精细调参）：")
    cv.text(26, 4, "z_{l+1} = z_l + F_l(z_l)   ->   Jacobian = I + dF_l")
    cv.text(27, 4, "所有特征值集中在 1 附近，于是连乘近似变成连加：prod(I + J_l) ~ I + sum J_l")
    cv.text(28, 4, "梯度不再指数衰减，而是线性累积 —— 这就是「能训练 100 层」的直接原因")
    cv.text(29, 4, "与第 18 章同一判据：特征值不越过边界（时间上不过虚轴，深度上不过单位圆）")
    cv.text(31, 2, "一张对照表：三件套各自治什么病（对症下药，别乱用）：")
    cv.text(32, 4, "病征                    药                      对应前文")
    cv.text(33, 4, "梯度消失 / 爆炸          良好初始化 + 残差连接    18 章稳定性、Lyapunov 指数")
    cv.text(34, 4, "尺度敏感、学习率难调    归一化                   22 章自适应、25 章条件数")
    cv.text(35, 4, "深度不可训练            残差连接（近恒等映射）   18 章「接近恒等的系统」")
    return cv.render()


# ---------- ch27 block0：从非凸宽网络到核回归的桥梁 ----------
def fig_ntk_pipeline() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "本章的桥梁：非凸宽网络 ==(两道极限)==> 可解析的核回归（第 6 章的语言）")
    cv.text(2, 3, "起点  有限宽网络 f(x; theta) —— 非凸、层间耦合、损失景观无解析式")
    cv.text(3, 6, "（这就是第 26 章的全部困境，也是本章要设法绕开的对象）")
    cv.text(4, 6, "                       |   （注意：这一步只动初始化，还没有开始训练）")
    cv.text(5, 6, "                       |  第一道极限：宽度 n -> 无穷（只看初始化）")
    cv.text(6, 6, "                       v   ——  得到的是一个「先验」，还不是「预测」")
    cv.text(7, 3, "中点  随机特征 / NNGP 先验 —— 网络在初始化处就是一个高斯过程")
    cv.text(8, 6, "网络在初始化处就是一个高斯过程：核 K(x,x') 只由架构与激活决定")
    cv.text(9, 6, "与具体抽到哪组参数无关（自平均：有限宽的涨落随 1/sqrt(n) 消失）")
    cv.text(10, 6, "                       |   （从这一行往下，才开始真正地动参数）")
    cv.text(11, 6, "                       |  第二道极限：训练时输出变化极小（lazy training）")
    cv.text(12, 6, "                       v   ——  得到的是一个「核回归解」，有闭式表达")
    cv.text(13, 3, "终点  NTK 回归 —— 问题已经退化成一个线性问题，可以闭式求解")
    cv.text(14, 6, "输出的演化 = 核梯度流，核 Theta 在整个训练中冻结（不变）")
    cv.text(15, 6, "预测 = 核岭回归的闭式解，或线性 ODE 的指数衰减解 e^{-Theta t}")
    cv.text(17, 2, "三道立刻可用的推论（这才是本章的实际收获）：")
    cv.text(18, 4, "一  NTK 是「f 对参数的梯度」的内积 —— 一个 Gram 矩阵，必然正定")
    cv.text(19, 4, "二  核的谱决定能学到的频率：多项式尾能学高频，指数尾几乎学不到")
    cv.text(20, 4, "三  「网络超过核」只能来自 lazy 失效（特征演化 / 低维结构 / muP）")
    cv.text(22, 2, "为什么值得花一整章（三个身份，认出它比记住公式有用）：")
    cv.text(23, 4, "第 26 章的结局   非凸还剩什么 -> 极限答案「宽度给凸性」")
    cv.text(24, 4, "第 6 章的回声   核、RKHS、Mercer 都在 6 章讲过，只是把 phi 换成了梯度")
    cv.text(25, 4, "第 28 章的工具   NTK 把非凸问题转成线性问题，范数界与谱方法全部可用")
    cv.text(27, 2, "但代价是真实的（这是本章要反复提醒的一句话）：")
    cv.text(28, 4, "在 lazy 极限下，你训练的不再是「会学特征的网络」，而是一个核方法")
    cv.text(29, 4, "网络相对于核的全部优势，都必须发生在「核还没冻住」的那段时间里")
    return cv.render()


# ---------- ch27 block1：NNGP 核与 NTK 的双重递推 ----------
def fig_ntk_recursion() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "无限宽网络的双重递推：两个核一起往前传，一个管前向，一个管训练")
    cv.text(2, 2, "记号（第 l 层的两个核，都是 x 与 x' 的标量函数）：")
    cv.text(3, 4, "K^(l)(x,x')     = E[ z_i^(l)(x) * z_i^(l)(x') ]        前向相关（NNGP 核）")
    cv.text(4, 4, "Theta^(l)(x,x') = 第 l 层「参数梯度」对输出的贡献        训练用的 NTK")
    cv.text(6, 2, "递推一（NNGP，只管前向信号的传播，与训练无关）：")
    cv.text(7, 4, "K^(0)     = x . x' / d_in                      （输入层：内积）")
    cv.text(8, 4, "K^(l+1)   = sigma_b^2 + sigma_w^2 * E[ phi(u) phi(v) ]")
    cv.text(9, 4, "其中 (u,v) ~ N(0, Lambda^(l))，Lambda^(l) 是 2x2 协方差矩阵：")
    cv.text(10, 4, "    对角元 = K^(l)(x,x) 与 K^(l)(x',x')，非对角元 = K^(l)(x,x')")
    cv.text(12, 2, "递推二（NTK，在 NNGP 之上再叠一层「导数因子」）：")
    cv.text(13, 4, "Theta^(0)   = K^(0)                       （起点与 NNGP 核完全相同）")
    cv.text(14, 4, "Theta^(l+1) = K^(l+1)  +  sigma_w^2 * Theta^(l) * E[ phi'(u) phi'(v) ]")
    cv.text(15, 4, "                ^第一条：本层（第 l+1 层）的贡献")
    cv.text(16, 4, "                                        ^第二条：前面所有层的累积贡献")
    cv.text(18, 2, "读出三件事（这三条就是 27.2 的全部内容）：")
    cv.text(19, 4, "一  Theta = K + sum_l (前向核 x 导数核) —— 每一层都给一点，没有白给的层")
    cv.text(20, 4, "二  递推是「逐层的标量函数」，可用高斯期望做数值积分逐层算出来")
    cv.text(21, 4, "三  深度增加时 Theta 趋于不动点 —— 这就是「深网络也约等于核」的原因")
    cv.text(23, 2, "两个特例（可以先背下来，考场上直接套用）：")
    cv.text(24, 4, "只训最后一层   递推二的第二项消失，Theta 退化为 NNGP 核 K（随机特征）")
    cv.text(25, 4, "深线性网络     phi 恒等，phi' = 1，于是 Theta^(l+1) = K^(l+1) + sigma_w^2 Theta^(l)")
    cv.text(27, 2, "一个关键的「反直觉」点（它解释了为什么 NTK 不是故事的全部）：")
    cv.text(28, 4, "上面的递推全都在「初始化」处成立，靠的是「核在训练中不变」这一条假设")
    cv.text(29, 4, "如果核真的不变，网络就永远等于一个核方法 —— 特征从头到尾一次都没学过")
    cv.text(30, 4, "所以整章的技术核心落在 27.5：「核在什么条件下才近似不变」")
    return cv.render()


# ---------- ch27 block2：三类核的谱衰减对照 ----------
def fig_ntk_spectrum() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "三类核的谱衰减：它决定「这个核能不能学到高频」——27.4 的核心对照")
    cv.text(2, 2, "核类型            特征值衰减           能学到的函数        代表场景")
    cv.text(3, 3, "高斯核 RBF        lambda_k ~ exp(-c k^{2/d})   极光滑（解析）      经典核回归")
    cv.text(4, 3, "拉普拉斯核        lambda_k ~ k^{-(d+1)}        一阶光滑            指数型核")
    cv.text(5, 3, "弧余弦核 ReLU     lambda_k ~ k^{-(d+1)}        一阶光滑（H^1）     无限宽 ReLU 网络")
    cv.text(7, 2, "把谱当「学费」来读（这一句解决本章一半的困惑）：")
    cv.text(8, 4, "谱衰减快  =  高频方向的特征值趋于 0  =  在那个方向学习需要极大样本量")
    cv.text(9, 4, "于是：RBF 核「天生不适合学高频」；弧余弦核能学高频，但慢（多项式级）")
    cv.text(11, 2, "为什么弧余弦核与高斯核的差别是「本章最关键的技术细节」：")
    cv.text(12, 4, "两者都是一阶光滑核的常客，但一个是指数尾、一个是多项式尾")
    cv.text(13, 4, "多项式尾意味着「高频特征值虽然小，却不趋于零」—— 与指数尾是质的差别")
    cv.text(14, 4, "这就是「为什么（宽）神经网络在学高频上显著优于 RBF 核」的数学原因")
    cv.text(16, 2, "维度诅咒的核版本（也是「网络为什么能赢核」的入口）：")
    cv.text(17, 4, "要在 d 维输入上学到一个「阶 K」的函数，需要的样本量与 K^d 同阶")
    cv.text(18, 4, "但诅咒的强度取决于「目标到底依赖多少个方向 r」，而不是输入维数 d")
    cv.text(19, 4, "若 r 远小于 d（低维结构），核的实际劣势被大幅削弱")
    cv.text(20, 4, "反过来说：目标真有低维结构时，网络能自适应地找到那几个方向（27.5.3）")
    cv.text(22, 2, "谱偏差：核梯度流对第 k 个特征方向的收敛速率恰好就是 lambda_k")
    cv.text(23, 4, "于是低频（大 lambda）先学会，高频（小 lambda）后学会，顺序被谱完全锁死")
    cv.text(24, 4, "它就是第 6 章「谱显式解」在 NTK 上的原样重演：误差 e^{-lambda_k t} 逐方向衰减")
    cv.text(26, 2, "一张谱衰减的速查表（把 lambda_k 当成「学到该频率的难度」）：")
    cv.text(27, 4, "谱衰减        高频学习难度       典型核              什么时候吃亏")
    cv.text(28, 4, "指数尾极快    极难               高斯 RBF            目标含高频分量")
    cv.text(29, 4, "多项式尾      中等（可学但慢）   弧余弦（ReLU NTK）  样本量太小")
    cv.text(30, 4, "有限阶截断    高频为零           多项式核            高频完全无法表示")
    return cv.render()


# ---------- ch27 block3：SP 与 muP 参数化对照 ----------
def fig_mup_scaling() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "参数化决定极限行为：为什么「小模型调好的超参」不能直接搬到宽模型")
    cv.text(2, 2, "标准参数化 SP（教科书默认写法）在宽极限下的行为：")
    cv.text(3, 4, "隐藏层学习率 = eta                逐层贡献随宽度衰减到 0")
    cv.text(4, 4, "输出层学习率 = eta                更新量随宽度放大 n 倍 -> 主导且不稳")
    cv.text(5, 4, "初始化方差   = 1 / fan_in         于是宽模型退化为随机特征 / NNGP")
    cv.text(7, 2, "最大更新参数化 muP（让每层贡献保持 O(1)）：")
    cv.text(8, 4, "隐藏层学习率 = eta                每一层对函数更新的贡献都保持 O(1)")
    cv.text(9, 4, "输出层学习率 = eta / n            所有层一起动，既不衰减也不爆炸")
    cv.text(10, 4, "初始化方差   = 1 / fan_in         于是「小模型调好的超参」能搬到宽模型")
    cv.text(12, 2, "一条可操作的判据（这是 27.5 最实用的一句话）：")
    cv.text(13, 4, "检查每一层对「函数更新」的贡献，在宽度增大时是否保持 O(1)：")
    cv.text(14, 6, "衰减到 0    -> 该层在极限下被冻结（SP 的失效模式）")
    cv.text(15, 6, "爆炸        -> 该层主导一切（另一类失效，训练不稳）")
    cv.text(16, 6, "保持 O(1)   -> 这才是「正确的参数化」（muP 的设计目标）")
    cv.text(18, 2, "为什么这件事值钱（把「调参」的成本量级降下来）：")
    cv.text(19, 4, "在小模型上把所有超参调好  ==>  直接搬到宽模型，无需重调")
    cv.text(20, 4, "成本从 O(搜索 x 大模型成本) 降到 O(搜索 x 小模型成本)")
    cv.text(21, 4, "对一个几十亿参数的模型，「能否用几百万参数的代理模型定超参」是关键")
    cv.text(23, 2, "与 lazy / rich 的关系（两种极限是同一件事的两面）：")
    cv.text(24, 4, "SP    极限下核冻结 -> lazy   -> 等价于核方法（特征是随机的、不学的）")
    cv.text(25, 4, "muP   极限下各层都动 -> rich  -> 特征真的在演化（网络才可能超过核）")
    cv.text(27, 2, "一句话总结本章的实践建议（两条路，选一条，别混着用）：")
    cv.text(28, 4, "想用「宽模型 + 超参迁移」-> 用 muP；想用「宽模型 + 理论保证」-> 用 NTK")
    cv.text(29, 4, "想真的赢过核方法 -> 必须离开 lazy，把学习率、宽度、训练时长都调到 rich 区")
    return cv.render()


# ---------- ch27 block4：lazy 与 rich 的分界 ----------
def fig_lazy_rich() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "lazy 与 rich：NTK 什么时候「冻住」，什么时候「演化」——27.5 的分界")
    cv.text(2, 4, "lazy（惰性）regime                  rich（丰富）regime")
    cv.text(3, 4, "核 Theta_t 训练中不变              核 Theta_t 随 t 演化")
    cv.text(4, 4, "输出是 theta_0 附近的线性化        输出走出了线性化区域")
    cv.text(5, 4, "等价于核方法（或随机特征）         等价于真正的「特征学习」")
    cv.text(6, 4, "条件：lr 小 + 宽度大 + 时间短      条件：lr 大 / 宽度有限 / 训练久")
    cv.text(8, 2, "分界怎么刻画（27.5 的核心判据）：比较两个时间尺度")
    cv.text(9, 4, "一个尺度：特征移动的速率（核自己变多快）")
    cv.text(10, 4, "另一个：输出拟合的速率（预测追标签多快）")
    cv.text(11, 6, "特征移动 远小于 输出拟合   ->  lazy（两个尺度分离）")
    cv.text(12, 6, "两者同阶                   ->  rich（特征在跟着一起学）")
    cv.text(14, 2, "网络在什么问题上能超过核（27.5.3 的判据，三条）：")
    cv.text(15, 4, "一  目标有低维 / 稀疏结构：网络能自适应地找到那几个方向")
    cv.text(16, 4, "二  目标的高频部分重要：核的样本复杂度不可接受")
    cv.text(17, 4, "三  样本量中等且结构明确：网络的优势最明显")
    cv.text(19, 2, "实践对照表（「理论上网络更强」与「你的预算下网络更强」是两个问题）：")
    cv.text(20, 4, "你的情形                        建议  <- 先问「哪个更强」")
    cv.text(21, 4, "低维 / 稀疏结构 + 中等样本      网络（别用核）")
    cv.text(22, 4, "一般光滑函数 + 海量样本         核 / 宽网络（更稳、更好调）")
    cv.text(23, 4, "样本量极小（小于 1e3）          核 / GP（没有优化不稳的问题）")
    cv.text(24, 4, "需要严格的不确定性量化          GP / NNGP 后验（天然优势）")
    cv.text(25, 4, "高维图像 / 文本                 网络（核的样本复杂度不可接受）")
    cv.text(27, 2, "最后一条常被低估的实践真相（选型时最容易踩的坑）：")
    cv.text(28, 4, "在小样本下，网络「能超过核」的理论优势，常被「优化不稳 + 调参成本高」抵消")
    cv.text(29, 4, "所以选型时先问「我的预算下哪一个真的更强」，而不是「哪一个理论上界更高」")
    return cv.render()



# ---------- ch28 block0：泛化理论的五条路线总览 ----------
def fig_gen_learning_map() -> list[str]:
    ROWS, COLS = 34, 100
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "泛化理论的五条路线：都在回答同一个问题，但拿的是不同的「复杂度尺子」")
    cv.text(2, 2, "问题   sup_f |R(f) - R_hat(f)| 到底有多大？")
    cv.text(3, 4, "（28.1：一致收敛把「泛化」转化成一个纯几何 / 概率问题）")
    cv.text(5, 2, "路线 1  容量：假设类复杂度               尺子 = 类的表达能力")
    cv.text(6, 4, "VC 维 / 增长函数 / Sauer 引理 / 充要条件（分类）")
    cv.text(7, 4, "软肋：只对分类、与数据无关、与算法无关（三条短板）")
    cv.text(9, 2, "路线 2  数据相关复杂度                   尺子 = 在数据上拟合噪声的能力")
    cv.text(10, 4, "Rademacher / 收缩引理 / 按层算谱范数乘积 / 局部 Rademacher 快速率")
    cv.text(11, 4, "软肋：仍是上界；深度网络里松弛很大（当诊断可以，当处方不行）")
    cv.text(13, 2, "路线 3  算法稳定性                       尺子 = 动一个样本，输出动多少")
    cv.text(14, 4, "均匀稳定性 / Bousquet-Elisseeff 界 / 稳定性<=>可学习性 / SGD 的隐式正则")
    cv.text(15, 4, "软肋：常数大、beta 难验证（但方向与处方都是对的）")
    cv.text(17, 2, "路线 4  PAC-Bayes 与信息论               尺子 = 算法从数据里取走多少比特")
    cv.text(18, 4, "Gibbs 分类器 / KL(Q||P) 界 / 互信息界 / 后验来自 SGD 的噪声")
    cv.text(19, 4, "软肋：依赖先验选择；绝对数值常常大 1-3 个数量级")
    cv.text(21, 2, "路线 5  插值与谱（现代路线）             尺子 = 有效秩")
    cv.text(22, 4, "双下降 / 最小范数插值的精确风险曲线 / 良性过拟合的三条件")
    cv.text(23, 4, "软肋：只对线性 / 核 / 宽网络可解析，但能解释经典界解释不了的现象")
    cv.text(25, 2, "五条路线不是「谁替代谁」，而是「互相夹逼」：")
    cv.text(26, 4, "看总量级  用路线 2；看趋势  用路线 5；看处方  用路线 3、4；看充要性  用路线 1")
    cv.text(28, 2, "一个容易忽略的事实：五条路线里只有路线 1 给出过「充要条件」，")
    cv.text(29, 4, "其余四条都只是「充分条件」—— 所以它们本质上都在做上界工程。")
    cv.text(30, 4, "真正的「下界」（构造反例说明学习不可能）只出现在无免费午餐与 VC 必要性里。")
    return cv.render()


# ---------- ch28 block1：打散、增长函数与 Sauer 引理 ----------
def fig_vc_shatter() -> list[str]:
    ROWS, COLS = 34, 100
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "打散与增长函数：VC 维是「指数增长」与「多项式增长」之间的那个开关")
    cv.text(2, 2, "打散的定义（关键：是「存在性」，不是「任意性」）：")
    cv.text(3, 4, "存在一个 m 点集，使 {+1,-1}^m 里每一种标签都能被 F 里某个 f 实现")
    cv.text(4, 4, "是「存在某个点集」，不是「任意点集」—— 方向搞反会让 VC 维反而变小")
    cv.text(6, 2, "增长函数  Pi_F(m) = max_{点集} #{ (f(z1),...,f(zm)) : f in F }")
    cv.text(7, 4, "Pi_F(m) <= 2^m（上界：全部标签组合，指数级）")
    cv.text(8, 4, "若 F 能打散某个 m 点集，则 Pi_F(m) = 2^m（指数，最坏情形）")
    cv.text(9, 4, "若 d_VC(F) = d < 无穷，则 Pi_F(m) <= sum_{k<=d} C(m,k) <= (em/d)^d（多项式）")
    cv.text(11, 2, "三个可直接对照的例子（VC 维就是个整数，很好算）：")
    cv.text(12, 4, "类                           Pi_F(m)                 d_VC")
    cv.text(13, 4, "R 上的阈值函数               m + 1                   1")
    cv.text(14, 4, "一维区间指示函数             C(m+1,2) + 1（二次）    2")
    cv.text(15, 4, "R^2 上的线性分类器           最高约 m^2 量级          3")
    cv.text(16, 4, "1-近邻 / 周期模式类          2^m（能打散一切）       无穷")
    cv.text(18, 2, "Sauer 引理是学习理论的支点（它一次做了三件事）：")
    cv.text(19, 4, "一  把无穷的假设类「折叠」成有限多种有效行为（联合界只需算这么多）")
    cv.text(20, 4, "二  解释了「泛化为什么可能」：没有它，无穷大的类无法一致收敛")
    cv.text(21, 4, "三  解释了 log n 因子的来源：log Pi ~ d log(n/d)，是组合结构的产物")
    cv.text(23, 2, "可学习性的充要条件（分类 / 有界损失的情形）：")
    cv.text(24, 4, "F 可学习（一致 / ERM）    <=>    d_VC(F) < 无穷")
    cv.text(25, 4, "「<=」这一半才是「VC 维为什么是正确的复杂度度量」的答案")
    cv.text(27, 2, "最后一行提醒（它正是 28.4 要引入稳定性的动机）：")
    cv.text(28, 4, "1-近邻的 d_VC = 无穷，却泛化良好 —— 但它的 Rademacher 复杂度恒等于 1，")
    cv.text(29, 4, "一致收敛救不了它；救它的是「动一个样本，输出动多少」—— 稳定性（28.4）。")
    return cv.render()


# ---------- ch28 block2：Rademacher 界的四个模块 ----------
def fig_rademacher_anatomy() -> list[str]:
    ROWS, COLS = 34, 100
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Rademacher 界的四个模块：它为什么既「可算」又「可加」")
    cv.text(2, 2, "模块 1  复杂度   R_n(F) = E sup_f (1/n) sum_k sigma_k f(Z_k)")
    cv.text(3, 6, "—— 用随机符号「扰动」数据，看这个类能拟合多少纯噪声")
    cv.text(5, 2, "模块 2  集中     以概率 1-delta：sup_f |R(f)-R_hat(f)| 不超过 2 R_n(F) + sqrt(log(1/delta)/2n)")
    cv.text(6, 6, "—— 期望 -> 高概率（McDiarmid / 有界差分，第 8 章）")
    cv.text(8, 2, "模块 3  收缩     R_n(phi o F) <= L_phi * R_n(F)   （phi 为 Lipschitz 且过原点）")
    cv.text(9, 6, "—— 复杂度沿「组合链」线性传播：这才是可加性的来源")
    cv.text(11, 2, "模块 4  结构     逐层回传：损失 -> 激活 -> 每层乘 ||W^(l)|| -> 输入界 B/sqrt(n)")
    cv.text(12, 6, "—— 结果是「B * prod_l ||W^(l)|| / sqrt(n)」这一形态")
    cv.text(14, 2, "三个必须记住的读数（它们解释了它为什么好用、又为什么松）：")
    cv.text(15, 4, "一  复杂度不看参数量，看「在经验测度下拟合随机噪声的能力」")
    cv.text(16, 4, "二  「可加」是它成为深度网络主流工具的唯一原因（VC 维不可加）")
    cv.text(17, 4, "三  深度只以「谱范数乘积」出现 -> 控制乘积就是控制泛化（weight decay 的作用点）")
    cv.text(19, 2, "它的两个短板（正好对应 28.4 与 28.6 这两节）：")
    cv.text(20, 4, "短板 1  仍是上界：深度网络里松弛可达几个数量级（当诊断可以，当处方不行）")
    cv.text(21, 4, "短板 2  仍是一致收敛：对「算法选出的那一个 f」并非必要 -> 换稳定性语言")
    cv.text(23, 2, "与 VC 维的三处对照（一句话说清换了什么）：")
    cv.text(24, 4, "数据相关   R_n 的期望是对实际抽到的 Z 取的，数据若低维它自动变小")
    cv.text(25, 4, "可加       复杂度随函数类的组合线性叠加 -> 这是「按层算」的唯一起点")
    cv.text(26, 4, "不要求有限维 核方法 / 无穷维 RKHS / 深度网络仍然是一个有限数、可算")
    return cv.render()


# ---------- ch28 block3：稳定性这条线的全景 ----------
def fig_stability_sgd() -> list[str]:
    ROWS, COLS = 34, 100
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "稳定性这条线的全景：从「动一个样本」到「隐式正则」")
    cv.text(2, 2, "定义层   均匀 beta-稳定： |l(A(S),z) - l(A(S^(k)),z)| <= beta")
    cv.text(3, 6, "含义：动一个样本，输出动多少 —— 这就是「记忆 vs 平滑」的定量版")
    cv.text(4, 6, "关键：只依赖算法 A，不依赖假设类 F（所以 F 可以是无穷维，如核方法）")
    cv.text(6, 2, "定量层   Bousquet-Elisseeff： |R - R_hat| <= beta*log(1/delta) + sqrt(n*beta*M/n)")
    cv.text(7, 6, "只要 beta = beta_n -> 0，泛化就成立（注意：两边都趋于零）")
    cv.text(8, 6, "对比：容量界要一致收敛（对所有 f），稳定性只要「你实际产出的那一个 f」")
    cv.text(10, 2, "等价层   d_VC < 无穷   <=等价=>   ERM 一致稳定")
    cv.text(11, 6, "可学习性本质上是「算法」的性质，而不是「假设类」的性质")
    cv.text(13, 2, "处方层   三条降低 beta 的手段（都已在前面章节出现过）：")
    cv.text(14, 6, "强正则（lambda 大）      beta ~ B^2 B_y / (lambda n)       <- 25 章条件数")
    cv.text(15, 6, "早停（t 小）             lambda_eff ~ 1 / t                <- 27.1.2")
    cv.text(16, 6, "噪声 / 温度（eta/B 大）  Q 被摊开，单样本敏感度下降      <- 26.6.2")
    cv.text(17, 6, "合一：beta 下降 <=> 泛化上升 —— 这就是「隐式正则」的精确翻译")
    cv.text(19, 2, "一条反面提醒（关于这个界到底要怎么用才对）：")
    cv.text(20, 4, "beta 的界常数很大、实践中很难严格验证；它的价值是给出正确的「剂量-反应关系」，")
    cv.text(21, 4, "而不是算出一个可以印在论文里的数。所以：看趋势，别盯绝对值。")
    cv.text(23, 2, "为什么它在深度学习的语境里比容量界更「讲道理」：")
    cv.text(24, 4, "它从定义上就绕开了一致收敛 —— 而一致收敛正是 p >> n 时失效的那一步（28.1.2）")
    cv.text(25, 4, "它天然给出处方 —— 容量界说「把类变小」，稳定性说「把单样本敏感度压小」")
    cv.text(26, 4, "而后者在实践里是可执行的（正则、早停、批量、噪声），前者常常不是。")
    return cv.render()


# ---------- ch28 block4：双下降的区域与判据 ----------
def fig_double_descent_theory() -> list[str]:
    ROWS, COLS = 34, 100
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "双下降的三个区域：把横轴换成「有效秩」，经典曲线就回来了")
    cv.text(2, 2, "横轴用参数量 p（容易被误读）        横轴用有效自由度 df_hat（推荐）")
    cv.text(3, 4, "p < n    欠参数化区：经典界有效，曲线单调下降")
    cv.text(4, 4, "p ~ n    峰值区：插值刚刚可能，风险发散（最危险的一段）")
    cv.text(5, 4, "p > n    过参数化区：风险重新下降，需要新的解释工具")
    cv.text(7, 2, "区域的正确判据（用一个可测量的量，而不是参数量）：")
    cv.text(8, 4, "df_hat = #{ k : lambda_k >~ 1/n }        （核谱里「能学到」的方向数）")
    cv.text(9, 4, "或者    df_hat = tr[ X (X^T X)^{-1} X^T ]  （线性模型的有效自由度）")
    cv.text(10, 6, "df_hat < n    经典区：容量界单调、加数据有效")
    cv.text(11, 6, "df_hat ~ n    峰值区：最危险，千万别停在这里")
    cv.text(12, 6, "df_hat > n    插值区：用最小范数 / 谱衰减 / 隐式偏差来解释")
    cv.text(14, 2, "三个区域的泛化风险形状（线性最小范数插值，有解析式）：")
    cv.text(15, 4, "df < n     风险 ~ sigma^2 * df / (n - df)             随 df 上升（经典上升段）")
    cv.text(16, 4, "df = n     风险发散：这就是双下降的峰，与 p ~ n 等价")
    cv.text(17, 4, "df > n     风险 ~ sigma^2 * (1 - n/df) * 谱因子        随 df 上升而下降")
    cv.text(18, 4, "df -> 无穷 风险 -> sigma^2 * 谱因子                    收敛到非零常数（不免费）")
    cv.text(20, 2, "两个竞争机制的较量（它们就写在同一行公式里）：")
    cv.text(21, 4, "近似误差：多出来的方向能学到更多细节        作用方向 -> 让风险下降")
    cv.text(22, 4, "噪声放大：多出来的方向同时也接收噪声        作用方向 -> 让风险上升")
    cv.text(23, 4, "双下降 = 两者在不同区间里相对强弱的切换，而不是什么新的数学")
    cv.text(25, 2, "处方（与 28.8.5 的五症状诊断表一一对应）：")
    cv.text(26, 4, "停在峰值区          -> 继续加大模型，穿过峰（千万别停在峰上）")
    cv.text(27, 4, "过峰后仍不如小模型  -> 谱太长尾，加显式正则或数据增强")
    cv.text(28, 4, "无峰值、单调上升    -> 噪声主导：降容量、加正则、查标签质量")
    cv.text(29, 4, "无峰值、单调下降    -> 瓶颈是表达能力：加深度 / 宽度")
    return cv.render()



# ---------- ch29 block0：三条线汇到同一个方程 ----------
def fig_genmodel_map() -> list[str]:
    ROWS, COLS = 32, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "三条线汇到同一个方程：采样 = 分布上的梯度下降；生成 = 先破坏、再复原")
    cv.text(2, 2, "线路 1（优化视角）   SGD 的梯度噪声：方差 ~ eta / B，连续化后")
    cv.text(3, 4, "dtheta = -grad f dt + sqrt(2T) dB，其稳态是 Gibbs 分布 exp(-f / T)")
    cv.text(4, 4, "这正是 26.3.2 讲的「温度」：T 由学习率与批量大小共同决定")
    cv.text(6, 2, "线路 2（采样视角）   Langevin 动力学：取 U = -log p、T = 1，则")
    cv.text(7, 4, "dX = grad log p dt + sqrt(2) dB，其稳态恰好是 p 本身（定理 9.24）")
    cv.text(8, 4, "于是「从 p 采样」被改写成了「解一个 SDE 跑到稳态」")
    cv.text(10, 2, "线路 3（生成视角）   扩散模型：两段前后相接的动力学")
    cv.text(11, 4, "前向：加噪，把 p_data 淹成 N(0, I)，方程已知且转移核有闭式")
    cv.text(12, 4, "反向：用得分把噪声搬回数据，这就是定理 29.7（Anderson 反向 SDE）")
    cv.text(14, 2, "三条线唯一的交点是同一个量：得分函数 s(x) = grad log p(x)")
    cv.text(16, 2, "本章骨架（一条直线走完，每一步都只加一个概念，不换工具）")
    cv.text(17, 4, "29.2 认识得分   ->   29.3 学得分   ->   29.4 用得分采样")
    cv.text(18, 4, "29.5 / 29.6 升级成生成（反向 SDE）  ->  29.7 / 29.8 与优化理论接轨")
    cv.text(20, 2, "全部可行性的那一句话：密度要归一化，得分不用（Z 与 x 无关，梯度为零）")
    cv.text(22, 2, "六个必须记住的结果（本章的主干，后面每一节都挂在这六条上）")
    cv.text(23, 4, "1  得分不用归一化        grad log p = grad log p_tilde")
    cv.text(24, 4, "2  Tweedie：得分 = 去噪  E[x0 | xt] = xt + sigma_t^2 grad log p_t")
    cv.text(25, 4, "3  DSM 等价于回归噪声    min E || s_theta + eps / sigma_t ||^2")
    cv.text(26, 4, "4  反向 SDE 的漂移       f - g^2 grad log p_t（定理 29.7）")
    cv.text(27, 4, "5  概率流 ODE 与 SDE 同边缘  v = f - 0.5 g^2 grad log p_t（定理 29.8）")
    cv.text(28, 4, "6  Langevin = KL 的梯度流  dKL / dt = -I(rho)（定理 29.9）")
    return cv.render()


# ---------- ch29 block1：得分函数的解剖 ----------
def fig_score_anatomy() -> list[str]:
    ROWS, COLS = 38, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "得分函数 s(x) = grad log p(x)：一个对象，四种身份，三条几何事实")
    cv.text(2, 2, "四个身份（看清这四个，整章的动机就已经完整了）")
    cv.text(3, 4, "1  归一化常数的绝缘体   grad log p = grad log p_tilde - grad log Z")
    cv.text(4, 4, "                       而 grad log Z = 0（Z 与 x 无关）—— 可行性的起点")
    cv.text(5, 4, "2  力场                 s = -grad U，其中 U = -log p：Langevin 的漂移")
    cv.text(6, 4, "3  最优去噪器           E[x0 | xt] = xt + sigma_t^2 s_t(xt)（Tweedie）")
    cv.text(7, 4, "4  Fisher 信息          I(p) = E_p[ || s(X) ||^2 ]：KL 的下降速率")
    cv.text(9, 2, "几何事实一：真实得分一定是保守场，但学出来的不是")
    cv.text(10, 4, "由定义 s = grad(log p)，任何标量函数的梯度都无旋：d_i s_j = d_j s_i")
    cv.text(11, 4, "而网络参数化的 s_theta 不受此约束；多数实践干脆不约束，代价可接受")
    cv.text(13, 2, "几何事实二：多峰之间的平坦区是采样器的坟墓（一维双峰示意）")
    cv.text(14, 4, "        s:   -->  -->  <-    空    ->  <--  <--")
    cv.text(15, 4, "        p:      /\\                     /\\")
    cv.text(16, 4, "               /  \\                   /  \\")
    cv.text(17, 4, "        ______/    \\_________________/    \\______")
    cv.text(18, 4, "                    ^^^^^^^^^^^^^^^^^^^^^^^^")
    cv.text(19, 4, "                    谷底：s 约为 0，漂移消失，样本一旦进来就卡住")
    cv.text(20, 4, "与 26.3 的鞍点完全同源：那里 grad f = 0 让 GD 停滞，这里让 Langevin 停滞")
    cv.text(22, 2, "几何事实三：低密度区的得分既极大又最难估（这是必须加噪的根本原因）")
    cv.text(23, 4, "数据附近（峰上）   s 很小    只做微调，细节全靠这一带")
    cv.text(24, 4, "远离数据（尾部）   s 很大    强回拉力，但训练数据覆盖不到，误差最大")
    cv.text(25, 4, "而采样轨迹恰恰必须从尾部走向峰上 —— 于是 29.3.5 的多尺度成为必需")
    return cv.render()


# ---------- ch29 block2：得分匹配的三条路线 ----------
def fig_dsm_pipeline() -> list[str]:
    ROWS, COLS = 36, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "得分匹配的三条路线：一条死、一条贵、一条通（通的那条就是扩散模型的 loss）")
    cv.text(2, 2, "路线 1  显式得分匹配（ESM，朴素目标）  J = 0.5 E_p || s_theta - grad log p ||^2")
    cv.text(3, 4, "死结：grad log p 正是要学的东西，却出现在目标里 —— 循环依赖")
    cv.text(4, 4, "展开成三项后：0.5 E || s_theta ||^2 - E[s_theta^T grad log p] + const")
    cv.text(5, 4, "                这一项可算          这一项不可算（含未知的 grad log p）")
    cv.text(7, 2, "路线 2  隐式得分匹配（ISM，Hyvarinen 恒等式）：用分部积分把不可算项搬走")
    cv.text(8, 4, "E_p[s_theta^T grad log p] = -E_p[ div s_theta ]   （边界项假设消失）")
    cv.text(9, 4, "目标变成可算的  E_p[ 0.5 || s_theta ||^2 + div s_theta ]")
    cv.text(10, 4, "代价：div s_theta 精确算需要 d 次反向传播；Hutchinson 估计方差 O(d)")
    cv.text(11, 4, "结论：能用，但代价随维数线性上涨 —— d ~ 10^6 时不可接受")
    cv.text(13, 2, "路线 3  去噪得分匹配（DSM，通行做法）：先加噪，再回归（定理 29.3）")
    cv.text(14, 4, "加噪        xt = alpha_t x0 + sigma_t eps")
    cv.text(15, 4, "Tweedie     E[x0 | xt] = (xt + sigma_t^2 grad log p_t) / alpha_t")
    cv.text(16, 4, "等价性      || s_theta - grad log p_t ||^2")
    cv.text(17, 4, "          = || s_theta + (xt - x0) / sigma_t^2 ||^2 + const")
    cv.text(18, 4, "取 alpha_t = 1：就是回归噪声 eps / sigma_t，或等价地回归 x0")
    cv.text(19, 4, "好处：不需要任何未知量、不需要散度、无维数代价 —— 一个纯回归问题")
    cv.text(21, 2, "一个噪声尺度不够（29.3.5）：覆盖与精度不可兼得")
    cv.text(22, 4, "sigma 大   p_sigma 被抹平成近似高斯，处处有支撑 -> 覆盖好、细节丢")
    cv.text(23, 4, "sigma 小   p_sigma 保留细节，只在数据附近有支撑 -> 细节准、覆盖差")
    cv.text(24, 4, "把 sigma 展开成时间轴（多尺度）才能两全 —— 这就是扩散的时间维的来历")
    cv.text(26, 2, "一句话总结本节：训练扩散模型 = 训练一个去噪器 = 训练一个得分函数")
    return cv.render()


# ---------- ch29 block3：前向加噪与反向去噪 ----------
def fig_forward_reverse() -> list[str]:
    ROWS, COLS = 36, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "前向加噪与反向去噪：同一个 Fokker-Planck 方程，两个方向的读法")
    cv.text(2, 2, "前向（t: 0 -> T）：把数据淹成噪声，全程方程已知")
    cv.text(3, 4, "t = 0    p_0 = p_data                     高频细节完整")
    cv.text(4, 4, "t 增大   p_t = p_data 与 N(0, sigma_t^2) 卷积   高频先死（谱衰减）")
    cv.text(5, 4, "t = T    p_T 约为 N(0, I)                 已知分布，是采样器的唯一入口")
    cv.text(7, 2, "时间轴示意（上下两条箭头是同一族的 p_t，只是方向相反）")
    cv.text(8, 6, "数据 x_0  ==>  轻微噪声  ==>  中等噪声  ==>  ...  ==>  纯噪声 x_T")
    cv.text(9, 6, "         加噪         加噪                       （前向：已知，无参数）")
    cv.text(10, 6, "数据 x_0  <==  略去一点  <==  略去一点  <==  ...  <==  纯噪声 x_T")
    cv.text(11, 6, "         去噪         去噪                       （反向：学 s_theta）")
    cv.text(13, 2, "反向漂移 = 前向漂移 - g^2 乘以得分（定理 29.7）")
    cv.text(14, 4, "dX_rev = [ f(X, t) - g(t)^2 grad log p_t(X) ] dt + g(t) dB_rev")
    cv.text(15, 4, "第二项 -g^2 s 就是「逆着密度下降方向推」：把样本系统性地推回数据流形")
    cv.text(17, 2, "两种标准设计（前向过程的设计自由度只有两个标量函数）")
    cv.text(18, 4, "VP（方差保持）  f = -0.5 beta(t),  g = sqrt(beta(t))")
    cv.text(19, 4, "                alpha_t = exp(-0.5 积分 beta),  sigma_t^2 = 1 - alpha_t^2")
    cv.text(20, 4, "                终态恰好是 N(0, I)，方差恒为 1 —— DDPM 用的就是它")
    cv.text(21, 4, "VE（方差爆炸）  f = 0,  g = sqrt(d sigma^2 / dt),  alpha_t 恒为 1")
    cv.text(22, 4, "                终态是 N(0, sigma_T^2 I)，小噪声端更贴近真实数据")
    cv.text(24, 2, "加噪 = 与高斯卷积 = 频域乘一个衰减因子（与 27.4 的谱偏差同源）")
    cv.text(25, 4, "p_t 的傅里叶变换 = p_data 的傅里叶变换 乘以 exp(-sigma_t^2 ||k||^2 / 2)")
    cv.text(26, 4, "低频几乎不变、高频指数衰减 —— 采样顺序天然就是「先低频轮廓、后高频细节」")
    return cv.render()


# ---------- ch29 block4：SDE 与概率流 ODE ----------
def fig_probflow_vs_sde() -> list[str]:
    ROWS, COLS = 36, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "SDE 与概率流 ODE：同一族边缘分布 p_t，两条完全不同的路径")
    cv.text(2, 2, "反向 SDE（含噪声）                    概率流 ODE（无噪声）")
    cv.text(3, 4, "dx = [f - g^2 s] dt + g dB            dx = [f - 0.5 g^2 s] dt")
    cv.text(4, 4, "每步注入噪声                          每步只有确定性位移")
    cv.text(5, 4, "同一起点 -> 不同终点（随机）          同一起点 -> 唯一终点（确定）")
    cv.text(6, 4, "不可逆                                可逆（可编码、可算似然）")
    cv.text(7, 4, "噪声有自纠错作用（对得分误差鲁棒）    误差沿轨迹被放大（无自纠错）")
    cv.text(8, 4, "用途：祖先采样、需要样本多样性        用途：DDIM、一致性、可逆编辑")
    cv.text(10, 2, "路径示意（一维，同一个初始 x_T，同一族边缘）")
    cv.text(11, 6, "SDE:   x_T  ~>~>~>  抖动上升  ~>~>~>  抖动  ~>~>~>  x_0（随机落点）")
    cv.text(12, 6, "ODE:   x_T  --->    平滑上升  --->    平滑  --->    x_0（唯一落点）")
    cv.text(14, 2, "两者共享：同一族 p_t、同一个得分 s、同一个定理 29.7 / 29.8")
    cv.text(15, 4, "差别的唯一来源：把扩散项 g^2 算进漂移（系数 0.5）还是单列（系数 1）")
    cv.text(17, 2, "为什么「往漂移里塞多少、往扩散里塞多少」是自由的")
    cv.text(18, 4, "在连续时间下这等价于选择离散化的插值点（回到 9.4.2 的 Itô 积分三步走）")
    cv.text(19, 4, "于是同一个 p_t 可以由一整族过程实现 —— 这就是 DDIM、流匹配、")
    cv.text(20, 4, "一致性模型的共同祖先，也是「采样器家族」全部自由度的来源")
    cv.text(22, 2, "一个必须避免的误解：ODE 并不比 SDE「更好」")
    cv.text(23, 4, "ODE 少了噪声，就少了「把轨迹推离局部错误」的机制；两者是取舍不是优劣")
    cv.text(24, 4, "实践常用组合：早期用 SDE（探索、纠错），后期用 ODE（精细、无抖动）")
    return cv.render()


# ---------- ch29 block5：Wasserstein 梯度流与 JKO ----------
def fig_wasserstein_flow() -> list[str]:
    ROWS, COLS = 38, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Langevin 采样 = 在分布空间用 W_2 度量做梯度下降（与 25 章逐项对照）")
    cv.text(2, 2, "项目          参数空间（第 25 章）        分布空间（本章）")
    cv.text(3, 4, "变量          theta in R^p                 测度 rho")
    cv.text(4, 4, "度量          欧氏（delta_ij）             Wasserstein-2")
    cv.text(5, 4, "目标          f(theta)                     KL(rho || p)")
    cv.text(6, 4, "下降方程      dtheta = -grad f dt          drho = div(rho grad log(rho / p))")
    cv.text(7, 4, "随机实现      梯度下降                     Langevin 采样")
    cv.text(8, 4, "耗散率        df / dt = -|| grad f ||^2    dKL / dt = -I(rho || p)")
    cv.text(9, 4, "凸性常数      mu（强凸）                   alpha（LSI 常数）")
    cv.text(10, 4, "难问题的名字  条件数 kappa = L / mu        混合时间 ~ 1 / alpha")
    cv.text(12, 2, "JKO 格式：把隐式欧拉搬到测度空间（它就是 prox 的无穷维版本）")
    cv.text(13, 4, "rho_{k+1} = argmin_rho { W_2^2(rho_k, rho) / (2 Delta) + KL(rho || p) }")
    cv.text(14, 4, "与 25.5 的近端算子逐字对应（其实只换了两个东西）：")
    cv.text(15, 4, "prox_{Delta f}(z) = argmin_theta { || theta - z ||^2 / (2 Delta) + f(theta) }")
    cv.text(16, 4, "把 || theta - z ||^2 换成 W_2^2(rho_k, rho)，把 f 换成 KL —— 就这两个替换")
    cv.text(18, 2, "凸性在测度空间的三种推广（与 25 章同一条链）")
    cv.text(19, 4, "对数凹（p）  ->  LSI 常数 alpha  ->  KL 以 exp(-2 alpha t) 衰减")
    cv.text(20, 4, "25 章的版本：强凸 mu  ->  唯一最优  ->  线性收敛")
    cv.text(21, 4, "两边的「非凸」账单也是同一张：多峰势垒 / 平坦方向，只是换了名字")
    cv.text(23, 2, "一句话：采样不是数值分析问题，它是分布上的优化问题")
    cv.text(24, 4, "于是 25 章关于凸性、近端、IMPLICIT 格式的全部直觉都可以平移过来")
    return cv.render()


# ---------- ch29 block6：采样器光谱 ----------
def fig_sampler_spectrum() -> list[str]:
    ROWS, COLS = 34, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "采样器光谱：它们不是不同的模型，而是同一条 ODE / SDE 的不同数值解法")
    cv.text(2, 2, "采样器                     求解对象               随机性    典型步数")
    cv.text(3, 4, "Euler-Maruyama / 祖先      反向 SDE               全量      500 - 1000")
    cv.text(4, 4, "DDIM（eta 可调）           概率流 ODE（eta = 0）  可调      20 - 100")
    cv.text(5, 4, "Heun / DPM-Solver          概率流 ODE，2 - 3 阶   无        10 - 50")
    cv.text(6, 4, "一致性模型                 ODE 的解算子（flow map）  无      1 - 2")
    cv.text(7, 4, "蒸馏 / 对抗蒸馏            学生网络逼近老师轨迹   视情况    1 - 4")
    cv.text(9, 2, "规律：从上往下，被「压缩」的东西越来越厉害，步数下降一个量级")
    cv.text(10, 4, "每上一层（SDE -> ODE）、每换一次求解器（一阶 -> 高阶）、每加一层蒸馏")
    cv.text(11, 4, "代价都是「需要更强的理论保证」：稳定域、误差界、蒸馏偏差")
    cv.text(13, 2, "设计原则（29.7.1 的取舍）：随机性用来纠错与探索，确定性用来精细收尾")
    cv.text(14, 4, "早期用 SDE、后期用 ODE —— 与 26.6.2 的「先粗后细 = 温度调度」同一策略")
    cv.text(16, 2, "有理论出处的几条工程 trick（每条都指到具体定理）")
    cv.text(17, 4, "lambda(t) 加权        不同噪声尺度的误差分布不均匀（29.9.3）")
    cv.text(18, 4, "t 的采样分布          多尺度的覆盖与精度张力（29.3.5）")
    cv.text(19, 4, "分类器自由引导 CFG    构造一个被修改过的得分（分布被锐化，gamma 太大有害）")
    cv.text(20, 4, "噪声表 beta schedule  让信噪比沿时间均匀（29.5.2 的 alpha_t / sigma_t 设计）")
    cv.text(22, 2, "与第 32 章的接口：换 ODE 求解器就是换采样器")
    cv.text(23, 4, "稳定性域、局部误差阶、刚性问题 —— 全是同一套数值积分语言，只是时间被重标定")
    return cv.render()


# ---------- ch30 block0：本章的三条路 ----------
def fig_contour_map() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "第 5 章的遗产：一次成型的围道（留数五种算法 + 五类模板 + 七类实积分套路）")
    cv.text(2, 2, "本章走完剩下的三条路，每条对应一种「围道不再听话」的局面")
    cv.text(4, 2, "第 1 条   围道可以自由变形   ->   30.2 变形原理 + 30.3 辐角原理")
    cv.text(5, 6, "收益：可以把围道拖到任何让被积函数变简单的位置（这是唯一的自由度）")
    cv.text(6, 6, "代价：每拖一次都要交代两件事 —— 绕数变了吗？跨过极点了吗？")
    cv.text(8, 2, "第 2 条   被积函数是多值的   ->   30.4 分支切与割缝 + 30.5 特殊函数围道")
    cv.text(9, 6, "收益：割缝围道把发散的实积分搬回复平面，合法地给出定义（Pochhammer）")
    cv.text(10, 6, "代价：每次都要从 arg z 的区间重推上下沿的取值差，不能凭记忆")
    cv.text(12, 2, "第 3 条   只求量级不求闭式   ->   30.6 鞍点法与最速下降")
    cv.text(13, 6, "收益：围道自己收缩到鞍点附近的一个微元，问题变成一次局部展开")
    cv.text(14, 6, "代价：必须交代相位与主鞍点，跨过 Stokes 线就得换公式")
    cv.text(16, 2, "主线只有一句话（本章的全部技术风险都从这一句来）")
    cv.text(17, 6, "围道是自由的探针：能拖、能数、能贴、能定义、能自己收缩")
    cv.text(18, 6, "唯一的代价：每一次行动都要交代「绕数、极点、相位」这三件事")
    cv.text(20, 2, "与相邻章的分工（本章只做复变这一支，不抢别人的活）")
    cv.text(21, 4, "第 9 章已讲 SDE 与随机分析：Itô、Fokker-Planck、Langevin、Girsanov")
    cv.text(22, 4, "第 31 章给表（特殊函数与积分清单）；第 33 章给实轴渐近与不等式")
    return cv.render()


# ---------- ch30 block1：辐角原理 ----------
def fig_argument_principle() -> list[str]:
    ROWS, COLS = 28, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "辐角原理：把「求解 f(z) = 0」换成「画一条曲线、数它绕原点几圈」")
    cv.text(2, 3, "z 平面（围道所在）                    w 平面（像曲线所在）")
    cv.text(3, 3, "+---------------------+               +---------------------+")
    cv.text(4, 3, "|        gamma        |               |       f(gamma)      |")
    cv.text(5, 3, "|     （简单闭曲线）  |  ---- f ----> |      （像曲线）     |")
    cv.text(6, 3, "+---------------------+               +---------------------+")
    cv.text(7, 5, "数 gamma 内部的 Z - P                 数 f(gamma) 绕原点 0 的圈数")
    cv.text(8, 5, "（零点数减极点数，按重数计）          （这恰好就是绕数 Ind 的定义）")
    cv.text(10, 2, "公式一行就够（定理 30.6 辐角原理的完整陈述）")
    cv.text(11, 6, "(1 / 2 pi i) 沿 gamma 积分 f' / f  =  Z - P  =  Ind_{f(gamma)}(0)")
    cv.text(13, 2, "为什么这个恒等式成立（30.3.1 的局部结构是关键）")
    cv.text(14, 6, "m 阶零点   使 f' / f 得到一个留数为 +m 的一阶极点")
    cv.text(15, 6, "n 阶极点   使 f' / f 得到一个留数为 -n 的一阶极点")
    cv.text(16, 6, "其余点处 f' / f 解析，于是留数定理的右端只剩 Z - P 这一项")
    cv.text(18, 2, "三个后代（按它们在书里出现的先后顺序各自展开）")
    cv.text(19, 6, "1  Rouché 定理（定理 30.7）：若在 gamma 上 |g| < |f|，则零点数不变")
    cv.text(20, 6, "2  Nyquist 判据（定理 30.8）：把 1 + L 代进去，得到控制论稳定判据")
    cv.text(21, 6, "3  根轨迹（30.7.2）：辐角条件直接给出轨迹所在的曲线族")
    cv.text(23, 2, "使用前必须核对的两件事（否则结论会静默地错）")
    cv.text(24, 6, "gamma 上不能有零点或极点（否则要缩进绕开，见 5.6.6 的小圆弧技术）")
    cv.text(25, 6, "辐角的跟踪必须连续（沿 gamma 走一圈，中途不允许跳变）")
    return cv.render()


# ---------- ch30 block2：Nyquist 判据 ----------
def fig_nyquist_map() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Nyquist 判据的几何：整张图只用来回答一个问题 —— 绕不绕 -1")
    cv.text(2, 3, "s 平面（围道的来源）                     w 平面（像曲线所在）")
    cv.text(3, 3, "      Im                                       Im")
    cv.text(4, 3, "      |    Nyquist 围道                        |")
    cv.text(5, 3, "      |    （虚轴 + 右半大圆，                  |      +--------+")
    cv.text(6, 3, "      |     顺时针包住右半平面）               |      |   -1   |")
    cv.text(7, 3, "      |                                        |      +--------+")
    cv.text(8, 3, "------+--------> Re     ---- L ---->   --------+------------------> Re")
    cv.text(9, 3, "      |                                        |    <-- 只看这个点")
    cv.text(11, 3, "围道上的极点要缩进绕开（例 30.4）      像曲线绕 -1 的净圈数记为 N")
    cv.text(13, 2, "判据（定理 30.8）：Z_cl = P_ol - N，三个符号的含义如下")
    cv.text(14, 6, "P_ol   开环在右半平面的极点数（已知量：由对象与控制器的结构决定）")
    cv.text(15, 6, "N      像曲线 L(gamma_N) 绕 -1 点的逆时针净圈数")
    cv.text(16, 6, "Z_cl   闭环在右半平面的极点数（正是我们想求的那个量）")
    cv.text(17, 6, "闭环稳定  <=>  Z_cl = 0  <=>  N = P_ol（这就是判据的全部内容）")
    cv.text(19, 2, "为什么偏偏看 -1（这是判据全部直觉的来源所在）")
    cv.text(20, 6, "L(s) = -1  <=>  1 + L(s) = 0  <=>  闭环特征方程成立")
    cv.text(21, 6, "所以 -1 是「临界点」：像曲线到它的距离就是增益裕度")
    cv.text(22, 6, "像曲线穿过单位圆时的相位就是相位裕度（工程最常用的两个数）")
    cv.text(24, 2, "方向约定警告（这是各家教科书符号不一致的根源）")
    cv.text(25, 6, "Nyquist 围道是顺时针包住右半平面的，与「逆时针为正」的惯例相反")
    cv.text(26, 6, "所以永远用代数判据 Routh 回验一次（例 30.4 第六步的做法）")
    return cv.render()


# ---------- ch30 block3：Pochhammer 围道 ----------
def fig_pochhammer() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Pochhammer 围道：参数越界、实轴积分发散时的救场工具")
    cv.text(2, 2, "为什么需要它（先把问题的形状彻底摆清楚再动手）")
    cv.text(3, 6, "例 30.5 的公式只在 0 < a < 1 时成立（因为两端圆才归零）")
    cv.text(4, 6, "但 pi / sin(pi a) 在整个 a 不为整数处都有定义，说明一定能延拓")
    cv.text(5, 6, "矛盾 => 让围道「只在 0 与 1 之间绕圈、不经过奇端点」")
    cv.text(7, 2, "形状（双割缝路径，绕两个分支点走，绝不碰端点）")
    cv.text(8, 4, "      Im    （复平面：横向是实轴，纵向是虚轴）")
    cv.text(9, 4, "      |       上侧      +--------+      左段：沿割上侧向右走")
    cv.text(10, 4, "      |    ------->-----|        |      绕 t = 1 逆时针转一圈")
    cv.text(11, 4, "      |    0 ----------+--------+--- 1 ------------>  Re")
    cv.text(12, 4, "      |    -------<-----|        |      右段：沿割下侧向左返回")
    cv.text(13, 4, "      |       下侧      +--------+      两段之差就是积分的核")
    cv.text(14, 4, "      |    起点与终点都落在 0 附近，最后再绕 t = 0 逆时针一圈")
    cv.text(16, 2, "它给出什么（定理 30.9：Beta 函数的 Pochhammer 表示）")
    cv.text(17, 6, "绕一个分支点就贡献一个 (1 - e^(2 pi i ·)) 因子，这是全部结构")
    cv.text(18, 6, "把 B(a, b) 从「0 < a, b 的实积分」解析延拓到复参数")
    cv.text(19, 6, "由此证明 pi / sin(pi a) 在整个 a 不为整数处都成立")
    cv.text(21, 2, "它在体系中的地位（为什么值得为它单独开一节）")
    cv.text(22, 6, "它是 Gamma 的 Hankel 表示（定理 30.11）的原型")
    cv.text(23, 6, "「绕分支点的围道」= 处理多值性的通用模板，30.5 全靠它")
    cv.text(24, 6, "代价：绕数与归一约定各家写法不同，正文给了三条等价形式")
    return cv.render()


# ---------- ch30 block4：分支切与钥匙孔 ----------
def fig_branch_cut() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "分支切与钥匙孔围道：绕开多值性的标准做法（5.7.4 的系统升级）")
    cv.text(2, 4, "      Im    （正实轴被划为分支切，arg z 的取值范围是 (0, 2 pi)）")
    cv.text(3, 4, "      |                                ________________________")
    cv.text(4, 4, "      |                            ___/                        大圆 R -> 无穷")
    cv.text(5, 4, "      |                           |     归零条件：a < 1（衰减指数大于 1）")
    cv.text(6, 4, "      |                           |     <--- 上沿：arg z = 0")
    cv.text(7, 4, "------+---------------------------+------------------------------------> Re")
    cv.text(8, 4, "      |                           |     <--- 下沿：arg z = 2 pi")
    cv.text(9, 4, "      |                           |___     （小圆接在这里，半径 eps）")
    cv.text(10, 4, "      |                               +----------------   两端小圆 eps -> 0")
    cv.text(11, 4, "      |                               归零条件：a > 0（增长指数小于 1）")
    cv.text(12, 4, "      |    被围住的极点：z = -1（例 30.5 里钥匙孔内的唯一极点）")
    cv.text(14, 2, "上下沿之差 = 积分的核（本节唯一的算术，也是唯一易错处）")
    cv.text(15, 6, "幂函数 z^(a-1)    差值 = (1 - e^(2 pi i (a-1))) 乘 r^(a-1)")
    cv.text(16, 6, "对数   log z      差值 = 2 pi i（与 r 无关，所以取 log 得到常数核）")
    cv.text(17, 6, "对数平方 log^2 z  差值 = 4 pi i ln r - 4 pi^2（同时给出两项）")
    cv.text(19, 2, "四步法（照做即可，千万不要凭记忆，这是唯一的纪律）")
    cv.text(20, 6, "1  选分支切：让它贴着目标积分区间（通常是正实轴）")
    cv.text(21, 6, "2  造钥匙孔：上沿、大圆、下沿、小圆，按逆时针顺序走")
    cv.text(22, 6, "3  算两侧之差：从 arg z 的区间重推，注意下沿是反向走的")
    cv.text(23, 6, "4  验证两圆归零：剩下的就是留数之和（例 30.5 得 pi / sin(pi a)）")
    cv.text(25, 2, "一句话总结（把上面的全部操作压缩成一句话来记）")
    cv.text(26, 6, "分支切把「多值」变成「两条单值路径」，两者之差就是积分的核")
    cv.text(27, 6, "若参数越出两圆归零的区间，就改用 Pochhammer 围道（见 30.4.7）")
    return cv.render()


# ---------- ch30 block5：特殊函数积分表示 ----------
def fig_special_fn_bridge() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "特殊函数为什么需要积分表示：三个不可替代的作用")
    cv.text(2, 2, "作用一   提供解析延拓（在实轴积分发散处仍然有定义）")
    cv.text(3, 6, "Gamma(z) = 积分 t^(z-1) e^(-t) dt 只在 Re z > 0 收敛")
    cv.text(4, 6, "Hankel 围道版本对整个复平面有效（定理 30.11）")
    cv.text(5, 6, "Schläfli 积分（定理 30.10）是同一思想的另一种写法")
    cv.text(7, 2, "作用二   提供渐近（大参数行为几乎全从这里来）")
    cv.text(8, 6, "大参数行为几乎全部由「积分表示 + 鞍点法」得到")
    cv.text(9, 6, "Stirling 公式（例 30.8）与 Airy 渐近（例 30.9）都是这样来的")
    cv.text(11, 2, "作用三   提供递推与恒等式（可以完全不动手做积分）")
    cv.text(12, 6, "分部积分、换元、围道变形，全部直接在积分上操作")
    cv.text(13, 6, "Bessel 母函数推到 Poisson 积分（推论 30.14）只需一次参数化")
    cv.text(15, 2, "本章的四台「造机器」工具（30.5 逐一给出构造）")
    cv.text(16, 6, "Schläfli 积分     1 / Gamma(z) 的 Hankel 型围道（定理 30.10）")
    cv.text(17, 6, "Hankel 围道       Gamma 的复平面表示（定理 30.11）")
    cv.text(18, 6, "Bessel 母函数     Laurent 系数 = 围道积分（推论 30.13）")
    cv.text(19, 6, "Poisson 形式      取实部、用偶性（推论 30.14）")
    cv.text(21, 2, "与第 31 章的分工（同一台机器，前后两种用法）")
    cv.text(22, 6, "本章 = 怎么造（方法：围道表示 + 系数提取 + 鞍点读数）")
    cv.text(23, 6, "第 31 章 = 有哪些（清单：积分表示 + 成立条件 + 速查表）")
    cv.text(24, 6, "两者的接口正好落在鞍点法：造出来的积分表示要在大参数下读渐近")
    return cv.render()


# ---------- ch30 block6：鞍点与最速下降 ----------
def fig_saddle_path() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "鞍点与最速下降路径：围道自己找到了最好走的那条线")
    cv.text(2, 2, "Re h 的地形（在鞍点 z0 附近，二维调和函数只能是鞍形）")
    cv.text(4, 6, "            上坡                         上坡（Re h 极大方向）")
    cv.text(5, 6, "             /  \\                     /  \\        等高线")
    cv.text(6, 6, "            /    \\                   /    \\       Re h = 常数")
    cv.text(7, 6, "  ---------*------*-----------------*------*-----------------")
    cv.text(8, 6, "            \\    /                   \\    /       水平直线")
    cv.text(9, 6, "             \\  /                     \\  /        Im h = 常数")
    cv.text(10, 6, "            下坡                        下坡（Re h 极小方向）")
    cv.text(12, 4, "水平直线 = 最速下降路径（相位不动，所以能做高斯近似）")
    cv.text(13, 4, "曲线 = 等高线（模不变，所以不是我们要走的路径）")
    cv.text(15, 2, "四件事一起看（这四条合起来就是鞍点法的全部原理）")
    cv.text(16, 6, "1  h'(z0) = 0             鞍点：h 的驻点，积分贡献的集中处")
    cv.text(17, 6, "2  最大模原理              Re h 无极值 => 「峰」只能是鞍形")
    cv.text(18, 6, "3  沿 Im h = 常数的路径    相位不动、模最快下降 => 可做高斯近似")
    cv.text(19, 6, "4  方向由 h''(z0) 决定     角度 alpha = (pi - arg h'') / 2")
    cv.text(21, 2, "主定理（定理 30.17 的最速下降公式，全章核心）")
    cv.text(22, 6, "积分_C e^(N h(z)) dz = e^(N h(z0)) 乘 e^(i alpha) 乘 sqrt(2 pi / (N |h''(z0)|))")
    cv.text(23, 6, "误差 O(1 / N)；前提是围道能合法地变形到最速下降路径")
    cv.text(25, 2, "与 Laplace 方法逐项对照（结构完全一样，只差一个相位）")
    cv.text(26, 6, "Laplace：找 f 的最小值点（实轴）；最速下降：找 h 的鞍点（复平面）")
    cv.text(27, 6, "唯一差别：复平面多出一个相位因子 e^(i alpha)，来自 dz = e^(i alpha) du")
    return cv.render()


# ---------- ch30 block7：Stirling 的推导节奏 ----------
def fig_stirling_saddle() -> list[str]:
    ROWS, COLS = 30, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Stirling 公式的推导节奏（记住方法，比记住结果重要得多）")
    cv.text(2, 2, "起点   N! = 积分_0^无穷 t^N e^(-t) dt = 积分 e^(N ln t - t) dt")
    cv.text(3, 6, "被积函数已经是「指数上带 N」的形状，这正是 Laplace 方法的入口")
    cv.text(5, 2, "第一步   写成指数形式，把 N 提成统一的尺度（这一步是形式上的）")
    cv.text(6, 6, "指数 = N ln t - t，N 已经显式地站在指数上，不需要额外操作")
    cv.text(8, 2, "第二步   找驻点并换元，把驻点搬到固定位置（最关键的一步）")
    cv.text(9, 6, "g(t) = N ln t - t，g'(t) = N / t - 1 = 0  =>  t = N")
    cv.text(10, 6, "换元 t = N s（这一步让公式只依赖 N，不依赖「N 藏在哪」）")
    cv.text(11, 6, "=>  N! = N^(N+1) 乘 积分_0^无穷 e^(N (ln s - s)) ds")
    cv.text(13, 2, "第三步   应用 Laplace 方法（此时 f(s) = s - ln s）")
    cv.text(14, 6, "f'(s) = 1 - 1 / s = 0  =>  s0 = 1；f''(s0) = 1")
    cv.text(15, 6, "积分 = e^(-N) 乘 sqrt(2 pi / N)（定理 30.15 的直接代入）")
    cv.text(16, 6, "合并 => N! ~ sqrt(2 pi N) 乘 (N / e)^N，即 Stirling 公式")
    cv.text(18, 2, "数值校验（N = 10 时量级已经对了，系数也几乎对）")
    cv.text(19, 6, "公式给 3.599e6；真值 10! = 3.6288e6；相对误差约 0.8%")
    cv.text(21, 2, "为什么还要复版（这就是最速下降必须存在的理由）")
    cv.text(22, 6, "被积函数带振荡相位时，实轴上根本没有极大值可以找")
    cv.text(23, 6, "=> 必须走复围道，用定理 30.17（Airy 函数是标准例子，例 30.9）")
    cv.text(25, 2, "三步节奏的推广（几乎所有渐近问题都逃不出这三步）")
    cv.text(26, 6, "写成 e^(N ·) -> 找驻点 -> 换元把驻点搬到固定位置 -> 二阶展开")
    return cv.render()


# ---------- ch30 block8：渐近方法三兄弟 ----------
def fig_asymptotic_family() -> list[str]:
    ROWS, COLS = 32, 96
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "渐近方法三兄弟：同一套「定位 + 二阶展开 + 高斯」，三种驻点形态")
    cv.text(2, 2, "兄弟一   Laplace 方法（实轴，处理实指数峰，见 30.6.2）")
    cv.text(3, 6, "积分 e^(-N f) g dx，驻点满足 f' = 0 且 f'' > 0")
    cv.text(4, 6, "=> g(x0) e^(-N f(x0)) 乘 sqrt(2 pi / (N f''(x0)))")
    cv.text(5, 6, "形象：实指数峰（Peak），峰越陡就越只看得见 x0 附近")
    cv.text(7, 2, "兄弟二   最速下降（复平面，处理复鞍点，见 30.6.4）")
    cv.text(8, 6, "积分_C e^(N h) dz，鞍点满足 h' = 0（Re h 无极值，只能是鞍形）")
    cv.text(9, 6, "=> e^(N h(z0)) 乘 e^(i alpha) 乘 sqrt(2 pi / (N |h''(z0)|))")
    cv.text(10, 6, "形象：复鞍点（Saddle），沿 Im h = 常数的路径走")
    cv.text(12, 2, "兄弟三   驻相法（纯相位，处理振荡积分，见 30.6.7）")
    cv.text(13, 6, "积分 g e^(i N phi) dx，驻点满足 phi' = 0")
    cv.text(14, 6, "=> g(x0) e^(i N phi(x0)) e^(正负 i pi / 4) 乘 sqrt(2 pi / (N |phi''(x0)|))")
    cv.text(15, 6, "形象：相位驻点（Stationary phase），振荡停下来的地方")
    cv.text(17, 2, "三者的共同结构（学会一个，另外两个几乎是免费的）")
    cv.text(18, 6, "定位驻点  ->  二阶展开  ->  高斯积分  =>  主项 加 O(1 / N)")
    cv.text(19, 6, "差别只在「驻点附近被积函数长什么样」：实指数峰 / 复鞍点 / 纯相位")
    cv.text(21, 2, "三条使用纪律（更细的版本见 30.6.8 的五条陷阱）")
    cv.text(22, 6, "1  多个鞍点时只留 Re h 最大的（主鞍点），其余贡献指数小")
    cv.text(23, 6, "2  跨 Stokes 线时次主导项系数跳变，同一个公式要换形式")
    cv.text(24, 6, "3  驻点在端点时结果除以 2；鞍点合并时公式失效（需均匀渐近）")
    return cv.render()


# ---------- ch31 block0：超几何森林（汇合树） ----------
def fig_special_fn_forest() -> list[str]:
    ROWS, COLS = 30, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "超几何森林：一个家族的三层，靠「参数推到无穷」向下汇合")
    cv.text(2, 2, "第 1 层   _2F_1(a, b; c; z)    三个奇点 0, 1, 无穷 -> 收敛半径 1，圆外必须换形式")
    cv.text(3, 8, "后代：Legendre / Chebyshev / 椭圆积分 K, E / 不完全 Beta / Jacobi 族")
    cv.text(4, 8, "识别信号：出现 sqrt(1 - z^2)，或问题的几何本身是椭圆型的")
    cv.text(6, 12, "|   汇合：b -> 无穷，同时 z -> z / b（把奇点 1 与无穷并成一个）")
    cv.text(7, 12, "v   含义：两奇点合并后解族下落到合流层（Bessel 就是这么掉出来的）")
    cv.text(10, 2, "第 2 层   _1F_1(a; c; z)       两个奇点 0, 无穷 -> 全平面整函数（Kummer）")
    cv.text(11, 8, "后代：erf / 不完全 Gamma / Laguerre / Hermite / 抛物柱 / Whittaker")
    cv.text(12, 8, "识别信号：出现 exp(-z^2)，或问题是高斯型的尾概率")
    cv.text(13, 12, "|   汇合：a -> 无穷，同时 z -> z / a（把奇点 0 与无穷并成一个）")
    cv.text(14, 12, "v   含义：再并掉一个，只剩一个奇点 -> 整函数，代价是丢掉初等性")
    cv.text(18, 2, "第 3 层   _0F_1(; c; z)        只剩一个奇点 -> 整函数（Bessel 层）")
    cv.text(19, 8, "后代：J_nu / I_nu / Airy / 球 Bessel / Kelvin 函数")
    cv.text(20, 8, "识别信号：出现 sin z / z，或问题是柱对称的模式分解")
    cv.text(22, 2, "三条使用判据（先定层次，再定具体函数：层次决定了能用的递推与渐近）")
    cv.text(23, 6, "1   根号里是最高次    ->   _2F_1 层（椭圆几何、Legendre、Chebyshev）")
    cv.text(24, 6, "2   指数里是最高次    ->   _1F_1 层（高斯尾、误差函数、Laguerre）")
    cv.text(25, 6, "3   分母里是最高次    ->   _0F_1 层（Bessel、柱对称、Airy 转折）")
    cv.text(27, 2, "反向读法：第 3 层的函数都是第 1 层的极限，判据是「参数能否被推到无穷」")
    cv.text(28, 6, "例：J_nu 就是 _2F_1 在 a -> 无穷时剩下的残骸（见例 31.2 的两级汇合）")
    return cv.render()


# ---------- ch31 block1：Gamma 家族谱系 ----------
def fig_gamma_family() -> list[str]:
    ROWS, COLS = 32, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Gamma 家族谱系：一个函数如何繁衍出一棵覆盖半个应用数学的树")
    cv.text(2, 2, "根：Gamma(z) —— 五种面孔（积分 / 递推 / Weierstrass 乘积 / Hankel 围道 / Euler 极限）")
    cv.text(4, 4, "取对数 ------------->  ln Gamma(z)（大参数计算的唯一稳妥形式）")
    cv.text(5, 10, "求导 ----------->  psi(z) = (ln Gamma) prime，唯一正零点 1.46163...")
    cv.text(6, 10, "求导 m 次 ------>  psi^(m)(z) = (-1)^(m+1) m! zeta(m+1, z)（接第 5 章 5.7.7）")
    cv.text(7, 10, "渐近 ----------->  Stirling 级数（含 1/(12z)、-1/(360z^3) 修正）")
    cv.text(9, 4, "截断积分上限 ------->  不完全 Gamma（阈值问题的数学名字）")
    cv.text(10, 10, "整数 s = n ------>  指数和（(n-1)! exp(-x) 乘 sum x^k / k!）")
    cv.text(11, 10, "半整数 s = n + 1/2 ->  erfc（Gamma(1/2, x) = sqrt(pi) erfc(sqrt(x))）")
    cv.text(12, 10, "正则化 -------->  P(s,x) 与 Q(s,x)（概率论里出镜率最高的特殊函数）")
    cv.text(14, 4, "造比值 ----------->  Beta 函数 B(a,b) = Gamma(a) Gamma(b) / Gamma(a+b)")
    cv.text(15, 10, "截断积分 ------>  不完全 Beta（Student t、F 分布的尾部概率）")
    cv.text(16, 10, "多元推广 ------>  Gamma_p(a)（Wishart、Dirichlet 的归一化常数）")
    cv.text(18, 2, "三条「看起来不像、其实是同一件事」的等式（记住它们能省掉半章篇幅）")
    cv.text(19, 6, "(1)  erf(z) = (2z / sqrt(pi)) 乘 _1F_1(1/2; 3/2; -z^2)")
    cv.text(20, 6, "(2)  Gamma(1/2, x) = sqrt(pi) 乘 erfc(sqrt(x))")
    cv.text(21, 6, "(3)  Poisson 累积 sum_{k<=n} exp(-lambda) lambda^k / k! = Q(n+1, lambda)")
    cv.text(23, 2, "三个必须知道的事实（每一条都能避免一类真实的数值事故）")
    cv.text(24, 6, "1   Gamma(200) 约 1e372，双精度直接溢出 -> 一切大参数都在对数域算")
    cv.text(25, 6, "2   Gamma 没有零点、极点在 0, -1, -2, ...，留数 (-1)^n / n!（来自乘积定义）")
    cv.text(26, 6, "3   反射公式只在两个参数互补时有用（Gamma(0.3) 单用是没法用反射的）")
    cv.text(28, 2, "一条跨卷的连接：psi^(m)(z) = (-1)^(m+1) m! zeta(m+1, z)")
    cv.text(29, 6, "含义：一切 sum (n+z)^(-s) 型求和都可以翻译成 psi，然后调用现成高精度实现")
    cv.text(30, 6, "例：sum 1/(n+1/2)^2 = psi prime(1/2) = pi^2 / 2")
    return cv.render()


# ---------- ch31 block2：不完全 Gamma 与七个分布 ----------
def fig_incomplete_gamma_map() -> list[str]:
    ROWS, COLS = 32, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "不完全 Gamma 是概率论的通用货币：一个 Q(s,x) 兑换七个分布")
    cv.text(2, 2, "      Q(s, x) = Gamma(s, x) / Gamma(s)      （正则化上不完全 Gamma）")
    cv.text(4, 2, "概率对象                              换参数                       取哪个")
    cv.text(5, 2, "----------------------------------------------------------------------------")
    cv.text(6, 2, "卡方检验 p 值（上尾）    chi^2(nu) 的上尾          s = nu/2,  x = stat/2")
    cv.text(7, 2, "卡方置信下尾             chi^2(nu) 的下尾          s = nu/2,  x = stat/2    (用 P)")
    cv.text(8, 2, "Gamma 分布 CDF           Gamma(alpha, beta)        s = alpha, x = x 乘 beta")
    cv.text(9, 2, "Poisson 累积概率         sum_{k<=n} exp(-l) l^k/k! s = n+1,  x = lambda")
    cv.text(10, 2, "正态上尾                 P[Z > t]                 s = 1/2,  x = t^2 / 2")
    cv.text(11, 2, "指数生存函数             exp(-lambda x)            s = 1,    x = lambda x")
    cv.text(12, 2, "Rayleigh 分布 CDF        s = 1,  x = r^2 / (2 sigma^2)")
    cv.text(13, 2, "Wishart 归一化           Gamma_p(n/2)              每加一维多一个 Gamma 因子")
    cv.text(15, 2, "两张手算的对照表（chi^2 检验，p = 0.05 的临界值）")
    cv.text(16, 6, "nu = 4：s = 2, x = 4.744，Q = exp(-4.744) 乘 (1 + 4.744) = 0.04993")
    cv.text(17, 6, "nu = 2：s = 1, Q(1,x) = exp(-x)，所以 p 值就是 exp(-stat/2) = 0.0500")
    cv.text(18, 6, "结论：nu = 2 的 p 值公式简单到可以背下来（这正是定理 31.6(c) 的直接后果）")
    cv.text(20, 2, "算法判据（这是 31.8.6 实施清单里最常用的一条）")
    cv.text(21, 6, "第一步永远是：先比较 x 与 s + 1 的大小（这一步决定级数还是连分式）")
    cv.text(22, 6, "x < s + 1  ->  用级数（Picard 迭代，收敛快且无相消）")
    cv.text(23, 6, "x > s + 1  ->  用连分式（Lentz 算法，避免尾部相消）")
    cv.text(24, 6, "绝对不要用 1 - P 去反推 Q（尾部时相消会吞掉全部有效数字）")
    cv.text(26, 2, "为什么值得记住这张表：学会算一个 Q，就同时会算了七个分布的尾部概率")
    cv.text(27, 6, "这七个分布在书里分散在第 7、8、20、28 章，但它们共享同一个内核")
    return cv.render()


# ---------- ch31 block3：erfc 的算法分区 ----------
def fig_erf_uniform() -> list[str]:
    ROWS, COLS = 34, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "erfc(x) 的算法分区：同一函数、三个区域、三套公式（数值纪律的样板）")
    cv.text(2, 2, "区域一   x < 1        Taylor 级数（交错项小，直接算就准）")
    cv.text(3, 8, "erf(x) = (2 / sqrt(pi)) 乘 sum (-1)^n x^(2n+1) / (n! (2n+1))")
    cv.text(4, 8, "可以用的理由：x 小则项快速衰减，交错相消不严重")
    cv.text(6, 2, "区域二   1 <= x < 4   连分式（这里没有交错相消）")
    cv.text(7, 8, "erfc(x) = exp(-x^2) / sqrt(pi) 乘 1 / (x + (1/2)/(x + 1/(x + (3/2)/(x + ...))))")
    cv.text(8, 8, "为什么用它：级数在这里相消严重，而渐近又不够好，连分式两头都不怕")
    cv.text(10, 2, "区域三   x >= 4       渐近级数（只需前 2 到 3 项）")
    cv.text(11, 8, "erfc(x) 约等于 exp(-x^2) / (x sqrt(pi)) 乘 (1 - 1/(2x^2) + 3/(4x^4) - ...)")
    cv.text(12, 8, "为什么可以：指数因子主导，修正项只影响常数因子")
    cv.text(14, 2, "三条必须记住的判断（每一条都能省下几小时的调试）")
    cv.text(15, 6, "1   绝对不要用 1 - erf(x) 代替 erfc(x)：x > 3 后有效数字掉到 2 位以内")
    cv.text(16, 6, "2   渐近区的门槛是 x >= 4，不是 x >= 1（判据是最优截断 n* 约等于 x^2）")
    cv.text(17, 6, "3   需要复平面（Faddeeva w(z)）时用 Weideman 算法，不要拼三条实公式")
    cv.text(19, 2, "实现之后必须跑的两项自检（它们能抓住九成以上的实现错误）")
    cv.text(20, 6, "(1) 在交界处 x = 1 与 x = 4 检查两套公式的衔接误差（应小于 1e-12）")
    cv.text(21, 6, "(2) 大 x 端与渐近首项比较（比值应趋于 1，且方向与 1/(2x^2) 相符）")
    cv.text(23, 2, "家族的换算（同一件事的不同名字，符号错一个就全错）")
    cv.text(24, 6, "Phi(x) = 0.5 乘 erfc(-x / sqrt(2))      正态 CDF")
    cv.text(25, 6, "Q(x)   = 0.5 乘 erfc( x / sqrt(2))      高斯 Q 函数（上尾）")
    cv.text(26, 6, "erfi(x) = -i 乘 erf(i x)               虚误差函数（无衰减，靠级数）")
    cv.text(27, 6, "D(x)   = (sqrt(pi) / 2) 乘 exp(-x^2) 乘 erfi(x)    Dawson 积分")
    cv.text(29, 2, "极限检查（这是抓符号错误最快也最可靠的办法，务必做一次）")
    cv.text(30, 6, "x -> +无穷 时 Q(x) -> 0、Phi(x) -> 1；用这个做一次单向检查即可定位符号")
    return cv.render()


# ---------- ch31 block4：Bessel 的渐近三区域 ----------
def fig_bessel_regions() -> list[str]:
    ROWS, COLS = 32, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Bessel 的渐近三区域：判据是比值 nu / z，不是 nu 或 z 各自的绝对值")
    cv.text(2, 2, "区域一   小 z（|z| 远小于 sqrt(nu + 1)）        幂律主导")
    cv.text(3, 8, "J_nu(z) 约等于 (z/2)^nu / Gamma(nu + 1)")
    cv.text(4, 8, "形态：首项主导；若 nu 不小，则函数值本身就是指数小的")
    cv.text(6, 2, "区域二   中等 z（|z| 与 nu 同量级）              过渡区（最容易出错）")
    cv.text(7, 8, "正确工具：Debye 渐近，或一致的 Airy 型（见 31.7.4）")
    cv.text(8, 8, "J_nu(nu sech a) 约等于 exp(nu (tanh a - a)) / sqrt(2 pi nu tanh a)")
    cv.text(9, 8, "警告：这里套用「大 z 公式」会指数级出错，而那个公式看起来毫无问题")
    cv.text(11, 2, "区域三   大 z（|z| 远大于 nu^2）                振荡衰减")
    cv.text(12, 8, "J_nu(z) 约等于 sqrt(2 / (pi z)) 乘 cos(z - nu pi / 2 - pi / 4)")
    cv.text(13, 8, "形态：振幅按 z^(-1/2) 衰减（这是二维波扩散的标准衰减率）")
    cv.text(15, 2, "大阶情形（nu 远大于 1，z 固定）                 指数小")
    cv.text(16, 8, "J_nu(z) 约等于 (z/2)^nu / Gamma(nu + 1)（回到区域一的公式）")
    cv.text(17, 8, "物理含义：高阶柱模式被强烈截止（圆波导高次模截止频率的来源）")
    cv.text(19, 2, "为什么区域二必须用 Airy：那里两个指数率相等（转点）")
    cv.text(20, 6, "最简模型就是 Airy 方程 y 的二阶导 = z 乘 y，解为 Ai(z), Bi(z)")
    cv.text(21, 6, "第 30 章例 30.9 已经推过：x > 0 纯指数衰减、x < 0 纯振荡，同一公式两种行为")
    cv.text(23, 2, "递推方向的警钟（与 31.8.2 的定理 31.26 完全呼应）")
    cv.text(24, 6, "J_nu 随 nu 指数衰减，是最小解；Y_nu 是指数增长的主见解")
    cv.text(25, 6, "所以：从低阶往上推只能稳定地算 Y_nu，算 J_nu 必须反向递推 + 归一化")
    cv.text(26, 6, "记忆口诀：衰减的那个（J、I、Ai、erfc）不能顺推，必须倒推")
    cv.text(28, 2, "一张自检工具：Wronskian 恒等式（任何实现都该先跑一次）")
    cv.text(29, 6, "J_nu Y_nu prime - J_nu prime Y_nu = 2 / (pi z)；偏差超过 1e-13 就说明有错")
    return cv.render()


# ---------- ch31 block5：正交多项式与 Jacobi 矩阵 ----------
def fig_orthopoly_ladder() -> list[str]:
    ROWS, COLS = 34, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "正交多项式的一张核心图：三项递推、Jacobi 矩阵、Gauss 求积是同一件事")
    cv.text(2, 2, "三项递推（首一形式，这就是全部正交多项式族的共同结构）")
    cv.text(3, 8, "p_{n+1}(x) = (x - alpha_n) p_n(x) - beta_n p_{n-1}(x)")
    cv.text(4, 8, "alpha_n = (x p_n, p_n) / (p_n, p_n)      beta_n = (p_n, p_n) / (p_{n-1}, p_{n-1})")
    cv.text(6, 2, "写成对称三对角矩阵（Jacobi 矩阵，它是全部算法的载体）")
    cv.text(7, 8, "[ alpha_0      sqrt(beta_1)     0            0       ]")
    cv.text(8, 8, "[ sqrt(beta_1) alpha_1         sqrt(beta_2)  0       ]")
    cv.text(9, 8, "[ 0            sqrt(beta_2)     alpha_2      sqrt(beta_3) ]")
    cv.text(11, 2, "三类对象是同一批数（这就是定理 31.17 的全部内容）")
    cv.text(12, 6, "求零点  ==  解超越方程  ==  三对角矩阵特征值分解")
    cv.text(13, 6, "求权重  ==  特征向量首分量的平方  ==  自动满足权重和等于 mu_0")
    cv.text(14, 6, "这条等价让「换一族多项式」变成「换两组系数」，代码模板完全不变")
    cv.text(16, 2, "一次完整验证（Legendre，n = 2，可直接手算）")
    cv.text(17, 6, "首一形式：p_0 = 1, p_1 = x, p_2 = x^2 - 1/3，故零点在正负 1 / sqrt(3)")
    cv.text(18, 6, "J_2 = [[0, 1/sqrt(3)], [1/sqrt(3), 0]]，特征向量为 (1, 正负 1) / sqrt(2)")
    cv.text(19, 6, "首分量平方 = 1/2，乘 mu_0 = 2 => 权重 = 1, 1（与教科书一致）")
    cv.text(21, 2, "三条工程含义（每一条都直接决定代码该怎么写，值得对照）")
    cv.text(22, 6, "1   节点与权重一起出来，不必单独求解（第 32 章 Gauss 求积的实现基础）")
    cv.text(23, 6, "2   求值用 Clenshaw 求和，与矩阵法共用同一套 alpha, beta 系数")
    cv.text(24, 6, "3   零点必然落在区间 (a, b) 内且单重（定理由 beta_n > 0 保证）")
    cv.text(26, 2, "各族的 beta_n 一览（Chebyshev 的 sqrt(beta) 恒定，因此只有它有初等零点）")
    cv.text(27, 6, "Legendre   beta_n = n^2 / (4n^2 - 1)      Hermite   beta_n = n / 2")
    cv.text(28, 6, "Laguerre   beta_n = n (n + alpha)          Gegenbauer beta_n = n(n+2l-1)/(4(n+l)^2-1)")
    cv.text(29, 6, "Chebyshev  beta_1 = 1/2，beta_{n>=2} = 1/4（sqrt(beta) 恒 1/2，故 T_n = cos(n arccos x)）")
    cv.text(31, 2, "大 n 渐近的普适结构（与 31.5.4、31.7.4 是同一个故事）")
    cv.text(32, 6, "内部区：Chebyshev 型包络 sqrt(2/(pi n sin theta)) 乘 cos(...)")
    cv.text(33, 6, "端点区：Airy 型过渡层（因为那里 Sturm-Liouville 方程出现转点）")
    return cv.render()


# ---------- ch31 block6：Gauss 求积的精度台阶 ----------
def fig_gauss_quadrature() -> list[str]:
    ROWS, COLS = 34, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "Gauss 求积的精度台阶：n 个点为什么能精确到 2n - 1 次")
    cv.text(2, 2, "代数精度对照（Legendre，区间 [-1, 1]；n 个点有 2n 个自由度）")
    cv.text(3, 6, "n = 1    节点 0                        精确到 1 次多项式")
    cv.text(4, 6, "n = 2    节点 正负 1 / sqrt(3)          精确到 3 次多项式")
    cv.text(5, 6, "n = 3    节点 0, 正负 sqrt(3/5)         精确到 5 次多项式")
    cv.text(6, 6, "n = 4    节点见 31.6.5                 精确到 7 次多项式")
    cv.text(7, 6, "一般规律：n 个节点 -> 2n 个自由度 -> 精度上限 2n - 1")
    cv.text(9, 2, "为什么 2n - 1 是上限（关键论证只有三行，值得逐字读懂）")
    cv.text(10, 6, "把 f 除以 p_n：f = q 乘 p_n + r，其中 deg r < n")
    cv.text(11, 6, "积分 = 积分(q p_n) + 积分(r) = 0 + sum w_i r(lambda_i)")
    cv.text(12, 6, "第一项为零正是「节点取 p_n 的零点」的全部作用（q 次数 <= n-1 保证正交）")
    cv.text(13, 6, "若要再精确到 2n 次，需多消一个自由度，但节点已经用完了 —— 这就是上限")
    cv.text(15, 2, "一次数值验证（n = 2，f = x^4，两个数字必须吻合）")
    cv.text(16, 6, "真值：积分 x^4 从 -1 到 1 等于 2/5 = 0.4")
    cv.text(17, 6, "求积：2 乘 (1/3)^2 = 2/9 约 0.22222（两个节点各算一次）")
    cv.text(18, 6, "误差：0.17778；余项公式给 f^(4)/(4!) 乘 (p_2, p_2) = 1 乘 8/45 = 0.17778")
    cv.text(20, 2, "与 Newton-Cotes 的对照（同样精度，Gauss 更省点）")
    cv.text(21, 6, "Simpson（3 个等距点）精度 3 次；Gauss（2 个自由节点）精度也是 3 次")
    cv.text(22, 6, "高阶 Newton-Cotes 会因等距节点出现 Runge 型振荡而数值不稳，Gauss 始终稳定")
    cv.text(23, 6, "代价：Gauss 的节点依赖权函数（必须先知道 w 才能定 alpha, beta）")
    cv.text(25, 2, "实现路径（本章给出构造，第 32 章给出工程化）")
    cv.text(26, 6, "1   由权函数递推算出 alpha_n, beta_n（可查表，见 31.6.3）")
    cv.text(27, 6, "2   组装对称三对角 Jacobi 矩阵，做特征值分解得到节点与权重")
    cv.text(28, 6, "3   用 Clenshaw 求和求函数值（避免显式构造每个多项式）")
    cv.text(30, 2, "一条实践提醒（端点有奇性时不要硬套 Legendre 求积）")
    cv.text(31, 6, "被积函数有端点奇性时（如 1/sqrt(1-x^2)），不要硬套 Legendre ——")
    cv.text(32, 6, "改用对应的 Jacobi 权（Chebyshev 权正好把奇性吸收进权函数），精度立刻恢复")
    return cv.render()


# ---------- ch31 block7：渐近展开的解剖 ----------
def fig_asymptotic_anatomy() -> list[str]:
    ROWS, COLS = 34, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "渐近展开的解剖：为什么「加项越多越好」是错的")
    cv.text(2, 2, "定义（取极限的次序与收敛级数完全相反，这是全部误解的源头）")
    cv.text(3, 6, "f(z) = sum_{n<N} a_n phi_n(z) + o(phi_N(z))    当 z -> z_0")
    cv.text(4, 6, "关键：先固定 N，再让 z 动。所以这是「有限项逼近」的渐近，不是级数收敛")
    cv.text(6, 2, "三项必须记住的性质（第二条与第三条最反直觉）")
    cv.text(7, 6, "(1) 唯一性：给定渐近序列，系数 a_n 唯一确定")
    cv.text(8, 6, "(2) 不收敛：级数可以处处发散，而渐近关系照旧成立")
    cv.text(9, 6, "     例：-1/x + 1!/x^2 - 2!/x^3 + ... 因 n! 增长而发散")
    cv.text(10, 6, "(3) 非唯一：两个不同函数可有同一个渐近展开（相差 exp(-1/z^2) 量级）")
    cv.text(11, 6, "     这一条正是 Stokes 现象的来源（第 30 章陷 30.6.8 陷阱 3）")
    cv.text(13, 2, "误差随项数的形状（两侧都变差的 V 形，最小值在第 n* 项）")
    cv.text(14, 6, "截断太少的代价：丢掉了仍有贡献的项，误差是幂律衰减")
    cv.text(15, 6, "截断太多的代价：阶乘增长项失控，误差转为指数上升")
    cv.text(16, 6, "最小值位置：n* 约等于 rho z（rho 是系数增长率的底数）")
    cv.text(17, 6, "结论：存在唯一最优截断，超过它误差单调上升，加项绝不会更准")
    cv.text(19, 2, "两个实例（Stirling 级数：等效项号 m=2n，按 rho=2 pi 得 n* 约等于 pi z）")
    cv.text(20, 6, "z = 2    第 7 项触底（约 7.8e-7），理论 n* 约等于 pi*z = 6.3（直接吻合）")
    cv.text(21, 6, "         => 只能给 6 位有效数字，达不到双精度，必须换公式")
    cv.text(22, 6, "z = 10   第 9 项已到 1.8e-18，低于双精度 2.2e-16（机器精度先到）")
    cv.text(23, 6, "         => 取前 7 项就是机器精度，「最优截断」这个概念用不上")
    cv.text(25, 2, "Watson 引理：把「局部化」变成逐项系数（大 z 时只有 t 约 1/z 处说话）")
    cv.text(26, 6, "若 f(t) 在 t -> 0 有 f ~ sum c_n t^((n+l)/m - 1)，则")
    cv.text(27, 6, "积分 exp(-z t) f(t) dt ~ sum c_n Gamma((n+l)/m) z^(-(n+l)/m)")
    cv.text(28, 6, "证明的关键一步：t > delta 的部分被指数压死，是 O(exp(-z delta))，比任何幂都小")
    cv.text(30, 2, "什么时候必须换成 Airy（一条可以背下来的转点判据）")
    cv.text(31, 6, "出现「两个驻点在靠拢」或「一侧振荡、另一侧指数」 -> 局部必是 Airy 型")
    cv.text(32, 6, "标准模型：y 的二阶导 = z 乘 y；普适性在于与 q 的具体来源无关")
    return cv.render()


# ---------- ch31 block8：应用落点总图 ----------
def fig_special_fn_apps() -> list[str]:
    ROWS, COLS = 34, 104
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, "特殊函数的应用落点：一条判据 —— 函数的类型等于支撑集的几何")
    cv.text(2, 2, "支撑集是正半轴   ->  归一化常数含 Gamma（阶乘的连续化）")
    cv.text(3, 8, "Gamma / chi^2 / Wishart / 指数 / Maxwell-Boltzmann")
    cv.text(4, 8, "尾部概率一律用 Q(s, x)（上不完全 Gamma）")
    cv.text(6, 2, "支撑集是区间     ->  归一化常数含 Beta（区间上的万能积分）")
    cv.text(7, 8, "Beta / Dirichlet / F 分布 / Student t")
    cv.text(8, 8, "尾部概率用不完全 Beta（t 分布与 F 分布都走这条路）")
    cv.text(10, 2, "支撑集是角度或相位  ->  归一化常数含 Bessel I")
    cv.text(11, 8, "von Mises / Rician / 相位噪声（共同点：支撑集是圆或球面）")
    cv.text(12, 8, "尾部概率用 Marcum Q（内部含 I_{nu/2}）")
    cv.text(14, 2, "物理与工程的落点（都是分离变量后剩下的一维径向问题）")
    cv.text(15, 6, "圆膜 / 圆波导 / 圆腔      ->  J_nu 的零点（本征频率表，例 31.5）")
    cv.text(16, 6, "圆柱热传导 / 扩散          ->  I_0 与 K_0（指数型核）")
    cv.text(17, 6, "散射 / 行波                ->  Hankel 函数（分离出入射与出射）")
    cv.text(18, 6, "天线方向图 / 圆孔衍射      ->  J_1(x) / x（主瓣由首个零点决定）")
    cv.text(19, 6, "球域（量子力学 / 声散射）  ->  j_n 是初等函数，方程退化为 tan(ka)")
    cv.text(21, 2, "信息论与学习的落点（把第 11 章与第 28 章的 KL 项接起来）")
    cv.text(22, 6, "速率函数 I(x) 是 ln M 的 Fenchel 共轭（第 30 章 30.7.3）")
    cv.text(23, 6, "Gamma 族情形可算到底：I(x) = KL( Gamma(alpha, alpha/x) 与 Gamma(alpha,1) )")
    cv.text(24, 6, "于是 exp(-n I(x)) 的指数就是「用错参数描述数据的代价」")
    cv.text(25, 6, "PAC-Bayes 界里的 KL 项与此同源（第 28 章 28.5）")
    cv.text(27, 2, "分数阶的落点（接第 9 章的分数布朗运动与记忆核）")
    cv.text(28, 6, "分数阶方程的解是 Mittag-Leffler E_alpha，alpha < 1 时给出幂律衰减")
    cv.text(29, 6, "alpha = 1/2 那一支退化为 exp(z^2) erfc(-z)，与误差函数合流")
    cv.text(31, 2, "总判据（遇到陌生分布时的查表顺序，照这三步走即可）")
    cv.text(32, 6, "先问支撑集 -> 定函数族 -> 再问「上尾还是下尾」-> 定不完全函数与参数")
    return cv.render()



# ---------- ch32 block0：数值积分的地图 ----------
def fig_numerics_map() -> list[str]:
    ROWS, COLS = 28, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  数值积分的地图：三条失败轴与对应的工具箱（先定失败模式，再选算法）')
    cv.text(2, 2, '  轴一：维数 d（决定「能不能做下去」，4 到 6 维是分水岭）')
    cv.text(3, 2, '      d = 1 ~ 3      张量积 / 复合 Newton-Cotes / Gauss 求积（32.2）')
    cv.text(4, 2, '                     高精度可达 1e-15（若函数光滑）')
    cv.text(5, 2, '      d = 4 ~ 10     稀疏网格（Smolyak），代价从 N^d 降到 N (log N)^(d-1)（32.5.5）')
    cv.text(6, 2, '      d >= 10        蒙特卡洛 / 拟蒙特卡洛 / 贝叶斯求积（32.5.2 - 32.5.6）')
    cv.text(7, 2, '                     理由：MC 的误差 1/sqrt(N) 与 d 无关，而任何网格方法都被 d 击穿')
    cv.text(9, 2, '  轴二：正则性 alpha（端点行为 f 约等于 (x-a)^alpha）')
    cv.text(10, 2, '      alpha 无穷（光滑）     复合求积 + Richardson / Romberg 外推，指数级精度（32.2.6）')
    cv.text(11, 2, '      alpha > 0（弱奇性）    换元（双指数）或 Jacobi 加权求积，精度可回到机器精度（32.4.2）')
    cv.text(12, 2, '      alpha = 0（跳跃）      分段处理 + 端点校正（Euler-Maclaurin 的端点项）')
    cv.text(13, 2, '      含 log（对数奇性）     同弱奇性，但换元的形式不同（32.4.1 表）')
    cv.text(14, 2, '      内部奇点 / 振荡         拆区间 + Filon / Levin / 驻相（32.4.5）')
    cv.text(16, 2, '  轴三：精度承诺 epsilon（决定用哪一类算法，也决定要不要外推）')
    cv.text(17, 2, '      1e-2 ~ 1e-4     低成本固定公式就够（梯形 / Simpson / 低阶 Gauss）')
    cv.text(18, 2, '      1e-6 ~ 1e-10    必须做外推或自适应细分（32.3），并监控收敛率')
    cv.text(19, 2, '      1e-12 ~ 1e-15   必须处理端点、必须做外推、且受舍入误差底线限制（32.3.4）')
    cv.text(21, 2, '  三条轴的关系（这是本章最重要的一句话，值得抄进笔记本）')
    cv.text(22, 2, '      精度承诺越高，函数就越「不像」光滑函数：')
    cv.text(23, 2, '      端点上的 O(h^alpha) 行为决定收敛率，想拿高精度就必须在端点做手脚')
    cv.text(25, 2, '  一条元规则（先实测收敛率，再据此选方法；顺序不能颠倒）')
    cv.text(26, 2, '      先用一条公式算两三个不同步长，看误差随步长怎么降（拟合出阶 p）')
    cv.text(27, 2, '      再据此选方法。这一步（收敛率实测）比选公式本身更重要')
    return cv.render()


# ---------- ch32 block1：求积公式家族 ----------
def fig_quadrature_family() -> list[str]:
    ROWS, COLS = 31, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  求积公式家族：一个坐标系（n 个点有 2n 个自由度，看它们花在哪）')
    cv.text(2, 2, '  基础事实（一切求积公式都是线性泛函，差别只在自由度怎么花）')
    cv.text(3, 2, '      求积 = 线性泛函 Q(f) = sum w_i f(x_i)；n 点共有 2n 个自由参数')
    cv.text(4, 2, '      花 n 个自由度去固定节点 -> 剩 n 个 -> 代数精度 n-1（Newton-Cotes）')
    cv.text(5, 2, '      把 2n 个自由度全花在精度上 -> 代数精度 2n-1（Gauss）')
    cv.text(7, 2, '  家族对照（同样点数下谁更准；最后两行的对比最关键）')
    cv.text(8, 2, '      梯形        n = 2 点      精度 1      核 K_2 不变号（凸函数恒高估）')
    cv.text(9, 2, '      Simpson     n = 3 点      精度 3      对称性送一阶（奇数点免费）')
    cv.text(10, 2, '      Boole       n = 5 点      精度 5      以上开始出现负权重')
    cv.text(11, 2, '      N-C n>=9                  精度 n      **不要用**：sum|w_i| 指数增长')
    cv.text(12, 2, '      Gauss       n 点          精度 2n-1   节点不固定，sum|w_i| 只按 log n 增长')
    cv.text(13, 2, '      Gauss-Kronrod 2n+1 点     精度 3n+1   含 n 个 Gauss 点，用于误差估计')
    cv.text(15, 2, '  误差的两级语言（一级只回答「加密能改善多少」，二级给具体量）')
    cv.text(16, 2, '      一级（阶）：E = O(h^p)，只回答「加密能改善多少」')
    cv.text(17, 2, '      二级（量）：Euler-Maclaurin  E = sum B_2k/(2k)! h^2k (f^(2k-1)(b) - f^(2k-1)(a)) + ...')
    cv.text(18, 2, '                  误差只依赖端点导数！内部再光滑也没用')
    cv.text(19, 2, '                  => 端点奇性直接毁掉阶（sqrt(x) 让 O(h^2) 降为 O(h^1.5)）')
    cv.text(20, 2, '                  => 周期解析函数的端点导数自动相等 => 梯形法则指数收敛')
    cv.text(22, 2, '  两条提速路线（从同一个 Euler-Maclaurin 展开出发）')
    cv.text(23, 2, '      Richardson / Romberg：用同一族的多步长消掉 h^2, h^4, ... 逐级外推')
    cv.text(24, 2, '      Gauss 换节点：用最优点位一次性把精度拉到 2n-1')
    cv.text(25, 2, '      现代库的做法：Gauss-Kronrod 嵌入（复用旧点）+ 自适应细分（32.3）')
    cv.text(27, 2, '  三条必须记住的数字（都是从实测与理论界里挑出来的经验门槛）')
    cv.text(28, 2, '      n >= 9       等距 Newton-Cotes 出现负权，禁用')
    cv.text(29, 2, '      n 约 100     Gauss 的节点间距太小，求值误差被放大 n^2 倍，改用复合 Gauss')
    cv.text(30, 2, '      j 约 3-5     Romberg 外推的层数上限（再往上被舍入误差吃掉）')
    return cv.render()


# ---------- ch32 block2：自适应求积的解剖 ----------
def fig_adaptive_refine() -> list[str]:
    ROWS, COLS = 32, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  自适应求积的解剖：误差均分 + 递归细分 + 三道刹车（缺任何一道都会出事故）')
    cv.text(2, 2, '  核心原理（等分布：均分的是「相对」误差，不是绝对误差）')
    cv.text(3, 2, '      每段的误差预算  epsilon_i = epsilon 乘 (eta_i / eta)，eta_i 是该段上 |f| 的积分')
    cv.text(4, 2, '      对 p 阶方法，局部误差 = C 乘 h_i^(p+1)，于是最优网格满足')
    cv.text(5, 2, '      h_i^(p+1) 正比于 eta_i        即 h_i 正比于 eta_i^(1/(p+1))')
    cv.text(6, 2, '      含义：函数值大的地方多花预算；p 越小，网格对 eta 的依赖越剧烈')
    cv.text(8, 2, '  一次迭代的四步（每一步都有具体的失败模式）')
    cv.text(9, 2, '      第一步  取误差贡献最大的段（不是误差最大的段，要乘上该段的权重）')
    cv.text(10, 2, '      第二步  一分为二（或三点细化），分别求积并估计各自的局部误差')
    cv.text(11, 2, '      第三步  用子段结果替换父段（父子误差估值可能矛盾，以子段为准）')
    cv.text(12, 2, '      第四步  全局误差小于 epsilon 则停机，否则回到第一步')
    cv.text(14, 2, '  三道刹车（这是工程实现与教科书伪代码的唯一区别）')
    cv.text(15, 2, '      刹车一  相对加绝对双判据：err <= max(atol, rtol 乘 |Q|)')
    cv.text(16, 2, '              只给相对判据：I 约 0 时死循环；只给绝对判据：I 约 1e9 时过早停机')
    cv.text(17, 2, '      刹车二  舍入底线 rtol >= 50 乘 eps_mach 约 1e-14（再小就是噪声，见陷阱 3）')
    cv.text(18, 2, '      刹车三  迭代上限（200 层 / 1e6 次求值），防死循环；工程上必须有这一条')
    cv.text(20, 2, '  两个必须做的自检（花几分钟，省几小时，值得每次都做一遍）')
    cv.text(21, 2, '      自检一  收敛率实测 p = log2(|Q_h - Q_h/2| / |Q_h/2 - Q_h/4|)，与理论值对不上就是有奇性')
    cv.text(22, 2, '      自检二  误差估计的趋势：连续三层应当递减；出现回升或跳动说明已到舍入极限，立刻停')
    cv.text(24, 2, '  一条最重要的判据（什么时候该用自适应，什么时候不该用）')
    cv.text(25, 2, '      擅长：峰值位置事先不知道（黑箱仿真、窄共振、尖锐峰、多层介质）')
    cv.text(26, 2, '      不擅长：端点或内部有「已知」奇性（那是换元与剥离的活，不是自适应的活）')
    cv.text(27, 2, '      优先级顺序：换元 > 剥离 > 分级网格 > 自适应 > 单纯加密')
    cv.text(29, 2, '  代价（对数律与幂律的差别，这是选它的唯一理由）')
    cv.text(30, 2, '      光滑函数上：区间数按 O(log(1/epsilon)) 层增长（对数，几乎免费）')
    cv.text(31, 2, '      在 x^alpha 奇性上：区间数按 O(epsilon^(-1/(1+alpha))) 幂律增长，自适应救不了')
    return cv.render()


# ---------- ch32 block3：奇性与振荡的五种指纹 ----------
def fig_singularity_zoo() -> list[str]:
    ROWS, COLS = 35, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  奇性与振荡：五种指纹与三条手法（先认型，再选手法）')
    cv.text(2, 2, '  第一步：认型（只看一个数：实测收敛率 p = log2 |Q_h - Q_h/2| / |Q_h/2 - Q_h/4|）')
    cv.text(3, 2, '      p = 2           光滑，正常（不必做任何事）')
    cv.text(4, 2, '      p = 1.5         端点 f 约等于 x^(1/2)         -> 幂次奇性 alpha = 1/2')
    cv.text(5, 2, '      p = 1.1         端点 f 约等于 x^(0.1)         -> 强幂次奇性')
    cv.text(6, 2, '      p = 2 但常数大   对数奇性                    -> 需要专门处理')
    cv.text(7, 2, '      误差不收敛       内部奇点 / 振荡 / 区间截断不足')
    cv.text(9, 2, '  第二步：选手法（三条，按优先级；前两条优先，第三条是兜底）')
    cv.text(10, 2, '      (1) 换元             能改函数就改函数（最优先）')
    cv.text(11, 2, '          代数换元 x = a + u^m，要求 m >= 1 / (1 + alpha)')
    cv.text(12, 2, '          alpha = -1/2  ->  m >= 2       alpha = -3/4  ->  m >= 4')
    cv.text(13, 2, '          m 不要过大：u^m 在 u 约 1 处陡变，收益被常数吃掉')
    cv.text(14, 2, '          正弦型 / 双指数换元：任何端点奇性都压成指数小，误差约 exp(-cN / log N)')
    cv.text(15, 2, '      (2) 解析剥离 + 加权求积   知道 alpha 但函数是黑箱')
    cv.text(16, 2, '          写 w_s = (x-a)^alpha (b-x)^beta，Gauss-Jacobi 精确吃掉奇性')
    cv.text(17, 2, '          必查：g = f / w_s 在奇点处有有限非零极限（否则 alpha 取错，结果全错）')
    cv.text(18, 2, '          对数奇性：用「对 alpha 求导」把它变成幂次（与第 30 章例 30.6 同法）')
    cv.text(19, 2, '      (3) 分级网格 / 自适应     既不能换元也不知道 alpha')
    cv.text(20, 2, '          网格 x_i = (i/N)^gamma，gamma >= 2 / (1 + alpha) 恢复 O(N^-2)')
    cv.text(21, 2, '          自适应会自动逼近分级网格，但需要 O(N) 次细分才抵得上一次换元')
    cv.text(23, 2, '  特殊的两类（不适用上面三条，必须单独处理，判据各不相同）')
    cv.text(24, 2, '      振荡：判据是 omega 乘区间长度（不是 omega 本身）')
    cv.text(25, 2, '            < 10       加密即可（每波长 2 到 10 个采样点即可）')
    cv.text(26, 2, '            10 - 1e3   Filon（误差与 omega 无关，把权重解析算出来）')
    cv.text(27, 2, '            > 1e3      驻相法（只要主项，代价 O(1)）；注意端点贡献不能漏')
    cv.text(28, 2, '      无穷区间：尾部是幂律 -> 换元或剥离 + 闭式尾部')
    cv.text(29, 2, '                尾部是指数 -> 直接截断，X 约 (1/c) log(C / (c epsilon))')
    cv.text(30, 2, '                尾部是高斯 -> Gauss-Hermite（题目送权，代价几乎为零）')
    cv.text(32, 2, '  一条元规则（顺序不能颠倒：改变正则性优先于优化常数）')
    cv.text(33, 2, '      换元 > 剥离 > 分级网格 > 自适应 > 单纯加密')
    cv.text(34, 2, '      前两个改变问题的正则性，后三个只是优化常数')
    return cv.render()


# ---------- ch32 block4：高维积分的四条路 ----------
def fig_highdim_routes() -> list[str]:
    ROWS, COLS = 36, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  高维积分的四条路：从 d = 1 到 d = 100，方法要换三次（临界点都有公式）')
    cv.text(2, 2, '  第一段  d = 1 ~ 3     张量积 / 复合 Gauss（精度可达机器精度）')
    cv.text(3, 2, '      代价 n^d，精度与 d 无关（定理 32.15：每维只需 n 约 ln(1/eps) / (2 ln rho) 点）')
    cv.text(4, 2, '      精度可达机器精度；这一段的唯一技巧是处理奇性（32.4）')
    cv.text(6, 2, '  第二段  d = 4 ~ 9     张量积与蒙特卡洛的过渡区')
    cv.text(7, 2, '      张量积仍是首选（表：d = 9 时 7^9 = 4.0e7，MC 要 1e8）')
    cv.text(8, 2, '      临界维数 d* = ln(sigma^2 / eps^2) / ln(n)：eps = 1e-4 时 d* = 9.47')
    cv.text(10, 2, '  第三段  d = 10 ~ 20   蒙特卡洛 / 拟蒙特卡洛 / 稀疏网格')
    cv.text(11, 2, '      蒙特卡洛：误差 sigma / sqrt(N)，与 d 无关（这是它唯一的优点）')
    cv.text(12, 2, '      方差缩减四件套：控制变量（省 1/(1-rho^2) 倍）、对偶、分层、重要性采样')
    cv.text(13, 2, '      拟蒙特卡洛：星偏差 D_N* 与 Koksma-Hlawka，理想是 N^-1（快一个数量级）')
    cv.text(14, 2, '                  前提是「有效维数低」——只有少数变量真正重要')
    cv.text(15, 2, '      稀疏网格：误差 N^-s（指数与 d 无关！），代价是 (log N)^((s+1)(d-1)) 的对数幂')
    cv.text(16, 2, '                  硬前提是「各维混合导数有界」，即函数不可强耦合')
    cv.text(17, 2, '      经验范围：稀疏网格 d <= 10 ~ 15 好用；QMC 可到上百维（靠低有效维数）')
    cv.text(19, 2, '  第四段  d >= 20 以上   放弃数值积分，改用解析近似')
    cv.text(20, 2, '      要 ln Z 到几个有效数字       -> Laplace / 鞍点法（代价只有 O(d^3)）')
    cv.text(21, 2, '      要 E[g(X)] 的具体值         -> MCMC / 重要性采样 / 贝叶斯求积')
    cv.text(22, 2, '      要误差棒                    -> 贝叶斯求积（自带后验方差）或 MCMC')
    cv.text(23, 2, '      多模态                      -> 前三种都不好，先做峰值枚举再说')
    cv.text(25, 2, '  三条必须提前问的问题（顺序不能颠倒，问错了方法就选错）')
    cv.text(26, 2, '      问题一  这个积分到底要的是「一个数」还是「ln 这个数」？（后者可以降到 Laplace）')
    cv.text(27, 2, '      问题二  有效维数是多少？（低 -> QMC/稀疏网格；高 -> 只有 MC 可用）')
    cv.text(28, 2, '      问题三  各维之间耦合强不强？（弱 -> 稀疏网格可用；强 -> 稀疏网格失效）')
    cv.text(30, 2, '  一条容易忽略的对照（经验数字，用于快速估量级）')
    cv.text(31, 2, '      同一精度 eps = 1e-4 所需的求值次数（跨七个数量级的对比）')
    cv.text(32, 2, '      d = 1      张量积 7          蒙特卡洛 1e8')
    cv.text(33, 2, '      d = 9      张量积 4.0e7      蒙特卡洛 1e8')
    cv.text(34, 2, '      d = 20     张量积 8.0e16     蒙特卡洛 1e8')
    cv.text(35, 2, '      读法：蒙特卡洛在低维是「用一亿次求值换七次求值」，在高维却是唯一的选择')
    return cv.render()


# ---------- ch32 block5：函数近似的四种武器 ----------
def fig_approx_arsenal() -> list[str]:
    ROWS, COLS = 34, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  函数近似的四种武器：从多项式到有理式，从单变量到高维')
    cv.text(2, 2, '  插值（节点给定，必须穿过所有点，误差上限由一个常数决定）')
    cv.text(3, 2, '      误差上限 = (1 + Lebesgue 常数) 乘 最佳逼近误差')
    cv.text(4, 2, '      等距节点：Lambda_n 约 2^n / (e n ln n)      指数增长 -> 高阶插值发散（Runge 反例）')
    cv.text(5, 2, '      Chebyshev 节点：Lambda_n = (2/pi) ln n + 1  对数增长 -> 唯一可用的高阶插值')
    cv.text(6, 2, '      实测（Runge 函数，n = 26）：等距误差 75.8（发散！），Chebyshev 误差 1.1e-2（收敛）')
    cv.text(8, 2, '  最佳一致逼近（Chebyshev 意义，误差等波纹，提供精度下界）')
    cv.text(9, 2, '      特征：误差有 n+2 个交错极值点（交错定理）')
    cv.text(10, 2, '      作用：给所有其他方法提供精度标尺（下界），本身不适合当算法用')
    cv.text(12, 2, '  最小二乘（L2 投影，就是第 6 章的正交投影定理的直接应用）')
    cv.text(13, 2, '      就是第 6 章的投影定理：误差与逼近空间正交')
    cv.text(14, 2, '      风险：节点分布与积分权重决定了它偏向哪个区域')
    cv.text(16, 2, '  Chebyshev 与谱方法（周期问题则改用傅里叶，两者是同一件事）')
    cv.text(17, 2, '      收敛率的唯一控制量是 rho（解析椭圆半轴和）')
    cv.text(18, 2, '      |a_k| <= 2 M rho^(-k)：ln|a_k| 对 k 作图的斜率就是 -ln rho')
    cv.text(19, 2, '      三个 rho 是同一个 rho：Gauss 求积、插值、Chebyshev 展开')
    cv.text(20, 2, '      结论：收敛率不是算法的属性，是函数的属性（反推可定位复奇点）')
    cv.text(22, 2, '  Pade 与有理逼近（让极点去贴奇性，代价是可能出现伪极点）')
    cv.text(23, 2, '      匹配 Taylor 到 L+M 阶，自由度 L+M+1 个（比多项式多一倍）')
    cv.text(24, 2, '      优势：极点可以跨越奇点，能给出散级数的"尾巴"（与连分式等价，用 Lentz 算）')
    cv.text(25, 2, '      风险：伪极点（分子分母有近似公因子）-> 图上出现虚假尖峰')
    cv.text(26, 2, '      两个在用的例子：时滞 e^(-tau s) 的 Padé（顺带解释了 16.7 的非最小相位）')
    cv.text(27, 2, '                      tanh 的 [3/2]（极点 sqrt(2.5) = 1.581 贴近真奇点 pi/2 = 1.571）')
    cv.text(29, 2, '  高维的墙（与 32.5 是同一堵墙，两种表述、同一个根源）')
    cv.text(30, 2, '      多项式逼近：误差 O(n^(-k/d))，指数被维数除')
    cv.text(31, 2, '      d = 10, k = 2 时要 1e-4 需 n 约 1e20 项 —— 不可行')
    cv.text(32, 2, '      绕过方式一：结构性假设（稀疏网格、低有效维数）')
    cv.text(33, 2, '      绕过方式二：组合性假设（Barron 类，误差 O(n^(-1/2)) 与 d 无关）')
    return cv.render()


# ---------- ch32 block6：数值积分的应用落点 ----------
def fig_numerics_apps() -> list[str]:
    ROWS, COLS = 31, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  数值积分的应用落点：五类问题、五种精度要求、五套工具')
    cv.text(2, 2, '  一  归一化常数 / 配分函数（只要 ln Z，不要分布细节）')
    cv.text(3, 2, '      Laplace / 鞍点法（32.5.7）：代价 O(d^3)，高维反而更准（例 32.10）')
    cv.text(4, 2, '      要误差棒时改用桥抽样或贝叶斯求积（32.5.6）')
    cv.text(5, 2, '      陷阱：调和均值估计器的方差可能无穷（逆似然重尾）')
    cv.text(7, 2, '  二  期望与风险度量（要具体数值加误差棒，不要对数尺度）')
    cv.text(8, 2, '      CVaR 的积分没有奇性（只有一阶导不连续）-> 复合求积就够')
    cv.text(9, 2, '      VaR 的估计是分位数问题（密度在分母）-> 误差被放大的原因就在这里')
    cv.text(10, 2, '      Rockafellar-Uryasev 把 CVaR 变成凸问题 -> 与第 25 章的锥规划接上')
    cv.text(12, 2, '  三  窄峰问题（峰宽远小于区间尺度，全局最优公式必然失效）')
    cv.text(13, 2, '      核心事实：全局最优公式会失效（Gauss 的节点与特征尺度无关）')
    cv.text(14, 2, '      峰位已知 -> 按峰拆区间 + 每段 Gauss（剥离思想）')
    cv.text(15, 2, '      峰位未知 -> 自适应细分（这是它真正的用武之地）')
    cv.text(16, 2, '      分辨率条件是 N > 1 / gamma，达不到时任何公式都白搭')
    cv.text(18, 2, '  四  反问题 / 积分方程（Fredholm 第一类，求积精度是噪声底）')
    cv.text(19, 2, '      Nystrom 方法：求积 -> 线性系统 -> Tikhonov/TSVD 正则化')
    cv.text(20, 2, '      关键：求积误差是正则化的噪声底，锁死整个反演的精度上限')
    cv.text(21, 2, '      增加点数反而让条件数变差 -> 存在最优点数（不是越多越好）')
    cv.text(23, 2, '  五  数值实验的可靠性（对所有四类都适用，必须每次都走一遍）')
    cv.text(24, 2, '      三要素：加密序列、报告阶与外推值、检查舍入底线')
    cv.text(25, 2, '      两条最值钱的检验：两种原理不同的方法互相对照；找闭式特例对照')
    cv.text(26, 2, '      一次成功的收敛率测量，胜过十次盲目的参数调整（实测优先）')
    cv.text(28, 2, '  一条贯穿全部五类的原则（精度永远是用解析知识换来的）')
    cv.text(29, 2, '      精度永远是「用知识换来的」：知道峰在哪、知道 alpha、知道解析域')
    cv.text(30, 2, '      知识越多，需要的点数越少；什么都不知道时，只能付自适应的对数代价')
    return cv.render()


# ---------- ch32 block7：决策链总图 ----------
def fig_numerics_decision() -> list[str]:
    ROWS, COLS = 40, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  本章的决策链收拢为一张图（照箭头走，不需要记公式）')
    cv.text(2, 2, '  起点：这个积分有几维？（第一个岔路口，决定走左支还是右支）')
    cv.text(3, 2, '      |   （左支：一维或各维可分离；右支：高维，见下面的分界）')
    cv.text(4, 2, '      +-- d = 1 或各维可分离 --------------------------------+')
    cv.text(5, 2, '      |                                                       |')
    cv.text(6, 2, '      |   函数有奇性吗？（测收敛率 p，看 32.4.1 指纹表）      |')
    cv.text(7, 2, '      |       没有（p 等于理论值）                            |')
    cv.text(8, 2, '      |           |                                           |')
    cv.text(9, 2, '      |           +-- 周期函数 -> 等距梯形（谱精度，例 32.4）  |')
    cv.text(10, 2, '      |           +-- 一般光滑 -> Gauss-Kronrod + 自适应      |')
    cv.text(11, 2, '      |           +-- 有振荡   -> 按 omega 乘区间长度分档      |')
    cv.text(12, 2, '      |       有（p 非整数 / 收敛异常）                       |')
    cv.text(13, 2, '      |           |                                           |')
    cv.text(14, 2, '      |           +-- 能换元吗？ 能 -> 代数或双指数换元（最优）|')
    cv.text(15, 2, '      |           +-- 知道 alpha 吗？ -> 剥离 + Gauss-Jacobi  |')
    cv.text(16, 2, '      |           +-- 都不知道 -> 分级网格 / 自适应（代价大）  |')
    cv.text(17, 2, '      |                                                       |')
    cv.text(18, 2, '      +-- d >= 4 --------------------------------------------+')
    cv.text(19, 2, '      |   （高维支：先问有效维数，再问各维之间的耦合强度）')
    cv.text(20, 2, '      有效维数低吗？（少数变量是否贡献了 99% 的方差）')
    cv.text(21, 2, '         低                    高（少数变量决定一切）')
    cv.text(22, 2, '         |                     |（分界判据见 32.5.4 的两行判据）')
    cv.text(23, 2, '         +-- 且各维耦合弱      +-- 强耦合 / 无结构')
    cv.text(24, 2, '         |     稀疏网格         |     蒙特卡洛 + 方差缩减')
    cv.text(25, 2, '         |     (d <= 10~15)     |     (误差 sigma / sqrt(N))')
    cv.text(26, 2, '         +-- 否则 QMC (Sobol)  |（在有效维数低时这个差距是常态）')
    cv.text(27, 2, '               比 MC 快一个量级 |（QMC 的星偏差是 N^-1 量级）')
    cv.text(28, 2, '                                +-- d >= 20 且只要 ln Z')
    cv.text(29, 2, '                                       -> Laplace / 鞍点法（便宜且更准）')
    cv.text(31, 2, '  终点前必须做的验收（无论走哪条路，三步都不能省）')
    cv.text(32, 2, '      第一步  四个层次的加密序列，拟合实测阶 p')
    cv.text(33, 2, '      第二步  Richardson 外推，报告外推值与 p（不要报告最后一次计算值）')
    cv.text(34, 2, '      第三步  两种原理不同的方法互相对照 + 找一个闭式特例对照')
    cv.text(36, 2, '  三条最容易踩的线（记住这三条就避开了 90% 的事故）')
    cv.text(37, 2, '      线一  n >= 9 的等距 Newton-Cotes 绝对不用；等距高阶插值也绝对不用')
    cv.text(38, 2, '      线二  误差估计必须"连看三层、确认按 2^-p 递减"才能相信')
    cv.text(39, 2, '      线三  自适应救不了奇性（换元才行）；全局最优公式救不了窄峰（拆区间才行）')
    return cv.render()


# ---------- ch33 block0：不等式地图（33.1.4 的四条主线） ----------
def fig_ineq_map() -> list[str]:
    ROWS, COLS = 34, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  第 33 章的地图：一个动作、四类工具、一个终点')
    cv.text(2, 2, '  全章唯一的动作（所有不等式的共同形状，也是唯一的解题动作）')
    cv.text(3, 2, '      把一个「不知道的量」拆成「已知的因子」乘起来；拆法不同，就是各类不等式的不同')
    cv.text(5, 2, '  工具一  内积与范数型（33.2；共同形状：把「乘积之和」换成「平方和之积」）')
    cv.text(6, 2, '      Cauchy-Schwarz   内积的上界；等号条件是线性相关（夹角余弦为 1）')
    cv.text(7, 2, '      Holder           把 L^p 与 L^q 配对；等号条件是 |f|^p 与 |g|^q 成比例')
    cv.text(8, 2, '      Young / eps-Young 用一个平方项吸收一个乘积项，代价是付出 1/eps')
    cv.text(9, 2, '      Minkowski        和的范数不超过范数的和（三角不等式的范数版）')
    cv.text(10, 2, '      对偶范数         上确界就等于一个内积（Fenchel 对偶的起点）')
    cv.text(11, 2, '      Kantorovich      夹角余弦的下界（条件数进入界的地方）')
    cv.text(12, 2, '      范数链与次可乘   ||A||_2 <= ||A||_F <= sqrt(r) ||A||_2 <= ||A||_*')
    cv.text(14, 2, '  工具二  凸性与几何型（33.3；共同形状：用「切线或割线」把函数夹住）')
    cv.text(15, 2, '      Jensen           期望与函数值的比较；差值约为 0.5 乘 f 的二阶导乘方差')
    cv.text(16, 2, '      二次夹逼         强凸给下包、光滑给上包；两包合起来定出收敛率')
    cv.text(17, 2, '      加权 AM-GM       乘积不超过加权和；等号条件：全部变量相等')
    cv.text(18, 2, '      排序不等式       同序和最大、逆序和最小（一切配对问题的极值）')
    cv.text(19, 2, '      指对数不等式族   1 + x <= e^x 是 Chernoff 方法的全部原料')
    cv.text(20, 2, '      Stirling 双侧界  把渐近式升级成对一切 n 都成立的严格界')
    cv.text(22, 2, '  工具三  迭代与微分型（33.4；共同形状：把微分不等式积成显式界）')
    cv.text(23, 2, '      Gronwall         微分形式的指数放大（连续 / 积分 / 离散三种形式）')
    cv.text(24, 2, '      比较原理         把高维系统的行为比较到标量系统（Lyapunov 方法的全部内容）')
    cv.text(25, 2, '      递推不等式       时变系数下的展开式（先放大后衰减的两段式估计）')
    cv.text(27, 2, '  工具四  概率型（33.5 - 33.6；共同形状：把尾概率换成指数矩，再换回来）')
    cv.text(28, 2, '      尾部积分恒等式   E[X] 等于 P(X>t) 的积分（概率与期望之间唯一的桥）')
    cv.text(29, 2, '      Markov 族        Markov / Chebyshev / Cantelli（单边版恒不超过 1）')
    cv.text(30, 2, '      期望与高概率     高概率到期望便宜（截断法），反向昂贵（Markov 只有 1/t）')
    cv.text(31, 2, '      极端值           union bound 的代价只有 log m；E[max] 多减一项更紧')
    cv.text(32, 2, '      指数族           有精确率函数就用它，没有才退到 Bernstein 或 Hoeffding')
    cv.text(33, 2, '      组合             union -> 覆盖网 -> chaining（代价从 m 降到熵积分）')
    return cv.render()


# ---------- ch33 block1：Cauchy-Schwarz 家族与两个边界 ----------
def fig_cs_family() -> list[str]:
    ROWS, COLS = 30, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Cauchy-Schwarz 的四种形态与一个几何（夹角余弦的两个边界）')
    cv.text(2, 2, '  四个空间，同一句话（把「乘积的和」换成「平方和之积」）')
    cv.text(3, 2, '      向量     |<x,y>| <= ||x|| ||y||（最基本的形态，其余三种都是它的实例）')
    cv.text(4, 2, '      函数     |积分 f g| <= ||f||_2 ||g||_2')
    cv.text(5, 2, '      概率     |E[XY]| <= sqrt(E[X^2] E[Y^2])，即 |Cov| <= sigma_X sigma_Y')
    cv.text(6, 2, '      矩阵     |tr(A^T B)| <= ||A||_F ||B||_F（把矩阵看成拉直的向量）')
    cv.text(8, 2, '  唯一的等号条件（几何说法，四种形态完全一致）')
    cv.text(9, 2, '      夹角余弦 cos(theta) = <x,y> / (||x|| ||y||)，其绝对值等于 1')
    cv.text(10, 2, '      也就是 x 与 y 线性相关（同向或反向；此时 cos^2 精确等于 1）')
    cv.text(12, 2, '  夹角余弦的两个边界（这是本章两条主定理的分工）')
    cv.text(13, 2, '      上界（Cauchy-Schwarz）      cos^2 <= 1        对任意两个向量都成立')
    cv.text(14, 2, '      下界（Kantorovich，33.2.6） cos^2 >= 1/eta    当谱被夹在 [m,M] 内时成立')
    cv.text(15, 2, '      其中 eta = (M+m)^2 / (4Mm)，1/eta = 1 - ((kappa-1)/(kappa+1))^2')
    cv.text(17, 2, '  这个下界为什么重要（它同时控制两件看起来无关的事）')
    cv.text(18, 2, '      能量比   <Ax,x> 与 <A^{-1}x,x> 的比被夹在 [1/eta, eta]（条件数的代价）')
    cv.text(19, 2, '      迭代速率 梯度下降的最坏收缩因子就是 1 - 1/eta 的量级')
    cv.text(20, 2, '      所以「条件数」同时出现在几何与算法两侧，这不是巧合而是同一个量')
    cv.text(22, 2, '  用的时候最常见的错（务必区分两种「有界」，否则会写出被违反的界）')
    cv.text(23, 2, '      正确（Kantorovich 的条件）：比值 x_i / y_i 落在 [m,M] 内')
    cv.text(24, 2, '      错误（会给出被违反的界）：分量 x_i 与 y_i 各自落在 [m,M] 内')
    cv.text(25, 2, '      反例：x=(10,1)、y=(1,10) 的分量都在 [1,10] 内')
    cv.text(26, 2, '            但 cos^2 = 400/10201 = 0.03921，小于「各自有界」给的 0.33058')
    cv.text(27, 2, '            按比值读则是 m=0.1、M=10，得 0.039212，精确取等')
    cv.text(29, 2, '  记住这一句：Kantorovich 管的是「比值」，不是「分量」')
    return cv.render()


# ---------- ch33 block2：凸性的三层夹逼 ----------
def fig_convex_chain() -> list[str]:
    ROWS, COLS = 30, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  凸函数的三种「夹逼」与各自的用途（从弱到强，需要的假设也越来越多）')
    cv.text(2, 2, '  第一层  Jensen（只需要凸性，不需要可微；最弱也最常用）')
    cv.text(3, 2, '      E[f(X)] >= f(E[X])，这就是「割线在函数上方」的整体化')
    cv.text(4, 2, '      差值定量：约等于 0.5 乘 f 的二阶导乘 Var(X)')
    cv.text(5, 2, '      精确情形：对数正态时差值恒为 -sigma^2/2（例 33.5 的全部内容）')
    cv.text(6, 2, '      用途：证明 KL >= 0（Gibbs）、证明均方稳定可推出 a.s. 稳定')
    cv.text(8, 2, '  第二层  一阶条件（需要可微；这是凸性分析的主力工具）')
    cv.text(9, 2, '      f(y) >= f(x) + <grad f(x), y-x>，即切线恒在函数的下方')
    cv.text(10, 2, '      用途：凸性的判据、KKT 条件的来源、镜像下降与 Bregman 散度')
    cv.text(12, 2, '  第三层  二次夹逼（需要强凸 + 光滑，这是最强的假设）')
    cv.text(13, 2, '      f(x) + <g,y-x> + (mu/2)||y-x||^2  <=  f(y)  <=  f(x) + <g,y-x> + (L/2)||y-x||^2')
    cv.text(14, 2, '      左边来自 mu-强凸，右边来自 L-光滑（下降引理就是右边）')
    cv.text(15, 2, '      用途：梯度下降的收敛率 (kappa-1)/(kappa+1)，以及「函数值误差与距离平方同阶」')
    cv.text(17, 2, '  三层之间的关系（做题顺序不能颠倒，跳步就会用错工具）')
    cv.text(18, 2, '      凸不凸？       -> 用 Jensen（不需要任何光滑性）')
    cv.text(19, 2, '      有梯度吗？     -> 用一阶条件（切线在下）')
    cv.text(20, 2, '      曲率有界吗？   -> 用二次夹逼（上下两个包同时给）')
    cv.text(21, 2, '      三者都成立时，二次夹逼的两个常数就是条件数的两端：')
    cv.text(22, 2, '          kappa = L/mu，它同时是 33.2.6 的 eta 与 33.7.3 的步数因子')
    cv.text(24, 2, '  一个必须记住的提醒（常数是全局最坏值，实际常常好得多）')
    cv.text(25, 2, '      mu 与 L 是全定义域上 Hessian 的下确界与上确界')
    cv.text(26, 2, '      局部曲率通常比全局值好得多，所以用它们算出的步数是上界且可能极松')
    cv.text(27, 2, '      这与 Kantorovich 界「只在最坏方向上取等」是同一件事')
    cv.text(29, 2, '  一句话：凸性给方向，梯度给切线，曲率界给速率；三者缺一就只能得到更弱的结论')
    return cv.render()


# ---------- ch33 block3：指对数不等式族 ----------
def fig_log_ineq() -> list[str]:
    ROWS, COLS = 30, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  指对数不等式族：Chernoff 方法的全部原料（五个成员，各有擅长的区间）')
    cv.text(2, 2, '  成员一  1 + x <= e^x                   （对一切实 x 成立，等号仅在 x = 0）')
    cv.text(3, 2, '      小 x 时缺口约为 x^2/2（很紧）；大 x 时缺口迅速变大')
    cv.text(4, 2, '      实测：x=0.01 时缺口/ x^2 = 0.5017；x=1 时 0.7183；x=2 时 1.0973')
    cv.text(5, 2, '      用途：Hoeffding 引理的逐点不等式（因此只适合做局部或小偏差控制）')
    cv.text(7, 2, '  成员二  x/(1+x) <= log(1+x) <= x       （x > -1）')
    cv.text(8, 2, '      左端在 x 趋于无穷时渐进接近（相对误差趋于零）')
    cv.text(9, 2, '      右端在 x 小时很紧，大 x 时松得多（实测 x=2 时左端缺口/ x^2 = 0.108）')
    cv.text(10, 2, '      用途：相对误差形式的 Chernoff 界、Bernoulli 率函数的来源')
    cv.text(12, 2, '  成员三  log x <= x - 1                 （x > 0）')
    cv.text(13, 2, '      用途：Gibbs 不等式（KL >= 0）的一行证明、一切对数域的界')
    cv.text(15, 2, '  成员四  log(1+x) >= x - x^2/2          （x >= 0）')
    cv.text(16, 2, '      用途：小 x 时给出二次下界（比成员二的右端更精确）')
    cv.text(18, 2, '  成员五  e^x <= 1 + x + x^2             （|x| <= 1）')
    cv.text(19, 2, '      用途：把指数矩换成二次多项式（矩方法与次高斯刻画的入口）')
    cv.text(21, 2, '  使用的总纪律（三句话，选错成员是集中不等式最常见的错误来源）')
    cv.text(22, 2, '      小 x        -> 用二次近似（缺口 = 系数乘 x^2，系数在 0.44 到 0.72 之间）')
    cv.text(23, 2, '      大 x        -> 只能用成员二（它渐进紧），其余成员会迅速变松')
    cv.text(24, 2, '      动手前先问  -> 这里的 x 有多大？这个问题的答案直接决定用哪一个成员')
    cv.text(26, 2, '  为什么这一族值得单独列一张图（它是集中不等式唯一的地基）')
    cv.text(27, 2, '      Markov 到 Chernoff 的四步里，唯一需要「不等式」的是第 3 步（控制矩母函数）')
    cv.text(28, 2, '      而第 3 步全部用的是这一族；所以记住这一族，就不必再背 Hoeffding 的常数')
    cv.text(29, 2, '      常数都是从 log(1+x) 的二次展开里出来的（8 分之 (b-a)^2 也是这么来的）')
    return cv.render()


# ---------- ch33 block4：Gronwall 三种形式与紧度 ----------
def fig_gronwall() -> list[str]:
    ROWS, COLS = 31, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Gronwall 族：从微分不等式到显式界（三种形式 + 一条紧度规律）')
    cv.text(2, 2, '  形式一  微分形式（定理 33.21，最一般也最容易证明）')
    cv.text(3, 2, '      u 的导数 <= beta(t) 乘 u(t)   =>   u(t) <= u(0) 乘 exp(积分 beta)')
    cv.text(4, 2, '      证明动作只有一步：令 v = u 乘 exp(-积分 beta)，则 v 的导数 <= 0，故 v 不增')
    cv.text(6, 2, '  形式二  积分形式（定理 33.22，控制里最常用）')
    cv.text(7, 2, '      u(t) <= alpha + beta 乘 积分 u(s) ds   =>   u(t) <= alpha 乘 e^(beta t)')
    cv.text(8, 2, '      注意：当 alpha 本身振荡（不单调）时，不能只用 e^(beta t) 因子')
    cv.text(9, 2, '            必须写成 Duhamel 卷积形式，否则方向会错')
    cv.text(11, 2, '  形式三  离散形式（定理 33.23，工程上用最多，也最容易出错）')
    cv.text(12, 2, '      x 的第 n+1 项 <= lambda 乘 x 的第 n 项 + b')
    cv.text(13, 2, '      =>  x_n <= lambda^n x_0 + b 乘 (lambda^n - 1)/(lambda - 1)')
    cv.text(14, 2, '      陷阱：不能把 lambda^n 直接换成 e^(a n)（其中 lambda = 1 + a）')
    cv.text(15, 2, '            实测 a=0.1、n=1000 时两者差 109 倍；a=0.5、n=100 时差 4 个数量级')
    cv.text(17, 2, '  紧度规律（例 33.9 实测，这是整张图最实用的一条）')
    cv.text(18, 2, '      扰动全部同号时（系统偏差、未补偿的常值误差、量化的固定偏置）')
    cv.text(19, 2, '          -> 界被精确取到：实测紧度 1.000000，可以放心当预测用')
    cv.text(20, 2, '      扰动符号交替时（零均值噪声、随机舍入）')
    cv.text(21, 2, '          -> 界松 40 倍以上，甚至出现界为正而真值为负（此时完全不要用它）')
    cv.text(22, 2, '      判据只有一句：问「这个误差有没有可能一直朝同一个方向累积？」')
    cv.text(24, 2, '  更一般的形式：比较原理（定理 33.25，第 18 章整章的逻辑基础）')
    cv.text(25, 2, '      把一个高维非线性系统的行为「比较」到一个标量系统上')
    cv.text(26, 2, '      这就是 Lyapunov 方法（第 18 章）的全部数学内容')
    cv.text(27, 2, '      所以 K 类、K 无穷类、KL 类函数就是「标量比较系统的解」的抽象')
    cv.text(29, 2, '  一条使用纪律（选错工具族会松几十倍，这是最常见的事故）')
    cv.text(30, 2, '      先判断扰动是「系统的」还是「随机的」：系统用 Gronwall，随机用集中不等式')
    return cv.render()


# ---------- ch33 block5：尾部积分恒等式 ----------
def fig_tail_identity() -> list[str]:
    ROWS, COLS = 32, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  尾部积分恒等式：概率与期望之间唯一的桥（两个方向的代价极不对称）')
    cv.text(2, 2, '  恒等式（定理 33.27，几何上是「同一块面积的两种数法」）')
    cv.text(3, 2, '      E[X] = 积分（从 0 到无穷）P(X > t) dt            （要求 X >= 0）')
    cv.text(4, 2, '      E[X^2] = 2 乘 积分（从 0 到无穷）t 乘 P(X > t) dt')
    cv.text(5, 2, '      离散版：E[X] = sum（k 从 1 到无穷）P(X >= k)')
    cv.text(6, 2, '      证明只有一步：Fubini 交换（把 x 轴上的长度换成 t 轴下的面积）')
    cv.text(7, 2, '      注意：对可正可负的 X 必须换成 |X|，否则会漏掉一个因子 2（例 33.10）')
    cv.text(9, 2, '  数值核对（例 33.10，五项全部十位吻合，可当自检模板）')
    cv.text(10, 2, '      Exp(1)        积分 P(X>t) dt = 1.0000000000，而 E[X] = 1')
    cv.text(11, 2, '      |N(0,1)|      积分 P(X>t) dt = 0.7978845608，而 E|X| = sqrt(2/pi)')
    cv.text(12, 2, '      Poisson(3)    sum_k P(X>=k) = 3.0000000000，而 E[X] = 3')
    cv.text(14, 2, '  两个方向的翻译（代价完全不对称，这是本节最重要的一条）')
    cv.text(15, 2, '      概率 -> 期望（截断法，便宜；尾界的指数结构被完整保留）')
    cv.text(16, 2, '          把 [0, 无穷) 拆成 [0, eps] 与 (eps, 无穷) 两段')
    cv.text(17, 2, '          E|X| <= eps + 积分（从 eps 到无穷）g(t) dt，其中 g 是尾界')
    cv.text(18, 2, '          eps 的最优取法是让 g(eps) = 1，结果是量级 sqrt(2 pi / n)')
    cv.text(19, 2, '          好处：尾界的指数结构被完整保留（积分后仍是指数量级）')
    cv.text(20, 2, '      期望 -> 概率（Markov，昂贵；只用到一阶矩，信息损失极大）')
    cv.text(21, 2, '          P(X >= t) <= E[X] / t，只有 1/t 那么弱')
    cv.text(22, 2, '          原因：一阶矩无法区分「值小但概率大」与「值大但概率小」')
    cv.text(23, 2, '          极端的例子：Exp(1) 与「以 0.001 概率取 1000」的均值相同，尾部差 1000 倍')
    cv.text(25, 2, '  工程结论（这一条决定了很多领域的路线选择）')
    cv.text(26, 2, '      能用尾概率表述的结论，就不要用期望表述')
    cv.text(27, 2, '      这就是第 21 章「期望好不等于路径好」的根源')
    cv.text(28, 2, '      也是第 28 章从「期望泛化」转向「高概率泛化」的原因')
    cv.text(30, 2, '  一句话：这条恒等式是「概率侧」与「矩侧」之间的唯一合法汇率')
    cv.text(31, 2, '      而汇率是不对称的，所以一开始就把结论写成哪一侧，会决定后续能不能继续推')
    return cv.render()


# ---------- ch33 block6：Chernoff 执行流程 ----------
def fig_chernoff_flow() -> list[str]:
    ROWS, COLS = 32, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Chernoff 方法的执行流程（第 1、2 步是套路，全部差别在第 3 步）')
    cv.text(2, 2, '  输入  独立的 X_1 到 X_n，目标 P(S_n - E S_n >= n t)，其中 S_n = sum X_k')
    cv.text(4, 2, '  第 1 步  指数化（把事件换成一个更容易处理的事件）')
    cv.text(5, 2, '      因为 e^(lambda x) 单调，{S_n >= s} 等价于 {e^(lambda S_n) >= e^(lambda s)}')
    cv.text(7, 2, '  第 2 步  Markov（整个方法里唯一一次真正的不等式）')
    cv.text(8, 2, '      P(S_n >= s) <= e^(-lambda s) 乘 E[e^(lambda S_n)]')
    cv.text(9, 2, '      用的是 Markov（定理 33.28，取 phi(x) = e^(lambda x)）')
    cv.text(11, 2, '  第 3 步  控制矩母函数（唯一需要结构的一步，也是唯一有差别的一步）')
    cv.text(12, 2, '      独立性把 E[e^(lambda S_n)] 拆成乘积，取对数变加法')
    cv.text(13, 2, '      每一项用 1 + x <= e^x 或其加强版控制，得到三条分支：')
    cv.text(14, 2, '          只有取值范围 [a,b]      -> Hoeffding 引理')
    cv.text(15, 2, '          取值范围 + 已知方差      -> Bernstein / Bennett（低方差时远好）')
    cv.text(16, 2, '          分布已知（Bernoulli 等） -> 精确率函数（最优，优先选它）')
    cv.text(18, 2, '  第 4 步  对 lambda 取上确界（免费的一维优化，千万不要省）')
    cv.text(19, 2, '      结果指数就是 Cramer 率函数 n 乘 Lambda*(t)（第 11 章 11.5.1 已建立）')
    cv.text(21, 2, '  第 5 步  反解（若目标是样本量而不是概率，就要做这一步）')
    cv.text(22, 2, '      已知分布时用精确率函数反解；不知道分布时只能退回 Hoeffding')
    cv.text(23, 2, '      注意：不同分支的常数差 5 到 6 倍（例 33.16 实测，见下）')
    cv.text(25, 2, '  选用判据（只需要记住这一个问题，就能选对分支）')
    cv.text(26, 2, '      有没有精确率函数？有，就用它（它同时给出正确的指数与正确的常数）')
    cv.text(27, 2, '      没有，则按「方差是否远小于 (b-a)^2/4」在 Bernstein 与 Hoeffding 之间选')
    cv.text(29, 2, '  反解常数对照（Bernoulli(0.1)，双边 delta = 0.05）')
    cv.text(30, 2, '      eps = 0.10：Hoeffding 需要 n >= 184.44，精确需要 n >= 36（差 5.12 倍）')
    cv.text(31, 2, '      eps = 0.02：Hoeffding 需要 n >= 4611.1，精确需要 n >= 834（差 5.53 倍）')
    return cv.render()


# ---------- ch33 block7：六种界的对照 ----------
def fig_bound_zoo() -> list[str]:
    ROWS, COLS = 34, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  同一个问题的六种界（X 服从 Bernoulli(0.1)，n = 100，考察单边事件）')
    cv.text(2, 2, '  情形 A：eps = 0.1（远离均值，约 10 倍标准差以外区）')
    cv.text(3, 2, '      精确（二项分布）              1.9786e-03      松度 1（基准）')
    cv.text(4, 2, '      Chernoff（率函数 D = 0.0444） 1.1792e-02      松 5.96 倍')
    cv.text(5, 2, '      Bernstein                     1.7352e-02      松 8.77 倍')
    cv.text(6, 2, '      Cantelli（单边 Chebyshev）    8.2569e-02      松 41.7 倍')
    cv.text(7, 2, '      Chebyshev（双边）             9.0000e-02      松 45.5 倍')
    cv.text(8, 2, '      Hoeffding                     1.3534e-01      松 68.4 倍（最差）')
    cv.text(9, 2, '      排序：精确 < Chernoff < Bernstein < Cantelli < Chebyshev < Hoeffding')
    cv.text(11, 2, '  情形 B：eps = 0.05（接近均值，同一个问题的另一个尺度）')
    cv.text(12, 2, '      精确                          7.2573e-02      松度 1（基准）')
    cv.text(13, 2, '      Cantelli                      2.6471e-01      松 3.65 倍（变成最好！）')
    cv.text(14, 2, '      Chernoff（率函数 D = 0.01224）2.9412e-01      松 4.05 倍')
    cv.text(15, 2, '      Bernstein                     3.0979e-01      松 4.27 倍')
    cv.text(16, 2, '      Chebyshev（双边）             3.6000e-01      松 4.96 倍')
    cv.text(17, 2, '      Hoeffding                     6.0653e-01      松 8.36 倍（仍最差）')
    cv.text(18, 2, '      排序变了：Cantelli 反超 Chernoff，成为最紧的一条')
    cv.text(20, 2, '  为什么排序会变（这是本章最值得记住的一个现象）')
    cv.text(21, 2, '      远离均值时：指数界碾压矩界（68 倍 对 42 倍）')
    cv.text(22, 2, '      接近均值时：矩界反而最好，因为 Cantelli 知道「概率不可能超过 1」')
    cv.text(23, 2, '                  而指数界在小 eps 时退化成 e^(-0.5) = 0.61，白浪费了一半')
    cv.text(25, 2, '  实用判据（按偏差与标准差的比例分档，两档都要算一遍）')
    cv.text(26, 2, '      偏差只有几个标准差（n eps 与 sigma sqrt(n) 同量级）  -> 用 Cantelli')
    cv.text(27, 2, '      偏差远大于几个标准差                              -> 用 Chernoff 或 Bernstein')
    cv.text(28, 2, '      完全不知道分布                                    -> 用 Hoeffding（接受保守）')
    cv.text(30, 2, '  三条与这张表配套的提醒（每一条都对应一个常见的错误）')
    cv.text(31, 2, '      一  单边事件一律用 Cantelli，不要用双边 Chebyshev（后者可能大于 1）')
    cv.text(32, 2, '      二  Hoeffding 在 p = 0.5 时是紧的，在 p 远离 0.5 时最差（方差没被利用）')
    cv.text(33, 2, '      三  六条界的顺序不是固定的，换 eps 就会变，所以要做「两档对照」再选')
    return cv.render()


# ---------- ch33 block8：几何 vs 幂律 ----------
def fig_conv_rates() -> list[str]:
    ROWS, COLS = 34, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  几何收敛与幂律收敛：交点在哪里（第 32 章 32.8.4 留下的接口 iii）')
    cv.text(2, 2, '  两类误差的形状（识别方法只看坐标轴是半对数还是双对数）')
    cv.text(3, 2, '      几何  E = C_1 乘 rho^(-n)   半对数图上是直线；rho 由解析域或谱隙决定')
    cv.text(4, 2, '      幂律  E = C_2 乘 n^(-p)     双对数图上是直线；p 由光滑性或收敛阶决定')
    cv.text(6, 2, '  交点方程（没有初等闭式解，但两行牛顿迭代可求）')
    cv.text(7, 2, '      n* ln(rho) = p ln(n*) + ln(C_2 / C_1)')
    cv.text(8, 2, '      粗略估计：n* 约等于 (p / ln rho) 乘 ln(p / ln rho)（C_1 约等于 C_2 时）')
    cv.text(10, 2, '  实测交点（最大的根，即「几何最终取胜」的位置）')
    cv.text(11, 2, '      rho=2.0   p=2  c=1       n* = 4.00       强解析，四步之后几何就赢')
    cv.text(12, 2, '      rho=2.0   p=2  c=1e2     n* = 14.32      常数涨 100 倍只推后 3.6 倍')
    cv.text(13, 2, '      rho=1.5   p=2  c=1       n* = 12.43      中等解析性，十几步后几何赢')
    cv.text(14, 2, '      rho=1.1   p=2  c=1       n* = 95.72      弱解析：要等到第 96 步')
    cv.text(15, 2, '      rho=1.05  p=2  c=1       n* = 221.34     每步只缩小 5%，要两百多步')
    cv.text(16, 2, '      rho=1.01  p=2  c=1       n* = 1465.23    几乎不能算「几何收敛」')
    cv.text(17, 2, '      rho=1.1   p=4  c=1       n* = 227.83     p 翻倍，交点后移 2.4 倍')
    cv.text(18, 2, '      rho=1.1   p=2  c=1e6     n* = 261.78     常数的灾难：只推后 2.7 倍')
    cv.text(19, 2, '      rho=2.0   p=1  c=1       无解            p=1 太慢，幂律永远翻不了身')
    cv.text(21, 2, '  达到固定精度 eps = 1e-6 需要的步数（这张表最贴近工程决策）')
    cv.text(22, 2, '      幂律：p=1 -> 1e6 步；p=2 -> 1000 步；p=3 -> 100 步；p=4 -> 31.6 步')
    cv.text(23, 2, '      几何：rho=10 -> 6 步；rho=5 -> 8.6；rho=2 -> 19.9；rho=1.5 -> 34.1')
    cv.text(24, 2, '            rho=1.2 -> 75.8；rho=1.1 -> 145.0；rho=1.05 -> 283.2；rho=1.01 -> 1388.5')
    cv.text(25, 2, '      注意对角线：rho=1.01 的「几何」（1389 步）比 p=2 的幂律（1000 步）还慢')
    cv.text(27, 2, '  三条判断规则（把 33.7 的全部内容压成三句）')
    cv.text(28, 2, '      规则一  先算 n*，不要凭感觉（rho=2 时是个位数，rho=1.1 时是百位数）')
    cv.text(29, 2, '      规则二  常数的力量远小于 rho 的力量（c 涨 1e6 只推后 2.7 倍）')
    cv.text(30, 2, '      规则三  判断「几何」真假，只看它是否依赖离散化参数（见下一张图）')
    cv.text(32, 2, '  一句话：几何收敛在 n 大时必胜，但「大」是相对的')
    cv.text(33, 2, '      误用这条规则的最常见方式是「看到 rho 小于 1 就以为一定会很快」')
    return cv.render()


# ---------- ch33 block9：给一个界的决策链 ----------
def fig_bound_workflow() -> list[str]:
    ROWS, COLS = 36, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  给一个界：完整的决策链（照箭头走，不需要记住任何公式）')
    cv.text(2, 2, '  起点  我手上有什么信息？（先做这一步分类，分错了后面全错）')
    cv.text(3, 2, '      |  （下面五个分支按「信息类型」划分，不是按方法难易划分）')
    cv.text(4, 2, '      +-- 只有内积、能量、范数这一类的量（结构最弱，界也最一般）')
    cv.text(5, 2, '      |       -> Cauchy-Schwarz（等号：线性相关）')
    cv.text(6, 2, '      |       -> 若要下界且谱被夹住：Kantorovich（33.2.6）')
    cv.text(7, 2, '      +-- 有个乘积项要吸收（估计里出现「交叉项」时的标准动作）')
    cv.text(8, 2, '      |       -> eps-Young（最优 eps = b/(2a)，代价是付出 1/eps）')
    cv.text(9, 2, '      +-- 要比较「期望」与「函数值」（或均值与对数均值）')
    cv.text(10, 2, '      |       -> Jensen（差值约为 0.5 乘二阶导乘方差）')
    cv.text(11, 2, '      +-- 条件是不等式之间的变化率关系（微分或递推）')
    cv.text(12, 2, '      |       -> 先问：扰动是随机的还是系统的？')
    cv.text(13, 2, '      |          系统（可能同号累积）-> Gronwall（此时界常常是紧的）')
    cv.text(14, 2, '      |          随机（零均值、近似独立）-> 转到下面的概率分支')
    cv.text(15, 2, '      +-- 概率问题（下面四步按顺序走，每步只回答一个问题）')
    cv.text(16, 2, '             第一步：有没有精确率函数？（这是最重要的一步）')
    cv.text(17, 2, '                 有（分布已知）-> Chernoff，直接用率函数（最优）')
    cv.text(18, 2, '                 没有 -> 第二步：知道方差吗？')
    cv.text(19, 2, '                         知道 -> Bernstein（低方差时远好于 Hoeffding）')
    cv.text(20, 2, '                         不知道 -> Hoeffding（接受 5 到 6 倍的保守）')
    cv.text(21, 2, '             第三步：偏差有多大？（决定用指数界还是用 Cantelli）')
    cv.text(22, 2, '                 只有几个标准差 -> 用 Cantelli 反而最好（例 33.15）')
    cv.text(23, 2, '             第四步：要同时管 m 个事件吗？（决定要不要做覆盖）')
    cv.text(24, 2, '                 是 -> union bound（代价只有 log m，很便宜）')
    cv.text(25, 2, '                 要管一整类函数 -> 覆盖数加 chaining（代价是熵积分）')
    cv.text(26, 2, '             变量不独立 -> McDiarmid 或 Azuma（第 8 章 8.5）')
    cv.text(28, 2, '  写完之后的四道检查（一道都不能省，这是本章 33.1.2 的四件套）')
    cv.text(29, 2, '      检查一  条件写全了吗？（独立性、有界性、强凸性、解析性）')
    cv.text(30, 2, '      检查二  方向对吗？（单边事件是否误用了双边版）')
    cv.text(31, 2, '      检查三  等号条件能达到吗？（能则界到顶，该换问题而不是换界）')
    cv.text(32, 2, '      检查四  界小于 1 吗？（大于 1 是废界；小于 1 但松 100 倍也是废界）')
    cv.text(34, 2, '  最后一步  收敛类型的判断（33.7，决定「能不能继续加密」）')
    cv.text(35, 2, '      半对数直线 -> 几何；双对数直线 -> 幂律；加密后步数也涨 -> 换方法')
    return cv.render()


# ---------- ch34 block1：方程的三个层级（原手写块改造） ----------
def fig_eq_layers() -> list[str]:
    ROWS, COLS = 24, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  第 34 章的地图：方程的三个层级（越往下越难解，但表达力越强）')
    cv.text(1, 2, '  第一层  线性矩阵方程（可直接解，一次分解就完事，代价 O(n^3)）')
    cv.text(2, 2, '      Sylvester   A X + X B = C（两个矩阵可以完全不同）')
    cv.text(3, 2, '      取 B = A^T 并要求未知量对称，就得到 Lyapunov（连续时间）')
    cv.text(4, 2, '      把 -Q 换成 -Q - P B R^-1 B^T P（多乘一个未知量），就升级到第二层')
    cv.text(5, 2, '  第二层  二次矩阵方程（不能直接解，要特征分解或迭代）')
    cv.text(6, 2, '      Riccati   A^T P + P A - P B R^-1 B^T P + Q = 0（连续 CARE）')
    cv.text(7, 2, '                P = A^T P A + Q - A^T P B (B^T P B + R)^-1 B^T P A（离散 DARE）')
    cv.text(8, 2, '      Riccati 是 HJB 在"线性系统 + 二次代价"下的特例')
    cv.text(9, 2, '      若代价里有"最坏情形"，二次项会变成不定的（H-infinity，另一支）')
    cv.text(10, 2, '  第三层  非线性偏微分方程（只能近似，且随状态维数指数变难）')
    cv.text(11, 2, '      HJB        0 = min_u { L(x,u) + gradV . f(x,u) }')
    cv.text(12, 2, '      去掉动态规划、只做静态优化，就退化为 KKT 条件（第 25 章）')
    cv.text(13, 2, '  旁支（不在主链上，但同样常用，各有各的解法）')
    cv.text(14, 2, '      Stein（离散 Lyapunov）／时滞特征方程（超越方程）／Lyapunov-Krasovskii')
    cv.text(15, 2, '      Wiener-Hopf（第 12 章）／Fokker-Planck（第 9 章与第 29 章）')
    cv.text(16, 2, '  判读规则（三句话）：看未知量在方程里出现几次就能定层级')
    cv.text(17, 2, '      出现一次      -> 第一层，直接法，O(n^3)，一次分解就结束')
    cv.text(18, 2, '      出现两次      -> 第二层，Schur 或迭代，代价取决于迭代步数')
    cv.text(19, 2, '      出现未知函数及其导数（且非线性）-> 第三层，只能数值近似')
    cv.text(21, 2, '  一个补充：三层的关系不是"哪个更高级"，而是"多乘了什么东西"')
    cv.text(22, 2, '      每多乘一次未知量，求解难度就从"一次分解"跳到"特征分解"再跳到"迭代"')
    return cv.render()


# ---------- ch34 block11：选方程决策树（原手写块改造） ----------
def fig_choose_eq() -> list[str]:
    ROWS, COLS = 34, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  给定一个控制或估计问题：我该立哪个方程？（照问题形式走，不看学科）')
    cv.text(1, 2, '  起点：先问"未知量是什么"，这一步分类错了后面全错')
    cv.text(2, 2, '      一个「矩阵」，且方程里它出现一次   -> 线性矩阵方程（第一层）')
    cv.text(3, 2, '          要求对称正定？ 是 -> Lyapunov（连续 A^T P + P A = -Q）')
    cv.text(4, 2, '                          否 -> Sylvester（A X + X B = C）')
    cv.text(5, 2, '          解法：Schur 分解 + 逐列回代，O(n^3)，一次就算完')
    cv.text(6, 2, '      一个「对称矩阵」，且方程里它出现两次 -> Riccati（第二层）')
    cv.text(7, 2, '          时间连续？ 是 -> CARE（Hamilton 矩阵 + Schur 分解）')
    cv.text(8, 2, '                      否 -> DARE（辛铅笔 + QZ 分解）')
    cv.text(9, 2, '          代价里有"最坏情形"？ 是 -> 不定 Riccati，再对 gamma 二分')
    cv.text(10, 2, '          是"每步更新一次"的？ 是 -> 递推 Riccati（Kalman 滤波）')
    cv.text(11, 2, '          解法：直接法 O(n^3)，或用 Kleinman 迭代（二次收敛，5~7 步）')
    cv.text(12, 2, '      一个「函数」V(x)，问最小代价       -> HJB（第三层，是 PDE）')
    cv.text(13, 2, '          线性系统 + 二次代价？ 是 -> 退化为 CARE，直接解（不要碰 PDE）')
    cv.text(14, 2, '          状态维数很小（3 以内）？ 是 -> 网格化数值解（幂律收敛）')
    cv.text(15, 2, '          否则 -> 参数化 V（神经网络）+ Bellman 残差迭代（第 24 章）')
    cv.text(16, 2, '      一个「轨迹」x(t) 与协态 lambda(t)  -> Pontryagin 两点边值问题')
    cv.text(17, 2, '          解法：打靶法或边值求解器（得到开环轨迹，不是反馈律）')
    cv.text(18, 2, '      一个「点」x（没有任何动态）        -> KKT 条件（第 25 章）')
    cv.text(19, 2, '          解法：内点法 / SQP / 投影梯度 / 有效集法（第 25 章）')
    cv.text(20, 2, '      一个「时滞 tau」                    -> 超越特征方程（有无穷多根）')
    cv.text(21, 2, '          要精确的稳定边界？ -> Lambert W 的全部分支（定理 34.16）')
    cv.text(22, 2, '          要设计控制器？     -> LKF + LMI，不等式越精细结果越紧')
    cv.text(24, 2, '  三个「不要」（三条都来自本章的实测反例，不是经验之谈）')
    cv.text(25, 2, '      不要用 Kronecker 形式做数值计算（只用来讲道理，交叉点只有 n* = 4.02）')
    cv.text(26, 2, '      不要在没验证前提的情况下相信迭代结果（Kleinman 会原地踏步且不报错）')
    cv.text(27, 2, '      不要把"残差小"当成"解准"（两者可以相差七个量级，见例 34.1）')
    cv.text(29, 2, '  一句话收尾：方程的选择由"问题的形式"决定，与方法的名字无关')
    cv.text(30, 2, '      同一个"最优控制"问题，线性时停在 CARE，非线性时才升到 HJB')
    return cv.render()


# ---------- ch34 block0：方程卡片与全章阅读方式 ----------
def fig_eq_card() -> list[str]:
    ROWS, COLS = 26, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  第 34 章的阅读方式：每个方程配一张六栏卡片（前两栏决定能不能用）')
    cv.text(1, 2, '      ① 标准形式      方程长什么样（转置、符号、正负号，一处写错全盘皆错）')
    cv.text(2, 2, '      ② 适用条件      什么假设下才有唯一解（可镇定、可检测、sep 非零）')
    cv.text(3, 2, '      ③ 解的性质      解有什么结构性结论（对称、正定、闭环稳定三者都要查）')
    cv.text(4, 2, '      ④ 求解算法      直接法还是迭代法（Schur 分解一次算完 vs 迭代逐步逼近）')
    cv.text(5, 2, '      ⑤ 复杂度与精度  代价多大、精度由谁决定（O(n^3)，精度看 sep 不看残差）')
    cv.text(6, 2, '      ⑥ 常见陷阱      哪个条件最容易被漏掉（漏前提、取错解、用错算法三类）')
    cv.text(8, 2, '  六栏里最容易出事的三个（本章反复出现，每一个都有实测反例）')
    cv.text(9, 2, '      ② 漏前提    Lyapunov 不看稳定、Kleinman 不看初值、Kalman 不看可检测')
    cv.text(10, 2, '      ④ 错算法    用 Kronecker 的 O(n^6) 去做本该 Schur 的 O(n^3)，差 15000 倍')
    cv.text(11, 2, '      ⑤ 看错量    用残差判断精度（残差是后向稳定性的指标，不是精度的指标）')
    cv.text(13, 2, '  一个例子填满六栏：Lyapunov 方程 A^T P + P A = -Q')
    cv.text(14, 2, '      ① A^T P + P A = -Q          ② sep(A, A^T) 非零即可解（对任意 Q 都有解）')
    cv.text(15, 2, '      ③ Q > 0 且 A 稳定 则 P > 0   ④ Schur 分解 + 逐列回代，直接法不需要迭代')
    cv.text(16, 2, '      ⑤ O(n^3)；精度约为 1/sep     ⑥ 漏检 P 的正定性，于是误判不稳定系统为稳定')
    cv.text(18, 2, '  三条待查清单的交付位置（第 33 章 33.9.4 留给本章的）')
    cv.text(19, 2, '      清单一  复杂度与 g(n) 归属        ->  34.2.5 与 34.5.4 的速查四')
    cv.text(20, 2, '      清单二  迭代算法对应哪一列        ->  34.5.3 的速查三（并补出第三列：二次）')
    cv.text(21, 2, '      清单三  协方差递推对应哪条不等式  ->  34.7.4 与 34.8.1 的归属表')
    cv.text(23, 2, '  一句话概括：本章管等式与解法，第 33 章管方向与界，两者合起来才是工程手册')
    cv.text(24, 2, '      先立方程解出对象（本章），再给解配上误差界与保证（第 33 章）')
    cv.text(25, 2, '      只有前者你不知道答案有多可信；只有后者你连答案都没有')
    return cv.render()


# ---------- ch34 block1：Sylvester 族 ----------
def fig_sylvester_family() -> list[str]:
    ROWS, COLS = 26, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Sylvester 族：三个名字、一个算法（全部 O(n^3)，全部一次分解就算完）')
    cv.text(1, 2, '      Sylvester   A X + X B = C        一般情形（A 与 B 可以是不同的矩阵）')
    cv.text(2, 2, '      取 B = A^T 并要求未知量对称，就得到下面两兄弟（只差一个转置的位置）')
    cv.text(3, 2, '      Lyapunov    A^T P + P A = -Q     连续时间（判定 Re(lambda) < 0 是否成立）')
    cv.text(4, 2, '      Stein       A^T P A - P = -Q     离散时间（判定 |lambda| < 1 是否成立）')
    cv.text(6, 2, '  唯一的解条件（三者共用同一条判据的形式，只是"特征值组合"的写法不同）')
    cv.text(7, 2, '      Sylvester   lambda_i(A) + lambda_j(B) != 0')
    cv.text(8, 2, '      Lyapunov    lambda_i(A) + lambda_j(A) != 0')
    cv.text(9, 2, '      Stein       lambda_i(A) * lambda_j(A) != 1')
    cv.text(11, 2, '  精度由谁决定：全部由 sep 决定，绝不看残差（这是本章要反复强调的一条）')
    cv.text(12, 2, '      ||X|| <= ||C|| / sep，sep 越小时解越大、误差也越大')
    cv.text(13, 2, '      实测：sep 每降一个量级，||X||_F 精确放大 10 倍（从 8.17 涨到 1.27e5）')
    cv.text(15, 2, '  解出来的 P 拿来做什么（这一步决定"要不要花时间解"）')
    cv.text(16, 2, '      P > 0        -> 候选 Lyapunov 函数 V = x^T P x，且 dV/dt = -x^T Q x < 0')
    cv.text(17, 2, '      P 有负特征值 -> A 不稳定（注意：此时方程照样有唯一解，解不是 L 函数）')
    cv.text(19, 2, '  两个算法：代价差 n^3 倍，交叉点只有 n* = 4.02')
    cv.text(20, 2, '      Bartels-Stewart（Schur + 逐列回代）   O(n^3)  永远不组装 n^2 阶矩阵')
    cv.text(21, 2, '      Kronecker 直接法（拉直成 n^2 维）     O(n^6)  只用来讲道理，不用来算数字')
    cv.text(23, 2, '  三条可用性检查（拿到任何线性矩阵方程都要走一遍，一条都不能省）')
    cv.text(24, 2, '      一  算 sep：它决定这个方程值不值得解、解出来能信几分')
    cv.text(25, 2, '      二  检查解是否对称：Lyapunov 的解必须对称，解出不对称说明算法用错')
    return cv.render()


# ---------- ch34 block2：sep 与三个精度基准 ----------
def fig_sep_danger() -> list[str]:
    ROWS, COLS = 28, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  sep 趋于 0 时，三个基准给出三种完全不同的结论（本章第一个反直觉结论）')
    cv.text(1, 2, '  （n = 4，取 B = -A + eps I，于是 sep = eps；每个星号代表 10 的 1 次幂）')
    cv.text(3, 2, '      eps      ||X||_F 的量级   res/||C|| 的量级   res/(||A||||X||)  真实相对误差')
    cv.text(4, 2, '      1e0      *                *                  *                 *')
    cv.text(5, 2, '      1e-2     ****             **                 *                 **')
    cv.text(6, 2, '      1e-4     ********         ****               *                 ****')
    cv.text(7, 2, '      1e-6     ************     ******             *                 ******')
    cv.text(8, 2, '      1e-8     **************** ********           *                 ********')
    cv.text(9, 2, '      解读     每降一个量级     同比例放大         恒定在 2e-16      与第三列同步')
    cv.text(10, 2, '                就放大 10 倍      （涨 7 个量级）    （机器精度）      （两者同源）')
    cv.text(12, 2, '  实测原始数据（上述星条图的来源，四列分别是三个基准与真实误差）')
    cv.text(13, 2, '      eps      ||X||_F        res/||C||      res/(||A||||X||)    真实相对误差')
    cv.text(14, 2, '      1e0      1.75e+00       1.3e-15        2.9e-16             1.2e-15')
    cv.text(15, 2, '      1e-2     1.15e+02       6.9e-14        2.6e-16             1.4e-13')
    cv.text(16, 2, '      1e-4     1.15e+04       6.0e-12        2.3e-16             1.1e-11')
    cv.text(17, 2, '      1e-6     1.15e+06       6.9e-10        2.7e-16             2.1e-09')
    cv.text(18, 2, '      1e-8     1.15e+08       5.1e-08        2.0e-16             8.7e-08')
    cv.text(20, 2, '  三句话（这是本章第一个反直觉结论，也是"速查"里最该记住的一条）')
    cv.text(21, 2, '      一  残差归一化到 ||C|| 会跟着 ||X|| 一起涨：它反映的只是后向稳定性')
    cv.text(22, 2, '      二  只有归一化到 (||A||+||B||) ||X|| 的残差是恒定的，那才是"算得准"')
    cv.text(23, 2, '      三  真实相对误差与第一列同阶，误差不是被残差掩盖，两者同源于 1/sep')
    cv.text(25, 2, '  工程含义：精度看 sep（或条件数），残差只能证明算法没写错')
    cv.text(26, 2, '      sep 趋于 0 时要做的不是换更精确的求解器，而是换问题的提法')
    cv.text(27, 2, '      例如平移坐标消除近共振、加正则化、或改用对 sep 不敏感的算法')
    return cv.render()


# ---------- ch34 block3：两种求解算法的代价 ----------
def fig_bs_vs_kron() -> list[str]:
    ROWS, COLS = 24, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  两个算法的代价：都是幂律，但阶数不同，于是交叉点决定一切')
    cv.text(1, 2, '      Bartels-Stewart（Schur + 逐列回代）   t ~ 2.6e-9 n^3   n 翻倍涨 8 倍')
    cv.text(2, 2, '      Kronecker 直接法（把 X 拉直成 n^2 维） t ~ 4.0e-11 n^6  n 翻倍涨 64 倍')
    cv.text(3, 2, '      两条直线相交于 n* = (c_BS/c_Kron)^(1/3) = 4.02 —— 比的是常数，不是阶')
    cv.text(5, 2, '  实测对照（由上面两式外推得到；时间单位是毫秒）')
    cv.text(6, 2, '      n = 5    :  BS 0.0003     Kron 0.0006      Kron 慢 1.9 倍')
    cv.text(7, 2, '      n = 10   :  BS 0.0026     Kron 0.040       Kron 慢 15.4 倍')
    cv.text(8, 2, '      n = 20   :  BS 0.0208     Kron 2.56        Kron 慢 122.9 倍')
    cv.text(9, 2, '      n = 50   :  BS 0.3254     Kron 624.91      Kron 慢 1920.6 倍')
    cv.text(10, 2, '      n = 100  :  BS 2.6029     Kron 39993.95    Kron 慢 15365 倍')
    cv.text(12, 2, '  局部指数实测（用相邻区间的耗时比反推指数，看它是否趋近理论值）')
    cv.text(13, 2, '      Bartels-Stewart：n 从 40 到 640 的四个区间给出 2.11 / 2.10 / 2.34 / 2.95')
    cv.text(14, 2, '                        指数随 n 增大单调趋近理论值 3（小 n 时固定开销占主导）')
    cv.text(15, 2, '      Kronecker      ：n 从 10 到 40 的五个区间给出 3.76 / 4.55 / 5.80 / 4.99 / 4.96')
    cv.text(16, 2, '                        在 4 到 6 之间波动（n 大后受内存带宽限制，指数会被压低）')
    cv.text(18, 2, '  实测原始耗时（单线程 + 取最小值，避开 BLAS 线程调度与缓存噪声）')
    cv.text(19, 2, '      Bartels-Stewart（ms）：0.940  4.069  17.400  88.166  682.342（n=40 到 640）')
    cv.text(20, 2, '      Kronecker（ms）      ：0.255  1.170  4.335   15.819  39.304  163.815')
    cv.text(22, 2, '  结论：交叉点小得惊人（n* = 4.02），只要 n >= 5 就该用 Schur 类算法')
    cv.text(23, 2, '      这正是 33.7.7 那条规则的应用：判断快慢不能只比阶，要比阶 + 常数 + 规模')
    return cv.render()


# ---------- ch34 block4：Riccati 族地图 ----------
def fig_riccati_map() -> list[str]:
    ROWS, COLS = 28, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Riccati 族地图：只差一个二次项，分成四支（未知量出现两次，故不能一次解完）')
    cv.text(1, 2, '      一般形式   A^T P + P A - P (二次项) P + Q = 0')
    cv.text(3, 2, '      二次项取什么，决定是哪一支、以及解有什么性质')
    cv.text(4, 2, '          B R^-1 B^T                  ->  CARE   连续 LQR    解 P > 0，闭环稳定')
    cv.text(5, 2, '          A^T P B (B^T P B + R)^-1   ->  DARE   离散 LQR    用 QZ 分解（辛铅笔）')
    cv.text(6, 2, '          B2 R^-1 B2^T - g^-2 B1B1^T ->  不定    H-infinity  解不保证正定，需 gamma 大')
    cv.text(7, 2, '          每步更新一次                ->  递推    Kalman      每步 O(n^3)，稳态即 DARE')
    cv.text(9, 2, '      退化的两端（这是本章最重要的一组对照）')
    cv.text(10, 2, '          二次项趋于 0（即 B = 0）    ->  Lyapunov  线性方程，无条件唯一解，O(n^3)')
    cv.text(11, 2, '          一般非线性 + 一般代价       ->  HJB       非线性 PDE，只能近似')
    cv.text(13, 2, '  求解的三条途径：复杂度都是 O(n^3)，区别全在步数（这是选算法的唯一判据）')
    cv.text(14, 2, '      Schur on Hamilton 矩阵    直接法，1 步           默认选择，scipy 就是这个')
    cv.text(15, 2, '      Kleinman 迭代             5~7 步，二次收敛       需要稳定的初值，否则原地踏步')
    cv.text(16, 2, '      值迭代                    25~81 步，几何收敛     不需要任何初值，但步数多 10 倍')
    cv.text(18, 2, '  Hamilton 矩阵为什么是枢纽（定理 34.9 把这个枢纽讲清楚了）')
    cv.text(19, 2, '      H 的左半平面 n 个特征值 -> 稳定不变子空间 -> P = X2 X1^-1 就是 CARE 的稳定解')
    cv.text(20, 2, '      且闭环极点 lambda(A - B K) 恰好等于 H 的那 n 个稳定特征值')
    cv.text(21, 2, '      于是"控制设计"与"矩阵谱分解"成了同一件事的两个说法')
    cv.text(23, 2, '  四个必须记住的判据（每条都对应一个常见的"解不出来"）')
    cv.text(24, 2, '      可镇定 + 可检测   ->  CARE 有唯一稳定解（P 对称正定）')
    cv.text(25, 2, '      gamma 大于阈值    ->  不定 Riccati 有解（这就是 H-infinity 的可行性条件）')
    cv.text(26, 2, '      可检测 + 可稳定   ->  递推收敛到 DARE 的稳态解（与初值 P_0 的选取无关）')
    cv.text(27, 2, '      B = 0             ->  退化为 Lyapunov，条件从"有条件下有"变成"无条件有"')
    return cv.render()


# ---------- ch34 block5：Hamilton 谱与闭环极点 ----------
def fig_hamilton_spectrum() -> list[str]:
    ROWS, COLS = 24, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  Hamilton 矩阵 H 的谱关于虚轴对称，左右各占一半（n = 4 时共 8 个特征值）')
    cv.text(1, 2, '      H 的构造：H = [[A, -B R^-1 B^T], [-Q, -A^T]]，是一个 2n 阶方阵')
    cv.text(2, 2, '      实测配对（lambda 与 -lambda 之和，理论上应恒为 0）')
    cv.text(3, 2, '           +3.645819             与 -3.645819             配对，和 =  2.2e-15')
    cv.text(4, 2, '           +1.910967 + 0.327725i 与 -1.910967 - 0.327725i 配对，和 =  1.8e-15')
    cv.text(5, 2, '           +1.910967 - 0.327725i 与 -1.910967 + 0.327725i 配对，和 =  1.8e-15')
    cv.text(6, 2, '           +1.108386             与 -1.108386             配对，和 = -4.4e-16')
    cv.text(7, 2, '      实部大于 0 的恰好 4 个、小于 0 的恰好 4 个，都等于 n，且无纯虚特征值')
    cv.text(8, 2, '      "无纯虚特征值"这一条就是 CARE 存在唯一稳定解的充要条件')
    cv.text(10, 2, '  用左半平面的稳定子空间重建 P（实测用 schur(H, sort=lhp)，维数 sdim = 4）')
    cv.text(11, 2, '      重建的 P 与标准求解器的 P 之差     1.5e-14（两条完全不同的代码路径）')
    cv.text(12, 2, '      重建 P 的 Riccati 残差              2.5e-14')
    cv.text(13, 2, '      P 的对称性误差 ||P - P^T||          9.1e-16')
    cv.text(14, 2, '      diag(T) 的稳定部分                  [-3.6458, -1.9110, -1.9110, -1.1084]')
    cv.text(15, 2, '      闭环谱 lambda(A - B K)              [-3.6458, -1.9110, -1.9110, -1.1084]')
    cv.text(17, 2, '  最后两行完全相同 —— 这就是定理 34.9 的第 4 条，也是本章最关键的一句话')
    cv.text(18, 2, '      LQR 设计里"选极点"这件事，本质上是"选 Hamilton 矩阵的哪一半谱"')
    cv.text(19, 2, '      工程含义：所有 Riccati 解不出来的麻烦，都是稳定不变子空间找不出来')
    cv.text(20, 2, '      具体表现：纯虚特征值（临界稳定）或子空间退化（X1 奇异，于是 P 爆炸）')
    cv.text(22, 2, '  一个副产品：这条定理让"控制"与"线性代数"共用同一套语言')
    cv.text(23, 2, '      所以调 LQR 权重时看到的极点移动，可以用 Hamilton 矩阵的谱移动来解释')
    return cv.render()


# ---------- ch34 block6：HJB 到 Lyapunov 的降级阶梯 ----------
def fig_hjb_ladder() -> list[str]:
    ROWS, COLS = 26, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  LQR 现场：四个方程是同一条链上的四层，每层都由上一层"退化"得到')
    cv.text(1, 2, '      第三层   HJB 方程        0 = min_u { L(x,u) + gradV . f(x,u) }')
    cv.text(2, 2, '      第一步   猜 V 的形式      因为问题关于 (x, u) 是二次的，故猜 V = x^T P x')
    cv.text(3, 2, '      第二步   对 u 求导        u* = -R^-1 B^T P x（这一步就是"求解器"）')
    cv.text(4, 2, '      第三步   回代 u*          整理后对一切 x 成立，于是括号内必须为零')
    cv.text(5, 2, '      第二层   CARE            A^T P + P A - P B R^-1 B^T P + Q = 0')
    cv.text(6, 2, '      第四步   令 B = 0        无法控制，或者预先固定增益 K')
    cv.text(7, 2, '      第一层   Lyapunov        A^T P + P A = -Q（线性，一次分解就算完）')
    cv.text(8, 2, '      第五步   看闭环谱        定理 34.9：lambda(A - B K) = H 的稳定特征值')
    cv.text(10, 2, '  一次"降级"到底丢掉了什么（每一层都比上一层弱，但都比上一层好算）')
    cv.text(11, 2, '      HJB 到一阶条件      丢掉"全局最优"（只对凸问题才等价，一般问题只是必要）')
    cv.text(12, 2, '      CARE 到 Lyapunov    丢掉"最优性"（只剩稳定性，最优性无从评估）')
    cv.text(13, 2, '      Lyapunov 到谱       什么也没丢（定理 34.6 是充要条件，两边完全等价）')
    cv.text(15, 2, '  反向读一遍（设计者的视角，这比正向读更有用）')
    cv.text(16, 2, '      想把问题变成"可解的线性方程" -> 去掉二次项（B = 0，或预先固定增益 K）')
    cv.text(17, 2, '      想保留"最优"但要能算       -> 停在 CARE（Schur 一次解完，O(n^3)）')
    cv.text(18, 2, '      只有"一般系统 + 一般代价"   -> 只能停在 HJB（网格或神经网络近似）')
    cv.text(20, 2, '  近似动态规划的全部内容：放弃精确解 HJB，改用迭代逼近值函数 V')
    cv.text(21, 2, '      线性问题：猜二次型一次成功      多项式系统：平方和规划（可用 SDP 解）')
    cv.text(22, 2, '      一般系统：参数化 V（神经网络）+ Bellman 残差训练（第 24 章）')
    cv.text(24, 2, '  一条重要的实践结论：能用 CARE 就不要碰 HJB')
    cv.text(25, 2, '      线性 + 二次代价 -> 直接解 CARE，完全不必写 PDE 也不需要打网格')
    return cv.render()


# ---------- ch34 block7：三种收敛类型 ----------
def fig_iter_rates() -> list[str]:
    ROWS, COLS = 26, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  三种收敛类型：同样降到 1e-12，步数相差 20 倍以上（这是选算法的第一判据）')
    cv.text(1, 2, '      幂律   e ~ C k^-2        降到 1e-12 需要约 1e6 步（次梯度法的量级）')
    cv.text(2, 2, '      几何   e ~ 0.488^k       比值恒为 0.48794，41 步到 1e-12（值迭代）')
    cv.text(3, 2, '      二次   e ~ C e^2         0.194 -> 4.0e-5 -> 3.3e-11 -> 6.4e-15，3 步')
    cv.text(5, 2, '  实测数据（同一问题：离散 LQR，n = 5，Q = I，R = 1，见例 34.8 与例 34.9）')
    cv.text(6, 2, '      值迭代的相邻比值从 k = 6 起严格恒为 0.48794（教科书级的几何收敛）')
    cv.text(7, 2, '      而 rho(A_cl)^2 = 0.698529^2 = 0.487943，与实测差 0.001%（这不是巧合）')
    cv.text(8, 2, '      所以几何收敛的收缩因子不是"调出来的"，而是闭环谱的平方')
    cv.text(9, 2, '      策略迭代的 e_k/e_{k-1}^2 稳定在同一量级（1e-3 到 1e-2），这就是二次收敛')
    cv.text(11, 2, '  三种类型对精度要求的敏感性（决定"要不要追求高精度"）')
    cv.text(12, 2, '      幂律：eps 从 1e-6 到 1e-12，步数涨 1000 倍（线性依赖，代价最高）')
    cv.text(13, 2, '      几何：eps 从 1e-6 到 1e-12，步数只涨 2 倍（对数依赖）')
    cv.text(14, 2, '      二次：eps 从 1e-6 到 1e-12，步数只多 1 步（双对数依赖，几乎免疫）')
    cv.text(16, 2, '  第 33 章 33.7.3 的表里只有前两列，第三列（二次）是本章补上的')
    cv.text(17, 2, '      放进那张表里，它应占据"几何列的最左端"（等效收缩因子趋于零）')
    cv.text(18, 2, '      单列出来是因为它的步数规律（双对数）与几何列（对数）差别太大')
    cv.text(20, 2, '  通用配方（两阶段法）：先用便宜的几何方法压到 1e-1 量级')
    cv.text(21, 2, '      再切到 Newton 类方法（二次收敛）把剩余位数一次拿完')
    cv.text(22, 2, '      代价：Newton 每步要解一个子问题（O(n^3)），且要求一个好初值')
    cv.text(24, 2, '  一个必须记住的负面事实：二次收敛的算法"快"是有条件的')
    cv.text(25, 2, '      初值不好时它可能退化成线性甚至原地踏步（例 34.9 的陷阱，且不报错）')
    return cv.render()


# ---------- ch34 block8：时滞特征方程的分支 ----------
def fig_delay_branches() -> list[str]:
    ROWS, COLS = 26, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  时滞特征方程的无穷多个根，全部由 Lambert W 的分支给出（tau = 1.0，共 33 个）')
    cv.text(1, 2, '      分支 k = -1 与 k = 0     实部 +0.214004（成对共轭，决定稳定性的一对）')
    cv.text(2, 2, '      分支 k = 1 与 k = -2     实部 -0.963018（模更大的模态，衰减更快）')
    cv.text(3, 2, '      分支 k = 2 与 k = -3     实部 -1.548198')
    cv.text(4, 2, '      分支 k = 3 与 k = -4     实部 -1.916727')
    cv.text(5, 2, '      分支 k = 4 与 k = -5     实部 -2.185506')
    cv.text(6, 2, '      规律：|k| 越大实部越负，所以只有最靠近 0 的几个分支决定稳定性')
    cv.text(7, 2, '      每个分支代回特征方程的余量都在 1e-41 量级（40 位精度下的纯舍入误差）')
    cv.text(8, 2, '      所以这 33 个根全部精确满足方程，分支枚举不需要任何筛选或剔除')
    cv.text(10, 2, '  临界时滞：一对复根穿越虚轴的位置（这是"失稳"的确切机制）')
    cv.text(11, 2, '      tau* = arccos(-a/b) / sqrt(b^2 - a^2) = arccos(-1/3) / sqrt(8) = 0.675511')
    cv.text(13, 2, '  实测扫描（最大实部随 tau 变化；主导分支恒为 k = -1，即那对共轭根）')
    cv.text(14, 2, '      tau = 0.300   max Re = -1.605999   稳定（离临界还很远）')
    cv.text(15, 2, '      tau = 0.500   max Re = -0.347556   稳定')
    cv.text(16, 2, '      tau = 0.670   max Re = -0.006916   稳定')
    cv.text(17, 2, '      tau = 0.675   max Re = -0.000634   稳定（临界的左侧）')
    cv.text(18, 2, '      tau = 0.676   max Re = +0.000605   不稳定（临界的右侧）')
    cv.text(19, 2, '      tau = 1.000   max Re = +0.214004   不稳定（与分支 k=0/-1 的实部一致）')
    cv.text(20, 2, '      tau = 3.000   max Re = +0.232173   不稳定（实部随 tau 不再单调）')
    cv.text(22, 2, '  实测穿越点落在 0.675 与 0.676 之间，与解析 tau* = 0.675511 吻合到四位有效数字')
    cv.text(23, 2, '  退化校验：tau 趋于 0 时 max Re 应趋于 -(a+b) = -4（实测 tau=1e-6 给 -4.000012）')
    cv.text(25, 2, '  相位视角：时滞环节增益为 1、相位为 -omega*tau，它不衰减信号只白送滞后')
    return cv.render()


# ---------- ch34 block9：协方差递推的两条命运 ----------
def fig_cov_recursion() -> list[str]:
    ROWS, COLS = 28, 112
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  误差协方差递推的两条命运：只看一件事 —— rho((I - K C) A) 是否小于 1')
    cv.text(1, 2, '  命运一：初值失配很大时，递推会自己"冷静下来"（收敛，rho < 1）')
    cv.text(2, 2, '      初值 P_0 = 10 I，稳态约 0.6 I，误差 ||P_k - P_inf||_F 的实测演化')
    cv.text(3, 2, '          k =  0      1.79e+01      （初值差得很远）')
    cv.text(4, 2, '          k =  5      1.88e-01      （已经降了两个量级）')
    cv.text(5, 2, '          k = 10      1.38e-03      （比值稳定在 0.3 附近）')
    cv.text(6, 2, '          k = 15      6.52e-06      （没有任何振荡或停滞的迹象）')
    cv.text(7, 2, '          k = 20      2.29e-08      （纯几何衰减，一直单调下降）')
    cv.text(8, 2, '          k = 27      9.06e-12      （跨 17 步的平均几何速率 = 0.330）')
    cv.text(9, 2, '      理论值 rho((I-KC)A)^2 = 0.58775^2 = 0.34545，与实测 0.330 吻合得很好')
    cv.text(10, 2, '      注意相邻比值在 0.14 到 0.83 之间剧烈波动 —— 多模态叠加时看平均速率')
    cv.text(12, 2, '  命运二：观测不到不稳定模态时，递推指数发散（rho >= 1，无法挽救）')
    cv.text(13, 2, '      A = diag(1.2, 0.9)，C = [0 1]（只观测第二模态，第一模态不稳定且不可观测）')
    cv.text(14, 2, '          k =  0      ||P_k||_F = 1.4142e+00')
    cv.text(15, 2, '          k =  5      ||P_k||_F = 7.3772e+00')
    cv.text(16, 2, '          k = 10      ||P_k||_F = 4.6824e+01')
    cv.text(17, 2, '          k = 20      ||P_k||_F = 1.8036e+03')
    cv.text(18, 2, '          k = 40      ||P_k||_F = 2.6512e+06')
    cv.text(19, 2, '          k = 80      ||P_k||_F = 5.7272e+12')
    cv.text(20, 2, '      从 k=40 到 k=80 涨 2.16e6 倍 = 1.44^40（第一模态每步乘 1.2^2 = 1.44）')
    cv.text(22, 2, '  模型失配时（Q 假设错了 3 倍）会怎样：不发散，但会系统性低估')
    cv.text(23, 2, '      滤波器自认为的稳态                2.52755')
    cv.text(24, 2, '      实际发生的稳态（固定错误增益）     9.48334      低估 3.75 倍')
    cv.text(25, 2, '      若知道真 Q 时的最优稳态            7.17702')
    cv.text(26, 2, '      失配的主要危害不是"性能变差"，而是"滤波器不知道自己变差了"')
    cv.text(27, 2, '  有界性来源（33.4.1 离散式）：Sigma_k <= ||Sigma_0|| rho(F)^(2k) + ||W||/(1-rho(F)^2)')
    return cv.render()


# ======================================================================
# 第 35 章：学习理论中的估计方法
# ======================================================================

# ---------- ch35 block0：泛化误差的两个来源 ----------
def fig35_risk_decomp() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  泛化误差的两个来源：方向相反、药方不同（先定病型，再定药）')
    cv.text(1, 2, '      总误差 R(f_hat) - R*  =  2 x 估计误差  +  近似误差')
    cv.text(3, 2, '      估计误差  <- 一致收敛不够（样本太少，或假设类太大）')
    cv.text(4, 2, '          症状：训练误差低、测试误差高，两者差距大')
    cv.text(5, 2, '          药方：加样本、加正则、降容量、早停（见 35.5）')
    cv.text(6, 2, '          标度：随 n 按 n^{-1/2} 下降，对数依赖容量（例 35.1）')
    cv.text(8, 2, '      近似误差  <- 假设类装不下真函数（模型表达能力不足）')
    cv.text(9, 2, '          症状：训练误差与测试误差都高，两者差距小')
    cv.text(10, 2, '          药方：加大模型、换特征、加深网络、换核（第 6 章）')
    cv.text(11, 2, '          标度：加数据几乎无效，是一条平台（例 35.16 p=1）')
    cv.text(13, 2, '      判断口诀：先看差距（定病型），再看绝对值（定严重度）')
    cv.text(14, 2, '          只盯测试误差一个数，无法区分这两种病（最常见误诊）')
    cv.text(16, 2, '      两种极限都有实测反例（例 35.16，多项式拟合 sin 目标）')
    cv.text(17, 2, '          类太小 p=1：n 从 50 涨到 3200（64 倍），risk 只降 7.7%')
    cv.text(18, 2, '          类太大 p=9：n=50 时 risk=0.14067，比 p=3 差 12 倍')
    cv.text(19, 2, '                        n=3200 时降到 0.00030，反超 p=3')
    cv.text(21, 2, '      交叉现象：p=3 与 p=9 在 n 约 200 处交叉，p=3 与 p=5 在 n 约 75 处')
    cv.text(22, 2, '          所以"哪个模型更好"没有绝对答案，必须连同 n 一起回答')
    cv.text(24, 2, '      一句话：估计误差是"数据不够"的病，近似误差是"模型不够"的病')
    cv.text(25, 2, '          两种病的药方向相反，因此混用一定治不好任何一种')
    return cv.render()


# ---------- ch35 block1：一条链、三个阶段 ----------
def fig35_learn_chain() -> list[str]:
    ROWS, COLS = 26, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  第 35 章的总路线：一条链、三个阶段、三种可计算性')
    cv.text(1, 2, '      数据 S  ->  算法 A  ->  假设 f_hat  ->  预测  ->  损失')
    cv.text(3, 2, '      第一段（35.2、35.3）：经验风险 R_hat 是可算的量')
    cv.text(4, 2, '          由样本直接平均得到，不需要知道真实分布 D')
    cv.text(5, 2, '      第二段（35.2-35.4）：从 R_hat 到 R 的泛化间隙')
    cv.text(6, 2, '          由容量控制（35.3），也由算法稳定性控制（35.4）')
    cv.text(7, 2, '          这一段是"不可算"的，只能给界，不能给值')
    cv.text(8, 2, '      第三段（35.5）：f_hat 的"身份"由隐式偏差决定')
    cv.text(9, 2, '          不是"多快到达"，而是"到达了哪一个极小元"')
    cv.text(10, 2, '      第四段（35.6）：随样本量 n 的下降阶（幂律指数）')
    cv.text(11, 2, '          这一段决定"还要多少标注预算"，是唯一能反推的量')
    cv.text(13, 2, '      三层的食用顺序：值 -> 界 -> 阶（现在 / 最坏 / 趋势）')
    cv.text(14, 2, '          值告诉你现在在哪（经验风险、CV 估计）')
    cv.text(15, 2, '          界告诉你最坏在哪（Hoeffding、VC、Rademacher）')
    cv.text(16, 2, '          阶告诉你往哪走（n^{-1}、n^{-2beta/(2beta+d)}）')
    cv.text(18, 2, '      只有值：不知道离最坏有多远；只有界：太松时不敢用')
    cv.text(19, 2, '      只有阶：不知道自己在渐近段的哪个位置（外推没有落脚点）')
    cv.text(21, 2, '      与第 28 章的分工：28 章是地图（为什么能泛化）')
    cv.text(22, 2, '                        本章是路书（算出数、选界、估样本量）')
    cv.text(24, 2, '      一句话：可算的只有 R_hat；本章给"R_hat 到 R"配界、身份与速度')
    return cv.render()


# ---------- ch35 block2：有限类界的两个标度律 ----------
def fig35_bound_scaling() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  有限类界的两个标度律：容量是对数，样本是平方根')
    cv.text(2, 2, '      规律一：对容量的依赖是"对数级"，极慢（n=10000 固定）')
    cv.text(3, 2, '          |H|=10      -> 界 0.01731（容量极小）')
    cv.text(4, 2, '          |H|=1000    -> 界 0.02302（容量适中）')
    cv.text(5, 2, '          |H|=1000000 -> 界 0.02958（容量极大）')
    cv.text(6, 2, '          容量涨 10 万倍（对数涨 11.5），界只涨 1.71 倍')
    cv.text(8, 2, '      规律二：对样本量的依赖是"平方根律"，极硬（|H|=1000 固定）')
    cv.text(9, 2, '          n=10000   -> 0.02302   （基准），此列最小')
    cv.text(10, 2, '          n=40000   -> 0.01151   （与首项之比 0.5000）')
    cv.text(11, 2, '          n=160000  -> 0.00575   （与首项之比 0.2500）')
    cv.text(12, 2, '          样本每乘 4，界恰好减半：这是 1/sqrt(n) 律最直观的露脸')
    cv.text(14, 2, '      两条规律合起来说了一件事：容量便宜，样本昂贵')
    cv.text(15, 2, '          容量不是敌人（对数级），样本才是硬约束（平方根级）')
    cv.text(16, 2, '          所以"把模型做大"的代价远小于"把数据砍半"的代价')
    cv.text(18, 2, '      但别忘了这只是"界"的标度，不是真实误差的标度（例 35.2 实测）：')
    cv.text(19, 2, '          理论界 0.2120，实测中位数 0.1307（界是中位数的 1.62 倍）')
    cv.text(20, 2, '          实测 95% 分位 0.1687，界仍松 26%（界偏保守）')
    cv.text(21, 2, '          理论承诺违反率 <= 5%，实测违反率 0.05%（小 100 倍）')
    cv.text(23, 2, '      一句话：界用来排序与判前提，不用来报数；报数要用 CV 或独立测试集')
    return cv.render()


# ---------- ch35 block3：VC 维的暴力验证 ----------
def fig35_vc_bruteforce() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  VC 维的暴力验证：穷举 2^m 种标号，逐个判线性可分')
    cv.text(1, 2, '      判据：存在 w,b 使 y_i (w.x_i + b) >= 1（用线性规划判可行性）')
    cv.text(3, 2, '      d 维线性分类器：理论 VC = d+1，实测完全吻合')
    cv.text(4, 2, '          d=1：m=1 可，m=2 可，m=3 不可  ->  VC = 2')
    cv.text(5, 2, '          d=2：m=2 可，m=3 可，m=4 不可  ->  VC = 3')
    cv.text(6, 2, '          d=3：m=3 可，m=4 可，m=5 不可  ->  VC = 4')
    cv.text(7, 2, '          每行的"可"恰好停在 m = d+1 处，一步都不多')
    cv.text(9, 2, '      易混点：单向阈值分类器 sign(x - t) 只有参数 t 一个')
    cv.text(10, 2, '          m=1：2 种标号全可打散（太弱，不说明问题）')
    cv.text(11, 2, '          m=2：4 种标号里有 1 种做不到（标号 +,- 需要 x1>t 且 x2<t）')
    cv.text(12, 2, '          m=3：8 种标号里有 4 种做不到（方向被固定死了）')
    cv.text(13, 2, '          结论：一个参数的模型，VC 维就是 1，不是 2')
    cv.text(15, 2, '      为什么 VC 维数的是"自由度"而不是"参数个数"：')
    cv.text(16, 2, '          sign(w x + b) 允许翻转方向，等价于两个单向阈值 -> VC=2')
    cv.text(17, 2, '          sign(x - t) 只允许一个方向              -> VC=1')
    cv.text(18, 2, '          参数个数相同（都含 1 个自由度加 1 个偏置），VC 维不同')
    cv.text(20, 2, '      与第 28 章的分工：定义与 Sauer 引理在 28.2.1-28.2.2')
    cv.text(21, 2, '          本章只给 28 章没有的"暴力数值验证"与"参数自由度"辨析')
    cv.text(23, 2, '      一句话：VC 维 = 这个类能记住多少任意标号，不是参数表有多长')
    return cv.render()


# ---------- ch35 block4：覆盖数的指数爆炸 ----------
def fig35_cover_growth() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  覆盖数：单位球的 eps-net 大小随维数指数爆炸（贪心构造实测）')
    cv.text(2, 2, '      eps = 0.50 时：（先看指数增长的量级）')
    cv.text(3, 2, '          d=1 -> net 大小 2，上界 (1+2/eps)^d = 5')
    cv.text(4, 2, '          d=2 -> net 大小 10，上界 25（上界很松）')
    cv.text(5, 2, '          d=3 -> net 大小 35，上界 125（上界很松）')
    cv.text(6, 2, '          d=5 -> net 大小 277，上界 3125（指数已显）')
    cv.text(7, 2, '      eps = 0.25 时：（eps 减半，检验 2^d 律）')
    cv.text(8, 2, '          d=2 -> 19（上界 81）      d=3 -> 129（上界 729）')
    cv.text(9, 2, '          d=5 -> 3241（上界 59049）（差 18 倍）')
    cv.text(11, 2, '      两条读法：（上界松但指数对，后者才可用）')
    cv.text(12, 2, '          上界与实测差 1~2 个数量级（常数因子），但指数增长规律一致')
    cv.text(13, 2, '          eps 减半 -> 体积乘 2^d：实测 1.90 / 3.69 / 11.70（d=2,3,5）')
    cv.text(14, 2, '              理论 2^d = 4 / 8 / 32，实测偏小（小 d 时有边界效应）')
    cv.text(16, 2, '      为什么这是进步：覆盖数是"几何量"，不是"数个数"')
    cv.text(17, 2, '          log N(eps) 自动体察"类很平滑""类落在低维流形上"这类结构')
    cv.text(18, 2, '          而 VC 维只给一个整数，看不见这些结构（见 28.2.4）')
    cv.text(20, 2, '      维数灾难在这里的准确含义：（d 每加 1 都要重新付一次）')
    cv.text(21, 2, '          d 每加 1，log N(eps) 就线性增加 d log(1/eps)')
    cv.text(22, 2, '          于是界里的对数项随 d 线性涨，n^{-1/2} 必须压过它')
    cv.text(23, 2, '          唯一出路：让"有效维数"远小于名义维数（第 27 章有效秩）')
    cv.text(25, 2, '      一句话：覆盖数把"类大不大"从数数换成了量体积，代价是要算 eps-net')
    return cv.render()


# ---------- ch35 block5：Rademacher 的精确标度 ----------
def fig35_rademacher_scale() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  线性类的 Rademacher 复杂度：精确的 n^{-1/2}，常数只依赖 d')
    cv.text(1, 2, '      取 ||w|| <= 1，则 sup 化为范数，R_n = E ||(1/n) sum sigma_i x_i||')
    cv.text(3, 2, '      实测（4000 次 Monte Carlo，x_i 取单位球面均匀点）：')
    cv.text(4, 2, '          n=50   ->  d=2: 0.12338    d=5: 0.13453    d=20: 0.14011')
    cv.text(5, 2, '          n=400  ->  d=2: 0.04465    d=5: 0.04783    d=20: 0.04954')
    cv.text(6, 2, '          n=6400 ->  d=2: 0.01115    d=5: 0.01187    d=20: 0.01234')
    cv.text(7, 2, '          1/sqrt(n)    0.14142 / 0.05000 / 0.01250')
    cv.text(9, 2, '      结论一：同一列内 R_n / (1/sqrt(n)) 恒定到 3 位有效数字')
    cv.text(10, 2, '          那就是说 R_n 与 1/sqrt(n) 的比值不随 n 变，只随 d 变')
    cv.text(11, 2, '      结论二：比值常数有闭式解释（可用各向同性高斯近似算出）')
    cv.text(12, 2, '          (1/n) sum sigma_i x_i 近似 N(0, I/(nd))')
    cv.text(13, 2, '          R_n = E||g||_d / sqrt(nd)，而 E||g||_d 约等于 sqrt(d)')
    cv.text(14, 2, '          有限 d 的修正给出常数：d=2 -> 0.8862，d=5 -> 0.9516')
    cv.text(15, 2, '          实测 0.892 / 0.951 / 0.987，理论 0.8862 / 0.9516 / 0.9880')
    cv.text(17, 2, '      结论三：尺度一次齐次（把 x_i 放大 c 倍，R_n 乘 c）')
    cv.text(18, 2, '          c=0.5 -> 0.023856（比值 0.5029）    c=4.0 -> 0.192000（4.0477）')
    cv.text(20, 2, '      三条结论合起来，就是 Rademacher 优于 union bound 的根本原因：')
    cv.text(21, 2, '          它把"类大不大"（进常数）与"样本多不多"（进 n^{-1/2}）彻底分离')
    cv.text(22, 2, '          而 union bound 的 log N 与 n 混在同一个根号里，无法分离')
    cv.text(24, 2, '      一句话：R_n = 常数(d) x n^{-1/2}；要降它只能加样本或缩小类的尺度')
    return cv.render()


# ---------- ch35 block6：beta 的衰减率决定界的存亡 ----------
def fig35_beta_decay() -> list[str]:
    ROWS, COLS = 28, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  稳定性界的存亡：beta 必须随 n 衰减，否则界发散')
    cv.text(1, 2, '      界 = 2beta + (2n beta + M) x sqrt(log(1/delta)/(2n))')
    cv.text(2, 2, '      关键结构：2n beta 这一项把 beta 放大了 n 倍（与 sqrt(1/n) 部分抵消）')
    cv.text(4, 2, '      情形一：beta = M/n（典型正则化算法，M=1, delta=0.05）')
    cv.text(5, 2, '          n=100    -> 2beta=0.02000   界=0.38716')
    cv.text(6, 2, '          n=1000   -> 2beta=0.00200   界=0.11811')
    cv.text(7, 2, '          n=10000  -> 2beta=0.00020   界=0.03692')
    cv.text(8, 2, '          n=100000 -> 2beta=0.00002   界=0.01163')
    cv.text(9, 2, '          界按 n^{-1/2} 下降（n 乘 100，界降 10.49 倍）：可用')
    cv.text(11, 2, '      情形二：beta = 0.01 固定（不随数据改善的算法）')
    cv.text(12, 2, '          n=100   -> 界 0.38716（此时仍可用）')
    cv.text(13, 2, '          n=1000  -> 界 0.83275（开始失效）')
    cv.text(14, 2, '          n=10000 -> 界 2.47999   （已超过 M=1，完全无信息）')
    cv.text(15, 2, '          n 增大界反而变大：这类算法不可学习')
    cv.text(17, 2, '      实测验证一（ridge 回归，lam=0.01，平方损失，|y|<=1）：')
    cv.text(18, 2, '          n=100 -> beta=2.926e-04，n x beta=0.02926')
    cv.text(19, 2, '          n=800 -> beta=3.760e-05，n x beta=0.03008')
    cv.text(20, 2, '          n x beta 稳定在 0.0295 附近（波动 <3%）：严格 beta 约 0.03/n')
    cv.text(22, 2, '      实测验证二（Nadaraya 型 k 近邻，k 固定）：')
    cv.text(23, 2, '          beta 不随 n 衰减 -> 落入情形二 -> 界发散')
    cv.text(24, 2, '          正确做法：k 必须随 n 增（例 35.15 实测 k 约 n^{0.8}）')
    cv.text(26, 2, '      一句话：稳定性界要求的不是"beta 小"，而是"beta 随 n 减到 o(n^{-1/2})"')
    return cv.render()


# ---------- ch35 block7：隐式偏差的三段行为 ----------
def fig35_max_margin_drift() -> list[str]:
    ROWS, COLS = 28, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  隐式偏差：可分数据上 logistic + GD 的三段行为（n=60, d=2）')
    cv.text(1, 2, '      参照：硬间隔 SVM 解 w_svm，||w_svm|| = 0.92360')
    cv.text(2, 2, '      优化：无正则 logistic 损失 + 全批次 GD，零初始化，lr=0.5，2 万步')
    cv.text(4, 2, '      第 1 段（t=0..5）：迅速分开数据（先把方向找准）')
    cv.text(5, 2, '          ||w||   0.0000 -> 1.1608      测试误差 1.0000 -> 0.0000')
    cv.text(6, 2, '          训练损失 6.93e-01 -> 8.15e-02（只降了一个数量级）')
    cv.text(7, 2, '      第 2 段（t=5..19999）：方向收敛，范数无界增长')
    cv.text(8, 2, '          ||w||   1.1608 -> 6.2446（一直在涨，从未停下）')
    cv.text(9, 2, '          cos(w, w_svm)  0.979255 -> 0.999653（夹角 1.5 度）')
    cv.text(10, 2, '          训练损失 8.15e-02 -> 9.96e-05（降 3 个数量级）')
    cv.text(11, 2, '          测试误差 0.0000 -> 0.0000（19994 步毫无变化）')
    cv.text(13, 2, '      第 3 段（隐式偏差的稳健性）：换四条优化路径，方向几乎不变')
    cv.text(14, 2, '          w0=0, lr=0.5,    2 万步   -> cos 0.999653，||w|| 6.245')
    cv.text(15, 2, '          w0=0, lr=0.1,   10 万步   -> cos 0.999658，||w|| 6.244')
    cv.text(16, 2, '          w0=0, lr=2.0,  6000 步   -> cos 0.999639，||w|| 6.398')
    cv.text(17, 2, '          w0 随机（尺度 3），2 万步   -> cos 0.970851，||w|| 8.076')
    cv.text(18, 2, '          步长相差 20 倍，前三条收敛到同一个方向（4 位有效数字一致）')
    cv.text(20, 2, '      为什么范数必须无界增长：可分数据上损失由最难样本主导')
    cv.text(21, 2, '          损失 约等于 C x exp(-||w|| x gamma)，gamma 为当前方向的最小间隔')
    cv.text(22, 2, '          实测 dln(loss)/d||w|| = -0.594963，同期 gamma = 0.546537')
    cv.text(23, 2, '          比值 1.0886（差 <10%，来自次难样本对加权平均的贡献）')
    cv.text(24, 2, '          所以 loss -> 0 要求 ||w|| -> 无穷：不是过拟合，是无界化')
    cv.text(26, 2, '      一句话：方向早已定，范数一直涨；泛化只看方向')
    return cv.render()


# ---------- ch35 block8：早停 = 谱滤波的 U 型 ----------
def fig35_early_stop_u() -> list[str]:
    ROWS, COLS = 28, 114
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  早停 = 谱滤波：训练误差单调降，population risk 是 U 型')
    cv.text(1, 2, '      设定：n=100, d=300（过参数化），噪声 0.5，信号落在前 20 个奇异方向')
    cv.text(2, 2, '      步长 lr = 0.1/s_max^2 = 1.3814e-04，零初始化')
    cv.text(4, 2, '          t=0     -> train 2.899155   risk 0.467632')
    cv.text(5, 2, '          t=5     -> train 1.244486   risk 0.203893')
    cv.text(6, 2, '          t=10    -> train 0.139176   risk 0.097921')
    cv.text(7, 2, '          t=25    ->          最优点      risk 0.040069')
    cv.text(8, 2, '          t=100   -> train 0.003749   risk 0.085024')
    cv.text(9, 2, '          t=1000  -> train 0.000000   risk 0.112719')
    cv.text(10, 2, '          t=无穷  -> train 0.000000   risk 0.112723（插值解）')
    cv.text(12, 2, '      三条读法（关于早停本身）：训练误差单调、risk 呈 U 型、解析式可验证')
    cv.text(13, 2, '          训练误差单调降到精确 0（d>n 可插值），完全看不出转折')
    cv.text(14, 2, '          risk 是 U 型：最优 t*=25，插值解的代价是最优的 2.81 倍')
    cv.text(15, 2, '          解析与真跑 GD 的逐元素最大偏差 <= 1.3e-15（四个 t 点全测）')
    cv.text(17, 2, '      机制：GD 在右奇异基上按方向解耦，收缩因子 r_j = 1 - lr s_j^2')
    cv.text(18, 2, '          大奇异值方向（信号在此）收敛快，小奇异值方向（噪声）极慢')
    cv.text(19, 2, '          所以"迭代数"就是一把带宽可调的"低通滤波器"')
    cv.text(20, 2, '          t 小 -> 只保留大方向（容量小，欠拟合风险）')
    cv.text(21, 2, '          t 大 -> 全方向都保留（容量大，过拟合风险）')
    cv.text(23, 2, '      与 L2 正则的关系：存在一一对应 t <-> lambda，给出同一个解')
    cv.text(24, 2, '          但 lr 与 t 通过 r_j = 1 - lr s_j^2 耦合，所以')
    cv.text(25, 2, '          "小步长跑很多步"与"大步长跑少数步"并不等价')
    cv.text(27, 2, '      一句话：训练轮数不是"跑够就好"的开关，而是必须调的超参数')
    return cv.render()


# ---------- ch35 block9：信号/噪声误差的交叉 ----------
def fig35_sig_noise_split() -> list[str]:
    ROWS, COLS = 28, 114
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  U 型的机制：信号方向误差单调降，噪声方向误差单调升，在 t* 交叉')
    cv.text(1, 2, '      把 risk 按右奇异基拆成两半：信号方向（前 20 维）与噪声方向（其余）')
    cv.text(3, 2, '          t=1     -> 信号误差 0.394223   噪声误差 0.000089   合计 0.394312')
    cv.text(4, 2, '          t=5     -> 信号误差 0.202011   噪声误差 0.001882   合计 0.203893')
    cv.text(5, 2, '          t=10    -> 信号误差 0.091742   噪声误差 0.006179   合计 0.097921')
    cv.text(6, 2, '          t=20    -> 信号误差 0.025556   噪声误差 0.017316   合计 0.042872')
    cv.text(7, 2, '          t=25    -> 信号误差 0.017024   噪声误差 0.023045   合计 0.040069')
    cv.text(8, 2, '          t=40    -> 信号误差 0.011002   噪声误差 0.038585   合计 0.049587')
    cv.text(9, 2, '          t=100   -> 信号误差 0.010611   噪声误差 0.074413   合计 0.085024')
    cv.text(10, 2, '          t=1000  -> 信号误差 0.010619   噪声误差 0.102100   合计 0.112719')
    cv.text(12, 2, '      三条读法（关于误差分解）：信号误差在降、噪声误差在升、两条曲线交叉')
    cv.text(13, 2, '          信号误差先快速下降，在 t 约 60-100 间触底约 0.0106')
    cv.text(14, 2, '              残余不是零：插值解把噪声在信号方向的投影也拟合了进去')
    cv.text(15, 2, '          噪声误差单调上升，从不回头（这就是"开始学噪声"）')
    cv.text(16, 2, '          两条曲线在 t 约 25 处交叉，交叉点就是 t*（合计最小）')
    cv.text(18, 2, '      为什么 t* 不等于"信号误差最小处"（那是 t 约 60）：')
    cv.text(19, 2, '          总代价 = 信号误差 + 噪声误差，最小化总代价要权衡两者')
    cv.text(20, 2, '          这是"偏差-方差权衡"在迭代维度上的精确版本')
    cv.text(22, 2, '      与模型容量的类比：（加大模型 对 跑更多步）')
    cv.text(23, 2, '          加大模型 <-> 跑更多步：都同时降低偏差、提高方差')
    cv.text(24, 2, '          早停 <-> 缩小模型：都在权衡点之前主动停下')
    cv.text(26, 2, '      一句话：最优停机点是两条曲线的交叉处，不是任何一条的极小处')
    return cv.render()


# ---------- ch35 block10：学习曲线的四种指数 ----------
def fig35_learning_curve() -> list[str]:
    ROWS, COLS = 26, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  学习曲线的幂律指数：四个情形都从 2beta/(2beta+d) 分化而来')
    cv.text(2, 2, '      统一公式：risk - risk* 约等于 n^{-alpha}，alpha = 2beta/(2beta+d)')
    cv.text(3, 2, '          分子记光滑（beta），分母再加维数（d）')
    cv.text(5, 2, '      四种情形：（参数化 / Lipschitz / C2 / 解析）')
    cv.text(6, 2, '          参数化正确设定（beta 无穷）：alpha = 1，常数 = sigma^2 p')
    cv.text(7, 2, '             实测（p=20, sigma^2=0.25）：risk 与 sigma^2 p/(n-p-1) 逐点吻合')
    cv.text(8, 2, '             n=400 -> 0.012807（理论 0.013193）；n=6400 -> 0.000805')
    cv.text(9, 2, '             尾段斜率 -0.998（涨 16 倍，降 15.91 倍）：渐近斜率确为 -1')
    cv.text(10, 2, '          Lipschitz 非参数（beta=1）：alpha = 2/(2+d)')
    cv.text(11, 2, '          C2 非参数（beta=2）：alpha = 4/(4+d)，d=1 时 = 0.8')
    cv.text(12, 2, '             实测（k 近邻，sin 目标，d=1）：log-log 斜率 -0.8704')
    cv.text(13, 2, '             实测最优 k：n=100 -> 15，n=6400 -> 461，标度 0.8236')
    cv.text(14, 2, '             理论 2beta/(2beta+d) = 0.8，吻合到 3%')
    cv.text(15, 2, '          解析（beta 无穷, d 维）：alpha -> 1，但常数极小')
    cv.text(17, 2, '      两条极限行为（都从同一个公式读出）：（同一个公式的两个端点）')
    cv.text(18, 2, '          beta -> 无穷：指数 -> 1，退化为参数化率')
    cv.text(19, 2, '          d -> 无穷：指数 -> 0，维数灾难（样本再多也没用）')
    cv.text(21, 2, '      实用推论：每加 1 维，达到同一精度所需样本至少乘 2^{1/alpha}')
    cv.text(22, 2, '          近似为 2^{1+d/(2beta)}；d=10, beta=2 时是 11.3 倍')
    cv.text(24, 2, '      一句话：分子记光滑、分母加维数；指数里每 1 个单位都是一次标注成本')
    return cv.render()


# ---------- ch35 block11：偏差-方差随 n ----------
def fig35_bias_var_n() -> list[str]:
    ROWS, COLS = 28, 114
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  偏差-方差权衡随 n 的走向：小模型是平台，大模型先炸后超')
    cv.text(1, 2, '      目标 sin(2 pi x)，x 在 [-0.5, 0.5] 均匀，噪声 0.3，p 阶多项式拟合')
    cv.text(2, 2, '      3000 个测试点，每个 (p, n) 组合重复 60 次，取平均')
    cv.text(4, 2, '          p=1  :  0.21279  0.19962  0.19711  0.19648   （n=50/200/800/3200）')
    cv.text(5, 2, '          p=3  :  0.01132  0.00635  0.00486  0.00453')
    cv.text(6, 2, '          p=5  :  0.01579  0.00281  0.00065  0.00018')
    cv.text(7, 2, '          p=9  :  0.14067  0.00486  0.00124  0.00030')
    cv.text(9, 2, '      三条读法（关于模型容量）：小模型是平台、大模型先炸后超、交叉点随 n')
    cv.text(10, 2, '          p=1 是平台：n 从 50 涨到 3200（64 倍），risk 只降 7.7%')
    cv.text(11, 2, '              加数据几乎无效，病根是"模型装不下 sin"（近似误差）')
    cv.text(12, 2, '          p=9 先炸后超：n=50 时 0.14067（比 p=3 差 12 倍）')
    cv.text(13, 2, '              n=3200 时 0.00030，反超 p=3 的 0.00453（快 15 倍）')
    cv.text(14, 2, '          交叉现象：p=3 与 p=9 在 n 约 200 处交叉，p=3 与 p=5 在 n 约 75 处')
    cv.text(16, 2, '      为什么"大模型更好"这句话不完整：（缺了 n 这个条件）')
    cv.text(17, 2, '          p=9 只在 n 足够大时更好；n=50 时它是最差的')
    cv.text(18, 2, '          所以选模型必须连同样本量一起考虑，不能只比容量')
    cv.text(20, 2, '      与 35.6.2 的幂律呼应：（大模型的风险曲线更陡）')
    cv.text(21, 2, '          p 固定 -> alpha 由"有效 beta"与 d 决定；p 越大 -> 有效 beta 越大')
    cv.text(22, 2, '          所以大模型的风险曲线更陡（n 依赖性强），但起点更高')
    cv.text(24, 2, '      一句话：小模型是平台（加数据无效），大模型是陡坡（数据一少就翻车）')
    return cv.render()


# ---------- ch35 block12：选哪条泛化界 ----------
def fig35_choose_bound() -> list[str]:
    ROWS, COLS = 34, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  选哪条泛化界：四步决策（自上而下，先满足前提的先用）')
    cv.text(2, 2, '      第 1 步：f 与数据独立吗（f 是事先定死的吗）')
    cv.text(3, 2, '          是 -> 用 Hoeffding（定理 35.2），最紧，直接算')
    cv.text(4, 2, '          否 -> 往下走（继续判断下一层条件）')
    cv.text(6, 2, '      第 2 步：算法能写出来吗（SGD？闭式解？还是黑盒）')
    cv.text(7, 2, '          能，且知道它 beta-稳定 -> 用稳定性界（定理 35.9）')
    cv.text(8, 2, '          不能 -> 往下走（继续判断下一层条件）')
    cv.text(10, 2, '      第 3 步：假设类有限吗？能算出 VC 维吗')
    cv.text(11, 2, '          有限 N -> union bound（定理 35.3）或 Massart（定理 35.7）')
    cv.text(12, 2, '          能算 VC -> VC 界（定理 35.4）（按维数给界）')
    cv.text(13, 2, '          都不行 -> 往下走（继续判断下一层条件）')
    cv.text(15, 2, '      第 4 步：能估 Rademacher 复杂度吗（采样 + 优化子问题）')
    cv.text(16, 2, '          能 -> Rademacher 界（定理 35.6），最紧、与数据耦合')
    cv.text(17, 2, '          不能 -> 用覆盖数（定理 35.5），或退回经验方法（CV）')
    cv.text(19, 2, '      兜底：什么都不满足 -> 用 CV 给"值"，用学习曲线给"阶"')
    cv.text(20, 2, '          但要标注"这是估计，不是保证"（见 35.7.2 的取舍表）')
    cv.text(22, 2, '      七条界的"信息含量"阶梯（从上到下越来越紧，信息越来越多）：')
    cv.text(23, 2, '          个数 N -> 维数 d -> 体积 N(eps) -> 噪声耦合 R_n -> 算法 beta')
    cv.text(24, 2, '          选择原则：从"信息最少"的那条起步，松到不能用再往下走')
    cv.text(26, 2, '      三个"不要"（都来自本章的实测反例）（不是经验之谈）')
    cv.text(27, 2, '          不要用训练误差当泛化误差（例 35.12：训练误差到精确 0）')
    cv.text(28, 2, '          不要把容量的界当预测值（例 35.2：界是中位数的 1.62 倍）')
    cv.text(29, 2, '          不要以为收敛快就泛化好（例 35.13：快 40 倍，误差大 2.14 倍）')
    cv.text(31, 2, '      一句话：能算的就别界，能界的就别猜；猜的时候标注"不是保证"')
    return cv.render()


# ======================================================================
# 第 36 章：综合项目与案例
# ======================================================================

# ---------- ch36 block0：七道工序与依赖图 ----------
def fig36_seven_steps() -> list[str]:
    ROWS, COLS = 17, 116
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  第 36 章的总路线：七道工序、两条并行支路、三个不可逆点')
    cv.text(1, 2, '      S1 定义交付物  ->  S2 建模与假设  ->  S3 立方程（第 34 章）')
    cv.text(2, 2, '      S4 求解        ->  输入是 S3 的方程，输出是数值解与残差')
    cv.text(3, 2, '      S5 配界        <-  只用 S4 的输出，工具来自第 33 章的不等式库')
    cv.text(4, 2, '      S6 估泛化      <-  只用 S4 的输出，工具来自第 35 章的估计框架')
    cv.text(5, 2, '      S7 结论与局限  <-  必须同时等 S5 与 S6 完成，否则缺一半')
    cv.text(6, 2, '      依赖结构：S1->S2->S3->S4 是唯一主干，串行，不可跳过')
    cv.text(7, 2, '                S5 与 S6 是主干上的两条并行支路，彼此不依赖')
    cv.text(8, 2, '                S7 是汇合点，它在 S5 与 S6 都完成前写不出来')
    cv.text(9, 2, '      三个不可逆点（错了之后无法从数值上发现，只能靠语义检查）：')
    cv.text(10, 2, '          ① S1 定义交付物：形状错了，后面每一步都在解正确但无用的问题')
    cv.text(11, 2, '          ② S2 建模：模型失配不会被残差诊断自动发现（见例 36.13）')
    cv.text(12, 2, '          ③ S7 措辞：限定词漏掉后，界从"在某模型内成立"变成"普遍成立"')
    cv.text(13, 2, '      主干四步与支路的成本量级（实测，见例 36.1）：')
    cv.text(14, 2, '          S3 纸面推导约 0 秒 | S4 一次求解 1e-4 秒 | S5+S6 验证 1e-1 秒起')
    cv.text(15, 2, '      一句话：主干是"一次性的"，支路是"可重复的"，成本差集中在支路上')
    return cv.render()


# ---------- ch36 block1：成本账 ----------
def fig36_cost() -> list[str]:
    ROWS, COLS = 26, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  成本账：解析界几乎免费，验证性重算贵三到四个数量级（例 36.1）')
    cv.text(2, 2, '      项目一（控制），以"解一次 CARE"为 1 倍基准：')
    cv.text(3, 2, '          S4 解一次 CARE（2x2）           = 0.26 毫秒    1.0 倍')
    cv.text(4, 2, '          S4 解一次对偶 CARE（观测器）    = 0.29 毫秒    1.1 倍')
    cv.text(5, 2, '          S5 Lyapunov 界的解析计算        = 0.016 毫秒   0.06 倍（几乎免费）')
    cv.text(6, 2, '          S5 跑一次仿真验证该界           = 5.5 秒       21000 倍')
    cv.text(7, 2, '          S6 时滞根扫描加二分 14 次       = 0.62 秒      2400 倍')
    cv.text(9, 2, '      项目二（估计），以"一次最小二乘"为 1 倍基准：')
    cv.text(10, 2, '          S4 一次最小二乘（30x5，QR）     = 0.037 毫秒   1.0 倍')
    cv.text(11, 2, '          S5 CRB 的解析计算               = 0.0018 毫秒  0.05 倍（几乎免费）')
    cv.text(12, 2, '          S6 覆盖率 Monte Carlo 2000 次   = 0.44 秒      12000 倍')
    cv.text(14, 2, '      项目三（跨域），以"解一次 DARE"为 1 倍基准：')
    cv.text(15, 2, '          S4 解一次 DARE（2x2）           = 0.73 毫秒    1.0 倍')
    cv.text(16, 2, '          S3/S4 辨识 (A,B)，N = 4000      = 0.073 毫秒   0.1 倍')
    cv.text(17, 2, '          S3 Q 函数回归一次（向量化）     = 2.4 毫秒     3.3 倍')
    cv.text(18, 2, '          S3 同上，按样本循环的朴素写法   = 0.63 秒      863 倍')
    cv.text(20, 2, '      四条读法：解析界免费，验证性重算贵一万倍')
    cv.text(21, 2, '          ① 解析界与求解同量级甚至更便宜，"配界很贵"是错的直觉')
    cv.text(22, 2, '          ② 贵的是把求解重复很多次，仿真与 Monte Carlo 都贵 1e3 到 1e4 倍')
    cv.text(23, 2, '          ③ 所以"省一步"应当省次数，而不是省公式（见 36.5.4 元规则①）')
    cv.text(24, 2, '          ④ 同一数学不同实现的差距（朴素/向量化 260 倍）与工序选择无关，但极易被误当成工序成本')
    return cv.render()


# ---------- ch36 block2：项目一总览 ----------
def fig36_ctrl_flow() -> list[str]:
    ROWS, COLS = 22, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  项目一（控制）总览：五道工序与它们各自产出的关键数字')
    cv.text(2, 2, '      S1/S2 定义与建模：二阶质量-弹簧-阻尼，m=1，k=2，c=0.5')
    cv.text(3, 2, '            交付物 = 状态反馈 K 加四句限定词（扰动界、时滞、参数、观测）')
    cv.text(5, 2, '      S2/S3 结构检验（例 36.3）：rank Wc = rank Wo = 2，两个 Gramian 都满秩')
    cv.text(6, 2, '            cond Wc = 2.0000，cond Wo = 2.9413，开环阻尼比 0.1768')
    cv.text(8, 2, '      S4 求解 CARE（例 36.4）：解、残差、Hamilton 谱三件都要看')
    cv.text(9, 2, '            P = [[1.934396, 0.236068], [0.236068, 0.812302]]')
    cv.text(10, 2, '            K = [0.236068, 0.812302]，残差 1.099e-15')
    cv.text(11, 2, '            Hamilton 谱 = 闭环极点，两者完全一致（三重验证通过）')
    cv.text(12, 2, '            闭环阻尼比由 0.1768 升到 0.4383，提高 2.48 倍')
    cv.text(14, 2, '      S4 求解对偶 CARE（例 36.5）：L = [7.221523, 26.075198]')
    cv.text(15, 2, '            观测器极点实部 -3.8608，比控制器快 5.88 倍（W/V = 1000）')
    cv.text(16, 2, '            复合 4 阶极点恰为两组极点之并，分离原理数值验证通过')
    cv.text(18, 2, '      S5 配界（例 36.6）：稳态上界 1.691818，实测峰值 0.383369，松 4.41 倍')
    cv.text(19, 2, '      S6 时滞（例 36.7）：临界时滞 tau* = 1.1592')
    cv.text(20, 2, '            tau -> 0 时根回到闭环极点，这是程序里的第一条自检断言')
    cv.text(21, 2, '      交付：K 与 tau* 加四条撤销条件，见 36.2.7 的四段式写法')
    return cv.render()


# ---------- ch36 block3：结构检验 ----------
def fig36_ctrl_struct() -> list[str]:
    ROWS, COLS = 18, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  结构检验：两个 Gramian 的秩与条件数（例 36.3）')
    cv.text(2, 2, '      Wc = [[0.5, 0], [0, 1]]，rank = 2，cond = 2.0000')
    cv.text(3, 2, '      Wo = [[1.125, 0.25], [0.25, 0.5]]，rank = 2，cond = 2.9413')
    cv.text(4, 2, '      开环极点 = -0.25 加减 1.391941 i，omega_n = 1.414214')
    cv.text(5, 2, '      开环阻尼比 zeta = 0.176777，欠阻尼，阶跃响应有明显振荡')
    cv.text(7, 2, '      三条读法：定性结论、阻尼比、尺度依赖性')
    cv.text(8, 2, '          ① "可控"只是定性结论，决定数值精度的是条件数')
    cv.text(9, 2, '             若 cond Wc 达到 1e6，Riccati 解的有效位数会掉到 1e-10 量级')
    cv.text(10, 2, '             此时残差检查依然通过，而解已经不准（见 34.2.2 的 sep 界限）')
    cv.text(11, 2, '          ② 开环阻尼比 0.1768 而不是 0，解释了闭环极点为何仍带虚部')
    cv.text(12, 2, '             LQR 提高阻尼但不消除振荡，闭环 zeta = 0.4383，提高 2.48 倍')
    cv.text(13, 2, '          ③ Gramian 的条件数依赖状态的单位尺度')
    cv.text(14, 2, '             把 x1 从米改成毫米会改掉 cond Wc 一个 mu^2 的因子')
    cv.text(15, 2, '             而"可控"这个定性结论不变；后面配出来的界也有同样的尺度依赖性')
    cv.text(16, 2, '      什么时候可以省这一步：A,B,C 为手写解析模型时只当抄错检查')
    cv.text(17, 2, '          来自辨识的 A,B 不可省，伪零点会让秩看起来满秩（见 36.5.2 判据①）')
    return cv.render()


# ---------- ch36 block4：CARE 三重验证 ----------
def fig36_ctrl_care() -> list[str]:
    ROWS, COLS = 17, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  CARE 的三重验证：残差、对称性、Hamilton 一致性（例 36.4）')
    cv.text(2, 2, '      第 (i) 项 残差 = 1.099e-15，是 P 尺度的 5.7e-16 倍')
    cv.text(3, 2, '          P 的尺度约 1.93，所以相对精度 5.7e-16，已达双精度极限')
    cv.text(4, 2, '          注意：残差小不等于解准（34.2.2），残差是必要条件而非充分条件')
    cv.text(5, 2, '      第 (ii) 项 对称性 = 0.000e+00，精确为 0，由解的唯一性保证')
    cv.text(6, 2, '      第 (iii) 项 Hamilton 谱 = -0.656151 加减 1.343702 i，与闭环极点一致')
    cv.text(7, 2, '          H = [[A, -B R^-1 B^T], [-Q, -A^T]]，取左半平面的那些谱')
    cv.text(8, 2, '          这一项保证取到的是稳定解，只做 (i) 无法排除另一个解')
    cv.text(10, 2, '      解的量：P = [[1.934396, 0.236068], [0.236068, 0.812302]]')
    cv.text(11, 2, '          P 的特征值 0.764660 与 1.982038，全为正，故 P 正定')
    cv.text(12, 2, '          cond P = 2.592，与 cond Wc = 2.000 同量级，这不是巧合')
    cv.text(14, 2, '      写报告的纪律：三项必须同时报，只报残差是最常见的偷工')
    cv.text(15, 2, '          只报残差的项目，会在 CARE 存在两个解时静默地取到不稳定解')
    return cv.render()


# ---------- ch36 block5：观测器与分离原理 ----------
def fig36_ctrl_obs() -> list[str]:
    ROWS, COLS = 19, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  观测器：对偶 CARE 与分离原理的数值验证（例 36.5）')
    cv.text(2, 2, '      过程噪声强度 W = 1.000，量测噪声强度 V = 0.0010，比值 W/V = 1000')
    cv.text(3, 2, '      Po = [[0.007222, 0.026075], [0.026075, 0.215783]]')
    cv.text(4, 2, '      L = [7.221523, 26.075198]，观测器极点 -3.860762 加减 4.096398 i')
    cv.text(5, 2, '      控制器极点实部 -0.6562，观测器实部 -3.8608，比值 5.88 倍')
    cv.text(6, 2, '      复合 4 阶极点恰为两组极点之并，分离原理被一次性验证')
    cv.text(8, 2, '      三条读法：分离是数学性质，快慢是工程性质')
    cv.text(9, 2, '          ① 分离原理允许控制器与观测器分别设计，不必联立解 4 阶方程')
    cv.text(10, 2, '             但它只是数学性质，不保证工程性能，见下一条')
    cv.text(11, 2, '          ② 第一版取 W = V = 1，观测器实部只有控制器的一半')
    cv.text(12, 2, '             四个极点依然构成并集，但"控制器设计得好"已失去意义')
    cv.text(13, 2, '             所以"观测器快于控制器"必须主动检查，不能靠原理默认')
    cv.text(14, 2, '          ③ L 的量级完全由 W/V 决定，L2 = 26.08 意味着量测噪声被放大 26 倍')
    cv.text(15, 2, '             它会经 u = -K x_hat 进入执行器，这是 Kalman 权衡的具体形态')
    cv.text(17, 2, '      一句话：分离原理保证极点，不保证"好"；快慢比要自己查')
    return cv.render()


# ---------- ch36 block6：Lyapunov 圈界 ----------
def fig36_ctrl_bound() -> list[str]:
    ROWS, COLS = 19, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  S5 配界：Lyapunov 圈界与它的松紧比（例 36.6）')
    cv.text(2, 2, '      取 V = x^T P x，沿闭环求导，令 dV/dt = 0 得不变椭球')
    cv.text(3, 2, '          稳态上界 = 2 |P B| / lambda_min(Q + K^T R K)')
    cv.text(4, 2, '          实测 lambda_min = 1.000000，|P B| = 0.845909')
    cv.text(5, 2, '          代入得上界 1.691818，这就是要写进报告的那个数')
    cv.text(6, 2, '      真跑仿真：d = sin(3t)，|d| <= 1，t > 20 后的峰值 0.383369')
    cv.text(7, 2, '          界 / 实测 = 4.41 倍，界成立且松 4.41 倍')
    cv.text(9, 2, '      松从哪里来（三条，都是范数链的固有损失）：')
    cv.text(10, 2, '          ① 用 |d| 的最坏方向代替实际方向，而 d 只作用在一个通道方向上')
    cv.text(11, 2, '          ② 用 lambda_min 代替整个矩阵，丢掉 Q + K^T R K 与 P B 的方向对齐')
    cv.text(12, 2, '          ③ 用稳态代替瞬态峰值，忽略了初始条件的瞬态贡献')
    cv.text(14, 2, '      三条结论：松紧比的量级、假收益、可用性判据')
    cv.text(15, 2, '          ① 松紧比是 1 到 10 的量级，不是 1e3；松 1e3 倍说明用错了工具')
    cv.text(16, 2, '          ② 调 Q 让界变小是假收益：界与实测会同比例缩小，比值不变')
    cv.text(17, 2, '          ③ 可用性判据：界的绝对值应当小于"次优方案的代价"')
    cv.text(18, 2, '             本例 1.69 远小于"不加控制时发散"的代价，所以这个界有用')
    return cv.render()


# ---------- ch36 block7：时滞临界值 ----------
def fig36_ctrl_delay() -> list[str]:
    ROWS, COLS = 21, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  S6 时滞：真实的稳定边界，max Re(s) 对 tau 并不单调（例 36.7）')
    cv.text(2, 2, '      特征方程（手算展开 det）：g(s) = s^2 + 0.5 s + 2 + (k2 s + k1) e^(-s tau)')
    cv.text(3, 2, '          k1 = 0.236068，k2 = 0.812302，这是一条拟多项式方程')
    cv.text(5, 2, '      根扫描结果：根数与 max Re(s) 都随 tau 变化')
    cv.text(6, 2, '          tau = 0.0：2 个根，max Re = -0.656151，稳定（等于闭环极点）')
    cv.text(7, 2, '          tau = 0.2：2 个根，max Re = -0.742838，稳定')
    cv.text(8, 2, '          tau = 0.4：3 个根，max Re = -0.771968，稳定')
    cv.text(9, 2, '          tau = 0.6：5 个根，max Re = -0.509836，稳定')
    cv.text(10, 2, '          tau = 0.8：5 个根，max Re = -0.235192，稳定')
    cv.text(11, 2, '          tau = 1.0：5 个根，max Re = -0.074850，稳定')
    cv.text(12, 2, '          tau = 1.2：7 个根，max Re = +0.014064，不稳定')
    cv.text(13, 2, '          tau = 1.4：7 个根，max Re = +0.062379，不稳定')
    cv.text(14, 2, '      二分 14 次得 tau* = 1.1592（该处 max Re = -4.2e-05）')
    cv.text(16, 2, '      四条读法：根数、非单调、自检、这一步不可省')
    cv.text(17, 2, '          ① 根数随 tau 从 2 涨到 7，这是拟多项式的本质，只数 n 个根是错的')
    cv.text(18, 2, '          ② max Re 对 tau 不单调，因为主导根在不同分支之间跳')
    cv.text(19, 2, '          ③ tau -> 0 必须回到闭环极点，这是程序的第一条自检断言')
    cv.text(20, 2, '          ④ 这一步不能省：Lyapunov 界对任意 tau > 0 都报"稳定"')
    return cv.render()


# ---------- ch36 block8：项目二总览 ----------
def fig36_est_flow() -> list[str]:
    ROWS, COLS = 22, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  项目二（估计）总览：交付物是两个不同的区间，不能混（例 36.8）')
    cv.text(2, 2, '      设定：d = 5 维参数，n = 30 个样本，噪声标准差 sigma = 0.5')
    cv.text(3, 2, '          刻意让设计矩阵第 1、2 列相关，使 cond(X^T X) = 43.546')
    cv.text(5, 2, '      S1 交付物的两个候选（平均宽度差 1.44 倍）：')
    cv.text(6, 2, '          参数置信区间：theta_j 加减 t * sqrt(s^2 * [(X^T X)^-1]_jj)')
    cv.text(7, 2, '          预测区间：y_new 加减 t * sqrt(s^2 * (1 + x_new^T (X^T X)^-1 x_new))')
    cv.text(8, 2, '          多出来的那个 1 是新样本自身的噪声，绝对不可省')
    cv.text(10, 2, '      S4 一次估计（例 36.9）：s^2 = 0.215861，真值 0.25，偏低 13.7%')
    cv.text(11, 2, '          这 13.7% 只有 0.48 个标准差（s^2 相对标准差为 sqrt(2/25) = 0.283）')
    cv.text(13, 2, '      S5 配界（例 36.10）：CRB 对角与实测方差的比值落在 0.988 到 1.019')
    cv.text(14, 2, '          说明最小二乘是有效估计器，而这一步只花 0.0018 毫秒')
    cv.text(15, 2, '      S5 区间（例 36.11）：名义 0.95，实测覆盖率 0.9545')
    cv.text(16, 2, '          平均宽度 2.812522 可拆成三个因子：2 sigma = 1.959964，')
    cv.text(17, 2, '          乘分位数因子 1.050804，再乘参数不确定因子 1.393387')
    cv.text(18, 2, '      S3/S4 递推（例 36.12）：RLS 与批量 LS 的最大偏差 7.776e-07')
    cv.text(19, 2, '          注意 RLS 的 P 收敛到 (X^T X)^-1，不是 s^2 (X^T X)^-1，用前须乘 s^2')
    cv.text(20, 2, '      S6 压力测试（例 36.13）：失配 gamma = 1 时覆盖率 0.8887，宽度涨 1.99 倍')
    cv.text(21, 2, '      交付：预测区间加"模型必须线性"这一条撤销条件，见 36.3.7')
    return cv.render()


# ---------- ch36 block9：LS 达到 CRB ----------
def fig36_est_crb() -> list[str]:
    ROWS, COLS = 17, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  LS 达到 CRB：一个检验同时回答三个问题（例 36.10）')
    cv.text(2, 2, '      CRB 对角 = [0.120525, 0.108081, 0.009620, 0.009512, 0.021748]')
    cv.text(3, 2, '      3000 次 Monte Carlo 的实测方差（逐参数对照）：')
    cv.text(4, 2, '          [0.119134, 0.108001, 0.009683, 0.009689, 0.021646]')
    cv.text(5, 2, '      实测 / CRB = [0.9885, 0.9993, 1.0065, 1.0186, 0.9953]')
    cv.text(7, 2, '      Monte Carlo 的方差估计相对标准差 = sqrt(2/3000) = 2.58%')
    cv.text(8, 2, '          所以最大的偏差 1.86% 只有 0.72 个标准差，完全在抽样噪声内')
    cv.text(10, 2, '      三条读法：有效性、一箭三雕、下界与自检')
    cv.text(11, 2, '          ① 五个比值都在 1 附近，最小二乘达到 CRB，即它是有效估计器')
    cv.text(12, 2, '          ② 这一步的成本是 0.0018 毫秒，却一次性回答三个问题：')
    cv.text(13, 2, '             估计器是否有效、噪声模型是否正确、Monte Carlo 规模是否够')
    cv.text(14, 2, '          ③ CRB 是下界不是预测值，比值 1.0186 超过 1 并不违反 CRB')
    cv.text(15, 2, '             若噪声是重尾的，这个检验会失败，所以它同时是噪声模型的自检')
    cv.text(16, 2, '      一个纪律：报比值时必须同时报 Monte Carlo 的标准误，见 36.4.5')
    return cv.render()


# ---------- ch36 block10：覆盖率压力测试 ----------
def fig36_est_coverage() -> list[str]:
    ROWS, COLS = 20, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  S6 压力测试：失配的代价先表现为区间变宽，其次才是覆盖率下降')
    cv.text(2, 2, '      真模型加一个二次项 gamma * x1^2，估计式仍然只用 X（例 36.13）')
    cv.text(3, 2, '      gamma   E[s^2]     平均半宽    覆盖率   参数偏差范数')
    cv.text(4, 2, '        0.0   0.250618   2.843453    0.9553   0.013120')
    cv.text(5, 2, '        0.2   0.280195   2.999005    0.9400   0.175411')
    cv.text(6, 2, '        0.5   0.435072   3.763554    0.9093   0.421009')
    cv.text(7, 2, '        1.0   0.993155   5.653964    0.8887   0.816472')
    cv.text(9, 2, '      机制可以完全算清：s^2 多出的部分是投影之后的确定值')
    cv.text(10, 2, '          delta s^2 = gamma^2 * |(I - H) z|^2 / (n - d)')
    cv.text(11, 2, '          实测 |(I - H) z|^2 / (n - d) = 0.743411')
    cv.text(12, 2, '          gamma = 1 时理论 s^2 = 0.25 + 0.743411 = 0.993411')
    cv.text(13, 2, '          实测 E[s^2] = 0.993155，吻合到三位有效数字')
    cv.text(15, 2, '      四条读法：被救回、投影、偏差比值、正确做法')
    cv.text(16, 2, '          ① 覆盖率只掉到 0.8887，是因为 s^2 自动膨胀把区间撑宽了 1.99 倍')
    cv.text(17, 2, '             若验收标准是"覆盖率不低于 0.90"，插值看 gamma 约 0.7 才跌破 0.90')
    cv.text(18, 2, '          ② 若把 z 当成随机的，会把 delta s^2 算成 2(n-d)/n = 1.666667，高估 2.24 倍')
    cv.text(19, 2, '          ③ 真正的失配指标是"偏差 / 标准误"，本例这个比值差了近一个数量级')
    return cv.render()


# ---------- ch36 block11：两条数据驱动路线 ----------
def fig36_xdom() -> list[str]:
    ROWS, COLS = 24, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  项目三：两条数据驱动路线，误差传递路径不同（例 36.15 到 36.17）')
    cv.text(2, 2, '      真模型：离散 LTI，开环谱半径 0.950000，闭环谱半径 0.861014')
    cv.text(3, 2, '          最优 K* = [0.204821, 0.614357]，最优代价 J* = 4.487328')
    cv.text(5, 2, '      路线 A 两步法：先辨识 (A,B)，再解离散 ARE')
    cv.text(6, 2, '          N = 100：|A_hat - A| = 1.471e-02，|K - K*| = 8.266e-03')
    cv.text(7, 2, '          N = 4000：|A_hat - A| = 7.167e-04，|K - K*| = 1.664e-04')
    cv.text(8, 2, '          误差一次性传进 ARE，没有修正机会，但每步便宜（0.073 毫秒）')
    cv.text(10, 2, '      路线 B 一步法：Q 函数参数化加纯数据策略迭代，全程不解 (A,B)')
    cv.text(11, 2, '          N = 100：第 1 次迭代后 |K - K*| = 1.719e-02，之后停滞')
    cv.text(12, 2, '          N = 4000：第 1 次 3.959e-03，第 2 次 1.706e-03，之后停滞')
    cv.text(13, 2, '          第 1 次迭代改进最大，之后被 H_uu 的估计误差卡住')
    cv.text(14, 2, '          成本是两步法的 33 倍（2.4 毫秒），而 N = 4000 时误差反而大 10 倍')
    cv.text(16, 2, '      两条路线在代价意义上打平：J / J* 都在 1.001 以内')
    cv.text(17, 2, '          原因是 J 对 K 在最优点的导数为零，损失是 O(|K - K*|^2)')
    cv.text(19, 2, '      选择判据：三条，按数据量与模型可得性分')
    cv.text(20, 2, '          ① (A,B) 可辨识且数据量中等以上 -> 选两步法，便宜、可解释、误差可控')
    cv.text(21, 2, '          ② 不允许"先辨识再控制"或模型形式写不出来 -> 选一步法')
    cv.text(22, 2, '          ③ 数据量大且 H_uu 条件数好 -> 一步法可以省掉建模这一整道工序')
    cv.text(23, 2, '      一条纪律：表中的数是四组不同随机数据的单次实现，不能用来拟合幂律')
    return cv.render()


# ---------- ch36 block12：省略决策树 ----------
def fig36_omit_tree() -> list[str]:
    ROWS, COLS = 24, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  省略决策树：从最贵的工序开始问，省最贵的收益最大（36.5.3）')
    cv.text(2, 2, '      第 1 问：交付物里有没有"对新样本的预测"？')
    cv.text(3, 2, '          有 -> S6 估泛化与样本量必须做（覆盖率或样本量反推）')
    cv.text(4, 2, '          没有 -> 转到第 2 问，看交付物是不是控制器')
    cv.text(5, 2, '      第 2 问：交付物是不是一个控制器或策略？')
    cv.text(6, 2, '          是 -> S6 只保留"边界条件扫描"：扰动界、时滞、参数不确定性')
    cv.text(7, 2, '                  至少要扫一项，否则等于没有 S6（见例 36.7）')
    cv.text(8, 2, '          不是 -> 转到第 3 问，看模型形式能否写出来')
    cv.text(9, 2, '      第 3 问：模型形式写不出来，或不允许先辨识再控制？')
    cv.text(10, 2, '          是 -> S2 建模可以由数据替代（一步法，见例 36.16）')
    cv.text(11, 2, '                  代价：误差被中间量的条件数卡住，需要更大的数据量')
    cv.text(12, 2, '          不是 -> S2 建模与 S3 立方程都必须保留')
    cv.text(13, 2, '      第 4 问：S5 的解析界能不能省？（这一问答案唯一）')
    cv.text(14, 2, '          不能省。它的成本只有求解一次的 0.05 到 0.06 倍（见例 36.1）')
    cv.text(15, 2, '          唯一可省的是"验证界的那次重算"，而它是精度决策不是二值决策')
    cv.text(16, 2, '      第 5 问：S7 的撤销条件能不能省？（同样唯一）')
    cv.text(17, 2, '          不能省。它是唯一能指导后续工作的那一段（见 36.1.2 第三个不可逆点）')
    cv.text(19, 2, '      三条元规则的落点：每条都对应上面某一问')
    cv.text(20, 2, '          ① 省次数不省公式 -> 落到第 4 问，即永远要配解析界')
    cv.text(21, 2, '          ② 省一步就要把它的假设写进撤销条件 -> 落到第 1、2 问')
    cv.text(22, 2, '          ③ 省掉的量必须能被别的量交叉验证 -> 落到第 3 问与 S7 自查')
    cv.text(23, 2, '      若三条都做不到，这个项目就没有任何能证伪的环节，见 36.6.4')
    return cv.render()


# ---------- ch36 block13：三个界的松紧比 ----------
def fig36_loose() -> list[str]:
    ROWS, COLS = 21, 118
    cv = Canvas(ROWS, COLS)
    cv.text(0, 2, '  三个"界 / 实测"比值：松紧由"要在多大的集合上一致成立"决定')
    cv.text(2, 2, '      项目一（Lyapunov 圈界）：界 1.691818，实测 0.383369，比值 4.41')
    cv.text(3, 2, '          集合 = 所有满足 |d| <= 1 的扰动，方向任意')
    cv.text(4, 2, '      项目二（CRB 对参数方差）：比值 0.988 到 1.019')
    cv.text(5, 2, '          集合 = 单个参数，且噪声分布已知为高斯')
    cv.text(6, 2, '      第 35 章 35.2.3（例 35.2，有限类泛化界）：界与实测风险之比约 1.62')
    cv.text(7, 2, '          集合 = 一个有限假设类，样本独立同分布')
    cv.text(9, 2, '      两条读法：紧与松的分界、界的可用性判据')
    cv.text(10, 2, '          ① 紧的一类是"已知分布加单个目标"，松的一类是"任意方向加一致成立"')
    cv.text(11, 2, '             这不是工具的缺陷，而是一致性要求付出的定价（33.1.1）')
    cv.text(12, 2, '          ② 可用性判据：界的绝对值应当小于"次优方案的代价"')
    cv.text(13, 2, '             松 1e3 倍以上的界在决策上等价于没有界，它不排除任何可能')
    cv.text(15, 2, '      一张换算表（用于快速判断自己的界是否还在可用区间）：')
    cv.text(16, 2, '          比值 1 到 2      很紧，可直接用于定量决策')
    cv.text(17, 2, '          比值 2 到 10     常规，可用于比较方案优劣，不用于报数')
    cv.text(18, 2, '          比值 10 到 100   偏松，只能用于"证明有界"')
    cv.text(19, 2, '          比值 1e3 以上    等价于无界，应当换工具或换建模方式')
    cv.text(20, 2, '      注意：这张表只适用于"界与实测同量纲"的情形，跨量纲比较无意义')
    return cv.render()


# ======================================================================
# 附录 A：常用积分表与特殊函数
# ======================================================================
def _figA(lines: list[str]) -> list[str]:
    """附录 A 的图：逐行贴文本（列位置已手工排好）。"""
    cv = Canvas(len(lines), 120)
    for i, ln in enumerate(lines):
        cv.text(i, 0, ln)
    return cv.render()


# ---------- appA block0：十条主族地图 ----------
def figA_families() -> list[str]:
    return _figA([
        '    附录 A 十条主族地图——形态决定族，族决定手段与陷阱（92 条）',
        '',
        '      F1  高斯族        e^{-ax^2} 及其多项式、平移、乘积',
        '           手段：配方 + 高斯积分  |  陷阱：a 必须大于 0，b^2/(4a) 别丢',
        '           落点：概率密度、核方法、热核、Gauss 求积权函数',
        '      F2  幂×指数       x^{s-1} e^{-ax} 及 (1-x)^{b-1}',
        '           手段：Gamma 与 Beta 直接套  |  陷阱：s 必须大于 0；参数要移动一位',
        '           落点：Gamma/Beta 家族、矩、贝叶斯共轭',
        '      F3  幂×对数       x^a (1-x)^b ln x 及 ln x/(1+x^2)',
        '           手段：对 Beta 参数求导  |  陷阱：结果常常是 0，要用对称性而不是硬算',
        '           落点：熵与 KL、最大熵、对数域数值计算',
        '      F4  有理函数      1/(x^2+a^2)^n、x^{p-1}/(1+x^q)',
        '           手段：部分分式或 Beta 一步  |  陷阱：0<p<q 是硬条件，p 趋 q 时发散',
        '           落点：留数与围道（第 30 章）、系统频响、稳定性判据',
        '      F5  指数×三角     e^{-ax} 乘 sin/cos、乘 1/x',
        '           手段：配方配对成复数指数  |  陷阱：结果里必有 e^{-ab}，b=0 时退化',
        '           落点：二阶系统冲激响应、阻尼振荡能量、拉普拉斯反变换',
        '      F6  三角有理/Si Ci sin x/x、1/(a+b cosθ)、Bose-Fermi 型',
        '           手段：Dirichlet 判法 + 特殊函数  |  陷阱：条件收敛，绝对积分发散',
        '           落点：傅里叶变换、采样、信息论微分熵、量子统计',
        '      F7  根式与椭圆   1/sqrt(1-x^2)、sqrt(1-x^4)、1/(x^2+a^2)^{3/2}',
        '           手段：三角换元落到 K(k) 与 E(k)  |  陷阱：K 的模数 k 与参数 m=k^2 差一层',
        '           落点：周期与摆、天线与散射、曲面弧长、椭圆滤波器',
        '      F8  振荡/Bessel  J_0、Fresnel、sin(x^2)',
        '           手段：只谈"到 X 为止"或加指数正则化  |  陷阱：直接 quad 会报错或给出错值',
        '           落点：衍射、色散、射频链、Slepian 与锥形核',
        '      F9  统计型        正态/chi^2/Beta/t 密度及其矩',
        '           手段：全部归结为 F1/F2 的尺度变换  |  陷阱：归一化常数与分数自由度',
        '           落点：区间估计、覆盖率、集中不等式（第 8 章）',
        '      F10 学习与核      核内积、卷积、特征函数、logistic 配分',
        '           手段：高斯核闭式 + 对数域  |  陷阱：logistic 族在无穷远处溢出',
        '           落点：RKHS（第 6 章）、NTK（第 27 章）、逻辑回归与 ELBO（第 11 章）',
        '',
        '      读法：先用形态定位族，再用条件列筛条目，最后用校验值核对一次',
        '      若三族都定位不到：转附录 B 的决策树；若落点是 F4 且有理：优先转附录 C',
    ])

# ---------- appA block1：振荡截断的两个区间 ----------
def figA_trunc() -> list[str]:
    return _figA([
        '    附录 A 插图：振荡积分截断的两个区间——理论收敛区与求积器失效区',
        '',
        '      被积函数          X         周期数      实际误差     自报 abserr    判读',
        '      sin(t)/t         1e+05     15915      9.99e-06     1.95e-08      低估 3 个数量级',
        '      sin(t)/t         2e+05     31831      4.99e-06     2.14e-08      低估 2 个数量级',
        '      sin(t)/t         3e+05     47746      3.31e-06     1.95e-05      自报开始膨胀',
        '      sin(t)/t         4e+05     63662      2.47e-06     3.35e-02      膨胀四万倍',
        '      sin(t)/t         5e+05     79577      8.04e-01     4.28e-01      值已失效',
        '      cos(t^2)         4e+02     25465      1.21e-03     1.49e-08      低估 5 个数量级',
        '      cos(t^2)         8e+02     101859     1.32e+00     7.33e+00      值已失效',
        '      J_0(t)           1e+05     15915      1.85e-03     1.49e-08      低估 5 个数量级',
        '      J_0(t)           1e+06     159155     2.17e+00     9.26e-02      值已失效而自报仍很小',
        '',
        '      三个区间（以区间内振荡周期数为标尺）：',
        '        正则区   周期数 小于 3e+04   实际误差等于截断公式，与上限成反比',
        '        预警区   周期数 大于 4e+04   自报 abserr 突然膨胀，这是唯一的早期信号',
        '        失效区   周期数 大于 8e+04   值与自报误差都不可信，自报可能又变小',
        '',
        '      统一残差界（命题 A.1）：残差 约等于 包络值(X) 除以 相位导数(X)',
        '        sin t/t 型        包络 1/X    相位导数 1     界 1.00/X     实测系数 1.00',
        '        sin^2 t/t^2 型    包络 1/2X^2 相位导数 2     界 1/4X 加 1/2X  实测系数 2.00',
        '        cos(t^2) 型       包络 1      相位导数 2X    界 0.5/X      实测系数 0.97',
        '        J_0 型            包络 X^-1/2 相位导数 1     界 0.798/X^0.5 实测系数 0.73',
        '        带指数阻尼型      e^-aX 型                       无截断问题（残差 1e-170 量级）',
        '',
        '      想压到残差 1e-06 所需的上限：',
        '        sin t/t 型     X 约 1.0e+06   周期数 159155，已失效，普通求积做不到',
        '        cos(t^2) 型    X 约 5.0e+05   周期数 4.0e+10，更做不到',
        '        J_0 型         X 约 3.4e+11   周期数 5.4e+10，完全不可行',
        '',
        '      结论：无穷上限不能靠把 X 取大来逼近',
        '            有闭式（Si / Ci / Fresnel / J_0）就用闭式，没有就乘指数因子做正则化',
    ])

# ---------- appA block3：用法总图 ----------
def figA_workflow() -> list[str]:
    return _figA([
        '    附录 A 的用法总图：四步检索流程与三条退路',
        '',
        '      第 0 步  看清三件事：被积函数形态 / 区间 / 参数的取值范围',
        '              先把 a>0、0<p<q、a>|b|、epsilon>0 这类硬条件写在纸上',
        '      第 1 步  按形态定位族（A.1 的地图）',
        '              F1 高斯 -> F2 幂乘指数 -> F3 幂乘对数 -> F4 有理函数',
        '              F5 指数乘三角 -> F6 三角有理 -> F7 根式椭圆',
        '              F8 振荡 -> F9 统计 -> F10 核方法',
        '              十族都定位不到：转附录 B 的决策树（判断它到底能不能积）',
        '      第 2 步  在族表里筛条目：先读条件列，再读结果列',
        '              条件不满足 -> 回第 2 章 2.3 重新判收敛性，不要照抄结果',
        '              条件满足   -> 取结果，并标明它属于"反常值 / 主值 / Abel 和"哪一种',
        '      第 3 步  数值落地（A.4）',
        '              用 A.2 的校验值当回归基线；标星的条目必须读它的截断说明',
        '              按 A.4.6 的五条清单逐项过一遍',
        '      第 4 步  交叉验证',
        '              用第二条独立路径核对：换元 / 对称性 / 渐近 / 特殊函数递推',
        '              至少用一条，两条更好',
        '',
        '      三条退路：',
        '        退路一  积分真的发散            -> 附录 B 决策树的最后一层',
        '        退路二  被积函数是有理函数      -> 附录 C 的围道表（往往比查表更快）',
        '        退路三  要的是"哪个函数能算"    -> 附录 I 的入口表（scipy 与 sympy）',
    ])

# ======================================================================
# 附录 B：「积不出来」决策树
# ======================================================================
def _figlines(lines: list[str], width: int = 120) -> list[str]:
    """通用：逐行贴文本（列位置已在 md 里排好）。"""
    cv = Canvas(len(lines), width)
    for i, ln in enumerate(lines):
        cv.text(i, 0, ln)
    return cv.render()


# ---------- appB block0：四类判决分流图 ----------
def figB_flow() -> list[str]:
    return _figlines([
        '    附录 B 四类判决的分流图——入口一个问题，出口四条路',
        '',
        '                          ┌─────────────────────────────────────┐',
        '                          │  拿到 I = ∫ f dx（含假设与区间）    │',
        '                          └──────────────────┬──────────────────┘',
        '                                             │',
        '                      第 0 问  ┌──────────────▼──────────────┐',
        '                      要不    │ 我需要的是"值"还是"界/量级"？│',
        '                      要积？  └──────┬───────────────┬──────┘',
        '                                     │只要界          │要值',
        '                                     ▼                │',
        '                    ┌────────────────────────┐        │',
        '                    │ 判决：不必积（B.3.7）  │        │',
        '                    │ 界 = 二十五万分之一的  │        │',
        '                    │ 代价，且常常够用       │        │',
        '                    └────────────────────────┘        │',
        '                                                      ▼',
        '                      第 1 问  ┌───────────────────────────────────┐',
        '                      能初等  │ 形态是否落在"必定可积"的清单里？  │',
        '                      积吗？  │   有理函数 / 有理三角 / 根式代换  │',
        '                              └──────┬──────────────────┬─────────┘',
        '                                     │是                │否 / 不确定',
        '                                     ▼                  ▼',
        '                    ┌────────────────────────┐  ┌──────────────────────────┐',
        '                    │ 判决 E：初等可积        │  │ 交给 CAS 做一次 Risch 判决│',
        '                    │ 走 1.5 流程树，三到五步 │  └──────┬────────────┬──────┘',
        '                    └────────────────────────┘         │            │',
        '                                            返回 NonEl│ementary  返回普通',
        '                                            （有证明）│          Integral',
        '                                                       ▼            ▼',
        '                                     ┌──────────────────────┐  ┌──────────────────┐',
        '                                     │ 判决 N：初等不可积   │  │ 判决 U：没有判定  │',
        '                                     │ （已证）             │  │ 换元/换假设再试  │',
        '                                     └──────────┬───────────┘  └────────┬─────────┘',
        '                                                │                       │',
        '                                                └───────────┬───────────┘',
        '                                                            ▼',
        '                      第 2 问  ┌───────────────────────────────────────────┐',
        '                      有闭式  │ 形态是否落在附录 A 的十族里 / 是否属于     │',
        '                      吗？    │ B.3.6 的"定积分专属"清单？                 │',
        '                              └──────┬──────────────────────────┬──────────┘',
        '                                     │是                        │否',
        '                                     ▼                          ▼',
        '                    ┌────────────────────────────┐  ┌────────────────────────────┐',
        '                    │ 判决 S：换名字（附录 A）   │  │ 判决 "第三类：该闭嘴"      │',
        '                    │ 或判决 D：换战场（B.3.6）  │  │ 转 B.3.8 的五条退路        │',
        '                    └────────────────────────────┘  └────────────────────────────┘',
        '',
        '    一句话读法：第 0 问省掉最多的时间，第 1 问决定"要不要动笔"，第 2 问决定"动笔写什么"。',
    ])

# ---------- appB block1：判决树四层过滤 ----------
def figB_tree() -> list[str]:
    return _figlines([
        '    附录 B 判决树——四层过滤，每层都可能终止',
        '',
        '  ┌──────────────────────────────────────────────────────────────────────────┐',
        '  │ 第 0 层　需求过滤：要"值"还是"界"？                                      │',
        '  └────────────────────────────────┬─────────────────────────────────────────┘',
        '                    只要界 ────────┴──────── 要值',
        '                      │                              │',
        '                      ▼                              ▼',
        '        ┌──────────────────────────┐   ┌──────────────────────────────────────┐',
        '        │ 终止于"不必积"（B.3.7）  │   │ 第 1 层　形态过滤                    │',
        '        │ 界往往一步可得，且对定理 │   │ 落在"必定可积"清单 → 判决 E，走 1.5  │',
        '        │ 证明已经足够             │   │ 清单：有理 / 有理三角 / 二次根式     │',
        '        └──────────────────────────┘   └────────────────┬─────────────────────┘',
        '                                                        │不在清单里',
        '                                                        ▼',
        '  ┌──────────────────────────────────────────────────────────────────────────┐',
        '  │ 第 2 层　机器过滤：让 CAS 做一次 Risch 判决                              │',
        '  │   返回 NonElementaryIntegral（码 N，有证明）→ 直接进第 3 层              │',
        '  │   返回普通 Integral（码 U，无判定）        → 回第 1 层换元一次再试       │',
        '  │   返回含特殊函数的式子（码 S）             → 已得答案，只需登记          │',
        '  └────────────────────────────────┬─────────────────────────────────────────┘',
        '                                   ▼',
        '  ┌──────────────────────────────────────────────────────────────────────────┐',
        '  │ 第 3 层　区间过滤：这是不定积分还是定积分？                              │',
        '  │   不定积分 → 判决"该闭嘴"，转 B.3.8 五条退路                             │',
        '  │   定积分   → 过 B.3.6 的清单，命中则判决 D（换战场），否则同样转退路     │',
        '  └────────────────────────────────┬─────────────────────────────────────────┘',
        '                                   ▼',
        '  ┌──────────────────────────────────────────────────────────────────────────┐',
        '  │ 第 4 层　退路选择：数值 / 级数 / 渐近 / 界 / 换问题表述                  │',
        '  └──────────────────────────────────────────────────────────────────────────┘',
        '',
        '  关键区别：流程树回答"下一步做什么"，判决树回答"还有没有必要往下走"。',
        '  判决树走到第 4 层，意味着你拿不到闭式——这不等于失败，见 B.3.8。',
    ])

# ---------- appB block2：CAS 返回值读法 ----------
def figB_cas() -> list[str]:
    return _figlines([
        '    CAS 返回值的读法——六种返回，六种动作',
        '',
        '    ┌─────────────────────────────────────────────────────────────────────────────┐',
        '    │ 你看到的返回                                                你该做什么      │',
        '    ├─────────────────────────────────────────────────────────────────────────────┤',
        '    │                                                                             │',
        '    │ 纯初等表达式（Add / Mul / 三角与对数组合）                                  │',
        '    │     └─ 码 E，存在初等原函数 ................ 走 1.5 流程树，直接用          │',
        '    │                                                                             │',
        '    │ 含 erf / Ei / Si / elliptic / hyper / polylog 的表达式                      │',
        '    │     └─ 码 S，非初等但有闭式 ................ 查附录 A 登记，不要硬推        │',
        '    │                                                                             │',
        '    │ NonElementaryIntegral                                                       │',
        '    │     └─ 码 N，已证明无初等原函数 ............. 转卡 6：定积分仍可能有值！    │',
        '    │                                                                             │',
        '    │ 普通 Integral（未求值）                                                     │',
        '    │     └─ 码 U，没有判定 ...................... 换元 / 补假设 / 换工具再试     │',
        '    │           !! 这一档里混着"其实能积"的题（B.5.1）                            │',
        '    │                                                                             │',
        '    │ Piecewise((应答, 条件), (Integral(...), True))                              │',
        '    │     └─ 条件性回答，不是"答不出来" .......... 回去补参数假设（卡 5）         │',
        '    │                                                                             │',
        '    │ nan / 抛异常 / 主值警告                                                     │',
        '    │     └─ 发散或未定义 ........................ 回第 2 章重判收敛性，别用主值  │',
        '    │                                                                             │',
        '    └─────────────────────────────────────────────────────────────────────────────┘',
        '',
        '    两条最容易被读错的：',
        '      (1) 把 N 读成 U  -> 多花时间；把 U 读成 N -> 直接丢掉能做的题（更严重）',
        '      (2) 把 Piecewise 的第二支读成"算不出" -> 其实是"你没告诉我参数的符号"',
    ])


# ---------- appC block0：六问决策树 ----------
def figC_decision() -> list[str]:
    return _figlines([
        '  留数速查：拿到实积分先问六件事（前两步不过，围道法根本用不上）',
        '',
        '      拿到实积分  I = ∫ f(x) dx',
        '                    │',
        '                    ▼',
        '  Q1   积分收敛吗？（第 2 章 p 标尺 / Dirichlet / 比较）',
        '     ├─ 否 / 条件收敛 ──> 先判收敛；发散则围道算得再漂亮也没意义',
        '     └─ 是 ───────────> 进入 Q2',
        '                    │',
        '                    ▼',
        '  Q2   不定积分，还是定积分？',
        '     ├─ 不定 ────────> 围道法通常给不出原函数，转附录 B 的判决树',
        '     └─ 定  ─────────> 进入 Q3',
        '                    │',
        '                    ▼',
        '  Q3   积分区间是什么？',
        '     ├─ (-∞, ∞) ─────> 半圆 / 矩形（见模板一、二）',
        '     ├─ [0, 2π] ─────> 单位圆 |z|=1（换元 z=e^{iθ}，套路 B）',
        '     ├─ [0, ∞) 含 log / 幂 ─> 钥匙孔 / 扇形（模板四、三）',
        '     └─ Σ f(n) ──────> 矩形 + π cot πz（套路 G）',
        '                    │',
        '                    ▼',
        '  Q4   含 e^{iaz} 吗？（Fourier 型）',
        '     ├─ 含，a>0 ─────> 上半圆 + Jordan 引理',
        '     ├─ 含，a<0 ─────> 下半圆（半平面随 a 的符号翻面）',
        '     └─ 含 sin/cos ──> 先化成 e^{iaz}，再取实部 / 虚部',
        '                    │',
        '                    ▼',
        '  Q5   被积函数多值吗？（含 z^a、log z）',
        '     ├─ 是 ──────────> 选分支切 + 钥匙孔，每次重推 arg z 区间',
        '     └─ 否 ──────────> 跳过',
        '                    │',
        '                    ▼',
        '  Q6   实轴上有极点吗？',
        '     ├─ 是（一阶） ──> 缩进围道 + 主值，补 iπ·Res（半留数）',
        '     └─ 否 ──────────> 直接闭围道',
        '                    │',
        '                    ▼',
        '      选定围道后：画奇点 → 定围道 → 求留数(优先方法3) → 留数和=0 校验',
    ])


# ---------- appC block1：五模板 × 七套路对照 ----------
def figC_contours() -> list[str]:
    return _figlines([
        '  五类围道模板 × 七类实积分套路（谁解决哪一类）',
        '',
        '  模板     圈住的奇点            消失机制          典型被积 / 套路',
        '  ──────  ───────────────────  ────────────────  ──────────────────────────',
        '  一·半圆   上半平面全部          ML / Jordan       A 有理式 · C Fourier(e^{iaz})',
        '  二·矩形   条带 0<Im z<Y          Jordan+平移相消   e^{iaz}/cosh z · G 级数求和',
        '  三·扇形   扇形内               ML(弧长~R)        D 幂函数 x^{a-1}/(1+x^n)',
        '  四·钥匙孔 全平面(含分支)       R→∞ / ε→0        E 含 ln x · 多值函数',
        '  五·缩进   上半平面 + 轴上半留数 小圆弧引理        F 实轴有极点的 p.v. 积分',
        '',
        '  记忆法：模板一二三解决"奇点在哪"（上半 / 条带 / 扇形）；',
        '          模板四解决"函数多值"；模板五解决"奇点恰好在实轴上"。',
        '  先判问题属于哪一格，再套对应模板；跨格混用是 90% 失分的来源。',
    ])


# ---------- appC block2：符号陷阱与留数校验速查 ----------
def figC_check() -> list[str]:
    return _figlines([
        '  四条符号陷阱（每次变形 / 每条割缝都重查一遍）',
        '',
        '  ① 半平面选错      e^{iaz} 中 a>0 才配上半圆；写成 a<0 还套上半圆必错。',
        '  ② 割缝因子写错    幂给 (1-e^{2πia})、对数给 2πi、log² 给 4πi ln r-4π²；',
        '                   三个差值每次从 arg z 区间重推，下沿是反向(别忘了负号)。',
        '  ③ 主轴半留数漏    实轴一阶极点贡献 iπ·Res，不是 2πi·Res，也不能当它不存在。',
        '  ④ 变形不补账      跨过极点或分支切必须补上跨过的贡献；每次重列"内部有哪些奇点"。',
        '',
        '  留数校验两种独立办法（算完立刻做，能抓出上面 80% 的错）',
        '  (a) 留数和为零：  Σ_{有限} Res + Res_∞ = 0；有限奇点留数之和应为 0 的常见情形。',
        '  (b) 实部 / 虚部对称：含 e^{iaz} 的题，结果实部应与实变对称一致，虚部与奇偶一致。',
    ])


# ---------- appD 图：显示宽度辅助（须与 measure.mjs 的 isWide 完全一致） ----------
def _isw(c: str) -> bool:
    o = ord(c)
    return (0x1100 <= o <= 0x115F) or (0x2E80 <= o <= 0xA4CF) or (0xAC00 <= o <= 0xD7A3) \
        or (0xF900 <= o <= 0xFAFF) or (0xFE30 <= o <= 0xFE6F) or (0xFF00 <= o <= 0xFF60) \
        or (0xFFE0 <= o <= 0xFFE6)

def _dw(s: str) -> int:
    return sum(2 if _isw(c) else 1 for c in s)

def _pad(s: str, w: int) -> str:
    return s + ' ' * max(0, w - _dw(s))

# ---------- appD block0：三十秒决策图（两栏海报） ----------
def figD_decision() -> list[str]:
    L, R = 30, 40
    top = '┌' + '─' * (L + 2) + '┬' + '─' * (R + 2) + '┐'
    sep = '├' + '─' * (L + 2) + '┼' + '─' * (R + 2) + '┤'
    bot = '└' + '─' * (L + 2) + '┴' + '─' * (R + 2) + '┘'
    rows = [
        ('内积 / 能量 / 范数', 'Cauchy-Schwarz  (33.2.1)'),
        ('乘积要在 L^p 里拆开', 'Hölder  (33.2.2)'),
        ('一个交叉项要吸收掉', 'ε-Young  (33.2.3)'),
        ('特征值被夹在 [m,M]', 'Kantorovich  (33.2.6)'),
        ('期望与函数值要比较', 'Jensen  (33.3.1)'),
        ('只有取值范围 [a,b]', 'Hoeffding  (33.6.2)'),
        ('还有方差信息', 'Bernstein / Bennett  (33.6.2)'),
        ('分布已知（Bernoulli 等）', 'Chernoff + 率函数  (33.6.2)'),
        ('偏差只几个标准差', 'Cantelli  (33.5.2)'),
        ('变量不独立', 'McDiarmid / Azuma  (第 8 章)'),
        ('微分 / 积分不等式', 'Grönwall  (33.4.1)'),
        ('要同时管 m 个事件', 'union bound  (33.5.5)'),
    ]
    out = ['    附录 D 三十秒决策图——你手上的信息 → 该用哪条（章节）', '']
    out.append('    ' + top)
    out.append('    ' + '│ ' + _pad('你手上的信息', L) + ' │ ' + _pad('该用哪条（章节）', R) + ' │')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '│ ' + _pad(a, L) + ' │ ' + _pad(b, R) + ' │')
    out.append('    ' + bot)
    out.append('')
    out.append('    读法：永远先问"有没有率函数"——有就上 Chernoff；没有再按信息量降级。')
    return out

# ---------- appD block1：不等式家族谱（三主线） ----------
def figD_family() -> list[str]:
    W = 70
    top = '┌' + '─' * (W + 2) + '┐'
    bot = '└' + '─' * (W + 2) + '┘'
    body = [
        '主线一　内积几何（管"夹角"）',
        '  Cauchy-Schwarz   cos^2 <= 1        （任意两向量，上界）',
        '  Kantorovich      cos^2 >= 1/eta     （谱夹 [m,M]，下界；eta=(M+m)^2/4Mm）',
        '  一句话：CS 管"最多多斜"，Kantorovich 管"最少多斜"',
        '',
        '主线二　凸性几何（管"弯曲"）',
        '  Jensen    = 切线的整体版   E[f(X)] >= f(E[X])',
        '  一阶条件  = 切线在下         f(y) >= f(x)+<g, y-x>',
        '  二次夹逼  = 一阶 + 曲率界（上下两个包，mu,L 即条件数 kappa）',
        '  一句话：凸性给方向，梯度给切线，曲率给速率',
        '',
        '主线三　集中概率（管"尾部"）',
        '  指对数族（1+x<=e^x 等 5 条）是地基',
        '  地基 → Chernoff → Hoeffding/Bennett/Bernstein（指数界）',
        '  期望侧用 Markov/Cantelli，概率侧用尾部积分恒等式翻译',
    ]
    out = ['    附录 D 不等式家族谱——三条主线，每个成员都挂在某条线上', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '│ ' + _pad(ln, W) + ' │')
    out.append('    ' + bot)
    return out

# ---------- appD block2：五条致命误用与代价 ----------
def figD_traps() -> list[str]:
    W = 70
    top = '┌' + '─' * (W + 2) + '┐'
    bot = '└' + '─' * (W + 2) + '┘'
    body = [
        '(1) 单边事件用双边界      → 多一个因子 2，甚至给 >1 的废界；一律用 Cantelli',
        '(2) 随机扰动用 Grönwall    → 松 40 倍以上，甚至界正真负；系统扰动才用它',
        '(3) (1+a)^n 当 e^{an}      → a=0.1,n=1000 差 109 倍；离散必须用 lambda^n',
        '(4) 渐近式当界用          → n=10 时差 3 个数量级；必须带截断项 + 余项',
        '(5) 界忘了查 <1           → Chebyshev 在 t<sigma 时 >1 即废界；先查再写',
    ]
    out = ['    附录 D 五条致命误用与代价（写任何界之前自查）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '│ ' + _pad(ln, W) + ' │')
    out.append('    ' + bot)
    return out



# ---------- appE 图：定理条件清单 ----------
def figE_decision() -> list[str]:
    L, R = 38, 38
    top = '┌' + '─' * (L + 2) + '┬' + '─' * (R + 2) + '┐'
    sep = '├' + '─' * (L + 2) + '┼' + '─' * (R + 2) + '┤'
    bot = '└' + '─' * (L + 2) + '┴' + '─' * (R + 2) + '┘'
    rows = [
        ('算含参积分 / 交换极限积分', '连续+可微 -> E.1 / E.2'),
        ('级数求和或重排',           '一致收敛 / 绝对收敛 -> E.2'),
        ('复积分 / 数零极点',        '解析+围道无奇点 -> E.3（附录 C）'),
        ('交换极限与积分 / 累次积',  '可测+控制 / 绝对可积 -> E.4'),
        ('最佳逼近 / 变分问题',      '闭凸 / 强制 -> E.5'),
        ('统计推断 / 大样本',        'iid+矩存在 / 同方差 -> E.6'),
        ('SDE / 采样 / 滤波',        'Lipschitz / 带限 -> E.7'),
        ('稳定性 / 优化 / 几何',     '小增益<1 / 凸内点 / 对合 -> E.8'),
        ('上机算积分 / 递推',        '递推方向 / 结构 -> E.9'),
    ]
    out = ['    附录 E 三十秒决策图——你打算用定理做什么 -> 先查哪类条件（哪组）', '']
    out.append('    ' + top)
    out.append('    ' + '│ ' + _pad('你打算用定理做什么', L) + ' │ ' + _pad('先查哪类条件（哪组）', R) + ' │')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '│ ' + _pad(a, L) + ' │ ' + _pad(b, R) + ' │')
    out.append('    ' + bot)
    out.append('')
    out.append('    读法：先问"换序 / 收敛 / 解存在"三类问题中的哪一类——它决定查 E.1-E.9 的哪一组。')
    return out


def figE_family() -> list[str]:
    W = 70
    top = '┌' + '─' * (W + 2) + '┐'
    bot = '└' + '─' * (W + 2) + '┘'
    body = [
        '主线一　连续与可测（换序定理的命门）',
        '  FTC：f 连续才保证 F=f（可积只给几乎处处）',
        '  DCT：要可测 + 可积控制函数 g',
        '  Riesz 表示：要连续线性泛函',
        '  一句话：连续 / 可测决定能不能换序',
        '',
        '主线二　有界与单调（收敛判别的命门）',
        '  MCT：要非负；中值：g 不变号',
        '  Dirichlet：部分和有界 + 单调趋于 0',
        '  条件收敛重排可改变和（Riemann）',
        '  一句话：有界 / 单调决定收不收敛',
        '',
        '主线三　凸与对合（解 / 对偶的命门）',
        '  Slater：凸 + 严格内点才强对偶',
        '  Frobenius：分布对合才可积分为流形',
        '  Brockett：非完整不能用光滑反馈镇定',
        '  一句话：凸 / 对合决定解不存在',
    ]
    out = ['    附录 E 条件类型家族谱——三条主线，每条都挂一组最致命条件', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '│ ' + _pad(ln, W) + ' │')
    out.append('    ' + bot)
    return out


def figE_caveat() -> list[str]:
    W = 70
    top = '┌' + '─' * (W + 2) + '┐'
    bot = '└' + '─' * (W + 2) + '┘'
    body = [
        '(1) 把可积当连续   -> FTC 只给几乎处处可导，不是处处；先查 f 连续',
        '(2) 点态收敛当一致 -> 逐项积分 / 求导失效；条件收敛重排改变和',
        '(3) 忘控制函数用 DCT -> 无 g 时极限与积分可不等；先找可积控制',
        '(4) 重尾套 CLT/LLN -> 方差无穷则极限非正态甚至不收敛；先查矩',
        '(5) 缺约束规范用 KKT -> KKT 非必要条件；先查 LICQ 等约束规范',
    ]
    out = ['    附录 E 五条最常被忘的条件（用任何定理之前自查）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '│ ' + _pad(ln, W) + ' │')
    out.append('    ' + bot)
    return out



# ---------- appF 图：控制方程速查 ----------
def figF_layers() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        '第一层  线性矩阵方程（未知量出现一次，一次 Schur，O(n^3)）',
        '    Sylvester   A X + X B = C      Bartels-Stewart',
        '    Lyapunov    A^T P + P A = -Q   Schur + 回代（连续稳定）',
        '    Stein       A^T P A - P = -Q   Schur + 回代（离散稳定）',
        '第二层  Riccati（未知量出现两次，Schur / 迭代，O(n^3)+步数）',
        '    CARE   连续 LQR   Schur on Hamilton    P>0 闭环稳定',
        '    DARE   离散 LQR   QZ 辛铅笔           稳态即 Kalman',
        '    不定   H-infinity  gamma 二分         解不保证正定',
        '第三层  非线性 PDE（未知函数+非线性导数，只能近似）',
        '    HJB    min_u L + gradV.f   网格化 / 参数化（维数指数）',
        '    KKT    去掉时间的 HJB        内点法 / SQP（第 25 章）',
        '旁支  时滞超越方程(Lambert W) / LKF(LMI) / Wiener-Hopf',
        '判读：未知量出现几次 -> 哪一层；多乘一次难度跳一阶',
    ]
    out = ['    附录 F 方程的三个层级地图——越往下越难解，表达力越强', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


def figF_tree() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        '起点：未知量是什么？（分错后面全错）',
        '  矩阵，出现一次        -> 线性矩阵方程（Lyapunov / Sylvester）',
        '    要对称正定？ 是 -> Lyapunov(A^T P + P A = -Q)',
        '                 否 -> Sylvester(A X + X B = C)',
        '  对称矩阵，出现两次    -> Riccati（第二层）',
        '    连续？ 是 -> CARE(Hamilton + Schur)',
        '          否 -> DARE(辛铅笔 + QZ)',
        '    最坏情形？ 是 -> 不定 Riccati + gamma 二分',
        '    每步更新？ 是 -> 递推 Riccati(Kalman)',
        '  函数 V 问最小代价     -> HJB（第三层，PDE）',
        '    线性+二次？ 是 -> 退化回 CARE（别碰 PDE）',
        '  轨迹+协态             -> Pontryagin 两点边值（打靶法）',
        '  点 x 无动态           -> KKT（第 25 章）',
        '  时滞 tau              -> 超越特征方程(Lambert W) / LKF',
    ]
    out = ['    附录 F 选择决策树——照问题形式走，不看学科名字', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


def figF_cost() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        '① 矩阵方程只用 Schur/QZ，不用 Kronecker（n=100 慢 15365 倍）',
        '② 精度看 sep，不看残差（可差 7 个量级，例 34.1）',
        '③ 对称矩阵方程先对称化再解（否则 P 不对称，正定性失效）',
        '④ 二次方程必须验证要哪个解（定理 34.9 四个解，取错则发散）',
        '⑤ 迭代法先验证前提（Kleinman 初值 / Kalman 可检测，不报错）',
        '三个不要：不用 Kronecker 算；不盲信迭代；不把残差当精度',
    ]
    out = ['    附录 F 求解成本与数值稳定性五条', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


# ---------- appG 图：贯通思考题 ----------
def figG_map() -> list[str]:
    L, R = 22, 44
    top = '\u250c' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2510'
    sep = '\u251c' + '\u2500' * (L + 2) + '\u2502' + '\u2500' * (R + 2) + '\u2524'
    bot = '\u2514' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2518'
    rows = [
        ('控制 \u2194 估计', 'G.1 / G.2'),
        ('学习 \u2194 控制', 'G.3 / G.4'),
        ('积分 \u2194 复变', 'G.5 / G.6'),
        ('不等式 \u2194 概率', 'G.7 / G.8'),
        ('数值 \u2194 符号', 'G.9 / G.10'),
        ('跨域综合', 'G.11 / G.12 / G.13 / G.14'),
    ]
    out = ['    附录 G 主题 \u00d7 思考题地图——每题横跨至少两章', '']
    out.append('    ' + top)
    out.append('    ' + '\u2502 ' + _pad('主题', L) + ' \u2502 ' + _pad('题号', R) + ' \u2502')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '\u2502 ' + _pad(a, L) + ' \u2502 ' + _pad(b, R) + ' \u2502')
    out.append('    ' + bot)
    return out


def figG_flow() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        '我想证 / 算什么？',
        '  -> 是换序 / 收敛 / 解存在 哪类？（附录 E）',
        '  -> 立方程还是套不等式？（附录 F / 附录 D）',
        '  -> 写前提断言，不靠求解器报错（附录 F 铁律三）',
        '  -> 符号结论用数值复核，数值用符号解释',
        '     （附录 B / 附录 I 交叉验证）',
        '  -> 推不出 -> 回对应章查条件与反例',
    ]
    out = ['    附录 G 一道题的思考路径', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


def figG_index() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        'G.1 不知(A,B)能否解方程？路线 A vs B',
        'G.2 可检测为何够？一条不等式说清',
        'G.3 早停=迭代停在哪阶段？与两阶段法',
        'G.4 泛化误差两类来源，哪类界能管',
        'G.5 sin x/x 条件收敛，闭围道错在哪',
        'G.6 sqrt(tan x) 留数法为何帮不上',
        'G.7 Cauchy/Markov/Hoeffding/Chernoff 选谁',
        'G.8 KL>=0 等号是 EM 单调性的命门',
        'G.9 sympy 返 Integral：N 还是 U？',
        'G.10 quad 端点奇异掉两阶是 bug 吗',
        'G.11 残差小\u2260解准：三个现场+统一判据',
        'G.12 换序定理条件表：最易被忘哪条',
        'G.13 拟合不出幂律：bug 还是事实',
        'G.14 三条 Gr\u00f6nwall 分别用在哪',
    ]
    out = ['    附录 G 题号索引（每条只给提示，不给标准答案）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


# ---------- appH 图：论文阅读地图 ----------
def figH_map() -> list[str]:
    L, R = 22, 46
    top = '\u250c' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2510'
    sep = '\u251c' + '\u2500' * (L + 2) + '\u2502' + '\u2500' * (R + 2) + '\u2524'
    bot = '\u2514' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2518'
    rows = [
        ('积分/特殊函数', 'A / B / ch30'),
        ('复变/留数', 'C / ch30'),
        ('不等式/概率界', 'D / ch33'),
        ('测度/泛函', 'ch04 / E'),
        ('控制方程/Riccati', 'F / ch34'),
        ('学习理论', 'ch35'),
        ('优化/KKT', 'ch25 / E'),
        ('随机/SDE', 'ch09 / 29 / E'),
        ('综合项目', 'ch36'),
    ]
    out = ['    附录 H 九大主题 \u00d7 落点章节', '']
    out.append('    ' + top)
    out.append('    ' + '\u2502 ' + _pad('主题', L) + ' \u2502 ' + _pad('落点章节', R) + ' \u2502')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '\u2502 ' + _pad(a, L) + ' \u2502 ' + _pad(b, R) + ' \u2502')
    out.append('    ' + bot)
    return out


def figH_order() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        '第 1 阶段  基础工具：ch04 测度 / ch05 泛函 / 附录 E 条件清单',
        '第 2 阶段  计算内核：附录 A 积分 / 附录 C 留数 / 附录 B 决策',
        '第 3 阶段  估计语言：附录 D 不等式 / ch33 / ch35 学习理论',
        '第 4 阶段  方程与解：附录 F 控制方程 / ch34 / ch25 优化',
        '第 5 阶段  随机与采样：ch09 / ch29 / 附录 E E.7',
        '第 6 阶段  综合：ch36 三项目（控制/估计/跨域）',
        '读法：每阶段先过该章六栏卡片，再读 H.1-H.9 对应论文',
    ]
    out = ['    附录 H 建议阅读顺序（由基础到综合）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


def figH_do() -> list[str]:
    L, R = 22, 46
    top = '\u250c' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2510'
    sep = '\u251c' + '\u2500' * (L + 2) + '\u2502' + '\u2500' * (R + 2) + '\u2524'
    bot = '\u2514' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2518'
    rows = [
        ('积分/特殊函数', '查表验证自己的积分'),
        ('复变/留数', '用围道算实积分'),
        ('不等式/概率界', '给 ML 算法写高概率界'),
        ('测度/泛函', '严格证 DCT/Fubini'),
        ('控制/Riccati', '写 LQR/H-infinity 求解器'),
        ('学习理论', '用 Rademacher 写泛化界'),
        ('优化/KKT', '写牛顿/SQP 求解器'),
        ('随机/SDE', '写 Euler-Maruyama 采样'),
        ('综合项目', '端到端三项目复现'),
    ]
    out = ['    附录 H 每主题的可复现任务', '']
    out.append('    ' + top)
    out.append('    ' + '\u2502 ' + _pad('主题', L) + ' \u2502 ' + _pad('读完你能做', R) + ' \u2502')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '\u2502 ' + _pad(a, L) + ' \u2502 ' + _pad(b, R) + ' \u2502')
    out.append('    ' + bot)
    return out


# ---------- appI 图：数值与符号计算工具速查 ----------
def figI_decide() -> list[str]:
    L, R = 26, 40
    top = '\u250c' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2510'
    sep = '\u251c' + '\u2500' * (L + 2) + '\u2502' + '\u2500' * (R + 2) + '\u2524'
    bot = '\u2514' + '\u2500' * (L + 2) + '\u2500' + '\u2500' * (R + 2) + '\u2518'
    rows = [
        ('定积分(光滑)', 'scipy.integrate.quad'),
        ('判定是否初等', 'sympy.integrate'),
        ('Lyapunov/Riccati', 'scipy.linalg.solve_*'),
        ('稳定子空间', 'scipy.linalg.schur'),
        ('泛化/概率', 'scipy.stats + 手推'),
        ('优化/KKT', 'scipy.optimize.minimize'),
        ('随机过程采样', 'numpy.random + SDE'),
        ('符号推导', 'sympy (limit/series)'),
    ]
    out = ['    附录 I 想算 X -> 该用哪个函数', '']
    out.append('    ' + top)
    out.append('    ' + '\u2502 ' + _pad('你想算', L) + ' \u2502 ' + _pad('第一选择', R) + ' \u2502')
    out.append('    ' + sep)
    for a, b in rows:
        out.append('    ' + '\u2502 ' + _pad(a, L) + ' \u2502 ' + _pad(b, R) + ' \u2502')
    out.append('    ' + bot)
    return out


def figI_numpy() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        'np.linalg.solve(A,b)   一般线性解   坑：先查 cond(A)',
        'np.linalg.eig(A)       特征值       坑：不排序，别当 schur',
        'np.linalg.svd(A)       奇异值       坑：比 eig(A^T A) 稳',
        'np.polyfit(x,y,deg)    多项式拟合   坑：高次 Runge 震荡',
        'np.random.default_rng  可复现随机   坑：别用旧 seed',
        'np.kron(A,B)           克罗内克     坑：解矩阵方程别手拉直',
    ]
    out = ['    附录 I numpy 常用函数（算什么 / 函数 / 坑）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


def figI_scipy() -> list[str]:
    W = 72
    top = '\u250c' + '\u2500' * (W + 2) + '\u2510'
    bot = '\u2514' + '\u2500' * (W + 2) + '\u2518'
    body = [
        'scipy.integrate.quad      定积分     坑：端点奇异掉两阶',
        'scipy.linalg.solve_lyapunov  Lyapunov  坑：解完查 P>0',
        'scipy.linalg.solve_continuous_are CARE 坑：R 须正定',
        'scipy.linalg.schur(H)      稳定子空间  坑：取左半平面 n 个',
        'scipy.optimize.minimize    有约束优化  坑：LICQ 满足才 KKT',
        'scipy.stats.*              分布/检验  坑：重尾套 CLT 失效',
        'sympy.integrate            符号积分   坑：返 Integral 是 U',
        'sympy.sympify              符号构造   坑：须传 locals',
    ]
    out = ['    附录 I scipy + sympy 常用函数（算什么 / 函数 / 坑）', '']
    out.append('    ' + top)
    for ln in body:
        out.append('    ' + '\u2502 ' + _pad(ln, W) + ' \u2502')
    out.append('    ' + bot)
    return out


FIGURES = [
    ("ch00.md", 0, fig_layers),
    ("ch00.md", 1, fig_control_split),
    ("ch00.md", 2, fig_chapter_skeleton),
    ("ch01.md", 0, fig_weapons),
    ("ch01.md", 1, fig_feynman),
    ("ch01.md", 2, fig_special_fn),
    ("ch01.md", 3, fig_decision_tree),
    ("ch02.md", 0, fig_improper_flow),
    ("ch05.md", 0, fig_contour_semicircle),
    ("ch05.md", 1, fig_contour_rect),
    ("ch05.md", 2, fig_contour_sector),
    ("ch05.md", 3, fig_contour_keyhole),
    ("ch05.md", 4, fig_contour_indent),
    ("ch06.md", 0, fig_space_hierarchy),
    ("ch06.md", 1, fig_projection),
    ("ch06.md", 2, fig_truncation),
    ("ch06.md", 3, fig_compact),
    ("ch06.md", 4, fig_convergence),
    ("ch06.md", 5, fig_spectrum),
    ("ch06.md", 6, fig_kernel_matrix),
    ("ch07.md", 0, fig_cond_exp_proj),
    ("ch07.md", 1, fig_conv_modes),
    ("ch07.md", 2, fig_filtration),
    ("ch07.md", 3, fig_total_var),
    ("ch08.md", 0, fig_tail_compare),
    ("ch08.md", 1, fig_thin_shell),
    ("ch08.md", 2, fig_jl_projection),
    ("ch08.md", 3, fig_complexity_measures),
    ("ch08.md", 4, fig_gen_bound_pipeline),
    ("ch09.md", 0, fig_quad_variation),
    ("ch09.md", 1, fig_donsker_scaling),
    ("ch09.md", 2, fig_ito_correction),
    ("ch09.md", 3, fig_sde_zoo),
    ("ch09.md", 4, fig_gen_flow),
    ("ch10.md", 0, fig_est_zoo),
    ("ch10.md", 1, fig_info_identity),
    ("ch10.md", 2, fig_bias_variance),
    ("ch10.md", 3, fig_sysid_flow),
    ("ch10.md", 4, fig_em_lower_bound),
    ("ch11.md", 0, fig_entropy_zoo),
    ("ch11.md", 1, fig_kl_asymmetry),
    ("ch11.md", 2, fig_fisher_geometry),
    ("ch11.md", 3, fig_info_limits),
    ("ch11.md", 4, fig_elbo_decomp),
    ("ch12.md", 0, fig_fourier_family),
    ("ch12.md", 1, fig_conv_theorem),
    ("ch12.md", 2, fig_sampling_chain),
    ("ch12.md", 3, fig_window_tradeoff),
    ("ch12.md", 4, fig_tf_tiling),
    ("ch13.md", 0, fig_roc_plane),
    ("ch13.md", 1, fig_laplace_zmap),
    ("ch13.md", 2, fig_lti_zoo),
    ("ch13.md", 3, fig_bilinear_warp),
    ("ch13.md", 4, fig_filter_approx),
    ("ch14.md", 0, fig_statespace_flow),
    ("ch14.md", 1, fig_matrix_exp_zoo),
    ("ch14.md", 2, fig_ctrb_obsv),
    ("ch14.md", 3, fig_lyapunov_geom),
    ("ch14.md", 4, fig_kalman_cycle),
    ("ch15.md", 0, fig_basis_vs_frame),
    ("ch15.md", 1, fig_l1_geometry),
    ("ch15.md", 2, fig_rip_sketch),
    ("ch15.md", 3, fig_cs_phase),
    ("ch15.md", 4, fig_ista_flow),
    ("ch16.md", 0, fig_feedback_loop),
    ("ch16.md", 1, fig_root_locus),
    ("ch16.md", 2, fig_nyquist_encircle),
    ("ch16.md", 3, fig_bode_margin),
    ("ch16.md", 4, fig_pid_geometry),
    ("ch17.md", 0, fig_ctrl_two_paths),
    ("ch17.md", 1, fig_lqr_geometry),
    ("ch17.md", 2, fig_h2_hinf_ball),
    ("ch17.md", 3, fig_gramian_balance),
    ("ch17.md", 4, fig_sampled_phase),
    ("ch18.md", 0, fig_stability_zoo),
    ("ch18.md", 1, fig_lasalle),
    ("ch18.md", 2, fig_iss_gain),
    ("ch18.md", 3, fig_circle_popov),
    ("ch18.md", 4, fig_bifurcation),
    ("ch19.md", 0, fig_opt_three_routes),
    ("ch19.md", 1, fig_pmp_geometry),
    ("ch19.md", 2, fig_hjb_flow),
    ("ch19.md", 3, fig_bangbang_phase),
    ("ch19.md", 4, fig_mpc_recede),
    ("ch20.md", 1, fig_uncertainty_zoo),
    ("ch20.md", 3, fig_lft_standard),
    ("ch20.md", 4, fig_robust_two_bounds),
    ("ch20.md", 5, fig_mu_geometry),
    ("ch20.md", 8, fig_dk_loop),
    ("ch21.md", 0, fig_uncertainty_philosophy),
    ("ch21.md", 1, fig_ch21_map),
    ("ch21.md", 2, fig_dual_effect),
    ("ch21.md", 3, fig_stability_three),
    ("ch21.md", 4, fig_packet_loss),
    ("ch22.md", 0, fig_nonlinear_four),
    ("ch22.md", 1, fig_choice_flow),
    ("ch22.md", 2, fig_zero_dynamics),
    ("ch22.md", 3, fig_sliding_mode),
    ("ch22.md", 4, fig_adapt_issues),
    ("ch23.md", 0, fig_geom_layers),
    ("ch23.md", 1, fig_zero_manifold),
    ("ch23.md", 2, fig_nonholonomic),
    ("ch23.md", 3, fig_exp_map),
    ("ch23.md", 4, fig_phs_shaping),
    ("ch24.md", 0, fig_rl_landscape),
    ("ch24.md", 1, fig_bellman_operator),
    ("ch24.md", 2, fig_td_anatomy),
    ("ch24.md", 3, fig_pg_landscape),
    ("ch24.md", 4, fig_explore_safe),
    ("ch25.md", 0, fig_convex_geometry),
    ("ch25.md", 1, fig_conjugate_web),
    ("ch25.md", 2, fig_duality_picture),
    ("ch25.md", 3, fig_cone_ladder),
    ("ch25.md", 4, fig_firstorder_rates),
    ("ch26.md", 0, fig_nonconvex_landscape),
    ("ch26.md", 1, fig_implicit_bias),
    ("ch26.md", 2, fig_saddle_escape),
    ("ch26.md", 3, fig_backprop_adjoint),
    ("ch26.md", 4, fig_normalization_map),
    ("ch27.md", 0, fig_ntk_pipeline),
    ("ch27.md", 1, fig_ntk_recursion),
    ("ch27.md", 2, fig_ntk_spectrum),
    ("ch27.md", 3, fig_mup_scaling),
    ("ch27.md", 4, fig_lazy_rich),
    ("ch28.md", 0, fig_gen_learning_map),
    ("ch28.md", 1, fig_vc_shatter),
    ("ch28.md", 2, fig_rademacher_anatomy),
    ("ch28.md", 3, fig_stability_sgd),
    ("ch28.md", 4, fig_double_descent_theory),
    ("ch29.md", 0, fig_genmodel_map),
    ("ch29.md", 1, fig_score_anatomy),
    ("ch29.md", 2, fig_dsm_pipeline),
    ("ch29.md", 3, fig_forward_reverse),
    ("ch29.md", 4, fig_probflow_vs_sde),
    ("ch29.md", 5, fig_wasserstein_flow),
    ("ch29.md", 6, fig_sampler_spectrum),
    ("ch30.md", 0, fig_contour_map),
    ("ch30.md", 1, fig_argument_principle),
    ("ch30.md", 2, fig_nyquist_map),
    ("ch30.md", 3, fig_pochhammer),
    ("ch30.md", 4, fig_branch_cut),
    ("ch30.md", 5, fig_special_fn_bridge),
    ("ch30.md", 6, fig_saddle_path),
    ("ch30.md", 7, fig_stirling_saddle),
    ("ch30.md", 8, fig_asymptotic_family),
    ("ch31.md", 0, fig_special_fn_forest),
    ("ch31.md", 1, fig_gamma_family),
    ("ch31.md", 2, fig_incomplete_gamma_map),
    ("ch31.md", 3, fig_erf_uniform),
    ("ch31.md", 4, fig_bessel_regions),
    ("ch31.md", 5, fig_orthopoly_ladder),
    ("ch31.md", 6, fig_gauss_quadrature),
    ("ch31.md", 7, fig_asymptotic_anatomy),
    ("ch31.md", 8, fig_special_fn_apps),
    ("ch32.md", 0, fig_numerics_map),
    ("ch32.md", 1, fig_quadrature_family),
    ("ch32.md", 2, fig_adaptive_refine),
    ("ch32.md", 3, fig_singularity_zoo),
    ("ch32.md", 4, fig_highdim_routes),
    ("ch32.md", 5, fig_approx_arsenal),
    ("ch32.md", 6, fig_numerics_apps),
    ("ch32.md", 7, fig_numerics_decision),
    ("ch33.md", 0, fig_ineq_map),
    ("ch33.md", 1, fig_cs_family),
    ("ch33.md", 2, fig_convex_chain),
    ("ch33.md", 3, fig_log_ineq),
    ("ch33.md", 4, fig_gronwall),
    ("ch33.md", 5, fig_tail_identity),
    ("ch33.md", 6, fig_chernoff_flow),
    ("ch33.md", 7, fig_bound_zoo),
    ("ch33.md", 8, fig_conv_rates),
    ("ch33.md", 9, fig_bound_workflow),
    ("ch34.md", 0, fig_eq_card),
    ("ch34.md", 1, fig_eq_layers),
    ("ch34.md", 2, fig_sep_danger),
    ("ch34.md", 3, fig_bs_vs_kron),
    ("ch34.md", 4, fig_sylvester_family),
    ("ch34.md", 5, fig_hamilton_spectrum),
    ("ch34.md", 6, fig_riccati_map),
    ("ch34.md", 7, fig_hjb_ladder),
    ("ch34.md", 8, fig_iter_rates),
    ("ch34.md", 9, fig_delay_branches),
    ("ch34.md", 10, fig_cov_recursion),
    ("ch34.md", 11, fig_choose_eq),
    ("ch35.md", 0, fig35_risk_decomp),
    ("ch35.md", 1, fig35_learn_chain),
    ("ch35.md", 2, fig35_bound_scaling),
    ("ch35.md", 3, fig35_vc_bruteforce),
    ("ch35.md", 4, fig35_cover_growth),
    ("ch35.md", 5, fig35_rademacher_scale),
    ("ch35.md", 6, fig35_beta_decay),
    ("ch35.md", 7, fig35_max_margin_drift),
    ("ch35.md", 8, fig35_early_stop_u),
    ("ch35.md", 9, fig35_sig_noise_split),
    ("ch35.md", 10, fig35_learning_curve),
    ("ch35.md", 11, fig35_bias_var_n),
    ("ch35.md", 12, fig35_choose_bound),
    ('ch36.md', 0, fig36_seven_steps),
    ('ch36.md', 1, fig36_cost),
    ('ch36.md', 2, fig36_ctrl_flow),
    ('ch36.md', 3, fig36_ctrl_struct),
    ('ch36.md', 4, fig36_ctrl_care),
    ('ch36.md', 5, fig36_ctrl_obs),
    ('ch36.md', 6, fig36_ctrl_bound),
    ('ch36.md', 7, fig36_ctrl_delay),
    ('ch36.md', 8, fig36_est_flow),
    ('ch36.md', 9, fig36_est_crb),
    ('ch36.md', 10, fig36_est_coverage),
    ('ch36.md', 11, fig36_xdom),
    ('ch36.md', 12, fig36_omit_tree),
    ('ch36.md', 13, fig36_loose),
    ('appA.md', 0, figA_families),
    ('appA.md', 1, figA_trunc),
    ('appA.md', 3, figA_workflow),
    ('appB.md', 0, figB_flow),
    ('appB.md', 1, figB_tree),
    ('appB.md', 2, figB_cas),
    ('appC.md', 0, figC_decision),
    ('appC.md', 1, figC_contours),
    ('appC.md', 2, figC_check),
    ('appD.md', 0, figD_decision),
    ('appD.md', 1, figD_family),
    ('appD.md', 2, figD_traps),
    ('appE.md', 0, figE_decision),
    ('appE.md', 1, figE_family),
    ('appE.md', 2, figE_caveat),
    ('appF.md', 0, figF_layers),
    ('appF.md', 1, figF_tree),
    ('appF.md', 2, figF_cost),
    ('appG.md', 0, figG_map),
    ('appG.md', 1, figG_flow),
    ('appG.md', 2, figG_index),
    ('appH.md', 0, figH_map),
    ('appH.md', 1, figH_order),
    ('appH.md', 2, figH_do),
    ('appI.md', 0, figI_decide),
    ('appI.md', 1, figI_numpy),
    ('appI.md', 2, figI_scipy),
]
BLOCK_RE = re.compile(r"(```[^\n]*\n)(.*?)(```)", re.S)


def iter_blocks(text: str):
    return list(BLOCK_RE.finditer(text))


# ----------------------------------------------------------------------
# 图内禁用字符
# ----------------------------------------------------------------------
# 栅格模型（w()）把下列字符按 1 列计（east_asian_width 判为 A/N），
# 但实测它们比西文宽 1.3～1.8 倍，浏览器端会按「实测宽度 ≥ 1.5 列」
# 包成 2ch，于是每出现一个就比模型多出 1 列 —— 整行右移。
# 结论：**图中一律不用这些字符**，改用 → / 文字 / 〈〉。
UNSAFE_IN_FIG = "⟶⟺⟹⇔⇒∀∈∋⟂⇀↼ℝℂℕℤ∐∏∮∯"


def audit_chars() -> int:
    """扫描所有图，报告两类问题：
    ① 宽度不整（模型 1 列但实测更宽）的字符；
    ② 图内残留 LaTeX（`$`）—— 代码块会被 build.py 保护，所以 merror 为 0、
       公式计数也正常，但渲染后在正文里留下裸 `$`（check.mjs 报 rawDollar: true）。
    """
    bad = 0
    for fname, idx, maker in FIGURES:
        for no, ln in enumerate(maker()):
            hits = sorted({ch for ch in ln if ch in UNSAFE_IN_FIG})
            if hits:
                bad += 1
                print(
                    f"  [!!] {fname} block{idx} 第 {no} 行含 {''.join(hits)}"
                    f"（宽度不整，会撑歪整行）：{ln.strip()[:52]}"
                )
            if "$" in ln:
                bad += 1
                print(
                    f"  [!!] {fname} block{idx} 第 {no} 行含 $"
                    f"（图内禁止 LaTeX，会残留裸美元号）：{ln.strip()[:52]}"
                )
    if not bad:
        print("  [ok] 所有图均无宽度不整字符，也无 LaTeX 残留")
    return bad


def cmd_check():
    drift = 0
    for fn, idx, maker in FIGURES:
        path = CH_DIR / fn
        text = path.read_text(encoding="utf-8")
        matches = iter_blocks(text)
        if idx >= len(matches):
            print(f"  [!!] {fn} block{idx} 缺失")
            drift += 1
            continue
        cur = matches[idx].group(2).rstrip("\n")
        want = "\n".join(maker()).rstrip("\n")   # 两侧都要去尾空行，否则末尾留白会误报
        same = cur == want
        drift += 0 if same else 1
        ws = {w(l.rstrip()) for l in want.split("\n") if l.strip()}
        print(
            f"  [{'ok' if same else '!!'}] {fn} block{idx}: "
            f"{len(want.splitlines())} 行, {len(ws)} 种行宽"
            + ("" if same else "   ← 与生成器不一致，请运行 apply")
        )
    print(f"\n{drift} 处需要同步" if drift else "\n所有图形均已同步")
    print()
    audit_chars()


def cmd_apply():
    for fn, idx, fn_maker in FIGURES:
        path = CH_DIR / fn
        text = path.read_text(encoding="utf-8")
        matches = iter_blocks(text)
        if idx >= len(matches):
            print(f"  [skip] {fn} block{idx} 不存在")
            continue
        m = matches[idx]
        body = "\n".join(fn_maker()) + "\n"
        start, end = m.span(2)
        text = text[:start] + body + text[end:]
        path.write_text(text, encoding="utf-8")
        ws = {w(l.rstrip()) for l in body.rstrip("\n").split("\n") if l.strip()}
        print(f"  [ok] 已更新 {fn} block{idx}  ({len(body.splitlines())} 行, {len(ws)} 种行宽)")


if __name__ == "__main__":
    if MODE == "apply":
        cmd_apply()
    else:
        cmd_check()

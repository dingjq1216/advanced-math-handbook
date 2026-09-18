# -*- coding: utf-8 -*-
"""
进阶数学手册 · 构建脚本
====================================================
把 chapters/*.md 编译成 content/all.js，使 index.html 可以直接双击打开
（file:// 协议）而无需本地服务器。

用法：
    python build.py
"""

from __future__ import annotations

import datetime
import html as H
import json
import pathlib
import re

import markdown

ROOT = pathlib.Path(__file__).resolve().parent
CH_DIR = ROOT / "chapters"
OUT_DIR = ROOT / "content"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BOOK_META = {
    "title": "进阶数学手册",
    "subtitle": "信号处理 · 控制 · 机器学习 · 泛化理论",
    "edition": "第一版",
}

# ======================================================================
# 全书结构（唯一数据源）：改这里即可调整目录
# ======================================================================
TOC = [
    {
        "vol": "导论",
        "chapters": [
            {"id": "ch00", "no": "0", "title": "导论：数学地图与学习路线", "src": "ch00.md"},
        ],
    },
    {
        "vol": "第一卷　分析、积分与空间",
        "chapters": [
            {"id": "ch01", "no": "1", "title": "微积分进阶与积分策略", "src": "ch01.md"},
            {"id": "ch02", "no": "2", "title": "黎曼积分、反常积分与可积性", "src": "ch02.md"},
            {"id": "ch03", "no": "3", "title": "测度与勒贝格积分", "src": "ch03.md"},
            {"id": "ch04", "no": "4", "title": "分布、δ 函数与弱导数", "src": "ch04.md"},
            {"id": "ch05", "no": "5", "title": "复变函数、留数定理与围道积分", "src": "ch05.md"},
            {"id": "ch06", "no": "6", "title": "泛函分析、希尔伯特空间与 RKHS", "src": "ch06.md"},
        ],
    },
    {
        "vol": "第二卷　概率、随机与统计",
        "chapters": [
            {"id": "ch07", "no": "7", "title": "概率论进阶与条件期望", "src": "ch07.md"},
            {"id": "ch08", "no": "8", "title": "高维概率与集中不等式", "src": "ch08.md"},
            {"id": "ch09", "no": "9", "title": "随机过程与随机分析", "src": "ch09.md"},
            {"id": "ch10", "no": "10", "title": "统计估计与系统辨识", "src": "ch10.md"},
            {"id": "ch11", "no": "11", "title": "信息论与统计推断", "src": "ch11.md"},
        ],
    },
    {
        "vol": "第三卷　信号、变换与系统",
        "chapters": [
            {"id": "ch12", "no": "12", "title": "傅里叶分析、采样与小波", "src": "ch12.md"},
            {"id": "ch13", "no": "13", "title": "拉普拉斯、Z 变换与 LTI 系统", "src": "ch13.md"},
            {"id": "ch14", "no": "14", "title": "状态空间、矩阵分析与线性系统", "src": "ch14.md"},
            {"id": "ch15", "no": "15", "title": "框架、稀疏与压缩感知"},
        ],
    },
    {
        "vol": "第四卷　控制、估计与决策",
        "chapters": [
            {"id": "ch16", "no": "16", "title": "经典控制数学"},
            {"id": "ch17", "no": "17", "title": "现代控制：状态空间与线性系统"},
            {"id": "ch18", "no": "18", "title": "稳定性理论"},
            {"id": "ch19", "no": "19", "title": "最优控制"},
            {"id": "ch20", "no": "20", "title": "鲁棒控制（重点扩展）"},
            {"id": "ch21", "no": "21", "title": "随机控制与估计"},
            {"id": "ch22", "no": "22", "title": "非线性与自适应控制"},
            {"id": "ch23", "no": "23", "title": "几何控制"},
            {"id": "ch24", "no": "24", "title": "学习控制与强化学习"},
        ],
    },
    {
        "vol": "第五卷　优化、学习与泛化",
        "chapters": [
            {"id": "ch25", "no": "25", "title": "凸优化"},
            {"id": "ch26", "no": "26", "title": "非凸优化与深度学习"},
            {"id": "ch27", "no": "27", "title": "神经正切核与无限宽网络"},
            {"id": "ch28", "no": "28", "title": "泛化理论核心专题"},
            {"id": "ch29", "no": "29", "title": "随机微分方程与生成模型"},
        ],
    },
    {
        "vol": "第六卷　数学工具与方法专章",
        "chapters": [
            {"id": "ch30", "no": "30", "title": "留数定理与围道积分方法"},
            {"id": "ch31", "no": "31", "title": "特殊函数与积分表"},
            {"id": "ch32", "no": "32", "title": "数值积分与近似方法"},
            {"id": "ch33", "no": "33", "title": "常用不等式与估计方法"},
            {"id": "ch34", "no": "34", "title": "控制方程与方法速查"},
            {"id": "ch35", "no": "35", "title": "学习理论中的估计方法"},
        ],
    },
    {
        "vol": "第七卷　综合应用与附录",
        "chapters": [
            {"id": "ch36", "no": "36", "title": "综合项目与案例"},
            {"id": "appA", "no": "A", "title": "附录 A　常用积分表与特殊函数"},
            {"id": "appB", "no": "B", "title": "附录 B　「积不出来」决策树"},
            {"id": "appC", "no": "C", "title": "附录 C　留数计算速查"},
            {"id": "appD", "no": "D", "title": "附录 D　常用不等式"},
            {"id": "appE", "no": "E", "title": "附录 E　定理条件清单"},
            {"id": "appF", "no": "F", "title": "附录 F　控制方程速查"},
            {"id": "appG", "no": "G", "title": "附录 G　贯通思考题（附提示）"},
            {"id": "appH", "no": "H", "title": "附录 H　论文阅读地图"},
            {"id": "appI", "no": "I", "title": "附录 I　数值与符号计算工具速查"},
        ],
    },
]

MD_EXT = ["tables", "sane_lists"]

PH_L, PH_R = "\ue000", "\ue001"

QUOTE_PREFIX = re.compile(r"^[ \t]*>[ \t]?", re.M)
# 首行的 `>` 只有在后面紧跟空白时才算引用标记。
# 反例：`$>0$` 抽出来就是 `>0`，照剥会把比较号吃掉（`$>$` 甚至会变成空公式）。
QUOTE_FIRST = re.compile(r"^[ \t]*>(?=[ \t])[ \t]?")


def unquote(text: str) -> str:
    """剥掉行首的 blockquote 标记。

    公式与代码是在 markdown 解析**之前**从原始文本里抽出来的，此时
    callout 框内的每一行还带着 `> ` 前缀。若不剥掉，`> $$ … $$` 这种写法
    会把 `> ` 一起抽进 TeX 里，在公式前面渲染出一个多余的 `>`。

    首行要区别对待：公式自身的首字符就可能是数学里的 `>`（如 `$>0$`、
    `$>$`），此时 `>` 后面不会跟空白，不能当成引用标记剥掉。
    """
    lines = text.split("\n")
    m = QUOTE_FIRST.match(lines[0])
    if m:
        lines[0] = lines[0][m.end():]
    if len(lines) == 1:
        return lines[0]
    return lines[0] + "\n" + QUOTE_PREFIX.sub("", "\n".join(lines[1:]))

FENCE_RE = re.compile(r"^[ \t]*```([^\n`]*)\n(.*?)^[ \t]*```[ \t]*$", re.S | re.M)
DISPLAY_DOLLAR = re.compile(r"\$\$(.+?)\$\$", re.S)
DISPLAY_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.S)
INLINE_PAREN = re.compile(r"\\\((.+?)\\\)", re.S)
INLINE_DOLLAR = re.compile(r"(?<!\\)\$([^\$\n]+?)\$", re.S)

HEAD_RE = re.compile(r"<h([234])>(.*?)</h\1>", re.S)
BLOCK_RE = re.compile(r"<blockquote>(.*?)</blockquote>", re.S)

BOX_TYPES = [
    ("定义", "def"), ("定理", "thm"), ("命题", "prop"), ("引理", "lem"),
    ("推论", "cor"), ("例", "ex"), ("例子", "ex"), ("注", "rem"), ("注记", "rem"),
    ("提示", "rem"), ("正确做法", "rem"), ("校验", "rem"),
    ("算法", "rem"), ("约定", "rem"),
    ("要点", "key"), ("小结", "key"), ("口诀", "key"), ("速查", "key"),
    ("记忆法", "key"), ("通用", "key"),
    ("陷阱", "warn"), ("警告", "warn"), ("铁律", "warn"), ("自查", "warn"),
    ("接口", "link"), ("定位", "link"),
]


# ----------------------------------------------------------------------
# 预处理：保护代码块与公式
# ----------------------------------------------------------------------
def preprocess(text: str):
    fences: list[tuple[str, str]] = []

    def _fence(m):
        fences.append((m.group(1).strip(), m.group(2)))
        return f"\n\n{PH_L}CODE{len(fences) - 1}{PH_R}\n\n"

    text = FENCE_RE.sub(_fence, text)

    maths: list[tuple[str, bool]] = []

    def _math(tex: str, display: bool):
        # 先 unquote 再 strip：反过来会让首行的 `>` 落到字符串开头之外，
        # 无法与公式自身的 `>`（如 `$>0$`）区分。
        maths.append((unquote(tex).strip(), display))
        return f"{PH_L}MATH{len(maths) - 1}{PH_R}"

    text = DISPLAY_DOLLAR.sub(lambda m: _math(m.group(1), True), text)
    text = DISPLAY_BRACKET.sub(lambda m: _math(m.group(1), True), text)
    text = INLINE_PAREN.sub(lambda m: _math(m.group(1), False), text)
    text = INLINE_DOLLAR.sub(lambda m: _math(m.group(1), False), text)

    return text, fences, maths


# ----------------------------------------------------------------------
# 还原：把占位符换回公式 / 代码块
# ----------------------------------------------------------------------
def restore(html_str: str, fences, maths) -> str:
    # 单独成段的占位符，脱掉 <p> 外壳
    html_str = re.sub(r"<p>\s*" + PH_L + r"(MATH\d+|CODE\d+)" + PH_R + r"\s*</p>", PH_L + r"\1" + PH_R, html_str)

    def _sub(m):
        kind, idx = m.group(1), int(m.group(2))
        if kind == "MATH":
            tex, display = maths[idx]
            esc = H.escape(tex, quote=False)
            if display:
                return f'<div class="math-display">\\[{esc}\\]</div>'
            return f'<span class="math-inline">\\({esc}\\)</span>'
        lang, code = fences[idx]
        label = f'<span class="code-lang">{H.escape(lang)}</span>' if lang else ""
        return (
            f'<div class="code-block">{label}'
            f"<pre><code>{H.escape(code)}</code></pre></div>"
        )

    return re.sub(PH_L + r"(MATH|CODE)(\d+)" + PH_R, _sub, html_str)


# ----------------------------------------------------------------------
# 提示框样式化
# ----------------------------------------------------------------------
def style_callouts(html_str: str) -> str:
    """把 `> **标签** …` 引用块着色。

    ⚠ markdown 会把「相邻的多个引用块」合并成一个 <blockquote>
    （只要后一段第一行仍以 `> ` 开头，中间的空行不会终止引用块）。
    于是 `> **例** …` 紧跟 `> **接口** …` 时，二者共用一个 <blockquote>，
    旧实现只看第一个 <p> —— 后面的框全部被当成前一个框的正文，**颜色错误**。

    本实现按 <p> 段落切分：凡是以类型词开头的 <p> 一律另起一个新框；
    非 <p> 的片段（<ul>、<div class="math-display"> 等）并入当前框。
    """
    P_RE = re.compile(r"<p>.*?</p>", re.S)

    def _cls(seg: str):
        """判断片段是否以某个提示框类型词开头，返回对应 class。"""
        head = re.search(r"^\s*<p>\s*<strong>(.{1,24}?)(?:</strong>|[\s　])", seg)
        if not head:
            return None
        name = head.group(1)
        for key, cls in BOX_TYPES:
            if name.startswith(key):
                return cls
        return None

    def _box(m):
        inner = m.group(1)

        parts, pos = [], 0
        for pm in P_RE.finditer(inner):
            if pm.start() > pos:
                parts.append(inner[pos:pm.start()])
            parts.append(pm.group(0))
            pos = pm.end()
        if pos < len(inner):
            parts.append(inner[pos:])

        groups: list = []          # [class 或 None, html]
        for seg in parts:
            cls = _cls(seg)
            if cls is not None:
                groups.append([cls, seg])
            elif groups:
                groups[-1][1] += seg
            else:
                groups.append([None, seg])

        if not groups:
            return m.group(0)
        out = []
        for cls, seg in groups:
            if cls:
                out.append(f'<blockquote class="box box-{cls}">{seg}</blockquote>')
            else:
                out.append(f"<blockquote>{seg}</blockquote>")
        return "".join(out)

    return BLOCK_RE.sub(_box, html_str)


# ----------------------------------------------------------------------
# 标题编号与锚点
# ----------------------------------------------------------------------
def annotate_headings(html_str: str, cid: str):
    heads: list[dict] = []
    counter = [0, 0, 0]  # h2, h3, h4

    def _h(m):
        lvl, inner = int(m.group(1)), m.group(2)
        idx = lvl - 2
        counter[idx] += 1
        for k in range(idx + 1, 3):
            counter[k] = 0
        hid = cid + "-" + "-".join(str(counter[i]) for i in range(idx + 1))
        plain = H.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        plain = re.sub(r"\\\\?[\(\)\[\]]", "", plain)
        heads.append({"level": lvl, "id": hid, "text": plain})
        return (
            f'<h{lvl} id="{hid}">{inner}'
            f'<a class="anchor" href="#{hid}" aria-hidden="true">#</a>'
            f"</h{lvl}>"
        )

    return HEAD_RE.sub(_h, html_str), heads


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    chapters: dict[str, dict] = {}
    built, missing = [], []

    for vol in TOC:
        for ch in vol["chapters"]:
            src = CH_DIR / ch.get("src", ch["id"] + ".md")
            if not src.exists():
                missing.append(ch["id"])
                continue
            raw = src.read_text(encoding="utf-8")

            # 源文件首个 H1 交给框架渲染，正文从 H2 开始
            raw = re.sub(r"^#\s+.*?\n", "", raw, count=1)

            body, fences, maths = preprocess(raw)
            md = markdown.Markdown(extensions=MD_EXT, output_format="html5")
            html_str = md.convert(body)
            html_str = restore(html_str, fences, maths)
            html_str = style_callouts(html_str)
            html_str, heads = annotate_headings(html_str, ch["id"])

            chapters[ch["id"]] = {
                "id": ch["id"],
                "no": ch["no"],
                "title": ch["title"],
                "volume": vol["vol"],
                "html": html_str,
                "headings": heads,
                "chars": len(re.sub(r"\s", "", raw)),
                "formulas": len(maths),
            }
            built.append(ch["id"])

    payload = {
        "meta": BOOK_META,
        "toc": TOC,
        "chapters": chapters,
        "builtAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    js = "window.BOOK_DATA = " + json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (OUT_DIR / "all.js").write_text(js, encoding="utf-8")

    total_chars = sum(c["chars"] for c in chapters.values())
    total_formulas = sum(c["formulas"] for c in chapters.values())
    print(f"[OK] 已构建 {len(built)} 章：{', '.join(built)}")
    print(f"     总字数约 {total_chars:,}，公式 {total_formulas} 处")
    print(f"     输出 → {OUT_DIR / 'all.js'}")
    if missing:
        print(f"[--] 尚未撰写 {len(missing)} 章：{', '.join(missing)}")


if __name__ == "__main__":
    main()

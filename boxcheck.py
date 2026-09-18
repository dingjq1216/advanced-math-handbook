# -*- coding: utf-8 -*-
"""
提示框着色体检（离线 MD 手册项目）
====================================================
读 content/all.js，逐章报告三件事：

  1. 各类提示框的着色计数
  2. **被吞框** —— 每个 <blockquote> 内「除首个 <p> 外」仍以类型词开头的 <p> 个数
     （markdown 会把相邻引用块合并成一个 blockquote；着色实现必须按 <p> 切分）
  3. **漏着色** —— 以类型词开头的 <blockquote> 却没有 class

判据：被吞 = 0 且 漏着色 = 0。

用法：项目根目录下运行 `python boxcheck.py`（配置见下方 CONFIG，不用命令行参数）
"""

from __future__ import annotations

import json
import pathlib
import re

# ======================================================================
# 配置
# ======================================================================
CONFIG = {
    "all_js": "content/all.js",     # 构建产物
    "only_chapters": [],            # 留空 = 全部；否则只报这些 id，如 ["ch12"]
}

BOX_TYPES = [
    "定义", "定理", "命题", "引理", "推论", "例", "例子", "注", "注记",
    "提示", "正确做法", "校验",
    "算法", "约定",
    "要点", "小结", "口诀", "速查", "记忆法", "通用",
    "陷阱", "警告", "铁律", "自查",
    "接口", "定位",
]

HEAD_RE = re.compile(r"^\s*<p>\s*<strong>(.{1,24}?)(?:</strong>|[\s\u3000])")
BQ_RE = re.compile(r"<blockquote([^>]*)>(.*?)</blockquote>", re.S)
P_RE = re.compile(r"<p>.*?</p>", re.S)


def is_box_head(seg: str):
    """片段是否以某个提示框类型词开头。"""
    m = HEAD_RE.match(seg)
    if not m:
        return None
    name = m.group(1)
    for key in BOX_TYPES:
        if name.startswith(key):
            return key
    return None


def load_chapters(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"window\.BOOK_DATA\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not m:
        raise SystemExit("[!!] 未在 all.js 里找到 window.BOOK_DATA")
    data = json.loads(m.group(1))

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "html" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    return list(walk(data))


def report() -> int:
    root = pathlib.Path(__file__).resolve().parent
    path = pathlib.Path(CONFIG["all_js"])
    if not path.exists():
        path = root / CONFIG["all_js"]
    chapters = load_chapters(path)

    only = set(CONFIG["only_chapters"])
    bad_total = 0

    print(f"{'章':<7}{'着色框':>7}{'无色块':>8}{'被吞':>7}{'漏着色':>8}   明细")
    print("-" * 78)
    for ch in chapters:
        if only and ch["id"] not in only:
            continue
        html = ch["html"]

        counts: dict[str, int] = {}
        for cls in re.findall(r'class="box box-([a-z]+)"', html):
            counts[cls] = counts.get(cls, 0) + 1

        swallowed = 0
        for attrs, inner in BQ_RE.findall(html):
            ps = P_RE.findall(inner)
            for seg in ps[1:]:
                if is_box_head(seg):
                    swallowed += 1

        missed = 0
        for attrs, inner in BQ_RE.findall(html):
            if "box" in attrs:
                continue
            if is_box_head(inner):
                missed += 1

        bad_total += swallowed + missed
        detail = " ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        flag = "" if not (swallowed or missed) else "   <== 异常"
        print(f"{ch['id']:<7}{sum(counts.values()):>7}{html.count('<blockquote>'):>8}"
              f"{swallowed:>7}{missed:>8}   {detail}{flag}")

    print("-" * 78)
    if bad_total:
        print(f"[!!] 被吞 + 漏着色 = {bad_total}，需检查 style_callouts 的 <p> 切分逻辑")
    else:
        print("[ok] 被吞 0、漏着色 0 —— 提示框着色正常")
    return bad_total


if __name__ == "__main__":
    raise SystemExit(1 if report() else 0)

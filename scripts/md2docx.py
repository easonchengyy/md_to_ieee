#!/usr/bin/env python3
"""Markdown -> IEEE 风格 Word（.docx）。

用途
----
专门生成 Word 版本。与 PDF 共用同一份源 Markdown，但 Word 不能直接吃
pandoc 的原样输出，必须先做一轮预处理：

  * 标题块：从首行 H1、`**Author**:`、`# Abstract`、`**Index Terms**:`
    提取标题/作者/摘要/关键词，写成 pandoc YAML + IEEE 样式段落
  * 图片：把 `![alt](img)` 与其下方 `**Fig. n　caption**` 合并成一张
    带 caption 的图（否则 Word 里会出现两段残缺图题），并统一指定物理
    宽度 —— 不指定的话 pandoc 按图片原始像素排，普遍是整版宽，必然溢出
  * 表格：`**TABLE n　caption**` 改写成 pandoc 表题，落到 Table Caption 样式
  * 公式：`\\tag{n}` 在 OMML 里会被 pandoc 丢弃，改写成 `\\qquad(n)`
    保住编号
  * 分隔线 `---` 删除（Word 里没有意义）
  * 版式：默认单栏（Word 里表格/图片都按整版宽排，双栏必然溢出）

用法
----
    python3 md2docx.py input.md                    # 单栏，输出同目录
    python3 md2docx.py input.md -o out/            # 指定输出目录
    python3 md2docx.py input.md --fig-width 6.2in  # 改图宽
    python3 md2docx.py input.md --two-columns      # 双栏（表格需自行收窄）
    python3 md2docx.py input.md --keep-md          # 保留预处理后的中间 md
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE_DOCX = HERE / "ieee-reference.docx"
MAKE_REF_DOCX = HERE / "make_reference_docx.py"

TITLE_RE = re.compile(r"^#\s+(?!#)(.+?)\s*$")
AUTHOR_RE = re.compile(r"^\*\*Author\*\*\s*[:：]?\s*(.+?)\s*$")
SID_RE = re.compile(r"\*\*Student ID\*\*\s*[:：]?\s*(\S+)")
ABSTRACT_RE = re.compile(r"^#\s+Abstract\s*$", re.I)
INDEX_RE = re.compile(r"^\*\*Index Terms\*\*\s*[:：]?\s*(.+?)\s*$", re.I)
FIG_HEAD_RE = re.compile(r"^\*\*Fig\.\s*(\d+)\s*(?:\(([a-z])\)\s*\*\*)?[\u3000\s]+(.*)$")
TAB_RE = re.compile(r"^\*\*TABLE\s+([IVXLC]+)[\u3000\s]+(.+?)\*\*\s*$")
IMG_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<path>[^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
TAG_RE = re.compile(r"\\tag\s*\{\s*(\d+)\s*\}")
SECT_RE = re.compile(r"^<w:cols\b[^>]*/>")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 元数据抽取
def split_front_matter(text: str) -> dict:
    """拆出 title / author / abstract / keywords，其余作为 body。"""
    lines = text.splitlines()
    meta = {"title": "", "authors": [], "abstract": "", "keywords": ""}
    body_start = 0

    # 若源文件已带 YAML，直接尊重它，不做任何搬运
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
        meta["has_yaml"] = True
        return meta

    meta["has_yaml"] = False
    i = 0
    # 标题：第一个 H1
    while i < len(lines):
        m = TITLE_RE.match(lines[i])
        if m:
            meta["title"] = m.group(1).strip()
            i += 1
            break
        i += 1
    # 作者行（在 Abstract 之前）
    while i < len(lines) and not ABSTRACT_RE.match(lines[i]):
        m = AUTHOR_RE.match(lines[i])
        if m:
            raw = m.group(1)
            sid = SID_RE.search(lines[i])
            name = SID_RE.sub("", raw).strip(" 　:：,、")
            meta["authors"] = [name] if name else []
            if sid:
                meta["sid"] = sid.group(1)
        i += 1
    # 摘要
    if i < len(lines) and ABSTRACT_RE.match(lines[i]):
        i += 1
        buf = []
        while i < len(lines):
            if (re.match(r"^#\s+\S", lines[i]) or INDEX_RE.match(lines[i])
                    or lines[i].strip() == "---"):
                break
            buf.append(lines[i])
            i += 1
        meta["abstract"] = "\n".join(buf).strip()
    # 关键词
    for j, ln in enumerate(lines):
        m = INDEX_RE.match(ln)
        if m:
            meta["keywords"] = m.group(1).strip()
            break
    # body：从第一个编号章节开始（I. / 1.），否则从摘要之后
    first_sec = re.compile(r"^#\s+(?:[IVXLC]+\.|\d+\.)\s+")
    for j, ln in enumerate(lines):
        if first_sec.match(ln):
            body_start = j
            break
    else:
        body_start = i
    return meta


def merge_authors(meta: dict) -> str:
    """作者行；有学号时另起一行。"""
    names = meta.get("authors") or []
    if not names:
        return ""
    out = "  \n".join(names)
    if meta.get("sid"):
        out += "  \nStudent ID: %s" % meta["sid"]
    return out


# ---------------------------------------------------------------- body 改写
def parse_fig(line):
    """解析图题行，返回 (num, letter, caption, tail)；不是图题则 None。

    源文件里图题常带尾随说明（`**Fig. 8　…。** The low-frequency magnitude …`），
    这些尾句属于图题而不是正文，必须一并并入，否则图题会被截断。
    """
    m = FIG_HEAD_RE.match(line.strip())
    if not m:
        return None
    body = m.group(3)
    if "**" in body:
        cap, tail = body.split("**", 1)
    else:
        cap, tail = body, ""
    return m.group(1), m.group(2), cap.strip(), tail.strip()


def fig_caption(parsed) -> str:
    """规范图题：`**Fig. n**　正文`（可带 (a)/(b) 分图字母）。"""
    num, letter, cap, tail = parsed
    if tail:
        cap = (cap + " " + tail).strip()
    label = "Fig. %s" % num + ("(%s)" % letter if letter else "")
    return "**%s**　%s" % (label, cap)


ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV", "XV", "XVI"]


def _disp_w(s: str) -> int:
    """显示宽度：CJK/全角按 2 计，其余按 1 计。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _cells(row: str) -> list:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_sep(row: str) -> bool:
    s = row.strip()
    return bool(s) and set(s) <= set("|-: ") and "-" in s


def is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


# ---------------------------------------------------------------- 分节（双栏）
PAGE_W, PAGE_H = 12240, 15840
MARGIN_LR, MARGIN_TB = 900, 1080
TEXT_W = PAGE_W - 2 * MARGIN_LR          # 10440 twips = 7.25 in
COL_SPACE = 360
COL_W = (TEXT_W - COL_SPACE) // 2        # 5040 twips = 3.5 in

SECT_OPEN = ("<w:p><w:pPr><w:sectPr><w:type w:val=\"continuous\"/>"
             "<w:pgSz w:w=\"%d\" w:h=\"%d\"/>"
             "<w:pgMar w:top=\"%d\" w:right=\"%d\" w:bottom=\"%d\" w:left=\"%d\" "
             "w:header=\"432\" w:footer=\"432\" w:gutter=\"0\"/>"
             "<w:cols w:num=\"%d\" w:space=\"%d\" w:equalWidth=\"1\"/>"
             "</w:sectPr></w:pPr></w:p>")


def sect_break(cols: int) -> list:
    """产生一个「结束当前节」的段落：其后的内容按 cols 栏续排。

    sectPr 描述的是它**前面**那一节的属性，所以在通栏内容前放一个 cols=2
    的断点、后面放一个 cols=1 的断点，中间就成了一节单栏。
    """
    return ["```{=openxml}",
            SECT_OPEN % (PAGE_W, PAGE_H, MARGIN_TB, MARGIN_LR, MARGIN_TB, MARGIN_LR,
                         cols, COL_SPACE),
            "```", ""]


def png_size(path) -> tuple | None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        return (w, h) if w and h else None
    except OSError:
        return None


def is_wide_fig(line: str, wide_figs, base_dir) -> bool:
    """双栏时判断某张图是否要通栏。

    显式给了 --wide-figs 就按名单；否则按宽高比猜（宽扁的原理图缩到半栏
    后标注会看不清，所以超过 1.95:1 的直接通栏）。
    """
    m = IMG_RE.match(line.strip())
    if not m:
        return False
    path = m.group("path")
    name = Path(path).name
    if wide_figs:
        return name in wide_figs
    full = Path(path) if Path(path).is_absolute() else Path(base_dir or ".") / path
    size = png_size(full)
    return bool(size) and size[0] / size[1] >= 1.95


def rebalance_table(block) -> list:
    """按各列内容长度重写分隔行，让 pandoc 按比例分配列宽。

    pandoc 把分隔行的短横数量当作相对宽度，全用 `|---|` 就会得到等宽列，
    长文本列被挤成七八行。这里按每列最长单元格估算权重，再换算成短横数。
    """
    if len(block) < 2 or not _is_sep(block[1]):
        return block
    rows = [block[0]] + block[2:]
    ncol = max(len(_cells(r)) for r in rows)
    weights = []
    for j in range(ncol):
        w = 0
        for r in rows:
            cs = _cells(r)
            if j < len(cs):
                w = max(w, _disp_w(cs[j]))
        weights.append(max(w, 10))

    seps = _cells(block[1])
    out_sep = []
    for j in range(len(seps)):
        token = seps[j]
        left = token.startswith(":")
        right = token.endswith(":")
        dashes = "-" * max(3, min(60, int(round(weights[j] * 1.3))))
        out_sep.append((":" if left else "") + dashes + (":" if right else ""))
    new = list(block)
    new[1] = "|" + "|".join(out_sep) + "|"
    return new


def plan_tables(lines):
    """给每张表定编号，并补齐缺失的表题。

    返回 (cap_rewrite, cap_insert, table_starts)：
      cap_rewrite[i] = 该行是表题，改成新编号后的文本
      cap_insert[j]  = 第 j 行是表头首行，需在其前插入该表题
    """
    n = len(lines)
    starts = []
    i = 0
    while i < n:
        if is_table_row(lines[i]) and i + 1 < n and _is_sep(lines[i + 1]):
            j = i
            while j < n and is_table_row(lines[j]):
                j += 1
            starts.append(i)
            i = j
        else:
            i += 1

    cap_rewrite, cap_insert = {}, {}
    for k, st in enumerate(starts):
        num = ROMAN[k] if k < len(ROMAN) else str(k + 1)
        # 表题就在表头上方（允许中间空行）
        cap_at = None
        back = st - 1
        while back >= 0 and not lines[back].strip():
            back -= 1
        if back >= 0 and TAB_RE.match(lines[back].strip()):
            cap_at = back
        if cap_at is not None:
            cap_rewrite[cap_at] = ": TABLE %s\u3000%s" % (
                num, TAB_RE.match(lines[cap_at].strip()).group(2).strip())
        else:
            # 用最近的（小）节标题兜底，去掉编号前缀
            heading = "Results"
            for b in range(st - 1, -1, -1):
                s = lines[b].strip()
                if s.startswith("#"):
                    heading = re.sub(r"^#+\s*", "", s)
                    heading = re.sub(r"^(?:[IVXLC]+\.|[A-Z]\.|\([a-z0-9]+\))\s*", "", heading)
                    heading = heading.strip()
                    break
            cap_insert[st] = ": TABLE %s\u3000%s" % (num, heading or "Results")
    return cap_rewrite, cap_insert, starts


def transform_body(lines, fig_width: str, number_equations: bool,
                   two_columns: bool = False, wide_figs=None,
                   base_dir=None, wide_fig_width: str = "6.9in") -> str:
    n = len(lines)
    cap_rewrite, cap_insert, table_starts = plan_tables(lines)

    # 预扫描：每张图向后找图题，中间只允许空行（多图共用一个图题时，
    # 只有紧邻图题的那张能直接匹配到）
    is_img = [bool(IMG_RE.match(lines[i].strip())) for i in range(n)]
    cap_match = [parse_fig(lines[i]) for i in range(n)]

    # 哪些表要通栏；通栏表的表题必须先进入同一个单栏节，否则表题会被
    # 留在双栏节里、和表格分家（Word 里图题跟在表后面跨页就是这么来的）
    table_wide, cap_to_table = {}, {}
    for st in table_starts:
        j = st
        while j < n and is_table_row(lines[j]):
            j += 1
        table_wide[st] = two_columns and max(len(_cells(r)) for r in lines[st:j]) > 3
        for back in (st - 1, st - 2, st - 3):
            if back >= 0 and TAB_RE.match(lines[back].strip()):
                cap_to_table[back] = st
                break
    wide_caps = {c for c, st in cap_to_table.items() if table_wide.get(st)}
    widened = set()
    cap_for = {}
    for i in range(n):
        if not is_img[i]:
            continue
        j = i + 1
        while j < n and not lines[j].strip():
            j += 1
        if j < n and cap_match[j]:
            cap_for[i] = j

    # 图组：连续若干张图（中间只有空行），末尾跟一个图题
    group_end = {}
    for i in range(n):
        if not is_img[i]:
            continue
        run = [i]
        k = i
        while True:
            j = k + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and is_img[j]:
                run.append(j)
                k = j
                continue
            break
        for idx in run:
            group_end[idx] = run

    # 孤立图（后续有正文、没有图题）：借用后面的图号，标成 (a)/(b)
    orphan_letter = {}

    out = []
    consumed = set()
    i = 0
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if s == "---":
            i += 1
            continue

        if is_img[i]:
            run = group_end.get(i, [i])
            cap_line = cap_for.get(run[-1])
            wide = two_columns and is_wide_fig(lines[run[0]], wide_figs, base_dir)
            w = wide_fig_width if wide else fig_width
            if cap_line is not None:
                if wide:
                    out.extend(sect_break(2))
                cap = fig_caption(cap_match[cap_line])
                if len(run) > 1:
                    # 多图共用一个图题：图片堆叠成一段，图题另起一段落到
                    # Image Caption 样式，避免每张图各带一段残缺图题
                    imgs = []
                    for r in run:
                        m = IMG_RE.match(lines[r].strip())
                        imgs.append("![](%s){width=%s}" % (m.group("path"), w))
                    out.append("\\\n".join(imgs))
                    out.append("")
                    out.append('::: {custom-style="Image Caption"}')
                    out.append(cap)
                    out.append(":::")
                else:
                    m = IMG_RE.match(lines[run[0]].strip())
                    out.append("![%s](%s){width=%s}" % (cap, m.group("path"), w))
                    out.append("")
                consumed.add(cap_line)
                for r in run:
                    consumed.add(r)
                i = max(run + [cap_line]) + 1
                if wide:
                    out.extend(sect_break(1))
                continue

            # 无图题的孤立图
            m = IMG_RE.match(s)
            alt = m.group("alt").strip() or "figure"
            nxt = None
            k = i + 1
            seen = 0
            while k < n and seen <= 8:
                t = lines[k].strip()
                if t:
                    seen += 1
                    if cap_match[k]:
                        nxt = k
                        break
                k += 1
            if nxt is not None:
                num = cap_match[nxt][0]
                letter = orphan_letter.get(num)
                if letter is None:
                    letter = "a"
                    orphan_letter[num] = "a"
                    # 后一个图题降级为 (b)
                    lines[nxt] = fig_caption(cap_match[nxt]).replace(
                        "**Fig. %s**" % num, "**Fig. %s(b)**" % num, 1)
                    cap_match[nxt] = parse_fig(lines[nxt])
                else:
                    letter = "b"
                out.append("![**Fig. %s(%s)**　%s](%s){width=%s}" % (
                    num, letter, alt.rstrip(".") + ".", m.group("path"), fig_width))
            else:
                out.append("![%s](%s){width=%s}" % (alt, m.group("path"), fig_width))
            out.append("")
            consumed.add(i)
            i += 1
            continue

        # 表题（编号按出现顺序重排）
        mt = TAB_RE.match(s)
        if mt:
            if i in wide_caps:
                out.extend(sect_break(2))
                widened.add(cap_to_table[i])
            if i in cap_rewrite:
                out.append(cap_rewrite[i])
            else:
                out.append(": TABLE %s　%s" % (mt.group(1), mt.group(2).strip()))
            out.append("")
            i += 1
            continue

        # 表格：缺表题的先补，再按内容重排列宽
        if i in table_starts:
            j = i
            while j < n and is_table_row(lines[j]):
                j += 1
            wide = table_wide.get(i, False)
            if wide and i not in widened:
                out.extend(sect_break(2))
            if i in cap_insert:
                out.append(cap_insert[i])
                out.append("")
            out.extend(rebalance_table(lines[i:j]))
            out.append("")
            if wide:
                out.extend(sect_break(1))
            i = j
            continue

        if i in consumed:
            i += 1
            continue

        out.append(ln)
        i += 1

    text = "\n".join(out)
    if number_equations:
        # \tag{n} -> \qquad(n)：pandoc 的 OMML 转换会丢弃 \tag，编号会凭空消失
        text = TAG_RE.sub(lambda m: "\\qquad(%s)" % m.group(1), text)
    else:
        text = TAG_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def build_markdown(md: Path, fig_width: str, number_equations: bool,
                   two_columns: bool = False, wide_figs=None) -> str:
    text = _read(md)
    meta = split_front_matter(text)
    lines = text.splitlines()

    if meta["has_yaml"]:
        # 已有 YAML：只做 body 级改写（图片宽度、表题、公式编号）
        head_end = 0
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                head_end = i + 1
                break
        yaml_head = "\n".join(lines[:head_end])
        body = transform_body(lines[head_end:], fig_width, number_equations,
                              two_columns, wide_figs, md.parent)
        if two_columns:
            # 标题块单栏，正文起双栏
            return yaml_head + "\n\n" + "\n".join(sect_break(1)) + "\n" + body
        return yaml_head + "\n\n" + body

    fm = ["---"]
    fm.append('title: "%s"' % meta["title"].replace('"', '\\"'))
    au = merge_authors(meta)
    if au:
        fm.append("author:")
        fm.append("  - |")
        for ln in au.splitlines():
            fm.append("    " + ln)
    fm.append("---")
    fm.append("")

    if meta["abstract"]:
        fm.append('::: {custom-style="Abstract"}')
        fm.append("*Abstract*—" + " ".join(meta["abstract"].split()))
        fm.append(":::")
        fm.append("")
    if meta["keywords"]:
        fm.append('::: {custom-style="Abstract"}')
        fm.append("*Index Terms*—" + meta["keywords"])
        fm.append(":::")
        fm.append("")

    body = transform_body(lines[body_start_index(lines):], fig_width, number_equations,
                          two_columns, wide_figs, md.parent)
    if two_columns:
        fm.extend(sect_break(1))
    return "\n".join(fm) + "\n" + body


def body_start_index(lines) -> int:
    first_sec = re.compile(r"^#\s+(?:[IVXLC]+\.|\d+\.)\s+")
    for j, ln in enumerate(lines):
        if first_sec.match(ln):
            return j
    return 0


# ---------------------------------------------------------------- docx 后处理
def set_columns(docx: Path, num: int, space: int = 360) -> None:
    """改写**正文节**的栏数（默认单栏）。

    只动最后一个 sectPr —— 也就是 body 级那一个。通栏图表用的分节符也带
    sectPr，一并改写会把通栏区域重新拉回双栏。
    """
    tmp = docx.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                cols = '<w:cols w:num="%d" w:space="%d" w:equalWidth="1"/>' % (num, space)
                at = xml.rfind("<w:sectPr>")
                if at == -1:
                    xml = xml.replace("</w:body>", cols + "</w:body>")
                else:
                    xml = xml[:at] + re.sub(r"<w:cols\b[^>]*/>", cols, xml[at:], count=1)
                    if "<w:cols" not in xml[at:]:
                        xml = xml.replace("</w:sectPr>", cols + "</w:sectPr>", 1)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp), str(docx))


def shrink_display_math(xml: str, half_points: int = 17, min_chars: int = 55) -> str:
    """双栏时把**过长的**独立公式缩到 8.5 pt。

    公式宽度按整版排，长公式塞进半栏会溢出（Word 不会自动缩行），只能把
    这类公式的字号降一档。短公式保持原字号，免得全篇公式都比正文小。
    """
    def one(m):
        blk = m.group(0)
        text = "".join(re.findall(r"<m:t[^>]*>(.*?)</m:t>", blk, re.S))
        if len(text) < min_chars:
            return blk
        rpr = ('<w:rPr><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
               % (half_points, half_points))
        return re.sub(r"(<m:r>(?:<m:rPr>.*?</m:rPr>)?)(<m:t)", r"\1" + rpr + r"\2", blk)

    return re.sub(r"<m:oMathPara>.*?</m:oMathPara>", one, xml, flags=re.S)


def keep_rows_together(tbl: str) -> str:
    """让整张表尽量不跨栏/跨页断开：除最后一行外，全部 keepNext。"""
    rows = tbl.split("<w:tr>")
    if len(rows) <= 2:
        return tbl
    head, body = rows[0], rows[1:]
    for k in range(len(body) - 1):
        body[k] = re.sub(r"<w:pPr>", "<w:pPr><w:keepNext/>", body[k])
    return head + "<w:tr>" + "<w:tr>".join(body)


def fit_columns(cols, target: int) -> list:
    """把列宽比例缩放到 target，并给窄列一个下限，但总和不得超出 target。

    下限按列数摊（target/(n*1.6)），否则 6 列的表每列都顶到下限，
    加起来的表宽会比版心还宽。
    """
    n = len(cols)
    total = sum(cols) or 1
    floor = max(520, int(target / (n * 1.6)))
    w = [max(floor, int(round(c * target / total))) for c in cols]

    over = sum(w) - target
    if over > 0:
        flex = [i for i, x in enumerate(w) if x > floor]
        pool = sum(w[i] - floor for i in flex)
        if pool > 0:
            for i in flex:
                w[i] -= int(round(over * (w[i] - floor) / pool))
            over = sum(w) - target
        if over > 0:                     # 全被压到下限，只能整体等比缩
            k = target / sum(w)
            w = [int(x * k) for x in w]
    w[-1] += target - sum(w)
    return [max(300, x) for x in w]


def widen_tables(docx: Path, full_twips: int = 9936, col_twips: int = 4980) -> None:
    """把每张表按原列宽比例撑到所在节的宽度（pandoc 默认只有 5.5 in）。

    双栏时表要区分：落在单栏节里的表撑到一栏宽，落在通栏节里的撑到版心宽。
    sectPr 描述的是它前面那一节，所以某张表的栏数要看它**之后**最近的 sectPr。
    """
    tmp = docx.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")

                sects = []
                for m in re.finditer(r"<w:sectPr>.*?</w:sectPr>", xml, re.S):
                    mm = re.search(r'<w:cols w:num="(\d+)"', m.group(0))
                    sects.append((m.start(), int(mm.group(1)) if mm else 1))

                def cols_at(pos: int) -> int:
                    for p, n in sects:
                        if p > pos:
                            return n
                    return 1

                pieces, last = [], 0
                for m in re.finditer(r"<w:tbl>.*?</w:tbl>", xml, re.S):
                    target = full_twips if cols_at(m.start()) == 1 else col_twips
                    tbl = m.group(0)
                    cols = [int(x) for x in re.findall(r'<w:gridCol w:w="(\d+)"', tbl)]
                    if cols:
                        new = fit_columns(cols, target)
                        it = iter(new)
                        tbl = re.sub(r'(<w:gridCol w:w=")\d+(")',
                                     lambda mm: mm.group(1) + str(next(it)) + mm.group(2), tbl)
                        tbl = re.sub(r'<w:tblW[^>]*/>',
                                     '<w:tblW w:type="dxa" w:w="%d"/>' % target, tbl, count=1)
                        tbl = tbl.replace(
                            "</w:tblPr>",
                            '<w:tblCellMar><w:left w:w="57" w:type="dxa"/>'
                            '<w:right w:w="57" w:type="dxa"/></w:tblCellMar></w:tblPr>', 1)
                        tbl = keep_rows_together(tbl)
                    pieces.append(xml[last:m.start()])
                    pieces.append(tbl)
                    last = m.end()
                pieces.append(xml[last:])
                xml = "".join(pieces)

                def no_split(m):
                    row = m.group(0)
                    if "<w:trPr>" in row:
                        return row.replace("<w:trPr>", "<w:trPr><w:cantSplit/>", 1)
                    return row.replace("<w:tr>", "<w:tr><w:trPr><w:cantSplit/></w:trPr>", 1)

                xml = re.sub(r"<w:tr>.*?</w:tr>", no_split, xml, flags=re.S)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp), str(docx))


def shrink_math_in(docx: Path, half_points: int = 17) -> None:
    tmp = docx.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = shrink_display_math(data.decode("utf-8"), half_points).encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp), str(docx))


def ensure_reference() -> None:
    if REFERENCE_DOCX.exists():
        return
    print("生成 IEEE Word 参考模板 ...")
    subprocess.run([sys.executable, str(MAKE_REF_DOCX), str(REFERENCE_DOCX)], check=True)


def build_docx(md: Path, outdir: Path, stem: str | None = None,
               fig_width: str = "6.9in", number_equations: bool = True,
               two_columns: bool = False, keep_md: bool = False,
               wide_figs=None) -> Path:
    ensure_reference()
    outdir.mkdir(parents=True, exist_ok=True)
    stem = stem or md.stem
    src_md = outdir / (stem + ".docx-src.md")
    src_md.write_text(build_markdown(md, fig_width, number_equations,
                                     two_columns, wide_figs), encoding="utf-8")

    docx = outdir / (stem + ".docx")
    # 资源路径：图按 md 所在目录解析，故 pandoc 需以 md 目录为工作目录
    # 不要加 --columns=200：pandoc 只有在「表格比版心宽」时才按分隔行短横
    # 的比例分配列宽，放宽列宽上限会让所有表退化成等宽列
    cmd = ["pandoc", str(src_md), "-o", str(docx),
           "--reference-doc=%s" % REFERENCE_DOCX,
           "--resource-path=%s" % md.parent]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(_safe(proc.stdout)[-3000:] + "\n" + _safe(proc.stderr)[-3000:])
        raise SystemExit("pandoc 转换 Word 失败")

    set_columns(docx, 2 if two_columns else 1)
    widen_tables(docx)
    if two_columns:
        shrink_math_in(docx)
    if not keep_md:
        src_md.unlink(missing_ok=True)
    return docx


def _safe(b) -> str:
    return b.decode("utf-8", errors="replace") if isinstance(b, bytes) else (b or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown 转 IEEE 风格 Word")
    ap.add_argument("input")
    ap.add_argument("-o", "--output-dir", default=None)
    ap.add_argument("--fig-width", default=None,
                    help="图片宽度；单栏默认 6.9in，双栏默认 3.4in（半栏）")
    ap.add_argument("--no-number-equations", action="store_true",
                    help="去掉公式编号")
    ap.add_argument("--two-columns", action="store_true", help="双栏排版")
    ap.add_argument("--wide-figs", default=None,
                    help="双栏时强制通栏的图片文件名，逗号分隔；不给则按宽高比自动判断")
    ap.add_argument("--keep-md", action="store_true", help="保留预处理后的 md")
    args = ap.parse_args()

    md = Path(args.input).resolve()
    if not md.exists():
        print("找不到输入文件:", md)
        return 1
    outdir = Path(args.output_dir).resolve() if args.output_dir else md.parent
    fig_width = args.fig_width or ("3.4in" if args.two_columns else "6.9in")
    wide = {s.strip() for s in args.wide_figs.split(",")} if args.wide_figs else None
    p = build_docx(md, outdir, fig_width=fig_width,
                   number_equations=not args.no_number_equations,
                   two_columns=args.two_columns, keep_md=args.keep_md,
                   wide_figs=wide)
    print("✓", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())

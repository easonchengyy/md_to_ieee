#!/usr/bin/env python3
"""pandoc LaTeX 输出后处理器：把 longtable 改写成 IEEE 风格的 table。

背景
----
pandoc 把 Markdown 表格统一输出成 longtable 环境，而 longtable 只能在
单栏版式里工作，与 IEEEtran 的双栏模板不兼容。IEEE 论文中的表格应当是
浮动体（table 环境）：表题居上、三线表、8pt 字号。

pandoc 生成的 longtable 结构：

    \begin{longtable}[]{@{}ll@{}}
    \caption{标题}\tabularnewline
    \toprule\noalign{}
    表头 A & 表头 B \\
    \midrule\noalign{}
    \endfirsthead
    \toprule\noalign{}        <- 续页表头，删除
    表头 A & 表头 B \\
    \midrule\noalign{}
    \endhead
    \bottomrule\noalign{}     <- 删除
    \endlastfoot
    数据行 ... \\
    \end{longtable}

改写为：

    \begin{table}[!t]
    \centering
    \caption{标题}
    \begin{tabular}{@{}ll@{}}
    \toprule
    表头 A & 表头 B \\
    \midrule
    数据行 ... \\
    \bottomrule
    \end{tabular}
    \end{table}

用法：
    python3 fix_tables.py file.tex                  # 就地改写，用默认阈值
    python3 fix_tables.py file.tex --wide-threshold 5
    python3 fix_tables.py file.tex --no-resize
"""
import argparse
import re
import sys
from pathlib import Path

# 版式阈值（可用命令行覆盖）：
#   列数 <= wide_threshold  -> 单栏浮动表 table
#   列数 >  wide_threshold  -> 通栏浮动表 table*
# 默认 4：4 列的表（如 参数/TT/FF/SS）内容通常很短，单栏足够；
# 做成通栏会同时占掉左右两栏，是页数超限最常见的原因。
# 若某个5~6 列表确实窄，放宽到 5~6 能显著省版面。
DEFAULT_WIDE_THRESHOLD = 4


def _grab_braced(text: str, start: int):
    """从 text[start] == '{' 开始，返回 (花括号内内容, 右括号之后的位置)。

    pandoc 的列格式串如 @{}ll@{} 内部含成对花括号，必须按配对规则提取。
    """
    if text[start] != "{":
        raise ValueError("expected '{' at %d" % start)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
    raise ValueError("unbalanced braces")


LONGTABLE_START = re.compile(r"\\begin\{longtable\}")
END_MARKER = "\\end{longtable}"


def iter_longtables(src: str):
    """逐个产出 (start, end, colspec, body)。"""
    for m in LONGTABLE_START.finditer(src):
        i = m.end()
        # 跳过可选的 [位置参数]，例如 [!t]
        if i < len(src) and src[i] == "[":
            j = src.find("]", i)
            if j != -1:
                i = j + 1
        while i < len(src) and src[i].isspace():
            i += 1
        if i >= len(src) or src[i] != "{":
            continue
        colspec, i = _grab_braced(src, i)
        end = src.find(END_MARKER, i)
        if end == -1:
            continue
        yield m.start(), end + len(END_MARKER), colspec, src[i:end]


def _strip_markers(text: str) -> str:
    """清掉 longtable 专有标记，只留下可放进 tabular 的内容。"""
    text = text.replace("\\noalign{}", "")
    text = text.replace("\\tabularnewline", "")
    for tok in ("\\endfirsthead", "\\endhead", "\\endlastfoot"):
        text = text.replace(tok, "")
    return text


MINIPAGE_CELL_RE = re.compile(
    r"\\begin\{minipage\}\[b\]\{[^}]*\}\\raggedright\s*(.*?)\\end\{minipage\}",
    re.S,
)


def _unwrap_minipages(text: str) -> str:
    """pandoc 给每个表头单元格套了 minipage，在定宽表格里是多余的。

    minipage 宽度是 \\linewidth，放进 l 列会导致整表远超栏宽（实测 2600pt+）。
    这里把包裹层剥掉，只留内容。
    """
    return MINIPAGE_CELL_RE.sub(lambda m: m.group(1).strip(), text)


def _split_header_body(body: str):
    """把 longtable 主体拆成 (表头段, 数据段)，丢弃续页表头。"""
    head, rest = body, ""
    for splitter in ("\\endfirsthead", "\\endhead", "\\endlastfoot"):
        if splitter in head:
            head, rest = head.split(splitter, 1)
            break
    # 数据段前面可能还粘着续页标记
    for splitter in ("\\endlastfoot", "\\endhead", "\\endfirsthead"):
        if splitter in rest:
            _, rest = rest.split(splitter, 1)
            break
    return _strip_markers(head).strip(), _strip_markers(rest).strip()


def _extract_caption(head: str):
    """取出 \\caption{...}，返回 (标题源码, 去掉标题后的表头)。"""
    m = re.search(r"\\caption(?:\[[^\]]*\])?\{", head)
    if not m:
        return "", head
    try:
        inner, after = _grab_braced(head, head.index("{", m.start()))
    except ValueError:
        return "", head
    caption = "\\caption{%s}" % inner
    head = head[: m.start()] + head[after:]
    return caption, head


def _convert(colspec: str, body: str, wide_threshold: int, resize: bool) -> str:
    head, rest = _split_header_body(body)
    caption, head = _extract_caption(head)
    head = head.replace("\\toprule", "").replace("\\midrule", "").strip()
    head = _unwrap_minipages(head)
    rest = _unwrap_minipages(rest)

    # 列数决定版式：窄表走单栏，宽表才做通栏。
    ncols = _count_columns(colspec)
    env = "table" if ncols <= wide_threshold else "table*"
    #   通栏表给出 [t]/[b] 两个位置，配合模板里的 stfloats，
    #   浮动体能同时排在页顶和页底，避免图表密集时堆到文末、留出大片空白。
    pos = "[!t]" if env == "table" else "[!tb]"

    # 含 \texttt 的长代码串要能换行，否则会溢出整栏
    if "\\texttt{" in body:
        colspec = _wrappable_colspec(colspec, ncols)

    lines = ["\\begin{%s}%s" % (env, pos), "\\centering"]
    if caption:
        lines.append(caption)

    # 列多的表：只在「自然宽度超过可用宽度」时缩小，绝不放大。
    # 用 \ifdim\width>目标 判断：窄表保持原尺寸，避免被拉伸到通栏而虚增高度。
    target = "\\textwidth" if env == "table*" else "\\linewidth"
    shrink = resize and ncols > 2
    if shrink:
        lines.append("\\resizebox{\\ifdim\\width>%s %s\\else\\width\\fi}{!}{%%"
                     % (target, target))

    lines.append("\\begin{tabular}{" + colspec + "}")
    lines.append("\\toprule")
    if head:
        lines.append(head)
        lines.append("\\midrule")
    if rest:
        lines.append(rest)
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    if shrink:
        lines.append("}")
    lines.append("\\end{%s}" % env)
    return "\n".join(lines)


def _wrappable_colspec(colspec: str, ncols: int) -> str:
    """把 l 列换成可换行的 p{} 列，用于含长代码串的表格。

    文本列继续用 l，最后一列（通常是代码）用 p 列允许多行换行。
    """
    if ncols <= 1:
        return colspec
    if ncols == 2:
        return ("@{}>{\\raggedright\\arraybackslash}p{0.40\\linewidth}"
                ">{\\raggedright\\arraybackslash}p{0.56\\linewidth}@{}")
    # 多于两列：前面的列保持 l，最后一列改成可换行的 p 列
    prefix = "l" * (ncols - 1)
    return ("@{}%s>{\\raggedright\\arraybackslash}p{0.40\\linewidth}@{}"
            % prefix)


def _count_columns(colspec: str) -> int:
    """从 tabular 列格式里数列数。

    只统计列格式本身（形如 @{}llc@{}），"l/c/r" 各算一列，
    p{...}/m{...}/b{...} 各算一列及其内容。
    注意不要被列格式之外的名字误导。
    """
    n = 0
    i = 0
    while i < len(colspec):
        ch = colspec[i]
        if ch in "@!><":
            # @{...} !{...} 以及 >{...} <{...} 都要整体跳过
            if i + 1 < len(colspec) and colspec[i + 1] == "{":
                depth, j = 0, i + 1
                while j < len(colspec):
                    if colspec[j] == "{":
                        depth += 1
                    elif colspec[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                i = j
        elif ch in "lcrX":
            n += 1
        elif ch in "pmb" and i + 1 < len(colspec) and colspec[i + 1] == "{":
            n += 1
            depth, j = 0, i + 1
            while j < len(colspec):
                if colspec[j] == "{":
                    depth += 1
                elif colspec[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            i = j
        i += 1
    return n


FIGURE_HYPERTARGET_RE = re.compile(
    r"\\begin\{figure\}\s*\\hypertarget\{([^}]*)\}\{%\s*(.*?)\s*\}\s*\\end\{figure\}",
    re.S,
)

FIGURE_BOUNDED_RE = re.compile(
    r"\\begin\{figure\}\s*\\centering\s*(.*?)\\end\{figure\}", re.S
)

# pandoc 3.x 给显式定宽的图套 \pandocbounded{...}；模板里已 providecommand
# 定义为「超栏宽才等比缩小」，这里仅在图内已有 \caption 时做一次整理。
CAPTION_INNER_RE = re.compile(r"(.*?)(\\caption\{.*?\})\s*$", re.S)


def _fix_figures(src: str) -> str:
    """规范 pandoc 生成的 figure 环境。

    pandoc 会输出两种包装，都会干扰 IEEE 双栏排版：

    1. 旧版（<= 2.x）用 \\hypertarget 包住全部内容：

           \\begin{figure}
           \\hypertarget{fig:xxx}{%
           \\centering
           \\includegraphics{...}
           \\caption{...}\\label{fig:xxx}
           }
           \\end{figure}

       这个分组会把 \\centering 和 \\caption 关进一个组里，
       导致图片不居中、图编号异常。剥掉包装层即可。

    2. 新版（3.x）对显式定宽的图改用 \\pandocbounded{\\includegraphics...}。
       模板已定义该命令，此处只需保证 \\caption 在 bounded 盒之外，
       这样编号右对齐不受缩放影响。
    """

    def repl_hypertarget(m: re.Match) -> str:
        return "\\begin{figure}\n%s\n\\end{figure}" % m.group(2).strip()

    def repl_bounded(m: re.Match) -> str:
        inner = m.group(1).strip()
        cm = CAPTION_INNER_RE.match(inner)
        if cm and "\\pandocbounded" in cm.group(1):
            # 把 caption 提到 bounded 盒外，保证编号不被缩放
            inner = "%s\n%s" % (cm.group(1).strip(), cm.group(2).strip())
        pos = "" if "[!" in m.group(0)[:40] else "[!tb]"
        return "\\begin{figure}%s\n\\centering\n%s\n\\end{figure}" % (pos, inner)

    src = FIGURE_HYPERTARGET_RE.sub(repl_hypertarget, src)
    src = FIGURE_BOUNDED_RE.sub(repl_bounded, src)
    return src


DISPLAY_MATH_RE = re.compile(r"^\\\[(.*?)\\\]$", re.S | re.M)


def _fix_display_math(src: str) -> str:
    """把过长的行间公式包进 \\resizebox，防止溢出栏宽。

    判定方式：把公式源码里的 LaTeX 命令替换成等长的占位符，
    再按「渲染后大概占多少字符宽」估算。超过阈值就缩放到 \\linewidth。
    编号 \\eqno 留在缩放盒之外，仍然右对齐。
    """
    # 单栏大约能容纳的「有效字符宽度」，经验值
    MAX_WIDTH = 48

    def _est_width(body: str) -> float:
        w = 0.0
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\":
                m = re.match(r"\\[a-zA-Z]+", body[i:])
                if m:
                    cmd = m.group(0)
                    # 分数、根号这类结构按窄字符算，其余命令按 1 算
                    w += 1.0
                    i += len(cmd)
                    continue
                w += 1.0  # 转义字符 \mu 之类
                i += 2
                continue
            if ch in "{}":
                i += 1
                continue
            if ch.isspace():
                # 普通空格算 0.6，\quad 之类已被命令分支吃掉
                w += 0.6
                i += 1
                continue
            w += 1.0
            i += 1
        return w

    def repl(m: re.Match) -> str:
        body = m.group(1)
        if _est_width(body) <= MAX_WIDTH:
            return m.group(0)
        # 把 \eqno 拆出来，编号留在缩放盒之外
        eq = ""
        eqm = re.search(r"\\eqno\{.*?\}\s*$", body, re.S)
        if eqm:
            eq = eqm.group(0).strip()
            body = body[: eqm.start()]
        return ("\\[\n\\resizebox{\\linewidth}{!}{$\\displaystyle %s$}%s\n\\]"
                % (body.strip(), (" " + eq) if eq else ""))

    return DISPLAY_MATH_RE.sub(repl, src)


def _demote_leading_float(src: str) -> str:
    """把正文第一个浮动体从 [!t] 降级为 [!b]。

    IEEEtran 的标题块（\\maketitle + abstract + index terms）是通栏结构，
    而紧随其后的第一个浮动表若带 [!t]，LaTeX 会把它排到标题块「上方」，
    结果表格出现在摘要之前，违反 IEEE 顺序。文本流顶部已被标题块占满，
    把首个浮动体改为优先页底即可自然避开。
    """
    m = re.search(r"\\begin\{(table\*?|figure\*?)\}\[!t\]", src)
    if not m:
        return src
    return src[:m.start()] + "\\begin{%s}[!b]" % m.group(1) + src[m.end():]


def fix_all(path: str, wide_threshold: int = DEFAULT_WIDE_THRESHOLD,
            resize: bool = True) -> tuple:
    src = open(path, encoding="utf-8").read()
    out, pos, n = [], 0, 0
    for start, end, colspec, body in iter_longtables(src):
        out.append(src[pos:start])
        out.append(_convert(colspec, body, wide_threshold, resize))
        pos = end
        n += 1
    out.append(src[pos:])
    result = _fix_figures("".join(out))
    result = _fix_display_math(result)
    result = _demote_leading_float(result)
    open(path, "w", encoding="utf-8").write(result)
    return n, result.count("\\begin{figure}")


def fix_tables(path: str, wide_threshold: int = DEFAULT_WIDE_THRESHOLD,
               resize: bool = True) -> int:
    n, _ = fix_all(path, wide_threshold, resize)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="把 pandoc 的 longtable 改写成 IEEE 表格")
    ap.add_argument("tex", help="要就地改写的 .tex 文件")
    ap.add_argument("--wide-threshold", type=int, default=DEFAULT_WIDE_THRESHOLD,
                    help="列数超过此值才排成通栏 table*（默认 %d）" % DEFAULT_WIDE_THRESHOLD)
    ap.add_argument("--no-resize", action="store_true",
                    help="不自动缩放超宽表格")
    a = ap.parse_args()
    if not Path(a.tex).exists():
        sys.exit("找不到文件: %s" % a.tex)
    print("rewrote %d table(s)" % fix_tables(a.tex, a.wide_threshold, not a.no_resize))

#!/usr/bin/env python3
"""Markdown -> IEEE 论文（LaTeX / PDF / Word）。

流水线
------
                        ┌──► assets/ieee-template.tex ──► .tex ──►(引擎)──► .pdf
Markdown ──(pandoc)─────┤
                        └──► scripts/ieee-reference.docx ──► .docx

必须走 .tex 中转：pandoc 直接输出 PDF 会用longtable，而 longtable 与
IEEEtran 的双栏版式不兼容，编译必然失败。所以先产出 .tex，经 fix_tables.py
把 longtable 改写成 IEEE 浮动表，再编译。

用法
----
    python3 md2ieee.py input.md                  # tex + pdf + docx
    python3 md2ieee.py input.md --pdf            # 只要 PDF
    python3 md2ieee.py input.md --tex            # 只要 LaTeX
    python3 md2ieee.py input.md --docx           # 只要 Word
    python3 md2ieee.py input.md -o out/          # 指定输出目录
    python3 md2ieee.py input.md --images-dir fig --copy-images
    python3 md2ieee.py input.md --wide-threshold 5
    python3 md2ieee.py input.md --target-pages 6 # 报告页数偏差

产物命名：input.tex / input.pdf / input.docx
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
TEMPLATE_TEX = SKILL_ROOT / "assets" / "ieee-template.tex"
REFERENCE_DOCX = HERE / "ieee-reference.docx"
FIX_TABLES = HERE / "fix_tables.py"
MAKE_REF_DOCX = HERE / "make_reference_docx.py"

# 引擎查找顺序：环境变量 -> PATH -> 常见安装位置。
# Tectonic 是单文件引擎，自带 TeX 宏包，brew install 失败时也能用。
TECTONIC_CANDIDATES = [
    os.environ.get("TECTONIC", ""),
    shutil.which("tectonic") or "",
    str(Path.home() / ".workbuddy" / "binaries" / "tectonic" / "tectonic"),
    "/opt/homebrew/bin/tectonic",
    "/usr/local/bin/tectonic",
]

IMG_MD_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)\s]+)")
IMG_LATEX_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")


def find_tectonic() -> str | None:
    for cand in TECTONIC_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    return None


def run(cmd, **kw):
    """执行外部命令；失败时打印可读的诊断信息。

    传统 TeX 引擎的日志可能含非 UTF-8 字节（尤其中文内容），
    因此按字节捕获再容错解码，避免 UnicodeDecodeError 掩盖真实错误。
    """
    kw.setdefault("text", False)
    proc = subprocess.run(cmd, capture_output=True, **kw)
    out = _safe_decode(proc.stdout)
    err = _safe_decode(proc.stderr)
    if proc.returncode != 0:
        sys.stderr.write("命令失败: %s\n" % " ".join(map(str, cmd)))
        sys.stderr.write(out[-3000:] + "\n" + err[-3000:] + "\n")
        raise SystemExit(1)
    return proc, out, err


def _safe_decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def ensure_reference_docx():
    if REFERENCE_DOCX.exists():
        return
    print("生成 IEEE Word 参考模板 ...")
    run([sys.executable, str(MAKE_REF_DOCX), str(REFERENCE_DOCX)])


CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def has_cjk(md: Path) -> bool:
    """检测源文件是否含CJK 字符（决定用 XeLaTeX 还是 pdfLaTeX）。"""
    return bool(CJK_RE.search(md.read_text(encoding="utf-8", errors="ignore")))


def collect_images(md: Path) -> list:
    """列出 Markdown 里引用的所有图片路径（去重，保持出现顺序）。"""
    text = md.read_text(encoding="utf-8", errors="ignore")
    paths = [m.group("path") for m in IMG_MD_RE.finditer(text)]
    paths += IMG_LATEX_RE.findall(text)
    seen, out = set(), []
    for p in paths:
        p = p.strip()
        if p and not p.startswith(("http://", "https://", "data:")) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def stage_images(md: Path, images_dir, outdir: Path, copy_images: bool) -> Path:
    """把图片统一放到输出目录旁，并返回解析后的图片根目录。

    pandoc 生成的 .tex 用相对路径引图，编译时按 .tex 所在目录解析。
    源md 常把图放在别处（或图名与md 不在一��目录），因此统一拷到
    <outdir>/<images_dir>/，必要时改写 md 里的路径。

    images_dir 为 None 时：按 md 所在目录查找；找不到就跳过（可能由用户
    后续自行放置），只报告缺失项。
    """
    refs = collect_images(md)
    if not refs:
        return md.parent

    root = md.parent if images_dir is None else (outdir / images_dir)

    if not copy_images:
        missing = [p for p in refs if not (md.parent / p).exists()]
        if missing:
            print("提示：以下图片在 md 同目录下未找到，编译可能失败：")
            for m in missing[:20]:
                print("   ", m)
        return md.parent

    root.mkdir(parents=True, exist_ok=True)
    missing = []
    for rel in refs:
        # 依次尝试常见位置：md 同目录、md 同目录下的常见图片子目录、输出目录。
        # 覆盖 figs/ figures/ images/ assets/ img/ 等命名习惯。
        sub = Path(rel).parent
        subs = [sub] if str(sub) not in (".", "") else []
        subs += [Path("images"), Path("figs"), Path("figures"),
                 Path("assets"), Path("img"), Path("media")]
        cands = [md.parent / rel] + [md.parent / s / rel for s in subs] + [outdir / rel]
        src = next((c for c in cands if c.exists()), None)
        if src is None:
            missing.append(rel)
            continue
        dst = root / Path(rel).name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)

    if missing:
        print("提示：以下图片未找到，已跳过（请手动放入 %s）：" % root)
        for m in missing[:20]:
            print("   ", m)

    # 改写 md 中的路径，使其指向暂存目录
    text = md.read_text(encoding="utf-8", errors="ignore")
    for rel in refs:
        if (root / Path(rel).name).exists():
            new = str((root / Path(rel).name).as_posix())
            text = text.replace("](%s)" % rel, "](%s)" % new)
            text = text.replace("{%s}" % rel, "{%s}" % new)
    staged = md.with_name(md.stem + ".staged.md")
    staged.write_text(text, encoding="utf-8")
    return staged


def _pandoc_common(md: Path, cjk: bool):
    args = ["pandoc", str(md), "--top-level-division=section"]
    if cjk:
        args += ["-V", "cjk=true"]
    return args


def _require_metadata(md: Path) -> None:
    """源文件缺少 YAML 元数据时给出可操作提示。

    IEEEtran 的 \\maketitle 需要 \\title，缺失时 LaTeX 只报
    "No \\title given."，看不出是源文件问题。这里提前拦截并说明
    补哪些字段，避免排查方向偏向 LaTeX/引擎。
    """
    head = md.read_text(encoding="utf-8", errors="ignore")[:4000]
    if not head.lstrip().startswith("---"):
        raise SystemExit(
            "源文件开头没有 YAML 元数据，IEEE 标题块无法生成。\n"
            "请在文件最前面补上：\n\n"
            "---\n"
            'title: "文档标题"\n'
            "author:\n"
            "  - |\n"
            "    作者姓名\n"
            "    *单位名称*\n"
            'abstract: |\n'
            "  摘要内容。\n"
            'keywords: "关键词一, 关键词二"\n'
            "---\n"
        )
    if "title:" not in head:
        raise SystemExit(
            'YAML 元数据里缺少 title 字段，IEEEtran 的 \\maketitle 会报错。\n'
            '请补上：title: "文档标题"'
        )


def build_tex(md: Path, outdir: Path, wide_threshold: int, resize: bool,
             name: str | None = None) -> Path:
    """生成 .tex。name 指定输出文件名（暂存输入时不沿用 .staged 后缀）。"""
    _require_metadata(md)
    tex = outdir / ((name or md.stem) + ".tex")
    run(_pandoc_common(md, has_cjk(md)) + [
        "-o", str(tex),
        "--standalone",
        "--template=%s" % TEMPLATE_TEX,
    ])
    # pandoc 的 longtable 改写成 IEEE 可用的table 浮动体
    cmd = [sys.executable, str(FIX_TABLES), str(tex),
           "--wide-threshold", str(wide_threshold)]
    if not resize:
        cmd.append("--no-resize")
    run(cmd)
    return tex


def _compile_native(engine: str, texdir: Path, stem: str) -> bool:
    """用系统 TeX Live 引擎编译，跑两遍让 \\ref / 公式编号稳定。"""
    for _ in range(2):
        proc = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error", stem + ".tex"],
            cwd=texdir, capture_output=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(_safe_decode(proc.stdout)[-3000:] + "\n")
            raise SystemExit("编译失败，请查看 %s" % (texdir / (stem + ".log")))
    for ext in (".aux", ".log", ".out"):
        f = texdir / (stem + ext)
        if f.exists():
            f.unlink()
    return True


def _compile_tectonic(texdir: Path, stem: str) -> bool:
    tectonic = find_tectonic()
    if tectonic is None:
        raise SystemExit(
            "未找到 LaTeX 引擎。请任选其一：\n"
            "  * 安装 TeX Live（提供 pdflatex / xelatex）\n"
            "  * 安装 Tectonic：brew install tectonic\n"
            "  * 或下载单文件版并用 TECTONIC 环境变量指定路径"
        )
    print("使用 Tectonic 编译（首次运行需联网下载宏包）...")
    proc = subprocess.run(
        [tectonic, "-X", "compile", stem + ".tex", "--outdir", "."],
        cwd=texdir, capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(_safe_decode(proc.stdout)[-3000:] + "\n")
        sys.stderr.write(_safe_decode(proc.stderr)[-3000:] + "\n")
        raise SystemExit("Tectonic 编译失败")
    return True


def pdf_page_count(pdf: Path) -> int | None:
    """读取 PDF 页数；无法确定时返回 None（绝不返回 0，避免误报）。

    按可靠性依次尝试：
      1. pymupdf（若已安装，最可靠）
      2. 解析页树 /Count——需先解压交叉引用流与对象流，
         因为 Tectonic 等引擎默认启用压缩，裸正则读不到
      3. 统计 /Type /Page 对象出现次数（未压缩时的兜底）
    """
    # 1) pymupdf
    try:
        import pymupdf
        with pymupdf.open(pdf) as d:
            return d.page_count
    except Exception:
        pass

    data = pdf.read_bytes()

    # 2) 解压所有 FlateDecode 流后查找页树
    blobs = [data]
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        try:
            blobs.append(zlib.decompress(data[start:end]))
        except Exception:
            continue

    for blob in blobs:
        counts = [int(x) for x in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", blob)]
        if counts:
            return max(counts)

    # 3) 统计页对象
    for blob in blobs:
        n = len(re.findall(rb"/Type\s*/Page[^s]", blob))
        if n:
            return n
    return None


def build_pdf(md: Path, outdir: Path, tex: Path, target_pages: int | None,
              stem: str | None = None) -> Path:
    """编译 PDF。含中文用 XeLaTeX，其余用 pdfLaTeX；都没有则退回 Tectonic。"""
    stem = stem or md.stem
    pdf = outdir / (stem + ".pdf")
    cjk = has_cjk(md)
    texdir, stem_tex = tex.parent, tex.stem

    engine = "xelatex" if cjk else "pdflatex"
    if shutil.which(engine):
        _compile_native(engine, texdir, stem_tex)
    else:
        _compile_tectonic(texdir, stem_tex)

    built = texdir / (stem_tex + ".pdf")
    if built.resolve() != pdf.resolve():
        shutil.move(str(built), str(pdf))

    if target_pages:
        n = pdf_page_count(pdf)
        if n is None:
            print("\n[页数提醒] 无法自动统计页数（PDF 已压缩）。"
                  "请用预览打开 PDF 手动核对是否超过 %d 页。" % target_pages)
        elif n > target_pages:
            print("\n[页数提醒] 实际 %d 页，目标 %d 页。" % (n, target_pages))
            print("  依次尝试：① 调大 --wide-threshold 让更多表走通栏或单栏；")
            print("  ② 缩小 md 中 \\includegraphics[width=..\\linewidth] 的宽度值；")
            print("  ③ 把最简短的行间公式并入正文行内；")
            print("  ④ 合并结构重复的表格；⑤ 精简冗余文字。")
        elif n < target_pages:
            print("\n[页数提醒] 实际 %d 页，目标 %d 页，尚有余量，可适当放大图表。"
                  % (n, target_pages))
    return pdf


def build_docx(md: Path, outdir: Path, stem: str | None = None) -> Path:
    ensure_reference_docx()
    docx = outdir / ((stem or md.stem) + ".docx")
    run(["pandoc", str(md), "-o", str(docx),
         "--reference-doc=%s" % REFERENCE_DOCX])
    return docx


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Markdown 转 IEEE 格式论文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("input", help="输入的 Markdown 文件")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="输出目录（默认与输入同目录）")
    ap.add_argument("--tex", action="store_true", help="只输出 LaTeX")
    ap.add_argument("--pdf", action="store_true", help="只输出 PDF")
    ap.add_argument("--docx", action="store_true", help="只输出 Word")
    ap.add_argument("--images-dir", default=None,
                    help="图片子目录名（默认与 md 同目录，不额外拷贝）")
    ap.add_argument("--copy-images", action="store_true",
                    help="把引用的图片拷贝到输出目录的 images/ 下")
    ap.add_argument("--wide-threshold", type=int, default=4,
                    help="表格列数超过此值才排成通栏 table*（默认 4）")
    ap.add_argument("--no-resize", action="store_true",
                    help="不自动缩放超宽表格")
    ap.add_argument("--target-pages", type=int, default=None,
                    help="期望页数；编译后报告偏差并给出调节建议")
    args = ap.parse_args()

    md = Path(args.input).resolve()
    if not md.exists():
        print("找不到输入文件:", md)
        return 1

    outdir = Path(args.output_dir).resolve() if args.output_dir else md.parent
    outdir.mkdir(parents=True, exist_ok=True)

    src = md
    if args.copy_images:
        staged = stage_images(md, args.images_dir or "images", outdir, True)
        if staged != md:
            src = staged

    # 产物一律以原始文件名命名，不受暂存文件名的 .staged 影响
    stem = md.stem

    only = args.tex or args.pdf or args.docx
    made = []
    tex_path = None
    if args.tex or args.pdf or not only:
        tex_path = build_tex(src, outdir, args.wide_threshold,
                             not args.no_resize, name=stem)
        if args.tex or not only:
            made.append(tex_path)
    if args.pdf or not only:
        made.append(build_pdf(src, outdir, tex_path, args.target_pages, stem=stem))
    if args.docx or not only:
        made.append(build_docx(src, outdir, stem=stem))

    for p in made:
        print("✓", p)
    # 清理暂存中间文件，避免污染输出目录
    if src != md and src.exists():
        src.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
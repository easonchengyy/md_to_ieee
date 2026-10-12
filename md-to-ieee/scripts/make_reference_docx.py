#!/usr/bin/env python3
"""生成 IEEE 风格的 pandoc reference.docx。

用途
----
pandoc 把 Markdown 转成 Word 时，用 `--reference-doc=xxx.docx` 指定
样式来源文档。本脚本在 pandoc 默认 reference.docx 的基础上，
把各段落/字符样式改写成 IEEE Transactions 论文的规格：

  * 页面：US Letter，左右边距 0.625 in，上下 0.75 in
  * 正文：Times New Roman 10 pt，两端对齐
  * 章节标题：小体大写（H1 居中，H2/H3 左对齐斜体缩进）
  * 摘要：8 pt 加粗，首行缩进
  * 图表标题：8 pt，表题居上、图题居下
  * 双栏正文

用法
----
    python3 make_reference_docx.py [输出路径]

默认输出 ieee-reference.docx（与脚本同目录）。
"""
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SERIF = "Times New Roman"
SANS = "Arial"

# 页面尺寸（twips：1 inch = 1440 twips）
PAGE = dict(w=12240, h=15840, top=1080, right=900, bottom=1080, left=900)


def _sz(half_points: int) -> str:
    return f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>'


def _fonts(ascii_font=SERIF, ea=SERIF, cs=SERIF) -> str:
    return (
        f'<w:rFonts w:ascii="{ascii_font}" w:hAnsi="{ascii_font}" '
        f'w:eastAsia="{ea}" w:cs="{cs}"/>'
    )


def _rpr(
    half_points: int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    smallcaps: bool | None = None,
    font: str = SERIF,
) -> str:
    parts = [_fonts(font)]
    if bold is not None:
        parts.append(f'<w:b w:val="{"1" if bold else "0"}"/>')
    if italic is not None:
        parts.append(f'<w:i w:val="{"1" if italic else "0"}"/>')
    if smallcaps:
        parts.append('<w:smallCaps w:val="1"/>')
    if half_points:
        parts.append(_sz(half_points))
    return "".join(parts)


def build_styles_xml() -> str:
    """返回改写后的 styles.xml 全文。"""
    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True,
        check=True,
    ).stdout
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "r.docx"
        p.write_bytes(default)
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/styles.xml").decode("utf-8")

    def set_style(style_id: str, name_el: str, ppr: str = "", rpr: str = "") -> None:
        """替换指定 styleId 的属性块；已存在则注意保留 <w:name>。"""
        nonlocal xml
        pat = re.compile(
            r'(<w:style [^>]*w:styleId="%s"[^>]*>)(.*?)(</w:style>)' % re.escape(style_id),
            re.S,
        )
        m = pat.search(xml)
        if not m:
            return
        body = m.group(2)
        body = re.sub(r"<w:pPr>.*?</w:pPr>", "", body, flags=re.S)
        body = re.sub(r"<w:rPr>.*?</w:rPr>", "", body, flags=re.S)
        new = m.group(1) + body + ppr + rpr + m.group(3)
        xml = xml[: m.start()] + new + xml[m.end():]

    # --- 整体默认字体 ---
    xml = re.sub(
        r"<w:rPrDefault>.*?</w:rPrDefault>",
        "<w:rPrDefault><w:rPr>%s</w:rPr></w:rPrDefault>" % _rpr(font=SERIF),
        xml,
        flags=re.S,
    )
    xml = re.sub(
        r"<w:pPrDefault>.*?</w:pPrDefault>",
        "<w:pPrDefault><w:pPr><w:spacing w:after=\"0\"/></w:pPr></w:pPrDefault>",
        xml,
        flags=re.S,
    )

    # --- 正文：10pt，两端对齐，首行缩进 0.2in ---
    set_style(
        "Normal",
        "Normal",
        ppr='<w:pPr><w:jc w:val="both"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>',
        rpr=_rpr(20),
    )
    set_style(
        "BodyText",
        "Body Text",
        ppr='<w:pPr><w:ind w:firstLine="200"/><w:jc w:val="both"/></w:pPr>',
        rpr=_rpr(20),
    )

    # --- 标题：H1 居中无编号大写；H2/H3 斜体 ---
    set_style(
        "Heading1",
        "Heading 1",
        ppr='<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/></w:pPr>',
        rpr=_rpr(20, bold=False, italic=False, smallcaps=True),
    )
    set_style(
        "Heading2",
        "Heading 2",
        ppr='<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr>',
        rpr=_rpr(20, italic=True),
    )
    set_style(
        "Heading3",
        "Heading 3",
        ppr='<w:pPr><w:keepNext/><w:spacing w:before="100" w:after="40"/><w:outlineLvl w:val="2"/></w:pPr>',
        rpr=_rpr(20, italic=True),
    )

    # --- 标题块 ---
    set_style(
        "Title",
        "Title",
        ppr='<w:pPr><w:spacing w:before="0" w:after="240"/><w:jc w:val="center"/></w:pPr>',
        rpr=_rpr(48, bold=False),
    )
    set_style(
        "Author",
        "Author",
        ppr='<w:pPr><w:spacing w:after="320"/><w:jc w:val="center"/></w:pPr>',
        rpr=_rpr(22),
    )
    set_style(
        "Date",
        "Date",
        ppr='<w:pPr><w:jc w:val="center"/></w:pPr>',
        rpr=_rpr(20),
    )
    set_style(
        "AbstractTitle",
        "Abstract Title",
        ppr='<w:pPr><w:jc w:val="center"/></w:pPr>',
        rpr=_rpr(20, bold=True),
    )
    # 摘要：8pt 加粗
    set_style(
        "Abstract",
        "Abstract",
        ppr='<w:pPr><w:ind w:firstLine="202"/><w:jc w:val="both"/></w:pPr>',
        rpr=_rpr(18, bold=True),
    )

    # --- 图表标题：8pt，表题上、图题下 ---
    set_style(
        "TableCaption",
        "Table Caption",
        ppr='<w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="60"/></w:pPr>',
        rpr=_rpr(16, smallcaps=True),
    )
    set_style(
        "ImageCaption",
        "Image Caption",
        ppr='<w:pPr><w:jc w:val="both"/><w:spacing w:before="60" w:after="120"/></w:pPr>',
        rpr=_rpr(16),
    )
    set_style("Caption", "Caption", ppr='<w:pPr><w:jc w:val="center"/></w:pPr>', rpr=_rpr(16))

    # --- 参考文献：8pt ---
    set_style(
        "Bibliography",
        "Bibliography",
        ppr='<w:pPr><w:ind w:left="200" w:hanging="200"/><w:jc w:val="both"/></w:pPr>',
        rpr=_rpr(16),
    )

    # --- 代码块 ---
    set_style(
        "SourceCode",
        "Source Code",
        ppr='<w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="left"/></w:pPr>',
        rpr=_rpr(16, font="Courier New"),
    )

    return xml


def build_sectpr() -> str:
    return (
        '<w:sectPr>'
        f'<w:pgSz w:w="{PAGE["w"]}" w:h="{PAGE["h"]}"/>'
        f'<w:pgMar w:top="{PAGE["top"]}" w:right="{PAGE["right"]}" '
        f'w:bottom="{PAGE["bottom"]}" w:left="{PAGE["left"]}" '
        'w:header="432" w:footer="432" w:gutter="0"/>'
        '<w:cols w:num="2" w:space="360" w:equalWidth="1"/>'
        "</w:sectPr>"
    )


def build_document_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"{build_sectpr()}"
        "</w:body></w:document>"
    )


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("ieee-reference.docx")

    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True,
        check=True,
    ).stdout
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "r.docx"
        src.write_bytes(default)
        dst = Path(td) / "out.docx"
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = build_styles_xml().encode("utf-8")
                elif item.filename == "word/document.xml":
                    data = build_document_xml().encode("utf-8")
                zout.writestr(item, data)
        shutil.move(str(dst), out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

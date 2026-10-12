---
name: md-to-ieee
description: Converts Markdown documents into IEEE conference/journal LaTeX and PDF (IEEEtran two-column format), including figures, three-line booktabs tables, numbered equations, abstract/index terms, and references. This skill should be used when the user asks to convert a .md report, paper, thesis chapter, or technical document into IEEE format, asks for an IEEE-styled .tex or .pdf from Markdown, or wants a Markdown paper laid out in IEEE Transactions style.
agent_created: true
---

# Markdown to IEEE Format

Convert a Markdown document into a properly typeset IEEE conference paper
(LaTeX + PDF), with correct IEEE typography: two-column layout, Times
font, abstract/index-terms block, numbered equations, booktabs tables,
and IEEE figure/table captions.

This skill contains no content of any particular document — it is fully
reusable for any Markdown source.

## Quick Start

```bash
python3<skill>/scripts/md2ieee.py input.md --pdf --tex
```

Replace `<skill>` with this skill's directory. Always report the produced
`.pdf` and `.tex` paths to the user.

Common options:

| Option | Effect |
|--------|--------|
| `--pdf` / `--tex` / `--docx` | Select outputs. Default: all three. |
| `-o out/` | Output directory (default: alongside the input). |
| `--copy-images` | Copy referenced images into `out/images/` and rewrite paths. Use when images live elsewhere or the `.md` sits apart from its figures. |
| `--images-dir NAME` | Subdirectory name for `--copy-images` (default `images`). |
| `--target-pages N` | Report page count vs. target and suggest adjustments. |
| `--wide-threshold N` | Tables with more than N columns become full-width `table*` (default 4). |

## Prerequisites

`pandoc` is required. For LaTeX compilation the script uses, in order:

1. `pdflatex` / `xelatex` (TeX Live) — `xelatex` is selected automatically
   when the source contains CJK characters.
2. `tectonic` as fallback — a single-file engine that downloads its own
   macro packages, so it works without TeX Live.

Search order for tectonic: `$TECTONIC` env var → `PATH` → common install
paths. If neither engine is available the script prints install
instructions; installing Tectonic (`brew install tectonic`) is usually the
lightest option.

## How the Pipeline Works

```
Markdown --(pandoc + assets/ieee-template.tex)--> .tex
.tex     --(scripts/fix_tables.py)--> IEEE-clean .tex
.tex     --(pdflatex/xelatex/tectonic)--> .pdf
```

The `.tex` intermediate is mandatory, not an artifact to skip: pandoc
emits Markdown tables as `longtable`, which is incompatible with
IEEEtran's two-column body and fails to compile. `fix_tables.py` rewrites
each one into a `table`/`table*` float with booktabs rules.

When editing the pipeline, preserve these constraints — each was a real
failure encountered:

- **`\pandocbounded` must stay defined in the template.** pandoc 3.x wraps
  explicitly-sized images in it. Without a definition the build dies with
  "Undefined control sequence".
- **Never redefine `\noalign`.** booktabs internals depend on it;
  overriding it triggers a "Missing `\cr` inserted" error chain.
- **The `\def\]{` block needs its closing brace.** A missing brace makes
  TeX report "File ended while scanning definition of `\]`", which is easy
  to misread as an engine problem.
- **Do not load `parskip`.** It adds ~3pt between paragraphs, which both
  breaks IEEE style and can silently add a full page.

## Controlling Page Count

IEEE submissions and reports often have a page limit. Page count is driven
mostly by float congestion, not text volume. When the count must come
down, work through these in order — each is cheaper than rewriting prose:

1. **Table column threshold.** A 5–6 column table built as `table*`
   consumes both columns of a page. Lower `--wide-threshold` so it renders
   as a single-column `table`. This alone is frequently the whole fix.
2. **Figure widths.** Scale down the `width=` values in the Markdown
   source. Tall schematics and layout plots benefit most.
3. **Short display equations.** Inline trivial equations instead of giving
   them a numbered display block.
4. **Merge structurally identical tables** by adding a differentiating
   column.
5. **Tighten prose** only as a last resort.

Beware threshold effects: scaling all figures up by 20% can flip a
6-page document back to 7, while 10% is safe. Iterate and re-check rather
than assuming linearity.

To verify a build, render pages to images and inspect them — float
problems (a column left empty while tables pile up at the end) are
invisible in the text layer but obvious visually:

```bash
python3 -c "import pymupdf; d=pymupdf.open('out.pdf'); [p.get_pixmap(dpi=105).save(f'/tmp/pg{i+1}.png') for i,p in enumerate(d)]"
```

Also check the build log for `Overfull \hbox`, which signals content
spilling outside the column.

## Source Authoring Conventions

See `references/markdown-syntax.md` for the Markdown constructs this
pipeline understands — YAML metadata, figure and table captions, equation
numbering, citations, and image sizing. Read it before hand-authoring or
repairing a source document, since correct input avoids most layout
problems at the source.

For the LaTeX-side rationale (fonts per engine, float parameters,
caption styling), see `references/ieee-latex-notes.md`.

## Scope

This skill converts and typesets documents. It does not rewrite content,
translate between languages, or invent missing figures. When a source
references an image that is absent, the script reports it; obtain the
image rather than substituting a placeholder.

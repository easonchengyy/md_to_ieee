# IEEEtran LaTeX Notes

Rationale behind the template and post-processor. Consult when modifying
`assets/ieee-template.tex` or `scripts/fix_tables.py`, or when diagnosing a
build failure.

## Document Class

`\documentclass[conference]{IEEEtran}` produces the standard two-column
meeting-paper layout. Useful alternatives:

| Option | Layout |
|--------|--------|
| `conference` | Two-column, 10pt (default) |
| `journal` | Two-column journal format |
| `techreport` | One-column |

For very wide tables or figures, `journal` often reads better because its
measure is wider.

## Never Redefine `\maketitle`

IEEEtran supplies `\title`, `\author`, and `\maketitle` natively. Pandoc
emits a `\maketitle` that IEEEtran adopts directly, yielding the
top-spanning title, centered author block, and two-column body. Redefining
any of these three breaks the layout.

Abstract and index terms come from IEEEtran's `abstract` and
`IEEEkeywords` environments, which must follow `\maketitle` immediately —
the title block is single-column at that point.

## Fonts

IEEE specifies a Times-like typeface. The available approach differs by
engine, and getting this wrong silently changes metrics:

**pdfLaTeX** — `mathptmx` (psnfss) plus `helvet` for sans. Text and math
match.

**XeLaTeX / LuaLaTeX / Tectonic** — `mathptmx` does *not* work. Use
`fontspec` with TeX Gyre Termes (the metric-compatible open-source Times
clone shipped with TeX Live and Tectonic) and its companion math font
`texgyretermes-math.otf`. Without an explicit math font, XeTeX falls back
to Latin Modern math, which changes glyph widths and therefore line
breaks.

The template guards the font names with `\IfFontExistsTF` and falls back
to the default font family if unavailable, so the build degrades rather
than fails.

## Float Placement Parameters

IEEEtran's default float limits are conservative. With many figures and
tables, LaTeX defers floats and leaves large gaps, sometimes adding a
full page. The template relaxes them:

```latex
\setcounter{totalnumber}{12}
\setcounter{dbltopnumber}{6}
\renewcommand{\topfraction}{0.95}
\renewcommand{\dbltopfraction}{0.95}
\renewcommand{\bottomfraction}{0.90}
\renewcommand{\floatpagefraction}{0.80}
\renewcommand{\textfraction}{0.03}
\usepackage{stfloats}
```

`stfloats` is what makes `[b]` a valid position for `figure*`/`table*`;
without it, full-width floats may only sit at a page top, which is the
usual cause of a document overflowing by a page.

Tighten `\textfloatsep`, `\floatsep`, and `\intextsep` to reclaim space.
The values here (6pt with stretch) are already aggressive; IEEE's
defaults are looser.

## Table版式 Decision

`fix_tables.py` converts every pandoc `longtable` into a float:

- **Column count ≤ `--wide-threshold` (default 4)** → `table`, single
  column, position `[!t]`.
- **Above the threshold** → `table*`, full width, position `[!tb]`.

The threshold is the single most effective page-count lever. A 5-column
table as `table*` consumes both columns of a page; the same table as a
single-column float usually costs a third of that. Raise the threshold
when tables are too wide to be readable in one column.

Widths are scaled with a conditional guard:

```latex
\resizebox{\ifdim\width>\linewidth\linewidth\else\width\fi}{!}{...}
```

This shrinks only when the natural width exceeds the target. A plain
`\resizebox{\linewidth}{!}` would also *enlarge* narrow tables,
artificially increasing their height and consuming space.

## Figure Post-Processing

pandoc has used two wrappers over time, and both need normalization:

1. **Older pandoc** wraps figure contents in `\hypertarget{...}{...}`.
   The group swallows `\centering` and `\caption`, so images stop being
   centered and numbering breaks. The wrapper is stripped.
2. **pandoc 3.x** wraps explicitly-sized images in `\pandocbounded{...}`,
   a command defined only in pandoc's own template. The skill's template
   provides it as "shrink to column width only if wider". The post-
   processor hoists `\caption` outside that box so the figure number is
   not scaled along with the image.

## Long Display Equations

`fix_tables.py` estimates the rendered width of each display equation by
walking the source and counting LaTeX commands as roughly one character
width. Equations beyond the threshold are wrapped in `\resizebox` with
`\eqno` extracted so numbering stays outside the scaled box.

This is a heuristic. It prevents overflow in the common case; it is not a
substitute for visual inspection of the rendered PDF.

## Diagnostic Commands

Count pages (requires `pymupdf`; the script also has a dependency-free
fallback that decompresses object streams):

```bash
python3 -c "import pymupdf; print(pymupdf.open('out.pdf').page_count)"
```

Render pages for visual inspection:

```bash
python3 -c "import pymupdf; d=pymupdf.open('out.pdf'); [p.get_pixmap(dpi=105).save(f'/tmp/pg{i+1}.png') for i,p in enumerate(d)]"
```

Check for content spilling outside columns:

```bash
grep "Overfull" out.log
```

Keep logs by compiling with `--keep-logs` (tectonic) or by removing the
log cleanup in `_compile_native` while debugging.

## Common Build Failures

| Symptom | Cause |
|---------|-------|
| `Undefined control sequence` on `\pandocbounded` | Template missing the `\providecommand` definition |
| `File ended while scanning definition of \]` | Missing closing brace in the `\def\]{` block |
| `Missing \cr inserted` | `\noalign` was redefined, breaking booktabs |
| Table wider than the page | Lower `--wide-threshold`, or the table has too many columns |
| Empty column with floats piled at document end | Float congestion; verify `stfloats` loaded and threshold is tuned |
| CJK renders as boxes | Compile with XeLaTeX and install a CJK font (e.g. Noto Serif CJK SC) |
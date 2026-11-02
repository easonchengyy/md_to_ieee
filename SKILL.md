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

## Default Workflow — Fast First PDF, Then Iterate

Unless the user explicitly asks for a finished, polished document in one
shot, run the pipeline in **two rounds**. Do not compress them into one.

**Round 1 — ship a PDF as fast as possible.** Get from Markdown to a
compiling `.pdf` and hand it to the user immediately. Do not spend the
first round on page-count tuning, float placement, figure widths,
overfull boxes, or page-by-page visual review. The user looking at a
rough PDF will point at the one or two things they actually care about;
guessing at those costs far more than one extra compile.

Minimum bar for round 1:

- pandoc and a LaTeX engine are present; `.tex` generated, `.pdf` produced.
- Every referenced image resolves — no `File not found` in the build log.
- The PDF is presented to the user with its path, page count, and image
  count, plus any defect already known.

Deliberately **defer to round 2**: `--target-pages` tuning,
`--wide-threshold` changes, figure `width=` scaling, merging tables,
tightening prose, and the page-image inspection loop described under
*Controlling Page Count*.

**Round 2 — fix only what the user flagged.** Take their concrete
complaints (a float stranded at the end of the document, a schematic too
small to read, a table that failed to render, a duplicated caption, an
awkward page break) and change the minimum needed to resolve each. Then
recompile and state precisely what changed. Repeat as needed.

Two rules keep this honest:

- If a layout defect is already visible during round 1 **and** one cheap
  flag fixes it, fix it. Otherwise ship the PDF and list the known issue
  in the delivery message instead of silently iterating.
- Never block delivery on polish. A compiling PDF with every figure
  embedded is already useful output.

Skip the fast path only when the user asks for a final version, asks you
to perfect it before showing anything, or when there is no human in the
loop (batch job, scheduled automation) — then do the full verification
pass before delivering.

## Quick Start

```bash
python3<skill>/scripts/md2ieee.py input.md --pdf --tex
```

Replace `<skill>` with this skill's directory. Always report the produced
`.pdf` and `.tex` paths to the user.

The first invocation should be exactly this bare command — no tuning
flags, no page-count target. Deliver the resulting PDF, then iterate per
*Default Workflow* above. Add options only in round 2 or when the source
requires them (`--copy-images` when figures live outside the source
directory, `--wide-threshold` for wide tables).

Common options:

| Option | Effect |
|--------|--------|
| `--pdf` / `--tex` / `--docx` | Select outputs. Default: all three. |
| `-o out/` | Output directory (default: alongside the input). |
| `--copy-images` | Copy referenced images into `out/images/` and rewrite paths. Use when images live elsewhere or the `.md` sits apart from its figures. |
| `--images-dir NAME` | Subdirectory name for `--copy-images` (default `images`). |
| `--target-pages N` | Report page count vs. target and suggest adjustments. |
| `--wide-threshold N` | Tables with more than N columns become full-width `table*` (default 4). |
| `--docx-fig-width 6.9in` | Figure width in Word (default 6.9 in single column, 3.4 in two). |
| `--docx-two-columns` | Lay the Word file out in two columns (default single). |
| `--docx-wide-figs a.png,b.png` | Force these figures to span both columns in Word. |

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

Markdown --(scripts/md2docx.py: 预处理)--> .docx-src.md
.docx-src.md --(pandoc + scripts/ieee-reference.docx)--> .docx
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

## Word Output

`--docx` is not a bare `pandoc -o out.docx`. The direct conversion
produces a file that looks broken in Word; every item below was an
observed failure, and `scripts/md2docx.py` fixes it before pandoc runs:

- **Images arrive at native pixel width.** Without an explicit width
  pandoc sizes each image from its pixel dimensions — usually a full text
  block or more — so schematics overflow the margins. The preprocessor
  injects `{width=6.9in}`.
- **Figure captions split in two.** `![alt](img)` followed by a separate
  `**Fig. n　caption**` paragraph yields an image captioned with the short
  alt text plus an orphan bold paragraph. The two are merged into a single
  captioned figure.
- **`\tag{n}` disappears silently.** pandoc's OMML conversion drops
  equation tags, so all numbering vanishes with no warning. Rewritten to
  `\qquad(n)`, which survives as trailing text inside the equation.
- **Two images sharing one caption lose that caption.** A paragraph with
  two images and a line break is not an implicit figure, so pandoc drops
  the caption entirely. Such groups are stacked with `\` and the caption
  is emitted as an explicit `custom-style="Image Caption"` block.
- **The title is just another H1.** Title, author, `# Abstract`, and
  `**Index Terms**` are lifted out of the body into Word's Title / Author
  / Abstract styles.
- **`**TABLE n　caption**` is a loose bold line.** Converted to a pandoc
  table caption so it lands in the Table Caption style above the table.
  Numbers are then renumbered **sequentially in document order**, and a
  table with no caption at all gets one derived from the nearest heading —
  so a body that mixes captioned and caption-less tables still ends up
  with I, II, III, IV in order.
- **Tables come out as narrow equal columns.** pandoc takes column widths
  from the separator row's dash counts, but only when the table is treated
  as wider than the text column — raising `--columns` silently switches
  every table to equal widths, which shreds long cells into six lines.
  `md2docx.py` therefore (a) rewrites each separator so dash counts are
  proportional to the longest cell in that column, (b) never passes
  `--columns`, and (c) rescales the finished `gridCol` values to the full
  text block (pandoc's default is only ~5.5 in).
- **Table cells inherit justified text.** Cell paragraphs use pandoc's
  `Compact` style, which the reference doc leaves undefined, so they fall
  back to justified `Normal` and short strings get splayed across the
  cell. The reference doc now defines `Compact` as left-aligned.
- **A table can break between the caption and the first row.** `Table
  Caption` has `keepNext`, and every row gets `cantSplit`.

Single column is the default: it is the fastest way to a clean Word file,
and figures keep their full size. Two columns are available with
`--two-columns` and now mostly work without hand-tuning:

- **`fig_width` drops to 3.4in** (half a column) automatically unless you
  pass `--fig-width`.
- **Wide items get their own single-column section.** Word has no floats,
  so the only way to let a schematic span both columns is a pair of
  continuous section breaks — one carrying `cols=2` before the item, one
  carrying `cols=1` after it. `sectPr` describes the section that *ends*
  at it, which is what makes the sandwich work.
- **Which items are wide.** Figures: give `--wide-figs a.png,b.png`, or
  let it guess for images whose aspect ratio is ≥ 1.95:1 (a wide, flat
  schematic shrunk to half a column is unreadable). Tables: any table with
  more than three columns goes wide automatically.
- **A wide table's caption must cross the break with the table.** Emitting
  the break at the table start leaves the `TABLE n` line in the two-column
  section and the table on the next page, alone. The caption index is
  mapped to its table up front (`plan_tables` + `cap_to_table`) so the
  break is emitted above the caption.
- **Tables inside a section are sized to that section** — one column's
  width in a two-column stretch, the text block in a wide stretch. The
  section a table lives in is resolved by looking at the *next* `sectPr`,
  for the same "describes what came before" reason.
- **Long display equations are set at 8.5 pt.** A formula laid out for a
  7.25 in measure will not fit a 3.5 in column, and Word will not reflow
  math. Blocks whose content exceeds ~55 characters get `w:rPr/w:sz`
  injected into every `m:r`; short formulas keep the body size.
  LibreOffice ignores this attribute on import, so its PDF export still
  shows the long formulas at full width — judge this one in Word, not in
  the LibreOffice preview.

Accept the consequence: every full-width band interrupts the column flow,
so pages carrying one end with white space. That is what a float does in
LaTeX and what an inline block cannot do in Word; `keepNext` on rows and
captions keeps tables from being torn apart, but nothing fills the holes.
If the user wants a tight Word file instead, drop back to single column.

### Verifying a Word build

LaTeX verification does not transfer here. Cheapest first:

1. **Structural check** — styles, image extents, tables, section columns:

   ```bash
   python3 - <<'EOF'
   import zipfile, re
   d = zipfile.ZipFile("out.docx").read("word/document.xml").decode()
   print("imgs", len(re.findall(r"<wp:extent", d)), "tables", d.count("<w:tbl>"))
   print("cols", re.findall(r"<w:cols[^>]*/>", d))
   print("styles", sorted(set(re.findall(r'<w:pStyle w:val="([^"]+)"', d))))
   EOF
   ```

   Expect one image extent per source figure, `num="1"` columns, and
   `Title` / `Author` / `Abstract` / `ImageCaption` / `TableCaption`
   present. A missing `ImageCaption` means captions were not merged.

2. **Render to PDF, then look at it.** LibreOffice is the only reliable
   converter available here (Word via AppleScript is blocked in sandboxed
   sessions; Quick Look only shows page 1):

   ```bash
   /Volumes/LibreOffice/LibreOffice.app/Contents/MacOS/soffice \
       --headless --norestore --convert-to pdf --outdir /tmp out.docx
   python3 -c "import pymupdf; d=pymupdf.open('/tmp/out.pdf'); \
     [p.get_pixmap(dpi=100).save(f'/tmp/w{i+1}.png') for i,p in enumerate(d)]"
   ```

   What to look for, in order of how often it breaks: a table whose cells
   wrap into four or more lines (column widths), a table without a
   `TABLE n` caption, an image spilling past the margin, a caption stranded
   at a page top while its figure sits on the previous page.

3. **Otherwise hand it over and say what to check.** Word layout cannot be
   fully predicted from XML, and AppleScript control of Word is blocked in
   sandboxed sessions, so a visual pass is often the user's to do.

## Controlling Page Count

**This is round-2 work.** Do not open with it — deliver a compiling PDF
first, then apply these only when the user asks for fewer pages or the
document overflows a stated limit.

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
invisible in the text layer but obvious visually. This is a round-2
step: run it when you are specifically hunting a layout problem, not
before the first delivery.

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
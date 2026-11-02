# Markdown Syntax for the IEEE Pipeline

How to author Markdown so that `scripts/md2ieee.py` renders it as a proper
IEEE paper. Follow these conventions and the output needs almost no
post-editing.

## 1. YAML Metadata (required for title block)

IEEE papers need a title, author, abstract, and index terms. pandoc reads
them from YAML front matter:

```yaml
---
title: "A Compact 2.4 GHz CMOS LC-VCO Testchip: Design and Post-Layout Verification"
author:
  - |
    Test Author
    *Affiliation Placeholder*
abstract: |
  This paper describes the design and verification of a fully integrated
  2.4 GHz LC oscillator fabricated in a 28 nm CMOS process.
keywords: "LC oscillator, phase noise, adaptive bias, post-layout simulation"
---
```

Notes:

- `abstract` and `keywords` are optional; omitting them simply drops the
  block.
- An author entry may span multiple lines; use `|` (literal block) so
  markdown does not reflow it. The template joins multiple authors with
  `\and`, producing the standard IEEE author block.
- Keep the abstract as one paragraph. Blank lines inside it become
  paragraph breaks that look wrong under the "Abstract—" heading.

## 2. Sections

Use level-1 ATX headings (`#`). The script passes
`--top-level-division=section`, so `#` maps to `\section` and IEEEtran
renders it in small caps.

```markdown
# I. INTRODUCTION
```

Numbering sections with Roman numerals (as above) matches IEEE
conventions. `##` maps to `\subsection` for subsections.

## 3. Figures

Native Markdown image with alt text as the caption, plus a width:

```markdown
![Phase noise versus offset frequency.](pn.png){width=52%}
```

Accepted widths:

| Syntax | Meaning |
|--------|---------|
| `{width=100%}` or omitted | Fill the column width (default) |
| `{width=52%}` | 52% of column width |
| `{width=0.52\linewidth}` | Same, LaTeX form |

Guidance:

- Keep circuit schematics and layout plots at 45–70% so labels stay
  legible without dominating the page.
- Wide plots (phase noise, AC response) suit 80–100%.
- The alt text becomes the IEEE figure caption, so write it as a caption,
  not as alt-text prose.
- Figure captions render as "Fig. 1. Caption." in bold below the image.

### Alternative: raw LaTeX figure

For cross-references or subfigures, write the float directly. The
post-processor still normalizes float placement:

```markdown
\begin{figure}[!tb]
\centering
\includegraphics[width=0.6\linewidth]{figures/circuit.png}
\caption{Cross-coupled LC oscillator core.}
\label{fig:core}
\end{figure}
```

## 4. Tables

Place the caption **on the line immediately before** the table, as a
`: caption` line. pandoc only associates it correctly in that position.

```markdown
: Post-layout performance versus specification.

| Parameter | Specification | Post-layout | Result |
|-----------|---------------|-------------|--------|
| Center frequency | 2.4 GHz | 2.36 GHz | Pass |
| Phase noise @ 1 MHz | <= -110 dBc/Hz | -112 dBc/Hz | Pass |
```

The pipeline renders these as booktabs three-line tables (`\toprule` /
`\midrule` / `\bottomrule`) with the caption above in small caps, per
IEEE style. Widths adapt automatically and are never upscaled.

Inline code such as `nmos_rvt` in a cell is rendered as `\texttt` and set
to wrap, so long device names do not overflow.

## 5. Equations

### Numbered display equation

```markdown
$$R_{out} = (g_{m2}r_{o2}r_{o1}) \parallel (g_{m3}r_{o3}r_{o4})$$
```

Renders with a right-aligned sequential number, IEEE style. The template
redefines `\[` / `\]` to increment the equation counter and emit `\eqno`,
which avoids amsmath's `\tag` restriction.

### Unnumbered display equation

For equations that should not be numbered (intermediate steps), use:

```markdown
$$A_v \approx -g_m R_{out}$$ {#eq:av}
```

A bracketed label keeps the equation unnumbered while allowing
cross-referencing. Keep numbered equations to the few results a reader
will actually cite — every numbered display block consumes vertical
space, and in a page-limited paper this is a meaningful cost.

### Inline math

Use single dollars: `$g_m r_o$`. Inline math costs no vertical space;
prefer it for short expressions.

## 6. Citations and References

pandoc's citation syntax requires a bibliography source. Two workable
paths:

**Manual (simplest, fully predictable).** Write IEEE-style references
literally as a final section:

```markdown
# REFERENCES

[1] R. A. Martin and A. Paidimarri, "A wide-bandwidth LC oscillator,"
*IEEE J. Solid-State Circuits*, vol. 34, no. 4, pp. 456-464, 1999.
```

Reference the numbers inline as `[1]` or `Fig. 1` style text.

**Citation metadata (auto-numbered).** Add a `references.bib` and a YAML
block:

```yaml
---
bibliography: references.bib
link-citations: true
---
```

Then cite with `[@martin1999]` in text. pandoc renders the bracketed
number automatically.

Note that a hand-written `[#ref1]`-style marker is pandoc *link* syntax,
not a citation — it renders literally as `#ref1`. Use one of the two
approaches above instead.

## 7. Lists and Blocks

- Ordered/unordered lists render normally.
- Block quotes and fenced code blocks render as such. Avoid very wide code
  blocks in a two-column paper — they overflow the column.
- Horizontal rules produce `\begin{center}\rule...\end{center}`; use them
  sparingly.

## 8. Language

Set `lang` in YAML to enable correct hyphenation:

```yaml
lang: en-US
```

This materially improves justified text in a two-column layout, where
bad hyphenation produces rivers of whitespace.

For a Chinese source document, the script detects CJK characters and
automatically switches to XeLaTeX plus `xeCJK`. Verify a CJK font
(Noto Serif CJK SC) is installed, or the build will fail on missing
glyphs.

## Pre-Flight Checklist

Before converting a new document, confirm:

- [ ] YAML front matter has at least a `title`.
- [ ] Every table has a `: caption` line directly above it.
- [ ] Figure alt text reads as a proper caption.
- [ ] Every image path resolves on disk (`ls` them) — missing images are
      reported, not silently dropped.
- [ ] Section headings use `#` for top level.
- [ ] No literal `[#ref...]` citation markers.
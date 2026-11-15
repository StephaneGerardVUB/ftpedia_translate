#!/usr/bin/env python3
"""Convert extracted ft:pedia Markdown articles to LaTeX and compile them.

The Markdown files are those produced by ``split_ftpedia.py``. Each article is
rendered with ``ftpedia.cls`` (in ``ftpedia_template/``) and, unless disabled,
compiled to PDF with XeLaTeX.

Examples:
    python3 md2latex.py --magazine ftpedia-2026-1 --limit 2
    python3 md2latex.py --md output/ftpedia-2026-1/articles/03_*/*.md
    python3 md2latex.py --magazine ftpedia-2025-2 --limit 3 --no-fr --dpi 300
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import unicodedata

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(HERE, "ftpedia_template")

TITLE_RE = re.compile(r"^#\s+(.*)$")
HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")
META_RE = re.compile(r"^\*\*(Kategorie|Catégorie|Autor|Auteur)\s*:?\*\*\s*(.*)$")
IMAGE_RE = re.compile(r"^!\[[^\]]*\]\((?:\./)?images/([^)]+)\)\s*$")
CAPTION_RE = re.compile(
    r"^(Abb\.|Abbildung|Fig\.|Tab\.|Tabelle|Tableau|Bild)(?=\s|:|\d|$)")
FN_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
LIST_RE = re.compile(r"^[-*]\s+(.*)$")
ORDERED_RE = re.compile(r"^\d{1,2}[.)]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^:?-{3,}:?$")
LINK_RE = re.compile(r"\[([^\]]*)\]\(((?:[^()]|\([^)]*\))*)\)")

INLINE_RE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<math>\$[^$\n]+\$)"
    r"|(?P<link>\[[^\]]*\]\((?:[^()]|\([^)]*\))*\))"
    r"|(?P<bi>\*\*\*[^*]+\*\*\*)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<ital>\*[^*]+\*)"
    r"|(?P<fn>\[\^[^\]]+\])"
)

# Unicode maths symbols mapped to LaTeX: the text fonts used for maths
# (Computer Modern) have no Greek or symbol glyphs in their text encoding.
MATH_SYMBOLS = {
    "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ",
    "ε": r"\varepsilon ", "ϵ": r"\epsilon ", "ζ": r"\zeta ", "η": r"\eta ",
    "θ": r"\theta ", "ϑ": r"\vartheta ", "ι": r"\iota ", "κ": r"\kappa ",
    "λ": r"\lambda ", "μ": r"\mu ", "µ": r"\mu ", "ν": r"\nu ",
    "ξ": r"\xi ", "π": r"\pi ", "ϖ": r"\varpi ", "ρ": r"\rho ",
    "ϱ": r"\varrho ", "σ": r"\sigma ", "ς": r"\varsigma ", "τ": r"\tau ",
    "υ": r"\upsilon ", "φ": r"\varphi ", "ϕ": r"\phi ", "χ": r"\chi ",
    "ψ": r"\psi ", "ω": r"\omega ",
    "Γ": r"\Gamma ", "Δ": r"\Delta ", "∆": r"\Delta ", "Θ": r"\Theta ",
    "Λ": r"\Lambda ", "Ξ": r"\Xi ", "Π": r"\Pi ", "Σ": r"\Sigma ",
    "Υ": r"\Upsilon ", "Φ": r"\Phi ", "Ψ": r"\Psi ", "Ω": r"\Omega ",
    "−": "-", "×": r"\times ", "÷": r"\div ", "⋅": r"\cdot ",
    "∙": r"\cdot ", "·": r"\cdot ", "±": r"\pm ", "∓": r"\mp ",
    "≈": r"\approx ", "≠": r"\neq ", "≤": r"\leq ", "≥": r"\geq ",
    "≡": r"\equiv ", "∼": r"\sim ", "∝": r"\propto ",
    "∞": r"\infty ", "∑": r"\sum ", "∏": r"\prod ", "∫": r"\int ",
    "∂": r"\partial ", "∇": r"\nabla ", "√": r"\surd ",
    "→": r"\to ", "←": r"\leftarrow ", "↔": r"\leftrightarrow ",
    "⇒": r"\Rightarrow ", "⇐": r"\Leftarrow ", "⇔": r"\Leftrightarrow ",
    "∈": r"\in ", "∉": r"\notin ", "⊂": r"\subset ", "⊃": r"\supset ",    "⊆": r"\subseteq ", "⊇": r"\supseteq ", "∪": r"\cup ", "∩": r"\cap ",
    "∀": r"\forall ", "∃": r"\exists ", "∠": r"\angle ", "⊥": r"\perp ",
    "⨁": r"\oplus ", "⊕": r"\oplus ", "⨂": r"\otimes ", "⊗": r"\otimes ",
    "∨": r"\vee ", "∧": r"\wedge ", "¬": r"\neg ",
    "°": r"^{\circ}", "′": "'", "″": "''", "…": r"\ldots ",
}

MATH_TEXT_GROUP_RE = re.compile(r"\\(?:text|mathrm|operatorname|mbox|textrm)\s*\{")

# Artefacts left by the maths reconstruction: stretchy vector arrows and
# large delimiters reported as unrelated code points by the PDF extractor.
MATH_ARTIFACTS = {
    "\u122c": "", "\u20d7": "",       # stretchy/combining vector arrow
    "\u0d6d": "(", "\u1246": "(",      # large opening delimiter
    "\u0d71": ")",                     # large closing delimiter
    "\u0131": "i",                     # dotless i used as a maths variable
}


def normalize_math_glyphs(text: str) -> str:
    """Fold mathematical alphanumerics to plain characters.

    The PDF stores maths italics as ``U+1D400..U+1D7FF`` code points; text
    fonts have no glyph for them. NFKC maps them back to ASCII letters.
    """
    out: list[str] = []
    for char in text:
        if 0x1D400 <= ord(char) <= 0x1D7FF:
            char = unicodedata.normalize("NFKC", char)
        out.append(MATH_ARTIFACTS.get(char, char))
    return "".join(out)


def _brace_end(text: str, start: int) -> int:
    """Return the index just after the brace group opening at ``start``."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def latex_math(text: str) -> str:
    """Convert Unicode maths symbols to LaTeX, leaving textual groups alone."""
    text = normalize_math_glyphs(text)
    out: list[str] = []
    index = 0
    while index < len(text):
        group = MATH_TEXT_GROUP_RE.match(text, index)
        if group:
            end = _brace_end(text, group.end() - 1)
            out.append(text[index:end])
            index = end
            continue
        out.append(MATH_SYMBOLS.get(text[index], text[index]))
        index += 1
    return "".join(out)


TEXT_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_text(value: str) -> str:
    value = normalize_math_glyphs(value)
    return "".join(TEXT_ESCAPES.get(ch, ch) for ch in value)


def escape_url(value: str) -> str:
    return value.replace("%", r"\%").replace("#", r"\#").replace("&", r"\&")


class Converter:
    def __init__(self, source: str, out_root: str, dpi: int, issue: str | None):
        self.source = source
        self.dpi = dpi
        self.issue = issue
        self.footnotes: dict[str, str] = {}

    # -- inline -----------------------------------------------------------
    def inline(self, text: str) -> str:
        parts: list[str] = []
        last = 0
        for match in INLINE_RE.finditer(text):
            parts.append(escape_text(text[last:match.start()]))
            kind = match.lastgroup
            raw = match.group(0)
            if kind == "code":
                parts.append(r"\texttt{" + escape_text(raw[1:-1]) + "}")
            elif kind == "math":
                parts.append(r"\(" + latex_math(raw[1:-1]) + r"\)")
            elif kind == "link":
                link = LINK_RE.match(raw)
                anchor = self.inline(link.group(1))
                parts.append(r"\ftpediahref{" + escape_url(link.group(2))
                             + "}{" + anchor + "}")
            elif kind == "bi":
                parts.append(r"\textbf{\emph{" + self.inline(raw[3:-3]) + "}}")
            elif kind == "bold":
                parts.append(r"\textbf{" + self.inline(raw[2:-2]) + "}")
            elif kind == "ital":
                parts.append(r"\emph{" + self.inline(raw[1:-1]) + "}")
            elif kind == "fn":
                key = raw[2:-1]
                definition = self.footnotes.get(key, "")
                parts.append(r"\footnote{" + self.inline(definition) + "}")
            last = match.end()
        parts.append(escape_text(text[last:]))
        return "".join(parts)

    # -- tables -----------------------------------------------------------
    @staticmethod
    def split_row(line: str) -> list[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        cells = re.split(r"(?<!\\)\|", line)
        return [cell.strip().replace(r"\|", "|") for cell in cells]

    def table_block(self, rows: list[list[str]], caption: str | None) -> str:
        ncols = max(len(row) for row in rows)
        rows = [row + [""] * (ncols - len(row)) for row in rows]
        header, data = rows[0], rows[1:]
        header_cells = [r"\textbf{" + self.inline(cell) + "}" for cell in header]
        data_cells = [[self.inline(cell) for cell in row] for row in data]

        def render(cells: list[str]) -> str:
            return " & ".join(cells) + r" \\"

        if len(data) > 25:
            spec = (r"@{}*{" + str(ncols) + r"}{>{\raggedright\arraybackslash}"
                    r"p{\dimexpr(\linewidth-2\tabcolsep*" + str(ncols)
                    + r")/" + str(ncols) + r"\relax}}@{}")
            out = [r"\begin{longtable}{" + spec + "}"]
            if caption:
                out.append(r"\caption*{" + self.inline(caption) + r"}\\")
            out += [r"\hline", render(header_cells), r"\hline", r"\endhead"]
            out += [render(row) for row in data_cells]
            out.append(r"\hline")
            out.append(r"\end{longtable}")
            return "\n".join(out)

        small = r"\small" + "\n" if ncols > 4 else ""
        if ncols <= 2:
            begin = r"\begin{tabular}{@{}ll@{}}"
            end = r"\end{tabular}"
        else:
            begin = (r"\begin{tabularx}{\linewidth}{@{}*{" + str(ncols)
                     + r"}{X}@{}}")
            end = r"\end{tabularx}"
        out = [r"\begin{table}[H]", r"\centering"]
        if small:
            out.append(small.rstrip("\n"))
        out.append(begin)
        out += [r"\hline", render(header_cells), r"\hline"]
        out += [render(row) for row in data_cells]
        out.append(r"\hline")
        out.append(end)
        if caption:
            out.append(r"\caption*{" + self.inline(caption) + "}")
        out.append(r"\end{table}")
        return "\n".join(out)

    # -- images -----------------------------------------------------------
    def image_size_pt(self, filename: str) -> float:
        path = os.path.join(os.path.dirname(self.source), "images", filename)
        try:
            width = Image.open(path).size[0]
        except Exception:
            return 200.0
        return width * 72.0 / self.dpi

    # -- main conversion --------------------------------------------------
    def convert(self) -> str:
        with open(self.source, encoding="utf-8") as handle:
            raw_lines = handle.read().split("\n")

        body_lines: list[str] = []
        for line in raw_lines:
            match = FN_DEF_RE.match(line)
            if match:
                self.footnotes[match.group(1)] = match.group(2).strip()
            else:
                body_lines.append(line)

        title = rubrik = author = ""
        lines: list[str] = []
        for line in body_lines:
            stripped = line.strip()
            if not title:
                match = TITLE_RE.match(stripped)
                if match:
                    title = match.group(1).strip()
                    continue
            match = META_RE.match(stripped)
            if match:
                kind = match.group(1)
                value = match.group(2).strip()
                if kind in ("Kategorie", "Catégorie"):
                    rubrik = value
                else:
                    author = value
                continue
            lines.append(line)

        n = len(lines)
        i = 0
        abstract: str | None = None
        body: list[str] = []
        in_columns = False
        seen_section = False

        def cols_on() -> None:
            nonlocal in_columns
            if not in_columns:
                body.append(r"\begin{multicols}{2}")
                in_columns = True

        def cols_off() -> None:
            nonlocal in_columns
            if in_columns:
                body.append(r"\end{multicols}")
                in_columns = False

        def take_caption(index: int) -> tuple[str | None, int]:
            j = index
            while j < n and not lines[j].strip():
                j += 1
            if j < n and CAPTION_RE.match(lines[j].strip()):
                return lines[j].strip(), j + 1
            return None, index

        while i < n:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue

            # Fenced code
            if stripped.startswith("```"):
                i += 1
                code: list[str] = []
                while i < n and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    i += 1
                i += 1
                cols_on()
                block = [r"\begin{lstlisting}"] + code + [r"\end{lstlisting}"]
                body.append("\n".join(block))
                continue

            # Display maths
            if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) >= 4:
                maths = latex_math(stripped[2:-2].strip())
                cols_on()
                body.append(r"\[ " + maths + r" \]")
                i += 1
                continue

            # Image
            match = IMAGE_RE.match(stripped)
            if match:
                filename = match.group(1)
                caption, i = take_caption(i + 1)
                width_pt = self.image_size_pt(filename)
                full = width_pt > 300
                if full:
                    cols_off()
                else:
                    cols_on()
                out = [r"\begin{figure}[H]", r"\centering"]
                if full:
                    width = (r"\linewidth" if width_pt >= 440
                             else f"{width_pt:.1f}pt")
                else:
                    width = (r"\linewidth" if width_pt >= 195
                             else f"{width_pt:.1f}pt")
                out.append(r"\includegraphics[width=" + width
                           + r",height=0.9\textheight,keepaspectratio]{"
                           + filename + "}")
                if caption:
                    out.append(r"\caption*{" + self.inline(caption) + "}")
                out.append(r"\end{figure}")
                body.append("\n".join(out))
                continue

            # Table
            if stripped.startswith("|"):
                raw_rows: list[list[str]] = []
                while i < n and lines[i].strip().startswith("|"):
                    raw_rows.append(self.split_row(lines[i]))
                    i += 1
                if len(raw_rows) >= 2 and all(TABLE_SEP_RE.match(cell)
                                              for cell in raw_rows[1] if cell):
                    raw_rows = [raw_rows[0]] + raw_rows[2:]
                caption, i = take_caption(i)
                cols_off()
                body.append(self.table_block(raw_rows, caption))
                continue

            # Headings
            match = HEADING_RE.match(stripped)
            if match:
                level = len(match.group(1))
                command = r"\section" if level == 2 else r"\subsection"
                cols_on()
                body.append(command + "{" + self.inline(match.group(2)) + "}")
                seen_section = True
                i += 1
                continue

            # Blockquote (abstract / quote)
            if stripped.startswith(">"):
                quote: list[str] = []
                while i < n and lines[i].strip().startswith(">"):
                    quote.append(re.sub(r"^>\s?", "", lines[i].strip()))
                    i += 1
                text = self.inline(" ".join(quote).strip())
                if abstract is None and not seen_section:
                    abstract = text
                else:
                    cols_on()
                    body.append(r"\begin{quote}" + text + r"\end{quote}")
                continue

            # Bullet list
            match = LIST_RE.match(stripped)
            if match:
                cols_on()
                items = [r"\begin{itemize}"]
                while i < n:
                    item = LIST_RE.match(lines[i].strip())
                    if not item:
                        break
                    items.append(r"\item " + self.inline(item.group(1)))
                    i += 1
                items.append(r"\end{itemize}")
                body.append("\n".join(items))
                continue

            # Numbered list
            match = ORDERED_RE.match(stripped)
            if match:
                cols_on()
                items = [r"\begin{enumerate}"]
                while i < n:
                    item = ORDERED_RE.match(lines[i].strip())
                    if not item:
                        break
                    items.append(r"\item " + self.inline(item.group(1)))
                    i += 1
                items.append(r"\end{enumerate}")
                body.append("\n".join(items))
                continue

            # Paragraph
            paragraph: list[str] = [stripped]
            i += 1
            while i < n and lines[i].strip():
                candidate = lines[i].strip()
                if (HEADING_RE.match(candidate) or IMAGE_RE.match(candidate)
                        or candidate.startswith(("|", "```", "$$", ">"))
                        or LIST_RE.match(candidate) or ORDERED_RE.match(candidate)):
                    break
                paragraph.append(candidate)
                i += 1
            cols_on()
            body.append(self.inline(" ".join(paragraph)))

        cols_off()

        language = "french" if self.source.endswith(".fr.md") else "german"
        year, number = self.issue_parts()
        preamble: list[str] = [
            r"\documentclass[" + language + r"]{ftpedia}",
            r"\ftpediaissue{" + year + "}{" + number + "}",
            r"\rubrik{" + self.inline(rubrik) + "}",
            r"\titel{" + self.inline(title) + "}",
            r"\autor{" + self.inline(author) + "}",
            r"\graphicspath{{images/}}",
        ]
        document = "\n".join(preamble)
        document += "\n" + r"\begin{document}" + "\n" + r"\artikelkopf" + "\n"
        if abstract:
            document += ("\n" + r"\begin{ftabstract}" + "\n" + abstract + "\n"
                         + r"\end{ftabstract}" + "\n")
        document += "\n" + "\n\n".join(body) + "\n" + r"\end{document}" + "\n"
        return document

    def issue_parts(self) -> tuple[str, str]:
        if self.issue:
            match = re.match(r"(\d{4})-(\d+)", self.issue)
            if match:
                return match.group(1), match.group(2)
        match = re.search(r"ftpedia-(\d{4})-(\d+)", self.source)
        if match:
            return match.group(1), match.group(2)
        return "2026", "1"


def compile_pdf(tex_path: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env["TEXINPUTS"] = TEMPLATE_DIR + ":" + env.get("TEXINPUTS", "")
    folder = os.path.dirname(tex_path)
    name = os.path.basename(tex_path)
    output = ""
    for _ in range(2):
        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", name],
            cwd=folder, env=env, capture_output=True, text=True)
        output = result.stdout
        if result.returncode != 0:
            return False, output
    base = os.path.splitext(tex_path)[0]
    for ext in (".aux", ".log", ".out"):
        try:
            os.remove(base + ext)
        except OSError:
            pass
    return True, output


def convert_one(md_path: str, out_root: str, dpi: int, issue: str | None,
                compile_it: bool) -> bool:
    md_path = os.path.abspath(md_path)
    converter = Converter(md_path, out_root, dpi, issue)
    latex = converter.convert()
    tex_path = md_path[:-3] + ".tex"
    with open(tex_path, "w", encoding="utf-8") as handle:
        handle.write(latex)
    print(f"  LaTeX : {tex_path}")
    if compile_it:
        ok, output = compile_pdf(tex_path)
        if ok:
            print(f"  PDF   : {os.path.splitext(tex_path)[0]}.pdf")
        else:
            print(f"  ÉCHEC compilation : {tex_path}", file=sys.stderr)
            tail = "\n".join(output.splitlines()[-25:])
            print(tail, file=sys.stderr)
        return ok
    return True


def article_markdowns(magazine: str, out_root: str, limit: int | None,
                      include_fr: bool) -> list[str]:
    art_dir = os.path.join(out_root, magazine, "articles")
    if not os.path.isdir(art_dir):
        return []
    folders = sorted(d for d in os.listdir(art_dir)
                     if os.path.isdir(os.path.join(art_dir, d)))
    if limit:
        folders = folders[:limit]
    documents: list[str] = []
    for folder in folders:
        path = os.path.join(art_dir, folder)
        for filename in sorted(os.listdir(path)):
            if not filename.endswith(".md"):
                continue
            if filename.endswith(".fr.md") and not include_fr:
                continue
            documents.append(os.path.join(path, filename))
    return documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert ft:pedia Markdown articles to LaTeX (and PDF).")
    parser.add_argument("--magazine", default=None,
                        help="magazine folder under --out (e.g. ftpedia-2026-1)")
    parser.add_argument("--out", default="output", help="output root (default: output)")
    parser.add_argument("--md", nargs="+", default=None,
                        help="convert these Markdown files instead of a magazine")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N articles")
    parser.add_argument("--no-fr", action="store_true",
                        help="skip the French .fr.md files")
    parser.add_argument("--dpi", type=int, default=300,
                        help="DPI used when the images were rendered (default: 300)")
    parser.add_argument("--issue", default=None,
                        help="override the issue, e.g. 2026-1")
    parser.add_argument("--no-compile", action="store_true",
                        help="only write the .tex files (no PDF)")
    args = parser.parse_args(argv)

    if args.md:
        documents = args.md
    elif args.magazine:
        documents = article_markdowns(args.magazine, args.out, args.limit,
                                      not args.no_fr)
    else:
        parser.error("give either --magazine or --md")
        return 2
    if not documents:
        print("No Markdown document found.", file=sys.stderr)
        return 1

    failed = 0
    for md_path in documents:
        print(f"[{os.path.basename(os.path.dirname(md_path))}]")
        if not convert_one(md_path, args.out, args.dpi, args.issue,
                           not args.no_compile):
            failed += 1
    print(f"\n{len(documents) - failed}/{len(documents)} document(s) converted.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

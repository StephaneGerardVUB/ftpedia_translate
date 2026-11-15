#!/usr/bin/env python3
"""Split an ft:pedia PDF into single-article PDFs and extract their content.

For every article (bookmark of level 1) the script:

1. writes a standalone PDF containing only the pages of that article;
2. writes a Markdown file with the article text (two-column aware);
3. renders every figure to a PNG inside an ``images/`` sub-folder and inserts
   a Markdown reference at the right position in the text.

The category ("Kategorie") and the author ("Autor") printed on the first page
are detected and written as metadata lines at the top of the Markdown file and
into the PDF metadata. Paragraphs cut by a page break, a column break or an
illustration are stitched back together (when the first part does not end with
sentence punctuation) so that a sentence is never translated in two pieces. The
italic standfirst is written as a Markdown blockquote (the article abstract), tables are re-flowed as Markdown tables,
lists are kept as Markdown lists and footnotes become Markdown footnotes
(``[^n]`` references plus ``[^n]:`` definitions). Mathematical formulas set in
the CambriaMath font are rebuilt as LaTeX (``$$ ... $$``), including
super/subscripts, square roots and fractions; their equation numbers are kept
as ``\\tag{n}``. The optional ``--math-engine pix2tex`` runs
LaTeX-OCR on the detected formula regions instead (falls back to the geometric
reconstruction when the OCR result looks unreliable). Inline bold/italic and
external (URI) hyperlinks are preserved. When translating, the author name is
never translated, the labels become language specific (e.g. "Auteur :") and the
Markdown syntax (links, emphasis, tables, code, footnotes, maths) is protected.

Figures that are stored as several adjacent image tiles ("parts") inside the
PDF are re-assembled automatically: the tiles are grouped and the whole figure
is exported in one piece.

If ``--translate`` is given, an additional ``<article>.<lang>.md`` file is
written for every article. The translation engine is chosen with ``--engine``:
``azure`` (default; needs only ``azurekey.txt``, endpoint/location have
built-in defaults and can be overridden with ``--azure-params``),
``deepl`` (``deeplkey.txt``; several key files may be given for automatic
fallback), ``argos`` (offline, no key) or ``libre``
(``--libre-url`` + optional ``librekey.txt``). Translation can be postponed:
run once to extract the German Markdown, then run again with
``--translate-only`` to translate the existing ``.md`` files (no PDF/image
work; already-translated files are reused).

Free-tier notes (Azure F0): the free allowance is 2 million characters per
month (exhaustion -> HTTP 403 / 403001) on top of a throughput limit of
2 million characters per hour (too fast -> HTTP 429 / 429001).

Usage:
    python3 split_ftpedia.py                       # uses ./ftpedia-*.pdf
    python3 split_ftpedia.py --pdf file.pdf --out out --dpi 300
    python3 split_ftpedia.py --translate           # French, Azure engine
    python3 split_ftpedia.py --translate-only --engine deepl   # later pass
    python3 split_ftpedia.py --translate --engine argos --to en

The results go into one folder per magazine::

    <out>/<magazine>/
        pdf/            # one PDF per article
        articles/       # one folder per article (Markdown + images/)
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter

import fitz  # PyMuPDF
import requests


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
TILE_TOL = 2.0        # points: tolerance when detecting contiguous image tiles
COLUMN_GAP = 20.0     # points: half-width of the shield around the column axis
TOP_MARGIN = 72.0     # points: everything above is a running header
BOTTOM_MARGIN = 774.0 # points: everything below is a page number / footer

MAX_BATCH_ITEMS = 100    # Azure Translator: max 100 strings per request
MAX_BATCH_CHARS = 45000  # Azure Translator: max 50000 characters per request
MIN_REQUEST_INTERVAL = 1.2  # seconds between two Azure requests (F0 friendly)

# Default Azure Translator settings (no parameters file required).
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/"
AZURE_LOCATION = "westeurope"

CODE_FONT = "Courier"    # font used for code listings and inline code

_last_request = 0.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return value.strip("_") or "article"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def title_key(value: str) -> str:
    """Normalise a title, ignoring hyphenation/spacing differences.

    The table of contents title and the printed title often differ by
    hyphenation across line breaks (e.g. "Linear-antrieben" vs
    "Linearantrieben"), so comparing the space-free form is more robust.
    """
    return re.sub(r"\s+", "", normalize(value))


def approx(a: float, b: float, tol: float = TILE_TOL) -> bool:
    return abs(a - b) <= tol


CONJUNCTIONS = {"und", "oder", "sowie", "bzw", "bzw.", "beziehungsweise"}
UNITS = {"mm", "cm", "m", "km", "kg", "g", "mg", "v", "a", "w", "kw",
         "hz", "khz", "mhz", "ω", "kω", "µf", "nf", "pf", "l", "ml",
         "s", "ms", "µs", "%", "°", "°c"}
URL_RE = re.compile(r"(?:www\.|/|\.(?:de|com|org|net|fr|ch|at|eu|io)(?:\b|$|/))",
                    re.IGNORECASE)


def hyphen_parts(prev: str, nxt: str) -> tuple[bool, bool]:
    """Decide how to join at a hyphen: (keep the hyphen, add a space)."""
    head = nxt.split(None, 1)[0] if nxt.split() else ""
    tail = prev.rsplit(None, 1)[-1] if prev.split() else prev
    segment = tail[:-1].rsplit("-", 1)[-1]
    keep = (head[:1].isupper()
            or any(ch.isdigit() for ch in segment)
            or segment.lower() in UNITS
            or URL_RE.search(tail) is not None
            or URL_RE.search(head) is not None)
    space = head.strip(",.;:!?\"'“”„").lower() in CONJUNCTIONS
    return keep, space


def hyphen_join(prev: str, nxt: str) -> str:
    """Join two fragments where ``prev`` ends with a hyphen.

    A hyphen at a line break is either a soft hyphen (syllable break, to be
    dropped) or a real hyphen (compound, unit, path or URL, to be kept). A
    spaced dash (``100 -`` / ``400``) keeps its spaces.
    """
    tail = prev.rsplit(None, 1)[-1] if prev.split() else prev
    if tail == "-":
        return prev + " " + nxt
    keep, space = hyphen_parts(prev, nxt)
    if keep:
        return prev + nxt
    if space:
        return prev + " " + nxt
    return prev[:-1] + nxt


def join_fragments(prev: str, nxt: str) -> str:
    """Join two text fragments, handling the hyphen at the break."""
    prev, nxt = prev.rstrip(), nxt.lstrip()
    if not prev:
        return nxt
    if not nxt:
        return prev
    if prev.endswith("-"):
        return hyphen_join(prev, nxt)
    return prev + " " + nxt


def join_lines(lines: list[str]) -> str:
    """Join the lines of a text block, removing soft hyphens at line breaks."""
    out = ""
    for i, line in enumerate(lines):
        line = line.rstrip()
        out = line if i == 0 else join_fragments(out, line)
    return re.sub(r"\s+", " ", out).strip()


# Emphasis runs split over several lines: ``**a** **b**`` -> ``**a b**``.
ADJACENT_EMPH_RE = re.compile(r"(\*{1,3})([^*]+?)\1[ \t]+\1(?=[^*])")


def merge_emphasis(text: str) -> str:
    """Merge emphasis markers that a line break left on both sides.

    A bold (or italic) sentence wrapped over several PDF lines becomes one
    run; a trailing hyphen inside the run is handled like a line-break hyphen.
    """
    def repl(match: re.Match) -> str:
        marker, body = match.group(1), match.group(2)
        if body.endswith("-"):
            rest = match.string[match.end():]
            keep, space = hyphen_parts(body, rest)
            if keep:
                return f"{marker}{body}"
            if space:
                return f"{marker}{body} "
            return f"{marker}{body[:-1]}"
        return f"{marker}{body} "

    previous = None
    while previous != text:
        previous = text
        text = ADJACENT_EMPH_RE.sub(repl, text)
    return text


# ---------------------------------------------------------------------------
# Article detection / splitting
# ---------------------------------------------------------------------------
def find_articles(doc: fitz.Document, min_page: int) -> list[dict]:
    """Return one entry per top-level bookmark on/after ``min_page`` (1-based)."""
    groups: list[dict] = []
    for level, title, page in doc.get_toc():
        if level != 1 or page < min_page:
            continue
        if groups and groups[-1]["start"] == page:
            groups[-1]["titles"].append(title)
        else:
            groups.append({"titles": [title], "start": page})

    articles = []
    for i, group in enumerate(groups):
        end = groups[i + 1]["start"] - 1 if i + 1 < len(groups) else doc.page_count
        articles.append({
            "title": group["titles"][0],
            "start": group["start"],
            "end": end,
        })
        articles[-1]["name"] = f"{i + 1:02d}_{slugify(group['titles'][0])}"
    return articles


def split_pdfs(doc: fitz.Document, articles: list[dict], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for art in articles:
        out = fitz.open()
        out.insert_pdf(doc, from_page=art["start"] - 1, to_page=art["end"] - 1)
        category = art.get("category", "")
        title = art["title"]
        out.set_metadata({
            "title": f"{category}: {title}" if category else title,
            "author": art.get("author", ""),
            "subject": "ft:pedia",
        })
        target = os.path.join(out_dir, art["name"] + ".pdf")
        out.save(target, garbage=3, deflate=True)
        out.close()
        art["pdf"] = target


# ---------------------------------------------------------------------------
# Figure grouping (re-assembling tiled images)
# ---------------------------------------------------------------------------
def find_figures(page: fitz.Page) -> list[dict]:
    """Group the image placements of a page into logical, contiguous figures."""
    rects: list[fitz.Rect] = []
    for img in page.get_images(full=True):
        for rect in page.get_image_rects(img[0]):
            rects.append(fitz.Rect(rect))
    n = len(rects)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        a = rects[i]
        for j in range(i + 1, n):
            b = rects[j]
            vertical = (approx(a.x0, b.x0) and approx(a.x1, b.x1)
                        and (approx(a.y1, b.y0) or approx(b.y1, a.y0)))
            horizontal = (approx(a.y0, b.y0) and approx(a.y1, b.y1)
                          and (approx(a.x1, b.x0) or approx(b.x1, a.x0)))
            if vertical or horizontal:
                union(i, j)

    grouped: dict[int, list[fitz.Rect]] = {}
    for i, rect in enumerate(rects):
        grouped.setdefault(find(i), []).append(rect)

    figures = []
    for parts in grouped.values():
        union_rect = parts[0]
        for part in parts[1:]:
            union_rect = union_rect | part
        figures.append({"rect": union_rect, "parts": parts})
    return figures


def render_figure(page: fitz.Page, rect: fitz.Rect, dpi: int) -> fitz.Pixmap:
    zoom = dpi / 72.0
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)


# ---------------------------------------------------------------------------
# Math (CambriaMath) reconstruction to LaTeX
# ---------------------------------------------------------------------------
MATH_FONT = "Math"
RADICAL_CHARS = "\u0da5\u221a"  # CambriaMath radical glyph, plain sqrt sign
_MATH_INDICATOR = re.compile(r"[0-9=+\-−∙<>≈≤≥√()^]")
_EQ_NUMBER = re.compile(r"\(\d{1,3}[a-z]?\)")
_GREEK = {"𝛽": "\\beta", "𝛾": "\\gamma", "𝛼": "\\alpha", "𝛿": "\\delta",
          "𝜃": "\\theta", "𝜔": "\\omega", "𝜋": "\\pi", "𝜇": "\\mu"}
# Large delimiter glyphs from CambriaMath that map to stray code points.
_DELIMS = {"\u0d6c": "\\left(", "\u0d70": "\\right)"}


def _math_char(char: str) -> str:
    if char in _DELIMS:
        return _DELIMS[char]
    code = ord(char)
    if 0x1D44E <= code <= 0x1D467:              # mathematical italic a..z
        return chr(ord("a") + code - 0x1D44E)
    if 0x1D434 <= code <= 0x1D44D:              # mathematical italic A..Z
        return chr(ord("A") + code - 0x1D434)
    if code == 0x210E:                          # Planck h
        return "h"
    return _GREEK.get(char, char)


def _math_text(text: str) -> str:
    # Function names first, while Greek/italic chars are still single code
    # points (so "ωtan" is not blocked by the letters of a later "\omega").
    for name in ("arccos", "arcsin", "arctan", "cos", "sin", "tan", "cot", "log"):
        text = re.sub(r"(?<![A-Za-z\\])" + name + r"(?![A-Za-z])",
                      "\\\\" + name + " ", text)
    out = "".join(_math_char(c) for c in text)
    out = (out.replace("∙", "\\cdot ").replace("−", "-").replace("·", "\\cdot ")
           .replace("≈", "\\approx ").replace("≤", "\\le ").replace("≥", "\\ge ")
           .replace("°", "^{\\circ}"))
    for sup, value in (("⁰", "0"), ("¹", "1"), ("²", "2"), ("³", "3"),
                       ("⁴", "4"), ("⁵", "5"), ("⁶", "6"), ("⁷", "7"),
                       ("⁸", "8"), ("⁹", "9")):
        out = out.replace(sup, f"^{{{value}}}")
    return out


def is_math_block(block: dict) -> bool:
    """True for a block that is essentially a maths expression.

    The equation number (e.g. "(9)") is usually set in the body font, so it is
    ignored when checking that the remaining spans all use the maths font.
    """
    spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
    if not spans:
        return False
    core = [s for s in spans if not _EQ_NUMBER.fullmatch(s["text"].strip())]
    if not core or not all(MATH_FONT in s["font"] for s in core):
        return False
    text = "".join(s["text"] for s in core)
    return bool(_MATH_INDICATOR.search(text)) or any(c in text for c in RADICAL_CHARS)


def _split_span_at_x(span: dict, end_x: float) -> tuple[dict | None, dict | None]:
    """Split a span whose bounding box straddles ``end_x`` (approx. by width)."""
    x0, y0, x1, y1 = span["bbox"]
    if x1 <= end_x:
        return span, None
    if x0 >= end_x:
        return None, span
    text = span["text"]
    ratio = (end_x - x0) / max(x1 - x0, 1e-6)
    index = min(max(round(len(text) * ratio), 1), len(text) - 1)
    for offset in range(0, 4):
        for candidate in (index - offset, index + offset):
            if 0 < candidate < len(text) and text[candidate] == " ":
                index = candidate
                break
        else:
            continue
        break

    def piece(value: str, left: float, right: float) -> dict | None:
        if not value.strip():
            return None
        clone = dict(span)
        clone["text"] = value
        clone["bbox"] = (left, y0, right, y1)
        return clone

    return piece(text[:index], x0, end_x), piece(text[index:], end_x, x1)


def render_math(spans: list[dict], sqrt_end: dict | None = None) -> str:
    """Render a list of spans as a LaTeX fragment (super/subscripts, roots)."""
    spans = [s for s in spans if s["text"].strip()]
    if not spans:
        return ""
    sqrt_end = sqrt_end or {}
    base = max(s["size"] for s in spans)
    centres = [(s["bbox"][1] + s["bbox"][3]) / 2 for s in spans
               if s["size"] >= base - 1.5]
    base_y = sum(centres) / len(centres) if centres else 0
    parts: list[str] = []
    index = 0
    while index < len(spans):
        span = spans[index]
        raw = span["text"]
        if any(c in raw for c in RADICAL_CHARS):
            end_x = sqrt_end.get(id(span))
            if end_x is not None:
                radicand = []
                j = index + 1
                while j < len(spans):
                    candidate = spans[j]
                    cx0 = candidate["bbox"][0]
                    cx1 = candidate["bbox"][2]
                    if cx1 <= end_x + 4:
                        radicand.append(candidate)
                        j += 1
                        continue
                    if cx0 < end_x + 4:  # straddles the end of the vinculum
                        inside, outside = _split_span_at_x(candidate, end_x)
                        if inside:
                            radicand.append(inside)
                        if outside:
                            spans = spans[:j] + [outside] + spans[j + 1:]
                    break
                parts.append("\\sqrt{" + render_math(radicand, sqrt_end) + "}")
                index = j
                continue
            # No vinculum: wrap the next token as radicand.
            if index + 1 < len(spans):
                parts.append("\\sqrt{" + render_math([spans[index + 1]],
                                                      sqrt_end) + "}")
                index += 2
            else:
                parts.append("\\sqrt{}")
                index += 1
            continue
        if span["size"] < base - 1.5:
            centre = (span["bbox"][1] + span["bbox"][3]) / 2
            mark = "^" if centre < base_y else "_"
            parts.append(f"{mark}{{{_math_text(raw.strip())}}}")
        else:
            parts.append(_math_text(raw))
        index += 1
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def extract_math(page: fitz.Page, drawings: list,
                 blocks: list[dict]) -> list[dict]:
    """Build LaTeX items from maths blocks, merging fractions (bar + two lines)."""
    lines: list[dict] = []
    for block in blocks:
        for line in block["lines"]:
            spans = [s for s in line["spans"]
                     if s["text"].strip()
                     and not _EQ_NUMBER.fullmatch(s["text"].strip())]
            if spans:
                lines.append({"bbox": fitz.Rect(line["bbox"]), "spans": spans})

    def centre_x(span: dict) -> float:
        return (span["bbox"][0] + span["bbox"][2]) / 2

    def centre_y(span: dict) -> float:
        return (span["bbox"][1] + span["bbox"][3]) / 2

    all_spans = [s for line in lines for s in line["spans"]]

    # Radical signs carry a vinculum (thin horizontal rule) that tells where
    # the radicand ends; collect it and keep those rules out of the fraction
    # detection below.
    sqrt_end: dict[int, float] = {}
    radical_bars: set[tuple] = set()
    for span in all_spans:
        if not any(c in span["text"] for c in RADICAL_CHARS):
            continue
        best = None
        for drawing in drawings:
            rect = drawing["rect"]
            if (rect.height < 2.5 and rect.width > 2
                    and abs(rect.x0 - span["bbox"][2]) < 5
                    and abs(rect.y0 - span["bbox"][1]) < 8):
                if best is None or rect.x1 > best.x1:
                    best = rect
        if best is not None:
            sqrt_end[id(span)] = best.x1
            radical_bars.add((round(best.x0, 1), round(best.y0, 1),
                              round(best.x1, 1)))

    bars = [fitz.Rect(d["rect"]) for d in drawings
            if d["rect"].height < 2.5 and 4 < d["rect"].width < 260
            and (round(d["rect"].x0, 1), round(d["rect"].y0, 1),
                 round(d["rect"].x1, 1)) not in radical_bars]
    bars.sort(key=lambda r: (round(r.y0), r.x0))
    items: list[dict] = []
    consumed: set[int] = set()

    def strip_operators(spans: list[dict]) -> list[dict]:
        cleaned = []
        for position, span in enumerate(spans):
            text = span["text"]
            if position == 0:  # only drop a leading operator at the very start
                text = text.lstrip("∙·⋅×")
            if text.strip():
                clone = dict(span)
                clone["text"] = text
                cleaned.append(clone)
        return cleaned

    for bar in bars:
        y_mid = (bar.y0 + bar.y1) / 2
        near = [s for s in all_spans if id(s) not in consumed
                and bar.y0 - 18 <= centre_y(s) <= bar.y1 + 14]
        prefix = [s for s in near if centre_x(s) < bar.x0 - 1]
        numerator = [s for s in near if bar.x0 - 1 <= centre_x(s) <= bar.x1 + 2
                     and centre_y(s) < y_mid]
        denominator = [s for s in near if bar.x0 - 1 <= centre_x(s) <= bar.x1 + 2
                       and centre_y(s) >= y_mid]
        if not strip_operators(numerator) or not strip_operators(denominator):
            continue
        for group in (prefix, numerator, denominator):
            group.sort(key=centre_x)
        consumed.update(id(s) for s in prefix + numerator + denominator)
        numerator = strip_operators(numerator)
        denominator = strip_operators(denominator)
        rect = fitz.Rect(min(s["bbox"][0] for s in numerator + denominator),
                         min(s["bbox"][1] for s in numerator + denominator),
                         max(s["bbox"][2] for s in numerator + denominator),
                         max(s["bbox"][3] for s in numerator + denominator))
        items.append({"kind": "math", "rect": rect,
                      "latex": (render_math(prefix, sqrt_end)
                                + f"\\frac{{{render_math(numerator, sqrt_end)}}}"
                                  f"{{{render_math(denominator, sqrt_end)}}}")})

    for line in lines:
        remaining = [s for s in line["spans"] if id(s) not in consumed]
        if not remaining:
            continue
        text = "".join(s["text"] for s in remaining)
        if not _MATH_INDICATOR.search(text):
            continue
        latex = render_math(remaining, sqrt_end)
        if latex:
            items.append({"kind": "math", "rect": line["bbox"], "latex": latex})
    return merge_math_items(items)


def merge_math_items(items: list[dict]) -> list[dict]:
    """Merge maths fragments that share a baseline (same formula line)."""
    def centre_y(item: dict) -> float:
        return (item["rect"].y0 + item["rect"].y1) / 2

    items.sort(key=lambda it: (round(centre_y(it) / 4), it["rect"].x0))
    merged: list[dict] = []
    for item in items:
        if merged:
            prev = merged[-1]
            same_line = abs(centre_y(prev) - centre_y(item)) < 11
            close = item["rect"].x0 - prev["rect"].x1 < 25
            if same_line and close:
                prev["latex"] = f"{prev['latex']} {item['latex']}".strip()
                prev["rect"] = prev["rect"] | item["rect"]
                continue
        merged.append({"kind": "math", "rect": item["rect"],
                       "latex": item["latex"]})
    return merged


def attach_equation_labels(items: list[dict], page_blocks: list[dict]) -> list[dict]:
    """Attach equation numbers "(n)" to their formula using LaTeX ``\\tag{n}``.

    Labels that sit to the right of a formula on the same line are turned into
    ``\\tag{n}``; the corresponding standalone "(n)" text items are removed.
    """
    labels: list[tuple[fitz.Rect, str]] = []
    for block in page_blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if _EQ_NUMBER.fullmatch(span["text"].strip()):
                    labels.append((fitz.Rect(span["bbox"]), span["text"].strip()))

    attached: list[fitz.Rect] = []
    for rect, text in labels:
        centre = (rect.y0 + rect.y1) / 2
        best, best_dy = None, 1e9
        for item in items:
            if item.get("kind") != "math" or "\\tag{" in item["latex"]:
                continue
            r = item["rect"]
            dy = abs(centre - (r.y0 + r.y1) / 2)
            if dy <= 12 and rect.x0 >= r.x1 - 6 and dy < best_dy:
                best, best_dy = item, dy
        if best is not None:
            number = text.strip("()")
            best["latex"] = f"{best['latex']} \\tag{{{number}}}"
            best["rect"] = best["rect"] | rect
            attached.append(rect)

    if not attached:
        return items

    def is_attached_label(item: dict) -> bool:
        if item.get("kind") != "text" or not _EQ_NUMBER.fullmatch(item["text"].strip()):
            return False
        r = item["rect"]
        return any(abs(r.x0 - a.x0) < 4 and abs(r.y0 - a.y0) < 4 for a in attached)

    return [it for it in items if not is_attached_label(it)]


# Maths OCR (pix2tex / LaTeX-OCR) used on the detected formula regions.
_MATH_ENGINE = "heuristic"
_LATEX_OCR = None
# pix2tex sometimes hallucinates on dense/nested formulas; such results are
# rejected in favour of the geometric reconstruction.
_OCR_DENYLIST = ("\\mathcal", "\\underline", "\\I", "\\l_", "\\boldsymbol")


def set_math_engine(name: str) -> str:
    """Select the maths engine: 'heuristic', 'pix2tex' or 'auto'."""
    global _MATH_ENGINE
    name = (name or "heuristic").lower()
    if name == "auto":
        import importlib.util
        name = "pix2tex" if importlib.util.find_spec("pix2tex") else "heuristic"
    if name not in ("heuristic", "pix2tex"):
        raise ValueError(f"unknown maths engine: {name}")
    _MATH_ENGINE = name
    return name


def ocr_math(page: fitz.Page, rect: fitz.Rect, dpi: int = 300) -> str | None:
    """Run LaTeX-OCR on a formula region and return LaTeX (or None)."""
    global _LATEX_OCR
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    if _LATEX_OCR is None:
        from pix2tex.cli import LatexOCR
        _LATEX_OCR = LatexOCR()
    pad = 3.0
    clip = fitz.Rect(rect.x0 - pad, rect.y0 - pad,
                     rect.x1 + pad, rect.y1 + pad) & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip)
    from PIL import Image
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    guess = _LATEX_OCR(image).strip()
    if not guess or len(guess) < 3:
        return None
    if any(bad in guess for bad in _OCR_DENYLIST):
        return None
    return guess


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------
def page_links(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """Return the external (URI) hyperlinks of a page as (rect, uri) pairs."""
    links = []
    for link in page.get_links():
        if link.get("kind") == 2 and link.get("uri"):
            links.append((fitz.Rect(link["from"]), link["uri"]))
    return links


def link_for_span(rect: fitz.Rect, links: list[tuple[fitz.Rect, str]]) -> str | None:
    """Return the URI covering ``rect`` (largest overlap), if any."""
    best_uri, best_area = None, 0.0
    span_area = max(rect.width, 0) * max(rect.height, 0) or 1.0
    for link_rect, uri in links:
        overlap = rect & link_rect
        if overlap.is_empty:
            continue
        area = max(overlap.width, 0) * max(overlap.height, 0)
        center_inside = link_rect.contains(fitz.Point((rect.x0 + rect.x1) / 2,
                                                      (rect.y0 + rect.y1) / 2))
        if (area > 0.45 * span_area or center_inside) and area > best_area:
            best_uri, best_area = uri, area
    return best_uri


def markdown_link(text: str, uri: str) -> str:
    """Wrap ``text`` in a Markdown link, keeping the original spacing."""
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}[{stripped}]({uri}){trail}"


def _wrap_marker(parts: list[str], marker: str) -> str:
    """Wrap a run of spans in a Markdown marker, keeping the spacing."""
    joined = "".join(parts)
    stripped = joined.strip()
    if not stripped:
        return joined
    lead = joined[:len(joined) - len(joined.lstrip())]
    trail = joined[len(joined.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{trail}"


# Characters used as bullet points in the magazine (Symbol font included).
BULLETS = "\uf0b7\u2022\u25aa\u25e6\u2023\u00b7\u25cf\u25a0"
ORDERED_RE = re.compile(r"^(\d{1,2})[.)]\s+\S")


def _looks_like_code(line: str) -> bool:
    """True if a code line starts a statement instead of continuing a comment."""
    text = line.strip()
    if not text:
        return False
    if text.startswith(("#", "//", "/*", "*", "}", "{")):
        return True
    if any(token in text for token in (";", "=", "{", "}")):
        return True
    if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*\s*\(", text):
        return True
    if re.match(r"^(?:if|for|while|switch|case|else|return|void|int|char"
                r"|float|double|long|unsigned|const|static|struct|typedef"
                r"|class|public|private|def|import|from|print|echo|end"
                r"|begin|function|var|let)\b", text):
        return True
    return False


def _has_comment(line: str) -> bool:
    """True if the line contains a ``//`` comment (and not a URL scheme)."""
    return re.search(r"(?:^|\s)//", line) is not None


def rejoin_code_lines(code: str) -> str:
    """Stitch back comment lines wrapped by the narrow PDF column.

    In the magazine a long ``//`` comment is wrapped onto the next line; the
    continuation has no statement marker, so it is appended to the comment.
    """
    lines: list[str] = []
    for raw in code.split("\n"):
        line = raw.rstrip()
        if (lines and _has_comment(lines[-1]) and line.strip()
                and not _looks_like_code(line)):
            lines[-1] = lines[-1].rstrip() + " " + line.strip()
        else:
            lines.append(line)
    return "\n".join(lines)


def _segment_runs(records: list[dict]) -> list[dict]:
    """Group records into code runs, list items and prose runs.

    A bullet starts a list item; the following prose lines belong to it until
    the next bullet (wrapped list items) or a code line.
    """
    runs: list[dict] = []
    for record in records:
        if record["code"]:
            if runs and runs[-1]["kind"] == "code":
                runs[-1]["records"].append(record)
            else:
                runs.append({"kind": "code", "records": [record]})
        elif record["bullet"] or record["ordered"]:
            # Every bullet / numbered marker starts a new list item.
            runs.append({"kind": "list", "records": [record]})
        elif runs and runs[-1]["kind"] == "list":
            runs[-1]["records"].append(record)  # continuation of a list item
        elif runs and runs[-1]["kind"] == "text":
            runs[-1]["records"].append(record)
        else:
            runs.append({"kind": "text", "records": [record]})
    return runs


def find_footnote_top(page: fitz.Page, drawings: list) -> float | None:
    """Return the y of the short rule that separates footnotes, if any."""
    top = None
    for drawing in drawings:
        rect = drawing["rect"]
        if (rect.height < 2 and 100 < rect.width < 220
                and rect.x0 < page.rect.width * 0.5):
            top = rect.y1 if top is None else max(top, rect.y1)
    return top


def has_footnote_marker(page: fitz.Page, footnote_top: float) -> bool:
    """True if a numbered footnote block exists below the separator rule."""
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0 or block["bbox"][1] < footnote_top - 2:
            continue
        spans = [s for s in block["lines"][0]["spans"] if s["text"].strip()]
        if (spans and spans[0]["size"] <= 9
                and re.fullmatch(r"\d{1,2}", spans[0]["text"].strip())):
            return True
    return False


def page_items(page: fitz.Page) -> list[dict]:
    """Return text, code, lists, footnotes, figures and tables of a page."""
    figures = find_figures(page)
    links = page_links(page)
    drawings = page.get_drawings()
    footnote_top = find_footnote_top(page, drawings)
    # A short rule may be a fraction bar or a decorative line; only treat it as
    # a footnote separator when a numbered note actually follows it.
    if footnote_top is not None and not has_footnote_marker(page, footnote_top):
        footnote_top = None
    tables = []
    # Tables are rare and only occur on pages with many drawn grid lines.
    if len(drawings) > 50:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                found = page.find_tables()
        except Exception:
            found = None
        if found:
            for table in found.tables:
                info = extract_table(page, fitz.Rect(table.bbox))
                if info and len(info["rows"]) >= 2:
                    tables.append({
                        "kind": "table", "rect": info["rect"],
                        "markdown": table_to_markdown(info["rows"],
                                                      info["columns"]),
                    })
    items: list[dict] = []
    footnote_blocks: list[dict] = []

    page_blocks = page.get_text("dict")["blocks"]
    math_ids = {i for i, b in enumerate(page_blocks)
                if b["type"] == 0 and is_math_block(b)}
    math_items = (extract_math(page, drawings, [page_blocks[i] for i in math_ids])
                  if math_ids else [])

    last_ordered_no = 0  # to accept numbered lists only as 1, 2, 3, ...

    for index, block in enumerate(page_blocks):
        if block["type"] != 0 or index in math_ids:
            continue
        x0, y0, x1, y1 = block["bbox"]
        if y1 < TOP_MARGIN or y0 > BOTTOM_MARGIN:
            continue
        center = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if any(t["rect"].contains(center) for t in tables):
            continue
        block_size = max((s["size"] for line in block["lines"]
                          for s in line["spans"] if s["text"].strip()), default=0)
        is_footnote = (footnote_top is not None and y0 >= footnote_top - 2
                       and block_size <= 10.5)

        records: list[dict] = []
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            raw_line = "".join(s["text"] for s in line["spans"])
            if all(CODE_FONT in s["font"] for s in spans):
                records.append({
                    "code": True, "bullet": False, "ordered": False,
                    "bbox": fitz.Rect(line["bbox"]),
                    "raw": raw_line,
                })
                continue

            # A line that is entirely italic (caption, standfirst) or entirely
            # bold-italic (subtitle) is not wrapped with inline markers.
            all_italic = all("Italic" in s["font"] for s in spans)
            bullet = raw_line.strip()[:1] in BULLETS

            parts: list[str] = []
            fonts: list[str] = []
            line_size = 0.0
            line_bold = line_italic = False
            current_kind = None
            buffer: list[str] = []

            def flush_run() -> None:
                if current_kind == "code":
                    parts.append(_wrap_marker(buffer, "`"))
                elif current_kind == "bi":
                    parts.append(_wrap_marker(buffer, "***"))
                elif current_kind == "bold":
                    parts.append(_wrap_marker(buffer, "**"))
                elif current_kind == "italic":
                    parts.append(_wrap_marker(buffer, "*"))
                else:
                    parts.append("".join(buffer))

            for span in line["spans"]:
                is_code = CODE_FONT in span["font"]
                if (not is_code and not is_footnote and footnote_top is not None
                        and span["size"] <= 9
                        and re.fullmatch(r"\d{1,2}", span["text"].strip())):
                    # Superscript footnote reference in the body text. Only on
                    # pages that actually have a footnote zone, so that maths
                    # exponents (also small digits) are not mistaken for notes.
                    if current_kind is not None:
                        flush_run()
                    current_kind, buffer = "plain", []
                    buffer.append(f"[[FN:{span['text'].strip()}]]")
                    continue
                is_bold = not is_code and "Bold" in span["font"]
                is_italic = (not is_code and "Italic" in span["font"]
                             and not all_italic)
                if is_code:
                    kind = "code"
                elif is_bold and is_italic:
                    kind = "bi"
                elif is_bold:
                    kind = "bold"
                elif is_italic:
                    kind = "italic"
                else:
                    kind = "plain"
                span_text = span["text"]
                if not is_code:
                    uri = link_for_span(fitz.Rect(span["bbox"]), links)
                    if uri:
                        span_text = markdown_link(span_text, uri)
                    fonts.append(span["font"])
                    line_size = max(line_size, span["size"])
                    line_bold = line_bold or "Bold" in span["font"]
                    line_italic = line_italic or "Italic" in span["font"]
                if kind != current_kind:
                    if current_kind is not None:
                        flush_run()
                    current_kind, buffer = kind, []
                buffer.append(span_text)
            if current_kind is not None:
                flush_run()
            line_text = "".join(parts)
            ordered = False
            match = ORDERED_RE.match(line_text)
            if match and int(match.group(1)) in (1, last_ordered_no + 1):
                # Only treat "N." as a list marker when it fits a 1,2,3...
                # sequence, so that stray references like "15)" are ignored.
                ordered = True
                last_ordered_no = int(match.group(1))
            records.append({
                "code": False, "bullet": bullet, "ordered": ordered,
                "bbox": fitz.Rect(line["bbox"]),
                "text": line_text, "size": line_size,
                "bold": line_bold, "italic": line_italic,
                "font": Counter(fonts).most_common(1)[0][0] if fonts else "",
            })

        if is_footnote:
            first_spans = [s for s in block["lines"][0]["spans"] if s["text"].strip()]
            marker = None
            if (first_spans and first_spans[0]["size"] <= 9
                    and re.fullmatch(r"\d{1,2}", first_spans[0]["text"].strip())):
                marker = first_spans[0]["text"].strip()
            text_lines = [r.get("text", r.get("raw", "")) for r in records]
            if marker and text_lines:
                text_lines[0] = re.sub(r"^\s*" + re.escape(marker) + r"\s*", "",
                                       text_lines[0], count=1)
            footnote_blocks.append({
                "number": marker, "y0": y0, "x0": x0,
                "rect": fitz.Rect(x0, y0, x1, y1),
                "text": join_lines([t for t in text_lines if t.strip()]),
            })
            continue

        for run in _segment_runs(records):
            group = run["records"]
            rect = group[0]["bbox"]
            for record in group[1:]:
                rect = rect | record["bbox"]

            if run["kind"] == "code":
                code = rejoin_code_lines(
                    "\n".join(r["raw"].rstrip() for r in group))
                if code.strip():
                    items.append({"kind": "code", "rect": rect, "text": code})
                continue

            if run["kind"] == "list":
                if group[0].get("ordered"):
                    text = join_lines([r["text"] for r in group])
                else:
                    first = group[0]["text"].lstrip(BULLETS).lstrip()
                    lines = ([first] if first else []) + [r["text"] for r in group[1:]]
                    text = "- " + join_lines([l for l in lines if l.strip()]).strip()
                if text.strip():
                    items.append({"kind": "list", "rect": rect, "text": text.strip()})
                continue

            text = join_lines([r["text"] for r in group])
            if not text:
                continue
            items.append({
                "kind": "text", "rect": rect, "text": text,
                "size": max(r["size"] for r in group),
                "bold": any(r["bold"] for r in group),
                "italic": any(r["italic"] for r in group),
                "font": Counter(r["font"] for r in group if r["font"])
                        .most_common(1)[0][0] if any(r["font"] for r in group) else "",
                "lines": [{"text": r["text"], "size": r["size"],
                           "bold": r["bold"], "italic": r["italic"]}
                          for r in group],
            })

    for figure in figures:
        items.append({"kind": "figure", "rect": figure["rect"],
                      "parts": figure["parts"]})

    items.extend(tables)
    items.extend(math_items)
    items = attach_equation_labels(items, page_blocks)

    # Assemble footnote blocks in reading order (left column, then right):
    # a marked block starts a note, the following unmarked block(s) continue it.
    current = None
    for block in sorted(footnote_blocks,
                        key=lambda f: (0 if f["x0"] < page.rect.width / 2 else 1,
                                       f["y0"])):
        if block["number"] is not None:
            if current:
                items.append(current)
            current = {"kind": "footnote", "number": block["number"],
                       "text": block["text"], "rect": block["rect"]}
        elif current:
            current["text"] = join_lines([current["text"], block["text"]])
    if current:
        items.append(current)

    # Drop markers that do not match an actual footnote on the page: revert
    # them to the plain digit (e.g. a maths exponent such as a^2).
    defined = {block["number"] for block in footnote_blocks if block["number"]}
    for item in items:
        if item.get("kind") in ("text", "list") and "[[FN:" in item["text"]:
            item["text"] = re.sub(
                r"\[\[FN:(\d+)\]\]",
                lambda m: m.group(0) if m.group(1) in defined else m.group(1),
                item["text"])

    attach_captions(items)
    return [it for it in items if not it.get("_caption")]


CAPTION_RE = re.compile(
    r"^\s*(Abb\.|Bild|Fig\.|Tab\.|Tabelle|Foto|Quelle)(?=\s|:|\d|$)")


def is_caption(item: dict) -> bool:
    if item["kind"] != "text":
        return False
    return bool(CAPTION_RE.match(item["text"])) or (
        item["italic"] and item["size"] <= 11.5)


def attach_captions(items: list[dict]) -> None:
    """Attach a caption sitting under a figure/table to that host."""
    hosts = [it for it in items if it["kind"] in ("figure", "table")]
    for item in items:
        if item["kind"] != "text" or not is_caption(item):
            continue
        caption = item["rect"]
        best, best_gap = None, 1e9
        for host in hosts:
            rect = host["rect"]
            if caption.x1 < rect.x0 - 5 or caption.x0 > rect.x1 + 5:
                continue
            gap = caption.y0 - rect.y1
            if -5 <= gap <= 60 and gap < best_gap:
                best, best_gap = host, gap
        if best is not None:
            best.setdefault("captions", []).append(item)
            item["_caption"] = True


def _group_rows(words: list) -> list[dict]:
    """Group words into visual rows (clustered by their vertical centre)."""
    rows: list[dict] = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        y_center = (word[1] + word[3]) / 2
        for row in rows:
            if abs(row["y"] - y_center) <= 4:
                row["words"].append(word)
                break
        else:
            rows.append({"y": y_center, "words": [word]})
    rows.sort(key=lambda r: r["y"])
    return rows


def extract_table(page: fitz.Page, rect: fitz.Rect) -> dict | None:
    """Reconstruct a table that has no reliable grid lines.

    Words are grouped into rows and the columns are derived from the
    horizontal whitespace gaps between words; this copes with merged header
    cells (e.g. "TOP Oktave") that a geometric table finder mis-splits.
    """
    words = page.get_text("words", clip=rect)
    if not words:
        return None

    data_rows, caption_rows = [], []
    for group in _group_rows(words):
        text = " ".join(w[4] for w in sorted(group["words"], key=lambda w: w[0]))
        (caption_rows if CAPTION_RE.match(text.strip()) else data_rows).append(
            group["words"])

    data_words = [w for group in data_rows for w in group]
    if not data_words:
        return None

    intervals = sorted((w[0], w[2]) for w in data_words)
    columns: list[list[float]] = []
    for x0, x1 in intervals:
        if columns and x0 - columns[-1][1] <= 6:
            columns[-1][1] = max(columns[-1][1], x1)
        else:
            columns.append([x0, x1])

    def column_of(x: float) -> int:
        best, best_dist = 0, 1e9
        for i, (x0, x1) in enumerate(columns):
            dist = 0.0 if x0 <= x <= x1 else min(abs(x - x0), abs(x - x1))
            if dist < best_dist:
                best, best_dist = i, dist
        return best

    rows = []
    for group in data_rows:
        cells = [""] * len(columns)
        for word in sorted(group, key=lambda w: w[0]):
            index = column_of(word[0])
            cells[index] = (cells[index] + " " + word[4]).strip()
        rows.append(cells)

    table_rect = fitz.Rect(
        min(w[0] for w in data_words), min(w[1] for w in data_words),
        max(w[2] for w in data_words), max(w[3] for w in data_words))
    return {"rows": rows, "columns": len(columns), "rect": table_rect}


def table_to_markdown(rows: list[list[str]], columns: int) -> str:
    def line(cells: list[str]) -> str:
        padded = cells + [""] * (columns - len(cells))
        return "| " + " | ".join((c or "").replace("|", "\\|")
                                 for c in padded) + " |"

    output = [line(rows[0]), "| " + " | ".join("---" for _ in range(columns)) + " |"]
    output.extend(line(cells) for cells in rows[1:])
    return "\n".join(output)


def order_items(items: list[dict], mid_x: float) -> list[dict]:
    """Order items in two-column reading order.

    Items that really span the whole text width (headlines, full-width
    figures) act as separators; inside each band all left-column items are read
    top-to-bottom and then all right-column items.
    """
    text_items = [it for it in items if it["kind"] == "text"]
    if text_items:
        content_left = min(it["rect"].x0 for it in text_items)
        content_right = max(it["rect"].x1 for it in text_items)
    else:
        content_left, content_right = 0.0, 2.0 * mid_x

    def is_full(item: dict) -> bool:
        rect = item["rect"]
        return (rect.x0 < content_left + COLUMN_GAP
                and rect.x1 > content_right - COLUMN_GAP)

    def column(item: dict) -> int:
        rect = item["rect"]
        return 0 if (rect.x0 + rect.x1) / 2.0 < mid_x else 1

    fulls = sorted((it for it in items if is_full(it)),
                   key=lambda it: it["rect"].y0)
    rest = [it for it in items if not is_full(it)]

    ordered: list[dict] = []
    prev_y = -1e9
    for full in fulls:
        band = [it for it in rest if prev_y <= it["rect"].y0 < full["rect"].y0]
        band.sort(key=lambda it: (column(it), it["rect"].y0))
        ordered.extend(band)
        ordered.append(full)
        prev_y = full["rect"].y0
    band = [it for it in rest if it["rect"].y0 >= prev_y]
    band.sort(key=lambda it: (column(it), it["rect"].y0))
    ordered.extend(band)
    return ordered


def body_font_size(pages: list[tuple]) -> float:
    sizes: list[float] = []
    for _, _, items in pages:
        sizes.extend(it["size"] for it in items if it["kind"] == "text")
    if not sizes:
        return 12.0
    return Counter(round(s, 1) for s in sizes).most_common(1)[0][0]


def detect_metadata(doc: fitz.Document, article: dict) -> tuple[str, str]:
    """Return the (category, author) shown on the first page of an article.

    The category is the small non-bold line inside the title block; the author
    is the short sans-serif block sitting between the title and the italic
    standfirst. Either value is empty when it cannot be found.
    """
    page = doc[article["start"] - 1]
    items = page_items(page)
    target = title_key(article["title"])
    page_height = page.rect.height

    title_item = None
    for item in items:
        if (item["kind"] == "text" and item["size"] >= 18 and item["bold"]
                and target and target in title_key(item["text"])):
            title_item = item
            break

    category = ""
    title_bottom = 0.0
    if title_item:
        title_bottom = title_item["rect"].y1
        title_size = title_item["size"]
        parts = [line["text"].strip() for line in title_item["lines"]
                 if line["size"] < title_size - 3 and line["text"].strip()]
        category = " ".join(parts).strip()
        if not category:
            # The category may have been split into its own block (different
            # font weight than the title): look for a short non-bold sans-serif
            # line sitting just above the title, left aligned with it.
            candidates = []
            for item in items:
                if item is title_item or item["kind"] != "text":
                    continue
                if item["bold"] or "Arial" not in item.get("font", ""):
                    continue
                if item["size"] >= title_size - 1:
                    continue
                text = item["text"].strip()
                if not text or len(text) > 40:
                    continue
                if abs(item["rect"].x0 - title_item["rect"].x0) > 25:
                    continue
                if (title_item["rect"].y0 - 60 <= item["rect"].y0
                        and item["rect"].y1 <= title_item["rect"].y0 + 6):
                    candidates.append(item)
            if candidates:
                candidates.sort(key=lambda it: it["rect"].y1)
                category = candidates[-1]["text"].strip()

    intro_top = page_height
    for item in items:
        if (item["kind"] == "text" and item.get("italic")
                and "Times" in item.get("font", "") and item["rect"].width > 300):
            intro_top = item["rect"].y0
            break

    author = ""
    for item in items:
        if item is title_item or item["kind"] != "text":
            continue
        if len(item["lines"]) != 1:
            continue
        if not (11 <= item["size"] <= 13 and not item["bold"] and not item["italic"]):
            continue
        if "Arial" not in item.get("font", ""):
            continue
        text = item["text"].strip()
        if not text or len(text) > 100:
            continue
        if (item["rect"].y0 >= title_bottom - 5
                and item["rect"].y1 < intro_top
                and item["rect"].y0 < page_height * 0.45):
            author = text
            break

    return category, author


# ---------------------------------------------------------------------------
# Per-article processing
# ---------------------------------------------------------------------------
def process_article(doc: fitz.Document, article: dict, out_root: str, dpi: int) -> dict:
    pages = []
    for pno in range(article["start"] - 1, article["end"]):
        page = doc[pno]
        items = order_items(page_items(page), page.rect.width / 2.0)
        pages.append((pno, page, items))

    body_size = body_font_size(pages)

    folder = os.path.join(out_root, article["name"])
    image_dir = os.path.join(folder, "images")
    os.makedirs(image_dir, exist_ok=True)

    category = article.get("category", "")
    author = article.get("author", "")

    lines: list[str] = [f"# {article['title']}"]
    if category:
        lines.append(f"**Kategorie:** {category}")
        lines.append("")
    if author:
        lines.append(f"**Autor:** {author}")
        lines.append("")
    if not category and not author:
        lines.append("")

    # The italic standfirst on the first page is the article abstract.
    abstract_id = None
    if pages:
        for item in pages[0][2]:
            if (item["kind"] == "text" and item.get("italic")
                    and "Times" in item.get("font", "")
                    and item["rect"].width > 300):
                abstract_id = id(item)
                break

    figure_no = 0
    title_skipped = False
    author_skipped = False
    target_title = title_key(article["title"])
    paragraph_index = None  # index in ``lines`` of the last open paragraph
    para_page = None        # page / column where that paragraph started
    para_col = None
    illustration_since = False  # an image/table interrupted the open paragraph

    def append_paragraph(text: str, pno: int, col: int,
                         gap: float | None = None) -> None:
        """Append a paragraph, joining it to the previous one when it clearly
        continues it across a page break, a column break or an illustration.

        ``gap`` is the vertical distance (in points) between the previous text
        block and this one on the same page and in the same column. Text
        wrapped around an illustration is split into several blocks by the PDF
        extractor; those blocks touch each other, so a very small gap marks a
        continuation even when the next word is capitalised.
        """
        nonlocal paragraph_index, para_page, para_col, illustration_since
        if paragraph_index is not None:
            previous = lines[paragraph_index]
            core = previous.rstrip().rstrip("*").rstrip()
            terminal = ".!?:;…\"»)]”’"
            continuation = ((pno != para_page) or (col != para_col)
                            or illustration_since)
            tight = gap is not None and gap < 2.0
            if (core and core[-1] not in terminal
                    and (text[:1].islower() or continuation or tight)):
                if previous.endswith("-"):
                    if (text[:1].isdigit() or text[:1].isupper()
                            or "/" in previous or "/" in text):
                        joined = previous + text
                    else:
                        joined = previous[:-1] + text
                    lines[paragraph_index] = merge_emphasis(joined)
                else:
                    lines[paragraph_index] = merge_emphasis(
                        previous + " " + text)
                para_page, para_col, illustration_since = pno, col, False
                return
        lines.append(merge_emphasis(text))
        lines.append("")
        paragraph_index = len(lines) - 2
        para_page, para_col, illustration_since = pno, col, False

    code_buffer: list[str] = []

    def flush_code() -> None:
        nonlocal paragraph_index, illustration_since
        if code_buffer:
            lines.append("```")
            lines.append("\n".join(code_buffer))
            lines.append("```")
            lines.append("")
            code_buffer.clear()
            paragraph_index = None
            illustration_since = False

    fn_ids: dict = {}
    fn_defs: list = []
    fn_counter = [0]

    def resolve_refs(text: str, pno: int) -> str:
        """Replace page-local footnote markers by unique Markdown labels."""
        def repl(match: re.Match) -> str:
            key = (pno, match.group(1))
            if key not in fn_ids:
                fn_counter[0] += 1
                fn_ids[key] = fn_counter[0]
            return f"[^{fn_ids[key]}]"
        return re.sub(r"\[\[FN:(\d+)\]\]", repl, text)

    # Last text block seen, used to detect blocks that the PDF extractor split
    # only because the text wraps around an illustration.
    prev_text_rect = None
    prev_text_page = None
    prev_text_col = None

    for _pno, page, items in pages:
        for item in items:
            mid = page.rect.width / 2
            col = 0 if (item["rect"].x0 + item["rect"].x1) / 2 < mid else 1
            gap = None
            if (prev_text_rect is not None and prev_text_page == _pno
                    and prev_text_col == col):
                gap = item["rect"].y0 - prev_text_rect.y1
            if item["kind"] == "code":
                code_buffer.append(item["text"])
                prev_text_rect = None
                continue
            flush_code()

            if item["kind"] == "footnote":
                key = (_pno, item["number"])
                if key not in fn_ids:
                    fn_counter[0] += 1
                    fn_ids[key] = fn_counter[0]
                fn_defs.append((fn_ids[key], item["text"]))
                paragraph_index = None
                illustration_since = False
                prev_text_rect = None
                continue

            if item["kind"] == "math":
                latex = item["latex"]
                if _MATH_ENGINE == "pix2tex":
                    try:
                        guess = ocr_math(page, item["rect"])
                        if guess:
                            latex = guess
                    except Exception:  # keep the heuristic result on failure
                        pass
                lines.append(f"$$ {latex} $$")
                lines.append("")
                paragraph_index = None
                illustration_since = False
                prev_text_rect = None
                continue

            if item["kind"] == "list":
                lines.append(resolve_refs(item["text"], _pno))
                lines.append("")
                paragraph_index = None
                illustration_since = False
                prev_text_rect = None
                continue

            if item["kind"] == "table":
                lines.append(item["markdown"])
                lines.append("")
                for caption in sorted(item.get("captions", []),
                                      key=lambda c: c["rect"].y0):
                    lines.append(caption["text"])
                    lines.append("")
                # A table can interrupt a paragraph: keep it open so the rest
                # of the sentence, if any, is still joined.
                illustration_since = True
                prev_text_rect = None
                continue

            if item["kind"] == "figure":
                figure_no += 1
                filename = f"fig_{figure_no:02d}.png"
                pix = render_figure(page, item["rect"], dpi)
                pix.save(os.path.join(image_dir, filename))
                lines.append(f"![{filename}](images/{filename})")
                lines.append("")
                for caption in sorted(item.get("captions", []),
                                      key=lambda c: c["rect"].y0):
                    lines.append(caption["text"])
                    lines.append("")
                # An illustration can interrupt a paragraph: keep it open.
                illustration_since = True
                prev_text_rect = None
                continue

            text = resolve_refs(item["text"], _pno)
            is_heading = item["bold"] and item["size"] >= body_size + 1.5
            is_subheading = (not is_heading and item["bold"]
                             and "Arial" in item.get("font", "")
                             and len(item.get("lines", [])) == 1
                             and len(text) <= 80)

            if id(item) == abstract_id:
                lines.append("> " + text)
                lines.append("")
                paragraph_index = None
                illustration_since = False
                continue
            if (is_heading and not title_skipped
                    and target_title and target_title in title_key(text)):
                title_skipped = True
                continue
            if not is_heading and not author_skipped and author and text.strip() == author:
                author_skipped = True
                continue
            if is_heading:
                lines.append("## " + re.sub(r"\*+", "", text))
                lines.append("")
                paragraph_index = None
                illustration_since = False
                prev_text_rect = None
            elif is_subheading:
                lines.append("### " + re.sub(r"\*+", "", text))
                lines.append("")
                paragraph_index = None
                illustration_since = False
                prev_text_rect = None
            else:
                append_paragraph(text, _pno, col, gap)
                prev_text_rect = item["rect"]
                prev_text_page = _pno
                prev_text_col = col

    flush_code()

    if fn_defs:
        lines.append("")
        for label, definition in sorted(fn_defs):
            lines.append(f"[^{label}]: {definition}")
            lines.append("")

    markdown = "\n".join(lines).strip() + "\n"
    md_path = os.path.join(folder, article["name"] + ".md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    return {"figures": figure_no, "md": md_path, "images": figure_no}


# ---------------------------------------------------------------------------
# Translation engines
# ---------------------------------------------------------------------------
IMAGE_REF_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)$")
META_RE = re.compile(r"^\*\*(Kategorie|Autor):\*\*\s*(.*)$")
ORDERED_ITEM_RE = re.compile(r"^(\d{1,2}[.)])\s+(.*)$")
LEADING_NUM_RE = re.compile(r"^(\d{1,2})\s+")
LINK_RE = re.compile(r"\[([^\]]*)\]\(((?:[^()]|\([^)]*\))*)\)")
INLINE_RE = re.compile(
    r"(?P<code>`[^`]*`)"
    r"|(?P<fn>\[\^[^\]]+\])"
    r"|(?P<bi>\*\*\*[^*]+\*\*\*)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<ital>\*[^*]+\*)"
    r"|(?P<link>\[[^\]]*\]\((?:[^()]|\([^)]*\))*\))")
FN_DEF_RE = re.compile(r"^(\[\^[^\]]+\]:\s*)(.*)$")
TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]+\|?\s*$")

# Language specific labels for the article metadata lines (bold to stand out).
META_LABELS = {
    "de": {"Kategorie": "**Kategorie:**", "Autor": "**Autor:**"},
    "fr": {"Kategorie": "**Catégorie :**", "Autor": "**Auteur :**"},
    "en": {"Kategorie": "**Category:**", "Autor": "**Author:**"},
}


def meta_label(kind: str, lang: str) -> str:
    return META_LABELS.get(lang, {}).get(kind, f"**{kind}:**")


class QuotaExceededError(RuntimeError):
    """Raised when a translation provider reports an exhausted free quota."""


# Characters / requests actually accepted by the provider during this run.
_USAGE = {"requests": 0, "characters": 0}


def usage_snapshot() -> dict:
    return dict(_USAGE)


def _read_key(path: str, label: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{label} key file not found: {path}")
    with open(path, encoding="utf-8") as handle:
        key = handle.read().strip()
    if not key:
        raise ValueError(f"{label} key file is empty: {path}")
    return key


def _read_azure_params(params_file: str) -> dict:
    config: dict = {}
    if not os.path.isfile(params_file):
        raise FileNotFoundError(f"Azure parameters file not found: {params_file}")
    with open(params_file, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip()
            try:
                config[name] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                config[name] = value.strip("'\"")
    if "endpoint" not in config:
        raise ValueError(f"'endpoint' missing from {params_file}")
    return config


def build_translation_config(engine: str, azure_params: str = "",
                             azure_key: str = "", *, to_lang: str | None = None,
                             deepl_key_file: str = "deeplkey.txt",
                             deepl_key_files: list[str] | None = None,
                             libre_url: str | None = None,
                             libre_key_file: str | None = None) -> dict:
    """Build the settings for the requested translation engine."""
    engine = engine.lower()
    config: dict = {"_engine": engine, "from_lang": "de",
                    "to_lang": to_lang or "fr"}
    if engine == "azure":
        config["endpoint"] = AZURE_ENDPOINT
        config["location"] = AZURE_LOCATION
        if azure_params and os.path.isfile(azure_params):
            config.update(_read_azure_params(azure_params))
        config["_key"] = _read_key(azure_key, "Azure")
        config["_max_items"], config["_max_chars"] = MAX_BATCH_ITEMS, MAX_BATCH_CHARS
        config["_label"] = "Azure Translator"
        if to_lang:
            config["to_lang"] = to_lang
    elif engine == "deepl":
        key_files = deepl_key_files or [deepl_key_file]
        keys = [_read_key(path, "DeepL") for path in key_files]
        config["_keys"] = keys
        config["_key"] = keys[0]
        config["_key_index"] = 0
        free = any(key.endswith(":fx") for key in keys)
        config["endpoint"] = ("https://api-free.deepl.com/v2/translate" if free
                              else "https://api.deepl.com/v2/translate")
        config["_max_items"], config["_max_chars"] = 50, 120000
        config["_label"] = "DeepL"
    elif engine == "libre":
        config["endpoint"] = libre_url or "https://libretranslate.com/translate"
        if libre_key_file and os.path.isfile(libre_key_file):
            with open(libre_key_file, encoding="utf-8") as handle:
                config["_key"] = handle.read().strip()
        config["_max_items"], config["_max_chars"] = 50, 10000
        config["_label"] = "LibreTranslate"
    elif engine == "argos":
        try:
            import argostranslate.translate  # noqa: F401
        except ImportError as error:
            raise ValueError("argostranslate is not installed "
                             "(pip install argostranslate)") from error
        config["_max_items"], config["_max_chars"] = 100, 45000
        config["_label"] = "Argos Translate"
    else:
        raise ValueError(f"unknown translation engine: {engine}")
    return config


def _azure_translate(batch: list[str], config: dict) -> list[str]:
    global _last_request
    url = config["endpoint"].rstrip("/") + "/translate"
    params = {"api-version": "3.0", "from": config.get("from_lang", "de"),
              "to": config.get("to_lang", "fr")}
    headers = {"Ocp-Apim-Subscription-Key": config["_key"],
               "Content-Type": "application/json"}
    if config.get("location"):
        headers["Ocp-Apim-Subscription-Region"] = config["location"]
    body = [{"text": text} for text in batch]

    last_error = "unknown error"
    for attempt in range(8):
        delay = MIN_REQUEST_INTERVAL - (time.time() - _last_request)
        if delay > 0:
            time.sleep(delay)
        response = requests.post(url, params=params, headers=headers,
                                 data=json.dumps(body), timeout=60)
        _last_request = time.time()
        if response.status_code == 200:
            return [item["translations"][0]["text"] for item in response.json()]

        code, message = None, response.text[:200]
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            message = error.get("message", message)
        except (ValueError, AttributeError):
            pass
        last_error = f"HTTP {response.status_code} (code {code}): {message}"

        if response.status_code == 403 and str(code) == "403001":
            raise QuotaExceededError(
                "quota gratuit Azure Translator épuisé (403 / 403001): " + message)
        if response.status_code == 429 or response.status_code >= 500:
            wait = response.headers.get("Retry-After")
            wait = int(wait) if wait else min(5 * 2 ** attempt, 60)
            print(f"      ... Azure busy (HTTP {response.status_code}), "
                  f"waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        break
    raise RuntimeError(f"Azure translation failed ({last_error})")


def _deepl_translate(batch: list[str], config: dict) -> list[str]:
    global _last_request
    keys = config.get("_keys") or [config["_key"]]
    body = {"text": list(batch), "target_lang": config.get("to_lang", "fr").upper()}
    if config.get("from_lang"):
        body["source_lang"] = config["from_lang"].upper()

    while True:
        index = config.get("_key_index", 0)
        key = keys[index]
        endpoint = ("https://api-free.deepl.com/v2/translate"
                    if key.endswith(":fx") else
                    "https://api.deepl.com/v2/translate")
        headers = {"Authorization": f"DeepL-Auth-Key {key}",
                   "Content-Type": "application/json"}
        rotate = False
        last_error = "unknown error"
        for attempt in range(6):
            delay = MIN_REQUEST_INTERVAL - (time.time() - _last_request)
            if delay > 0:
                time.sleep(delay)
            response = requests.post(endpoint, headers=headers,
                                     json=body, timeout=60)
            _last_request = time.time()
            if response.status_code == 200:
                return [item["text"] for item in response.json()["translations"]]
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if (response.status_code in (401, 403, 456)
                    or "quota" in response.text.lower()):
                rotate = True  # exhausted / invalid key: try the next one
                break
            if response.status_code == 429 or response.status_code >= 500:
                wait = response.headers.get("Retry-After")
                wait = int(wait) if wait else min(5 * 2 ** attempt, 60)
                print(f"      ... DeepL busy (HTTP {response.status_code}), "
                      f"waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            break
        if rotate and index + 1 < len(keys):
            config["_key_index"] = index + 1
            print(f"      ... clé DeepL #{index + 1} indisponible, "
                  f"bascule sur la suivante", file=sys.stderr)
            continue
        if rotate:
            raise QuotaExceededError(
                "aucune clé DeepL disponible (quota/clé invalide): " + last_error)
        raise RuntimeError(f"DeepL translation failed ({last_error})")


def _libre_translate(batch: list[str], config: dict) -> list[str]:
    global _last_request
    body = {"q": list(batch), "source": config.get("from_lang", "de"),
            "target": config.get("to_lang", "fr"), "format": "text"}
    if config.get("_key"):
        body["api_key"] = config["_key"]

    last_error = "unknown error"
    for attempt in range(6):
        delay = MIN_REQUEST_INTERVAL - (time.time() - _last_request)
        if delay > 0:
            time.sleep(delay)
        response = requests.post(config["endpoint"], json=body, timeout=60)
        _last_request = time.time()
        if response.status_code == 200:
            result = response.json()["translatedText"]
            return result if isinstance(result, list) else [result]
        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        if response.status_code == 429:
            wait = response.headers.get("Retry-After")
            wait = int(wait) if wait else min(5 * 2 ** attempt, 60)
            print(f"      ... LibreTranslate busy (HTTP 429), waiting {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        break
    raise RuntimeError(f"LibreTranslate translation failed ({last_error})")


def _argos_translate(batch: list[str], config: dict) -> list[str]:
    import argostranslate.translate as argos
    source, target = config.get("from_lang", "de"), config.get("to_lang", "fr")
    return [argos.translate(text, source, target) for text in batch]


def _translate_batch(batch: list[str], config: dict) -> list[str]:
    engines = {"azure": _azure_translate, "deepl": _deepl_translate,
               "libre": _libre_translate, "argos": _argos_translate}
    return engines[config["_engine"]](batch, config)


def translate_texts(texts: list[str], config: dict) -> list[str]:
    """Translate a list of strings, batching according to the engine limits."""
    max_items = config.get("_max_items", MAX_BATCH_ITEMS)
    max_chars = config.get("_max_chars", MAX_BATCH_CHARS)
    translated: list[str] = []
    batch: list[str] = []
    batch_chars = 0
    for text in texts:
        if batch and (len(batch) >= max_items
                      or batch_chars + len(text) > max_chars):
            translated.extend(_translate_batch(batch, config))
            _USAGE["requests"] += 1
            _USAGE["characters"] += sum(len(item) for item in batch)
            batch, batch_chars = [], 0
        batch.append(text)
        batch_chars += len(text)
    if batch:
        translated.extend(_translate_batch(batch, config))
        _USAGE["requests"] += 1
        _USAGE["characters"] += sum(len(item) for item in batch)
    return translated


def _append_translatable(segments: list[tuple], text: str) -> None:
    """Append translatable text, keeping leading/trailing spaces literal."""
    core = text.strip()
    if not core:
        segments.append(("lit", text))
        return
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    if lead:
        segments.append(("lit", lead))
    segments.append(("tr", core))
    if trail:
        segments.append(("lit", trail))


def inline_segments(text: str) -> list[tuple]:
    """Split text into translatable parts, links, emphasis and inline code.

    Bold/italic text is emitted as a ("bold"/"italic"/"bi", inner) segment so
    its wording gets translated while the markers are always restored verbatim.
    """
    segments: list[tuple] = []
    last = 0
    for match in INLINE_RE.finditer(text):
        if match.start() > last:
            _append_translatable(segments, text[last:match.start()])
        if match.group("code") or match.group("fn"):
            # Inline code and footnote references are kept verbatim.
            segments.append(("lit", match.group(0)))
            last = match.end()
            continue
        marker = None
        if match.group("bi") is not None:
            marker, inner = "***", match.group("bi")[3:-3]
        elif match.group("bold") is not None:
            marker, inner = "**", match.group("bold")[2:-2]
        elif match.group("ital") is not None:
            marker, inner = "*", match.group("ital")[1:-1]
        if marker is not None:
            link = LINK_RE.match(inner)
            rest = inner[link.end():] if link else ""
            if link and not re.search(r"[A-Za-z0-9]", rest):
                # Emphasis around a link (optionally followed by punctuation).
                segments.append(("elink", link.group(1), link.group(2), marker))
                if rest:
                    segments.append(("lit", rest))
            else:
                segments.append(("bold" if marker == "**" else
                                 "bi" if marker == "***" else "italic", inner))
            last = match.end()
            continue
        link = LINK_RE.match(match.group("link"))  # Markdown link
        segments.append(("link", link.group(1), link.group(2)))
        last = match.end()
    if last < len(text):
        _append_translatable(segments, text[last:])
    return segments


def table_row_segments(line: str) -> list[tuple]:
    """Split a Markdown table row so that only the cell texts are translated."""
    content = line.strip()
    inner = content[1:-1] if content.startswith("|") else content
    segments: list[tuple] = [("lit", "| ")]
    for i, cell in enumerate(inner.split("|")):
        if i:
            segments.append(("lit", " | "))
        core = cell.strip()
        if core:
            segments.extend(inline_segments(core))
    segments.append(("lit", " |"))
    return segments


# TeX function names and units that must never be translated inside maths.
MATH_KEEP_WORDS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh",
    "arcsin", "arccos", "arctan", "log", "ln", "lg", "exp", "lim",
    "max", "min", "sup", "inf", "det", "dim", "mod", "gcd", "deg",
    "abs", "sgn", "ker", "arg", "const", "and", "or", "not", "if",
    "else", "for", "ohm", "mm", "cm", "km", "kg", "ms", "hz", "khz",
}

MATH_WORD_RE = re.compile(r"(?<![\\A-Za-z])([A-Za-zÄÖÜäöüß]{3,})(?![A-Za-z])")

# Groups that hold identifiers, units or pre-formatted labels: kept verbatim.
MATH_PROTECT_RE = re.compile(
    r"(?:_|\^|\\text(?:bf|it|rm|sf|tt)?|\\mathrm|\\operatorname"
    r"|\\mathbf|\\mathit|\\mathsf)\s*\{")


def _brace_span(text: str, start: int) -> int:
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


def _protected_spans(latex: str) -> list[tuple[int, int]]:
    spans = []
    for match in MATH_PROTECT_RE.finditer(latex):
        start = latex.index("{", match.start())
        spans.append((start, _brace_span(latex, start)))
    return spans


def math_phrases(latex: str) -> list[tuple[int, int, str]]:
    """Return the plain-language phrases of a maths expression.

    A phrase is a run of words separated by spaces only (``Impulse pro
    Umdrehung``); subscripts, superscripts and ``\\text``-like groups are
    skipped because they hold identifiers or already-formatted labels.
    """
    protected = _protected_spans(latex)

    def is_protected(position: int) -> bool:
        return any(start <= position < end for start, end in protected)

    phrases: list[tuple[int, int, str]] = []
    for match in MATH_WORD_RE.finditer(latex):
        word = match.group(1)
        if is_protected(match.start()):
            continue
        if word.isupper() or any(char.isdigit() for char in word):
            continue
        if word.lower() in MATH_KEEP_WORDS:
            continue
        if not re.search(r"[aeiouyäöü]", word.lower()):
            continue
        if phrases and latex[phrases[-1][1]:match.start()].strip() == "":
            start, _end, text = phrases[-1]
            phrases[-1] = (start, match.end(), latex[start:match.end()])
        else:
            phrases.append((match.start(), match.end(), word))
    return phrases


def translate_math_lines(lines: list[str], config: dict) -> None:
    """Translate the words inside display-maths lines, in place.

    German quantity names (``Drehwinkel``, ``Impulse pro Umdrehung``) are
    common in formulas; they are translated and wrapped in ``\\text{…}`` so
    they typeset upright in the target language.
    """
    indices = [index for index, line in enumerate(lines)
               if line.strip().startswith("$$") and line.strip().endswith("$$")
               and len(line.strip()) > 4]
    if not indices:
        return

    texts: list[str] = []
    for index in indices:
        for _start, _end, phrase in math_phrases(lines[index]):
            if phrase not in texts:
                texts.append(phrase)
    if not texts:
        return

    translated = translate_texts(texts, config)
    mapping = {}
    for source, target in zip(texts, translated):
        target = " ".join(target.split()).strip(" .")
        target = re.sub(r"([%&#_])", r"\\\1", target)
        if target and target.casefold() != source.casefold():
            mapping[source] = target
    if not mapping:
        return

    for index in indices:
        line = lines[index]
        pieces: list[str] = []
        last = 0
        for start, end, phrase in math_phrases(line):
            if phrase not in mapping:
                continue
            pieces.append(line[last:start])
            pieces.append("\\text{" + mapping[phrase] + "}")
            last = end
        pieces.append(line[last:])
        lines[index] = "".join(pieces)


def translate_markdown(md_path: str, config: dict, force: bool = False) -> str:
    """Write a translated copy of ``md_path`` next to it.

    The file is split into segments: literal Markdown (markers, image
    references, links' URLs, table pipes) is copied verbatim while prose,
    link anchors and table cells are translated. An existing translation is
    reused unless ``force`` is set.
    """
    lang = config.get("to_lang", "fr")
    out_path = md_path[:-3] + f".{lang}.md"
    if os.path.isfile(out_path) and not force:
        return out_path

    with open(md_path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")

    # Each unit is (line index, [segments]); a segment is one of
    # ("lit", text), ("tr", text) or ("link", anchor, url).
    units: list[tuple[int, list[tuple]]] = []
    in_code = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped or IMAGE_REF_RE.match(stripped):
            continue
        if stripped.startswith("$$"):  # display maths: keep verbatim
            continue
        footnote = FN_DEF_RE.match(stripped)
        if footnote:
            units.append((index, [("lit", footnote.group(1))]
                          + inline_segments(footnote.group(2))))
            continue
        if TABLE_ROW_RE.match(stripped):
            if TABLE_SEP_RE.match(stripped):
                units.append((index, [("lit", line)]))
            else:
                units.append((index, table_row_segments(line)))
            continue
        ordered = ORDERED_ITEM_RE.match(stripped)
        if ordered:
            units.append((index, [("lit", ordered.group(1) + " ")]
                          + inline_segments(ordered.group(2))))
            continue
        lead = LEADING_NUM_RE.match(stripped)
        if lead:
            # Keep a leading line/part number verbatim (avoid "4 abgefragt." ->
            # "4. ..." turning a plain reference into a list item).
            units.append((index, [("lit", lead.group(1) + " ")]
                          + inline_segments(stripped[lead.end():])))
            continue
        meta = META_RE.match(stripped)
        if meta:
            kind, value = meta.group(1), meta.group(2).strip()
            label = meta_label(kind, lang)
            if kind == "Autor":
                # Never translate a person's name: keep the whole line.
                units.append((index, [("lit", f"{label} {value}".strip())]))
            else:
                units.append((index, [("lit", label + " "), ("tr", value)]))
            continue
        quote = BLOCKQUOTE_RE.match(stripped)
        if quote:
            units.append((index, [("lit", "> ")] + inline_segments(quote.group(1))))
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            units.append((index, [("lit", heading.group(1) + " ")]
                          + inline_segments(heading.group(2))))
        else:
            units.append((index, inline_segments(stripped)))

    if not units:
        return md_path

    # Collect every translatable string (prose, anchors, bold, cells).
    translatable: list[str] = []
    for _index, segments in units:
        for segment in segments:
            if segment[0] in ("tr", "link", "bold", "italic", "bi", "elink"):
                translatable.append(segment[1])
    translated = translate_texts(translatable, config) if translatable else []

    markers = {"bold": "**", "italic": "*", "bi": "***"}
    pointer = 0
    for index, segments in units:
        parts: list[str] = []
        for segment in segments:
            if segment[0] == "lit":
                parts.append(segment[1])
            elif segment[0] == "tr":
                parts.append(translated[pointer])
                pointer += 1
            elif segment[0] in markers:
                mark = markers[segment[0]]
                parts.append(f"{mark}{translated[pointer]}{mark}")
                pointer += 1
            elif segment[0] == "elink":
                mark = segment[3]
                parts.append(f"[{mark}{translated[pointer]}{mark}]({segment[2]})")
                pointer += 1
            else:  # link
                parts.append(f"[{translated[pointer]}]({segment[2]})")
                pointer += 1
        lines[index] = "".join(parts)

    # Formulas are copied verbatim, but their plain words (often German
    # quantity names) are translated and set upright.
    translate_math_lines(lines, config)

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def translate_existing(out_root: str, name: str | None, config: dict,
                       force: bool) -> int:
    """Translate the German Markdown files already present under ``out_root``."""
    lang = config.get("to_lang", "fr")
    if name:
        roots = [os.path.join(out_root, name)]
    elif os.path.isdir(out_root):
        roots = [os.path.join(out_root, d) for d in sorted(os.listdir(out_root))]
    else:
        roots = []

    documents: list[str] = []
    for root in roots:
        article_dir = os.path.join(root, "articles")
        if not os.path.isdir(article_dir):
            continue
        for folder in sorted(os.listdir(article_dir)):
            folder_path = os.path.join(article_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            for filename in sorted(os.listdir(folder_path)):
                if filename.endswith(".md") and not filename.endswith(f".{lang}.md"):
                    documents.append(os.path.join(folder_path, filename))

    if not documents:
        print(f"No German .md file found under {out_root!r}.", file=sys.stderr)
        return 1

    print(f"Translating {len(documents)} document(s): de -> {lang} "
          f"({config.get('_label', '')})\n")
    stopped = False
    for md_path in documents:
        out_path = md_path[:-3] + f".{lang}.md"
        if os.path.isfile(out_path) and not force:
            print(f"{os.path.basename(os.path.dirname(md_path))}: (déjà traduit)")
            continue
        before = usage_snapshot()["characters"]
        try:
            translated = translate_markdown(md_path, config, force=force)
            sent = usage_snapshot()["characters"] - before
            print(f"{os.path.basename(os.path.dirname(md_path))}: {translated} "
                  f"({sent} caractères)")
        except QuotaExceededError as error:
            print(f"QUOTA ÉPUISÉ : {error}", file=sys.stderr)
            print("-> arrêt des traductions restantes.", file=sys.stderr)
            stopped = True
            break
        except RuntimeError as error:
            print(f"traduction échouée : {error}", file=sys.stderr)

    used = usage_snapshot()
    print(f"\n{config.get('_label', 'Translation')} : {used['requests']} "
          f"requête(s), {used['characters']} caractères envoyés.")
    return 0 if not stopped else 1


def default_pdf() -> str:
    candidates = sorted(name for name in os.listdir(".")
                        if name.lower().endswith(".pdf"))
    if len(candidates) > 1:
        print(f"Several PDFs found, using {candidates[0]!r}. "
              f"Use --pdf to pick another one:", file=sys.stderr)
        for name in candidates:
            print(f"   - {name}", file=sys.stderr)
    return candidates[0] if candidates else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", default=None,
                        help="source PDF (default: the only *.pdf in the folder)")
    parser.add_argument("--out", default="output",
                        help="output root folder (default: ./output)")
    parser.add_argument("--name", default=None,
                        help="magazine folder name (default: from the PDF file name)")
    parser.add_argument("--min-page", type=int, default=4,
                        help="first page (1-based) that is still an article")
    parser.add_argument("--dpi", type=int, default=300,
                        help="resolution used to re-assemble figures")
    parser.add_argument("--math-engine", default="heuristic",
                        choices=["auto", "heuristic", "pix2tex"],
                        help="maths formula extraction (default: heuristic)")
    parser.add_argument("--translate", action="store_true",
                        help="also write translated Markdown")
    parser.add_argument("--translate-only", action="store_true",
                        help="only translate the existing German .md files "
                             "(no PDF/image regeneration)")
    parser.add_argument("--engine", default="azure",
                        choices=["azure", "deepl", "argos", "libre"],
                        help="translation engine (default: azure)")
    parser.add_argument("--to", default=None,
                        help="target language for --translate (default: de->fr)")
    parser.add_argument("--force-translate", action="store_true",
                        help="re-translate even if the output file already exists")
    parser.add_argument("--azure-params", default=None,
                        help="optional Azure parameters file (endpoint/location "
                             "have built-in defaults)")
    parser.add_argument("--azure-key", default="azurekey.txt",
                        help="file containing the Azure subscription key")
    parser.add_argument("--deepl-key", nargs="+", default=["deeplkey.txt"],
                        metavar="FILE",
                        help="DeepL API key file(s); several may be given for "
                             "automatic fallback (default: deeplkey.txt)")
    parser.add_argument("--libre-url", default=None,
                        help="LibreTranslate endpoint URL")
    parser.add_argument("--libre-key", default="librekey.txt",
                        help="file containing the LibreTranslate API key (optional)")
    args = parser.parse_args(argv)

    trans_config = None
    if args.translate or args.translate_only:
        try:
            trans_config = build_translation_config(
                args.engine, args.azure_params, args.azure_key, to_lang=args.to,
                deepl_key_files=args.deepl_key, libre_url=args.libre_url,
                libre_key_file=args.libre_key)
        except (FileNotFoundError, ValueError) as error:
            print(f"Translation disabled: {error}", file=sys.stderr)
            return 1

    if args.translate_only:
        return translate_existing(args.out, args.name, trans_config,
                                  args.force_translate)

    pdf_path = args.pdf or default_pdf()
    if not pdf_path or not os.path.isfile(pdf_path):
        print("No PDF found. Use --pdf <file>.", file=sys.stderr)
        return 1

    try:
        math_engine = set_math_engine(args.math_engine)
    except ValueError as error:
        print(f"Invalid --math-engine: {error}", file=sys.stderr)
        return 1

    doc = fitz.open(pdf_path)
    articles = find_articles(doc, args.min_page)
    if not articles:
        print("No article found in the table of contents.", file=sys.stderr)
        return 1

    magazine = args.name or re.sub(r'[\\/:*?"<>|\s]+', "_",
                                   os.path.splitext(os.path.basename(pdf_path))[0]).strip("_")
    magazine_dir = os.path.join(args.out, magazine)
    pdf_dir = os.path.join(magazine_dir, "pdf")
    art_dir = os.path.join(magazine_dir, "articles")

    print(f"Source      : {pdf_path} ({doc.page_count} pages)")
    print(f"Articles    : {len(articles)}")
    print(f"Output      : {magazine_dir}/")
    print(f"Maths       : {math_engine}")
    if trans_config:
        print(f"Translation : de -> {trans_config.get('to_lang', 'fr')} "
              f"({trans_config.get('_label', '')})")
    print()

    for article in articles:
        article["category"], article["author"] = detect_metadata(doc, article)

    split_pdfs(doc, articles, pdf_dir)

    translation_stopped = False
    for article in articles:
        info = process_article(doc, article, art_dir, args.dpi)
        print(f"[{article['name']}]")
        print(f"    pages   : {article['start']}-{article['end']}")
        print(f"    pdf     : {article['pdf']}")
        print(f"    markdown: {info['md']}")
        print(f"    images  : {info['figures']}")
        if article["category"] or article["author"]:
            print(f"    méta    : Kategorie={article['category']!r} "
                  f"Autor={article['author']!r}")
        if not trans_config or translation_stopped:
            continue
        existing = info["md"][:-3] + f".{trans_config.get('to_lang', 'fr')}.md"
        if os.path.isfile(existing) and not args.force_translate:
            print(f"    traduit : {existing} (déjà traduit)")
            continue
        before = usage_snapshot()["characters"]
        try:
            translated = translate_markdown(info["md"], trans_config,
                                            force=args.force_translate)
            sent = usage_snapshot()["characters"] - before
            print(f"    traduit : {translated} ({sent} caractères)")
        except QuotaExceededError as error:
            print(f"    QUOTA ÉPUISÉ : {error}", file=sys.stderr)
            print("    -> arrêt des traductions pour les articles restants.",
                  file=sys.stderr)
            translation_stopped = True
        except RuntimeError as error:
            print(f"    traduction échouée : {error}", file=sys.stderr)

    if trans_config:
        used = usage_snapshot()
        print(f"\n{trans_config.get('_label', 'Translation')} : "
              f"{used['requests']} requête(s), {used['characters']} caractères envoyés.")

    doc.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

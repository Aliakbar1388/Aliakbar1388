#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2pdf_fa — تبدیل جزوهٔ متنی (خروجی NotebookLM / Google Docs / Markdown) به PDF فارسی

قابلیت‌ها:
  • راست‌به‌چپ کامل با شکل‌دهی درست حروف (HarfBuzz) و فونت وزیرمتن
  • پشتیبانی از سرفصل، پاراگراف، لیست نقطه‌ای/شماره‌دار، جدول، نقل‌قول،
    بلوک کد، تصویر، خط جداکننده و پیوند
  • صفحهٔ جلد، فهرست مطالب با شماره صفحه، سرصفحه/پاصفحه
  • تبدیل خودکار اعداد به فارسی و پاک‌سازی نشانه‌های لاتک (مثل \\( \\) و \\frac)

نحوهٔ استفاده:
    python3 tools/md2pdf_fa.py jozve.md -o jozve.pdf
    python3 tools/md2pdf_fa.py notes.html -o jozve.pdf --title "جزوهٔ درس شبکه"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence

try:
    from fpdf import FPDF, XPos, YPos
    from fpdf.enums import TableBordersLayout, TextDirection
    from fpdf.fonts import FontFace
except ImportError:  # pragma: no cover
    sys.exit(
        "کتابخانهٔ fpdf2 نصب نیست. اجرا کنید:\n"
        "  pip install fpdf2 arabic-reshaper python-bidi uharfbuzz"
    )

VERSION = "1.0"

# ---------------------------------------------------------------------------
# پالت رنگ
# ---------------------------------------------------------------------------


def rgb(hexcode: str) -> tuple[int, int, int]:
    hexcode = hexcode.lstrip("#")
    return tuple(int(hexcode[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@dataclass(frozen=True)
class Palette:
    ink: tuple[int, int, int] = rgb("#1B1F24")           # متن اصلی
    muted: tuple[int, int, int] = rgb("#6B7280")         # متن کم‌رنگ
    primary: tuple[int, int, int] = rgb("#1F4E79")       # آبی سرفصل‌ها
    accent: tuple[int, int, int] = rgb("#C2410C")        # نارنجی تأکیدی
    line: tuple[int, int, int] = rgb("#D6DBE1")          # خطوط
    fill: tuple[int, int, int] = rgb("#F4F6F8")          # پس‌زمینهٔ کادر
    quote_fill: tuple[int, int, int] = rgb("#FBF6EE")    # پس‌زمینهٔ نقل‌قول
    code_fill: tuple[int, int, int] = rgb("#F3F4F6")     # پس‌زمینهٔ کد


PALETTE = Palette()

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
SUPERSCRIPT = str.maketrans("0123456789+-()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾ⁿ")


def fa_num(value: object) -> str:
    """ارقام لاتین را به ارقام فارسی تبدیل می‌کند."""
    return str(value).translate(FA_DIGITS)


# ---------------------------------------------------------------------------
# پاک‌سازی متن و نرمال‌سازی نشانه‌گذاری درون‌خطی
# ---------------------------------------------------------------------------

LATEX_MAP = {
    r"\times": "×",
    r"\cdot": "·",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\leftarrow": "←",
    r"\leftrightarrow": "↔",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\infty": "∞",
    r"\pm": "±",
    r"\mp": "∓",
    r"\degree": "°",
    r"\deg": "°",
    r"\percent": "٪",
    r"\%": "٪",
    r"\&": "&",
    r"\#": "#",
    r"\_": "_",
    r"\{": "{",
    r"\}": "}",
    r"\$": "$",
    r"\,": "،",
    r"\;": " ",
    r"\:": " ",
    r"\ ": " ",
    r"\quad": " ",
    r"\qquad": "  ",
    r"\ldots": "…",
    r"\dots": "…",
    r"\epsilon": "ε",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\sigma": "σ",
    r"\phi": "φ",
    r"\omega": "ω",
    r"\Omega": "Ω",
    r"\Delta": "Δ",
    r"\Sigma": "Σ",
    r"\sum": "∑",
    r"\int": "∫",
    r"\sqrt": "√",
}

LATEX_FONT_CMDS = re.compile(r"\\(?:text|mathrm|mathbf|mathit|operatorname|mbox)\{([^{}]*)\}")
LATEX_FRAC = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
LATEX_SQRT = re.compile(r"\\sqrt\{([^{}]*)\}")
LATEX_ENV = re.compile(r"\\(?:begin|end)\{[^{}]*\}")
LATEX_LEFTOVER_CMD = re.compile(r"\\[A-Za-z]+")


def clean_latex(text: str) -> str:
    """نشانه‌های لاتک را به معادل خوانا تبدیل می‌کند."""
    text = LATEX_FONT_CMDS.sub(r"\1", text)
    text = LATEX_FRAC.sub(r"(\1) ÷ (\2)", text)
    text = LATEX_SQRT.sub(r"√(\1)", text)
    text = LATEX_ENV.sub("", text)
    # دستورات شناخته‌شده
    for cmd, repl in sorted(LATEX_MAP.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(cmd, repl)
    # پرانتز/براکت ریاضی و علامت دلار
    text = re.sub(r"\\[()\[\]]", "", text)
    text = text.replace("$$", "").replace("$", "")
    text = re.sub(r"\^\{\s*([0-9n+\-()]+)\s*\}", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"_\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?=[^A-Za-z])", "", text)
    text = LATEX_LEFTOVER_CMD.sub("", text)
    return text


def normalize_inline(text: str, persian_digits: bool = True) -> str:
    """
    متن را برای موتور markdown کتابخانهٔ fpdf2 آماده می‌کند:
      • کد درون‌خطی (`x`) به متن ساده تبدیل می‌شود (fpdf2 از کد پشتیبانی نمی‌کند)
      • تأکید تک‌ستاره‌ای (*x*) به قالب دو‌زیرخطی (__x__) تبدیل می‌شود
      • نشانه‌های تک‌افتاده (مثل -- یا ~~) بی‌اثر می‌شوند
    """
    if not text:
        return ""

    # محافظت از * های ضرب و گلوله در متن (فاصله‌دار) پیش از تبدیل تأکید
    text = clean_latex(text)
    text = text.replace("\u200f", "").replace("\u200e", "")

    # کد درون‌خطی: فقط نشانهٔ بک‌تیک حذف می‌شود
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # تأکید تک‌ستاره‌ای و تک‌زیرخط → قالب پشتیبانی‌شده
    text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])", r"__\1__", text)
    text = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"__\1__", text)

    # نشانه‌های تکی که ممکن است اتفاقی باشند
    for marker in ("--", "~~"):
        if text.count(marker) % 2:
            text = text.replace(marker, "\\" + marker)

    if persian_digits:
        text = re.sub(r"\d+", lambda m: fa_num(m.group(0)), text)
    return text.strip()


# ---------------------------------------------------------------------------
# خواندن فایل ورودی: متن ساده/مارک‌داون یا HTML
# ---------------------------------------------------------------------------


class _HTMLToMarkdown(HTMLParser):
    """تبدیل سادهٔ HTML به مارک‌داون (برای خروجی Google Docs / NotebookLM)."""

    _BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "ul", "ol", "table"}
    _HEADINGS = {f"h{i}": i for i in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[str] = []
        self.in_pre = False
        self.in_table = False
        self.row: list[str] = []
        self.in_cell = False
        self._pending_prefix = ""
        self._skip_depth = 0

    # -- کمکی -------------------------------------------------------------
    def _newline(self, count: int = 2) -> None:
        tail = "".join(self.parts[-1:])
        if tail.endswith("\n\n"):
            return
        if tail.endswith("\n"):
            count = max(0, count - 1)
        self.parts.append("\n" * count)

    def _prefix(self) -> str:
        if self.in_table:
            return "| "
        if self.list_stack:
            kind = self.list_stack[-1]
            depth = max(0, len(self.list_stack) - 1)
            indent = "  " * depth
            if kind == "ul":
                return f"{indent}- "
            return f"{indent}1. "
        return ""

    # -- رویدادها ---------------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs or {})
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if tag == "pre":
            self.in_pre = True
            self._newline(2)
            self.parts.append("```\n")
            return
        if tag in self._HEADINGS:
            self._newline(2)
            self.parts.append("#" * self._HEADINGS[tag] + " ")
            return
        if tag in ("strong", "b"):
            self.parts.append("**")
            return
        if tag in ("em", "i"):
            self.parts.append("__")
            return
        if tag == "code" and not self.in_pre:
            self.parts.append("`")
            return
        if tag == "a":
            self.parts.append("[")
            return
        if tag == "br":
            self.parts.append("\n")
            return
        if tag in ("ul", "ol"):
            if not self.list_stack:
                self._newline(2)
            self.list_stack.append(tag)
            return
        if tag == "li":
            self._newline(1)
            self.parts.append(self._prefix())
            return
        if tag == "table":
            self.in_table = True
            self._newline(2)
            return
        if tag == "tr":
            self.row = []
            return
        if tag in ("td", "th"):
            self.in_cell = True
            return
        if tag in self._BLOCK:
            self._newline(2)
        if tag == "img":
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            if src:
                self._newline(2)
                self.parts.append(f"![{alt}]({src})")
                self._newline(2)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "pre":
            self.in_pre = False
            self._newline(1)
            self.parts.append("```")
            self._newline(2)
            return
        if tag in ("strong", "b"):
            self.parts.append("**")
            return
        if tag in ("em", "i"):
            self.parts.append("__")
            return
        if tag == "code" and not self.in_pre:
            self.parts.append("`")
            return
        if tag == "a":
            self.parts.append(")")
            return
        if tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack:
                self._newline(2)
            return
        if tag == "li":
            self._newline(1)
            return
        if tag in ("td", "th"):
            self.in_cell = False
            return
        if tag == "tr":
            if self.row:
                self.parts.append("\n| " + " | ".join(c.strip() for c in self.row))
                if len(self.parts) and self._table_header_needed():
                    self.parts.append("\n|" + "---|" * len(self.row))
            self.row = []
            return
        if tag == "table":
            self.in_table = False
            self._newline(2)
            return
        if tag in self._HEADINGS:
            self._newline(2)
            return
        if tag in self._BLOCK:
            self._newline(2)

    def _table_header_needed(self) -> bool:
        return sum(1 for p in self.parts if p.startswith("\n| ")) <= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self.in_cell:
            self.row.append(re.sub(r"\s+", " ", data))
            return
        if self.in_pre:
            self.parts.append(data)
            return
        data = re.sub(r"[ \t\r\f\v]+", " ", data)
        if not data.strip():
            if self.parts and not self.parts[-1].endswith((" ", "\n")):
                self.parts.append(" ")
            return
        self.parts.append(data)

    def result(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\n\n(\s*-\s)", r"\n\1", text)
        return text.strip() + "\n"


def read_source(path: Path) -> str:
    if str(path) == "-":  # خواندن از ورودی استاندارد (مثلاً متن چسبانده‌شده)
        raw = sys.stdin.read()
        path = Path("جزوه")
    else:
        raw = path.read_text(encoding="utf-8", errors="replace")
    head = raw.lstrip()[:400].lower()
    looks_html = (
        path.suffix.lower() in (".html", ".htm")
        or head.startswith("<!doctype html")
        or "<html" in head
        or "<body" in head
    )
    if looks_html:
        parser = _HTMLToMarkdown()
        parser.feed(raw)
        return parser.result()
    return raw


# ---------------------------------------------------------------------------
# تحلیل‌گر مارک‌داون
# ---------------------------------------------------------------------------


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    items: list[tuple[int, str, str | None]] = field(default_factory=list)  # (عمق، متن، شمارهٔ اصلی)
    rows: list[list[str]] = field(default_factory=list)
    lang: str = ""


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
UL_RE = re.compile(r"^(\s*)([-*+•▪◦])\s+(.*)$")
OL_RE = re.compile(r"^(\s*)(\d{1,3})\s*[.)\-٫]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$")
IMAGE_RE = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
FENCE_RE = re.compile(r"^\s*```\s*([\w+.#-]*)\s*$")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[match.end() :]


def split_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def parse_markdown(text: str) -> list[Block]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            joined = " ".join(part.strip() for part in paragraph).strip()
            if joined:
                blocks.append(Block("p", text=joined))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # بلوک کد
        fence = FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            lang = fence.group(1) or ""
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1  # بستن بلوک
            blocks.append(Block("code", text="\n".join(code_lines).strip("\n"), lang=lang))
            continue

        # خط خالی
        if not stripped:
            flush_paragraph()
            index += 1
            continue

        # سرفصل
        heading = HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            blocks.append(Block("h", text=heading.group(2), level=len(heading.group(1))))
            index += 1
            continue

        # خط جداکننده
        if HR_RE.match(stripped) and not stripped.startswith("|"):
            flush_paragraph()
            blocks.append(Block("hr"))
            index += 1
            continue

        # تصویر
        image = IMAGE_RE.match(stripped)
        if image:
            flush_paragraph()
            blocks.append(Block("image", text=image.group(2), lang=image.group(1)))
            index += 1
            continue

        # جدول
        if stripped.startswith("|") and index + 1 < len(lines) and TABLE_SEP_RE.match(lines[index + 1]):
            flush_paragraph()
            header = split_table_row(stripped)
            index += 2
            rows = [header]
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(split_table_row(lines[index]))
                index += 1
            blocks.append(Block("table", rows=rows))
            continue

        # نقل‌قول
        quote = QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            quote_lines = []
            while index < len(lines) and QUOTE_RE.match(lines[index]):
                quote_lines.append(QUOTE_RE.match(lines[index]).group(1))  # type: ignore[union-attr]
                index += 1
            blocks.append(Block("quote", text=" ".join(part for part in quote_lines if part).strip()))
            continue

        # لیست‌ها
        ul = UL_RE.match(line)
        ol = OL_RE.match(line)
        if ul or ol:
            flush_paragraph()
            items: list[tuple[int, str, str | None]] = []
            while index < len(lines):
                current = lines[index]
                if not current.strip():
                    # لیست را با خط خالی ادامه می‌دهیم اگر آیتم بعدی هم لیست باشد
                    nxt = lines[index + 1] if index + 1 < len(lines) else ""
                    if UL_RE.match(nxt) or OL_RE.match(nxt):
                        index += 1
                        continue
                    break
                bullet = UL_RE.match(current)
                numbered = OL_RE.match(current)
                if bullet:
                    depth = len(bullet.group(1).replace("\t", "    ")) // 2
                    items.append((depth, bullet.group(3).strip(), None))
                elif numbered:
                    depth = len(numbered.group(1).replace("\t", "    ")) // 2
                    items.append((depth, numbered.group(3).strip(), numbered.group(2)))
                else:
                    break
                index += 1
            kind = "ol" if any(item[2] for item in items) else "ul"
            blocks.append(Block(kind, items=items))
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    return blocks


# ---------------------------------------------------------------------------
# موتور تولید PDF
# ---------------------------------------------------------------------------


class Handout(FPDF):
    """سند PDF فارسی با چیدمان راست‌به‌چپ."""

    def __init__(
        self,
        *,
        meta: dict[str, str],
        fonts_dir: Path,
        base_size: float = 11.5,
        total_pages: int | None = None,
        persian_digits: bool = True,
        source_dir: Path | None = None,
    ) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.meta = meta
        self.fonts_dir = fonts_dir
        self.base = base_size
        self.total_pages = total_pages
        self.persian_digits = persian_digits
        self.source_dir = source_dir or Path.cwd()
        self.palette = PALETTE
        self.section_title = ""
        self.page_sections: dict[int, str] = {}
        self.suppress_header = False
        self.first_content_page = 1

        self.set_margins(left=18, top=18, right=18)
        self.set_auto_page_break(auto=True, margin=24)
        self.set_text_shaping(True, direction=TextDirection.RTL)
        self.MARKDOWN_LINK_UNDERLINE = True
        self.MARKDOWN_LINK_COLOR = self.palette.primary

        self._register_fonts()
        self._set_document_metadata()

    def _set_document_metadata(self) -> None:
        self.set_title(self.meta.get("title", "جزوه"))
        if self.meta.get("author"):
            self.set_author(self.meta["author"])
        if self.meta.get("course"):
            self.set_subject(self.meta["course"])
        self.set_creator("md2pdf_fa")
        self.set_lang("fa-IR")
        keywords = [self.meta.get(key, "") for key in ("course", "teacher")]
        keywords = [word for word in keywords if word]
        if keywords:
            self.set_keywords(", ".join(keywords))

    # -- امکانات پایه -----------------------------------------------------
    @property
    def content_left(self) -> float:
        return self.l_margin

    @property
    def content_right(self) -> float:
        return self.w - self.r_margin

    @property
    def content_width(self) -> float:
        return self.content_right - self.content_left

    @property
    def right_edge(self) -> float:
        """در چیدمان راست‌به‌چپ، نقطهٔ شروع متن (لبهٔ راست)."""
        return self.content_right

    def _register_fonts(self) -> None:
        regular = self.fonts_dir / "Vazirmatn-Regular.ttf"
        bold = self.fonts_dir / "Vazirmatn-Bold.ttf"
        medium = self.fonts_dir / "Vazirmatn-Medium.ttf"
        mono = self.fonts_dir / "JetBrainsMono-Regular.ttf"
        mono_bold = self.fonts_dir / "JetBrainsMono-Bold.ttf"
        fallback = self.fonts_dir / "DejaVuSans-Subset.ttf"
        fallback_bold = self.fonts_dir / "DejaVuSans-Bold-Subset.ttf"
        missing = [p.name for p in (regular, bold, mono) if not p.exists()]
        if missing:
            sys.exit(
                "فونت‌های لازم پیدا نشد: "
                + ", ".join(missing)
                + f"\nمسیر جست‌وجو: {self.fonts_dir}"
                + "\nبرای دریافت فونت‌ها: python3 notebooklm-to-pdf/fetch_fonts.py"
            )
        self.add_font("Vazir", "", str(regular))
        self.add_font("Vazir", "B", str(bold if bold.exists() else regular))
        self.add_font("Vazir", "I", str(medium if medium.exists() else regular))
        self.add_font("Mono", "", str(mono))
        self.add_font("Mono", "B", str(mono_bold if mono_bold.exists() else mono))
        # فونت پشتیبان برای نمادهایی که وزیرمتن ندارد (یونانی، فلش، ریاضی)
        self._fallback_families = ["Vazir"]
        if fallback.exists():
            self.add_font("Sym", "", str(fallback))
            self.add_font("Sym", "B", str(fallback_bold if fallback_bold.exists() else fallback))
            self._fallback_families.append("Sym")
        self.set_fallback_fonts(self._fallback_families, exact_match=False)

    # -- سرصفحه/پاصفحه ----------------------------------------------------
    def header(self) -> None:
        if self.page_no() < self.first_content_page or self.suppress_header:
            return
        self.set_font("Vazir", "", 8.5)
        self.set_text_color(*self.palette.muted)
        y = 11
        running = self.page_sections.get(self.page_no(), "")
        if running:
            self.set_xy(self.content_left, y)
            self.cell(0, 5, normalize_inline(running, self.persian_digits), align="R",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        title = self.meta.get("title", "")
        if title and title.strip() != running.strip():
            self.set_xy(self.content_left, y)
            self.cell(self.content_width, 5, normalize_inline(title, self.persian_digits), align="L")
        self.set_draw_color(*self.palette.line)
        self.set_line_width(0.2)
        self.line(self.content_left, y + 6, self.content_right, y + 6)
        self.set_y(16)
        self.set_text_color(*self.palette.ink)

    def footer(self) -> None:
        if self.suppress_header or self.page_no() <= self.first_content_page - 1:
            return
        self.set_y(-15)
        self.set_font("Vazir", "", 8.5)
        self.set_text_color(*self.palette.muted)
        label = f"صفحهٔ {fa_num(self.page_no())}"
        if self.total_pages:
            label += f" از {fa_num(self.total_pages)}"
        self.cell(0, 6, label, align="C")
        self.set_text_color(*self.palette.ink)

    # -- کمکی‌های چیدمان ---------------------------------------------------
    def set_base_font(self, size: float | None = None, style: str = "") -> None:
        self.set_font("Vazir", style, size if size is not None else self.base)
        self.set_text_color(*self.palette.ink)

    def space(self, amount: float) -> None:
        self.set_y(self.get_y() + amount)

    def ensure_space(self, height: float) -> None:
        if self.will_page_break(height):
            self.add_page()

    def rtl_cell(
        self,
        width: float,
        height: float,
        text: str,
        *,
        markdown: bool = False,
        align: str = "R",
        x: float | None = None,
    ) -> None:
        if x is not None:
            self.set_x(x)
        self.multi_cell(
            width,
            height,
            text,
            align=align,
            markdown=markdown,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    # -- عناصر سند ---------------------------------------------------------
    def draw_cover(self, meta: dict[str, str]) -> None:
        self.add_page()
        band = 62.0
        self.set_fill_color(*self.palette.primary)
        self.rect(0, 0, self.w, band, style="F")
        self.set_fill_color(*self.palette.accent)
        self.rect(0, band, self.w, 2.2, style="F")

        title = meta.get("title", "جزوهٔ درسی")
        subtitle = meta.get("subtitle", "")
        self.set_text_color(255, 255, 255)
        self.set_font("Vazir", "B", 23)
        self.set_xy(self.r_margin, band - 34)
        self.multi_cell(self.content_width, 12, title, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if subtitle:
            self.set_font("Vazir", "", 12.5)
            self.set_xy(self.r_margin, self.get_y() + 3)
            self.multi_cell(
                self.content_width, 8, subtitle, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )

        self.set_text_color(*self.palette.ink)
        self.set_y(band + 22)
        for label, key in (
            ("درس", "course"),
            ("استاد / مدرس", "teacher"),
            ("تهیه‌کننده", "author"),
            ("تاریخ", "date"),
        ):
            value = meta.get(key, "")
            if not value:
                continue
            self.set_font("Vazir", "B", 11)
            self.set_x(self.r_margin)
            self.cell(0, 8, f"{label}: {value}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font("Vazir", "", 11)
        if meta.get("source"):
            self.set_font("Vazir", "", 10)
            self.set_text_color(*self.palette.muted)
            self.set_xy(self.r_margin, self.h - 32)
            self.multi_cell(
                self.content_width,
                6,
                meta["source"],
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        self.set_text_color(*self.palette.ink)

    def render_toc(self, pdf_unused, outline: Sequence) -> None:
        """فهرست مطالب راست‌به‌چپ با نقطه‌چین و شمارهٔ صفحه."""
        self.suppress_header = True
        self.set_base_font(self.base + 3, "B")
        self.set_text_color(*self.palette.primary)
        self.set_xy(self.content_left, self.get_y() + 2)
        self.cell(0, 10, "فهرست مطالب", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*self.palette.accent)
        self.set_line_width(0.6)
        y = self.get_y() + 0.8
        self.line(self.right_edge - 26, y, self.right_edge, y)
        self.space(7)

        for section in outline:
            title = (section.name or "").strip()
            if not title:
                continue
            level = max(0, min(int(section.level), 2))
            page_label = fa_num(section.page_number) if self.persian_digits else str(section.page_number)
            indent = 5.0 * level
            line_h = 8.0 if level == 0 else 7.2

            style = "B" if level == 0 else ""
            size = self.base if level == 0 else self.base - 0.8
            self.set_font("Vazir", style, size)
            self.set_text_color(*(self.palette.ink if level < 2 else self.palette.muted))

            # سه‌بار تلاش برای جا شدن در یک سطر، با کوتاه کردن نقطه‌چین
            rendered = False
            for dots in (60, 40, 22, 10, 4, 0):
                line = " " * (level * 3)
                line += title
                if dots:
                    line += "  " + "·" * dots + "  "
                else:
                    line += "  "
                line += page_label
                if self.get_string_width(line) <= self.content_width - 0.5 or dots == 0:
                    self.ensure_space(line_h + 1.5)
                    self.set_x(self.content_left)
                    self.cell(
                        self.content_width,
                        line_h,
                        line,
                        align="R",
                        new_x=XPos.LMARGIN,
                        new_y=YPos.NEXT,
                    )
                    rendered = True
                    break
            if not rendered:  # pragma: no cover - حالت اضطراری
                self.ensure_space(line_h + 1.5)
                self.set_x(self.content_left)
                self.multi_cell(
                    self.content_width,
                    line_h,
                    title + "  " + page_label,
                    align="R",
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
            self.space(1.4 if level else 2.6)

        self.suppress_header = False
        self.set_base_font()

    def heading(self, text: str, level: int) -> None:
        sizes = {1: 17.5, 2: 14.5, 3: 12.8, 4: 11.8, 5: 11.3, 6: 11.0}
        size = sizes.get(level, 11.0)
        space_before = {1: 6, 2: 5, 3: 4}.get(level, 3)
        line_h = size * 0.62

        if level == 1 and self.get_y() > self.t_margin + 12:
            self.add_page()
        self.space(space_before)
        self.ensure_space(line_h * 2.6)
        self.set_font("Vazir", "B", size)
        self.set_text_color(*self.palette.primary if level <= 2 else self.palette.ink)

        marker_w = 4.2 if level == 2 else 0.0
        if marker_w:
            y = self.get_y() + 1.0
            self.set_fill_color(*self.palette.accent)
            self.rect(self.right_edge - 1.4, y, 1.4, line_h + 1.2, style="F")
        self.set_xy(self.content_left, self.get_y())
        self.multi_cell(
            self.content_width - marker_w,
            line_h,
            normalize_inline(text, self.persian_digits),
            align="R",
            markdown=True,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        if level <= 2:
            self.set_draw_color(*self.palette.line)
            self.set_line_width(0.25)
            y = self.get_y() + 1.2
            self.line(self.content_left, y, self.right_edge, y)
            self.space(2.6)
        else:
            self.space(1.2)
        self.set_text_color(*self.palette.ink)
        self.section_title = text if level <= 2 else self.section_title
        if level <= 2:
            for page in range(self.page_no(), self.page_no() + 1):
                self.page_sections[page] = self.section_title

    def paragraph(self, text: str) -> None:
        self.set_base_font()
        self.ensure_space(7)
        self.set_x(self.content_left)
        self.multi_cell(
            self.content_width,
            self.base * 0.72,
            normalize_inline(text, self.persian_digits),
            align="R",
            markdown=True,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.space(3.4)

    def bullets(self, items: Sequence[tuple[int, str, str | None]], ordered: bool) -> None:
        self.set_base_font()
        line_h = self.base * 0.72
        counters: dict[int, int] = {}
        for depth, text, number in items:
            indent = 6.0 + depth * 6.0
            if ordered:
                if number is not None:
                    counters[depth] = int(number)
                else:
                    counters[depth] = counters.get(depth, 0) + 1
                marker = f"{fa_num(counters[depth])}."
            else:
                marker = "•"
            self.ensure_space(line_h + 1.5)
            y0 = self.get_y()
            self.set_font("Vazir", "B" if number else "", self.base)
            self.set_text_color(*self.palette.accent)
            marker_w = self.get_string_width(marker) + 1.0
            self.set_xy(self.content_right - indent, y0)
            self.cell(marker_w, line_h, marker, align="R")
            self.set_base_font()
            self.set_xy(self.content_left, y0)
            self.multi_cell(
                self.content_width - indent - marker_w + 1.0,
                line_h,
                normalize_inline(text, self.persian_digits),
                align="R",
                markdown=True,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.space(1.6)
        self.space(1.8)

    def quote(self, text: str) -> None:
        self.set_base_font(self.base - 0.2)
        line_h = (self.base - 0.2) * 0.72
        pad = 4.0
        inner_w = self.content_width - 2 * pad - 2.6
        inner_lines = self.multi_cell(
            inner_w, line_h, normalize_inline(text, self.persian_digits),
            align="R", markdown=True, dry_run=True, output="LINES",
        )
        height = line_h * max(1, len(inner_lines)) + 2 * pad
        self.ensure_space(height + 4)
        y0 = self.get_y()
        self.set_fill_color(*self.palette.quote_fill)
        self.rect(self.content_left, y0, self.content_width, height, style="F", round_corners=True, corner_radius=1.2)
        self.set_fill_color(*self.palette.accent)
        self.rect(self.right_edge - 1.8, y0, 1.8, height, style="F")
        self.set_xy(self.content_left + pad, y0 + pad)
        self.multi_cell(
            inner_w, line_h, normalize_inline(text, self.persian_digits),
            align="R", markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        self.set_y(y0 + height + 4)
        self.set_base_font()

    def code_block(self, code: str, lang: str = "") -> None:
        if not code.strip():
            return
        size = self.base - 2.2
        line_h = size * 0.62
        pad = 3.2
        lines = code.split("\n")
        chunk: list[str] = []
        max_lines = 40
        for start in range(0, len(lines), max_lines):
            chunk = lines[start : start + max_lines]
            height = line_h * len(chunk) + 2 * pad + (5 if lang and start == 0 else 0)
            self.ensure_space(height + 3)
            y0 = self.get_y()
            self.set_fill_color(*self.palette.code_fill)
            self.rect(self.content_left, y0, self.content_width, height, style="F", round_corners=True, corner_radius=1.2)
            self.set_fill_color(*self.palette.primary)
            self.rect(self.content_left, y0, 1.6, height, style="F")
            y = y0 + pad
            if lang and start == 0:
                self.set_font("Vazir", "", size - 0.8)
                self.set_text_color(*self.palette.muted)
                self.set_xy(self.content_left + 3, y)
                self.cell(self.content_width - 6, 4, lang.upper(), align="L")
                y += 5
            self.set_text_shaping(True, direction=TextDirection.LTR)
            self.set_font("Mono", "", size)
            self.set_text_color(*self.palette.ink)
            for line in chunk:
                self.set_xy(self.content_left + 4, y)
                self.cell(self.content_width - 8, line_h, line.replace("\t", "    "), align="L")
                y += line_h
            self.set_text_shaping(True, direction=TextDirection.RTL)
            self.set_y(y0 + height + 4)
        self.set_base_font()

    def table_block(self, rows: Sequence[Sequence[str]]) -> None:
        rows = [list(r) for r in rows if any(str(c).strip() for c in r)]
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        cleaned = [[normalize_inline(str(c), self.persian_digits) for c in r] for r in rows]

        self.ensure_space(24)
        self.set_base_font(self.base - 1.2)
        self.set_draw_color(*self.palette.line)
        self.set_line_width(0.2)
        # نکته: کتابخانهٔ fpdf2 رنگ پرشدگی جاری را به‌عنوان پس‌زمینهٔ ردیف‌های جدول
        # برمی‌دارد؛ پس پیش از ساختن جدول آن را به سفید بازنشانی می‌کنیم.
        self.set_fill_color(255, 255, 255)
        with self.table(
            rows=cleaned,
            text_align="RIGHT",
            first_row_as_headings=True,
            markdown=True,
            line_height=(self.base - 1.0) * 0.72,
            padding=(1.8, 2.2, 1.8, 2.2),
            borders_layout=TableBordersLayout.HORIZONTAL_LINES,
            headings_style=FontFace(
                family="Vazir",
                emphasis="B",
                size_pt=self.base - 0.6,
                color=self.palette.primary,
                fill_color=rgb("#EDF1F5"),
            ),
            repeat_headings=1,
            num_heading_rows=1,
        ):
            pass
        self.set_base_font()
        self.space(4)

    def image_block(self, path_text: str, alt: str = "") -> None:
        path = Path(path_text.strip())
        if not path.is_absolute():
            path = (self.source_dir / path).resolve()
        if not path.exists():
            self.set_font("Vazir", "", self.base - 1.5)
            self.set_text_color(*self.palette.muted)
            self.ensure_space(7)
            self.set_x(self.content_left)
            self.multi_cell(
                self.content_width, 5, f"⟨تصویر یافت نشد: {path_text}⟩",
                align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            self.set_text_color(*self.palette.ink)
            return
        try:
            from fpdf.image_parsing import get_img_info

            info = get_img_info(str(path))
            ratio = info.height / info.width
            width = min(self.content_width, info.width * 0.2646)
            height = width * ratio
        except Exception:
            width, height = self.content_width, self.content_width * 0.6
        if height > 150:
            scale = 150 / height
            width, height = width * scale, height * scale
        self.ensure_space(height + 8)
        y0 = self.get_y()
        self.image(str(path), x=self.content_left + (self.content_width - width) / 2, y=y0, w=width)
        self.set_y(y0 + height + 2)
        if alt:
            self.set_font("Vazir", "", self.base - 2.0)
            self.set_text_color(*self.palette.muted)
            self.set_x(self.content_left)
            self.multi_cell(
                self.content_width, 5, normalize_inline(alt, self.persian_digits),
                align="C", markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        self.set_base_font()
        self.space(4)

    def hr(self) -> None:
        self.space(3)
        self.set_draw_color(*self.palette.line)
        self.set_line_width(0.3)
        y = self.get_y()
        inset = self.content_width * 0.28
        self.line(self.content_left + inset, y, self.content_right - inset, y)
        self.space(4)

    # -- حلقهٔ اصلی --------------------------------------------------------
    def render_blocks(self, blocks: Iterable[Block]) -> None:
        for block in blocks:
            if block.kind == "h":
                self.start_section(block.text, level=max(0, block.level - 1))
                self.heading(block.text, block.level)
            elif block.kind == "p":
                self.paragraph(block.text)
            elif block.kind in ("ul", "ol"):
                self.bullets(block.items, ordered=block.kind == "ol")
            elif block.kind == "quote":
                self.quote(block.text)
            elif block.kind == "code":
                self.code_block(block.text, block.lang)
            elif block.kind == "table":
                self.table_block(block.rows)
            elif block.kind == "image":
                self.image_block(block.text, block.lang)
            elif block.kind == "hr":
                self.hr()


# ---------------------------------------------------------------------------
# ساخت سند (دو مرحله‌ای: ابتدا برای شمارش صفحات، سپس با شمارهٔ کل صفحات)
# ---------------------------------------------------------------------------


@dataclass
class BuildOptions:
    fonts_dir: Path
    base_size: float = 11.5
    cover: bool = True
    toc: bool = True
    persian_digits: bool = True


def build_pdf(
    blocks: Sequence[Block],
    meta: dict[str, str],
    options: BuildOptions,
    total_pages: int | None,
    source_dir: Path,
    page_sections: dict[int, str] | None = None,
) -> Handout:
    pdf = Handout(
        meta=meta,
        fonts_dir=options.fonts_dir,
        base_size=options.base_size,
        total_pages=total_pages,
        persian_digits=options.persian_digits,
        source_dir=source_dir,
    )
    if page_sections:
        pdf.page_sections = page_sections
    if options.cover:
        pdf.draw_cover(meta)
    pdf.add_page()
    pdf.first_content_page = pdf.page_no()
    if options.toc:
        pdf.insert_toc_placeholder(pdf.render_toc, pages=1, allow_extra_pages=True)
    pdf.render_blocks(blocks)
    return pdf


def convert(
    source: Path,
    output: Path,
    *,
    options: BuildOptions,
    meta_override: dict[str, str] | None = None,
) -> tuple[int, int]:
    text = read_source(source)
    front_matter, body = parse_front_matter(text)
    meta = dict(front_matter)
    if meta_override:
        meta.update({k: v for k, v in meta_override.items() if v})
    blocks = parse_markdown(body)

    if not meta.get("title"):
        first_heading = next((b.text for b in blocks if b.kind == "h"), None)
        meta["title"] = first_heading or source.stem
    if not meta.get("source"):
        meta["source"] = "این جزوه از یادداشت‌های NotebookLM تهیه و در قالب PDF بازآرایی شده است."

    # مرحلهٔ اول: شمارش صفحات و استخراج عنوان هر صفحه
    first_pass = build_pdf(blocks, meta, options, total_pages=None, source_dir=source.parent)
    first_pass.output()  # تولید در حافظه (بدون ذخیره)
    total_pages = first_pass.page

    page_sections: dict[int, str] = {}
    starts = sorted(
        (
            (section.page_number, int(section.level), section.name)
            for section in getattr(first_pass, "_outline", ())
            if section.name
        ),
        key=lambda item: item[0],
    )
    # برای عنوان در جریان فقط سرفصل‌های اصلی (سطح ۰ و ۱ یعنی # و ##) در اولویت‌اند.
    main_starts = [item for item in starts if item[1] <= 1] or starts
    for page in range(1, total_pages + 1):
        # عنوان در جریان: آخرین سرفصلی که پیش از این صفحه آغاز شده؛
        # اگر سرفصلی پیش از صفحه شروع نشده باشد، سرفصل آغازشده در همین صفحه.
        earlier = [name for start, _level, name in main_starts if start < page]
        on_page = [name for start, _level, name in main_starts if start == page]
        page_sections[page] = earlier[-1] if earlier else (on_page[0] if on_page else "")

    # مرحلهٔ دوم: خروجی نهایی با شمارهٔ کل صفحات
    final = build_pdf(
        blocks,
        meta,
        options,
        total_pages=total_pages,
        source_dir=source.parent,
        page_sections=page_sections,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    final.output(str(output))
    words = sum(len(b.text.split()) + sum(len(i[1].split()) for i in b.items) for b in blocks)
    return total_pages, words


# ---------------------------------------------------------------------------
# رابط خط فرمان
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="md2pdf_fa",
        description="تبدیل جزوهٔ متنی/مارک‌داون/HTML (خروجی NotebookLM) به PDF فارسی",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "نمونه:\n"
            "  python3 tools/md2pdf_fa.py jozve.md -o jozve.pdf\n"
            "  python3 tools/md2pdf_fa.py notes.html -o jozve.pdf --title \"جزوهٔ شبکه\" --author \"علی\"\n"
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        help="فایل ورودی: .md، .txt یا .html (یا «-» برای خواندن از ورودی استاندارد)",
    )
    parser.add_argument("-o", "--output", type=Path, help="مسیر فایل PDF خروجی")
    parser.add_argument("--title", help="عنوان جزوه (روی جلد و سرصفحه)")
    parser.add_argument("--subtitle", help="زیرعنوان")
    parser.add_argument("--course", help="نام درس")
    parser.add_argument("--teacher", help="نام استاد/مدرس")
    parser.add_argument("--author", help="تهیه‌کننده")
    parser.add_argument("--date", help="تاریخ (پیش‌فرض: تاریخ خروجی)")
    parser.add_argument("--fonts-dir", type=Path, help="پوشهٔ فونت‌ها (پیش‌فرض: tools/fonts)")
    parser.add_argument("--font-size", type=float, default=11.5, help="اندازهٔ متن پایه (پیش‌فرض 11.5)")
    parser.add_argument("--no-cover", action="store_true", help="بدون صفحهٔ جلد")
    parser.add_argument("--no-toc", action="store_true", help="بدون فهرست مطالب")
    parser.add_argument("--latin-digits", action="store_true", help="اعداد لاتین بمانند")
    parser.add_argument("--version", action="version", version=f"md2pdf_fa {VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if str(args.input) != "-" and not args.input.exists():
        print(f"✗ فایل ورودی پیدا نشد: {args.input}", file=sys.stderr)
        return 2

    script_dir = Path(__file__).resolve().parent
    fonts_dir = (args.fonts_dir or (script_dir / "fonts")).resolve()
    output = args.output or (
        Path("jozve.pdf") if str(args.input) == "-" else args.input.with_suffix(".pdf")
    )

    overrides = {
        "title": args.title,
        "subtitle": args.subtitle,
        "course": args.course,
        "teacher": args.teacher,
        "author": args.author,
        "date": args.date,
    }
    overrides = {k: v for k, v in overrides.items() if v}
    if "date" not in overrides:
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from persian_date import jalali_today  # type: ignore

        overrides["date"] = jalali_today()

    options = BuildOptions(
        fonts_dir=fonts_dir,
        base_size=args.font_size,
        cover=not args.no_cover,
        toc=not args.no_toc,
        persian_digits=not args.latin_digits,
    )
    pages, words = convert(args.input, output, options=options, meta_override=overrides)
    size_kb = output.stat().st_size / 1024
    print(f"✓ PDF ساخته شد: {output}")
    print(f"  صفحه‌ها: {fa_num(pages)} | واژه‌های تقریبی: {fa_num(words)} | حجم: {fa_num(f'{size_kb:.0f}')} کیلوبایت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

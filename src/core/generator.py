"""PDF reconstruction and visual layout matching using ReportLab without hardcoded layout values.

Includes dynamic typography auto-fitting, line wrapping, font downscaling, collision avoidance,
and internal layout boundary self-validation checks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from src.core.models import (
    BackgroundOverlay,
    CategoryLegendItem,
    ScheduleCategory,
    SessionOverride,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)

logger = logging.getLogger("uwm_timetable_generator")


class FootnoteEntry:
    """Represents an abbreviated term and its referenced legend footnote."""

    def __init__(self, index: int, short_text: str, full_text: str, kind: str):
        self.index = index
        self.short_text = short_text
        self.full_text = full_text
        self.kind = kind

    @property
    def marker(self) -> str:
        return f"[*{self.index}]"

    @property
    def cell_label(self) -> str:
        return f"{self.short_text} [*{self.index}]"

    @property
    def legend_line(self) -> str:
        return f"[*{self.index}] {self.short_text} — {self.full_text}"


def compress_subject_to_acronym(text: str) -> str:
    """Convert subject name into initials/acronym (e.g. 'Advanced Computer Architecture' -> 'A.C.A.')."""
    cleaned = text.strip()
    tokens = re.split(r"[\s\-/]+", cleaned)
    words = [re.sub(r"[^a-zA-Z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", "", t) for t in tokens]
    words = [w for w in words if w]
    if not words:
        return cleaned
    return "".join(w[0].upper() + "." for w in words)




def compress_instructor_to_short(text: str) -> str:
    """Convert instructor title + full name to title + first initial + surname (e.g. 'Prof. Jan Kowalski' -> 'Prof. J. Kowalski')."""
    cleaned = text.strip()
    title_words = {
        "prof.", "prof", "dr", "hab.", "hab", "inż.", "inż", "mgr", "mgr.",
        "doc.", "doc", "nzw.", "nadzw."
    }
    parts = cleaned.split("/")
    res_parts = []
    for part in parts:
        p = re.sub(r",\s*prof\..*$", "", part.strip(), flags=re.IGNORECASE)
        tokens = p.split()
        titles = []
        names = []
        for t in tokens:
            t_clean = t.rstrip(",.").lower()
            if t_clean in title_words or t.lower() in title_words:
                titles.append(t)
            else:
                names.append(t)
        if len(names) >= 2:
            first_inits = "".join(n[0].upper() + "." for n in names[:-1])
            res = " ".join(titles + [first_inits, names[-1]])
        elif names:
            res = " ".join(titles + names)
        else:
            res = part
        res_parts.append(res)
    return " / ".join(res_parts) if res_parts else cleaned

def compress_instructor_to_initials(text: str) -> str:
    """Convert academic instructor title + name into initials (e.g. 'Prof. Jan Kowalski' -> 'Prof. J.K.')."""
    cleaned = text.strip()
    title_words = {
        "prof.", "prof", "dr", "hab.", "hab", "inż.", "inż", "mgr", "mgr.",
        "doc.", "doc", "nzw.", "nadzw."
    }
    parts = cleaned.split("/")
    abbr_parts = []
    for part in parts:
        p = re.sub(r",\s*prof\..*$", "", part.strip(), flags=re.IGNORECASE)
        tokens = p.split()
        titles = []
        names = []
        for t in tokens:
            t_clean = t.rstrip(",.").lower()
            if t_clean in title_words or t.lower() in title_words:
                titles.append(t)
            else:
                names.append(t)
        if not names and titles:
            names = titles
            titles = []
        initial_parts = []
        for n in names:
            subnames = n.split("-")
            inits = "-".join(sn[0].upper() + "." for sn in subnames if sn and sn[0].isalpha())
            if inits:
                initial_parts.append(inits)
        prefix = " ".join(titles) + (" " if titles else "")
        abbr_parts.append(f"{prefix}{''.join(initial_parts)}".strip())
    return " / ".join(abbr_parts) if abbr_parts else cleaned


def get_instructor_display_variants(name: str) -> List[str]:
    """Generate progressively compressed instructor variants preserving the surname as long as possible.
    Per requirements: Truncate instructor first names to initials before ever truncating the last name.
    """
    raw = name.strip()
    if not raw:
        return []
    variants: List[str] = [raw]

    short_inst = compress_instructor_to_short(raw)
    if short_inst not in variants:
        variants.append(short_inst)

    title_words = {
        "prof.", "prof", "dr", "hab.", "hab", "inż.", "inż", "mgr", "mgr.",
        "doc.", "doc", "nzw.", "nadzw."
    }
    tokens = raw.split()
    titles = []
    names = []
    for t in tokens:
        t_clean = t.rstrip(",.").lower()
        if t_clean in title_words or t.lower() in title_words:
            titles.append(t)
        else:
            names.append(t)

    if names:
        last_name = names[-1]
        first_inits = "".join(n[0].upper() + "." for n in names[:-1]) if len(names) >= 2 else ""

        # Primary title + first initial + last name (e.g. 'Prof. J. Kowalski' or 'Dr T. Nowak')
        if titles:
            primary_title = titles[0]
            cand1 = f"{primary_title} {first_inits} {last_name}".replace("  ", " ").strip()
            if cand1 not in variants:
                variants.append(cand1)

        # First initial + last name (e.g. 'T. Nowak', 'J. Kowalski')
        cand2 = f"{first_inits} {last_name}".strip()
        if cand2 and cand2 not in variants:
            variants.append(cand2)

        # Surname only (e.g. 'Nowak', 'Kowalski')
        if last_name not in variants:
            variants.append(last_name)

    # Last resort before footnotes: initials (e.g. 'Dr inż. T.N.', 'T.N.')
    inits_inst = compress_instructor_to_initials(raw)
    if inits_inst not in variants:
        variants.append(inits_inst)

    return variants


def compress_room_to_acronym(text: str) -> str:
    """Convert room label into acronym with room number (e.g. 'Laboratorium Komputerowe L204' -> 'L.K. L204')."""
    cleaned = text.strip()
    tokens = cleaned.split()
    if len(tokens) <= 1:
        return cleaned
    words = tokens[:-1]
    last = tokens[-1]
    if any(ch.isdigit() for ch in last) or len(last) <= 3:
        initials = "".join(w[0].upper() + "." for w in words if w and w[0].isalpha())
        return f"{initials} {last}".strip()
    return "".join(w[0].upper() + "." for w in tokens if w and w[0].isalpha())


def draw_striped_or_solid_background(
    c: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    colors_list: List[str],
    border_color: str = "#000000",
    border_width: float = 0.6,
) -> None:
    """Draw solid or vertically-striped multi-color background rectangle for timetable cells."""
    if not colors_list:
        colors_list = ["#FFFFFF"]

    valid_hex: List[str] = []
    for col in colors_list:
        if not col:
            continue
        c_str = str(col).strip()
        if not c_str.startswith("#"):
            c_str = f"#{c_str}"
        valid_hex.append(c_str)

    if not valid_hex:
        valid_hex = ["#FFFFFF"]

    n = len(valid_hex)
    if n == 1:
        try:
            c.setFillColor(colors.HexColor(valid_hex[0]))
        except Exception:
            c.setFillColor(colors.HexColor("#FFFFFF"))
        try:
            c.setStrokeColor(colors.HexColor(border_color))
        except Exception:
            c.setStrokeColor(colors.black)
        c.setLineWidth(border_width)
        c.rect(x, y, width, height, fill=1, stroke=1)
    else:
        stripe_w = width / float(n)
        for idx, col_hex in enumerate(valid_hex):
            sx = x + idx * stripe_w
            try:
                c.setFillColor(colors.HexColor(col_hex))
            except Exception:
                c.setFillColor(colors.HexColor("#FFFFFF"))
            c.rect(sx, y, stripe_w, height, fill=1, stroke=0)
        # Outer border
        try:
            c.setStrokeColor(colors.HexColor(border_color))
        except Exception:
            c.setStrokeColor(colors.black)
        c.setLineWidth(border_width)
        c.rect(x, y, width, height, fill=0, stroke=1)


SESSION_TYPE_ABBREVIATIONS: Dict[str, str] = {
    "lecture": "w.",
    "auditory/classes": "ćw.",
    "classes": "ćw.",
    "auditory": "ćw.",
    "laboratory": "lab.",
    "lab": "lab.",
    "project": "proj.",
    "seminar": "sem.",
    "work": "pr.",
    "pracownia": "pr.",
    "wykład": "w.",
    "ćwiczenia": "ćw.",
    "laboratorium": "lab.",
    "projekt": "proj.",
    "seminarium": "sem.",
}


class TimetablePDFGenerator:
    """Pure renderer for timetable PDFs based on layout schemas with robust auto-fitting typography."""

    def __init__(
        self,
        log_handler: Optional[logging.Logger] = None,
        cell_padding: float = 2.5,
        min_font_size: float = 6.0,
    ):
        self.log = log_handler or logger
        self.cell_padding: float = cell_padding
        self.min_font_size: float = min_font_size
        self.layout_warnings: List[str] = []
        self.page_footnotes: Dict[str, FootnoteEntry] = {}
        self._next_footnote_idx: int = 1
        self.font_regular, self.font_bold, self.font_italic = self._setup_fonts()

    def _setup_fonts(self) -> Tuple[str, str, str]:
        """Register TrueType fonts with Polish diacritic support, falling back to Helvetica."""
        font_candidates = [
            (
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
                "LiberationSans",
            ),
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/DejaVuSans-Oblique.ttf",
                "DejaVuSans",
            ),
        ]

        for reg_path, bold_path, ital_path, base_name in font_candidates:
            if os.path.exists(reg_path) and os.path.exists(bold_path):
                try:
                    pdfmetrics.registerFont(TTFont(base_name, reg_path))
                    pdfmetrics.registerFont(TTFont(f"{base_name}-Bold", bold_path))
                    if os.path.exists(ital_path):
                        pdfmetrics.registerFont(TTFont(f"{base_name}-Italic", ital_path))
                    else:
                        pdfmetrics.registerFont(TTFont(f"{base_name}-Italic", reg_path))
                    self.log.info(f"Registered system font family: {base_name}")
                    return base_name, f"{base_name}-Bold", f"{base_name}-Italic"
                except Exception as e:
                    self.log.warning(f"Failed to register font {base_name}: {e}")

        self.log.info("Falling back to standard Helvetica fonts.")
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

    def _y_to_cv(self, y_top: float, page_height: float) -> float:
        """Convert top-down coordinate to ReportLab bottom-up coordinate dynamically."""
        return page_height - y_top

    def _register_footnote(self, full_text: str, kind: str) -> FootnoteEntry:
        """Register or retrieve an indexed footnote entry for oversized terms de-duplicated per page."""
        key = full_text.strip()
        if key in self.page_footnotes:
            return self.page_footnotes[key]

        if kind == "subject":
            short = compress_subject_to_acronym(key)
        elif kind == "instructor":
            short = compress_instructor_to_initials(key)
        elif kind == "room":
            short = compress_room_to_acronym(key)
        else:
            short = compress_subject_to_acronym(key)

        entry = FootnoteEntry(
            index=self._next_footnote_idx,
            short_text=short,
            full_text=key,
            kind=kind,
        )
        self.page_footnotes[key] = entry
        self._next_footnote_idx += 1
        return entry

    # =========================================================================
    # Typography & Text Fitting Engine
    # =========================================================================

    def _wrap_text(self, text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
        """Wrap text into lines using actual glyph measurements from pdfmetrics."""
        if not text:
            return []
        words = text.strip().split()
        if not words:
            return []

        lines: List[str] = []
        current_words: List[str] = []

        for word in words:
            test_line = " ".join(current_words + [word]) if current_words else word
            w = pdfmetrics.stringWidth(test_line, font_name, font_size)
            if w <= max_width:
                current_words.append(word)
            else:
                if current_words:
                    lines.append(" ".join(current_words))
                    current_words = []
                # Check if word itself exceeds max_width
                if pdfmetrics.stringWidth(word, font_name, font_size) <= max_width:
                    current_words = [word]
                else:
                    # Break long word into sub-chunks
                    chunks = self._break_word(word, font_name, font_size, max_width)
                    lines.extend(chunks[:-1])
                    current_words = [chunks[-1]]

        if current_words:
            lines.append(" ".join(current_words))

        return lines

    def _break_word(self, word: str, font_name: str, font_size: float, max_width: float) -> List[str]:
        """Break a long single word into character chunks that fit within max_width."""
        chunks: List[str] = []
        curr = ""
        for ch in word:
            test = curr + ch
            if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width or not curr:
                curr = test
            else:
                chunks.append(curr)
                curr = ch
        if curr:
            chunks.append(curr)
        return chunks

    def _truncate_with_ellipsis(
        self, text: str, font_name: str, font_size: float, max_width: float
    ) -> str:
        """Truncate text gracefully with an ellipsis (...) to strictly respect max_width."""
        if not text:
            return ""
        if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
            return text

        ellipsis = "..."
        ell_w = pdfmetrics.stringWidth(ellipsis, font_name, font_size)
        if ell_w >= max_width:
            return "."

        target_w = max_width - ell_w
        curr = ""
        for ch in text:
            if pdfmetrics.stringWidth(curr + ch, font_name, font_size) <= target_w:
                curr += ch
            else:
                break

        return curr.rstrip() + ellipsis

    def _abbreviate_session_type(self, session_type: Optional[str]) -> str:
        """Abbreviate session types (e.g. Lecture -> w., Laboratory -> lab., etc.)."""
        if not session_type:
            return ""
        st_clean = session_type.strip().lower()
        if st_clean in SESSION_TYPE_ABBREVIATIONS:
            return SESSION_TYPE_ABBREVIATIONS[st_clean]

        # English-specific abbreviation fallback
        if "lec" in st_clean:
            return "Lec"
        if "lab" in st_clean:
            return "Lab"
        if "audit" in st_clean or "class" in st_clean:
            return "Aud"
        if "proj" in st_clean:
            return "Proj"
        if "sem" in st_clean:
            return "Sem"

        return session_type.strip()

    # =========================================================================
    # Concurrent Slot Subdivision Engine
    # =========================================================================

    def _is_alternating_week(self, notes: Optional[str]) -> bool:
        """Detect whether slot notes indicate alternating weeks."""
        if not notes:
            return False
        n = notes.lower()
        return any(kw in n for kw in ("tydz.", "tydzień", "week", "tydź", "(a)", "(b)", "1-7", "8-15"))

    def _subdivide_concurrent_entries(
        self,
        entries: List[TimetableEntry],
        base_x: float,
        base_y: float,
        slot_w: float,
        cohort_h: float,
    ) -> List[Tuple[TimetableEntry, float, float, float, float]]:
        """Subdivide available bounding box evenly or side-by-side for concurrent/split entries."""
        n = len(entries)
        if n == 0:
            return []
        if n == 1:
            return [(entries[0], base_x, base_y, slot_w, cohort_h)]

        # Check for alternating week patterns with sufficient slot width
        has_alt = any(self._is_alternating_week(e.notes) for e in entries)
        if has_alt and (slot_w / n) >= 42.0:
            sub_w = slot_w / float(n)
            return [
                (entries[i], base_x + i * sub_w, base_y, sub_w, cohort_h)
                for i in range(n)
            ]

        # Default vertical stacking across cohort height
        sub_h = cohort_h / float(n)
        return [
            (entries[i], base_x, base_y + i * sub_h, slot_w, sub_h)
            for i in range(n)
        ]

    # =========================================================================
    # Layout Self-Validation
    # =========================================================================

    def _validate_element_bounds(
        self,
        day_key: str,
        slot: TimetableEntry,
        card_box: Tuple[float, float, float, float],
        inner_box: Tuple[float, float, float, float],
        rendered_lines: List[Tuple[str, str, float, float, float]],
        layout: TimetableLayout,
        day_y_start: float,
        day_h: float,
    ) -> None:
        """Verify element and glyph boundaries, logging structured warnings on any overflow."""
        x, y_top, w, h = card_box
        inner_x, inner_y, avail_w, avail_h = inner_box
        bounds = layout.grid_bounds

        # Check card horizontal boundaries against table bounds
        if x < bounds.table_x0 - 0.5 or (x + w) > bounds.table_x1 + 0.5:
            msg = (
                f"[LAYOUT OVERFLOW] Card exceeds table grid boundaries: day='{day_key}', "
                f"hours='{slot.hours}', subject='{slot.subject}', "
                f"x={x:.1f}, w={w:.1f}, table_x0={bounds.table_x0:.1f}, table_x1={bounds.table_x1:.1f}"
            )
            self.log.warning(msg)
            self.layout_warnings.append(msg)

        # Check card vertical boundaries against day row bounds
        if y_top < day_y_start - 0.5 or (y_top + h) > day_y_start + day_h + 0.5:
            msg = (
                f"[LAYOUT OVERFLOW] Card exceeds day vertical bounds: day='{day_key}', "
                f"hours='{slot.hours}', subject='{slot.subject}', "
                f"y={y_top:.1f}, h={h:.1f}, day_y0={day_y_start:.1f}, day_y1={day_y_start + day_h:.1f}"
            )
            self.log.warning(msg)
            self.layout_warnings.append(msg)

        # Check rendered text lines within inner bounding box
        for text, font, size, x_pos, baseline_y in rendered_lines:
            lw = pdfmetrics.stringWidth(text, font, size)
            if x_pos < inner_x - 0.5 or (x_pos + lw) > inner_x + avail_w + 0.5:
                msg = (
                    f"[LAYOUT OVERFLOW] Text width exceeds inner cell box: day='{day_key}', "
                    f"hours='{slot.hours}', subject='{slot.subject}', text='{text}', "
                    f"lw={lw:.1f}pt > avail_w={avail_w:.1f}pt"
                )
                self.log.warning(msg)
                self.layout_warnings.append(msg)

            glyph_top = baseline_y + size * 0.85
            glyph_bottom = baseline_y - size * 0.25
            if glyph_top > inner_y + avail_h + 0.5:
                msg = (
                    f"[LAYOUT OVERFLOW] Glyph ascender breaches top inner boundary: day='{day_key}', "
                    f"hours='{slot.hours}', subject='{slot.subject}', text='{text}', "
                    f"glyph_top={glyph_top:.1f} > limit={inner_y + avail_h:.1f}"
                )
                self.log.warning(msg)
                self.layout_warnings.append(msg)

            if glyph_bottom < inner_y - 0.5:
                msg = (
                    f"[LAYOUT OVERFLOW] Glyph descender breaches bottom inner boundary: day='{day_key}', "
                    f"hours='{slot.hours}', subject='{slot.subject}', text='{text}', "
                    f"glyph_bottom={glyph_bottom:.1f} < limit={inner_y:.1f}"
                )
                self.log.warning(msg)
                self.layout_warnings.append(msg)

    # =========================================================================
    # PDF Document Generation Pipeline
    # =========================================================================

    def generate(self, timetable: Timetable, output_pdf_path: str | Path) -> Path:
        """Generate the timetable PDF reflecting the given Timetable and dynamic layout state."""
        out_path = Path(output_pdf_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.layout_warnings.clear()
        self.page_footnotes.clear()
        self._next_footnote_idx = 1

        layout = timetable.layout or TimetableLayout.create_default()
        bounds = layout.grid_bounds

        self.log.info(f"Generating timetable PDF -> {out_path.resolve()}")

        c = canvas.Canvas(str(out_path), pagesize=(bounds.page_width, bounds.page_height))
        c.setTitle("Timetable - Informatyka IV Rok")

        # 1. Draw Title Header Banner
        self._draw_header_banner(c, layout)

        # 2. Draw Weekly Timetable Grid & Slots for each day
        for day_key, y_start in layout.row_metrics.day_y_starts.items():
            entries = timetable.get_entries(day_key)
            self._draw_day_block(c, day_key, y_start, entries, layout)

        # 3. Draw Legend, Annotations & Footer Notes
        self._draw_footer_notes(c, layout)

        c.save()

        if self.layout_warnings:
            self.log.warning(
                f"Generated timetable PDF with {len(self.layout_warnings)} layout boundary warning(s)."
            )
        else:
            self.log.info(
                f"Successfully generated timetable PDF at: {out_path.resolve()} (zero layout breaches)."
            )

        return out_path

    def _draw_header_banner(self, c: canvas.Canvas, layout: TimetableLayout) -> None:
        """Draw top banner with term and degree program header dynamically."""
        banner = layout.banner
        bounds = layout.grid_bounds
        styles = layout.color_styles
        typo = layout.typography

        cv_y = self._y_to_cv(banner.y0 + banner.height, bounds.page_height)

        # Banner background
        c.setFillColor(colors.HexColor(styles.header_banner_bg))
        c.rect(banner.x0, cv_y, banner.width, banner.height, fill=1, stroke=0)

        # Banner text
        c.setFillColor(colors.black)
        c.setFont(self.font_bold, typo.header_font_size)
        c.drawString(banner.x0 + 35.0, cv_y + 2.5, banner.term_text)
        c.drawString(banner.x0 + 128.0, cv_y + 2.5, banner.program_text)

    def _draw_day_block(
        self,
        c: canvas.Canvas,
        day_key: str,
        y_start: float,
        entries: List[TimetableEntry],
        layout: TimetableLayout,
    ) -> None:
        """Draw complete grid structure and slots for a single day with standardized group alignment."""
        bounds = layout.grid_bounds
        cols = layout.column_metrics
        rows = layout.row_metrics
        styles = layout.color_styles
        typo = layout.typography

        group_span_h = rows.rows_per_group * rows.baseline_row_height
        day_h = rows.header_row_height + 2.0 * group_span_h
        y_end = y_start + day_h

        # 1. Day Outer Border
        c.setStrokeColor(colors.HexColor(styles.day_border_stroke))
        c.setLineWidth(styles.day_border_width)
        c.rect(
            bounds.table_x0,
            self._y_to_cv(y_end, bounds.page_height),
            bounds.table_x1 - bounds.table_x0,
            day_h,
            fill=0,
            stroke=1,
        )

        # 2. Minor 15-Minute Grid Lines (15, 30, 45 min)
        c.setStrokeColor(colors.HexColor(styles.minor_grid_stroke))
        c.setLineWidth(styles.minor_grid_width)
        for i in range(1, cols.total_columns):
            if i % 4 != 0:
                x_line = cols.time_start_x + i * cols.col_15m_width
                c.line(
                    x_line,
                    self._y_to_cv(y_start + rows.header_row_height, bounds.page_height),
                    x_line,
                    self._y_to_cv(y_end, bounds.page_height),
                )

        # Minor horizontal sub-row lines
        for r_idx in range(1, rows.rows_per_group):
            y_sub = y_start + rows.header_row_height + r_idx * rows.baseline_row_height
            c.line(
                cols.time_start_x,
                self._y_to_cv(y_sub, bounds.page_height),
                bounds.table_x1,
                self._y_to_cv(y_sub, bounds.page_height),
            )
        for r_idx in range(1, rows.rows_per_group):
            y_sub = y_start + rows.header_row_height + group_span_h + r_idx * rows.baseline_row_height
            c.line(
                cols.time_start_x,
                self._y_to_cv(y_sub, bounds.page_height),
                bounds.table_x1,
                self._y_to_cv(y_sub, bounds.page_height),
            )

        # 3. Major Full-Hour Divider Lines
        c.setStrokeColor(colors.HexColor(styles.major_grid_stroke))
        c.setLineWidth(styles.major_grid_width)
        for i in range(0, cols.total_columns + 1, 4):
            x_line = cols.time_start_x + i * cols.col_15m_width
            if x_line <= bounds.table_x1:
                c.line(
                    x_line,
                    self._y_to_cv(y_start, bounds.page_height),
                    x_line,
                    self._y_to_cv(y_end, bounds.page_height),
                )

        # Horizontal separator between header and timetable grid (Major)
        c.line(
            bounds.table_x0,
            self._y_to_cv(y_start + rows.header_row_height, bounds.page_height),
            bounds.table_x1,
            self._y_to_cv(y_start + rows.header_row_height, bounds.page_height),
        )

        # Horizontal separator between Group 1 and Group 2 (Major)
        y_grp_split = y_start + rows.header_row_height + group_span_h
        c.line(
            bounds.table_x0 + cols.day_col_width,
            self._y_to_cv(y_grp_split, bounds.page_height),
            bounds.table_x1,
            self._y_to_cv(y_grp_split, bounds.page_height),
        )

        # 4. Vertical Separators for Day and Group Columns
        c.setStrokeColor(colors.HexColor(styles.day_border_stroke))
        c.setLineWidth(0.6)
        c.line(
            bounds.table_x0 + cols.day_col_width,
            self._y_to_cv(y_start, bounds.page_height),
            bounds.table_x0 + cols.day_col_width,
            self._y_to_cv(y_end, bounds.page_height),
        )
        c.line(
            cols.time_start_x,
            self._y_to_cv(y_start, bounds.page_height),
            cols.time_start_x,
            self._y_to_cv(y_end, bounds.page_height),
        )

        # 5. Day Name & Group Labels
        day_label = layout.day_labels.get(day_key, day_key.upper())
        c.setFont(self.font_bold, typo.day_label_font_size)
        c.setFillColor(colors.black)
        c.drawCentredString(
            bounds.table_x0 + cols.day_col_width / 2.0,
            self._y_to_cv(y_start + day_h / 2.0 - 2.5, bounds.page_height),
            day_label,
        )

        # Group 1 label vertically centered
        g1_y_center = y_start + rows.header_row_height + group_span_h / 2.0 - 2.5
        c.setFont(self.font_bold, typo.group_label_font_size)
        c.drawCentredString(
            bounds.table_x0 + cols.day_col_width + cols.group_col_width / 2.0,
            self._y_to_cv(g1_y_center, bounds.page_height),
            "1",
        )

        # Group 2 label vertically centered
        g2_y_center = y_start + rows.header_row_height + group_span_h + group_span_h / 2.0 - 2.5
        c.drawCentredString(
            bounds.table_x0 + cols.day_col_width + cols.group_col_width / 2.0,
            self._y_to_cv(g2_y_center, bounds.page_height),
            "2",
        )

        # 6. Hour Column Headers
        c.setFont(self.font_bold, typo.hour_label_font_size)
        c.setFillColor(colors.black)
        header_text_y = self._y_to_cv(y_start + rows.header_row_height - 2.1, bounds.page_height)
        for h in range(cols.start_hour, cols.end_hour):
            x_hour = cols.time_start_x + (h - cols.start_hour) * 4 * cols.col_15m_width
            c.drawString(x_hour + 2.0, header_text_y, f"{h:02d}:00")

        # 7. Background Overlays (e.g. Godziny Rektorskie / Dekanackie, custom zones)
        self._draw_background_overlays(c, day_key, y_start, layout, group_span_h)

        # 8. Render Timetable Entries with Dynamic Collision-Free Subdivision
        self._render_day_entries(c, day_key, y_start, entries, layout, day_h)

    def _render_day_entries(
        self,
        c: canvas.Canvas,
        day_key: str,
        y_start: float,
        entries: List[TimetableEntry],
        layout: TimetableLayout,
        day_h: float,
    ) -> None:
        """Render all course slots for a day with dynamic concurrent subdivision and no cell collisions."""
        cols = layout.column_metrics
        rows = layout.row_metrics
        group_span_h = rows.rows_per_group * rows.baseline_row_height

        grouped_by_time: Dict[str, List[TimetableEntry]] = {}
        for entry in entries:
            grouped_by_time.setdefault(entry.hours, []).append(entry)

        for hours_key, slot_list in grouped_by_time.items():
            start_parts = hours_key.split("-")[0].split(":")
            end_parts = hours_key.split("-")[1].split(":")

            s_min = (int(start_parts[0]) - cols.start_hour) * 60 + int(start_parts[1])
            e_min = (int(end_parts[0]) - cols.start_hour) * 60 + int(end_parts[1])

            x0 = cols.time_start_x + (s_min / 15.0) * cols.col_15m_width
            x1 = cols.time_start_x + (e_min / 15.0) * cols.col_15m_width
            slot_w = x1 - x0

            # Partition into cohorts
            whole_cohort = [s for s in slot_list if s.group is None or s.group == 0]
            g1_slots = [s for s in slot_list if s.group == 1]
            g2_slots = [s for s in slot_list if s.group == 2]
            other_slots = [
                s for s in slot_list
                if s not in whole_cohort and s not in g1_slots and s not in g2_slots
            ]

            # 1. Whole cohort events (e.g. Lectures)
            if whole_cohort:
                base_y = y_start + rows.header_row_height
                band_h = 2.0 * group_span_h
                if g1_slots and not g2_slots:
                    base_y += group_span_h
                    band_h = group_span_h
                elif g2_slots and not g1_slots:
                    band_h = group_span_h

                sub_boxes = self._subdivide_concurrent_entries(whole_cohort, x0, base_y, slot_w, band_h)
                for slot, bx, by, bw, bh in sub_boxes:
                    self._draw_slot_box(c, bx, by, bw, bh, slot, layout, day_key, y_start, day_h)

            # 2. Group 1 events (e.g. Labs, Seminars, Subgroups)
            if g1_slots:
                base_y1 = y_start + rows.header_row_height
                sub_boxes = self._subdivide_concurrent_entries(g1_slots, x0, base_y1, slot_w, group_span_h)
                for slot, bx, by, bw, bh in sub_boxes:
                    self._draw_slot_box(c, bx, by, bw, bh, slot, layout, day_key, y_start, day_h)

            # 3. Group 2 events
            if g2_slots:
                base_y2 = y_start + rows.header_row_height + group_span_h
                sub_boxes = self._subdivide_concurrent_entries(g2_slots, x0, base_y2, slot_w, group_span_h)
                for slot, bx, by, bw, bh in sub_boxes:
                    self._draw_slot_box(c, bx, by, bw, bh, slot, layout, day_key, y_start, day_h)

            # 4. Other events
            if other_slots:
                base_yo = y_start + rows.header_row_height
                sub_boxes = self._subdivide_concurrent_entries(other_slots, x0, base_yo, slot_w, group_span_h)
                for slot, bx, by, bw, bh in sub_boxes:
                    self._draw_slot_box(c, bx, by, bw, bh, slot, layout, day_key, y_start, day_h)

    def _lookup_category_colors(self, cat_ids: List[str], layout: TimetableLayout) -> List[str]:
        """Look up hex color codes for given category IDs from layout or registered categories."""
        res: List[str] = []
        cat_map: Dict[str, str] = {}
        if hasattr(layout, "categories") and layout.categories:
            for cat in layout.categories:
                cat_map[cat.category_id] = cat.color
        if hasattr(layout.footer, "active_categories") and layout.footer.active_categories:
            for cat in layout.footer.active_categories:
                cat_map[cat.category_id] = cat.color

        for cid in cat_ids:
            if cid in cat_map:
                res.append(cat_map[cid])
        return res

    def _lookup_subject_colors(self, subject_name: str, layout: TimetableLayout) -> List[str]:
        """Look up colors assigned at the global subject level if present in layout/categories."""
        s_norm = subject_name.strip().lower()
        if hasattr(layout, "categories") and layout.categories:
            for cat in layout.categories:
                if cat.name.lower() in s_norm or cat.category_id.lower() in s_norm:
                    return [cat.color]
        return []

    def _resolve_slot_colors(
        self,
        slot: TimetableEntry,
        layout: TimetableLayout,
        day_key: str,
    ) -> List[str]:
        """Resolve cell fill colors from exact session overrides, slot colors, categories, or fallback."""
        resolved: List[str] = []

        # 1. Exact session override
        if hasattr(layout, "session_overrides") and layout.session_overrides:
            for ov in layout.session_overrides:
                if ov.day.lower() == day_key.lower():
                    time_match = (not ov.hours or ov.hours == slot.hours)
                    subj_match = (not ov.subject or ov.subject.lower() in slot.subject.lower())
                    grp_match = (ov.group is None or ov.group == slot.group)
                    if time_match and subj_match and grp_match:
                        if ov.colors:
                            resolved = list(ov.colors)
                            break
                        if ov.category_ids:
                            cat_cols = self._lookup_category_colors(ov.category_ids, layout)
                            if cat_cols:
                                resolved = cat_cols
                                break

        # 2. Slot-level colors
        if not resolved and hasattr(slot, "colors") and slot.colors:
            resolved = list(slot.colors)

        # 3. Slot-level category IDs
        if not resolved and hasattr(slot, "category_ids") and slot.category_ids:
            cat_cols = self._lookup_category_colors(slot.category_ids, layout)
            if cat_cols:
                resolved = cat_cols

        # 4. Global subject-level category / color lookup
        if not resolved:
            subj_cols = self._lookup_subject_colors(slot.subject, layout)
            if subj_cols:
                resolved = list(subj_cols)

        # 5. Check if marked modified
        if getattr(slot, "is_modified", False):
            mod_col = "#E67E22"
            if not resolved:
                resolved = [mod_col]
            elif mod_col not in resolved:
                resolved.append(mod_col)

        # 6. Fallback neutral color
        if not resolved:
            styles = layout.color_styles
            fallback = styles.regular_fill if styles.regular_fill else "#FFFFFF"
            resolved = [fallback]

        return resolved

    def _draw_background_overlays(
        self,
        c: canvas.Canvas,
        day_key: str,
        y_start: float,
        layout: TimetableLayout,
        group_span_h: float,
    ) -> None:
        """Draw custom background overlays with labels, start/end times, opacity, and pattern."""
        cols = layout.column_metrics
        rows = layout.row_metrics
        bounds = layout.grid_bounds

        overlays: List[BackgroundOverlay] = []
        if hasattr(layout, "custom_overlays") and layout.custom_overlays:
            overlays.extend(layout.custom_overlays)

        # Backward compatibility with deans_hour
        if layout.deans_hour and layout.deans_hour.get("day") == day_key:
            dh_hours = layout.deans_hour.get("hours", "11:30-12:45")
            dh_label = layout.deans_hour.get("label", "Godziny Dziekańskie")
            if not any(o.day == day_key and f"{o.start_time}-{o.end_time}" == dh_hours for o in overlays):
                s_part, e_part = dh_hours.split("-")
                overlays.append(
                    BackgroundOverlay(
                        overlay_id="deans_hour",
                        label=dh_label,
                        day=day_key,
                        start_time=s_part.strip(),
                        end_time=e_part.strip(),
                        color=layout.color_styles.deans_fill,
                        opacity=0.35,
                        pattern="solid",
                    )
                )

        for ov in overlays:
            if ov.day.lower() != day_key.lower():
                continue

            try:
                s_h, s_m = map(int, ov.start_time.split(":"))
                e_h, e_m = map(int, ov.end_time.split(":"))
            except Exception:
                continue

            s_min = (s_h - cols.start_hour) * 60 + s_m
            e_min = (e_h - cols.start_hour) * 60 + e_m

            dx0 = cols.time_start_x + (s_min / 15.0) * cols.col_15m_width
            dx1 = cols.time_start_x + (e_min / 15.0) * cols.col_15m_width
            dw = max(1.0, dx1 - dx0)

            # Determine vertical span
            if ov.target_group_ids == ["1"]:
                dh = group_span_h
                dy = y_start + rows.header_row_height
            elif ov.target_group_ids == ["2"]:
                dh = group_span_h
                dy = y_start + rows.header_row_height + group_span_h
            else:
                dh = 2.0 * group_span_h
                dy = y_start + rows.header_row_height

            cv_y = self._y_to_cv(dy + dh, bounds.page_height)

            c.saveState()
            try:
                fill_col = colors.HexColor(ov.color)
            except Exception:
                fill_col = colors.HexColor("#FF5429")

            c.setFillColor(fill_col, alpha=ov.opacity)
            c.setStrokeColor(fill_col, alpha=min(1.0, ov.opacity + 0.3))
            c.setLineWidth(0.8)
            c.rect(dx0, cv_y, dw, dh, fill=1, stroke=1)

            # Pattern rendering
            if ov.pattern in ("diagonal", "cross"):
                c.setStrokeColor(fill_col, alpha=min(1.0, ov.opacity + 0.25))
                c.setLineWidth(0.5)
                step = 10.0
                cur_x = dx0 - dh
                while cur_x < dx0 + dw + dh:
                    x_start_line = max(dx0, cur_x)
                    x_end_line = min(dx0 + dw, cur_x + dh)
                    if x_start_line < x_end_line:
                        c.line(x_start_line, cv_y, x_end_line, cv_y + dh)
                    cur_x += step
                if ov.pattern == "cross":
                    cur_x = dx0 - dh
                    while cur_x < dx0 + dw + dh:
                        x_start_line = max(dx0, cur_x)
                        x_end_line = min(dx0 + dw, cur_x + dh)
                        if x_start_line < x_end_line:
                            c.line(x_start_line, cv_y + dh, x_end_line, cv_y)
                        cur_x += step

            # Overlay Label
            if ov.label and dw > 25.0:
                c.setFillColor(colors.black, alpha=0.85)
                c.setFont(self.font_bold, 7.0)
                c.drawCentredString(dx0 + dw / 2.0, cv_y + dh / 2.0 - 2.5, ov.label)

            c.restoreState()

    # =========================================================================
    # Structured 3-Zone Cell Layout & Typography Engine
    # =========================================================================

    def _layout_3zone_cell(
        self,
        slot: TimetableEntry,
        avail_w: float,
        avail_h: float,
        layout: TimetableLayout,
    ) -> Tuple[List[str], float, List[str], float, List[str], float]:
        """Compute structured 3-zone cell layout maximizing readability without clipping.

        Zone 1 (Top): Full subject name with clean multi-line wrapping (Bold 7.5-9.0 pt, down to 6.5 pt).
        Zone 2 (Middle): Instructor name & class type (Regular/Italic 6.0-7.5 pt, initials before surname trunc).
        Zone 3 (Bottom): Room code/location pinned to bottom, horizontally centered (#333333, 6.0-7.0 pt).
        """
        typo = layout.typography

        # -------------------------------------------------------------
        # 1. Bottom Zone (Room): Pinned to bottom, subordinate, no ellipsis
        # -------------------------------------------------------------
        full_room = slot.room.strip() if slot.room else ""
        room_lines: List[str] = []
        room_size = 6.5 if (avail_h >= 45.0) else 6.0

        if full_room:
            found_r = False
            for r_cand in (6.8, 6.5, 6.2, 6.0, 5.8, 5.5, 5.0):
                w_cand = pdfmetrics.stringWidth(full_room, self.font_bold, r_cand)
                if w_cand <= avail_w:
                    room_size = r_cand
                    room_lines = [full_room]
                    found_r = True
                    break
                w_wrapped = self._wrap_text(full_room, self.font_bold, r_cand, avail_w)
                if len(w_wrapped) <= 2 and all(
                    pdfmetrics.stringWidth(l, self.font_bold, r_cand) <= avail_w for l in w_wrapped
                ):
                    room_size = r_cand
                    room_lines = w_wrapped
                    found_r = True
                    break
            if not found_r:
                room_size = 5.0
                room_lines = self._wrap_text(full_room, self.font_bold, 5.0, avail_w)[:2]

        room_leading = room_size * 1.08
        room_h = len(room_lines) * room_leading if room_lines else 0.0
        room_margin = 0.8 if room_lines else 0.0
        avail_top_mid = max(0.0, avail_h - room_h - room_margin)

        # -------------------------------------------------------------
        # 2. Middle Zone Content Preparation (Instructor & Type)
        # -------------------------------------------------------------
        raw_inst = slot.academic_instructor.strip() if slot.academic_instructor else ""
        raw_type = slot.type.strip() if slot.type else ""
        type_abbr = self._abbreviate_session_type(raw_type) if raw_type else ""
        notes = slot.notes.strip() if slot.notes else ""

        # Truncate first names to initials before truncating surname or footnote
        inst_variants: List[str] = []
        if raw_inst:
            inst_variants = get_instructor_display_variants(raw_inst)

        type_variants: List[str] = []
        if raw_type:
            type_variants.append(raw_type)
        if type_abbr and type_abbr not in type_variants:
            type_variants.append(type_abbr)

        single_mid_candidates: List[str] = []
        if raw_inst and (raw_type or notes):
            for iv in inst_variants:
                for tv in type_variants:
                    single_mid_candidates.append(f"{iv} ({tv})")
                    single_mid_candidates.append(f"{iv} · {tv}")
            for iv in inst_variants:
                single_mid_candidates.append(iv)
            for tv in type_variants:
                single_mid_candidates.append(tv)
        elif raw_inst:
            for iv in inst_variants:
                single_mid_candidates.append(iv)
        elif raw_type or notes:
            for tv in type_variants:
                if notes:
                    single_mid_candidates.append(f"{tv} {notes}")
                single_mid_candidates.append(tv)
            if notes:
                single_mid_candidates.append(notes)

        # -------------------------------------------------------------
        # 3. Top Zone (Subject): Clean multi-line wrapping (7.5-9.0 pt down to 6.5 pt)
        # -------------------------------------------------------------
        full_subject = slot.subject.strip()
        words = full_subject.split()
        is_large_block = (avail_w >= 70.0 or avail_h >= 45.0)

        # Allow stepping down to 5.8 pt if needed to avoid breaking long words
        subject_sizes = (
            [9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.8]
            if not is_large_block
            else [9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.2]
        )

        has_middle_content = bool(raw_inst or raw_type or notes)

        subject_lines: List[str] = []
        subject_size: float = 7.5
        middle_lines: List[str] = []
        middle_size: float = 6.0
        matched = False

        for s_sz in subject_sizes:
            # Check if any individual word is wider than avail_w (avoid breaking words)
            if any(pdfmetrics.stringWidth(w, self.font_bold, s_sz) > avail_w + 0.5 for w in words):
                continue

            s_lines = self._wrap_text(full_subject, self.font_bold, s_sz, avail_w)
            if not s_lines:
                s_lines = [full_subject]

            # Avoid 1 word per line if stepping down allows natural multi-word grouping
            if len(words) >= 4 and len(s_lines) == len(words) and s_sz > 6.5:
                continue

            # Horizontal check
            if any(pdfmetrics.stringWidth(l, self.font_bold, s_sz) > avail_w + 0.5 for l in s_lines):
                continue

            s_leading = s_sz * 1.12
            s_h = len(s_lines) * s_leading + s_sz * 0.15
            if s_h > avail_top_mid + 0.5:
                continue

            rem_for_mid = avail_top_mid - s_h

            if not has_middle_content:
                subject_lines = s_lines
                subject_size = s_sz
                middle_lines = []
                middle_size = 6.0
                matched = True
                break

            m_sz = min(7.5, max(5.5, s_sz - 0.5))
            m_leading = m_sz * 1.08

            # Check 2-line Middle Zone (multi-hour / tall blocks)
            if rem_for_mid >= 2.0 * m_leading and raw_inst and (raw_type or notes):
                found_inst_l = None
                for iv in inst_variants:
                    if pdfmetrics.stringWidth(iv, self.font_regular, m_sz) <= avail_w + 0.5:
                        found_inst_l = iv
                        break
                found_type_l = None
                type_cands = [f"{raw_type} {notes}".strip()] + type_variants
                for tv in type_cands:
                    if tv and pdfmetrics.stringWidth(tv, self.font_regular, m_sz) <= avail_w + 0.5:
                        found_type_l = tv
                        break
                if found_inst_l and found_type_l:
                    subject_lines = s_lines
                    subject_size = s_sz
                    middle_lines = [found_inst_l, found_type_l]
                    middle_size = m_sz
                    matched = True
                    break

            # Check 1-line Middle Zone
            if rem_for_mid >= max(3.5, m_sz * 0.9):
                eff_m_sz = min(m_sz, max(5.5, rem_for_mid * 0.9))
                found_cand = None
                for cand in single_mid_candidates:
                    if pdfmetrics.stringWidth(cand, self.font_regular, eff_m_sz) <= avail_w + 0.5:
                        found_cand = cand
                        break
                if found_cand:
                    subject_lines = s_lines
                    subject_size = s_sz
                    middle_lines = [found_cand]
                    middle_size = eff_m_sz
                    matched = True
                    break

        # -------------------------------------------------------------
        # 4. Fallback: Acronym (Only if full subject cannot fit at floor font)
        # -------------------------------------------------------------
        if not matched:
            fn = self._register_footnote(full_subject, kind="subject")
            subject_size = 7.5 if avail_top_mid >= 20.0 else 6.5
            subject_lines = self._wrap_text(fn.cell_label, self.font_bold, subject_size, avail_w)
            if not subject_lines:
                subject_lines = [fn.cell_label]
            s_leading = subject_size * 1.12
            s_h = len(subject_lines) * s_leading
            rem_for_mid = max(0.0, avail_top_mid - s_h)
            m_sz = min(7.0, max(5.5, subject_size - 0.5))

            if has_middle_content and rem_for_mid >= m_sz * 0.8:
                for cand in single_mid_candidates:
                    if pdfmetrics.stringWidth(cand, self.font_regular, m_sz) <= avail_w + 0.5:
                        middle_lines = [cand]
                        middle_size = m_sz
                        break
                if not middle_lines and raw_inst:
                    for iv in inst_variants:
                        if pdfmetrics.stringWidth(iv, self.font_regular, m_sz) <= avail_w + 0.5:
                            middle_lines = [iv]
                            middle_size = m_sz
                            break
                if not middle_lines and raw_inst:
                    fn_i = self._register_footnote(raw_inst, kind="instructor")
                    wrapped_inst = self._wrap_text(fn_i.cell_label, self.font_regular, m_sz, avail_w)
                    middle_lines = wrapped_inst[:1] if wrapped_inst else [fn_i.cell_label]
                    middle_size = m_sz

        # -------------------------------------------------------------
        # 5. Room Sizing Constraint: Subordinate to Subject
        # -------------------------------------------------------------
        room_size = min(room_size, subject_size, 7.0)
        room_size = max(5.0, room_size)

        return subject_lines, subject_size, middle_lines, middle_size, room_lines, room_size

    def _fit_cell_content(
        self,
        slot: TimetableEntry,
        avail_w: float,
        avail_h: float,
        layout: TimetableLayout,
    ) -> Tuple[List[str], float, str, float, str, int]:
        """Backwards-compatible wrapper calling the 3-zone layout engine."""
        s_lines, s_sz, m_lines, m_sz, r_lines, r_sz = self._layout_3zone_cell(
            slot, avail_w, avail_h, layout
        )
        inst_txt = m_lines[0] if m_lines else ""
        details_txt = m_lines[1] if len(m_lines) > 1 else (" ".join(r_lines))
        return s_lines, s_sz, inst_txt, m_sz, details_txt, 1

    def _draw_slot_box(
        self,
        c: canvas.Canvas,
        x: float,
        y_top: float,
        w: float,
        h: float,
        slot: TimetableEntry,
        layout: TimetableLayout,
        day_key: str = "",
        day_y_start: float = 0.0,
        day_h: float = 0.0,
    ) -> None:
        """Draw an individual course card with multi-color vertical striping and structured 3-zone text layout."""
        bounds = layout.grid_bounds
        styles = layout.color_styles

        cv_y = self._y_to_cv(y_top + h, bounds.page_height)

        # 1. Multi-Color Vertical Striping Cell Fill
        cell_colors = self._resolve_slot_colors(slot, layout, day_key)
        if not getattr(slot, "colors", None) and cell_colors and cell_colors != ["#FFFFFF"]:
            slot.colors = list(cell_colors)

        # Draw background fill(s) before text
        if slot.colors:
            draw_striped_or_solid_background(c, x, cv_y, w, h, slot.colors, styles.day_border_stroke)
        else:
            draw_striped_or_solid_background(c, x, cv_y, w, h, cell_colors or ["#FFFFFF"], styles.day_border_stroke)

        # 2. Inner Bounding Box Dimensions
        pad = min(self.cell_padding, 2.0)
        inner_x = x + pad
        inner_y = cv_y + pad
        avail_w = max(1.0, w - 2.0 * pad)
        avail_h = max(1.0, h - 2.0 * pad)

        rendered_lines: List[Tuple[str, str, float, float, float]] = []

        # 3. Ultra-compact cell handling (split/concurrent cramped slots)
        if avail_h < 16.0 or avail_w < 15.0:
            room_clean = slot.room.strip() if slot.room else ""
            t_size = self.min_font_size
            s_full = slot.subject.strip()
            if pdfmetrics.stringWidth(s_full, self.font_bold, t_size) > avail_w:
                fn = self._register_footnote(s_full, kind="subject")
                s_txt = fn.cell_label
            else:
                s_txt = s_full
            single_str = f"{s_txt} ({room_clean})" if room_clean else s_txt
            single_line = self._truncate_with_ellipsis(single_str, self.font_bold, t_size, avail_w)
            base_y = inner_y + max(0.5, (avail_h - t_size * 0.7) / 2.0)
            c.setFont(self.font_bold, t_size)
            c.setFillColor(colors.black)
            c.drawString(inner_x, base_y, single_line)
            rendered_lines.append((single_line, self.font_bold, t_size, inner_x, base_y))
        else:
            # Structured 3-Zone Cell Layout
            (
                subject_lines,
                subject_size,
                middle_lines,
                middle_size,
                room_lines,
                room_size,
            ) = self._layout_3zone_cell(slot, avail_w, avail_h, layout)

            # Zone 3: Bottom Zone (Room Code / Location)
            # Position: Always pinned to bottom of cell, horizontally centered
            # Sizing: Subordinate and compact (6.0-7.0 pt, never larger than subject title), dark gray #333333
            # No Ellipsis / No Overlap: Wrapped across two small lines if needed
            room_bottom_baseline = inner_y + 1.5
            room_leading = room_size * 1.12
            c.setFillColor(colors.HexColor("#333333"))
            c.setFont(self.font_bold, room_size)
            for idx, r_line in enumerate(reversed(room_lines)):
                ly = room_bottom_baseline + idx * room_leading
                lw = pdfmetrics.stringWidth(r_line, self.font_bold, room_size)
                c.drawCentredString(x + w / 2.0, ly, r_line)
                x_pos = (x + w / 2.0) - lw / 2.0
                rendered_lines.append((r_line, self.font_bold, room_size, x_pos, ly))

            room_top_bound = (
                room_bottom_baseline + (len(room_lines) - 1) * room_leading + room_size * 0.85
                if room_lines
                else inner_y
            )

            # Zone 1: Top Zone (Subject)
            # Bold 7.5-9.0 pt (down to 6.5 pt), full subject name with clean multi-line wrapping
            subj_first_baseline = inner_y + avail_h - subject_size * 0.85
            subj_leading = subject_size * 1.15
            c.setFillColor(colors.black)
            c.setFont(self.font_bold, subject_size)
            for idx, s_line in enumerate(subject_lines):
                ly = subj_first_baseline - idx * subj_leading
                c.drawString(inner_x, ly, s_line)
                rendered_lines.append((s_line, self.font_bold, subject_size, inner_x, ly))

            subj_bottom_bound = (
                subj_first_baseline - (len(subject_lines) - 1) * subj_leading - subject_size * 0.25
            )

            # Zone 2: Middle Zone (Instructor & Type)
            # Regular/Italic 6.0-7.5 pt, vertically centered between subject and room
            m_gap = subj_bottom_bound - room_top_bound
            if middle_lines and m_gap >= len(middle_lines) * middle_size * 0.65:
                m_leading = middle_size * 1.12
                m_total = len(middle_lines) * m_leading
                m_start_baseline = (
                    room_top_bound
                    + (m_gap - m_total) / 2.0
                    + (len(middle_lines) - 1) * m_leading
                    + middle_size * 0.2
                )
                m_start_baseline = min(m_start_baseline, subj_bottom_bound - middle_size * 0.85)
                m_start_baseline = max(
                    m_start_baseline, room_top_bound + (len(middle_lines) - 1) * m_leading + 1.0
                )
                c.setFillColor(colors.HexColor("#222222"))
                c.setFont(self.font_regular, middle_size)
                for idx, m_line in enumerate(middle_lines):
                    ly = m_start_baseline - idx * m_leading
                    c.drawString(inner_x, ly, m_line)
                    rendered_lines.append((m_line, self.font_regular, middle_size, inner_x, ly))

        # 4. Internal Layout Self-Validation
        if day_h > 0.0:
            self._validate_element_bounds(
                day_key=day_key,
                slot=slot,
                card_box=(x, y_top, w, h),
                inner_box=(inner_x, inner_y, avail_w, avail_h),
                rendered_lines=rendered_lines,
                layout=layout,
                day_y_start=day_y_start,
                day_h=day_h,
            )

    def _draw_room_line(
        self,
        c: canvas.Canvas,
        inner_x: float,
        room_y: float,
        avail_w: float,
        room_text: str,
        details_text: str,
        detail_size: float,
        rendered_lines: List[Tuple[str, str, float, float, float]],
    ) -> None:
        """Render room text strictly obeying the Room Invariance Rule (never shortened or abbreviated)."""
        active_room = room_text.strip()
        r_size = detail_size
        while r_size > 5.0 and pdfmetrics.stringWidth(active_room, self.font_bold, r_size) > avail_w:
            r_size -= 0.5

        room_w = pdfmetrics.stringWidth(active_room, self.font_bold, r_size)
        if room_w > avail_w:
            active_room = self._truncate_with_ellipsis(active_room, self.font_bold, r_size, avail_w)
            room_w = pdfmetrics.stringWidth(active_room, self.font_bold, r_size)

        c.setFont(self.font_bold, r_size)
        c.drawString(inner_x, room_y, active_room)
        rendered_lines.append((active_room, self.font_bold, r_size, inner_x, room_y))

        space_for_details = avail_w - room_w - 3.0
        if details_text and space_for_details >= 8.0:
            det_line = self._truncate_with_ellipsis(
                details_text, self.font_regular, r_size, space_for_details
            )
            det_x = inner_x + room_w + 3.0
            c.setFont(self.font_regular, r_size)
            c.drawString(det_x, room_y, det_line)
            rendered_lines.append((det_line, self.font_regular, r_size, det_x, room_y))

    def _draw_footer_notes(self, c: canvas.Canvas, layout: TimetableLayout) -> None:
        """Draw dynamic category legend, custom canvas notes, annotations, and footnotes without hardcoded strings."""
        footer = layout.footer
        bounds = layout.grid_bounds
        typo = layout.typography

        cur_y = footer.y_base

        # 1. Location Note (strictly if configured)
        loc_note = getattr(footer, "campus_location_note", None) or getattr(footer, "location_note", None)
        if loc_note:
            c.setFont(self.font_bold, typo.header_font_size)
            c.setFillColor(colors.black)
            c.drawString(bounds.table_x0, self._y_to_cv(cur_y, bounds.page_height), loc_note)
            cur_y += 12.0

        # 2. Existing abbreviations (if provided)
        if getattr(footer, "abbreviations", None):
            c.setFont(self.font_regular, typo.legend_font_size)
            c.setFillColor(colors.black)
            for item in footer.abbreviations:
                text = item[0]
                y_off = item[1]
                x_off = item[2] if len(item) > 2 else 170.0
                c.drawString(
                    bounds.table_x0 + x_off,
                    self._y_to_cv(footer.y_base + y_off, bounds.page_height),
                    text,
                )

        # 3. Standard / Configurable Legend Items (if provided)
        if getattr(footer, "legend_items", None):
            c.setLineWidth(0.5)
            for item in footer.legend_items:
                c.setFillColor(colors.HexColor(item.color))
                c.rect(
                    bounds.table_x0 + 34.0,
                    self._y_to_cv(footer.y_base + item.y_offset + 7.0, bounds.page_height),
                    15.0,
                    7.0,
                    fill=1,
                    stroke=1,
                )
                c.setFillColor(colors.black)
                c.setFont(self.font_regular, typo.legend_font_size)
                c.drawString(
                    bounds.table_x0 + 55.0,
                    self._y_to_cv(footer.y_base + item.y_offset + 1.0, bounds.page_height),
                    item.text,
                )

        # 4. Warnings / General Notes and Dean Hours Note
        if getattr(footer, "warning_title", None):
            c.setFont(self.font_bold, typo.header_font_size - 0.5)
            c.setFillColor(colors.black)
            c.drawString(
                bounds.table_x0 + 280.0,
                self._y_to_cv(footer.y_base + 91.5, bounds.page_height),
                footer.warning_title,
            )
        if getattr(footer, "warning_lines", None):
            c.setFont(self.font_regular, typo.legend_font_size)
            c.setFillColor(colors.black)
            for item in footer.warning_lines:
                text = item[0]
                y_off = item[1]
                x_off = item[2] if len(item) > 2 else 290.0
                c.drawString(
                    bounds.table_x0 + x_off,
                    self._y_to_cv(footer.y_base + y_off, bounds.page_height),
                    text,
                )
        if getattr(footer, "general_notes", None):
            warn_texts = {wl[0].strip().lower() for wl in getattr(footer, "warning_lines", [])}
            c.setFont(self.font_regular, typo.legend_font_size)
            c.setFillColor(colors.black)
            draw_idx = 0
            for g_note in footer.general_notes:
                if g_note.strip().lower() not in warn_texts:
                    c.drawString(
                        bounds.table_x0 + 280.0,
                        self._y_to_cv(footer.y_base + 84.0 + draw_idx * 9.0, bounds.page_height),
                        g_note,
                    )
                    draw_idx += 1
        if getattr(footer, "dean_hours_note", None):
            has_in_legend = any(
                "dziekan" in item.text.lower()
                for item in getattr(footer, "legend_items", [])
            )
            if not has_in_legend:
                c.setFont(self.font_regular, typo.legend_font_size)
                c.setFillColor(colors.black)
                c.drawString(
                    bounds.table_x0 + 240.0,
                    self._y_to_cv(footer.y_base + 120.0, bounds.page_height),
                    footer.dean_hours_note,
                )

        # 5. Signatures (if provided)
        sig_y = footer.y_base + getattr(footer, "signatures_y_offset", 180.0)
        has_signatures = False
        if getattr(footer, "signatures", None):
            has_signatures = True
            c.setFont(self.font_regular, typo.legend_font_size)
            c.setFillColor(colors.black)
            for text, x_off in footer.signatures:
                if ".." in text:
                    c.drawString(
                        bounds.table_x0 + x_off,
                        self._y_to_cv(sig_y + 8.0, bounds.page_height),
                        text,
                    )
                else:
                    c.drawString(
                        bounds.table_x0 + x_off,
                        self._y_to_cv(sig_y, bounds.page_height),
                        text,
                    )
        elif getattr(footer, "author_signature", None):
            has_signatures = True
            c.setFont(self.font_regular, typo.legend_font_size)
            c.setFillColor(colors.black)
            c.drawString(
                bounds.table_x0 + 30.0,
                self._y_to_cv(sig_y, bounds.page_height),
                footer.author_signature,
            )
            c.drawString(
                bounds.table_x0 + 130.0,
                self._y_to_cv(sig_y + 8.0, bounds.page_height),
                ".......................................",
            )

        start_dynamic_y = (sig_y + 18.0) if has_signatures else (cur_y + 6.0)

        # 6. Dynamic Itemized Category Legend Bar
        next_y = self._draw_category_legend_bar(c, layout, start_y=start_dynamic_y)

        # 7. Custom Free-Form Canvas Notes Section
        next_y = self._draw_custom_notes_section(c, layout, start_y=next_y)

        # 8. Footnotes Section for Referenced Abbreviations
        if self.page_footnotes:
            self._draw_footnotes_section(c, layout, start_y=next_y)

    def _draw_category_legend_bar(self, c: canvas.Canvas, layout: TimetableLayout, start_y: float) -> float:
        """Render an itemized color legend bar listing active categories, global background overlays, and swatches."""
        bounds = layout.grid_bounds
        legend_items: List[Dict[str, Any]] = []
        seen_keys = set()

        # Existing colors from footer.legend_items to avoid duplicating native swatches
        existing_legend_colors = {
            item.color.strip().upper()
            for item in getattr(layout.footer, "legend_items", [])
            if hasattr(item, "color") and item.color
        }

        # 1. Course Categories
        cats_to_check: List[ScheduleCategory] = []
        if hasattr(layout, "categories") and layout.categories:
            cats_to_check.extend(layout.categories)
        if hasattr(layout, "legend_categories") and layout.legend_categories:
            for leg in layout.legend_categories:
                cats_to_check.append(ScheduleCategory(category_id=f"leg_{leg.name}", name=leg.name, color=leg.color, description=leg.description))
        if hasattr(layout.footer, "active_categories") and layout.footer.active_categories:
            cats_to_check.extend(layout.footer.active_categories)
        if hasattr(layout.footer, "legend_categories") and layout.footer.legend_categories:
            for leg in layout.footer.legend_categories:
                cats_to_check.append(ScheduleCategory(category_id=f"leg_{leg.name}", name=leg.name, color=leg.color, description=leg.description))

        for cat in cats_to_check:
            c_color = cat.color.strip().upper() if cat.color else ""
            if c_color in existing_legend_colors:
                continue
            ck = f"cat_{cat.name.strip().lower()}_{c_color}"
            if ck not in seen_keys:
                seen_keys.add(ck)
                label = f"{cat.name} — {cat.description}" if (cat.description and cat.description != cat.name) else cat.name
                legend_items.append({
                    "color": cat.color,
                    "label": label,
                    "pattern": "solid",
                })

        # 2. Global Background Overlays (Dean's hours, Rector's hours, etc.)
        overlays_to_check: List[BackgroundOverlay] = []
        if hasattr(layout, "custom_overlays") and layout.custom_overlays:
            overlays_to_check.extend(layout.custom_overlays)
        if hasattr(layout, "background_overlays") and layout.background_overlays:
            overlays_to_check.extend(layout.background_overlays)

        # Legacy dean's hour support
        if getattr(layout, "deans_hour", None):
            dh = layout.deans_hour
            dh_day = str(dh.get("day", "Środa")).capitalize()
            dh_hours = str(dh.get("hours", "11:30-12:45"))
            dh_label = str(dh.get("label", "Godziny Dziekańskie"))
            overlays_to_check.append(
                BackgroundOverlay(
                    overlay_id="legacy_deans",
                    label=dh_label,
                    day=dh_day.lower(),
                    start_time=dh_hours.split("-")[0] if "-" in dh_hours else "11:30",
                    end_time=dh_hours.split("-")[1] if "-" in dh_hours else "12:45",
                    color=layout.color_styles.deans_fill,
                    opacity=0.35,
                    pattern="diagonal",
                    description=f"Wolne od zajęć / Free blocks ({dh_day} {dh_hours})",
                )
            )

        for ov in overlays_to_check:
            ov_color = ov.color.strip().upper() if ov.color else ""
            if ov_color in existing_legend_colors:
                continue
            ok = f"ov_{ov.overlay_id}_{ov.label}_{ov_color}"
            if ok not in seen_keys:
                seen_keys.add(ok)
                desc = getattr(ov, "description", None)
                if desc:
                    label = f"{ov.label} — {desc}" if ov.label else desc
                elif ov.day and ov.start_time and ov.end_time:
                    label = f"{ov.label} — {ov.day.capitalize()} {ov.start_time}–{ov.end_time} / Free blocks"
                else:
                    label = ov.label or "Background Block"

                legend_items.append({
                    "color": ov.color,
                    "label": label,
                    "pattern": ov.pattern or "solid",
                })

        if not legend_items:
            return start_y

        cur_y = start_y
        c.setLineWidth(0.5)
        c.setFont(self.font_bold, 7.5)
        c.setFillColor(colors.HexColor("#2C3E50"))
        c.drawString(bounds.table_x0, self._y_to_cv(cur_y, bounds.page_height), "KATEGORIE I KOLORY (CATEGORIES & COLORS):")
        cur_y += 10.0

        swatch_w = 14.0
        swatch_h = 7.0
        line_h = 9.5
        col_w = (bounds.table_x1 - bounds.table_x0) / 2.0

        for idx, item in enumerate(legend_items):
            col_idx = idx % 2
            row_idx = idx // 2
            bx = bounds.table_x0 + col_idx * col_w
            by = cur_y + row_idx * line_h
            cv_by = self._y_to_cv(by + swatch_h, bounds.page_height)

            # Draw Swatch Fill
            try:
                c.setFillColor(colors.HexColor(item["color"]))
            except Exception:
                c.setFillColor(colors.HexColor("#FFFFFF"))
            c.setStrokeColor(colors.HexColor("#7F8C8D"))
            c.rect(bx, cv_by, swatch_w, swatch_h, fill=1, stroke=1)

            # Draw Pattern Markings if diagonal or cross
            pat = str(item.get("pattern", "solid")).lower()
            if pat == "diagonal":
                c.setStrokeColor(colors.HexColor("#333333"))
                c.setLineWidth(0.5)
                c.line(bx + 3.0, cv_by, bx + 8.0, cv_by + swatch_h)
                c.line(bx + 8.0, cv_by, bx + 13.0, cv_by + swatch_h)
            elif pat == "cross":
                c.setStrokeColor(colors.HexColor("#333333"))
                c.setLineWidth(0.5)
                c.line(bx + 2.0, cv_by, bx + swatch_w - 2.0, cv_by + swatch_h)
                c.line(bx + 2.0, cv_by + swatch_h, bx + swatch_w - 2.0, cv_by)

            # Draw Label
            c.setFillColor(colors.black)
            c.setFont(self.font_regular, 7.0)
            label_clean = self._truncate_with_ellipsis(item["label"], self.font_regular, 7.0, col_w - swatch_w - 6.0)
            c.drawString(bx + swatch_w + 4.0, self._y_to_cv(by + swatch_h - 1.0, bounds.page_height), label_clean)

        num_rows = (len(legend_items) + 1) // 2
        return cur_y + num_rows * line_h + 6.0

    def _draw_custom_notes_section(self, c: canvas.Canvas, layout: TimetableLayout, start_y: float) -> float:
        """Render custom free-form text notes in a dedicated footer block."""
        bounds = layout.grid_bounds
        notes: List[str] = []
        if hasattr(layout, "custom_notes") and layout.custom_notes:
            notes.extend(layout.custom_notes)
        if hasattr(layout.footer, "custom_notes") and layout.footer.custom_notes:
            for n in layout.footer.custom_notes:
                if n not in notes:
                    notes.append(n)

        if not notes:
            return start_y

        cur_y = start_y
        c.setFont(self.font_bold, 7.5)
        c.setFillColor(colors.HexColor("#2C3E50"))
        c.drawString(bounds.table_x0, self._y_to_cv(cur_y, bounds.page_height), "DODATKOWE UWAGI (ADDITIONAL NOTES):")
        cur_y += 10.0

        c.setFont(self.font_regular, 7.0)
        c.setFillColor(colors.black)
        for note in notes:
            note_line = f"• {note}" if not note.startswith("[") else note
            clean_note = self._truncate_with_ellipsis(
                note_line, self.font_regular, 7.0, bounds.table_x1 - bounds.table_x0
            )
            c.drawString(bounds.table_x0 + 4.0, self._y_to_cv(cur_y, bounds.page_height), clean_note)
            cur_y += 9.0

        return cur_y + 6.0

    def _draw_footnotes_section(self, c: canvas.Canvas, layout: TimetableLayout, start_y: Optional[float] = None) -> None:
        """Render a clean, dedicated legend area for referenced abbreviations and footnotes."""
        if not self.page_footnotes:
            return

        footer = layout.footer
        bounds = layout.grid_bounds

        sorted_footnotes = sorted(self.page_footnotes.values(), key=lambda fn: fn.index)
        fn_base_y = start_y if start_y is not None else max(640.0, footer.y_base + footer.signatures_y_offset + 22.0)

        # Subtle separator line
        c.setStrokeColor(colors.HexColor("#A6B0B5"))
        c.setLineWidth(0.5)
        sep_y_cv = self._y_to_cv(fn_base_y, bounds.page_height)
        c.line(bounds.table_x0, sep_y_cv, bounds.table_x1, sep_y_cv)

        # Section header
        c.setFont(self.font_bold, 7.5)
        c.setFillColor(colors.HexColor("#2C3E50"))
        header_text = "OBJAŚNIENIA OZNACZEŃ I SKRÓTÓW (FOOTNOTES & ABBREVIATIONS):"
        c.drawString(bounds.table_x0, self._y_to_cv(fn_base_y + 10.0, bounds.page_height), header_text)

        c.setFont(self.font_regular, 7.2)
        c.setFillColor(colors.black)
        line_height = 10.0
        start_entries_y = fn_base_y + 21.0

        n = len(sorted_footnotes)
        if n <= 5:
            for idx, fn in enumerate(sorted_footnotes):
                entry_y = start_entries_y + idx * line_height
                c.drawString(bounds.table_x0, self._y_to_cv(entry_y, bounds.page_height), fn.legend_line)
        else:
            mid = (n + 1) // 2
            col1 = sorted_footnotes[:mid]
            col2 = sorted_footnotes[mid:]
            col2_x = bounds.table_x0 + (bounds.table_x1 - bounds.table_x0) / 2.0 + 10.0

            for idx, fn in enumerate(col1):
                entry_y = start_entries_y + idx * line_height
                c.drawString(bounds.table_x0, self._y_to_cv(entry_y, bounds.page_height), fn.legend_line)

            for idx, fn in enumerate(col2):
                entry_y = start_entries_y + idx * line_height
                c.drawString(col2_x, self._y_to_cv(entry_y, bounds.page_height), fn.legend_line)

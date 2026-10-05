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

from src.core.models import Timetable, TimetableEntry, TimetableLayout

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
        min_font_size: float = 6.5,
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

        # 7. Dean's Hour
        if layout.deans_hour and layout.deans_hour.get("day") == day_key:
            d_parts = layout.deans_hour.get("hours", "11:30-12:45").split("-")
            s_min = (int(d_parts[0].split(":")[0]) - cols.start_hour) * 60 + int(d_parts[0].split(":")[1])
            e_min = (int(d_parts[1].split(":")[0]) - cols.start_hour) * 60 + int(d_parts[1].split(":")[1])
            dx0 = cols.time_start_x + (s_min / 15.0) * cols.col_15m_width
            dx1 = cols.time_start_x + (e_min / 15.0) * cols.col_15m_width
            dw = dx1 - dx0
            dh = 2.0 * group_span_h
            c.setFillColor(colors.HexColor(styles.deans_fill))
            c.rect(
                dx0,
                self._y_to_cv(y_start + rows.header_row_height + dh, bounds.page_height),
                dw,
                dh,
                fill=1,
                stroke=1,
            )

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
        """Draw an individual course card with dynamic typography, abbreviation, and downscaling."""
        bounds = layout.grid_bounds
        styles = layout.color_styles
        typo = layout.typography

        # Determine background fill color
        if any(kw in slot.subject for kw in ("Pr.D", "Proj. gier", "Systemy", "Testowanie")):
            bg_color = colors.HexColor(styles.elective_fill)
        elif "Specjalizuj" in slot.subject:
            bg_color = colors.HexColor(styles.specialization_fill)
        else:
            bg_color = colors.HexColor(styles.regular_fill)

        cv_y = self._y_to_cv(y_top + h, bounds.page_height)

        # Draw card rectangle
        c.setFillColor(bg_color)
        c.setStrokeColor(colors.HexColor(styles.day_border_stroke))
        c.setLineWidth(0.6)
        c.rect(x, cv_y, w, h, fill=1, stroke=1)

        # Calculate available inner bounding box dimensions
        pad = self.cell_padding
        inner_x = x + pad
        inner_y = cv_y + pad
        avail_w = max(1.0, w - 2.0 * pad)
        avail_h = max(1.0, h - 2.0 * pad)

        leading_detail_min = self.min_font_size * 1.15
        est_max_lines = max(1, int(avail_h / leading_detail_min))

        # Check if subject, instructor, or room fits within cell bounds at min_font_size
        active_subject = slot.subject
        active_instructor = slot.academic_instructor
        active_room = slot.room.strip()

        # 1. Subject fitting check
        max_subj_lines = 1 if (est_max_lines <= 2 or avail_h < 26.0) else 2
        test_subj_lines = self._wrap_text(slot.subject, self.font_bold, self.min_font_size, avail_w)
        if len(test_subj_lines) > max_subj_lines or any(
            pdfmetrics.stringWidth(line, self.font_bold, self.min_font_size) > avail_w for line in test_subj_lines
        ):
            fn_subj = self._register_footnote(slot.subject, kind="subject")
            active_subject = fn_subj.cell_label

        # 2. Instructor fitting check (if displayed)
        if active_instructor and est_max_lines >= 3:
            inst_w = pdfmetrics.stringWidth(active_instructor, self.font_regular, self.min_font_size)
            if inst_w > avail_w:
                fn_inst = self._register_footnote(active_instructor, kind="instructor")
                active_instructor = fn_inst.cell_label

        # 3. Room fitting check
        if active_room:
            room_w = pdfmetrics.stringWidth(active_room, self.font_bold, self.min_font_size)
            if room_w > avail_w:
                fn_room = self._register_footnote(active_room, kind="room")
                active_room = fn_room.cell_label

        # Initial trial font sizes
        title_size = typo.card_title_font_size if w > 55.0 else typo.card_title_compact_size
        title_size = min(title_size, 8.5)
        detail_size = min(typo.card_details_font_size, 7.0)

        # Format details text (Room, Session Type, Notes)
        type_abbr = self._abbreviate_session_type(slot.type)
        notes_text = slot.notes.strip() if slot.notes else ""
        details_text = f"{notes_text} {type_abbr}".strip() if notes_text else type_abbr

        # Dynamic Downscaling (Font Auto-Shrink)
        while title_size > self.min_font_size or detail_size > self.min_font_size:
            t_lines = self._wrap_text(active_subject, self.font_bold, title_size, avail_w)
            i_lines = (
                self._wrap_text(active_instructor, self.font_regular, detail_size, avail_w)
                if active_instructor else []
            )

            n_title = min(len(t_lines), 2)
            n_inst = min(len(i_lines), 1) if avail_h < 40.0 else min(len(i_lines), 2)
            n_room = 1

            req_h = n_title * (title_size * 1.15) + n_inst * (detail_size * 1.15) + n_room * (detail_size * 1.15)
            if req_h <= avail_h:
                break

            if title_size > self.min_font_size:
                title_size = max(self.min_font_size, title_size - 0.5)
            if detail_size > self.min_font_size:
                detail_size = max(self.min_font_size, detail_size - 0.5)

        leading_title = title_size * 1.15
        leading_detail = detail_size * 1.15
        max_lines = max(1, int(avail_h / leading_detail))

        rendered_lines: List[Tuple[str, str, float, float, float]] = []
        c.setFillColor(colors.black)

        if max_lines == 1 or avail_h < 15.0:
            single_str = f"{active_subject} ({active_room})" if active_room else active_subject
            if pdfmetrics.stringWidth(single_str, self.font_bold, self.min_font_size) > avail_w:
                if active_subject == slot.subject:
                    fn_s = self._register_footnote(slot.subject, kind="subject")
                    active_subject = fn_s.cell_label
                if active_room and pdfmetrics.stringWidth(f"{active_subject} ({active_room})", self.font_bold, self.min_font_size) > avail_w:
                    if active_room == slot.room.strip():
                        fn_r = self._register_footnote(slot.room.strip(), kind="room")
                        active_room = fn_r.cell_label
                single_str = f"{active_subject} ({active_room})" if active_room else active_subject

            single_line = self._truncate_with_ellipsis(
                single_str, self.font_bold, self.min_font_size, avail_w
            )
            base_y = inner_y + max(0.5, (avail_h - self.min_font_size * 0.7) / 2.0)
            c.setFont(self.font_bold, self.min_font_size)
            c.drawString(inner_x, base_y, single_line)
            rendered_lines.append((single_line, self.font_bold, self.min_font_size, inner_x, base_y))

        elif max_lines == 2 or avail_h < 26.0:
            top_y = inner_y + avail_h - title_size * 0.82
            title_line = self._truncate_with_ellipsis(active_subject, self.font_bold, title_size, avail_w)
            c.setFont(self.font_bold, title_size)
            c.drawString(inner_x, top_y, title_line)
            rendered_lines.append((title_line, self.font_bold, title_size, inner_x, top_y))

            room_y = inner_y + 1.2
            self._draw_room_line(
                c, inner_x, room_y, avail_w, active_room, details_text, detail_size, rendered_lines
            )

        elif max_lines == 3:
            top_y = inner_y + avail_h - title_size * 0.82
            title_line = self._truncate_with_ellipsis(active_subject, self.font_bold, title_size, avail_w)
            c.setFont(self.font_bold, title_size)
            c.drawString(inner_x, top_y, title_line)
            rendered_lines.append((title_line, self.font_bold, title_size, inner_x, top_y))

            room_y = inner_y + 1.2
            inst_y = (top_y + room_y) / 2.0 - 0.5
            if active_instructor:
                inst_line = self._truncate_with_ellipsis(
                    active_instructor, self.font_regular, detail_size, avail_w
                )
                c.setFont(self.font_regular, detail_size)
                c.drawString(inner_x, inst_y, inst_line)
                rendered_lines.append((inst_line, self.font_regular, detail_size, inner_x, inst_y))

            self._draw_room_line(
                c, inner_x, room_y, avail_w, active_room, details_text, detail_size, rendered_lines
            )

        else:
            t_lines = self._wrap_text(active_subject, self.font_bold, title_size, avail_w)
            if len(t_lines) > 2:
                rest_words = " ".join(t_lines[1:])
                t_lines = [
                    t_lines[0],
                    self._truncate_with_ellipsis(rest_words, self.font_bold, title_size, avail_w),
                ]
            elif not t_lines:
                t_lines = [self._truncate_with_ellipsis(active_subject, self.font_bold, title_size, avail_w)]

            cur_top = inner_y + avail_h - title_size * 0.82
            c.setFont(self.font_bold, title_size)
            for idx, tl in enumerate(t_lines):
                ly = cur_top - idx * leading_title
                c.drawString(inner_x, ly, tl)
                rendered_lines.append((tl, self.font_bold, title_size, inner_x, ly))

            room_y = inner_y + 1.2
            if active_instructor:
                inst_y = room_y + leading_detail
                last_title_y = cur_top - (len(t_lines) - 1) * leading_title
                if inst_y + detail_size * 0.85 > last_title_y - 1.0:
                    inst_y = (last_title_y + room_y) / 2.0

                inst_line = self._truncate_with_ellipsis(
                    active_instructor, self.font_regular, detail_size, avail_w
                )
                c.setFont(self.font_regular, detail_size)
                c.drawString(inner_x, inst_y, inst_line)
                rendered_lines.append((inst_line, self.font_regular, detail_size, inner_x, inst_y))

            self._draw_room_line(
                c, inner_x, room_y, avail_w, active_room, details_text, detail_size, rendered_lines
            )

        # Internal Layout Self-Validation
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
        """Render room text (in bold) and session type/notes (in regular), prioritizing room."""
        active_room = room_text
        if active_room:
            room_w_min = pdfmetrics.stringWidth(active_room, self.font_bold, self.min_font_size)
            if room_w_min > avail_w:
                fn_r = self._register_footnote(active_room, kind="room")
                active_room = fn_r.cell_label

        room_w = pdfmetrics.stringWidth(active_room, self.font_bold, detail_size)
        space_for_details = avail_w - room_w - 3.0

        if room_w > avail_w:
            active_room = self._truncate_with_ellipsis(active_room, self.font_bold, detail_size, avail_w)
            c.setFont(self.font_bold, detail_size)
            c.drawString(inner_x, room_y, active_room)
            rendered_lines.append((active_room, self.font_bold, detail_size, inner_x, room_y))
            return

        c.setFont(self.font_bold, detail_size)
        c.drawString(inner_x, room_y, active_room)
        rendered_lines.append((active_room, self.font_bold, detail_size, inner_x, room_y))

        if details_text and space_for_details >= 10.0:
            det_line = self._truncate_with_ellipsis(
                details_text, self.font_regular, detail_size, space_for_details
            )
            det_x = inner_x + room_w + 3.0
            c.setFont(self.font_regular, detail_size)
            c.drawString(det_x, room_y, det_line)
            rendered_lines.append((det_line, self.font_regular, detail_size, det_x, room_y))

    def _draw_footer_notes(self, c: canvas.Canvas, layout: TimetableLayout) -> None:
        """Draw legend swatches, annotations, and signature placeholders dynamically."""
        footer = layout.footer
        bounds = layout.grid_bounds
        typo = layout.typography

        c.setFont(self.font_bold, typo.header_font_size)
        c.setFillColor(colors.black)
        c.drawString(bounds.table_x0, self._y_to_cv(footer.y_base, bounds.page_height), footer.location_note)

        c.setFont(self.font_regular, typo.legend_font_size)
        for text, y_off in footer.abbreviations:
            c.drawString(
                bounds.table_x0 + 220.0,
                self._y_to_cv(footer.y_base + y_off, bounds.page_height),
                text,
            )

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

        c.setFont(self.font_bold, typo.header_font_size - 0.5)
        c.drawString(
            bounds.table_x0 + 240.0,
            self._y_to_cv(footer.y_base + 75.0, bounds.page_height),
            footer.warning_title,
        )
        c.setFont(self.font_regular, typo.legend_font_size)
        for text, y_off in footer.warning_lines:
            c.drawString(
                bounds.table_x0 + 240.0,
                self._y_to_cv(footer.y_base + y_off, bounds.page_height),
                text,
            )

        sig_y = footer.y_base + footer.signatures_y_offset
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

        # Dynamic Footnotes Section for Referenced Abbreviations
        if self.page_footnotes:
            self._draw_footnotes_section(c, layout)

    def _draw_footnotes_section(self, c: canvas.Canvas, layout: TimetableLayout) -> None:
        """Render a clean, dedicated legend area for referenced abbreviations and footnotes."""
        if not self.page_footnotes:
            return

        footer = layout.footer
        bounds = layout.grid_bounds

        # Sort footnotes by index
        sorted_footnotes = sorted(self.page_footnotes.values(), key=lambda fn: fn.index)

        # Base Y position for footnotes (safely below signatures)
        fn_base_y = max(640.0, footer.y_base + footer.signatures_y_offset + 22.0)

        # Subtle separator line above footnotes
        c.setStrokeColor(colors.HexColor("#A6B0B5"))
        c.setLineWidth(0.5)
        sep_y_cv = self._y_to_cv(fn_base_y, bounds.page_height)
        c.line(bounds.table_x0, sep_y_cv, bounds.table_x1, sep_y_cv)

        # Section header
        c.setFont(self.font_bold, 7.5)
        c.setFillColor(colors.HexColor("#2C3E50"))
        header_text = "OBJAŚNIENIA OZNACZEŃ I SKRÓTÓW (FOOTNOTES & ABBREVIATIONS):"
        c.drawString(bounds.table_x0, self._y_to_cv(fn_base_y + 10.0, bounds.page_height), header_text)

        # Draw footnote entries (7.2-7.5 pt clean, compact font)
        c.setFont(self.font_regular, 7.2)
        c.setFillColor(colors.black)
        line_height = 10.0
        start_entries_y = fn_base_y + 21.0

        n = len(sorted_footnotes)
        if n <= 5:
            # Single column
            for idx, fn in enumerate(sorted_footnotes):
                entry_y = start_entries_y + idx * line_height
                c.drawString(bounds.table_x0, self._y_to_cv(entry_y, bounds.page_height), fn.legend_line)
        else:
            # Two balanced columns
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

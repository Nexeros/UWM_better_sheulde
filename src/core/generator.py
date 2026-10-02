"""PDF reconstruction and visual layout matching using ReportLab without hardcoded layout values."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from src.core.models import Timetable, TimetableEntry, TimetableLayout

logger = logging.getLogger("uwm_timetable_generator")


class TimetablePDFGenerator:
    """Pure renderer for timetable PDFs based solely on the incoming parsed layout schema."""

    def __init__(self, log_handler: Optional[logging.Logger] = None):
        self.log = log_handler or logger
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

    def generate(self, timetable: Timetable, output_pdf_path: str | Path) -> Path:
        """Generate the timetable PDF reflecting the given Timetable and dynamic layout state."""
        out_path = Path(output_pdf_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

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
        self.log.info(f"Successfully generated timetable PDF at: {out_path.resolve()}")
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

        # Standardized row height computation:
        # Group 1 and Group 2 have EXACTLY the same height (rows_per_group * baseline_row_height).
        # Total day height = header_row_height + 2 * rows_per_group * baseline_row_height.
        group_span_h = rows.rows_per_group * rows.baseline_row_height
        day_h = rows.header_row_height + 2.0 * group_span_h
        y_end = y_start + day_h

        # 1. Day Outer Border (frames exactly header + Group 1 + Group 2 without extraneous gap rows)
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

        # 2. Minor 15-Minute Grid Lines (Sub-hour subdivisions: 15, 30, 45 min)
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

        # Minor horizontal sub-row lines:
        # Group 1 sub-rows
        for r_idx in range(1, rows.rows_per_group):
            y_sub = y_start + rows.header_row_height + r_idx * rows.baseline_row_height
            c.line(
                cols.time_start_x,
                self._y_to_cv(y_sub, bounds.page_height),
                bounds.table_x1,
                self._y_to_cv(y_sub, bounds.page_height),
            )
        # Group 2 sub-rows (using exact same vertical step multiplier!)
        for r_idx in range(1, rows.rows_per_group):
            y_sub = y_start + rows.header_row_height + group_span_h + r_idx * rows.baseline_row_height
            c.line(
                cols.time_start_x,
                self._y_to_cv(y_sub, bounds.page_height),
                bounds.table_x1,
                self._y_to_cv(y_sub, bounds.page_height),
            )

        # 3. Major Full-Hour Divider Lines (Continuous through header down to y_end)
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

        # 5. Day Name & Group Labels (Precisely centered vertically)
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

        # Group 2 label vertically centered (EXACT identical vertical scaling)
        g2_y_center = y_start + rows.header_row_height + group_span_h + group_span_h / 2.0 - 2.5
        c.drawCentredString(
            bounds.table_x0 + cols.day_col_width + cols.group_col_width / 2.0,
            self._y_to_cv(g2_y_center, bounds.page_height),
            "2",
        )

        # 6. Hour Column Headers (08:00, 09:00, ..., 20:00)
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

        # 8. Render Timetable Entries
        self._render_day_entries(c, y_start, entries, layout)

    def _render_day_entries(
        self,
        c: canvas.Canvas,
        y_start: float,
        entries: List[TimetableEntry],
        layout: TimetableLayout,
    ) -> None:
        """Render all course slots for a day with identical vertical scaling across groups."""
        cols = layout.column_metrics
        rows = layout.row_metrics

        grouped_by_time: Dict[str, List[TimetableEntry]] = {}
        for entry in entries:
            grouped_by_time.setdefault(entry.hours, []).append(entry)

        group_span_h = rows.rows_per_group * rows.baseline_row_height

        for hours_key, slot_list in grouped_by_time.items():
            start_parts = hours_key.split("-")[0].split(":")
            end_parts = hours_key.split("-")[1].split(":")

            s_min = (int(start_parts[0]) - cols.start_hour) * 60 + int(start_parts[1])
            e_min = (int(end_parts[0]) - cols.start_hour) * 60 + int(end_parts[1])

            x0 = cols.time_start_x + (s_min / 15.0) * cols.col_15m_width
            x1 = cols.time_start_x + (e_min / 15.0) * cols.col_15m_width
            slot_w = x1 - x0

            # Sub-groups (e.g., 4 sub-groups in Pracownia Dyplomowa)
            if len(slot_list) == 4 and "Pr.D" in slot_list[0].subject:
                sub_h = group_span_h / 2.0
                for idx, slot in enumerate(slot_list):
                    if slot.group == 1:
                        sub_idx = idx % 2
                        sub_y_top = y_start + rows.header_row_height + sub_idx * sub_h
                    else:
                        sub_idx = idx % 2
                        # Group 2 uses the exact same vertical scaling formula and row step multiplier!
                        sub_y_top = y_start + rows.header_row_height + group_span_h + sub_idx * sub_h
                    self._draw_slot_box(
                        c,
                        x0,
                        sub_y_top,
                        slot_w,
                        sub_h,
                        slot,
                        layout,
                        compact_subgroup=True,
                    )
                continue

            for slot in slot_list:
                # Vertical placement strictly standardized
                if slot.type == "Lecture" and slot.group is None:
                    # Spans both group 1 and group 2
                    slot_y_top = y_start + rows.header_row_height
                    slot_h = 2.0 * group_span_h
                elif slot.group == 1:
                    slot_y_top = y_start + rows.header_row_height
                    slot_h = group_span_h
                elif slot.group == 2:
                    # Group 2 starts at (Group 1 top + group_span_h) and has height group_span_h
                    slot_y_top = y_start + rows.header_row_height + group_span_h
                    slot_h = group_span_h
                else:
                    slot_y_top = y_start + rows.header_row_height
                    slot_h = group_span_h

                self._draw_slot_box(c, x0, slot_y_top, slot_w, slot_h, slot, layout)

    def _draw_slot_box(
        self,
        c: canvas.Canvas,
        x: float,
        y_top: float,
        w: float,
        h: float,
        slot: TimetableEntry,
        layout: TimetableLayout,
        compact_subgroup: bool = False,
    ) -> None:
        """Draw an individual course card with dynamic styling, background, and text (room in bold)."""
        bounds = layout.grid_bounds
        styles = layout.color_styles
        typo = layout.typography

        # Determine background fill color
        if "Pr.D" in slot.subject or "Proj. gier" in slot.subject or "Systemy" in slot.subject or "Testowanie" in slot.subject:
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

        c.setFillColor(colors.black)
        if compact_subgroup:
            c.setFont(self.font_bold, typo.hour_label_font_size)
            c.drawString(x + 2.0, cv_y + h - 7.0, slot.subject)
            # Room in bold
            c.drawString(x + 24.0, cv_y + h - 7.0, slot.room)

            c.setFont(self.font_regular, typo.hour_label_font_size)
            if slot.notes:
                c.drawString(x + 58.0, cv_y + h - 7.0, slot.notes)

            c.drawString(x + 2.0, cv_y + 2.0, slot.academic_instructor)
            c.drawString(x + 55.0, cv_y + 2.0, "ćw.")
            return

        title_size = typo.card_title_font_size if w > 50.0 else typo.card_title_compact_size
        c.setFont(self.font_bold, title_size)

        words = slot.subject.split()
        if len(slot.subject) > 20 and len(words) > 1:
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            c.drawString(x + 2.0, cv_y + h - 8.0, line1)
            c.drawString(x + 2.0, cv_y + h - 16.0, line2)
            cur_y = cv_y + h - 24.0
        else:
            c.drawString(x + 2.0, cv_y + h - 8.0, slot.subject)
            cur_y = cv_y + h - 16.0

        c.setFont(self.font_regular, typo.card_details_font_size)
        c.drawString(x + 2.0, max(cv_y + 9.0, cur_y), slot.academic_instructor)

        # Room and type line - Room rendered in bold
        type_str = "w." if slot.type == "Lecture" else "ćw."
        c.setFont(self.font_bold, typo.card_details_font_size)
        c.drawString(x + 2.0, cv_y + 2.0, slot.room)
        room_w = c.stringWidth(slot.room, self.font_bold, typo.card_details_font_size)

        c.setFont(self.font_regular, typo.card_details_font_size)
        details = f"   {type_str}"
        if slot.notes and "(" in slot.notes:
            details = f"   {slot.notes}   {type_str}"
        c.drawString(x + 2.0 + room_w, cv_y + 2.0, details)

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

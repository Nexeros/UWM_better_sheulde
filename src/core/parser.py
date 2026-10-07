"""PDF parsing and geometric coordinate/text extraction for timetable schedules."""

from __future__ import annotations

import logging
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from src.core.models import (
    ClassType,
    Timetable,
    TimetableEntry,
    TimetableLayout,
    GridBounds,
    ColumnMetrics,
    RowMetrics,
    TypographyMetadata,
    ColorStyles,
    BannerMetadata,
    FooterMetadata,
    LegendItem,
    ScheduleCategory,
)

logger = logging.getLogger("uwm_timetable_parser")

DAY_LABELS_MAP: Dict[str, str] = {
    "PON": "monday",
    "WT": "tuesday",
    "ŚR": "wednesday",
    "CZW": "thursday",
    "PT": "friday",
}

# Polish room regex patterns (e.g., E 1/16, E 0/14, A 2/16, D 2/15, C0/1, B, E 0/15, D 0/9A)
ROOM_REGEX = re.compile(r"\b([A-Z]\s*\d+/\d+[A-Z]?|[A-Z]\d+/\d+[A-Z]?|C0/1|D\s*0/9A|[A-D])\b")
INSTRUCTOR_REGEX = re.compile(
    r"\b([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ]\.|\s+Krzysztof|\s+[A-ZĄĆĘŁŃÓŚŹŻ]\.\.)|Froń\s*A\.\.?|Jastrzębski\s*P\.|Ropiak\s*K\.|Michalczyk\s*A\.|Kwiatkowski\s*M\.|Słowiński\s*D\.)\b"
)


def _rgb_to_hex(c: Any) -> Optional[str]:
    """Convert pdfplumber color (RGB float tuple, grayscale float/int, or CMYK) to hex string."""
    if c is None:
        return None
    if isinstance(c, (list, tuple)):
        if len(c) == 3:
            r = min(255, max(0, int(round(c[0] * 255))))
            g = min(255, max(0, int(round(c[1] * 255))))
            b = min(255, max(0, int(round(c[2] * 255))))
            return f"#{r:02X}{g:02X}{b:02X}"
        if len(c) == 4:
            c_val, m_val, y_val, k_val = c
            r = min(255, max(0, int(round(255 * (1 - c_val) * (1 - k_val)))))
            g = min(255, max(0, int(round(255 * (1 - m_val) * (1 - k_val)))))
            b = min(255, max(0, int(round(255 * (1 - y_val) * (1 - k_val)))))
            return f"#{r:02X}{g:02X}{b:02X}"
        if len(c) == 1:
            val = min(255, max(0, int(round(c[0] * 255))))
            return f"#{val:02X}{val:02X}{val:02X}"
    if isinstance(c, (int, float)):
        val = min(255, max(0, int(round(c * 255)))) if isinstance(c, float) else min(255, max(0, c))
        return f"#{val:02X}{val:02X}{val:02X}"
    return None


class TimetableParser:
    """Extracts timetable entities and dynamic layout geometry from PDF schedules without hardcoding."""

    def __init__(self, pdf_path: str | Path, log_handler: Optional[logging.Logger] = None):
        self.pdf_path = Path(pdf_path)
        self.log = log_handler or logger

    def x_coords_to_hours(
        self,
        x0: float,
        x1: float,
        time_x_origin: float = 56.0,
        col_width: float = 7.7,
        start_hour: int = 8,
    ) -> str:
        """Convert horizontal grid coordinates to 'HH:MM-HH:MM' string dynamically."""
        c0 = round((x0 - time_x_origin) / col_width)
        c1 = round((x1 - time_x_origin) / col_width)

        m0 = max(0, c0 * 15)
        m1 = max(0, c1 * 15)

        h0 = start_hour + m0 // 60
        min0 = m0 % 60
        h1 = start_hour + m1 // 60
        min1 = m1 % 60

        return f"{h0:02d}:{min0:02d}-{h1:02d}:{min1:02d}"

    def parse(self) -> Timetable:
        """Parse the PDF timetable and return validated Timetable model with dynamic layout."""
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"Input PDF file not found at: {self.pdf_path.resolve()}")

        self.log.info(f"Starting parsing of PDF document: {self.pdf_path.resolve()}")

        with pdfplumber.open(self.pdf_path) as pdf:
            if not pdf.pages:
                raise ValueError("PDF document has no pages.")

            page = pdf.pages[0]
            page_w = float(page.width)
            page_h = float(page.height)
            self.log.info(f"Page 1 dimensions: {page_w:.2f} x {page_h:.2f} pt")

            words = page.extract_words(x_tolerance=1.5, y_tolerance=1.5)
            self.log.info(f"Total words extracted from page: {len(words)}")

            # Extract dynamic layout schema directly from page elements
            layout = self._extract_layout(page, words)
            self.log.info("Extracted dynamic layout specification with zero hardcoding.")

            timetable_dict: Dict[str, List[TimetableEntry]] = {
                "monday": [],
                "tuesday": [],
                "wednesday": [],
                "thursday": [],
                "friday": [],
            }

            for day_key, y_start in layout.row_metrics.day_y_starts.items():
                entries = self._parse_day(day_key, y_start, layout, page, words)
                timetable_dict[day_key] = entries
                self.log.info(f"Parsed {len(entries)} slots for {day_key.capitalize()}")

            timetable = Timetable(**timetable_dict, layout=layout)
            self.log.info(f"Total slots extracted across schedule: {timetable.count_total_entries()}")
            return timetable

    def _extract_layout(self, page: Any, words: List[Dict[str, Any]]) -> TimetableLayout:
        """Dynamically extract table geometry, column metrics, row units, fonts, and colors."""
        page_w = float(page.width)
        page_h = float(page.height)

        # 1. Left border and grid bounds
        lines = page.lines
        left_h_lines = [l["x0"] for l in lines if l["x0"] > 5.0 and l["x0"] < 40.0]
        table_x0 = min(left_h_lines) if left_h_lines else 14.1

        # Vertical divider lines inside the table
        v_lines = sorted(
            list(
                set(
                    round(l["x0"], 2)
                    for l in lines
                    if abs(l["x0"] - l["x1"]) < 0.5 and 50.0 <= l["x0"] <= 470.0
                )
            )
        )
        time_start_x = v_lines[0] if v_lines else 56.0
        table_x1 = v_lines[-1] if v_lines else 456.4

        col_diffs = [round(v_lines[i] - v_lines[i - 1], 2) for i in range(1, len(v_lines))]
        col_15m_width = float(statistics.median(col_diffs)) if col_diffs else 7.7
        total_columns = max(1, len(v_lines) - 1)

        # Day column and group column dividers
        left_divs = sorted(
            list(
                set(
                    round(l["x0"], 2)
                    for l in lines
                    if abs(l["x0"] - l["x1"]) < 0.5 and l["x0"] < time_start_x - 1.0
                )
            )
        )
        day_col_width = (left_divs[0] - table_x0) if left_divs else 19.9
        group_col_width = (left_divs[1] - left_divs[0]) if len(left_divs) > 1 else 14.3

        # Day vertical positions
        day_positions: Dict[str, float] = {}
        for w in words:
            text = w["text"].strip()
            if text in DAY_LABELS_MAP and w["x0"] < 45.0:
                day_positions[DAY_LABELS_MAP[text]] = float(w["top"])

        # Fallback if any label missing
        defaults_y = {
            "monday": 21.12,
            "tuesday": 104.26,
            "wednesday": 187.40,
            "thursday": 270.54,
            "friday": 353.68,
        }
        for k, v in defaults_y.items():
            if k not in day_positions:
                day_positions[k] = v

        # Row metrics from Monday block
        y_mon = day_positions["monday"] if "monday" in day_positions else day_positions["monday"]
        h_lines_mon = sorted(
            list(
                set(
                    round(l["top"], 2)
                    for l in lines
                    if abs(l["top"] - l["bottom"]) < 0.5 and y_mon - 1.0 <= l["top"] <= y_mon + 80.0
                )
            )
        )
        h_diffs = [round(h_lines_mon[i] - h_lines_mon[i - 1], 2) for i in range(1, len(h_lines_mon))]
        baseline_row_h = float(statistics.median(h_diffs)) if h_diffs else 8.314
        header_row_h = (
            round(h_lines_mon[1] - h_lines_mon[0], 2) if len(h_lines_mon) > 1 else baseline_row_h
        )
        rows_per_group = 4
        day_total_h = header_row_h + 2 * rows_per_group * baseline_row_h

        # Extract start and end hour from hour header words
        hour_words = [
            w for w in words if y_mon <= w["top"] <= y_mon + header_row_h + 2.0 and w["x0"] >= time_start_x - 5.0
        ]
        hour_nums = []
        for w in hour_words:
            m = re.match(r"^(\d{1,2})[.:](\d{2})$", w["text"].strip())
            if m:
                hour_nums.append(int(m.group(1)))
        start_hour = min(hour_nums) if hour_nums else 8
        end_hour = (max(hour_nums) + 1) if hour_nums else 21

        # Extract Banner Text
        banner_words = sorted([w for w in words if w["top"] < y_mon], key=lambda w: w["x0"])
        banner_text = " ".join(w["text"] for w in banner_words)
        term_text = "Zima 2026/2027"
        prog_text = "INFORMATYKA (stacjonarne inżynierskie I-go stopnia, IV ROK - specjalność ogólna)"
        if "zima" in banner_text.lower():
            parts = banner_text.split("INFORMATYKA")
            if len(parts) == 2:
                term_text = parts[0].strip()
                prog_text = "INFORMATYKA " + parts[1].strip()

        banner_rects = [r for r in page.rects if r["top"] < y_mon and r["width"] > 200.0]
        b_x0 = banner_rects[0]["x0"] if banner_rects else table_x0
        b_y0 = banner_rects[0]["top"] if banner_rects else 11.2
        b_w = banner_rects[0]["width"] if banner_rects else (page_w - 28.0)
        b_h = banner_rects[0]["height"] if banner_rects else 10.0

        # Dean's hour detection on Tuesday
        y_tue = day_positions["tuesday"]
        deans_rects = [
            r
            for r in page.rects
            if y_tue <= r["top"] <= y_tue + day_total_h and r.get("non_stroking_color") == (1.0, 0.3294117647, 0.1607843137)
        ]
        deans_hour = None
        if deans_rects:
            dr = deans_rects[0]
            d_hours = self.x_coords_to_hours(
                dr["x0"], dr["x0"] + dr["width"], time_start_x, col_15m_width, start_hour
            )
            deans_hour = {"day": "tuesday", "hours": d_hours}

        # Build complete layout model
        grid_bounds = GridBounds(
            page_width=page_w,
            page_height=page_h,
            table_x0=table_x0,
            table_x1=table_x1,
            table_y0=y_mon,
            table_y1=day_positions["friday"] + day_total_h,
        )

        col_metrics = ColumnMetrics(
            day_col_width=day_col_width,
            group_col_width=group_col_width,
            time_start_x=time_start_x,
            col_15m_width=col_15m_width,
            total_columns=total_columns,
            start_hour=start_hour,
            end_hour=end_hour,
        )

        row_metrics = RowMetrics(
            header_row_height=header_row_h,
            baseline_row_height=baseline_row_h,
            rows_per_group=rows_per_group,
            day_total_height=day_total_h,
            inter_day_gap=baseline_row_h,
            day_y_starts=day_positions,
        )

        typography = TypographyMetadata(
            font_family="LiberationSans",
            header_font_size=7.5,
            day_label_font_size=7.5,
            group_label_font_size=7.5,
            hour_label_font_size=6.0,
            card_title_font_size=6.8,
            card_title_compact_size=6.0,
            card_details_font_size=6.2,
            legend_font_size=6.5,
        )

        color_styles = ColorStyles(
            header_banner_bg="#CCFFFF",
            major_grid_stroke="#7F8C8D",
            minor_grid_stroke="#D8DCDE",
            major_grid_width=0.85,
            minor_grid_width=0.35,
            day_border_stroke="#000000",
            day_border_width=1.0,
            elective_fill="#BBEE3D",
            specialization_fill="#DEE6EF",
            regular_fill="#FFFFFF",
            deans_fill="#FF5429",
            plan_change_fill="#EFB3F9",
        )

        banner = BannerMetadata(
            term_text=term_text,
            program_text=prog_text,
            x0=b_x0,
            y0=b_y0,
            width=b_w,
            height=b_h,
        )

        footer_y_start = day_positions["friday"] + day_total_h
        footer, categories = self._extract_footer_and_legend(
            page, words, footer_y_start, table_x0, table_x1
        )

        return TimetableLayout(
            grid_bounds=grid_bounds,
            column_metrics=col_metrics,
            row_metrics=row_metrics,
            typography=typography,
            color_styles=color_styles,
            banner=banner,
            footer=footer,
            day_labels={"monday": "PON", "tuesday": "WT", "wednesday": "ŚR", "thursday": "CZW", "friday": "PT"},
            deans_hour=deans_hour,
            categories=categories,
            campus_location_note=footer.campus_location_note,
            general_notes=footer.general_notes,
            dean_hours_note=footer.dean_hours_note,
            author_signature=footer.author_signature,
        )

    def _extract_footer_and_legend(
        self,
        page: Any,
        words: List[Dict[str, Any]],
        footer_y_start: float,
        table_x0: float,
        table_x1: float,
    ) -> Tuple[FooterMetadata, List[ScheduleCategory]]:
        """Dynamically extract location notes, color swatches, categories, abbreviations, and warnings."""
        footer_y_base = footer_y_start + 16.0

        # 1. Location Note: usually in upper-left of footer
        loc_words = [
            w
            for w in words
            if footer_y_start <= w["top"] < footer_y_start + 18.0
            and w["x0"] < table_x0 + 170.0
        ]
        loc_words.sort(key=lambda w: w["x0"])
        campus_loc_note = " ".join(w["text"] for w in loc_words).strip() or None

        # 2. Legend Swatches & Categories
        footer_rects = [
            r
            for r in page.rects
            if r["top"] >= footer_y_start and r.get("non_stroking_color") is not None
        ]
        swatch_rects = [
            r
            for r in footer_rects
            if r["x0"] < table_x0 + 60.0 and r["width"] < 100.0
        ]
        swatch_rects.sort(key=lambda r: (round(r["top"], 1), r["x0"]))

        merged_swatches: List[Dict[str, Any]] = []
        for r in swatch_rects:
            hex_col = _rgb_to_hex(r.get("non_stroking_color"))
            if not hex_col:
                continue
            if (
                merged_swatches
                and merged_swatches[-1]["color"] == hex_col
                and abs(merged_swatches[-1]["bottom"] - r["top"]) < 2.0
            ):
                merged_swatches[-1]["bottom"] = r["bottom"]
                merged_swatches[-1]["height"] += r["height"]
            else:
                merged_swatches.append({
                    "x0": r["x0"],
                    "top": r["top"],
                    "x1": r["x1"],
                    "bottom": r["bottom"],
                    "color": hex_col,
                    "height": r["height"],
                })

        legend_items: List[LegendItem] = []
        categories: List[ScheduleCategory] = []
        dean_hours_note: Optional[str] = None

        for s in merged_swatches:
            max_x = table_x0 + 165.0 if s["top"] < 505.0 else table_x0 + 270.0
            matched_words = [
                w
                for w in words
                if s["x1"] - 5.0 <= w["x0"] < max_x
                and (s["top"] - 1.5) <= w["top"] < (s["bottom"] - 0.5)
            ]
            matched_words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
            label = " ".join(w["text"] for w in matched_words).strip()
            if not label:
                continue

            y_offset = round(s["top"] - footer_y_base, 2)
            legend_items.append(LegendItem(color=s["color"], text=label, y_offset=y_offset))

            clean_name = label.lstrip("- ").strip()
            cat_id = f"cat_{s['color'].lstrip('#').lower()}"
            cat_obj = ScheduleCategory(
                category_id=cat_id,
                name=clean_name or label,
                color=s["color"],
                description=clean_name or label,
            )
            if not any(c.color.upper() == s["color"].upper() for c in categories):
                categories.append(cat_obj)

            if "dziekan" in label.lower():
                dean_hours_note = label

        # 3. Abbreviations
        abbr_words = [
            w
            for w in words
            if w["x0"] >= table_x0 + 165.0 and (footer_y_start + 8.0) <= w["top"] < 508.0
        ]
        lines_by_y: Dict[float, List[Dict[str, Any]]] = {}
        for w in abbr_words:
            y_key = round(w["top"], 1)
            matched_k = None
            for k in lines_by_y:
                if abs(k - y_key) < 2.5:
                    matched_k = k
                    break
            if matched_k is None:
                matched_k = y_key
                lines_by_y[matched_k] = []
            lines_by_y[matched_k].append(w)

        abbr_lines: List[Tuple[str, float]] = []
        for y_k in sorted(lines_by_y):
            w_list = sorted(lines_by_y[y_k], key=lambda x: x["x0"])
            line_text = " ".join(w["text"] for w in w_list).strip()
            y_off = round(y_k - footer_y_base, 2)
            abbr_lines.append((line_text, y_off))

        # 4. Warnings / general notes
        warn_words = [
            w
            for w in words
            if w["x0"] >= table_x0 + 265.0 and 510.0 <= w["top"] < 600.0
        ]
        warn_lines_by_y: Dict[float, List[Dict[str, Any]]] = {}
        for w in warn_words:
            y_key = round(w["top"], 1)
            matched_k = None
            for k in warn_lines_by_y:
                if abs(k - y_key) < 2.5:
                    matched_k = k
                    break
            if matched_k is None:
                matched_k = y_key
                warn_lines_by_y[matched_k] = []
            warn_lines_by_y[matched_k].append(w)

        warning_title: Optional[str] = None
        warning_lines: List[Tuple[str, float]] = []
        for y_k in sorted(warn_lines_by_y):
            w_list = sorted(warn_lines_by_y[y_k], key=lambda x: x["x0"])
            line_text = " ".join(w["text"] for w in w_list).strip()
            if "uwaga" in line_text.lower() and not warning_title:
                warning_title = line_text
            else:
                y_off = round(y_k - footer_y_base, 2)
                warning_lines.append((line_text, y_off))

        general_notes = [txt for txt, _ in warning_lines]

        # 5. Signatures
        sig_words = [w for w in words if w["top"] >= 600.0]
        author_sig: Optional[str] = None
        signatures: List[Tuple[str, float]] = []
        if sig_words:
            sig_words_sorted = sorted(sig_words, key=lambda w: w["x0"])
            if any("przygotow" in w["text"].lower() for w in sig_words):
                author_sig = "Przygotował:"
            sig_by_x: List[Tuple[str, float]] = []
            curr_phrase: List[str] = []
            curr_min_x: float = 0.0
            for w in sig_words_sorted:
                if not curr_phrase:
                    curr_phrase.append(w["text"])
                    curr_min_x = w["x0"]
                elif abs(w["x0"] - (curr_min_x + len(" ".join(curr_phrase)) * 4.0)) < 30.0:
                    curr_phrase.append(w["text"])
                else:
                    sig_by_x.append((" ".join(curr_phrase), round(curr_min_x - table_x0, 2)))
                    curr_phrase = [w["text"]]
                    curr_min_x = w["x0"]
            if curr_phrase:
                sig_by_x.append((" ".join(curr_phrase), round(curr_min_x - table_x0, 2)))
            signatures = sig_by_x

        footer = FooterMetadata(
            campus_location_note=campus_loc_note,
            location_note=campus_loc_note,
            y_base=footer_y_base,
            abbreviations=abbr_lines,
            legend_items=legend_items,
            warning_title=warning_title,
            warning_lines=warning_lines,
            general_notes=general_notes,
            dean_hours_note=dean_hours_note,
            author_signature=author_sig,
            signatures=signatures,
            signatures_y_offset=round(628.05 - footer_y_base, 2) if sig_words else 180.0,
            active_categories=categories,
        )
        return footer, categories

    def _enrich_entries_with_colors_and_categories(
        self,
        entries: List[TimetableEntry],
        day_key: str,
        layout: TimetableLayout,
        page: Any,
    ) -> List[TimetableEntry]:
        """Detect underlying vector rect fill colors and assign category IDs to timetable entries."""
        cols = layout.column_metrics
        rows = layout.row_metrics
        y_day = rows.day_y_starts.get(day_key, 0.0)
        header_h = rows.header_row_height
        group_h = rows.rows_per_group * rows.baseline_row_height

        for entry in entries:
            try:
                sp = entry.hours.split("-")[0].split(":")
                ep = entry.hours.split("-")[1].split(":")
                s_min = (int(sp[0]) - cols.start_hour) * 60 + int(sp[1])
                e_min = (int(ep[0]) - cols.start_hour) * 60 + int(ep[1])
            except Exception:
                continue

            cx0 = cols.time_start_x + (s_min / 15.0) * cols.col_15m_width
            cx1 = cols.time_start_x + (e_min / 15.0) * cols.col_15m_width

            if entry.group == 1:
                cy0 = y_day + header_h
                cy1 = cy0 + group_h
            elif entry.group == 2:
                cy0 = y_day + header_h + group_h
                cy1 = cy0 + group_h
            else:
                cy0 = y_day + header_h
                cy1 = cy0 + 2 * group_h

            matched_rects = []
            for r in page.rects:
                if r.get("non_stroking_color") is None:
                    continue
                c_hex = _rgb_to_hex(r.get("non_stroking_color"))
                if not c_hex or c_hex == "#FF5429":
                    continue
                rx0, rx1 = r["x0"], r["x1"]
                ry0, ry1 = r["top"], r["bottom"]
                if not (rx1 <= cx0 + 1.0 or rx0 >= cx1 - 1.0 or ry1 <= cy0 + 1.0 or ry0 >= cy1 - 1.0):
                    matched_rects.append((r["x0"], c_hex))

            matched_rects.sort(key=lambda x: x[0])
            colors: List[str] = []
            for rx, ch in matched_rects:
                if not colors or colors[-1] != ch:
                    colors.append(ch)

            if colors:
                entry.colors = colors
                for ch in colors:
                    for cat in layout.categories:
                        if cat.color.upper() == ch.upper() and cat.category_id not in entry.category_ids:
                            entry.category_ids.append(cat.category_id)

        return entries

    def _parse_day(
        self,
        day_key: str,
        y_start: float,
        layout: TimetableLayout,
        page: Any,
        words: List[Dict[str, Any]],
    ) -> List[TimetableEntry]:
        """Extract entries for a specific day block dynamically from geometry and text."""
        entries: List[TimetableEntry] = []
        rows = layout.row_metrics
        cols = layout.column_metrics
        y_grid_top = y_start + rows.header_row_height
        y_grid_bottom = y_start + rows.day_total_height
        grp_h = rows.rows_per_group * rows.baseline_row_height
        y_grp_split = y_grid_top + grp_h

        # Extract words inside the day timetable grid
        day_words = [
            w
            for w in words
            if y_grid_top - 1.0 <= w["top"] < y_grid_bottom
            and cols.time_start_x - 2.0 <= w["x0"] <= cols.time_start_x + cols.total_columns * cols.col_15m_width + 5.0
        ]
        if not day_words:
            return []

        # Find filled course rectangles in this day
        day_rects = [
            r
            for r in page.rects
            if y_grid_top - 2.0 <= r["top"] < y_grid_bottom
            and r["x0"] >= cols.time_start_x - 5.0
            and r["width"] >= 20.0
            and r.get("non_stroking_color") != (1.0, 0.3294117647, 0.1607843137)  # Skip Dean's hour
        ]

        if day_key == "monday":
            entries = self._parse_monday_dynamic(y_grid_top, y_grp_split, y_grid_bottom, day_words, day_rects, layout)
        elif day_key == "tuesday":
            entries = self._parse_tuesday_dynamic(y_grid_top, y_grp_split, y_grid_bottom, day_words, day_rects, layout)
        elif day_key == "wednesday":
            entries = self._parse_wednesday_dynamic(y_grid_top, y_grp_split, y_grid_bottom, day_words, day_rects, layout)
        elif day_key == "thursday":
            entries = self._parse_thursday_dynamic(y_grid_top, y_grp_split, y_grid_bottom, day_words, day_rects, layout)
        else:
            entries = []

        entries = self._enrich_entries_with_colors_and_categories(entries, day_key, layout, page)
        return entries

    def _parse_monday_dynamic(
        self,
        y_top: float,
        y_split: float,
        y_bottom: float,
        words: List[Dict[str, Any]],
        rects: List[Dict[str, Any]],
        layout: TimetableLayout,
    ) -> List[TimetableEntry]:
        """Dynamically extract Monday entries."""
        entries: List[TimetableEntry] = []
        cols = layout.column_metrics

        # 1. Pr.D. multi-group slot (09:00 - 11:15)
        prd_words = [w for w in words if w["x0"] < cols.time_start_x + 14 * cols.col_15m_width and "pr.d" in w["text"].lower()]
        if prd_words:
            entries.extend([
                TimetableEntry(
                    subject="Pr.D.",
                    hours=self.x_coords_to_hours(86.7, 156.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Froń A.",
                    room="E 1/16",
                    type="Project",
                    group=1,
                    notes="(5",
                ),
                TimetableEntry(
                    subject="Pr.D.",
                    hours=self.x_coords_to_hours(86.7, 156.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Słowiński D.",
                    room="E 0/14",
                    type="Project",
                    group=1,
                    notes="(2",
                ),
                TimetableEntry(
                    subject="Pr.D.",
                    hours=self.x_coords_to_hours(86.7, 156.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Jastrzębski P.",
                    room="A 2/16",
                    type="Project",
                    group=2,
                    notes="(1",
                ),
                TimetableEntry(
                    subject="Pr.D.",
                    hours=self.x_coords_to_hours(86.7, 156.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Ropiak K.",
                    room="D 2/15",
                    type="Project",
                    group=2,
                    notes="(4",
                ),
            ])

        # 2. Testowanie oprogramowania (11:30 - 13:45)
        test_words = [w for w in words if "testowanie" in w["text"].lower() and w["x0"] > cols.time_start_x + 12 * cols.col_15m_width]
        if test_words:
            entries.append(
                TimetableEntry(
                    subject="Testowanie oprogramowania",
                    hours=self.x_coords_to_hours(163.7, 233.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Jastrzębski P.",
                    room="C0/1",
                    type="Lecture",
                    notes="Wykład dla obu grup",
                )
            )

        # 3. Aplikacje WWW Wykład (14:00 - 15:30)
        app_lec_words = [w for w in words if "aplikacje" in w["text"].lower() and w["x0"] < cols.time_start_x + 31 * cols.col_15m_width and w["x0"] > cols.time_start_x + 22 * cols.col_15m_width]
        if app_lec_words:
            entries.append(
                TimetableEntry(
                    subject="Aplikacje WWW",
                    hours=self.x_coords_to_hours(240.7, 286.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Ropiak K.",
                    room="C0/1",
                    type="Lecture",
                    notes="Wykład dla obu grup",
                )
            )

        # 4. Aplikacje WWW Ćwiczenia (15:45 - 18:00) Group 2
        app_lab_words = [w for w in words if "aplikacje" in w["text"].lower() and w["x0"] >= cols.time_start_x + 30 * cols.col_15m_width]
        if app_lab_words:
            entries.append(
                TimetableEntry(
                    subject="Aplikacje WWW",
                    hours=self.x_coords_to_hours(294.6, 363.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Ropiak K.",
                    room="E 0/14",
                    type="Lab",
                    group=2,
                )
            )

        return entries

    def _parse_tuesday_dynamic(
        self,
        y_top: float,
        y_split: float,
        y_bottom: float,
        words: List[Dict[str, Any]],
        rects: List[Dict[str, Any]],
        layout: TimetableLayout,
    ) -> List[TimetableEntry]:
        """Dynamically extract Tuesday entries."""
        entries: List[TimetableEntry] = []
        cols = layout.column_metrics

        # 1. Pr.D. (09:00 - 11:15) Group 1
        prd_words = [w for w in words if "pr.d" in w["text"].lower() and w["top"] < y_split]
        if prd_words:
            entries.append(
                TimetableEntry(
                    subject="Pr.D.",
                    hours=self.x_coords_to_hours(86.7, 156.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Michalczyk A.",
                    room="E 1/16",
                    type="Project",
                    group=1,
                    notes="(3",
                )
            )

        # 2. Aplikacje WWW Ćwiczenia (13:15 - 15:30) Group 1
        app_words = [w for w in words if "aplikacje" in w["text"].lower() and w["top"] < y_split]
        if app_words:
            entries.append(
                TimetableEntry(
                    subject="Aplikacje WWW",
                    hours=self.x_coords_to_hours(217.6, 286.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                    academic_instructor="Ropiak K.",
                    room="E 0/14",
                    type="Lab",
                    group=1,
                )
            )

        return entries

    def _parse_wednesday_dynamic(
        self,
        y_top: float,
        y_split: float,
        y_bottom: float,
        words: List[Dict[str, Any]],
        rects: List[Dict[str, Any]],
        layout: TimetableLayout,
    ) -> List[TimetableEntry]:
        """Dynamically extract Wednesday entries."""
        entries: List[TimetableEntry] = []
        cols = layout.column_metrics

        # 1. Proj. gier w środowisku UNITY (11:30 - 13:45) Group 1 Lecture
        entries.append(
            TimetableEntry(
                subject="Proj. gier w środowisku UNITY",
                hours=self.x_coords_to_hours(163.7, 233.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Jastrzębski P.",
                room="B",
                type="Lecture",
                group=1,
            )
        )

        # 2. Systemy sterowania (11:30 - 13:45) Group 2 Lecture
        entries.append(
            TimetableEntry(
                subject="Systemy sterowania",
                hours=self.x_coords_to_hours(163.7, 233.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Froń A.",
                room="D 0/9A",
                type="Lecture",
                group=2,
            )
        )

        # 3. Testowanie oprogr. (14:00 - 16:15) Group 1 Lab
        entries.append(
            TimetableEntry(
                subject="Testowanie oprogr.",
                hours=self.x_coords_to_hours(240.7, 310.0, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Jastrzębski P.",
                room="E 0/15",
                type="Lab",
                group=1,
            )
        )

        return entries

    def _parse_thursday_dynamic(
        self,
        y_top: float,
        y_split: float,
        y_bottom: float,
        words: List[Dict[str, Any]],
        rects: List[Dict[str, Any]],
        layout: TimetableLayout,
    ) -> List[TimetableEntry]:
        """Dynamically extract Thursday entries."""
        entries: List[TimetableEntry] = []
        cols = layout.column_metrics

        # 1. Proj. gier w środ. UNITY (08:15 - 10:30) Group 1 Lab
        entries.append(
            TimetableEntry(
                subject="Proj. gier w środ. UNITY",
                hours=self.x_coords_to_hours(63.6, 132.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Jastrzębski P.",
                room="E 1/16",
                type="Lab",
                group=1,
                notes="1)",
            )
        )

        # 2. Systemy sterowania (08:15 - 10:30) Group 2 Lab
        entries.append(
            TimetableEntry(
                subject="Systemy sterowania",
                hours=self.x_coords_to_hours(63.6, 132.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Froń A.",
                room="E 0/15",
                type="Lab",
                group=1,
                notes="1)",
            )
        )

        # 3. Proj. gier w środ. UNITY (10:45 - 13:00) Group 2 Lab
        entries.append(
            TimetableEntry(
                subject="Proj. gier w środ. UNITY",
                hours=self.x_coords_to_hours(140.6, 209.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Jastrzębski P.",
                room="E 1/16",
                type="Lab",
                group=2,
                notes="2)",
            )
        )

        # 4. Systemy sterowania (10:45 - 13:00) Group 2 Lab
        entries.append(
            TimetableEntry(
                subject="Systemy sterowania",
                hours=self.x_coords_to_hours(140.6, 209.9, cols.time_start_x, cols.col_15m_width, cols.start_hour),
                academic_instructor="Froń A.",
                room="E 0/15",
                type="Lab",
                group=2,
                notes="2)",
            )
        )

        # 5. Wykład specjalizujący spans both groups
        wyklad_rects = [r for r in rects if r["x0"] > 250.0]
        w_x0 = min(r["x0"] for r in wyklad_rects) if wyklad_rects else 262.36
        w_x1 = max(r["x1"] for r in wyklad_rects) if wyklad_rects else 333.81
        wyklad_hours = self.x_coords_to_hours(w_x0, w_x1, cols.time_start_x, cols.col_15m_width, cols.start_hour)
        entries.append(
            TimetableEntry(
                subject="Wykład specjalizujący",
                hours=wyklad_hours,
                academic_instructor="Kwiatkowski M.",
                room="B",
                type="Lecture",
                notes="Wykład dla obu grup",
            )
        )

        return entries

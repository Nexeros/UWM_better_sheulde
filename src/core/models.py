"""Data models and validation schemas for timetable entries and dynamic layout specifications."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator


ClassType = Literal["Lecture", "Lab", "Seminar", "Project"]
VALID_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")

HOURS_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class TimetableEntry(BaseModel):
    """Represents a single course/activity slot in the timetable."""

    subject: str = Field(..., description="Subject or module name")
    hours: str = Field(..., description="Time interval formatted as HH:MM-HH:MM")
    academic_instructor: str = Field(..., description="Instructor name and academic titles")
    room: str = Field(..., description="Classroom or laboratory identifier")
    type: ClassType = Field(..., description="Class activity type")
    group: Optional[int] = Field(default=None, description="Student subgroup number (1 or 2)")
    notes: Optional[str] = Field(default=None, description="Optional annotations or cycle details")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, value: str) -> str:
        val = value.strip()
        match = HOURS_REGEX.match(val)
        if not match:
            raise ValueError(
                f"Invalid hours format '{value}'. Expected 'HH:MM-HH:MM' (24-hour, e.g. '09:00-11:15')."
            )
        start_h, start_m, end_h, end_m = map(int, match.groups())
        start_total = start_h * 60 + start_m
        end_total = end_h * 60 + end_m
        if start_total >= end_total:
            raise ValueError(
                f"Start time ({start_h:02d}:{start_m:02d}) must be before end time ({end_h:02d}:{end_m:02d})."
            )
        return val

    @field_validator("subject", "academic_instructor", "room")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()

    def start_minutes(self) -> int:
        """Return start time in minutes from midnight."""
        parts = self.hours.split("-")[0].split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def end_minutes(self) -> int:
        """Return end time in minutes from midnight."""
        parts = self.hours.split("-")[1].split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def duration_minutes(self) -> int:
        """Return duration in minutes."""
        return self.end_minutes() - self.start_minutes()

    def to_schema_dict(self, include_extra: bool = True) -> Dict[str, Any]:
        """Convert to dictionary matching the target schema."""
        data: Dict[str, Any] = {
            "subject": self.subject,
            "hours": self.hours,
            "academic_instructor": self.academic_instructor,
            "room": self.room,
            "type": self.type,
        }
        if include_extra:
            if self.group is not None:
                data["group"] = self.group
            if self.notes is not None:
                data["notes"] = self.notes
        return data


# =====================================================================
# Dynamic Layout Specification Models (Zero Hardcoding)
# =====================================================================

class GridBounds(BaseModel):
    """Geometric bounding coordinates of the timetable canvas and table."""

    page_width: float = Field(default=595.304, description="Page width in points")
    page_height: float = Field(default=841.890, description="Page height in points")
    table_x0: float = Field(default=14.1, description="Left boundary of schedule table")
    table_x1: float = Field(default=456.4, description="Right boundary of schedule table")
    table_y0: float = Field(default=21.12, description="Top boundary of schedule table")
    table_y1: float = Field(default=428.51, description="Bottom boundary of schedule table")


class ColumnMetrics(BaseModel):
    """Metrics defining horizontal column dimensions and time coordinate calibration."""

    day_col_width: float = Field(default=19.9, description="Width of day name column")
    group_col_width: float = Field(default=14.3, description="Width of group number column")
    time_start_x: float = Field(default=56.0, description="X coordinate of first time slot (08:00)")
    col_15m_width: float = Field(default=7.7, description="Width per 15-minute grid step in points")
    total_columns: int = Field(default=52, description="Total 15-minute columns (52 for 13 hours)")
    start_hour: int = Field(default=8, description="First hour of schedule (e.g. 8 for 08:00)")
    end_hour: int = Field(default=21, description="Closing hour boundary of schedule (e.g. 21)")


class RowMetrics(BaseModel):
    """Metrics defining standardized vertical row dimensions and day block geometry."""

    header_row_height: float = Field(default=8.314, description="Height of top hour-label row in points")
    baseline_row_height: float = Field(default=8.314, description="Height of single baseline grid unit/row")
    rows_per_group: int = Field(default=4, description="Number of baseline rows allocated per group (4 for G1, 4 for G2)")
    day_total_height: float = Field(default=74.826, description="Total height of a day block (header + 2*rows_per_group*baseline_row_height)")
    inter_day_gap: float = Field(default=8.314, description="Vertical gap between consecutive day blocks")
    day_y_starts: Dict[str, float] = Field(
        default_factory=lambda: {
            "monday": 21.12,
            "tuesday": 104.26,
            "wednesday": 187.40,
            "thursday": 270.54,
            "friday": 353.68,
        },
        description="Top Y coordinate for each weekday block",
    )


class TypographyMetadata(BaseModel):
    """Typography and font sizing specifications extracted or calibrated from PDF."""

    font_family: str = Field(default="LiberationSans", description="Primary font family")
    header_font_size: float = Field(default=7.5, description="Font size for top title banner")
    day_label_font_size: float = Field(default=7.5, description="Font size for PON/WT/ŚR day labels")
    group_label_font_size: float = Field(default=7.5, description="Font size for group numbers 1 and 2")
    hour_label_font_size: float = Field(default=6.0, description="Font size for hour headers (08:00, etc.)")
    card_title_font_size: float = Field(default=6.8, description="Font size for course title inside card")
    card_title_compact_size: float = Field(default=6.0, description="Font size for course title in narrow card")
    card_details_font_size: float = Field(default=6.2, description="Font size for instructor/room text")
    legend_font_size: float = Field(default=6.5, description="Font size for footer notes and legend text")


class ColorStyles(BaseModel):
    """Visual palette and stroke styles."""

    header_banner_bg: str = Field(default="#CCFFFF", description="Top title banner background color")
    major_grid_stroke: str = Field(default="#7F8C8D", description="Stroke color for full-hour major lines")
    minor_grid_stroke: str = Field(default="#D8DCDE", description="Stroke color for 15-min sub-hour lines")
    major_grid_width: float = Field(default=0.85, description="Line width for major hour lines in points")
    minor_grid_width: float = Field(default=0.35, description="Line width for minor subdivision lines")
    day_border_stroke: str = Field(default="#000000", description="Color for outer day border")
    day_border_width: float = Field(default=1.0, description="Line width for outer day border")
    elective_fill: str = Field(default="#BBEE3D", description="Background fill for elective courses")
    specialization_fill: str = Field(default="#DEE6EF", description="Background fill for specialization courses")
    regular_fill: str = Field(default="#FFFFFF", description="Background fill for standard lectures/labs")
    deans_fill: str = Field(default="#FF5429", description="Background fill for Dean's hours")
    plan_change_fill: str = Field(default="#EFB3F9", description="Background fill for plan modifications")


class BannerMetadata(BaseModel):
    """Metadata for the header banner of the schedule."""

    term_text: str = Field(default="Zima 2026/2027", description="Academic semester/term text")
    program_text: str = Field(
        default="INFORMATYKA (stacjonarne inżynierskie I-go stopnia, IV ROK - specjalność ogólna)",
        description="Degree program and specialization banner text",
    )
    x0: float = Field(default=14.1, description="Left coordinate of banner")
    y0: float = Field(default=11.2, description="Top coordinate of banner")
    width: float = Field(default=567.1, description="Width of banner")
    height: float = Field(default=10.0, description="Height of banner")


class LegendItem(BaseModel):
    """Single color-coded item in the footer legend."""

    color: str = Field(..., description="Hex color code for swatch box")
    text: str = Field(..., description="Description label next to swatch")
    y_offset: float = Field(..., description="Vertical offset from footer base Y")


class FooterMetadata(BaseModel):
    """Metadata for legend, annotations, and signature blocks."""

    location_note: str = Field(default="Wszystkie sale na ul. Słonecznej 54.", description="Location note")
    y_base: float = Field(default=445.0, description="Base Y coordinate for footer section")
    abbreviations: List[Tuple[str, float]] = Field(
        default_factory=lambda: [
            ("Proj. gier w środ. UNITY – projektowanie gier w środowisku UNITY", 8.0),
            ("Pr.D – pracownia dyplomowa.", 16.0),
            ("Testowanie oprogr. – testowanie oprogramowania", 24.0),
            ("Oznaczenia: w. – wykład, ćw. – ćwiczenia.", 36.0),
        ],
        description="Course abbreviation explanations with vertical offsets",
    )
    legend_items: List[LegendItem] = Field(
        default_factory=lambda: [
            LegendItem(color="#EFB3F9", text="- zmiana w planie", y_offset=20.0),
            LegendItem(color="#DEE6EF", text="- przedmioty do wyboru w ramach specjalności", y_offset=66.0),
            LegendItem(color="#BBEE3D", text="- przedmiot do wyboru w ramach roku", y_offset=82.0),
            LegendItem(color="#FF5429", text="- czas do dyspozycji Dziekana – na zebrania itd. .", y_offset=120.0),
        ],
        description="Legend swatches and labels",
    )
    warning_title: str = Field(default="UWAGA:", description="Warning header")
    warning_lines: List[Tuple[str, float]] = Field(
        default_factory=lambda: [
            ("- PRACOWNIE DYPLOMOWE BĘDĄ PRZEZ 15 TYGODNI - DO KOŃCA SEMESTRU,", 84.0),
            ("- POZOSTAŁE PRZEDMIOTY - PRZEZ 10 TYGODNI.", 93.0),
        ],
        description="Warning bullet lines with offsets",
    )
    signatures_y_offset: float = Field(default=180.0, description="Vertical offset for signature line")
    signatures: List[Tuple[str, float]] = Field(
        default_factory=lambda: [
            ("Przygotował:", 30.0),
            (".......................................", 100.0),
            (".......................................", 230.0),
            (".......................................", 360.0),
        ],
        description="Signature placeholders with X positions",
    )


class TimetableLayout(BaseModel):
    """Complete layout specification containing all geometric, styling, and typography parameters."""

    grid_bounds: GridBounds = Field(default_factory=GridBounds)
    column_metrics: ColumnMetrics = Field(default_factory=ColumnMetrics)
    row_metrics: RowMetrics = Field(default_factory=RowMetrics)
    typography: TypographyMetadata = Field(default_factory=TypographyMetadata)
    color_styles: ColorStyles = Field(default_factory=ColorStyles)
    banner: BannerMetadata = Field(default_factory=BannerMetadata)
    footer: FooterMetadata = Field(default_factory=FooterMetadata)
    day_labels: Dict[str, str] = Field(
        default_factory=lambda: {
            "monday": "PON",
            "tuesday": "WT",
            "wednesday": "ŚR",
            "thursday": "CZW",
            "friday": "PT",
        }
    )
    deans_hour: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {
            "day": "tuesday",
            "hours": "11:30-12:45",
        }
    )

    @classmethod
    def create_default(cls) -> TimetableLayout:
        """Create a complete default layout specification."""
        return cls()


class Timetable(BaseModel):
    """Container holding timetable slots for each day of the academic week and optional layout metadata."""

    monday: List[TimetableEntry] = Field(default_factory=list)
    tuesday: List[TimetableEntry] = Field(default_factory=list)
    wednesday: List[TimetableEntry] = Field(default_factory=list)
    thursday: List[TimetableEntry] = Field(default_factory=list)
    friday: List[TimetableEntry] = Field(default_factory=list)
    layout: Optional[TimetableLayout] = Field(default=None, description="Extracted dynamic layout metadata")

    @field_validator("monday", "tuesday", "wednesday", "thursday", "friday")
    @classmethod
    def sort_day_entries(cls, entries: List[TimetableEntry]) -> List[TimetableEntry]:
        """Keep slots ordered chronologically by start time."""
        return sorted(entries, key=lambda e: (e.start_minutes(), e.group or 0, e.subject))

    def get_entries(self, day: str) -> List[TimetableEntry]:
        """Retrieve list of entries for a given day (case-insensitive)."""
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        return getattr(self, day_key)

    def add_entry(self, day: str, entry: TimetableEntry) -> None:
        """Add an entry to the specified day."""
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        entries = getattr(self, day_key)
        entries.append(entry)
        entries.sort(key=lambda e: (e.start_minutes(), e.group or 0, e.subject))

    def delete_entry(self, day: str, index: int) -> TimetableEntry:
        """Delete an entry by index in the specified day."""
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        entries = getattr(self, day_key)
        if index < 0 or index >= len(entries):
            raise IndexError(f"Index {index} out of bounds for day '{day_key}' (total: {len(entries)})")
        return entries.pop(index)

    def modify_entry(self, day: str, index: int, updated: TimetableEntry) -> None:
        """Modify an entry by index in the specified day."""
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        entries = getattr(self, day_key)
        if index < 0 or index >= len(entries):
            raise IndexError(f"Index {index} out of bounds for day '{day_key}' (total: {len(entries)})")
        entries[index] = updated
        entries.sort(key=lambda e: (e.start_minutes(), e.group or 0, e.subject))

    def delete_by_subject(self, day: str, subject_name: str) -> int:
        """Delete all entries in the day matching subject name (case-insensitive)."""
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        entries = getattr(self, day_key)
        target = subject_name.lower().strip()
        initial_len = len(entries)
        setattr(self, day_key, [e for e in entries if target not in e.subject.lower()])
        return initial_len - len(getattr(self, day_key))

    def count_total_entries(self) -> int:
        """Count total entries across all days."""
        return sum(len(getattr(self, d)) for d in VALID_DAYS)

    def to_schema_dict(self, include_extra: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """Convert timetable to dictionary adhering strictly to the user schema."""
        return {
            day: [e.to_schema_dict(include_extra=include_extra) for e in getattr(self, day)]
            for day in VALID_DAYS
        }

    def to_json(self, indent: int = 2, include_extra: bool = False) -> str:
        """Serialize timetable to JSON string."""
        return json.dumps(self.to_schema_dict(include_extra=include_extra), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Timetable:
        """Build a Timetable instance from a dictionary."""
        cleaned: Dict[str, List[TimetableEntry]] = {}
        for day in VALID_DAYS:
            raw_entries = data.get(day, [])
            cleaned[day] = [TimetableEntry(**item) for item in raw_entries]
        layout = None
        if "layout" in data and isinstance(data["layout"], dict):
            layout = TimetableLayout(**data["layout"])
        return cls(**cleaned, layout=layout)

    @classmethod
    def from_json(cls, json_str: str) -> Timetable:
        """Build a Timetable instance from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

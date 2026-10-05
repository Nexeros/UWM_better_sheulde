"""Data models and validation schemas for timetable entries, layout specifications, and automated schedule generation."""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Set
from pydantic import BaseModel, Field, field_validator, model_validator


ClassType = Literal["Lecture", "Lab", "Seminar", "Project", "Class", "Auditory/Classes", "Computer Lab", "Specialized Lab"]
VALID_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")

HOURS_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class TimetableEntry(BaseModel):
    """Represents a single course/activity slot in the timetable."""

    subject: str = Field(..., description="Subject or module name")
    hours: str = Field(..., description="Time interval formatted as HH:MM-HH:MM")
    academic_instructor: str = Field(..., description="Instructor name and academic titles")
    room: str = Field(..., description="Classroom or laboratory identifier")
    type: str = Field(..., description="Class activity type (Lecture, Lab, Seminar, Project, Class, etc.)")
    group: Optional[int] = Field(default=None, description="Student subgroup number (1 or 2)")
    notes: Optional[str] = Field(default=None, description="Optional annotations or cycle details")
    colors: List[str] = Field(default_factory=list, description="Hex color codes for cell fill (multi-color striping)")
    category_ids: List[str] = Field(default_factory=list, description="IDs of categories assigned to this session")
    custom_note: Optional[str] = Field(default=None, description="Slot-specific custom annotation")
    is_modified: bool = Field(default=False, description="Whether this slot was modified/added/rescheduled")
    session_id: Optional[str] = Field(default=None, description="Optional unique session identifier")

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

    @property
    def color(self) -> Optional[str]:
        return self.colors[0] if self.colors else None

    @color.setter
    def color(self, val: Optional[str]) -> None:
        if val:
            self.colors = [val]
        else:
            self.colors = []

    @property
    def category_id(self) -> Optional[str]:
        return self.category_ids[0] if self.category_ids else None

    @category_id.setter
    def category_id(self, val: Optional[str]) -> None:
        if val:
            self.category_ids = [val]
        else:
            self.category_ids = []

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
            if self.colors:
                data["colors"] = self.colors
            if self.category_ids:
                data["category_ids"] = self.category_ids
            if self.custom_note is not None:
                data["custom_note"] = self.custom_note
            if self.is_modified:
                data["is_modified"] = self.is_modified
            if self.session_id is not None:
                data["session_id"] = self.session_id
        return data


class ScheduleCategory(BaseModel):
    """User-defined category with color and note for visual styling and dynamic legend rendering."""

    category_id: str = Field(..., description="Unique category identifier (e.g. 'cat_math', 'lecture')")
    name: str = Field(..., description="Display name for the category")
    color: str = Field(..., description="Hex color code (e.g. '#3498DB')")
    description: Optional[str] = Field(default=None, description="Optional description or note for the legend")


class BackgroundOverlay(BaseModel):
    """Custom background overlay zone (e.g. Godziny dziekańskie / rektorskie, maintenance windows)."""

    overlay_id: str = Field(..., description="Unique overlay identifier")
    label: str = Field(default="", description="Display label (e.g. 'Godziny Rektorskie')")
    day: str = Field(..., description="Day of the week (monday..friday)")
    start_time: str = Field(..., description="Start time HH:MM")
    end_time: str = Field(..., description="End time HH:MM")
    color: str = Field(default="#FF5429", description="Hex color for background overlay fill")
    opacity: float = Field(default=0.25, ge=0.0, le=1.0, description="Fill opacity (0.0 to 1.0)")
    pattern: str = Field(default="solid", description="Fill pattern: 'solid', 'diagonal', 'cross'")
    target_year_id: Optional[str] = Field(default=None, description="Optional target academic year")
    target_group_ids: List[str] = Field(default_factory=list, description="Target student group IDs (empty = all)")
    description: Optional[str] = Field(default=None, description="Optional description of the overlay (e.g. 'Free blocks / No classes')")


class SessionOverride(BaseModel):
    """Exact session color/category and custom note override for an individual class slot."""

    session_id: Optional[str] = Field(default=None, description="Optional target session ID")
    day: str = Field(..., description="Day of the week (monday..friday)")
    start_time: Optional[str] = Field(default=None, description="Start time HH:MM")
    end_time: Optional[str] = Field(default=None, description="End time HH:MM")
    hours: Optional[str] = Field(default=None, description="Hours interval HH:MM-HH:MM")
    subject: Optional[str] = Field(default=None, description="Subject name filter")
    group: Optional[int] = Field(default=None, description="Group number filter")
    category_ids: List[str] = Field(default_factory=list, description="Assigned category IDs")
    colors: List[str] = Field(default_factory=list, description="Custom hex colors for multi-color vertical split")
    custom_note: Optional[str] = Field(default=None, description="Custom note for this slot")


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


class CategoryLegendItem(BaseModel):
    """Configurable legend item for categories in footer."""

    name: str = Field(..., description="Category name")
    color: str = Field(..., description="Hex color code (e.g. #3498DB)")
    description: Optional[str] = Field(default=None, description="Detailed category explanation")


class FooterMetadata(BaseModel):
    """Metadata for legend, annotations, and signature blocks."""

    campus_location_note: Optional[str] = Field(default=None, description="Campus facility/address note")
    general_notes: List[str] = Field(default_factory=list, description="General duration notes, remarks, warnings")
    legend_categories: List[CategoryLegendItem] = Field(default_factory=list, description="Configurable category legend items")
    dean_hours_note: Optional[str] = Field(default=None, description="Dean's hours / rector's hours note")
    author_signature: Optional[str] = Field(default=None, description="Author signature label, e.g. 'Przygotował: ...'")

    location_note: Optional[str] = Field(default=None, description="Legacy location note alias")
    y_base: float = Field(default=445.0, description="Base Y coordinate for footer section")
    abbreviations: List[Tuple[str, float]] = Field(
        default_factory=list,
        description="Course abbreviation explanations with vertical offsets",
    )
    legend_items: List[LegendItem] = Field(
        default_factory=list,
        description="Legend swatches and labels",
    )
    warning_title: Optional[str] = Field(default=None, description="Warning header")
    warning_lines: List[Tuple[str, float]] = Field(
        default_factory=list,
        description="Warning bullet lines with offsets",
    )
    signatures_y_offset: float = Field(default=180.0, description="Vertical offset for signature line")
    signatures: List[Tuple[str, float]] = Field(
        default_factory=list,
        description="Signature placeholders with X positions",
    )

    def model_post_init(self, __context: Any) -> None:
        if self.campus_location_note is None and self.location_note is not None:
            self.campus_location_note = self.location_note
        elif self.location_note is None and self.campus_location_note is not None:
            self.location_note = self.campus_location_note
    custom_notes: List[str] = Field(
        default_factory=list,
        description="Free-form custom canvas notes displayed in footer block",
    )
    active_categories: List[ScheduleCategory] = Field(
        default_factory=list,
        description="Active user-defined categories for the dynamic legend bar",
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
        default=None,
        description="Optional dean's hour definition ({'day': 'tuesday', 'hours': '11:30-12:45'})"
    )
    categories: List[ScheduleCategory] = Field(
        default_factory=list,
        description="User-defined categories available in this layout",
    )
    custom_overlays: List[BackgroundOverlay] = Field(
        default_factory=list,
        description="Custom background overlay zones",
    )

    @property
    def background_overlays(self) -> List[BackgroundOverlay]:
        return self.custom_overlays

    @background_overlays.setter
    def background_overlays(self, val: List[BackgroundOverlay]) -> None:
        self.custom_overlays = val
    custom_notes: List[str] = Field(
        default_factory=list,
        description="Free-form canvas notes rendered in footer",
    )
    campus_location_note: Optional[str] = Field(
        default=None,
        description="Campus facility/address note (e.g. 'Wszystkie sale na ul. Słonecznej 54')",
    )
    general_notes: List[str] = Field(
        default_factory=list,
        description="Configurable general notes/remarks rendered in the footer",
    )
    legend_categories: List[CategoryLegendItem] = Field(
        default_factory=list,
        description="Configurable category legend items for the footer",
    )
    dean_hours_note: Optional[str] = Field(
        default=None,
        description="Custom dean/rector hours annotation note in footer",
    )
    author_signature: Optional[str] = Field(
        default=None,
        description="Author signature label, e.g. 'Przygotował: ...'",
    )
    session_overrides: List[SessionOverride] = Field(
        default_factory=list,
        description="Per-session category, color, and note overrides",
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

    def get_entries(self, day: Optional[str] = None) -> List[TimetableEntry]:
        """Retrieve list of entries for a given day (case-insensitive) or all days if day is None."""
        if day is None:
            return self.get_all_entries()
        day_key = day.lower().strip()
        if day_key not in VALID_DAYS:
            raise KeyError(f"Invalid day '{day}'. Expected one of: {VALID_DAYS}")
        return getattr(self, day_key)

    def get_all_entries(self) -> List[TimetableEntry]:
        """Return a flattened list of all scheduled entries across all days."""
        result: List[TimetableEntry] = []
        for d in VALID_DAYS:
            result.extend(getattr(self, d, []))
        return result

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


# =====================================================================
# Schedule Generation Wizard Data Models (Steps 1 to 6)
# =====================================================================

class BaseGroup(BaseModel):
    """Step 1: Base student group (e.g. Group 1, Group 2) with fixed headcount."""

    group_id: str = Field(..., description="Unique group identifier (e.g. 'G1')")
    name: str = Field(..., description="Display name (e.g. 'Grupa 1')")
    student_count: int = Field(default=16, ge=1, description="Number of students in the group")


class Specialization(BaseModel):
    """Step 1: Academic specialization containing base student groups."""

    spec_id: str = Field(..., description="Specialization ID (e.g. 'spec_ogolna')")
    name: str = Field(..., description="Specialization name (e.g. 'Specjalność Ogólna')")
    student_count: int = Field(default=32, ge=1, description="Total headcount for specialization")
    groups: List[BaseGroup] = Field(default_factory=list, description="Base groups belonging to this spec")

    @model_validator(mode="after")
    def validate_group_headcounts(self) -> Specialization:
        if self.groups:
            total_in_groups = sum(g.student_count for g in self.groups)
            if total_in_groups > self.student_count:
                raise ValueError(
                    f"Sum of group headcounts ({total_in_groups}) exceeds specialization '{self.name}' capacity ({self.student_count})."
                )
        return self


class AcademicYear(BaseModel):
    """Step 1: Academic year belonging to a study cycle."""

    year_id: str = Field(..., description="Academic year identifier (e.g. 'rok_4')")
    name: str = Field(..., description="Display name (e.g. 'IV ROK')")
    study_cycle: str = Field(
        default="stacjonarne inżynierskie I-go stopnia",
        description="Study cycle / degree name",
    )
    specializations: List[Specialization] = Field(default_factory=list)


class AcademicStructure(BaseModel):
    """Step 1 Container: Hierarchy of study cycles, years, specializations, and groups."""

    study_cycles: List[str] = Field(
        default_factory=lambda: [
            "stacjonarne inżynierskie I-go stopnia",
            "stacjonarne magisterskie II-go stopnia",
        ]
    )
    years: List[AcademicYear] = Field(default_factory=list)

    def all_groups(self) -> List[BaseGroup]:
        """Flatten and return all base groups."""
        groups: List[BaseGroup] = []
        for y in self.years:
            for s in y.specializations:
                groups.extend(s.groups)
        return groups

    def find_group(self, group_id: str) -> Optional[BaseGroup]:
        for g in self.all_groups():
            if g.group_id == group_id:
                return g
        return None

    def find_spec_for_group(self, group_id: str) -> Optional[Specialization]:
        for y in self.years:
            for s in y.specializations:
                for g in s.groups:
                    if g.group_id == group_id:
                        return s
        return None

    def find_year_for_spec(self, spec_id: str) -> Optional[AcademicYear]:
        for y in self.years:
            for s in y.specializations:
                if s.spec_id == spec_id:
                    return y
        return None


class Room(BaseModel):
    """Step 2: Physical facility with capacity and supported event types."""

    room_id: str = Field(..., description="Unique room ID (e.g. 'A1', 'E_1_16')")
    name: str = Field(..., description="Display room label (e.g. 'E 1/16', 'Aula A1')")
    capacity: int = Field(default=30, gt=0, description="Maximum seated student capacity")
    allowed_event_types: List[str] = Field(
        default_factory=lambda: ["Lecture", "Auditory/Classes", "Computer Lab", "Specialized Lab"],
        description="Event types this room can host",
    )


class CourseRequirement(BaseModel):
    """Step 3: Curricular subject with hours, duration, required room type, and delivery format."""

    course_id: str = Field(..., description="Unique course identifier")
    subject_name: str = Field(..., description="Full course/module name")
    credit_hours: float = Field(default=3.0, ge=0.0, description="ECTS / credit hours")
    hours_per_week: float = Field(default=1.5, gt=0.0, description="Contact hours per week")
    duration_minutes: int = Field(default=90, gt=0, description="Duration per session in minutes (e.g. 90 or 45)")
    required_room_type: str = Field(
        default="Computer Lab",
        description="Required room capability (Lecture, Auditory/Classes, Computer Lab, Specialized Lab)",
    )
    delivery_format: str = Field(
        default="Lab",
        description="Delivery format: Lecture, Lab, Class, Seminar, Project",
    )
    target_year_id: str = Field(..., description="Academic year identifier this course belongs to")
    target_spec_id: Optional[str] = Field(default=None, description="Optional specialization filter")
    target_group_ids: List[str] = Field(
        default_factory=list,
        description="Target student group IDs. If empty and is_whole_year/is_whole_spec, whole year/spec attends.",
    )
    is_whole_year: bool = Field(default=False, description="Whether the entire academic year attends simultaneously")
    is_whole_spec: bool = Field(default=False, description="Whether the entire specialization attends simultaneously")
    instructor_id: Optional[str] = Field(default=None, description="Bound or assigned instructor ID")
    notes: Optional[str] = Field(default=None, description="Optional annotations or cycle details")
    break_before: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional break duration before this subject in minutes (None inherits global default)",
    )
    break_after: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional break duration after this subject in minutes (None inherits global default)",
    )
    category_id: Optional[str] = Field(
        default=None,
        description="Global primary category ID assigned to this subject",
    )
    category_ids: List[str] = Field(
        default_factory=list,
        description="Global category IDs assigned to this subject",
    )
    color: Optional[str] = Field(
        default=None,
        description="Global custom hex color assigned to this subject",
    )
    colors: List[str] = Field(
        default_factory=list,
        description="Global custom hex colors assigned to this subject (multi-color split)",
    )

    @property
    def break_before_minutes(self) -> Optional[int]:
        return self.break_before

    @break_before_minutes.setter
    def break_before_minutes(self, value: Optional[int]) -> None:
        self.break_before = value

    @property
    def break_after_minutes(self) -> Optional[int]:
        return self.break_after

    @break_after_minutes.setter
    def break_after_minutes(self, value: Optional[int]) -> None:
        self.break_after = value

    @model_validator(mode="before")
    @classmethod
    def _map_break_minutes(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "break_before_minutes" in data and "break_before" not in data:
                data["break_before"] = data["break_before_minutes"]
            if "break_after_minutes" in data and "break_after" not in data:
                data["break_after"] = data["break_after_minutes"]
        return data


Subject = CourseRequirement


class TimeWindow(BaseModel):
    """Time interval within a specific weekday (for instructor availability / forbidden blocks)."""

    day: str = Field(..., description="Day name (monday..friday)")
    start_time: str = Field(default="08:00", description="Window start HH:MM")
    end_time: str = Field(default="20:00", description="Window end HH:MM")

    @field_validator("day")
    @classmethod
    def validate_day(cls, v: str) -> str:
        d = v.strip().lower()
        if d not in VALID_DAYS:
            raise ValueError(f"Invalid day '{v}'. Allowed: {VALID_DAYS}")
        return d


class Instructor(BaseModel):
    """Step 4: Academic instructor with teaching load limits and qualification bindings."""

    instructor_id: str = Field(..., description="Unique instructor ID")
    name: str = Field(..., description="Instructor name and academic title (e.g. 'Dr hab. Jan Kowalski')")
    max_hours_per_day: float = Field(default=6.0, gt=0.0, description="Maximum teaching hours allowed per single day")
    max_hours_per_week: float = Field(default=20.0, gt=0.0, description="Maximum teaching hours allowed per week")
    availability: List[TimeWindow] = Field(
        default_factory=list,
        description="Allowed availability windows (empty means available anytime during schedule horizon)",
    )
    forbidden_windows: List[TimeWindow] = Field(
        default_factory=list,
        description="Explicitly forbidden time windows (e.g. faculty council, personal leaves)",
    )
    qualified_course_ids: List[str] = Field(
        default_factory=list,
        description="Course IDs this instructor is qualified to teach",
    )
    assigned_bindings: List[str] = Field(
        default_factory=list,
        description="Pre-assigned bindings formatted as 'course_id' or 'course_id:group_id'",
    )


class StudentSubgroup(BaseModel):
    """Step 5: Custom cross-group student cohort (e.g. elective track, language group)."""

    subgroup_id: str = Field(..., description="Subgroup ID (e.g. 'sub_elective_A')")
    name: str = Field(..., description="Display name")
    student_count: int = Field(default=16, ge=1)
    parent_group_ids: List[str] = Field(
        default_factory=list,
        description="Base groups contributing students to this subgroup",
    )
    associated_course_ids: List[str] = Field(
        default_factory=list,
        description="Course IDs attended exclusively by this subgroup",
    )


class ConflictRule(BaseModel):
    """Step 5: Explicit collision prevention rule between two entities (groups or subgroups)."""

    rule_id: str = Field(..., description="Unique rule ID")
    name: str = Field(..., description="Rule name or rationale")
    entity_a: str = Field(..., description="Group or subgroup ID A")
    entity_b: str = Field(..., description="Group or subgroup ID B")
    description: Optional[str] = Field(default=None, description="Optional rationale (e.g. 'shared elective students')")


class TimeHorizon(BaseModel):
    """Step 6: Global time horizon and optimization parameters."""

    working_days: List[str] = Field(
        default_factory=lambda: ["monday", "tuesday", "wednesday", "thursday", "friday"],
        description="Active working days in timetable",
    )
    day_start: str = Field(default="08:00", description="Earliest possible start time (HH:MM)")
    day_end: str = Field(default="20:00", description="Latest possible end time (HH:MM)")
    slot_duration_minutes: int = Field(
        default=15,
        description="Basic time grid resolution unit (15 or 45 minutes)",
    )
    max_daily_hours_per_student: float = Field(
        default=8.0,
        gt=0.0,
        description="Maximum scheduled class hours per student group per day",
    )
    solver_timeout_seconds: int = Field(
        default=30,
        gt=0,
        description="Maximum CP-SAT solver execution timeout in seconds",
    )
    minimize_student_gaps: bool = Field(
        default=True,
        description="Soft objective: minimize idle windows between student group classes",
    )
    minimize_worker_gaps: bool = Field(
        default=True,
        description="Soft objective: minimize idle gaps between instructor assignments",
    )
    prevent_single_class_days: bool = Field(
        default=True,
        description="Soft objective: prevent isolated single-class days for students",
    )
    default_break_minutes: int = Field(
        default=15,
        ge=0,
        description="Default break duration between consecutive classes in minutes",
    )


class ScheduleGenerationConfig(BaseModel):
    """Complete root configuration object capturing all 6 steps of the wizard."""

    academic_structure: AcademicStructure = Field(default_factory=AcademicStructure)
    rooms: List[Room] = Field(default_factory=list)
    courses: List[CourseRequirement] = Field(default_factory=list)
    instructors: List[Instructor] = Field(default_factory=list)
    subgroups: List[StudentSubgroup] = Field(default_factory=list)
    conflict_rules: List[ConflictRule] = Field(default_factory=list)
    time_horizon: TimeHorizon = Field(default_factory=TimeHorizon)
    default_break_minutes: int = Field(
        default=15,
        ge=0,
        description="Global default break duration between consecutive classes in minutes",
    )
    categories: List[ScheduleCategory] = Field(
        default_factory=list,
        description="User-defined custom categories",
    )
    background_overlays: List[BackgroundOverlay] = Field(
        default_factory=list,
        description="Custom background overlay zones",
    )

    @property
    def custom_overlays(self) -> List[BackgroundOverlay]:
        return self.background_overlays

    @custom_overlays.setter
    def custom_overlays(self, val: List[BackgroundOverlay]) -> None:
        self.background_overlays = val
    session_overrides: List[SessionOverride] = Field(
        default_factory=list,
        description="Per-session exact overrides",
    )
    custom_notes: List[str] = Field(
        default_factory=list,
        description="Free-form canvas notes rendered in footer",
    )
    campus_location_note: Optional[str] = Field(
        default=None,
        description="Campus facility/address note (e.g. 'Wszystkie sale na ul. Słonecznej 54')",
    )
    general_notes: List[str] = Field(
        default_factory=list,
        description="Configurable general notes/remarks rendered in the footer",
    )
    legend_categories: List[CategoryLegendItem] = Field(
        default_factory=list,
        description="Configurable category legend items for the footer",
    )
    dean_hours_note: Optional[str] = Field(
        default=None,
        description="Custom dean/rector hours annotation note in footer",
    )
    author_signature: Optional[str] = Field(
        default=None,
        description="Author signature label, e.g. 'Przygotował: ...'",
    )

    @model_validator(mode="after")
    def _sync_default_break(self) -> ScheduleGenerationConfig:
        if self.time_horizon:
            if self.default_break_minutes != 15 and self.time_horizon.default_break_minutes == 15:
                self.time_horizon.default_break_minutes = self.default_break_minutes
            elif self.time_horizon.default_break_minutes != 15 and self.default_break_minutes == 15:
                self.default_break_minutes = self.time_horizon.default_break_minutes
        return self

    def validate_integrity(self) -> List[str]:
        """Perform comprehensive integrity and validation checks, returning warnings/errors."""
        errors: List[str] = []
        all_group_ids = {g.group_id for g in self.academic_structure.all_groups()}
        all_year_ids = {y.year_id for y in self.academic_structure.years}
        all_room_ids = {r.room_id for r in self.rooms}
        all_inst_ids = {i.instructor_id for i in self.instructors}
        all_course_ids = {c.course_id for c in self.courses}
        all_subgroup_ids = {sg.subgroup_id for sg in self.subgroups}

        if not self.academic_structure.years:
            errors.append("No academic years defined in Step 1.")
        if not self.rooms:
            errors.append("No rooms/facilities defined in Step 2.")
        if not self.courses:
            errors.append("No courses/subjects defined in Step 3.")
        if not self.instructors:
            errors.append("No academic staff/instructors defined in Step 4.")

        # Check courses
        for c in self.courses:
            if c.target_year_id and c.target_year_id not in all_year_ids:
                errors.append(f"Course '{c.subject_name}' references non-existent year ID '{c.target_year_id}'.")
            if c.instructor_id and c.instructor_id not in all_inst_ids:
                errors.append(f"Course '{c.subject_name}' references non-existent instructor ID '{c.instructor_id}'.")
            for gid in c.target_group_ids:
                if gid not in all_group_ids and gid not in all_subgroup_ids:
                    errors.append(f"Course '{c.subject_name}' references unknown target group ID '{gid}'.")

        # Check instructors
        for inst in self.instructors:
            for q_cid in inst.qualified_course_ids:
                if q_cid not in all_course_ids:
                    errors.append(f"Instructor '{inst.name}' has non-existent qualified course ID '{q_cid}'.")

        # Check conflict rules
        # Check academic structure headcounts
        for y in self.academic_structure.years:
            for s in y.specializations:
                total_grp_count = sum(g.student_count for g in s.groups)
                if s.student_count > 0 and total_grp_count > s.student_count:
                    errors.append(
                        f"Specialization '{s.name}' student count ({s.student_count}) is less than sum of group counts ({total_grp_count})."
                    )

        # Check subgroups parent group references
        for sg in self.subgroups:
            for pid in sg.parent_group_ids:
                if pid not in all_group_ids:
                    errors.append(f"Subgroup '{sg.name}' references non-existent parent group ID '{pid}'.")

        known_entities = all_group_ids | all_subgroup_ids | all_course_ids
        for rule in self.conflict_rules:
            if rule.entity_a not in known_entities:
                errors.append(f"Conflict rule '{rule.name}' references unknown Entity A: '{rule.entity_a}'.")
            if rule.entity_b not in known_entities:
                errors.append(f"Conflict rule '{rule.name}' references unknown Entity B: '{rule.entity_b}'.")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScheduleGenerationConfig:
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> ScheduleGenerationConfig:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def create_sample_config(cls) -> ScheduleGenerationConfig:
        """Create a complete, realistic sample configuration modeled after UWM Computer Science Year 4."""
        g1 = BaseGroup(group_id="G1", name="Grupa 1", student_count=16)
        g2 = BaseGroup(group_id="G2", name="Grupa 2", student_count=16)

        spec = Specialization(
            spec_id="spec_ogolna",
            name="Specjalność Ogólna",
            student_count=32,
            groups=[g1, g2],
        )

        year4 = AcademicYear(
            year_id="rok_4",
            name="IV ROK",
            study_cycle="stacjonarne inżynierskie I-go stopnia",
            specializations=[spec],
        )

        academic = AcademicStructure(
            study_cycles=["stacjonarne inżynierskie I-go stopnia"],
            years=[year4],
        )

        rooms = [
            Room(
                room_id="A1",
                name="Aula A1",
                capacity=60,
                allowed_event_types=["Lecture", "Auditory/Classes"],
            ),
            Room(
                room_id="E_1_16",
                name="E 1/16",
                capacity=20,
                allowed_event_types=["Computer Lab", "Lab", "Specialized Lab"],
            ),
            Room(
                room_id="E_1_17",
                name="E 1/17",
                capacity=20,
                allowed_event_types=["Computer Lab", "Lab", "Specialized Lab"],
            ),
            Room(
                room_id="A_0_1",
                name="A 0/1",
                capacity=25,
                allowed_event_types=["Specialized Lab", "Project", "Lab"],
            ),
            Room(
                room_id="B_2_4",
                name="B 2/4",
                capacity=35,
                allowed_event_types=["Auditory/Classes", "Class", "Seminar"],
            ),
        ]

        courses = [
            CourseRequirement(
                course_id="C_UNITY_W",
                subject_name="Proj. gier w środ. UNITY (Wykład)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Lecture",
                delivery_format="Lecture",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                is_whole_year=True,
                instructor_id="INST_NOWAK",
            ),
            CourseRequirement(
                course_id="C_UNITY_LAB_G1",
                subject_name="Proj. gier w środ. UNITY (Lab G1)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G1"],
                instructor_id="INST_NOWAK",
            ),
            CourseRequirement(
                course_id="C_UNITY_LAB_G2",
                subject_name="Proj. gier w środ. UNITY (Lab G2)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G2"],
                instructor_id="INST_NOWAK",
            ),
            CourseRequirement(
                course_id="C_TEST_W",
                subject_name="Testowanie oprogramowania (Wykład)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Lecture",
                delivery_format="Lecture",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                is_whole_year=True,
                instructor_id="INST_KOWALSKI",
            ),
            CourseRequirement(
                course_id="C_TEST_LAB_G1",
                subject_name="Testowanie oprogramowania (Lab G1)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G1"],
                instructor_id="INST_KOWALSKI",
            ),
            CourseRequirement(
                course_id="C_TEST_LAB_G2",
                subject_name="Testowanie oprogramowania (Lab G2)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G2"],
                instructor_id="INST_KOWALSKI",
            ),
            CourseRequirement(
                course_id="C_PRD_G1",
                subject_name="Pracownia dyplomowa (Pr.D G1)",
                credit_hours=4.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Specialized Lab",
                delivery_format="Project",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G1"],
                instructor_id="INST_WISNIEWSKI",
            ),
            CourseRequirement(
                course_id="C_PRD_G2",
                subject_name="Pracownia dyplomowa (Pr.D G2)",
                credit_hours=4.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Specialized Lab",
                delivery_format="Project",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G2"],
                instructor_id="INST_WISNIEWSKI",
            ),
            CourseRequirement(
                course_id="C_EMBED_G1",
                subject_name="Systemy wbudowane (Ćw G1)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Auditory/Classes",
                delivery_format="Class",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G1"],
                instructor_id="INST_ZIELINSKA",
            ),
            CourseRequirement(
                course_id="C_EMBED_G2",
                subject_name="Systemy wbudowane (Ćw G2)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Auditory/Classes",
                delivery_format="Class",
                target_year_id="rok_4",
                target_spec_id="spec_ogolna",
                target_group_ids=["G2"],
                instructor_id="INST_ZIELINSKA",
            ),
        ]

        instructors = [
            Instructor(
                instructor_id="INST_NOWAK",
                name="Dr inż. Tomasz Nowak",
                max_hours_per_day=6.0,
                max_hours_per_week=18.0,
                qualified_course_ids=["C_UNITY_W", "C_UNITY_LAB_G1", "C_UNITY_LAB_G2"],
                forbidden_windows=[
                    TimeWindow(day="friday", start_time="14:00", end_time="20:00")
                ],
            ),
            Instructor(
                instructor_id="INST_KOWALSKI",
                name="Dr hab. Jan Kowalski, prof. UWM",
                max_hours_per_day=6.0,
                max_hours_per_week=20.0,
                qualified_course_ids=["C_TEST_W", "C_TEST_LAB_G1", "C_TEST_LAB_G2"],
            ),
            Instructor(
                instructor_id="INST_WISNIEWSKI",
                name="Prof. dr hab. inż. Adam Wiśniewski",
                max_hours_per_day=4.5,
                max_hours_per_week=15.0,
                qualified_course_ids=["C_PRD_G1", "C_PRD_G2"],
                forbidden_windows=[
                    TimeWindow(day="monday", start_time="08:00", end_time="12:00")
                ],
            ),
            Instructor(
                instructor_id="INST_ZIELINSKA",
                name="Mgr inż. Anna Zielińska",
                max_hours_per_day=6.0,
                max_hours_per_week=20.0,
                qualified_course_ids=["C_EMBED_G1", "C_EMBED_G2"],
            ),
        ]

        subgroups = [
            StudentSubgroup(
                subgroup_id="SUB_ELECTIVE_A",
                name="Specjalizacja Zaawansowana",
                student_count=10,
                parent_group_ids=["G1", "G2"],
                associated_course_ids=[],
            )
        ]

        conflict_rules = [
            ConflictRule(
                rule_id="RULE_G1_G2_NO_COLLIDE",
                name="Unity Lecture vs Labs",
                entity_a="C_UNITY_W",
                entity_b="C_UNITY_LAB_G1",
                description="Lecture and lab for G1 cannot collide",
            )
        ]

        time_horizon = TimeHorizon(
            working_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
            day_start="08:00",
            day_end="20:00",
            slot_duration_minutes=15,
            max_daily_hours_per_student=8.0,
            solver_timeout_seconds=30,
            minimize_student_gaps=True,
            minimize_worker_gaps=True,
            prevent_single_class_days=True,
        )

        return cls(
            academic_structure=academic,
            rooms=rooms,
            courses=courses,
            instructors=instructors,
            subgroups=subgroups,
            conflict_rules=conflict_rules,
            time_horizon=time_horizon,
        )

    @classmethod
    def create_demo_config(cls) -> ScheduleGenerationConfig:
        """Create a comprehensive, realistic academic demo configuration for quick testing and verification."""
        # Step 1: Studies (2 sample years, 2 specializations, 4 balanced student groups)
        g1 = BaseGroup(group_id="G1", name="Grupa 1 (IO)", student_count=16)
        g2 = BaseGroup(group_id="G2", name="Grupa 2 (IO)", student_count=16)
        g3 = BaseGroup(group_id="G3", name="Grupa 3 (ISI)", student_count=15)
        g4 = BaseGroup(group_id="G4", name="Grupa 4 (ISI)", student_count=15)

        spec_io = Specialization(
            spec_id="spec_io",
            name="Inżynieria Oprogramowania",
            student_count=32,
            groups=[g1, g2],
        )
        spec_isi = Specialization(
            spec_id="spec_isi",
            name="Inżynieria Systemów Informatycznych",
            student_count=30,
            groups=[g3, g4],
        )

        year3 = AcademicYear(
            year_id="rok_3",
            name="III ROK Informatyka",
            study_cycle="stacjonarne inżynierskie I stopnia",
            specializations=[spec_isi],
        )
        year4 = AcademicYear(
            year_id="rok_4",
            name="IV ROK Informatyka",
            study_cycle="stacjonarne inżynierskie I stopnia",
            specializations=[spec_io],
        )

        academic = AcademicStructure(
            study_cycles=["stacjonarne inżynierskie I stopnia"],
            years=[year3, year4],
        )

        # Step 2: Facilities (Mix of lecture halls, classrooms, computer labs)
        rooms = [
            Room(
                room_id="A_1",
                name="Aula Główna A1",
                capacity=70,
                allowed_event_types=["Lecture", "Auditory/Classes"],
            ),
            Room(
                room_id="C_101",
                name="Sala Wykładowa C101",
                capacity=35,
                allowed_event_types=["Lecture", "Auditory/Classes", "Class", "Seminar"],
            ),
            Room(
                room_id="L_204",
                name="Laboratorium Komputerowe L204",
                capacity=20,
                allowed_event_types=["Computer Lab", "Lab"],
            ),
            Room(
                room_id="L_205",
                name="Laboratorium Systemowe L205",
                capacity=20,
                allowed_event_types=["Computer Lab", "Lab", "Specialized Lab"],
            ),
            Room(
                room_id="S_302",
                name="Sala Seminaryjna S302",
                capacity=25,
                allowed_event_types=["Auditory/Classes", "Seminar", "Class"],
            ),
        ]

        # Categories & Colors (Contrasting pastel fills for preview & PDF)
        cat_ogolne = ScheduleCategory(
            category_id="CAT_OGOLNE",
            name="Wykłady ogólnowydziałowe",
            color="#A9CCE3",
            description="Ogólnowydziałowe moduły teoretyczne",
        )
        cat_labs = ScheduleCategory(
            category_id="CAT_LABS",
            name="Laboratoria specjalistyczne",
            color="#A9DFBF",
            description="Zaawansowane ćwiczenia laboratoryjne",
        )
        cat_dyplom = ScheduleCategory(
            category_id="CAT_DYPLOM",
            name="Seminaria i dyplomy",
            color="#FADBD8",
            description="Prace dyplomowe i seminaria",
        )

        # Background Overlays (Free blocks, Dean's & Rector's hours)
        ov_deans = BackgroundOverlay(
            overlay_id="OV_DEANS",
            label="Godziny Dziekańskie",
            day="wednesday",
            start_time="13:00",
            end_time="15:00",
            color="#FADBD8",
            opacity=0.35,
            pattern="diagonal",
            description="Wolne od zajęć / Free blocks",
        )
        ov_rector = BackgroundOverlay(
            overlay_id="OV_RECTOR",
            label="Konsultacje / Okienko rektorskie",
            day="friday",
            start_time="10:00",
            end_time="12:00",
            color="#D4EFDF",
            opacity=0.35,
            pattern="solid",
            description="Okienko rektorskie / No classes",
        )

        # Step 3: Courses (Mandatory lectures, labs, seminars, electives with categories & colors)
        courses = [
            CourseRequirement(
                course_id="C_ARCH_W",
                subject_name="Architektura Systemów Rozproszonych (Wykład)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Lecture",
                delivery_format="Lecture",
                target_year_id="rok_4",
                is_whole_year=True,
                instructor_id="INST_KOWALSKI",
                category_id="CAT_OGOLNE",
                color="#A9CCE3",
            ),
            CourseRequirement(
                course_id="C_TEST_W",
                subject_name="Testowanie Oprogramowania (Wykład)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Lecture",
                delivery_format="Lecture",
                target_year_id="rok_4",
                is_whole_year=True,
                instructor_id="INST_NOWAK",
                category_id="CAT_OGOLNE",
                color="#A9CCE3",
            ),
            CourseRequirement(
                course_id="C_TEST_LAB_G1",
                subject_name="Testowanie Oprogramowania (Lab G1)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_group_ids=["G1"],
                instructor_id="INST_NOWAK",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
            CourseRequirement(
                course_id="C_TEST_LAB_G2",
                subject_name="Testowanie Oprogramowania (Lab G2)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_group_ids=["G2"],
                instructor_id="INST_NOWAK",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
            CourseRequirement(
                course_id="C_EMBED_LAB_G3",
                subject_name="Systemy Wbudowane (Lab G3)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Specialized Lab",
                delivery_format="Lab",
                target_year_id="rok_3",
                target_group_ids=["G3"],
                instructor_id="INST_ZIELINSKA",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
            CourseRequirement(
                course_id="C_EMBED_LAB_G4",
                subject_name="Systemy Wbudowane (Lab G4)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Specialized Lab",
                delivery_format="Lab",
                target_year_id="rok_3",
                target_group_ids=["G4"],
                instructor_id="INST_ZIELINSKA",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
            CourseRequirement(
                course_id="C_SEM_IO",
                subject_name="Seminarium Dyplomowe (Sem)",
                credit_hours=2.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Auditory/Classes",
                delivery_format="Seminar",
                target_year_id="rok_4",
                target_group_ids=["G1", "G2"],
                instructor_id="INST_WISNIEWSKI",
                category_id="CAT_DYPLOM",
                color="#FADBD8",
            ),
            CourseRequirement(
                course_id="C_ELEC_AI",
                subject_name="Przetwarzanie Danych i AI (Wybieralny)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_group_ids=["SUB_AI"],
                instructor_id="INST_KOWALSKI",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
            CourseRequirement(
                course_id="C_ELEC_SEC",
                subject_name="Cyberbezpieczeństwo Systemów (Wybieralny)",
                credit_hours=3.0,
                hours_per_week=1.5,
                duration_minutes=90,
                required_room_type="Computer Lab",
                delivery_format="Lab",
                target_year_id="rok_4",
                target_group_ids=["SUB_SEC"],
                instructor_id="INST_ZIELINSKA",
                category_id="CAT_LABS",
                color="#A9DFBF",
            ),
        ]

        # Step 4: Workers (Instructors with realistic load and forbidden windows)
        instructors = [
            Instructor(
                instructor_id="INST_KOWALSKI",
                name="Dr hab. Jan Kowalski, prof. UWM",
                max_hours_per_day=6.0,
                max_hours_per_week=18.0,
                qualified_course_ids=["C_ARCH_W", "C_ELEC_AI"],
                forbidden_windows=[
                    TimeWindow(day="friday", start_time="14:00", end_time="20:00")
                ],
            ),
            Instructor(
                instructor_id="INST_NOWAK",
                name="Dr inż. Tomasz Nowak",
                max_hours_per_day=6.0,
                max_hours_per_week=20.0,
                qualified_course_ids=["C_TEST_W", "C_TEST_LAB_G1", "C_TEST_LAB_G2"],
            ),
            Instructor(
                instructor_id="INST_ZIELINSKA",
                name="Mgr inż. Anna Zielińska",
                max_hours_per_day=6.0,
                max_hours_per_week=20.0,
                qualified_course_ids=["C_EMBED_LAB_G3", "C_EMBED_LAB_G4", "C_ELEC_SEC"],
            ),
            Instructor(
                instructor_id="INST_WISNIEWSKI",
                name="Prof. dr hab. inż. Adam Wiśniewski",
                max_hours_per_day=5.0,
                max_hours_per_week=15.0,
                qualified_course_ids=["C_SEM_IO"],
                forbidden_windows=[
                    TimeWindow(day="monday", start_time="08:00", end_time="12:00")
                ],
            ),
        ]

        # Step 5: Subgroups & Conflicts (2 elective subgroups sharing overlapping students)
        subgroups = [
            StudentSubgroup(
                subgroup_id="SUB_AI",
                name="Elective: AI & Data Science",
                student_count=14,
                parent_group_ids=["G1", "G3"],
                associated_course_ids=["C_ELEC_AI"],
            ),
            StudentSubgroup(
                subgroup_id="SUB_SEC",
                name="Elective: Cybersecurity",
                student_count=14,
                parent_group_ids=["G1", "G4"],
                associated_course_ids=["C_ELEC_SEC"],
            ),
        ]

        conflict_rules = [
            ConflictRule(
                rule_id="RULE_ELECTIVES",
                name="Electives Conflict Prevention",
                entity_a="SUB_AI",
                entity_b="SUB_SEC",
                description="AI and Security electives share G1 students and cannot overlap",
            ),
            ConflictRule(
                rule_id="RULE_ARCH_LAB",
                name="Architecture vs Lab G1",
                entity_a="C_ARCH_W",
                entity_b="C_TEST_LAB_G1",
                description="G1 students cannot overlap lecture and lab",
            ),
        ]

        # Step 6: Time Horizon & Notes
        time_horizon = TimeHorizon(
            working_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
            day_start="08:00",
            day_end="20:00",
            slot_duration_minutes=15,
            max_daily_hours_per_student=8.0,
            solver_timeout_seconds=30,
            minimize_student_gaps=True,
            minimize_worker_gaps=True,
            prevent_single_class_days=True,
        )

        return cls(
            academic_structure=academic,
            rooms=rooms,
            courses=courses,
            instructors=instructors,
            subgroups=subgroups,
            conflict_rules=conflict_rules,
            time_horizon=time_horizon,
            categories=[cat_ogolne, cat_labs, cat_dyplom],
            background_overlays=[ov_deans, ov_rector],
            campus_location_note="Wszystkie zajęcia odbywają się w budynkach Wydziału Matematyki i Informatyki (ul. Słoneczna 54).",
            dean_hours_note="W środy w godz. 13:00–15:00 obowiązują godziny dziekańskie (wolne od zajęć).",
            author_signature="Dziekan Wydziału Matematyki i Informatyki",
        )


class ScheduleProject(BaseModel):
    """Complete project workspace state serialized to .schedproj / JSON."""

    project_name: str = Field(default="Timetable Project", description="Project title")
    name: Optional[str] = Field(default=None, description="Project title alias")
    created_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    version: str = Field(default="1.0")
    config: Optional[ScheduleGenerationConfig] = Field(default=None)
    timetable: Optional[Timetable] = Field(default=None, description="Current scheduled timetable slots")
    baseline_timetable: Optional[Timetable] = Field(default=None, description="Baseline timetable for change tracking/diff")
    categories: List[ScheduleCategory] = Field(default_factory=list)
    background_overlays: List[BackgroundOverlay] = Field(default_factory=list)
    session_overrides: List[SessionOverride] = Field(default_factory=list)
    custom_notes: List[str] = Field(default_factory=list)
    campus_location_note: Optional[str] = Field(default=None)
    general_notes: List[str] = Field(default_factory=list)
    legend_categories: List[CategoryLegendItem] = Field(default_factory=list)
    dean_hours_note: Optional[str] = Field(default=None)
    author_signature: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def model_post_init(self, __context: Any) -> None:
        if self.name and (not self.project_name or self.project_name == "Timetable Project"):
            self.project_name = self.name
        elif self.project_name and not self.name:
            self.name = self.project_name

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScheduleProject:
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> ScheduleProject:
        return cls.from_dict(json.loads(json_str))

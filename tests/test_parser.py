"""Unit and integration tests for TimetableParser and dynamic layout extraction."""

from pathlib import Path
import pytest

from src.core.models import Timetable, TimetableLayout, VALID_DAYS
from src.core.parser import TimetableParser


def test_parser_loads_reference_pdf(sample_pdf_path: Path):
    """Verify that TimetableParser successfully extracts entries and layout from reference PDF."""
    parser = TimetableParser(sample_pdf_path)
    timetable = parser.parse()

    assert isinstance(timetable, Timetable)
    assert timetable.layout is not None
    assert isinstance(timetable.layout, TimetableLayout)

    all_entries = timetable.get_entries()
    assert len(all_entries) > 0, "Parser must extract at least one timetable entry from reference PDF"

    # Verify every extracted entry contains required fields
    for entry in all_entries:
        assert entry.subject.strip() != "", "Extracted entry must have a non-empty subject"
        assert entry.hours.strip() != "", "Extracted entry must have hours"
        assert "-" in entry.hours, f"Hours format invalid: {entry.hours}"
        assert entry.academic_instructor.strip() != "", "Extracted entry must have an instructor"
        assert entry.room.strip() != "", "Extracted entry must have a room"
        assert entry.type.strip() != "", "Extracted entry must have a type"


def test_parser_extracts_days_distribution(sample_pdf_path: Path):
    """Verify parser extracts schedule entries across the academic week."""
    parser = TimetableParser(sample_pdf_path)
    timetable = parser.parse()

    non_empty_days = [day for day in VALID_DAYS if len(timetable.get_entries(day)) > 0]
    assert len(non_empty_days) >= 3, f"Expected classes across multiple weekdays, got: {non_empty_days}"


def test_parser_layout_geometry_extraction(sample_pdf_path: Path):
    """Verify dynamic extraction of table dimensions, row coordinates, and header banner."""
    parser = TimetableParser(sample_pdf_path)
    timetable = parser.parse()
    layout = timetable.layout

    assert layout is not None
    # Grid bounds
    assert layout.grid_bounds.page_width > 500
    assert layout.grid_bounds.page_height > 700
    assert layout.grid_bounds.table_x1 > layout.grid_bounds.table_x0
    assert layout.grid_bounds.table_y1 > layout.grid_bounds.table_y0

    # Column metrics
    assert layout.column_metrics.day_col_width > 10
    total_schedule_width = layout.column_metrics.total_columns * layout.column_metrics.col_15m_width
    assert total_schedule_width > 200

    # Day starts calibration
    assert len(layout.row_metrics.day_y_starts) >= 4, "Should detect Y-start coordinates for weekdays"
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        if day in layout.row_metrics.day_y_starts:
            assert layout.row_metrics.day_y_starts[day] > 0

    # Banner metadata
    assert layout.banner.program_text != "" or layout.banner.term_text != ""


def test_parser_coordinate_to_hours_calibration(sample_pdf_path: Path):
    """Verify that x_coords_to_hours converts horizontal point coordinates to valid time intervals."""
    parser = TimetableParser(sample_pdf_path)
    # Calibrated coordinates: 56.0 (08:00) to 102.2 (approx 09:30)
    hours_str = parser.x_coords_to_hours(56.0, 102.2)
    assert "-" in hours_str
    start_t, end_t = hours_str.split("-")
    assert len(start_t) == 5 and ":" in start_t
    assert len(end_t) == 5 and ":" in end_t


def test_parser_nonexistent_file_raises_error(tmp_path: Path):
    """Verify that attempting to parse a non-existent PDF raises FileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.pdf"
    parser = TimetableParser(non_existent)
    with pytest.raises(FileNotFoundError):
        parser.parse()

def test_parser_footer_dedup_and_single_source_of_truth(sample_pdf_path: Path):
    """Verify parser implements single source of truth for footer data and does not duplicate notes."""
    parser = TimetableParser(sample_pdf_path)
    tt = parser.parse()
    footer = tt.layout.footer

    # 1. Warning lines are categorized under warning_lines with warning_title
    assert footer.warning_title == "UWAGA:"
    assert len(footer.warning_lines) >= 3

    # 2. General notes does not duplicate warning_lines
    assert len(footer.general_notes) == 0

    # 3. Abbreviations are extracted as structured items
    assert len(footer.abbreviations) >= 3
    abbr_texts = [item[0] for item in footer.abbreviations]
    assert any("Pr.D" in t for t in abbr_texts)

    # 4. Swatches and categories are structured
    assert len(footer.legend_items) >= 4
    assert len(footer.active_categories) >= 4


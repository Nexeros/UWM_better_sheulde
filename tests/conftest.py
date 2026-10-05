"""Pytest configuration and shared fixtures for academic timetable test suite."""

from pathlib import Path
import pytest

from src.core.models import (
    AcademicStructure,
    AcademicYear,
    BaseGroup,
    ConflictRule,
    CourseRequirement,
    Instructor,
    Room,
    ScheduleGenerationConfig,
    Specialization,
    StudentSubgroup,
    TimeHorizon,
    TimeWindow,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)
from src.core.parser import TimetableParser


@pytest.fixture(scope="session")
def sample_pdf_path() -> Path:
    """Return the absolute path to the reference academic timetable PDF."""
    pdf_path = Path(__file__).resolve().parent.parent / "input" / "IV-io 2gr zima 2026.pdf"
    assert pdf_path.exists(), f"Reference PDF not found at {pdf_path}"
    return pdf_path


@pytest.fixture
def demo_config() -> ScheduleGenerationConfig:
    """Return a pristine instance of the comprehensive academic demo configuration."""
    return ScheduleGenerationConfig.create_demo_config()


@pytest.fixture
def sample_timetable(sample_pdf_path: Path) -> Timetable:
    """Return a parsed Timetable instance from the reference PDF."""
    parser = TimetableParser(sample_pdf_path)
    tt = parser.parse()
    assert len(tt.get_entries()) > 0
    return tt


@pytest.fixture
def synthetic_timetable() -> Timetable:
    """Return an in-memory synthesized Timetable with multiple days and entries."""
    tt = Timetable()
    layout = TimetableLayout.create_default()
    layout.banner.program_text = "INFORMATYKA ROK IV semestr 7"
    layout.banner.term_text = "Zima 2026/2027"
    tt.layout = layout

    # Add sample entries for monday and tuesday
    tt.add_entry(
        "monday",
        TimetableEntry(
            subject="Architektura Oprogramowania",
            hours="08:15-09:45",
            academic_instructor="Prof. dr hab. Jan Kowalski",
            room="A1",
            type="Lecture",
            group=None,
        ),
    )
    tt.add_entry(
        "monday",
        TimetableEntry(
            subject="Testowanie Systemów",
            hours="10:00-11:30",
            academic_instructor="Dr inż. Tomasz Nowak",
            room="L204",
            type="Lab",
            group=1,
        ),
    )
    tt.add_entry(
        "tuesday",
        TimetableEntry(
            subject="Uczenie Maszynowe",
            hours="12:00-13:30",
            academic_instructor="Mgr inż. Anna Zielińska",
            room="S302",
            type="Seminar",
            group=None,
        ),
    )
    return tt

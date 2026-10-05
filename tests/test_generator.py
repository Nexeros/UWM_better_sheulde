"""Unit and integration tests for TimetablePDFGenerator, dynamic typography, and collision-free rendering."""

from pathlib import Path
import pdfplumber
import pytest

from src.core.generator import TimetablePDFGenerator
from src.core.models import Timetable, TimetableEntry, TimetableLayout


def test_generator_renders_from_sample_timetable(sample_timetable: Timetable, tmp_path: Path):
    """Verify that TimetablePDFGenerator renders a valid PDF from reference timetable data."""
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "regenerated_timetable.pdf"

    gen.generate(sample_timetable, out_pdf)

    assert out_pdf.exists(), "Generated PDF must exist on disk"
    assert out_pdf.stat().st_size > 1000, "Generated PDF must be non-empty"

    # Verify standard PDF header signature
    with open(out_pdf, "rb") as f:
        header = f.read(5)
        assert header.startswith(b"%PDF-"), f"File is not a valid PDF: {header}"

    # Verify zero layout boundary breaches on reference schedule
    assert len(gen.layout_warnings) == 0


def test_generator_renders_synthetic_timetable(synthetic_timetable: Timetable, tmp_path: Path):
    """Verify PDF generation from an in-memory synthesized Timetable with multiple entries."""
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "synthetic_schedule.pdf"

    gen.generate(synthetic_timetable, out_pdf)
    assert out_pdf.exists()
    assert out_pdf.stat().st_size > 1000
    assert len(gen.layout_warnings) == 0


def test_generator_pdf_structure_and_readability(synthetic_timetable: Timetable, tmp_path: Path):
    """Verify generated PDF can be re-opened with pdfplumber and contains extracted text."""
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "readable_schedule.pdf"
    gen.generate(synthetic_timetable, out_pdf)

    with pdfplumber.open(out_pdf) as pdf:
        assert len(pdf.pages) == 1, "Academic timetable must be formatted as single page"
        page = pdf.pages[0]
        text = page.extract_text() or ""

        # Banner text should be present
        assert "INFORMATYKA" in text or "Zima" in text
        # Subject names should be present
        assert "Architektura" in text or "Testowanie" in text or "Uczenie" in text


def test_generator_font_setup():
    """Verify font setup handles standard and Unicode fonts without crashing."""
    gen = TimetablePDFGenerator()
    fonts = gen._setup_fonts()
    assert isinstance(fonts, tuple)
    assert len(fonts) == 3
    assert any(base in fonts[0] for base in ("LiberationSans", "DejaVuSans", "Helvetica", "Arial"))


def test_auto_fitting_line_wrapping_and_font_downscaling(tmp_path: Path):
    """Verify that extended subject titles and multi-instructor names are wrapped and fitted without clipping."""
    tt = Timetable()
    tt.add_entry(
        "monday",
        TimetableEntry(
            subject="Projektowanie i implementacja wysoce skalowalnych rozproszonych systemów wbudowanych",
            hours="08:15-09:45",
            academic_instructor="Prof. dr hab. inż. Janusz Kowalski-Nowakowski / mgr inż. Adam Małysz",
            room="Audytorium Maksimum A1",
            type="Lecture",
            group=None,
        ),
    )

    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "wrapped_schedule.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.layout_warnings) == 0, "No text or card boundaries should be breached"

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Projektowanie" in text
        assert "Audytorium" in text or "Maksimum" in text


def test_concurrent_split_subgroups_and_alternating_weeks(tmp_path: Path):
    """Verify concurrent events divide available bounding boxes without overlapping."""
    tt = Timetable()
    # Concurrent split subgroups for Group 1 on Tuesday
    tt.add_entry(
        "tuesday",
        TimetableEntry(
            subject="Laboratorium AI gr 1A",
            hours="10:15-11:45",
            academic_instructor="Dr A. Kowalski",
            room="Lab 101",
            type="Laboratory",
            group=1,
        ),
    )
    tt.add_entry(
        "tuesday",
        TimetableEntry(
            subject="Laboratorium AI gr 1B",
            hours="10:15-11:45",
            academic_instructor="Dr B. Nowak",
            room="Lab 102",
            type="Laboratory",
            group=1,
        ),
    )
    # Concurrent alternating weeks on Thursday
    tt.add_entry(
        "thursday",
        TimetableEntry(
            subject="Bazy danych",
            hours="12:00-13:30",
            academic_instructor="Dr C. Wiśniewski",
            room="Aula B",
            type="Auditory/Classes",
            group=2,
            notes="(tydz. 1-7)",
        ),
    )
    tt.add_entry(
        "thursday",
        TimetableEntry(
            subject="Inżynieria wiedzy",
            hours="12:00-13:30",
            academic_instructor="Dr D. Wójcik",
            room="Aula B",
            type="Auditory/Classes",
            group=2,
            notes="(tydz. 8-15)",
        ),
    )

    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "concurrent_schedule.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.layout_warnings) == 0, "Subdivided concurrent slots must produce 0 boundary collisions"


def test_multi_hour_blocks_scaling(tmp_path: Path):
    """Verify multi-hour slots scale available bounding width and height before line wrapping."""
    tt = Timetable()
    tt.add_entry(
        "wednesday",
        TimetableEntry(
            subject="Zaawansowane programowanie aplikacji rozproszonych w środowiskach chmurowych",
            hours="12:00-15:30",  # 3.5-hour block
            academic_instructor="Prof. dr hab. inż. Janusz Kowalski",
            room="Aula Główna",
            type="Lecture",
            group=None,
        ),
    )

    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "multi_hour_schedule.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.layout_warnings) == 0

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Zaawansowane" in text
        assert "Aula" in text


def test_layout_self_validation_boundary_breach_detection():
    """Verify that _validate_element_bounds detects and logs structured warnings on breach."""
    gen = TimetablePDFGenerator()
    layout = TimetableLayout.create_default()
    entry = TimetableEntry(
        subject="Overflow Subject",
        hours="08:15-09:45",
        academic_instructor="Instructor",
        room="Room 1",
        type="Lecture",
    )

    # Intentionally test an overflowing card outside table bounds
    gen._validate_element_bounds(
        day_key="monday",
        slot=entry,
        card_box=(layout.grid_bounds.table_x1 + 10.0, 100.0, 50.0, 30.0),
        inner_box=(layout.grid_bounds.table_x1 + 12.5, 102.5, 45.0, 25.0),
        rendered_lines=[("Test line", gen.font_regular, 8.0, layout.grid_bounds.table_x1 + 12.5, 110.0)],
        layout=layout,
        day_y_start=90.0,
        day_h=150.0,
    )

    assert len(gen.layout_warnings) > 0
    assert any("[LAYOUT OVERFLOW]" in w for w in gen.layout_warnings)


def test_abbreviate_session_types():
    """Verify session types are abbreviated appropriately."""
    gen = TimetablePDFGenerator()
    assert gen._abbreviate_session_type("Lecture") == "w."
    assert gen._abbreviate_session_type("Auditory/Classes") == "ćw."
    assert gen._abbreviate_session_type("Laboratory") == "lab."
    assert gen._abbreviate_session_type("Project") == "proj."
    assert gen._abbreviate_session_type("Seminar") == "sem."
    assert gen._abbreviate_session_type("wykład") == "w."
    assert gen._abbreviate_session_type("laboratorium") == "lab."


from src.core.generator import (
    compress_subject_to_acronym,
    compress_instructor_to_initials,
    compress_room_to_acronym,
)


def test_compression_functions():
    """Verify acronym and initial compression rules for subjects, instructors, and rooms."""
    assert compress_subject_to_acronym("Advanced Computer Architecture") == "A.C.A."
    assert compress_subject_to_acronym("Programowanie Obiektowe i Zaawansowane") == "P.O.I.Z."
    assert compress_instructor_to_initials("Prof. Jan Kowalski") == "Prof. J.K."
    assert compress_instructor_to_initials("dr inż. Adam Nowak") == "dr inż. A.N."
    assert compress_room_to_acronym("Laboratorium Komputerowe L204") == "L.K. L204"


def test_generator_smart_abbreviation_and_footnote_legend(tmp_path: Path):
    """Verify oversized names trigger acronym compression with [*N] footnote references and bottom legend."""
    oversized_subject = "Super Ultra Extremely Long Course Title That Cannot Possibly Fit In Cell"
    oversized_instructor = "Prof. dr hab. inż. Jan Chryzostom Pasek-Kowalski"
    oversized_room = "Specjalistyczne Centrum Konferencyjno Audytoryjne C401"

    entries = [
        TimetableEntry(
            subject=oversized_subject,
            hours="08:15-08:30",
            academic_instructor=oversized_instructor,
            room=oversized_room,
            type="Lecture",
            group=1,
        )
    ]
    tt = Timetable(
        monday=entries,
        layout=TimetableLayout.create_default(),
    )

    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "footnotes_test_schedule.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.page_footnotes) > 0

    # Verify registered footnote entries format
    for fn in gen.page_footnotes.values():
        assert fn.marker.startswith("[*" ) and fn.marker.endswith("]")
        assert " — " in fn.legend_line
        assert fn.short_text in fn.legend_line
        assert fn.full_text in fn.legend_line

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "FOOTNOTES & ABBREVIATIONS" in text or "OBJAŚNIENIA" in text
        assert "[*1]" in text

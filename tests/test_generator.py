"""Unit and integration tests for TimetablePDFGenerator, dynamic typography, and collision-free rendering."""

from pathlib import Path
import pdfplumber
import pytest

from src.core.generator import TimetablePDFGenerator
from src.core.models import BackgroundOverlay, ScheduleCategory, Timetable, TimetableEntry, TimetableLayout


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


def test_room_invariance_rule(tmp_path: Path):
    """Verify Room Invariance Rule: Room codes/names are NEVER abbreviated into acronyms or footnotes."""
    oversized_room = "A.2.14 Lab Specjalistyczne 104"
    entry = TimetableEntry(
        subject="Operating Systems Architecture",
        hours="08:00-09:30",
        academic_instructor="Dr Jan Kowalski",
        room=oversized_room,
        type="Lecture",
    )
    tt = Timetable(monday=[entry], layout=TimetableLayout.create_default())
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "room_invariance.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    # Footnotes should NEVER contain room abbreviations (kind == 'room')
    for fn in gen.page_footnotes.values():
        assert fn.kind != "room"
        assert oversized_room not in fn.full_text


def test_multi_color_vertical_striping(tmp_path: Path):
    """Verify cells with 2 and 3 colors render vertical striping cleanly without errors."""
    entry_two_colors = TimetableEntry(
        subject="Two Color Cross-Listed",
        hours="08:00-09:30",
        academic_instructor="Instructor A",
        room="Room 101",
        type="Lecture",
        colors=["#3498DB", "#E74C3C"],
    )
    entry_three_colors = TimetableEntry(
        subject="Three Color Split Specialization",
        hours="10:00-11:30",
        academic_instructor="Instructor B",
        room="Room 102",
        type="Lab",
        colors=["#2ECC71", "#F1C40F", "#9B59B6"],
    )
    tt = Timetable(
        monday=[entry_two_colors],
        tuesday=[entry_three_colors],
        layout=TimetableLayout.create_default(),
    )
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "multi_color_stripes.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()


def test_background_overlays_rendering(tmp_path: Path):
    """Verify global background overlays (e.g. Godziny rektorskie) render with opacity and patterns."""
    overlay_diag = BackgroundOverlay(
        overlay_id="rector_hours",
        label="Godziny rektorskie",
        day="wednesday",
        start_time="12:00",
        end_time="16:00",
        color="#F39C12",
        opacity=0.25,
        pattern="diagonal",
    )
    overlay_cross = BackgroundOverlay(
        overlay_id="dean_hours",
        label="Godziny dziekańskie",
        day="friday",
        start_time="10:00",
        end_time="14:00",
        color="#9B59B6",
        opacity=0.3,
        pattern="cross",
    )
    layout = TimetableLayout.create_default()
    layout.custom_overlays = [overlay_diag, overlay_cross]
    tt = Timetable(layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "overlay_test.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Godziny rektorskie" in text or "Godziny" in text


def test_category_legend_and_canvas_notes(tmp_path: Path):
    """Verify itemized category legend bar and custom canvas notes render in footer."""
    cat1 = ScheduleCategory(category_id="cat_core", name="Core Courses", color="#3498DB")
    cat2 = ScheduleCategory(category_id="cat_elective", name="Electives", color="#9B59B6")
    layout = TimetableLayout.create_default()
    layout.categories = [cat1, cat2]
    layout.custom_notes = ["Important Note: All labs take place in building A."]
    entry = TimetableEntry(
        subject="Operating Systems",
        hours="08:00-09:30",
        academic_instructor="Prof. J. Kowalski",
        room="104",
        type="Lecture",
        category_ids=["cat_core"],
    )
    tt = Timetable(monday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "legend_notes.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Core Courses" in text
        assert "Important Note" in text


def test_zero_hardcoded_footer_content(tmp_path: Path):
    """Verify all footer content is fully parameterized with zero hardcoded strings."""
    from src.core.models import CategoryLegendItem

    # 1. Fully custom parameterized footer
    custom_campus = "Politechnika UWM, Kampus Kortowo II, Budynek A"
    custom_general_1 = "Zajecia laboratoryjne odbywaja sie w blokach 90 min."
    custom_general_2 = "Obowiazuje bezwzgledna obecnosc na pierwszych zajeciach."
    custom_dean = "Godziny rektorskie: kazda druga sroda miesiaca."
    custom_sig = "Przygotowal: Zespol Planowania Dydaktyki"

    layout = TimetableLayout.create_default()
    layout.footer.campus_location_note = custom_campus
    layout.footer.general_notes = [custom_general_1, custom_general_2]
    layout.footer.dean_hours_note = custom_dean
    layout.footer.author_signature = custom_sig
    layout.footer.legend_categories = [
        CategoryLegendItem(name="Specjalistyczne", color="#E67E22", description="Laboratoria zaawansowane"),
    ]

    entry = TimetableEntry(
        subject="Architektura Systemow",
        hours="08:00-09:30",
        academic_instructor="Dr Inz. Kowalski",
        room="Sala 101",
        type="Lecture",
    )
    tt = Timetable(monday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "zero_hardcoded_custom.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert custom_campus in text
        assert custom_general_1 in text
        assert custom_general_2 in text
        assert custom_dean in text
        assert custom_sig in text
        assert "Specjalistyczne" in text

    # 2. Blank/None footer should render without errors and without hardcoded defaults
    empty_layout = TimetableLayout.create_default()
    empty_layout.footer.campus_location_note = None
    empty_layout.footer.location_note = None
    empty_layout.footer.general_notes = []
    empty_layout.footer.warning_title = None
    empty_layout.footer.warning_lines = []
    empty_layout.footer.dean_hours_note = None
    empty_layout.footer.author_signature = None
    empty_layout.footer.legend_categories = []
    empty_layout.footer.legend_items = []
    empty_layout.deans_hour = None

    tt_empty = Timetable(monday=[entry], layout=empty_layout)
    out_empty = tmp_path / "zero_hardcoded_empty.pdf"
    gen.generate(tt_empty, out_empty)
    assert out_empty.exists()


def test_draw_striped_or_solid_background_and_cell_drawer(tmp_path: Path):
    """Verify draw_striped_or_solid_background renders solid and striped fills before text."""
    from src.core.generator import draw_striped_or_solid_background
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "bg_test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=(200, 200))

    # Test single solid color
    draw_striped_or_solid_background(c, 10, 10, 80, 40, ["#3498DB"])

    # Test two-color striped background
    draw_striped_or_solid_background(c, 10, 60, 80, 40, ["#3498DB", "#E74C3C"])

    # Test three-color striped background
    draw_striped_or_solid_background(c, 10, 110, 80, 40, ["#2ECC71", "#F1C40F", "#9B59B6"])

    c.save()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 500


def test_structured_3zone_cell_layout_engine(tmp_path: Path):
    """Verify structured 3-zone layout: Top (Subject), Middle (Instructor & Type), Bottom (Room)."""
    entry = TimetableEntry(
        subject="Programowanie Aplikacji Internetowych",
        hours="08:00-10:00",
        academic_instructor="Dr inż. Tomasz Nowak",
        room="Aula Główna A1",
        type="Lab",
        group=None,
        colors=["#BBEE3D"],
    )
    tt = Timetable(monday=[entry], layout=TimetableLayout.create_default())
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "three_zone_schedule.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.layout_warnings) == 0

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        # Full subject name preserved
        assert "Programowanie" in text
        assert "Internetowych" in text
        # Instructor with first name initials preserved
        assert "Nowak" in text or "T. Nowak" in text
        # Room preserved without ellipsis
        assert "Aula" in text
        assert "Główna" in text or "A1" in text
        assert "..." not in text


def test_multi_hour_slot_scaling_bounding_box(tmp_path: Path):
    """Verify 2-hour and 3-hour blocks utilize expanded width and height for complete readable text."""
    entry_2h = TimetableEntry(
        subject="Zaawansowane Bazy Danych i Hurtownie Informacji",
        hours="10:00-12:00",
        academic_instructor="Prof. dr hab. inż. Janusz Kowalski",
        room="Laboratorium Komputerowe 204",
        type="Lecture",
        group=None,  # Full 2-group height (~66pt)
    )
    entry_3h = TimetableEntry(
        subject="Inteligentne Systemy Wspomagania Decyzji Biznesowych",
        hours="12:00-15:00",  # 3-hour block width
        academic_instructor="Dr hab. Anna Wiśniewska",
        room="Audytorium A",
        type="Project",
        group=None,  # Full 2-group height (~66pt)
    )
    tt = Timetable(tuesday=[entry_2h, entry_3h], layout=TimetableLayout.create_default())
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "multi_hour_scaling.pdf"
    gen.generate(tt, out_pdf)

    assert out_pdf.exists()
    assert len(gen.layout_warnings) == 0

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Zaawansowane Bazy Danych" in text or "Zaawansowane" in text
        assert "Inteligentne Systemy" in text or "Inteligentne" in text
        assert "Kowalski" in text
        assert "Wiśniewska" in text


def test_category_legend_includes_background_overlays(tmp_path: Path):
    """Verify background overlays appear in the generated PDF legend alongside course categories."""
    cat1 = ScheduleCategory(category_id="cat_core", name="Wykłady ogólnowydziałowe", color="#A9CCE3")
    ov1 = BackgroundOverlay(
        overlay_id="ov_dean",
        label="Godziny Dziekańskie",
        day="wednesday",
        start_time="13:00",
        end_time="15:00",
        color="#FADBD8",
        pattern="diagonal",
        description="Free blocks / No classes",
    )
    ov2 = BackgroundOverlay(
        overlay_id="ov_rector",
        label="Godziny Rektorskie",
        day="friday",
        start_time="10:00",
        end_time="12:00",
        color="#D4EFDF",
        pattern="solid",
        description="Brak zajęć dydaktycznych",
    )
    layout = TimetableLayout.create_default()
    layout.categories = [cat1]
    layout.background_overlays = [ov1, ov2]

    entry = TimetableEntry(
        subject="Architektura Systemów",
        hours="08:00-09:30",
        academic_instructor="Prof. J. Kowalski",
        room="104",
        type="Lecture",
        category_ids=["cat_core"],
    )
    tt = Timetable(wednesday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "legend_overlays.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "Wykłady ogólnowydziałowe" in text
        assert "Godziny Dziekańskie" in text
        assert "Free blocks / No classes" in text
        assert "Godziny Rektorskie" in text
        assert "Brak zajęć dydaktycznych" in text

def test_footer_multi_column_non_overlapping(sample_timetable: Timetable, tmp_path: Path):
    """Verify footer elements are grouped into non-overlapping side-by-side columns with strict bounds."""
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "test_footer_cols.pdf"
    gen.generate(sample_timetable, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        page = pdf.pages[0]
        words = [w for w in page.extract_words() if w['top'] > 430]
        words_c1 = [w for w in words if w['x0'] < 150.0 and w['top'] < 570.0]
        words_c2 = [w for w in words if 150.0 <= w['x0'] < 315.0 and w['top'] < 570.0]
        words_c3 = [w for w in words if w['x0'] >= 315.0 and w['top'] < 570.0]

        # Column 1 should contain campus location and UWAGA notices
        c1_text = " ".join(w['text'] for w in words_c1)
        assert "Wszystkie sale" in c1_text or "Słonecznej" in c1_text
        assert "UWAGA:" in c1_text
        assert "PRACOWNIE DYPLOMOWE" in c1_text

        # Column 2 should contain Categories and swatches
        c2_text = " ".join(w['text'] for w in words_c2)
        assert "KATEGORIE I KOLORY:" in c2_text
        assert "zmiana w planie" in c2_text
        assert "specjalności" in c2_text

        # Column 3 should contain Abbreviations and Footnotes
        c3_text = " ".join(w['text'] for w in words_c3)
        assert "OBJAŚNIENIA" in c3_text
        assert "Pr.D" in c3_text
        assert "UNITY" in c3_text

        # Verify no horizontal collisions: max X of C1 < min X of C2; max X of C2 < min X of C3
        assert max(w['x1'] for w in words_c1) < min(w['x0'] for w in words_c2)
        assert max(w['x1'] for w in words_c2) < min(w['x0'] for w in words_c3)


def test_footer_dedup_abbreviation_expansions_not_readded_as_notes(tmp_path: Path):
    """Verify abbreviation expansions already in abbreviations/footnotes are never duplicated as bullet notes."""
    layout = TimetableLayout.create_default()
    layout.footer.abbreviations = [
        ("Pr.D – pracownia dyplomowa.", 10.0),
        ("Testowanie oprogr. – testowanie oprogramowania", 20.0),
    ]
    # Add duplicate abbreviation expansions to custom_notes and general_notes
    layout.custom_notes = [
        "Pr.D – pracownia dyplomowa.",
        "Testowanie oprogr. – testowanie oprogramowania",
        "Zajęcia w blokach 90-minutowych",  # Genuine general note
    ]
    layout.general_notes = [
        "Pr.D — pracownia dyplomowa",  # Slight variation
    ]

    entry = TimetableEntry(
        subject="Architektura",
        hours="08:00-09:30",
        academic_instructor="Dr Kowalski",
        room="Aula 1",
        type="Lecture",
    )
    tt = Timetable(monday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "test_dedup_notes.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        # The genuine note must be present
        assert "Zajęcia w blokach 90-minutowych" in text
        # Count occurrences of pracownia dyplomowa: exactly 1 in abbreviations column
        assert text.count("pracownia dyplomowa") == 1
        assert text.count("testowanie oprogramowania") == 1


def test_footer_zero_injection_of_hardcoded_headers_and_signatures(tmp_path: Path):
    """Verify no 'Przygotował: ...' or 'DODATKOWE UWAGI' is injected if unconfigured."""
    layout = TimetableLayout.create_default()
    layout.custom_notes = ["Zajecia rozpoczynaja sie punktualnie."]
    layout.footer.author_signature = None
    layout.footer.signatures = []

    entry = TimetableEntry(
        subject="Matematyka",
        hours="08:00-09:30",
        academic_instructor="Prof. Nowak",
        room="Aula 2",
        type="Lecture",
    )
    tt = Timetable(monday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "test_zero_hardcoded.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        text = pdf.pages[0].extract_text() or ""
        assert "DODATKOWE UWAGI" not in text
        assert "Przygotował:" not in text
        assert "Zajecia rozpoczynaja sie punktualnie." in text


def test_footer_boundary_check_and_spacing_scaling(tmp_path: Path):
    """Verify extensive notes trigger dynamic downscaling without breaching 20pt bottom page margin."""
    layout = TimetableLayout.create_default()
    layout.custom_notes = [
        f"Bardzo dluga uwaga porzadkowa numer {i} dotyczaca zasad zaliczania przedmiotu w semestrze zimowym"
        for i in range(1, 15)
    ]
    layout.footer.campus_location_note = "Wydzial Matematyki i Informatyki UWM"
    layout.footer.author_signature = "Autor: Samorzad Studencki"

    entry = TimetableEntry(
        subject="Fizyka",
        hours="08:00-09:30",
        academic_instructor="Dr Wiśniewski",
        room="Aula F",
        type="Lecture",
    )
    tt = Timetable(monday=[entry], layout=layout)
    gen = TimetablePDFGenerator()
    out_pdf = tmp_path / "test_footer_scaling.pdf"
    gen.generate(tt, out_pdf)
    assert out_pdf.exists()

    with pdfplumber.open(out_pdf) as pdf:
        page = pdf.pages[0]
        words = [w for w in page.extract_words() if w['top'] > 430]
        assert len(words) > 0
        # All words must stay strictly above the 20 pt bottom page margin (bottom < page_height - 20)
        max_bottom = max(w['bottom'] for w in words)
        assert max_bottom <= page.height - 20.0, f"Footer breached bottom margin: {max_bottom} > {page.height - 20.0}"


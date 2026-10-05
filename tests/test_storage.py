"""Unit and integration tests for storage operations, project serialization, and timetable diffing."""

from pathlib import Path
import pytest

from src.core.models import (
    CourseRequirement,
    Instructor,
    Room,
    ScheduleCategory,
    ScheduleGenerationConfig,
    ScheduleProject,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)
from src.core.storage import compute_timetable_diff, load_project, save_project


def test_save_and_load_full_project(tmp_path: Path):
    """Verify round-trip serialization of complete ScheduleProject (.schedproj / JSON)."""
    config = ScheduleGenerationConfig()
    config.time_horizon.working_days = ["monday", "tuesday", "wednesday"]
    config.categories = [
        ScheduleCategory(category_id="cat_1", name="Obligatory", color="#3498DB", description="Mandatory core courses")
    ]
    config.custom_notes = ["Classes start promptly at 8:00 AM"]

    entry = TimetableEntry(
        subject="Algorithms",
        hours="08:00-09:30",
        academic_instructor="Prof. Turing",
        room="A.1.01",
        type="Lecture",
        category_ids=["cat_1"],
        colors=["#3498DB"],
    )
    timetable = Timetable(monday=[entry], layout=TimetableLayout.create_default())

    project = ScheduleProject(
        name="Semester 1 Schedule",
        config=config,
        timetable=timetable,
        baseline_timetable=timetable,
        metadata={"author": "Dean Office", "semester": "Winter 2026"},
    )

    proj_file = tmp_path / "project.schedproj"
    save_project(project, proj_file)
    assert proj_file.exists()

    loaded = load_project(proj_file)
    assert loaded.name == "Semester 1 Schedule"
    assert loaded.metadata["author"] == "Dean Office"
    assert loaded.config is not None
    assert loaded.config.time_horizon.working_days == ["monday", "tuesday", "wednesday"]
    assert len(loaded.config.categories) == 1
    assert loaded.config.categories[0].name == "Obligatory"
    assert loaded.timetable is not None
    assert len(loaded.timetable.monday) == 1
    assert loaded.timetable.monday[0].subject == "Algorithms"
    assert loaded.timetable.monday[0].colors == ["#3498DB"]
    assert loaded.baseline_timetable is not None
    assert len(loaded.baseline_timetable.monday) == 1


def test_save_and_load_draft_partial_project(tmp_path: Path):
    """Verify saving/loading partial/draft project states without resolved schedules."""
    config = ScheduleGenerationConfig()
    config.rooms.append(Room(room_id="R101", name="Lecture Hall 101", capacity=120))
    config.instructors.append(Instructor(instructor_id="INS1", name="Dr. Euler", max_daily_hours=4.0))

    draft_project = ScheduleProject(
        name="Draft Incomplete Setup",
        config=config,
        timetable=None,
        baseline_timetable=None,
    )

    proj_file = tmp_path / "draft.schedproj"
    save_project(draft_project, proj_file)
    assert proj_file.exists()

    loaded = load_project(proj_file)
    assert loaded.name == "Draft Incomplete Setup"
    assert loaded.timetable is None
    assert loaded.baseline_timetable is None
    assert loaded.config is not None
    assert len(loaded.config.rooms) == 1
    assert loaded.config.rooms[0].room_id == "R101"
    assert len(loaded.config.instructors) == 1


def test_compute_timetable_diff_detects_changes():
    """Verify visual diff tracks added, moved/rescheduled, and edited slots, applying vertical multi-color split and audit note."""
    base_entry_1 = TimetableEntry(
        session_id="sess_1",
        subject="Linear Algebra",
        hours="08:00-09:30",
        academic_instructor="Dr. Gauss",
        room="Room 10",
        type="Lecture",
        colors=["#3498DB"],
    )
    base_entry_2 = TimetableEntry(
        session_id="sess_2",
        subject="Physics Lab",
        hours="10:00-11:30",
        academic_instructor="Prof. Newton",
        room="Lab 3",
        type="Laboratory",
        colors=["#2ECC71"],
    )
    baseline_tt = Timetable(
        monday=[base_entry_1],
        tuesday=[base_entry_2],
        layout=TimetableLayout.create_default(),
    )

    # 1. Reschedule base_entry_1 from Monday 08:00-09:30 to Monday 12:00-13:30
    curr_entry_1 = TimetableEntry(
        session_id="sess_1",
        subject="Linear Algebra",
        hours="12:00-13:30",  # Moved
        academic_instructor="Dr. Gauss",
        room="Room 10",
        type="Lecture",
        colors=["#3498DB"],
    )
    # 2. Modify base_entry_2 room from Lab 3 to Lab 7
    curr_entry_2 = TimetableEntry(
        session_id="sess_2",
        subject="Physics Lab",
        hours="10:00-11:30",
        academic_instructor="Prof. Newton",
        room="Lab 7",  # Edited room
        type="Laboratory",
        colors=["#2ECC71"],
    )
    # 3. Add brand new session on Wednesday
    curr_entry_3 = TimetableEntry(
        session_id="sess_3",
        subject="Chemistry Seminar",
        hours="14:00-15:30",
        academic_instructor="Dr. Curie",
        room="Auditorium B",
        type="Seminar",
        colors=["#9B59B6"],
    )

    current_tt = Timetable(
        monday=[curr_entry_1],
        tuesday=[curr_entry_2],
        wednesday=[curr_entry_3],
        layout=TimetableLayout.create_default(),
    )

    diff_tt, changes = compute_timetable_diff(baseline_tt, current_tt)

    # Should detect 3 modifications: rescheduled, modified, added
    assert len(changes) == 3
    change_types = {c["type"] for c in changes}
    assert "rescheduled" in change_types
    assert "modified" in change_types
    assert "added" in change_types

    # Check that multi-color vertical split preserved original colors and appended change stripe (#E67E22)
    # 1. Rescheduled Linear Algebra
    e1 = diff_tt.monday[0]
    assert e1.is_modified is True
    assert "#3498DB" in e1.colors
    assert "#E67E22" in e1.colors
    assert len(e1.colors) == 2  # Two vertical halves

    # 2. Edited Physics Lab
    e2 = diff_tt.tuesday[0]
    assert e2.is_modified is True
    assert "#2ECC71" in e2.colors
    assert "#E67E22" in e2.colors
    assert len(e2.colors) == 2

    # 3. Added Chemistry Seminar
    e3 = diff_tt.wednesday[0]
    assert e3.is_modified is True
    assert "#9B59B6" in e3.colors
    assert "#E67E22" in e3.colors

    # Check footer audit note injected
    assert any("[!] Marked cells indicate updates from previous plan version" in note for note in diff_tt.layout.custom_notes)

    # Check "Modified" category registered in layout categories
    assert any(c.name == "Modified / Change" and c.color == "#E67E22" for c in diff_tt.layout.categories)

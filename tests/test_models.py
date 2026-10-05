"""Unit tests for Timetable data models, wizard configuration schemas, and validation logic."""

import json
import pytest

from src.core.models import (
    AcademicStructure,
    AcademicYear,
    BaseGroup,
    ConflictRule,
    CourseRequirement,
    GridBounds,
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


def test_timetable_entry_validation():
    """Verify TimetableEntry validation rules for hours and string stripping."""
    entry = TimetableEntry(
        subject="  Metody Numeryczne  ",
        hours="08:15-09:45",
        academic_instructor="Dr hab. inż. Jan Kowalski ",
        room=" C101 ",
        type="Lecture",
        group=1,
    )
    assert entry.subject == "Metody Numeryczne"
    assert entry.academic_instructor == "Dr hab. inż. Jan Kowalski"
    assert entry.room == "C101"
    assert entry.start_minutes() == 8 * 60 + 15
    assert entry.end_minutes() == 9 * 60 + 45
    assert entry.duration_minutes() == 90

    # Invalid hours format raises ValueError
    with pytest.raises(ValueError):
        TimetableEntry(
            subject="Test",
            hours="8:15 to 9:45",
            academic_instructor="Inst",
            room="R1",
            type="Lab",
        )

    # Inverted hours (end before start) raises ValueError
    with pytest.raises(ValueError):
        TimetableEntry(
            subject="Test",
            hours="11:15-09:45",
            academic_instructor="Inst",
            room="R1",
            type="Lab",
        )


def test_timetable_model_serialization():
    """Verify Timetable and TimetableLayout JSON schema roundtrip."""
    tt = Timetable()
    tt.add_entry(
        "monday",
        TimetableEntry(
            subject="Systemy Rozproszone",
            hours="10:00-11:30",
            academic_instructor="Dr Kowalski",
            room="A1",
            type="Lecture",
        ),
    )
    schema_dict = tt.to_schema_dict(include_extra=True)
    assert "monday" in schema_dict
    assert len(schema_dict["monday"]) == 1
    assert schema_dict["monday"][0]["subject"] == "Systemy Rozproszone"

    # Layout default creation
    layout = TimetableLayout.create_default()
    assert layout.grid_bounds.page_width > 0
    assert layout.column_metrics.day_col_width > 0


def test_academic_structure_headcount_validation():
    """Verify that group capacities cannot exceed parent specialization capacity."""
    g1 = BaseGroup(group_id="G1", name="Group 1", student_count=20)
    g2 = BaseGroup(group_id="G2", name="Group 2", student_count=20)

    # Sum of groups (40) > specialization student_count (30) raises ValueError
    with pytest.raises(ValueError, match="exceeds specialization"):
        Specialization(spec_id="s1", name="Spec 1", student_count=30, groups=[g1, g2])

    # Valid specialization
    spec = Specialization(spec_id="s1", name="Spec 1", student_count=40, groups=[g1, g2])
    assert spec.student_count == 40


def test_schedule_generation_config_json_roundtrip(demo_config: ScheduleGenerationConfig):
    """Verify full serialization and deserialization of ScheduleGenerationConfig."""
    json_str = demo_config.to_json(indent=2)
    reconstructed = ScheduleGenerationConfig.from_json(json_str)

    assert reconstructed.academic_structure.study_cycles == demo_config.academic_structure.study_cycles
    assert len(reconstructed.academic_structure.years) == len(demo_config.academic_structure.years)
    assert len(reconstructed.rooms) == len(demo_config.rooms)
    assert len(reconstructed.courses) == len(demo_config.courses)
    assert len(reconstructed.instructors) == len(demo_config.instructors)
    assert len(reconstructed.subgroups) == len(demo_config.subgroups)
    assert len(reconstructed.conflict_rules) == len(demo_config.conflict_rules)
    assert reconstructed.time_horizon.day_start == demo_config.time_horizon.day_start
    assert reconstructed.time_horizon.day_end == demo_config.time_horizon.day_end


def test_validate_integrity_detects_all_inconsistencies():
    """Verify validate_integrity identifies missing references, foreign keys, and empty sections."""
    cfg = ScheduleGenerationConfig(
        academic_structure=AcademicStructure(
            years=[
                AcademicYear(
                    year_id="Y1",
                    name="Year 1",
                    specializations=[
                        Specialization(
                            spec_id="S1",
                            name="Spec 1",
                            student_count=30,
                            groups=[BaseGroup(group_id="G1", name="Group 1", student_count=15)],
                        )
                    ],
                )
            ]
        ),
        rooms=[Room(room_id="R101", name="Room 101", capacity=30, allowed_event_types=["Lecture"])],
        courses=[
            CourseRequirement(
                course_id="C1",
                subject_name="Intro to AI",
                credit_hours=30,
                duration_minutes=90,
                target_year_id="Y_NONEXISTENT",  # Invalid Year ID
                target_group_ids=["G_NONEXISTENT"],  # Invalid Group ID
                instructor_id="INST_UNKNOWN",  # Invalid Instructor ID
            )
        ],
        instructors=[],
        subgroups=[
            StudentSubgroup(
                subgroup_id="SG1",
                name="Subgroup 1",
                student_count=10,
                parent_group_ids=["G_NONEXISTENT_PARENT"],  # Invalid Parent Group
            )
        ],
        conflict_rules=[
            ConflictRule(
                rule_id="RULE1",
                name="Broken Rule",
                entity_a="UNKNOWN_A",
                entity_b="UNKNOWN_B",
            )
        ],
        time_horizon=TimeHorizon(),
    )

    errors = cfg.validate_integrity()
    assert len(errors) >= 5
    assert any("Y_NONEXISTENT" in e for e in errors)
    assert any("G_NONEXISTENT" in e for e in errors)
    assert any("INST_UNKNOWN" in e for e in errors)
    assert any("G_NONEXISTENT_PARENT" in e for e in errors)
    assert any("UNKNOWN_A" in e for e in errors)

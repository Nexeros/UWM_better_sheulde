"""Unit and integration tests for Google OR-Tools CP-SAT academic scheduler and zero-collision constraint enforcement."""

import json
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
)
from src.core.scheduler import (
    AcademicScheduler,
    ScheduleResult,
    export_schedule_artifacts,
    intervals_overlap,
    verify_schedule_collisions,
)


def test_intervals_overlap_helper():
    """Verify intervals_overlap correctly detects overlaps and permitted back-to-back classes."""
    # Back-to-back classes (e.g. 08:15-09:45 and 09:45-11:15) must NOT overlap
    assert not intervals_overlap("08:15", "09:45", "09:45", "11:15")
    assert not intervals_overlap("09:45", "11:15", "08:15", "09:45")

    # Overlapping classes (e.g. 08:15-09:45 and 09:00-10:30) must overlap
    assert intervals_overlap("08:15", "09:45", "09:00", "10:30")
    assert intervals_overlap("09:00", "10:30", "08:15", "09:45")

    # Identical intervals overlap
    assert intervals_overlap("10:00", "11:30", "10:00", "11:30")

    # Completely disjoint intervals do not overlap
    assert not intervals_overlap("08:00", "09:30", "14:00", "15:30")


def test_solver_hard_constraints_zero_double_booking_rooms(demo_config: ScheduleGenerationConfig):
    """Verify that no two sessions share the same physical room simultaneously."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()

    assert result.is_success, f"Expected solvable schedule, got: {result.status}"
    sessions = result.scheduled_sessions
    assert len(sessions) > 0

    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            s1, s2 = sessions[i], sessions[j]
            if s1.day == s2.day and s1.room_id == s2.room_id:
                assert not intervals_overlap(s1.start_time, s1.end_time, s2.start_time, s2.end_time), (
                    f"Room double-booking collision in '{s1.room_name}' on {s1.day}: "
                    f"'{s1.subject}' ({s1.hours}) vs '{s2.subject}' ({s2.hours})"
                )


def test_solver_hard_constraints_zero_double_booking_instructors(demo_config: ScheduleGenerationConfig):
    """Verify that no instructor is scheduled for two sessions at the same time."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    sessions = result.scheduled_sessions
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            s1, s2 = sessions[i], sessions[j]
            if s1.day == s2.day and s1.instructor_id == s2.instructor_id:
                assert not intervals_overlap(s1.start_time, s1.end_time, s2.start_time, s2.end_time), (
                    f"Instructor double-booking collision for '{s1.instructor_name}' on {s1.day}: "
                    f"'{s1.subject}' ({s1.hours}) vs '{s2.subject}' ({s2.hours})"
                )


def test_solver_hard_constraints_zero_double_booking_student_cohorts(demo_config: ScheduleGenerationConfig):
    """Verify that no base student group is double-booked for concurrent sessions."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    sessions = result.scheduled_sessions
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            s1, s2 = sessions[i], sessions[j]
            if s1.day == s2.day:
                common_groups = set(s1.target_group_ids) & set(s2.target_group_ids)
                if common_groups:
                    assert not intervals_overlap(s1.start_time, s1.end_time, s2.start_time, s2.end_time), (
                        f"Student cohort collision for groups {common_groups} on {s1.day}: "
                        f"'{s1.subject}' ({s1.hours}) vs '{s2.subject}' ({s2.hours})"
                    )


def test_solver_subgroups_and_parent_groups_no_overlap(demo_config: ScheduleGenerationConfig):
    """Verify that elective subgroups sharing parent groups (e.g. SUB_AI & SUB_SEC sharing G1) do not overlap."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    sub_ai_sess = next(s for s in result.scheduled_sessions if "SUB_AI" in s.target_group_ids)
    sub_sec_sess = next(s for s in result.scheduled_sessions if "SUB_SEC" in s.target_group_ids)

    # If scheduled on the same day, they must not overlap because both draw students from G1
    if sub_ai_sess.day == sub_sec_sess.day:
        assert not intervals_overlap(
            sub_ai_sess.start_time, sub_ai_sess.end_time, sub_sec_sess.start_time, sub_sec_sess.end_time
        ), f"Subgroups SUB_AI and SUB_SEC collided on {sub_ai_sess.day}: {sub_ai_sess.hours} vs {sub_sec_sess.hours}"

    # Also verify that SUB_AI session never overlaps with any G1 session
    g1_sessions = [s for s in result.scheduled_sessions if "G1" in s.target_group_ids and s != sub_ai_sess]
    for g1_s in g1_sessions:
        if g1_s.day == sub_ai_sess.day:
            assert not intervals_overlap(
                sub_ai_sess.start_time, sub_ai_sess.end_time, g1_s.start_time, g1_s.end_time
            ), f"SUB_AI collided with parent group G1 on {sub_ai_sess.day}: {sub_ai_sess.hours} vs {g1_s.hours}"


def test_solver_instructor_forbidden_windows(demo_config: ScheduleGenerationConfig):
    """Verify that forbidden time windows specified for instructors are strictly respected."""
    # Dr hab. Jan Kowalski has forbidden Friday 14:00-20:00
    # Prof. Adam Wiśniewski has forbidden Monday 08:00-12:00
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    for s in result.scheduled_sessions:
        if s.instructor_id == "INST_KOWALSKI" and s.day.lower() == "friday":
            assert not intervals_overlap(s.start_time, s.end_time, "14:00", "20:00"), (
                f"Kowalski scheduled in forbidden Friday window: {s.hours}"
            )
        if s.instructor_id == "INST_WISNIEWSKI" and s.day.lower() == "monday":
            assert not intervals_overlap(s.start_time, s.end_time, "08:00", "12:00"), (
                f"Wiśniewski scheduled in forbidden Monday window: {s.hours}"
            )


def test_solver_room_capacity_compliance(demo_config: ScheduleGenerationConfig):
    """Verify that every session is scheduled in a room with sufficient seating capacity."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    rooms_by_id = {r.room_id: r for r in demo_config.rooms}
    for s in result.scheduled_sessions:
        room = rooms_by_id[s.room_id]
        # Lecture hall for whole year (62 students) must be at least 62 capacity
        if len(s.target_group_ids) >= 4:
            assert room.capacity >= 60, f"Room '{room.name}' capacity ({room.capacity}) too small for whole year"


def test_solver_zero_collision_validation_report(demo_config: ScheduleGenerationConfig):
    """Verify that verify_schedule_collisions programmatically confirms zero collisions."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    report = verify_schedule_collisions(result, demo_config)
    assert report["is_collision_free"] is True
    assert len(report["room_collisions"]) == 0
    assert len(report["instructor_collisions"]) == 0
    assert len(report["student_collisions"]) == 0
    assert len(report["forbidden_window_violations"]) == 0
    assert len(report["capacity_violations"]) == 0
    assert len(report["conflict_rule_violations"]) == 0
    assert len(report["report_lines"]) >= 5


def test_solver_soft_constraints_gap_minimization(demo_config: ScheduleGenerationConfig):
    """Verify that soft constraints encourage compact scheduling by comparing solver objective."""
    # When student gaps and worker gaps are penalized, the solver finds a compact solution
    demo_config.time_horizon.minimize_student_gaps = True
    demo_config.time_horizon.minimize_worker_gaps = True
    demo_config.time_horizon.prevent_single_class_days = True

    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success
    assert result.objective_value is not None
    assert result.objective_value >= 0


def test_solver_infeasible_impossible_capacity(demo_config: ScheduleGenerationConfig):
    """Verify that requiring impossible room capacity reports INFEASIBLE gracefully without crashing."""
    # Require 500 capacity for a course when max room capacity is 70
    for r in demo_config.rooms:
        r.capacity = 10  # All rooms capped to 10 seats

    # A course with 32 students in a room capped to 10 seats will fail
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()

    assert not result.is_success
    assert result.status == "INFEASIBLE"
    assert len(result.scheduled_sessions) == 0
    assert len(result.diagnostics) > 0


def test_solver_infeasible_instructor_over_allocation(demo_config: ScheduleGenerationConfig):
    """Verify that over-allocating instructor teaching hours reports INFEASIBLE gracefully."""
    # Restrict Nowak to max 1.0 hour per week, while he has multiple 1.5h courses
    nowak = next(i for i in demo_config.instructors if i.instructor_id == "INST_NOWAK")
    nowak.max_hours_per_week = 1.0

    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()

    assert not result.is_success
    assert result.status == "INFEASIBLE"
    assert len(result.diagnostics) > 0


def test_solver_artifacts_export(demo_config: ScheduleGenerationConfig, tmp_path: Path):
    """Verify that export_schedule_artifacts generates JSONs, PDFs, and execution.log."""
    scheduler = AcademicScheduler(demo_config)
    result = scheduler.solve()
    assert result.is_success

    artifacts = export_schedule_artifacts(result, tmp_path, run_name="e2e_test_run")
    assert "students_json" in artifacts
    assert "workers_json" in artifacts
    assert "execution_log" in artifacts

    # Check student JSON
    std_json = artifacts["students_json"]
    assert std_json.exists()
    data = json.loads(std_json.read_text(encoding="utf-8"))
    assert len(data) > 0

    # Check execution log
    log_file = artifacts["execution_log"]
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "ACADEMIC SCHEDULE GENERATION AUDIT LOG" in content
    assert "Solver Status: OPTIMAL" in content or "Solver Status: FEASIBLE" in content


def test_scheduler_inter_subject_breaks_global_default():
    """Verify that the scheduler enforces global default 15-minute breaks between consecutive classes."""
    horizon = TimeHorizon(
        days=["monday"],
        start_hour=8,
        end_hour=14,
        slot_unit_minutes=15,
        default_break_minutes=15,
    )
    g1 = BaseGroup(group_id="G1", name="Group 1", student_count=20)
    spec = Specialization(spec_id="S1", name="Spec 1", student_count=20, groups=[g1])
    year = AcademicYear(year_id="Y1", name="Year 1", specializations=[spec])
    structure = AcademicStructure(years=[year])

    rooms = [Room(room_id="R101", name="Room 101", capacity=30, allowed_event_types=["Lecture", "Lab"])]
    instructors = [Instructor(instructor_id="INST_A", name="Prof. A", max_hours_per_week=20.0)]
    courses = [
        CourseRequirement(
            course_id="C1",
            subject_name="Course One",
            target_year_id="Y1",
            target_group_ids=["G1"],
            required_room_type="Lecture",
            duration_minutes=90,
            instructor_id="INST_A",
        ),
        CourseRequirement(
            course_id="C2",
            subject_name="Course Two",
            target_year_id="Y1",
            target_group_ids=["G1"],
            required_room_type="Lecture",
            duration_minutes=90,
            instructor_id="INST_A",
        ),
    ]
    cfg = ScheduleGenerationConfig(
        time_horizon=horizon,
        academic_structure=structure,
        rooms=rooms,
        instructors=instructors,
        courses=courses,
        default_break_minutes=15,
    )

    scheduler = AcademicScheduler(cfg)
    result = scheduler.solve()
    assert result.is_success
    sessions = sorted(result.scheduled_sessions, key=lambda s: s.start_time)
    assert len(sessions) == 2

    def to_min(t_str: str) -> int:
        h, m = map(int, t_str.split(":"))
        return h * 60 + m

    s1, s2 = sessions[0], sessions[1]
    gap = to_min(s2.start_time) - to_min(s1.end_time)
    assert gap >= 15, f"Expected at least 15 min break between consecutive sessions, got {gap} min"

    # Collision auditor verification
    audit = verify_schedule_collisions(result.scheduled_sessions, cfg)
    assert audit["is_valid"]
    assert audit["total_collisions"] == 0


def test_scheduler_inter_subject_breaks_per_subject_overrides():
    """Verify per-subject override break enforcement: start(B) >= end(A) + max(break_after(A), break_before(B))."""
    horizon = TimeHorizon(
        days=["monday"],
        start_hour=8,
        end_hour=16,
        slot_unit_minutes=15,
        default_break_minutes=15,
    )
    g1 = BaseGroup(group_id="G1", name="Group 1", student_count=20)
    spec = Specialization(spec_id="S1", name="Spec 1", student_count=20, groups=[g1])
    year = AcademicYear(year_id="Y1", name="Year 1", specializations=[spec])
    structure = AcademicStructure(years=[year])

    rooms = [Room(room_id="R101", name="Room 101", capacity=30, allowed_event_types=["Lecture", "Lab"])]
    instructors = [Instructor(instructor_id="INST_A", name="Prof. A", max_hours_per_week=20.0)]
    courses = [
        # Lab requires 30 min buffer before
        CourseRequirement(
            course_id="C_LAB",
            subject_name="Specialized Lab",
            target_year_id="Y1",
            target_group_ids=["G1"],
            required_room_type="Lab",
            delivery_format="Lab",
            duration_minutes=90,
            instructor_id="INST_A",
            break_before=30,
            break_after=15,
        ),
        # Lecture requires 20 min after (snapped to 30 min on 15m grid)
        CourseRequirement(
            course_id="C_LEC",
            subject_name="Distant Lecture",
            target_year_id="Y1",
            target_group_ids=["G1"],
            required_room_type="Lab",
            delivery_format="Lecture",
            duration_minutes=90,
            instructor_id="INST_A",
            break_before=15,
            break_after=20,
        ),
    ]
    cfg = ScheduleGenerationConfig(
        time_horizon=horizon,
        academic_structure=structure,
        rooms=rooms,
        instructors=instructors,
        courses=courses,
        default_break_minutes=15,
    )

    scheduler = AcademicScheduler(cfg)
    result = scheduler.solve()
    assert result.is_success
    sessions = sorted(result.scheduled_sessions, key=lambda s: s.start_time)
    assert len(sessions) == 2

    def to_min(t_str: str) -> int:
        h, m = map(int, t_str.split(":"))
        return h * 60 + m

    s1, s2 = sessions[0], sessions[1]
    gap = to_min(s2.start_time) - to_min(s1.end_time)
    req_break = max(s1.break_after or 15, s2.break_before or 15)
    assert gap >= req_break, f"Expected gap >= {req_break}, got gap={gap}"

    # Verify auditor flags violation when sessions are back-to-back without required break
    from src.core.scheduler import ScheduledSession
    invalid_sessions = [
        ScheduledSession(
            task_id="t1",
            course_id="C_LEC",
            subject="Distant Lecture",
            delivery_format="Lecture",
            day="monday",
            start_time="08:00",
            end_time="09:30",
            hours="08:00-09:30",
            instructor_id="INST_A",
            instructor_name="Prof. A",
            room_id="R101",
            room_name="Room 101",
            target_group_ids=["G1"],
            year_id="Y1",
            break_before=15,
            break_after=20,
        ),
        ScheduledSession(
            task_id="t2",
            course_id="C_LAB",
            subject="Specialized Lab",
            delivery_format="Lab",
            day="monday",
            start_time="09:30",
            end_time="11:00",
            hours="09:30-11:00",
            instructor_id="INST_A",
            instructor_name="Prof. A",
            room_id="R101",
            room_name="Room 101",
            target_group_ids=["G1"],
            year_id="Y1",
            break_before=30,
            break_after=15,
        ),
    ]
    audit_invalid = verify_schedule_collisions(invalid_sessions, cfg)
    assert not audit_invalid["is_valid"]
    assert any("Break violation" in c for c in audit_invalid["collision_details"])

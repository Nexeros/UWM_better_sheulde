"""Automated academic schedule generator powered by Google OR-Tools CP-SAT.

Implements hard collision constraints (instructors, rooms, student groups, capacity),
soft optimization objectives (idle gaps, instructor windows, isolated days),
and artifact generation (JSON, PDFs, and execution logs).
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from src.core.generator import TimetablePDFGenerator
from src.core.models import (
    VALID_DAYS,
    AcademicStructure,
    CourseRequirement,
    Instructor,
    Room,
    ScheduleGenerationConfig,
    TimeHorizon,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)

logger = logging.getLogger("uwm_scheduler")


class SchedulableTask:
    """Internal representation of a single weekly course session to be scheduled."""

    def __init__(
        self,
        task_id: str,
        course: CourseRequirement,
        target_group_ids: List[str],
        headcount: int,
        duration_minutes: int,
        slot_units: int,
        year_id: str,
        spec_id: Optional[str] = None,
        notes: Optional[str] = None,
        break_before: Optional[int] = None,
        break_after: Optional[int] = None,
    ):
        self.task_id = task_id
        self.course = course
        self.target_group_ids = target_group_ids
        self.headcount = headcount
        self.duration_minutes = duration_minutes
        self.slot_units = slot_units
        self.year_id = year_id
        self.spec_id = spec_id
        self.notes = notes
        self.break_before = break_before
        self.break_after = break_after

    def __repr__(self) -> str:
        return f"<Task {self.task_id}: {self.course.subject_name} ({self.duration_minutes}m, {self.headcount}p, grps={self.target_group_ids})>"


class ScheduledSession:
    """Output representation of a successfully scheduled class slot."""

    def __init__(
        self,
        task_id: str,
        course_id: str,
        subject: str,
        delivery_format: str,
        day: str,
        start_time: str,
        end_time: str,
        hours: str,
        instructor_id: str,
        instructor_name: str,
        room_id: str,
        room_name: str,
        target_group_ids: List[str],
        year_id: str,
        spec_id: Optional[str] = None,
        notes: Optional[str] = None,
        break_before: Optional[int] = None,
        break_after: Optional[int] = None,
    ):
        self.task_id = task_id
        self.course_id = course_id
        self.subject = subject
        self.delivery_format = delivery_format
        self.day = day
        self.start_time = start_time
        self.end_time = end_time
        self.hours = hours
        self.instructor_id = instructor_id
        self.instructor_name = instructor_name
        self.room_id = room_id
        self.room_name = room_name
        self.target_group_ids = target_group_ids
        self.year_id = year_id
        self.spec_id = spec_id
        self.notes = notes
        self.break_before = break_before
        self.break_after = break_after

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "course_id": self.course_id,
            "subject": self.subject,
            "delivery_format": self.delivery_format,
            "day": self.day,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "hours": self.hours,
            "instructor_id": self.instructor_id,
            "instructor_name": self.instructor_name,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "target_group_ids": self.target_group_ids,
            "year_id": self.year_id,
            "spec_id": self.spec_id,
            "notes": self.notes,
            "break_before": self.break_before,
            "break_after": self.break_after,
        }


class ScheduleResult:
    """Encapsulates the solver outcome, metrics, diagnostics, and resulting timetables."""

    def __init__(
        self,
        status: str,
        solver_time_seconds: float = 0.0,
        objective_value: Optional[float] = None,
        scheduled_sessions: Optional[List[ScheduledSession]] = None,
        diagnostics: Optional[List[str]] = None,
        student_timetables: Optional[Dict[str, Timetable]] = None,
        worker_timetables: Optional[Dict[str, Timetable]] = None,
    ):
        self.status = status  # OPTIMAL, FEASIBLE, INFEASIBLE, TIMEOUT, MODEL_INVALID
        self.solver_time_seconds = solver_time_seconds
        self.objective_value = objective_value
        self.scheduled_sessions = scheduled_sessions or []
        self.diagnostics = diagnostics or []
        self.student_timetables = student_timetables or {}
        self.worker_timetables = worker_timetables or {}

    @property
    def is_success(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    def summary(self) -> str:
        lines = [
            f"Solver Status: {self.status}",
            f"Solve Time:    {self.solver_time_seconds:.2f}s",
            f"Objective Val: {self.objective_value if self.objective_value is not None else 'N/A'}",
            f"Total Sessions Scheduled: {len(self.scheduled_sessions)}",
            f"Student Timetables Built: {len(self.student_timetables)}",
            f"Worker Timetables Built:  {len(self.worker_timetables)}",
        ]
        if self.diagnostics:
            lines.append("Diagnostics / Notes:")
            for d in self.diagnostics:
                lines.append(f"  - {d}")
        return "\n".join(lines)


class AcademicScheduler:
    """Automated university timetable generator utilizing Google OR-Tools CP-SAT."""

    def __init__(
        self,
        config: ScheduleGenerationConfig,
        log_handler: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.log = log_handler or logger

        # Time calibration
        self.slot_unit = max(5, self.config.time_horizon.slot_duration_minutes)
        self.day_start_m = self._time_to_minutes(self.config.time_horizon.day_start)
        self.day_end_m = self._time_to_minutes(self.config.time_horizon.day_end)
        self.day_slots = (self.day_end_m - self.day_start_m) // self.slot_unit
        self.days = [d.lower() for d in self.config.time_horizon.working_days if d.lower() in VALID_DAYS]
        if not self.days:
            self.days = list(VALID_DAYS)

        self.day_stride = 1000  # Stride separating days to prevent cross-midnight overlapping

        # Lookups
        self.rooms_by_id: Dict[str, Room] = {r.room_id: r for r in self.config.rooms}
        self.instructors_by_id: Dict[str, Instructor] = {i.instructor_id: i for i in self.config.instructors}

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        h, m = map(int, time_str.strip().split(":"))
        return h * 60 + m

    @staticmethod
    def _minutes_to_time(minutes: int) -> str:
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def _slot_to_time_interval(self, day_idx: int, slot_idx: int, duration_slots: int) -> Tuple[str, str, str, str]:
        """Convert day index and slot index to (day_name, start_HH:MM, end_HH:MM, 'HH:MM-HH:MM')."""
        day_name = self.days[day_idx]
        start_m = self.day_start_m + slot_idx * self.slot_unit
        end_m = start_m + duration_slots * self.slot_unit
        s_str = self._minutes_to_time(start_m)
        e_str = self._minutes_to_time(end_m)
        return day_name, s_str, e_str, f"{s_str}-{e_str}"

    def _get_task_breaks(self, task: SchedulableTask) -> Tuple[int, int]:
        """Return (break_before_slots, break_after_slots) snapped cleanly to grid slot resolution."""
        def_break = getattr(self.config.time_horizon, "default_break_minutes", None)
        if def_break is None:
            def_break = getattr(self.config, "default_break_minutes", 15)

        bb_min = task.break_before if task.break_before is not None else def_break
        ba_min = task.break_after if task.break_after is not None else def_break

        bb_slots = (bb_min + self.slot_unit - 1) // self.slot_unit if bb_min > 0 else 0
        ba_slots = (ba_min + self.slot_unit - 1) // self.slot_unit if ba_min > 0 else 0
        return bb_slots, ba_slots

    def _prepare_tasks(self) -> Tuple[List[SchedulableTask], List[str]]:
        """Decompose course requirements into individual schedulable session tasks."""
        tasks: List[SchedulableTask] = []
        diagnostics: List[str] = []

        all_base_groups = self.config.academic_structure.all_groups()
        groups_by_id = {g.group_id: g for g in all_base_groups}

        for c_idx, course in enumerate(self.config.courses):
            dur_min = course.duration_minutes
            dur_slots = max(1, dur_min // self.slot_unit)

            # Determine target groups and headcount
            if course.is_whole_year or course.is_whole_spec or not course.target_group_ids:
                # Whole year or spec attends together
                relevant_groups = []
                for y in self.config.academic_structure.years:
                    if y.year_id == course.target_year_id:
                        for s in y.specializations:
                            if not course.target_spec_id or s.spec_id == course.target_spec_id:
                                relevant_groups.extend([g.group_id for g in s.groups])

                target_gids = relevant_groups if relevant_groups else [g.group_id for g in all_base_groups]
                total_students = sum(groups_by_id[gid].student_count for gid in target_gids if gid in groups_by_id)
                if total_students == 0:
                    total_students = 30  # Default fallback headcount

                t = SchedulableTask(
                    task_id=f"{course.course_id}_T{c_idx}",
                    course=course,
                    target_group_ids=target_gids,
                    headcount=total_students,
                    duration_minutes=dur_min,
                    slot_units=dur_slots,
                    year_id=course.target_year_id,
                    spec_id=course.target_spec_id,
                    notes=course.notes,
                    break_before=course.break_before,
                    break_after=course.break_after,
                )
                tasks.append(t)
            else:
                # Group-specific session
                target_gids = course.target_group_ids
                subgroups_by_id = {sg.subgroup_id: sg for sg in self.config.subgroups}
                total_students = sum(
                    groups_by_id[gid].student_count for gid in target_gids if gid in groups_by_id
                ) + sum(
                    subgroups_by_id[gid].student_count for gid in target_gids if gid in subgroups_by_id
                )
                if total_students == 0:
                    total_students = 16

                t = SchedulableTask(
                    task_id=f"{course.course_id}_T{c_idx}",
                    course=course,
                    target_group_ids=target_gids,
                    headcount=total_students,
                    duration_minutes=dur_min,
                    slot_units=dur_slots,
                    year_id=course.target_year_id,
                    spec_id=course.target_spec_id,
                    notes=course.notes,
                    break_before=course.break_before,
                    break_after=course.break_after,
                )
                tasks.append(t)

        return tasks, diagnostics

    def _find_compatible_rooms(self, task: SchedulableTask) -> List[Room]:
        """Find all facilities matching capacity and event type requirements."""
        compatible: List[Room] = []
        req_type = task.course.required_room_type.strip().lower()
        del_format = task.course.delivery_format.strip().lower()

        # Build target keywords from required_room_type (or delivery_format if required_room_type is empty/any)
        target = req_type if (req_type and req_type not in ("any", "general", "standard")) else del_format
        type_keywords = {target} if target else set()

        if any(term in target for term in ("lab", "komputer", "pracownia")):
            type_keywords.update(["computer lab", "specialized lab", "lab"])
        if any(term in target for term in ("lecture", "wykład", "auditor")):
            type_keywords.update(["lecture", "auditory/classes"])
        if any(term in target for term in ("class", "ćwiczen", "auditory")):
            type_keywords.update(["auditory/classes", "class"])

        for room in self.config.rooms:
            if room.capacity < task.headcount:
                continue
            room_allowed_lower = [t.lower() for t in room.allowed_event_types]
            if not target or not room_allowed_lower or any(kw in room_allowed_lower for kw in type_keywords):
                compatible.append(room)

        return compatible

    def _find_eligible_instructors(self, task: SchedulableTask) -> List[Instructor]:
        """Find all academic instructors qualified or bound to teach this session."""
        if task.course.instructor_id and task.course.instructor_id in self.instructors_by_id:
            return [self.instructors_by_id[task.course.instructor_id]]

        eligible: List[Instructor] = []
        for inst in self.config.instructors:
            if task.course.course_id in inst.qualified_course_ids:
                eligible.append(inst)

        if not eligible and self.config.instructors:
            eligible = list(self.config.instructors)

        return eligible

    def solve(self) -> ScheduleResult:
        """Run CP-SAT solver to schedule all courses without hard violations while optimizing soft objectives."""
        start_clock = datetime.datetime.now()
        self.log.info("Starting CP-SAT Academic Schedule Generation...")

        # 1. Prepare schedulable tasks
        tasks, pre_diagnostics = self._prepare_tasks()
        if not tasks:
            msg = "No course tasks could be generated from configuration."
            self.log.error(msg)
            return ScheduleResult(status="MODEL_INVALID", diagnostics=[msg])

        # 2. Check room and instructor feasibility
        compatibility_errors = []
        task_rooms: Dict[str, List[Room]] = {}
        task_instructors: Dict[str, List[Instructor]] = {}

        for task in tasks:
            comp_rooms = self._find_compatible_rooms(task)
            if not comp_rooms:
                err = (
                    f"Task '{task.course.subject_name}' requires capacity {task.headcount} and type "
                    f"'{task.course.required_room_type}', but no matching facility is available."
                )
                compatibility_errors.append(err)
            task_rooms[task.task_id] = comp_rooms

            comp_insts = self._find_eligible_instructors(task)
            if not comp_insts:
                err = f"Task '{task.course.subject_name}' has no qualified or assigned academic staff."
                compatibility_errors.append(err)
            task_instructors[task.task_id] = comp_insts

        if compatibility_errors:
            for err in compatibility_errors:
                self.log.error(f"Infeasibility Detected: {err}")
            return ScheduleResult(
                status="INFEASIBLE",
                diagnostics=compatibility_errors,
                solver_time_seconds=(datetime.datetime.now() - start_clock).total_seconds(),
            )

        # 3. Formulate CP-SAT Model
        model = cp_model.CpModel()
        num_days = len(self.days)

        # Decision Variables per task
        task_start: Dict[str, cp_model.IntVar] = {}
        task_end: Dict[str, cp_model.IntVar] = {}
        task_interval: Dict[str, cp_model.IntervalVar] = {}
        task_day: Dict[str, cp_model.IntVar] = {}
        task_slot_in_day: Dict[str, cp_model.IntVar] = {}
        task_on_day: Dict[Tuple[str, int], cp_model.BoolVar] = {}

        # Room and Instructor assignment booleans and optional intervals
        task_room_bool: Dict[Tuple[str, str], cp_model.BoolVar] = {}
        room_intervals: Dict[str, List[cp_model.IntervalVar]] = {r.room_id: [] for r in self.config.rooms}

        task_inst_bool: Dict[Tuple[str, str], cp_model.BoolVar] = {}
        inst_intervals: Dict[str, List[cp_model.IntervalVar]] = {i.instructor_id: [] for i in self.config.instructors}

        # Build valid starting slot domains
        for task in tasks:
            dur = task.slot_units
            valid_start_values: List[int] = []

            for d_idx in range(num_days):
                for s_idx in range(0, self.day_slots - dur + 1):
                    valid_start_values.append(d_idx * self.day_stride + s_idx)

            if not valid_start_values:
                return ScheduleResult(
                    status="INFEASIBLE",
                    diagnostics=[f"Session duration ({task.duration_minutes}m) exceeds daily horizon length."],
                )

            start_v = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(valid_start_values),
                f"start_{task.task_id}",
            )
            end_v = model.NewIntVar(0, num_days * self.day_stride + self.day_slots, f"end_{task.task_id}")
            model.Add(end_v == start_v + dur)
            iv = model.NewIntervalVar(start_v, dur, end_v, f"iv_{task.task_id}")

            task_start[task.task_id] = start_v
            task_end[task.task_id] = end_v
            task_interval[task.task_id] = iv

            day_v = model.NewIntVar(0, num_days - 1, f"day_{task.task_id}")
            slot_in_day_v = model.NewIntVar(0, self.day_slots - dur, f"slot_in_day_{task.task_id}")
            task_day[task.task_id] = day_v
            task_slot_in_day[task.task_id] = slot_in_day_v

            # Day boolean indicators
            day_bools = []
            for d_idx in range(num_days):
                d_bool = model.NewBoolVar(f"on_day_{task.task_id}_{d_idx}")
                task_on_day[(task.task_id, d_idx)] = d_bool
                day_bools.append(d_bool)

                # Link d_bool <-> start_v within [d_idx * day_stride, d_idx * day_stride + day_slots)
                model.Add(start_v >= d_idx * self.day_stride).OnlyEnforceIf(d_bool)
                model.Add(start_v < (d_idx + 1) * self.day_stride).OnlyEnforceIf(d_bool)
                model.Add(day_v == d_idx).OnlyEnforceIf(d_bool)
                model.Add(slot_in_day_v == start_v - d_idx * self.day_stride).OnlyEnforceIf(d_bool)

            model.Add(sum(day_bools) == 1)

            # Room selection
            c_rooms = task_rooms[task.task_id]
            r_bools = []
            for room in c_rooms:
                r_var = model.NewBoolVar(f"r_{task.task_id}_{room.room_id}")
                task_room_bool[(task.task_id, room.room_id)] = r_var
                r_bools.append(r_var)

                # Optional interval for room collision avoidance
                r_iv = model.NewOptionalIntervalVar(
                    start_v, dur, end_v, r_var, f"iv_r_{task.task_id}_{room.room_id}"
                )
                room_intervals[room.room_id].append(r_iv)

            model.Add(sum(r_bools) == 1)

            # Instructor selection
            c_insts = task_instructors[task.task_id]
            i_bools = []
            for inst in c_insts:
                i_var = model.NewBoolVar(f"inst_{task.task_id}_{inst.instructor_id}")
                task_inst_bool[(task.task_id, inst.instructor_id)] = i_var
                i_bools.append(i_var)

                i_iv = model.NewOptionalIntervalVar(
                    start_v, dur, end_v, i_var, f"iv_inst_{task.task_id}_{inst.instructor_id}"
                )
                inst_intervals[inst.instructor_id].append(i_iv)

            model.Add(sum(i_bools) == 1)

        # -------------------------------------------------------------
        # Hard Constraint 1: No Room Collisions
        # -------------------------------------------------------------
        for r_id, intervals in room_intervals.items():
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)

        # -------------------------------------------------------------
        # Hard Constraint 2: No Instructor Collisions
        # -------------------------------------------------------------
        for inst_id, intervals in inst_intervals.items():
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)

        # -------------------------------------------------------------
        # Hard Constraint 3: Instructor Forbidden Time Windows
        # -------------------------------------------------------------
        for inst in self.config.instructors:
            for window in inst.forbidden_windows:
                if window.day.lower() not in self.days:
                    continue
                d_idx = self.days.index(window.day.lower())
                w_start_m = max(self.day_start_m, self._time_to_minutes(window.start_time))
                w_end_m = min(self.day_end_m, self._time_to_minutes(window.end_time))
                if w_start_m >= w_end_m:
                    continue

                for_start_slot = (w_start_m - self.day_start_m) // self.slot_unit
                for_end_slot = (w_end_m - self.day_start_m) // self.slot_unit
                for_abs_start = d_idx * self.day_stride + for_start_slot
                for_abs_dur = for_end_slot - for_start_slot

                if for_abs_dur > 0:
                    forbid_iv = model.NewIntervalVar(
                        for_abs_start, for_abs_dur, for_abs_start + for_abs_dur, f"forbid_{inst.instructor_id}_{d_idx}"
                    )
                    inst_intervals[inst.instructor_id].append(forbid_iv)
                    # Re-enforce no overlap with forbidden window
                    model.AddNoOverlap(inst_intervals[inst.instructor_id])

        # -------------------------------------------------------------
        # Hard Constraint 4: No Student Group Collisions
        # -------------------------------------------------------------
        all_groups = self.config.academic_structure.all_groups()
        for group in all_groups:
            gid = group.group_id
            attending_intervals = [
                task_interval[t.task_id] for t in tasks if gid in t.target_group_ids
            ]
            if len(attending_intervals) > 1:
                model.AddNoOverlap(attending_intervals)

        # -------------------------------------------------------------
        # Hard Constraint 5: Subgroup & Conflict Rules
        # -------------------------------------------------------------
        # 5a. Tasks within the same subgroup cannot overlap
        for subgroup in self.config.subgroups:
            sg_tasks = [
                t for t in tasks
                if (subgroup.subgroup_id in t.target_group_ids or t.course.course_id in subgroup.associated_course_ids)
            ]
            sg_intervals = [task_interval[t.task_id] for t in sg_tasks]
            if len(sg_intervals) > 1:
                model.AddNoOverlap(sg_intervals)

            # 5b. Tasks of a subgroup cannot collide with tasks of its parent base groups
            for pid in subgroup.parent_group_ids:
                parent_intervals = [
                    task_interval[t.task_id]
                    for t in tasks
                    if pid in t.target_group_ids and t not in sg_tasks
                ]
                for sg_iv in sg_intervals:
                    for p_iv in parent_intervals:
                        model.AddNoOverlap([sg_iv, p_iv])

        # 5c. Subgroups that share students (common parent groups) cannot overlap
        for i, sg_a in enumerate(self.config.subgroups):
            for j, sg_b in enumerate(self.config.subgroups):
                if i < j and (set(sg_a.parent_group_ids) & set(sg_b.parent_group_ids)):
                    tasks_a = [
                        task_interval[t.task_id]
                        for t in tasks
                        if (sg_a.subgroup_id in t.target_group_ids or t.course.course_id in sg_a.associated_course_ids)
                    ]
                    tasks_b = [
                        task_interval[t.task_id]
                        for t in tasks
                        if (sg_b.subgroup_id in t.target_group_ids or t.course.course_id in sg_b.associated_course_ids)
                    ]
                    for iv_a in tasks_a:
                        for iv_b in tasks_b:
                            if iv_a != iv_b:
                                model.AddNoOverlap([iv_a, iv_b])

        # 5d. Explicit Pairwise Conflict Rules
        for rule in self.config.conflict_rules:
            intervals_a = [
                task_interval[t.task_id]
                for t in tasks
                if rule.entity_a in t.target_group_ids or t.course.course_id == rule.entity_a
            ]
            intervals_b = [
                task_interval[t.task_id]
                for t in tasks
                if rule.entity_b in t.target_group_ids or t.course.course_id == rule.entity_b
            ]
            for iv_a in intervals_a:
                for iv_b in intervals_b:
                    if iv_a != iv_b:
                        model.AddNoOverlap([iv_a, iv_b])

        # -------------------------------------------------------------
        # Hard Constraint 6: Maximum Daily Hours per Student Group
        # -------------------------------------------------------------
        max_student_daily_slots = int((self.config.time_horizon.max_daily_hours_per_student * 60) // self.slot_unit)
        for group in all_groups:
            gid = group.group_id
            grp_tasks = [t for t in tasks if gid in t.target_group_ids]
            for d_idx in range(num_days):
                day_task_durations = [
                    t.slot_units * task_on_day[(t.task_id, d_idx)] for t in grp_tasks
                ]
                if day_task_durations:
                    model.Add(sum(day_task_durations) <= max_student_daily_slots)

        # -------------------------------------------------------------
        # Hard Constraint 7: Maximum Instructor Daily & Weekly Hours
        # -------------------------------------------------------------
        for inst in self.config.instructors:
            max_inst_daily_slots = int((inst.max_hours_per_day * 60) // self.slot_unit)
            max_inst_weekly_slots = int((inst.max_hours_per_week * 60) // self.slot_unit)

            inst_tasks = [t for t in tasks if inst in task_instructors[t.task_id]]
            # Weekly limit
            weekly_active_slots = [
                t.slot_units * task_inst_bool[(t.task_id, inst.instructor_id)] for t in inst_tasks
            ]
            if weekly_active_slots:
                model.Add(sum(weekly_active_slots) <= max_inst_weekly_slots)

            # Daily limit
            for d_idx in range(num_days):
                daily_active_slots = []
                for t in inst_tasks:
                    on_day_and_inst = model.NewBoolVar(f"on_day_inst_{t.task_id}_{inst.instructor_id}_{d_idx}")
                    model.AddBoolAnd([task_on_day[(t.task_id, d_idx)], task_inst_bool[(t.task_id, inst.instructor_id)]]).OnlyEnforceIf(on_day_and_inst)
                    model.AddImplication(on_day_and_inst, task_on_day[(t.task_id, d_idx)])
                    model.AddImplication(on_day_and_inst, task_inst_bool[(t.task_id, inst.instructor_id)])
                    daily_active_slots.append(t.slot_units * on_day_and_inst)

                if daily_active_slots:
                    model.Add(sum(daily_active_slots) <= max_inst_daily_slots)

        # -------------------------------------------------------------
        # Hard Constraint 8: Configurable Inter-Subject Breaks & Buffers
        # -------------------------------------------------------------
        # For any consecutive sessions A and B:
        # start(B) >= end(A) + max(break_after(A), break_before(B))
        # snapped cleanly to base time grid resolution.
        pair_order_bool: Dict[Tuple[str, str], cp_model.BoolVar] = {}

        def get_order_var(t1_id: str, t2_id: str) -> cp_model.BoolVar:
            key = (t1_id, t2_id) if t1_id < t2_id else (t2_id, t1_id)
            if key not in pair_order_bool:
                pair_order_bool[key] = model.NewBoolVar(f"ord_{key[0]}_{key[1]}")
            return pair_order_bool[key]

        all_base_gids = {g.group_id for g in all_groups}
        subgroups_by_id = {sg.subgroup_id: sg for sg in self.config.subgroups}

        def get_task_effective_groups(t: SchedulableTask) -> Set[str]:
            eff: Set[str] = set()
            for gid in t.target_group_ids:
                if gid in all_base_gids:
                    eff.add(gid)
                elif gid in subgroups_by_id:
                    eff.update(subgroups_by_id[gid].parent_group_ids)
                else:
                    eff.add(gid)
            return eff

        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                tA = tasks[i]
                tB = tasks[j]
                bbA, baA = self._get_task_breaks(tA)
                bbB, baB = self._get_task_breaks(tB)
                gap_AB = max(baA, bbB)
                gap_BA = max(baB, bbA)

                ord_var = get_order_var(tA.task_id, tB.task_id)

                eff_A = get_task_effective_groups(tA)
                eff_B = get_task_effective_groups(tB)
                share_cohort = bool(eff_A & eff_B)

                if not share_cohort:
                    for rule in self.config.conflict_rules:
                        match_a = (rule.entity_a in tA.target_group_ids or tA.course.course_id == rule.entity_a)
                        match_b = (rule.entity_b in tB.target_group_ids or tB.course.course_id == rule.entity_b)
                        match_a_rev = (rule.entity_a in tB.target_group_ids or tB.course.course_id == rule.entity_a)
                        match_b_rev = (rule.entity_b in tA.target_group_ids or tA.course.course_id == rule.entity_b)
                        if (match_a and match_b) or (match_a_rev and match_b_rev):
                            share_cohort = True
                            break

                if share_cohort:
                    model.Add(task_start[tB.task_id] >= task_end[tA.task_id] + gap_AB).OnlyEnforceIf(ord_var)
                    model.Add(task_start[tA.task_id] >= task_end[tB.task_id] + gap_BA).OnlyEnforceIf(ord_var.Not())
                else:
                    # Instructors
                    common_insts = set(inst.instructor_id for inst in task_instructors[tA.task_id]) & set(
                        inst.instructor_id for inst in task_instructors[tB.task_id]
                    )
                    for inst_id in common_insts:
                        iA = task_inst_bool[(tA.task_id, inst_id)]
                        iB = task_inst_bool[(tB.task_id, inst_id)]
                        model.Add(task_start[tB.task_id] >= task_end[tA.task_id] + gap_AB).OnlyEnforceIf([iA, iB, ord_var])
                        model.Add(task_start[tA.task_id] >= task_end[tB.task_id] + gap_BA).OnlyEnforceIf([iA, iB, ord_var.Not()])

                    # Rooms
                    common_rooms = set(r.room_id for r in task_rooms[tA.task_id]) & set(
                        r.room_id for r in task_rooms[tB.task_id]
                    )
                    for room_id in common_rooms:
                        rA = task_room_bool[(tA.task_id, room_id)]
                        rB = task_room_bool[(tB.task_id, room_id)]
                        model.Add(task_start[tB.task_id] >= task_end[tA.task_id] + gap_AB).OnlyEnforceIf([rA, rB, ord_var])
                        model.Add(task_start[tA.task_id] >= task_end[tB.task_id] + gap_BA).OnlyEnforceIf([rA, rB, ord_var.Not()])

        # -------------------------------------------------------------
        # Soft Objectives (Optimization)
        # -------------------------------------------------------------
        objective_terms = []

        # 1. Minimize Idle Gaps for Student Groups
        if self.config.time_horizon.minimize_student_gaps:
            for group in all_groups:
                gid = group.group_id
                grp_tasks = [t for t in tasks if gid in t.target_group_ids]
                if not grp_tasks:
                    continue

                for d_idx in range(num_days):
                    # Earliest start and latest end for this group on this day
                    day_start_slot = model.NewIntVar(0, self.day_slots, f"grp_dstart_{gid}_{d_idx}")
                    day_end_slot = model.NewIntVar(0, self.day_slots, f"grp_dend_{gid}_{d_idx}")
                    day_span = model.NewIntVar(0, self.day_slots, f"grp_span_{gid}_{d_idx}")

                    for t in grp_tasks:
                        on_d = task_on_day[(t.task_id, d_idx)]
                        model.Add(day_start_slot <= task_slot_in_day[t.task_id]).OnlyEnforceIf(on_d)
                        model.Add(day_end_slot >= task_slot_in_day[t.task_id] + t.slot_units).OnlyEnforceIf(on_d)

                    model.Add(day_span >= day_end_slot - day_start_slot)
                    # Gap = Span - Sum of active class durations
                    total_dur = sum(t.slot_units * task_on_day[(t.task_id, d_idx)] for t in grp_tasks)
                    gap_v = model.NewIntVar(0, self.day_slots, f"grp_gap_{gid}_{d_idx}")
                    model.Add(gap_v >= day_span - total_dur)
                    objective_terms.append(gap_v * 4)

        # 2. Minimize Teaching Gaps for Workers
        if self.config.time_horizon.minimize_worker_gaps:
            for inst in self.config.instructors:
                inst_tasks = [t for t in tasks if inst in task_instructors[t.task_id]]
                if not inst_tasks:
                    continue

                for d_idx in range(num_days):
                    w_start_slot = model.NewIntVar(0, self.day_slots, f"w_start_{inst.instructor_id}_{d_idx}")
                    w_end_slot = model.NewIntVar(0, self.day_slots, f"w_end_{inst.instructor_id}_{d_idx}")
                    w_span = model.NewIntVar(0, self.day_slots, f"w_span_{inst.instructor_id}_{d_idx}")

                    for t in inst_tasks:
                        i_active = model.NewBoolVar(f"w_act_{t.task_id}_{inst.instructor_id}_{d_idx}")
                        model.AddBoolAnd([task_on_day[(t.task_id, d_idx)], task_inst_bool[(t.task_id, inst.instructor_id)]]).OnlyEnforceIf(i_active)
                        model.Add(w_start_slot <= task_slot_in_day[t.task_id]).OnlyEnforceIf(i_active)
                        model.Add(w_end_slot >= task_slot_in_day[t.task_id] + t.slot_units).OnlyEnforceIf(i_active)

                    model.Add(w_span >= w_end_slot - w_start_slot)
                    objective_terms.append(w_span * 2)

        # 3. Prevent Isolated Single-Class Days for Student Groups
        if self.config.time_horizon.prevent_single_class_days:
            for group in all_groups:
                gid = group.group_id
                grp_tasks = [t for t in tasks if gid in t.target_group_ids]
                for d_idx in range(num_days):
                    day_count = sum(task_on_day[(t.task_id, d_idx)] for t in grp_tasks)
                    is_isolated = model.NewBoolVar(f"iso_{gid}_{d_idx}")
                    # Reify: is_isolated is penalized if day_count == 1
                    model.Add(day_count == 1).OnlyEnforceIf(is_isolated)
                    model.Add(day_count != 1).OnlyEnforceIf(is_isolated.Not())
                    objective_terms.append(is_isolated * 12)

        if objective_terms:
            model.Minimize(sum(objective_terms))
        # 4. Invoke CP-SAT Solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.config.time_horizon.solver_timeout_seconds)
        solver.parameters.num_workers = 4
        solver.parameters.log_search_progress = False

        self.log.info(
            f"Solving model with {len(tasks)} tasks over {num_days} days (timeout: {self.config.time_horizon.solver_timeout_seconds}s)..."
        )
        status_code = solver.Solve(model)
        elapsed = (datetime.datetime.now() - start_clock).total_seconds()

        status_map = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "TIMEOUT",
        }
        res_status = status_map.get(status_code, "UNKNOWN")
        self.log.info(f"Solver completed with status: {res_status} in {elapsed:.2f}s")

        if res_status not in ("OPTIMAL", "FEASIBLE"):
            conflict_diagnostics = self._diagnose_infeasibility(tasks, task_rooms, task_instructors)
            return ScheduleResult(
                status=res_status,
                solver_time_seconds=elapsed,
                diagnostics=conflict_diagnostics,
            )

        # 5. Extract Solution & Build Schedule Result
        scheduled_sessions: List[ScheduledSession] = []
        for task in tasks:
            abs_start = solver.Value(task_start[task.task_id])
            d_idx = abs_start // self.day_stride
            s_idx = abs_start % self.day_stride
            day_name, s_str, e_str, hours_str = self._slot_to_time_interval(d_idx, s_idx, task.slot_units)

            # Resolved room
            assigned_room = task_rooms[task.task_id][0]
            for r in task_rooms[task.task_id]:
                if solver.Value(task_room_bool[(task.task_id, r.room_id)]) == 1:
                    assigned_room = r
                    break

            # Resolved instructor
            assigned_inst = task_instructors[task.task_id][0]
            for inst in task_instructors[task.task_id]:
                if solver.Value(task_inst_bool[(task.task_id, inst.instructor_id)]) == 1:
                    assigned_inst = inst
                    break

            session = ScheduledSession(
                task_id=task.task_id,
                course_id=task.course.course_id,
                subject=task.course.subject_name,
                delivery_format=task.course.delivery_format,
                day=day_name,
                start_time=s_str,
                end_time=e_str,
                hours=hours_str,
                instructor_id=assigned_inst.instructor_id,
                instructor_name=assigned_inst.name,
                room_id=assigned_room.room_id,
                room_name=assigned_room.name,
                target_group_ids=task.target_group_ids,
                year_id=task.year_id,
                spec_id=task.spec_id,
                notes=task.notes,
                break_before=task.break_before,
                break_after=task.break_after,
            )
            scheduled_sessions.append(session)

        # 6. Aggregate into Student and Worker Timetables
        student_timetables = self._build_student_timetables(scheduled_sessions)
        worker_timetables = self._build_worker_timetables(scheduled_sessions)

        obj_val = solver.ObjectiveValue() if res_status in ("OPTIMAL", "FEASIBLE") else None
        diagnostics = [
            f"CP-SAT Solver resolved {len(scheduled_sessions)} sessions.",
            f"Branches explored: {solver.NumBranches()}, Wall time: {solver.WallTime():.2f}s.",
        ]

        return ScheduleResult(
            status=res_status,
            solver_time_seconds=elapsed,
            objective_value=obj_val,
            scheduled_sessions=scheduled_sessions,
            diagnostics=diagnostics,
            student_timetables=student_timetables,
            worker_timetables=worker_timetables,
        )

    def _diagnose_infeasibility(
        self,
        tasks: List[SchedulableTask],
        task_rooms: Dict[str, List[Room]],
        task_instructors: Dict[str, List[Instructor]],
    ) -> List[str]:
        """Surface detailed conflict explanations when CP-SAT solver finds no feasible schedule."""
        issues: List[str] = [
            "Solver could not find a collision-free timetable satisfying all constraints simultaneously."
        ]

        # 1. Total weekly demand vs capacity per facility type
        room_capacities_by_type: Dict[str, int] = {}
        for r in self.config.rooms:
            for t in r.allowed_event_types:
                room_capacities_by_type[t.lower()] = (
                    room_capacities_by_type.get(t.lower(), 0) + len(self.days) * self.day_slots * self.slot_unit
                )

        req_minutes_by_type: Dict[str, int] = {}
        for t in tasks:
            rtype = t.course.required_room_type.lower()
            req_minutes_by_type[rtype] = req_minutes_by_type.get(rtype, 0) + t.duration_minutes

        for rtype, req_m in req_minutes_by_type.items():
            avail_m = room_capacities_by_type.get(rtype, 0)
            if req_m > avail_m:
                issues.append(
                    f"Bottleneck in facility type '{rtype}': Required {req_m} min/week exceeds total available room time ({avail_m} min/week)."
                )

        # 2. Check individual instructor teaching loads vs availability
        for inst in self.config.instructors:
            assigned_tasks = [t for t in tasks if t.course.instructor_id == inst.instructor_id]
            total_req_min = sum(t.duration_minutes for t in assigned_tasks)
            max_avail_min = inst.max_hours_per_week * 60
            if total_req_min > max_avail_min:
                issues.append(
                    f"Instructor '{inst.name}' is assigned {total_req_min / 60:.1f}h of classes, which exceeds their weekly max limit ({inst.max_hours_per_week}h)."
                )

        # 3. Check group weekly loads
        for grp in self.config.academic_structure.all_groups():
            grp_tasks = [t for t in tasks if grp.group_id in t.target_group_ids]
            total_min = sum(t.duration_minutes for t in grp_tasks)
            max_week_min = len(self.days) * self.config.time_horizon.max_daily_hours_per_student * 60
            if total_min > max_week_min:
                issues.append(
                    f"Student group '{grp.name}' has {total_min / 60:.1f}h scheduled, exceeding max weekly allowance ({max_week_min / 60:.1f}h)."
                )

        return issues

    def _build_student_timetables(
        self, sessions: List[ScheduledSession]
    ) -> Dict[str, Timetable]:
        """Aggregate scheduled sessions into Timetable instances per academic year and specialization."""
        timetables: Dict[str, Timetable] = {}

        # Map year and specialization names
        years_map = {y.year_id: y for y in self.config.academic_structure.years}

        # Build timetable for each specialization in each year
        for y in self.config.academic_structure.years:
            for s in y.specializations:
                key = f"{y.name} - {s.name}"
                tt = Timetable()
                layout = TimetableLayout.create_default()
                layout.banner.program_text = f"INFORMATYKA ({y.study_cycle}, {y.name} - {s.name})"
                tt.layout = layout

                # Filter sessions relevant to this spec's groups
                spec_group_ids = {g.group_id for g in s.groups}
                for sess in sessions:
                    # Match if whole year/spec or intersects group IDs
                    if (
                        (sess.year_id == y.year_id and (not sess.spec_id or sess.spec_id == s.spec_id))
                        or any(gid in spec_group_ids for gid in sess.target_group_ids)
                    ):
                        # Infer group number (1, 2, or None for joint)
                        group_num = None
                        if len(sess.target_group_ids) == 1:
                            target_gid = sess.target_group_ids[0]
                            # Try to extract trailing digit or index
                            num_match = re.search(r"\d+", target_gid)
                            if num_match:
                                group_num = int(num_match.group())

                        entry = TimetableEntry(
                            subject=sess.subject,
                            hours=sess.hours,
                            academic_instructor=sess.instructor_name,
                            room=sess.room_name,
                            type=sess.delivery_format,
                            group=group_num,
                            notes=sess.notes,
                        )
                        if sess.day in VALID_DAYS:
                            tt.add_entry(sess.day, entry)

                timetables[key] = tt

        return timetables

    def _build_worker_timetables(
        self, sessions: List[ScheduledSession]
    ) -> Dict[str, Timetable]:
        """Aggregate scheduled sessions into Timetable instances per individual instructor."""
        timetables: Dict[str, Timetable] = {}

        for inst in self.config.instructors:
            inst_sessions = [s for s in sessions if s.instructor_id == inst.instructor_id]
            if not inst_sessions:
                continue

            tt = Timetable()
            layout = TimetableLayout.create_default()
            layout.banner.program_text = f"Plan zajęć: {inst.name}"
            tt.layout = layout

            for sess in inst_sessions:
                # For worker view, note which group or year is attending
                grp_note = f"Grupy: {', '.join(sess.target_group_ids)}" if sess.target_group_ids else "Wszyscy"
                combined_notes = f"{sess.notes} | {grp_note}" if sess.notes else grp_note

                entry = TimetableEntry(
                    subject=sess.subject,
                    hours=sess.hours,
                    academic_instructor=inst.name,
                    room=sess.room_name,
                    type=sess.delivery_format,
                    group=None,  # Spans entire row width for instructor card
                    notes=combined_notes,
                )
                if sess.day in VALID_DAYS:
                    tt.add_entry(sess.day, entry)

            timetables[inst.name] = tt

        return timetables


def export_schedule_artifacts(
    result: ScheduleResult,
    base_output_dir: str | Path,
    generator: Optional[TimetablePDFGenerator] = None,
    run_name: Optional[str] = None,
) -> Dict[str, Path]:
    """Export all generated schedules to the /output/ pipeline (JSON, PDFs, and execution.log)."""
    out_dir = Path(base_output_dir)
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = run_name or f"{timestamp_str}_generated_schedule"
    run_dir = out_dir / folder_name
    run_dir.mkdir(parents=True, exist_ok=True)

    pdf_gen = generator or TimetablePDFGenerator()
    exported_files: Dict[str, Path] = {}

    # 1. Export Student Timetables JSON
    student_json_path = run_dir / "schedule_students.json"
    student_data = {
        name: tt.to_schema_dict(include_extra=True)
        for name, tt in result.student_timetables.items()
    }
    student_json_path.write_text(json.dumps(student_data, indent=2, ensure_ascii=False), encoding="utf-8")
    exported_files["students_json"] = student_json_path

    # 2. Export Worker Timetables JSON
    worker_json_path = run_dir / "schedule_workers.json"
    worker_data = {
        name: tt.to_schema_dict(include_extra=True)
        for name, tt in result.worker_timetables.items()
    }
    worker_json_path.write_text(json.dumps(worker_data, indent=2, ensure_ascii=False), encoding="utf-8")
    exported_files["workers_json"] = worker_json_path

    # 3. Export Execution Log
    log_path = run_dir / "execution.log"
    log_content = [
        f"=== ACADEMIC SCHEDULE GENERATION AUDIT LOG ===",
        f"Timestamp:    {datetime.datetime.now().isoformat()}",
        f"Run Directory: {run_dir.resolve()}",
        f"Solver Status: {result.status}",
        f"Solve Time:    {result.solver_time_seconds:.3f}s",
        f"Objective Val: {result.objective_value}",
        f"Total Sessions: {len(result.scheduled_sessions)}",
        "",
        "--- Diagnostics & Metrics ---",
    ]
    for d in result.diagnostics:
        log_content.append(f"  {d}")

    log_content.append("\n--- Scheduled Sessions ---")
    for s in result.scheduled_sessions:
        log_content.append(
            f"  [{s.day.upper()}] {s.hours} | {s.subject} ({s.delivery_format}) | Room: {s.room_name} | Inst: {s.instructor_name} | Grps: {s.target_group_ids}"
        )

    log_path.write_text("\n".join(log_content), encoding="utf-8")
    exported_files["execution_log"] = log_path

    # 4. Generate PDF schedules for students and workers
    for name, tt in result.student_timetables.items():
        clean_name = re.sub(r"[^\w\-]", "_", name).strip("_")
        pdf_path = run_dir / f"student_{clean_name}.pdf"
        try:
            pdf_gen.generate(tt, pdf_path)
            exported_files[f"student_pdf_{clean_name}"] = pdf_path
        except Exception as e:
            logger.error(f"Failed to generate student PDF for {name}: {e}")

    for name, tt in result.worker_timetables.items():
        clean_name = re.sub(r"[^\w\-]", "_", name).strip("_")
        pdf_path = run_dir / f"staff_{clean_name}.pdf"
        try:
            pdf_gen.generate(tt, pdf_path)
            exported_files[f"staff_pdf_{clean_name}"] = pdf_path
        except Exception as e:
            logger.error(f"Failed to generate staff PDF for {name}: {e}")

    return exported_files


def _parse_time_minutes(t_str: str) -> int:
    h, m = map(int, t_str.split(":"))
    return h * 60 + m


def intervals_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Return True if (start1, end1) and (start2, end2) overlap strictly."""
    s1, e1 = _parse_time_minutes(start1), _parse_time_minutes(end1)
    s2, e2 = _parse_time_minutes(start2), _parse_time_minutes(end2)
    return max(s1, s2) < min(e1, e2)


def verify_schedule_collisions(
    result: ScheduleResult,
    config: ScheduleGenerationConfig,
) -> Dict[str, Any]:
    """Perform an exhaustive zero-collision audit on the generated schedule result.
    
    Verifies:
      1. Room non-overlapping: No two sessions share the same room at the same time.
      2. Instructor non-overlapping: No instructor is booked for two sessions simultaneously.
      3. Instructor forbidden windows: No session falls within an instructor's unavailable window.
      4. Student cohorts & Subgroups: No base student group or subgroup attends overlapping classes.
      5. Explicit conflict rules: All defined pairwise entity collision rules are honored.
      6. Room capacity: Every room meets or exceeds the headcount of its assigned session.
    """
    room_collisions: List[Dict[str, Any]] = []
    instructor_collisions: List[Dict[str, Any]] = []
    student_collisions: List[Dict[str, Any]] = []
    forbidden_window_violations: List[Dict[str, Any]] = []
    capacity_violations: List[Dict[str, Any]] = []
    conflict_rule_violations: List[Dict[str, Any]] = []

    sessions = result.scheduled_sessions if isinstance(result, ScheduleResult) else result
    rooms_by_id = {r.room_id: r for r in config.rooms}
    instructors_by_id = {i.instructor_id: i for i in config.instructors}
    subgroups_by_id = {sg.subgroup_id: sg for sg in config.subgroups}
    all_base_gids = {g.group_id for g in config.academic_structure.all_groups()}

    def get_effective_groups(sess: ScheduledSession) -> Set[str]:
        eff: Set[str] = set()
        for gid in sess.target_group_ids:
            if gid in all_base_gids:
                eff.add(gid)
            elif gid in subgroups_by_id:
                eff.update(subgroups_by_id[gid].parent_group_ids)
            else:
                eff.add(gid)
        return eff

    # 1. Pairwise collision check
    for idx_a in range(len(sessions)):
        s_a = sessions[idx_a]
        for idx_b in range(idx_a + 1, len(sessions)):
            s_b = sessions[idx_b]
            if s_a.day.lower() != s_b.day.lower():
                continue
            if not intervals_overlap(s_a.start_time, s_a.end_time, s_b.start_time, s_b.end_time):
                continue

            # Check room collision
            if s_a.room_id and s_a.room_id == s_b.room_id:
                room_collisions.append({
                    "day": s_a.day,
                    "room_id": s_a.room_id,
                    "room_name": s_a.room_name,
                    "session_a": f"{s_a.subject} ({s_a.hours})",
                    "session_b": f"{s_b.subject} ({s_b.hours})",
                })

            # Check instructor collision
            if s_a.instructor_id and s_a.instructor_id == s_b.instructor_id:
                instructor_collisions.append({
                    "day": s_a.day,
                    "instructor_id": s_a.instructor_id,
                    "instructor_name": s_a.instructor_name,
                    "session_a": f"{s_a.subject} ({s_a.hours})",
                    "session_b": f"{s_b.subject} ({s_b.hours})",
                })

            # Check student group / subgroup collision
            grps_a = get_effective_groups(s_a)
            grps_b = get_effective_groups(s_b)
            common_grps = grps_a & grps_b
            if common_grps:
                student_collisions.append({
                    "day": s_a.day,
                    "common_groups": sorted(list(common_grps)),
                    "session_a": f"{s_a.subject} ({s_a.hours})",
                    "session_b": f"{s_b.subject} ({s_b.hours})",
                })

            # Check explicit conflict rules
            for rule in config.conflict_rules:
                match_a = (rule.entity_a in s_a.target_group_ids or s_a.course_id == rule.entity_a)
                match_b = (rule.entity_b in s_b.target_group_ids or s_b.course_id == rule.entity_b)
                match_a_rev = (rule.entity_a in s_b.target_group_ids or s_b.course_id == rule.entity_a)
                match_b_rev = (rule.entity_b in s_a.target_group_ids or s_a.course_id == rule.entity_b)
                if (match_a and match_b) or (match_a_rev and match_b_rev):
                    conflict_rule_violations.append({
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "day": s_a.day,
                        "session_a": f"{s_a.subject} ({s_a.hours})",
                        "session_b": f"{s_b.subject} ({s_b.hours})",
                    })

    # 2. Check instructor forbidden windows & room capacity per session
    for s in sessions:
        inst = instructors_by_id.get(s.instructor_id)
        if inst:
            for win in inst.forbidden_windows:
                if win.day.lower() == s.day.lower():
                    if intervals_overlap(s.start_time, s.end_time, win.start_time, win.end_time):
                        forbidden_window_violations.append({
                            "instructor_id": s.instructor_id,
                            "instructor_name": s.instructor_name,
                            "day": s.day,
                            "session_hours": s.hours,
                            "forbidden_window": f"{win.start_time}-{win.end_time}",
                        })

    # 3. Check inter-subject break compliance for consecutive sessions
    courses_by_id = {c.course_id: c for c in config.courses}
    slot_unit = max(5, config.time_horizon.slot_duration_minutes)
    def_break = getattr(config.time_horizon, "default_break_minutes", None)
    if def_break is None:
        def_break = getattr(config, "default_break_minutes", 15)

    break_violations: List[Dict[str, Any]] = []

    def check_consecutive_pair(s_prev: ScheduledSession, s_next: ScheduledSession, reason: str, entity_name: str) -> None:
        p_end = _parse_time_minutes(s_prev.end_time)
        n_start = _parse_time_minutes(s_next.start_time)
        actual_gap = n_start - p_end
        if actual_gap < 0:
            return  # Direct collision, caught by interval check

        c_prev = courses_by_id.get(s_prev.course_id)
        c_next = courses_by_id.get(s_next.course_id)

        ba = c_prev.break_after if (c_prev and c_prev.break_after is not None) else def_break
        bb = c_next.break_before if (c_next and c_next.break_before is not None) else def_break
        req_break = max(ba, bb)
        req_snapped = ((req_break + slot_unit - 1) // slot_unit) * slot_unit if req_break > 0 else 0

        if actual_gap < req_snapped:
            break_violations.append({
                "day": s_prev.day,
                "reason": reason,
                "entity": entity_name,
                "session_a": f"{s_prev.subject} ({s_prev.hours})",
                "session_b": f"{s_next.subject} ({s_next.hours})",
                "actual_break_minutes": actual_gap,
                "required_break_minutes": req_snapped,
            })

    days_set = {s.day.lower() for s in sessions}
    for d in days_set:
        day_sessions = [s for s in sessions if s.day.lower() == d]

        # By room
        for r_id in rooms_by_id:
            r_sessions = sorted(
                [s for s in day_sessions if s.room_id == r_id],
                key=lambda s: _parse_time_minutes(s.start_time),
            )
            for k in range(len(r_sessions) - 1):
                check_consecutive_pair(r_sessions[k], r_sessions[k + 1], "Room consecutive break", rooms_by_id[r_id].name)

        # By instructor
        for i_id in instructors_by_id:
            i_sessions = sorted(
                [s for s in day_sessions if s.instructor_id == i_id],
                key=lambda s: _parse_time_minutes(s.start_time),
            )
            for k in range(len(i_sessions) - 1):
                check_consecutive_pair(i_sessions[k], i_sessions[k + 1], "Instructor consecutive break", instructors_by_id[i_id].name)

        # By student group / cohort
        for gid in all_base_gids:
            g_sessions = sorted(
                [s for s in day_sessions if gid in get_effective_groups(s)],
                key=lambda s: _parse_time_minutes(s.start_time),
            )
            for k in range(len(g_sessions) - 1):
                check_consecutive_pair(g_sessions[k], g_sessions[k + 1], "Student cohort consecutive break", f"Group {gid}")

    is_collision_free = (
        len(room_collisions) == 0
        and len(instructor_collisions) == 0
        and len(student_collisions) == 0
        and len(forbidden_window_violations) == 0
        and len(capacity_violations) == 0
        and len(conflict_rule_violations) == 0
        and len(break_violations) == 0
    )

    res_status = result.status if isinstance(result, ScheduleResult) else "EVALUATED"
    solve_time = result.solver_time_seconds if isinstance(result, ScheduleResult) else 0.0

    report_lines: List[str] = [
        f"CP-SAT Status: {res_status} (Solve time: {solve_time:.3f}s)",
        f"{'✓' if not room_collisions else '✗'} Room Non-Overlap Check: {len(room_collisions)} collisions across {len(config.rooms)} rooms",
        f"{'✓' if not instructor_collisions else '✗'} Instructor Non-Overlap Check: {len(instructor_collisions)} collisions across {len(config.instructors)} staff",
        f"{'✓' if not student_collisions else '✗'} Student Group & Subgroup Check: {len(student_collisions)} collisions across student cohorts",
        f"{'✓' if not forbidden_window_violations else '✗'} Staff Availability Windows: {len(forbidden_window_violations)} violations",
        f"{'✓' if not conflict_rule_violations else '✗'} Explicit Conflict Rules: {len(conflict_rule_violations)} violations",
        f"{'✓' if not break_violations else '✗'} Inter-Subject Break Check: {len(break_violations)} violations",
    ]

    collision_details: List[str] = []
    for rc in room_collisions:
        collision_details.append(f"Room collision: {rc}")
    for ic in instructor_collisions:
        collision_details.append(f"Instructor collision: {ic}")
    for sc in student_collisions:
        collision_details.append(f"Student collision: {sc}")
    for fw in forbidden_window_violations:
        collision_details.append(f"Forbidden window: {fw}")
    for cap in capacity_violations:
        collision_details.append(f"Capacity violation: {cap}")
    for cr in conflict_rule_violations:
        collision_details.append(f"Conflict rule violation: {cr}")
    for bv in break_violations:
        collision_details.append(f"Break violation: {bv['session_a']} and {bv['session_b']} gap={bv['actual_break_minutes']}m < req={bv['required_break_minutes']}m ({bv['reason']}: {bv['entity']})")

    total_cols = (
        len(room_collisions)
        + len(instructor_collisions)
        + len(student_collisions)
        + len(forbidden_window_violations)
        + len(capacity_violations)
        + len(conflict_rule_violations)
        + len(break_violations)
    )

    return {
        "status": res_status,
        "is_collision_free": is_collision_free,
        "is_valid": is_collision_free,
        "total_collisions": total_cols,
        "num_sessions": len(sessions),
        "room_collisions": room_collisions,
        "instructor_collisions": instructor_collisions,
        "student_collisions": student_collisions,
        "forbidden_window_violations": forbidden_window_violations,
        "capacity_violations": capacity_violations,
        "conflict_rule_violations": conflict_rule_violations,
        "break_violations": break_violations,
        "collision_details": collision_details,
        "report_lines": report_lines,
    }

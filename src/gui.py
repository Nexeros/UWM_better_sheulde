"""Graphical User Interface for timetable editing and automated schedule generation wizard."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from src.core.generator import TimetablePDFGenerator
from src.core.models import (
    VALID_DAYS,
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
)
from src.core.parser import TimetableParser
from src.core.scheduler import AcademicScheduler, ScheduleResult, export_schedule_artifacts, verify_schedule_collisions
from src.core.storage import StorageManager, ensure_input_directory


# =====================================================================
# Editor Slot Dialog
# =====================================================================

class SlotDialog(tk.Toplevel):
    """Modal dialog for adding or editing a timetable slot with full keyboard navigation."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        title: str,
        initial_day: str = "monday",
        entry: Optional[TimetableEntry] = None,
    ):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[Tuple[str, TimetableEntry]] = None
        self.initial_day = initial_day
        self.entry = entry

        self._build_ui()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))

        # Keyboard shortcuts inside dialog
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.grid(row=0, column=0, sticky=(tk.N, tk.W, tk.E, tk.S))

        # Day
        ttk.Label(frame, text="Day of Week:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.day_var = tk.StringVar(value=self.initial_day)
        self.day_combo = ttk.Combobox(
            frame, textvariable=self.day_var, values=list(VALID_DAYS), state="readonly", width=25
        )
        self.day_combo.grid(row=0, column=1, sticky=tk.W, pady=4)

        # Subject
        ttk.Label(frame, text="Subject:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.subject_var = tk.StringVar(value=self.entry.subject if self.entry else "")
        self.subject_entry = ttk.Entry(frame, textvariable=self.subject_var, width=27)
        self.subject_entry.grid(row=1, column=1, sticky=tk.W, pady=4)

        # Hours
        ttk.Label(frame, text="Hours (HH:MM-HH:MM):").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.hours_var = tk.StringVar(value=self.entry.hours if self.entry else "08:15-09:45")
        self.hours_entry = ttk.Entry(frame, textvariable=self.hours_var, width=27)
        self.hours_entry.grid(row=2, column=1, sticky=tk.W, pady=4)

        # Instructor
        ttk.Label(frame, text="Instructor:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.instructor_var = tk.StringVar(value=self.entry.academic_instructor if self.entry else "")
        self.instructor_entry = ttk.Entry(frame, textvariable=self.instructor_var, width=27)
        self.instructor_entry.grid(row=3, column=1, sticky=tk.W, pady=4)

        # Room
        ttk.Label(frame, text="Room:").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.room_var = tk.StringVar(value=self.entry.room if self.entry else "")
        self.room_entry = ttk.Entry(frame, textvariable=self.room_var, width=27)
        self.room_entry.grid(row=4, column=1, sticky=tk.W, pady=4)

        # Type
        ttk.Label(frame, text="Type:").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.type_var = tk.StringVar(value=self.entry.type if self.entry else "Lab")
        self.type_combo = ttk.Combobox(
            frame,
            textvariable=self.type_var,
            values=["Lecture", "Lab", "Seminar", "Project", "Class"],
            state="readonly",
            width=25,
        )
        self.type_combo.grid(row=5, column=1, sticky=tk.W, pady=4)

        # Group
        ttk.Label(frame, text="Group (1, 2, or blank):").grid(row=6, column=0, sticky=tk.W, pady=4)
        grp_val = str(self.entry.group) if (self.entry and self.entry.group is not None) else ""
        self.group_var = tk.StringVar(value=grp_val)
        self.group_entry = ttk.Entry(frame, textvariable=self.group_var, width=27)
        self.group_entry.grid(row=6, column=1, sticky=tk.W, pady=4)

        # Notes
        ttk.Label(frame, text="Notes:").grid(row=7, column=0, sticky=tk.W, pady=4)
        self.notes_var = tk.StringVar(value=(self.entry.notes or "") if self.entry else "")
        self.notes_entry = ttk.Entry(frame, textvariable=self.notes_var, width=27)
        self.notes_entry.grid(row=7, column=1, sticky=tk.W, pady=4)

        # Buttons
        btn_frame = ttk.Frame(frame, padding="10 10 0 0")
        btn_frame.grid(row=8, column=0, columnspan=2, sticky=tk.E)

        cancel_btn = ttk.Button(btn_frame, text="Cancel (Esc)", command=self._on_cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=5)
        confirm_btn = ttk.Button(btn_frame, text="Confirm (Enter)", command=self._on_confirm)
        confirm_btn.pack(side=tk.RIGHT)

        self.after(50, lambda: self.subject_entry.focus_set())

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def _on_confirm(self) -> None:
        subject = self.subject_var.get().strip()
        hours = self.hours_var.get().strip()
        instructor = self.instructor_var.get().strip()
        room = self.room_var.get().strip()
        slot_type = self.type_var.get().strip()
        day = self.day_var.get().strip().lower()

        grp_str = self.group_var.get().strip()
        group = int(grp_str) if grp_str.isdigit() else None
        notes = self.notes_var.get().strip() or None

        if not subject or not hours or not instructor or not room:
            messagebox.showerror(
                "Validation Error",
                "Please fill in all required fields (Subject, Hours, Instructor, Room).",
                parent=self,
            )
            return

        try:
            entry = TimetableEntry(
                subject=subject,
                hours=hours,
                academic_instructor=instructor,
                room=room,
                type=slot_type,  # type: ignore[arg-type]
                group=group,
                notes=notes,
            )
            self.result = (day, entry)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Format Error", str(e), parent=self)


# =====================================================================
# Wizard Dialogs: Academic Structure, Facilities, Staff, Courses, etc.
# =====================================================================

class RoomDialog(tk.Toplevel):
    """Dialog to create/edit a room."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, room: Optional[Room] = None):
        super().__init__(parent)
        self.title("Edit Room" if room else "Add New Room")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.room = room
        self.result: Optional[Room] = None

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Room ID (e.g. 'E_1_16'):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.room.room_id if self.room else "")
        ttk.Entry(frame, textvariable=self.id_var, width=25).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name (e.g. 'E 1/16'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.room.name if self.room else "")
        ttk.Entry(frame, textvariable=self.name_var, width=25).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Capacity (Seats):").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.cap_var = tk.StringVar(value=str(self.room.capacity if self.room else 30))
        ttk.Entry(frame, textvariable=self.cap_var, width=25).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Allowed Event Types:").grid(row=3, column=0, sticky=tk.NW, pady=4)
        types_frame = ttk.Frame(frame)
        types_frame.grid(row=3, column=1, sticky=tk.W, pady=4)

        self.type_checks: Dict[str, tk.BooleanVar] = {}
        standard_types = ["Lecture", "Auditory/Classes", "Computer Lab", "Specialized Lab"]
        curr_types = self.room.allowed_event_types if self.room else standard_types
        for t in standard_types:
            var = tk.BooleanVar(value=t in curr_types)
            self.type_checks[t] = var
            ttk.Checkbutton(types_frame, text=t, variable=var).pack(anchor=tk.W)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=4, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

    def _on_confirm(self) -> None:
        rid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cap_str = self.cap_var.get().strip()
        selected_types = [t for t, v in self.type_checks.items() if v.get()]

        if not rid or not name or not cap_str.isdigit() or int(cap_str) <= 0:
            messagebox.showerror("Error", "Please provide a valid Room ID, Name, and positive Capacity.", parent=self)
            return

        self.result = Room(
            room_id=rid,
            name=name,
            capacity=int(cap_str),
            allowed_event_types=selected_types or ["Lecture", "Auditory/Classes", "Computer Lab", "Specialized Lab"],
        )
        self.destroy()


class CourseDialog(tk.Toplevel):
    """Dialog to create/edit a course requirement."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        course: Optional[CourseRequirement] = None,
        available_years: Optional[List[str]] = None,
        available_groups: Optional[List[str]] = None,
        available_instructors: Optional[List[Tuple[str, str]]] = None,
    ):
        super().__init__(parent)
        self.title("Edit Course" if course else "Add New Course")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.course = course
        self.available_years = available_years or ["rok_4"]
        self.available_groups = available_groups or ["G1", "G2"]
        self.available_instructors = available_instructors or []
        self.result: Optional[CourseRequirement] = None

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        # ID & Name
        ttk.Label(frame, text="Course ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.course.course_id if self.course else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Subject Name:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.course.subject_name if self.course else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        # Duration & Hours
        ttk.Label(frame, text="Duration (Minutes):").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.dur_var = tk.StringVar(value=str(self.course.duration_minutes if self.course else 90))
        ttk.Combobox(frame, textvariable=self.dur_var, values=["45", "90", "135", "180"], width=26).grid(
            row=2, column=1, sticky=tk.W, pady=4
        )

        # Delivery format & Room type
        ttk.Label(frame, text="Delivery Format:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.fmt_var = tk.StringVar(value=self.course.delivery_format if self.course else "Lab")
        ttk.Combobox(frame, textvariable=self.fmt_var, values=["Lecture", "Lab", "Class", "Seminar", "Project"], width=26).grid(
            row=3, column=1, sticky=tk.W, pady=4
        )

        ttk.Label(frame, text="Required Facility:").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.room_type_var = tk.StringVar(value=self.course.required_room_type if self.course else "Computer Lab")
        ttk.Combobox(
            frame,
            textvariable=self.room_type_var,
            values=["Lecture", "Auditory/Classes", "Computer Lab", "Specialized Lab"],
            width=26,
        ).grid(row=4, column=1, sticky=tk.W, pady=4)

        # Target Year
        ttk.Label(frame, text="Academic Year:").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.year_var = tk.StringVar(value=self.course.target_year_id if self.course else self.available_years[0])
        ttk.Combobox(frame, textvariable=self.year_var, values=self.available_years, width=26).grid(
            row=5, column=1, sticky=tk.W, pady=4
        )

        # Whole year vs group
        ttk.Label(frame, text="Cohort Scope:").grid(row=6, column=0, sticky=tk.W, pady=4)
        scope_frame = ttk.Frame(frame)
        scope_frame.grid(row=6, column=1, sticky=tk.W, pady=4)
        self.is_whole_year_var = tk.BooleanVar(value=self.course.is_whole_year if self.course else False)
        ttk.Checkbutton(scope_frame, text="Whole Year attends together (Lecture)", variable=self.is_whole_year_var).pack(
            anchor=tk.W
        )

        ttk.Label(frame, text="Target Groups (e.g. 'G1'):").grid(row=7, column=0, sticky=tk.W, pady=4)
        target_g = ", ".join(self.course.target_group_ids) if self.course else "G1"
        self.groups_var = tk.StringVar(value=target_g)
        ttk.Entry(frame, textvariable=self.groups_var, width=28).grid(row=7, column=1, sticky=tk.W, pady=4)

        # Instructor
        ttk.Label(frame, text="Assigned Instructor:").grid(row=8, column=0, sticky=tk.W, pady=4)
        inst_options = ["None / Any Qualified"] + [f"{name} ({iid})" for iid, name in self.available_instructors]
        init_inst = "None / Any Qualified"
        if self.course and self.course.instructor_id:
            for iid, name in self.available_instructors:
                if iid == self.course.instructor_id:
                    init_inst = f"{name} ({iid})"
                    break
        self.inst_var = tk.StringVar(value=init_inst)
        ttk.Combobox(frame, textvariable=self.inst_var, values=inst_options, width=26).grid(
            row=8, column=1, sticky=tk.W, pady=4
        )

        # Break Overrides
        ttk.Label(frame, text="Break Before (min):").grid(row=9, column=0, sticky=tk.W, pady=4)
        bb_val = str(self.course.break_before) if (self.course and self.course.break_before is not None) else ""
        self.break_before_var = tk.StringVar(value=bb_val)
        ttk.Combobox(frame, textvariable=self.break_before_var, values=["", "0", "10", "15", "20", "30", "45", "60"], width=26).grid(
            row=9, column=1, sticky=tk.W, pady=4
        )

        ttk.Label(frame, text="Break After (min):").grid(row=10, column=0, sticky=tk.W, pady=4)
        ba_val = str(self.course.break_after) if (self.course and self.course.break_after is not None) else ""
        self.break_after_var = tk.StringVar(value=ba_val)
        ttk.Combobox(frame, textvariable=self.break_after_var, values=["", "0", "10", "15", "20", "30", "45", "60"], width=26).grid(
            row=10, column=1, sticky=tk.W, pady=4
        )

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=11, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

    def _on_confirm(self) -> None:
        cid = self.id_var.get().strip()
        sname = self.name_var.get().strip()
        dur = int(self.dur_var.get().strip()) if self.dur_var.get().strip().isdigit() else 90
        del_fmt = self.fmt_var.get().strip()
        rtype = self.room_type_var.get().strip()
        y_id = self.year_var.get().strip()
        is_wy = self.is_whole_year_var.get()

        g_str = self.groups_var.get().strip()
        target_g = [g.strip() for g in g_str.split(",") if g.strip()] if not is_wy else []

        # Parse instructor
        chosen_inst = self.inst_var.get().strip()
        inst_id = None
        if "(" in chosen_inst and chosen_inst.endswith(")"):
            inst_id = chosen_inst.split("(")[-1].rstrip(")")

        if not cid or not sname:
            messagebox.showerror("Error", "Please provide a valid Course ID and Subject Name.", parent=self)
            return

        bb_str = self.break_before_var.get().strip()
        ba_str = self.break_after_var.get().strip()
        break_before = int(bb_str) if bb_str.isdigit() else None
        break_after = int(ba_str) if ba_str.isdigit() else None

        self.result = CourseRequirement(
            course_id=cid,
            subject_name=sname,
            duration_minutes=dur,
            delivery_format=del_fmt,
            required_room_type=rtype,
            target_year_id=y_id,
            target_group_ids=target_g,
            is_whole_year=is_wy,
            instructor_id=inst_id,
            break_before=break_before,
            break_after=break_after,
        )
        self.destroy()


class InstructorDialog(tk.Toplevel):
    """Dialog to create/edit an instructor."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, instructor: Optional[Instructor] = None):
        super().__init__(parent)
        self.title("Edit Instructor" if instructor else "Add New Instructor")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.instructor = instructor
        self.result: Optional[Instructor] = None

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Instructor ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.instructor.instructor_id if self.instructor else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Full Name & Title:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.instructor.name if self.instructor else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Max Hours / Day:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.max_d_var = tk.StringVar(value=str(self.instructor.max_hours_per_day if self.instructor else 6.0))
        ttk.Entry(frame, textvariable=self.max_d_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Max Hours / Week:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.max_w_var = tk.StringVar(value=str(self.instructor.max_hours_per_week if self.instructor else 20.0))
        ttk.Entry(frame, textvariable=self.max_w_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Qualified Course IDs (comma separated):").grid(row=4, column=0, sticky=tk.W, pady=4)
        qc = ", ".join(self.instructor.qualified_course_ids) if self.instructor else ""
        self.qual_var = tk.StringVar(value=qc)
        ttk.Entry(frame, textvariable=self.qual_var, width=28).grid(row=4, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=5, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

    def _on_confirm(self) -> None:
        iid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        try:
            max_d = float(self.max_d_var.get().strip())
            max_w = float(self.max_w_var.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Daily and weekly hours must be valid numbers.", parent=self)
            return

        qual_ids = [c.strip() for c in self.qual_var.get().split(",") if c.strip()]

        if not iid or not name:
            messagebox.showerror("Error", "Please provide a valid Instructor ID and Name.", parent=self)
            return

        self.result = Instructor(
            instructor_id=iid,
            name=name,
            max_hours_per_day=max_d,
            max_hours_per_week=max_w,
            qualified_course_ids=qual_ids,
        )
        self.destroy()




class AcademicYearDialog(tk.Toplevel):
    """Dialog to add an academic year."""

    def __init__(self, parent: tk.Widget, study_cycles: List[str]):
        super().__init__(parent)
        self.title("Add Academic Year")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.study_cycles = study_cycles
        self.result: Optional[AcademicYear] = None

        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Year ID (e.g. 'rok_1'):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name (e.g. 'I ROK'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Study Cycle:").grid(row=2, column=0, sticky=tk.W, pady=4)
        default_cycle = study_cycles[0] if study_cycles else "stacjonarne inżynierskie I-go stopnia"
        self.cycle_var = tk.StringVar(value=default_cycle)
        ttk.Combobox(frame, textvariable=self.cycle_var, values=study_cycles, width=26).grid(row=2, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=3, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self) -> None:
        yid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cycle = self.cycle_var.get().strip()
        if not yid or not name:
            messagebox.showerror("Error", "Please provide a valid Year ID and Display Name.", parent=self)
            return
        self.result = AcademicYear(year_id=yid, name=name, study_cycle=cycle, specializations=[])
        self.destroy()


class SpecializationDialog(tk.Toplevel):
    """Dialog to add a specialization under an academic year."""

    def __init__(self, parent: tk.Widget, years: List[AcademicYear]):
        super().__init__(parent)
        self.title("Add Specialization")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.years = years
        self.result: Optional[Tuple[str, Specialization]] = None

        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Target Year:").grid(row=0, column=0, sticky=tk.W, pady=4)
        year_options = [f"{y.name} ({y.year_id})" for y in years]
        self.year_var = tk.StringVar(value=year_options[0] if year_options else "")
        ttk.Combobox(frame, textvariable=self.year_var, values=year_options, state="readonly", width=26).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Spec ID (e.g. 'spec_io'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Total Headcount:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value="32")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=4, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self) -> None:
        sid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cnt = self.count_var.get().strip()
        if not sid or not name or not cnt.isdigit() or int(cnt) <= 0:
            messagebox.showerror("Error", "Please provide a valid Spec ID, Name, and positive Headcount.", parent=self)
            return
        selected_val = self.year_var.get()
        selected_idx = [f"{y.name} ({y.year_id})" for y in self.years].index(selected_val)
        target_year_id = self.years[selected_idx].year_id
        self.result = (target_year_id, Specialization(spec_id=sid, name=name, student_count=int(cnt), groups=[]))
        self.destroy()


class BaseGroupDialog(tk.Toplevel):
    """Dialog to add a base student group under a specialization."""

    def __init__(self, parent: tk.Widget, specs: List[Tuple[str, str, Specialization]]):
        super().__init__(parent)
        self.title("Add Student Base Group")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.specs = specs
        self.result: Optional[Tuple[str, str, BaseGroup]] = None

        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Target Specialization:").grid(row=0, column=0, sticky=tk.W, pady=4)
        spec_options = [f"{s.name} ({s.spec_id})" for _, _, s in specs]
        self.spec_var = tk.StringVar(value=spec_options[0] if spec_options else "")
        ttk.Combobox(frame, textvariable=self.spec_var, values=spec_options, state="readonly", width=26).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Group ID (e.g. 'G1'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Group Headcount:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value="16")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=4, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self) -> None:
        gid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cnt = self.count_var.get().strip()
        if not gid or not name or not cnt.isdigit() or int(cnt) <= 0:
            messagebox.showerror("Error", "Please provide a valid Group ID, Name, and positive Headcount.", parent=self)
            return
        selected_val = self.spec_var.get()
        selected_idx = [f"{s.name} ({s.spec_id})" for _, _, s in self.specs].index(selected_val)
        yid, sid, _ = self.specs[selected_idx]
        self.result = (yid, sid, BaseGroup(group_id=gid, name=name, student_count=int(cnt)))
        self.destroy()


class SubgroupDialog(tk.Toplevel):
    """Dialog to create an elective/shared student subgroup."""

    def __init__(self, parent: tk.Widget, available_groups: List[str]):
        super().__init__(parent)
        self.title("Add Student Subgroup")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: Optional[StudentSubgroup] = None

        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Subgroup ID (e.g. 'SUB_AI'):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Headcount:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value="15")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Parent Groups (CSV):").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.parents_var = tk.StringVar(value=", ".join(available_groups[:2]) if available_groups else "")
        ttk.Entry(frame, textvariable=self.parents_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=4, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self) -> None:
        sid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cnt = self.count_var.get().strip()
        parents = [p.strip() for p in self.parents_var.get().split(",") if p.strip()]
        if not sid or not name or not cnt.isdigit() or int(cnt) <= 0:
            messagebox.showerror("Error", "Please provide a valid Subgroup ID, Name, and positive Headcount.", parent=self)
            return
        self.result = StudentSubgroup(subgroup_id=sid, name=name, student_count=int(cnt), parent_group_ids=parents)
        self.destroy()


class ConflictRuleDialog(tk.Toplevel):
    """Dialog to create an explicit collision prevention rule."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.title("Add Conflict Rule")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: Optional[ConflictRule] = None

        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Rule ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Entity A (Course / Group ID):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.a_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.a_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Entity B (Course / Group ID):").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.b_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.b_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Description:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.desc_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.desc_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        btn_box = ttk.Frame(frame, padding="10 10 0 0")
        btn_box.grid(row=4, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self) -> None:
        rid = self.id_var.get().strip()
        ea = self.a_var.get().strip()
        eb = self.b_var.get().strip()
        if not rid or not ea or not eb:
            messagebox.showerror("Error", "Please provide Rule ID, Entity A, and Entity B.", parent=self)
            return
        self.result = ConflictRule(rule_id=rid, entity_a=ea, entity_b=eb, description=self.desc_var.get().strip() or None)
        self.destroy()

# =====================================================================
# Schedule Verification Dialog & Preview Modal
# =====================================================================

class ScheduleVerificationDialog(tk.Toplevel):
    """Dedicated interactive dialog displaying solver status, zero-collision audit report, and schedule previews."""

    def __init__(
        self,
        parent: tk.Widget,
        result: ScheduleResult,
        config: ScheduleGenerationConfig,
        verification: Dict[str, Any],
        artifacts: Dict[str, Path],
        on_open_in_editor: Optional[Any] = None,
    ):
        super().__init__(parent)
        self.title("Academic Schedule Generation & Collision Verification Report")
        self.geometry("980x640")
        self.minsize(820, 520)
        self.transient(parent)
        self.grab_set()

        self.result = result
        self.config = config
        self.verification = verification
        self.artifacts = artifacts
        self.on_open_in_editor = on_open_in_editor

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build_ui(self) -> None:
        # 1. Top Header Banner with Solver Status Badge
        header = ttk.Frame(self, padding="16 14 16 10")
        header.pack(fill=tk.X)

        is_free = self.verification.get("is_collision_free", False)
        status_color = "#0d7a3e" if (self.result.is_success and is_free) else ("#b35900" if self.result.is_success else "#b30000")

        badge_frame = tk.Frame(header, bg=status_color, padx=12, pady=5)
        badge_frame.pack(side=tk.LEFT, padx=(0, 16))
        status_lbl = tk.Label(
            badge_frame,
            text=f"CP-SAT: {self.result.status}",
            font=("Helvetica", 12, "bold"),
            fg="white",
            bg=status_color,
        )
        status_lbl.pack()

        meta_frame = ttk.Frame(header)
        meta_frame.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = ttk.Label(
            meta_frame,
            text="Optimization Run & Zero-Collision Validation Report",
            font=("Helvetica", 12, "bold"),
        )
        title_lbl.pack(anchor=tk.W)

        obj_str = f"{self.result.objective_value:.1f}" if self.result.objective_value is not None else "N/A"
        sub_lbl = ttk.Label(
            meta_frame,
            text=f"Solve Time: {self.result.solver_time_seconds:.3f}s   |   Total Sessions: {len(self.result.scheduled_sessions)}   |   Objective Penalty: {obj_str}",
            font=("Helvetica", 9),
            foreground="#444",
        )
        sub_lbl.pack(anchor=tk.W)

        # 2. Main Tabbed Notebook
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        tab_audit = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_audit, text="  ✓ Zero-Collision Audit  ")
        self._build_audit_tab(tab_audit)

        tab_students = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_students, text="  📅 Student Schedules  ")
        self._build_students_tab(tab_students)

        tab_staff = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_staff, text="  👨‍🏫 Staff Schedules  ")
        self._build_staff_tab(tab_staff)

        # 3. Bottom Action Bar
        btn_bar = ttk.Frame(self, padding="16 10 16 14")
        btn_bar.pack(fill=tk.X)

        if self.on_open_in_editor and self.result.student_timetables:
            first_tt = next(iter(self.result.student_timetables.values()))
            first_pdf = next((p for k, p in self.artifacts.items() if k.startswith("student_pdf")), None)
            ttk.Button(
                btn_bar,
                text="📅 Open Student Timetable in Editor",
                command=lambda: self._open_in_editor(first_tt, first_pdf),
            ).pack(side=tk.LEFT, padx=4)

        run_dir = next(iter(self.artifacts.values())).parent if self.artifacts else None
        if run_dir:
            ttk.Button(
                btn_bar,
                text=f"📂 Output Folder ({run_dir.name})",
                command=lambda: messagebox.showinfo("Output Artifacts Location", f"Generated artifacts saved in directory: {run_dir.resolve()}"),
            ).pack(side=tk.LEFT, padx=4)

        ttk.Button(btn_bar, text="Close (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=4)

    def _build_audit_tab(self, parent: ttk.Frame) -> None:
        is_free = self.verification.get("is_collision_free", False)

        # Validation status card
        card_bg = "#e8f5e9" if is_free else "#ffebee"
        card_fg = "#1b5e20" if is_free else "#b71c1c"
        status_banner = tk.Frame(parent, bg=card_bg, padx=14, pady=10, relief=tk.RIDGE, bd=1)
        status_banner.pack(fill=tk.X, pady=(0, 10))

        v_title = "✅ ZERO-COLLISION SCHEDULE VERIFIED" if is_free else "⚠️ CONSTRAINTS OR COLLISIONS DETECTED"
        tk.Label(
            status_banner,
            text=v_title,
            font=("Helvetica", 12, "bold"),
            fg=card_fg,
            bg=card_bg,
        ).pack(anchor=tk.W)

        v_desc = (
            "All physical rooms, instructor time slots, student cohort cohorts, and elective subgroups "
            "have been mathematically proven collision-free by Google OR-Tools CP-SAT."
            if is_free
            else "Some constraints or overlaps were recorded. Review the detailed log items below."
        )
        tk.Label(
            status_banner,
            text=v_desc,
            font=("Helvetica", 9),
            fg="#333",
            bg=card_bg,
            wraplength=880,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        # Verification breakdown listbox / tree
        cols = ("Rule / Constraint Check", "Status", "Details")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=7)
        tree.heading("Rule / Constraint Check", text="Rule / Constraint Check")
        tree.heading("Status", text="Status")
        tree.heading("Details", text="Audit Details")
        tree.column("Rule / Constraint Check", width=260)
        tree.column("Status", width=110, anchor=tk.CENTER)
        tree.column("Details", width=500)
        tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Populate checks
        rm_col = self.verification.get("room_collisions", [])
        inst_col = self.verification.get("instructor_collisions", [])
        std_col = self.verification.get("student_collisions", [])
        forbid_col = self.verification.get("forbidden_window_violations", [])
        rule_col = self.verification.get("conflict_rule_violations", [])
        cap_col = self.verification.get("capacity_violations", [])

        tree.insert("", tk.END, values=(
            "Room Non-Overlapping",
            "PASSED" if not rm_col else f"FAILED ({len(rm_col)})",
            "0 room double-bookings across all days" if not rm_col else f"{len(rm_col)} room overlaps detected",
        ))
        tree.insert("", tk.END, values=(
            "Instructor Non-Overlapping",
            "PASSED" if not inst_col else f"FAILED ({len(inst_col)})",
            "0 instructor double-bookings across all days" if not inst_col else f"{len(inst_col)} instructor clashes detected",
        ))
        tree.insert("", tk.END, values=(
            "Student Cohort & Subgroup Non-Overlapping",
            "PASSED" if not std_col else f"FAILED ({len(std_col)})",
            "0 cohort or subgroup overlaps across all days" if not std_col else f"{len(std_col)} student group clashes detected",
        ))
        tree.insert("", tk.END, values=(
            "Staff Forbidden Time Windows",
            "PASSED" if not forbid_col else f"FAILED ({len(forbid_col)})",
            "All instructor unavailable time slots respected" if not forbid_col else f"{len(forbid_col)} forbidden window violations",
        ))
        tree.insert("", tk.END, values=(
            "Explicit Pairwise Conflict Rules",
            "PASSED" if not rule_col else f"FAILED ({len(rule_col)})",
            "All pairwise conflict prevention rules honored" if not rule_col else f"{len(rule_col)} conflict rule breaches",
        ))
        tree.insert("", tk.END, values=(
            "Facility Capacity Compliance",
            "PASSED" if not cap_col else f"FAILED ({len(cap_col)})",
            "All sessions placed in facilities with sufficient seating capacity",
        ))

        # Artifacts overview box
        art_box = ttk.LabelFrame(parent, text="Generated Export Artifacts", padding="8 6 8 6")
        art_box.pack(fill=tk.X)
        for key, p in list(self.artifacts.items())[:4]:
            ttk.Label(art_box, text=f"• {key}: {p.name}", font=("Monospace", 8)).pack(anchor=tk.W)

    def _build_students_tab(self, parent: ttk.Frame) -> None:
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(top_bar, text="Filter Cohort / Subgroup:", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        # Collect distinct group IDs
        all_gids = set()
        for s in self.result.scheduled_sessions:
            all_gids.update(s.target_group_ids)
        grp_options = ["All Cohorts"] + sorted(list(all_gids))

        self.student_filter_var = tk.StringVar(value="All Cohorts")
        grp_combo = ttk.Combobox(
            top_bar,
            textvariable=self.student_filter_var,
            values=grp_options,
            state="readonly",
            width=22,
        )
        grp_combo.pack(side=tk.LEFT)
        grp_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_student_table())

        cols = ("Day", "Time", "Subject", "Format", "Room", "Instructor", "Attending Groups")
        self.tree_std_prev = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree_std_prev.heading(c, text=c)
        self.tree_std_prev.column("Day", width=80, anchor=tk.CENTER)
        self.tree_std_prev.column("Time", width=105, anchor=tk.CENTER)
        self.tree_std_prev.column("Subject", width=250)
        self.tree_std_prev.column("Format", width=85, anchor=tk.CENTER)
        self.tree_std_prev.column("Room", width=110)
        self.tree_std_prev.column("Instructor", width=170)
        self.tree_std_prev.column("Attending Groups", width=130)

        std_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree_std_prev.yview)
        self.tree_std_prev.configure(yscrollcommand=std_scroll.set)
        self.tree_std_prev.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        std_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_student_table()

    def _refresh_student_table(self) -> None:
        self.tree_std_prev.delete(*self.tree_std_prev.get_children())
        filter_val = self.student_filter_var.get()

        for s in self.result.scheduled_sessions:
            if filter_val != "All Cohorts" and filter_val not in s.target_group_ids:
                continue
            self.tree_std_prev.insert("", tk.END, values=(
                s.day.capitalize(),
                s.hours,
                s.subject,
                s.delivery_format,
                s.room_name,
                s.instructor_name,
                ", ".join(s.target_group_ids),
            ))

    def _build_staff_tab(self, parent: ttk.Frame) -> None:
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(top_bar, text="Filter Instructor:", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        all_insts = sorted(list({s.instructor_name for s in self.result.scheduled_sessions}))
        inst_options = ["All Instructors"] + all_insts

        self.staff_filter_var = tk.StringVar(value="All Instructors")
        inst_combo = ttk.Combobox(
            top_bar,
            textvariable=self.staff_filter_var,
            values=inst_options,
            state="readonly",
            width=32,
        )
        inst_combo.pack(side=tk.LEFT)
        inst_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_staff_table())

        cols = ("Day", "Time", "Subject", "Format", "Room", "Attending Groups")
        self.tree_staff_prev = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree_staff_prev.heading(c, text=c)
        self.tree_staff_prev.column("Day", width=85, anchor=tk.CENTER)
        self.tree_staff_prev.column("Time", width=110, anchor=tk.CENTER)
        self.tree_staff_prev.column("Subject", width=280)
        self.tree_staff_prev.column("Format", width=90, anchor=tk.CENTER)
        self.tree_staff_prev.column("Room", width=120)
        self.tree_staff_prev.column("Attending Groups", width=160)

        staff_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree_staff_prev.yview)
        self.tree_staff_prev.configure(yscrollcommand=staff_scroll.set)
        self.tree_staff_prev.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        staff_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_staff_table()

    def _refresh_staff_table(self) -> None:
        self.tree_staff_prev.delete(*self.tree_staff_prev.get_children())
        filter_val = self.staff_filter_var.get()

        for s in self.result.scheduled_sessions:
            if filter_val != "All Instructors" and s.instructor_name != filter_val:
                continue
            self.tree_staff_prev.insert("", tk.END, values=(
                s.day.capitalize(),
                s.hours,
                s.subject,
                s.delivery_format,
                s.room_name,
                ", ".join(s.target_group_ids),
            ))

    def _open_in_editor(self, timetable: Timetable, pdf_path: Optional[Path]) -> None:
        if self.on_open_in_editor:
            self.on_open_in_editor(timetable, pdf_path)
            self.destroy()


# =====================================================================
# Schedule Generation Wizard Frame (Multi-Step Flow)
# =====================================================================

class ScheduleWizardFrame(ttk.Frame):
    """Multi-step schedule generation wizard frame with visual progress steps."""

    TOTAL_STEPS = 6

    def __init__(
        self,
        parent: tk.Widget,
        on_solve_complete: Optional[Any] = None,
        base_output_dir: str | Path = "output",
    ):
        super().__init__(parent)
        self.on_solve_complete = on_solve_complete
        self.base_output_dir = Path(base_output_dir)

        # Internal wizard state config
        self.config = ScheduleGenerationConfig()
        self.current_step = 1

        self._build_ui()
        self._show_step(1)

    def _build_ui(self) -> None:
        # 1. Top Visual Progress Steps Header & Quick Action Buttons
        self.progress_frame = ttk.Frame(self, padding="10 8 10 4")
        self.progress_frame.pack(fill=tk.X)

        self.step_indicators: List[ttk.Label] = []
        step_labels = [
            "1. Studies",
            "2. Facilities",
            "3. Curriculum",
            "4. Staff",
            "5. Conflicts",
            "6. Settings & Solve",
        ]
        left_steps = ttk.Frame(self.progress_frame)
        left_steps.pack(side=tk.LEFT)
        for idx, lbl in enumerate(step_labels, start=1):
            w = ttk.Label(
                left_steps,
                text=f" [ {lbl} ] ",
                font=("Helvetica", 9),
                padding="4 2 4 2",
            )
            w.pack(side=tk.LEFT, padx=2)
            self.step_indicators.append(w)

        # Quick Test / Demo Data Action Buttons
        header_actions = ttk.Frame(self.progress_frame)
        header_actions.pack(side=tk.RIGHT)

        ttk.Button(
            header_actions,
            text="🧪 Load Test Data",
            command=self.load_demo_test_data,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            header_actions,
            text="⚡ Quick Test & Solve",
            command=self.quick_test_and_solve,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            header_actions,
            text="🔄 Clear / Reset",
            command=lambda: self.reset_wizard(confirm=True),
        ).pack(side=tk.LEFT, padx=3)

        # Notification Banner
        self.banner_frame = ttk.Frame(self, padding="10 2 10 4")
        self.banner_label = ttk.Label(
            self.banner_frame,
            text="",
            font=("Helvetica", 9, "italic"),
            foreground="#0b6623",
        )
        self.banner_label.pack(side=tk.LEFT)

        # 2. Main Content Container
        self.content_container = ttk.Frame(self, padding="10 5 10 5")
        self.content_container.pack(fill=tk.BOTH, expand=True)

        # Individual Step Frames
        self.step_frames: Dict[int, ttk.Frame] = {}
        for s in range(1, self.TOTAL_STEPS + 1):
            sf = ttk.Frame(self.content_container)
            self.step_frames[s] = sf

        self._build_step1_ui(self.step_frames[1])
        self._build_step2_ui(self.step_frames[2])
        self._build_step3_ui(self.step_frames[3])
        self._build_step4_ui(self.step_frames[4])
        self._build_step5_ui(self.step_frames[5])
        self._build_step6_ui(self.step_frames[6])

        # 3. Bottom Wizard Navigation Bar
        nav_frame = ttk.Frame(self, padding="10 8 10 8")
        nav_frame.pack(fill=tk.X)

        self.back_btn = ttk.Button(nav_frame, text="< Back (Esc / Backspace)", command=self.previous_step)
        self.back_btn.pack(side=tk.LEFT, padx=4)

        self.next_btn = ttk.Button(nav_frame, text="Next > (Enter)", command=self.next_step)
        self.next_btn.pack(side=tk.LEFT, padx=4)

        self.solve_btn = ttk.Button(
            nav_frame,
            text="⚡ Generate Schedule (Ctrl+Enter)",
            command=self.solve_schedule,
        )
        self.solve_btn.pack(side=tk.RIGHT, padx=4)

        ttk.Button(nav_frame, text="💾 Export JSON", command=self._export_config_json).pack(side=tk.RIGHT, padx=4)
        ttk.Button(nav_frame, text="📂 Import JSON", command=self._import_config_json).pack(side=tk.RIGHT, padx=4)
        ttk.Button(nav_frame, text="🔄 Load UWM Preset", command=self._load_preset).pack(side=tk.RIGHT, padx=4)
        ttk.Button(nav_frame, text="🗑️ Reset", command=lambda: self.reset_wizard(confirm=True)).pack(side=tk.RIGHT, padx=4)

    def _update_progress_header(self) -> None:
        for idx, lbl in enumerate(self.step_indicators, start=1):
            if idx == self.current_step:
                lbl.configure(font=("Helvetica", 9, "bold"), foreground="blue")
            elif idx < self.current_step:
                lbl.configure(font=("Helvetica", 9), foreground="darkgreen")
            else:
                lbl.configure(font=("Helvetica", 9), foreground="gray")

    def _show_step(self, step: int) -> None:
        self.current_step = step
        for s, frame in self.step_frames.items():
            frame.pack_forget()
        self.step_frames[step].pack(fill=tk.BOTH, expand=True)

        self._update_progress_header()
        self.back_btn.configure(state=tk.NORMAL if step > 1 else tk.DISABLED)
        if step == self.TOTAL_STEPS:
            self.next_btn.configure(text="Solve Schedule ➔")
        else:
            self.next_btn.configure(text="Next > (Enter)")

    def next_step(self) -> None:
        if self.current_step < self.TOTAL_STEPS:
            self._show_step(self.current_step + 1)
        else:
            self.solve_schedule()

    def previous_step(self) -> None:
        if self.current_step > 1:
            self._show_step(self.current_step - 1)

    # -------------------------------------------------------------
    # Step 1: Academic Structure
    # -------------------------------------------------------------
    def _build_step1_ui(self, parent: ttk.Frame) -> None:
        header_bar = ttk.Frame(parent)
        header_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header_bar,
            text="Step 1: Academic Structure (Degrees, Years, Specializations & Groups)",
            font=("Helvetica", 11, "bold"),
        ).pack(side=tk.LEFT)

        btn_box = ttk.Frame(header_bar)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="+ Add Year", command=self._on_add_year).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_box, text="+ Add Specialization", command=self._on_add_specialization).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_box, text="+ Add Group", command=self._on_add_base_group).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_box, text="Delete Selected", command=self._on_delete_academic_item).pack(side=tk.LEFT, padx=2)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("Level", "ID", "Name", "Headcount")
        self.tree_academic = ttk.Treeview(tree_frame, columns=cols, show="tree headings", selectmode="browse")
        self.tree_academic.heading("#0", text="Hierarchy")
        self.tree_academic.heading("Level", text="Level")
        self.tree_academic.heading("ID", text="Identifier")
        self.tree_academic.heading("Name", text="Title")
        self.tree_academic.heading("Headcount", text="Capacity / Students")

        self.tree_academic.column("#0", width=180)
        self.tree_academic.column("Level", width=100)
        self.tree_academic.column("ID", width=100)
        self.tree_academic.column("Name", width=220)
        self.tree_academic.column("Headcount", width=100, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_academic.yview)
        self.tree_academic.configure(yscrollcommand=vsb.set)
        self.tree_academic.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_step1_tree()

    def _refresh_step1_tree(self) -> None:
        self.tree_academic.delete(*self.tree_academic.get_children())
        for y in self.config.academic_structure.years:
            y_node = self.tree_academic.insert(
                "", tk.END, text=y.name, values=("Year", y.year_id, y.study_cycle, "-"), open=True
            )
            for s in y.specializations:
                s_node = self.tree_academic.insert(
                    y_node, tk.END, text=s.name, values=("Specialization", s.spec_id, s.name, s.student_count), open=True
                )
                for g in s.groups:
                    self.tree_academic.insert(
                        s_node, tk.END, text=g.name, values=("Base Group", g.group_id, g.name, g.student_count)
                    )

    def _on_add_year(self) -> None:
        dlg = AcademicYearDialog(self, study_cycles=self.config.academic_structure.study_cycles)
        self.wait_window(dlg)
        if dlg.result:
            self.config.academic_structure.years.append(dlg.result)
            self._refresh_step1_tree()

    def _on_add_specialization(self) -> None:
        if not self.config.academic_structure.years:
            messagebox.showwarning("Warning", "Please define at least one Academic Year first.", parent=self)
            return
        dlg = SpecializationDialog(self, years=self.config.academic_structure.years)
        self.wait_window(dlg)
        if dlg.result:
            yid, spec = dlg.result
            for y in self.config.academic_structure.years:
                if y.year_id == yid:
                    y.specializations.append(spec)
                    break
            self._refresh_step1_tree()

    def _on_add_base_group(self) -> None:
        specs: List[Tuple[str, str, Specialization]] = []
        for y in self.config.academic_structure.years:
            for s in y.specializations:
                specs.append((y.year_id, s.spec_id, s))
        if not specs:
            messagebox.showwarning("Warning", "Please define at least one Specialization first.", parent=self)
            return
        dlg = BaseGroupDialog(self, specs=specs)
        self.wait_window(dlg)
        if dlg.result:
            yid, sid, group = dlg.result
            for y in self.config.academic_structure.years:
                if y.year_id == yid:
                    for s in y.specializations:
                        if s.spec_id == sid:
                            s.groups.append(group)
                            break
            self._refresh_step1_tree()

    def _on_delete_academic_item(self) -> None:
        sel = self.tree_academic.selection()
        if not sel:
            return
        item = sel[0]
        vals = self.tree_academic.item(item, "values")
        if not vals:
            return
        level, item_id = vals[0], vals[1]
        if level == "Year":
            self.config.academic_structure.years = [
                y for y in self.config.academic_structure.years if y.year_id != item_id
            ]
        elif level == "Specialization":
            for y in self.config.academic_structure.years:
                y.specializations = [s for s in y.specializations if s.spec_id != item_id]
        elif level == "Base Group":
            for y in self.config.academic_structure.years:
                for s in y.specializations:
                    s.groups = [g for g in s.groups if g.group_id != item_id]
        self._refresh_step1_tree()


    # -------------------------------------------------------------
    # Step 2: Facilities (Rooms)
    # -------------------------------------------------------------
    def _build_step2_ui(self, parent: ttk.Frame) -> None:
        header_bar = ttk.Frame(parent)
        header_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header_bar,
            text="Step 2: Facilities & Rooms (Capacity & Allowed Activity Types)",
            font=("Helvetica", 11, "bold"),
        ).pack(side=tk.LEFT)

        btn_box = ttk.Frame(header_bar)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="+ Add Room", command=self._on_add_room).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Edit Room", command=self._on_edit_room).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Delete Room", command=self._on_delete_room).pack(side=tk.LEFT, padx=3)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("ID", "Name", "Capacity", "Allowed Event Types")
        self.tree_rooms = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree_rooms.heading(c, text=c)

        self.tree_rooms.column("ID", width=100, anchor=tk.CENTER)
        self.tree_rooms.column("Name", width=140, anchor=tk.W)
        self.tree_rooms.column("Capacity", width=100, anchor=tk.CENTER)
        self.tree_rooms.column("Allowed Event Types", width=360, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_rooms.yview)
        self.tree_rooms.configure(yscrollcommand=vsb.set)
        self.tree_rooms.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_step2_tree()

    def _refresh_step2_tree(self) -> None:
        self.tree_rooms.delete(*self.tree_rooms.get_children())
        for idx, r in enumerate(self.config.rooms):
            types_str = ", ".join(r.allowed_event_types)
            self.tree_rooms.insert("", tk.END, iid=str(idx), values=(r.room_id, r.name, r.capacity, types_str))

    def _on_add_room(self) -> None:
        dlg = RoomDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.config.rooms.append(dlg.result)
            self._refresh_step2_tree()

    def _on_edit_room(self) -> None:
        sel = self.tree_rooms.selection()
        if not sel:
            return
        idx = int(sel[0])
        dlg = RoomDialog(self, room=self.config.rooms[idx])
        self.wait_window(dlg)
        if dlg.result:
            self.config.rooms[idx] = dlg.result
            self._refresh_step2_tree()

    def _on_delete_room(self) -> None:
        sel = self.tree_rooms.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.rooms[idx]
        self._refresh_step2_tree()

    # -------------------------------------------------------------
    # Step 3: Curriculum
    # -------------------------------------------------------------
    def _build_step3_ui(self, parent: ttk.Frame) -> None:
        header_bar = ttk.Frame(parent)
        header_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header_bar,
            text="Step 3: Curriculum (Subjects, Contact Hours, Format & Room Types)",
            font=("Helvetica", 11, "bold"),
        ).pack(side=tk.LEFT)

        btn_box = ttk.Frame(header_bar)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="+ Add Course", command=self._on_add_course).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Edit Course", command=self._on_edit_course).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Delete Course", command=self._on_delete_course).pack(side=tk.LEFT, padx=3)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("Course ID", "Subject", "Duration", "Format", "Required Room", "Target Cohort", "Instructor", "Breaks (B/A)")
        self.tree_courses = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree_courses.heading(c, text=c)

        self.tree_courses.column("Course ID", width=110)
        self.tree_courses.column("Subject", width=200)
        self.tree_courses.column("Duration", width=70, anchor=tk.CENTER)
        self.tree_courses.column("Format", width=70, anchor=tk.CENTER)
        self.tree_courses.column("Required Room", width=110, anchor=tk.CENTER)
        self.tree_courses.column("Target Cohort", width=100, anchor=tk.CENTER)
        self.tree_courses.column("Instructor", width=120)
        self.tree_courses.column("Breaks (B/A)", width=90, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_courses.yview)
        self.tree_courses.configure(yscrollcommand=vsb.set)
        self.tree_courses.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_step3_tree()

    def _refresh_step3_tree(self) -> None:
        self.tree_courses.delete(*self.tree_courses.get_children())
        for idx, c in enumerate(self.config.courses):
            cohort = "Whole Year" if c.is_whole_year else (", ".join(c.target_group_ids) or "All")
            inst_name = c.instructor_id or "Any Qualified"
            for i in self.config.instructors:
                if i.instructor_id == c.instructor_id:
                    inst_name = i.name
                    break

            bb_str = f"{c.break_before}m" if c.break_before is not None else "auto"
            ba_str = f"{c.break_after}m" if c.break_after is not None else "auto"
            breaks_str = f"{bb_str} / {ba_str}"
            self.tree_courses.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    c.course_id,
                    c.subject_name,
                    f"{c.duration_minutes}m",
                    c.delivery_format,
                    c.required_room_type,
                    cohort,
                    inst_name,
                    breaks_str,
                ),
            )

    def _on_add_course(self) -> None:
        years = [y.year_id for y in self.config.academic_structure.years] or ["rok_4"]
        groups = [g.group_id for g in self.config.academic_structure.all_groups()] or ["G1", "G2"]
        insts = [(i.instructor_id, i.name) for i in self.config.instructors]

        dlg = CourseDialog(self, available_years=years, available_groups=groups, available_instructors=insts)
        self.wait_window(dlg)
        if dlg.result:
            self.config.courses.append(dlg.result)
            self._refresh_step3_tree()

    def _on_edit_course(self) -> None:
        sel = self.tree_courses.selection()
        if not sel:
            return
        idx = int(sel[0])
        years = [y.year_id for y in self.config.academic_structure.years] or ["rok_4"]
        groups = [g.group_id for g in self.config.academic_structure.all_groups()] or ["G1", "G2"]
        insts = [(i.instructor_id, i.name) for i in self.config.instructors]

        dlg = CourseDialog(
            self,
            course=self.config.courses[idx],
            available_years=years,
            available_groups=groups,
            available_instructors=insts,
        )
        self.wait_window(dlg)
        if dlg.result:
            self.config.courses[idx] = dlg.result
            self._refresh_step3_tree()

    def _on_delete_course(self) -> None:
        sel = self.tree_courses.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.courses[idx]
        self._refresh_step3_tree()

    # -------------------------------------------------------------
    # Step 4: Academic Staff
    # -------------------------------------------------------------
    def _build_step4_ui(self, parent: ttk.Frame) -> None:
        header_bar = ttk.Frame(parent)
        header_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header_bar,
            text="Step 4: Academic Staff (Instructors, Load Limits & Time Windows)",
            font=("Helvetica", 11, "bold"),
        ).pack(side=tk.LEFT)

        btn_box = ttk.Frame(header_bar)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="+ Add Staff", command=self._on_add_staff).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Edit Staff", command=self._on_edit_staff).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="Delete Staff", command=self._on_delete_staff).pack(side=tk.LEFT, padx=3)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("ID", "Name", "Max Day (h)", "Max Week (h)", "Qualified Courses", "Forbidden Windows")
        self.tree_staff = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree_staff.heading(c, text=c)

        self.tree_staff.column("ID", width=110)
        self.tree_staff.column("Name", width=220)
        self.tree_staff.column("Max Day (h)", width=90, anchor=tk.CENTER)
        self.tree_staff.column("Max Week (h)", width=90, anchor=tk.CENTER)
        self.tree_staff.column("Qualified Courses", width=200)
        self.tree_staff.column("Forbidden Windows", width=160)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_staff.yview)
        self.tree_staff.configure(yscrollcommand=vsb.set)
        self.tree_staff.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_step4_tree()

    def _refresh_step4_tree(self) -> None:
        self.tree_staff.delete(*self.tree_staff.get_children())
        for idx, i in enumerate(self.config.instructors):
            qc_str = ", ".join(i.qualified_course_ids) or "All / Unrestricted"
            forb_str = ", ".join(f"{w.day} {w.start_time}-{w.end_time}" for w in i.forbidden_windows) or "None"
            self.tree_staff.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(i.instructor_id, i.name, i.max_hours_per_day, i.max_hours_per_week, qc_str, forb_str),
            )

    def _on_add_staff(self) -> None:
        dlg = InstructorDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.config.instructors.append(dlg.result)
            self._refresh_step4_tree()

    def _on_edit_staff(self) -> None:
        sel = self.tree_staff.selection()
        if not sel:
            return
        idx = int(sel[0])
        dlg = InstructorDialog(self, instructor=self.config.instructors[idx])
        self.wait_window(dlg)
        if dlg.result:
            self.config.instructors[idx] = dlg.result
            self._refresh_step4_tree()

    def _on_delete_staff(self) -> None:
        sel = self.tree_staff.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.instructors[idx]
        self._refresh_step4_tree()

    # -------------------------------------------------------------
    # Step 5: Subgroups & Conflict Management
    # -------------------------------------------------------------
    def _build_step5_ui(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Step 5: Subgroups & Conflict Management (Collision & Shared Student Constraints)",
            font=("Helvetica", 11, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: Subgroups
        left_frame = ttk.LabelFrame(paned, text="Student Subgroups", padding="5 5 5 5")
        paned.add(left_frame, weight=1)

        sg_btn_box = ttk.Frame(left_frame)
        sg_btn_box.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(sg_btn_box, text="+ Add Subgroup", command=self._on_add_subgroup).pack(side=tk.LEFT, padx=2)
        ttk.Button(sg_btn_box, text="Delete Subgroup", command=self._on_delete_subgroup).pack(side=tk.LEFT, padx=2)

        cols_sg = ("ID", "Name", "Headcount", "Parents")
        self.tree_subgroups = ttk.Treeview(left_frame, columns=cols_sg, show="headings", selectmode="browse")
        for c in cols_sg:
            self.tree_subgroups.heading(c, text=c)
        self.tree_subgroups.column("ID", width=80)
        self.tree_subgroups.column("Name", width=120)
        self.tree_subgroups.column("Headcount", width=60, anchor=tk.CENTER)
        self.tree_subgroups.column("Parents", width=100)
        self.tree_subgroups.pack(fill=tk.BOTH, expand=True)

        # Right: Conflict Rules
        right_frame = ttk.LabelFrame(paned, text="Explicit Collision Prevention Rules", padding="5 5 5 5")
        paned.add(right_frame, weight=1)

        cr_btn_box = ttk.Frame(right_frame)
        cr_btn_box.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(cr_btn_box, text="+ Add Conflict Rule", command=self._on_add_conflict_rule).pack(side=tk.LEFT, padx=2)
        ttk.Button(cr_btn_box, text="Delete Rule", command=self._on_delete_conflict_rule).pack(side=tk.LEFT, padx=2)

        cols_cr = ("Rule ID", "Entity A", "Entity B", "Description")
        self.tree_conflicts = ttk.Treeview(right_frame, columns=cols_cr, show="headings", selectmode="browse")
        for c in cols_cr:
            self.tree_conflicts.heading(c, text=c)
        self.tree_conflicts.column("Rule ID", width=100)
        self.tree_conflicts.column("Entity A", width=100)
        self.tree_conflicts.column("Entity B", width=100)
        self.tree_conflicts.column("Description", width=180)
        self.tree_conflicts.pack(fill=tk.BOTH, expand=True)

        self._refresh_step5()

    def _refresh_step5(self) -> None:
        self.tree_subgroups.delete(*self.tree_subgroups.get_children())
        for sg in self.config.subgroups:
            p_str = ", ".join(sg.parent_group_ids)
            self.tree_subgroups.insert("", tk.END, values=(sg.subgroup_id, sg.name, sg.student_count, p_str))

        self.tree_conflicts.delete(*self.tree_conflicts.get_children())
        for cr in self.config.conflict_rules:
            self.tree_conflicts.insert("", tk.END, values=(cr.rule_id, cr.entity_a, cr.entity_b, cr.description or ""))

    def _on_add_subgroup(self) -> None:
        all_groups = [g.group_id for g in self.config.academic_structure.all_groups()]
        dlg = SubgroupDialog(self, available_groups=all_groups)
        self.wait_window(dlg)
        if dlg.result:
            self.config.subgroups.append(dlg.result)
            self._refresh_step5()

    def _on_delete_subgroup(self) -> None:
        sel = self.tree_subgroups.selection()
        if not sel:
            return
        idx = self.tree_subgroups.index(sel[0])
        if 0 <= idx < len(self.config.subgroups):
            del self.config.subgroups[idx]
            self._refresh_step5()

    def _on_add_conflict_rule(self) -> None:
        dlg = ConflictRuleDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.config.conflict_rules.append(dlg.result)
            self._refresh_step5()

    def _on_delete_conflict_rule(self) -> None:
        sel = self.tree_conflicts.selection()
        if not sel:
            return
        idx = self.tree_conflicts.index(sel[0])
        if 0 <= idx < len(self.config.conflict_rules):
            del self.config.conflict_rules[idx]
            self._refresh_step5()


    # -------------------------------------------------------------
    # Step 6: Time Horizon & Solver Trigger
    # -------------------------------------------------------------
    def _build_step6_ui(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Step 6: Time Horizon & Global Optimization Settings",
            font=("Helvetica", 11, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        card = ttk.LabelFrame(parent, text="Scheduling Parameters", padding="15 15 15 15")
        card.pack(fill=tk.BOTH, expand=True)

        # Days
        ttk.Label(card, text="Working Days:").grid(row=0, column=0, sticky=tk.W, pady=6)
        days_box = ttk.Frame(card)
        days_box.grid(row=0, column=1, sticky=tk.W, pady=6)
        self.day_vars: Dict[str, tk.BooleanVar] = {}
        for d in VALID_DAYS:
            var = tk.BooleanVar(value=d in self.config.time_horizon.working_days)
            self.day_vars[d] = var
            ttk.Checkbutton(days_box, text=d.capitalize(), variable=var).pack(side=tk.LEFT, padx=5)

        # Time range
        ttk.Label(card, text="Daily Time Range:").grid(row=1, column=0, sticky=tk.W, pady=6)
        tr_box = ttk.Frame(card)
        tr_box.grid(row=1, column=1, sticky=tk.W, pady=6)
        self.day_start_var = tk.StringVar(value=self.config.time_horizon.day_start)
        self.day_end_var = tk.StringVar(value=self.config.time_horizon.day_end)
        ttk.Entry(tr_box, textvariable=self.day_start_var, width=8).pack(side=tk.LEFT)
        ttk.Label(tr_box, text=" to ").pack(side=tk.LEFT)
        ttk.Entry(tr_box, textvariable=self.day_end_var, width=8).pack(side=tk.LEFT)

        # Slot unit
        ttk.Label(card, text="Grid Slot Unit:").grid(row=2, column=0, sticky=tk.W, pady=6)
        self.slot_unit_var = tk.StringVar(value=str(self.config.time_horizon.slot_duration_minutes))
        ttk.Combobox(card, textvariable=self.slot_unit_var, values=["15", "30", "45"], width=15).grid(
            row=2, column=1, sticky=tk.W, pady=6
        )

        # Max student daily hours
        ttk.Label(card, text="Max Daily Hours / Student:").grid(row=3, column=0, sticky=tk.W, pady=6)
        self.max_std_var = tk.StringVar(value=str(self.config.time_horizon.max_daily_hours_per_student))
        ttk.Entry(card, textvariable=self.max_std_var, width=17).grid(row=3, column=1, sticky=tk.W, pady=6)

        # Timeout
        ttk.Label(card, text="CP-SAT Solver Timeout (s):").grid(row=4, column=0, sticky=tk.W, pady=6)
        self.timeout_var = tk.StringVar(value=str(self.config.time_horizon.solver_timeout_seconds))
        ttk.Entry(card, textvariable=self.timeout_var, width=17).grid(row=4, column=1, sticky=tk.W, pady=6)

        # Default break duration
        ttk.Label(card, text="Default Class Break (min):").grid(row=5, column=0, sticky=tk.W, pady=6)
        def_break = getattr(self.config.time_horizon, "default_break_minutes", 15)
        self.default_break_var = tk.StringVar(value=str(def_break))
        ttk.Combobox(card, textvariable=self.default_break_var, values=["0", "5", "10", "15", "20", "30", "45"], width=15).grid(
            row=5, column=1, sticky=tk.W, pady=6
        )

        # Soft objectives
        ttk.Label(card, text="Optimization Objectives:").grid(row=6, column=0, sticky=tk.NW, pady=6)
        obj_box = ttk.Frame(card)
        obj_box.grid(row=6, column=1, sticky=tk.W, pady=6)

        self.min_std_gaps_var = tk.BooleanVar(value=self.config.time_horizon.minimize_student_gaps)
        ttk.Checkbutton(obj_box, text="Minimize idle gaps between classes for students", variable=self.min_std_gaps_var).pack(
            anchor=tk.W
        )

        self.min_wrk_gaps_var = tk.BooleanVar(value=self.config.time_horizon.minimize_worker_gaps)
        ttk.Checkbutton(obj_box, text="Minimize teaching windows/gaps for academic staff", variable=self.min_wrk_gaps_var).pack(
            anchor=tk.W
        )

        self.prev_single_var = tk.BooleanVar(value=self.config.time_horizon.prevent_single_class_days)
        ttk.Checkbutton(obj_box, text="Prevent single-class isolated days for student groups", variable=self.prev_single_var).pack(
            anchor=tk.W
        )

    def _sync_step6_settings(self) -> None:
        self.config.time_horizon.working_days = [d for d, v in self.day_vars.items() if v.get()]
        self.config.time_horizon.day_start = self.day_start_var.get().strip()
        self.config.time_horizon.day_end = self.day_end_var.get().strip()
        if self.slot_unit_var.get().strip().isdigit():
            self.config.time_horizon.slot_duration_minutes = int(self.slot_unit_var.get().strip())
        try:
            self.config.time_horizon.max_daily_hours_per_student = float(self.max_std_var.get().strip())
            self.config.time_horizon.solver_timeout_seconds = int(self.timeout_var.get().strip())
        except ValueError:
            pass
        if hasattr(self, "default_break_var") and self.default_break_var.get().strip().isdigit():
            brk = int(self.default_break_var.get().strip())
            self.config.time_horizon.default_break_minutes = brk
            self.config.default_break_minutes = brk
        self.config.time_horizon.minimize_student_gaps = self.min_std_gaps_var.get()
        self.config.time_horizon.minimize_worker_gaps = self.min_wrk_gaps_var.get()
        self.config.time_horizon.prevent_single_class_days = self.prev_single_var.get()

    def load_demo_test_data(self) -> None:
        """Populate all wizard steps with comprehensive, realistic test/demo data."""
        self.config = ScheduleGenerationConfig.create_demo_config()
        self._refresh_step1_tree()
        self._refresh_step2_tree()
        self._refresh_step3_tree()
        self._refresh_step4_tree()
        self._refresh_step5()
        self._sync_step6_from_config()
        self._show_step(1)

        self.banner_frame.pack(fill=tk.X, before=self.content_container)
        self.banner_label.configure(
            text="✓ Realistic demo data loaded (2 specializations, 4 groups, 5 rooms, 4 instructors, 2 elective subgroups). All fields remain fully editable."
        )

    def reset_wizard(self, confirm: bool = False) -> None:
        """Reset wizard to an empty configuration with zero pre-populated entities."""
        if confirm:
            if not messagebox.askyesno(
                "Reset Schedule Wizard",
                "Are you sure you want to clear all data and start with an empty schedule?",
                parent=self,
            ):
                return

        self.config = ScheduleGenerationConfig()
        self._refresh_step1_tree()
        self._refresh_step2_tree()
        self._refresh_step3_tree()
        self._refresh_step4_tree()
        self._refresh_step5()
        self._sync_step6_from_config()
        self.banner_frame.pack_forget()
        self._show_step(1)


    def quick_test_and_solve(self) -> None:
        """Immediately populate demo data if empty and solve schedule with verification dialog."""
        if len(self.config.courses) <= 1:
            self.load_demo_test_data()
        self.solve_schedule()

    def _sync_step6_from_config(self) -> None:
        """Synchronize Step 6 controls to match current config."""
        if hasattr(self, "day_vars"):
            for d, var in self.day_vars.items():
                var.set(d in self.config.time_horizon.working_days)
            self.day_start_var.set(self.config.time_horizon.day_start)
            self.day_end_var.set(self.config.time_horizon.day_end)
            self.slot_unit_var.set(str(self.config.time_horizon.slot_duration_minutes))
            self.max_std_var.set(str(self.config.time_horizon.max_daily_hours_per_student))
            self.timeout_var.set(str(self.config.time_horizon.solver_timeout_seconds))
            self.min_std_gaps_var.set(self.config.time_horizon.minimize_student_gaps)
            self.min_wrk_gaps_var.set(self.config.time_horizon.minimize_worker_gaps)
            self.prev_single_var.set(self.config.time_horizon.prevent_single_class_days)
            if hasattr(self, "default_break_var"):
                def_break = getattr(self.config.time_horizon, "default_break_minutes", 15)
                self.default_break_var.set(str(def_break))

    def _load_preset(self) -> None:
        if messagebox.askyesno("Load Preset", "Overwrite current wizard data with standard UWM Year 4 Preset?", parent=self):
            self.load_demo_test_data()

    def _export_config_json(self) -> None:
        self._sync_step6_settings()
        dest = filedialog.asksaveasfilename(
            title="Export Wizard Configuration JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            parent=self,
        )
        if dest:
            Path(dest).write_text(self.config.to_json(indent=2), encoding="utf-8")
            messagebox.showinfo("Export Success", f"Configuration exported successfully to:\n{dest}", parent=self)

    def _import_config_json(self) -> None:
        src = filedialog.askopenfilename(
            title="Import Wizard Configuration JSON",
            filetypes=[("JSON files", "*.json")],
            parent=self,
        )
        if src:
            try:
                raw = Path(src).read_text(encoding="utf-8")
                self.config = ScheduleGenerationConfig.from_json(raw)
                self._refresh_step1_tree()
                self._refresh_step2_tree()
                self._refresh_step3_tree()
                self._refresh_step4_tree()
                self._refresh_step5()
                self._show_step(1)
                messagebox.showinfo("Import Success", f"Imported configuration from:\n{src}", parent=self)
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to load JSON configuration:\n{e}", parent=self)

    def solve_schedule(self) -> None:
        """Run CP-SAT solver and export artifacts."""
        self._sync_step6_settings()

        # Validate configuration integrity
        errors = self.config.validate_integrity()
        if errors:
            msg = "Configuration has integrity issues:\n\n" + "\n".join(f"• {e}" for e in errors[:5])
            messagebox.showerror("Integrity Warning", msg, parent=self)
            return

        scheduler = AcademicScheduler(self.config)
        result: ScheduleResult = scheduler.solve()

        if not result.is_success:
            diag_text = "\n".join(f"• {d}" for d in result.diagnostics)
            messagebox.showerror(
                "Solver Result: Infeasible",
                f"CP-SAT solver returned '{result.status}' ({result.solver_time_seconds:.2f}s):\n\n{diag_text}",
                parent=self,
            )
            return

        # Perform zero-collision verification audit
        verification = verify_schedule_collisions(result, self.config)

        # Export artifacts
        artifacts = export_schedule_artifacts(result, self.base_output_dir)

        # Show dedicated verification & preview dialog
        dlg = ScheduleVerificationDialog(
            parent=self,
            result=result,
            config=self.config,
            verification=verification,
            artifacts=artifacts,
            on_open_in_editor=self.on_solve_complete,
        )
        self.wait_window(dlg)


# =====================================================================
# Main Application GUI (Dual-Mode: Editor & Generator Wizard)
# =====================================================================

class TimetableGUI:
    """Primary Graphical User Interface featuring a dual-mode switch between Schedule Editor and Generator Wizard."""

    def __init__(
        self,
        timetable: Optional[Timetable] = None,
        storage: Optional[StorageManager] = None,
        generator: Optional[TimetablePDFGenerator] = None,
        base_output_dir: str | Path = "output",
        initial_mode: str = "edit",  # "edit" or "create"
    ):
        self.timetable = timetable
        self.storage = storage
        self.generator = generator or TimetablePDFGenerator()
        self.base_output_dir = Path(base_output_dir)
        self.is_modified = False
        self.current_mode = initial_mode

        self.root = tk.Tk()
        self.root.title("UWM Better Schedule — Academic Timetable Suite")
        self.root.geometry("1020x700")
        self.root.minsize(860, 560)

        self.file_path_var = tk.StringVar(
            value=str(self.storage.input_pdf_path) if self.storage else "No PDF file loaded"
        )
        self.run_dir_var = tk.StringVar(
            value=f"Run Dir: {self.storage.run_dir.name}" if self.storage else "Run Dir: [Not initialized]"
        )

        self.tree_views: Dict[str, ttk.Treeview] = {}
        self._build_ui()
        self._setup_keyboard_shortcuts()
        self._refresh_all_tables()
        self.set_mode(initial_mode)

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Top Global Switch Bar
        top_bar = ttk.Frame(self.root, padding="10 8 10 4")
        top_bar.pack(fill=tk.X)

        title_label = ttk.Label(
            top_bar,
            text="UWM Better Schedule",
            font=("Helvetica", 14, "bold"),
        )
        title_label.pack(side=tk.LEFT, padx=(0, 15))

        # Mode Selector Buttons
        mode_frame = ttk.Frame(top_bar)
        mode_frame.pack(side=tk.LEFT)

        self.btn_mode_editor = ttk.Button(
            mode_frame,
            text="📅 Schedule Editor",
            command=lambda: self.set_mode("edit"),
        )
        self.btn_mode_editor.pack(side=tk.LEFT, padx=2)

        self.btn_mode_wizard = ttk.Button(
            mode_frame,
            text="🪄 Schedule Generator Wizard",
            command=lambda: self.set_mode("create"),
        )
        self.btn_mode_wizard.pack(side=tk.LEFT, padx=2)

        info_label = ttk.Label(
            top_bar,
            textvariable=self.run_dir_var,
            font=("Helvetica", 9),
            foreground="gray",
        )
        info_label.pack(side=tk.RIGHT, pady=4)

        # Main Switchable Views Container
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # View 1: Schedule Editor Frame
        # -------------------------------------------------------------
        self.editor_frame = ttk.Frame(self.main_container)

        # File Ingestion / Selection Bar
        file_frame = ttk.Frame(self.editor_frame, padding="10 4 10 6")
        file_frame.pack(fill=tk.X)

        ttk.Label(file_frame, text="Target File:", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var, font=("Helvetica", 9))
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_btn = ttk.Button(
            file_frame,
            text="📁 Browse / Load File... (Ctrl+O)",
            command=self._on_browse_file,
        )
        browse_btn.pack(side=tk.RIGHT)

        # Notebook with Day Tabs
        self.notebook = ttk.Notebook(self.editor_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        for day in VALID_DAYS:
            day_frame = ttk.Frame(self.notebook, padding="5 5 5 5")
            self.notebook.add(day_frame, text=day.capitalize())

            tree_frame = ttk.Frame(day_frame)
            tree_frame.pack(fill=tk.BOTH, expand=True)

            cols = ("Hours", "Subject", "Instructor", "Room", "Type", "Group", "Notes")
            tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
            for c in cols:
                tree.heading(c, text=c)

            tree.column("Hours", width=110, anchor=tk.CENTER)
            tree.column("Subject", width=220, anchor=tk.W)
            tree.column("Instructor", width=140, anchor=tk.W)
            tree.column("Room", width=80, anchor=tk.CENTER)
            tree.column("Type", width=90, anchor=tk.CENTER)
            tree.column("Group", width=60, anchor=tk.CENTER)
            tree.column("Notes", width=120, anchor=tk.W)

            vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)

            tree.bind("<Double-1>", lambda e, d=day: self._on_edit_slot(d))
            tree.bind("<Return>", lambda e, d=day: self._on_edit_slot(d))

            self.tree_views[day] = tree

            btn_box = ttk.Frame(day_frame, padding="5 5 5 5")
            btn_box.pack(fill=tk.X)

            ttk.Button(btn_box, text="+ Add Slot", command=lambda d=day: self._on_add_slot(d)).pack(
                side=tk.LEFT, padx=3
            )
            ttk.Button(btn_box, text="Edit Selected (Enter)", command=lambda d=day: self._on_edit_slot(d)).pack(
                side=tk.LEFT, padx=3
            )
            ttk.Button(btn_box, text="Delete Selected (Del)", command=lambda d=day: self._on_delete_slot(d)).pack(
                side=tk.LEFT, padx=3
            )

        # Editor Bottom Bar
        bottom_frame = ttk.Frame(self.editor_frame, padding="10 5 10 10")
        bottom_frame.pack(fill=tk.X)

        default_status = (
            "Ready. Press Ctrl+O to open, Ctrl+S to save PDF, Del to delete, Esc to deselect."
            if self.timetable
            else "No file loaded. Press Ctrl+O to browse and select a PDF timetable."
        )
        self.status_var = tk.StringVar(value=default_status)
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, font=("Helvetica", 9, "italic"))
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(bottom_frame, text="View JSON", command=self._on_view_json).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            bottom_frame,
            text="Save & Regenerate PDF (Ctrl+S)",
            command=self._on_save_regenerate,
        ).pack(side=tk.RIGHT, padx=5)

        # -------------------------------------------------------------
        # View 2: Schedule Generator Wizard Frame
        # -------------------------------------------------------------
        self.wizard_frame = ScheduleWizardFrame(
            self.main_container,
            on_solve_complete=self._on_solve_complete,
            base_output_dir=self.base_output_dir,
        )

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def set_mode(self, mode: str) -> None:
        """Switch between Schedule Editor ('edit') and Generator Wizard ('create')."""
        self.current_mode = mode
        if mode == "create":
            self.editor_frame.pack_forget()
            self.wizard_frame.pack(fill=tk.BOTH, expand=True)
            self.root.title("UWM Better Schedule — Schedule Generator Wizard")
        else:
            self.wizard_frame.pack_forget()
            self.editor_frame.pack(fill=tk.BOTH, expand=True)
            self.root.title("UWM Better Schedule — Timetable Editor")

    def _on_solve_complete(self, timetable: Timetable, pdf_path: Optional[Path]) -> None:
        """Receive newly solved timetable and switch directly to Editor view."""
        self.timetable = timetable
        if pdf_path and pdf_path.exists():
            if self.storage is None:
                self.storage = StorageManager(input_pdf_path=pdf_path, base_output_dir=self.base_output_dir)
            else:
                self.storage.switch_file(pdf_path)
            self.file_path_var.set(str(pdf_path))
            self.run_dir_var.set(f"Run Dir: {self.storage.run_dir.name}")

        self._refresh_all_tables()
        self.is_modified = False
        self.set_mode("edit")
        self.status_var.set("Generated schedule loaded into Editor!")

    def _setup_keyboard_shortcuts(self) -> None:
        """Register global keyboard shortcuts."""
        # 1. Ctrl+O: Open / Load file
        self.root.bind("<Control-o>", lambda e: self._on_key_browse(e))
        self.root.bind("<Control-O>", lambda e: self._on_key_browse(e))

        # 2. Ctrl+S: Save & Regenerate PDF
        self.root.bind("<Control-s>", lambda e: self._on_key_save(e))
        self.root.bind("<Control-S>", lambda e: self._on_key_save(e))

        # 3. Ctrl+Enter: Trigger solver when in wizard mode
        self.root.bind("<Control-Return>", lambda e: self._on_key_ctrl_enter(e))

        # 4. Enter & Esc & Delete
        self.root.bind("<Return>", lambda e: self._on_key_enter(e))
        self.root.bind("<Escape>", lambda e: self._on_key_escape(e))
        self.root.bind("<Delete>", self._on_key_delete)
        self.root.bind("<BackSpace>", self._on_key_backspace)

    def _on_key_ctrl_enter(self, event: tk.Event) -> str:
        if self.current_mode == "create":
            self.wizard_frame.solve_schedule()
            return "break"
        return ""

    def _on_key_enter(self, event: tk.Event) -> Optional[str]:
        # If in wizard mode and not inside an entry/table, advance wizard step
        if self.current_mode == "create":
            focused = self.root.focus_get()
            if not isinstance(focused, (ttk.Entry, tk.Entry, ttk.Combobox, tk.Text, ttk.Treeview)):
                self.wizard_frame.next_step()
                return "break"
        return None

    def _on_key_backspace(self, event: tk.Event) -> Optional[str]:
        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry, ttk.Combobox, tk.Text)):
            return None
        if self.current_mode == "create":
            self.wizard_frame.previous_step()
            return "break"
        else:
            return self._on_key_delete(event)

    def _on_key_browse(self, event: Optional[tk.Event] = None) -> str:
        if self.current_mode == "edit":
            self._on_browse_file()
        return "break"

    def _on_key_save(self, event: Optional[tk.Event] = None) -> str:
        if self.current_mode == "edit":
            self._on_save_regenerate()
        return "break"

    def _on_key_escape(self, event: Optional[tk.Event] = None) -> str:
        if self.current_mode == "create":
            self.wizard_frame.previous_step()
            return "break"

        current_day = self._get_current_day()
        tree = self.tree_views.get(current_day)
        if tree:
            tree.selection_remove(tree.selection())
        self.status_var.set("Selection cleared (Esc).")
        return "break"

    def _on_key_delete(self, event: tk.Event) -> Optional[str]:
        if self.current_mode != "edit":
            return None
        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry, ttk.Combobox, tk.Text)):
            return None

        current_day = self._get_current_day()
        self._on_delete_slot(current_day)
        return "break"

    def _on_tab_changed(self, event: tk.Event) -> None:
        current_day = self._get_current_day()
        tree = self.tree_views.get(current_day)
        if tree:
            tree.focus_set()

    def _on_browse_file(self) -> None:
        if self.is_modified:
            resp = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before loading a new file?",
                parent=self.root,
            )
            if resp is None:
                return
            if resp is True:
                self._on_save_regenerate()

        initial_dir = ensure_input_directory()
        selected = filedialog.askopenfilename(
            title="Select Timetable PDF Document",
            initialdir=str(initial_dir),
            filetypes=[("PDF files", "*.pdf"), ("PDF files (all cases)", "*.PDF"), ("All files", "*.*")],
            parent=self.root,
        )
        if not selected:
            return

        self.load_pdf(selected)

    def load_pdf(self, file_path: str | Path) -> bool:
        target_path = Path(file_path).resolve()
        if not target_path.is_file():
            messagebox.showerror("File Error", f"Selected file does not exist:\n{target_path}", parent=self.root)
            return False

        try:
            if self.storage is None:
                self.storage = StorageManager(input_pdf_path=target_path, base_output_dir=self.base_output_dir)
            else:
                self.storage.switch_file(target_path)

            parser = TimetableParser(target_path, log_handler=self.storage.logger)
            self.timetable = parser.parse()
            self.storage.save_extracted(self.timetable)

            self.file_path_var.set(str(target_path))
            self.run_dir_var.set(f"Run Dir: {self.storage.run_dir.name}")
            self.is_modified = False

            self._refresh_all_tables()
            self.status_var.set(f"Loaded '{target_path.name}' ({self.timetable.count_total_entries()} slots)")

            current_day = self._get_current_day()
            if current_day in self.tree_views:
                self.tree_views[current_day].focus_set()

            return True
        except Exception as e:
            messagebox.showerror("Parsing Error", f"Failed to parse PDF timetable:\n{e}", parent=self.root)
            if self.storage:
                self.storage.error(f"Error loading {target_path}: {e}")
            return False

    def _get_current_day(self) -> str:
        tab_id = self.notebook.select()
        tab_text = self.notebook.tab(tab_id, "text").lower()
        return tab_text

    def _refresh_day_table(self, day: str) -> None:
        tree = self.tree_views[day]
        for item in tree.get_children():
            tree.delete(item)

        if not self.timetable:
            return

        entries = self.timetable.get_entries(day)
        for idx, e in enumerate(entries):
            grp_text = str(e.group) if e.group is not None else "All"
            notes_text = e.notes or ""
            tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(e.hours, e.subject, e.academic_instructor, e.room, e.type, grp_text, notes_text),
            )

    def _refresh_all_tables(self) -> None:
        for day in VALID_DAYS:
            self._refresh_day_table(day)

    def _on_add_slot(self, day: str) -> None:
        if self.timetable is None:
            messagebox.showinfo("No File Loaded", "Please load a PDF timetable first.", parent=self.root)
            return

        dlg = SlotDialog(self.root, title=f"Add Class Slot ({day.capitalize()})", initial_day=day)
        self.root.wait_window(dlg)
        if dlg.result:
            target_day, entry = dlg.result
            self.timetable.add_entry(target_day, entry)
            self.is_modified = True
            self._refresh_day_table(target_day)
            self.status_var.set(f"Added '{entry.subject}' to {target_day.capitalize()}.")

    def _on_edit_slot(self, day: str) -> None:
        if self.timetable is None:
            messagebox.showinfo("No File Loaded", "Please load a PDF timetable first.", parent=self.root)
            return

        tree = self.tree_views[day]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a slot to edit.", parent=self.root)
            return

        idx = int(sel[0])
        entry = self.timetable.get_entries(day)[idx]

        dlg = SlotDialog(self.root, title=f"Edit Slot #{idx} ({day.capitalize()})", initial_day=day, entry=entry)
        self.root.wait_window(dlg)
        if dlg.result:
            target_day, updated_entry = dlg.result
            if target_day == day:
                self.timetable.modify_entry(day, idx, updated_entry)
            else:
                self.timetable.delete_entry(day, idx)
                self.timetable.add_entry(target_day, updated_entry)
                self._refresh_day_table(target_day)

            self.is_modified = True
            self._refresh_day_table(day)
            self.status_var.set(f"Updated slot '{updated_entry.subject}'.")

    def _on_delete_slot(self, day: str) -> None:
        if self.timetable is None:
            messagebox.showinfo("No File Loaded", "Please load a PDF timetable first.", parent=self.root)
            return

        tree = self.tree_views[day]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a slot to delete.", parent=self.root)
            return

        idx = int(sel[0])
        entry = self.timetable.get_entries(day)[idx]

        if messagebox.askyesno("Confirm Deletion", f"Delete '{entry.subject}' ({entry.hours})?", parent=self.root):
            self.timetable.delete_entry(day, idx)
            self.is_modified = True
            self._refresh_day_table(day)
            self.status_var.set(f"Deleted slot #{idx} from {day.capitalize()}.")

    def _on_view_json(self) -> None:
        if self.timetable is None:
            messagebox.showinfo("No File Loaded", "No timetable is currently loaded.", parent=self.root)
            return

        json_window = tk.Toplevel(self.root)
        json_window.title("Timetable JSON Schema")
        json_window.geometry("640x500")

        text_area = tk.Text(json_window, wrap=tk.NONE, font=("Courier", 10))
        text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(json_window, orient=tk.VERTICAL, command=text_area.yview)
        text_area.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        text_area.insert(tk.END, self.timetable.to_json(indent=2))
        text_area.configure(state="disabled")
        json_window.bind("<Escape>", lambda e: json_window.destroy())

    def _on_save_regenerate(self) -> None:
        if self.timetable is None or self.storage is None:
            messagebox.showwarning("No Timetable", "Please load a PDF timetable before saving.", parent=self.root)
            return

        try:
            self.storage.save_modified(self.timetable)
            self.generator.generate(self.timetable, self.storage.output_pdf_path)
            self.is_modified = False
            self.status_var.set(f"Saved & regenerated: {self.storage.output_pdf_path.name}")
            messagebox.showinfo(
                "Success",
                f"Successfully saved and regenerated timetable!\n\nPDF: {self.storage.output_pdf_path}\nLog: {self.storage.log_file_path}",
                parent=self.root,
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PDF: {e}", parent=self.root)

    def _on_close(self) -> None:
        if self.is_modified:
            if messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Save before exiting?", parent=self.root):
                self._on_save_regenerate()
        if self.storage:
            self.storage.close()
        self.root.destroy()

    def run(self) -> None:
        """Start Tkinter main event loop."""
        self.root.mainloop()

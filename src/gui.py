"""Graphical User Interface for timetable editing and automated schedule generation wizard."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from src.core.generator import TimetablePDFGenerator
from src.core.models import (
    VALID_DAYS,
    AcademicStructure,
    AcademicYear,
    BackgroundOverlay,
    BaseGroup,
    ConflictRule,
    CourseRequirement,
    Instructor,
    Room,
    ScheduleCategory,
    ScheduleGenerationConfig,
    ScheduleProject,
    SessionOverride,
    Specialization,
    StudentSubgroup,
    TimeHorizon,
    TimeWindow,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)
from src.core.parser import TimetableParser
from src.core.scheduler import AcademicScheduler, ScheduleResult, export_schedule_artifacts, verify_schedule_collisions
from src.core.storage import StorageManager, compute_timetable_diff, ensure_input_directory, load_project, save_project


# =====================================================================
# Scrollable Container & Dialog Form Components
# =====================================================================

class ScrollableDialogBody(ttk.Frame):
    """Scrollable container frame for dialog forms to prevent layout clipping on any screen resolution."""

    def __init__(self, parent: tk.Widget, *args: Any, **kwargs: Any):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.interior = ttk.Frame(self.canvas, padding="15 15 15 15")

        self.interior_id = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.interior.bind("<Configure>", self._on_interior_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._bind_mousewheel(self)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.interior)

    def _on_interior_configure(self, event: Any) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: Any) -> None:
        if event.width > 10:
            self.canvas.itemconfig(self.interior_id, width=event.width)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_mousewheel, add="+")

    def _on_mousewheel(self, event: Any) -> None:
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        elif getattr(event, "delta", 0):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# =====================================================================
# In-App Tooltips, Help Badges & Safe Double-Click Binding
# =====================================================================

class ToolTip:
    """Lightweight, flicker-free hover tooltip for Tkinter widgets without stealing focus."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 350):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event=None) -> None:
        self._cancel_timer()
        self._after_id = self.widget.after(self.delay_ms, self._show_tip)

    def _on_leave(self, event=None) -> None:
        self._cancel_timer()
        self._hide_tip()

    def _cancel_timer(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show_tip(self) -> None:
        if self.tip_window or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 15
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except Exception:
            pass

        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#2C3E50",
            foreground="#FFFFFF",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=4,
            font=("Helvetica", 8),
            wraplength=280,
        )
        label.pack()

    def _hide_tip(self) -> None:
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


def add_help_icon(parent: tk.Widget, tooltip_text: str) -> ttk.Label:
    """Create a small distinct '(?)' help badge with a hover tooltip."""
    lbl = ttk.Label(
        parent,
        text="(?)",
        foreground="#2980B9",
        cursor="question_arrow",
        font=("Helvetica", 8, "bold"),
    )
    ToolTip(lbl, tooltip_text)
    return lbl


def bind_tree_double_click(tree: ttk.Treeview, edit_func: Callable[[], None]) -> None:
    """Safely bind double-click to an edit action, ignoring clicks on empty treeview areas."""
    def on_dbl_click(event):
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        tree.selection_set(row_id)
        tree.focus(row_id)
        edit_func()

    tree.bind("<Double-1>", on_dbl_click)


# =====================================================================
# Editor Slot Dialog
# =====================================================================

class CategoryDialog(tk.Toplevel):
    """Modal dialog for defining or editing a custom visual category with hex color."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, title: str, category: Optional[ScheduleCategory] = None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()

        self.category = category
        self.result: Optional[ScheduleCategory] = None
        self._build_ui()
        w, h = 480, 360
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 280)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_bar = ttk.Frame(self, padding="10 8 10 10")
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        ttk.Button(btn_bar, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_bar, text="Save (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Category ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.category.category_id if self.category else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Category Name:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.category.name if self.category else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Color (Hex):").grid(row=2, column=0, sticky=tk.W, pady=4)
        col_box = ttk.Frame(frame)
        col_box.grid(row=2, column=1, sticky=tk.W, pady=4)
        self.color_var = tk.StringVar(value=self.category.color if self.category else "#3498DB")
        ttk.Entry(col_box, textvariable=self.color_var, width=14).pack(side=tk.LEFT, padx=(0, 4))

        init_preview_bg = self.color_var.get().strip() or "#3498DB"
        self.color_swatch = tk.Label(
            col_box,
            text="   ",
            background=init_preview_bg if init_preview_bg.startswith("#") else "#3498DB",
            relief=tk.RIDGE,
            borderwidth=2,
            width=3,
        )
        self.color_swatch.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(col_box, text="Pick Color...", command=self._pick_color).pack(side=tk.LEFT)
        self.color_var.trace_add("write", lambda *_: self._update_swatch())

        ttk.Label(frame, text="Description / Note:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.desc_var = tk.StringVar(value=(self.category.description or "") if self.category else "")
        ttk.Entry(frame, textvariable=self.desc_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

    def _update_swatch(self) -> None:
        c = self.color_var.get().strip()
        if c.startswith("#") and len(c) in (4, 7):
            try:
                self.color_swatch.configure(background=c)
            except Exception:
                pass

    def _pick_color(self) -> None:
        init_c = self.color_var.get().strip() or "#3498DB"
        chosen = colorchooser.askcolor(color=init_c, title="Select Category Color", parent=self)
        if chosen and chosen[1]:
            self.color_var.set(chosen[1].upper())
            self._update_swatch()

    def _on_confirm(self) -> None:
        cid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        color = self.color_var.get().strip()
        desc = self.desc_var.get().strip() or None
        if not cid or not name:
            messagebox.showerror("Validation Error", "Category ID and Name are required.", parent=self)
            return
        if not color.startswith("#") or len(color) not in (4, 7):
            messagebox.showerror("Validation Error", "Valid hex color (e.g. #3498DB) is required.", parent=self)
            return
        self.result = ScheduleCategory(category_id=cid, name=name, color=color, description=desc)
        self.destroy()


class OverlayDialog(tk.Toplevel):
    """Modal dialog for configuring background overlay zones (e.g. Godziny Rektorskie / Dekanackie)."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, title: str, overlay: Optional[BackgroundOverlay] = None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()

        self.overlay = overlay
        self.result: Optional[BackgroundOverlay] = None
        self._build_ui()
        w, h = 490, 480
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(420, 360)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_bar = ttk.Frame(self, padding="10 8 10 10")
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        ttk.Button(btn_bar, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_bar, text="Save (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Overlay ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.overlay.overlay_id if self.overlay else "overlay_1")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Label:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.label_var = tk.StringVar(value=self.overlay.label if self.overlay else "Godziny Rektorskie")
        ttk.Entry(frame, textvariable=self.label_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Description:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.desc_var = tk.StringVar(value=(self.overlay.description if self.overlay and self.overlay.description else ""))
        ttk.Entry(frame, textvariable=self.desc_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Day of Week:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.day_var = tk.StringVar(value=self.overlay.day if self.overlay else "tuesday")
        ttk.Combobox(frame, textvariable=self.day_var, values=list(VALID_DAYS), state="readonly", width=26).grid(
            row=3, column=1, sticky=tk.W, pady=4
        )

        lbl_time_frame = ttk.Frame(frame)
        lbl_time_frame.grid(row=4, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_time_frame, text="Hours (Start - End):").pack(side=tk.LEFT)
        add_help_icon(lbl_time_frame, "Time range in HH:MM format for this background block (e.g. Dean's hours, Rector's hours, maintenance windows).").pack(side=tk.LEFT, padx=3)

        time_box = ttk.Frame(frame)
        time_box.grid(row=4, column=1, sticky=tk.W, pady=4)
        self.start_var = tk.StringVar(value=self.overlay.start_time if self.overlay else "11:30")
        self.end_var = tk.StringVar(value=self.overlay.end_time if self.overlay else "12:45")
        ttk.Entry(time_box, textvariable=self.start_var, width=8).pack(side=tk.LEFT)
        ttk.Label(time_box, text=" - ").pack(side=tk.LEFT)
        ttk.Entry(time_box, textvariable=self.end_var, width=8).pack(side=tk.LEFT)

        ttk.Label(frame, text="Color:").grid(row=5, column=0, sticky=tk.W, pady=4)
        col_box = ttk.Frame(frame)
        col_box.grid(row=5, column=1, sticky=tk.W, pady=4)
        self.color_var = tk.StringVar(value=self.overlay.color if self.overlay else "#FF5429")
        ttk.Entry(col_box, textvariable=self.color_var, width=14).pack(side=tk.LEFT, padx=(0, 4))

        init_preview_bg = self.color_var.get().strip() or "#FF5429"
        self.color_swatch = tk.Label(
            col_box,
            text="   ",
            background=init_preview_bg if init_preview_bg.startswith("#") else "#FF5429",
            relief=tk.RIDGE,
            borderwidth=2,
            width=3,
        )
        self.color_swatch.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(col_box, text="Pick Color...", command=self._pick_color).pack(side=tk.LEFT)
        self.color_var.trace_add("write", lambda *_: self._update_swatch())

        ttk.Label(frame, text="Opacity (0.0 - 1.0):").grid(row=6, column=0, sticky=tk.W, pady=4)
        self.opacity_var = tk.StringVar(value=str(self.overlay.opacity if self.overlay else 0.25))
        ttk.Combobox(frame, textvariable=self.opacity_var, values=["0.15", "0.25", "0.35", "0.50", "0.75"], width=26).grid(
            row=7, column=1, sticky=tk.W, pady=4
        )

        lbl_pat_frame = ttk.Frame(frame)
        lbl_pat_frame.grid(row=7, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_pat_frame, text="Pattern:").pack(side=tk.LEFT)
        add_help_icon(lbl_pat_frame, "Hatching style rendered on timetable grid and legend swatches: solid, diagonal, or cross.").pack(side=tk.LEFT, padx=3)
        self.pattern_var = tk.StringVar(value=self.overlay.pattern if self.overlay else "solid")
        ttk.Combobox(frame, textvariable=self.pattern_var, values=["solid", "diagonal", "cross"], state="readonly", width=26).grid(
            row=7, column=1, sticky=tk.W, pady=4
        )

    def _update_swatch(self) -> None:
        c = self.color_var.get().strip()
        if c.startswith("#") and len(c) in (4, 7):
            try:
                self.color_swatch.configure(background=c)
            except Exception:
                pass

    def _pick_color(self) -> None:
        init_c = self.color_var.get().strip() or "#FF5429"
        chosen = colorchooser.askcolor(color=init_c, title="Select Overlay Color", parent=self)
        if chosen and chosen[1]:
            self.color_var.set(chosen[1].upper())
            self._update_swatch()

    def _on_confirm(self) -> None:
        oid = self.id_var.get().strip()
        label = self.label_var.get().strip()
        day = self.day_var.get().strip().lower()
        s_time = self.start_var.get().strip()
        e_time = self.end_var.get().strip()
        color = self.color_var.get().strip()
        try:
            opacity = float(self.opacity_var.get().strip())
        except ValueError:
            opacity = 0.25
        pattern = self.pattern_var.get().strip()

        if not oid or not day or not s_time or not e_time:
            messagebox.showerror("Validation Error", "ID, Day, and Hours are required.", parent=self)
            return

        desc = self.desc_var.get().strip() or None
        self.result = BackgroundOverlay(
            overlay_id=oid,
            label=label,
            day=day,
            start_time=s_time,
            end_time=e_time,
            color=color,
            opacity=opacity,
            pattern=pattern,
            description=desc,
        )
        self.destroy()


class CustomNoteDialog(tk.Toplevel):
    """Modal dialog for entering free-form custom canvas notes."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, title: str, initial_text: str = ""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[str] = None

        # 1. Persistent bottom button bar packed first
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Main content container
        frame = ttk.Frame(self, padding="15 15 15 15")
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Note Text:").pack(anchor=tk.W, pady=(0, 4))
        self.note_var = tk.StringVar(value=initial_text)
        entry = ttk.Entry(frame, textvariable=self.note_var, width=48)
        entry.pack(fill=tk.X, pady=(0, 10))
        entry.focus_set()

        w, h = 480, 220
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(380, 180)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _on_confirm(self) -> None:
        val = self.note_var.get().strip()
        if val:
            self.result = val
        self.destroy()


class SlotDialog(tk.Toplevel):
    """Modal dialog for adding or editing a timetable slot with full keyboard navigation."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        title: str,
        initial_day: str = "monday",
        entry: Optional[TimetableEntry] = None,
        available_categories: Optional[List[ScheduleCategory]] = None,
    ):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[Tuple[str, TimetableEntry]] = None
        self.initial_day = initial_day
        self.entry = entry
        self.available_categories = list(available_categories) if available_categories else []

        self._build_ui()
        w, h = 520, 580
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(440, 400)

        # Keyboard shortcuts inside dialog
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_frame = ttk.Frame(self, padding="10 8 10 10")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        cancel_btn = ttk.Button(btn_frame, text="Cancel (Esc)", command=self._on_cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=5)
        confirm_btn = ttk.Button(btn_frame, text="Confirm (Enter)", command=self._on_confirm)
        confirm_btn.pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

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

        # Category
        ttk.Label(frame, text="Category:").grid(row=8, column=0, sticky=tk.W, pady=4)
        cat_labels = [""]
        self.cat_map: Dict[str, ScheduleCategory] = {}
        for c in self.available_categories:
            label = f"{c.name} ({c.category_id})"
            cat_labels.append(label)
            self.cat_map[label] = c
            self.cat_map[c.category_id] = c
            self.cat_map[c.name] = c

        init_cat = ""
        if self.entry and self.entry.category_ids:
            for c in self.available_categories:
                if c.category_id in self.entry.category_ids:
                    init_cat = f"{c.name} ({c.category_id})"
                    break
            if not init_cat and self.entry.category_ids:
                init_cat = self.entry.category_ids[0]

        self.category_var = tk.StringVar(value=init_cat)
        self.category_combo = ttk.Combobox(frame, textvariable=self.category_var, values=cat_labels, width=25)
        self.category_combo.grid(row=8, column=1, sticky=tk.W, pady=4)

        def _on_slot_cat_selected(*_):
            val = self.category_var.get().strip()
            cat = self.cat_map.get(val)
            if not cat:
                for c in self.available_categories:
                    if c.category_id == val or c.name == val:
                        cat = c
                        break
            if cat and cat.color:
                cur = self.colors_var.get().strip()
                if not cur or cur == "#FFFFFF":
                    self.colors_var.set(cat.color)
                elif cat.color not in cur:
                    self.colors_var.set(f"{cur}, {cat.color}")

        self.category_combo.bind("<<ComboboxSelected>>", _on_slot_cat_selected)

        # Colors (comma-separated hex for multi-color striping)
        ttk.Label(frame, text="Colors (Hex, csv):").grid(row=9, column=0, sticky=tk.W, pady=4)
        col_frame = ttk.Frame(frame)
        col_frame.grid(row=9, column=1, sticky=tk.W, pady=4)
        init_cols = ", ".join(self.entry.colors) if (self.entry and self.entry.colors) else ""
        self.colors_var = tk.StringVar(value=init_cols)
        self.colors_entry = ttk.Entry(col_frame, textvariable=self.colors_var, width=17)
        self.colors_entry.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(col_frame, text="Pick...", command=self._pick_slot_color).pack(side=tk.LEFT)

        # Custom Note
        ttk.Label(frame, text="Custom Note:").grid(row=10, column=0, sticky=tk.W, pady=4)
        self.custom_note_var = tk.StringVar(value=(self.entry.custom_note or "") if self.entry else "")
        self.custom_note_entry = ttk.Entry(frame, textvariable=self.custom_note_var, width=27)
        self.custom_note_entry.grid(row=10, column=1, sticky=tk.W, pady=4)

        self.after(50, lambda: self.subject_entry.focus_set())

    def _pick_slot_color(self) -> None:
        chosen = colorchooser.askcolor(title="Pick Cell Color", parent=self)
        if chosen and chosen[1]:
            cur = self.colors_var.get().strip()
            if cur:
                self.colors_var.set(f"{cur}, {chosen[1].upper()}")
            else:
                self.colors_var.set(chosen[1].upper())

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

        col_str = self.colors_var.get().strip()
        colors_list = [c.strip() for c in col_str.split(",") if c.strip()]
        c_note = self.custom_note_var.get().strip() or None

        raw_cat = getattr(self, "category_var", tk.StringVar()).get().strip()
        cat_ids: List[str] = []
        if raw_cat:
            cat = getattr(self, "cat_map", {}).get(raw_cat)
            if not cat:
                for c in getattr(self, "available_categories", []):
                    if c.category_id == raw_cat or c.name == raw_cat:
                        cat = c
                        break
            if cat:
                cat_ids.append(cat.category_id)
                if not colors_list and cat.color:
                    colors_list = [cat.color]
            else:
                cat_ids.append(raw_cat)

        try:
            entry = TimetableEntry(
                subject=subject,
                hours=hours,
                academic_instructor=instructor,
                room=room,
                type=slot_type,  # type: ignore[arg-type]
                group=group,
                notes=notes,
                colors=colors_list,
                category_ids=cat_ids,
                custom_note=c_note,
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
        self.transient(parent)
        self.grab_set()

        self.room = room
        self.result: Optional[Room] = None

        self._build_ui()
        w, h = 490, 440
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 320)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_bar = ttk.Frame(self, padding="10 8 10 10")
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        ttk.Button(btn_bar, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_bar, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

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
    """Dialog to create/edit a course requirement with category and color selection."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        course: Optional[CourseRequirement] = None,
        available_years: Optional[List[str]] = None,
        available_groups: Optional[List[str]] = None,
        available_instructors: Optional[List[Tuple[str, str]]] = None,
        available_categories: Optional[List[ScheduleCategory]] = None,
    ):
        super().__init__(parent)
        self.title("Edit Course" if course else "Add New Course")
        self.transient(parent)
        self.grab_set()

        self.course = course
        self.available_years = available_years or ["rok_4"]
        self.available_groups = available_groups or ["G1", "G2"]
        self.available_instructors = available_instructors or []
        self.available_categories = list(available_categories) if available_categories else []
        self.result: Optional[CourseRequirement] = None

        self._build_ui()
        w, h = 540, 680
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(460, 420)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    @property
    def current_color(self) -> str:
        """Return the current valid hex color string or fallback to default."""
        c = self.course_color_var.get().strip()
        if c.startswith("#") and len(c) in (4, 7):
            return c
        if self.course and self.course.color:
            return self.course.color
        return "#3498DB"

    def _update_course_color_swatch(self) -> None:
        """Update color preview swatch widget."""
        c = self.course_color_var.get().strip()
        if c.startswith("#") and len(c) in (4, 7):
            try:
                self.course_color_swatch.configure(background=c)
            except Exception:
                pass
        else:
            try:
                self.course_color_swatch.configure(background="#E0E0E0")
            except Exception:
                pass

    def _pick_course_color(self) -> None:
        """Open system color chooser dialog and store selected hex value in dialog state."""
        chosen = colorchooser.askcolor(color=self.current_color, title="Select Course Category Color", parent=self)
        if chosen and chosen[1]:
            hex_color = chosen[1].upper()
            self.course_color_var.set(hex_color)
            self._update_course_color_swatch()

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

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
            row=3, column=1, sticky=tk.W, pady=4
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
            row=7, column=1, sticky=tk.W, pady=4
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
        lbl_bb_frame = ttk.Frame(frame)
        lbl_bb_frame.grid(row=9, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_bb_frame, text="Break Before (min):").pack(side=tk.LEFT)
        add_help_icon(lbl_bb_frame, "Minimum mandatory rest/travel buffer (in minutes) required before this course starts.").pack(side=tk.LEFT, padx=3)

        bb_val = str(self.course.break_before) if (self.course and self.course.break_before is not None) else ""
        self.break_before_var = tk.StringVar(value=bb_val)
        ttk.Combobox(frame, textvariable=self.break_before_var, values=["", "0", "10", "15", "20", "30", "45", "60"], width=26).grid(
            row=9, column=1, sticky=tk.W, pady=4
        )

        lbl_ba_frame = ttk.Frame(frame)
        lbl_ba_frame.grid(row=10, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_ba_frame, text="Break After (min):").pack(side=tk.LEFT)
        add_help_icon(lbl_ba_frame, "Minimum mandatory rest/travel buffer (in minutes) required after this course ends.").pack(side=tk.LEFT, padx=3)

        ba_val = str(self.course.break_after) if (self.course and self.course.break_after is not None) else ""
        self.break_after_var = tk.StringVar(value=ba_val)
        ttk.Combobox(frame, textvariable=self.break_after_var, values=["", "0", "10", "15", "20", "30", "45", "60"], width=26).grid(
            row=10, column=1, sticky=tk.W, pady=4
        )

        # Category / Color
        lbl_cat_frame = ttk.Frame(frame)
        lbl_cat_frame.grid(row=11, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_cat_frame, text="Category:").pack(side=tk.LEFT)
        add_help_icon(lbl_cat_frame, "Assign a visual category and hex fill color. Courses with multiple groups or categories render split color striping.").pack(side=tk.LEFT, padx=3)
        cat_options = [""]
        self.cat_lookup: Dict[str, ScheduleCategory] = {}
        for c in self.available_categories:
            lbl = f"{c.name} ({c.category_id})"
            cat_options.append(lbl)
            self.cat_lookup[lbl] = c
            self.cat_lookup[c.category_id] = c
            self.cat_lookup[c.name] = c

        init_cat = ""
        if self.course and self.course.category_id:
            for c in self.available_categories:
                if c.category_id == self.course.category_id:
                    init_cat = f"{c.name} ({c.category_id})"
                    break
            if not init_cat:
                init_cat = self.course.category_id

        self.category_var = tk.StringVar(value=init_cat)
        self.category_combo = ttk.Combobox(frame, textvariable=self.category_var, values=cat_options, width=26)
        self.category_combo.grid(row=11, column=1, sticky=tk.W, pady=4)

        def _on_course_cat_selected(*_):
            val = self.category_var.get().strip()
            cat = self.cat_lookup.get(val)
            if not cat:
                for c in self.available_categories:
                    if c.category_id == val or c.name == val:
                        cat = c
                        break
            if cat and cat.color:
                self.course_color_var.set(cat.color)
                self._update_course_color_swatch()

        self.category_combo.bind("<<ComboboxSelected>>", _on_course_cat_selected)
        self.category_var.trace_add("write", _on_course_cat_selected)

        ttk.Label(frame, text="Subject Color (Hex):").grid(row=12, column=0, sticky=tk.W, pady=4)
        cd_col_box = ttk.Frame(frame)
        cd_col_box.grid(row=12, column=1, sticky=tk.W, pady=4)
        self.course_color_var = tk.StringVar(value=(self.course.color or "") if self.course else "")
        ttk.Entry(cd_col_box, textvariable=self.course_color_var, width=14).pack(side=tk.LEFT, padx=(0, 4))

        init_preview_bg = self.course_color_var.get().strip() or "#E0E0E0"
        self.course_color_swatch = tk.Label(
            cd_col_box,
            text="   ",
            background=init_preview_bg if init_preview_bg.startswith("#") else "#E0E0E0",
            relief=tk.RIDGE,
            borderwidth=2,
            width=3,
        )
        self.course_color_swatch.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(cd_col_box, text="Pick...", command=self._pick_course_color).pack(side=tk.LEFT)
        self.course_color_var.trace_add("write", lambda *_: self._update_course_color_swatch())
        self._update_course_color_swatch()

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

        raw_cat = self.category_var.get().strip()
        cat_id = None
        c_color = self.course_color_var.get().strip() or None
        if raw_cat:
            cat = getattr(self, "cat_lookup", {}).get(raw_cat)
            if not cat:
                for c in getattr(self, "available_categories", []):
                    if c.category_id == raw_cat or c.name == raw_cat:
                        cat = c
                        break
            if cat:
                cat_id = cat.category_id
                if not c_color and cat.color:
                    c_color = cat.color
            else:
                cat_id = raw_cat

        # Sync color and category into subject model
        colors_list = [c_color] if c_color else []
        cat_ids = [cat_id] if cat_id else []

        self.result = CourseRequirement(
            course_id=cid,
            subject_name=sname,
            duration_minutes=dur,
            delivery_format=del_fmt,
            required_room_type=rtype,
            target_year_id=y_id,
            is_whole_year=is_wy,
            target_group_ids=target_g,
            instructor_id=inst_id,
            break_before=break_before,
            break_after=break_after,
            category_id=cat_id,
            category_ids=cat_ids,
            color=c_color,
            colors=colors_list,
        )
        self.destroy()


class InstructorDialog(tk.Toplevel):
    """Dialog to create/edit an instructor."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, instructor: Optional[Instructor] = None):
        super().__init__(parent)
        self.title("Edit Instructor" if instructor else "Add New Instructor")
        self.transient(parent)
        self.grab_set()

        self.instructor = instructor
        self.result: Optional[Instructor] = None

        self._build_ui()
        w, h = 490, 420
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 320)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_confirm())

    def _build_ui(self) -> None:
        # 1. Persistent bottom action button bar packed first
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._on_confirm).pack(side=tk.RIGHT)

        # 2. Scrollable form body packed second
        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Instructor ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.instructor.instructor_id if self.instructor else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Full Name & Title:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.instructor.name if self.instructor else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        lbl_md_frame = ttk.Frame(frame)
        lbl_md_frame.grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_md_frame, text="Max Hours / Day:").pack(side=tk.LEFT)
        add_help_icon(lbl_md_frame, "Upper limit on teaching hours in a single calendar day to avoid teacher burnout.").pack(side=tk.LEFT, padx=3)

        self.max_d_var = tk.StringVar(value=str(self.instructor.max_hours_per_day if self.instructor else 6.0))
        ttk.Entry(frame, textvariable=self.max_d_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        lbl_mw_frame = ttk.Frame(frame)
        lbl_mw_frame.grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Label(lbl_mw_frame, text="Max Hours / Week:").pack(side=tk.LEFT)
        add_help_icon(lbl_mw_frame, "Weekly teaching hour ceiling for this instructor across all assigned courses.").pack(side=tk.LEFT, padx=3)
        self.max_w_var = tk.StringVar(value=str(self.instructor.max_hours_per_week if self.instructor else 20.0))
        ttk.Entry(frame, textvariable=self.max_w_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Qualified Course IDs (comma separated):").grid(row=4, column=0, sticky=tk.W, pady=4)
        qc = ", ".join(self.instructor.qualified_course_ids) if self.instructor else ""
        self.qual_var = tk.StringVar(value=qc)
        ttk.Entry(frame, textvariable=self.qual_var, width=28).grid(row=4, column=1, sticky=tk.W, pady=4)

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
    """Dialog to add/edit an academic year."""

    def __init__(self, parent: tk.Widget, study_cycles: List[str], year: Optional[AcademicYear] = None):
        super().__init__(parent)
        self.year = year
        self.title("Edit Academic Year" if year else "Add Academic Year")
        self.transient(parent)
        self.grab_set()
        self.study_cycles = study_cycles
        self.result: Optional[AcademicYear] = None

        self._build_ui()
        w, h = 480, 320
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 260)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _build_ui(self) -> None:
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Year ID (e.g. 'rok_1'):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.year.year_id if self.year else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name (e.g. 'I ROK'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.year.name if self.year else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Study Cycle:").grid(row=2, column=0, sticky=tk.W, pady=4)
        default_cycle = self.year.study_cycle if self.year else (self.study_cycles[0] if self.study_cycles else "stacjonarne inżynierskie I-go stopnia")
        self.cycle_var = tk.StringVar(value=default_cycle)
        ttk.Combobox(frame, textvariable=self.cycle_var, values=self.study_cycles, width=26).grid(row=2, column=1, sticky=tk.W, pady=4)

    def _confirm(self) -> None:
        yid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cycle = self.cycle_var.get().strip()
        if not yid or not name:
            messagebox.showerror("Error", "Please provide a valid Year ID and Display Name.", parent=self)
            return
        specs = list(self.year.specializations) if self.year else []
        self.result = AcademicYear(year_id=yid, name=name, study_cycle=cycle, specializations=specs)
        self.destroy()

    _on_confirm = _confirm


class SpecializationDialog(tk.Toplevel):
    """Dialog to add/edit a specialization under an academic year."""

    def __init__(
        self,
        parent: tk.Widget,
        years: List[AcademicYear],
        spec: Optional[Specialization] = None,
        parent_year_id: Optional[str] = None,
    ):
        super().__init__(parent)
        self.spec = spec
        self.parent_year_id = parent_year_id
        self.title("Edit Specialization" if spec else "Add Specialization")
        self.transient(parent)
        self.grab_set()
        self.years = years
        self.result: Optional[Tuple[str, Specialization]] = None

        self._build_ui()
        w, h = 480, 340
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 260)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _build_ui(self) -> None:
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Target Year:").grid(row=0, column=0, sticky=tk.W, pady=4)
        year_options = [f"{y.name} ({y.year_id})" for y in self.years]
        init_y_opt = ""
        if self.parent_year_id:
            for y in self.years:
                if y.year_id == self.parent_year_id:
                    init_y_opt = f"{y.name} ({y.year_id})"
                    break
        if not init_y_opt and year_options:
            init_y_opt = year_options[0]

        self.year_var = tk.StringVar(value=init_y_opt)
        ttk.Combobox(frame, textvariable=self.year_var, values=year_options, state="readonly", width=26).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Spec ID (e.g. 'spec_io'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.spec.spec_id if self.spec else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.spec.name if self.spec else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Total Headcount:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value=str(self.spec.student_count) if self.spec else "32")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

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
        grps = list(self.spec.groups) if self.spec else []
        self.result = (target_year_id, Specialization(spec_id=sid, name=name, student_count=int(cnt), groups=grps))
        self.destroy()

    _on_confirm = _confirm


class BaseGroupDialog(tk.Toplevel):
    """Dialog to add/edit a base student group under a specialization."""

    def __init__(
        self,
        parent: tk.Widget,
        specs: List[Tuple[str, str, Specialization]],
        group: Optional[BaseGroup] = None,
        parent_spec_id: Optional[str] = None,
    ):
        super().__init__(parent)
        self.group = group
        self.parent_spec_id = parent_spec_id
        self.title("Edit Student Base Group" if group else "Add Student Base Group")
        self.transient(parent)
        self.grab_set()
        self.specs = specs
        self.result: Optional[Tuple[str, str, BaseGroup]] = None

        self._build_ui()
        w, h = 480, 340
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 260)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _build_ui(self) -> None:
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Target Specialization:").grid(row=0, column=0, sticky=tk.W, pady=4)
        spec_options = [f"{s.name} ({s.spec_id})" for _, _, s in self.specs]
        init_spec_opt = ""
        if self.parent_spec_id:
            for _, sid, s in self.specs:
                if sid == self.parent_spec_id:
                    init_spec_opt = f"{s.name} ({s.spec_id})"
                    break
        if not init_spec_opt and spec_options:
            init_spec_opt = spec_options[0]

        self.spec_var = tk.StringVar(value=init_spec_opt)
        ttk.Combobox(frame, textvariable=self.spec_var, values=spec_options, state="readonly", width=26).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Group ID (e.g. 'G1'):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.group.group_id if self.group else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.group.name if self.group else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Group Headcount:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value=str(self.group.student_count) if self.group else "16")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

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

    _on_confirm = _confirm


class SubgroupDialog(tk.Toplevel):
    """Dialog to create/edit an elective/shared student subgroup."""

    def __init__(self, parent: tk.Widget, available_groups: List[str], subgroup: Optional[StudentSubgroup] = None):
        super().__init__(parent)
        self.subgroup = subgroup
        self.title("Edit Student Subgroup" if subgroup else "Add Student Subgroup")
        self.transient(parent)
        self.grab_set()
        self.result: Optional[StudentSubgroup] = None

        self.available_groups = available_groups
        self._build_ui()
        w, h = 480, 340
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 260)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _build_ui(self) -> None:
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Subgroup ID (e.g. 'SUB_AI'):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.subgroup.subgroup_id if self.subgroup else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Display Name:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar(value=self.subgroup.name if self.subgroup else "")
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Headcount:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value=str(self.subgroup.student_count) if self.subgroup else "15")
        ttk.Entry(frame, textvariable=self.count_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Parent Groups (CSV):").grid(row=3, column=0, sticky=tk.W, pady=4)
        init_p = ", ".join(self.subgroup.parent_group_ids) if self.subgroup else (", ".join(self.available_groups[:2]) if self.available_groups else "")
        self.parents_var = tk.StringVar(value=init_p)
        ttk.Entry(frame, textvariable=self.parents_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

    def _confirm(self) -> None:
        sid = self.id_var.get().strip()
        name = self.name_var.get().strip()
        cnt = self.count_var.get().strip()
        parents = [p.strip() for p in self.parents_var.get().split(",") if p.strip()]
        if not sid or not name or not cnt.isdigit() or int(cnt) <= 0:
            messagebox.showerror("Error", "Please provide a valid Subgroup ID, Name, and positive Headcount.", parent=self)
            return
        associated = list(self.subgroup.associated_course_ids) if self.subgroup else []
        self.result = StudentSubgroup(subgroup_id=sid, name=name, student_count=int(cnt), parent_group_ids=parents, associated_course_ids=associated)
        self.destroy()

    _on_confirm = _confirm


class ConflictRuleDialog(tk.Toplevel):
    """Dialog to create/edit an explicit collision prevention rule."""

    def __init__(self, parent: tk.Widget, rule: Optional[ConflictRule] = None):
        super().__init__(parent)
        self.rule = rule
        self.title("Edit Conflict Rule" if rule else "Add Conflict Rule")
        self.transient(parent)
        self.grab_set()
        self.result: Optional[ConflictRule] = None

        self._build_ui()
        w, h = 480, 340
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")
        self.minsize(400, 260)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._confirm())

    def _build_ui(self) -> None:
        btn_box = ttk.Frame(self, padding="10 8 10 10")
        btn_box.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)
        ttk.Button(btn_box, text="Cancel (Esc)", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Confirm (Enter)", command=self._confirm).pack(side=tk.RIGHT)

        body = ScrollableDialogBody(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame = body.interior

        ttk.Label(frame, text="Rule ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.id_var = tk.StringVar(value=self.rule.rule_id if self.rule else "")
        ttk.Entry(frame, textvariable=self.id_var, width=28).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Entity A (Course / Group ID):").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.a_var = tk.StringVar(value=self.rule.entity_a if self.rule else "")
        ttk.Entry(frame, textvariable=self.a_var, width=28).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Entity B (Course / Group ID):").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.b_var = tk.StringVar(value=self.rule.entity_b if self.rule else "")
        ttk.Entry(frame, textvariable=self.b_var, width=28).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Description:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.desc_var = tk.StringVar(value=(self.rule.description or "") if self.rule else "")
        ttk.Entry(frame, textvariable=self.desc_var, width=28).grid(row=3, column=1, sticky=tk.W, pady=4)

    def _confirm(self) -> None:
        rid = self.id_var.get().strip()
        ea = self.a_var.get().strip()
        eb = self.b_var.get().strip()
        desc = self.desc_var.get().strip()
        if not rid or not ea or not eb:
            messagebox.showerror("Error", "Please provide a Rule ID and both Entities (A and B).", parent=self)
            return
        rule_name = self.rule.name if (self.rule and self.rule.name) else f"Collision rule {rid}"
        self.result = ConflictRule(rule_id=rid, name=rule_name, entity_a=ea, entity_b=eb, description=desc or None)
        self.destroy()

    _on_confirm = _confirm

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
        self.bind("<Return>", lambda e: self.destroy())

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

        # 2. Persistent Bottom Action Bar packed BEFORE expandable body
        btn_bar = ttk.Frame(self, padding="16 10 16 14")
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=8, padx=10)

        # 3. Main Tabbed Notebook packed second
        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=6)

        tab_audit = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_audit, text="  ✓ Zero-Collision Audit  ")
        self._build_audit_tab(tab_audit)

        tab_students = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_students, text="  📅 Student Schedules  ")
        self._build_students_tab(tab_students)

        tab_staff = ttk.Frame(notebook, padding="12 12 12 12")
        notebook.add(tab_staff, text="  👨‍🏫 Staff Schedules  ")
        self._build_staff_tab(tab_staff)

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
            tags = ()
            if hasattr(s, "colors") and s.colors:
                c_tag = f"col_{s.colors[0].lstrip('#')}"
                self.tree_std_prev.tag_configure(c_tag, background=s.colors[0])
                tags = (c_tag,)
            self.tree_std_prev.insert("", tk.END, values=(
                s.day.capitalize(),
                s.hours,
                s.subject,
                s.delivery_format,
                s.room_name,
                s.instructor_name,
                ", ".join(s.target_group_ids),
            ), tags=tags)

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
            tags = ()
            if hasattr(s, "colors") and s.colors:
                c_tag = f"col_{s.colors[0].lstrip('#')}"
                self.tree_staff_prev.tag_configure(c_tag, background=s.colors[0])
                tags = (c_tag,)
            self.tree_staff_prev.insert("", tk.END, values=(
                s.day.capitalize(),
                s.hours,
                s.subject,
                s.delivery_format,
                s.room_name,
                ", ".join(s.target_group_ids),
            ), tags=tags)

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

        ttk.Button(nav_frame, text="💾 Save Project", command=self._on_save_project).pack(side=tk.RIGHT, padx=4)
        ttk.Button(nav_frame, text="📂 Load Project", command=self._on_load_project).pack(side=tk.RIGHT, padx=4)
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
        ttk.Button(btn_box, text="Edit Selected", command=self._on_edit_academic_item).pack(side=tk.LEFT, padx=2)
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

        bind_tree_double_click(self.tree_academic, self._on_edit_academic_item)

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

    def _on_edit_academic_item(self) -> None:
        sel = self.tree_academic.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select an academic item to edit.", parent=self)
            return
        item = sel[0]
        vals = self.tree_academic.item(item, "values")
        if not vals:
            return
        level, item_id = vals[0], vals[1]
        if level == "Year":
            target_year = next((y for y in self.config.academic_structure.years if y.year_id == item_id), None)
            if not target_year:
                return
            dlg = AcademicYearDialog(self, study_cycles=self.config.academic_structure.study_cycles, year=target_year)
            self.wait_window(dlg)
            if dlg.result:
                target_year.year_id = dlg.result.year_id
                target_year.name = dlg.result.name
                target_year.study_cycle = dlg.result.study_cycle
                self._refresh_step1_tree()
        elif level == "Specialization":
            target_spec = None
            target_year = None
            for y in self.config.academic_structure.years:
                for s in y.specializations:
                    if s.spec_id == item_id:
                        target_spec = s
                        target_year = y
                        break
                if target_spec:
                    break
            if not target_spec or not target_year:
                return
            dlg = SpecializationDialog(
                self,
                years=self.config.academic_structure.years,
                spec=target_spec,
                parent_year_id=target_year.year_id,
            )
            self.wait_window(dlg)
            if dlg.result:
                target_yid, updated_spec = dlg.result
                target_year.specializations = [s for s in target_year.specializations if s.spec_id != item_id]
                for y in self.config.academic_structure.years:
                    if y.year_id == target_yid:
                        y.specializations.append(updated_spec)
                        break
                self._refresh_step1_tree()
        elif level == "Base Group":
            specs: List[Tuple[str, str, Specialization]] = []
            target_group = None
            target_spec = None
            for y in self.config.academic_structure.years:
                for s in y.specializations:
                    specs.append((y.year_id, s.spec_id, s))
                    for g in s.groups:
                        if g.group_id == item_id:
                            target_group = g
                            target_spec = s
            if not target_group or not target_spec:
                return
            dlg = BaseGroupDialog(self, specs=specs, group=target_group, parent_spec_id=target_spec.spec_id)
            self.wait_window(dlg)
            if dlg.result:
                target_yid, target_sid, updated_group = dlg.result
                target_spec.groups = [g for g in target_spec.groups if g.group_id != item_id]
                for y in self.config.academic_structure.years:
                    if y.year_id == target_yid:
                        for s in y.specializations:
                            if s.spec_id == target_sid:
                                s.groups.append(updated_group)
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

        bind_tree_double_click(self.tree_rooms, self._on_edit_room)

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

        bind_tree_double_click(self.tree_courses, self._on_edit_course)

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

        dlg = CourseDialog(self, available_years=years, available_groups=groups, available_instructors=insts, available_categories=self.config.categories)
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
            available_categories=self.config.categories,
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

        bind_tree_double_click(self.tree_staff, self._on_edit_staff)

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
        ttk.Button(sg_btn_box, text="Edit Subgroup", command=self._on_edit_subgroup).pack(side=tk.LEFT, padx=2)
        ttk.Button(sg_btn_box, text="Delete Subgroup", command=self._on_delete_subgroup).pack(side=tk.LEFT, padx=2)
        add_help_icon(sg_btn_box, "Student subgroups (e.g. elective tracks or language groups) that draw members from parent groups. The solver ensures overlapping cohorts never clash.").pack(side=tk.RIGHT, padx=4)

        cols_sg = ("ID", "Name", "Headcount", "Parents")
        self.tree_subgroups = ttk.Treeview(left_frame, columns=cols_sg, show="headings", selectmode="browse")
        for c_col in cols_sg:
            self.tree_subgroups.heading(c_col, text=c_col)
        self.tree_subgroups.column("ID", width=80)
        self.tree_subgroups.column("Name", width=120)
        self.tree_subgroups.column("Headcount", width=60, anchor=tk.CENTER)
        self.tree_subgroups.column("Parents", width=100)
        self.tree_subgroups.pack(fill=tk.BOTH, expand=True)
        bind_tree_double_click(self.tree_subgroups, self._on_edit_subgroup)

        # Right: Conflict Rules
        right_frame = ttk.LabelFrame(paned, text="Explicit Collision Prevention Rules", padding="5 5 5 5")
        paned.add(right_frame, weight=1)

        cr_btn_box = ttk.Frame(right_frame)
        cr_btn_box.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(cr_btn_box, text="+ Add Conflict Rule", command=self._on_add_conflict_rule).pack(side=tk.LEFT, padx=2)
        ttk.Button(cr_btn_box, text="Edit Rule", command=self._on_edit_conflict_rule).pack(side=tk.LEFT, padx=2)
        ttk.Button(cr_btn_box, text="Delete Rule", command=self._on_delete_conflict_rule).pack(side=tk.LEFT, padx=2)
        add_help_icon(cr_btn_box, "Pairwise conflict rules enforcing mutual exclusion between two entities (courses or groups) to prevent concurrent scheduling.").pack(side=tk.RIGHT, padx=4)

        cols_cr = ("Rule ID", "Entity A", "Entity B", "Description")
        self.tree_conflicts = ttk.Treeview(right_frame, columns=cols_cr, show="headings", selectmode="browse")
        for c_col in cols_cr:
            self.tree_conflicts.heading(c_col, text=c_col)
        self.tree_conflicts.column("Rule ID", width=100)
        self.tree_conflicts.column("Entity A", width=100)
        self.tree_conflicts.column("Entity B", width=100)
        self.tree_conflicts.column("Description", width=180)
        self.tree_conflicts.pack(fill=tk.BOTH, expand=True)
        bind_tree_double_click(self.tree_conflicts, self._on_edit_conflict_rule)

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

    def _on_edit_subgroup(self) -> None:
        sel = self.tree_subgroups.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a subgroup to edit.", parent=self)
            return
        idx = self.tree_subgroups.index(sel[0])
        if not (0 <= idx < len(self.config.subgroups)):
            return
        all_groups = [g.group_id for g in self.config.academic_structure.all_groups()]
        dlg = SubgroupDialog(self, available_groups=all_groups, subgroup=self.config.subgroups[idx])
        self.wait_window(dlg)
        if dlg.result:
            self.config.subgroups[idx] = dlg.result
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

    def _on_edit_conflict_rule(self) -> None:
        sel = self.tree_conflicts.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a conflict rule to edit.", parent=self)
            return
        idx = self.tree_conflicts.index(sel[0])
        if not (0 <= idx < len(self.config.conflict_rules)):
            return
        dlg = ConflictRuleDialog(self, rule=self.config.conflict_rules[idx])
        self.wait_window(dlg)
        if dlg.result:
            self.config.conflict_rules[idx] = dlg.result
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
            text="Step 6: Time Horizon, Categories, Overlays & Custom Notes",
            font=("Helvetica", 11, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        self.step6_notebook = nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # Tab 1: Scheduling Parameters
        # -------------------------------------------------------------
        card = ttk.Frame(nb, padding="12 12 12 12")
        nb.add(card, text="Scheduling Parameters")

        # Days
        ttk.Label(card, text="Working Days:").grid(row=0, column=0, sticky=tk.W, pady=5)
        days_box = ttk.Frame(card)
        days_box.grid(row=0, column=1, sticky=tk.W, pady=5)
        self.day_vars: Dict[str, tk.BooleanVar] = {}
        for d in VALID_DAYS:
            var = tk.BooleanVar(value=d in self.config.time_horizon.working_days)
            self.day_vars[d] = var
            ttk.Checkbutton(days_box, text=d.capitalize(), variable=var).pack(side=tk.LEFT, padx=4)

        # Time range
        ttk.Label(card, text="Daily Time Range:").grid(row=1, column=0, sticky=tk.W, pady=5)
        tr_box = ttk.Frame(card)
        tr_box.grid(row=1, column=1, sticky=tk.W, pady=5)
        self.day_start_var = tk.StringVar(value=self.config.time_horizon.day_start)
        self.day_end_var = tk.StringVar(value=self.config.time_horizon.day_end)
        ttk.Entry(tr_box, textvariable=self.day_start_var, width=8).pack(side=tk.LEFT)
        ttk.Label(tr_box, text=" to ").pack(side=tk.LEFT)
        ttk.Entry(tr_box, textvariable=self.day_end_var, width=8).pack(side=tk.LEFT)

        # Slot unit
        ttk.Label(card, text="Grid Slot Unit:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.slot_unit_var = tk.StringVar(value=str(self.config.time_horizon.slot_duration_minutes))
        ttk.Combobox(card, textvariable=self.slot_unit_var, values=["15", "30", "45"], width=15).grid(
            row=2, column=1, sticky=tk.W, pady=5
        )

        # Max student daily hours
        lbl_std_frame = ttk.Frame(card)
        lbl_std_frame.grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Label(lbl_std_frame, text="Max Daily Hours / Student:").pack(side=tk.LEFT)
        add_help_icon(lbl_std_frame, "Upper limit on daily academic contact hours for any student group or subgroup.").pack(side=tk.LEFT, padx=3)

        self.max_std_var = tk.StringVar(value=str(self.config.time_horizon.max_daily_hours_per_student))
        ttk.Entry(card, textvariable=self.max_std_var, width=17).grid(row=3, column=1, sticky=tk.W, pady=5)

        # Timeout
        lbl_to_frame = ttk.Frame(card)
        lbl_to_frame.grid(row=4, column=0, sticky=tk.W, pady=5)
        ttk.Label(lbl_to_frame, text="CP-SAT Solver Timeout (s):").pack(side=tk.LEFT)
        add_help_icon(lbl_to_frame, "Maximum wall-clock execution time allowed for the OR-Tools constraint satisfaction solver.").pack(side=tk.LEFT, padx=3)

        self.timeout_var = tk.StringVar(value=str(self.config.time_horizon.solver_timeout_seconds))
        ttk.Entry(card, textvariable=self.timeout_var, width=17).grid(row=4, column=1, sticky=tk.W, pady=5)

        # Default break duration
        lbl_brk_frame = ttk.Frame(card)
        lbl_brk_frame.grid(row=5, column=0, sticky=tk.W, pady=5)
        ttk.Label(lbl_brk_frame, text="Default Class Break (min):").pack(side=tk.LEFT)
        add_help_icon(lbl_brk_frame, "Global minimum transition buffer between consecutive classes unless overridden by course-specific breaks.").pack(side=tk.LEFT, padx=3)
        def_break = getattr(self.config.time_horizon, "default_break_minutes", 15)
        self.default_break_var = tk.StringVar(value=str(def_break))
        ttk.Combobox(card, textvariable=self.default_break_var, values=["0", "5", "10", "15", "20", "30", "45"], width=15).grid(
            row=5, column=1, sticky=tk.W, pady=5
        )

        # Soft objectives
        ttk.Label(card, text="Optimization Objectives:").grid(row=6, column=0, sticky=tk.NW, pady=5)
        obj_box = ttk.Frame(card)
        obj_box.grid(row=6, column=1, sticky=tk.W, pady=5)

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

        # -------------------------------------------------------------
        # Tab 2: Custom Categories & Colors
        # -------------------------------------------------------------
        cat_frame = ttk.Frame(nb, padding="10 10 10 10")
        nb.add(cat_frame, text="Categories & Colors")

        cat_top_bar = ttk.Frame(cat_frame)
        cat_top_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 4))
        ttk.Label(cat_top_bar, text="Subject Visual Categories & Hex Palettes", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)
        add_help_icon(cat_top_bar, "Define colors for course types (e.g. Lectures, Labs). Multi-category subjects render split color striping.").pack(side=tk.LEFT, padx=4)

        cols_cat = ("ID", "Name", "Color", "Description")
        self.cat_tree = ttk.Treeview(cat_frame, columns=cols_cat, show="headings", selectmode="browse")
        for c_col in cols_cat:
            self.cat_tree.heading(c_col, text=c_col)
        self.cat_tree.column("ID", width=90)
        self.cat_tree.column("Name", width=140)
        self.cat_tree.column("Color", width=80)
        self.cat_tree.column("Description", width=200)
        self.cat_tree.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        bind_tree_double_click(self.cat_tree, self._on_edit_category)

        cat_btn_box = ttk.Frame(cat_frame, padding="5 5 0 0")
        cat_btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(cat_btn_box, text="+ Add Category", command=self._on_add_category).pack(side=tk.LEFT, padx=3)
        ttk.Button(cat_btn_box, text="Edit Category", command=self._on_edit_category).pack(side=tk.LEFT, padx=3)
        ttk.Button(cat_btn_box, text="Delete Category", command=self._on_delete_category).pack(side=tk.LEFT, padx=3)

        # -------------------------------------------------------------
        # Tab 3: Background Overlays
        # -------------------------------------------------------------
        ov_frame = ttk.Frame(nb, padding="10 10 10 10")
        nb.add(ov_frame, text="Background Overlays")

        ov_top_bar = ttk.Frame(ov_frame)
        ov_top_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 4))
        ttk.Label(ov_top_bar, text="Global Time Horizon Overlays & Reserved Blocks", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)
        add_help_icon(ov_top_bar, "Global events (Dean's hours, Rector's hours, maintenance windows) displayed with custom colors and hatching patterns in timetable and PDF legend.").pack(side=tk.LEFT, padx=4)

        cols_ov = ("ID", "Label", "Day", "Hours", "Color", "Opacity", "Pattern", "Description")
        self.ov_tree = ttk.Treeview(ov_frame, columns=cols_ov, show="headings", selectmode="browse")
        for c_col in cols_ov:
            self.ov_tree.heading(c_col, text=c_col)
        self.ov_tree.column("ID", width=70)
        self.ov_tree.column("Label", width=130)
        self.ov_tree.column("Day", width=80)
        self.ov_tree.column("Hours", width=90)
        self.ov_tree.column("Color", width=70)
        self.ov_tree.column("Opacity", width=60)
        self.ov_tree.column("Pattern", width=70)
        self.ov_tree.column("Description", width=180)
        self.ov_tree.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        bind_tree_double_click(self.ov_tree, self._on_edit_overlay)

        ov_btn_box = ttk.Frame(ov_frame, padding="5 5 0 0")
        ov_btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(ov_btn_box, text="+ Add Overlay", command=self._on_add_overlay).pack(side=tk.LEFT, padx=3)
        ttk.Button(ov_btn_box, text="Edit Overlay", command=self._on_edit_overlay).pack(side=tk.LEFT, padx=3)
        ttk.Button(ov_btn_box, text="Delete Overlay", command=self._on_delete_overlay).pack(side=tk.LEFT, padx=3)

        # -------------------------------------------------------------
        # Tab 4: Configurable Canvas Footer & Notes
        # -------------------------------------------------------------
        notes_frame = ttk.Frame(nb, padding="10 10 10 10")
        nb.add(notes_frame, text="Footer & Canvas Notes")

        # Top Footer Fields Box
        f_box = ttk.LabelFrame(notes_frame, text="Configurable Canvas Footer Elements (Zero Hardcoding)", padding="10 8 10 8")
        f_box.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        ttk.Label(f_box, text="Campus / Facility Note:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.campus_loc_var = tk.StringVar(value=self.config.campus_location_note or "")
        ttk.Entry(f_box, textvariable=self.campus_loc_var, width=54).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(4, 0))

        ttk.Label(f_box, text="Dean / Rector Hours Note:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.deans_hours_note_var = tk.StringVar(value=self.config.dean_hours_note or "")
        ttk.Entry(f_box, textvariable=self.deans_hours_note_var, width=54).grid(row=1, column=1, sticky=tk.W, pady=3, padx=(4, 0))

        ttk.Label(f_box, text="Author Signature Label:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.author_sig_var = tk.StringVar(value=self.config.author_signature or "")
        ttk.Entry(f_box, textvariable=self.author_sig_var, width=54).grid(row=2, column=1, sticky=tk.W, pady=3, padx=(4, 0))

        # Bottom Treeview for free-form custom notes / remarks
        n_box = ttk.LabelFrame(notes_frame, text="General Remarks & Canvas Notes", padding="10 8 10 8")
        n_box.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        self.notes_tree = ttk.Treeview(n_box, columns=("Note",), show="headings", selectmode="browse")
        self.notes_tree.heading("Note", text="Canvas Note / General Remark")
        self.notes_tree.column("Note", width=550)
        self.notes_tree.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        notes_btn_box = ttk.Frame(n_box, padding="5 5 0 0")
        notes_btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(notes_btn_box, text="+ Add Note", command=self._on_add_note).pack(side=tk.LEFT, padx=3)
        ttk.Button(notes_btn_box, text="Edit Note", command=self._on_edit_note).pack(side=tk.LEFT, padx=3)
        ttk.Button(notes_btn_box, text="Delete Note", command=self._on_delete_note).pack(side=tk.LEFT, padx=3)
        bind_tree_double_click(self.notes_tree, self._on_edit_note)

    def _refresh_step6_categories(self) -> None:
        if not hasattr(self, "cat_tree"):
            return
        for item in self.cat_tree.get_children():
            self.cat_tree.delete(item)
        for idx, cat in enumerate(self.config.categories):
            self.cat_tree.insert("", tk.END, iid=str(idx), values=(cat.category_id, cat.name, cat.color, cat.description or ""))

    def _on_add_category(self) -> None:
        dlg = CategoryDialog(self, title="Add Visual Category")
        self.wait_window(dlg)
        if dlg.result:
            self.config.categories.append(dlg.result)
            self._refresh_step6_categories()

    def _on_edit_category(self) -> None:
        sel = self.cat_tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a category to edit.", parent=self)
            return
        idx = int(sel[0])
        cat = self.config.categories[idx]
        dlg = CategoryDialog(self, title="Edit Category", category=cat)
        self.wait_window(dlg)
        if dlg.result:
            self.config.categories[idx] = dlg.result
            self._refresh_step6_categories()

    def _on_delete_category(self) -> None:
        sel = self.cat_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.categories[idx]
        self._refresh_step6_categories()

    def _refresh_step6_overlays(self) -> None:
        if not hasattr(self, "ov_tree"):
            return
        for item in self.ov_tree.get_children():
            self.ov_tree.delete(item)
        for idx, ov in enumerate(self.config.background_overlays):
            hours_str = f"{ov.start_time}-{ov.end_time}"
            self.ov_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    ov.overlay_id,
                    ov.label,
                    ov.day.capitalize(),
                    hours_str,
                    ov.color,
                    ov.opacity,
                    ov.pattern,
                    ov.description or "",
                ),
            )

    def _on_add_overlay(self) -> None:
        dlg = OverlayDialog(self, title="Add Background Overlay")
        self.wait_window(dlg)
        if dlg.result:
            self.config.background_overlays.append(dlg.result)
            self._refresh_step6_overlays()

    def _on_edit_overlay(self) -> None:
        sel = self.ov_tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select an overlay to edit.", parent=self)
            return
        idx = int(sel[0])
        ov = self.config.background_overlays[idx]
        dlg = OverlayDialog(self, title="Edit Overlay", overlay=ov)
        self.wait_window(dlg)
        if dlg.result:
            self.config.background_overlays[idx] = dlg.result
            self._refresh_step6_overlays()

    def _on_delete_overlay(self) -> None:
        sel = self.ov_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.background_overlays[idx]
        self._refresh_step6_overlays()

    def _refresh_step6_notes(self) -> None:
        if not hasattr(self, "notes_tree"):
            return
        for item in self.notes_tree.get_children():
            self.notes_tree.delete(item)
        for idx, note in enumerate(self.config.custom_notes):
            self.notes_tree.insert("", tk.END, iid=str(idx), values=(note,))

    def _on_add_note(self) -> None:
        dlg = CustomNoteDialog(self, title="Add Canvas Note")
        self.wait_window(dlg)
        if dlg.result:
            self.config.custom_notes.append(dlg.result)
            self._refresh_step6_notes()

    def _on_edit_note(self) -> None:
        sel = self.notes_tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a note to edit.", parent=self)
            return
        idx = int(sel[0])
        initial = self.config.custom_notes[idx]
        dlg = CustomNoteDialog(self, title="Edit Canvas Note", initial_text=initial)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.config.custom_notes[idx] = dlg.result
            self._refresh_step6_notes()

    def _on_delete_note(self) -> None:
        sel = self.notes_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.config.custom_notes[idx]
        self._refresh_step6_notes()

    def _refresh_step6(self) -> None:
        self._refresh_step6_categories()
        self._refresh_step6_overlays()
        self._refresh_step6_notes()

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

        if hasattr(self, "campus_loc_var"):
            self.config.campus_location_note = self.campus_loc_var.get().strip() or None
        if hasattr(self, "deans_hours_note_var"):
            self.config.dean_hours_note = self.deans_hours_note_var.get().strip() or None
        if hasattr(self, "author_sig_var"):
            self.config.author_signature = self.author_sig_var.get().strip() or None

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
        if hasattr(self, "campus_loc_var"):
            self.campus_loc_var.set(self.config.campus_location_note or "")
        if hasattr(self, "deans_hours_note_var"):
            self.deans_hours_note_var.set(self.config.dean_hours_note or "")
        if hasattr(self, "author_sig_var"):
            self.author_sig_var.set(self.config.author_signature or "")

    def _on_save_project(self) -> None:
        self._sync_step6_settings()
        dest = filedialog.asksaveasfilename(
            title="Save Timetable Project Draft",
            defaultextension=".schedproj",
            filetypes=[("Timetable Project", "*.schedproj"), ("JSON files", "*.json"), ("All files", "*.*")],
            parent=self,
        )
        if dest:
            proj = ScheduleProject(
                name=Path(dest).stem,
                config=self.config,
            )
            save_project(proj, dest)
            messagebox.showinfo("Project Saved", f"Saved project draft to:\n{dest}", parent=self)

    def _on_load_project(self) -> None:
        src = filedialog.askopenfilename(
            title="Load Timetable Project",
            filetypes=[("Timetable Project", "*.schedproj"), ("JSON files", "*.json"), ("All files", "*.*")],
            parent=self,
        )
        if src:
            try:
                proj = load_project(src)
                if proj.config:
                    self.config = proj.config
                    self._refresh_step1_tree()
                    self._refresh_step2_tree()
                    self._refresh_step3_tree()
                    self._refresh_step4_tree()
                    self._refresh_step5()
                    self._sync_step6_from_config()
                    self._refresh_step6()
                    self._show_step(1)
                    messagebox.showinfo("Project Loaded", f"Loaded project config from:\n{src}", parent=self)
                if proj.timetable and self.on_solve_complete:
                    self.on_solve_complete(proj.timetable, None)
            except Exception as e:
                messagebox.showerror("Project Load Error", f"Failed to load project:\n{e}", parent=self)

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

        # Forward footer notes to generated timetables
        if result.is_success and result.student_timetables:
            for tt in result.student_timetables.values():
                if tt.layout and tt.layout.footer:
                    tt.layout.footer.campus_location_note = self.config.campus_location_note
                    tt.layout.footer.dean_hours_note = self.config.dean_hours_note
                    tt.layout.footer.author_signature = self.config.author_signature
                    tt.layout.footer.general_notes = list(self.config.general_notes)
                    tt.layout.custom_notes = list(self.config.custom_notes)
                    tt.layout.categories = list(self.config.categories)
                    tt.layout.custom_overlays = list(self.config.background_overlays)

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
        self.baseline_timetable: Optional[Timetable] = copy.deepcopy(timetable) if timetable else None

        self.root = tk.Tk()
        self.root.title("UWM Better Schedule — Academic Timetable Suite")

        # Dynamic Auto-Scaling Window Geometry based on active screen metrics
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_w = max(1400, int(screen_w * 0.80))
        target_h = max(850, int(screen_h * 0.82))
        target_w = min(target_w, screen_w)
        target_h = min(target_h, screen_h)
        x_offset = max(0, (screen_w - target_w) // 2)
        y_offset = max(0, (screen_h - target_h) // 2)
        self.root.geometry(f"{target_w}x{target_h}+{x_offset}+{y_offset}")
        self.root.minsize(1200, 750)

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

        ttk.Separator(mode_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.btn_save_proj = ttk.Button(
            mode_frame,
            text="💾 Save Project (.schedproj)",
            command=self._on_save_project,
        )
        self.btn_save_proj.pack(side=tk.LEFT, padx=2)

        self.btn_load_proj = ttk.Button(
            mode_frame,
            text="📂 Load Project...",
            command=self._on_load_project,
        )
        self.btn_load_proj.pack(side=tk.LEFT, padx=2)

        self.btn_diff = ttk.Button(
            mode_frame,
            text="🔄 Compare Diff",
            command=self._on_compare_diff,
        )
        self.btn_diff.pack(side=tk.LEFT, padx=2)

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

            bind_tree_double_click(tree, lambda d=day: self._on_edit_slot(d))
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
        self.baseline_timetable = copy.deepcopy(timetable)
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

        # 5. Project management shortcuts
        self.root.bind("<Control-Shift-s>", lambda e: self._on_key_save_proj(e))
        self.root.bind("<Control-Shift-S>", lambda e: self._on_key_save_proj(e))
        self.root.bind("<Control-Shift-o>", lambda e: self._on_key_load_proj(e))
        self.root.bind("<Control-Shift-O>", lambda e: self._on_key_load_proj(e))
        self.root.bind("<Control-d>", lambda e: self._on_key_diff(e))
        self.root.bind("<Control-D>", lambda e: self._on_key_diff(e))

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

    def _on_key_save_proj(self, event: Optional[tk.Event] = None) -> str:
        self._on_save_project()
        return "break"

    def _on_key_load_proj(self, event: Optional[tk.Event] = None) -> str:
        self._on_load_project()
        return "break"

    def _on_key_diff(self, event: Optional[tk.Event] = None) -> str:
        self._on_compare_diff()
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
            self.baseline_timetable = copy.deepcopy(self.timetable)

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

        tree.tag_configure("modified", background="#FFF3CD")
        entries = self.timetable.get_entries(day)
        for idx, e in enumerate(entries):
            grp_text = str(e.group) if e.group is not None else "All"
            notes_text = e.notes or ""
            if e.is_modified and "[MOD]" not in notes_text:
                notes_text = f"[MOD] {notes_text}".strip()
            tags = ()
            if e.is_modified:
                tags = ("modified",)
            elif e.colors:
                col_hex = e.colors[0]
                tag_name = f"col_{col_hex.lstrip('#')}"
                tree.tag_configure(tag_name, background=col_hex)
                tags = (tag_name,)
            tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(e.hours, e.subject, e.academic_instructor, e.room, e.type, grp_text, notes_text),
                tags=tags,
            )

    def _refresh_all_tables(self) -> None:
        for day in VALID_DAYS:
            self._refresh_day_table(day)

    def _on_add_slot(self, day: str) -> None:
        if self.timetable is None:
            messagebox.showinfo("No File Loaded", "Please load a PDF timetable first.", parent=self.root)
            return

        cats = self.timetable.layout.categories if (self.timetable and self.timetable.layout) else []
        dlg = SlotDialog(self.root, title=f"Add Class Slot ({day.capitalize()})", initial_day=day, available_categories=cats)
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

        cats = self.timetable.layout.categories if (self.timetable and self.timetable.layout) else []
        dlg = SlotDialog(self.root, title=f"Edit Slot #{idx} ({day.capitalize()})", initial_day=day, entry=entry, available_categories=cats)
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
            if hasattr(self, "wizard_frame"):
                cfg = self.wizard_frame.config
                if cfg.categories and not self.timetable.layout.categories:
                    self.timetable.layout.categories = list(cfg.categories)
                if cfg.custom_overlays and not self.timetable.layout.custom_overlays:
                    self.timetable.layout.custom_overlays = list(cfg.custom_overlays)
                if cfg.custom_notes and not self.timetable.layout.custom_notes:
                    self.timetable.layout.custom_notes = list(cfg.custom_notes)
                if cfg.campus_location_note:
                    self.timetable.layout.footer.campus_location_note = cfg.campus_location_note
                if cfg.dean_hours_note:
                    self.timetable.layout.footer.dean_hours_note = cfg.dean_hours_note
                if cfg.author_signature:
                    self.timetable.layout.footer.author_signature = cfg.author_signature
                if cfg.general_notes:
                    self.timetable.layout.footer.general_notes = list(cfg.general_notes)

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

    def _on_save_project(self) -> None:
        """Save complete project workspace (.schedproj / JSON)."""
        self.wizard_frame._sync_step6_settings()
        dest = filedialog.asksaveasfilename(
            title="Save Timetable Project Workspace",
            defaultextension=".schedproj",
            filetypes=[
                ("Timetable Project files", "*.schedproj"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
            parent=self.root,
        )
        if not dest:
            return

        if self.timetable:
            if self.wizard_frame.config.categories and not self.timetable.layout.categories:
                self.timetable.layout.categories = list(self.wizard_frame.config.categories)
            if self.wizard_frame.config.custom_overlays and not self.timetable.layout.custom_overlays:
                self.timetable.layout.custom_overlays = list(self.wizard_frame.config.custom_overlays)
            if self.wizard_frame.config.custom_notes and not self.timetable.layout.custom_notes:
                self.timetable.layout.custom_notes = list(self.wizard_frame.config.custom_notes)

        proj = ScheduleProject(
            name=Path(dest).stem,
            config=self.wizard_frame.config,
            timetable=self.timetable,
            baseline_timetable=self.baseline_timetable,
        )
        try:
            save_project(proj, dest)
            self.is_modified = False
            self.status_var.set(f"Project saved successfully to {Path(dest).name}")
            messagebox.showinfo("Project Saved", f"Project saved successfully to:\n{dest}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Save Project Error", f"Failed to save project:\n{e}", parent=self.root)

    def _on_load_project(self) -> None:
        """Load complete project workspace (.schedproj / JSON)."""
        if self.is_modified:
            resp = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved modifications. Save before opening another project?",
                parent=self.root,
            )
            if resp is None:
                return
            if resp is True:
                self._on_save_project()

        src = filedialog.askopenfilename(
            title="Load Timetable Project Workspace",
            filetypes=[
                ("Timetable Project files", "*.schedproj"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
            parent=self.root,
        )
        if not src:
            return

        try:
            proj = load_project(src)
            if proj.config:
                self.wizard_frame.config = proj.config
                self.wizard_frame._refresh_step1_tree()
                self.wizard_frame._refresh_step2_tree()
                self.wizard_frame._refresh_step3_tree()
                self.wizard_frame._refresh_step4_tree()
                self.wizard_frame._refresh_step5()
                self.wizard_frame._sync_step6_from_config()
                self.wizard_frame._refresh_step6()

            if proj.timetable:
                self.timetable = proj.timetable
                self.baseline_timetable = proj.baseline_timetable or copy.deepcopy(proj.timetable)
                self._refresh_all_tables()
                self.file_path_var.set(str(src))
                self.set_mode("edit")
                self.status_var.set(f"Loaded project '{Path(src).name}' with {self.timetable.count_total_entries()} slots.")
            else:
                self.set_mode("create")
                self.status_var.set(f"Loaded project configuration '{Path(src).name}'.")

            self.is_modified = False
            messagebox.showinfo("Project Loaded", f"Successfully loaded project:\n{src}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Load Project Error", f"Failed to load project:\n{e}", parent=self.root)

    def _on_compare_diff(self) -> None:
        """Compare current schedule against baseline and visually highlight changes."""
        if self.timetable is None:
            messagebox.showwarning(
                "No Timetable",
                "Please load a timetable or project first to compare differences.",
                parent=self.root,
            )
            return

        baseline = self.baseline_timetable
        if baseline is None:
            choose = messagebox.askyesno(
                "Baseline Required",
                "No active baseline snapshot found in memory.\nWould you like to select a baseline project/file (.schedproj or .json) to compare against?",
                parent=self.root,
            )
            if not choose:
                return
            src = filedialog.askopenfilename(
                title="Select Baseline Timetable or Project",
                filetypes=[
                    ("Timetable files", "*.schedproj;*.json"),
                    ("All files", "*.*"),
                ],
                parent=self.root,
            )
            if not src:
                return
            try:
                if str(src).endswith(".schedproj"):
                    p = load_project(src)
                    baseline = p.timetable
                else:
                    data = json.loads(Path(src).read_text(encoding="utf-8"))
                    if "config" in data and ("timetable" in data or "name" in data):
                        p = load_project(src)
                        baseline = p.timetable
                    else:
                        baseline = Timetable.from_json(Path(src).read_text(encoding="utf-8"))
                if baseline is None:
                    messagebox.showerror("Diff Error", "The selected file does not contain a timetable schedule.", parent=self.root)
                    return
                self.baseline_timetable = baseline
            except Exception as e:
                messagebox.showerror("Diff Load Error", f"Failed to load baseline file:\n{e}", parent=self.root)
                return

        diff_tt, changes = compute_timetable_diff(baseline, self.timetable)
        if not changes:
            messagebox.showinfo("Diff Result", "Zero differences detected between current schedule and baseline state.", parent=self.root)
            return

        self.timetable = diff_tt
        self.is_modified = True
        self._refresh_all_tables()

        summary_lines = [f"Found {len(changes)} modification(s) against baseline:"]
        for chg in changes[:10]:
            t = chg["type"].upper()
            d = chg["day"].capitalize()
            desc = chg.get("description", "")
            summary_lines.append(f"• [{t}] {d}: {desc}")
        if len(changes) > 10:
            summary_lines.append(f"... and {len(changes) - 10} more.")
        summary_lines.append("\nModified cells have been marked with multi-color visual split (#E67E22) and audit footnote added.")

        self.status_var.set(f"Diff applied: {len(changes)} modified slots highlighted.")
        messagebox.showinfo("Diff Changes Detected", "\n".join(summary_lines), parent=self.root)

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

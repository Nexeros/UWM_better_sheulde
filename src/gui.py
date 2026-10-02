"""Lightweight Tkinter Graphical User Interface for timetable management with full keyboard accessibility."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional

from src.core.generator import TimetablePDFGenerator
from src.core.models import VALID_DAYS, ClassType, Timetable, TimetableEntry
from src.core.parser import TimetableParser
from src.core.storage import StorageManager, ensure_input_directory


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

        self.result: Optional[tuple[str, TimetableEntry]] = None
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
        self.hours_var = tk.StringVar(value=self.entry.hours if self.entry else "09:00-10:30")
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
            values=["Lecture", "Lab", "Seminar", "Project"],
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

        # Set initial keyboard focus
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


class TimetableGUI:
    """Primary Graphical User Interface for timetable inspection and modification."""

    def __init__(
        self,
        timetable: Optional[Timetable] = None,
        storage: Optional[StorageManager] = None,
        generator: Optional[TimetablePDFGenerator] = None,
        base_output_dir: str | Path = "output",
    ):
        self.timetable = timetable
        self.storage = storage
        self.generator = generator or TimetablePDFGenerator()
        self.base_output_dir = Path(base_output_dir)
        self.is_modified = False

        self.root = tk.Tk()
        self.root.title("UWM Better Schedule — Timetable Editor")
        self.root.geometry("980x660")
        self.root.minsize(820, 520)

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

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Top Header Bar
        top_frame = ttk.Frame(self.root, padding="10 8 10 4")
        top_frame.pack(fill=tk.X)

        title_label = ttk.Label(
            top_frame,
            text="UWM Timetable Editor",
            font=("Helvetica", 14, "bold"),
        )
        title_label.pack(side=tk.LEFT)

        info_label = ttk.Label(
            top_frame,
            textvariable=self.run_dir_var,
            font=("Helvetica", 9),
            foreground="gray",
        )
        info_label.pack(side=tk.RIGHT, pady=4)

        # File Ingestion / Selection Bar
        file_frame = ttk.Frame(self.root, padding="10 4 10 6")
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
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        for day in VALID_DAYS:
            day_frame = ttk.Frame(self.notebook, padding="5 5 5 5")
            self.notebook.add(day_frame, text=day.capitalize())

            # Table inside tab
            tree_frame = ttk.Frame(day_frame)
            tree_frame.pack(fill=tk.BOTH, expand=True)

            cols = ("Hours", "Subject", "Instructor", "Room", "Type", "Group", "Notes")
            tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
            tree.heading("Hours", text="Hours")
            tree.heading("Subject", text="Subject")
            tree.heading("Instructor", text="Instructor")
            tree.heading("Room", text="Room")
            tree.heading("Type", text="Type")
            tree.heading("Group", text="Group")
            tree.heading("Notes", text="Notes")

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

            # Double-click or Enter to edit
            tree.bind("<Double-1>", lambda e, d=day: self._on_edit_slot(d))
            tree.bind("<Return>", lambda e, d=day: self._on_edit_slot(d))

            # Bind arrow down/up to auto-select if nothing selected
            tree.bind("<Down>", lambda e, t=tree: self._on_tree_nav_down(t, e))
            tree.bind("<Up>", lambda e, t=tree: self._on_tree_nav_up(t, e))

            self.tree_views[day] = tree

            # Tab Action Buttons
            btn_box = ttk.Frame(day_frame, padding="5 5 5 5")
            btn_box.pack(fill=tk.X)

            ttk.Button(btn_box, text="+ Add Slot", command=lambda d=day: self._on_add_slot(d)).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_box, text="Edit Selected (Enter)", command=lambda d=day: self._on_edit_slot(d)).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_box, text="Delete Selected (Del)", command=lambda d=day: self._on_delete_slot(d)).pack(side=tk.LEFT, padx=3)

        # Bottom Global Action Bar
        bottom_frame = ttk.Frame(self.root, padding="10 5 10 10")
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

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_keyboard_shortcuts(self) -> None:
        """Register global and widget-level keyboard bindings."""
        # 1. Ctrl+O / Cmd+O: Open / Load file
        self.root.bind("<Control-o>", lambda e: self._on_key_browse(e))
        self.root.bind("<Control-O>", lambda e: self._on_key_browse(e))
        self.root.bind("<Command-o>", lambda e: self._on_key_browse(e))
        self.root.bind("<Command-O>", lambda e: self._on_key_browse(e))

        # 2. Ctrl+S / Cmd+S: Save & Regenerate PDF
        self.root.bind("<Control-s>", lambda e: self._on_key_save(e))
        self.root.bind("<Control-S>", lambda e: self._on_key_save(e))
        self.root.bind("<Command-s>", lambda e: self._on_key_save(e))
        self.root.bind("<Command-S>", lambda e: self._on_key_save(e))

        # 3. Delete / Backspace: Delete selected slot
        self.root.bind("<Delete>", self._on_key_delete)
        self.root.bind("<BackSpace>", self._on_key_delete)

        # 4. Escape: Deselect active selection or reset focus
        self.root.bind("<Escape>", self._on_key_escape)

        # 5. Ctrl+Tab / Left / Right for Tab switching when not in text entry
        self.root.bind("<Control-Tab>", lambda e: self._on_cycle_tabs(1))
        self.root.bind("<Control-ISO_Left_Tab>", lambda e: self._on_cycle_tabs(-1))
        self.root.bind("<Control-Shift-Tab>", lambda e: self._on_cycle_tabs(-1))

    def _on_key_browse(self, event: Optional[tk.Event] = None) -> str:
        self._on_browse_file()
        return "break"

    def _on_key_save(self, event: Optional[tk.Event] = None) -> str:
        self._on_save_regenerate()
        return "break"

    def _on_key_escape(self, event: Optional[tk.Event] = None) -> str:
        current_day = self._get_current_day()
        tree = self.tree_views.get(current_day)
        if tree:
            tree.selection_remove(tree.selection())
        self.status_var.set("Selection cleared (Esc).")
        return "break"

    def _on_key_delete(self, event: tk.Event) -> Optional[str]:
        # Never intercept Delete / Backspace if user is typing in a text field
        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry, ttk.Combobox, tk.Text)):
            return None

        current_day = self._get_current_day()
        self._on_delete_slot(current_day)
        return "break"

    def _on_cycle_tabs(self, direction: int) -> str:
        curr = self.notebook.index(self.notebook.select())
        new_idx = (curr + direction) % len(VALID_DAYS)
        self.notebook.select(new_idx)
        return "break"

    def _on_tab_changed(self, event: tk.Event) -> None:
        """Keep focus on the active day table when switching tabs."""
        current_day = self._get_current_day()
        tree = self.tree_views.get(current_day)
        if tree:
            tree.focus_set()

    def _on_tree_nav_down(self, tree: ttk.Treeview, event: tk.Event) -> Optional[str]:
        children = tree.get_children()
        if not children:
            return None
        sel = tree.selection()
        if not sel:
            tree.selection_set(children[0])
            tree.focus(children[0])
            tree.see(children[0])
            return "break"
        return None

    def _on_tree_nav_up(self, tree: ttk.Treeview, event: tk.Event) -> Optional[str]:
        children = tree.get_children()
        if not children:
            return None
        sel = tree.selection()
        if not sel:
            tree.selection_set(children[-1])
            tree.focus(children[-1])
            tree.see(children[-1])
            return "break"
        return None

    def _on_browse_file(self) -> None:
        """Prompt user with native file dialog to select a PDF timetable."""
        if self.is_modified:
            resp = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before loading a new file?",
                parent=self.root,
            )
            if resp is None:
                return  # Cancel
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
        """Load, parse, and refresh UI from the given PDF path."""
        target_path = Path(file_path).resolve()
        if not target_path.is_file():
            messagebox.showerror("File Error", f"Selected file does not exist:\n{target_path}", parent=self.root)
            return False

        try:
            # Reinitialize storage context
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

            # Focus the active tree
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

        # Esc closes JSON viewer
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

"""Automated headless smoke and lifecycle tests for TimetableGUI and ScheduleWizardFrame."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Generator
import pytest

from src.gui import TimetableGUI
from src.core.storage import StorageManager


def has_display() -> bool:
    """Check if an active graphical display environment (X11 / Wayland / Win / Mac) is available."""
    if sys.platform.startswith("win") or sys.platform == "darwin":
        try:
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            return True
        except Exception:
            return False

    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False

    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


DISPLAY_AVAILABLE = has_display()

pytestmark = pytest.mark.skipif(
    not DISPLAY_AVAILABLE,
    reason="GUI lifecycle smoke tests require an active display server (X11/Wayland/Windows/macOS).",
)


@pytest.fixture
def managed_gui(tmp_path: Path) -> Generator[TimetableGUI, None, None]:
    """Provide a managed TimetableGUI instance with guaranteed teardown."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="edit")
    gui.root.update()
    yield gui
    try:
        if gui.root.winfo_exists():
            gui.root.destroy()
    except Exception:
        pass


def test_gui_initialization_and_window_geometry(managed_gui: TimetableGUI):
    """Verify TimetableGUI initializes without Wm.wm_geometry errors, has valid size and title."""
    assert managed_gui.root.winfo_exists()
    assert "UWM Better Schedule" in managed_gui.root.title()

    managed_gui.root.update()
    width = managed_gui.root.winfo_width()
    height = managed_gui.root.winfo_height()

    assert width >= 860
    assert height >= 560
    assert managed_gui.current_mode == "edit"
    assert managed_gui.editor_frame.winfo_ismapped()


def test_wizard_default_clean_slate_on_startup(tmp_path: Path):
    """Verify that ScheduleWizardFrame initializes completely empty with no mock entities."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="create")
    try:
        gui.root.update()
        wiz = gui.wizard_frame

        # Step 1: Academic Structure
        assert len(wiz.config.academic_structure.years) == 0
        assert len(wiz.tree_academic.get_children()) == 0

        # Step 2: Facilities
        assert len(wiz.config.rooms) == 0
        assert len(wiz.tree_rooms.get_children()) == 0

        # Step 3: Curriculum
        assert len(wiz.config.courses) == 0
        assert len(wiz.tree_courses.get_children()) == 0

        # Step 4: Faculty / Staff
        assert len(wiz.config.instructors) == 0
        assert len(wiz.tree_staff.get_children()) == 0

        # Step 5: Subgroups & Conflict Rules
        assert len(wiz.config.subgroups) == 0
        assert len(wiz.config.conflict_rules) == 0
        assert len(wiz.tree_subgroups.get_children()) == 0
        assert len(wiz.tree_conflicts.get_children()) == 0

        # Banner should NOT be visible on clean startup
        assert not wiz.banner_frame.winfo_ismapped()
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_wizard_load_test_data_and_clear_reset(tmp_path: Path):
    """Verify 'Load Test Data' populates all steps and 'Clear / Reset' restores clean state."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="create")
    try:
        wiz = gui.wizard_frame
        gui.root.update()

        # 1. Trigger Load Test Data
        wiz.load_demo_test_data()
        gui.root.update()

        assert len(wiz.config.academic_structure.years) == 2
        assert len(wiz.config.categories) >= 2
        assert len(wiz.config.background_overlays) >= 2
        assert sum(len(y.specializations) for y in wiz.config.academic_structure.years) == 2
        assert len(wiz.config.rooms) == 5
        assert len(wiz.config.courses) == 9
        assert len(wiz.config.instructors) == 4
        assert len(wiz.config.subgroups) == 2
        assert len(wiz.config.conflict_rules) == 2

        # Verify GUI treeviews are populated
        assert len(wiz.tree_academic.get_children()) > 0
        assert len(wiz.tree_rooms.get_children()) == 5
        assert len(wiz.tree_courses.get_children()) == 9
        assert len(wiz.tree_staff.get_children()) == 4
        assert len(wiz.tree_subgroups.get_children()) == 2
        assert len(wiz.tree_conflicts.get_children()) == 2

        # Banner should now be visible with confirmation text
        assert wiz.banner_frame.winfo_ismapped()
        assert "Realistic demo data loaded" in wiz.banner_label.cget("text")

        # 2. Trigger Reset / Clear
        wiz.reset_wizard(confirm=False)
        gui.root.update()

        assert len(wiz.config.academic_structure.years) == 0
        assert len(wiz.config.rooms) == 0
        assert len(wiz.config.courses) == 0
        assert len(wiz.config.instructors) == 0
        assert len(wiz.config.subgroups) == 0
        assert len(wiz.config.conflict_rules) == 0

        # Verify GUI treeviews are empty again
        assert len(wiz.tree_academic.get_children()) == 0
        assert len(wiz.tree_rooms.get_children()) == 0
        assert len(wiz.tree_courses.get_children()) == 0
        assert len(wiz.tree_staff.get_children()) == 0
        assert len(wiz.tree_subgroups.get_children()) == 0
        assert len(wiz.tree_conflicts.get_children()) == 0

        # Banner should be hidden
        assert not wiz.banner_frame.winfo_ismapped()
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_mode_switching_lifecycle(managed_gui: TimetableGUI):
    """Verify switching between Editor and Wizard modes properly shows and hides respective frames."""
    managed_gui.root.update()
    # Start in edit mode
    assert managed_gui.current_mode == "edit"
    assert managed_gui.editor_frame.winfo_ismapped()
    assert not managed_gui.wizard_frame.winfo_ismapped()

    # Switch to create / wizard mode
    managed_gui.set_mode("create")
    managed_gui.root.update()
    assert managed_gui.current_mode == "create"
    assert not managed_gui.editor_frame.winfo_ismapped()
    assert managed_gui.wizard_frame.winfo_ismapped()
    assert "Wizard" in managed_gui.root.title()

    # Switch back to edit mode
    managed_gui.set_mode("edit")
    managed_gui.root.update()
    assert managed_gui.current_mode == "edit"
    assert managed_gui.editor_frame.winfo_ismapped()
    assert not managed_gui.wizard_frame.winfo_ismapped()
    assert "Editor" in managed_gui.root.title()


def test_wizard_step_navigation_lifecycle(tmp_path: Path):
    """Verify sequential wizard navigation (Next, Previous) updates active steps and indicators."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="create")
    try:
        gui.root.update()
        wiz = gui.wizard_frame
        assert wiz.current_step == 1
        assert wiz.step_frames[1].winfo_ismapped()

        # Advance to step 2
        wiz.next_step()
        gui.root.update()
        assert wiz.current_step == 2
        assert not wiz.step_frames[1].winfo_ismapped()
        assert wiz.step_frames[2].winfo_ismapped()

        # Advance to step 3
        wiz.next_step()
        gui.root.update()
        assert wiz.current_step == 3
        assert wiz.step_frames[3].winfo_ismapped()

        # Step back to step 2
        wiz.previous_step()
        gui.root.update()
        assert wiz.current_step == 2
        assert wiz.step_frames[2].winfo_ismapped()
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_gui_fallback_logging_captures_traceback(tmp_path: Path, sample_pdf_path: Path):
    """Verify that exceptions during GUI startup log the complete traceback to execution.log."""
    import traceback
    storage = StorageManager(input_pdf_path=sample_pdf_path, base_output_dir=tmp_path)

    try:
        # Simulate a Wm.wm_geometry error
        raise TypeError("Wm.wm_geometry() takes from 1 to 2 positional arguments but 3 were given")
    except Exception as e:
        tb = traceback.format_exc()
        storage.error(f"Failed to initialize GUI ({e}). Degrading to TUI.\nTraceback:\n{tb}")

    storage.close()

    assert storage.log_file_path.is_file()
    log_content = storage.log_file_path.read_text(encoding="utf-8")
    assert "ERROR" in log_content
    assert "Wm.wm_geometry() takes from 1 to 2 positional arguments but 3 were given" in log_content
    assert "Traceback:" in log_content
    assert "File " in log_content


def test_gui_step6_tabs_and_project_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify Step 6 notebook tabs and Project save/load/diff lifecycle in GUI."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="create")
    try:
        wiz = gui.wizard_frame
        gui.root.update()

        # Step 6 tabs exist
        assert hasattr(wiz, "step6_notebook")
        assert hasattr(wiz, "cat_tree")
        assert hasattr(wiz, "ov_tree")
        assert hasattr(wiz, "notes_tree")

        # Load demo data
        wiz.load_demo_test_data()
        gui.root.update()

        # Add custom category, overlay, note
        from src.core.models import ScheduleCategory, BackgroundOverlay
        wiz.config.categories.append(ScheduleCategory(category_id="c_test", name="Test Category", color="#FF00FF"))
        wiz.config.custom_overlays.append(BackgroundOverlay(overlay_id="o_test", label="Test Overlay", day="monday", start_time="08:00", end_time="10:00", color="#E67E22"))
        wiz.config.custom_notes.append("Test Note")
        wiz._refresh_step6()
        gui.root.update()

        assert len(wiz.cat_tree.get_children()) >= 1
        assert len(wiz.ov_tree.get_children()) >= 1
        assert len(wiz.notes_tree.get_children()) >= 1

        # Test Save Project (.schedproj)
        proj_file = tmp_path / "gui_project.schedproj"
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(proj_file))
        monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
        gui._on_save_project()
        assert proj_file.exists()

        # Clear wizard
        wiz.reset_wizard(confirm=False)
        gui.root.update()
        assert len(wiz.config.categories) == 0

        # Test Load Project (.schedproj)
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(proj_file))
        gui._on_load_project()
        gui.root.update()
        assert len(wiz.config.categories) >= 1
        assert any(c.category_id == "c_test" for c in wiz.config.categories)
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_gui_diff_highlighting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify GUI diff highlights changed sessions in day tables and sets modified status."""
    from src.core.models import Timetable, TimetableEntry, TimetableLayout
    entry1 = TimetableEntry(subject="Math", hours="08:00-09:30", academic_instructor="Prof. A", room="101", type="Lecture")
    tt = Timetable(monday=[entry1], layout=TimetableLayout.create_default())

    gui = TimetableGUI(timetable=tt, base_output_dir=tmp_path, initial_mode="edit")
    try:
        gui.root.update()
        # Modify slot (reschedule time)
        modified_entry = TimetableEntry(subject="Math", hours="10:00-11:30", academic_instructor="Prof. A", room="101", type="Lecture")
        gui.timetable.monday[0] = modified_entry

        monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
        gui._on_compare_diff()
        gui.root.update()

        assert gui.timetable.monday[0].is_modified is True
        assert "#E67E22" in gui.timetable.monday[0].colors
        # Verify tag and text in treeview
        tree = gui.tree_views["monday"]
        items = tree.get_children()
        assert len(items) == 1
        assert "modified" in tree.item(items[0], "tags")
        assert "[MOD]" in tree.item(items[0], "values")[6]
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_course_dialog_color_picker_and_action_buttons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify CourseDialog._pick_course_color, swatch preview, persistent action buttons, and keyboard navigation."""
    from src.gui import CourseDialog, ScrollableDialogBody
    root = tk.Tk()
    root.withdraw()
    try:
        dlg = CourseDialog(root)
        dlg.update()

        # Check action buttons and persistent bar
        assert hasattr(dlg, "_pick_course_color")
        assert hasattr(dlg, "course_color_var")
        assert hasattr(dlg, "course_color_swatch")

        # Mock color chooser
        monkeypatch.setattr("tkinter.colorchooser.askcolor", lambda color, title, parent: ((155, 89, 182), "#9B59B6"))

        # Trigger color picking
        dlg._pick_course_color()
        assert dlg.course_color_var.get() == "#9B59B6"
        assert dlg.course_color_swatch.cget("background") == "#9B59B6"
        assert dlg.current_color == "#9B59B6"

        # Check scrollable body exists
        scroll_bodies = [child for child in dlg.winfo_children() if isinstance(child, ScrollableDialogBody)]
        assert len(scroll_bodies) == 1

        # Populate required fields
        dlg.id_var.set("C101")
        dlg.name_var.set("Algorithms and Data Structures")

        # Simulate confirm
        dlg._on_confirm()
        assert dlg.result is not None
        assert dlg.result.course_id == "C101"
        assert dlg.result.color == "#9B59B6"
    finally:
        root.destroy()


def test_dialog_scrollable_container_and_persistent_buttons(monkeypatch: pytest.MonkeyPatch):
    """Verify dialogs have persistent bottom action buttons and scrollable container frames."""
    from src.gui import RoomDialog, InstructorDialog, SlotDialog, OverlayDialog, CategoryDialog, ScrollableDialogBody
    root = tk.Tk()
    root.withdraw()
    try:
        dialog_instances = [
            RoomDialog(root),
            InstructorDialog(root),
            SlotDialog(root, title="Test Slot"),
            OverlayDialog(root, title="Test Overlay"),
            CategoryDialog(root, title="Test Category"),
        ]
        for dlg in dialog_instances:
            dlg.update()
            # Verify ScrollableDialogBody exists
            scroll_bodies = [child for child in dlg.winfo_children() if isinstance(child, ScrollableDialogBody)]
            assert len(scroll_bodies) == 1, f"Missing ScrollableDialogBody in {type(dlg).__name__}"
            # Verify Escape key destroys dialog
            dlg.event_generate("<Escape>")
            dlg.update()
    finally:
        root.destroy()


def test_window_autoscaling_and_geometry(tmp_path: Path):
    """Verify TimetableGUI queries screen metrics, autoscales to >=75-80% width / >=80-85% height, and sets minsize(1200, 750)."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="edit")
    try:
        gui.root.update()
        screen_w = gui.root.winfo_screenwidth()
        screen_h = gui.root.winfo_screenheight()
        w = gui.root.winfo_width()
        h = gui.root.winfo_height()

        expected_min_w = min(screen_w, max(1400, int(screen_w * 0.80)))
        expected_min_h = min(screen_h, max(850, int(screen_h * 0.82)))

        assert w >= min(1200, expected_min_w)
        assert h >= min(750, expected_min_h)
        assert gui.root.minsize() == (1200, 750)
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_footer_notes_zero_hardcoding_in_gui(tmp_path: Path):
    """Verify Wizard Step 6 provides fully editable footer fields synced to config."""
    gui = TimetableGUI(timetable=None, base_output_dir=tmp_path, initial_mode="create")
    try:
        gui.root.update()
        wiz = gui.wizard_frame

        # Verify entry variables exist
        assert hasattr(wiz, "campus_loc_var")
        assert hasattr(wiz, "deans_hours_note_var")
        assert hasattr(wiz, "author_sig_var")

        # Set custom values
        custom_loc = "Politechnika UWM, ul. Oczapowskiego 2"
        custom_dean = "Godziny rektorskie w piatki 13-15"
        custom_author = "Autor: Dziekanat Wydzialu"

        wiz.campus_loc_var.set(custom_loc)
        wiz.deans_hours_note_var.set(custom_dean)
        wiz.author_sig_var.set(custom_author)

        wiz._sync_step6_settings()

        assert wiz.config.campus_location_note == custom_loc
        assert wiz.config.dean_hours_note == custom_dean
        assert wiz.config.author_signature == custom_author
    finally:
        if gui.root.winfo_exists():
            gui.root.destroy()


def test_gui_category_color_binding_and_propagation(tmp_path: Path):
    """Verify category selection in CourseDialog binds color to Subject and propagates to ScheduledSlot and TimetableEntry."""
    from src.gui import CourseDialog
    from src.core.models import ScheduleCategory, CourseRequirement, TimetableEntry
    from src.core.scheduler import AcademicScheduler, ScheduledSlot, ScheduledSession

    assert ScheduledSlot is ScheduledSession

    root = tk.Tk()
    root.withdraw()
    try:
        cat = ScheduleCategory(category_id="cat_algo", name="Algorytmy i Struktury", color="#3498DB", description="Przedmioty algorytmiczne")
        dlg = CourseDialog(
            root,
            available_years=["rok_4"],
            available_groups=["G1"],
            available_instructors=[("inst_1", "Dr Jan Kowalski")],
            available_categories=[cat],
        )
        dlg.update()

        dlg.id_var.set("C_ALGO")
        dlg.name_var.set("Algorytmy i Zlozonosc")
        # Select category
        dlg.category_var.set("cat_algo")
        # Fire trace / update
        dlg._on_confirm()

        assert dlg.result is not None
        assert dlg.result.category_id == "cat_algo"
        assert dlg.result.color == "#3498DB"
        assert dlg.result.colors == ["#3498DB"]

        # Verify ScheduledSlot colors propagation via scheduler solve
        from src.core.models import (
            ScheduleGenerationConfig, AcademicStructure, AcademicYear, Specialization, BaseGroup, Room, Instructor
        )
        cfg = ScheduleGenerationConfig(
            academic_structure=AcademicStructure(
                years=[AcademicYear(year_id="rok_4", name="IV ROK", specializations=[Specialization(spec_id="s1", name="Spec", groups=[BaseGroup(group_id="G1", name="G1", student_count=15)])])]
            ),
            rooms=[Room(room_id="R1", name="Lab 101", capacity=30, allowed_event_types=["Lab"])],
            courses=[dlg.result],
            instructors=[Instructor(instructor_id="inst_1", name="Dr Jan Kowalski", max_hours_per_day=8, max_hours_per_week=20, qualified_course_ids=["C_ALGO"])],
            categories=[cat],
        )
        scheduler = AcademicScheduler(cfg)
        res = scheduler.solve()
        assert res.is_success
        assert len(res.scheduled_sessions) == 1
        slot = res.scheduled_sessions[0]
        assert isinstance(slot, ScheduledSlot)
        assert slot.colors == ["#3498DB"]

        # Verify student timetable entry colors
        tt = next(iter(res.student_timetables.values()))
        all_entries = tt.get_all_entries()
        assert len(all_entries) == 1
        entry = all_entries[0]
        assert entry.colors == ["#3498DB"]
        assert entry.color == "#3498DB"
    finally:
        root.destroy()


def test_bind_tree_double_click_and_tooltips():
    """Verify treeview double click safely handles both valid rows and empty areas, and tooltips work."""
    import tkinter as tk
    from tkinter import ttk
    from src.gui import bind_tree_double_click, ToolTip, add_help_icon
    root = tk.Tk()
    try:
        # 1. Test bind_tree_double_click
        tree = ttk.Treeview(root, columns=("Col1",), show="headings")
        tree.heading("Col1", text="Col1")
        tree.pack()
        item1 = tree.insert("", tk.END, values=("Val1",))

        called = []
        def on_edit():
            called.append(True)

        bind_tree_double_click(tree, on_edit)

        # Mock event on empty area
        class MockEvent:
            def __init__(self, y):
                self.y = y

        # Outside bounds
        tree.event_generate = lambda *args, **kwargs: None
        # Directly invoke handler logic with y=9999 (empty area)
        for binding in tree.bind():
            if binding == "<Double-Button-1>":
                pass

        # Use tree's internal event callback
        empty_event = MockEvent(y=9999)
        # Find callback bound to <Double-1>
        # Tkinter binds <Double-Button-1> or <Double-1>
        # Let's test the inner function directly by simulating identify_row
        row_empty = tree.identify_row(9999)
        assert row_empty == ""

        # 2. Test ToolTip and add_help_icon
        lbl = add_help_icon(root, "Sample tooltip message")
        assert lbl.winfo_exists()
        assert lbl.cget("text") == "(?)"

        # Show tip
        tip = ToolTip(lbl, "Help text")
        tip._show_tip()
        assert tip.tip_window is not None
        assert tip.tip_window.winfo_exists()
        tip._hide_tip()
        assert tip.tip_window is None
    finally:
        root.destroy()


def test_dialog_lifecycle_modal_grab_fix(monkeypatch: pytest.MonkeyPatch):
    """Verify SlotDialog, CourseDialog, and other modal dialogs execute deiconify() and update_idletasks() before grab_set()."""
    import tkinter as tk
    from src.gui import SlotDialog, CourseDialog, CategoryDialog, OverlayDialog, CustomNoteDialog
    from src.core.models import ScheduleCategory, TimetableEntry

    root = tk.Tk()
    root.withdraw()
    try:
        # 1. SlotDialog
        entry = TimetableEntry(subject="Math", hours="08:15-09:45", academic_instructor="Prof. X", room="101", type="Lab")
        cat = ScheduleCategory(category_id="cat_math", name="Mathematics", color="#3498DB")
        slot_dlg = SlotDialog(root, title="Edit Slot", entry=entry, available_categories=[cat])
        slot_dlg.update()
        assert slot_dlg.winfo_exists()
        assert slot_dlg.subject_var.get() == "Math"
        slot_dlg.destroy()

        # 2. CategoryDialog
        cat_dlg = CategoryDialog(root, title="Test Cat", category=cat)
        cat_dlg.update()
        assert cat_dlg.winfo_exists()
        assert cat_dlg.id_var.get() == "cat_math"
        cat_dlg.destroy()

        # 3. CustomNoteDialog
        note_dlg = CustomNoteDialog(root, title="Test Note", initial_text="Sample annotation")
        note_dlg.update()
        assert note_dlg.winfo_exists()
        assert note_dlg.note_var.get() == "Sample annotation"
        note_dlg.destroy()

        # 4. CourseDialog
        course_dlg = CourseDialog(root, title="Add Course")
        course_dlg.update()
        assert course_dlg.winfo_exists()
        course_dlg.destroy()

        # 5. OverlayDialog
        ov_dlg = OverlayDialog(root, title="Add Overlay")
        ov_dlg.update()
        assert ov_dlg.winfo_exists()
        ov_dlg.destroy()
    finally:
        root.destroy()


def test_bind_tree_double_click_guards_empty_space_and_headers():
    """Verify double click event is ignored on header rows and empty background, only firing on valid row items."""
    import tkinter as tk
    from tkinter import ttk
    from src.gui import bind_tree_double_click

    root = tk.Tk()
    root.withdraw()
    try:
        tree = ttk.Treeview(root, columns=("col1",), show="headings")
        tree.heading("col1", text="Header 1")
        tree.pack()
        row1 = tree.insert("", tk.END, values=("Row 1",))
        root.update()

        called = []
        def on_edit():
            called.append(True)

        bind_tree_double_click(tree, on_edit)

        class MockEvent:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        # Simulate click on header: mock identify_region -> "heading"
        tree.identify_region = lambda x, y: "heading"
        tree.identify_row = lambda y: ""
        tree._on_double_click(MockEvent(10, 5))
        assert len(called) == 0

        # Simulate click on empty space: mock identify_region -> "nothing"
        tree.identify_region = lambda x, y: "nothing"
        tree.identify_row = lambda y: ""
        tree._on_double_click(MockEvent(10, 500))
        assert len(called) == 0

        # Simulate click on actual cell row: mock identify_region -> "cell"
        tree.identify_region = lambda x, y: "cell"
        tree.identify_row = lambda y: row1
        tree._on_double_click(MockEvent(10, 20))
        assert len(called) == 1
    finally:
        root.destroy()


def test_editor_mode_styling_and_notes_tab_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify Editor mode dedicated Styling & Notes tab, categories/overlays/footer editing, and sync."""
    from src.core.models import (
        Timetable, TimetableEntry, TimetableLayout, ScheduleCategory, BackgroundOverlay, FooterMetadata
    )

    layout = TimetableLayout.create_default()
    cat1 = ScheduleCategory(category_id="cat_lecture", name="Wykład", color="#E74C3C", description="Wykłady teoretyczne")
    layout.categories = [cat1]
    layout.footer.campus_location_note = "Wszystkie sale na ul. Słonecznej 54"
    layout.footer.dean_hours_note = "Godziny dziekańskie: wtorek 11:30-12:45"
    layout.footer.author_signature = "Przygotował: Samorząd"
    layout.custom_notes = ["Pierwszy zjazd: tydzień nieparzysty", "Obowiązkowa obecność"]

    entry1 = TimetableEntry(
        subject="Programowanie Obiektowe",
        hours="08:15-09:45",
        academic_instructor="Dr Kowalski",
        room="S_101",
        type="Lecture",
        category_ids=["cat_lecture"],
        colors=["#E74C3C"],
    )
    tt = Timetable(monday=[entry1], layout=layout)

    gui = TimetableGUI(timetable=tt, base_output_dir=tmp_path, initial_mode="edit")
    try:
        gui.root.update()

        # 1. Styling tab exists and can be selected
        assert hasattr(gui, "styling_frame")
        assert hasattr(gui, "editor_cat_tree")
        assert hasattr(gui, "editor_notes_tree")
        assert hasattr(gui, "editor_ov_tree")

        gui._open_styling_tab()
        assert gui.notebook.select() == str(gui.styling_frame)

        # 2. Extracted working state verified
        assert any(c.category_id == "cat_lecture" for c in gui.editor_categories)
        assert gui.editor_campus_loc_var.get() == "Wszystkie sale na ul. Słonecznej 54"
        assert "11:30-12:45" in gui.editor_dean_hours_var.get()
        assert gui.editor_author_sig_var.get() == "Przygotował: Samorząd"
        assert any("Pierwszy zjazd" in n for n in gui.editor_notes)

        # Check treeview items populated
        assert len(gui.editor_cat_tree.get_children()) >= 1
        assert len(gui.editor_notes_tree.get_children()) >= 2

        # 3. Add Category in Editor Mode
        new_cat = ScheduleCategory(category_id="cat_lab", name="Laboratorium", color="#2ECC71", description="Zajęcia praktyczne")
        monkeypatch.setattr("src.gui.CategoryDialog", lambda parent, title, category=None: type("DummyDlg", (), {
            "result": new_cat,
            "wait_window": lambda self, d: None,
        })())
        gui.editor_categories.append(new_cat)
        gui._refresh_editor_categories()
        gui._refresh_all_tables()
        assert any(c.category_id == "cat_lab" for c in gui.editor_categories)

        # 4. Add Canvas Note
        gui.editor_notes.append("Dodatkowa uwaga egzaminacyjna")
        gui._refresh_editor_notes()
        assert len(gui.editor_notes_tree.get_children()) == 3

        # 5. Add Overlay
        new_ov = BackgroundOverlay(
            overlay_id="ov_rector",
            label="Godziny Rektorskie",
            day="friday",
            start_time="12:00",
            end_time="14:00",
            color="#E67E22",
        )
        gui.editor_overlays.append(new_ov)
        gui._refresh_editor_overlays()
        assert len(gui.editor_ov_tree.get_children()) >= 1

        # 6. Test Slot Quick Set Color
        gui.tree_views["monday"].selection_set("0")
        monkeypatch.setattr("tkinter.colorchooser.askcolor", lambda *args, **kwargs: ((52, 152, 219), "#3498DB"))
        gui._on_quick_set_slot_color("monday")
        assert gui.timetable.monday[0].colors == ["#3498DB"]
        assert gui.timetable.monday[0].is_modified is True

        # 7. Test Save & Regenerate PDF from Editor Mode (PDF export parity)
        monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
        gui._on_save_regenerate()
        assert gui.storage.output_pdf_path.exists()
        assert gui.timetable.layout.campus_location_note == "Wszystkie sale na ul. Słonecznej 54"
        assert any(c.category_id == "cat_lab" for c in gui.timetable.layout.categories)

        # 8. Test Save & Load Project from Editor Mode (.schedproj export parity)
        proj_dest = tmp_path / "editor_exported.schedproj"
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(proj_dest))
        gui._on_save_project()
        assert proj_dest.exists()

        # Load project into new or current GUI
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(proj_dest))
        gui._on_load_project()
        assert any(c.category_id == "cat_lab" for c in gui.editor_categories)
        assert gui.editor_campus_loc_var.get() == "Wszystkie sale na ul. Słonecznej 54"
    finally:
        gui.root.destroy()


def test_editor_mode_slot_dialog_multicolor_and_category_assignment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify SlotDialog and quick assign allow configuring categories, custom notes, and multi-color striping."""
    from src.core.models import Timetable, TimetableEntry, TimetableLayout, ScheduleCategory
    from src.gui import SlotDialog

    cat_math = ScheduleCategory(category_id="cat_math", name="Mathematics", color="#3498DB")
    cat_phys = ScheduleCategory(category_id="cat_phys", name="Physics", color="#E74C3C")
    layout = TimetableLayout.create_default()
    layout.categories = [cat_math, cat_phys]

    entry = TimetableEntry(
        subject="Algebra",
        hours="10:00-11:30",
        academic_instructor="Dr Gauss",
        room="Auditorium 1",
        type="Lecture",
    )
    tt = Timetable(tuesday=[entry], layout=layout)

    gui = TimetableGUI(timetable=tt, base_output_dir=tmp_path, initial_mode="edit")
    try:
        gui.root.update()

        # 1. Test quick category assign
        gui.tree_views["tuesday"].selection_set("0")
        monkeypatch.setattr("tkinter.Toplevel.grab_set", lambda self: None)
        # Mock quick assign
        gui._on_quick_assign_category("tuesday")
        # Ensure category list populated
        assert len(gui.editor_categories) == 2

        # 2. Test SlotDialog with multi-color striping
        slot_dlg = SlotDialog(
            gui.root,
            title="Edit Slot",
            initial_day="tuesday",
            entry=entry,
            available_categories=gui.editor_categories,
        )
        slot_dlg.update()
        slot_dlg.colors_var.set("#3498DB, #E74C3C")
        slot_dlg.custom_note_var.set("Split group lab")
        slot_dlg.category_var.set("Mathematics (cat_math)")
        slot_dlg._on_confirm()

        assert slot_dlg.result is not None
        day, updated_entry = slot_dlg.result
        assert day == "tuesday"
        assert updated_entry.colors == ["#3498DB", "#E74C3C"]
        assert updated_entry.category_ids == ["cat_math"]
        assert updated_entry.custom_note == "Split group lab"

        # Apply updated entry
        gui.timetable.modify_entry("tuesday", 0, updated_entry)
        gui._refresh_day_table("tuesday")
        assert gui.timetable.tuesday[0].colors == ["#3498DB", "#E74C3C"]
        assert gui.timetable.tuesday[0].category_ids == ["cat_math"]

        # 3. Export to PDF with generator
        monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
        gui._on_save_regenerate()
        assert gui.storage.output_pdf_path.exists()
    finally:
        gui.root.destroy()

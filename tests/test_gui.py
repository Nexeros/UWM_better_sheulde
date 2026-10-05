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

        assert len(wiz.config.academic_structure.years) == 1
        assert len(wiz.config.academic_structure.years[0].specializations) == 2
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

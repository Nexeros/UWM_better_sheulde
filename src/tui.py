"""Terminal User Interface (TUI) powered by Rich with dual-mode support (Editor & Generator Wizard)."""

from __future__ import annotations

import datetime
from pathlib import Path
import sys
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

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
from src.core.scheduler import AcademicScheduler, ScheduleResult, export_schedule_artifacts
from src.core.storage import (
    DEFAULT_INPUT_DIR,
    StorageManager,
    ensure_input_directory,
    list_discovered_pdfs,
    resolve_pdf_path,
)


class TimetableTUI:
    """Interactive Terminal User Interface for timetable management and multi-step schedule generation."""

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
        self.console = Console()
        self.is_modified = False
        self.current_mode = initial_mode

        # Wizard configuration state
        self.wizard_config = ScheduleGenerationConfig()

    def run(self) -> None:
        """Run the interactive TUI main loop with mode dispatcher."""
        self.console.clear()

        # If launched with create mode, jump straight into the wizard
        if self.current_mode == "create":
            self._run_wizard_flow()

        while True:
            self.console.print()
            self.console.print(
                Panel.fit(
                    "[bold cyan]UWM Better Schedule[/bold cyan] — [italic]Academic Timetable Suite[/italic]\n"
                    "Select an operation mode:",
                    title="Main Menu",
                    border_style="cyan",
                )
            )
            self.console.print("  [bold cyan]1[/bold cyan]. 📅 Schedule Editor Mode (Inspect, modify, or regenerate an existing timetable)")
            self.console.print("  [bold cyan]2[/bold cyan]. 🪄 Schedule Generator Wizard Mode (Create optimal new timetables via Google OR-Tools CP-SAT)")
            self.console.print("  [bold cyan]0[/bold cyan]. 🚪 Exit Application")

            mode_choice = Prompt.ask("\nSelect option [1/2/0]", default="1").strip()
            if mode_choice == "1":
                self._run_editor_loop()
            elif mode_choice == "2":
                self._run_wizard_flow()
            elif mode_choice in ("0", "q", "exit", "quit"):
                self.console.print("[cyan]Exiting Timetable Suite. Goodbye![/cyan]")
                break
            else:
                self.console.print(f"[yellow]Invalid option '{mode_choice}'. Please select 1, 2, or 0.[/yellow]")

    # =================================================================
    # Mode 1: Schedule Editor Loop
    # =================================================================

    def _run_editor_loop(self) -> None:
        """Run the interactive timetable editor loop."""
        # Handle empty/unloaded state on startup
        if self.timetable is None or self.storage is None:
            if not self._startup_file_selection():
                self.console.print("[yellow]Returning to main menu without loading a timetable.[/yellow]")
                return

        while True:
            active_file = self.storage.input_pdf_path.name if self.storage else "None"
            run_dir_name = self.storage.run_dir.name if self.storage else "None"

            self.console.print()
            self.console.print(
                Panel.fit(
                    f"[bold cyan]Schedule Editor[/bold cyan]\n"
                    f"Active File: [green]{active_file}[/green] | Run Dir: [yellow]{run_dir_name}[/yellow]",
                    title="Editor Workspace",
                    border_style="green",
                )
            )

            self.console.print("[bold green]Available Actions & Keyboard Shortcuts:[/bold green]")
            self.console.print("  [bold cyan]1[/bold cyan] / [bold cyan]v[/bold cyan]. View Full Schedule")
            self.console.print("  [bold cyan]2[/bold cyan] / [bold cyan]a[/bold cyan]. [bold]A[/bold]dd New Class Slot")
            self.console.print("  [bold cyan]3[/bold cyan] / [bold cyan]e[/bold cyan]. [bold]E[/bold]dit Existing Slot")
            self.console.print("  [bold cyan]4[/bold cyan] / [bold cyan]d[/bold cyan] / [bold cyan]del[/bold cyan]. [bold]D[/bold]elete Slot")
            self.console.print("  [bold cyan]5[/bold cyan] / [bold cyan]j[/bold cyan]. Display Raw [bold]J[/bold]SON Schema")
            self.console.print("  [bold cyan]6[/bold cyan] / [bold cyan]s[/bold cyan]. [bold]S[/bold]ave Changes & Regenerate PDF")
            self.console.print("  [bold cyan]7[/bold cyan] / [bold cyan]l[/bold cyan]. [bold]L[/bold]oad / Switch Input PDF")
            self.console.print("  [bold cyan]8[/bold cyan] / [bold cyan]w[/bold cyan]. Switch to Schedule Generator [bold]W[/bold]izard")
            self.console.print("  [bold cyan]0[/bold cyan] / [bold cyan]q[/bold cyan] / [bold cyan]esc[/bold cyan]. Return to Main Menu")

            raw_choice = Prompt.ask(
                "\nSelect action (press [bold]Enter[/bold] for View)",
                default="1",
            ).strip().lower()

            if raw_choice in ("1", "v", "view"):
                self._display_schedule()
            elif raw_choice in ("2", "a", "add"):
                self._add_slot()
            elif raw_choice in ("3", "e", "edit"):
                self._edit_slot()
            elif raw_choice in ("4", "d", "del", "delete"):
                self._delete_slot()
            elif raw_choice in ("5", "j", "json"):
                self._display_json()
            elif raw_choice in ("6", "s", "save"):
                self._save_and_regenerate()
            elif raw_choice in ("7", "l", "load"):
                self._select_and_load_file()
            elif raw_choice in ("8", "w", "wizard"):
                self._run_wizard_flow()
            elif raw_choice in ("0", "q", "quit", "exit", "esc"):
                if self.is_modified:
                    if Confirm.ask("You have unsaved changes. Save before returning? [Enter=Yes]", default=True):
                        self._save_and_regenerate()
                break
            else:
                self.console.print(f"[yellow]Unrecognized option '{raw_choice}'. Type a number or shortcut key.[/yellow]")

    def _startup_file_selection(self) -> bool:
        """Prompt user on startup when no valid timetable is loaded."""
        self.console.print(
            Panel(
                "[bold yellow]Notice:[/bold yellow] No PDF timetable is currently loaded.\n"
                "You can select an existing PDF from [cyan]./input/[/cyan] or enter a custom file path.",
                title="Input File Required",
                border_style="yellow",
            )
        )
        return self._select_and_load_file(allow_cancel=True)

    def _select_and_load_file(self, allow_cancel: bool = True) -> bool:
        """Browse discovered PDFs or prompt for custom path to load."""
        if self.is_modified:
            if Confirm.ask("You have unsaved changes on the current timetable. Save before switching? [Enter=Yes]", default=True):
                self._save_and_regenerate()

        discovered = list_discovered_pdfs()

        table = Table(
            title="Discovered PDF Files in [cyan]./input/[/cyan]",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Option", style="bold cyan", width=8)
        table.add_column("Filename", style="bold white")
        table.add_column("Size (KB)", justify="right", width=12)
        table.add_column("Last Modified", style="dim", width=20)

        choice_map = {}
        for idx, pdf_path in enumerate(discovered, start=1):
            stat = pdf_path.stat()
            size_kb = f"{stat.st_size / 1024:.1f}"
            mtime_str = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            table.add_row(str(idx), pdf_path.name, size_kb, mtime_str)
            choice_map[str(idx)] = pdf_path

        if not discovered:
            table.add_row("-", "[italic dim]No PDF files found in ./input/[/italic dim]", "-", "-")

        self.console.print(table)
        self.console.print("  [bold]c[/bold]. Enter custom file path manually")
        if allow_cancel and self.timetable is not None:
            self.console.print("  [bold]0[/bold] / [bold]q[/bold] / [bold]esc[/bold]. Cancel and keep current file")

        raw_sel = Prompt.ask(
            "\nSelect PDF to load (or [bold]c[/bold] for custom, [bold]q[/bold] to cancel)",
            default="1" if discovered else "c",
        ).strip().lower()

        if raw_sel in ("0", "q", "esc", "cancel"):
            return False

        if raw_sel == "c":
            custom_path_str = Prompt.ask("Enter path to PDF file (or [bold]q[/bold] to cancel)").strip()
            if not custom_path_str or custom_path_str.lower() in ("q", "esc"):
                return False
            try:
                target_file = resolve_pdf_path(custom_path_str)
            except Exception as e:
                self.console.print(f"[bold red]File error: {e}[/bold red]")
                return False
        elif raw_sel in choice_map:
            target_file = choice_map[raw_sel]
        else:
            self.console.print(f"[yellow]Invalid selection: '{raw_sel}'[/yellow]")
            return False

        if not target_file or not target_file.is_file():
            self.console.print(f"[bold red]Error: File not found: {target_file}[/bold red]")
            return False

        return self._load_file(target_file)

    def _load_file(self, target_path: Path) -> bool:
        """Parse the chosen PDF and initialize storage."""
        try:
            with self.console.status(f"[bold green]Parsing timetable from {target_path.name}...[/bold green]"):
                if self.storage is None:
                    self.storage = StorageManager(input_pdf_path=target_path, base_output_dir=self.base_output_dir)
                else:
                    self.storage.switch_file(target_path)

                parser = TimetableParser(target_path, log_handler=self.storage.logger)
                self.timetable = parser.parse()
                self.storage.save_extracted(self.timetable)
                self.is_modified = False

            self.console.print(
                f"[bold green]✓ Successfully loaded '{target_path.name}' "
                f"({self.timetable.count_total_entries()} slots extracted)[/bold green]"
            )
            return True
        except Exception as e:
            self.console.print(f"[bold red]Failed to parse timetable: {e}[/bold red]")
            if self.storage:
                self.storage.error(f"Error loading {target_path}: {e}")
            return False

    def _display_schedule(self) -> None:
        """Display formatted tables for all days."""
        if self.timetable is None:
            self.console.print("[yellow]No timetable loaded.[/yellow]")
            return

        total_slots = self.timetable.count_total_entries()
        self.console.print(f"\n[bold underline]Current Timetable ({total_slots} total slots):[/bold underline]\n")

        for day in VALID_DAYS:
            entries = self.timetable.get_entries(day)
            table = Table(
                title=f"[bold yellow]{day.upper()}[/bold yellow] ({len(entries)} slots)",
                show_header=True,
                header_style="bold magenta",
                border_style="dim",
                expand=True,
            )
            table.add_column("#", style="dim", width=4)
            table.add_column("Hours", style="cyan", width=13)
            table.add_column("Subject", style="bold white")
            table.add_column("Instructor", style="green")
            table.add_column("Room", style="yellow", width=10)
            table.add_column("Type", style="magenta", width=10)
            table.add_column("Group", style="blue", width=7)

            if not entries:
                table.add_row("-", "-", "[italic dim]No scheduled classes[/italic dim]", "-", "-", "-", "-")
            else:
                for idx, entry in enumerate(entries):
                    grp_str = str(entry.group) if entry.group is not None else "All"
                    table.add_row(
                        str(idx),
                        entry.hours,
                        entry.subject,
                        entry.academic_instructor,
                        entry.room,
                        entry.type,
                        grp_str,
                    )
            self.console.print(table)
            self.console.print()

    def _add_slot(self) -> None:
        """Prompt user to add a new slot."""
        if self.timetable is None:
            self.console.print("[yellow]Please load a timetable first.[/yellow]")
            return

        self.console.print("\n[bold cyan]Add New Class Slot[/bold cyan] (type [bold]q[/bold] or [bold]esc[/bold] to cancel)")
        day_input = Prompt.ask(
            "Day of week (monday/tuesday/wednesday/thursday/friday)",
            default="monday",
        ).strip().lower()

        if day_input in ("q", "esc", "cancel"):
            self.console.print("[yellow]Canceled adding slot.[/yellow]")
            return
        if day_input not in VALID_DAYS:
            self.console.print(f"[red]Invalid day '{day_input}'. Expected one of: {list(VALID_DAYS)}[/red]")
            return

        day = day_input
        subject = Prompt.ask("Subject Name").strip()
        if subject.lower() in ("q", "esc"):
            return

        hours = Prompt.ask("Hours (HH:MM-HH:MM, e.g. 08:15-09:45)").strip()
        if hours.lower() in ("q", "esc"):
            return

        instructor = Prompt.ask("Academic Instructor (e.g. Dr Kowalski)").strip()
        if instructor.lower() in ("q", "esc"):
            return

        room = Prompt.ask("Room (e.g. E 1/16)").strip()
        if room.lower() in ("q", "esc"):
            return

        slot_type = Prompt.ask(
            "Type",
            choices=["Lecture", "Lab", "Seminar", "Project", "Class"],
            default="Lab",
        )
        group_input = Prompt.ask("Group number (1, 2, or leave blank for all)", default="").strip()
        group = int(group_input) if group_input.isdigit() else None

        try:
            entry = TimetableEntry(
                subject=subject,
                hours=hours,
                academic_instructor=instructor,
                room=room,
                type=slot_type,  # type: ignore[arg-type]
                group=group,
            )
            self.timetable.add_entry(day, entry)
            self.is_modified = True
            self.console.print(f"[bold green]✓ Successfully added slot to {day.capitalize()}![/bold green]")
        except Exception as e:
            self.console.print(f"[bold red]Failed to add slot: {e}[/bold red]")

    def _edit_slot(self) -> None:
        """Select and edit an existing slot."""
        if self.timetable is None:
            self.console.print("[yellow]Please load a timetable first.[/yellow]")
            return

        day_input = Prompt.ask(
            "Select day to edit (monday/tuesday/wednesday/thursday/friday, or [bold]q[/bold] to cancel)",
            default="monday",
        ).strip().lower()

        if day_input in ("q", "esc", "cancel"):
            return
        if day_input not in VALID_DAYS:
            self.console.print(f"[red]Invalid day '{day_input}'.[/red]")
            return

        day = day_input
        entries = self.timetable.get_entries(day)
        if not entries:
            self.console.print(f"[yellow]No slots found for {day.capitalize()}.[/yellow]")
            return

        for idx, e in enumerate(entries):
            self.console.print(f"  [{idx}] {e.hours} | {e.subject} ({e.academic_instructor}, {e.room})")

        idx_input = Prompt.ask(
            f"Enter slot index to edit (0-{len(entries) - 1}, or [bold]q[/bold] to cancel)",
            default="0",
        ).strip().lower()

        if idx_input in ("q", "esc", "cancel"):
            return
        if not idx_input.isdigit() or int(idx_input) >= len(entries):
            self.console.print("[red]Invalid index selected.[/red]")
            return

        idx = int(idx_input)
        curr = entries[idx]

        self.console.print(f"\n[italic]Editing slot #{idx} (Press Enter to keep current value)[/italic]")
        subject = Prompt.ask("Subject", default=curr.subject)
        hours = Prompt.ask("Hours", default=curr.hours)
        instructor = Prompt.ask("Academic Instructor", default=curr.academic_instructor)
        room = Prompt.ask("Room", default=curr.room)
        slot_type = Prompt.ask(
            "Type",
            choices=["Lecture", "Lab", "Seminar", "Project", "Class"],
            default=curr.type,
        )
        group_default = str(curr.group) if curr.group is not None else ""
        group_input = Prompt.ask("Group (1, 2, or blank)", default=group_default).strip()
        group = int(group_input) if group_input.isdigit() else None

        try:
            updated = TimetableEntry(
                subject=subject,
                hours=hours,
                academic_instructor=instructor,
                room=room,
                type=slot_type,  # type: ignore[arg-type]
                group=group,
            )
            self.timetable.modify_entry(day, idx, updated)
            self.is_modified = True
            self.console.print("[bold green]✓ Successfully updated slot![/bold green]")
        except Exception as e:
            self.console.print(f"[bold red]Failed to update slot: {e}[/bold red]")

    def _delete_slot(self) -> None:
        """Select and delete a slot."""
        if self.timetable is None:
            self.console.print("[yellow]Please load a timetable first.[/yellow]")
            return

        day_input = Prompt.ask(
            "Select day to delete from (or [bold]q[/bold] to cancel)",
            default="monday",
        ).strip().lower()

        if day_input in ("q", "esc", "cancel"):
            return
        if day_input not in VALID_DAYS:
            self.console.print(f"[red]Invalid day '{day_input}'.[/red]")
            return

        day = day_input
        entries = self.timetable.get_entries(day)
        if not entries:
            self.console.print(f"[yellow]No slots found for {day.capitalize()}.[/yellow]")
            return

        for idx, e in enumerate(entries):
            self.console.print(f"  [{idx}] {e.hours} | {e.subject} ({e.academic_instructor})")

        idx_input = Prompt.ask(
            f"Enter slot index to delete (0-{len(entries) - 1}, or [bold]q[/bold] to cancel)",
            default="0",
        ).strip().lower()

        if idx_input in ("q", "esc", "cancel"):
            return
        if not idx_input.isdigit() or int(idx_input) >= len(entries):
            self.console.print("[red]Invalid index selected.[/red]")
            return

        idx = int(idx_input)

        if Confirm.ask(f"Are you sure you want to delete slot #{idx} ({entries[idx].subject})? [Enter=Yes]", default=True):
            removed = self.timetable.delete_entry(day, idx)
            self.is_modified = True
            self.console.print(f"[bold green]✓ Deleted: {removed.subject} ({removed.hours})[/bold green]")

    def _display_json(self) -> None:
        """Display raw JSON conforming to schema."""
        if self.timetable is None:
            self.console.print("[yellow]No timetable loaded.[/yellow]")
            return

        self.console.print(
            Panel(
                self.timetable.to_json(indent=2),
                title="Timetable JSON Schema Output",
                border_style="green",
            )
        )

    def _save_and_regenerate(self) -> None:
        """Save modified state and regenerate PDF."""
        if self.timetable is None or self.storage is None:
            self.console.print("[bold yellow]No timetable loaded to save.[/bold yellow]")
            return

        try:
            self.storage.save_modified(self.timetable)
            self.generator.generate(self.timetable, self.storage.output_pdf_path)
            self.is_modified = False
            self.console.print("[bold green]✓ Successfully saved modified.json and regenerated output.pdf![/bold green]")
            self.console.print(f"  PDF Output: [cyan]{self.storage.output_pdf_path}[/cyan]")
            self.console.print(f"  Audit Log:  [cyan]{self.storage.log_file_path}[/cyan]")
        except Exception as e:
            self.console.print(f"[bold red]Error saving/regenerating: {e}[/bold red]")

    # =================================================================
    # Mode 2: Schedule Generator Wizard Flow (Steps 1 to 6)
    # =================================================================

    def _run_wizard_flow(self) -> None:
        """Sequential multi-step interactive wizard flow."""
        current_step = 1

        while True:
            self.console.clear()
            self._print_wizard_header(current_step)

            if current_step == 1:
                current_step = self._wizard_step1_studies()
            elif current_step == 2:
                current_step = self._wizard_step2_facilities()
            elif current_step == 3:
                current_step = self._wizard_step3_curriculum()
            elif current_step == 4:
                current_step = self._wizard_step4_staff()
            elif current_step == 5:
                current_step = self._wizard_step5_conflicts()
            elif current_step == 6:
                current_step = self._wizard_step6_solve()

            if current_step == 0:
                # User chose to exit wizard back to main menu
                break

    def _print_wizard_header(self, active_step: int) -> None:
        steps = [
            "1. Studies",
            "2. Facilities",
            "3. Curriculum",
            "4. Staff",
            "5. Conflicts",
            "6. Settings & Solve",
        ]
        formatted = []
        for idx, s in enumerate(steps, start=1):
            if idx == active_step:
                formatted.append(f"[bold white on blue] {s} [/bold white on blue]")
            elif idx < active_step:
                formatted.append(f"[bold green]✓ {s}[/bold green]")
            else:
                formatted.append(f"[dim]{s}[/dim]")

        header_line = " ➔ ".join(formatted)
        self.console.print(Panel(header_line, title="Schedule Generator Wizard", border_style="cyan"))

    def _wizard_step1_studies(self) -> int:
        """Step 1: Academic Structure."""
        self.console.print("[bold yellow]Step 1: Academic Structure (Degrees, Years, Specializations & Groups)[/bold yellow]\n")

        table = Table(title="Configured Academic Cohorts", show_header=True, header_style="bold magenta")
        table.add_column("Level", style="cyan", width=14)
        table.add_column("ID", style="bold white", width=14)
        table.add_column("Name / Program", style="green")
        table.add_column("Headcount", justify="center", width=12)

        for y in self.wizard_config.academic_structure.years:
            table.add_row("Academic Year", y.year_id, f"{y.name} ({y.study_cycle})", "-")
            for s in y.specializations:
                table.add_row(" └ Specialization", s.spec_id, s.name, str(s.student_count))
                for g in s.groups:
                    table.add_row("   └ Base Group", g.group_id, g.name, str(g.student_count))

        self.console.print(table)
        self.console.print("\nActions: [bold][Enter][/bold]=Next Step, [bold][p][/bold]=Load UWM Preset, [bold][s][/bold]=Solve Now, [bold][q][/bold]=Exit Wizard")

        choice = Prompt.ask("Action", default="n").strip().lower()
        if choice in ("n", "next", ""):
            return 2
        elif choice in ("p", "preset"):
            self.wizard_config = ScheduleGenerationConfig()
            self.console.print("[green]Loaded UWM Year 4 Preset![/green]")
            return 1
        elif choice in ("s", "solve"):
            return 6
        elif choice in ("q", "quit", "exit"):
            return 0
        return 1

    def _wizard_step2_facilities(self) -> int:
        """Step 2: Facilities / Rooms."""
        self.console.print("[bold yellow]Step 2: Facilities & Rooms (Capacity & Allowed Activity Types)[/bold yellow]\n")

        table = Table(title="Configured Classrooms & Laboratories", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Room ID", style="bold white", width=12)
        table.add_column("Display Name", style="green", width=14)
        table.add_column("Capacity", justify="center", width=10)
        table.add_column("Allowed Event Types", style="yellow")

        for idx, r in enumerate(self.wizard_config.rooms):
            table.add_row(str(idx), r.room_id, r.name, str(r.capacity), ", ".join(r.allowed_event_types))

        self.console.print(table)
        self.console.print("\nActions: [bold][Enter][/bold]=Next, [bold][b][/bold]=Back, [bold][a][/bold]=Add Room, [bold][d][/bold]=Delete Room, [bold][s][/bold]=Solve")

        choice = Prompt.ask("Action", default="n").strip().lower()
        if choice in ("n", "next", ""):
            return 3
        elif choice in ("b", "back"):
            return 1
        elif choice in ("a", "add"):
            rid = Prompt.ask("Room ID (e.g. A2)").strip()
            name = Prompt.ask("Display Name (e.g. Aula A2)").strip()
            cap = int(Prompt.ask("Capacity (Seats)", default="30").strip())
            types_str = Prompt.ask("Allowed Types comma separated", default="Lecture, Computer Lab").strip()
            allowed = [t.strip() for t in types_str.split(",") if t.strip()]
            self.wizard_config.rooms.append(Room(room_id=rid, name=name, capacity=cap, allowed_event_types=allowed))
            return 2
        elif choice in ("d", "del", "delete"):
            idx_s = Prompt.ask("Room index to delete").strip()
            if idx_s.isdigit() and int(idx_s) < len(self.wizard_config.rooms):
                del self.wizard_config.rooms[int(idx_s)]
            return 2
        elif choice in ("s", "solve"):
            return 6
        elif choice in ("q", "quit"):
            return 0
        return 2

    def _wizard_step3_curriculum(self) -> int:
        """Step 3: Curriculum."""
        self.console.print("[bold yellow]Step 3: Curriculum (Subjects, Contact Hours, Format & Room Types)[/bold yellow]\n")

        table = Table(title="Curricular Subjects & Sessions", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Course ID", style="bold white", width=14)
        table.add_column("Subject Name", style="green")
        table.add_column("Duration", justify="center", width=10)
        table.add_column("Format", style="magenta", width=10)
        table.add_column("Room Type", style="yellow", width=14)
        table.add_column("Target Cohort", style="blue", width=12)

        for idx, c in enumerate(self.wizard_config.courses):
            cohort = "Whole Year" if c.is_whole_year else (", ".join(c.target_group_ids) or "All")
            table.add_row(str(idx), c.course_id, c.subject_name, f"{c.duration_minutes}m", c.delivery_format, c.required_room_type, cohort)

        self.console.print(table)
        self.console.print("\nActions: [bold][Enter][/bold]=Next, [bold][b][/bold]=Back, [bold][a][/bold]=Add Course, [bold][d][/bold]=Delete Course, [bold][s][/bold]=Solve")

        choice = Prompt.ask("Action", default="n").strip().lower()
        if choice in ("n", "next", ""):
            return 4
        elif choice in ("b", "back"):
            return 2
        elif choice in ("s", "solve"):
            return 6
        elif choice in ("q", "quit"):
            return 0
        return 3

    def _wizard_step4_staff(self) -> int:
        """Step 4: Academic Staff."""
        self.console.print("[bold yellow]Step 4: Academic Staff (Instructors, Load Limits & Windows)[/bold yellow]\n")

        table = Table(title="Academic Staff & Instructors", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Instructor ID", style="bold white", width=14)
        table.add_column("Full Name & Title", style="green")
        table.add_column("Max Day", justify="center", width=10)
        table.add_column("Max Week", justify="center", width=10)
        table.add_column("Qualified Courses", style="yellow")

        for idx, i in enumerate(self.wizard_config.instructors):
            qc_str = ", ".join(i.qualified_course_ids) or "All"
            table.add_row(str(idx), i.instructor_id, i.name, f"{i.max_hours_per_day}h", f"{i.max_hours_per_week}h", qc_str)

        self.console.print(table)
        self.console.print("\nActions: [bold][Enter][/bold]=Next, [bold][b][/bold]=Back, [bold][a][/bold]=Add Staff, [bold][d][/bold]=Delete Staff, [bold][s][/bold]=Solve")

        choice = Prompt.ask("Action", default="n").strip().lower()
        if choice in ("n", "next", ""):
            return 5
        elif choice in ("b", "back"):
            return 3
        elif choice in ("s", "solve"):
            return 6
        elif choice in ("q", "quit"):
            return 0
        return 4

    def _wizard_step5_conflicts(self) -> int:
        """Step 5: Subgroups & Conflict Rules."""
        self.console.print("[bold yellow]Step 5: Student Subgroups & Conflict Rules[/bold yellow]\n")

        table_sg = Table(title="Custom Student Subgroups", show_header=True, header_style="bold magenta")
        table_sg.add_column("Subgroup ID", style="bold white", width=16)
        table_sg.add_column("Name", style="green")
        table_sg.add_column("Headcount", justify="center", width=10)
        table_sg.add_column("Parent Groups", style="blue")

        for sg in self.wizard_config.subgroups:
            table_sg.add_row(sg.subgroup_id, sg.name, str(sg.student_count), ", ".join(sg.parent_group_ids))
        self.console.print(table_sg)

        table_cr = Table(title="Collision Prevention Rules", show_header=True, header_style="bold magenta")
        table_cr.add_column("Rule ID", style="bold white", width=18)
        table_cr.add_column("Entity A", style="cyan", width=14)
        table_cr.add_column("Entity B", style="yellow", width=14)
        table_cr.add_column("Description", style="dim")

        for cr in self.wizard_config.conflict_rules:
            table_cr.add_row(cr.rule_id, cr.entity_a, cr.entity_b, cr.description or "-")
        self.console.print(table_cr)

        self.console.print("\nActions: [bold][Enter][/bold]=Next, [bold][b][/bold]=Back, [bold][s][/bold]=Solve, [bold][q][/bold]=Exit")
        choice = Prompt.ask("Action", default="n").strip().lower()
        if choice in ("n", "next", ""):
            return 6
        elif choice in ("b", "back"):
            return 4
        elif choice in ("s", "solve"):
            return 6
        elif choice in ("q", "quit"):
            return 0
        return 5

    def _wizard_step6_solve(self) -> int:
        """Step 6: Time Horizon & Trigger Solver."""
        self.console.print("[bold yellow]Step 6: Time Horizon & Solver Execution[/bold yellow]\n")

        th = self.wizard_config.time_horizon
        self.console.print(f"  Working Days:          [green]{', '.join(th.working_days)}[/green]")
        self.console.print(f"  Daily Hours:           [cyan]{th.day_start} - {th.day_end}[/cyan]")
        self.console.print(f"  Grid Slot Unit:        [yellow]{th.slot_duration_minutes} minutes[/yellow]")
        self.console.print(f"  Max Student Day:       [magenta]{th.max_daily_hours_per_student} hours[/magenta]")
        self.console.print(f"  Solver Timeout:        [bold white]{th.solver_timeout_seconds} seconds[/bold white]")
        self.console.print(f"  Minimize Student Gaps: [green]{th.minimize_student_gaps}[/green]")
        self.console.print(f"  Minimize Worker Gaps:  [green]{th.minimize_worker_gaps}[/green]")
        self.console.print(f"  Prevent Isolated Days: [green]{th.prevent_single_class_days}[/green]")

        self.console.print("\nReady to solve academic timetable!")
        self.console.print("Actions: [bold][Enter][/bold]=Run CP-SAT Solver, [bold][b][/bold]=Back, [bold][e][/bold]=Export JSON, [bold][q][/bold]=Main Menu")

        choice = Prompt.ask("Action", default="solve").strip().lower()
        if choice in ("solve", "s", "run", ""):
            return self._execute_solver()
        elif choice in ("b", "back"):
            return 5
        elif choice in ("e", "export"):
            out_p = Path("output/wizard_config_exported.json")
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(self.wizard_config.to_json(indent=2), encoding="utf-8")
            self.console.print(f"[green]✓ Exported configuration to {out_p}[/green]")
            return 6
        elif choice in ("q", "quit"):
            return 0
        return 6

    def _execute_solver(self) -> int:
        """Execute CP-SAT solver and present results."""
        self.console.print("\n[bold cyan]Starting Google OR-Tools CP-SAT Solver...[/bold cyan]")
        scheduler = AcademicScheduler(self.wizard_config)

        with self.console.status("[bold green]Solving collision constraints and optimizing gaps...[/bold green]"):
            result: ScheduleResult = scheduler.solve()

        if not result.is_success:
            self.console.print(f"\n[bold red]Solver Failed with status: {result.status}[/bold red]")
            for d in result.diagnostics:
                self.console.print(f"  [red]• {d}[/red]")
            Prompt.ask("\nPress Enter to return to settings")
            return 6

        # Export artifacts
        artifacts = export_schedule_artifacts(result, self.base_output_dir)

        self.console.print(f"\n[bold green]✓ Solver Succeeded with status: {result.status} in {result.solver_time_seconds:.2f}s![/bold green]")
        self.console.print(f"  Scheduled Sessions: [bold white]{len(result.scheduled_sessions)}[/bold white]")
        self.console.print(f"  Objective Penalty:  [bold white]{result.objective_value}[/bold white]")
        self.console.print(f"\n[bold underline]Exported Artifacts in {self.base_output_dir}/:[/bold underline]")
        for k, p in artifacts.items():
            self.console.print(f"  • [cyan]{k}[/cyan]: [dim]{p}[/dim]")

        # Ask if user wants to load into editor
        if result.student_timetables:
            if Confirm.ask("\nWould you like to open the generated Student Schedule in Editor Mode? [Enter=Yes]", default=True):
                self.timetable = next(iter(result.student_timetables.values()))
                pdf_p = next((p for k, p in artifacts.items() if k.startswith("student_pdf")), None)
                if pdf_p and pdf_p.exists():
                    self.storage = StorageManager(input_pdf_path=pdf_p, base_output_dir=self.base_output_dir)
                self._run_editor_loop()
                return 0

        Prompt.ask("\nPress Enter to return to main menu")
        return 0

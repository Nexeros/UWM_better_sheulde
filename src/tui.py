"""Terminal User Interface (TUI) powered by Rich with keyboard shortcut navigation."""

from __future__ import annotations

import datetime
from pathlib import Path
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.core.generator import TimetablePDFGenerator
from src.core.models import VALID_DAYS, ClassType, Timetable, TimetableEntry
from src.core.parser import TimetableParser
from src.core.storage import (
    DEFAULT_INPUT_DIR,
    StorageManager,
    ensure_input_directory,
    list_discovered_pdfs,
    resolve_pdf_path,
)


class TimetableTUI:
    """Interactive Terminal User Interface for managing timetable slots."""

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
        self.console = Console()
        self.is_modified = False

    def run(self) -> None:
        """Run the interactive TUI main loop with keyboard shortcut navigation."""
        self.console.clear()

        # Handle empty/unloaded state on startup
        if self.timetable is None or self.storage is None:
            if not self._startup_file_selection():
                self.console.print("[yellow]Exiting TUI without loading a timetable.[/yellow]")
                return

        while True:
            active_file = self.storage.input_pdf_path.name if self.storage else "None"
            run_dir_name = self.storage.run_dir.name if self.storage else "None"

            self.console.print()
            self.console.print(
                Panel.fit(
                    f"[bold cyan]UWM Better Schedule[/bold cyan] — [italic]Terminal User Interface[/italic]\n"
                    f"Active File: [green]{active_file}[/green] | Run Dir: [yellow]{run_dir_name}[/yellow]",
                    title="Academic Timetable Editor",
                    border_style="cyan",
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
            self.console.print("  [bold cyan]0[/bold cyan] / [bold cyan]q[/bold cyan] / [bold cyan]esc[/bold cyan]. [bold]Q[/bold]uit / Exit")

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
            elif raw_choice in ("0", "q", "quit", "exit", "esc"):
                if self.is_modified:
                    if Confirm.ask("You have unsaved changes. Save before exiting? [Enter=Yes]", default=True):
                        self._save_and_regenerate()
                self.console.print("[cyan]Exiting Timetable TUI. Goodbye![/cyan]")
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

        valid_choices = list(choice_map.keys()) + ["c"]
        if allow_cancel and self.timetable is not None:
            valid_choices.extend(["0", "q", "esc"])

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
        """Prompt user to add a new slot with Enter confirming defaults and Esc/q canceling."""
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
            choices=["Lecture", "Lab", "Seminar", "Project"],
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
            choices=["Lecture", "Lab", "Seminar", "Project"],
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
        """Select and delete a slot with 'd' or 'del' shortcut support."""
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

"""Command-line interface and runtime interface dispatcher."""

from __future__ import annotations

import argparse
import datetime
import json
import traceback
import os
from pathlib import Path
import sys
from typing import Optional

from rich.console import Console
from rich.table import Table

from src.core.generator import TimetablePDFGenerator
from src.core.models import (
    VALID_DAYS,
    ClassType,
    ScheduleGenerationConfig,
    Timetable,
    TimetableEntry,
)
from src.core.parser import TimetableParser
from src.core.scheduler import AcademicScheduler, ScheduleResult, export_schedule_artifacts
from src.core.storage import (
    DEFAULT_INPUT_DIR,
    StorageManager,
    discover_latest_pdf,
    ensure_input_directory,
    resolve_pdf_path,
)


def is_display_available() -> bool:
    """Check if a graphical display environment (X11 / Wayland) is available."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter
        # Try creating and immediately destroying a hidden root window
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="uwm-schedule",
        description="Production-grade timetable parser, editor, and automated CP-SAT schedule generator.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["edit", "create"],
        default="edit",
        help="Global operation mode: 'edit' (Timetable Editor) or 'create' (Schedule Generator Wizard)",
    )
    parser.add_argument(
        "--create-from-config",
        type=str,
        metavar="CONFIG_JSON",
        help="Run automated schedule solver headlessly from wizard configuration JSON file",
    )
    parser.add_argument(
        "--sample-config",
        type=str,
        metavar="OUTPUT_JSON",
        help="Generate and export a sample wizard configuration JSON (UWM Year 4 CS) and exit",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to input timetable PDF (default: auto-discovers newest PDF in ./input/)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="output",
        help="Base directory for output artifacts (default: output)",
    )
    parser.add_argument(
        "--headless",
        "--cli",
        action="store_true",
        help="Run non-interactively without GUI or TUI",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Force Graphical User Interface (Tkinter)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Force Terminal User Interface (Rich)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print timetable JSON to stdout and exit",
    )
    parser.add_argument(
        "--add",
        type=str,
        metavar="JSON_STRING",
        help="Add a slot via JSON string (e.g. '{\"day\": \"friday\", \"subject\": \"AI\", \"hours\": \"10:15-11:45\", \"academic_instructor\": \"Dr X\", \"room\": \"E 1/16\", \"type\": \"Lab\"}')",
    )
    parser.add_argument(
        "--delete-day",
        type=str,
        choices=list(VALID_DAYS),
        help="Day from which to delete a slot",
    )
    parser.add_argument(
        "--delete-index",
        type=int,
        help="Index of slot within day to delete",
    )
    parser.add_argument(
        "--delete-subject",
        type=str,
        help="Subject name to delete within day (case-insensitive substring)",
    )
    return parser


def run_headless_generation(config_path: Path, output_dir: Path, console: Console, err_console: Console) -> int:
    """Execute automated schedule generation headlessly from a configuration JSON file."""
    if not config_path.is_file():
        err_console.print(f"[bold red]Error:[/bold red] Configuration file not found: {config_path}")
        return 1

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        config = ScheduleGenerationConfig.from_json(raw_text)
    except Exception as e:
        err_console.print(f"[bold red]Failed to load configuration JSON:[/bold red] {e}")
        return 1

    # Validate integrity
    errors = config.validate_integrity()
    if errors:
        err_console.print("[bold yellow]Configuration Integrity Warnings:[/bold yellow]")
        for err in errors:
            err_console.print(f"  • {err}")

    console.print(f"[cyan]Initializing CP-SAT Academic Schedule Generation from:[/cyan] [bold white]{config_path}[/bold white]")
    scheduler = AcademicScheduler(config)
    result: ScheduleResult = scheduler.solve()

    if not result.is_success:
        err_console.print(f"\n[bold red]Solver Failed with status: {result.status}[/bold red]")
        for diag in result.diagnostics:
            err_console.print(f"  • {diag}")
        return 1

    artifacts = export_schedule_artifacts(result, output_dir)

    # Print summary table
    table = Table(title="Schedule Generation Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="bold white")
    table.add_row("Solver Status", f"[green]{result.status}[/green]")
    table.add_row("Solve Time", f"{result.solver_time_seconds:.3f}s")
    table.add_row("Objective Penalty", str(result.objective_value))
    table.add_row("Total Schedulable Sessions", str(len(result.scheduled_sessions)))
    table.add_row("Student Timetables Built", str(len(result.student_timetables)))
    table.add_row("Worker Timetables Built", str(len(result.worker_timetables)))
    console.print(table)

    console.print(f"\n[bold green]✓ Artifacts successfully written to {output_dir}/:[/bold green]")
    for key, path in artifacts.items():
        console.print(f"  • [cyan]{key}[/cyan]: [dim]{path}[/dim]")

    return 0


def main(args_list: Optional[list[str]] = None) -> int:
    """CLI application entrypoint."""
    console = Console()
    err_console = Console(stderr=True)
    ensure_input_directory()

    parser = build_parser()
    args = parser.parse_args(args_list)

    # 1. Handle Sample Config Dump
    if args.sample_config:
        out_cfg_path = Path(args.sample_config)
        out_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        sample = ScheduleGenerationConfig.create_sample_config()
        out_cfg_path.write_text(sample.to_json(indent=2), encoding="utf-8")
        console.print(f"[bold green]✓ Sample configuration generated at:[/bold green] [cyan]{out_cfg_path.resolve()}[/cyan]")
        return 0

    # 2. Handle Headless Schedule Generation (--create-from-config)
    if args.create_from_config:
        cfg_path = Path(args.create_from_config)
        return run_headless_generation(cfg_path, Path(args.output_dir), console, err_console)

    # 3. Resolve target file or auto-discover from ./input/
    input_path: Optional[Path] = None
    if args.input:
        try:
            input_path = resolve_pdf_path(args.input)
        except FileNotFoundError as e:
            err_console.print(f"[bold red]Error:[/bold red] {e}")
            return 1
    else:
        input_path = discover_latest_pdf()

    is_non_interactive = (
        args.headless
        or args.add is not None
        or args.delete_index is not None
        or args.delete_subject is not None
        or args.json
    )

    # In headless/automation mode without create-from-config, an input file is mandatory
    if input_path is None and is_non_interactive:
        err_console.print(
            "[bold red]Error:[/bold red] No input PDF specified and no PDF files found in './input/'.\n"
            "Please provide --input <file.pdf>, place a timetable PDF in './input/', or use --create-from-config."
        )
        return 1

    generator = TimetablePDFGenerator()
    storage: Optional[StorageManager] = None
    timetable: Optional[Timetable] = None

    if input_path is not None:
        try:
            storage = StorageManager(input_pdf_path=input_path, base_output_dir=args.output_dir)
            storage.info(f"Target timetable resolved: {input_path.resolve()}")
            generator = TimetablePDFGenerator(log_handler=storage.logger)
            timetable_parser = TimetableParser(input_path, log_handler=storage.logger)
            timetable = timetable_parser.parse()
            storage.save_extracted(timetable)
        except Exception as e:
            if storage:
                storage.error(f"Failed to parse PDF: {e}")
                storage.close()
            err_console.print(f"[bold red]Parsing Error:[/bold red] {e}")
            return 1

    # Non-interactive CLI processing for slot modifications
    if is_non_interactive and timetable is not None and storage is not None:
        if args.delete_day and args.delete_index is not None:
            try:
                removed = timetable.delete_entry(args.delete_day, args.delete_index)
                storage.info(f"Deleted slot #{args.delete_index} ({removed.subject}) from {args.delete_day}")
                console.print(f"[green]✓ Deleted slot: {removed.subject} ({removed.hours})[/green]")
            except Exception as e:
                storage.error(f"Failed to delete slot: {e}")
                err_console.print(f"[red]Error deleting slot: {e}[/red]")

        if args.delete_day and args.delete_subject:
            deleted_count = timetable.delete_by_subject(args.delete_day, args.delete_subject)
            storage.info(f"Deleted {deleted_count} slots matching '{args.delete_subject}' from {args.delete_day}")
            console.print(f"[green]✓ Deleted {deleted_count} slot(s) matching '{args.delete_subject}'[/green]")

        if args.add:
            try:
                slot_data = json.loads(args.add)
                day = slot_data.pop("day", "monday").lower()
                entry = TimetableEntry(**slot_data)
                timetable.add_entry(day, entry)
                storage.info(f"Added slot '{entry.subject}' to {day}")
                console.print(f"[green]✓ Added slot: {entry.subject} ({entry.hours}) to {day}[/green]")
            except Exception as e:
                storage.error(f"Failed to add slot from JSON: {e}")
                err_console.print(f"[red]Error adding slot: {e}[/red]")

        storage.save_modified(timetable)
        generator.generate(timetable, storage.output_pdf_path)

        if args.json:
            print(timetable.to_json(indent=2))
        else:
            console.print(f"[bold green]Execution completed successfully![/bold green]")
            console.print(f"  Artifacts directory: [cyan]{storage.run_dir}[/cyan]")
            console.print(f"  Extracted JSON:      [dim]{storage.extracted_json_path}[/dim]")
            console.print(f"  Modified JSON:       [dim]{storage.modified_json_path}[/dim]")
            console.print(f"  Regenerated PDF:     [dim]{storage.output_pdf_path}[/dim]")
            console.print(f"  Execution Log:       [dim]{storage.log_file_path}[/dim]")

        storage.close()
        return 0

    # Interactive mode dispatch (GUI -> TUI)
    display_ok = is_display_available()
    target_mode = args.mode

    if args.gui:
        if not display_ok:
            if storage:
                storage.warning("GUI requested with --gui, but no display detected. Degrading to TUI.")
            console.print("[yellow]Warning: No display server detected. Falling back to TUI...[/yellow]")
            from src.tui import TimetableTUI
            tui = TimetableTUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
            tui.run()
        else:
            try:
                if storage:
                    storage.info("Launching Tkinter GUI (forced by --gui)")
                from src.gui import TimetableGUI
                gui = TimetableGUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
                gui.run()
            except Exception as e:
                tb = traceback.format_exc()
                if storage:
                    storage.error(f"Failed to launch GUI (forced by --gui): {e}\nTraceback:\n{tb}")
                else:
                    try:
                        out_dir = Path(args.output_dir)
                        out_dir.mkdir(parents=True, exist_ok=True)
                        with open(out_dir / "execution.log", "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] GUI failure: {e}\n{tb}\n")
                    except Exception:
                        pass
                console.print(f"[bold red]GUI Initialization Error:[/bold red] {e}\n[dim]{tb}[/dim]")
                return 1
    elif args.tui:
        if storage:
            storage.info("Launching Rich TUI (forced by --tui)")
        from src.tui import TimetableTUI
        tui = TimetableTUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
        tui.run()
    else:
        # Default behavior: GUI if display is available, else TUI
        if display_ok:
            try:
                if storage:
                    storage.info("Display server detected. Launching primary GUI (Tkinter)")
                from src.gui import TimetableGUI
                gui = TimetableGUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
                gui.run()
            except Exception as e:
                tb = traceback.format_exc()
                if storage:
                    storage.error(f"Failed to initialize GUI ({e}). Degrading to TUI.\nTraceback:\n{tb}")
                else:
                    try:
                        out_dir = Path(args.output_dir)
                        out_dir.mkdir(parents=True, exist_ok=True)
                        with open(out_dir / "execution.log", "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] Failed to initialize GUI ({e}). Degrading to TUI.\nTraceback:\n{tb}\n")
                    except Exception:
                        pass
                console.print(f"[yellow]Warning: GUI failed ({e}). Degrading to TUI...[/yellow]")
                from src.tui import TimetableTUI
                tui = TimetableTUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
                tui.run()
        else:
            if storage:
                storage.info("No display server detected. Gracefully launching secondary TUI (Rich)")
            from src.tui import TimetableTUI
            tui = TimetableTUI(timetable, storage, generator, base_output_dir=args.output_dir, initial_mode=target_mode)
            tui.run()

    if storage:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

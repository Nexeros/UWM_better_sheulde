"""Storage and output management for timetable execution artifacts."""

from __future__ import annotations

import datetime
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from src.core.models import (
    VALID_DAYS,
    ScheduleCategory,
    ScheduleProject,
    Timetable,
    TimetableEntry,
    TimetableLayout,
)

DEFAULT_INPUT_DIR = Path("input")


def ensure_input_directory(input_dir: str | Path = DEFAULT_INPUT_DIR) -> Path:
    """Ensure the standard input directory exists on startup."""
    path = Path(input_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_discovered_pdfs(input_dir: str | Path = DEFAULT_INPUT_DIR) -> List[Path]:
    """Scan directory for PDF files, ordered by modification time (newest first)."""
    dir_path = ensure_input_directory(input_dir)
    pdf_files: List[Path] = []
    for p in dir_path.iterdir():
        if p.is_file() and p.suffix.lower() == ".pdf":
            pdf_files.append(p)
    pdf_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return pdf_files


def discover_latest_pdf(input_dir: str | Path = DEFAULT_INPUT_DIR) -> Optional[Path]:
    """Discover the newest PDF file in the input directory based on mtime."""
    pdfs = list_discovered_pdfs(input_dir)
    return pdfs[0] if pdfs else None


def resolve_pdf_path(
    path_input: Optional[str | Path],
    input_dir: str | Path = DEFAULT_INPUT_DIR,
) -> Optional[Path]:
    """Resolve an input PDF path from string or discover the latest one."""
    if path_input is not None and str(path_input).strip():
        cleaned = str(path_input).strip()
        candidate = Path(os.path.expanduser(cleaned))
        if candidate.is_file():
            return candidate.resolve()

        # Check if relative to input_dir
        in_dir_candidate = Path(input_dir) / candidate
        if in_dir_candidate.is_file():
            return in_dir_candidate.resolve()

        raise FileNotFoundError(f"Specified PDF timetable file not found: {path_input}")

    return discover_latest_pdf(input_dir)


class StorageManager:
    """Manages isolated output directories and audit logs for each run."""

    def __init__(
        self,
        input_pdf_path: str | Path,
        base_output_dir: str | Path = "output",
        timestamp: Optional[datetime.datetime] = None,
    ):
        self.base_output_dir = Path(base_output_dir)
        self.input_pdf_path = Path(input_pdf_path)
        self.timestamp = timestamp or datetime.datetime.now()
        self._logger: Optional[logging.Logger] = None

        self._configure_paths()

    def _configure_paths(self) -> None:
        sanitized_stem = self._sanitize_filename(self.input_pdf_path.stem)
        time_str = self.timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        self.run_dir_name = f"{time_str}_{sanitized_stem}"
        self.run_dir = self.base_output_dir / self.run_dir_name

        self.extracted_json_path = self.run_dir / "extracted.json"
        self.modified_json_path = self.run_dir / "modified.json"
        self.output_pdf_path = self.run_dir / "output.pdf"
        self.log_file_path = self.run_dir / "execution.log"

        self._init_directory_and_logger()

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename to prevent directory traversal and unsafe characters."""
        cleaned = re.sub(r"[^\w\-_.]", "_", name)
        cleaned = re.sub(r"_+", "_", cleaned)
        return cleaned.strip("._") or "timetable"

    def _init_directory_and_logger(self) -> None:
        """Create directory and configure dedicated file logger."""
        self.run_dir.mkdir(parents=True, exist_ok=True)

        logger_name = f"timetable_run_{self.run_dir_name}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        # Clear existing handlers if any
        if self._logger.hasHandlers():
            self._logger.handlers.clear()

        # File handler for execution.log
        file_handler = logging.FileHandler(self.log_file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        self.info(f"Initialized run directory: {self.run_dir.resolve()}")
        self.info(f"Target input file: {self.input_pdf_path.resolve()}")

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._init_directory_and_logger()
        return self._logger  # type: ignore[return-value]

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def debug(self, message: str) -> None:
        self.logger.debug(message)

    def save_extracted(self, timetable: Timetable) -> Path:
        """Save initial extracted timetable state."""
        content = timetable.to_json(indent=2, include_extra=False)
        self.extracted_json_path.write_text(content, encoding="utf-8")
        self.info(f"Saved extracted state ({timetable.count_total_entries()} slots) -> {self.extracted_json_path.name}")
        return self.extracted_json_path

    def save_modified(self, timetable: Timetable) -> Path:
        """Save updated timetable state post modifications."""
        content = timetable.to_json(indent=2, include_extra=False)
        self.modified_json_path.write_text(content, encoding="utf-8")
        self.info(f"Saved modified state ({timetable.count_total_entries()} slots) -> {self.modified_json_path.name}")
        return self.modified_json_path

    def switch_file(self, new_input_pdf_path: str | Path) -> None:
        """Switch storage context to a newly loaded file with new run directory."""
        self.close()
        self.input_pdf_path = Path(new_input_pdf_path)
        self.timestamp = datetime.datetime.now()
        self._configure_paths()

    def close(self) -> None:
        """Flush and close logger handlers."""
        if self._logger:
            for handler in self._logger.handlers:
                handler.flush()
                handler.close()
            self._logger.handlers.clear()


# =====================================================================
# Project State Persistence & Diff Change Tracking (.schedproj / JSON)
# =====================================================================

def save_project(project: ScheduleProject, file_path: str | Path) -> Path:
    """Serialize the complete project workspace state into a .schedproj / JSON file."""
    p = Path(file_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    project.updated_at = datetime.datetime.now().isoformat()
    content = project.to_json(indent=2)
    p.write_text(content, encoding="utf-8")
    return p


def load_project(file_path: str | Path) -> ScheduleProject:
    """Load and reconstruct a ScheduleProject workspace state from .schedproj / JSON."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Project file not found: {p}")
    content = p.read_text(encoding="utf-8")
    return ScheduleProject.from_json(content)


class DiffRecord(dict):
    """Structured record representing an individual timetable change."""

    def __init__(
        self,
        change_type: str,
        message: str,
        day: Optional[str] = None,
        entry: Optional[TimetableEntry] = None,
    ):
        super().__init__(
            type=change_type,
            message=message,
            description=message,
            day=day,
            entry=entry,
        )
        self.type = change_type
        self.message = message
        self.description = message
        self.day = day
        self.entry = entry

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"<DiffRecord type='{self.type}' day='{self.day}': {self.message}>"

def compute_timetable_diff(
    baseline: Timetable,
    current: Timetable,
    change_color: str = "#E67E22",
) -> Tuple[Timetable, List[DiffRecord]]:
    """Compare current timetable against a baseline timetable, flagging all changes.

    Detects:
      - Added sessions: In current but not baseline.
      - Moved / Rescheduled sessions: Same subject and group, but different hours or day.
      - Edited sessions: Same day and hours, but different subject, instructor, or room.
      - Removed sessions: In baseline but missing in current (logged in diff).

    For every changed or added session in current:
      - Sets entry.is_modified = True
      - Appends change_color to entry.colors (multi-color split preserving original colors)

    Inserts audit note in layout.custom_notes:
      "[!] Marked cells indicate updates from previous plan version"
    """
    diff_messages: List[str] = []

    # Flatten baseline entries with day tag
    baseline_all: List[Tuple[str, TimetableEntry]] = []
    for d in VALID_DAYS:
        for b_entry in baseline.get_entries(d):
            baseline_all.append((d, b_entry))

    matched_baseline_indices = set()
    has_any_change = False

    for day in VALID_DAYS:
        curr_entries = current.get_entries(day)
        for c_entry in curr_entries:
            # 1. Exact match check
            exact_match_idx = None
            for b_idx, (b_day, b_entry) in enumerate(baseline_all):
                if b_idx in matched_baseline_indices:
                    continue
                if (
                    b_day == day
                    and b_entry.subject == c_entry.subject
                    and b_entry.hours == c_entry.hours
                    and b_entry.room == c_entry.room
                    and b_entry.academic_instructor == c_entry.academic_instructor
                    and b_entry.group == c_entry.group
                    and b_entry.type == c_entry.type
                ):
                    exact_match_idx = b_idx
                    break

            if exact_match_idx is not None:
                matched_baseline_indices.add(exact_match_idx)
                continue

            # 2. Similar session moved/rescheduled check
            similar_idx = None
            for b_idx, (b_day, b_entry) in enumerate(baseline_all):
                if b_idx in matched_baseline_indices:
                    continue
                if b_entry.subject == c_entry.subject and b_entry.group == c_entry.group:
                    similar_idx = b_idx
                    break

            c_entry.is_modified = True
            has_any_change = True
            if change_color not in c_entry.colors:
                c_entry.colors.append(change_color)

            if similar_idx is not None:
                matched_baseline_indices.add(similar_idx)
                b_day, b_entry = baseline_all[similar_idx]
                if b_day == day and b_entry.hours == c_entry.hours:
                    change_type = "modified"
                    desc = (
                        f"Modified details for '{c_entry.subject}' (Grp {c_entry.group or 'all'}) "
                        f"on {day.capitalize()} {c_entry.hours}: Room [{b_entry.room} -> {c_entry.room}], "
                        f"Instructor [{b_entry.academic_instructor} -> {c_entry.academic_instructor}]"
                    )
                else:
                    change_type = "rescheduled"
                    desc = (
                        f"Rescheduled '{c_entry.subject}' (Grp {c_entry.group or 'all'}) "
                        f"moved from {b_day.capitalize()} {b_entry.hours} [{b_entry.room}] "
                        f"to {day.capitalize()} {c_entry.hours} [{c_entry.room}]"
                    )
                diff_messages.append(DiffRecord(change_type=change_type, message=desc, day=day, entry=c_entry))
            else:
                change_type = "added"
                desc = (
                    f"Added session: '{c_entry.subject}' on {day.capitalize()} {c_entry.hours} "
                    f"in room {c_entry.room} ({c_entry.academic_instructor})"
                )
                diff_messages.append(DiffRecord(change_type=change_type, message=desc, day=day, entry=c_entry))

    # Check for removed sessions
    for b_idx, (b_day, b_entry) in enumerate(baseline_all):
        if b_idx not in matched_baseline_indices:
            desc = f"Removed session: '{b_entry.subject}' from {b_day.capitalize()} {b_entry.hours} [{b_entry.room}]"
            diff_messages.append(DiffRecord(change_type="removed", message=desc, day=b_day, entry=b_entry))

    if has_any_change:
        if current.layout is None:
            current.layout = TimetableLayout.create_default()

        # Insert audit note into custom notes
        audit_note = "[!] Marked cells indicate updates from previous plan version"
        if audit_note not in current.layout.custom_notes:
            current.layout.custom_notes.append(audit_note)

        # Register modified category for legend
        if not any(cat.category_id == "cat_modified" or cat.color == change_color for cat in current.layout.categories):
            current.layout.categories.append(
                ScheduleCategory(
                    category_id="cat_modified",
                    name="Modified / Change",
                    color=change_color,
                    description="Zaktualizowane zajęcia względem poprzedniej wersji",
                )
            )

    return current, diff_messages

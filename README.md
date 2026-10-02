# UWM Better Schedule

A production-grade, modular Python project to parse, modify, and visually reconstruct university timetable schedules (specifically designed for UWM Olsztyn timetable layouts such as `IV-io 2gr zima 2026.pdf`).

---

## Features

- **Automated Input Discovery**: Automatically scans the standard `./input/` directory for `.pdf` files, pre-loading the newest file based on modification time (`mtime`). Creates `./input/` automatically if missing.
- **Dynamic File Ingestion Across All Interfaces**:
  - **GUI**: Integrated file bar with "Browse / Load File..." dialog for instant hot-swapping of timetable PDFs.
  - **TUI**: Menu option to choose from discovered PDFs in `./input/` or input custom paths.
  - **CLI**: Flexible `--input` flag resolving relative paths, paths in `./input/`, or absolute filesystem paths.
- **Automated PDF Parsing**: Extracts timetable grid blocks, days (`monday`–`friday`), class hours, subject names, lecturers, room codes, and class types (`Lecture`, `Lab`, `Seminar`, `Project`) directly from the PDF layout geometry.
- **Data Validation & Modeling**: Full Pydantic v2 schemas validating time ranges, class types, and serialized JSON outputs.
- **Visual PDF Reconstruction**: Rebuilds the timetable with matching layout geometry, 15-minute grid spacing, pastel color tags, headers, bold room identifiers, and footer notes using ReportLab.
- **Triple-Tier Interface Strategy**:
  - **Primary (GUI)**: Modern, lightweight Tkinter interface with complete keyboard accessibility.
  - **Secondary (TUI)**: Rich terminal UI with interactive menus, slot inspection, and single-letter navigation.
  - **Tertiary (CLI)**: Non-interactive CLI flags (`--headless`, `--add`, `--delete`, `--output-dir`, `--json`) for automation and scripting.
- **Isolated Artifact Storage**: Organizes all artifacts under timestamped directories:
  `/output/{YYYY-MM-DD}_{HH-MM-SS}_{sanitized_original_filename}/`
  containing `extracted.json`, `modified.json`, `output.pdf`, and `execution.log`.

---

## Keyboard Shortcuts Reference

Both the GUI and TUI support seamless keyboard navigation for maximum efficiency without touching the mouse:

### 1. Graphical User Interface (GUI) Shortcuts

| Shortcut | Scope | Action |
|---|---|---|
| `Ctrl+O` / `Cmd+O` | Global | **Browse & Load File** — Open native file picker to select a timetable PDF |
| `Ctrl+S` / `Cmd+S` | Global | **Save & Regenerate PDF** — Generate updated `output.pdf` and `modified.json` |
| `Delete` / `Backspace` | Table / Window | **Delete Selected Slot** — Remove the currently highlighted class entry |
| `Enter` / `Return` | Table | **Edit Selected Slot** — Open the editing dialog for the highlighted entry |
| `Escape` | Global / Dialog | **Deselect / Cancel** — Clear slot selection or close modal dialogs |
| `Up` / `Down` Arrow | Table | **Navigate Slots** — Move selection up and down within the active day |
| `Tab` / `Shift+Tab` | Form / Dialog | **Navigate Form Fields** — Cycle through input fields smoothly |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Global | **Cycle Weekday Tabs** — Switch between Monday, Tuesday, Wednesday, etc. |

### 2. Terminal User Interface (TUI) Shortcuts

| Key / Shortcut | Menu Option | Action |
|---|---|---|
| `1` or `v` or `Enter` | View Schedule | Display beautifully formatted Rich tables for all weekdays |
| `2` or `a` | Add Slot | Add a new class slot with interactive validation |
| `3` or `e` | Edit Slot | Select and edit fields of an existing class slot |
| `4` or `d` or `del` | Delete Slot | Delete a slot by index after confirmation |
| `5` or `j` | JSON View | Display timetable adhering strictly to the JSON schema |
| `6` or `s` | Save PDF | Save `modified.json` and regenerate `output.pdf` |
| `7` or `l` | Load PDF | Select a PDF from `./input/` or enter a custom path |
| `0` or `q` or `esc` | Quit / Back | Exit the program or cancel current sub-menu |
| `Enter` | Everywhere | Confirm highlighted or default choice |

---

## Installation & Environment Setup

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, deterministic dependency management.

```bash
# Clone or navigate to the repository
cd /path/to/UWM_better_schedule

# Sync environment and dependencies
uv sync
```

To run commands within the managed virtual environment:
```bash
uv run main.py [FLAGS]
```

Or install the package in editable mode via uv:
```bash
uv run uwm-schedule --help
```

---

## Input Directory & Auto-Discovery Convention

- **Standard Input Directory**: `./input/`
- When launched without an explicit `--input` flag:
  1. The application ensures `./input/` exists.
  2. Scans for all `*.pdf` files.
  3. Sorts files by modification timestamp (`st_mtime`, newest first).
  4. Pre-loads the newest PDF schedule automatically.
- **Empty Directory Handling**:
  - If `./input/` is empty or has no PDFs:
    - **In GUI**: Launches in a clean ready state with an active "Browse / Load File..." button and status prompt.
    - **In TUI**: Prompts user to select from newly placed files or type a custom path.
    - **In Headless CLI**: Exits gracefully with an informative error message requesting an input path.

---

## Quick Start & Usage

### 1. Default Mode (GUI with Auto-Discovery)
```bash
uv run main.py
```
- Automatically picks the newest PDF in `./input/`.
- If a display server is detected (`$DISPLAY` or Wayland), Tkinter GUI launches.
- If no display server is found, it automatically degrades gracefully to the interactive Terminal UI (TUI).

### 2. Interactive Terminal UI (TUI)
```bash
uv run main.py --tui
```
- Provides a dedicated menu option `7. Load / Switch Input PDF` to choose any PDF in `./input/` or enter a manual path.
- Supports single-key navigation (`v`, `a`, `e`, `d`, `j`, `s`, `l`, `q`).

### 3. Non-Interactive Scripting / Headless CLI
```bash
# Auto-discover newest PDF in ./input/ and generate artifacts
uv run main.py --headless

# Parse specific timetable file (relative or absolute)
uv run main.py --headless --input "input/IV-io 2gr zima 2026.pdf"

# Add a new slot non-interactively via JSON string
uv run main.py --headless \
  --add '{"day": "friday", "subject": "Zaawansowane Bazy Danych", "hours": "10:15-11:45", "academic_instructor": "dr Kowalski", "room": "A 1/02", "type": "Lab"}'

# Delete a slot by day and index
uv run main.py --headless --delete-day friday --delete-index 0

# Delete slots by subject name (case-insensitive substring match)
uv run main.py --headless --delete-day monday --delete-subject "Aplikacje WWW"

# Print timetable JSON directly to stdout
uv run main.py --headless --json
```

---

## CLI Flag Reference

| Flag | Type | Description |
|---|---|---|
| `--input`, `-i <path>` | String | Optional path to timetable PDF. If omitted, automatically discovers newest PDF in `./input/`. |
| `--output-dir`, `-o <path>` | String | Base directory for output runs (default: `./output`). |
| `--headless`, `--cli` | Flag | Disable interactive UI; parse, apply modifications, and write output artifacts directly. |
| `--gui` | Flag | Force GUI mode. Fails with a descriptive message or falls back if no display is available. |
| `--tui` | Flag | Force Terminal UI (TUI) mode. |
| `--json` | Flag | Output the final timetable JSON directly to `stdout`. |
| `--add <json_str>` | String | Add a slot from JSON string. |
| `--delete-day <day>` | String | Day of slot to delete (`monday`..`friday`). |
| `--delete-index <idx>` | Integer | Zero-based index of slot within the specified day to delete. |
| `--delete-subject <name>` | String | Delete any slot matching the subject name in the specified day. |

---

## Fallback Behavior & Interface Matrix

```
                ┌────────────────────────┐
                │       main.py          │
                └──────────┬─────────────┘
                           │
               Explicit Flags Specified?
              /            │            \
      [--headless/--add] [--tui]      [--gui]
            /              │              \
           v               v               v
     ┌───────────┐   ┌───────────┐   Display Available?
     │    CLI    │   │    TUI    │      /          \
     │ (Script)  │   │  (Rich)   │    Yes           No
     └───────────┘   └───────────┘     v             v
                                   ┌─────────┐   ┌─────────┐
                                   │   GUI   │   │ Fallback│
                                   │(Tkinter)│   │ to TUI  │
                                   └─────────┘   └─────────┘
```

---

## Data Schema Specification

Timetable data adheres to the following JSON structure:

```json
{
  "monday": [
    {
      "subject": "String",
      "hours": "HH:MM-HH:MM",
      "academic_instructor": "String",
      "room": "String",
      "type": "Lecture | Lab | Seminar | Project"
    }
  ],
  "tuesday": [],
  "wednesday": [],
  "thursday": [],
  "friday": []
}
```

### Slot Field Constraints:
- `subject` (str): Name or abbreviation of course (e.g. `"Testowanie oprogramowania"`).
- `hours` (str): Time span formatted strictly as `"HH:MM-HH:MM"` (24-hour clock, start time strictly before end time).
- `academic_instructor` (str): Academic title and instructor name (e.g. `"Jastrzębski P."`).
- `room` (str): Hall / laboratory designation (rendered in **bold** on the generated PDF, e.g. `**E 1/16**`, `**C0/1**`).
- `type` (str): Must be one of `"Lecture"`, `"Lab"`, `"Seminar"`, `"Project"`.
- `group` (optional int): Group number if applicable (e.g. `1` or `2`).

---

## Directory & Architecture Layout

```text
.
├── pyproject.toml
├── .gitignore
├── README.md
├── documentation.md              # Beginner-friendly Stone-Age User Guide
├── LICENSE.md                    # Creative Commons Attribution-NonCommercial-ShareAlike 4.0
├── main.py                       # Project entry point
└── src/
    ├── __init__.py
    ├── cli.py                    # CLI argument parser, fallback logic & orchestration
    ├── tui.py                    # Interactive Rich terminal UI with keyboard shortcuts
    ├── gui.py                    # Tkinter graphical editor with keyboard shortcuts
    └── core/
        ├── __init__.py
        ├── models.py             # Pydantic data schemas & dynamic layout specifications
        ├── parser.py             # Geometry-based PDF extraction & text clustering
        ├── generator.py          # ReportLab vector timetable reconstruction (bold rooms)
        └── storage.py            # Input auto-discovery, isolated output runs & logging
```

---

## Storage & Audit Log Output

For every run, artifacts are saved in an isolated folder:

```text
output/
└── 2026-10-02_08-31-09_IV-io_2gr_zima_2026/
    ├── execution.log     # Detailed logger trace of operations and metrics
    ├── extracted.json    # Original parsed schedule before any modifications
    ├── modified.json     # Final state post modifications
    └── output.pdf        # High-fidelity vector PDF reconstruction (with bold rooms)
```

---

## License

This project, its source code, documentation, and reconstructed schedule templates are licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)** license. See [`LICENSE.md`](file:///home/leonidas/PycharmProjects/UWM_better_schedule/LICENSE.md) for the full license terms.

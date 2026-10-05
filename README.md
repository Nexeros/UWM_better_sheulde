# UWM Better Schedule

A production-grade, modular Python application to parse, modify, visually reconstruct, and **automatically generate** conflict-free university academic timetables. Powered by **Google OR-Tools CP-SAT**, ReportLab vector rendering, and Pydantic v2 validation. Specifically designed and calibrated for University of Warmia and Mazury (UWM Olsztyn) timetable standards.

---

## 🌟 Key Features

- **Dual-Mode System Switch**:
  - **Schedule Editor Mode**: Load, view, modify, add, delete, and reconstruct existing timetable schedules from PDF or JSON.
  - **Schedule Generator Wizard Mode**: End-to-end multi-step wizard to formulate academic requirements and automatically solve complex scheduling constraints via Google OR-Tools CP-SAT.
- **Interactive Quick Test / Demo Mode**:
  - **One-Click Test Data Loading**: `[ 🧪 Load Test Data ]` populates realistic academic requirements across all 6 wizard steps (1 year, 2 specializations, 4 balanced student groups, 5 facilities, 4 instructors with custom availability, 9 courses, and 2 elective subgroups).
  - **Instant Verification Dialog**: `[ ⚡ Quick Test & Solve ]` solves the schedule directly and displays a dedicated **Verification & Audit Modal** with zero-collision verification, solver timing, and interactive schedule previews for students and staff.
- **Automated CP-SAT Constraint Programming Solver**:
  - **Hard Constraints**: Room collision prevention, lecturer collision prevention, lecturer forbidden time windows (faculty councils, off-hours), student group non-overlapping, cross-group subgroup constraints, explicit conflict rules, and maximum daily/weekly teaching and study hour limits.
  - **Soft Optimization Objectives**: Minimization of student idle gaps (okienka), minimization of faculty teaching spans, and elimination of isolated single-class days.
  - **Instant Diagnostics**: High-speed resolution (< 0.05s) with automated bottleneck detection and conflict reports when a configuration is infeasible.
- **Automated Artifact Pipeline (`/output/`)**:
  - `schedule_students.json`: Structured timetables grouped by study cycle, year, and specialization.
  - `schedule_workers.json`: Individual timetables for every lecturer and faculty member.
  - `execution.log`: Full audit trail of solver decisions, objective metrics, and session allocations.
  - **High-Fidelity Vector PDFs**: Layout-matched student and staff PDF schedules with pastel category swatches, bold room identifiers, and 15-minute grid spacing.
- **Triple-Tier Interface Strategy**:
  - **Primary (GUI)**: Tkinter application with top-level mode switch, responsive 6-step wizard, interactive dialogs, and instant schedule preview.
  - **Secondary (TUI)**: Rich terminal UI with interactive menus, step-by-step forms, presets loader, and keyboard-first navigation.
  - **Tertiary (CLI)**: Non-interactive scripting flags (`--create-from-config`, `--sample-config`, `--headless`, `--add`, `--delete-day`) for automated batch processing.

---

## 🚀 Quick Start

### Installation with `uv`

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, deterministic dependency management.

```bash
# Clone or navigate to the repository
cd /path/to/UWM_better_schedule

# Sync environment and dependencies (includes ortools, reportlab, pydantic, rich, pypdf, pytest)
uv sync
```

---

## 🧭 Dual-Mode System Usage

Switch between modes seamlessly across GUI, TUI, and CLI interfaces:

```bash
# Launch GUI in Schedule Editor mode (default)
uv run main.py --mode edit

# Launch GUI directly in Schedule Generator Wizard mode
uv run main.py --mode create

# Launch interactive Terminal UI (TUI) in Generator mode
uv run main.py --tui --mode create

# Export sample generation configuration JSON
uv run main.py --sample-config sample_config.json

# Headless generation directly from configuration JSON
uv run main.py --create-from-config sample_config.json --output-dir ./output
```

---

## 🧪 Interactive Demo & Verification (GUI)

The Schedule Generator Wizard header includes quick-testing utilities:

1. **`🧪 Load Test Data`**:
   - Injects a complete academic year (IV ROK) with 2 specializations (*Inżynieria Oprogramowania*, *Inżynieria Systemów Informacyjnych*), 4 groups (G1–G4), 5 distinct rooms (auditorium, classroom, computer/systems labs, seminar room), 4 professors with realistic availability constraints, 9 courses, and 2 elective subgroups (*SUB_AI*, *SUB_SEC*) sharing students from G1.
   - All fields remain 100% editable across Steps 1 through 6 for custom scenario testing.
2. **`⚡ Quick Test & Solve`**:
   - Triggers Google OR-Tools CP-SAT directly from the demo data and opens the **Schedule Verification & Collision Report** dialog.
3. **Verification Dialog Capabilities**:
   - **Solver Status Badge**: Highlights `OPTIMAL` / `FEASIBLE` status and solve time.
   - **Zero-Collision Audit Report**: Verifies room non-overlapping, instructor non-overlapping, student cohort and subgroup non-overlapping, forbidden window compliance, and room capacity validation.
   - **Interactive Schedule Previews**: Filterable timetable views for Student Cohorts (G1, G2, G3, G4, SUB_AI, SUB_SEC) and Academic Staff.
   - **One-Click Editor Handoff**: Open any generated schedule directly in the Schedule Editor for fine-tuning.

---

## 🪄 Schedule Generation Wizard (6 Steps)

The Generation Wizard guides you through 6 sequential steps to build a complete academic scheduling problem:

1. **Step 1: Academic Structure (Studies)**
   - Define study cycles (e.g. *stacjonarne inżynierskie I-go stopnia*), academic years (e.g. *IV ROK*), specializations, and base student groups (*Grupa 1*, *Grupa 2*).
   - Set headcounts with automatic capacity validation (sum of group headcounts $\le$ specialization capacity).
2. **Step 2: Facilities (Rooms)**
   - Register lecture halls, computer labs, and classrooms with room IDs, display names, seated capacity, and allowed event types (`Lecture`, `Computer Lab`, `Auditory/Classes`, `Specialized Lab`).
3. **Step 3: Curriculum (Courses & Modules)**
   - Specify subject names, ECTS credits, contact hours per week, duration (e.g. 90 or 45 min), required facility type, delivery format (`Lecture`, `Lab`, `Class`, `Seminar`, `Project`), and target student groups.
4. **Step 4: Academic Staff (Instructors)**
   - Enter lecturers and professors, maximum daily and weekly teaching hours, course qualifications, and forbidden availability windows (e.g. Dean's hours, leaves).
5. **Step 5: Subgroups & Conflict Rules**
   - Create custom student subgroups (e.g. elective modules, language cohorts) and explicit disjoint rules preventing two courses or groups from colliding.
6. **Step 6: Time Horizon & Global Rules**
   - Configure working days (Monday–Friday), daily operating hours (e.g. 08:00–20:00), time grid slot duration (15 min), student daily workload limits, solver timeout, and soft optimization toggles.

---

## ⌨️ Keyboard Shortcuts Reference

### 1. Graphical User Interface (GUI)

| Shortcut | Scope | Action |
|---|---|---|
| `Ctrl+M` / Mode Buttons | Top Bar | **Toggle Mode** — Switch between Schedule Editor and Generator Wizard |
| `Ctrl+O` | Global | **Browse & Load File** — Open file picker to select a timetable PDF |
| `Ctrl+S` | Global | **Save & Regenerate PDF** — Generate updated `output.pdf` and `modified.json` |
| `Delete` / `Backspace` | Table / Wizard | **Delete Slot / Step Back** — Delete selected slot or return to previous wizard step |
| `Enter` / `Return` | Table / Wizard | **Edit Slot / Next Step** — Open slot editor or advance wizard step |
| `Ctrl+Enter` | Wizard | **Solve Schedule** — Run the CP-SAT solver on current wizard configuration |
| `Escape` | Global | **Cancel / Deselect** — Dismiss modals or step back in wizard |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Editor | **Cycle Weekday Tabs** — Switch between Monday–Friday |

### 2. Terminal User Interface (TUI)

| Key | Mode / Menu | Action |
|---|---|---|
| `1` | Main Menu | Launch **Schedule Editor** |
| `2` | Main Menu | Launch **Schedule Generator Wizard** |
| `1` .. `6` | Wizard Menu | Open and edit Steps 1 to 6 |
| `p` | Wizard Menu | **Load Default UWM Preset** (Computer Science Year 4) |
| `r` | Wizard Menu | **Run CP-SAT Solver** and export artifacts |
| `v`, `a`, `e`, `d` | Editor Menu | View, Add, Edit, Delete class slots |
| `s`, `l`, `q` | Editor Menu | Save PDF, Load PDF, Quit |

---

## 📊 Automated CP-SAT Solver Mechanics

The solver engine (`src/core/scheduler.py`) maps the academic timetable problem onto integer variables and interval variables in Google OR-Tools:

```
+-----------------------------------------------------------------------+
|                        Google OR-Tools CP-SAT                         |
+-----------------------------------------------------------------------+
| Hard Constraints:                                                     |
|   • Room Non-Overlap:       AddNoOverlap(room_intervals)              |
|   • Instructor Non-Overlap: AddNoOverlap(instructor_intervals)        |
|   • Student Non-Overlap:    AddNoOverlap(group_attending_intervals)   |
|   • Subgroup / Cohort:      AddNoOverlap across shared parent groups  |
|   • Forbidden Windows:      AddNoOverlap with instructor off-hours    |
|   • Daily Student Limit:    sum(task_durations) <= max_daily_slots    |
|   • Weekly Staff Limit:     sum(task_durations) <= max_weekly_slots   |
|                                                                       |
| Soft Optimization Objectives (Minimization):                         |
|   • Student Idle Gaps:      Sum of idle gaps between classes          |
|   • Worker Daily Spans:     Minimizing spread between first/last class|
|   • Single-Class Days:      Penalizing days with only 1 class         |
+-----------------------------------------------------------------------+
```

When a solution is found, the solver formats the output into `Timetable` domain models and triggers vector PDF compilation through ReportLab.

---

## 📁 Artifact Storage & Output Structure

Every run stores isolated, timestamped outputs under `./output/` or a custom `--output-dir`:

```text
output/
└── 2026-10-02_11-30-00_generated_schedule/
    ├── execution.log             # Solver audit log with timings and diagnostics
    ├── schedule_students.json    # Complete student timetable data
    ├── schedule_workers.json     # Complete faculty timetable data
    ├── student_IV_ROK_-_Specjalność_Ogólna.pdf  # Student vector timetable PDF
    ├── staff_Dr_inż._Tomasz_Nowak.pdf           # Staff timetable PDF
    ├── staff_Dr_hab._Jan_Kowalski_prof._UWM.pdf # Staff timetable PDF
    ├── staff_Prof._dr_hab._inż._Adam_Wiśniewski.pdf
    └── staff_Mgr_inż._Anna_Zielińska.pdf
```

---

## 🧪 Automated Testing Suite

The project includes an end-to-end testing suite organized with `pytest`:

```text
tests/
├── conftest.py          # Shared fixtures (dummy academic data, reference PDFs, synthetic timetables)
├── test_parser.py       # PDF parsing accuracy and dynamic layout extraction
├── test_scheduler.py    # CP-SAT solver constraint enforcement & zero-collision audit
├── test_generator.py    # PDF regeneration, vector rendering, and grid alignment
├── test_models.py       # Data validation, serialization/deserialization, and integrity checks
├── test_cli_scheduler.py# CLI mode routing, headless generation, and sample config export
└── test_gui.py          # Tkinter GUI initialization, geometry, clean-slate defaults & lifecycle
```

### Running Tests Locally

Run the complete test suite using `uv`:

```bash
# Run all tests with pytest via uv
uv run pytest

# Run tests with verbose output and coverage
uv run pytest -v
```

Or using standard python in your virtual environment:

```bash
python3 -m pytest -v tests/
```

All 35 tests verify layout extraction, CP-SAT constraint satisfaction, zero-collision compliance, infeasibility handling, vector PDF compilation, and GUI/Tkinter window lifecycle initialization in ~1.6 seconds.

---

## 📄 License

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)** license. See [`LICENSE.md`](file:///home/leonidas/PycharmProjects/UWM_better_schedule/LICENSE.md) for details.

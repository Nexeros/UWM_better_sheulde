# 📅 UWM Better Schedule — Academic Timetable Suite

A production-grade, modular Python application designed to inspect, edit, visually reconstruct, and **automatically generate conflict-free university timetables**. Powered by **Google OR-Tools CP-SAT**, ReportLab vector rendering, and Pydantic v2 validation. Calibrated specifically for the scheduling standards of the University of Warmia and Mazury (UWM Olsztyn).

---

## ⚡ One-Line Launch

You can run the entire application with a single command using [`uv`](https://docs.astral.sh/uv/):

```bash
uv run main.py
```

> [!TIP]
> **Don't have `uv` installed?** Install it in seconds:
> - **Linux & macOS**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
> - **Windows (PowerShell)**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
> 
> Alternatively, if using a standard Python 3.10+ virtual environment:
> ```bash
> pip install -r requirements.txt   # or pip install -e .
> python main.py
> ```

---

## 🧭 Visual Walkthrough & Quick Start

The application features a **Dual-Mode System**:
1. **Schedule Editor Mode**: Load, inspect, modify, and re-export existing timetable PDFs or JSON files.
2. **Schedule Generator Wizard Mode**: Formulate academic constraints and let the automated solver schedule all classes conflict-free.

You can switch modes anytime via the **"Switch to Generator Wizard"** / **"Switch to Schedule Editor"** buttons in the top header or with the shortcut `Ctrl+M`.

---

### Mode A: Schedule Editor (Editing an Existing Timetable)

```
[ Browse & Load PDF ] ➔ [ Select & Double-Click Row to Edit ] ➔ [ Save & Regenerate PDF ]
```

1. **Load a Timetable**:
   - Click **"Browse & Load File"** (`Ctrl+O`) and choose any UWM schedule PDF or JSON file.
   - The days (Monday–Friday) will appear in organized tabs with highlighted course blocks.
2. **Double-Click to Edit**:
   - **Double-click any slot** in the table to open the class editor modal.
   - Modify the subject name, instructor, room, time range, category, or note.
   - Click **Confirm (Enter)** to save changes. Modified entries are automatically highlighted with an amber indicator tag.
3. **Add or Delete Classes**:
   - Use the **"+ Add Slot"** or **"Delete Slot"** (`Delete`) buttons to adjust the schedule.
4. **Export Clean Vector PDF**:
   - Click **"Save & Regenerate PDF"** (`Ctrl+S`). A crisp, publication-ready vector PDF is compiled into the `output/` directory.

---

### Mode B: Schedule Generator Wizard (Automated Timetable Creation)

```
[ Load Test Data ] ➔ [ Fine-Tune Steps 1-6 ] ➔ [ Quick Test & Solve ] ➔ [ Export PDFs & JSON ]
```

1. **Switch to Generator Mode**:
   - Click **"Switch to Generator Wizard"** or launch directly with:
     ```bash
     uv run main.py --mode create
     ```
2. **One-Click Demo Test Data**:
   - Click the **`[ 🧪 Load Test Data ]`** button in the top right.
   - This instantly populates realistic university curriculum data:
     - **2 Academic Years**: Year 3 (*III ROK*) and Year 4 (*IV ROK*).
     - **2 Distinct Specializations**: Software Engineering (*Inżynieria Oprogramowania*) & Information Systems (*Inżynieria Systemów Informatycznych*).
     - **4 Student Base Groups**: G1, G2, G3, G4 with balanced headcounts.
     - **5 Room Facilities**: Auditory halls, classrooms, and specialized computer labs.
     - **4 Academic Instructors**: With realistic maximum daily/weekly limits and forbidden council windows.
     - **9 Curriculum Courses**: Complete with duration, delivery format, room requirements, and breaks.
     - **2 Student Subgroups & Conflict Rules**: Elective modules (*SUB_AI*, *SUB_SEC*) sharing students from base groups without clashes.
     - **2 Course Categories & Colors**: Soft pastel color fills (Soft Blue `#A9CCE3`, Soft Green `#A9DFBF`, Soft Pink `#FADBD8`).
     - **2 Global Background Overlays**: Dean's Hours (*Godziny Dziekańskie*, Wednesday 13:00–15:00) and Rector's Hours (*Okienko rektorskie*, Friday 10:00–12:00).
3. **Step-by-Step Customization (Double-Click Any Row to Edit)**:
   - In all 6 wizard steps, **double-click any item** in the tables to edit it:
     - **Step 1 (Academic Structure)**: Years, Specializations, and Groups.
     - **Step 2 (Facilities)**: Rooms, capacities, and allowed session types.
     - **Step 3 (Curriculum)**: Courses, duration, assigned lecturer, breaks, and visual category.
     - **Step 4 (Academic Staff)**: Teaching hours ceiling and forbidden time windows.
     - **Step 5 (Subgroups & Conflicts)**: Elective tracks, shared cohorts, and explicit collision rules.
     - **Step 6 (Time Horizon & Notes)**: Working days, hours, slot duration, solver timeout, custom canvas remarks, and background overlays.
4. **Solve & Verify**:
   - Click **`[ ⚡ Quick Test & Solve ]`** or **"Solve Schedule"** (`Ctrl+Enter`).
   - The **Google OR-Tools CP-SAT solver** will find an optimal, collision-free solution in a fraction of a second (< 0.2s).
   - An interactive **Verification & Collision Audit Modal** opens, certifying zero room collisions, zero lecturer clashes, and zero student overlap.
5. **Inspect & Export Outputs**:
   - Inspect individual schedules for student cohorts and instructors in the preview tabs.
   - Click **"Export All PDFs and JSONs"** to generate publication-grade vector PDFs and JSON datasets for all student groups and lecturers.

---

## 🎨 Feature & Visual System Reference

### 1. Categories & Colors
- Assign custom visual categories to courses (e.g., *Wykłady ogólnowydziałowe*, *Laboratoria specjalistyczne*).
- Cells are painted with their respective hex background colors before typography is rendered.
- **Split Color Striping**: Courses spanning multiple student groups or categories render vertical split-color striped swatches.

### 2. Background Overlays & Legend Integration
- Define global university-wide time blocks (such as Dean's hours, Rector's hours, or faculty maintenance windows) in Step 6.
- Background overlays appear across the schedule grid with custom colors, opacity, and pattern hatching (**solid**, **diagonal lines**, or **cross**).
- **PDF Footer Legend ("KATEGORIE I KOLORY")**: Background overlays are itemized alongside regular course categories in the footer legend, displaying their matching swatch pattern and descriptive label (e.g., `[Swatch] Godziny Dziekańskie — Wolne od zajęć / Free blocks`).

### 3. Structured 3-Zone Cell Layout
Every timetable cell is rendered with high-readability vector typography divided into three distinct zones:
- **Top Zone (Subject)**: Bold subject title with clean multi-line word wrapping and dynamic auto-fit.
- **Middle Zone (Instructor & Type)**: Regular/italic lecturer name (e.g. *Dr inż. T. Nowak*) and class format (*Wykład*, *Lab*).
- **Bottom Zone (Room Location)**: Horizontally centered, dark gray room tag (*Aula Główna A1*, *Lab 204*) pinned to the bottom of the cell.

### 4. Smart Footnote Legend & Invariance Rule
- If an instructor or room name cannot fit in a tight cell without sacrificing legibility, the system avoids squishing or ugly ellipsis (`...`). Instead, it cleanly abbreviates the title and places a numbered footnote reference (`[*1]`, `[*2]`) in the legend footer.

### 5. In-App Tooltips & Explanatory Help Badges `(?)`
- Unsure what a setting does? Hover your mouse over any blue **`(?)`** badge next to fields in the wizard and dialogs:
  - *Break Before / After*: Minimum mandatory pause or travel buffer before or after a class.
  - *Max Daily Hours*: Upper limit on daily academic contact hours to prevent teacher and student fatigue.
  - *Subgroup Overlaps & Conflict Matrix*: Prevents elective courses that share students from being scheduled at the same time.
  - *Background Overlay Times & Patterns*: Reserved time blocks and visual hatching styles.

---

## ⌨️ Complete Keyboard Shortcuts Reference

| Shortcut | Scope | Action |
|---|---|---|
| `Ctrl+M` | Global | **Switch Mode** — Toggle between Schedule Editor and Generator Wizard |
| `Ctrl+O` | Global | **Open File** — Browse and load a schedule PDF or JSON file |
| `Ctrl+S` | Editor | **Save & Recompile PDF** — Export modified schedule to vector PDF |
| `Double-Click` | Tables | **Edit Selected Row** — Open the edit dialog for the clicked entry |
| `Enter` / `Return` | Tables | **Edit Row** (in tables) or **Confirm** (in modal dialogs) |
| `Delete` / `Backspace` | Tables | **Delete Row** — Remove selected item or slot |
| `Ctrl+Enter` | Wizard | **Solve Schedule** — Trigger CP-SAT solver on current wizard data |
| `Escape` | Modals | **Cancel / Close** — Dismiss active modal dialog without saving |
| `Ctrl+Tab` | Editor | **Next Weekday** — Cycle to the next day tab (Monday ➔ Friday) |
| `Ctrl+Shift+Tab` | Editor | **Previous Weekday** — Cycle to the previous day tab |

---

## 💻 CLI & TUI Batch Automation (Advanced Users)

For headless servers, automated scripts, or terminal enthusiasts:

```bash
# 1. Launch interactive Terminal User Interface (TUI)
uv run main.py --tui --mode create

# 2. Export default generation configuration to JSON
uv run main.py --sample-config my_config.json

# 3. Headless schedule generation from configuration JSON
uv run main.py --create-from-config my_config.json --output-dir ./output

# 4. Headless PDF-to-PDF reconstruction
uv run main.py sample.pdf --headless --output ./output/reconstructed.pdf
```

---

## 📁 Output Directory Structure

Generated artifacts are cleanly separated into timestamped subdirectories inside `output/`:

```text
output/
└── 2026-10-06_12-00-00_generated_schedule/
    ├── execution.log                               # Detailed solver audit trail & performance metrics
    ├── schedule_students.json                      # Machine-readable JSON timetable for students
    ├── schedule_workers.json                       # Machine-readable JSON timetable for instructors
    ├── student_III_ROK_-_Inżynieria_Systemów.pdf    # Vector PDF timetable for Year 3
    ├── student_IV_ROK_-_Inżynieria_Oprogramowania.pdf # Vector PDF timetable for Year 4
    ├── staff_Prof._dr_hab._inż._Adam_Wiśniewski.pdf  # Individual PDF timetable for instructor
    ├── staff_Dr_hab._Jan_Kowalski_prof._UWM.pdf
    ├── staff_Dr_inż._Tomasz_Nowak.pdf
    └── staff_Mgr_inż._Anna_Zielińska.pdf
```

---

## ❓ Troubleshooting & FAQ

### Q1: `_tkinter.TclError: no display name and no $DISPLAY environment variable`
**Cause:** You are running on a remote headless Linux server (e.g. via SSH) without an X11 forwarding or Wayland graphical session.  
**Solutions:**
- **Run the Terminal UI**: `uv run main.py --tui` (requires no GUI display).
- **Run headless batch generation**: `uv run main.py --create-from-config my_config.json`
- **Use a virtual framebuffer**:
  ```bash
  sudo apt-get install -y xvfb
  xvfb-run -a uv run main.py
  ```

---

### Q2: Solver reports `Status: INFEASIBLE (No valid schedule found)`
**Cause:** The mathematical constraints are mutually impossible to satisfy simultaneously.  
**Troubleshooting Tips:**
1. **Facility Capacity**: Check if a course requires a room type that does not exist or has insufficient seating capacity for the assigned student group.
2. **Staff Overload**: Check if an instructor is assigned more teaching hours than their *Max Hours / Day* or *Max Hours / Week* settings allow.
3. **Forbidden Windows Clashing**: If an instructor is forbidden from teaching on certain days/hours, verify that their remaining available hours are sufficient for all their required courses.
4. **Room Congestion**: If you have 6 simultaneous computer labs scheduled at 08:00 but only 2 computer lab rooms, the solver cannot schedule them. Add more rooms or loosen delivery format constraints.
5. **Increase Timeout**: In Step 6, increase *CP-SAT Solver Timeout* from 10s to 30s for complex timetables.

---

### Q3: Double-clicking in an empty area of the table
- Double-clicking blank space in any table or list view safely does nothing; edit dialogs only open when an actual row is clicked.

---

### Q4: Are external system fonts required?
- No! All PDF vector graphics use ReportLab's standard built-in font metrics (`Helvetica`, `Helvetica-Bold`, `Helvetica-Oblique`), guaranteeing identical rendering on Windows, macOS, and Linux without installing external font files.

---

## 🧪 Running the Automated Test Suite

The test suite contains 64 comprehensive tests covering the full pipeline:

```bash
# Run all tests via uv
uv run pytest -v

# Or via standard python in your virtual environment
python3 -m pytest -v
```

All 64 tests pass with zero warnings in ~10 seconds.

---

## 📄 License

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)** license. See [`LICENSE.md`](file:///home/leonidas/PycharmProjects/UWM_better_schedule/LICENSE.md) for details.

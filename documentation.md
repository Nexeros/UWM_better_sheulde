# The Stone-Age Guide to UWM Better Schedule 🦣📅
*A complete, beginner-friendly walkthrough for human beings who just want their university timetable fixed or generated from scratch without getting a headache.*

---

## 1. Why Does This Program Exist? (The Problem We Solve)

If you are a student, teacher, or dean's office coordinator at the University of Warmia and Mazury (UWM), you are probably very familiar with this sight:
Every semester, timetables are published as **giant PDF documents exported from spreadsheets (like LibreOffice Calc or Excel)**. 

While they look okay on a huge monitor if you zoom in 300%, they are a nightmare in real life:
- **Tiny, cramped text:** Important room numbers and teacher names are squished into micro-cells.
- **Impossible to edit:** If a class time changes or you want to delete a lecture you aren't attending, you have to recreate the whole table from scratch.
- **Unfriendly to calendar apps:** You can't just copy-paste the schedule into Google Calendar or Notion without manually typing every single subject, hour, and room.
- **Messy layout bugs:** Columns misalign, rows have uneven heights, and printing them on a standard sheet of paper often cuts off half the text.
- **The Timetable Creation Nightmare:** Building a brand-new semester timetable by hand without teachers having two classes at once, without two groups ending up in the same computer lab, and without students having 5-hour empty gaps ("okienka") takes weeks of painful spreadsheet juggling.

**UWM Better Schedule** is here to fix that once and for all:
1. **Mode 1 — Schedule Editor:** It reads messy university PDF timetables, lets you edit them, and rebuilds high-resolution, bold-room PDFs.
2. **Mode 2 — Schedule Generator Wizard:** It uses **Google's world-class CP-SAT mathematical solver** to automatically construct collision-free schedules for all student groups and lecturers in less than a second!

---

## 2. What the Program Does (In Plain English)

Imagine you have two super-smart assistants sitting on your desk:

### Assistant A: The Schedule Editor 📅
- Reads an existing UWM timetable PDF.
- Shows you what classes are happening on Monday, Tuesday, Wednesday, Thursday, and Friday.
- Lets you add, edit, or delete any class with simple clicks.
- Re-draws a crisp vector PDF with bold rooms and clean colors when you hit `Ctrl+S`.

### Assistant B: The Schedule Generator Wizard 🪄
- Asks you 6 simple questions (What classes do you have? Who teaches them? What labs exist? When are teachers busy?).
- Feeds all these rules to an automated mathematical brain (CP-SAT).
- Solves the entire puzzle in 0.03 seconds!
- Gives you ready-to-print PDFs for every student group AND personalized timetable PDFs for every teacher!

---

## 3. How to Launch It (One Simple Command)

You only need **one single command** typed into your terminal:

```bash
uv run main.py
```

- If you want to jump straight into the **Generator Wizard**:
  ```bash
  uv run main.py --mode create
  ```
- If you want the **Interactive Terminal Menu (TUI)**:
  ```bash
  uv run main.py --tui
  ```

---

## 4. Switching Modes (Editor vs Generator)

At the top of the graphical window, you will always see two mode buttons:
```
[ 📅 Schedule Editor ]    [ 🪄 Schedule Generator Wizard ]
```
Click either button (or press `Ctrl+M`) to switch instantly between editing an existing timetable and generating a new one from scratch!

---

## 5. Mode 1: Editing Existing Schedules

### Method A: The "Drop and Forget" Folder (Easiest!)
1. Drop your timetable PDF into the `input/` folder in the project directory.
2. Run `uv run main.py`.
3. It opens automatically!

### Method B: The "Browse" Button
1. Click **📁 Browse / Load File...** (or press `Ctrl+O`).
2. Select any PDF timetable on your computer.

### Editing, Deleting, and Adding Classes
- **Edit:** Click any class, press `Enter`, change what you want, and save.
- **Delete:** Click any class, press `Delete` or `Backspace`.
- **Add:** Click **+ Add Slot**, fill in the details, and press `Enter`.
- **Save:** Click **Save & Regenerate PDF** (or press `Ctrl+S`).

---

## 6. Mode 2: Generating a New Schedule from Scratch (6-Step Wizard)

Click **🪄 Schedule Generator Wizard** and follow the step-by-step progress bar:

### Step 1: Academic Structure (Who are the students?)
- Define your study cycle (e.g. *stacjonarne inżynierskie I-go stopnia*).
- Add academic years (e.g. *IV ROK*).
- Define student groups (e.g. *Grupa 1* with 16 students, *Grupa 2* with 16 students).
- *The program automatically checks that group counts don't exceed your specialization limits!*

### Step 2: Facilities (Where can classes happen?)
- Add your lecture halls (e.g. *Aula A1*, capacity 60).
- Add computer labs (e.g. *E 1/16*, capacity 20).
- Add general classrooms.
- *The solver makes sure no two classes ever share the same room at the same time.*

### Step 3: Curriculum (What courses need to be taught?)
- Enter subjects like *Testowanie oprogramowania* or *Programowanie w UNITY*.
- Set session duration (e.g. 90 minutes) and required room type (*Computer Lab*, *Lecture Hall*).
- Specify whether the whole year attends together or if it's split into separate group labs.

### Step 4: Academic Staff (Who is teaching?)
- Add lecturers and professors (e.g. *Dr hab. Jan Kowalski*, *Prof. Adam Wiśniewski*).
- Set their maximum daily and weekly teaching hours.
- Set their **forbidden windows** (e.g. *Prof. Kowalski has Faculty Council every Friday after 14:00 and cannot teach then*).

### Step 5: Subgroups & Conflict Rules (Special conditions)
- Add elective subgroups (students from Group 1 and Group 2 taking an elective track together).
- Add custom conflict rules (e.g. *Unity Lecture must never happen at the same time as Unity Lab*).

### Step 6: Time Horizon & Global Rules (When does school happen?)
- Select working days (Monday through Friday).
- Set daily school hours (e.g. 08:00 to 20:00).
- Check the optimization options:
  - **Minimize Student Gaps:** Eliminates boring 3-hour waiting gaps between classes.
  - **Minimize Worker Gaps:** Groups teacher hours tightly together so they don't have to wait around.
  - **Prevent Single-Class Days:** Avoids making students come to university for just one 45-minute class.

### Solving the Puzzle!
Click **⚡ Solve Schedule** (or press `Ctrl+Enter`):
- The mathematical solver will run in ~0.03 seconds.
- You will see a success message showing the exact number of classes scheduled.
- Click **Yes** to instantly preview your newly solved timetable inside the visual editor!

---

## 7. Headless CLI Generation (For Scripts & Automation)

If you love the terminal or want to run schedule generation on a remote server:

```bash
# Export the pre-built UWM Computer Science Year 4 configuration template
uv run main.py --sample-config my_config.json

# Run the automated solver and export all files
uv run main.py --create-from-config my_config.json --output-dir ./output
```

---

## 8. Where to Find Your Finished Files (The Output Folder)

Every time you generate or save a schedule, a new timestamped folder appears inside `./output/`:

```text
output/2026-10-02_11-30-00_generated_schedule/
├── execution.log             # Full diary of how the solver calculated the schedule
├── schedule_students.json    # Complete student timetable data
├── schedule_workers.json     # Complete teacher timetable data
├── student_IV_ROK_-_Specjalność_Ogólna.pdf  # Ready-to-print student schedule PDF!
├── staff_Dr_inż._Tomasz_Nowak.pdf           # Personalized schedule for Dr Nowak!
├── staff_Dr_hab._Jan_Kowalski_prof._UWM.pdf # Personalized schedule for Prof. Kowalski!
└── ...
```

---

## 9. Summary Cheat Sheet for Keyboard Ninjas

| What You Want To Do | Keyboard Key |
|---|---|
| Toggle Editor / Generator Mode | `Ctrl + M` (or click top mode buttons) |
| Open a new PDF schedule | `Ctrl + O` |
| Save and make new PDF | `Ctrl + S` |
| Advance to Next Wizard Step | `Enter` |
| Go back to Previous Wizard Step | `Escape` (`Esc`) or `Backspace` |
| Solve the Generation Wizard | `Ctrl + Enter` |
| Delete highlighted class slot | `Delete` or `Backspace` |
| Edit highlighted class slot | `Enter` |
| Switch between weekday tabs | `Ctrl + Tab` |

*That's literally everything you need to know. You have the ultimate university scheduling powerhouse at your fingertips! 🎓🚀*

# The Stone-Age Guide to UWM Better Schedule 🦖📅
*A complete, beginner-friendly walkthrough for human beings who just want their university timetable fixed without getting a headache.*

---

## 1. Why Does This Program Exist? (The Problem We Solve)

If you are a student or teacher at the University of Warmia and Mazury (UWM), you are probably very familiar with this sight:
Every semester, timetables are published as **giant PDF documents exported from spreadsheets (like LibreOffice Calc or Excel)**. 

While they look okay on a huge monitor if you zoom in 300%, they are a nightmare in real life:
- **Tiny, cramped text:** Important room numbers and teacher names are squished into micro-cells.
- **Impossible to edit:** If a class time changes or you want to delete a lecture you aren't attending, you have to recreate the whole table from scratch.
- **Unfriendly to calendar apps:** You can't just copy-paste the schedule into Google Calendar or Notion without manually typing every single subject, hour, and room.
- **Messy layout bugs:** Columns misalign, rows have uneven heights, and printing them on a standard sheet of paper often cuts off half the text.

**UWM Better Schedule** is here to fix that once and for all:
1. It **reads** the messy, complicated university PDF timetable.
2. It **converts** it into clean, neat computer data (JSON).
3. It lets you **edit, add, or remove** any classes using simple clicks and keyboard buttons.
4. It **rebuilds a brand new, crisp vector PDF** with bold room numbers, perfectly aligned group rows, and beautiful colors ready for printing or your phone.

---

## 2. What the Program Does (In Plain English)

Imagine you have a magic assistant sitting on your desk:
1. You hand the assistant an official UWM timetable PDF.
2. The assistant reads every line:
   - *"Aha! On Monday from 14:00 to 15:30, both groups have 'Aplikacje WWW' in room C0/1 with lecturer Ropiak K."*
3. The assistant presents a neat window with tabs for **Monday, Tuesday, Wednesday, Thursday, and Friday**.
4. You can say: *"Remove this class,"* or *"Add a new workshop on Friday,"* or *"Change the room number."*
5. You press one button (or `Ctrl+S`), and the assistant draws a **brand-new, high-resolution PDF timetable** with crisp lines and **bold room numbers** that stand out clearly at a glance!

---

## 3. How to Launch It (One Simple Command)

You do **not** need to install ten different complicated tools. You only need **one single command** typed into your terminal.

### The Magic Command:
```bash
uv run main.py
```

That's it!
- The program will automatically check if you have a graphic screen.
- If you are on a normal computer with a desktop (Windows, Mac, or Linux with a display), it opens the **graphical window (GUI)**.
- If you are running on a server or terminal without a graphical screen, it automatically launches the **interactive terminal menu (TUI)** so you are never stuck.

---

## 4. How to Feed It a PDF File (No Coding Required!)

You don't need to write file paths in computer code. There are two super easy ways:

### Method A: The "Drop and Forget" Folder (Easiest!)
1. Open your computer's regular file explorer (Files, Finder, or Explorer).
2. Go into the project directory and look for the folder named:
   ```text
   input
   ```
   *(If it's not there yet, don't worry! Running the program once creates it automatically).*
3. **Drag and drop** your university timetable PDF (for example, `IV-io 2gr zima 2026.pdf`) right inside the `input` folder.
4. Launch the program with `uv run main.py`.
5. The program **automatically finds your newest PDF** and opens it right up!

### Method B: The "Browse" Button (Like Any Normal App)
1. Launch the program: `uv run main.py`.
2. At the top of the window, you will see a button that says:
   **📁 Browse / Load File...** (or simply press `Ctrl+O` on your keyboard).
3. A standard file selection window pops up.
4. Click on whatever PDF schedule you want to open, and click **Open**.
5. Boom! Your schedule appears instantly on your screen.

---

## 5. How to Edit Schedules with Mouse Clicks & Keyboard Keys

Once your timetable is loaded, you can manage it with zero stress:

### Looking at Your Week
- Along the top of the schedule view, you'll see tabs for each day: **Monday**, **Tuesday**, **Wednesday**, **Thursday**, **Friday**.
- Click any day to see all classes scheduled for that day.
- Or use `Ctrl+Tab` on your keyboard to flip through the days like a notebook.

### Editing a Class
1. Click on any class row you want to change.
2. Click **Edit Selected** (or just press the `Enter` key on your keyboard!).
3. A little popup window will appear with all the details:
   - *Subject name*
   - *Hours (e.g. 08:15-09:45)*
   - *Instructor name*
   - *Room number*
   - *Class type (Lecture, Lab, Seminar, Project)*
4. Change whatever you want, and click **Confirm** (or press `Enter`).

### Deleting a Class
1. Click on the class you want to remove.
2. Click **Delete Selected** (or press the `Delete` or `Backspace` key on your keyboard).
3. The program will ask: *"Are you sure you want to delete this class?"*
4. Confirm, and it's gone!

### Adding a New Class
1. Go to the day where you want to add the class.
2. Click the **+ Add Slot** button.
3. Fill in the details in the popup window.
4. Press `Enter` or click **Confirm**. Your new class is added and sorted into the right time slot automatically!

### Clearing a Mistake
- Selected the wrong thing? Just hit the `Escape` (`Esc`) key on your keyboard to clear the selection.

---

## 6. Saving and Getting Your New PDF Timetable

When you are happy with your schedule:
1. Click the button at the bottom right: **Save & Regenerate PDF** (or press `Ctrl+S`).
2. A friendly popup will tell you that your new timetable has been created!

---

## 7. Where to Find Your Finished Files (The Output Folder)

Every time you save or run the program, it creates a dedicated, organized time-stamped folder inside the:
```text
output/
```
directory.

Inside `output/`, you will see folders named like this:
```text
output/2026-10-02_09-30-00_IV-io_2gr_zima_2026/
```

Inside that folder, you have everything:

| File Name | What It Is |
|---|---|
| 📄 **`output.pdf`** | **Your shiny, brand-new timetable PDF!** Double-click to open it, print it, or save it to your phone. All room numbers are in bold for quick reading. |
| 📋 **`modified.json`** | The complete timetable data in clean computer format, including any changes you made. |
| 📑 **`extracted.json`** | A backup of the timetable exactly as it was originally read from the input PDF before your changes. |
| 📝 **`execution.log`** | A text diary explaining everything the program did step-by-step (handy if you ever want to check what happened). |

---

## 8. Summary Cheat Sheet for Keyboard Ninjas

| What You Want To Do | Keyboard Key |
|---|---|
| Open a new PDF schedule | `Ctrl + O` (or `Cmd + O` on Mac) |
| Save and make the new PDF | `Ctrl + S` (or `Cmd + S` on Mac) |
| Delete the highlighted class | `Delete` or `Backspace` |
| Edit the highlighted class | `Enter` |
| Cancel or unselect | `Escape` (`Esc`) |
| Move up and down classes | `Up Arrow` / `Down Arrow` |
| Switch between days | `Ctrl + Tab` |

*That's literally everything you need to know. You are now a master of your university timetable! 🎓🚀*

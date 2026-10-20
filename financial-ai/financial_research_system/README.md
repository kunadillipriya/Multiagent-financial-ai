# Multi-Agent Financial Research System

A plain-English guide. No coding knowledge needed — just follow the steps
in order.

---

## Part A — One-time setup (about 10 minutes)

### Step 1: Install Python
1. Go to **python.org/downloads**
2. Click "Download Python" (version 3.10 or newer)
3. Run the installer.
   - **Windows: important** — tick **"Add Python to PATH"** before clicking Install.
   - Mac/Linux: just follow the installer prompts.

### Step 2: Get the project folder
If you were given a zip file, right-click it and choose **"Extract All"**
(Windows) or double-click it (Mac). Put the resulting
`financial_research_system` folder somewhere easy to find, like your Desktop.

> **If you already had an older copy of this project:** delete that old
> folder completely first. Never mix files from two different versions —
> always use a fresh, complete extraction. (See Troubleshooting below if
> you're here because of an error message.)

### Step 3: Open a terminal in that folder
- **Windows:** Open the folder in File Explorer, click the address bar,
  type `cmd`, press Enter.
- **Mac:** Open the folder in Finder → **Applications → Utilities →
  Terminal**, type `cd ` (with a trailing space), drag the folder into the
  terminal window, press Enter.

### Step 4: Install requirements
```
pip install -r requirements.txt
```
Wait for it to finish — a lot of text scrolling by is normal.

### Step 5: Start the system
```
python run.py
```
Wait for the line `Application startup complete.` **Leave this window open.**

### Step 6: Open it in your browser
```
http://127.0.0.1:8000/
```
This opens the chat-style interface. (`http://127.0.0.1:8000/docs` opens
the raw API control panel, useful for the evaluation report — see below.)

---

## Part B — Using the system

1. **Workspace tab** — create a workspace (e.g. "My MBA Coursework").
2. **Session tab** — create a session inside it (e.g. "Sector Comparison").
3. **Load the 3 sample companies** — one click loads Aurora Technologies,
   Nova Foods, and Meridian Health, running the full agent pipeline
   (Document → Extraction → Red Flag) on each automatically.
4. **Chat tab** — ask questions like *"What was Aurora's revenue growth and
   does Meridian have debt concerns?"* The Research Agent splits multi-part
   questions, retrieves the relevant passages, and cites its sources.
5. **Documents tab** — upload your own `.txt`, `.pdf`, or `.docx` financial
   document. **Only real financial documents are accepted** (annual
   reports, 10-K/10-Q filings, earnings releases, financial statements) —
   anything else (a recipe, a letter, an unrelated PDF) is automatically
   rejected with a clear explanation, so it never pollutes your research
   session with irrelevant data.
6. **Red Flags tab** — every anomaly the Red Flag Agent found (rising debt,
   falling margins, auditor language, etc.), with severity and the exact
   source passage.
7. **Compare tab** — every company in the session ranked side-by-side on
   each metric.
8. **Report Preview tab** — the full 5-section report (Executive Summary,
   Key Financials, Red Flags, Comparison, Outlook). Click **"Download
   PDF"** to save it as an actual PDF file you can share or print.

### Checking the system's own accuracy (the evaluation report)
Open `http://127.0.0.1:8000/docs`, find **GET
/sessions/{session_id}/evaluate**, click "Try it out," enter your session's
number, and Execute. This scores the Extraction Agent and Red Flag Agent
against a hand-verified answer key for the 3 sample companies, reporting:
- **Accuracy** (precision/recall/F1) — did the agents find the right things?
- **Source faithfulness** — does every cited passage actually say what the
  agent claims? (Currently 100% on both agents.)

### Running the automated test suite
This checks the *entire system* end to end — not just one session — using
a temporary, throwaway copy of the data so it never touches your real
workspaces. From the project folder, with the server **stopped** (or in a
second terminal window), run:
```
python run_tests.py
```
It prints a PASS/FAIL line for every check (agent collaboration, extraction
correctness, citation accuracy, report completeness) and a summary at the
end. Currently: **40/40 checks pass.**

---

## What's built

- Workspace & session management
- **Document Agent** — upload, parse (.txt/.pdf/.docx), chunk, index —
  now with a financial-document filter that rejects non-financial uploads
- **Extraction Agent** — automatic metric extraction, tolerant of varied
  real-world label wording ("Revenues" vs "Net Sales" vs "Total Revenue", etc.)
- **Red Flag Agent** — rising debt, falling margins, weakening liquidity,
  negative cash flow, auditor language (material weakness, going concern,
  litigation, recalls, debt covenants, rising DSO)
- **Orchestration layer** — Document → Extraction → Red Flag run
  automatically, in order, with per-stage error handling
- **Comparison Agent** — side-by-side benchmarking across companies
- **Research Agent** — multi-part questions, multi-step retrieval, cited answers
- **Chat-style web interface** with Chat, Documents, Red Flags, Compare,
  and Report Preview tabs
- **Report Agent (complete)** — all 5 sections, exportable as a real PDF
- **Evaluation harness** (`/sessions/{id}/evaluate`) — accuracy and
  faithfulness scoring against a hand-verified answer key
- **End-to-end test suite** (`run_tests.py`) — tests the whole system
  through its real API, isolated from your real data

---

## Troubleshooting

- **`ImportError: cannot import name '...' from 'app'`** (or any similar
  "cannot import name" / "No module named" error) → Your folder has an
  incomplete or mixed-up set of files, usually from copying individual
  files into an older folder. **Fix:** delete the entire
  `financial_research_system` folder, re-extract the zip fresh, and run it
  from that new folder without copying anything in or out first.
- **"pip is not recognized" / "python is not recognized"** → Python wasn't
  added to PATH during install. Reinstall Python and tick that checkbox.
- **The browser page won't load** → Make sure the terminal from Step 5 is
  still open and still shows "Application startup complete." If closed,
  run `python run.py` again.
- **"Port already in use"** → Another copy is already running. Close other
  terminal windows and try again.
- **My document got rejected and I think it shouldn't have been** → The
  rejection message explains exactly why (how many financial terms, data
  lines, and filing-language phrases it found vs. needed). If it's a real
  financial document that happens to use unusual formatting, this is a
  known limitation worth refining further — the filter looks for standard
  financial vocabulary and "Label: value" style data lines.
- **Uploaded document shows an error** → Only `.txt`, `.pdf`, and `.docx`
  are supported, and the file needs an actual readable text layer (a
  scanned image PDF with no text layer won't work yet).

## Where things are stored
Everything is saved inside the `data/` folder, created automatically on
first run. Nothing is sent to the internet — this runs entirely on your
own computer.

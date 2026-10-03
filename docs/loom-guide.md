# Loom Guide — Feature Tour of the English–Polish Vocabulary Platform

Record one Loom (screen + microphone) showing every feature behind the
post-acceptance BRD gaps. Target **6–8 minutes**, no cuts that skip a
section. Use Chrome, full window (not maximised), dark mode.

## Pre-recording setup

1. Start the stack the same way the client uses it (README §4):
   - backend: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
   - frontend: `cd frontend && pnpm dev` → `http://localhost:3000`
2. Log in as the teacher (bootstrap account).
3. Open the **exact URLs** below, one per section. Keep them in separate
   tabs so you can jump straight to each feature:
   - Login: `/login`
   - Dashboard: `/dashboard`
   - Vocabulary: `/vocabulary`
   - Set detail: `/sets` → open any set **and** its "Review set" link
   - Student: `/students` → open any student, then its review link
   - Shortcuts: `/settings/shortcuts`
   - Backup: Task Scheduler (`taskschd.msc` on Windows) or `crontab -l`
4. Prepare the data: one student with assignments, at least one overdue
   due card, one difficult card, one `reliable` translation (search
   `translation_availability=reliable`), and one `uncertain` one. Use the
   API or the UI to set this up once — it makes the tour honest.
5. Mute everything except your voice. Never show the browser address bar
   during the tour.

## Walkthrough script

### 0:00 — Title card + what you're showing
One sentence: *"This is the teacher-facing vocabulary platform. I'll walk
through search, copy, sets, assignment, review with FSRS, the dashboards,
configurable shortcuts, and the automatic backups."* Then go straight to
`/login` (do not show the bootstrap create-account screen in detail).

### 0:20 — Login & teacher scope
- Log in with the teacher account.
- Show that the URL is `localhost:3000`, and point at the session bar.
- Explain: **students do not log in** — the teacher copies vocabulary to
  them as text (§23/§37). This is the single most important security
  point for the client.

### 0:45 — Dashboard (§98 + §36)
Open `/dashboard`.

- Call out: **who needs review next sorts to the top** (overdue →
  due → name), decided server-side.
- Read the six totals (Overdue / Due today / Learning / Reviewing /
  Mastered / Assigned) from the chips.
- Click a student's **Review** button and confirm it lands on
  `/students/<id>/review`.
- On the student profile, show the **Review dashboard** panel: counts,
  "What should I review next?", **Difficult** list with
  "Review difficult" link, and **Recent reviews**. The `difficult=yes`
  URL param is the live demo.
- Explain the split: the roster dashboard answers *who needs attention*;
  the student profile answers *what should I review next* (§1201).

### 1:40 — Vocabulary table (§20/§21/§22/§23)
Open `/vocabulary`.

- Type a topic phrase, e.g. **"things needed when traveling"**, and show
  it returns travel vocabulary even though the phrase never appears
  verbatim (§21 fallback).
- Switch modes: `lexical` ↔ `semantic` ↔ `hybrid`. Read the table as a
  whole — no client-side truncation; SQL orders the full filtered set.
- Switch sort: `relevance`, `headword`, `polish`, `cefr`, `topic`,
  `pos`, `priority`, `frequency`, `student_status`.
- Point at the shareable URL: the query, filters, sort and page are in the
  URL, so a teacher can send a colleague a one-click view.
- Open **FilterPanel**; walk the facets: CEFR, POS, priority (incl.
  HIGH+), topic category subtree, frequency bands, flags, student
  assignment, learning state, due/difficult/teacher-priority, and
  **translation availability**.

### 3:30 — Translation availability (§42)
Still in the vocabulary table, use the filter:

- `missing` — no translation row at all.
- `multiple` — more than one translation.
- `reliable` — at least one cognate-or-better alignment
  (`confidence >= 0.50`).
- `uncertain` — has translations, but only low-confidence ones
  (0.35 fallback; D007 live confidences are 0.50 / 0.35 / NULL).
- Be honest here: the live corpus's reliable confidences are exactly
  0.50, 0.35 and NULL for D007, so `>= 0.70` would return nothing; the
  UI uses `>= 0.50`. Show the four groups side by side in one filter
  session so the client sees the actual split.
- Explain this was added in Phase 30 (D031) to make Polish quality
  visible at a glance.

### 4:20 — Copy (§20/§37)
- Select 2–3 rows with the checkboxes + **Select all page**.
- Open the **copy** group next to the row count and click the four
  buttons: **EN**, **EN+PL**, **EN+def**, **all**. Read the "Copied N
  senses" confirmation each time.
- After one click, show the paste result in a text editor / chat — this
  is the teacher's delivery channel to students (no login for them).
- Note: the clipboard shows a clear fallback note if the browser blocks
  it (Settings → "Copy" — browser may block; re-try or allow clipboard
  permission).

### 5:05 — Sets (§26) + Assign (§28/§29/§30)
- Open `/sets` and show **Create set** (rename/describe + add items).
- Open a set detail `/sets/<id>`: rename, edit description, remove items,
  and **Assign set** to a student.
- On `/students/<id>` show the assigned list, the student's own
  **Review dashboard**, and the **Filter vocabulary →** link (§30).
- Show the assign response: `new / already_assigned / failed` — duplicates
  are structural, not just reported.

### 5:50 — Review + FSRS (§31–§38)
- On `/students/<id>/review`, read the top bar: **Card N of M**,
  overdue badge, learning state, review count.
- Reveal a card, then rate **HARD / MEDIUM / EASY**.
- Read the "Recorded HARD — next due <date>" line, then the back-button
  behavior: returning to the dashboard/profile shows a **fresh** state
  (invalidation happens on review; back navigation uses the cache).
- Show the URL params: `set=`, `difficult=yes`, `states=`, `search=`.
- Show the footer with the configured shortcut labels and the
  **configure** link.
- Open `/settings/shortcuts` for the next section (leave a few seconds).

### 6:45 — Configurable shortcuts (§35)
- Change the bindings (e.g. reveal `space` → `k`, HARD `1,h` → `2`).
- Save and explain it persists in `localStorage` (`vocab.shortcuts.v1`),
  so it is per-browser and survives page reloads.
- Cover: comma-separated alternatives (`1,h`), `space` token, reset to
  defaults, and the defaults row (reveal `space`, HARD `1/h`, MEDIUM
  `2/m`, EASY `3/e`).

### 7:20 — Automatic backups (§51)
- Open Task Scheduler (Windows) — show the `VocabPlatformBackup` task.
  Alternatively `crontab -l` on Linux/macOS.
- Run `python scripts/install_backup_schedule.py status` / `print`.
- Show the manual procedure: `db_backup.py backup --keep 7`, restore,
  `verify --fresh`. Reference `docs/backups.md` for the full procedure.
- Be honest: backups live **on the same machine by default**; disaster
  recovery needs a manual copy off the machine.

### 8:00 — Done / what to send
- Wrap: the 8 features above are exactly the post-acceptance BRD gap
  closure (search/sort/filters, translation availability, copy, sets,
  assignment, review + FSRS, configurable shortcuts, automatic backups).
- Say the repo is at commit `5fe6129` and `documentation.md` + `docs/`
  hold the client-facing docs. Offer `git archive` of the committed
  source plus `data/backups/*.dump` for client restore.

## Recording checklist (tick before sending)

- [ ] Chrome, local server running, teacher logged in
- [ ] URLs open in separate tabs; no address bar shown
- [ ] Overdue + difficult + reliable/uncertain data ready
- [ ] Clipboard permission allowed (or clipboard fallback shown)
- [ ] Shortcuts demo edits and saves successfully
- [ ] Backup scheduler visible (Task Scheduler or crontab)
- [ ] Audio clear, no UI pop-ups from dev servers
- [ ] Screen resolution not maximized (leaves room for callouts)

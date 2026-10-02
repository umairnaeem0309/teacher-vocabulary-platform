# End-to-End Testing (Phase 27)

Playwright acceptance suite for the teacher workbench — the automated
form of the critical acceptance workflows in `master_prompt.md`
§59 (critical), §60 (duplicates), §61 (semantic search) and §53
(responsive), as required by §103.

## Running the suite

```bash
cd frontend
pnpm exec playwright test                 # everything (7 tests, ~2 min)
pnpm exec playwright test e2e/acceptance.spec.ts   # §59 + §53 only
pnpm exec playwright show-trace test-results/<test>/trace.zip
```

Prerequisites: the PostgreSQL database with the imported vocabulary and
the `uv` Python environment available (backend directory), plus the
system Chrome (`channel: "chrome"`). The suite **starts its own
servers** and tears them down afterwards:

| Service   | How                                                       |
| --------- | --------------------------------------------------------- |
| backend   | `uv run uvicorn app.main:app --port 8737` — reused if already healthy |
| frontend  | `pnpm dev --port 3000` with `NEXT_PUBLIC_API_URL=http://localhost:8737` — **always restarted**, never a stale `next start` build (D029) |

Both hosts are `localhost` on purpose: the page and the API must be
same-site or the `SameSite=Lax` session cookie is never attached to the
fetches and every authenticated call 401s.

## How a run works

1. **Global setup** (`e2e/global-setup.ts`) runs
   `scripts/phase27_seed_acceptance.py` against the database:
   idempotent acceptance teacher (`acceptance@example.com`), a clean
   slate for that teacher, and student **John** with 6 genuinely overdue
   FSRS cards (§59 step 14 needs real DUE rows; steps 21–22 need due
   counts that can move).
2. The seed also mints a session token server-side; setup writes it to
   `e2e/storage-state.json` (Git-ignored) and every test context starts
   already authenticated. Exactly one test — §59's "login as teacher" —
   performs a real HTTP login, keeping each run inside the §39 login
   rate limit (10 per 5 min per IP) even across quick re-runs.
3. Tests run serially (`workers: 1`): one teacher account, one database.

## Coverage map (§103 areas → where they are tested)

| Area                | Automated coverage                                                    |
| ------------------- | --------------------------------------------------------------------- |
| authentication      | §59 step 1 (UI login) + backend `test_auth*`                          |
| students            | §59 steps 8/13 (student picker, profile), §60 creates a student       |
| vocabulary / sense identity | §59 steps 2–4 (browser), §60 (master sense ID as identity)     |
| exact / semantic / hybrid search | §59 step 3–4, §61 (six §21 queries + composition)     |
| filters / sorting   | §59 steps 5–9, 14; §61 combined filters; unit tests for URL state     |
| selection / assignment | §59 steps 10–12 (bulk select + §29 report)                         |
| sets                | §60 path 5 (new set from the table chip → assign set)                 |
| duplicates          | §60 (five discovery paths → one record; two senses → two records)     |
| not-assigned        | §59 step 9, §61 (`assigned: false` disjoint from John's records)      |
| learning states     | §59 steps 13–22 (REVIEWING → review flow), FilterPanel controls       |
| review / FSRS       | §59 steps 15–20 (reveal, EASY, "Recorded EASY — next due …")          |
| dashboard           | §59 steps 21–22 (due counts + recent reviews refresh after a review)  |
| import / export     | backend pytest + `ImportExportPanel` unit surface                     |
| security            | backend `test_security.py` (rate limit/CSRF/headers/authz)            |
| backup / restore    | backend `test_backup_tools.py` + `docs/backups.md` (Phase 26)         |
| responsive behavior | §53 viewport tests (1440/1280/768, no horizontal overflow)            |

## Design notes (D029)

- **Fixtures are the real corpus.** No synthetic vocabulary rows: the
  §61 assertions run against the 41,687-sense production build with its
  bge-m3 embeddings; §60 resolves the two BANK senses by their real
  definitions (`place and borrow money` / `edge of river`).
- **UI + API in one test.** §60 drives discovery through the actual
  workbench/sets UI, then asserts the §29 invariant against
  `GET /students/{id}/vocabulary` record counts — the count is the
  contract, the path must not change it.
- **URL-driven controls.** The filter panel is fully URL-state based, so
  checks use click + retrying `toBeChecked()` instead of `check()`'s
  single post-click read (the controlled re-render lands a tick later).
- **Rate limits are respected, not disabled**: one seed-minted session
  for the suite + one real login in §59.

## Debugging

- `test-results/<test-name>/error-context.md` contains the failure plus
  a page snapshot; the trace zip shows network and DOM timeline.
- If the frontend appears with dead API calls, a stale production
  `next start` was probably on :3000 — the config refuses to reuse it
  (`reuseExistingServer: false`); kill the process and rerun.
- The seed is idempotent; rerunning the suite always starts from the
  same state for the acceptance teacher.

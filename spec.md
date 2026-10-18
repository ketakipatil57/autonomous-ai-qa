# SPEC: Autonomous AI QA Engineer (Prototype)

Team: Tower of Hanoi | Event: VIT Code_Apex 3.0 | iMocha Track 2, IM-02

## 0. How you (the coding agent) must work

1. Read this entire spec before writing code.
2. First produce a short written PLAN: folder structure, milestones, and any assumptions. Ask me to confirm only if something is truly blocking. Otherwise state your assumption and continue.
3. Build milestone by milestone (Section 12). After each milestone: run the tests, fix failures, and show me the result before moving on.
4. Never claim a feature works unless you ran it and it passed. Never invent evaluation numbers. Evaluation numbers must come from actually running the evaluation script.
5. Do NOT use Spring Boot. The backend is FastAPI (Python). The frontend is React.
6. Keep everything runnable on a laptop: Windows, macOS or Linux, with clear README steps.
7. Prefer simple, readable code over clever abstractions. Add docstrings and type hints.

---

## 1. Goal

Build a working prototype of an AI-assisted QA tool. A user provides:
- an application URL (for example http://localhost:3000 or a deployed https URL),
- an optional application description,
- an optional specific test instruction (for example "Test login with a wrong password").

The system then:
- Branch A: if a specific test instruction is given, skip broad exploration and generate tests directly from it.
- Branch B: if no specific test instruction is given, use Playwright to explore the site, identify key user journeys, and generate tests from those.
- Execute the tests in a real browser (Playwright).
- Verify results with pytest assertions.
- Recheck suspicious failures to reduce false reports.
- Collect evidence for failures: screenshot, browser console errors, failed or 4xx/5xx network requests, pytest output.
- Generate an evidence-backed bug report (HTML, from a Jinja2 template).
- Save metadata to MySQL and evidence/reports to local file storage.
- Show live progress, statuses, evidence and reports in a React dashboard via FastAPI.
- Save passing journeys as regression tests that can be rerun later.

The prototype must work end to end on ONE controlled sample application with planted bugs.

---

## 2. Scope

### In scope (MVP)
- One controlled sample web app (we build it), with a known set of planted bugs.
- Branch A and Branch B input paths.
- Playwright browser execution (Chromium).
- pytest-based execution and results, exported with pytest-json-report.
- Evidence capture and evidence-backed HTML bug reports (Jinja2).
- Recheck logic and status rules (Section 6).
- Regression test save and rerun.
- FastAPI REST API, MySQL metadata, local file storage.
- React dashboard (simple, clean, functional).
- An evaluation script that measures bug detection rate and false-report ratio against the planted bugs.

### Out of scope (do NOT build)
- GitHub integration.
- AI-assisted code fix suggestions.
- Multi-agent collaboration.
- User accounts, authentication for our tool, or multi-tenant features.
- Video recording (screenshots only).
- Testing of arbitrary third-party websites beyond the allowlist (see Section 8).

---

## 3. Tech stack (use these exact tools)

| Layer | Technology |
|---|---|
| Sample app | Plain HTML/CSS/JavaScript served by a tiny Python or Node static server, on http://localhost:3000 |
| Frontend | React (Vite), plain CSS (no heavy UI kit required) |
| Backend REST API | Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.x, PyMySQL |
| Agent orchestration | Python |
| AI test planning and failure explanation | OpenAI API (official `openai` Python SDK), model name from env var `OPENAI_MODEL` |
| Structured output validation | Pydantic v2 |
| Browser automation and exploration | Playwright for Python (Chromium) |
| Test runner and assertions | pytest + pytest-playwright or direct Playwright sync API inside pytest |
| Test result export | pytest-json-report |
| Bug report generation | Python + Jinja2 (HTML template) |
| Database | MySQL 8 (run via docker-compose) |
| Evidence storage | Local file storage under `./storage/` |
| Config | `.env` loaded with python-dotenv |

Do not add other frameworks unless strictly necessary, and tell me why if you do.

---

## 4. Repository structure (create exactly this layout)udaan-qa-agent/ (name it qa-agent/ if you prefer, be consistent)
├── SPEC.md
├── README.md
├── .env.example
├── docker-compose.yml # MySQL 8
├── Makefile # or scripts/ with start/test commands
├── sample_app/
│ ├── server.py # serves static files on :3000
│ ├── public/
│ │ ├── index.html # product list + cart
│ │ ├── login.html
│ │ ├── checkout.html
│ │ ├── app.js
│ │ └── style.css
│ └── planted_bugs.json # GROUND TRUTH, used only by evaluation
├── backend/
│ ├── requirements.txt
│ ├── app/
│ │ ├── main.py # FastAPI app, CORS, routes
│ │ ├── config.py
│ │ ├── db.py # SQLAlchemy engine/session
│ │ ├── models.py # ORM tables
│ │ ├── schemas.py # Pydantic request/response models
│ │ ├── routers/
│ │ │ ├── sessions.py
│ │ │ ├── results.py
│ │ │ └── regression.py
│ │ ├── agent/
│ │ │ ├── orchestrator.py # runs the full pipeline
│ │ │ ├── explorer.py # Playwright site exploration (Branch B)
│ │ │ ├── planner.py # OpenAI + fallback planner -> TestPlan
│ │ │ ├── plan_models.py # Pydantic models: TestPlan, TestCase, Step
│ │ │ ├── executor.py # generates pytest files, runs pytest
│ │ │ ├── runner_lib.py # shared Playwright helpers used by generated tests
│ │ │ ├── verifier.py # interprets pytest results, recheck logic
│ │ │ ├── evidence.py # screenshots, console, network capture
│ │ │ ├── reporter.py # Jinja2 bug report rendering
│ │ │ └── safety.py # allowlist, step limits, timeouts
│ │ └── templates/
│ │ └── bug_report.html.j2
│ └── tests/ # backend unit tests (pytest)
├── frontend/
│ ├── package.json
│ ├── vite.config.js
│ └── src/
│ ├── main.jsx
│ ├── App.jsx
│ ├── api.js
│ ├── pages/
│ │ ├── NewRun.jsx
│ │ ├── RunProgress.jsx
│ │ ├── Results.jsx
│ │ └── BugDetail.jsx
│ └── components/
│ ├── StatusPill.jsx
│ └── Dashboard.jsx
├── storage/ # created at runtime: screenshots, logs, reports
├── generated_tests/ # created at runtime: generated pytest files per session
└── eval/
├── run_evaluation.py # runs the agent on sample app, compares to planted bugs
└── results/ # JSON output of evaluation runs


---

## 5. Sample application (build this first)

A small, controlled shop with these pages:
- **Login** (`/login.html`): email + password. Valid test account: `test@demo.com` / `Test@123`.
- **Products** (`/index.html`): 3 products with name, price, and "Add to cart" button. Cart shows item count and subtotal.
- **Checkout** (`/checkout.html`): shows items, total, and a "Place order" button. Shows "Order placed" on success.

Required error and validation behaviour (the CORRECT behaviour that tests will check):
- Wrong password shows error text "Invalid email or password" and the user stays on the login page.
- Empty email or password on login shows "Email and password are required".
- Checkout total equals the sum of (price x quantity) for all cart items.
- Placing an order with an empty cart shows "Your cart is empty" and does not place an order.

### Planted bugs (deliberately wrong behaviour, store in planted_bugs.json)

Implement these bugs in the sample app. Each must be switchable on/off by an environment variable or a query param so we can run with bugs ON (evaluation) and bugs OFF (control), for example `SAMPLE_BUGS=on|off`.

| Bug ID | Description | Trigger |
|---|---|---|
| BUG-01 | Login accepts a wrong password for the valid email | Enter test@demo.com with any wrong password |
| BUG-02 | Checkout total is wrong when quantity is 2 or more | Add the same product twice, check total |
| BUG-03 | Checkout allows placing an order with an empty cart | Open checkout with empty cart, click Place order |
| BUG-04 | Empty email on login does not show the required message | Submit login with empty fields |
| BUG-05 | Cart count badge does not update after adding a second item | Add two different products, check badge |

`planted_bugs.json` format:
```json
{
  "bugs": [
    {"id": "BUG-01", "title": "...", "page": "/login.html", "trigger": "...", "expected": "...", "actual": "..."}
  ]
}
```

Sample app server: serve `sample_app/public` at `http://localhost:3000`. Use only the Python standard library (`http.server`) or a minimal static server. No database needed.

---

## 6. Agent pipeline (the core)

### 6.1 Input models (Pydantic)
`RunRequest`: `app_url: HttpUrl`, `description: str | None`, `instruction: str | None`, `max_tests: int = 8`.

### 6.2 Branch logic (orchestrator.py)

if instruction is provided and not empty:
plan = planner.plan_from_instruction(instruction, description, page_snapshot=None)
# Optionally open the target page to read elements needed for the test (no broad crawl)
else:
site_map = explorer.explore(app_url, max_pages=10, max_depth=2)
plan = planner.plan_from_exploration(site_map, description)

Both branches produce a `TestPlan` object. Everything after this point is the same path.

### 6.3 Explorer (Branch B)
- Use Playwright (sync API, headless Chromium).
- Start at the app_url. Collect: page URL, title, all links (same origin only), buttons, inputs (type, name, id, placeholder, label text), forms, visible headings.
- Breadth-first, max 10 pages, max depth 2. Stay on the allowlisted origin.
- Return a `SiteMap` (Pydantic model). Save it as JSON in storage for debugging.

### 6.4 Planner (planner.py)
- If `OPENAI_API_KEY` is set: call the OpenAI API with a system prompt that says: return ONLY valid JSON matching the TestPlan schema, use ONLY the actions in the allowed action list, do not invent selectors that are not in the provided page data, keep at most `max_tests` tests.
- Use the SDK's structured output or JSON mode, then validate with Pydantic. If validation fails, retry once with the validation error included. If it fails again, fall back.
- If `OPENAI_API_KEY` is NOT set, or the call fails: use a deterministic FALLBACK planner that produces test plans from templates (login valid/invalid, add to cart, cart badge, checkout total, empty cart checkout, empty login). The demo must work fully offline with the fallback planner. Mark the plan source as `"fallback"` or `"openai"` in the database.
- Also implement `explain_failure(test_result, evidence) -> str` using the LLM when available (one short plain-English explanation). Fallback: return a template explanation based on the expected vs actual text.

### 6.5 TestPlan schema (plan_models.py)
```python
class Action(BaseModel):
    type: Literal["goto", "fill", "click", "expect_text", "expect_url", "expect_visible", "expect_not_visible", "expect_count_text"]
    target: str | None   # CSS selector or stable label/text, from the allowed list only
    value: str | None    # text to type, expected text, URL path, etc.

class TestCase(BaseModel):
    id: str              # e.g. "TC-01"
    title: str
    category: Literal["functional", "validation", "edge", "negative"]
    steps: list[Action]  # max 15
    expected: str        # human-readable expected behaviour
    related_bug_hint: str | None = None

class TestPlan(BaseModel):
    source: Literal["openai", "fallback"]
    branch: Literal["instruction", "exploration"]
    tests: list[TestCase]  # max 8
```
Only these action types are allowed. The LLM must never output raw Python or JavaScript. The executor translates each Action into a fixed Playwright call.

### 6.6 Executor (executor.py) and generated tests
- For each TestCase, generate a pytest file under `generated_tests/<session_id>/test_<tc_id>.py`.
- The generated file imports helpers from `runner_lib.py` and contains one test function. The test performs each Action in order using Playwright, then makes the expected assertion(s).
- Run pytest for the session with: `pytest generated_tests/<session_id> --json-report --json-report-file=<path> -p no:cacheprovider`.
- Each test runs with a per-test timeout (default 20 s) and the whole session has a cap (default 5 min).
- Parse the pytest JSON report into `TestOutcome` records: test id, outcome (passed/failed/error), duration, failure message, traceback summary.

Important: generated test files must be written by our code from the validated `TestPlan`, not free-form LLM text.

### 6.7 Evidence (evidence.py)
Attach these to every FAILED or NEEDS_REVIEW test:
- Screenshot of the page at failure (Playwright `page.screenshot`), saved to `storage/<session>/<tc>/failure.png`.
- Browser console messages with type `error` or `warning` (`page.on("console", ...)`).
- Network entries: `requestfailed` events, and responses with status >= 400 (`page.on("response", ...)`). Record method, URL, status.
- Final URL and page title.
- The pytest failure message.
Store the evidence as JSON in `storage/<session>/<tc>/evidence.json`.

Implement capture inside `runner_lib.py` so every generated test uses the same listeners.

### 6.8 Verifier and recheck logic (verifier.py)
Use these exact rules:
1. First run of a test:
   - passed -> status PASSED
   - failed or error -> go to step 2
2. Recheck: run the same test again (fresh browser context).
   - passed on recheck -> status NEEDS_REVIEW (flaky or inconsistent). Do not report as a bug.
   - failed again with the SAME failure message (normalised: ignore timings and random ids) -> status FAILED (confirmed bug). Create a bug report.
   - failed again with a DIFFERENT message, or error (for example a timeout or crash) -> status NEEDS_REVIEW.
3. If a test errors because of setup (for example the app is unreachable), status is NEEDS_REVIEW with reason "environment", and no bug report is created.

Status values: `PASSED`, `FAILED`, `NEEDS_REVIEW`. Store the reason string with every status.

### 6.9 Reporter (reporter.py)
For every FAILED test, render `bug_report.html.j2` into `storage/<session>/<tc>/bug_report.html` with:
- Bug ID (BUG-<session short id>-<n>), title, severity guess (LOW/MEDIUM/HIGH, from category: validation=LOW, functional=HIGH unless noted), status.
- Reproduction steps (numbered, from the TestCase steps in plain English).
- Expected behaviour, actual behaviour.
- Evidence: screenshot (relative link), console errors, failed/4xx network requests, pytest failure excerpt.
- Environment: app URL, browser, timestamp, planner source.
- Footer: "Generated by QA Agent. Verify before filing."

Also expose `GET /api/bugs/{id}/report` that returns the HTML.

---

## 7. Database (MySQL via SQLAlchemy)

Tables:
- `test_sessions`: id (UUID), app_url, description, instruction, branch (instruction|exploration), planner_source (openai|fallback), status (QUEUED|RUNNING|COMPLETED|FAILED_TO_RUN), created_at, completed_at, counts (total, passed, failed, needs_review).
- `test_cases`: id, session_id (FK), tc_code (TC-01), title, category, steps_json, expected, created_at.
- `test_results`: id, session_id, test_case_id, status (PASSED|FAILED|NEEDS_REVIEW), reason, first_run_outcome, recheck_outcome, duration_ms, failure_message, explanation.
- `bug_reports`: id, session_id, test_result_id, bug_code (BUG-...), title, severity, report_path, created_at.
- `evidence`: id, test_result_id, type (screenshot|console|network|pytest), path_or_json, created_at.
- `regression_tests`: id, source_session_id, test_case_id, tc_code, title, steps_json, expected, created_at, last_run_at, last_status, run_count.

Use SQLAlchemy models in `models.py`. Create tables on startup. Provide a `docker-compose.yml` with MySQL 8, a database `qa_agent`, and a user with a password from `.env`.

For automated tests of the backend, allow an env var `DATABASE_URL=sqlite:///./test.db` so unit tests do not need Docker.

---

## 8. Safety rules (must implement in safety.py)

- Domain allowlist: `ALLOWED_HOSTS` env var, default `localhost,127.0.0.1`. Reject any app_url or navigation outside these hosts, with a clear error. Allow extra hosts only by changing the env var.
- Maximum 30 browser actions per test and 15 steps per TestCase.
- Maximum 8 tests per run.
- Timeouts: 20 s per test, 5 min per session.
- No destructive actions: the planner and executor must never generate delete, remove, or unsubscribe actions on real data. Block any action whose target or value contains these words, and log it.
- Test credentials come only from env vars (`TEST_USER_EMAIL`, `TEST_USER_PASSWORD`). Never hard-code or log secrets. Mask them in logs and reports.
- Never send real personal data to the LLM. The sample app contains only fake data.
- API keys stay in `.env`, which is git-ignored. Provide `.env.example` only.

Write unit tests for the allowlist, step limit, and destructive-word block.

---

## 9. REST API (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| POST | /api/sessions | Create a session from RunRequest, returns session id, status QUEUED |
| POST | /api/sessions/{id}/start | Start the pipeline in a background task, status RUNNING |
| GET | /api/sessions/{id} | Session status, counts, progress (current step text, tests done/total) |
| GET | /api/sessions/{id}/results | List of test results with status and reason |
| GET | /api/results/{result_id} | Full result detail with evidence links and explanation |
| GET | /api/bugs | List bug reports |
| GET | /api/bugs/{id}/report | Rendered HTML bug report |
| GET | /api/regression | List saved regression tests |
| POST | /api/regression/run | Rerun all saved regression tests, returns a new session id |
| GET | /storage/... | Static files for screenshots and reports (read-only, restricted to storage dir) |

Notes:
- Pipeline progress must be visible: update the session row at each stage (exploring, planning, executing, rechecking, reporting, done).
- Use FastAPI background tasks or a simple worker thread. Do not add Celery or Redis.
- Enable CORS for the frontend dev server (http://localhost:5173).
- All responses use Pydantic schemas. Validate inputs.

### Saving regression tests
When a test is PASSED on the first run, save it to `regression_tests`. The `POST /api/regression/run` endpoint regenerates pytest files from the saved steps and runs them, updating `last_status` and `run_count`.

---

## 10. Frontend (React + Vite)

Four screens:

1. **New Run** (`NewRun.jsx`)
   - Fields: Application URL (default http://localhost:3000), Description (optional, textarea), Specific test instruction (optional, textarea).
   - Hint text: "Leave the instruction empty to let the agent explore the app."
   - Button: "Run tests". Validate the URL on the client and show errors.

2. **Run Progress** (`RunProgress.jsx`)
   - Poll `GET /api/sessions/{id}` every 2 seconds.
   - Show a stage stepper: Exploring -> Planning -> Executing -> Rechecking -> Reporting -> Done.
   - Show "3 of 8 tests complete" and a live list of finished tests with their status pills.

3. **Results** (`Results.jsx`)
   - Summary cards: Total, Passed, Failed, Needs Review.
   - Table: Test ID, title, status pill, reason (short), link to detail.
   - Filter by status. Button: "Rerun as regression" (for passed tests).

4. **Bug Detail** (`BugDetail.jsx`)
   - Title, severity, status.
   - Reproduction steps (numbered).
   - Expected vs actual, side by side.
   - Evidence: screenshot image, console errors list, failed network requests list, pytest excerpt.
   - Explanation (from the planner or fallback).
   - Buttons: "Open full HTML report", "Back to results".

Design: clean, readable, high contrast. Status pill colours: PASSED green, FAILED red, NEEDS_REVIEW amber. Use a dark or light theme, but be consistent. Responsive enough for a laptop projector.

No localStorage or sessionStorage needed. Keep state in React and the backend.

---

## 11. Evaluation (eval/run_evaluation.py)

The evaluation script must:
1. Start the sample app with `SAMPLE_BUGS=on` (if not running).
2. Run the full agent with Branch B (no instruction, exploration) against it, and also once with Branch A (instructions for each planted bug area).
3. Compare reported bugs with `planted_bugs.json`. Match by page and trigger keywords, and write the matching logic clearly in code.
4. Compute and write to `eval/results/<timestamp>.json`:
   - `bug_detection_rate` = correctly detected planted bugs / total planted bugs
   - `false_report_ratio` = reported bugs that do not match a planted bug / all reported bugs
   - `repeatability` = run the saved regression suite twice with the sample app unchanged, and compare outcomes (percentage of tests with identical outcome)
   - `planner_source` used for each run
   - list of detected and missed bugs
5. Print a clear summary table.

Also run the same evaluation with `SAMPLE_BUGS=off` (control). Expected: zero bugs reported, otherwise that is a false-report signal, and report it honestly.

Do NOT hard-code any numbers. Report whatever the run produces, even if the detection rate is low. Include the raw JSON in the output.

Do not use the ground-truth file (planted_bugs.json) anywhere in the agent itself. Only the evaluation script may read it. Enforce this by keeping it in `sample_app/` and not importing it in `backend/`. Add a test that checks this.

---

## 12. Milestones (build in this order, and report after each)

**M1 - Sample app and bugs**
- Build the 3 pages, the planted bug switch (`SAMPLE_BUGS`), and `planted_bugs.json`.
- Verify manually with Playwright: a valid login works, bugs appear only when `SAMPLE_BUGS=on`.
- Acceptance: a script shows BUG-01..05 are reproducible with bugs on, and absent with bugs off.

**M2 - Playwright executor and evidence**
- Build `runner_lib.py`, `executor.py`, `evidence.py`.
- Hand-write one TestPlan in JSON, run it through the executor, get PASSED or FAILED with screenshot and console logs.
- Acceptance: one failing test produces a screenshot, console entries, and a network log in `storage/`.

**M3 - Planner (OpenAI + fallback) and both branches**
- Build `plan_models.py`, `planner.py` (OpenAI path and fallback), `explorer.py`.
- Acceptance: Branch A with an instruction and Branch B with no instruction both produce a valid TestPlan validated by Pydantic. Works with no API key.

**M4 - Verifier, recheck and reporter**
- Build `verifier.py`, `reporter.py`, the Jinja2 template, and the status rules from Section 6.8.
- Acceptance: a flaky test (you can simulate it) becomes NEEDS_REVIEW; a consistent failure becomes FAILED with a rendered HTML report.

**M5 - Backend API and database**
- FastAPI app, MySQL models via SQLAlchemy, all endpoints in Section 9, background pipeline with stage updates, docker-compose for MySQL.
- Acceptance: curl or the FastAPI docs page can create a session, start it, poll status, and fetch results and bug reports.

**M6 - React dashboard**
- The four screens in Section 10 with live polling.
- Acceptance: a user can enter the URL, watch progress, see results, open a bug detail with evidence, and open the HTML report, all in the browser.

**M7 - Regression rerun and evaluation**
- Save passing tests, implement rerun, write `eval/run_evaluation.py`.
- Acceptance: evaluation runs end to end and writes JSON with real measured values.

**M8 - Documentation and demo script**
- README with exact commands, troubleshooting, and a 3-minute demo script.

---

## 13. Environment variables (.env.example)
OpenAI (optional: fallback planner is used if empty)

OPENAI_API_KEY=
OPENAI_MODEL=

Database

DATABASE_URL=mysql+pymysql://qa_user:qa_password@localhost:3306/qa_agent

Safety

ALLOWED_HOSTS=localhost,127.0.0.1
MAX_TESTS_PER_RUN=8
MAX_STEPS_PER_TEST=15
TEST_TIMEOUT_SECONDS=20
SESSION_TIMEOUT_SECONDS=300

Sample app test account (fake data only)

TEST_USER_EMAIL=test@demo.com
TEST_USER_PASSWORD=Test@123

Sample app bug switch

SAMPLE_BUGS=on

Storage

STORAGE_DIR=./storage
GENERATED_TESTS_DIR=./generated_tests


---

## 14. Testing requirements

Backend unit tests (pytest, under `backend/tests/`):
- Pydantic models reject invalid actions and too many steps.
- Safety: non-allowlisted URL is rejected; destructive words are blocked; step and test limits enforced.
- Fallback planner returns a valid TestPlan with no API key.
- Verifier status rules: first pass, consistent fail, flaky fail, environment error.
- Reporter renders HTML containing steps, expected and actual.
- Repo check: `backend/` never imports or reads `planted_bugs.json`.

End-to-end check (script or pytest): start sample app, run Branch B, assert at least BUG-01 and BUG-02 are found, and that the control run (`SAMPLE_BUGS=off`) reports zero bugs. Report the actual results, do not force them.

---

## 15. Acceptance criteria (the prototype is done when all are true)

1. `docker compose up -d` starts MySQL, and `make start` (or the README commands) starts the sample app, backend, and frontend.
2. From the React dashboard, a user can run a test session against http://localhost:3000 with NO API key and see live progress.
3. The same works with an OpenAI key set, and the plan source shows `openai`.
4. Branch A (instruction given) and Branch B (no instruction) both run and clearly differ in the session record.
5. Failed tests have a screenshot, console and network evidence, and an HTML bug report.
6. A non-reproducible failure is shown as NEEDS_REVIEW, not as a bug.
7. Passed tests can be saved and rerun from the dashboard.
8. The evaluation script produces a JSON file with real measured values for detection rate and false-report ratio, with bugs on and off.
9. No Spring Boot anywhere. Backend is FastAPI.
10. README lets a new person run everything on a clean machine in under 30 minutes.

---

## 16. Final deliverable message (what you must tell me at the end)

- What was built, milestone by milestone, with what was actually tested.
- The exact commands to run the demo.
- Evaluation results (copy the actual numbers from the JSON), including anything that failed.
- A list of known limitations and what is not yet done.
- Any assumptions you made.

Do not overstate. If something is partially working, say so.
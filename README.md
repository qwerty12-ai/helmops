# HelmOps - a computer operator for Accounts Payable

> **Transparency note:** This project was built for the Hulchul AI Engineering build assignment.
> I scaffolded it with Claude (vibe-coded) because browser automation with Playwright was new to me.
> I ran it end to end, verified results against the ERP database, debugged my own edit, and added a
> `min_amount` goal filter with a test (see ENGINEERING_NOTE.md). I treat this as an experiment in learning a new
> tool fast with AI assistance. My earlier projects (Reclaim, SignalForge, CursorVault, GitPulse) are separate and hand-built.

## Demo video:
https://youtu.be/TfvVkYB4yYM

## License:
MIT (see `LICENSE`).

Give it a plain-English goal ("Enter all vendor invoices, ask me before anything over $2,000").
It reads invoice files, **drives a real Chromium browser** to enter them as bills in a mock ERP (MiniLedger),
recovers from failures without duplicating anything, asks for approval beyond your authority, pauses on demand,
independently audits the ERP afterwards, and writes a report with screenshots.

Stack: Python 3.10+, FastAPI, Playwright (Chromium), MySQL 8.4 (Docker Compose), vanilla-JS dashboard (SSE). Optional free local LLM via Ollama.
No API keys, no paid services, synthetic data only.

## Run
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python scripts/make_invoices.py                         # (already generated, safe to re-run)
docker compose up -d                                    # MySQL for the test ERP (port 3307)
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 MYSQL_USER=helm MYSQL_PASSWORD=helm MYSQL_DATABASE=miniledger
# Windows PowerShell: $env:MYSQL_HOST="127.0.0.1"; $env:MYSQL_PORT="3307"; ... (same names)
> Windows tip: if the headed browser crashes on launch, use your installed Edge/Chrome:
> `$env:HELM_CHANNEL="msedge"` (or `"chrome"`) before `python run.py`.
# No Docker? Skip the two lines above: the ERP falls back to a local SQLite file automatically.
export HELM_HEADED=1 HELM_SLOW_MO=350                   # show the browser (Windows: set VAR=...)
python run.py                                           # dashboard :8000, ERP :8001
```
Open http://127.0.0.1:8000. (Do not use `--reload` on Windows; Playwright needs the default event loop.)

Tests: `python -m pytest -q tests` (7 tests; includes a fake-browser integration test of approvals + recovery).

## Optional: local LLM (free)
`ollama pull qwen2.5:3b` then `export OLLAMA_MODEL=qwen2.5:3b`. Used to (a) parse the goal and (b) fill fields
regex could not extract. Without it, deterministic rules are used. LLM output is validated against known vendors.

## Demo script (maps to the assignment)
1. **Task**: click *Reset ERP*, preset 1 -> Start. Watch the browser fill forms. INV-1003 skipped (already in ERP),
   INV-1002/1005 trigger approval (approve one, reject the other), INV-1007 (EUR) and INV-1008 (no amount) are BLOCKED visibly.
2. **Variation (no code change)**: Reset ERP, preset 2 (different vendors/date filter/authority) or type your own goal.
3. **Failure**: Reset ERP, click *Inject: save then 500*, start. The ERP saves a bill but returns 500. Operator re-reads the
   ERP, finds the bill, marks `done_recovered`, does NOT resubmit. Also try *503 x2* (nothing saved -> real retry).
4. **Human control**: press Pause mid-run (stops at next checkpoint), Resume, Cancel; approvals block until you decide.
5. **Evidence**: final audit line in the log, `artifacts/<run>/report.md|json` and per-invoice screenshots ("proof" links).

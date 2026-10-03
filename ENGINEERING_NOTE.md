# Engineering note - HelmOps

**Workflow chosen:** invoice -> ERP bill entry. Multi-step, real money semantics, and a natural place for duplicates,
approvals and partial failure, which are exactly what a computer operator must handle.

**Design choices**
- *Same patterns as my earlier projects.* The idempotent-execution + audit-trail idea comes from Reclaim; the human-approval
  checkpoint and graceful per-item failure handling come from SignalForge. The test ERP runs on MySQL via Docker Compose.
- *Browser-first, API for audit only.* All writes go through the UI (Playwright). The ERP's JSON API is used only by an
  independent verifier, so "done" is checked against ground truth, not the operator's own belief.
- *Idempotency over blind retry.* Before every attempt the operator searches the ERP for the bill. The nasty injected fault
  (server commits, then returns 500) therefore ends in `done_recovered`, never a duplicate. The final audit diffs the
  ERP before/after and flags missing, unexpected and duplicate rows.
- *Deterministic core, optional LLM.* Goal parsing and extraction use rules; Ollama is an optional, validated fallback.
  The operator still works offline and is explainable/testable.
- *Incomplete work is first-class.* Non-USD and missing-amount invoices are `blocked` with a reason; a run with any
  blocker ends `completed_with_issues`, never "completed".
- *Human control.* Pause/resume/cancel at checkpoints between actions; amounts over the stated authority create an approval
  request that blocks that item until Approve/Reject.

**Limitations:** single run at a time, in-memory run state (artifacts persist on disk); a pause takes effect at the next
checkpoint, not mid-keystroke; selectors are fixed to MiniLedger (no visual/vision grounding); .txt invoices only (no PDF OCR);
goal parsing by rules covers vendor/amount/due-date/authority phrasing only. The fake-browser test covers the logic;
real-Chromium behaviour should be re-checked on your machine before recording.

**Next:** PDF/OCR + vision-model fallback when selectors break, persistent run store + resumable runs after crash,
multi-app flow (email attachment -> ERP -> spreadsheet), per-action undo.

**AI assistance disclosure:** this project was scaffolded with Claude (Anthropic). Libraries: FastAPI, Playwright,
httpx, SQLite, Ollama (optional). *TODO before submitting: add 2-3 sentences on what you personally changed/extended
(e.g. a new fault mode or goal filter) and be ready to explain every file.*


# My contribution (personal changes and verification)
 
The base project was scaffolded with Claude (Anthropic). Below is what I personally changed, ran and verified.
 
## 1. New goal filter: `min_amount` ("at least $X")
**Why:** the original parser could cap invoice amounts ("under $5,000") but not set a floor. A real AP goal often says
"only enter invoices of at least $1,000".
 
**What I changed** (`helm/goal.py`, `tests/test_core.py`):
- Added a `min_amount` field to the `Plan` dataclass.
- Added a regex in `parse_goal` that reads phrases like "at least", "minimum of", "no less than".
- Added a check in `filter_reason` so smaller invoices are skipped with a visible reason
  (`amount below goal limit $1,000.00`).
- Added a unit test (`test_goal_min_amount`) for the parser.
**No other code changed** - the operator picks up the new behaviour from the goal text alone.
 
## 2. Debugging
My first edit broke Python indentation inside `parse_goal` (`IndentationError`). I found the bad block from the pytest
traceback, fixed the indentation and re-ran the tests.
 
## 3. End-to-end verification (run on my own machine)
Goal used: `Enter all vendor invoices of at least $1000. Ask me before anything over $2,000.`
 
| Check | Result |
|---|---|
| Invoices entered | INV-1001, INV-1002, INV-1005 (all >= $1,000) |
| Invoices skipped by the filter | INV-1003, 1004, 1006, 1007, 1009 with the reason shown in the UI |
| Approval gate | INV-1002 ($3,400) and INV-1005 ($7,800) waited for my Approve click |
| Blocked, not hidden | INV-1008 (missing amount) shown as `blocked` |
| ERP state | MiniLedger lists exactly the 3 new bills plus the pre-existing INV-1003 |
| Independent audit | `expected 3 new bills, found 3; missing=0 unexpected=0 duplicates=0` |
 
## 4. Failure case I ran
With "Inject: save then 500" the ERP **saved INV-1001 and then returned a 500 error**. The operator re-checked the ERP
before retrying, found the bill and marked it `done_recovered` instead of submitting again. MiniLedger shows INV-1001
exactly once and the audit passed.
 
## 5. What I can explain
- How `_enter()` in `helm/agent.py` checks the ERP before every attempt (idempotency).
- Why the final audit reads the database through the API rather than trusting the operator's own status.
- How the approval gate pauses a single invoice until I click Approve/Reject.

## 6. Learned while doing this
Playwright (browser automation) was new to me; I learned it by running the operator, reading `agent.py`, and changing
the goal parser myself. The MySQL/Docker setup follows patterns from my earlier project Reclaim.
 
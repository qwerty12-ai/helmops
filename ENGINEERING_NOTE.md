# Engineering note - HelmOps (Hulchul AI Engineering assignment)

## Workflow chosen
Invoice-to-ERP bill entry. The operator takes a plain-English goal, reads vendor invoice files, enters them as bills in a
test ERP (MiniLedger) through a real browser, and verifies the result. It is multi-step, has real-money semantics, and is a
natural place for duplicates, approvals and partial failure, which is what a computer operator must handle.

## Design choices
- **Browser-first, API for audit only.** All writes go through the UI with Playwright. The ERP's JSON API is used only by an
  independent verifier, so "done" is checked against ground truth, not the operator's own belief.
- **Idempotency over blind retry.** Before every attempt the operator searches the ERP for the bill. The hard injected fault
  (the server saves the bill, then returns a 500) therefore ends as `done_recovered` instead of a duplicate. The final audit
  diffs the ERP before and after and flags missing, unexpected and duplicate rows.
- **Incomplete work stays visible.** Non-USD and missing-amount invoices are `blocked` with a reason. A run with any blocker
  ends `completed_with_issues`, never "completed".
- **Human control.** Pause, resume and cancel work at checkpoints between actions. Amounts above the authority given in the
  goal create an approval request that blocks that invoice until Approve or Reject.
- **Deterministic core, optional LLM.** Goal parsing and invoice extraction use rules, so the operator is testable and works
  offline. An Ollama path exists as an optional fallback (see limitations).
- **Same patterns as my earlier projects.** The idempotent execution and audit trail follow Reclaim; the human-review
  checkpoint and per-item failure handling follow SignalForge. The test ERP uses MySQL via Docker Compose.

## Tools and AI assistance
I scaffolded this project with Claude (Anthropic), because browser automation with Playwright was new to me. Libraries:
FastAPI, Playwright, httpx, PyMySQL, MySQL 8.4 (Docker Compose), pytest, GitHub Actions. Ollama is optional. No API keys or
paid accounts are required, and all data is synthetic.

## My contribution
- **New goal filter, `min_amount`.** The parser could cap amounts ("under $5,000") but not set a floor. I added a `min_amount`
  field to `Plan`, a regex in `parse_goal` ("at least", "minimum of", "no less than"), a check in `filter_reason` that skips
  smaller invoices with a visible reason, and a unit test. The operator picks up the new behaviour from the goal text alone.
- **Debugging.** My first edit broke indentation in `parse_goal` (`IndentationError`). I found the line from the pytest
  traceback and fixed it with Claude's help.
- **Headed-browser fix.** With `HELM_HEADED=1`, Playwright's bundled Chromium crashed on launch on my Windows machine
  (`TargetClosedError`); headless runs were fine. The fix was an optional `HELM_CHANNEL` setting passed to
  `chromium.launch(channel=...)`, so the operator can drive an installed Edge or Chrome, plus `--disable-gpu` for headed runs.
  The failure was environmental, and making the browser configurable made the operator more portable.
- **End-to-end verification on my machine.** I ran the normal task, my `min_amount` variation, and the failure case, and
  checked the ERP state and audit results each time.

## Verification
| Case | Result |
|---|---|
| Normal run | Valid invoices entered; INV-1003 skipped as a duplicate already in the ERP; two large invoices waited for my approval; EUR and missing-amount invoices shown as `blocked`; audit passed |
| Variation (no code change) | Goal "at least $1000, ask me above $2,000" entered only INV-1001, 1002 and 1005; others skipped with a reason; audit passed |
| Failure | ERP saved INV-1001 then returned 500; the operator re-checked, found the bill, marked it `done_recovered` and did not resubmit; the bill appears once and the audit passed |
| Control | Pause and resume stop and continue the run at the next checkpoint; cancel ends it and writes a report |

Every run saves `report.md` / `report.json` and per-invoice screenshots under `artifacts/`.

## Limitations
- One run at a time; run state is in memory (reports and screenshots persist on disk).
- Pause takes effect at the next checkpoint, not mid-keystroke.
- Selectors are fixed to MiniLedger; there is no vision-based grounding.
- `.txt` invoices only (no PDF or OCR). Goal parsing by rules covers vendor, amount, due-date and authority phrasing only.
- The optional Ollama path is implemented but I did not test it.
- CI runs the unit tests and a fake-browser integration test of approvals and recovery. I verified the real browser flow
  manually on Windows.

## What I would build next
PDF/OCR extraction with a vision-model fallback when selectors break, a persistent run store with resume after a crash,
a multi-app flow (email attachment, ERP, spreadsheet), and per-action undo.
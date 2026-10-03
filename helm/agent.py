"""The operator: plans from a goal, drives a real browser against the ERP, recovers, verifies, reports."""
import asyncio
import json
import time
import uuid
from collections import Counter
from dataclasses import asdict
import httpx
from playwright.async_api import async_playwright
from . import config
from .extract import parse_invoice
from .goal import parse_goal, filter_reason

GOOD_END = {"done", "done_recovered", "skipped_duplicate", "skipped_filter", "rejected"}
ACTIVE = {"queued", "running", "paused", "awaiting_approval"}


class Cancelled(Exception):
    pass


def key(inv, vendor):
    return (str(inv).strip().lower(), str(vendor).strip().lower())


class Run:
    def __init__(self, goal: str):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.goal, self.status, self.plan = goal, "queued", None
        self.items, self.events, self.audit = [], [], None
        self.dir = config.ARTIFACTS / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.paused = self.cancelled = False
        self._go = asyncio.Event()
        self._go.set()
        self.approvals = {}
        self.task = None

    # ---------- control ----------
    def emit(self, kind, msg, **data):
        self.events.append({"i": len(self.events), "t": time.strftime("%H:%M:%S"), "kind": kind, "msg": msg, **data})

    def pause(self):
        if self.status in ACTIVE:
            self.paused = True
            self._go.clear()
            self.emit("control", "Paused by user - will stop at the next safe checkpoint")

    def resume(self):
        self.paused = False
        self._go.set()
        self.emit("control", "Resumed by user")

    def cancel(self):
        self.cancelled = True
        self._go.set()
        for f in self.approvals.values():
            if not f.done():
                f.cancel()
        self.emit("control", "Cancel requested")

    def decide(self, item_id, approve: bool):
        f = self.approvals.get(item_id)
        if f and not f.done():
            f.set_result(approve)
            return True
        return False

    async def checkpoint(self):
        if self.paused:
            self.emit("control", "Operator idle (paused)")
        await self._go.wait()
        if self.cancelled:
            raise Cancelled()

    def snapshot(self):
        return {"id": self.id, "goal": self.goal, "status": self.status, "paused": self.paused,
                "plan": asdict(self.plan) if self.plan else None, "items": self.items, "audit": self.audit}

    # ---------- main ----------
    async def execute(self):
        try:
            self.status = "running"
            await self._prepare()
            await self._operate()
        except (Cancelled, asyncio.CancelledError):
            self.status = "cancelled"
            self.emit("control", "Run cancelled; work so far is listed in the report")
        except Exception as ex:  # noqa
            self.status = "error"
            self.emit("error", f"Operator crashed: {type(ex).__name__}: {ex}")
        finally:
            self._write_report()

    async def _prepare(self):
        files = sorted(config.INVOICE_DIR.glob("*.txt"))
        self.emit("info", f"Reading {len(files)} invoice files")
        for n, f in enumerate(files):
            it = await asyncio.to_thread(parse_invoice, f)
            it["id"] = f"it{n}"
            self.items.append(it)
        vendors = sorted({i["vendor"] for i in self.items if i.get("vendor")})
        self.plan = await asyncio.to_thread(parse_goal, self.goal, vendors)
        p = self.plan
        self.emit("plan", f"Plan ({p.source}): include={p.include_vendors or 'all'} exclude={p.exclude_vendors or '-'} "
                          f"max_amount={p.max_amount} due_before={p.due_before} approval_above=${p.authority:,.2f}")
        for it in self.items:
            why = filter_reason(p, it)
            if why:
                it.update(status="skipped_filter", note=why)
            elif it["parse_error"]:
                it.update(status="blocked", note=it["parse_error"])
                self.emit("warn", f"{it['file']}: BLOCKED - {it['parse_error']}")

    async def _read_rows(self, page, q=""):
        await page.goto(f"{config.ERP_URL}/bills" + (f"?q={q}" if q else ""))
        return await page.eval_on_selector_all(
            "#bills tbody tr",
            "rs=>rs.map(r=>({invoice_no:r.dataset.invoice,vendor:r.dataset.vendor,"
            "amount:parseFloat(r.querySelector('.amount').textContent)}))")

    async def _find(self, page, it):
        rows = await self._read_rows(page, it["invoice_no"])
        return [r for r in rows if key(r["invoice_no"], r["vendor"]) == key(it["invoice_no"], it["vendor"])]

    async def _api_bills(self):
        async with httpx.AsyncClient(timeout=10) as c:
            return (await c.get(f"{config.ERP_URL}/api/bills")).json()

    async def _shot(self, page, it, suffix):
        name = f"{it['invoice_no']}-{suffix}.png"
        await page.screenshot(path=str(self.dir / name))
        it["screenshot"] = f"/artifacts/{self.id}/{name}"

    async def _operate(self):
        baseline = Counter(key(b["invoice_no"], b["vendor"]) for b in await self._api_bills())
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not config.HEADED, slow_mo=config.SLOW_MO, channel=config.CHANNEL or None, args=["--disable-gpu"] if config.HEADED else [])
            page = await (await browser.new_context(viewport={"width": 1100, "height": 760})).new_page()
            page.set_default_timeout(8000)
            try:
                existing = {key(r["invoice_no"], r["vendor"]) for r in await self._read_rows(page)}
                self.emit("action", f"Opened ERP bill list: {len(existing)} existing bill(s)")
                for it in self.items:
                    if it["status"] != "pending":
                        continue
                    await self.checkpoint()
                    if key(it["invoice_no"], it["vendor"]) in existing:
                        it.update(status="skipped_duplicate", note="Already in ERP - not entered again")
                        self.emit("info", f"{it['invoice_no']}: already in ERP, skipping")
                        continue
                    if it["amount"] > self.plan.authority:
                        if not await self._ask(it):
                            continue
                    await self._enter(page, it)
                    await self._shot(page, it, "final")
            finally:
                await browser.close()
        await self._verify(baseline)

    async def _ask(self, it):
        fut = asyncio.get_running_loop().create_future()
        self.approvals[it["id"]] = fut
        it["status"] = "awaiting_approval"
        prev, self.status = self.status, "awaiting_approval"
        self.emit("approval", f"{it['invoice_no']} (${it['amount']:,.2f}, {it['vendor']}) exceeds your "
                              f"${self.plan.authority:,.2f} authority - approve?", item_id=it["id"])
        ok = await fut  # raises CancelledError if run cancelled
        self.status = "running" if prev != "paused" else prev
        if not ok:
            it.update(status="rejected", note="Rejected by user")
            self.emit("info", f"{it['invoice_no']}: rejected by user, not entered")
            return False
        it["note"] = "Approved by user"
        self.emit("info", f"{it['invoice_no']}: approved by user")
        return True

    async def _enter(self, page, it):
        no, tries = it["invoice_no"], 3
        for attempt in range(1, tries + 1):
            await self.checkpoint()
            # IDEMPOTENCY GUARD: before every attempt, ask the ERP whether the bill already exists.
            found = await self._find(page, it)
            if found:
                if attempt > 1:
                    it.update(status="done_recovered",
                              note=f"Attempt {attempt-1} showed an error but ERP already holds the bill - NOT resubmitted")
                    self.emit("recover", f"{no}: error was a false negative; found it in ERP, no duplicate created")
                else:
                    it.update(status="skipped_duplicate", note="Appeared in ERP before entry")
                return
            it["status"] = "entering"
            self.emit("action", f"{no}: filling bill form (attempt {attempt}/{tries})")
            ok, msg = False, ""
            try:
                await page.goto(f"{config.ERP_URL}/bills/new")
                await page.fill("#invoice_no", no)
                await page.fill("#vendor", it["vendor"])
                await page.fill("#amount", f"{it['amount']:.2f}")
                await page.fill("#invoice_date", it["invoice_date"])
                await page.fill("#due_date", it["due_date"])
                await page.fill("#memo", it["memo"])
                await self._shot(page, it, f"form{attempt}")
                await page.click("#submit")
                await page.wait_for_load_state("load")
                res = page.locator("#result")
                ok = (await res.count() > 0) and (await res.get_attribute("data-status")) == "ok"
                msg = "" if ok else (await res.inner_text() if await res.count() else "no result banner")
            except Exception as ex:  # timeout, navigation error...
                msg = f"{type(ex).__name__}: {str(ex)[:100]}"
            if ok:
                break
            self.emit("warn", f"{no}: submit failed ({msg}). Re-checking ERP state before any retry")
            await asyncio.sleep(1.0 * attempt)
        # verify by reading the application state back
        found = await self._find(page, it)
        if len(found) == 1 and abs(found[0]["amount"] - it["amount"]) < 0.005:
            if it["status"] == "entering":
                it.update(status="done", note=it["note"] or "Entered and verified in ERP list")
            self.emit("ok", f"{no}: verified in ERP ({it['amount']:,.2f})")
        elif len(found) == 0:
            it.update(status="failed", note=f"Could not save after {tries} attempts: {msg}")
            self.emit("error", f"{no}: FAILED - {msg}")
        else:
            it.update(status="mismatch", note=f"ERP shows {len(found)} row(s) / amount differs")
            self.emit("error", f"{no}: MISMATCH in ERP")

    async def _verify(self, baseline):
        now = Counter(key(b["invoice_no"], b["vendor"]) for b in await self._api_bills())
        new = now - baseline
        expected = Counter(key(i["invoice_no"], i["vendor"]) for i in self.items
                           if i["status"] in ("done", "done_recovered"))
        missing, unexpected = expected - new, new - expected
        dupes = [k for k, v in now.items() if v > 1]
        self.audit = {"expected_new": sum(expected.values()), "actually_new": sum(new.values()),
                      "missing": [list(k) for k in missing], "unexpected": [list(k) for k in unexpected],
                      "duplicates": [list(k) for k in dupes], "passed": not (missing or unexpected or dupes)}
        self.emit("audit", f"Independent ERP audit via API: expected {self.audit['expected_new']} new bills, "
                           f"found {self.audit['actually_new']}; missing={len(missing)} unexpected={len(unexpected)} "
                           f"duplicates={len(dupes)}")
        clean = all(i["status"] in GOOD_END for i in self.items) and self.audit["passed"]
        self.status = "completed" if clean else "completed_with_issues"
        self.emit("done", "All requested work verified." if clean else
                  "Finished with issues - see blocked/failed items; they were NOT silently skipped.")

    def _write_report(self):
        snap = self.snapshot()
        (self.dir / "report.json").write_text(json.dumps(snap, indent=2))
        lines = [f"# HelmOps run {self.id}", f"**Goal:** {self.goal}", f"**Status:** {self.status}", "",
                 "| Invoice | Vendor | Amount | Status | Note |", "|---|---|---|---|---|"]
        for i in self.items:
            lines.append(f"| {i.get('invoice_no') or i['file']} | {i.get('vendor') or ''} | {i.get('amount') or ''} "
                         f"| {i['status']} | {i['note']} |")
        if self.audit:
            lines += ["", f"**ERP audit:** {json.dumps(self.audit)}"]
        lines += ["", "## Event log"] + [f"- {e['t']} [{e['kind']}] {e['msg']}" for e in self.events]
        (self.dir / "report.md").write_text("\n".join(lines))

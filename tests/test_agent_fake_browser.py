"""Exercises the full operator logic (approvals, failure recovery, audit) with a fake browser
that talks to the real ERP app in-process. Real Chromium is used in the actual demo."""
import asyncio, re, sys, pathlib, importlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx
from fastapi.testclient import TestClient


class FakePage:
    def __init__(self, client): self.c, self.form, self.html, self.url = client, {}, "", ""
    def set_default_timeout(self, _): pass
    async def goto(self, url):
        self.url = url.replace("http://127.0.0.1:8001", ""); self.html = self.c.get(self.url).text
    async def fill(self, sel, v): self.form[sel.lstrip("#")] = v
    async def click(self, _):
        r = self.c.post("/bills", data=self.form, follow_redirects=True); self.html = r.text; self.form = {}
    async def wait_for_load_state(self, _): pass
    async def screenshot(self, path): pathlib.Path(path).write_bytes(b"png")
    def locator(self, sel):
        html = self.html
        class L:
            async def count(s): return 1 if "id='result'" in html else 0
            async def get_attribute(s, a): return re.search(r"data-status='(\w+)'", html).group(1)
            async def inner_text(s): return re.search(r"id='result'[^>]*>([^<]*)", html).group(1)
        return L()
    async def eval_on_selector_all(self, sel, js):
        return [dict(invoice_no=a, vendor=b, amount=float(c)) for a, b, c in
                re.findall(r"data-invoice='([^']*)' data-vendor='([^']*)'><td class='inv'>.*?<td class='amount'>([\d.]+)", self.html)]


def run_goal(goal, fault, monkeypatch, tmp_path):
    monkeypatch.setenv("ERP_DB", str(tmp_path / "t.db")); monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    import erp.app as erp; importlib.reload(erp)
    import helm.config as cfg; importlib.reload(cfg)
    import helm.agent as agent; importlib.reload(agent)
    client = TestClient(erp.app); client.post("/admin/reset")
    if fault: client.post("/admin/fault", json=fault)

    class Ctx:
        async def new_page(s): return FakePage(client)
    class Br:
        async def new_context(s, **k): return Ctx()
        async def close(s): pass
    class Chromium:
        async def launch(s, **k): return Br()
    class PW:
        chromium = Chromium()
        async def __aenter__(s): return s
        async def __aexit__(s, *a): pass
    monkeypatch.setattr(agent, "async_playwright", lambda: PW())

    async def fake_api(self): return client.get("/api/bills").json()
    monkeypatch.setattr(agent.Run, "_api_bills", fake_api)

    async def go():
        run = agent.Run(goal)
        task = asyncio.create_task(run.execute())
        while not task.done():
            await asyncio.sleep(0.05)
            for it in run.items:
                if it["status"] == "awaiting_approval": run.decide(it["id"], it["invoice_no"] != "INV-1005")
        return run
    return asyncio.run(go()), client


def test_full_run_with_fault_and_approval(monkeypatch, tmp_path):
    run, client = run_goal("Enter all vendor invoices. Ask me before anything over $2,000.",
                           {"mode": "commit_then_500", "count": 1}, monkeypatch, tmp_path)
    st = {i["invoice_no"]: i["status"] for i in run.items}
    assert st["INV-1003"] == "skipped_duplicate"
    assert st["INV-1005"] == "rejected" and st["INV-1007"] == "blocked" and st["INV-1008"] == "blocked"
    assert "done_recovered" in st.values()                       # fault was recovered from
    rows = client.get("/api/bills").json()
    keys = [(r["invoice_no"], r["vendor"]) for r in rows]
    assert len(keys) == len(set(keys))                           # no duplicates created
    assert run.audit["passed"] and run.status == "completed_with_issues"  # blockers stay visible
    assert (run.dir / "report.md").exists()


def test_503_retry(monkeypatch, tmp_path):
    run, client = run_goal("Only enter Initech Software invoices due before 2026-10-26.",
                           {"mode": "fail_before_commit", "count": 2}, monkeypatch, tmp_path)
    st = {i["invoice_no"]: i["status"] for i in run.items}
    assert st["INV-1004"] == "done" and st["INV-1001"] == "skipped_filter"
    assert len([b for b in client.get("/api/bills").json() if b["invoice_no"] == "INV-1004"]) == 1

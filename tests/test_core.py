import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from helm.goal import parse_goal, filter_reason
from helm.extract import parse_invoice
from helm.config import INVOICE_DIR

V = ["Acme Supplies", "Globex Logistics", "Initech Software"]


def test_alias_invoice():
    it = parse_invoice(INVOICE_DIR / "INV-1004.txt")
    assert it["vendor"] == "Initech Software" and it["amount"] == 199.0 and it["due_date"] == "2026-10-25"


def test_blockers():
    assert "EUR" in parse_invoice(INVOICE_DIR / "INV-1007.txt")["parse_error"]
    assert "amount" in parse_invoice(INVOICE_DIR / "INV-1008.txt")["parse_error"]


def test_goal_variation():
    p = parse_goal("Only enter Globex Logistics and Initech Software invoices due before 2026-10-26. Ask me for anything over $500.", V)
    assert p.include_vendors == ["Globex Logistics", "Initech Software"]
    assert p.due_before == "2026-10-26" and p.authority == 500 and p.max_amount is None


def test_goal_exclude():
    p = parse_goal("Enter everything except Acme Supplies, only invoices under $5,000. Auto-approve up to $1,000.", V)
    assert p.exclude_vendors == ["Acme Supplies"] and p.max_amount == 5000 and p.authority == 1000
    assert filter_reason(p, {"vendor": "Acme Supplies"})


def test_erp_fault_saves_then_500(tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_DB", str(tmp_path / "t.db"))
    from fastapi.testclient import TestClient
    import importlib, erp.app as m
    importlib.reload(m)
    c = TestClient(m.app)
    c.post("/admin/fault", json={"mode": "commit_then_500", "count": 1})
    d = dict(invoice_no="X1", vendor="V", amount="5")
    assert c.post("/bills", data=d).status_code == 500
    assert len([b for b in c.get("/api/bills").json() if b["invoice_no"] == "X1"]) == 1

def test_goal_min_amount():
    p = parse_goal("Enter invoices of at least $1,000.", V)
    assert p.min_amount == 1000

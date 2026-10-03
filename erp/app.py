"""MiniLedger: a deliberately simple, flaky AP system that serves as the test environment."""
import html
import os
import sqlite3
import time
from contextlib import contextmanager
from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

DB = os.getenv("ERP_DB", os.path.join(os.path.dirname(__file__), "erp.db"))
MYSQL = os.getenv("MYSQL_HOST")  # set -> use MySQL; unset -> SQLite fallback (used by tests)
SEED = [("INV-1003", "Globex Logistics", 845.50, "2026-09-02", "2026-10-05", "pre-existing")]
fault = {"mode": None, "remaining": 0}
app = FastAPI(title="MiniLedger")
e = html.escape
STYLE = ("<style>body{font-family:system-ui;margin:2rem}table{border-collapse:collapse}"
         "td,th{border:1px solid #ccc;padding:6px 10px}.ok{background:#d1fae5;padding:8px}"
         ".err{background:#fee2e2;padding:8px}label{display:block;margin:8px 0}</style>")

if MYSQL:
    import pymysql
    import pymysql.cursors


@contextmanager
def db():
    if MYSQL:
        c = pymysql.connect(host=MYSQL, port=int(os.getenv("MYSQL_PORT", "3306")),
                            user=os.getenv("MYSQL_USER", "helm"), password=os.getenv("MYSQL_PASSWORD", "helm"),
                            database=os.getenv("MYSQL_DATABASE", "miniledger"),
                            cursorclass=pymysql.cursors.DictCursor)
    else:
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def q(c, sql, params=()):
    """Run SQL written with %s placeholders on either MySQL or SQLite; returns list of dict rows."""
    if MYSQL:
        cur = c.cursor()
        cur.execute(sql, params)
    else:
        cur = c.execute(sql.replace("%s", "?"), params)
    return [dict(r) for r in cur.fetchall()] if cur.description else []


def seed(reset=False):
    pk = "INT AUTO_INCREMENT PRIMARY KEY" if MYSQL else "integer primary key autoincrement"
    with db() as c:
        q(c, f"create table if not exists bills(id {pk}, invoice_no varchar(64), vendor varchar(128),"
             " amount double, invoice_date varchar(32), due_date varchar(32), memo varchar(255))")
        if reset:
            q(c, "delete from bills")
        if q(c, "select count(*) as n from bills")[0]["n"] == 0:
            for row in SEED:
                q(c, "insert into bills(invoice_no,vendor,amount,invoice_date,due_date,memo) values(%s,%s,%s,%s,%s,%s)", row)


for _ in range(30):  # wait for MySQL container to accept connections
    try:
        seed()
        break
    except Exception:
        if not MYSQL:
            raise
        time.sleep(1)
else:
    raise RuntimeError("MySQL not reachable - is `docker compose up -d` running and MYSQL_* exported?")


def page(body, status=200):
    return HTMLResponse("<!doctype html><html><head><title>MiniLedger</title>" + STYLE + "</head><body>"
                        "<h1>MiniLedger - Accounts Payable</h1><nav><a href='/bills'>Bills</a> | "
                        "<a href='/bills/new'>New bill</a></nav>" + body + "</body></html>", status_code=status)


@app.get("/")
def root():
    return RedirectResponse("/bills")


@app.get("/bills")
def bills(search: str = Query("", alias="q"), created: str = ""):
    qs = search
    with db() as c:
        rows = q(c, "select * from bills where invoice_no like %s or vendor like %s order by id",
                 (f"%{qs}%", f"%{qs}%"))
    banner = f"<div id='result' class='ok' data-status='ok'>Bill {e(created)} saved</div>" if created else ""
    trs = "".join(
        f"<tr data-invoice='{e(r['invoice_no'])}' data-vendor='{e(r['vendor'])}'><td class='inv'>{e(r['invoice_no'])}</td>"
        f"<td class='vendor'>{e(r['vendor'])}</td><td class='amount'>{r['amount']:.2f}</td>"
        f"<td class='due'>{e(r['due_date'] or '')}</td><td>{e(r['memo'] or '')}</td></tr>" for r in rows)
    return page(f"{banner}<form method='get'><input name='q' id='q' value='{e(qs)}' placeholder='search'>"
                f"<button>Search</button></form><table id='bills'><thead><tr><th>Invoice</th><th>Vendor</th>"
                f"<th>Amount (USD)</th><th>Due</th><th>Memo</th></tr></thead><tbody>{trs}</tbody></table>")


@app.get("/bills/new")
def new_form():
    return page("<form method='post' action='/bills' id='bill-form'>"
                "<label>Invoice no <input id='invoice_no' name='invoice_no' required></label>"
                "<label>Vendor <input id='vendor' name='vendor' required></label>"
                "<label>Amount (USD) <input id='amount' name='amount' required></label>"
                "<label>Invoice date <input id='invoice_date' name='invoice_date'></label>"
                "<label>Due date <input id='due_date' name='due_date'></label>"
                "<label>Memo <input id='memo' name='memo'></label>"
                "<button id='submit' type='submit'>Save bill</button></form>")


def err(msg, status):
    return page(f"<div id='result' class='err' data-status='error'>{e(msg)}</div>", status)


@app.post("/bills")
def create(invoice_no: str = Form(...), vendor: str = Form(...), amount: float = Form(...),
           invoice_date: str = Form(""), due_date: str = Form(""), memo: str = Form("")):
    if amount <= 0:
        return err("Amount must be positive", 422)
    if fault["remaining"] > 0 and fault["mode"] == "fail_before_commit":
        fault["remaining"] -= 1
        return err("503 Service unavailable (nothing saved)", 503)
    with db() as c:
        q(c, "insert into bills(invoice_no,vendor,amount,invoice_date,due_date,memo) values(%s,%s,%s,%s,%s,%s)",
          (invoice_no, vendor, amount, invoice_date, due_date, memo))
    if fault["remaining"] > 0 and fault["mode"] == "commit_then_500":
        fault["remaining"] -= 1
        return err("500 Gateway error while saving - please retry", 500)  # record WAS saved!
    return RedirectResponse(f"/bills?created={invoice_no}", status_code=303)


@app.get("/api/bills")
def api_bills():
    with db() as c:
        return q(c, "select * from bills order by id")


class Fault(BaseModel):
    mode: str  # commit_then_500 | fail_before_commit
    count: int = 1


@app.post("/admin/fault")
def set_fault(f: Fault):
    fault.update(mode=f.mode, remaining=f.count)
    return fault


@app.post("/admin/reset")
def reset():
    fault.update(mode=None, remaining=0)
    seed(reset=True)
    return {"ok": True}


@app.get("/admin/state")
def state():
    return fault

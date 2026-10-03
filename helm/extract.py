"""Invoice text -> structured fields. Rules first, optional Ollama fallback for missing fields."""
import re
from datetime import datetime
from pathlib import Path
from . import config
from .llm import ollama_json

ALIASES = {
    "invoice_no": ["invoice no", "invoice number", "invoice #", "invoice", "inv no", "inv #"],
    "vendor": ["vendor", "supplier", "billed by"],
    "amount": ["total", "amount due", "total due", "grand total", "amount"],
    "invoice_date": ["invoice date", "date", "issued"],
    "due_date": ["due date", "due", "payment due"],
    "memo": ["notes", "note", "memo", "description"],
}
LABEL_TO_FIELD = {a: f for f, al in ALIASES.items() for a in al}
REQUIRED = ["invoice_no", "vendor", "amount", "due_date"]
DATE_FORMATS = ["%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%B %d, %Y"]


def _amount(s):
    m = re.search(r"\d[\d,]*(?:\.\d{1,2})?", s or "")
    return round(float(m.group(0).replace(",", "")), 2) if m else None


def _date(s):
    s = (s or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _currency(s):
    s = s or ""
    for code, sym in (("EUR", "€"), ("GBP", "£"), ("INR", "₹")):
        if code in s.upper() or sym in s:
            return code
    return "USD"


def _rules(text):
    raw = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        field = LABEL_TO_FIELD.get(label.strip().lower())
        if field and field not in raw and value.strip():
            raw[field] = value.strip()
    return raw


def _normalize(raw):
    return {
        "invoice_no": raw.get("invoice_no"),
        "vendor": raw.get("vendor"),
        "amount": _amount(raw.get("amount")),
        "currency": _currency(raw.get("amount")),
        "invoice_date": _date(raw.get("invoice_date")) or "",
        "due_date": _date(raw.get("due_date")),
        "memo": raw.get("memo") or "",
    }


def parse_invoice(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    f = _normalize(_rules(text))
    missing = [k for k in REQUIRED if not f.get(k)]
    source = "rules"
    if missing and config.OLLAMA_MODEL:
        llm = ollama_json(
            "Extract invoice fields as JSON with keys invoice_no, vendor, amount (string incl. currency), "
            "invoice_date, due_date, memo. Use null if absent. Never guess.\n\n" + text)
        if llm:
            merged = {**_rules(text), **{k: str(v) for k, v in llm.items() if v}}
            f2 = _normalize(merged)
            f = {k: f.get(k) or f2.get(k) for k in f2} | {"currency": f2["currency"]}
            missing = [k for k in REQUIRED if not f.get(k)]
            source = "rules+ollama"
    err = None
    if missing:
        err = "missing required field(s): " + ", ".join(missing)
    elif f["currency"] != "USD":
        err = f"non-USD currency ({f['currency']}); ERP is USD-only"
    return {"file": path.name, **f, "status": "pending", "note": "", "screenshot": "",
            "parse_error": err, "parsed_by": source}

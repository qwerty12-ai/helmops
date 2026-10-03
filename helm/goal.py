"""Plain-English goal -> structured Plan. Ollama if configured, else regex rules."""
import re
from dataclasses import dataclass, field
from . import config
from .llm import ollama_json


@dataclass
class Plan:
    raw: str
    include_vendors: list = field(default_factory=list)
    exclude_vendors: list = field(default_factory=list)
    max_amount: float | None = None
    min_amount: float | None = None
    due_before: str | None = None
    authority: float = config.DEFAULT_AUTHORITY
    source: str = "rules"


NUM = r"\$?\s*(\d[\d,]*(?:\.\d+)?k?)"
AUTH_PATTERNS = [
    rf"(?:ask|approval|approve|confirm|check)[^.;]*?(?:over|above|exceeding|more than|greater than)\s*{NUM}",
    rf"(?:up to|under|below|within)\s*{NUM}\s*(?:is fine|without (?:asking|approval)|no approval|automatically)",
    rf"auto[- ]?approve[^.;]*?{NUM}",
]
NEG = r",|\band\b|\bbut\b|\bthen\b|\bprocess\b|\benter\b"


def _num(s):
    s = s.replace(",", "").strip()
    mult = 1000 if s.lower().endswith("k") else 1
    return float(s.rstrip("kK")) * mult


def parse_goal(goal: str, known_vendors: list[str]) -> Plan:
    plan = Plan(raw=goal)
    llm = ollama_json(
        "Convert this accounts-payable instruction to JSON with keys include_vendors (list), "
        "exclude_vendors (list), max_amount (number|null), due_before (YYYY-MM-DD|null), "
        f"authority_usd (number|null: amounts above this need human approval). Known vendors: {known_vendors}.\n"
        f"Instruction: {goal}")
    if llm:
        try:
            lv = {v.lower(): v for v in known_vendors}
            plan.include_vendors = [lv[x.lower()] for x in llm.get("include_vendors") or [] if x.lower() in lv]
            plan.exclude_vendors = [lv[x.lower()] for x in llm.get("exclude_vendors") or [] if x.lower() in lv]
            plan.max_amount = float(llm["max_amount"]) if llm.get("max_amount") else None
            plan.due_before = llm.get("due_before") or None
            if llm.get("authority_usd"):
                plan.authority = float(llm["authority_usd"])
            plan.source = "ollama"
            return plan
        except Exception:
            plan = Plan(raw=goal)

    text = goal
    for pat in AUTH_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            plan.authority = _num(m.group(1))
            text = text[:m.start()] + " " + text[m.end():]
            break
    low = text.lower()
    m = re.search(rf"(?:under|below|less than|at most|no more than)\s*{NUM}", low)
    if m:
        plan.max_amount = _num(m.group(1))
    m = re.search(rf"(?:at least|minimum of|no less than)\s*{NUM}", low)
    if m:
        plan.min_amount = _num(m.group(1))
    m = re.search(r"due\s+(?:before|by|on or before)\s+(\d{4}-\d{2}-\d{2})", low)
    if m:
        plan.due_before = m.group(1)
    for v in known_vendors:
        i = low.find(v.lower())
        if i < 0:
            continue
        prefix = re.split(NEG, low[max(0, i - 30):i])[-1]
        if re.search(r"\b(skip|except|exclude|excluding|ignore|without|not|other than)\b", prefix):
            plan.exclude_vendors.append(v)
        else:
            plan.include_vendors.append(v)
    return plan


def filter_reason(plan: Plan, it: dict):
    """Why this invoice is out of scope for the goal, or None if in scope."""
    v = (it.get("vendor") or "").lower()
    if plan.include_vendors and v not in [x.lower() for x in plan.include_vendors]:
        return "vendor not requested in goal"
    if v in [x.lower() for x in plan.exclude_vendors]:
        return "vendor excluded by goal"
    if plan.max_amount is not None and it.get("amount") and it["amount"] > plan.max_amount:
        return f"amount above goal limit ${plan.max_amount:,.2f}"
    if plan.min_amount is not None and it.get("amount") and it["amount"] < plan.min_amount:
        return f"amount below goal limit ${plan.min_amount:,.2f}"
    if plan.due_before and it.get("due_date") and it["due_date"] >= plan.due_before:
        return f"not due before {plan.due_before}"
    return None

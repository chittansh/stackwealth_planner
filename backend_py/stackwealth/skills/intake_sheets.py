"""Deterministic, field- and instrument-agnostic XLSX section parsers.

Replaces LLM extraction for spreadsheet uploads. Every sheet is read by finding
its header row and mapping columns / row-labels by KEYWORD (never fixed cell
position), so any column layout works. The value column is chosen by meaning
(prefer an explicit 'Total Value' over a per-share 'Current Value' over a
'Price'), foreign-currency holdings are converted to INR, and ANY labelled
field that doesn't map to a schema slot is captured into `extra_inputs` so
nothing in the file is silently dropped — it is instrument- and field-agnostic.

Entry point: `parse_workbook(wb) -> dict` returns a partial-state dict in the
same shape the LLM emitted, so it slots straight into the intake pipeline.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

# ── Primitives ──────────────────────────────────────────────────────────────

_FOREIGN_CCY = ("usd", "us$", "dollar", "eur", "gbp", "$")
_USD_INR = 86.0  # approx spot; foreign holdings → INR so 95,200 USD ≠ ₹95,200

# Row labels that mean "this is a total/summary line, not a data row".
_TOTAL_WORDS = ("total", "subtotal", "grand total", "sum ", "summary",
                "net worth", "networth")

# Value-column detection: prefer the holding's CURRENT/TOTAL value; never read an
# 'invested/principal/cost' column, a folio/quantity ID, a per-share price, or a
# rate as the value. Lower index in _VALUE_PRIORITY = stronger preference.
_VALUE_PRIORITY = (
    "total current value", "total value", "market value", "current value",
    "present value", "current amount", "value inr", "maturity value",
    "closing balance", "fund value", "corpus", "balance", "value", "amount",
)
_VALUE_EXCLUDE = (
    "invested", "principal", "purchase", "cost", "folio", "quantity", "units",
    "qty", "rate", "interest", "loan", "rental", "monthly", "premium", "emi",
    "price", "nav", "ltp", "tenure", "date", "year", "age",
)


def _find_value_col(header_low: list[str]) -> Optional[int]:
    """Pick the column holding each row's current value, by header keyword
    priority, skipping invested/folio/quantity/price/rate columns."""
    best, best_rank = None, 999
    for j, c in enumerate(header_low):
        if not c or any(x in c for x in _VALUE_EXCLUDE):
            continue
        for rank, kw in enumerate(_VALUE_PRIORITY):
            if kw in c:
                if rank < best_rank:
                    best, best_rank = j, rank
                break
    return best


_NAME_KW = ("instrument", "scheme", "fund name", "stock name", "asset", "fund",
            "stock", "particular", "holding", "security", "property", "policy",
            "name", "category", "type", "metal")


def _find_name_col(header_low: list[str]) -> int:
    for j, c in enumerate(header_low):
        if c and any(k in c for k in _NAME_KW) and "value" not in c and "amount" not in c:
            return j
    return 0


def _amt(v: Any) -> Optional[float]:
    """Coerce a cell to a rupee amount. Handles plain numbers and Indian text
    like '2 Crore', '25L', '1.5cr', '₹2,00,000'. Returns None if not numeric."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().lower().replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
    if not s:
        return None
    m = re.search(r"(-?\d+\.?\d*)\s*(crore|cr|lakhs?|lacs?|l|k)?", s)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").strip()
    if unit in ("crore", "cr"):
        num *= 1e7
    elif unit in ("lakh", "lakhs", "lac", "lacs", "l"):
        num *= 1e5
    elif unit == "k":
        num *= 1e3
    return num


def _txt(v: Any) -> str:
    if v in (None, ""):
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10]
    return str(v).strip()


def _norm(v: Any) -> str:
    """Lowercase, strip punctuation — for keyword matching on headers/labels."""
    return re.sub(r"[^a-z0-9 ]", " ", str(v or "").lower()).strip()


def _is_total_label(label: str) -> bool:
    nl = _norm(label)
    return any(w.strip() in nl for w in _TOTAL_WORDS)


def _find_sheet(wb, keywords, exclude=()):
    for sn in wb.sheetnames:
        l = sn.lower()
        if any(k in l for k in keywords) and not any(e in l for e in exclude):
            return wb[sn]
    return None


def _rows(ws) -> list[tuple]:
    return list(ws.iter_rows(values_only=True))


def _find_header(rows: list[tuple], role_kw: dict[str, tuple], *, require=("name",), max_scan=10):
    """Find the header row and a {role: col_index} map. A column is assigned to a
    role if its header text contains any of that role's keywords (first column
    wins per role). Returns (header_row_index, cols) or (None, None)."""
    for i, row in enumerate(rows[:max_scan]):
        low = [_norm(c) for c in row]
        if not any(low):
            continue
        cols: dict[str, int] = {}
        for role, kws in role_kw.items():
            for j, c in enumerate(low):
                if c and any(k in c for k in kws):
                    cols.setdefault(role, j)
                    break
        if all(r in cols for r in require) and len(cols) >= 2:
            return i, cols
    return None, None


def _kv_pairs(ws, max_rows=60) -> list[tuple[str, Any]]:
    """For 'label | value' sheets: return (label, first-non-empty-value-after)."""
    out = []
    for row in list(ws.iter_rows(values_only=True))[:max_rows]:
        label = next((str(c).strip() for c in row if isinstance(c, str) and str(c).strip()), None)
        if not label:
            continue
        idx = next((i for i, c in enumerate(row) if isinstance(c, str) and c.strip() == label), 0)
        value = next((c for c in row[idx + 1:] if c not in (None, "")), None)
        out.append((label, value))
    return out


# ── Holdings (instrument-agnostic list sheets: MF, equity, fixed income, …) ──

def _best_numeric_col(data_rows: list[tuple], exclude=()) -> Optional[int]:
    """Pick the column whose data is the value: most positive-numeric cells, tie
    broken by largest median magnitude (a value column dwarfs quantity/units).
    Used only as a fallback when header detection points at a non-numeric column."""
    exclude = {e for e in exclude if e is not None}
    width = max((len(r) for r in data_rows), default=0)
    best, best_score = None, ()
    for j in range(width):
        if j in exclude:
            continue
        vals = [a for a in (_amt(r[j]) for r in data_rows if j < len(r)) if a and a > 0]
        if len(vals) < 2:
            continue
        vals.sort()
        median = vals[len(vals) // 2]
        score = (len(vals), median)
        if score > best_score:
            best, best_score = j, score
    return best


def _header_row(rows: list[tuple], max_scan=10):
    """Find the row that is a header for a holdings list (has a name-like column
    AND a value-like column). Returns (idx, normalized_header) or (None, None)."""
    for i, row in enumerate(rows[:max_scan]):
        low = [_norm(c) for c in row]
        if not any(low):
            continue
        if any(any(k in c for k in _NAME_KW) for c in low) and _find_value_col(low) is not None:
            return i, low
    return None, None


def _parse_holding_list(ws, name_field: str, *, with_sip=False) -> list[dict]:
    """Generic per-row asset list, INSTRUMENT-AGNOSTIC: detect the name + value
    (+ sip + currency) columns by header keyword, extract every row regardless of
    instrument, convert foreign currency, skip total/summary rows. Folio /
    quantity / invested / price columns are never read as the value."""
    rows = _rows(ws)
    hdr, low = _header_row(rows)
    if hdr is None:
        return []
    name_c = _find_name_col(low)
    val_c = _find_value_col(low)
    sip_c = next((j for j, c in enumerate(low) if c and ("sip" in c or "monthly amount" in c or "monthly invest" in c)), None)
    cur_c = next((j for j, c in enumerate(low) if c and ("currency" in c or c == "ccy")), None)
    data = rows[hdr + 1:]
    # Header-misalignment fallback: some firm templates have shifted headers where
    # the "Current Value" label sits over a text column and the real amounts live
    # under a differently-labelled column. If the header-chosen column yields no
    # numbers across the data rows, re-pick by data (largest-magnitude numeric
    # column, which is the value — not quantity/price-per-share).
    if val_c is None or not any(_amt(r[val_c]) for r in data if val_c < len(r)):
        val_c = _best_numeric_col(data, exclude={name_c, sip_c, cur_c})
    out: list[dict] = []
    for row in rows[hdr + 1:]:
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        if _is_total_label(nm):
            break
        val = _amt(row[val_c]) if val_c is not None and val_c < len(row) else None
        if val is None or val <= 0:
            continue
        if cur_c is not None and cur_c < len(row):
            ccy = str(row[cur_c] or "").lower()
            if any(f in ccy for f in _FOREIGN_CCY):
                val *= _USD_INR
        rec: dict[str, Any] = {name_field: nm.strip(), "current_value": round(val, 2)}
        if with_sip and sip_c is not None and sip_c < len(row):
            sip = _amt(row[sip_c])
            if sip and sip > 0:
                rec["sip_amount"] = round(sip, 2)
        out.append(rec)
    return out


# ── Section parsers ─────────────────────────────────────────────────────────

def parse_mutual_funds(wb) -> list[dict]:
    ws = _find_sheet(wb, ("mutual", "4a"))
    return _parse_holding_list(ws, "fund_name", with_sip=True) if ws else []


def parse_equity(wb) -> list[dict]:
    ws = _find_sheet(wb, ("equity", "4b", "stock"))
    return _parse_holding_list(ws, "stock_name") if ws else []


_FI_MAP = [
    (("sukanya",), "SukanyaSamriddhi"), (("post office", "posa", "post-office"), "PostOffice"),
    (("ppf",), "PPF"), (("epf", "vpf", "provident"), "EPF"), (("nsc",), "NSC"),
    (("nps",), "NPS"), (("bond", "debenture", "ncd"), "Bonds"),
    (("rd", "recurring"), "RD"), (("fd", "fixed deposit", "term deposit"), "FD"),
]


def _fi_instrument(name: str) -> str:
    nl = _norm(name)
    for kws, inst in _FI_MAP:
        if any(k in nl for k in kws):
            return inst
    return "Other"


def parse_fixed_income(wb) -> list[dict]:
    ws = _find_sheet(wb, ("fixed", "4c", "debt"), exclude=("income_det",))
    if ws is None:
        return []
    rows = _rows(ws)
    hdr, low = _header_row(rows)
    if hdr is None:
        return []
    name_c = _find_name_col(low)
    val_c = _find_value_col(low)  # 'Current Value', never 'Invested Amount'
    inv_c = next((j for j, c in enumerate(low) if c and ("invested" in c or "principal" in c)), None)
    mat_c = next((j for j, c in enumerate(low) if c and "maturity" in c and "value" not in c), None)
    out = []
    for row in rows[hdr + 1:]:
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        if _is_total_label(nm):
            break
        cv = _amt(row[val_c]) if val_c is not None and val_c < len(row) else None
        iv = _amt(row[inv_c]) if inv_c is not None and inv_c < len(row) else None
        if (cv is None or cv <= 0) and (iv is None or iv <= 0):
            continue
        rec: dict[str, Any] = {"instrument": _fi_instrument(nm), "notes": nm.strip()}
        if cv and cv > 0:
            rec["current_value"] = round(cv, 2)
        if iv and iv > 0:
            rec["invested_amount"] = round(iv, 2)
        if mat_c is not None and mat_c < len(row) and row[mat_c] not in (None, ""):
            rec["maturity_date"] = _txt(row[mat_c])
        out.append(rec)
    return out


def _kind_real_estate(name: str) -> str:
    nl = _norm(name)
    if any(k in nl for k in ("plot", "land", "site")):
        return "land"
    if any(k in nl for k in ("shop", "office", "commercial", "warehouse")):
        return "commercial"
    if any(k in nl for k in ("apartment", "flat", "villa", "house", "home", "residential", "property")):
        return "residential"
    return "other"


def parse_real_estate(wb) -> list[dict]:
    ws = _find_sheet(wb, ("real estate", "real_estate", "4d", "property"))
    if ws is None:
        return []
    rows = _rows(ws)
    hdr, low = _header_row(rows)
    if hdr is None:
        return []
    name_c, val_c = _find_name_col(low), _find_value_col(low)  # market value, not loan/rental
    out = []
    for row in rows[hdr + 1:]:
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        if _is_total_label(nm):
            break
        val = _amt(row[val_c]) if val_c is not None and val_c < len(row) else None
        if val is None or val <= 0:
            continue
        out.append({"label": nm.strip(), "kind": _kind_real_estate(nm), "current_value": round(val, 2)})
    return out


def parse_gold(wb) -> list[dict]:
    ws = _find_sheet(wb, ("gold", "4e", "bullion"))
    if ws is None:
        return []
    rows = _rows(ws)
    hdr, low = _header_row(rows)
    if hdr is None:
        return []
    name_c, val_c = _find_name_col(low), _find_value_col(low)
    out = []
    for row in rows[hdr + 1:]:
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        if _is_total_label(nm):
            break
        val = _amt(row[val_c]) if val_c is not None and val_c < len(row) else None
        if val is None or val <= 0:
            continue
        nl = _norm(nm)
        kind = "sgb" if ("sgb" in nl or "sovereign" in nl) else "digital" if "digital" in nl else "jewellery" if "jewel" in nl else "physical"
        out.append({"label": nm.strip(), "kind": kind, "current_value": round(val, 2), "held_for_investment": True})
    return out


_INCOME_ROW_MAP = [
    (("salary", "in hand", "in-hand", "take home", "employment"), "salary_in_hand"),
    (("business", "profession", "self emp"), "business_income"),
    (("rental", "rent income", "house property"), "rental_income"),
    (("other", "misc", "dividend", "interest income"), "other_income"),
]


def parse_income(wb) -> dict:
    """Income sheet: 'Income Source | Client | Spouse | Total' (multi-column) or
    'Source | Amount'. Maps each row-label to client_/spouse_ × salary/business/
    rental/other. Picks the Client and Spouse columns by header."""
    ws = _find_sheet(wb, ("income", "2_"))
    if ws is None:
        return {}
    rows = _rows(ws)
    hdr, cols = _find_header(rows, {
        "name": ("income source", "source", "particular", "head", "type"),
        "client": ("client", "self", "primary", "applicant"),
        "spouse": ("spouse", "wife", "husband", "co-applicant", "partner"),
        "amount": ("amount", "monthly", "total", "value"),
    }, require=("name",))
    if hdr is None:
        # Firm template: a 'label | value' inflow list (Gross Salary / Business /
        # Rental / Other) with a Deductions section below that we must NOT read as
        # income. Walk kv pairs, stop at the first deductions/outflow boundary.
        out: dict[str, float] = {}
        for label, value in _kv_pairs(ws, max_rows=40):
            nl = _norm(label)
            if any(b in nl for b in ("deduction", "outflow", "net income", "net salary",
                                     "take home", "surplus", "expense", "tax from", "taxes from")):
                break
            if _is_total_label(label):
                continue
            field = next((f for kws, f in _INCOME_ROW_MAP if any(k in nl for k in kws)), None)
            if not field:
                continue
            a = _amt(value)
            if a is not None and a > 0:
                out.setdefault(f"client_{field}", round(a, 2))
        return out
    client_c = cols.get("client")
    spouse_c = cols.get("spouse")
    # No explicit client/spouse split → use the single amount column.
    amount_c = cols.get("amount")
    out: dict[str, float] = {}
    for row in rows[hdr + 1:]:
        nm = row[cols["name"]] if cols["name"] < len(row) else None
        if not (isinstance(nm, str) and nm.strip()) or _is_total_label(nm):
            continue
        field = next((f for kws, f in _INCOME_ROW_MAP if any(k in _norm(nm) for k in kws)), None)
        if not field:
            continue
        if client_c is not None or spouse_c is not None:
            cv = _amt(row[client_c]) if client_c is not None and client_c < len(row) else None
            sv = _amt(row[spouse_c]) if spouse_c is not None and spouse_c < len(row) else None
            if cv and cv > 0:
                out[f"client_{field}"] = round(cv, 2)
            if sv and sv > 0:
                out[f"spouse_{field}"] = round(sv, 2)
        elif amount_c is not None and amount_c < len(row):
            av = _amt(row[amount_c])
            if av and av > 0:
                out[f"client_{field}"] = round(av, 2)
    return out


_LIQUID_MAP = [
    (("saving", "bank balance", "sb "), "savings_account_balance"),
    (("idle cash", "idle", "cash for"), "idle_cash_for_investment"),
    (("fd breakable", "breakable", "liquid fd"), "fd_breakable_for_investment"),
    (("bonus expected", "bonus"), "bonus_expected_for_investment"),
]


def parse_liquid_capital(wb) -> dict:
    ws = _find_sheet(wb, ("liquid", "6_"))
    if ws is None:
        return {}
    out: dict[str, float] = {}
    for label, value in _kv_pairs(ws):
        if _is_total_label(label):
            continue
        field = next((f for kws, f in _LIQUID_MAP if any(k in _norm(label) for k in kws)), None)
        if not field:
            continue
        a = _amt(value)
        if a is not None and a > 0:
            out[field] = round(a, 2)
    return out


def parse_emergency_fund(wb) -> dict:
    ws = _find_sheet(wb, ("emergency", "7_"))
    if ws is None:
        return {}
    out: dict[str, Any] = {}
    for label, value in _kv_pairs(ws):
        nl = _norm(label)
        if "available" in nl and "fund" in nl:
            out["emergency_fund_available"] = str(value).strip().lower().startswith("y") if value is not None else None
        elif "corpus" in nl or ("total" in nl and "emergency" in nl):
            a = _amt(value)
            if a is not None:
                out["total_emergency_corpus"] = round(a, 2)
        elif "parked" in nl or "where" in nl:
            if _txt(value):
                out["where_is_it_parked"] = _txt(value)
        elif "monthly" in nl and ("household" in nl or "expense" in nl):
            a = _amt(value)
            if a is not None:
                out["monthly_household_expense_for_calculation"] = round(a, 2)
        elif "month" in nl and "cover" in nl:
            a = _amt(value)
            if a is not None:
                out["months_of_cover_available"] = a
    return {k: v for k, v in out.items() if v is not None}


_LOAN_MAP = [
    (("home", "housing", "mortgage"), "home_loan"),
    (("car", "vehicle", "auto"), "car_loan"),
    (("personal",), "personal_loan"),
    (("credit card", "card dues", "cc dues"), "credit_card_dues"),
]


def parse_loans(wb) -> dict:
    ws = _find_sheet(wb, ("loan", "liabilit", "8_"))
    if ws is None:
        return {}
    rows = _rows(ws)
    hdr, cols = _find_header(rows, {
        "name": ("loan type", "loan", "liability", "type", "particular"),
        "outstanding": ("outstanding", "balance", "principal", "amount due"),
        "emi": ("emi", "instal", "monthly"),
        "rate": ("interest rate", "rate", "roi"),
        "tenure": ("tenure", "term", "months left", "years left", "remaining"),
    })
    if hdr is None:
        return {}
    out: dict[str, dict] = {}
    for row in rows[hdr + 1:]:
        nm = row[cols["name"]] if cols["name"] < len(row) else None
        if not (isinstance(nm, str) and nm.strip()) or _is_total_label(nm):
            continue
        key = next((k for kws, k in _LOAN_MAP if any(w in _norm(nm) for w in kws)), None)
        if not key:
            continue
        blk: dict[str, float] = {}
        if "outstanding" in cols and cols["outstanding"] < len(row):
            a = _amt(row[cols["outstanding"]])
            if a and a > 0:
                blk["outstanding_amount"] = round(a, 2)
        if "emi" in cols and cols["emi"] < len(row):
            a = _amt(row[cols["emi"]])
            if a and a > 0:
                blk["emi"] = round(a, 2)
        if "rate" in cols and cols["rate"] < len(row):
            a = _amt(row[cols["rate"]])
            if a and a > 0:
                blk["interest_rate"] = a  # may be 0.0845 or 8.45
        if "tenure" in cols and cols["tenure"] < len(row):
            a = _amt(row[cols["tenure"]])
            if a and a > 0:
                blk["tenure_left"] = a
        if blk:
            out[key] = blk
    return out


_INSURANCE_MAP = [
    (("term",), "term_plan"),
    (("health", "medical", "mediclaim"), "health_insurance"),
    (("family floater", "floater"), "family_floater"),
    (("ulip", "endowment", "money back", "moneyback", "whole life"), "ulip_or_endowment"),
]


def parse_insurance(wb) -> dict:
    ws = _find_sheet(wb, ("insurance", "9_"), exclude=("computation",))
    if ws is None:
        return {}
    rows = _rows(ws)
    hdr, cols = _find_header(rows, {
        "name": ("policy type", "policy", "type", "particular", "cover type"),
        "company": ("company", "insurer", "provider"),
        "cover": ("cover amount", "cover", "sum assured", "sum insured"),
        "premium": ("annual premium", "premium"),
    })
    if hdr is None:
        return {}
    out: dict[str, dict] = {}
    for row in rows[hdr + 1:]:
        nm = row[cols["name"]] if cols["name"] < len(row) else None
        if not (isinstance(nm, str) and nm.strip()) or _is_total_label(nm):
            continue
        key = next((k for kws, k in _INSURANCE_MAP if any(w in _norm(nm) for w in kws)), None)
        if not key:
            continue
        blk: dict[str, Any] = {}
        if "company" in cols and cols["company"] < len(row) and _txt(row[cols["company"]]):
            blk["company"] = _txt(row[cols["company"]])
        if "cover" in cols and cols["cover"] < len(row):
            a = _amt(row[cols["cover"]])
            if a and a > 0:
                blk["cover_amount"] = round(a, 2)
        if "premium" in cols and cols["premium"] < len(row):
            a = _amt(row[cols["premium"]])
            if a and a > 0:
                blk["annual_premium"] = round(a, 2)
        if blk:
            out[key] = blk
    return out


# Personal-detail labels → PlanState.personal_details fields. Anything not here
# is captured into extra_inputs by the catch-all (so dependents/occupation/etc.
# are kept even before a field exists for them — but these DO have fields).
_PERSONAL_MAP = [
    (("full name", "client name", "name of"), "full_name", "text"),
    (("date of birth", "dob", "birth date"), "date_of_birth", "date"),
    (("pan",), "pan", "text"),
    (("email",), "email", "text"),
    (("mobile", "phone", "contact"), "mobile", "text"),
    (("address",), "address", "text"),
    (("marital",), "marital_status", "text"),
    (("spouse name",), "spouse_name_and_age", "text"),
    (("number of children", "no of children", "children", "kids"), "number_of_children", "num"),
    (("dependent",), "dependents", "text"),
    (("city of residence", "city", "location", "residence"), "city_of_residence", "text"),
    (("occupation", "profession"), "occupation", "text"),
    (("retirement age",), "retirement_age_target", "num"),
]


def parse_personal(wb) -> tuple[dict, list[dict]]:
    """Returns (personal_details dict, extra rows for extra_inputs). Handles BOTH
    layouts: a simple 'Question | Answer' Q&A (Vignesh/Depressed) and a
    multi-person 'Family Details | Name | Date Of Birth | Age | Retirement' table
    (firm template)."""
    ws = _find_sheet(wb, ("personal", "1_", "basic detail", "client detail"))
    if ws is None:
        return {}, []
    pd: dict[str, Any] = {}
    extras: list[dict] = []
    rows = _rows(ws)

    # ── Multi-person 'Family Details' table (firm template) ──
    thdr = tlow = None
    for i, row in enumerate(rows[:8]):
        low = [_norm(c) for c in row]
        if any(("date of birth" in c or c == "dob" or "birth" in c) for c in low) and any("name" in c for c in low):
            thdr, tlow = i, low
            break
    if thdr is not None:
        role_c = 0
        name_c = next((j for j, c in enumerate(tlow) if "name" in c and "birth" not in c), 1)
        dob_c = next((j for j, c in enumerate(tlow) if "birth" in c or c == "dob"), None)
        for row in rows[thdr + 1:]:
            role = _txt(row[role_c]) if role_c < len(row) else ""
            nm = _txt(row[name_c]) if name_c < len(row) else ""
            if not nm or _is_total_label(role):
                continue
            rl = _norm(role)
            dob = _txt(row[dob_c]) if dob_c is not None and dob_c < len(row) else ""
            if any(k in rl for k in ("client", "self", "applicant", "primary")) and "co" not in rl:
                pd["full_name"] = nm
                if dob:
                    pd["date_of_birth"] = dob
            elif any(k in rl for k in ("spouse", "wife", "husband", "partner")):
                pd["spouse_name_and_age"] = nm
            else:  # children, parents, dependents
                extras.append({"label": (role or "Dependent")[:160],
                               "value": (f"{nm} (DOB {dob})" if dob else nm)[:200], "sheet": ws.title})
        if pd:
            return pd, extras

    # ── Simple 'Question | Answer' Q&A ──
    for label, value in _kv_pairs(ws):
        nl = _norm(label)
        if nl in ("questions", "details to be filled by client", "particular", "field"):
            continue
        if value in (None, ""):
            continue
        field = ftype = None
        for kws, f, t in _PERSONAL_MAP:
            if any(k in nl for k in kws):
                field, ftype = f, t
                break
        if field:
            if ftype == "num":
                a = _amt(value)
                if a is not None:
                    pd[field] = a
            elif ftype == "date":
                pd[field] = _txt(value)
            else:
                pd[field] = _txt(value)
        else:
            extras.append({"label": label.strip()[:160], "value": _txt(value)[:200], "sheet": ws.title})
    return pd, extras


# ── Orchestrator ────────────────────────────────────────────────────────────

def parse_workbook(wb) -> dict[str, Any]:
    """Run every deterministic section parser and assemble a partial-state dict
    in the LLM's shape. Empty sections are omitted so callers can fall back."""
    state: dict[str, Any] = {}

    pd, pd_extras = parse_personal(wb)
    if pd:
        state["personal_details"] = pd

    for key, fn in (
        ("income_details", parse_income),
        ("liquid_capital", parse_liquid_capital),
        ("emergency_fund", parse_emergency_fund),
        ("loans_liabilities", parse_loans),
        ("insurance_details", parse_insurance),
    ):
        v = fn(wb)
        if v:
            state[key] = v

    for key, fn in (
        ("mutual_funds", parse_mutual_funds),
        ("equity_stocks", parse_equity),
        ("fixed_income", parse_fixed_income),
        ("real_estate", parse_real_estate),
        ("gold", parse_gold),
    ):
        v = fn(wb)
        if v:
            state[key] = v

    if pd_extras:
        state["_personal_extras"] = pd_extras
    return state

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
# Headers that UNAMBIGUOUSLY aren't the holding value — safe to exclude even in
# the header-agnostic magnitude fallback (unlike price/cost/value, which can be
# the real value column under a shifted firm header).
_SAFE_NONVALUE_KW = (
    "folio", "quantity", "units", "qty", "isin", "tenure", "date", "year", "age",
    "rate", "roi", "%",
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


# Rows that look like holdings but are actually a re-classification / summary block
# the firm appends BELOW a holdings list (restating the SAME portfolio by tag or
# liquidity). Counting them double-counts the portfolio (e.g. equity sheets append
# "Considered for playing in Equity" + "Available for sale" = the same total again).
# Once a row's name matches, the list has ended — stop reading.
_STOP_LABEL_KW = (
    "considered for playing", "available for sale", "by tag", "summary",
    "classification", "bifurcation", "break up", "breakup", "break-up",
    "as per risk",
)


def _is_stop_label(label: str) -> bool:
    nl = _norm(label)
    return _is_total_label(label) or any(w in nl for w in _STOP_LABEL_KW)


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
        # Exclude only columns whose header UNAMBIGUOUSLY isn't a value (folio /
        # quantity / units / dates / rates). NOT price/cost/value — on a shifted
        # firm header the real amounts can sit under a "Current Price" label, and
        # the whole point of this data-driven pick is to survive that.
        non_value = {j for j, c in enumerate(low)
                     if c and any(k in c for k in _SAFE_NONVALUE_KW)}
        val_c = _best_numeric_col(data, exclude={name_c, sip_c, cur_c} | non_value)
    out: list[dict] = []
    for row in rows[hdr + 1:]:
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        # Stop at a Total OR a re-classification/summary block ("Considered for
        # playing in Equity", "Available for sale", "By Tag" …) — those restate the
        # SAME portfolio and would double-count it.
        if _is_stop_label(nm):
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
        if _is_stop_label(nm):
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
        if _is_stop_label(nm):
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
        if _is_stop_label(nm):
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
    (("other", "misc", "dividend", "interest income", "investment"), "other_income"),
]
# Deduction rows in the firm's 2_Income "Deductions (Mandatory Cash Outflow)"
# section — captured so true NET income can be computed (gross − deductions).
_INCOME_DEDUCTION_MAP = [
    (("tax",), "taxes"),
    (("provident", "epf", " pf", "vpf"), "provident_fund"),
]
# Labels that mark the start of the deductions section / the net subtotal.
_DEDUCTION_MARKERS = ("deduction", "mandatory cash outflow")
_NET_MARKERS = ("net income", "net salary", "net monthly", "take home", "iii.")


def parse_income(wb) -> dict:
    """Income sheet, instrument-agnostic. Handles three shapes:
      • multi-column 'Particulars | Client | Spouse | Others | Total' (header
        keywords OR proper names like 'Mr Naga'/'Mrs Shweta' → positional)
      • single 'Source | Amount'
      • firm-template 'label | value' inflow list
    Walks the Income section, then the Deductions section (taxes / PF), and stops
    at the Net subtotal — so a 'Taxes from Salary' row can never be mistaken for
    salary income."""
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
        return _parse_income_kv(ws)

    name_c = cols["name"]
    header = [_norm(c) for c in rows[hdr]]
    total_c = next((j for j, h in enumerate(header) if h and "total" in h), None)
    client_c, spouse_c = cols.get("client"), cols.get("spouse")
    extra_cols: list[int] = []
    if client_c is None and spouse_c is None:
        # Person columns weren't named 'client'/'spouse' (e.g. 'Mr Naga' / 'Mrs
        # Shweta' / 'Others/Family'). Detect positionally: labelled columns after
        # the name column that actually carry numeric data, excluding the Total.
        persons = [j for j in range(name_c + 1, len(header))
                   if header[j] and j != total_c
                   and not any(k in header[j] for k in ("total", "sr", "note", "remark"))
                   and any(_amt(r[j]) for r in rows[hdr + 1:hdr + 14] if j < len(r))]
        if persons:
            client_c = persons[0]
            spouse_c = persons[1] if len(persons) > 1 else None
            extra_cols = persons[2:]            # 'Others/Family' etc. → fold into client
        else:
            client_c = total_c                  # no split — use the single amount/Total

    def _split(row):
        cv = _amt(row[client_c]) if client_c is not None and client_c < len(row) else None
        sv = _amt(row[spouse_c]) if spouse_c is not None and spouse_c < len(row) else None
        extra = sum((_amt(row[j]) or 0) for j in extra_cols if j < len(row))
        return (round((cv or 0) + extra, 2) if (cv or extra) else 0,
                round(sv, 2) if sv and sv > 0 else 0)

    out: dict[str, float] = {}
    section = "income"
    for row in rows[hdr + 1:]:
        # Section dividers ("I. Gross Income", "II. Deductions", "III. Net
        # Income") often sit in column A, not the name column — scan the whole row.
        row_text = _norm(" ".join(str(c) for c in row if isinstance(c, str)))
        if section == "income" and any(m in row_text for m in _DEDUCTION_MARKERS):
            section = "deduction"
            continue
        if section == "deduction" and any(m in row_text for m in _NET_MARKERS):
            break
        nm = row[name_c] if name_c < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        nl = _norm(nm)
        if _is_total_label(nm):
            continue
        cval, sval = _split(row)
        if section == "income":
            field = next((f for kws, f in _INCOME_ROW_MAP if any(k in nl for k in kws)), None)
            if not field:
                continue
            if cval > 0:
                out[f"client_{field}"] = cval
            if sval > 0:
                out[f"spouse_{field}"] = sval
        else:  # deduction
            dfield = next((f for kws, f in _INCOME_DEDUCTION_MAP if any(k in nl for k in kws)), None)
            if not dfield:
                continue
            if cval > 0:
                out[f"client_{dfield}"] = cval
            if sval > 0:
                out[f"spouse_{dfield}"] = sval
    return out


def _parse_income_kv(ws) -> dict:
    """Firm-template 'label | value' inflow list: Gross Salary / Business /
    Rental / Other, then a Deductions section (taxes / PF), stopping at Net."""
    out: dict[str, float] = {}
    section = "income"
    for label, value in _kv_pairs(ws, max_rows=40):
        nl = _norm(label)
        if section == "income" and any(m in nl for m in _DEDUCTION_MARKERS):
            section = "deduction"
            continue
        if section == "deduction" and any(m in nl for m in _NET_MARKERS):
            break
        if _is_total_label(label):
            continue
        a = _amt(value)
        if a is None or a <= 0:
            continue
        if section == "income":
            field = next((f for kws, f in _INCOME_ROW_MAP if any(k in nl for k in kws)), None)
            if field:
                out.setdefault(f"client_{field}", round(a, 2))
        else:
            dfield = next((f for kws, f in _INCOME_DEDUCTION_MAP if any(k in nl for k in kws)), None)
            if dfield:
                out.setdefault(f"client_{dfield}", round(a, 2))
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


# ── Goals ───────────────────────────────────────────────────────────────────

def _goal_kind(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("education", "college", "school", "tuition", "study")):
        return "child_education"
    if any(k in n for k in ("marriage", "wedding")):
        return "child_marriage"
    if any(k in n for k in ("retire", "fire", "pension")):
        return "retirement"
    if any(k in n for k in ("house", "home", "property", "flat", "apartment", "villa", "plot", "real estate")):
        return "house_purchase"
    if any(k in n for k in ("travel", "foreign", "vacation", "trip", "holiday", "tour")):
        return "foreign_travel"
    return "other"


def parse_goals(wb) -> list[dict]:
    """Capture EVERY named goal row — including name-only rows that carry no
    amount/year (so a goal the RM has only named still reaches the canvas). kind
    inferred from the name; target_amount taken from Today's Cost (today-money) or
    Future Value; inflation/priority/frequency captured when present."""
    ws = _find_sheet(wb, ("goal", "10_"))
    if ws is None:
        return []
    rows = _rows(ws)
    hdr, cols = _find_header(rows, {
        "name": ("goal",),
        "priority": ("importance", "priority"),
        "year": ("target year", "year"),
        "today": ("today", "current cost", "present cost", "cost"),
        "fv": ("future value", "future cost", "fv"),
        "inflation": ("inflation",),
        "frequency": ("nature", "frequency", "type"),
    }, require=("name",))
    if hdr is None:
        return []
    out: list[dict] = []
    for row in rows[hdr + 1:]:
        nm = row[cols["name"]] if cols["name"] < len(row) else None
        if not (isinstance(nm, str) and nm.strip()):
            continue
        name = nm.strip()
        nl = _norm(name)
        # The notes/assumptions block ends the real goal list — stop there.
        if nl.startswith("note") or "assumption" in nl:
            break
        # Skip bullets, sentences and total/footer rows.
        if (nl in ("goal", "goals") or _is_total_label(name) or name[0] in "•-*"
                or "total cost" in nl or "per annum" in nl or ":" in name or len(name.split()) > 6):
            continue
        pr = _txt(row[cols["priority"]]) if cols.get("priority") is not None and cols["priority"] < len(row) else ""
        yr = _amt(row[cols["year"]]) if cols.get("year") is not None and cols["year"] < len(row) else None
        today = _amt(row[cols["today"]]) if cols.get("today") is not None and cols["today"] < len(row) else None
        fv = _amt(row[cols["fv"]]) if cols.get("fv") is not None and cols["fv"] < len(row) else None
        # A real goal carries at least an importance, a target year, or an amount —
        # this filters section headers ("POST RETIREMENT REGULAR EXPENSES").
        if not (pr or (yr and 2000 <= yr <= 2100) or today or fv):
            continue
        goal: dict[str, Any] = {"goal_name": name, "kind": _goal_kind(name)}
        if yr and 2000 <= yr <= 2100:
            goal["target_year"] = int(yr)
        if today and today > 0:
            goal["target_amount"] = round(today, 2)
            goal["is_target_in_today_money"] = True
        elif fv and fv > 0:
            goal["target_amount"] = round(fv, 2)
            goal["is_target_in_today_money"] = False
        infl = _amt(row[cols["inflation"]]) if cols.get("inflation") is not None and cols["inflation"] < len(row) else None
        if infl and infl > 0:
            goal["inflation_assumed"] = round(infl / 100, 4) if infl > 1 else round(infl, 4)
        if cols.get("frequency") is not None and cols["frequency"] < len(row):
            freq = _txt(row[cols["frequency"]]).lower()
            if "annual" in freq or "year" in freq or "one" in freq:
                goal["contribution_frequency"] = "annual"
            elif "month" in freq:
                goal["contribution_frequency"] = "monthly"
        pl = pr.lower()
        if "essential" in pl or "must" in pl or "high" in pl:
            goal["priority"] = "essential"
        elif "important" in pl or "medium" in pl:
            goal["priority"] = "important"
        elif any(k in pl for k in ("desir", "aspiration", "nice", "want", "low", "optional")):
            goal["priority"] = "aspirational"
        out.append(goal)
    return out


# ── Expenses ────────────────────────────────────────────────────────────────
# Living-expense category → monthly_expenses field. Insurance is checked BEFORE
# medical so "Insurance Premium (health & LIC)" routes to insurance, not medical.
_EXPENSE_FIELD_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("school_fees", ("school", "tuition", "education fee", "college fee", "children expense", "child")),
    ("transport", ("transport", "commute", "petrol", "fuel", "car running", "conveyance")),
    ("utilities", ("utilit", "electric", "mobile", "internet", "phone", "water", "gas", "broadband", "wifi")),
    ("groceries", ("grocer", "food", "ration", "kitchen", "milk", "living expense")),
    ("insurance_premium", ("insurance", "premium", "lic")),
    ("medical", ("medical", "health", "doctor", "hospital", "pharma")),
    ("discretionary", ("entertain", "lifestyle", "leisure", "shopping", "restaurant", "gym", "dining", "discretionary")),
    ("travel_or_lifestyle", ("travel", "vacation", "holiday")),
    ("rent_or_emi", ("rent", "maintenance", "society")),
    ("other_expenses", ("other expense", "property tax", "donation", "misc")),
]


def _classify_expense(category: str, detail: str) -> tuple[str, Optional[str]]:
    """Classify a line as living expense / EMI / SIP. EMI and SIP match on WORD
    boundaries so 'premium' isn't read as an EMI; the detail column disambiguates."""
    t = f"{category} {detail}".lower()
    if re.search(r"\b(sip|mutual fund|investment)s?\b", t):
        return ("sip", None)
    if re.search(r"\b(emi|loan)s?\b", t):
        return ("emi", None)
    for field, kws in _EXPENSE_FIELD_KEYWORDS:
        if any(k in t for k in kws):
            return ("expense", field)
    return ("expense", "household_expenses")


_EXPENSE_LABEL_KW = ("category", "type of expense", "particular", "details", "head", "expense detail")


def parse_expenses(wb) -> Optional[dict]:
    """Parse the monthly-expenses sheet — capture EVERY line item, route EMI/SIP
    OUT of living expenses, reconcile to the stated total. Handles BOTH the
    'Category | Monthly Amount' layout and the firm 'Details | <persons> | Total'
    layout (section dividers + subtotals skipped, the grand 'Total Expenditure'
    stops the scan, Loan Repayments rows → EMI). Instrument-agnostic: any label is
    classified; unmapped rows fall to household_expenses so nothing is dropped.
    Returns {monthly_expenses, living, emi, sip, stated_total} or None."""
    ws = _find_sheet(wb, ("expense", "3_"), exclude=("computation",))
    if ws is None:
        return None
    rows = _rows(ws)
    # Locate the header: a label column + a value column (explicit monthly amount,
    # else a Total column, else summed person columns).
    hdr = label_c = val_c = det_c = None
    person_cols: list[int] = []
    for i, row in enumerate(rows[:20]):
        low = [_norm(c) for c in row]
        lc = next((j for j, c in enumerate(low) if c and any(k in c for k in _EXPENSE_LABEL_KW)), None)
        if lc is None:
            continue
        vc = next((j for j, c in enumerate(low) if c and "monthly" in c and ("amount" in c or "spend" in c)), None)
        if vc is None:
            vc = next((j for j, c in enumerate(low) if c and "total" in c), None)
        pcs = [j for j, c in enumerate(low) if c and j > lc and j != vc
               and not any(k in c for k in ("total", "remark", "detail", "note"))]
        if vc is None and not pcs:
            continue
        hdr, label_c, val_c, person_cols = i, lc, vc, pcs
        det_c = next((j for j, c in enumerate(low) if c and j != label_c and ("remark" in c or ("detail" in c and j != label_c))), None)
        break
    if hdr is None:
        return None

    def _row_amount(row):
        if val_c is not None and val_c < len(row):
            a = _amt(row[val_c])
            if a is not None:
                return a
        # No Total column → sum the person value columns.
        s = sum((_amt(row[j]) or 0) for j in person_cols if j < len(row))
        return s or None

    me: dict[str, float] = {}
    emi = sip = 0.0
    stated_total = None
    seen: set[str] = set()
    for row in rows[hdr + 1:]:
        cat = row[label_c] if label_c < len(row) else None
        if not isinstance(cat, str) or not cat.strip():
            continue
        cl = cat.strip().lower()
        # Grand total ends the scan; section subtotals/dividers are skipped.
        if ("total" in cl and ("expens" in cl or "expend" in cl or "monthly" in cl)) or cl.startswith("grand total"):
            amt = _row_amount(row)
            if amt:
                stated_total = amt
            break
        if "subtotal" in cl or _is_total_label(cat):
            continue
        amt = _row_amount(row)
        if amt is None:                 # section divider ("Essential Spends") — no value
            continue
        if cl in seen:
            continue
        seen.add(cl)
        det = _txt(row[det_c]) if det_c is not None and det_c < len(row) else ""
        kind, field = _classify_expense(cat, det)
        if kind == "sip":
            sip += amt
        elif kind == "emi":
            emi += amt
        else:
            me[field] = me.get(field, 0.0) + amt

    if len(me) < 2 and emi == 0:
        return None
    return {
        "monthly_expenses": {k: round(v) for k, v in me.items()},
        "living": round(sum(me.values())),
        "emi": round(emi),
        "sip": round(sip),
        "stated_total": round(stated_total) if stated_total else None,
    }


# ── Recurring investments ─────────────────────────────────────────────────────

def parse_recurring(wb) -> Optional[list[dict]]:
    """Read the recurring-investments tab so no monthly contribution is dropped;
    tag purpose so retirement instruments (NPS/VPF/EPF/PPF/pension) feed the
    retirement SIP and MF/RD/equity feed goals. Also recovers EPF/PF from the
    income deductions section (a monthly retirement contribution)."""
    ws = _find_sheet(wb, ("recurring", "5_"))
    if ws is None:
        return None
    rows = _rows(ws)
    hdr, cols = _find_header(rows, {
        "type": ("investment", "type", "instrument", "particular"),
        "amount": ("monthly amount", "amount", "monthly", "sip"),
        "remarks": ("remark", "comment", "purpose", "note"),
    }, require=("type", "amount"))
    if hdr is None:
        return None
    type_c, amt_c, rem_c = cols["type"], cols["amount"], cols.get("remarks")
    retire_kw = ("nps", "vpf", "epf", "ppf", "provident", "pension", "sukanya", "superannuation")
    goal_kw = ("house", "education", "college", "car", "travel", "vacation", "marriage", "wedding", "child", "goal")
    out: list[dict] = []
    for row in rows[hdr + 1:]:
        name = row[type_c] if type_c < len(row) else None
        if not (isinstance(name, str) and name.strip()):
            continue
        nlow = name.strip().lower()
        if _is_total_label(name) or "insurance" in nlow:
            continue
        amt = _amt(row[amt_c]) if amt_c < len(row) else None
        if not amt or amt <= 0:
            continue
        rem = _txt(row[rem_c]) if rem_c is not None and rem_c < len(row) else ""
        rl = rem.lower()
        if "retire" in rl:
            purpose = "retirement"
        elif any(k in rl for k in goal_kw):
            purpose = "goal"
        elif any(k in nlow for k in retire_kw):
            purpose = "retirement"
        elif any(k in nlow for k in ("mutual", "mf", "sip", "equity", "rd", "stock")):
            purpose = "goal"
        else:
            purpose = "general"
        out.append({"investment_type": name.strip(), "monthly_amount": round(amt, 2),
                    "purpose": purpose, "remarks": rem or None})

    have_pf = any("provident" in (r["investment_type"] or "").lower()
                  or (r["investment_type"] or "").lower().strip() == "epf" for r in out)
    if not have_pf:
        iws = _find_sheet(wb, ("income", "2_"))
        if iws is not None:
            for row in _rows(iws):
                for c, cell in enumerate(row):
                    if isinstance(cell, str) and ("provident fund" in cell.lower()
                                                  or cell.strip().lower() in ("epf", "vpf")):
                        amt = max((a for a in (_amt(v) for v in row[c + 1:]) if a and a > 0), default=0)
                        if amt > 0:
                            out.append({"investment_type": "EPF / Provident Fund",
                                        "monthly_amount": round(amt, 2), "purpose": "retirement",
                                        "remarks": "Provident Fund contribution (salary deduction)"})
                        break
                else:
                    continue
                break
    return out or None


# ── Universal unmapped catch-all ──────────────────────────────────────────────
# Labels already represented by a structured field — skip when harvesting extras.
_MAPPED_LABEL_KW: tuple[str, ...] = (
    "name", "date of birth", "dob", "age", "marital", "spouse", "children", "kids",
    "dependent", "occupation", "profession", "city", "residence", "retirement age",
    "salary", "business income", "rental", "other income", "gross", "net", "tax",
    "provident", "deduction", "savings", "idle cash", "fd ", "bonus", "emergency",
    "loan", "emi", "insurance", "premium", "cover", "sum assured", "sum insured",
    "term plan", "health", "floater", "ulip",
)
# Every KNOWN sheet — section-parsed (handled by a dedicated parser, so their rows
# must not be re-reported) or compute/frozen/index (no client input). The catch-all
# scans only what's left: observations, notes, risk and any NEW/custom tab, so
# nothing labelled on an unrecognized page is ever dropped.
_CATCHALL_SKIP_SHEETS: tuple[str, ...] = (
    "personal", "1_", "income", "2_", "expense", "3_", "mutual", "4a", "equity", "4b",
    "stock", "fixed", "4c", "real estate", "real_estate", "4d", "gold", "4e", "bullion",
    "recurring", "5_", "monthly_inv", "investment", "liquid", "6_", "emergency", "7_",
    "loan", "8_", "liabil", "insurance", "9_", "goal", "10_", "index", "checks",
    "list of tab", "asset return", "asset_return", "assumption", "yoy", "cash flow",
    "retirement", "debt mgt", "tax planning", "networth", "inc exp", "case study",
)
_EXTRA_SKIP_LABELS: tuple[str, ...] = (
    "questions", "question", "answer", "details to be filled by client", "s.no", "sno",
    "expense category", "goal", "monthly amount", "type of expense", "category", "amount",
    "particular", "particulars", "field", "details", "sr no", "#", "remarks", "name",
)


def parse_extra_inputs(wb) -> list[dict]:
    """Universal catch-all: walk EVERY non-holding tab and harvest any labelled
    value that has no standard schema slot (Risk appetite, investment experience,
    notes, custom firm fields on new tabs, …) into {label, value, sheet}. Holding/
    income/expense/goal tabs are handled by their own parsers and skipped here so
    their rows aren't re-reported. Nothing labelled on an UNKNOWN tab is dropped."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for sn in wb.sheetnames:
        sl = sn.lower()
        if any(k in sl for k in _CATCHALL_SKIP_SHEETS):
            continue
        ws = wb[sn]
        for label, value in _kv_pairs(ws, max_rows=120):
            if value in (None, ""):
                continue
            nl = _norm(label).rstrip(":").strip()
            if not nl or nl in _EXTRA_SKIP_LABELS or _is_total_label(label):
                continue
            if any(k in nl for k in _MAPPED_LABEL_KW):
                continue
            sig = (nl, str(value).strip().lower())
            if sig in seen:
                continue
            seen.add(sig)
            out.append({"label": label.strip()[:160], "value": _txt(value)[:200], "sheet": sn})
            if len(out) >= 80:
                return out
    return out


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

    goals = parse_goals(wb)
    if goals:
        state["financial_goals"] = goals

    # Universal catch-all + the personal-table family extras, deduped — so no
    # labelled field on any tab (mapped or not, known sheet or new) is dropped.
    extras = list(pd_extras or []) + parse_extra_inputs(wb)
    if extras:
        seen: set[tuple] = set()
        deduped = []
        for e in extras:
            sig = (str(e.get("label", "")).strip().lower(), str(e.get("value", "")).strip().lower())
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(e)
        state["extra_inputs"] = deduped
    return state

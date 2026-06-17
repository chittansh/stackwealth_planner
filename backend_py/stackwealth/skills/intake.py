"""
Universal intake — Python port of skills/intake/.

Strategy mirrors TS:
  Tier 1 deterministic — known PDF templates (AA), known XLSX templates.
  Tier 2 multimodal LLM — Claude (native PDF/image) → GPT-4o fallback.

The TS version has 8 specialized parsers; this port handles PDF, XLSX, CSV,
DOCX, MD/TXT, image, audio. The two-tier extraction strategy is preserved but
the AA-PDF deterministic regex set + xlsx-template detection are intentionally
simplified (the TS regex catalog is large; this port falls through to the LLM
on those cases — which is the same behavior the TS version uses when the
deterministic anchor doesn't match). Field paths and confidence values match
the TS contract exactly.
"""
from __future__ import annotations

import base64
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .. import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_result(parser_used: str) -> dict[str, Any]:
    return {
        "partial_state": {},
        "evidence": [],
        "missing": [],
        "parser_used": parser_used,
    }


# ── Schema instructions for the LLM ────────────────────────────────────────


EXTRACTION_INSTRUCTIONS = """You are an Indian household financial-plan extractor. Read the document and emit a JSON object with this exact shape:

{
  "partial_state": {
    "personal_details": { "full_name"?, "date_of_birth"?, "city_of_residence"?, "city_type"? ("Metro" | "Non-metro"), "occupation"?, "retirement_age_target"?, "dependents"? (int OR descriptive string like "Mother (78)"), "marital_status"?, "spouse_name_and_age"?, "number_of_children"? },
    "income_details":   { "client_salary_in_hand"?, "spouse_salary_in_hand"?, "client_business_income"?, "spouse_business_income"?, "client_rental_income"?, "spouse_rental_income"?, "client_other_income"?, "spouse_other_income"?  (all monthly INR — populate every non-zero field; business owners often have 0 salary but non-zero business_income) },
    "monthly_expenses": { "household_expenses"?, "rent_or_emi"?, "groceries"?, "utilities"?, "school_fees"?, "medical"?, "insurance_premium"?, "travel_or_lifestyle"?, "other_emis"? (loan EMIs only — NOT a SIP) },
    "monthly_investments": { "mutual_fund_sip"?, "nps"?, "ppf"?, "rd"?, "direct_equity"?, "insurance_premium"?, "other"? },
    "liquid_capital":   { "savings_account_balance"?, "idle_cash_for_investment"?, "fd_breakable_for_investment"? },
    "loans_liabilities": { "home_loan"? { outstanding_amount, emi, interest_rate, tenure_left }, "car_loan"?, "personal_loan"?, "credit_card_dues"? },
    "insurance_details": { "term_plan"? { "company"?, "cover_amount"?, "annual_premium"? }, "health_insurance"? { "company"?, "cover_amount"?, "annual_premium"? }, "family_floater"? { "company"?, "cover_amount"?, "annual_premium"? }, "ulip_or_endowment"? { "company"?, "cover_amount"?, "annual_premium"? } },
    "financial_goals": [ { "goal_name", "kind" ("child_education" | "child_marriage" | "retirement" | "house_purchase" | "foreign_travel" | "other"), "target_year"?, "target_amount"? (in TODAY's rupees — see Goals rules below), "is_target_in_today_money"? (bool — true if target_amount is today's cost; false ONLY if the source explicitly gives an already-inflated future-value figure with no today's cost), "inflation_assumed"? (decimal, e.g. 0.08 for 8%), "current_allocated_amount"?, "periodic_contribution"?, "contribution_frequency"? ("monthly" | "annual"), "priority"? } ],
    "mutual_funds":   [ { "fund_name", "current_value", "isin"?, "folio"? } ],
    "equity_stocks":  [ { "stock_name", "current_value", "quantity"?, "isin"? } ],
    "fixed_income":   [ { "instrument" ("FD" | "RD" | "PPF" | "EPF" | "Bonds" | "NPS"), "invested_amount"?, "current_value"?, "maturity_date"? } ],
    "freedom_score_inputs": { "age"?, "monthly_income"?, "monthly_expenses"?, "monthly_emi"?, "portfolio_current_value"?, "liquid_assets_current_value"?, "equity_allocation_percent"? }
  },
  "evidence": [ { "field": "<canonical.path>", "value": <same as in partial_state>, "confidence": 0..1, "evidence_quote": "<verbatim span from source>" } ],
  "missing":  [ "<canonical.path>" ]
}

Rules:
- The document may be structured (template xlsx, bank statement, form) OR completely unstructured (a paragraph someone wrote, a screenshot, a voice transcript, a WhatsApp chat). Extract EVERY financial fact you can identify, regardless of formatting.
- All monetary values are monthly INR unless they're in goals / portfolios / loans (then absolute INR).
- Indian number conversion (CRITICAL — get this wrong and the entire plan is off by 10x):
    * 1 thousand / 1k = 1000
    * 1 lakh / 1 L / 1 lac = 100000 (one hundred thousand, i.e. ₹1,00,000)
    * 1 crore / 1 Cr = 10000000 (ten million, i.e. ₹1,00,00,000 — exactly 100 lakhs)
    * Worked examples — VERIFY each before emitting:
        - "2.5L" → 250000 (NOT 2500000)
        - "2.6L savings" → savings_account_balance: 260000 (NOT 2600000)
        - "1.8L in savings" → 180000 (NOT 1800000)
        - "12L" → 1200000 (NOT 12000000)
        - "28L in MFs" → 2800000
        - "50 lakh" → 5000000
        - "1.5 Cr" → 15000000 (NOT 150000000)
        - "2.5 Cr" → 25000000 (NOT 2500000)
        - "80k" → 80000
        - "12 LPA" annual → 100000 per month (divide by 12 if the schema field is monthly)
    * Sanity check before every emit: "L" / "lakh" → multiply by 100000 EXACTLY. NOT 1000000. A value like "2.6L" must produce 260000, NOT 2600000. If the original text mentions a "lakh" / "L" value and your output has more than 6 digits for amounts < 10L, you 10x'd it — re-multiply by 0.1.
    * Sanity check: 1 Cr is 100x of 1 L. If your output has 9 digits for a "crore" value, it's WRONG by 10x.
- DOB format: DD-MM-YYYY (re-format "15-Aug-1997" → "15-08-1997"). If only an age is mentioned ("im 32"), set `freedom_score_inputs.age` to that integer. Don't fabricate a DOB.
- Age: ALWAYS emit `freedom_score_inputs.age` when an age is mentioned in any form ("32 years old", "age 45", "im 28", "I'm in my 40s" → 40).
- City type: Mumbai/Delhi/Kolkata/Chennai/Bengaluru/Hyderabad/Pune/Ahmedabad = "Metro"; else "Non-metro".
- Income: write every non-zero subfield individually. Business owners often have 0 salary but non-zero business_income. For each income line decide whose it is (client vs spouse) and which kind (salary / business / rental / other). Spouse only mentioned by name with no income? Don't invent zero — omit.
- Expenses vs Investments — THE BUCKET MATTERS:
    - SIP / PPF / NPS / RD / direct-equity contributions → `monthly_investments.*` (these are wealth-building, not consumption)
    - Loan EMI of any kind → `monthly_expenses.other_emis` AND describe the loan under `loans_liabilities.*`
    - Rent, groceries, utilities, school, insurance premium, medical, travel/lifestyle → `monthly_expenses.*`
    - NEVER put a SIP under monthly_expenses — that double-counts savings as spending.
- Portfolio aggregation: if the user mentions a portfolio total ("my portfolio is around 12L", "I have 50L in equities"), set `freedom_score_inputs.portfolio_current_value` to that absolute INR value. If they list individual MFs/stocks, also populate the `mutual_funds[]` / `equity_stocks[]` arrays.
- Liquid: cash in savings / current accounts → `liquid_capital.savings_account_balance` AND `freedom_score_inputs.liquid_assets_current_value` (same total).
- Loan tenure_left: numeric YEARS only. "12 years" → 12, "3 years 6 months" → 3.5. If credit card is paid in full each month, set `tenure_left` to 0 (not a string).
- Goals: extract intent like "want to buy a 1.5cr home by 2030" → `{goal_name: "Home Purchase", kind: "house_purchase", target_year: 2030, target_amount: 15000000, is_target_in_today_money: true}`. Goal `kind` MUST be one of: child_education | child_marriage | retirement | house_purchase | foreign_travel | other.
- Goals — TODAY'S COST vs FUTURE VALUE (CRITICAL — get this wrong and every projection is inflated 2-10x):
    * `target_amount` MUST be the cost in TODAY's rupees, NOT the inflation-adjusted future value. Then set `is_target_in_today_money: true`.
    * When a structured source (e.g. an xlsx with columns) has BOTH "Today's Cost" AND "Future Value Needed" / "FV" / "Future Value", READ the today's cost — IGNORE the future value column entirely. The FV is a DERIVED computation, not an input.
    * When the source has "Inflation Assumed" or similar (e.g. "8%"), populate `inflation_assumed` as a decimal (8% → 0.08, 6% → 0.06).
    * In free-form text ("buy a 1.5cr home in 2030") the user almost always means today's money — set `is_target_in_today_money: true`.
    * The only case for `is_target_in_today_money: false` is when the source EXPLICITLY says "₹X needed in 2030 (already inflation-adjusted)" / "future value of ₹X" without giving a separate today's-cost figure. This is rare.
- Goal priority: use `essential | important | aspirational` only. Map "High" → "essential", "Medium" → "important", "Low" → "aspirational".
- Don't invent values. If a field isn't clearly present, OMIT it from partial_state and add its dotted path to "missing".
- Every field in partial_state SHOULD have a matching evidence row with a verbatim quote when possible. For derived/inferred values (e.g. FSI aggregates summed from breakdown), confidence may be lower but still emit the value.
- Output JSON only. No prose, no code fences."""


# ── Text path ──────────────────────────────────────────────────────────────


async def parse_text(args: dict[str, Any]) -> dict[str, Any]:
    text = args["text"]
    source_type = args.get("source_type", "user")
    filename = args.get("filename")
    return await _llm_extract(text=text, source_type=source_type, filename=filename, parser_label=f"text:{source_type}")


# ── LLM extraction ─────────────────────────────────────────────────────────


def _stamp_evidence(rows: list[dict], source_type: str, source_file: Optional[str], parser_tier: str) -> list[dict]:
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "field": r.get("field"),
                "value": r.get("value"),
                "source_file": source_file,
                "source_type": source_type,
                "parser_tier": parser_tier,
                "confidence": float(r.get("confidence") or 0.6),
                "evidence_quote": r.get("evidence_quote"),
                "page_or_sheet": r.get("page_or_sheet"),
                "timestamp": _now(),
            }
        )
    return out


def _claude_client() -> Optional[Any]:
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic

        return Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception:
        return None


def _openai_client() -> Optional[Any]:
    if not config.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        return OpenAI(api_key=config.OPENAI_API_KEY)
    except Exception:
        return None


def _try_parse_json(s: str) -> Optional[dict]:
    s = s.strip()
    # Strip code fences if model added them.
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def _llm_extract(
    *,
    text: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = None,
    source_type: str,
    filename: Optional[str],
    parser_label: str,
) -> dict[str, Any]:
    """Try Claude first, GPT-4o as fallback, both with JSON mode."""
    out: Optional[dict] = None

    claude = _claude_client()
    if claude is not None:
        try:
            blocks: list[dict] = [{"type": "text", "text": EXTRACTION_INSTRUCTIONS}]
            if text:
                blocks.append({"type": "text", "text": f"\n\n# Document\n\n{text[:80_000]}"})
            if pdf_bytes:
                blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode(),
                        },
                    }
                )
            if image_bytes:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_mime or "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode(),
                        },
                    }
                )
            resp = claude.messages.create(
                model=config.INTAKE_MODEL or "claude-haiku-4-5-20251001",
                max_tokens=4096,
                temperature=0,
                messages=[{"role": "user", "content": blocks}],
            )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
            out = _try_parse_json(raw)
        except Exception as e:
            print(f"[intake] claude failed: {e}")

    if out is None:
        oa = _openai_client()
        if oa is not None:
            try:
                content: list[dict] = [{"type": "text", "text": EXTRACTION_INSTRUCTIONS}]
                if text:
                    content.append({"type": "text", "text": f"\n\n# Document\n\n{text[:80_000]}"})
                if image_bytes:
                    b64 = base64.b64encode(image_bytes).decode()
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime or 'image/jpeg'};base64,{b64}"},
                        }
                    )
                resp = oa.chat.completions.create(
                    model="gpt-4o",
                    response_format={"type": "json_object"},
                    temperature=0,
                    messages=[{"role": "user", "content": content}],
                )
                raw = resp.choices[0].message.content or ""
                out = _try_parse_json(raw)
            except Exception as e:
                print(f"[intake] openai failed: {e}")

    if out is None:
        return _empty_result(f"{parser_label}:no-llm")

    partial = out.get("partial_state") or {}
    evidence = _stamp_evidence(out.get("evidence") or [], source_type, filename, "llm")
    missing = out.get("missing") or []
    return {
        "partial_state": partial,
        "evidence": evidence,
        "missing": missing,
        "parser_used": parser_label,
    }


# ── PDF / XLSX / CSV / DOCX / image / audio dispatch ───────────────────────


async def _parse_pdf(buf: bytes, filename: str) -> dict[str, Any]:
    """Try Claude with native PDF doc-block; if no LLM available, fall back to
    extracted text."""
    out = await _llm_extract(
        pdf_bytes=buf, source_type="pdf_generic", filename=filename, parser_label="pdfGeneric:claude"
    )
    if out["evidence"]:
        return out
    # Fallback: extract text and try again.
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(buf))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        return {
            **_empty_result("pdfGeneric:failed"),
            "missing": [str(e)],
        }
    return await _llm_extract(
        text=text, source_type="pdf_generic", filename=filename, parser_label="pdfGeneric:textFallback"
    )


async def _parse_xlsx(buf: bytes, filename: str) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(buf), data_only=True)
        chunks: list[str] = []
        for sn in wb.sheetnames:
            ws = wb[sn]
            chunks.append(f"## Sheet: {sn}")
            for row in ws.iter_rows(values_only=True):
                chunks.append(",".join("" if c is None else str(c) for c in row))
        text = "\n".join(chunks)
    except Exception as e:
        return {**_empty_result("xlsx:failed"), "missing": [str(e)]}
    return await _llm_extract(
        text=text, source_type="xlsx", filename=filename, parser_label="xlsx:llm"
    )


async def _parse_csv(buf: bytes, filename: str) -> dict[str, Any]:
    text = buf.decode("utf-8", errors="ignore")
    return await _llm_extract(
        text=text, source_type="csv", filename=filename, parser_label="csv:llm"
    )


async def _parse_docx(buf: bytes, filename: str) -> dict[str, Any]:
    try:
        from docx import Document

        doc = Document(io.BytesIO(buf))
        text = "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as e:
        return {**_empty_result("docx:failed"), "missing": [str(e)]}
    return await _llm_extract(
        text=text, source_type="docx", filename=filename, parser_label="docx:llm"
    )


async def _parse_image(buf: bytes, filename: str, mime: str) -> dict[str, Any]:
    return await _llm_extract(
        image_bytes=buf,
        image_mime=mime,
        source_type="image",
        filename=filename,
        parser_label="image:claude",
    )


async def _parse_audio(buf: bytes, filename: str, mime: str) -> dict[str, Any]:
    """Whisper transcribe → parse_text."""
    oa = _openai_client()
    if oa is None:
        return {**_empty_result("audio:no-openai"), "missing": ["OPENAI_API_KEY required for audio"]}
    try:
        f = io.BytesIO(buf)
        f.name = filename
        r = oa.audio.transcriptions.create(model="whisper-1", file=f)
        text = r.text
    except Exception as e:
        return {**_empty_result("audio:failed"), "missing": [str(e)]}
    return await _llm_extract(
        text=text, source_type="audio", filename=filename, parser_label="audio:transcript"
    )


# ── Public dispatcher ──────────────────────────────────────────────────────


async def ingest(input: dict[str, Any]) -> dict[str, Any]:
    src = input["source"]
    if src["kind"] == "text":
        return await parse_text(
            {"text": src["text"], "source_type": src.get("source_type", "user")}
        )

    buf = base64.b64decode(src["contents_b64"])
    mime = (src.get("mime") or "application/octet-stream").lower()
    filename = src["filename"]
    lower = filename.lower()

    if mime == "application/pdf" or lower.endswith(".pdf"):
        return await _parse_pdf(buf, filename)
    if "spreadsheetml" in mime or re.search(r"\.xlsx?$", lower):
        return await _parse_xlsx(buf, filename)
    if mime == "text/csv" or lower.endswith(".csv"):
        return await _parse_csv(buf, filename)
    if "wordprocessingml" in mime or lower.endswith(".docx"):
        return await _parse_docx(buf, filename)
    if mime.startswith("text/") or re.search(r"\.(md|markdown|txt)$", lower):
        return await parse_text(
            {"text": buf.decode("utf-8", errors="ignore"), "source_type": "md", "filename": filename}
        )
    if mime.startswith("image/"):
        return await _parse_image(buf, filename, mime)
    if mime.startswith("audio/") or mime.startswith("video/"):
        return await _parse_audio(buf, filename, mime)
    return await parse_text(
        {"text": buf.decode("utf-8", errors="ignore")[:100_000], "source_type": "md", "filename": filename}
    )

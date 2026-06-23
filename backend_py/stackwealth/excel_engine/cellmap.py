"""Cell-map for the CFP Excel engine.

The firm's CFP workbook is the source of truth for the deterministic financial
plan. A client upload is the SAME template with only the input tabs filled in.
The transformer (``engine.py``) pours the client's inputs into a pristine master
copy, recalculates with LibreOffice, and reads the results back — so the numbers
the app shows are computed by the firm's own formulas, cell-for-cell.

Two facts drive the classification below (verified against the sample files):
  • Client uploads only ever carry literal values on the INPUT tabs and the
    RM-manual cells of YoY / Retirement. Every compute tab is pure formulas.
  • The Assumptions & Asset-Returns tabs hold the firm's standing assumptions;
    client files leave them blank, so they must come from the master, never the
    upload.

Invariant enforced by the engine: a cell that is a FORMULA in the master is
never overwritten. Inputs only ever land in the master's non-formula cells.
"""

from __future__ import annotations

# Tabs whose non-formula cells are CLIENT inputs. The engine mirrors these from
# the upload into the master (writing blanks too, so a sparse upload clears the
# master's sample data — no leakage).
INJECT_TABS: list[str] = [
    "1_Personal_Details",
    "2_Income",
    "3_Expenses ",          # trailing space is intentional — matches the tab name
    "4A_Mutual_Funds",
    "4B_Equity_Stocks",
    "4C_Fixed_Income",
    "5_Recurring_Investments",
    "4D_Real_Estate",
    "4E_Gold & Others",
    "6_Liquid_Capital",
    "7_Emergency_Fund",
    "8_Loans_Liabilities",
    "9_Insurance_Details",
    "10_Financial_Goals",
    "Risk Questannaire",     # firm's spelling
    # Compute tabs that also carry RM-manual judgment cells (lumpsum events,
    # life-expectancy overrides, step-up rate). Their ONLY literals are those
    # manual inputs — every other cell is a formula and is preserved.
    "YoY Cash Flow",
    "Retirement Plan",
]

# Tabs the engine must NEVER inject into — the master's values win. Listed for
# documentation / validation; anything not in INJECT_TABS is left untouched.
FROZEN_TABS: list[str] = [
    "Assumptions & Computation",
    "Asset Returns",
]

# Pure-computed tabs (all formulas, recalculated by LibreOffice). Not injected.
COMPUTE_TABS: list[str] = [
    "Insurance Computation",
    "Tax Planning",
    "Debt Mgt",
    "11. Inc Exp,Networth,Rec Invest",
    "10_Financial_Goals",   # formula columns; inputs handled via INJECT
]

# Tabs to ignore entirely (meta / leftover broken case study).
IGNORE_TABS: list[str] = [
    "Checks",
    "List of TABs",
    "Retirement Plan-Case Study-NA",
]

# ---------------------------------------------------------------------------
# OUTPUT cells — the headline results the Python layer (Monte Carlo, scenarios,
# freedom score) and the UI consume. Coordinates verified against the 18/06
# master. Each entry: key -> (sheet, cell).  Extend freely; unknown/blank cells
# come back as None rather than erroring.
# ---------------------------------------------------------------------------
SCALAR_OUTPUTS: dict[str, tuple[str, str]] = {
    # --- Retirement Plan (values in column E) ---
    "current_age": ("Retirement Plan", "E7"),
    "retire_age": ("Retirement Plan", "E8"),
    "years_to_retire": ("Retirement Plan", "E10"),
    "self_life_expectancy": ("Retirement Plan", "E12"),
    "spouse_life_expectancy": ("Retirement Plan", "E13"),
    "annual_expense_today": ("Retirement Plan", "E17"),
    "annual_expense_at_retire": ("Retirement Plan", "E20"),
    "retirement_corpus_recurring": ("Retirement Plan", "E25"),
    "retirement_corpus_required": ("Retirement Plan", "E30"),
    "retirement_monthly_sip": ("Retirement Plan", "E43"),
    "retirement_stepup_start_annual": ("Retirement Plan", "E54"),
    # --- Insurance Computation ---
    "human_life_value": ("Insurance Computation", "F14"),
    "life_cover_required": ("Insurance Computation", "F34"),
    "life_cover_existing": ("Insurance Computation", "F36"),
    "life_cover_additional": ("Insurance Computation", "F38"),
    "health_cover_required": ("Insurance Computation", "G63"),
    "health_cover_existing": ("Insurance Computation", "G64"),
    "health_cover_additional": ("Insurance Computation", "G65"),
    # --- Income / Net-worth summary (tab 11; values in cols F & I) ---
    "total_income_net_monthly": ("11. Inc Exp,Networth,Rec Invest", "F5"),
    "monthly_surplus": ("11. Inc Exp,Networth,Rec Invest", "I22"),
    "total_financial_assets": ("11. Inc Exp,Networth,Rec Invest", "I42"),
    "total_non_financial_assets": ("11. Inc Exp,Networth,Rec Invest", "I47"),
    "total_assets": ("11. Inc Exp,Networth,Rec Invest", "I49"),
    "total_loans": ("11. Inc Exp,Networth,Rec Invest", "I51"),
    "net_worth": ("11. Inc Exp,Networth,Rec Invest", "I53"),
}

# Output TABLES — variable-length result regions. Each entry describes a sheet,
# the header row, the first data row, and the column letters to pull. The
# extractor walks rows until the anchor column goes blank.
TABLE_OUTPUTS: dict[str, dict] = {
    "goals": {
        "sheet": "10_Financial_Goals",
        "first_row": 3,
        "anchor_col": "A",            # goal name; stop when blank
        "columns": {
            "goal": "A",
            "importance": "B",
            "target_year": "C",
            "years_to_go": "D",
            "todays_cost": "E",
            "nature": "F",
            "inflation": "G",
            "future_value_needed": "H",
            "current_allocated": "X",
            "gap_today": "Y",
            "future_value_of_gap": "Z",
            "required_sip": "AB",
            "sip_shortfall": "AD",
        },
    },
    "yoy_cashflow": {
        "sheet": "YoY Cash Flow",
        "first_row": 6,
        "anchor_col": "C",            # year column; stop when blank
        "columns": {
            "year": "C",
            "age": "D",
            "income_employment": "E",
            "income_business": "F",
            "income_rental": "G",
            "income_other": "H",
            "expenses": "J",
            "loan_repayment": "K",
            "lumpsum": "T",
            "financial_assets_close": "S",
            "non_financial_close": "Z",
        },
    },
}

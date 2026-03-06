"""
Education Loan Tracker — calculation engine.

Handles: daily interest accrual, moratorium simulation, interest
capitalization, EMI (reducing balance), amortization schedule,
prepayment analysis, total cost summary.

All monetary inputs / outputs in the loan's native currency.
"""

import math
import calendar
from datetime import date


# ── Date helpers ───────────────────────────────────────────────────────────────

def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _months_between(d1: date, d2: date) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def _days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


# ── Core interest calculations ─────────────────────────────────────────────────

def monthly_interest(principal: float, annual_rate: float) -> float:
    """Simple monthly interest = P × r / 12."""
    return round(principal * annual_rate / 100 / 12, 2)


def daily_interest_for_month(principal: float, annual_rate: float,
                              month_date: date, days_in_year: int = 365) -> float:
    """
    Daily accrual interest for a calendar month.
    interest = P × (annual_rate / 100 / days_in_year) × days_in_month
    """
    days = _days_in_month(month_date)
    return round(principal * annual_rate / 100 / days_in_year * days, 2)


def calculate_emi(principal: float, annual_rate: float, months: int) -> float:
    """Standard reducing balance EMI."""
    if months <= 0 or principal <= 0:
        return 0.0
    if annual_rate == 0:
        return round(principal / months, 2)
    r = annual_rate / 100 / 12
    return round(principal * r * (1 + r) ** months / ((1 + r) ** months - 1), 2)


def months_to_payoff(principal: float, annual_rate: float, emi: float) -> int:
    """Algebraically solve for n given principal, rate, EMI."""
    if emi <= 0 or principal <= 0:
        return 0
    r = annual_rate / 100 / 12
    if r == 0:
        return math.ceil(principal / emi)
    inside = 1 - (principal * r / emi)
    if inside <= 0:
        return 0
    return math.ceil(-math.log(inside) / math.log(1 + r))


# ── Moratorium simulation ──────────────────────────────────────────────────────

def simulate_moratorium(
    principal: float,
    loan_fee_capitalized: float,
    annual_rate: float,
    start_date: date,
    moratorium_end_date: date,
    token_payment: float,
    payments: list[dict],          # [{date: "YYYY-MM-DD", amount: float}]
    days_in_year: int = 365,
) -> tuple[list[dict], float, float]:
    """
    Simulate moratorium phase month by month.

    Payment application order (per standard loan agreements):
      1. Accrued interest (unpaid from prior months)
      2. Current month interest
      3. Principal (only if payment exceeds all interest)

    Returns
    -------
    rows                  : list of monthly rows
    final_principal       : principal balance at moratorium end (before cap)
    total_accrued_interest: cumulative unpaid interest at moratorium end
    """
    balance = principal + loan_fee_capitalized
    accrued_interest = 0.0
    rows = []

    # Build payment lookup: "YYYY-MM" -> total paid that month
    payment_by_month: dict[str, float] = {}
    for p in payments:
        ym = str(p["date"])[:7]
        payment_by_month[ym] = payment_by_month.get(ym, 0.0) + float(p["amount"])

    cur_date = start_date
    month_num = 0

    while cur_date < moratorium_end_date:
        month_num += 1
        ym = cur_date.strftime("%Y-%m")

        month_int = daily_interest_for_month(balance, annual_rate, cur_date, days_in_year)
        payment = payment_by_month.get(ym, token_payment)

        # Total interest owed = prior accrued + this month
        total_owed_interest = round(accrued_interest + month_int, 2)

        applied_interest  = round(min(payment, total_owed_interest), 2)
        applied_principal = round(max(0.0, payment - total_owed_interest), 2)
        shortfall         = round(total_owed_interest - applied_interest, 2)

        accrued_interest = shortfall
        balance = round(balance - applied_principal, 2)

        rows.append({
            "month":             month_num,
            "date":              ym,
            "date_label":        cur_date.strftime("%b %Y"),
            "opening_balance":   round(balance + applied_principal, 2),
            "monthly_interest":  month_int,
            "payment":           round(payment, 2),
            "applied_interest":  applied_interest,
            "applied_principal": applied_principal,
            "shortfall":         shortfall,
            "accrued_interest":  accrued_interest,
            "closing_balance":   balance,
        })

        cur_date = _add_months(cur_date, 1)

    return rows, round(balance, 2), round(accrued_interest, 2)


# ── Capitalization ─────────────────────────────────────────────────────────────

def capitalize_interest(principal: float, accrued_interest: float) -> float:
    """
    Add all accrued unpaid interest to principal.
    This is the single most expensive event — creates 'interest on interest'.
    """
    return round(principal + accrued_interest, 2)


# ── Amortization schedule ──────────────────────────────────────────────────────

def generate_amortization(
    capitalized_balance: float,
    annual_rate: float,
    emi_start_date: date,
    maturity_date: date,
    override_emi: float | None = None,
) -> tuple[list[dict], float]:
    """
    Generate full EMI amortization schedule (reducing balance method).

    If override_emi is provided, uses that instead of calculated EMI.
    The final payment is adjusted to clear any rounding difference.

    Returns (rows, emi)
    """
    n = _months_between(emi_start_date, maturity_date)
    if n <= 0 or capitalized_balance <= 0:
        return [], 0.0

    emi = override_emi or calculate_emi(capitalized_balance, annual_rate, n)
    r   = annual_rate / 100 / 12
    balance = capitalized_balance
    today   = date.today()

    rows = []
    cum_interest  = 0.0
    cum_principal = 0.0

    for i in range(1, n + 1):
        row_date = _add_months(emi_start_date, i)
        interest_part  = round(balance * r, 2)
        principal_part = round(emi - interest_part, 2)

        # Final payment: clear exactly what remains
        if i == n or balance - principal_part < 0:
            principal_part = balance
            actual_payment = round(balance + interest_part, 2)
        else:
            actual_payment = emi

        balance = max(0.0, round(balance - principal_part, 2))
        cum_interest  += interest_part
        cum_principal += principal_part

        rows.append({
            "month":                i,
            "date":                 row_date,
            "date_label":           row_date.strftime("%b %Y"),
            "opening_balance":      round(balance + principal_part, 2),
            "emi":                  actual_payment,
            "interest_portion":     interest_part,
            "principal_portion":    principal_part,
            "closing_balance":      round(balance, 2),
            "cumulative_interest":  round(cum_interest, 2),
            "cumulative_principal": round(cum_principal, 2),
            "is_past":    row_date < today,
            "is_current": row_date.year == today.year and row_date.month == today.month,
        })

        if balance <= 0:
            break

    return rows, emi


# ── Prepayment analysis ────────────────────────────────────────────────────────

def _run_amort(principal: float, r: float, months: int, emi: float) -> list[dict]:
    """Internal: simple amortization for prepayment comparison."""
    rows = []
    balance = principal
    for i in range(1, months + 1):
        interest  = round(balance * r, 2)
        principal_part = round(emi - interest, 2)
        balance   = max(0.0, round(balance - principal_part, 2))
        rows.append({"interest": interest, "principal": principal_part,
                     "payment": emi, "balance": balance})
        if balance <= 0:
            break
    return rows


def prepayment_analysis(
    current_principal: float,
    annual_rate: float,
    remaining_months: int,
    current_emi: float,
    extra_monthly: float  = 0.0,
    lump_sum: float       = 0.0,
    lump_sum_at_month: int = 1,
    strategy: str         = "reduce_tenure",  # "reduce_tenure" | "reduce_emi"
) -> dict:
    """
    Compare loan trajectory with and without extra prepayments.

    Strategy:
      reduce_tenure — EMI stays same, loan ends sooner
      reduce_emi    — tenure stays same, monthly burden decreases

    Returns dict: {baseline, scenario, savings}
    """
    r = annual_rate / 100 / 12

    # ── Baseline ──
    baseline = _run_amort(current_principal, r, remaining_months, current_emi)
    bl_interest = round(sum(x["interest"] for x in baseline), 2)
    bl_paid     = round(sum(x["payment"]  for x in baseline), 2)

    # ── Scenario ──
    balance      = current_principal
    sc_interest  = 0.0
    sc_paid      = 0.0
    active_emi   = current_emi
    sc_rows      = []
    month        = 0
    cap          = remaining_months * 3   # safety

    while balance > 0.01 and month < cap:
        month += 1

        # Apply lump sum
        if month == lump_sum_at_month and lump_sum > 0:
            applied = min(lump_sum, balance)
            balance = round(balance - applied, 2)
            sc_paid += applied
            if balance <= 0:
                break
            if strategy == "reduce_emi":
                rem = remaining_months - month + 1
                if rem > 0:
                    active_emi = calculate_emi(balance, annual_rate, rem)

        interest       = round(balance * r, 2)
        total_pmt      = active_emi + extra_monthly
        principal_part = min(max(0.0, total_pmt - interest), balance)
        actual_pmt     = round(interest + principal_part, 2)

        balance      = max(0.0, round(balance - principal_part, 2))
        sc_interest += interest
        sc_paid     += actual_pmt
        sc_rows.append({"interest": interest, "principal": principal_part,
                        "payment": actual_pmt, "balance": balance})

    return {
        "baseline": {
            "months":        len(baseline),
            "total_interest": bl_interest,
            "total_paid":    bl_paid,
            "monthly_emi":   current_emi,
        },
        "scenario": {
            "months":        len(sc_rows),
            "total_interest": round(sc_interest, 2),
            "total_paid":    round(sc_paid, 2),
            "monthly_emi":   round(active_emi + extra_monthly, 2),
        },
        "savings": {
            "months_saved":    max(0, len(baseline) - len(sc_rows)),
            "interest_saved":  round(bl_interest - sc_interest, 2),
            "total_saved":     round(bl_paid - sc_paid, 2),
        },
    }


# ── Cost summary ───────────────────────────────────────────────────────────────

def cost_summary(
    disbursed_amount: float,
    loan_fee_upfront: float,
    moratorium_rows: list[dict],
    amort_rows: list[dict],
) -> dict:
    """Aggregate lifetime cost of the loan."""
    mora_paid   = round(sum(r["payment"]         for r in moratorium_rows), 2)
    mora_int    = round(sum(r["applied_interest"] for r in moratorium_rows), 2)
    mora_princ  = round(sum(r["applied_principal"]for r in moratorium_rows), 2)
    emi_int_all = round(sum(r["interest_portion"] for r in amort_rows), 2)
    emi_total   = round(sum(r["emi"]              for r in amort_rows), 2)
    total_paid  = round(mora_paid + loan_fee_upfront + emi_total, 2)
    total_int   = round(total_paid - disbursed_amount, 2)

    return {
        "disbursed":          disbursed_amount,
        "fee_upfront":        loan_fee_upfront,
        "moratorium_paid":    mora_paid,
        "moratorium_interest":mora_int,
        "moratorium_principal":mora_princ,
        "emi_total":          emi_total,
        "emi_interest":       emi_int_all,
        "total_paid":         total_paid,
        "total_interest":     total_int,
        "cost_multiplier":    round(total_paid / disbursed_amount, 3) if disbursed_amount else 0,
        "interest_pct":       round(total_int / total_paid * 100, 1) if total_paid else 0,
        "daily_interest_cost": round(disbursed_amount * 11.60 / 100 / 365, 2),
    }

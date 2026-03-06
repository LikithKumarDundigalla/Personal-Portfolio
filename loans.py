"""
Loan calculators — Standard, Leap Finance, Prodigy Finance, SoFi.

────────────────────────────────────────────────────────────────────
STANDARD
  Plain EMI from day 1. No moratorium.

LEAP FINANCE  (fixed rate, interest-only Pre-EMI during moratorium)
  • Phase 1 — Moratorium (course_months + 6):
      Monthly Pre-EMI = outstanding_balance × monthly_rate
      Outstanding stays flat because full interest is paid every month.
  • Phase 2 — Repayment (tenure_months):
      Standard EMI on outstanding (= original principal if Pre-EMIs paid).

PRODIGY FINANCE  (variable/fixed rate, admin fee capitalised, partial in-school payment)
  • Admin fee (4–5 %) is ADDED to the disbursed principal up front.
      effective_principal = principal × (1 + admin_fee_pct / 100)
  • Phase 1 — Moratorium (course_months + 6):
      interest_accrued = outstanding × monthly_rate
      in_school_payment covers interest first; excess reduces principal.
      If in_school_payment < interest → unpaid interest CAPITALISES
        (added to outstanding → compound effect).
  • Phase 2 — Repayment (tenure_months):
      EMI recalculated on whatever outstanding remains after moratorium.

SOFI  (US-based, 6-month grace, four in-school repayment options)
  • No origination fee.
  • Phase 1 — In-school + grace (course_months + 6):
      'deferred'       → entire interest capitalises, no payment.
      'flat_25'        → $25/month; rest capitalises.
      'interest_only'  → pay full monthly interest; principal stays flat.
      'full'           → full EMI from day 1 (= standard loan).
  • Phase 2 — Repayment (tenure_months):
      EMI on outstanding balance after grace.
────────────────────────────────────────────────────────────────────
"""

import math
from datetime import date
import calendar


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_month_date(d: date) -> date:
    if d.month == 12:
        nxt = d.replace(year=d.year + 1, month=1)
    else:
        nxt = d.replace(month=d.month + 1)
    last = calendar.monthrange(nxt.year, nxt.month)[1]
    return nxt.replace(day=min(d.day, last))


def calculate_emi(principal: float, annual_rate: float, tenure_months: int,
                  flat_rate: bool = False) -> float:
    """
    Calculate monthly EMI.

    flat_rate=False (default) — Reducing balance:
        EMI = P × r × (1+r)^n / ((1+r)^n − 1)
        Interest charged only on outstanding balance each month.
        Used by most banks for home/auto/personal loans.

    flat_rate=True — Flat rate:
        Total interest = P × annual_rate% × years
        EMI = (P + total_interest) / tenure_months
        Interest always on original principal — common for some car/personal loans.
    """
    if annual_rate == 0 or tenure_months == 0:
        return round(principal / tenure_months, 2) if tenure_months else 0.0
    if flat_rate:
        years = tenure_months / 12
        total_interest = principal * (annual_rate / 100) * years
        return round((principal + total_interest) / tenure_months, 2)
    r = annual_rate / 12 / 100
    emi = principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1)
    return round(emi, 2)


def amortization_schedule(principal: float, annual_rate: float,
                           tenure_months: int, start_date: date) -> list[dict]:
    """Standard amortization — used for Phase 2 repayment of all loan types."""
    emi = calculate_emi(principal, annual_rate, tenure_months)
    r = annual_rate / 12 / 100
    balance = principal
    schedule = []
    current_date = start_date

    for month in range(1, tenure_months + 1):
        interest_part = round(balance * r, 2)
        principal_part = round(emi - interest_part, 2)
        balance = max(0.0, round(balance - principal_part, 2))
        due_date = _next_month_date(current_date)
        schedule.append({
            "month": month,
            "due_date": str(due_date),
            "phase": "Repayment",
            "payment": emi,
            "principal_component": principal_part,
            "interest_component": interest_part,
            "capitalized": 0.0,
            "balance": balance,
        })
        current_date = due_date

    return schedule


# ── Leap Finance ───────────────────────────────────────────────────────────────

def leap_finance_schedule(principal: float, annual_rate: float,
                           course_months: int, repayment_months: int,
                           start_date: date) -> tuple[list[dict], float, float]:
    """
    Returns (full_schedule, pre_emi_amount, repayment_emi).

    Phase 1: Moratorium = course_months + 6 months grace.
      Pre-EMI each month = interest only (outstanding × monthly_rate).
      Outstanding stays flat (interest fully serviced).

    Phase 2: Standard EMI on original principal for repayment_months.
    """
    moratorium = course_months + 6
    r = annual_rate / 12 / 100
    pre_emi = round(principal * r, 2)       # fixed monthly interest-only payment
    outstanding = principal
    schedule = []
    current_date = start_date

    # Phase 1 — Moratorium
    for m in range(1, moratorium + 1):
        interest = round(outstanding * r, 2)
        due_date = _next_month_date(current_date)
        schedule.append({
            "month": m,
            "due_date": str(due_date),
            "phase": "Pre-EMI (Moratorium)",
            "payment": pre_emi,
            "principal_component": 0.0,
            "interest_component": interest,
            "capitalized": 0.0,
            "balance": outstanding,          # flat — interest fully paid
        })
        current_date = due_date

    # Phase 2 — Repayment
    repayment_emi = calculate_emi(outstanding, annual_rate, repayment_months)
    balance = outstanding
    for m in range(1, repayment_months + 1):
        interest = round(balance * r, 2)
        principal_part = round(repayment_emi - interest, 2)
        balance = max(0.0, round(balance - principal_part, 2))
        due_date = _next_month_date(current_date)
        schedule.append({
            "month": moratorium + m,
            "due_date": str(due_date),
            "phase": "Repayment",
            "payment": repayment_emi,
            "principal_component": principal_part,
            "interest_component": interest,
            "capitalized": 0.0,
            "balance": balance,
        })
        current_date = due_date

    return schedule, pre_emi, repayment_emi


def leap_finance_summary(loan: dict) -> dict:
    moratorium = loan["moratorium_months"] or (loan["course_months"] + 6)
    pre_emi = round(loan["principal"] * (loan["interest_rate"] / 12 / 100), 2)
    repayment_emi = loan["emi"]
    total_pre_emi = round(pre_emi * moratorium, 2)
    total_repayment = round(repayment_emi * loan["tenure_months"], 2)
    total_interest = round(total_pre_emi + total_repayment - loan["principal"], 2)

    return {
        "moratorium_months": moratorium,
        "pre_emi": pre_emi,
        "repayment_emi": repayment_emi,
        "total_pre_emi_paid": total_pre_emi,
        "total_payable": round(total_pre_emi + total_repayment, 2),
        "total_interest": total_interest,
        "remaining_balance": loan["remaining_balance"],
        "outstanding_at_repay": loan["outstanding_at_repay"],
    }


# ── Prodigy Finance ────────────────────────────────────────────────────────────

def prodigy_finance_schedule(principal: float, annual_rate: float,
                              admin_fee_pct: float, course_months: int,
                              in_school_payment_amt: float,
                              repayment_months: int,
                              start_date: date) -> tuple[list[dict], float, float, float]:
    """
    Returns (full_schedule, effective_principal, outstanding_after_moratorium, repayment_emi).

    Admin fee is added to principal up front.
    Phase 1: moratorium = course_months + 6.
      Monthly interest accrues on outstanding.
      in_school_payment covers interest first, then principal.
      Shortfall capitalises (outstanding grows).
    Phase 2: EMI recalculated on outstanding after moratorium.
    """
    moratorium = course_months + 6
    effective_p = round(principal * (1 + admin_fee_pct / 100), 2)
    r = annual_rate / 12 / 100
    outstanding = effective_p
    schedule = []
    current_date = start_date

    # Phase 1 — Moratorium
    for m in range(1, moratorium + 1):
        interest = round(outstanding * r, 2)
        payment = in_school_payment_amt
        capitalized = 0.0

        if payment >= interest:
            # excess reduces principal
            outstanding = max(0.0, round(outstanding - (payment - interest), 2))
        else:
            # shortfall capitalises
            capitalized = round(interest - payment, 2)
            outstanding = round(outstanding + capitalized, 2)

        due_date = _next_month_date(current_date)
        schedule.append({
            "month": m,
            "due_date": str(due_date),
            "phase": "In-School (Moratorium)",
            "payment": payment,
            "principal_component": 0.0,
            "interest_component": interest,
            "capitalized": capitalized,
            "balance": outstanding,
        })
        current_date = due_date

    # Phase 2 — Repayment
    repayment_emi = calculate_emi(outstanding, annual_rate, repayment_months)
    balance = outstanding
    for m in range(1, repayment_months + 1):
        interest = round(balance * r, 2)
        principal_part = round(repayment_emi - interest, 2)
        balance = max(0.0, round(balance - principal_part, 2))
        due_date = _next_month_date(current_date)
        schedule.append({
            "month": moratorium + m,
            "due_date": str(due_date),
            "phase": "Repayment",
            "payment": repayment_emi,
            "principal_component": principal_part,
            "interest_component": interest,
            "capitalized": 0.0,
            "balance": balance,
        })
        current_date = due_date

    return schedule, effective_p, outstanding, repayment_emi


def prodigy_finance_summary(loan: dict) -> dict:
    moratorium = loan["moratorium_months"] or (loan["course_months"] + 6)
    eff_p = loan["effective_principal"] or loan["principal"]
    admin_fee = eff_p - loan["principal"]
    outstanding = loan["outstanding_at_repay"] or eff_p
    repayment_emi = loan["emi"]
    in_school_total = round(loan["in_school_payment_amt"] * moratorium, 2)
    total_repayment = round(repayment_emi * loan["tenure_months"], 2)
    total_payable = round(in_school_total + total_repayment, 2)
    total_interest = round(total_payable - loan["principal"], 2)

    return {
        "moratorium_months": moratorium,
        "effective_principal": eff_p,
        "admin_fee": round(admin_fee, 2),
        "in_school_payment": loan["in_school_payment_amt"],
        "in_school_total": in_school_total,
        "outstanding_at_repay": outstanding,
        "repayment_emi": repayment_emi,
        "total_payable": total_payable,
        "total_interest": total_interest,
        "remaining_balance": loan["remaining_balance"],
    }


# ── SoFi ──────────────────────────────────────────────────────────────────────

SOFI_PAYMENT_LABELS = {
    "deferred":      "Deferred (interest capitalises fully)",
    "flat_25":       "$25 / month flat",
    "interest_only": "Interest-only",
    "full":          "Full EMI from day 1",
}


def sofi_schedule(principal: float, annual_rate: float,
                  course_months: int, in_school_payment_type: str,
                  repayment_months: int,
                  start_date: date) -> tuple[list[dict], float, float]:
    """
    Returns (full_schedule, outstanding_after_grace, repayment_emi).

    Grace period = course_months + 6.
    in_school_payment_type: 'deferred' | 'flat_25' | 'interest_only' | 'full'
    """
    grace = course_months + 6
    r = annual_rate / 12 / 100
    outstanding = principal
    schedule = []
    current_date = start_date

    if in_school_payment_type == "full":
        # Treat exactly like a standard loan — no separate grace phase
        full_tenure = grace + repayment_months
        full_emi = calculate_emi(principal, annual_rate, full_tenure)
        balance = principal
        for m in range(1, full_tenure + 1):
            interest = round(balance * r, 2)
            principal_part = round(full_emi - interest, 2)
            balance = max(0.0, round(balance - principal_part, 2))
            due_date = _next_month_date(current_date)
            schedule.append({
                "month": m,
                "due_date": str(due_date),
                "phase": "Full EMI",
                "payment": full_emi,
                "principal_component": principal_part,
                "interest_component": interest,
                "capitalized": 0.0,
                "balance": balance,
            })
            current_date = due_date
        return schedule, balance, full_emi

    # Phase 1 — Grace period
    for m in range(1, grace + 1):
        interest = round(outstanding * r, 2)
        capitalized = 0.0

        if in_school_payment_type == "deferred":
            payment = 0.0
            capitalized = interest
            outstanding = round(outstanding + capitalized, 2)

        elif in_school_payment_type == "flat_25":
            payment = 25.0
            shortfall = max(0.0, interest - payment)
            capitalized = round(shortfall, 2)
            outstanding = round(outstanding + capitalized, 2)

        elif in_school_payment_type == "interest_only":
            payment = interest         # full interest covered, principal stays flat
            capitalized = 0.0

        else:
            payment = 0.0

        due_date = _next_month_date(current_date)
        schedule.append({
            "month": m,
            "due_date": str(due_date),
            "phase": f"Grace ({SOFI_PAYMENT_LABELS.get(in_school_payment_type, '')})",
            "payment": payment,
            "principal_component": 0.0,
            "interest_component": interest,
            "capitalized": capitalized,
            "balance": outstanding,
        })
        current_date = due_date

    # Phase 2 — Repayment
    repayment_emi = calculate_emi(outstanding, annual_rate, repayment_months)
    balance = outstanding
    for m in range(1, repayment_months + 1):
        interest = round(balance * r, 2)
        principal_part = round(repayment_emi - interest, 2)
        balance = max(0.0, round(balance - principal_part, 2))
        due_date = _next_month_date(current_date)
        schedule.append({
            "month": grace + m,
            "due_date": str(due_date),
            "phase": "Repayment",
            "payment": repayment_emi,
            "principal_component": principal_part,
            "interest_component": interest,
            "capitalized": 0.0,
            "balance": balance,
        })
        current_date = due_date

    return schedule, outstanding, repayment_emi


def sofi_summary(loan: dict) -> dict:
    grace = loan["moratorium_months"] or (loan["course_months"] + 6)
    outstanding = loan["outstanding_at_repay"] or loan["principal"]
    repayment_emi = loan["emi"]
    payment_type = loan["in_school_payment_type"]

    if payment_type == "deferred":
        in_school_total = 0.0
    elif payment_type == "flat_25":
        in_school_total = 25.0 * grace
    elif payment_type == "interest_only":
        r = loan["interest_rate"] / 12 / 100
        in_school_total = round(loan["principal"] * r * grace, 2)
    else:
        in_school_total = 0.0

    total_repayment = round(repayment_emi * loan["tenure_months"], 2)
    total_payable = round(in_school_total + total_repayment, 2)
    total_interest = round(total_payable - loan["principal"], 2)
    capitalized_interest = round(outstanding - loan["principal"], 2)

    return {
        "grace_months": grace,
        "in_school_type": SOFI_PAYMENT_LABELS.get(payment_type, payment_type),
        "in_school_total": in_school_total,
        "outstanding_at_repay": outstanding,
        "capitalized_interest": max(0.0, capitalized_interest),
        "repayment_emi": repayment_emi,
        "total_payable": total_payable,
        "total_interest": total_interest,
        "remaining_balance": loan["remaining_balance"],
    }


# ── Standard loan (kept for backward compat) ──────────────────────────────────

def loan_summary(loan: dict) -> dict:
    """Summary for a plain standard loan."""
    principal = loan["principal"]
    remaining  = loan["remaining_balance"]
    emi        = loan["emi"]
    tenure     = loan["tenure_months"]
    total_payable  = round(emi * tenure, 2)
    total_interest = round(total_payable - principal, 2)
    amount_paid    = round(principal - remaining, 2)
    if not emi:
        months_remaining = 0
    elif loan.get("interest_rate", 0) > 0:
        # Solve amortization formula: n = -log(1 - balance*r/emi) / log(1+r)
        r = loan["interest_rate"] / 12 / 100
        inside = 1 - (remaining * r / emi)
        if inside <= 0:
            months_remaining = loan["tenure_months"]   # fallback
        else:
            months_remaining = math.ceil(-math.log(inside) / math.log(1 + r))
    else:
        # Zero-rate (simple_emi): balance reduces by exactly EMI each month
        months_remaining = math.ceil(remaining / emi)
    return {
        "emi": emi,
        "total_payable": total_payable,
        "total_interest": total_interest,
        "amount_paid": amount_paid,
        "remaining_balance": round(remaining, 2),
        "months_remaining": months_remaining,
    }
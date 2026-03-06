"""
projections.py — Pure-Python financial simulation engine.
No Streamlit, no yfinance. Fully testable standalone.
"""

import calendar
from datetime import date


# ── Private helpers ─────────────────────────────────────────────────────────────

def _add_months(d: date, months: int) -> date:
    """Add `months` to a date, clamping day to end-of-month if needed."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _months_between(d1: date, d2: date) -> int:
    """Complete months elapsed from d1 to d2 (d2 >= d1)."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def _calc_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Standard fixed-EMI formula."""
    if principal <= 0 or tenure_months <= 0:
        return 0.0
    if annual_rate == 0:
        return round(principal / tenure_months, 2)
    r = annual_rate / 12 / 100
    emi = principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1)
    return round(emi, 2)


# ── Main simulation ─────────────────────────────────────────────────────────────

def project_finances(
    current_assets_usd: float,
    loans: list[dict],
    monthly_salary_usd: float,
    monthly_expenses_usd: float,
    monthly_investment_usd: float,
    annual_asset_growth_rate: float,
    annual_salary_growth_rate: float,
    years: int,
) -> tuple[list[dict], dict, dict]:
    """
    Simulate finances month by month for `years` years starting from today.

    All monetary inputs must be in USD.  Loans should have their
    remaining_balance, emi, and in_school_payment_amt already converted to
    USD before calling this function.

    Parameters
    ----------
    current_assets_usd        : current portfolio value in USD
    loans                     : list of loan dicts (db.get_all_loans() schema)
                                with USD-converted remaining_balance, emi,
                                in_school_payment_amt fields.
    monthly_salary_usd        : gross monthly salary in USD
    monthly_expenses_usd      : fixed monthly living expenses in USD
    monthly_investment_usd    : additional monthly investment added to assets
    annual_asset_growth_rate  : expected asset growth % p.a.  (e.g. 10.0)
    annual_salary_growth_rate : expected salary growth % p.a.  (e.g. 5.0)
    years                     : projection horizon in years

    Returns
    -------
    (rows, milestones, loan_balance_history)

    rows : list[dict] — one per month:
        month, year_label, date_label,
        salary_usd, expenses_usd, emi_total_usd, investment_usd, savings_usd,
        total_assets_usd, total_loan_usd, net_worth_usd, passive_income_usd

    milestones : dict:
        debt_free_month, debt_free_date,
        positive_networth_month, positive_networth_date,
        fi_month, fi_date

    loan_balance_history : dict {loan_name: [balance_month_1, ..., balance_month_N]}
    """
    today = date.today()
    monthly_growth = (1 + annual_asset_growth_rate / 100) ** (1 / 12) - 1

    # Per-loan balance tracking (USD)
    loan_balances: dict[int, float] = {}
    for loan in loans:
        lid = int(loan["id"])
        bal = float(loan.get("remaining_balance") or 0)
        loan_balances[lid] = max(0.0, bal)

    loan_balance_history: dict[str, list[float]] = {loan["name"]: [] for loan in loans}

    assets = float(current_assets_usd)
    rows: list[dict] = []

    # Milestones
    debt_free_month = None
    debt_free_date = None
    positive_networth_month = None
    positive_networth_date = None
    fi_month = None
    fi_date = None

    total_months = years * 12

    for t in range(1, total_months + 1):
        sim_date = _add_months(today, t)
        year_num = (t - 1) // 12 + 1
        year_label = f"Year {year_num}"
        date_label = sim_date.strftime("%b %Y")

        # Salary grows at the start of each new year
        completed_years = (t - 1) // 12
        salary_this_month = monthly_salary_usd * (
            (1 + annual_salary_growth_rate / 100) ** completed_years
        )

        # Asset appreciation (before this month's investment)
        assets *= 1 + monthly_growth

        # ── Process each loan ──────────────────────────────────────────────────
        emi_total = 0.0
        total_loan = 0.0

        for loan in loans:
            lid = int(loan["id"])
            bal = loan_balances[lid]

            if bal <= 0:
                loan_balance_history[loan["name"]].append(0.0)
                continue

            loan_start = date.fromisoformat(str(loan["start_date"]))
            months_elapsed = _months_between(loan_start, sim_date)
            moratorium = int(loan.get("moratorium_months") or 0)
            r = float(loan.get("interest_rate") or 0) / 12 / 100
            loan_type = str(loan.get("loan_type") or "standard")
            pay_type = str(loan.get("in_school_payment_type") or "standard")

            if moratorium > 0 and months_elapsed < moratorium:
                # ── Moratorium / in-school phase ──────────────────────────────
                interest = bal * r
                in_school_pmt = float(loan.get("in_school_payment_amt") or 0)

                if loan_type == "leap_finance" or pay_type == "interest_only":
                    # Interest-only: principal stays flat
                    emi_total += interest

                elif pay_type == "deferred":
                    # Nothing paid; entire interest capitalises
                    loan_balances[lid] = round(bal + interest, 2)
                    emi_total += 0.0

                elif pay_type == "flat_25":
                    payment = min(25.0, bal + interest)
                    shortfall = max(0.0, interest - payment)
                    loan_balances[lid] = round(bal + shortfall, 2)
                    emi_total += payment

                else:
                    # Prodigy-style / partial payment
                    payment = in_school_pmt
                    if payment >= interest:
                        excess = payment - interest
                        loan_balances[lid] = max(0.0, round(bal - excess, 2))
                    else:
                        loan_balances[lid] = round(bal + (interest - payment), 2)
                    emi_total += payment

            else:
                # ── Repayment phase ───────────────────────────────────────────
                stored_emi = float(loan.get("emi") or 0)
                if stored_emi <= 0:
                    stored_emi = _calc_emi(
                        bal,
                        float(loan.get("interest_rate") or 0),
                        max(1, int(loan.get("tenure_months") or 12)),
                    )

                interest = bal * r
                principal_part = max(0.0, stored_emi - interest)
                actual_payment = min(stored_emi, bal + interest)  # don't overpay
                loan_balances[lid] = max(0.0, round(bal - principal_part, 2))
                emi_total += actual_payment

            total_loan = round(total_loan + loan_balances[lid], 2)
            loan_balance_history[loan["name"]].append(round(loan_balances[lid], 2))

        # ── Add monthly investment to assets ───────────────────────────────────
        assets += monthly_investment_usd

        # ── Cash flow ─────────────────────────────────────────────────────────
        savings = salary_this_month - monthly_expenses_usd - emi_total - monthly_investment_usd
        net_worth = assets - total_loan
        passive_income = assets * 0.04 / 12   # 4% rule → monthly

        # ── Milestone detection ────────────────────────────────────────────────
        if debt_free_month is None and total_loan <= 0.01:
            debt_free_month = t
            debt_free_date = date_label

        if positive_networth_month is None and net_worth > 0:
            positive_networth_month = t
            positive_networth_date = date_label

        if (
            fi_month is None
            and monthly_expenses_usd > 0
            and passive_income >= monthly_expenses_usd
        ):
            fi_month = t
            fi_date = date_label

        rows.append({
            "month": t,
            "year_label": year_label,
            "date_label": date_label,
            "salary_usd": round(salary_this_month, 2),
            "expenses_usd": round(monthly_expenses_usd, 2),
            "emi_total_usd": round(emi_total, 2),
            "investment_usd": round(monthly_investment_usd, 2),
            "savings_usd": round(savings, 2),
            "total_assets_usd": round(assets, 2),
            "total_loan_usd": round(total_loan, 2),
            "net_worth_usd": round(net_worth, 2),
            "passive_income_usd": round(passive_income, 2),
        })

    milestones = {
        "debt_free_month": debt_free_month,
        "debt_free_date": debt_free_date,
        "positive_networth_month": positive_networth_month,
        "positive_networth_date": positive_networth_date,
        "fi_month": fi_month,
        "fi_date": fi_date,
    }

    return rows, milestones, loan_balance_history


# ── Health scorecard ─────────────────────────────────────────────────────────────

def health_scorecard(
    monthly_salary_usd: float,
    monthly_expenses_usd: float,
    total_emi_usd: float,
    total_assets_usd: float,
    total_loans_usd: float,
) -> dict:
    """
    Compute current financial health metrics (all inputs in USD).

    Returns
    -------
    dict with keys:
        savings_rate        : (salary − expenses − emi) / salary × 100  [%]
        emi_to_income_pct   : emi / salary × 100  [%]
        debt_to_income      : total_loans / (salary × 12)  [ratio]
        emergency_months    : total_assets / monthly_expenses  [months]
        fi_progress_pct     : assets / (25 × annual_expenses) × 100  [%]
        fi_target_usd       : 25 × annual_expenses  [USD]
    """
    result: dict = {}

    if monthly_salary_usd > 0:
        surplus = monthly_salary_usd - monthly_expenses_usd - total_emi_usd
        result["savings_rate"] = round(surplus / monthly_salary_usd * 100, 1)
        result["emi_to_income_pct"] = round(total_emi_usd / monthly_salary_usd * 100, 1)
        annual_salary = monthly_salary_usd * 12
        result["debt_to_income"] = (
            round(total_loans_usd / annual_salary, 2) if annual_salary > 0 else None
        )
    else:
        result["savings_rate"] = None
        result["emi_to_income_pct"] = None
        result["debt_to_income"] = None

    if monthly_expenses_usd > 0:
        result["emergency_months"] = round(total_assets_usd / monthly_expenses_usd, 1)
        fi_target = 25 * monthly_expenses_usd * 12
        result["fi_progress_pct"] = round(
            min(100.0, total_assets_usd / fi_target * 100), 1
        )
        result["fi_target_usd"] = round(fi_target, 2)
    else:
        result["emergency_months"] = None
        result["fi_progress_usd"] = None
        result["fi_target_usd"] = None

    return result


# ── Input validation ──────────────────────────────────────────────────────────────

def validate_inputs(
    monthly_salary_usd: float,
    monthly_expenses_usd: float,
    monthly_investment_usd: float,
    annual_asset_growth_rate: float,
    annual_salary_growth_rate: float,
    years: int,
) -> list[dict]:
    """
    Validate projection inputs and return a list of issues.

    Each issue dict has:
        level   : 'error' | 'warning' | 'info'
        message : human-readable explanation and suggested fix
    """
    issues: list[dict] = []

    if monthly_salary_usd <= 0:
        issues.append({
            "level": "error",
            "message": "Monthly salary must be greater than 0. Enter your gross monthly income.",
        })

    if monthly_expenses_usd < 0:
        issues.append({
            "level": "error",
            "message": "Monthly expenses cannot be negative.",
        })

    if monthly_investment_usd < 0:
        issues.append({
            "level": "error",
            "message": "Monthly investment cannot be negative.",
        })

    if monthly_salary_usd > 0 and monthly_expenses_usd >= monthly_salary_usd:
        issues.append({
            "level": "warning",
            "message": (
                f"Expenses (${monthly_expenses_usd:,.0f}) ≥ Salary (${monthly_salary_usd:,.0f}). "
                "You have no room for loan payments or investment — the plan will show a negative savings rate. "
                "Consider reducing expenses or increasing income."
            ),
        })

    if monthly_salary_usd > 0 and monthly_investment_usd > monthly_salary_usd:
        issues.append({
            "level": "error",
            "message": (
                f"Monthly investment (${monthly_investment_usd:,.0f}) exceeds salary "
                f"(${monthly_salary_usd:,.0f}). Reduce investment to a realistic amount."
            ),
        })

    if monthly_salary_usd > 0:
        total_committed = monthly_expenses_usd + monthly_investment_usd
        if total_committed > monthly_salary_usd:
            issues.append({
                "level": "warning",
                "message": (
                    f"Expenses + Investment (${total_committed:,.0f}) already exceeds salary "
                    f"(${monthly_salary_usd:,.0f}) — nothing left for EMIs. "
                    "Reduce expenses or investment, or increase salary."
                ),
            })

    if annual_asset_growth_rate > 20:
        issues.append({
            "level": "warning",
            "message": (
                f"Asset growth rate of {annual_asset_growth_rate:.0f}% p.a. is very optimistic. "
                "Long-term equity markets average 8–12%. Consider using a conservative estimate."
            ),
        })

    if annual_salary_growth_rate > 15:
        issues.append({
            "level": "warning",
            "message": (
                f"Salary growth of {annual_salary_growth_rate:.0f}% p.a. is very aggressive. "
                "Typical raises are 3–8% p.a. — this estimate may over-inflate future savings."
            ),
        })

    if years < 1:
        issues.append({
            "level": "error",
            "message": "Projection horizon must be at least 1 year.",
        })

    return issues

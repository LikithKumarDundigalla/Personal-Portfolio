"""
Personal Finance Tracker — Streamlit App
Run with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date

import db
import assets as asset_mod
import loans as loan_mod
import notifier
import scheduler
import projections
import education_loan as edu_mod

# ── Bootstrap ──────────────────────────────────────────────────────────────────
db.init_db()
scheduler.start_scheduler()

st.set_page_config(
    page_title="Finance Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("💰 Personal Finance Tracker")

tabs = st.tabs(["📊 Dashboard", "📈 Assets", "🏦 Loans", "🎓 Education Loan", "📋 Financial Plan", "⚙️ Settings"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header("Dashboard")

    portfolio, total_invested_usd, total_current_usd, fx_rates = asset_mod.get_portfolio_summary()
    loans = db.get_all_loans()

    # ── Currency selector ──
    display_cur = st.selectbox(
        "Display currency",
        asset_mod.SUPPORTED_CURRENCIES,
        index=0,
        key="dashboard_currency",
    )
    to_display = lambda usd_val: asset_mod.convert_from_usd(usd_val, display_cur)
    usd_to_rate = asset_mod.get_usd_to_currency_rate(display_cur)

    # Convert totals to display currency
    total_current_disp  = to_display(total_current_usd)
    total_invested_disp = to_display(total_invested_usd)
    total_gain_disp     = total_current_disp - total_invested_disp

    total_loan_usd = 0.0
    for loan in loans:
        total_loan_usd += loan["remaining_balance"] * asset_mod.get_fx_rate_to_usd(loan["currency"])

    # Include education loan (stored in settings, not loans table)
    _dash_edu_cfg = db.get_edu_loan_config()
    if _dash_edu_cfg:
        _dash_edu_r = asset_mod.get_fx_rate_to_usd(_dash_edu_cfg.get("currency", "USD"))
        _dash_edu_bal = (
            float(_dash_edu_cfg.get("current_principal") or _dash_edu_cfg.get("disbursed_amount", 0))
            + float(_dash_edu_cfg.get("current_accrued", 0))
        )
        total_loan_usd += _dash_edu_bal * _dash_edu_r

    total_loan_disp = to_display(total_loan_usd)
    net_worth_disp  = total_current_disp - total_loan_disp

    # ── Live FX rates caption ──
    all_fx = dict(fx_rates)
    all_fx[display_cur] = 1 / usd_to_rate if usd_to_rate else 1.0
    rate_parts = [f"1 {cur} = {display_cur} {rate * usd_to_rate:,.4f}"
                  for cur, rate in all_fx.items() if cur != display_cur]
    if rate_parts:
        st.caption("Live FX rates: " + "  |  ".join(rate_parts))

    # ── Top metrics ──
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"Portfolio Value ({display_cur})", f"{total_current_disp:,.2f}",
                f"{total_gain_disp:+,.2f}")
    col2.metric(f"Invested ({display_cur})",        f"{total_invested_disp:,.2f}")
    col3.metric(f"Total Loans ({display_cur})",     f"{total_loan_disp:,.2f}")
    col4.metric(f"Net Worth ({display_cur})",       f"{net_worth_disp:,.2f}")

    st.divider()

    # ── Portfolio breakdown pie (in display currency) ──
    if portfolio:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader(f"Portfolio Breakdown ({display_cur})")
            pie_data = []
            for r in portfolio:
                val_usd = r["current_value_usd"] or r["invested_value_usd"]
                pie_data.append({
                    "symbol": r["symbol"],
                    "value": to_display(val_usd) if val_usd else 0,
                })
            fig = px.pie(pie_data, names="symbol", values="value", hole=0.4)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, width='stretch')

        with col_b:
            st.subheader(f"Gain / Loss by Asset ({display_cur})")
            gl_data = [r for r in portfolio if r["gain_loss_usd"] is not None]
            if gl_data:
                df_gl = pd.DataFrame([{
                    "symbol": r["symbol"],
                    "gain_loss": to_display(r["gain_loss_usd"]),
                } for r in gl_data])
                df_gl["color"] = df_gl["gain_loss"].apply(lambda x: "gain" if x >= 0 else "loss")
                fig2 = px.bar(df_gl, x="symbol", y="gain_loss", color="color",
                              color_discrete_map={"gain": "#2ecc71", "loss": "#e74c3c"})
                fig2.update_layout(showlegend=False, yaxis_title=f"Gain / Loss ({display_cur})")
                st.plotly_chart(fig2, width='stretch')

    # ── Annual dividend income (quick summary) ──
    if portfolio:
        with st.expander("💵 Annual Dividend Income"):
            with st.spinner("Fetching dividends..."):
                div_rows, total_div_usd = asset_mod.get_annual_dividend_income()
            total_div_disp = to_display(total_div_usd)
            if div_rows:
                st.metric(f"Total Dividends ({display_cur})", f"{total_div_disp:,.2f}",
                          help="Last 12 months across all holdings")
                for d in div_rows:
                    st.write(f"**{d['symbol']}** — {d['currency']} {d['dividend_native']:,.2f} "
                             f"({d['quantity']} shares) = **USD {d['dividend_usd']:,.2f}**")
            else:
                st.info("No dividends found for your holdings in the last 12 months.")

    # ── Loan overview ──
    if loans or _dash_edu_cfg:
        st.subheader("Loan Balances")
        loan_rows = []
        for l in loans:
            bal_usd   = l["remaining_balance"] * asset_mod.get_fx_rate_to_usd(l["currency"])
            emi_usd   = float(l.get("emi") or 0) * asset_mod.get_fx_rate_to_usd(l["currency"])
            loan_rows.append({
                "Name": l["name"],
                f"EMI ({display_cur})": f"{to_display(emi_usd):,.2f}",
                f"Remaining ({display_cur})": f"{to_display(bal_usd):,.2f}",
                "Native": f"{l['currency']} {l['remaining_balance']:,.2f}",
                "Rate": f"{l['interest_rate']}%",
                "Tenure": f"{l['tenure_months']} mo",
            })
        if _dash_edu_cfg:
            _d_edu_r  = asset_mod.get_fx_rate_to_usd(_dash_edu_cfg.get("currency", "USD"))
            _d_in_mora = date.today() < date.fromisoformat(_dash_edu_cfg["moratorium_end"])
            _d_mora_end = date.fromisoformat(_dash_edu_cfg["moratorium_end"])
            _d_maturity = date.fromisoformat(_dash_edu_cfg["maturity_date"])
            _d_repay_mo = max(1, edu_mod._months_between(_d_mora_end, _d_maturity))
            _d_cap = edu_mod.capitalize_interest(
                float(_dash_edu_cfg.get("current_principal") or _dash_edu_cfg.get("disbursed_amount", 0)),
                float(_dash_edu_cfg.get("current_accrued", 0)),
            )
            _d_emi = float(_dash_edu_cfg.get("token_payment", 0)) if _d_in_mora else edu_mod.calculate_emi(
                _d_cap, float(_dash_edu_cfg["annual_rate"]), _d_repay_mo
            )
            loan_rows.append({
                "Name": f"🎓 {_dash_edu_cfg.get('lender', 'Education Loan')} (Education)",
                f"EMI ({display_cur})": f"{to_display(_d_emi * _d_edu_r):,.2f}",
                f"Remaining ({display_cur})": f"{to_display(_dash_edu_bal * _d_edu_r):,.2f}",
                "Native": f"{_dash_edu_cfg.get('currency', 'USD')} {_dash_edu_bal:,.2f}",
                "Rate": f"{_dash_edu_cfg.get('annual_rate', 0)}%",
                "Tenure": f"{_d_repay_mo} mo (repay)",
            })
        st.dataframe(pd.DataFrame(loan_rows), width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ASSETS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.header("Assets")

    # ── Add asset — three tabs: Stock/ETF, Commodity, Indian MF ──
    with st.expander("➕ Add New Asset", expanded=False):
        asset_add_tabs = st.tabs([
            "📈 Stock / ETF / Mutual Fund",
            "🥇 Commodity (Gold, Silver…)",
            "🇮🇳 Indian Mutual Fund",
        ])

        with asset_add_tabs[0]:
            st.caption(
                "**Stocks:** `AAPL` (US) · `RELIANCE.NS` (NSE) · `TCS.BO` (BSE)  \n"
                "**ETFs:** `QQQ`, `NIFTYBEES.NS`, `GOLDBEES.NS`  \n"
                "**US Mutual Funds:** `VTSAX`, `FXAIX` (NAV updated daily)  \n"
                "**Indian direct MFs:** use the **🇮🇳 Indian Mutual Fund** tab instead — NAV is entered manually.  \n"
                "**Crypto:** `BTC-USD`, `ETH-USD`"
            )
            with st.form("add_stock_form"):
                col1, col2 = st.columns(2)
                with col1:
                    symbol    = st.text_input("Symbol", placeholder="AAPL / RELIANCE.NS / VTSAX / BTC-USD")
                    exchange  = st.selectbox("Exchange / Type",
                                             ["NSE", "BSE", "NASDAQ", "NYSE", "MUTUAL_FUND", "CRYPTO", "OTHER"])
                with col2:
                    quantity      = st.number_input("Quantity / Units", min_value=0.0001, value=1.0, step=0.01)
                    avg_buy_price = st.number_input("Avg Buy Price (native currency)",
                                                    min_value=0.0, value=0.0, step=0.01)

                if st.form_submit_button("Add Asset", type="primary"):
                    if symbol:
                        with st.spinner(f"Fetching info for {symbol.upper()}..."):
                            info = asset_mod.fetch_symbol_info(symbol.strip())
                        asset_type = "crypto" if "USD" in symbol.upper() and "-" in symbol else "stock"
                        db.add_asset(symbol=symbol.strip(), name=info["name"], exchange=exchange,
                                     quantity=quantity, avg_buy_price=avg_buy_price,
                                     currency=info["currency"], asset_type=asset_type, unit="share")
                        st.success(f"Added {symbol.upper()} — {info['name']} ({info['currency']})")
                        st.rerun()

        with asset_add_tabs[1]:
            st.caption(
                "Live prices from COMEX futures via Yahoo Finance (GC=F, SI=F, etc.).  \n"
                "For Gold ETFs (GOLDBEES.NS, GOLD1.NS, GLD) use the **Stock / ETF** tab instead."
            )

            # ── Step 1: choose commodity (outside form so it drives the UI) ──
            _comm_name = st.selectbox(
                "Commodity", list(asset_mod.COMMODITIES.keys()), key="comm_name_sel"
            )
            _comm_sym, _comm_unit, _ = asset_mod.COMMODITIES[_comm_name]
            _is_metal = _comm_name in asset_mod.PHYSICAL_METAL_DENOMINATIONS

            # ── Step 2: physical or digital? (only for metals) ────────────────
            if _is_metal:
                _hold_type = st.radio(
                    "How do you hold this?",
                    ["🏅 Physical (bars / coins)", "💻 Digital (ETF, SGB, Digital Gold)"],
                    horizontal=True,
                    key="comm_hold_type",
                )
            else:
                _hold_type = "Digital"   # Oil / Gas — no bars

            _is_physical = "Physical" in str(_hold_type)

            # ── Step 3: weight unit + denomination (outside form — drives UI) ──
            _TROY_OZ = 31.1035   # grams per troy oz

            # oz-centric denomination list (weights stored as grams internally)
            _OZ_DENOMS: dict[str, list[tuple[str, float | None]]] = {
                "Gold": [
                    ("1/20 oz (1.56g)",   _TROY_OZ / 20),
                    ("1/10 oz (3.11g)",   _TROY_OZ / 10),
                    ("1/4 oz (7.78g)",    _TROY_OZ / 4),
                    ("1/2 oz (15.55g)",   _TROY_OZ / 2),
                    ("1 oz (31.10g)",     _TROY_OZ),
                    ("2 oz (62.21g)",     _TROY_OZ * 2),
                    ("5 oz (155.52g)",    _TROY_OZ * 5),
                    ("10 oz (311.04g)",   _TROY_OZ * 10),
                    ("Custom oz",         None),
                ],
                "Silver": [
                    ("1 oz (31.10g)",     _TROY_OZ),
                    ("5 oz (155.52g)",    _TROY_OZ * 5),
                    ("10 oz (311.04g)",   _TROY_OZ * 10),
                    ("100 oz (3.11 kg)",  _TROY_OZ * 100),
                    ("Custom oz",         None),
                ],
                "Platinum": [
                    ("1/2 oz (15.55g)",   _TROY_OZ / 2),
                    ("1 oz (31.10g)",     _TROY_OZ),
                    ("Custom oz",         None),
                ],
                "Palladium": [
                    ("1 oz (31.10g)",     _TROY_OZ),
                    ("Custom oz",         None),
                ],
            }

            _denom_grams: float | None = None
            if _is_physical:
                # Weight unit selector
                _wunit = st.radio(
                    "Preferred weight unit",
                    ["g  (grams)", "oz  (troy oz)"],
                    horizontal=True,
                    key="comm_wunit",
                )
                _use_oz = "oz" in _wunit

                # Pick the right denomination list
                _denoms = (
                    _OZ_DENOMS.get(_comm_name, [])
                    if _use_oz
                    else asset_mod.PHYSICAL_METAL_DENOMINATIONS.get(_comm_name, [])
                )
                _denom_labels = [d[0] for d in _denoms]
                _denom_sel = st.selectbox(
                    "Bar / coin denomination", _denom_labels, key="comm_denom_sel"
                )
                _denom_grams = dict(_denoms)[_denom_sel]  # None → custom

                if _denom_grams is None:
                    # Custom weight input — in whichever unit the user chose
                    if _use_oz:
                        _custom_oz = st.number_input(
                            "Custom weight per piece (troy oz)",
                            min_value=0.001, value=1.0, step=0.1,
                            key="comm_custom_oz",
                        )
                        _denom_grams = _custom_oz * _TROY_OZ
                    else:
                        _denom_grams = st.number_input(
                            "Custom weight per piece (grams)",
                            min_value=0.001, value=10.0, step=0.5,
                            key="comm_custom_g",
                        )
            else:
                _use_oz = False
                _denom_sel = ""

            # ── Step 4: the actual form ───────────────────────────────────────
            with st.form("add_commodity_form"):
                if _is_physical:
                    # ── Physical bars / coins ─────────────────────────────────
                    _pc1, _pc2 = st.columns(2)
                    with _pc1:
                        _num_pieces = st.number_input(
                            "Number of bars / coins",
                            min_value=1, value=1, step=1,
                        )
                    with _pc2:
                        _price_per_piece = st.number_input(
                            "Purchase price per bar / coin",
                            min_value=0.0, value=0.0, step=100.0,
                            help="The total amount you paid for one bar or coin.",
                        )
                        _comm_currency_p = st.selectbox(
                            "Currency", ["INR", "USD", "EUR", "AED", "CAD", "GBP"],
                            key="comm_cur_phys",
                        )

                    # Live preview (show in both g and oz)
                    if _denom_grams and _denom_grams > 0:
                        _total_g = _num_pieces * _denom_grams
                        _total_oz = _total_g / _TROY_OZ
                        _ppg = _price_per_piece / _denom_grams if _price_per_piece > 0 else 0
                        _ppoz = _price_per_piece / (_denom_grams / _TROY_OZ) if _price_per_piece > 0 else 0
                        st.info(
                            f"**{int(_num_pieces)} piece(s)** × "
                            f"**{_denom_grams:.4g}g ({_denom_grams/_TROY_OZ:.4g} oz)**"
                            f" = **{_total_g:.4g}g ({_total_oz:.4g} oz) total**  \n"
                            f"Cost per gram: **{_comm_currency_p} {_ppg:,.4f}**  |  "
                            f"Cost per oz: **{_comm_currency_p} {_ppoz:,.2f}**"
                        )

                    if st.form_submit_button("➕ Add Physical Metal", type="primary"):
                        if _denom_grams and _denom_grams > 0:
                            _total_g_final = int(_num_pieces) * _denom_grams
                            _ppg_final = _price_per_piece / _denom_grams
                            _piece_label = _denom_sel.split("(")[0].strip().rstrip("—").strip()
                            db.add_asset(
                                symbol=_comm_sym,
                                name=f"{_comm_name} — {_piece_label} ×{int(_num_pieces)}",
                                exchange="COMMODITY",
                                quantity=_total_g_final,
                                avg_buy_price=_ppg_final,
                                currency=_comm_currency_p,
                                asset_type="commodity",
                                unit="gram",
                            )
                            _oz_total = _total_g_final / _TROY_OZ
                            st.success(
                                f"Added {int(_num_pieces)}× {_piece_label} "
                                f"= {_total_g_final:.4g}g ({_oz_total:.4g} oz) of {_comm_name} "
                                f"@ {_comm_currency_p} {_price_per_piece:,.2f}/piece"
                            )
                            st.rerun()
                        else:
                            st.error("Bar weight must be greater than 0.")

                else:
                    # ── Digital / Oil / Gas ───────────────────────────────────
                    _unit_label = "gram" if _comm_unit == "troy oz" else _comm_unit
                    _dc1, _dc2 = st.columns(2)
                    with _dc1:
                        _quantity_d = st.number_input(
                            f"Quantity ({_unit_label}s)",
                            min_value=0.0001, value=10.0, step=1.0,
                            help=f"For Digital Gold / SGB enter grams; for Oil enter barrels."
                        )
                    with _dc2:
                        _avg_price_d = st.number_input(
                            f"Avg Buy Price (per {_unit_label})",
                            min_value=0.0, value=0.0, step=0.01,
                            help="Price per gram for Digital Gold / SGB."
                        )
                        _comm_currency_d = st.selectbox(
                            "Currency", ["USD", "INR", "EUR"], key="comm_cur_dig"
                        )

                    st.info(
                        f"yfinance symbol: `{_comm_sym}` ({_comm_unit} basis) → "
                        f"stored as **{_unit_label}**"
                    )

                    if st.form_submit_button("➕ Add Commodity", type="primary"):
                        _type_label = "Digital" if _is_metal else ""
                        db.add_asset(
                            symbol=_comm_sym,
                            name=f"{_comm_name}{' (Digital)' if _is_metal else ''}",
                            exchange="COMMODITY",
                            quantity=_quantity_d,
                            avg_buy_price=_avg_price_d,
                            currency=_comm_currency_d,
                            asset_type="commodity",
                            unit=_unit_label,
                        )
                        st.success(
                            f"Added {_quantity_d} {_unit_label}(s) of {_comm_name}"
                        )
                        st.rerun()

        # ── Indian Mutual Fund tab ─────────────────────────────────────────────
        with asset_add_tabs[2]:
            st.caption(
                "For **direct / regular Indian MF plans** whose NAV is not on Yahoo Finance.  \n"
                "You enter the NAV at purchase and update it manually whenever you like.  \n"
                "Current value = Units × Latest NAV (INR), converted to USD for portfolio totals."
            )
            with st.form("add_imf_form"):
                _if1, _if2 = st.columns(2)
                with _if1:
                    _imf_name = st.text_input(
                        "Fund Name",
                        placeholder="e.g. Mirae Asset Large Cap Fund — Direct Growth",
                        help="Full fund name as it appears on your statement.",
                    )
                    _imf_code = st.text_input(
                        "Short Code / AMFI Scheme No. (optional)",
                        placeholder="e.g. MIRAE_LC or 119551",
                        help="Used as the identifier in the portfolio table. Auto-generated from fund name if left blank.",
                    )
                    _imf_folio = st.text_input(
                        "Folio Number (optional)",
                        placeholder="e.g. 1234567/89",
                        help="For your own reference only.",
                    )
                with _if2:
                    _imf_units = st.number_input(
                        "Number of Units", min_value=0.001, value=100.0, step=0.001,
                        help="Total units held across all purchases (or for one SIP instalment).",
                    )
                    _imf_buy_nav = st.number_input(
                        "Purchase NAV (INR per unit)",
                        min_value=0.0, value=0.0, step=0.01,
                        help="Average NAV at which you bought. Used to compute gain/loss.",
                    )
                    _imf_cur_nav = st.number_input(
                        "Current NAV (INR, optional)",
                        min_value=0.0, value=0.0, step=0.01,
                        help="Today's NAV. Leave 0 to use purchase NAV for now — you can update it later.",
                    )

                if _imf_units > 0 and _imf_buy_nav > 0:
                    _imf_preview_nav = _imf_cur_nav if _imf_cur_nav > 0 else _imf_buy_nav
                    _imf_cur_val = _imf_units * _imf_preview_nav
                    _imf_invested = _imf_units * _imf_buy_nav
                    _imf_gl = _imf_cur_val - _imf_invested
                    st.info(
                        f"Units: **{_imf_units:,.3f}** × NAV: **₹{_imf_preview_nav:,.4f}** "
                        f"= **₹{_imf_cur_val:,.2f}**  |  "
                        f"Invested: ₹{_imf_invested:,.2f}  |  "
                        f"G/L: {'**+' if _imf_gl >= 0 else '**'}₹{_imf_gl:,.2f}**"
                    )

                if st.form_submit_button("➕ Add Indian MF", type="primary"):
                    if _imf_name and _imf_units > 0 and _imf_buy_nav > 0:
                        # Build symbol from code or fund name
                        _sym_raw = _imf_code.strip() if _imf_code.strip() else _imf_name.strip()
                        _imf_sym = _sym_raw.upper().replace(" ", "_")[:30]
                        _display_name = _imf_name.strip()
                        if _imf_folio:
                            _display_name += f" (Folio {_imf_folio.strip()})"
                        _asset_id = db.add_asset(
                            symbol=_imf_sym,
                            name=_display_name,
                            exchange="MUTUAL_FUND_IN",
                            quantity=_imf_units,
                            avg_buy_price=_imf_buy_nav,
                            currency="INR",
                            asset_type="mutual_fund",
                            unit="unit",
                        )
                        # Save current NAV if provided; else save purchase NAV
                        _nav_to_save = _imf_cur_nav if _imf_cur_nav > 0 else _imf_buy_nav
                        db.upsert_price(_asset_id, str(date.today()), _nav_to_save)
                        st.success(
                            f"Added **{_imf_name}** — {_imf_units:,.3f} units "
                            f"@ ₹{_imf_buy_nav:,.4f} purchase NAV"
                        )
                        st.rerun()
                    else:
                        st.error("Fund name, units, and purchase NAV are required.")

    # ── Refresh prices button ──
    col_r, _ = st.columns([1, 5])
    with col_r:
        if st.button("🔄 Refresh Prices Now"):
            with st.spinner("Fetching latest prices..."):
                results = asset_mod.refresh_all_prices()
            st.success(f"Updated {len(results)} assets.")
            st.rerun()

    # ── Portfolio table ──
    portfolio, total_invested_usd, total_current_usd, fx_rates = asset_mod.get_portfolio_summary()

    if not portfolio:
        st.info("No assets yet. Add one above.")
    else:
        st.subheader("Your Portfolio")

        if fx_rates:
            rate_parts = [f"1 {cur} = ${rate:.4f}" for cur, rate in fx_rates.items() if cur != "USD"]
            if rate_parts:
                st.caption("FX rates used: " + "  |  ".join(rate_parts))

        rows = []
        for r in portfolio:
            cur = r["currency"]
            val_usd = r["current_value_usd"]
            unit_label = r.get("unit", "share")
            qty_label = f"{r['quantity']:,.4f} {unit_label}" if unit_label != "share" else f"{r['quantity']:,.4f}"

            rows.append({
                "Type":           r.get("asset_type", "stock").capitalize(),
                "Symbol":         r["symbol"],
                "Name":           r["name"],
                "Qty":            qty_label,
                f"Price ({cur})": f"{r['current_price']:,.4f}" if r["current_price"] else "—",
                f"Value ({cur})": f"{r['current_value']:,.2f}" if r["current_value"] else "—",
                "Value (USD)":    f"${val_usd:,.2f}" if val_usd else "—",
                f"G/L ({cur})":   f"{r['gain_loss']:+,.2f}" if r["gain_loss"] is not None else "—",
                "G/L %":          f"{r['gain_loss_pct']:+.2f}%" if r["gain_loss_pct"] is not None else "—",
                "As of":          r["price_date"],
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, width='stretch', hide_index=True)

        # ── Portfolio totals ──
        port_c1, port_c2, port_c3 = st.columns(3)
        port_c1.metric("Portfolio Value (USD)", f"${total_current_usd:,.2f}",
                       f"{total_current_usd - total_invested_usd:+,.2f} total G/L")
        port_c2.metric("Total Invested (USD)", f"${total_invested_usd:,.2f}")
        _port_gl_pct = (total_current_usd - total_invested_usd) / total_invested_usd * 100 if total_invested_usd else 0
        port_c3.metric("Return", f"{_port_gl_pct:+.2f}%")

        # ── Indian MF NAV update panel ────────────────────────────────────────
        _imf_assets = [r for r in portfolio if r.get("asset_type") == "mutual_fund"]
        if _imf_assets:
            with st.expander("🇮🇳 Update Indian MF NAVs", expanded=True):
                st.caption(
                    "Enter today's NAV for each fund. "
                    "Find the latest NAV at [mfapi.in](https://www.mfapi.in) or your fund house website."
                )
                for _mf in _imf_assets:
                    _mf_nav_now = _mf.get("current_price") or _mf.get("avg_buy_price") or 0.0
                    _mf_invested = (_mf.get("avg_buy_price") or 0) * _mf["quantity"]
                    _mf_cur_val  = _mf_nav_now * _mf["quantity"]
                    _mf_gl       = _mf_cur_val - _mf_invested
                    _mf_gl_pct   = (_mf_gl / _mf_invested * 100) if _mf_invested else 0

                    with st.form(f"mf_nav_upd_{_mf['id']}"):
                        _nc1, _nc2, _nc3, _nc4 = st.columns([3, 1, 1, 1])
                        _nc1.markdown(
                            f"**{_mf['name']}**  \n"
                            f"`{_mf['symbol']}` · {_mf['quantity']:,.3f} units · "
                            f"Avg cost ₹{_mf.get('avg_buy_price',0):,.4f}"
                        )
                        _nc2.metric(
                            "Current NAV",
                            f"₹{_mf_nav_now:,.4f}",
                            help=f"As of {_mf.get('price_date','—')}",
                        )
                        _nc3.metric(
                            "Value",
                            f"₹{_mf_cur_val:,.2f}",
                            delta=f"{_mf_gl_pct:+.2f}%",
                            delta_color="normal" if _mf_gl >= 0 else "inverse",
                        )
                        _new_nav_input = _nc4.number_input(
                            "New NAV (₹)",
                            min_value=0.0,
                            value=float(_mf_nav_now),
                            step=0.01,
                            label_visibility="visible",
                            key=f"nav_inp_{_mf['id']}",
                        )
                        if st.form_submit_button("💾 Save NAV", width='stretch'):
                            if _new_nav_input > 0:
                                db.upsert_price(_mf["id"], str(date.today()), _new_nav_input)
                                _new_val = _new_nav_input * _mf["quantity"]
                                _new_gl  = _new_val - _mf_invested
                                st.success(
                                    f"NAV updated to ₹{_new_nav_input:,.4f}  |  "
                                    f"New value: ₹{_new_val:,.2f}  |  "
                                    f"G/L: {'▲' if _new_gl >= 0 else '▼'} ₹{abs(_new_gl):,.2f}"
                                )
                                st.rerun()
                            else:
                                st.error("NAV must be greater than 0.")

        # ── Analyst Insights & Valuation (on-demand, per asset) ──────────────
        with st.expander("🔍 Analyst Insights & Valuation"):
            st.caption(
                "Fetches live analyst price targets, consensus recommendation, "
                "52-week range and valuation multiples from Yahoo Finance. "
                "Available for most US/Indian listed stocks and ETFs; "
                "not available for commodities, crypto, or unlisted assets."
            )
            _stock_assets = [r for r in portfolio if r.get("asset_type") not in ("commodity",)]
            if not _stock_assets:
                st.info("No stocks/ETFs in your portfolio.")
            else:
                _insight_sym = st.selectbox(
                    "Select asset",
                    [f"{r['symbol']} — {r['name']}" for r in _stock_assets],
                    key="insight_sym",
                )
                if st.button("📡 Fetch Analyst Data", key="fetch_analyst"):
                    _sel_sym = _insight_sym.split(" — ")[0]
                    _sel_r = next(r for r in _stock_assets if r["symbol"] == _sel_sym)
                    with st.spinner(f"Fetching analyst data for {_sel_sym}…"):
                        _ad = asset_mod.fetch_analyst_data(_sel_sym)
                    st.session_state["_analyst_data"] = _ad
                    st.session_state["_analyst_sym"] = _sel_sym
                    st.session_state["_analyst_r"] = _sel_r

                if st.session_state.get("_analyst_sym"):
                    _ad  = st.session_state["_analyst_data"]
                    _sym = st.session_state["_analyst_sym"]
                    _ar  = st.session_state["_analyst_r"]
                    _cur = _ar["currency"]

                    if not _ad:
                        st.warning(f"No analyst data available for **{_sym}** (commodity, crypto, or unlisted).")
                    else:
                        st.markdown(f"#### {_sym} — {_ar['name']}")
                        _ia1, _ia2, _ia3, _ia4 = st.columns(4)

                        # Recommendation badge
                        _rec = (_ad.get("recommendation") or "").lower().replace("_", " ")
                        _rec_color = {
                            "strong buy": "🟢", "buy": "🟢",
                            "hold": "🟡",
                            "sell": "🔴", "strong sell": "🔴",
                        }.get(_rec, "⚪")
                        _ia1.metric(
                            "Analyst Consensus",
                            f"{_rec_color} {_rec.title() if _rec else 'N/A'}",
                            help=f"Based on {_ad.get('num_analysts') or 'N/A'} analyst opinions",
                        )

                        # Price target
                        _tgt = _ad.get("target_mean")
                        _ia2.metric(
                            f"Price Target ({_cur})",
                            f"{_tgt:,.2f}" if _tgt else "N/A",
                            delta=f"{_ad['upside_pct']:+.1f}% upside" if _ad.get("upside_pct") is not None else None,
                            delta_color="normal" if (_ad.get("upside_pct") or 0) >= 0 else "inverse",
                        )

                        # 52W range
                        _w_hi = _ad.get("week52_high")
                        _w_lo = _ad.get("week52_low")
                        _ia3.metric(
                            "52W High",
                            f"{_cur} {_w_hi:,.2f}" if _w_hi else "N/A",
                        )
                        _ia4.metric(
                            "52W Low",
                            f"{_cur} {_w_lo:,.2f}" if _w_lo else "N/A",
                        )

                        # Valuation multiples
                        _vm_cols = st.columns(4)
                        _tpe = _ad.get("trailing_pe")
                        _fpe = _ad.get("forward_pe")
                        _pb  = _ad.get("price_to_book")
                        _vm_cols[0].metric("Trailing P/E", f"{_tpe:.1f}×" if _tpe else "N/A")
                        _vm_cols[1].metric("Forward P/E",  f"{_fpe:.1f}×" if _fpe else "N/A")
                        _vm_cols[2].metric("Price/Book",   f"{_pb:.2f}×"  if _pb  else "N/A")

                        # 52W range bar
                        if _w_lo and _w_hi and _ar.get("current_price") and _w_hi > _w_lo:
                            _cp = _ar["current_price"]
                            _pos = min(1.0, max(0.0, (_cp - _w_lo) / (_w_hi - _w_lo)))
                            st.markdown(
                                f"**52W position** — {_cur} {_w_lo:,.2f} "
                                f"◀ current: {_cp:,.2f} ({_pos*100:.0f}% of range) ▶ "
                                f"{_cur} {_w_hi:,.2f}"
                            )
                            st.progress(_pos)

                        # Target range bar
                        _t_lo = _ad.get("target_low")
                        _t_hi = _ad.get("target_high")
                        if _t_lo and _t_hi and _tgt and _ar.get("current_price"):
                            _cp = _ar["current_price"]
                            st.markdown(
                                f"**Analyst target range** — "
                                f"Low {_cur} {_t_lo:,.2f} | "
                                f"Mean {_cur} {_tgt:,.2f} | "
                                f"High {_cur} {_t_hi:,.2f} "
                                f"(current: {_cur} {_cp:,.2f})"
                            )

        # ── Dividend income ──
        with st.expander("💵 Annual Dividend Income (last 12 months)"):
            with st.spinner("Fetching dividend data..."):
                div_rows, total_div_usd = asset_mod.get_annual_dividend_income()
            if not div_rows:
                st.info("No dividend income found for your holdings in the last 12 months.")
            else:
                div_df = pd.DataFrame([{
                    "Symbol": d["symbol"],
                    "Name": d["name"],
                    "Qty": d["quantity"],
                    f"Annual Div ({d['currency']})": f"{d['dividend_native']:,.2f}",
                    "Annual Div (USD)": f"${d['dividend_usd']:,.2f}",
                } for d in div_rows])
                st.dataframe(div_df, width='stretch', hide_index=True)
                st.metric("Total Annual Dividends (USD)", f"${total_div_usd:,.2f}",
                          help="Sum of dividends paid by all your holdings in the last 12 months")

        # ── Price history chart ──
        st.subheader("Price History")
        asset_options = {f"{r['symbol']} ({r['currency']}) — {r['name']}": r["id"] for r in portfolio}
        selected = st.selectbox("Select asset", list(asset_options.keys()))
        if selected:
            asset_id = asset_options[selected]
            sel_cur = next(r["currency"] for r in portfolio if r["id"] == asset_id)
            history = db.get_price_history(asset_id, days=180)
            if len(history) > 1:
                hist_df = pd.DataFrame(history)
                fig = px.line(hist_df, x="date", y="price", title=selected)
                fig.update_layout(xaxis_title="Date", yaxis_title=f"Price ({sel_cur})")
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("Not enough history yet — prices are recorded daily, check back tomorrow.")

        # ── Manual price update (for Indian MFs and assets not on Yahoo Finance) ──
        with st.expander("✏️ Update Price Manually (Indian MFs, unlisted assets)"):
            st.caption(
                "Use this for assets whose price **cannot be fetched automatically** — "
                "e.g. direct Indian Mutual Funds (not on Yahoo Finance), unlisted equity, PPF, NPS, FDs, SGBs, etc."
            )
            upd_options = {
                f"{r['symbol']} — {r['name']} ({r['currency']})": r["id"]
                for r in portfolio
            }
            upd_selected = st.selectbox("Select asset to update", list(upd_options.keys()), key="manual_price_asset")
            if upd_selected:
                _upd_id = upd_options[upd_selected]
                _upd_r = next(r for r in portfolio if r["id"] == _upd_id)
                _cur_price = _upd_r.get("current_price")
                with st.form("manual_price_form"):
                    _new_price = st.number_input(
                        f"New Price ({_upd_r['currency']})",
                        min_value=0.0,
                        value=float(_cur_price) if _cur_price else 0.0,
                        step=0.01,
                        help="Enter the latest NAV or market price in the asset's native currency.",
                    )
                    _price_date = st.date_input("As of date", value=date.today(), key="manual_price_date")
                    if st.form_submit_button("💾 Save Price", type="primary"):
                        db.upsert_price(_upd_id, str(_price_date), _new_price)
                        st.success(
                            f"Price updated: {_upd_r['currency']} {_new_price:,.4f} "
                            f"for {_upd_r['symbol']} on {_price_date}"
                        )
                        st.rerun()

        # ── Delete asset ──
        with st.expander("🗑️ Remove an Asset"):
            del_options = {f"{r['symbol']} ({r.get('asset_type','stock')}) — {r['name']}": r["id"] for r in portfolio}
            del_selected = st.selectbox("Select to remove", list(del_options.keys()), key="del_asset")
            if st.button("Remove Asset", type="secondary"):
                db.delete_asset(del_options[del_selected])
                st.success("Asset removed.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LOANS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.header("Loans")

    # ── Add loan ────────────────────────────────────────────────────────────────
    with st.expander("➕ Add New Loan", expanded=False):
        add_tabs = st.tabs(["🏠 Standard Loan", "💳 EMI-Only"])

        # ── STANDARD ──────────────────────────────────────────────────────────
        with add_tabs[0]:
            # Currency and rate-type outside form so they trigger reruns immediately
            _sc1, _sc2, _sc3 = st.columns(3)
            s_currency  = _sc1.selectbox("Currency", ["INR", "USD", "EUR", "GBP", "CAD", "AED"], key="s_c")
            s_rate_type = _sc2.radio(
                "Interest method",
                ["Reducing Balance", "Flat Rate"],
                horizontal=True,
                key="s_rt",
                help=(
                    "**Reducing Balance** — interest on outstanding balance. "
                    "Standard for most bank loans.\n\n"
                    "**Flat Rate** — interest always on original principal "
                    "(P × rate × years ÷ months). Common in some car/consumer schemes."
                ),
            )

            with st.form("form_standard"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    s_name      = st.text_input("Loan Name", placeholder="Home Loan / Car Loan / Personal Loan")
                    s_principal = st.number_input(f"Principal ({s_currency})", min_value=1.0, value=100000.0, step=1000.0, key="s_p")
                with c2:
                    s_rate      = st.number_input("Annual Interest Rate (%)", min_value=0.0, max_value=100.0, value=8.5, step=0.1, key="s_r")
                    s_tenure    = st.number_input("Tenure (months)", min_value=1, max_value=360, value=60, step=1, key="s_t")
                with c3:
                    s_date      = st.date_input("Start Date", value=date.today(), key="s_d")

                _is_flat = s_rate_type == "Flat Rate"
                emi_rb   = loan_mod.calculate_emi(s_principal, s_rate, s_tenure, flat_rate=False)
                emi_flat = loan_mod.calculate_emi(s_principal, s_rate, s_tenure, flat_rate=True)
                emi_preview = emi_flat if _is_flat else emi_rb

                _ci1, _ci2 = st.columns(2)
                _ci1.info(
                    f"Reducing Balance: **{s_currency} {emi_rb:,.2f}/mo**  "
                    f"| Total interest: {s_currency} {emi_rb * s_tenure - s_principal:,.2f}"
                )
                _ci2.info(
                    f"Flat Rate: **{s_currency} {emi_flat:,.2f}/mo**  "
                    f"| Total interest: {s_currency} {emi_flat * s_tenure - s_principal:,.2f}"
                )

                s_emi_override = st.number_input(
                    f"Actual Monthly EMI ({s_currency})",
                    min_value=0.01,
                    value=emi_preview,
                    step=100.0,
                    help="Pre-filled based on the method above. Override if your bank quotes a different amount.",
                )

                if st.form_submit_button("Add Loan", type="primary"):
                    if s_name:
                        db.add_loan(s_name, s_principal, s_rate, s_tenure,
                                    str(s_date), s_emi_override, s_currency, loan_type="standard")
                        st.success(f"Loan added! EMI = {s_currency} {s_emi_override:,.2f} / month")
                        st.rerun()

        # ── EMI-ONLY ──────────────────────────────────────────────────────────
        with add_tabs[1]:
            st.markdown("### EMI-Only / Simple Loan")
            st.caption(
                "Use this when you already have an active loan and only know your **monthly EMI** "
                "and **months remaining** — no need for principal or interest rate. "
                "Perfect for car loans, personal loans, or any EMI you just want to track."
            )
            se_currency = st.selectbox("Currency", ["INR", "USD", "EUR", "GBP", "CAD", "AED"], key="se_c")

            with st.form("form_simple_emi"):
                se1, se2, se3 = st.columns(3)
                with se1:
                    se_name   = st.text_input("Loan Name", placeholder="Car Loan / Personal Loan", key="se_n")
                    se_emi    = st.number_input(f"Monthly EMI ({se_currency})", min_value=1.0, value=5000.0, step=100.0, key="se_e")
                with se2:
                    se_months = st.number_input("Months Remaining", min_value=1, max_value=360, value=36, step=1, key="se_m")
                with se3:
                    se_date   = st.date_input("Start Date (approx.)", value=date.today(), key="se_d",
                                              help="Approximate date this loan started — used for display only.")

                se_total = se_emi * se_months
                st.info(
                    f"Total remaining: **{se_currency} {se_total:,.2f}**  |  "
                    f"EMI: **{se_currency} {se_emi:,.2f}/mo**  ×  {int(se_months)} months"
                )

                if st.form_submit_button("Add EMI-Only Loan", type="primary"):
                    if se_name:
                        db.add_loan(
                            se_name,
                            principal=se_total,
                            interest_rate=0.0,
                            tenure_months=int(se_months),
                            start_date=str(se_date),
                            emi=float(se_emi),
                            currency=se_currency,
                            loan_type="simple_emi",
                        )
                        st.success(f"Loan added! EMI = {se_currency} {se_emi:,.2f} / month × {int(se_months)} months")
                        st.rerun()
                    else:
                        st.error("Please enter a loan name.")


    # ── Monthly EMI Overview ───────────────────────────────────────────────────
    loans = db.get_all_loans()
    active_loans = [l for l in loans if l["remaining_balance"] > 0]

    if active_loans:
        st.subheader("This Month's EMIs")
        this_month = date.today().strftime("%Y-%m")
        for loan in active_loans:
            cur = loan["currency"]
            payments = db.get_payments(loan["id"])
            paid_this_month = any(p["payment_date"].startswith(this_month) for p in payments)
            emi_due = loan["in_school_payment_amt"] or loan["emi"] or 0

            status_col, info_col, action_col = st.columns([1, 3, 2])
            status_col.markdown("✅" if paid_this_month else "🔴")
            info_col.markdown(
                f"**{loan['name']}** — {cur} {emi_due:,.2f} / mo  "
                f"| Balance: {cur} {loan['remaining_balance']:,.2f}"
            )
            if not paid_this_month:
                with action_col.form(f"quick_pay_{loan['id']}"):
                    q_amt = st.number_input("Amount", value=float(emi_due), step=100.0,
                                            label_visibility="collapsed", key=f"qp_{loan['id']}")
                    if st.form_submit_button("Mark Paid", type="primary"):
                        db.log_payment(loan["id"], q_amt, str(date.today()), "Monthly EMI")
                        st.success(f"Logged {cur} {q_amt:,.2f} for {loan['name']}")
                        st.rerun()
            else:
                action_col.caption("Paid this month")

        st.divider()

    # ── Existing loans list ────────────────────────────────────────────────────
    if not loans:
        st.info("No loans added yet. Use the form above.")
    else:
        for loan in loans:
            cur       = loan["currency"]
            loan_type = loan.get("loan_type") or "standard"
            progress  = 1 - (loan["remaining_balance"] / loan["principal"]) if loan["principal"] else 0

            # ── Type badge ──
            badge_map = {
                "standard":       ("🏠", "Standard"),
                "simple_emi":     ("💳", "EMI Only"),
                "leap_finance":   ("🎓", "Leap Finance"),
                "prodigy_finance":("🌍", "Prodigy Finance"),
                "sofi":           ("🇺🇸", "SoFi"),
            }
            icon, label = badge_map.get(loan_type, ("", "Standard"))

            with st.container(border=True):
                st.markdown(f"**{icon} {loan['name']}** &nbsp; `{label}`")

                # ── Summary metrics (standard layout for all types) ──
                s = loan_mod.loan_summary(loan)
                if loan_type == "simple_emi":
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Monthly EMI", f"{cur} {s['emi']:,.2f}")
                    col2.metric("Remaining Balance", f"{cur} {s['remaining_balance']:,.2f}")
                    col3.metric("Months Left", s["months_remaining"])
                else:
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("EMI", f"{cur} {s['emi']:,.2f}")
                    col2.metric("Remaining", f"{cur} {s['remaining_balance']:,.2f}")
                    col3.metric("Total Interest", f"{cur} {s['total_interest']:,.2f}")
                    col4.metric("Months Left", s["months_remaining"])

                progress_text = (
                    f"{progress*100:.1f}% paid off"
                    if loan_type == "simple_emi"
                    else f"{progress*100:.1f}% paid off  |  Rate: {loan['interest_rate']}% p.a."
                )
                st.progress(progress, text=progress_text)

                lcol1, lcol2 = st.columns(2)

                # Log payment
                with lcol1.expander("💳 Log a Payment"):
                    with st.form(f"pay_{loan['id']}"):
                        default_pay = float(loan["in_school_payment_amt"] or loan["emi"] or 0)
                        pay_amount = st.number_input(f"Amount Paid ({cur})", min_value=0.01,
                                                     value=default_pay, step=100.0, key=f"amt_{loan['id']}")
                        pay_date = st.date_input("Payment Date", value=date.today(), key=f"dt_{loan['id']}")
                        pay_note = st.text_input("Note (optional)", key=f"note_{loan['id']}")
                        if st.form_submit_button("Log Payment"):
                            new_bal = db.log_payment(loan["id"], pay_amount, str(pay_date), pay_note)
                            st.success(f"Payment logged! New balance: {cur} {new_bal:,.2f}")
                            st.rerun()

                # Full schedule from remaining balance
                with lcol2.expander("📅 Full Payment Schedule"):
                    start = date.fromisoformat(loan["start_date"])
                    if loan_type == "simple_emi":
                        emi_amt = loan["emi"] or 0
                        bal = loan["remaining_balance"]
                        months_left = s["months_remaining"]
                        sched = []
                        cur_d = start
                        for m in range(1, months_left + 1):
                            payment = min(emi_amt, bal)
                            bal = max(0.0, round(bal - payment, 2))
                            cur_d = loan_mod._next_month_date(cur_d)
                            sched.append({
                                "month": m,
                                "due_date": str(cur_d),
                                "phase": "Repayment",
                                "payment": payment,
                                "principal_component": payment,
                                "interest_component": 0.0,
                                "capitalized": 0.0,
                                "balance": bal,
                            })
                    else:
                        sched = loan_mod.amortization_schedule(
                            loan["remaining_balance"], loan["interest_rate"],
                            s["months_remaining"], start)

                    sched_df = pd.DataFrame(sched)
                    sched_df = sched_df.rename(columns={
                        "month": "Month", "due_date": "Due Date", "phase": "Phase",
                        "payment": f"Payment ({cur})", "principal_component": "Principal",
                        "interest_component": "Interest", "capitalized": "Capitalised",
                        "balance": f"Balance ({cur})",
                    })
                    # Colour phase column
                    st.dataframe(sched_df, width='stretch', hide_index=True, height=350)

                # Payment history
                payments = db.get_payments(loan["id"])
                if payments:
                    with st.expander("🧾 Payment History"):
                        pay_df = pd.DataFrame(payments)[["payment_date", "amount_paid", "remaining_balance", "note"]]
                        pay_df.columns = ["Date", f"Paid ({cur})", f"Balance ({cur})", "Note"]
                        st.dataframe(pay_df, width='stretch', hide_index=True)

                    with st.expander("📉 Balance Over Time"):
                        bal_df = pd.DataFrame([{"date": p["payment_date"], "balance": p["remaining_balance"]}
                                               for p in reversed(payments)])
                        fig = px.line(bal_df, x="date", y="balance", title=f"{loan['name']} — Balance")
                        fig.update_layout(yaxis_title=f"Balance ({cur})")
                        st.plotly_chart(fig, width='stretch')

                if st.button(f"🗑️ Delete {loan['name']}", key=f"del_{loan['id']}"):
                    db.delete_loan(loan["id"])
                    st.success("Loan deleted.")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — EDUCATION LOAN TRACKER
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.header("🎓 Education Loan Tracker")

    # ── Default config (Leap Finance example) ─────────────────────────────────
    _EDU_DEFAULTS = {
        "lender":                "Leap Finance Inc",
        "borrower":              "",
        "purpose":               "",
        "currency":              "USD",
        "sanctioned_amount":     75000.0,
        "disbursed_amount":      65000.0,
        "loan_fee_total":        2250.0,
        "loan_fee_upfront":      750.0,
        "loan_fee_capitalized":  1500.0,
        "annual_rate":           11.60,
        "apr_rate":              11.70,
        "days_in_year":          365,
        "first_disbursement":    "2023-08-01",
        "moratorium_end":        "2026-08-01",
        "maturity_date":         "2036-09-05",
        "token_payment":         50.0,
        "current_principal":     68236.09,
        "current_accrued":       5810.10,
        "current_as_of":         str(date.today()),
        "payments":              [],   # [{date, amount}]
    }

    _saved_cfg = db.get_edu_loan_config()
    _cfg       = _saved_cfg or _EDU_DEFAULTS

    # ── A. Config form ─────────────────────────────────────────────────────────
    with st.expander("⚙️ Loan Configuration", expanded=_saved_cfg is None):
        with st.form("edu_loan_config_form"):
            st.markdown("#### Basic Info")
            _fc1, _fc2, _fc3 = st.columns(3)
            _lender    = _fc1.text_input("Lender",    value=_cfg["lender"])
            _borrower  = _fc2.text_input("Borrower",  value=_cfg["borrower"])
            _purpose   = _fc3.text_input("Purpose",   value=_cfg["purpose"])
            _currency  = _fc1.selectbox("Currency",
                ["USD","INR","EUR","GBP","CAD","AED"],
                index=["USD","INR","EUR","GBP","CAD","AED"].index(_cfg["currency"]))

            st.markdown("#### Amounts")
            _am1, _am2, _am3 = st.columns(3)
            _sanctioned  = _am1.number_input("Sanctioned Amount",      min_value=0.0, value=float(_cfg["sanctioned_amount"]),    step=1000.0)
            _disbursed   = _am2.number_input("Disbursed Amount",        min_value=0.0, value=float(_cfg["disbursed_amount"]),     step=1000.0)
            _fee_total   = _am3.number_input("Total Loan Fee",          min_value=0.0, value=float(_cfg["loan_fee_total"]),       step=100.0)
            _fee_upfront = _am1.number_input("Fee Paid Upfront",        min_value=0.0, value=float(_cfg["loan_fee_upfront"]),    step=100.0)
            _fee_cap     = _am2.number_input("Fee Capitalized (added to principal)", min_value=0.0, value=float(_cfg["loan_fee_capitalized"]), step=100.0)

            st.markdown("#### Rates & Dates")
            _rd1, _rd2, _rd3 = st.columns(3)
            _rate        = _rd1.number_input("Annual Interest Rate (%)", min_value=0.0, max_value=30.0, value=float(_cfg["annual_rate"]), step=0.05)
            _apr         = _rd2.number_input("APR (%)",                  min_value=0.0, max_value=30.0, value=float(_cfg["apr_rate"]),    step=0.05)
            _days_yr     = _rd3.selectbox("Days in Year", [365, 360], index=0 if _cfg["days_in_year"] == 365 else 1)
            _token_pmt   = _rd1.number_input("Monthly Token Payment",   min_value=0.0, value=float(_cfg["token_payment"]), step=10.0)
            _first_disb  = _rd2.date_input("First Disbursement Date",   value=date.fromisoformat(_cfg["first_disbursement"]))
            _mora_end    = _rd3.date_input("Moratorium End Date",        value=date.fromisoformat(_cfg["moratorium_end"]))
            _maturity    = _rd2.date_input("Maturity Date",              value=date.fromisoformat(_cfg["maturity_date"]))

            st.markdown("#### Current Status (from lender portal)")
            _cs1, _cs2, _cs3 = st.columns(3)
            _cur_princ   = _cs1.number_input("Current Principal Balance", min_value=0.0, value=float(_cfg["current_principal"]), step=100.0)
            _cur_accrued = _cs2.number_input("Current Accrued Interest",  min_value=0.0, value=float(_cfg["current_accrued"]),   step=10.0)
            _cur_as_of   = _cs3.date_input("As Of Date",                  value=date.fromisoformat(_cfg["current_as_of"]))

            if st.form_submit_button("💾 Save Configuration", type="primary"):
                _new_cfg = {
                    "lender": _lender, "borrower": _borrower, "purpose": _purpose,
                    "currency": _currency,
                    "sanctioned_amount": _sanctioned, "disbursed_amount": _disbursed,
                    "loan_fee_total": _fee_total, "loan_fee_upfront": _fee_upfront,
                    "loan_fee_capitalized": _fee_cap,
                    "annual_rate": _rate, "apr_rate": _apr, "days_in_year": _days_yr,
                    "token_payment": _token_pmt,
                    "first_disbursement": str(_first_disb),
                    "moratorium_end": str(_mora_end),
                    "maturity_date": str(_maturity),
                    "current_principal": _cur_princ,
                    "current_accrued": _cur_accrued,
                    "current_as_of": str(_cur_as_of),
                    "payments": _cfg.get("payments", []),
                }
                db.save_edu_loan_config(_new_cfg)
                st.success("Configuration saved!")
                st.rerun()

    # ── Payment history management ─────────────────────────────────────────────
    with st.expander("💳 Payment History (manual entry)"):
        _payments = list(_cfg.get("payments", []))
        st.caption("All payments made so far — moratorium token payments, prepayments, etc.")

        if _payments:
            _pay_df = pd.DataFrame(_payments)
            _pay_df.columns = ["Date", f"Amount ({_cfg['currency']})"]
            st.dataframe(_pay_df, hide_index=True, width='stretch')

        with st.form("add_edu_payment"):
            _pc1, _pc2, _pc3 = st.columns([2, 2, 1])
            _p_date   = _pc1.date_input("Payment Date", value=date.today())
            _p_amount = _pc2.number_input(f"Amount ({_cfg['currency']})", min_value=0.01, value=float(_cfg["token_payment"]), step=10.0)
            _pc3.write("")
            if _pc3.form_submit_button("Add", type="primary"):
                _payments.append({"date": str(_p_date), "amount": _p_amount})
                _updated = dict(_cfg)
                _updated["payments"] = _payments
                db.save_edu_loan_config(_updated)
                st.rerun()

        if _payments and st.button("🗑️ Clear All Payments"):
            _updated = dict(_cfg)
            _updated["payments"] = []
            db.save_edu_loan_config(_updated)
            st.rerun()

    # ── Run calculations ───────────────────────────────────────────────────────
    _today      = date.today()
    _mora_end   = date.fromisoformat(_cfg["moratorium_end"])
    _maturity   = date.fromisoformat(_cfg["maturity_date"])
    _first_disb = date.fromisoformat(_cfg["first_disbursement"])
    _in_mora    = _today < _mora_end

    # Moratorium simulation (from disbursement to end)
    _mora_rows, _mora_final_princ, _mora_total_accrued = edu_mod.simulate_moratorium(
        principal           = _cfg["disbursed_amount"],
        loan_fee_capitalized= _cfg["loan_fee_capitalized"],
        annual_rate         = _cfg["annual_rate"],
        start_date          = _first_disb,
        moratorium_end_date = _mora_end,
        token_payment       = _cfg["token_payment"],
        payments            = _cfg.get("payments", []),
        days_in_year        = _cfg["days_in_year"],
    )

    # Use actual current balance (from lender) for forward projection
    _cur_princ    = float(_cfg["current_principal"])
    _cur_accrued  = float(_cfg["current_accrued"])

    # Projected capitalized balance at moratorium end
    if _in_mora:
        # From current status, project forward to moratorium end
        _months_left_mora = edu_mod._months_between(_today, _mora_end)
        _projected_accrued = _cur_accrued
        _projected_princ   = _cur_princ
        _d = _today
        for _ in range(_months_left_mora):
            _m_int = edu_mod.daily_interest_for_month(_projected_princ, _cfg["annual_rate"], _d, _cfg["days_in_year"])
            _projected_accrued += _m_int - _cfg["token_payment"]  # shortfall accumulates
            _d = edu_mod._add_months(_d, 1)
        _cap_balance = edu_mod.capitalize_interest(_projected_princ, max(0, _projected_accrued))
    else:
        _cap_balance = edu_mod.capitalize_interest(_cur_princ, _cur_accrued)

    # Amortization from moratorium end (or from today if already in repayment)
    _emi_start     = _mora_end if _in_mora else _today
    _amort_rows, _calc_emi = edu_mod.generate_amortization(
        _cap_balance, _cfg["annual_rate"], _emi_start, _maturity)

    # Cost summary
    _cost = edu_mod.cost_summary(
        _cfg["disbursed_amount"], _cfg["loan_fee_upfront"],
        _mora_rows, _amort_rows)

    _cur_monthly_int = edu_mod.daily_interest_for_month(
        _cur_princ, _cfg["annual_rate"], _today, _cfg["days_in_year"])
    _daily_int_cost  = round(_cur_princ * _cfg["annual_rate"] / 100 / _cfg["days_in_year"], 2)

    # ── B. Overview Dashboard ──────────────────────────────────────────────────
    st.subheader("📊 Loan Overview")

    _ov1, _ov2, _ov3, _ov4 = st.columns(4)
    _ov1.metric("Principal Balance",   f"{_cfg['currency']} {_cur_princ:,.2f}")
    _ov2.metric("Accrued Interest",    f"{_cfg['currency']} {_cur_accrued:,.2f}",
                help="Unpaid interest accumulated — will be capitalized at moratorium end")
    _ov3.metric("Total Outstanding",   f"{_cfg['currency']} {_cur_princ + _cur_accrued:,.2f}")
    _ov4.metric("Annual Rate",         f"{_cfg['annual_rate']}%  (APR {_cfg['apr_rate']}%)")

    _ov5, _ov6, _ov7, _ov8 = st.columns(4)
    _ov5.metric("Calculated EMI",      f"{_cfg['currency']} {_calc_emi:,.2f}/mo",
                help="EMI on capitalized balance from moratorium end to maturity")
    _ov6.metric("Maturity",            _maturity.strftime("%b %Y"))
    _ov7.metric("Monthly Interest Now",f"{_cfg['currency']} {_cur_monthly_int:,.2f}",
                help="Interest accruing this month on current principal")
    _ov8.metric("Daily Interest Cost", f"{_cfg['currency']} {_daily_int_cost:,.2f}/day")

    _total_tenure_mo = edu_mod._months_between(_first_disb, _maturity)
    _elapsed_mo      = edu_mod._months_between(_first_disb, _today)
    _progress_time   = min(1.0, _elapsed_mo / _total_tenure_mo) if _total_tenure_mo else 0
    _progress_paid   = max(0.0, min(1.0, 1 - _cur_princ / _cfg["disbursed_amount"])) if _cfg["disbursed_amount"] else 0

    st.progress(_progress_paid, text=f"Principal paid off: {_progress_paid*100:.1f}%")
    st.progress(_progress_time, text=f"Time elapsed: {_elapsed_mo} of {_total_tenure_mo} months ({_progress_time*100:.1f}%)")

    _phase_label = "🟡 Moratorium / Grace Period" if _in_mora else "🟢 EMI Repayment"
    st.info(f"**Current Phase:** {_phase_label}  "
            + (f"| Moratorium ends **{_mora_end.strftime('%d %b %Y')}** "
               f"({edu_mod._months_between(_today, _mora_end)} months away)"
               if _in_mora else
               f"| {edu_mod._months_between(_today, _maturity)} months remaining"))

    # ── C. Phase Timeline ──────────────────────────────────────────────────────
    st.subheader("📅 Loan Phase Timeline")
    _tl_phases = [
        ("🏦 Disbursement",         _first_disb.strftime("%b %Y"),    False),
        ("📚 Moratorium / Grace",   f"{_first_disb.strftime('%b %Y')} – {_mora_end.strftime('%b %Y')}", _in_mora),
        ("💳 EMI Repayment",        f"{_mora_end.strftime('%b %Y')} – {_maturity.strftime('%b %Y')}",   not _in_mora),
        ("🎉 Payoff",               _maturity.strftime("%b %Y"),      False),
    ]
    _tl_cols = st.columns(len(_tl_phases))
    for _col, (_name, _period, _active) in zip(_tl_cols, _tl_phases):
        if _active:
            _col.markdown(f"**▶ {_name}**")
            _col.markdown(f"*{_period}*")
            _col.markdown("⬆ **YOU ARE HERE**")
        else:
            _col.markdown(_name)
            _col.markdown(f"*{_period}*")

    st.divider()

    # ── D. Moratorium Tracker ──────────────────────────────────────────────────
    if _mora_rows:
        with st.expander("📉 Moratorium Phase Tracker", expanded=_in_mora):
            _total_mora_paid     = sum(r["payment"]          for r in _mora_rows)
            _total_mora_int      = sum(r["applied_interest"]  for r in _mora_rows)
            _total_mora_princ    = sum(r["applied_principal"] for r in _mora_rows)
            _total_mora_shortfall= sum(r["shortfall"]         for r in _mora_rows)

            _dm1, _dm2, _dm3, _dm4 = st.columns(4)
            _dm1.metric("Total Paid (moratorium)",    f"{_cfg['currency']} {_total_mora_paid:,.2f}")
            _dm2.metric("Went to Interest",           f"{_cfg['currency']} {_total_mora_int:,.2f}")
            _dm3.metric("Went to Principal",          f"{_cfg['currency']} {_total_mora_princ:,.2f}")
            _dm4.metric("Total Shortfall Accumulated",f"{_cfg['currency']} {_total_mora_shortfall:,.2f}",
                        help="Unpaid interest that capitalizes at moratorium end")

            if _in_mora:
                _dm5, _dm6 = st.columns(2)
                _dm5.metric("Projected Capitalized Balance", f"{_cfg['currency']} {_cap_balance:,.2f}",
                            help="Principal + all accrued interest becomes new loan balance at moratorium end")
                _dm6.metric("Extra Principal from Capitalization",
                            f"{_cfg['currency']} {_cap_balance - _cfg['disbursed_amount']:,.2f}",
                            help="How much more you owe vs what was originally disbursed")

            st.caption("⚠️ **The Moratorium Trap**: Each month you pay the token amount but ~10× more interest accrues. "
                       "Almost all of your payments go toward interest, and at moratorium end all unpaid interest is added to principal.")

            # Monthly moratorium table
            _mora_df = pd.DataFrame([{
                "Month": r["date_label"],
                "Balance":          f"{r['opening_balance']:,.2f}",
                f"Interest Accrued": f"{r['monthly_interest']:,.2f}",
                "Payment":          f"{r['payment']:,.2f}",
                "→ Interest":       f"{r['applied_interest']:,.2f}",
                "→ Principal":      f"{r['applied_principal']:,.2f}",
                "Shortfall":        f"{r['shortfall']:,.2f}",
                "Running Accrued":  f"{r['accrued_interest']:,.2f}",
            } for r in _mora_rows])
            st.dataframe(_mora_df, hide_index=True, width='stretch', height=300)

            # Shortfall chart
            _mora_chart = pd.DataFrame({
                "Month":     [r["date_label"]     for r in _mora_rows],
                "Monthly Interest": [r["monthly_interest"]  for r in _mora_rows],
                "Token Payment":    [r["payment"]            for r in _mora_rows],
                "Shortfall":        [r["shortfall"]          for r in _mora_rows],
            })
            _fig_mora = go.Figure()
            _fig_mora.add_trace(go.Bar(name="Monthly Interest", x=_mora_chart["Month"], y=_mora_chart["Monthly Interest"], marker_color="#ef4444"))
            _fig_mora.add_trace(go.Bar(name="Token Payment",    x=_mora_chart["Month"], y=_mora_chart["Token Payment"],    marker_color="#22c55e"))
            _fig_mora.update_layout(barmode="overlay", title="Interest Accruing vs Token Payment",
                                    xaxis_title="Month", yaxis_title=f"Amount ({_cfg['currency']})",
                                    legend=dict(orientation="h"))
            st.plotly_chart(_fig_mora, width='stretch')

    # ── E. Amortization Schedule ───────────────────────────────────────────────
    with st.expander("📋 EMI Amortization Schedule"):
        if _amort_rows:
            _show_toggle = st.radio("Show", ["Remaining only", "Full schedule"], horizontal=True, key="amort_show")
            _rows_to_show = [r for r in _amort_rows if not r["is_past"]] if _show_toggle == "Remaining only" else _amort_rows

            _amort_df = pd.DataFrame([{
                "Month":               r["month"],
                "Date":                r["date_label"],
                f"Opening ({_cfg['currency']})": f"{r['opening_balance']:,.2f}",
                "EMI":                 f"{r['emi']:,.2f}",
                "Interest":            f"{r['interest_portion']:,.2f}",
                "Principal":           f"{r['principal_portion']:,.2f}",
                f"Closing ({_cfg['currency']})":  f"{r['closing_balance']:,.2f}",
                "Cum. Interest":       f"{r['cumulative_interest']:,.2f}",
            } for r in _rows_to_show])
            st.dataframe(_amort_df, hide_index=True, width='stretch', height=400)

            _crossover = next((r for r in _amort_rows if r["principal_portion"] >= r["interest_portion"]), None)
            if _crossover:
                st.caption(f"📍 **Crossover point** — principal portion exceeds interest from **{_crossover['date_label']}** (month {_crossover['month']})")
        else:
            st.info("Amortization schedule will be available once loan enters repayment phase.")

    # ── F. Interest vs Principal Charts ───────────────────────────────────────
    with st.expander("📊 Interest vs Principal Breakdown"):
        if _amort_rows:
            _chart_df = pd.DataFrame({
                "Month":     [r["date_label"]       for r in _amort_rows],
                "Interest":  [r["interest_portion"] for r in _amort_rows],
                "Principal": [r["principal_portion"]for r in _amort_rows],
                "Cum Interest": [r["cumulative_interest"]  for r in _amort_rows],
                "Cum Principal":[r["cumulative_principal"] for r in _amort_rows],
            })
            _fc1, _fc2 = st.columns(2)

            # Stacked bar: EMI split per month (yearly sampling for readability)
            _yearly = _chart_df.iloc[::12]
            _fig_bar = go.Figure()
            _fig_bar.add_trace(go.Bar(name="Interest",  x=_yearly["Month"], y=_yearly["Interest"],  marker_color="#ef4444"))
            _fig_bar.add_trace(go.Bar(name="Principal", x=_yearly["Month"], y=_yearly["Principal"], marker_color="#22c55e"))
            _fig_bar.update_layout(barmode="stack", title="EMI Breakdown (yearly)",
                                   xaxis_title="Year", yaxis_title=_cfg["currency"])
            _fc1.plotly_chart(_fig_bar, width='stretch')

            # Pie: lifetime total
            _total_int_amort  = _amort_rows[-1]["cumulative_interest"]
            _total_princ_amort= _amort_rows[-1]["cumulative_principal"]
            _fig_pie = px.pie(
                values=[_total_princ_amort, _total_int_amort],
                names=["Principal", "Total Interest"],
                color_discrete_sequence=["#22c55e", "#ef4444"],
                title="Lifetime: Principal vs Interest",
                hole=0.4,
            )
            _fc2.plotly_chart(_fig_pie, width='stretch')

            # Running cumulative area chart
            _fig_area = go.Figure()
            _fig_area.add_trace(go.Scatter(name="Cumulative Interest",  x=_chart_df["Month"], y=_chart_df["Cum Interest"],  fill="tozeroy", line_color="#ef4444"))
            _fig_area.add_trace(go.Scatter(name="Cumulative Principal", x=_chart_df["Month"], y=_chart_df["Cum Principal"], fill="tozeroy", line_color="#22c55e"))
            _fig_area.update_layout(title="Cumulative Interest vs Principal Paid",
                                    xaxis_title="Month", yaxis_title=_cfg["currency"])
            st.plotly_chart(_fig_area, width='stretch')

    # ── G. Prepayment Simulator ────────────────────────────────────────────────
    with st.expander("🚀 Prepayment Simulator"):
        st.caption("See how extra payments reduce your total interest and loan tenure.")
        _pp1, _pp2, _pp3 = st.columns(3)
        _extra_monthly = _pp1.number_input(f"Extra Monthly Payment ({_cfg['currency']})", min_value=0.0, value=0.0, step=100.0, key="pp_extra")
        _lump_sum      = _pp2.number_input(f"One-time Lump Sum ({_cfg['currency']})",      min_value=0.0, value=0.0, step=500.0, key="pp_lump")
        _lump_at       = _pp3.number_input("Lump Sum at Month #",  min_value=1, value=1, step=1, key="pp_lump_mo")
        _strategy      = st.radio("Prepayment Strategy",
                                  ["reduce_tenure", "reduce_emi"],
                                  format_func=lambda x: "Reduce Tenure (same EMI, end sooner)" if x == "reduce_tenure" else "Reduce EMI (same tenure, lower monthly)",
                                  horizontal=True, key="pp_strat")

        _rem_months = edu_mod._months_between(_today, _maturity)
        _pp_result  = edu_mod.prepayment_analysis(
            _cur_princ, _cfg["annual_rate"], _rem_months, _calc_emi,
            _extra_monthly, _lump_sum, int(_lump_at), _strategy)

        _bl  = _pp_result["baseline"]
        _sc  = _pp_result["scenario"]
        _sav = _pp_result["savings"]

        _pp_df = pd.DataFrame({
            "Metric": ["Monthly EMI", "Total Interest", "Total Paid", "Loan End", "Cost Multiplier"],
            "Without Prepayment": [
                f"{_cfg['currency']} {_bl['monthly_emi']:,.2f}",
                f"{_cfg['currency']} {_bl['total_interest']:,.2f}",
                f"{_cfg['currency']} {_bl['total_paid']:,.2f}",
                edu_mod._add_months(_today, _bl['months']).strftime("%b %Y"),
                f"{(_bl['total_paid'] / _cfg['disbursed_amount']):.2f}x" if _cfg["disbursed_amount"] else "—",
            ],
            "With Prepayment": [
                f"{_cfg['currency']} {_sc['monthly_emi']:,.2f}",
                f"{_cfg['currency']} {_sc['total_interest']:,.2f}",
                f"{_cfg['currency']} {_sc['total_paid']:,.2f}",
                edu_mod._add_months(_today, _sc['months']).strftime("%b %Y"),
                f"{(_sc['total_paid'] / _cfg['disbursed_amount']):.2f}x" if _cfg["disbursed_amount"] else "—",
            ],
            "Savings": [
                "—",
                f"{_cfg['currency']} {_sav['interest_saved']:,.2f}",
                f"{_cfg['currency']} {_sav['total_saved']:,.2f}",
                f"{_sav['months_saved']} months earlier",
                "—",
            ],
        })
        st.dataframe(_pp_df, hide_index=True, width='stretch')

        if _sav["interest_saved"] > 0:
            st.success(f"💰 Paying **{_cfg['currency']} {_extra_monthly + _lump_sum:,.0f}** extra saves you "
                       f"**{_cfg['currency']} {_sav['interest_saved']:,.2f}** in interest and ends your loan "
                       f"**{_sav['months_saved']} months** sooner!")

    # ── H. Payment History ─────────────────────────────────────────────────────
    if _cfg.get("payments"):
        with st.expander("🧾 Payment History"):
            _ph_rows = []
            _running_bal = float(_cfg["disbursed_amount"]) + float(_cfg["loan_fee_capitalized"])
            for _p in sorted(_cfg["payments"], key=lambda x: x["date"]):
                _ph_rows.append({
                    "Date":   _p["date"],
                    f"Amount ({_cfg['currency']})": f"{float(_p['amount']):,.2f}",
                    "Note": "Token/Prepayment",
                })
            st.dataframe(pd.DataFrame(_ph_rows), hide_index=True, width='stretch')
            st.caption(f"Total paid to date: **{_cfg['currency']} {sum(float(p['amount']) for p in _cfg['payments']):,.2f}**")

    # ── I. Key Insight Cards ───────────────────────────────────────────────────
    st.subheader("💡 Key Insights")
    _ins1, _ins2 = st.columns(2)

    _total_mora_paid_so_far = sum(float(p["amount"]) for p in _cfg.get("payments", []))
    _int_pct = round(_cur_monthly_int / (_cur_monthly_int + 0.001) * 100, 1)

    _ins1.warning(
        f"📛 **The Moratorium Trap**  \n"
        f"You're paying **{_cfg['currency']} {_cfg['token_payment']:,.0f}/mo** but "
        f"**{_cfg['currency']} {_cur_monthly_int:,.2f}/mo** in interest is accruing.  \n"
        f"Monthly shortfall: **{_cfg['currency']} {max(0, _cur_monthly_int - _cfg['token_payment']):,.2f}** "
        f"being added to your debt."
    )
    _ins2.info(
        f"💸 **Daily Cost**  \n"
        f"This loan costs you **{_cfg['currency']} {_daily_int_cost:,.2f} per day** in interest.  \n"
        f"Over a year that's **{_cfg['currency']} {_daily_int_cost * 365:,.2f}** — "
        f"just in interest on the current balance."
    )

    _ins3, _ins4 = st.columns(2)
    _ins3.error(
        f"🔴 **Capitalization Impact**  \n"
        f"At moratorium end, ~**{_cfg['currency']} {_cap_balance:,.2f}** becomes your new principal  \n"
        f"(vs **{_cfg['currency']} {_cfg['disbursed_amount']:,.2f}** originally disbursed).  \n"
        f"You'll pay interest on **{_cfg['currency']} {_cap_balance - _cfg['disbursed_amount']:,.2f}** "
        f"extra that was never cash in your hand."
    )
    _ins4.success(
        f"✅ **Cost Multiplier**  \n"
        f"Total projected repayment: **{_cfg['currency']} {_cost['total_paid']:,.2f}**  \n"
        f"For every **{_cfg['currency']} 1** borrowed, you'll repay **{_cost['cost_multiplier']:.2f}x**.  \n"
        f"Total interest: **{_cfg['currency']} {_cost['total_interest']:,.2f}** "
        f"({_cost['interest_pct']:.0f}% of all payments)."
    )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — FINANCIAL PLAN
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.header("📋 Financial Plan")
    st.caption(
        "Enter your real monthly numbers — every expense category, every EMI. "
        "The plan uses your actual assets and loans to project your financial life."
    )

    # ── Load live DB data ─────────────────────────────────────────────────────
    _portfolio, _, _total_current_usd, _ = asset_mod.get_portfolio_summary()
    _all_loans = db.get_all_loans()
    _active_loans = [l for l in _all_loans if l["remaining_balance"] > 0]

    _loan_emi_rows = []
    for _l in _active_loans:
        _r2u = asset_mod.get_fx_rate_to_usd(_l["currency"])
        _emi_u = float(_l.get("in_school_payment_amt") or _l.get("emi") or 0) * _r2u
        _loan_emi_rows.append({
            "name": _l["name"],
            "emi_usd": _emi_u,
            "currency": _l["currency"],
            "loan_type": _l.get("loan_type", "standard"),
        })
    _db_emi_total_usd = sum(x["emi_usd"] for x in _loan_emi_rows)
    _total_loan_usd = sum(
        _l["remaining_balance"] * asset_mod.get_fx_rate_to_usd(_l["currency"])
        for _l in _active_loans
    )

    # ── Include education loan if configured ──────────────────────────────────
    _edu_cfg_fp = db.get_edu_loan_config()
    if _edu_cfg_fp:
        _edu_r_fp        = asset_mod.get_fx_rate_to_usd(_edu_cfg_fp.get("currency", "USD"))
        _edu_mora_end_fp = date.fromisoformat(_edu_cfg_fp["moratorium_end"])
        _edu_maturity_fp = date.fromisoformat(_edu_cfg_fp["maturity_date"])
        _edu_first_fp    = date.fromisoformat(_edu_cfg_fp["first_disbursement"])
        _edu_in_mora_fp  = date.today() < _edu_mora_end_fp
        _edu_repay_mo_fp = max(1, edu_mod._months_between(_edu_mora_end_fp, _edu_maturity_fp))
        _edu_mora_mo_fp  = edu_mod._months_between(_edu_first_fp, _edu_mora_end_fp)
        _edu_princ_fp    = float(_edu_cfg_fp.get("current_principal") or _edu_cfg_fp.get("disbursed_amount", 0))
        _edu_accrued_fp  = float(_edu_cfg_fp.get("current_accrued", 0))
        # Capitalized balance = what repayment EMI will be based on
        _edu_cap_fp      = edu_mod.capitalize_interest(_edu_princ_fp, _edu_accrued_fp)
        _edu_repay_emi_fp = edu_mod.calculate_emi(_edu_cap_fp, float(_edu_cfg_fp["annual_rate"]), _edu_repay_mo_fp)
        # Display EMI: token payment if in moratorium, repayment EMI otherwise
        _edu_display_emi_fp = float(_edu_cfg_fp.get("token_payment", 0)) if _edu_in_mora_fp else _edu_repay_emi_fp
        _loan_emi_rows.append({
            "name":      f"🎓 {_edu_cfg_fp.get('lender', 'Education Loan')}",
            "emi_usd":   _edu_display_emi_fp * _edu_r_fp,
            "currency":  _edu_cfg_fp.get("currency", "USD"),
            "loan_type": "edu_loan",
        })
        _db_emi_total_usd += _edu_display_emi_fp * _edu_r_fp
        _total_loan_usd   += (_edu_princ_fp + _edu_accrued_fp) * _edu_r_fp

    # ── Session state initialisation ──────────────────────────────────────────
    if "fp_custom_cats" not in st.session_state:
        st.session_state["fp_custom_cats"] = []
    if "fp_custom_emis" not in st.session_state:
        st.session_state["fp_custom_emis"] = []

    # Standard expense categories — (session_key, label, default, step)
    _STD_CATS = [
        ("fp_rent",          "🏠 Rent / Mortgage",               0.0,  50.0),
        ("fp_groceries",     "🛒 Groceries & Household",          0.0,  20.0),
        ("fp_utilities",     "💡 Utilities (electricity/internet)", 0.0, 10.0),
        ("fp_transport",     "🚗 Transportation / Fuel",          0.0,  10.0),
        ("fp_car_emi",       "🚙 Car EMI",                        0.0,  10.0),
        ("fp_insurance",     "🛡️ Insurance (health/life/vehicle)", 0.0, 10.0),
        ("fp_healthcare",    "🏥 Healthcare & Medical",            0.0,  10.0),
        ("fp_entertainment", "🎬 Entertainment & Dining Out",      0.0,  10.0),
        ("fp_subscriptions", "📱 Subscriptions & Apps",           0.0,  5.0),
        ("fp_clothing",      "👕 Clothing & Personal Care",        0.0,  10.0),
        ("fp_education",     "📚 Education / Courses",            0.0,  10.0),
        ("fp_misc",          "📦 Miscellaneous",                  0.0,  10.0),
    ]

    # ── Two-column layout: inputs (left) | live budget summary (right) ────────
    _inp_col, _sum_col = st.columns([3, 1])

    with _inp_col:
        # ── A. Income ─────────────────────────────────────────────────────────
        st.subheader("A. Monthly Income")
        _a1, _a2 = st.columns([3, 1])
        with _a1:
            st.number_input(
                "Monthly Gross Salary",
                min_value=0.0, value=5000.0, step=100.0,
                key="fp_salary",
                help="Gross or take-home — be consistent with how you budget.",
            )
        with _a2:
            st.selectbox("Currency", asset_mod.SUPPORTED_CURRENCIES, key="fp_salary_cur")
        st.number_input(
            "Other Monthly Income (USD)",
            min_value=0.0, value=0.0, step=50.0,
            key="fp_other_income",
            help="Freelance, rental income, dividends, side business, etc.",
        )
        st.divider()

        # ── B. Monthly Expenses ───────────────────────────────────────────────
        st.subheader("B. Monthly Expenses")
        st.caption("All amounts in USD. Enter 0 for categories that don't apply to you.")
        _bc1, _bc2 = st.columns(2)
        for _idx, (_key, _lbl, _def, _stp) in enumerate(_STD_CATS):
            _col = _bc1 if _idx % 2 == 0 else _bc2
            _col.number_input(_lbl, min_value=0.0, value=_def, step=_stp, key=_key)

        # Custom expense categories
        if st.session_state["fp_custom_cats"]:
            st.markdown("**Custom Expense Categories**")
        _cats_to_remove = []
        for _ci, _cat in enumerate(st.session_state["fp_custom_cats"]):
            _cn1, _cn2, _cn3 = st.columns([2, 1, 0.4])
            _new_name = _cn1.text_input(
                "Name", value=_cat["name"],
                key=f"fp_cc_name_{_ci}", label_visibility="collapsed",
                placeholder="e.g. Pet care"
            )
            _new_amt = _cn2.number_input(
                "Amount", min_value=0.0, value=float(_cat["amount"]), step=10.0,
                key=f"fp_cc_amt_{_ci}", label_visibility="collapsed",
            )
            _cn3.write("")
            if _cn3.button("✕", key=f"fp_rm_cc_{_ci}"):
                _cats_to_remove.append(_ci)
            else:
                st.session_state["fp_custom_cats"][_ci]["name"] = _new_name
                st.session_state["fp_custom_cats"][_ci]["amount"] = _new_amt
        for _ci in reversed(_cats_to_remove):
            st.session_state["fp_custom_cats"].pop(_ci)
        if _cats_to_remove:
            st.rerun()

        if st.button("➕ Add Expense Category", key="fp_add_cat"):
            st.session_state["fp_custom_cats"].append({"name": "Other", "amount": 0.0})
            st.rerun()
        st.divider()

        # ── C. EMIs ───────────────────────────────────────────────────────────
        st.subheader("C. Loan EMIs")
        if _loan_emi_rows:
            st.caption(
                "These are pulled automatically from your **🏦 Loans** tab and included "
                "in the simulation. No need to enter them again."
            )
            for _x in _loan_emi_rows:
                _badge = {"leap_finance": "🎓", "prodigy_finance": "🌍",
                          "sofi": "🇺🇸", "simple_emi": "💳",
                          "edu_loan": "🎓"}.get(_x["loan_type"], "🏠")
                st.markdown(
                    f"{_badge} **{_x['name']}** — "
                    f"USD {_x['emi_usd']:,.2f} / month (auto-included)"
                )
        else:
            st.info("No active loans in the system. Add them under 🏦 Loans to include them here.")

        st.markdown("**Other EMIs not tracked in this app** *(credit card instalments, informal loans, etc.)*")
        _emis_to_remove = []
        for _ei, _emi in enumerate(st.session_state["fp_custom_emis"]):
            _en1, _en2, _en3 = st.columns([2, 1, 0.4])
            _new_ename = _en1.text_input(
                "Name", value=_emi["name"],
                key=f"fp_ce_name_{_ei}", label_visibility="collapsed",
                placeholder="e.g. Credit card EMI"
            )
            _new_eamt = _en2.number_input(
                "Amount (USD/mo)", min_value=0.0, value=float(_emi["amount"]), step=10.0,
                key=f"fp_ce_amt_{_ei}", label_visibility="collapsed",
            )
            _en3.write("")
            if _en3.button("✕", key=f"fp_rm_ce_{_ei}"):
                _emis_to_remove.append(_ei)
            else:
                st.session_state["fp_custom_emis"][_ei]["name"] = _new_ename
                st.session_state["fp_custom_emis"][_ei]["amount"] = _new_eamt
        for _ei in reversed(_emis_to_remove):
            st.session_state["fp_custom_emis"].pop(_ei)
        if _emis_to_remove:
            st.rerun()

        if st.button("➕ Add Untracked EMI", key="fp_add_emi"):
            st.session_state["fp_custom_emis"].append({"name": "Other EMI", "amount": 0.0})
            st.rerun()
        st.divider()

        # ── D. Investment & Assumptions ───────────────────────────────────────
        st.subheader("D. Investment & Growth Assumptions")
        _d1, _d2 = st.columns(2)
        with _d1:
            st.number_input(
                "Monthly Investment Target (USD)",
                min_value=0.0, value=500.0, step=50.0,
                key="fp_investment",
                help="Amount you plan to park in stocks / MFs / SIPs each month from savings.",
            )
            st.slider(
                "Annual Asset Growth Rate (%)", 0, 25, 10,
                key="fp_asset_growth",
                help="Expected portfolio return. Global equities long-run avg ≈ 8–12%.",
            )
        with _d2:
            st.radio(
                "Projection Horizon (years)",
                [5, 10, 15, 20], index=1,
                key="fp_years", horizontal=True,
            )
            st.slider(
                "Annual Salary Growth Rate (%)", 0, 20, 5,
                key="fp_salary_growth",
                help="Expected annual raise. Typical corporate range: 3–8%.",
            )

    # ── Live budget summary (right panel) ─────────────────────────────────────
    with _sum_col:
        # Read live values from session state
        _s_sal   = float(st.session_state.get("fp_salary", 5000))
        _s_cur   = str(st.session_state.get("fp_salary_cur", "USD"))
        _s_other = float(st.session_state.get("fp_other_income", 0))
        _s_inv   = float(st.session_state.get("fp_investment", 500))

        _sal_usd_live = _s_sal * asset_mod.get_fx_rate_to_usd(_s_cur)
        _total_income_live = _sal_usd_live + _s_other

        _fixed_exp_live = sum(float(st.session_state.get(k, 0)) for k, *_ in _STD_CATS)
        _custom_exp_live = sum(float(c.get("amount", 0)) for c in st.session_state["fp_custom_cats"])
        _custom_emi_live = sum(float(e.get("amount", 0)) for e in st.session_state["fp_custom_emis"])
        _total_exp_live = _fixed_exp_live + _custom_exp_live
        _total_emi_live = _db_emi_total_usd + _custom_emi_live
        _total_out_live = _total_exp_live + _total_emi_live + _s_inv
        _remaining_live = _total_income_live - _total_out_live

        st.subheader("📊 Live Budget")
        st.metric("💰 Income", f"${_total_income_live:,.0f}")
        st.metric("🏠 Expenses", f"${_total_exp_live:,.0f}",
                  delta=f"{_total_exp_live/_total_income_live*100:.0f}% of income" if _total_income_live else None,
                  delta_color="off")
        st.metric("💳 All EMIs", f"${_total_emi_live:,.0f}",
                  delta=f"{_total_emi_live/_total_income_live*100:.0f}% of income" if _total_income_live else None,
                  delta_color="inverse" if _total_income_live and _total_emi_live / _total_income_live > 0.4 else "off")
        st.metric("📈 Investment", f"${_s_inv:,.0f}")
        st.divider()

        _rem_pct = f"{_remaining_live / _total_income_live * 100:.1f}%" if _total_income_live else "—"
        st.metric(
            "🟢 Surplus" if _remaining_live >= 0 else "🔴 Deficit",
            f"${_remaining_live:,.0f}",
            delta=_rem_pct,
            delta_color="normal" if _remaining_live >= 0 else "inverse",
        )
        if _remaining_live < 0:
            st.error("Outflow exceeds income!")
        elif _total_income_live > 0 and _remaining_live / _total_income_live < 0.05:
            st.warning("Very thin buffer (<5%)")
        elif _total_income_live > 0 and _remaining_live / _total_income_live >= 0.2:
            st.success("Healthy buffer ≥20%")

        st.divider()
        st.caption("**Your current situation:**")
        st.caption(f"Portfolio: **${_total_current_usd:,.0f}**")
        st.caption(f"Total Loans: **${_total_loan_usd:,.0f}**")
        _nw_now = _total_current_usd - _total_loan_usd
        st.caption(
            f"Net Worth: **{'🟢' if _nw_now >= 0 else '🔴'} ${_nw_now:,.0f}**"
        )

    # ── Generate Plan button ───────────────────────────────────────────────────
    st.divider()
    _gen_c1, _gen_c2, _gen_c3 = st.columns([2, 1, 2])
    _gen_clicked = _gen_c2.button(
        "🚀 Generate My Financial Plan",
        type="primary",
        width='stretch',
    )

    if _gen_clicked:
        _sal_final   = float(st.session_state.get("fp_salary", 5000))
        _cur_final   = str(st.session_state.get("fp_salary_cur", "USD"))
        _other_final = float(st.session_state.get("fp_other_income", 0))
        _inv_final   = float(st.session_state.get("fp_investment", 500))
        _ag_final    = float(st.session_state.get("fp_asset_growth", 10))
        _sg_final    = float(st.session_state.get("fp_salary_growth", 5))
        _yr_final    = int(st.session_state.get("fp_years", 10))

        _sal_usd_f   = _sal_final * asset_mod.get_fx_rate_to_usd(_cur_final)
        _income_f    = _sal_usd_f + _other_final

        _fixed_f     = sum(float(st.session_state.get(k, 0)) for k, *_ in _STD_CATS)
        _ccat_f      = sum(float(c.get("amount", 0)) for c in st.session_state["fp_custom_cats"])
        _cemi_f      = sum(float(e.get("amount", 0)) for e in st.session_state["fp_custom_emis"])
        # Non-loan expenses only — DB loans are tracked separately by the engine
        _monthly_exp_f = _fixed_f + _ccat_f + _cemi_f

        _issues = projections.validate_inputs(
            _income_f, _monthly_exp_f + _db_emi_total_usd,
            _inv_final, _ag_final, _sg_final, _yr_final,
        )
        _has_err = any(i["level"] == "error" for i in _issues)
        for _iss in _issues:
            {"error": st.error, "warning": st.warning, "info": st.info}[_iss["level"]](
                f"{'❌' if _iss['level'] == 'error' else '⚠️'} {_iss['message']}"
            )

        if not _has_err:
            _loans_proj = []
            for _l in _active_loans:
                _r = asset_mod.get_fx_rate_to_usd(_l["currency"])
                _loans_proj.append({
                    **_l,
                    "remaining_balance": _l["remaining_balance"] * _r,
                    "emi": float(_l.get("emi") or 0) * _r,
                    "in_school_payment_amt": float(_l.get("in_school_payment_amt") or 0) * _r,
                })

            # Add education loan to projection engine
            if _edu_cfg_fp:
                _loans_proj.append({
                    "id":                    -999,
                    "name":                  f"{_edu_cfg_fp.get('lender', 'Education Loan')} (Education)",
                    "currency":              _edu_cfg_fp.get("currency", "USD"),
                    "remaining_balance":     (_edu_princ_fp + _edu_accrued_fp) * _edu_r_fp,
                    "emi":                   _edu_repay_emi_fp * _edu_r_fp,
                    "in_school_payment_amt": float(_edu_cfg_fp.get("token_payment", 0)) * _edu_r_fp,
                    "in_school_payment_type": "partial",
                    "interest_rate":         float(_edu_cfg_fp["annual_rate"]),
                    "start_date":            _edu_cfg_fp["first_disbursement"],
                    "moratorium_months":     _edu_mora_mo_fp,
                    "tenure_months":         _edu_repay_mo_fp,
                    "loan_type":             "edu_loan",
                })

            with st.spinner("Running simulation…"):
                _rows_r, _miles_r, _hist_r = projections.project_finances(
                    current_assets_usd=_total_current_usd,
                    loans=_loans_proj,
                    monthly_salary_usd=_income_f,
                    monthly_expenses_usd=_monthly_exp_f,
                    monthly_investment_usd=_inv_final,
                    annual_asset_growth_rate=_ag_final,
                    annual_salary_growth_rate=_sg_final,
                    years=_yr_final,
                )

            # Build expense breakdown for donut chart
            _exp_breakdown = {
                "Rent/Mortgage":    float(st.session_state.get("fp_rent", 0)),
                "Groceries":        float(st.session_state.get("fp_groceries", 0)),
                "Utilities":        float(st.session_state.get("fp_utilities", 0)),
                "Transport/Fuel":   float(st.session_state.get("fp_transport", 0)),
                "Car EMI":          float(st.session_state.get("fp_car_emi", 0)),
                "Insurance":        float(st.session_state.get("fp_insurance", 0)),
                "Healthcare":       float(st.session_state.get("fp_healthcare", 0)),
                "Entertainment":    float(st.session_state.get("fp_entertainment", 0)),
                "Subscriptions":    float(st.session_state.get("fp_subscriptions", 0)),
                "Clothing":         float(st.session_state.get("fp_clothing", 0)),
                "Education":        float(st.session_state.get("fp_education", 0)),
                "Misc":             float(st.session_state.get("fp_misc", 0)),
            }
            for _cc in st.session_state["fp_custom_cats"]:
                if float(_cc.get("amount", 0)) > 0:
                    _exp_breakdown[_cc["name"]] = float(_cc["amount"])
            for _ce in st.session_state["fp_custom_emis"]:
                if float(_ce.get("amount", 0)) > 0:
                    _exp_breakdown[_ce["name"] + " (EMI)"] = float(_ce["amount"])
            for _x in _loan_emi_rows:
                if _x["emi_usd"] > 0:
                    _exp_breakdown[_x["name"] + " (auto)"] = _x["emi_usd"]
            _exp_breakdown["Investment"] = _inv_final

            st.session_state.update({
                "fp_rows":       _rows_r,
                "fp_milestones": _miles_r,
                "fp_loan_history": _hist_r,
                "fp_income_usd": _income_f,
                "fp_salary_usd": _sal_usd_f,
                "fp_expenses_usd": _monthly_exp_f,
                "fp_all_emis_usd": _db_emi_total_usd + _cemi_f,
                "fp_investment_usd": _inv_final,
                "fp_exp_breakdown": _exp_breakdown,
                "fp_rent_usd": float(st.session_state.get("fp_rent", 0)),
            })

    # ── Results ───────────────────────────────────────────────────────────────
    if "fp_rows" not in st.session_state:
        st.info(
            "👆 Fill in your income and expenses above, then click "
            "**Generate My Financial Plan** to see your personalised projection."
        )
    else:
        fp_rows         = st.session_state["fp_rows"]
        fp_milestones   = st.session_state["fp_milestones"]
        fp_loan_history = st.session_state["fp_loan_history"]
        fp_income_usd   = st.session_state.get("fp_income_usd", 0.0)
        fp_expenses_usd = st.session_state.get("fp_expenses_usd", 0.0)
        fp_all_emis_usd = st.session_state.get("fp_all_emis_usd", 0.0)
        fp_invest_usd   = st.session_state.get("fp_investment_usd", 0.0)
        fp_exp_bdown    = st.session_state.get("fp_exp_breakdown", {})
        fp_rent_usd     = st.session_state.get("fp_rent_usd", 0.0)

        _total_monthly_out = fp_expenses_usd + fp_all_emis_usd + fp_invest_usd
        _surplus = fp_income_usd - _total_monthly_out

        # Display currency
        fp_disp_cur = st.selectbox(
            "Display currency for results",
            asset_mod.SUPPORTED_CURRENCIES,
            key="fp_disp_cur",
        )
        _dr = asset_mod.get_usd_to_currency_rate(fp_disp_cur)
        _D = lambda v: v * _dr   # USD → display currency

        st.divider()

        # ── Health Scorecard ──────────────────────────────────────────────────
        st.subheader("💊 Financial Health Scorecard")
        sc = projections.health_scorecard(
            fp_income_usd,
            fp_expenses_usd,
            fp_all_emis_usd,
            _total_current_usd,
            _total_loan_usd,
        )

        hc1, hc2, hc3, hc4 = st.columns(4)
        _sr = sc.get("savings_rate")
        hc1.metric("Savings Rate",
                   f"{_sr:.1f}%" if _sr is not None else "N/A",
                   help="(Income − Expenses − EMIs) / Income")

        _eti = sc.get("emi_to_income_pct")
        hc2.metric("EMI-to-Income",
                   f"{_eti:.1f}%" if _eti is not None else "N/A",
                   delta="Over 40% limit!" if (_eti or 0) > 40 else "OK",
                   delta_color="inverse" if (_eti or 0) > 40 else "normal",
                   help="Keep below 40% — lenders and financial planners use this threshold.")

        _dti = sc.get("debt_to_income")
        hc3.metric("Debt-to-Income",
                   f"{_dti:.2f}×" if _dti is not None else "N/A",
                   delta="High" if (_dti or 0) > 5 else ("Moderate" if (_dti or 0) > 3 else "Healthy"),
                   delta_color="inverse" if (_dti or 0) > 5 else ("off" if (_dti or 0) > 3 else "normal"),
                   help="Total loans ÷ annual income. Below 3× is healthy.")

        _fi_p = sc.get("fi_progress_pct")
        _fi_t = sc.get("fi_target_usd")
        hc4.metric("FI Progress",
                   f"{_fi_p:.1f}%" if _fi_p is not None else "N/A",
                   help=f"4% rule: need {fp_disp_cur} {_D(_fi_t):,.0f}" if _fi_t else "")

        # ── Personalised recommendations ──────────────────────────────────────
        _recs = []
        if _eti and _eti > 40:
            _recs.append(("🔴", f"Your EMI-to-income ratio is **{_eti:.1f}%** — above the safe 40% ceiling. "
                          "Consider prepaying the highest-rate loan first to free up cash flow."))
        if _sr is not None and _sr < 10:
            _recs.append(("🔴", f"Your savings rate is only **{_sr:.1f}%**. Target at least 20%. "
                          "Review your top 3 spending categories for cuts."))
        if fp_income_usd > 0 and fp_rent_usd / fp_income_usd > 0.35:
            _recs.append(("⚠️", f"Housing eats **{fp_rent_usd/fp_income_usd*100:.0f}%** of your income "
                          "(recommended ≤ 30%). This is your biggest lever to improve savings."))
        _emerg = sc.get("emergency_months")
        if _emerg is not None and _emerg < 3:
            _recs.append(("⚠️", f"Your emergency fund covers only **{_emerg:.1f} months** of expenses. "
                          "Build it to at least 6 months before increasing investments."))
        elif _emerg is not None and _emerg < 6:
            _recs.append(("💡", f"Emergency fund covers **{_emerg:.1f} months** — good start, "
                          "but aim for 6 months before aggressively investing."))
        if _surplus < 0:
            _recs.append(("🔴", "Your total outflows exceed your income. "
                          "Cut discretionary spending or increase income before investing."))
        elif fp_income_usd > 0 and fp_invest_usd / fp_income_usd < 0.10:
            _recs.append(("💡", f"You're investing **{fp_invest_usd/fp_income_usd*100:.0f}%** of income. "
                          "Work towards the 20% rule once your debt load eases."))
        if _dti and _dti > 5:
            _recs.append(("🔴", f"Debt-to-income ratio of **{_dti:.1f}×** is very high. "
                          "Focus on aggressive loan prepayment before taking on new debt."))
        if not _recs:
            _recs.append(("✅", "Your financial ratios look healthy. Stay consistent with your investment plan!"))

        with st.expander("📋 Personalised Recommendations", expanded=True):
            for _icon, _msg in _recs:
                st.markdown(f"{_icon} {_msg}")

        st.divider()

        # ── Budget donut + expense table ──────────────────────────────────────
        st.subheader("🥧 Where Your Money Goes")
        _donut_data = [{"category": k, "amount": v}
                       for k, v in fp_exp_bdown.items() if v > 0]
        if _donut_data:
            _donut_df = pd.DataFrame(_donut_data)
            _dc1, _dc2 = st.columns([2, 1])
            with _dc1:
                _fig_donut = px.pie(
                    _donut_df, names="category", values="amount",
                    hole=0.45, height=320,
                )
                _fig_donut.update_traces(textposition="inside", textinfo="percent+label")
                _fig_donut.update_layout(showlegend=False, margin=dict(t=10, b=10))
                st.plotly_chart(_fig_donut, width='stretch')
            with _dc2:
                st.markdown("**Monthly breakdown**")
                for _row in sorted(_donut_data, key=lambda x: -x["amount"]):
                    _pct = _row["amount"] / fp_income_usd * 100 if fp_income_usd else 0
                    st.markdown(
                        f"**{_row['category']}** — "
                        f"{fp_disp_cur} {_D(_row['amount']):,.0f} "
                        f"*({_pct:.1f}%)*"
                    )
                st.markdown("---")
                _total_shown = sum(r["amount"] for r in _donut_data)
                st.markdown(f"**Total outflow** — {fp_disp_cur} {_D(_total_shown):,.0f}")
                st.markdown(f"**Income** — {fp_disp_cur} {_D(fp_income_usd):,.0f}")
                _surp_disp = _D(fp_income_usd - _total_shown)
                st.markdown(
                    f"**{'Surplus' if _surp_disp >= 0 else 'Deficit'}** — "
                    f"{'🟢' if _surp_disp >= 0 else '🔴'} {fp_disp_cur} {_surp_disp:,.0f}"
                )

        st.divider()

        # ── Key Milestones ────────────────────────────────────────────────────
        st.subheader("🏁 Key Milestones")
        with st.container(border=True):
            _mc1, _mc2, _mc3 = st.columns(3)
            _mc1.metric(
                "Debt-Free Date",
                fp_milestones.get("debt_free_date") or ("✅ No loans" if not _active_loans else "Beyond horizon"),
            )
            _mc2.metric(
                "Net Worth Turns Positive",
                fp_milestones.get("positive_networth_date") or "Beyond horizon",
            )
            _mc3.metric(
                "Financial Independence",
                fp_milestones.get("fi_date") or "Beyond horizon",
                help="Month passive income (4% rule) ≥ monthly expenses",
            )

            _nw_snaps = {}
            for _yr in [1, 5, 10]:
                _idx = _yr * 12 - 1
                if _idx < len(fp_rows):
                    _nw_snaps[_yr] = fp_rows[_idx]["net_worth_usd"]
            if _nw_snaps:
                st.markdown("**Projected Net Worth Snapshots**")
                _snap_cols = st.columns(len(_nw_snaps))
                for _si, (_yr, _nw) in enumerate(_nw_snaps.items()):
                    _snap_cols[_si].metric(
                        f"Year {_yr} ({fp_disp_cur})",
                        f"{_D(_nw):,.0f}",
                        delta=f"{'▲' if _nw > (_total_current_usd - _total_loan_usd) else '▼'} vs today",
                        delta_color="normal" if _nw > (_total_current_usd - _total_loan_usd) else "inverse",
                    )

        st.divider()

        # ── Net Worth & Assets vs Loans charts ───────────────────────────────
        st.subheader("📈 Projections")
        _df = pd.DataFrame(fp_rows)
        _dates = _df["date_label"]

        _ch1, _ch2 = st.columns(2)
        with _ch1:
            st.markdown("**Net Worth Over Time**")
            _nw_d = _df["net_worth_usd"] * _dr
            _fig_nw = go.Figure()
            _fig_nw.add_trace(go.Scatter(
                x=_dates, y=_nw_d.clip(lower=0),
                fill="tozeroy", fillcolor="rgba(46,204,113,0.25)",
                line=dict(color="#2ecc71", width=2), name="Net Worth (+)",
                hovertemplate="%{x}<br>" + fp_disp_cur + " %{y:,.0f}<extra></extra>",
            ))
            _fig_nw.add_trace(go.Scatter(
                x=_dates, y=_nw_d.clip(upper=0),
                fill="tozeroy", fillcolor="rgba(231,76,60,0.25)",
                line=dict(color="#e74c3c", width=2), name="Net Worth (−)",
                hovertemplate="%{x}<br>" + fp_disp_cur + " %{y:,.0f}<extra></extra>",
            ))
            _fig_nw.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            _fig_nw.update_layout(
                showlegend=False,
                yaxis_title=f"Net Worth ({fp_disp_cur})",
                xaxis=dict(tickangle=-45, nticks=10),
                height=350, margin=dict(t=10),
            )
            st.plotly_chart(_fig_nw, width='stretch')

        with _ch2:
            st.markdown("**Assets vs Loans Over Time**")
            _fig_av = go.Figure()
            _fig_av.add_trace(go.Scatter(
                x=_dates, y=_df["total_assets_usd"] * _dr,
                name="Assets", line=dict(color="#2ecc71", width=2),
                hovertemplate="%{x}<br>Assets " + fp_disp_cur + " %{y:,.0f}<extra></extra>",
            ))
            _fig_av.add_trace(go.Scatter(
                x=_dates, y=_df["total_loan_usd"] * _dr,
                name="Loans", line=dict(color="#e74c3c", width=2),
                hovertemplate="%{x}<br>Loans " + fp_disp_cur + " %{y:,.0f}<extra></extra>",
            ))
            _fig_av.update_layout(
                yaxis_title=f"Value ({fp_disp_cur})",
                xaxis=dict(tickangle=-45, nticks=10),
                legend=dict(orientation="h", y=1.05),
                height=350, margin=dict(t=10),
            )
            st.plotly_chart(_fig_av, width='stretch')

        st.divider()

        # ── Loan Payoff Timeline ──────────────────────────────────────────────
        _active_hist = {
            n: b for n, b in fp_loan_history.items() if b and max(b) > 0.01
        }
        if _active_hist:
            st.subheader("💳 Loan Payoff Timeline")
            _fig_lp = go.Figure()
            for _ln, _bals in _active_hist.items():
                _months = list(range(1, len(_bals) + 1))
                _fig_lp.add_trace(go.Scatter(
                    x=_months, y=[b * _dr for b in _bals],
                    name=_ln, mode="lines",
                    hovertemplate="Month %{x}<br>" + fp_disp_cur + " %{y:,.0f}<extra></extra>",
                ))
                _po = next((i for i, b in enumerate(_bals) if b <= 0.01), None)
                if _po is not None:
                    _fig_lp.add_trace(go.Scatter(
                        x=[_months[_po]], y=[0], mode="markers",
                        marker=dict(size=13, symbol="star", color="gold",
                                    line=dict(color="black", width=1)),
                        showlegend=False,
                        hovertemplate=f"{_ln} paid off — month {_months[_po]}<extra></extra>",
                    ))
            _fig_lp.update_layout(
                xaxis_title="Month from today",
                yaxis_title=f"Remaining Balance ({fp_disp_cur})",
                legend=dict(orientation="h", y=1.05),
                height=380, margin=dict(t=10),
            )
            st.plotly_chart(_fig_lp, width='stretch')
            st.divider()

        # ── Annual Cash Flow Breakdown ────────────────────────────────────────
        st.subheader("📊 Annual Cash Flow Breakdown")
        _df["year_num"] = (_df["month"] - 1) // 12 + 1
        _yearly = _df.groupby("year_num").agg(
            salary_usd    =("salary_usd",      "sum"),
            expenses_usd  =("expenses_usd",    "sum"),
            emi_total_usd =("emi_total_usd",   "sum"),
            investment_usd=("investment_usd",  "sum"),
            savings_usd   =("savings_usd",     "sum"),
        ).reset_index()

        _fig_cf = go.Figure()
        _fig_cf.add_bar(name="Expenses",  x=_yearly["year_num"],
                        y=_yearly["expenses_usd"] * _dr,   marker_color="#e74c3c")
        _fig_cf.add_bar(name="EMIs",      x=_yearly["year_num"],
                        y=_yearly["emi_total_usd"] * _dr,  marker_color="#f39c12")
        _fig_cf.add_bar(name="Investment",x=_yearly["year_num"],
                        y=_yearly["investment_usd"] * _dr, marker_color="#3498db")
        _fig_cf.add_bar(name="Savings",   x=_yearly["year_num"],
                        y=_yearly["savings_usd"].clip(lower=0) * _dr, marker_color="#2ecc71")
        _fig_cf.add_trace(go.Scatter(
            x=_yearly["year_num"], y=_yearly["salary_usd"] * _dr,
            name="Income", mode="lines+markers",
            line=dict(color="white", dash="dot", width=1.5),
        ))
        _fig_cf.update_layout(
            barmode="stack",
            xaxis_title="Year",
            yaxis_title=f"Annual Amount ({fp_disp_cur})",
            legend=dict(orientation="h", y=1.05),
            height=420, margin=dict(t=10),
        )
        st.plotly_chart(_fig_cf, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.header("Settings")

    st.subheader("Email Reminders")
    st.caption("Use a Gmail account. Generate an **App Password** at myaccount.google.com → Security → 2-Step → App Passwords.")

    with st.form("settings_form"):
        col1, col2 = st.columns(2)
        with col1:
            email_sender   = st.text_input("Gmail Sender Address",
                                            value=db.get_setting("email_sender"),
                                            placeholder="you@gmail.com")
            email_password = st.text_input("Gmail App Password",
                                            value=db.get_setting("email_password"),
                                            type="password")
            email_receiver = st.text_input("Reminder To (email)",
                                            value=db.get_setting("email_receiver"),
                                            placeholder="you@gmail.com")
        with col2:
            reminder_day = st.number_input("Reminder Day of Month",
                                            min_value=1, max_value=28,
                                            value=int(db.get_setting("reminder_day", "1")))
            price_hour   = st.number_input("Price Refresh Hour (24h)",
                                            min_value=0, max_value=23,
                                            value=int(db.get_setting("price_update_hour", "18")))
            price_minute = st.number_input("Price Refresh Minute",
                                            min_value=0, max_value=59,
                                            value=int(db.get_setting("price_update_minute", "0")))

        if st.form_submit_button("Save Settings", type="primary"):
            db.save_setting("email_sender",        email_sender)
            db.save_setting("email_password",      email_password)
            db.save_setting("email_receiver",      email_receiver)
            db.save_setting("reminder_day",        str(reminder_day))
            db.save_setting("price_update_hour",   str(price_hour))
            db.save_setting("price_update_minute", str(price_minute))
            st.success("Settings saved! Restart the app to apply scheduler changes.")

    st.divider()
    st.subheader("Test Notifications")
    if st.button("Send Test Email + Desktop Notification"):
        sender   = db.get_setting("email_sender")
        password = db.get_setting("email_password")
        receiver = db.get_setting("email_receiver")
        notifier.desktop_notify("Finance Tracker", "Test notification working!")
        ok = notifier.send_email(sender, password, receiver,
                                 "Finance Tracker — Test",
                                 "This is a test email from your Finance Tracker.")
        if ok:
            st.success("Email sent and desktop notification triggered.")
        else:
            st.warning("Desktop notification sent. Email failed — check your credentials.")

    st.divider()
    st.subheader("Manual Triggers")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Refresh All Prices Now"):
            with st.spinner("Fetching..."):
                results = asset_mod.refresh_all_prices()
            st.success(f"Updated {len(results)} assets.")
    with col2:
        if st.button("Send Loan Reminder Now"):
            loans    = db.get_all_loans()
            active   = [l for l in loans if l["remaining_balance"] > 0]
            sender   = db.get_setting("email_sender")
            password = db.get_setting("email_password")
            receiver = db.get_setting("email_receiver")
            notifier.send_loan_reminder(active, sender, password, receiver)
            st.success("Reminder sent!")
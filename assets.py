"""
Asset price fetching via yfinance.
US stocks  : AAPL, TSLA, MSFT ...
NSE stocks : RELIANCE.NS, TCS.NS, INFY.NS ...
BSE stocks : RELIANCE.BO, TCS.BO ...
Crypto     : BTC-USD, ETH-USD ...
"""

from datetime import date
import yfinance as yf
import db

# In-memory FX cache so we don't hammer Yahoo Finance on every rerun
_fx_cache: dict[str, float] = {}

SUPPORTED_CURRENCIES = ["USD", "INR", "CAD", "AED", "EUR", "GBP", "SGD", "AUD"]

# Commodity symbols supported natively via yfinance
# Maps display name → (yfinance symbol, price unit, grams per price unit)
COMMODITIES = {
    "Gold":     ("GC=F",  "troy oz",  31.1035),
    "Silver":   ("SI=F",  "troy oz",  31.1035),
    "Platinum": ("PL=F",  "troy oz",  31.1035),
    "Palladium":("PA=F",  "troy oz",  31.1035),
    "Crude Oil":("CL=F",  "barrel",   None),
    "Natural Gas":("NG=F","mmBtu",    None),
}

TROY_OZ_PER_GRAM = 1 / 31.1035   # grams → troy oz conversion

# Standard bar / coin denominations for physical metals.
# Each entry: (display label, weight in grams).  None = user enters custom weight.
PHYSICAL_METAL_DENOMINATIONS: dict[str, list[tuple[str, float | None]]] = {
    "Gold": [
        ("1g bar",                   1.0),
        ("2g bar",                   2.0),
        ("2.5g bar",                 2.5),
        ("5g bar",                   5.0),
        ("8g — 1 Sovereign (Indian)", 8.0),
        ("10g bar",                  10.0),
        ("11.66g — 1 Tola (Indian)", 11.664),
        ("20g bar",                  20.0),
        ("50g bar",                  50.0),
        ("1 oz bar / coin (31.1g)",  31.1035),
        ("100g bar",                 100.0),
        ("250g bar",                 250.0),
        ("500g bar",                 500.0),
        ("1 kg bar (1000g)",         1000.0),
        ("Custom weight",            None),
    ],
    "Silver": [
        ("1 oz coin (31.1g)",        31.1035),
        ("5 oz bar (155.5g)",        155.517),
        ("10 oz bar (311g)",         311.035),
        ("100 oz bar (3.11 kg)",     3110.35),
        ("1 kg bar (1000g)",         1000.0),
        ("Custom weight",            None),
    ],
    "Platinum": [
        ("1 oz bar / coin (31.1g)",  31.1035),
        ("10g bar",                  10.0),
        ("50g bar",                  50.0),
        ("100g bar",                 100.0),
        ("Custom weight",            None),
    ],
    "Palladium": [
        ("1 oz bar / coin (31.1g)",  31.1035),
        ("100g bar",                 100.0),
        ("Custom weight",            None),
    ],
}


def get_fx_rate_to_usd(currency: str) -> float:
    """
    Return real-time rate: how many USD = 1 unit of `currency`.
    e.g. INR -> ~0.012,  EUR -> ~1.08,  USD -> 1.0
    Uses Yahoo Finance forex tickers ({CURRENCY}USD=X).
    Falls back to last cached value, then 1.0 if completely unavailable.
    """
    currency = currency.upper()
    if currency == "USD":
        return 1.0

    ticker_sym = f"{currency}USD=X"
    try:
        hist = yf.Ticker(ticker_sym).history(period="2d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            _fx_cache[currency] = rate
            return rate
    except Exception:
        pass

    return _fx_cache.get(currency, 1.0)


def get_usd_to_currency_rate(target: str) -> float:
    """
    Return real-time rate: how many units of `target` = 1 USD.
    e.g. INR -> ~84,  CAD -> ~1.36,  USD -> 1.0
    Uses Yahoo Finance forex tickers (USD{TARGET}=X).
    """
    target = target.upper()
    if target == "USD":
        return 1.0

    cache_key = f"USD_{target}"
    ticker_sym = f"USD{target}=X"
    try:
        hist = yf.Ticker(ticker_sym).history(period="2d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            _fx_cache[cache_key] = rate
            return rate
    except Exception:
        pass

    return _fx_cache.get(cache_key, 1.0)


def convert_from_usd(amount_usd: float, target_currency: str) -> float:
    """Convert a USD amount to any target currency."""
    return amount_usd * get_usd_to_currency_rate(target_currency)


def fetch_current_price(symbol: str) -> float | None:
    """Return the latest closing price for a symbol, or None on failure."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def fetch_symbol_info(symbol: str) -> dict:
    """Return basic metadata: longName, currency."""
    try:
        info = yf.Ticker(symbol).info
        return {
            "name": info.get("longName") or info.get("shortName") or symbol,
            "currency": info.get("currency", "USD"),
        }
    except Exception:
        return {"name": symbol, "currency": "USD"}


def refresh_all_prices():
    """Fetch today's price for every asset and store in asset_prices."""
    assets = db.get_all_assets()
    today = str(date.today())
    results = []
    for asset in assets:
        price = fetch_current_price(asset["symbol"])
        if price is not None:
            db.upsert_price(asset["id"], today, price)
            results.append((asset["symbol"], price))
    return results


def fetch_analyst_data(symbol: str) -> dict:
    """
    Fetch analyst price targets, recommendation, 52W range, and valuation
    multiples for a symbol.  Returns an empty dict on failure or if data is
    unavailable (commodities, crypto, unlisted assets).

    Keys returned (all optional — may be None):
        target_mean, target_high, target_low  : analyst price targets (native currency)
        recommendation : "buy" | "strong_buy" | "hold" | "sell" | "strong_sell" | None
        num_analysts   : number of covering analysts
        week52_high, week52_low : 52-week price range
        trailing_pe, forward_pe : P/E ratios
        price_to_book  : P/B ratio
        upside_pct     : (target_mean / current_price - 1) * 100  (None if unavailable)
    """
    try:
        info = yf.Ticker(symbol).info
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        target_mean = info.get("targetMeanPrice")
        upside = (
            round((target_mean / current - 1) * 100, 1)
            if (target_mean and current and current > 0)
            else None
        )
        return {
            "target_mean":   target_mean,
            "target_high":   info.get("targetHighPrice"),
            "target_low":    info.get("targetLowPrice"),
            "recommendation": info.get("recommendationKey"),
            "num_analysts":  info.get("numberOfAnalystOpinions"),
            "week52_high":   info.get("fiftyTwoWeekHigh"),
            "week52_low":    info.get("fiftyTwoWeekLow"),
            "trailing_pe":   info.get("trailingPE"),
            "forward_pe":    info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "upside_pct":    upside,
        }
    except Exception:
        return {}


def fetch_annual_dividends(symbol: str, quantity: float) -> float:
    """
    Return total dividend income received in the last 12 months for `quantity` shares.
    Returns 0.0 if no dividends or on error.
    """
    try:
        import pandas as pd
        ticker = yf.Ticker(symbol)
        divs = ticker.dividends
        if divs.empty:
            return 0.0
        one_year_ago = pd.Timestamp.now(tz=divs.index.tz) - pd.DateOffset(years=1)
        recent = divs[divs.index >= one_year_ago]
        return round(float(recent.sum()) * quantity, 2)
    except Exception:
        return 0.0


def get_commodity_price_per_unit(symbol: str, unit: str) -> float | None:
    """
    Return commodity price in the asset's stored unit.
    e.g. for Gold stored in grams: price = yfinance_price_per_troy_oz / 31.1035
    """
    price_per_trading_unit = fetch_current_price(symbol)
    if price_per_trading_unit is None:
        return None
    if unit == "gram":
        return price_per_trading_unit * TROY_OZ_PER_GRAM
    return price_per_trading_unit   # troy oz, barrel, etc.


def get_portfolio_summary():
    """
    Returns (rows, total_invested_usd, total_current_usd, fx_rates).

    Each row has both native-currency values and USD-converted equivalents:
      current_value      — in asset's native currency
      current_value_usd  — converted to USD at real-time rate
      invested_value     — in asset's native currency
      invested_value_usd — converted to USD at real-time rate
      gain_loss / gain_loss_pct — computed in native currency

    Totals (total_invested_usd, total_current_usd) are always in USD.
    fx_rates — dict of {currency: rate_to_usd} used this run.
    """
    assets = db.get_all_assets()
    rows = []
    total_invested_usd = 0.0
    total_current_usd = 0.0
    fx_rates: dict[str, float] = {}

    for a in assets:
        currency = a["currency"]
        if currency not in fx_rates:
            fx_rates[currency] = get_fx_rate_to_usd(currency)
        rate = fx_rates[currency]

        latest = db.get_latest_price(a["id"])
        raw_price = latest["price"] if latest else None

        # Commodities stored in grams need price conversion
        unit = a.get("unit", "share")
        if unit == "gram" and raw_price is not None:
            current_price = raw_price * TROY_OZ_PER_GRAM
        else:
            current_price = raw_price

        current_value = (current_price * a["quantity"]) if current_price else None
        invested_value = a["avg_buy_price"] * a["quantity"]

        current_value_usd  = (current_value  * rate) if current_value  is not None else None
        invested_value_usd = invested_value * rate

        gain_loss     = (current_value - invested_value) if current_value is not None else None
        gain_loss_usd = (gain_loss * rate)               if gain_loss    is not None else None
        gain_loss_pct = (gain_loss / invested_value * 100) if (gain_loss is not None and invested_value) else None

        rows.append({
            "id": a["id"],
            "symbol": a["symbol"],
            "name": a["name"],
            "exchange": a["exchange"],
            "asset_type": a.get("asset_type", "stock"),
            "unit": unit,
            "quantity": a["quantity"],
            "avg_buy_price": a["avg_buy_price"],
            "currency": currency,
            "fx_rate_to_usd": rate,
            "current_price": current_price,
            "current_value": current_value,
            "current_value_usd": current_value_usd,
            "invested_value": invested_value,
            "invested_value_usd": invested_value_usd,
            "gain_loss": gain_loss,
            "gain_loss_usd": gain_loss_usd,
            "gain_loss_pct": gain_loss_pct,
            "price_date": latest["date"] if latest else "—",
        })

        if current_value_usd is not None:
            total_current_usd += current_value_usd
        total_invested_usd += invested_value_usd

    return rows, total_invested_usd, total_current_usd, fx_rates


def get_annual_dividend_income() -> tuple[list[dict], float]:
    """
    Returns (rows, total_dividend_usd).
    Each row: symbol, name, quantity, currency, dividend_native, dividend_usd.
    Only includes assets with non-zero dividends.
    """
    assets = db.get_all_assets()
    rows = []
    total_usd = 0.0
    for a in assets:
        if a.get("asset_type") == "commodity":
            continue   # commodities don't pay dividends
        div_native = fetch_annual_dividends(a["symbol"], a["quantity"])
        if div_native <= 0:
            continue
        rate = get_fx_rate_to_usd(a["currency"])
        div_usd = round(div_native * rate, 2)
        total_usd += div_usd
        rows.append({
            "symbol": a["symbol"],
            "name": a["name"],
            "quantity": a["quantity"],
            "currency": a["currency"],
            "dividend_native": div_native,
            "dividend_usd": div_usd,
        })
    return rows, round(total_usd, 2)
import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            name            TEXT,
            exchange        TEXT,
            quantity        REAL NOT NULL,
            avg_buy_price   REAL DEFAULT 0,
            currency        TEXT DEFAULT 'USD',
            asset_type      TEXT DEFAULT 'stock',
            unit            TEXT DEFAULT 'share',
            added_date      TEXT DEFAULT (date('now'))
        )
    """)

    # Migrate existing asset rows
    existing_asset_cols = {row[1] for row in c.execute("PRAGMA table_info(assets)").fetchall()}
    for col, defn in [("asset_type", "TEXT DEFAULT 'stock'"), ("unit", "TEXT DEFAULT 'share'")]:
        if col not in existing_asset_cols:
            c.execute(f"ALTER TABLE assets ADD COLUMN {col} {defn}")

    # One row per asset per day — tracks price history
    c.execute("""
        CREATE TABLE IF NOT EXISTS asset_prices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id    INTEGER NOT NULL,
            date        TEXT NOT NULL,
            price       REAL,
            FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
            UNIQUE(asset_id, date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            name                    TEXT NOT NULL,
            principal               REAL NOT NULL,
            interest_rate           REAL NOT NULL,
            tenure_months           INTEGER NOT NULL,
            start_date              TEXT,
            emi                     REAL,
            remaining_balance       REAL,
            currency                TEXT DEFAULT 'INR',
            -- Education loan fields
            loan_type               TEXT DEFAULT 'standard',
            course_months           INTEGER DEFAULT 0,
            moratorium_months       INTEGER DEFAULT 0,
            admin_fee_pct           REAL DEFAULT 0,
            in_school_payment_type  TEXT DEFAULT 'standard',
            in_school_payment_amt   REAL DEFAULT 0,
            effective_principal     REAL DEFAULT 0,
            outstanding_at_repay    REAL DEFAULT 0
        )
    """)

    # Migrate existing DBs — add education columns if they don't exist yet
    edu_columns = [
        ("loan_type",              "TEXT DEFAULT 'standard'"),
        ("course_months",          "INTEGER DEFAULT 0"),
        ("moratorium_months",      "INTEGER DEFAULT 0"),
        ("admin_fee_pct",          "REAL DEFAULT 0"),
        ("in_school_payment_type", "TEXT DEFAULT 'standard'"),
        ("in_school_payment_amt",  "REAL DEFAULT 0"),
        ("effective_principal",    "REAL DEFAULT 0"),
        ("outstanding_at_repay",   "REAL DEFAULT 0"),
    ]
    existing = {row[1] for row in c.execute("PRAGMA table_info(loans)").fetchall()}
    for col, col_def in edu_columns:
        if col not in existing:
            c.execute(f"ALTER TABLE loans ADD COLUMN {col} {col_def}")

    c.execute("""
        CREATE TABLE IF NOT EXISTS loan_payments (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id             INTEGER NOT NULL,
            payment_date        TEXT DEFAULT (date('now')),
            amount_paid         REAL NOT NULL,
            remaining_balance   REAL,
            note                TEXT,
            FOREIGN KEY(loan_id) REFERENCES loans(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        )
    """)

    conn.commit()
    conn.close()


# ── Assets ────────────────────────────────────────────────────────────────────

def add_asset(symbol: str, name: str, exchange: str, quantity: float,
              avg_buy_price: float, currency: str,
              asset_type: str = "stock", unit: str = "share") -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO assets (symbol, name, exchange, quantity, avg_buy_price, currency, asset_type, unit) VALUES (?,?,?,?,?,?,?,?)",
        (symbol.upper(), name, exchange, quantity, avg_buy_price, currency, asset_type, unit),
    )
    asset_id = c.lastrowid
    conn.commit()
    conn.close()
    return asset_id


def get_all_assets():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM assets ORDER BY symbol").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_asset_quantity(asset_id: int, quantity: float, avg_buy_price: float):
    conn = get_conn()
    conn.execute(
        "UPDATE assets SET quantity=?, avg_buy_price=? WHERE id=?",
        (quantity, avg_buy_price, asset_id),
    )
    conn.commit()
    conn.close()


def delete_asset(asset_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    conn.commit()
    conn.close()


def upsert_price(asset_id: int, date: str, price: float):
    conn = get_conn()
    conn.execute(
        "INSERT INTO asset_prices (asset_id, date, price) VALUES (?,?,?) "
        "ON CONFLICT(asset_id, date) DO UPDATE SET price=excluded.price",
        (asset_id, date, price),
    )
    conn.commit()
    conn.close()


def get_latest_price(asset_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT price, date FROM asset_prices WHERE asset_id=? ORDER BY date DESC LIMIT 1",
        (asset_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_price_history(asset_id: int, days: int = 90):
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, price FROM asset_prices WHERE asset_id=? "
        "ORDER BY date DESC LIMIT ?",
        (asset_id, days),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ── Loans ─────────────────────────────────────────────────────────────────────

def add_loan(name: str, principal: float, interest_rate: float,
             tenure_months: int, start_date: str, emi: float, currency: str,
             loan_type: str = "standard", course_months: int = 0,
             moratorium_months: int = 0, admin_fee_pct: float = 0.0,
             in_school_payment_type: str = "standard",
             in_school_payment_amt: float = 0.0,
             effective_principal: float = 0.0,
             outstanding_at_repay: float = 0.0) -> int:
    conn = get_conn()
    c = conn.cursor()
    eff_p = effective_principal or principal
    out_r = outstanding_at_repay or principal
    c.execute(
        """INSERT INTO loans
           (name, principal, interest_rate, tenure_months, start_date, emi,
            remaining_balance, currency, loan_type, course_months, moratorium_months,
            admin_fee_pct, in_school_payment_type, in_school_payment_amt,
            effective_principal, outstanding_at_repay)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, principal, interest_rate, tenure_months, start_date, emi,
         out_r, currency, loan_type, course_months, moratorium_months,
         admin_fee_pct, in_school_payment_type, in_school_payment_amt,
         eff_p, out_r),
    )
    loan_id = c.lastrowid
    conn.commit()
    conn.close()
    return loan_id


def get_all_loans():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM loans ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_loan(loan_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_loan(loan_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM loans WHERE id=?", (loan_id,))
    conn.commit()
    conn.close()


def log_payment(loan_id: int, amount_paid: float, payment_date: str, note: str = ""):
    conn = get_conn()
    loan = dict(conn.execute("SELECT remaining_balance FROM loans WHERE id=?", (loan_id,)).fetchone())
    new_balance = max(0.0, loan["remaining_balance"] - amount_paid)
    conn.execute(
        "INSERT INTO loan_payments (loan_id, payment_date, amount_paid, remaining_balance, note) VALUES (?,?,?,?,?)",
        (loan_id, payment_date, amount_paid, new_balance, note),
    )
    conn.execute("UPDATE loans SET remaining_balance=? WHERE id=?", (new_balance, loan_id))
    conn.commit()
    conn.close()
    return new_balance


def get_payments(loan_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM loan_payments WHERE loan_id=? ORDER BY payment_date DESC",
        (loan_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Settings ──────────────────────────────────────────────────────────────────

def save_setting(key: str, value: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


# ── Education loan config ──────────────────────────────────────────────────────

def save_edu_loan_config(config: dict):
    """Persist education loan config as JSON in the settings table."""
    import json
    save_setting("edu_loan_config", json.dumps(config))


def get_edu_loan_config() -> dict | None:
    """Retrieve education loan config, or None if not set."""
    import json
    val = get_setting("edu_loan_config")
    if val:
        try:
            return json.loads(val)
        except Exception:
            return None
    return None
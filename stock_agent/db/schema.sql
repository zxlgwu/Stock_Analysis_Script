CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    exchange TEXT,
    name TEXT,
    cik TEXT,
    sector TEXT,
    industry TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_members (
    universe TEXT NOT NULL,
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    removed_at TEXT,
    PRIMARY KEY (universe, ticker, added_at),
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices (ticker, date);

CREATE TABLE IF NOT EXISTS price_stats_weekly (
    week_ending TEXT NOT NULL,
    ticker TEXT NOT NULL,
    ret_1y REAL,
    ret_3y REAL,
    ret_5y REAL,
    cagr REAL,
    rel_spy_1y REAL,
    rel_spy_3y REAL,
    rel_spy_5y REAL,
    rel_sector_1y REAL,
    rel_sector_3y REAL,
    rel_sector_5y REAL,
    max_drawdown REAL,
    max_dd_start TEXT,
    max_dd_end TEXT,
    current_drawdown REAL,
    vol_1y REAL,
    vol_full REAL,
    ma_convergence REAL,
    PRIMARY KEY (week_ending, ticker),
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

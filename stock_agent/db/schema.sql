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

CREATE TABLE IF NOT EXISTS company_profiles (
    ticker TEXT PRIMARY KEY,
    segments_json TEXT,
    regions_json TEXT,
    sensitivities_json TEXT,
    summary TEXT,
    as_of TEXT,
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

CREATE TABLE IF NOT EXISTS company_relations (
    src_ticker TEXT NOT NULL,
    dst_key TEXT NOT NULL,
    dst_ticker TEXT,
    relation TEXT NOT NULL,
    evidence TEXT,
    confidence REAL,
    PRIMARY KEY (src_ticker, dst_key, relation),
    FOREIGN KEY (src_ticker) REFERENCES companies (ticker)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT NOT NULL,
    period_end TEXT NOT NULL,
    revenue REAL,
    gross_margin REAL,
    op_margin REAL,
    fcf REAL,
    eps REAL,
    source TEXT NOT NULL,
    filed_at TEXT,
    PRIMARY KEY (ticker, period_end, source),
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT,
    title TEXT,
    body TEXT,
    published_at TEXT,
    fetched_at TEXT,
    content_hash TEXT,
    cluster_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_at);
CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles (content_hash);

CREATE TABLE IF NOT EXISTS article_clusters (
    cluster_id TEXT PRIMARY KEY,
    representative_article_id TEXT,
    first_seen TEXT,
    size INTEGER,
    event_summary TEXT,
    dropped INTEGER NOT NULL DEFAULT 0,
    drop_reason TEXT
);

CREATE TABLE IF NOT EXISTS cluster_entities (
    cluster_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    link_type TEXT NOT NULL,
    PRIMARY KEY (cluster_id, ticker, link_type)
);

CREATE TABLE IF NOT EXISTS materiality (
    cluster_id TEXT PRIMARY KEY,
    material INTEGER NOT NULL,
    category TEXT,
    reason TEXT,
    model TEXT,
    prompt_version TEXT
);

CREATE TABLE IF NOT EXISTS impacts (
    cluster_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    relation TEXT NOT NULL,
    direction TEXT NOT NULL,
    revenue_line TEXT,
    est_pct REAL,
    horizon TEXT NOT NULL,
    confidence REAL,
    priced_in TEXT,
    reasoning TEXT,
    model TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (cluster_id, ticker, horizon, relation)
);

CREATE TABLE IF NOT EXISTS scores_weekly (
    week_ending TEXT NOT NULL,
    ticker TEXT NOT NULL,
    news_mid REAL,
    news_long REAL,
    net_revenue_mid REAL,
    net_revenue_long REAL,
    quality REAL,
    value REAL,
    technical REAL,
    risk REAL,
    composite REAL,
    PRIMARY KEY (week_ending, ticker),
    FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

CREATE TABLE IF NOT EXISTS recommendations (
    week_ending TEXT NOT NULL,
    ticker TEXT NOT NULL,
    list_name TEXT NOT NULL,
    rank INTEGER,
    thesis TEXT,
    risks TEXT,
    PRIMARY KEY (week_ending, ticker, list_name)
);

CREATE TABLE IF NOT EXISTS reports_sent (
    week_ending TEXT PRIMARY KEY,
    recipients TEXT,
    status TEXT,
    message_id TEXT
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    filing_url TEXT,
    item_type TEXT NOT NULL,
    PRIMARY KEY (date, ticker, item_type)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    role TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    cache_hit INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls (ts);

CREATE TABLE IF NOT EXISTS llm_cache (
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (model, prompt_hash)
);

CREATE TABLE IF NOT EXISTS evaluation_metrics (
    as_of TEXT NOT NULL,
    metric TEXT NOT NULL,
    horizon TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (as_of, metric, horizon)
);

CREATE TABLE IF NOT EXISTS job_steps (
    week_ending TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (week_ending, step)
);

CREATE TABLE IF NOT EXISTS impact_channels (
    cluster_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    ord INTEGER NOT NULL,
    relation TEXT NOT NULL,
    direction TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    tickers TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    PRIMARY KEY (cluster_id, position)
);

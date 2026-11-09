from pathlib import Path

from stock_agent.core.models import Security
from stock_agent.ingest.prices.symbols import to_yfinance_symbol
from stock_agent.universe.custom import CustomListUniverse
from stock_agent.universe.nasdaq import parse_nasdaq_directory
from stock_agent.universe.sp500 import parse_sp500_html

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def test_sp500_parser_reads_ticker_sector_and_cik():
    securities = parse_sp500_html((FIXTURES / "sp500_sample.html").read_text())
    by_ticker = {sec.ticker: sec for sec in securities}
    assert set(by_ticker) == {"AAPL", "BRK.B"}
    assert by_ticker["AAPL"].sector == "Information Technology"
    assert by_ticker["AAPL"].cik == "0000320193"
    assert by_ticker["BRK.B"].industry == "Multi-Sector Holdings"
    assert to_yfinance_symbol("BRK.B") == "BRK-B"


def test_nasdaq_parser_drops_etfs_and_test_issues():
    securities = parse_nasdaq_directory((FIXTURES / "nasdaq_sample.txt").read_text())
    tickers = [sec.ticker for sec in securities]
    assert tickers == ["AAPL", "MSFT"]
    assert securities[0].exchange == "NASDAQ"


def test_public_company_list_keeps_universe_industry_and_outside_names():
    from stock_agent.universe.listings import merge_companies

    listings = parse_nasdaq_directory((FIXTURES / "nasdaq_sample.txt").read_text())
    members = [
        Security("AAPL", "NASDAQ", "Apple Inc.", cik="0000320193", sector="Information Technology", industry="Technology Hardware"),
        Security("BRK.B", "NYSE", "Berkshire Hathaway", industry="Multi-Sector Holdings"),
    ]
    merged = {security.ticker: security for security in merge_companies(listings, members)}
    assert merged["AAPL"].industry == "Technology Hardware"
    assert merged["AAPL"].cik == "0000320193"
    assert merged["MSFT"].name
    assert merged["BRK.B"].industry == "Multi-Sector Holdings"


def test_custom_yaml_watchlist():
    universe = CustomListUniverse("example_watchlist", directory=ROOT / "config" / "universes")
    tickers = [sec.ticker for sec in universe.list_members()]
    assert tickers == ["AAPL", "MSFT"]
    assert universe.name == "custom:example_watchlist"

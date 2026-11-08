"""Map tickers to the symbols yfinance expects."""


def to_yfinance_symbol(ticker: str) -> str:
    """Class shares are dots in listings (BRK.B) and hyphens in yfinance (BRK-B)."""
    return ticker.replace(".", "-")

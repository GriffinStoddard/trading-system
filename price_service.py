"""
Live price fetching for the buy list.

Pulls last-traded prices from Yahoo Finance (via yfinance). Only the buy list
is refreshed — holdings prices stay as captured in the Excel export, so account
totals remain a consistent snapshot. Each ticker is fetched independently so
one bad symbol doesn't sink the batch.
"""

from typing import Optional


def fetch_live_prices(tickers: list[str]) -> tuple[dict[str, float], list[str]]:
    """Fetch last prices for tickers.

    Returns (prices, failed_tickers). Raises ImportError if yfinance is not
    installed and ConnectionError if nothing could be fetched at all.
    """
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    prices: dict[str, float] = {}
    failed: list[str] = []

    for ticker in tickers:
        price = _fetch_one(yf, ticker)
        if price is not None and price > 0:
            prices[ticker] = round(price, 2)
        else:
            failed.append(ticker)

    if tickers and not prices:
        raise ConnectionError(
            "Could not fetch any prices — check your internet connection.")
    return prices, failed


def _fetch_one(yf, ticker: str) -> Optional[float]:
    try:
        info = yf.Ticker(ticker).fast_info
        price = info.last_price
        if price is None:
            price = info.previous_close
        return float(price) if price else None
    except Exception:
        return None

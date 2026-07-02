import argparse
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import requests
import numpy as np
from io import StringIO
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from multiprocessing import Pool, cpu_count
from bs4 import BeautifulSoup

def get_sp500_tickers():
    print("Downloading SP500 tickers...")
    # URL of Wikipedia page with S&P 500 companies
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    
    # Set a user-agent to avoid being blocked
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }
    
    # Fetch the page
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to retrieve page: Status code {response.status_code}")
    
    # Parse the HTML
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find the table with id 'constituents'
    table = soup.find('table', {'id': 'constituents'})
    if not table:
        raise Exception("Could not find S&P 500 constituents table")
    
    # Extract tickers from the first column
    tickers = []
    for row in table.find_all('tr')[1:]:  # Skip header row
        ticker = row.find_all('td')[0].text.strip()
        # Clean up ticker (remove newlines or footnotes like '[1]')
        ticker = ticker.replace('\n', '').split('[')[0]
        tickers.append(ticker)
    
    print(f"Retrieved {len(tickers)} S&P 500 tickers")
    return tickers

# Step 1: Get list of stock tickers
def get_nasdaq_tickers():
    print("Downloading NASDAQ tickers...")
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        df = pd.read_csv(StringIO(response.text), sep="|")
        tickers = df[(df['ETF'] == 'N') & (df['Test Issue'] == 'N')]['Symbol'].tolist()
        return tickers
    else:
        raise Exception("Failed to download ticker list")

def fetch_stock_history(stock, years):
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    return stock.history(start=start)

# Step 2: Worker function for multiprocessing (with new MA convergence metric)
def process_stock(ticker, years=1, ma_convergence_threshold=0.5):
    try:
        stock = yf.Ticker(ticker)
        hist = fetch_stock_history(stock, years)
        
        if len(hist) < 120:  # Need enough data for 120-day MA
            return ticker, None, None, None, None, False
        
        # Calculate daily returns
#        returns = hist['Close'].pct_change().dropna()
#        volatility = returns.std()
        
        # Check deviation from 50-day MA
#        ma50 = hist['Close'].rolling(window=50).mean()
#        deviation_from_ma = (hist['Close'] - ma50).abs() / ma50
#        avg_deviation = deviation_from_ma.mean()
        
        # New metric: Check if 20-day, 60-day, and 120-day MAs are close in last 60 days
        ma20 = hist['Close'].rolling(window=20).mean()
        ma60 = hist['Close'].rolling(window=60).mean()
        ma120 = hist['Close'].rolling(window=120).mean()
        
        # Take last 60 days
        last_60_days = -100
        ma20_last = ma20[last_60_days:]
        ma60_last = ma60[last_60_days:]
        ma120_last = ma120[last_60_days:]
        
        # Calculate max-min difference relative to average MA
        ma_avg = (ma20_last + ma60_last + ma120_last) / 3
        ma_spread = (ma20_last.combine(ma60_last, max).combine(ma120_last, max) - 
                    ma20_last.combine(ma60_last, min).combine(ma120_last, min))
        relative_spread = ma_spread / ma_avg
        avg_relative_spread = relative_spread.mean()

        ma20_delta_max_min = ma20_last.max() - ma20_last.min()

        ma20_delta = (ma20_last.iloc[-1]-ma20_last.iloc[0])/ma20_last.iloc[0]
        
        # Get market cap (for plotting)
        market_cap = stock.info.get('marketCap', None)
        if market_cap is None:
            return ticker, None, None, None, None, False
        
        # Define convergence: low volatility OR small MA deviation AND close MAs
        is_converged = (avg_relative_spread < ma_convergence_threshold) and (ma20_delta > -0.02)

        #print(f"company name: {stock.info.get('longName', ticker)}, avg_relative_spread: {avg_relative_spread}, ma20_delta: {ma20_delta}")

        company_name = stock.info.get('longName', ticker)
        
        if is_converged:
            print(f"{ticker} converged with avg_relative_spread: {avg_relative_spread} and ma20_delta: {ma20_delta}")
            return ticker, hist, market_cap, company_name, avg_relative_spread, True
        return ticker, None, None, None, None, False
    
    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        return ticker, None, None, None, None, False

# Step 3: Plot stock price with 20, 60, and 120-day MAs
def plot_stock(ticker, hist, market_cap, company_name, years, pdf):
    plt.figure(figsize=(10, 6))
    plt.plot(hist.index, hist['Close'], label=f"{ticker} Close Price", color='blue')
    plt.plot(hist.index, hist['Close'].rolling(window=20).mean(), label="20-Day MA", color='green', linestyle='--')
    plt.plot(hist.index, hist['Close'].rolling(window=60).mean(), label="60-Day MA", color='orange', linestyle='--')
    plt.plot(hist.index, hist['Close'].rolling(window=120).mean(), label="120-Day MA", color='red', linestyle='--')
    market_cap_billions = market_cap / 1e9
    year_label = f"{years} Year" if years == 1 else f"{years} Years"
    plt.title(f"{company_name} Stock Price ({year_label})\nMarket Cap billion: ${market_cap_billions:,.0f}B")
    plt.xlabel("Date")
    plt.ylabel("Price (USD)")
    plt.legend()
    plt.grid(True)
    
    pdf.savefig()
    plt.close()
# Main execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find S&P 500 stocks with converging moving averages.")
    parser.add_argument(
        "--years",
        type=int,
        default=1,
        help="Number of years of historical data to analyze (default: 1)",
    )
    args = parser.parse_args()
    if args.years < 1:
        parser.error("--years must be at least 1")

    # Configuration
    MIN_MARKET_CAP = 1e9  # $1 billion minimum market cap
    VOLATILITY_THRESHOLD = 0.02  # 2% daily return volatility threshold
    MA_CONVERGENCE_THRESHOLD = 0.09  # 50% relative spread threshold
    OUTPUT_PDF = "converged_stocks_plots.pdf"
    NUM_PROCESSES = cpu_count() - 1  # Use all cores minus one
    YEARS = args.years
    
    # Get all tickers
    tickers = get_sp500_tickers() #get_nasdaq_tickers()
#    tickers = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'TSLA', 'FB', 'NVDA', 'PYPL', 'ADBE', 'INTC']
    print(f"Found {len(tickers)} tickers")
    
    # Limit for demo (remove or adjust for full run)
#    tickers = tickers[:50]  # Using 50 for demo
    
    # Use multiprocessing to analyze stocks
    print(f"Processing {len(tickers)} tickers over {YEARS} year(s) with {NUM_PROCESSES} processes...")
    
    with Pool(processes=NUM_PROCESSES) as pool:
        results = pool.starmap(process_stock, [(ticker, YEARS, MA_CONVERGENCE_THRESHOLD) for ticker in tickers])

    # Collect converged stocks and sort by avg_relative_spread
    converged_stocks = []
    for ticker, hist, market_cap, company_name, avg_relative_spread, is_converged in results:
        if is_converged and hist is not None:
            print(f"appending {ticker} to converged_stocks")
            converged_stocks.append((ticker, hist, market_cap, company_name, avg_relative_spread))
    
    # Sort by avg_relative_spread in ascending order
    converged_stocks.sort(key=lambda x: x[4])  # x[4] is avg_relative_spread
    
    # Plot converged stocks in one PDF
    with PdfPages(OUTPUT_PDF) as pdf:
        converged_count = 0
        for ticker, hist, market_cap, company_name, avg_relative_spread in converged_stocks:
            plot_stock(ticker, hist, market_cap, company_name, YEARS, pdf)
            converged_count += 1
            print(f"Added plot for {ticker} to {OUTPUT_PDF}")
        
        print(f"Total converged stocks plotted: {converged_count}")
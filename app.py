import streamlit as st
import yfinance as yf
import pandas as pd
import requests
# 1. Basic security: A simple password check so only you and your friend can view it.
# To use this securely online, we will set a password in Streamlit Secrets later.
PASSWORD = st.secrets.get("APP_PASSWORD", "secret123") 

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Login Required")
        pwd = st.text_input("Enter Password", type="password")
        if st.button("Login"):
            if pwd == PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password")
        st.stop()

# Force the user to log in before seeing the rest of the app
check_password()

st.title("📈 GMMA Trend Screener")
st.write("Screening the S&P 500 and your custom watchlist using Daryl Guppy's GMMA.")

# 2. Get S&P 500 tickers directly from Wikipedia
# 2. Get S&P 500 tickers directly from Wikipedia securely
@st.cache_data
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    # Disguise our script as a normal web browser
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    # Fetch the page HTML first, then pass it to pandas
    html_data = requests.get(url, headers=headers).text
    df = pd.read_html(html_data)[0]
    
    return df['Symbol'].tolist()

# 3. Sidebar Configuration for your Custom Watchlist and Timeframes
st.sidebar.header("Screener Settings")
custom_input = st.sidebar.text_area("Custom Watchlist (comma-separated)", "NVDA, PLTR, TSLA")
timeframe = st.sidebar.radio("Chart Timeframe", ["1d", "1wk"], format_func=lambda x: "Daily" if x == "1d" else "Weekly")

# 4. The math for Daryl Guppy's Moving Averages
def is_gmma_bullish(close_prices):
    if len(close_prices) < 65: # Need enough data for a 60-period moving average
        return False
        
    short_emas = [3, 5, 8, 10, 12, 15]
    long_emas = [30, 35, 40, 45, 50, 60]
    
    emas = {}
    # Calculate all Exponential Moving Averages (EMAs)
    for period in short_emas + long_emas:
        emas[period] = close_prices.ewm(span=period, adjust=False).mean()
        
    # Rule: The lowest of the short-term averages must be HIGHER than the highest of the long-term averages.
    # This indicates a clear separation, meaning short-term traders and long-term investors both agree on the uptrend.
    lowest_short = min([emas[p].iloc[-1] for p in short_emas])
    highest_long = max([emas[p].iloc[-1] for p in long_emas])
    
    return lowest_short > highest_long

# 5. The Execution Engine
if st.sidebar.button("Run Screener"):
    # Clean up the custom tickers and combine them with the S&P 500
    custom_tickers = [x.strip().upper() for x in custom_input.split(",") if x.strip()]
    sp500 = get_sp500_tickers()
    all_tickers = list(set(sp500 + custom_tickers))
    
    st.info(f"Downloading historical data for {len(all_tickers)} tickers. This takes about 30 seconds...")
    
    # Download 1 year of historical data in bulk (much faster than one-by-one)
    data = yf.download(all_tickers, period="1y", interval=timeframe, progress=False)
    
    passed_gmma = []
    
    # Step A: Filter by GMMA first 
    for ticker in all_tickers:
        try:
            # Extract just the closing prices for this specific ticker
            close_prices = data['Close'][ticker].dropna()
            if is_gmma_bullish(close_prices):
                passed_gmma.append(ticker)
        except Exception:
            pass # Skip if data is missing or broken for a specific ticker
            
    st.write(f"✅ {len(passed_gmma)} stocks passed the GMMA trend test. Now checking Market Cap...")
    
    # Step B: Filter by Market Cap > $20 Billion
    final_results = []
    progress_bar = st.progress(0)
    
    for i, ticker in enumerate(passed_gmma):
        try:
            # Fetch the company info to check its size
            info = yf.Ticker(ticker).info
            market_cap = info.get("marketCap", 0)
            
            if market_cap >= 20_000_000_000:
                final_results.append({
                    "Ticker": ticker,
                    "Market Cap ($B)": round(market_cap / 1_000_000_000, 2),
                    "Price": round(info.get("currentPrice", info.get("regularMarketPrice", 0)), 2)
                })
        except:
            pass
        # Update the visual progress bar
        progress_bar.progress((i + 1) / len(passed_gmma))
        
    # Display the final list
    if final_results:
        st.success(f"Found {len(final_results)} stocks in a strong GMMA trend with >$20B Market Cap!")
        st.dataframe(pd.DataFrame(final_results).sort_values(by="Market Cap ($B)", ascending=False), use_container_width=True)
    else:
        st.warning("No stocks met all the criteria right now.")

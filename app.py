import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io

# 1. Password Security
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

check_password()

st.title("📈 Advanced GMMA Trend Screener")
st.write("Screening the S&P 500 and custom watchlists for specific GMMA compression setups.")

# 2. Get S&P 500 securely
@st.cache_data
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    html_data = requests.get(url, headers=headers).text
    df = pd.read_html(io.StringIO(html_data))[0]
    return df['Symbol'].tolist()

# 3. Sidebar Configuration 
st.sidebar.header("Screener Settings")

scan_type = st.sidebar.selectbox(
    "Select GMMA Setup",
    [
        "Standard Bullish (All short > All long)", 
        "Condition 1: Compression Above (Pullback)",
        "Condition 2: Compression Mixed (Deep Pullback)"
    ]
)

custom_input = st.sidebar.text_area("Custom Watchlist (comma-separated)", "NVDA, PLTR, TSLA")
timeframe = st.sidebar.radio("Chart Timeframe", ["1d", "1wk"], format_func=lambda x: "Daily" if x == "1d" else "Weekly")

# 4. The Advanced Math for 5-Candle Compression
def evaluate_gmma(close_prices):
    if len(close_prices) < 65: 
        return "None"
        
    short_emas = [3, 5, 8, 10, 12, 15]
    long_emas = [30, 35, 40, 45, 50, 60]
    
    emas = {}
    for period in short_emas + long_emas:
        emas[period] = close_prices.ewm(span=period, adjust=False).mean()
        
    # Group the short and long EMAs into dataframes to analyze history easily
    short_df = pd.DataFrame({p: emas[p] for p in short_emas})
    long_df = pd.DataFrame({p: emas[p] for p in long_emas})
    
    # Calculate the max and min lines for every single day in the chart
    max_s = short_df.max(axis=1)
    min_s = short_df.min(axis=1)
    max_l = long_df.max(axis=1)
    min_l = long_df.min(axis=1)
    
    # Check Long Term Uptrend on the most recent day
    is_long_uptrend = emas[30].iloc[-1] > emas[60].iloc[-1]
    
    if not is_long_uptrend:
        return "None"
        
    # --- NEW 5-CANDLE COMPRESSION LOGIC ---
    # Create a true/false list for every day showing if it was compressed
    short_spread = max_s - min_s
    long_spread = max_l - min_l
    daily_compression = short_spread < (long_spread * 0.5)
    
    # Check if the last 5 candles were ALL True (compressed)
    is_compressed_5_candles = daily_compression.iloc[-5:].all()
    
    # Check the current day's position (Above vs Mixed)
    all_short_above_long = min_s.iloc[-1] > max_l.iloc[-1]
    mixed_short_long = (min_s.iloc[-1] <= max_l.iloc[-1]) and (max_s.iloc[-1] >= min_l.iloc[-1])
    
    # Categorize the current chart setup
    if is_compressed_5_candles and all_short_above_long:
        return "Condition 1: Compression Above (Pullback)"
    elif is_compressed_5_candles and mixed_short_long:
        return "Condition 2: Compression Mixed (Deep Pullback)"
    elif all_short_above_long:
        # Standard bullish doesn't care about compression
        return "Standard Bullish (All short > All long)"
        
    return "None"

# 5. The Execution Engine
if st.sidebar.button("Run Screener"):
    custom_tickers = [x.strip().upper() for x in custom_input.split(",") if x.strip()]
    sp500 = get_sp500_tickers()
    all_tickers = list(set(sp500 + custom_tickers))
    
    # Request 5 years for Weekly to ensure we have enough data
    data_period = "5y" if timeframe == "1wk" else "1y"
    
    st.info(f"Downloading historical data for {len(all_tickers)} tickers. Scanning for: **{scan_type}**...")
    
    data = yf.download(all_tickers, period=data_period, interval=timeframe, progress=False)
    
    passed_gmma = []
    
    for ticker in all_tickers:
        try:
            close_prices = data['Close'][ticker].dropna()
            
            # Check if the chart matches the user's selected dropdown choice
            chart_state = evaluate_gmma(close_prices)
            if chart_state == scan_type:
                passed_gmma.append(ticker)
        except Exception:
            pass 
            
    st.write(f"✅ {len(passed_gmma)} stocks matched the chart pattern. Now checking Market Cap...")
    
    final_results = []
    if passed_gmma:
        progress_bar = st.progress(0)
        
        for i, ticker in enumerate(passed_gmma):
            try:
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
            progress_bar.progress((i + 1) / len(passed_gmma))
            
    if final_results:
        st.success(f"Found {len(final_results)} stocks matching your criteria!")
        st.dataframe(pd.DataFrame(final_results).sort_values(by="Market Cap ($B)", ascending=False), use_container_width=True)
    else:
        st.warning("No stocks met all the criteria right now. Try a different setup or timeframe.")

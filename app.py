import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import plotly.graph_objects as go

# 1. Page Configuration & Security
# MUST be the first Streamlit command. This forces the app to full-screen width.
st.set_page_config(page_title="GMMA Screener", layout="wide")

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

# 2. Market Tickers
@st.cache_data
def get_market_tickers():
    headers = {'User-Agent': 'Mozilla/5.0'}
    tickers = []
    
    try:
        sp_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp_html = requests.get(sp_url, headers=headers).text
        sp_df = pd.read_html(io.StringIO(sp_html))[0]
        tickers.extend(sp_df['Symbol'].tolist())
    except:
        pass
        
    try:
        ndx_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        ndx_html = requests.get(ndx_url, headers=headers).text
        ndx_tables = pd.read_html(io.StringIO(ndx_html))
        for df in ndx_tables:
            if 'Ticker' in df.columns:
                tickers.extend(df['Ticker'].tolist())
                break
    except:
        pass
        
    clean_tickers = [t.replace('.', '-') for t in set(tickers) if type(t) == str]
    return clean_tickers if clean_tickers else ["AAPL", "MSFT", "NVDA", "SPY"]

# 3. Sidebar Configuration 
st.sidebar.header("Screener Settings")

scan_type = st.sidebar.selectbox(
    "Select GMMA Trend Filter",
    [
        "Up Trend - Short Term GMMA", 
        "Down Trend - Short Term GMMA",
        "Up Trend - Long Term GMMA",
        "Down Trend - Long Term GMMA",
        "New Emerging GMMA Signal"
    ]
)

min_market_cap = st.sidebar.number_input("Minimum Market Cap ($ Billions)", min_value=0.0, value=20.0, step=1.0)
custom_input = st.sidebar.text_area("Custom Watchlist (comma-separated)", "PLTR, SOFI")
timeframe = st.sidebar.radio("Chart Timeframe", ["1d", "1wk"], format_func=lambda x: "Daily" if x == "1d" else "Weekly")

# 4. Math Engine
def evaluate_gmma(close_prices, scan_selection):
    if len(close_prices) < 65: 
        return False, 0, None
        
    short_emas = [3, 5, 8, 10, 12, 15]
    long_emas = [30, 35, 40, 45, 50, 60]
    
    emas = {}
    for period in short_emas + long_emas:
        emas[period] = close_prices.ewm(span=period, adjust=False).mean()
        
    short_df = pd.DataFrame({p: emas[p] for p in short_emas})
    long_df = pd.DataFrame({p: emas[p] for p in long_emas})
    
    max_s = short_df.max(axis=1)
    min_s = short_df.min(axis=1)
    max_l = long_df.max(axis=1)
    min_l = long_df.min(axis=1)
    
    # Compression counting logic (kept intact for the data table)
    short_spread = max_s - min_s
    long_spread = max_l - min_l
    daily_compression = short_spread < (long_spread * 0.5)
    
    compression_count = 0
    for is_compressed in reversed(daily_compression.tolist()):
        if is_compressed:
            compression_count += 1
        else:
            break

    # Determine Trend States based on the final day
    st_uptrend = emas[3].iloc[-1] > emas[15].iloc[-1]
    st_downtrend = emas[3].iloc[-1] < emas[15].iloc[-1]
    lt_uptrend = emas[30].iloc[-1] > emas[60].iloc[-1]
    lt_downtrend = emas[30].iloc[-1] < emas[60].iloc[-1]
    
    # Emerging Signal logic (Short term group crossed above long term group within last 5 periods)
    current_short_above_long = min_s.iloc[-1] > max_l.iloc[-1]
    past_short_below_long = min_s.iloc[-5] <= max_l.iloc[-5] if len(min_s) >= 5 else False
    is_emerging = current_short_above_long and past_short_below_long

    # Match the user's selected filter
    matches_filter = False
    if scan_selection == "Up Trend - Short Term GMMA" and st_uptrend:
        matches_filter = True
    elif scan_selection == "Down Trend - Short Term GMMA" and st_downtrend:
        matches_filter = True
    elif scan_selection == "Up Trend - Long Term GMMA" and lt_uptrend:
        matches_filter = True
    elif scan_selection == "Down Trend - Long Term GMMA" and lt_downtrend:
        matches_filter = True
    elif scan_selection == "New Emerging GMMA Signal" and is_emerging:
        matches_filter = True
        
    return matches_filter, compression_count, emas

# 5. Execution Engine
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "full_data" not in st.session_state:
    st.session_state.full_data = None

if st.sidebar.button("Run Screener"):
    custom_tickers = [x.strip().upper() for x in custom_input.split(",") if x.strip()]
    broad_market = get_market_tickers()
    all_tickers = list(set(broad_market + custom_tickers))
    
    if len(all_tickers) < 2:
        all_tickers.append("SPY")
        
    data_period = "5y" if timeframe == "1wk" else "1y"
    
    st.info(f"Downloading historical data for {len(all_tickers)} tickers. Scanning for: **{scan_type}**...")
    
    data = yf.download(all_tickers, period=data_period, interval=timeframe, progress=False)
    st.session_state.full_data = data 
    
    passed_gmma = []
    
    for ticker in all_tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data['Close'].columns:
                    close_prices = data['Close'][ticker].dropna()
                else:
                    continue
            else:
                close_prices = data['Close'].dropna()
                
            matches, comp_days, emas = evaluate_gmma(close_prices, scan_type)
            
            if matches:
                passed_gmma.append({
                    "Ticker": ticker,
                    "Periods Compressed": comp_days
                })
        except Exception:
            pass 
            
    st.write(f"✅ {len(passed_gmma)} stocks matched the chart pattern. Now getting Company Info & Market Cap (>{min_market_cap}B)...")
    
    final_results = []
    if passed_gmma:
        progress_bar = st.progress(0)
        
        for i, item in enumerate(passed_gmma):
            ticker = item["Ticker"]
            try:
                info = yf.Ticker(ticker).info
                market_cap = info.get("marketCap", 0)
                market_cap_b = market_cap / 1_000_000_000
                
                if market_cap_b >= min_market_cap:
                    final_results.append({
                        "Ticker": ticker,
                        "Company Name": info.get("longName", "N/A"),
                        "Sector": info.get("sector", "N/A"),
                        "Industry": info.get("industry", "N/A"),
                        "Periods Compressed": item["Periods Compressed"],
                        "Market Cap ($B)": round(market_cap_b, 2),
                        "Price": round(info.get("currentPrice", info.get("regularMarketPrice", 0)), 2)
                    })
            except:
                pass
            progress_bar.progress((i + 1) / len(passed_gmma))
            
    st.session_state.scan_results = final_results

# 6. Display Results
if st.session_state.scan_results:
    st.success(f"Found {len(st.session_state.scan_results)} stocks matching your criteria!")
    
    df_results = pd.DataFrame(st.session_state.scan_results).sort_values(by="Periods Compressed", ascending=False).reset_index(drop=True)
    
    st.write("👉 **Click anywhere on a row below to instantly view its chart.**")
    
    selection_event = st.dataframe(
        df_results, 
        use_container_width=True, 
        on_select="rerun", 
        selection_mode="single-row"
    )
    
    st.markdown("---")
    st.subheader("📊 Visual Charting")
    
    selected_ticker = None
    
    if selection_event and "selection" in selection_event and selection_event["selection"].get("rows"):
        selected_row_index = selection_event["selection"]["rows"][0]
        selected_ticker = df_results.iloc[selected_row_index]["Ticker"]
    
    if selected_ticker and st.session_state.full_data is not None:
        try:
            if

import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import plotly.graph_objects as go

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

# 2. Get the Russell 1000 (Top 1000 US Stocks) instead of just S&P 500
@st.cache_data
def get_broad_market_tickers():
    url = 'https://en.wikipedia.org/wiki/Russell_1000_Index'
    headers = {'User-Agent': 'Mozilla/5.0'}
    html_data = requests.get(url, headers=headers).text
    try:
        # Wikipedia tables change format sometimes, we look for the one with 'Ticker'
        tables = pd.read_html(io.StringIO(html_data))
        for df in tables:
            if 'Ticker' in df.columns:
                return df['Ticker'].tolist()
    except Exception as e:
        st.error("Could not load Russell 1000. Defaulting to a smaller list.")
        return ["AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN"] # Fallback

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

# New dynamic Market Cap input
min_market_cap = st.sidebar.number_input("Minimum Market Cap ($ Billions)", min_value=0.0, value=20.0, step=1.0)

custom_input = st.sidebar.text_area("Custom Watchlist (comma-separated)", "PLTR, SOFI")
timeframe = st.sidebar.radio("Chart Timeframe", ["1d", "1wk"], format_func=lambda x: "Daily" if x == "1d" else "Weekly")

# 4. Math & Compression Counter
def evaluate_gmma(close_prices):
    if len(close_prices) < 65: 
        return "None", 0, None
        
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
    
    is_long_uptrend = emas[30].iloc[-1] > emas[60].iloc[-1]
    
    if not is_long_uptrend:
        return "None", 0, emas
        
    # Calculate compression for all historical days
    short_spread = max_s - min_s
    long_spread = max_l - min_l
    daily_compression = short_spread < (long_spread * 0.5)
    
    # Count consecutive days of compression looking backward from today
    compression_count = 0
    for is_compressed in reversed(daily_compression.tolist()):
        if is_compressed:
            compression_count += 1
        else:
            break # Stop counting as soon as the compression breaks
            
    # Check current state
    all_short_above_long = min_s.iloc[-1] > max_l.iloc[-1]
    mixed_short_long = (min_s.iloc[-1] <= max_l.iloc[-1]) and (max_s.iloc[-1] >= min_l.iloc[-1])
    
    # Categorize
    chart_state = "None"
    if all_short_above_long:
        chart_state = "Standard Bullish (All short > All long)"
        if compression_count > 0:
            chart_state = "Condition 1: Compression Above (Pullback)"
    elif mixed_short_long and compression_count > 0:
        chart_state = "Condition 2: Compression Mixed (Deep Pullback)"
        
    return chart_state, compression_count, emas

# 5. The Execution Engine
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "full_data" not in st.session_state:
    st.session_state.full_data = None

if st.sidebar.button("Run Screener"):
    custom_tickers = [x.strip().upper() for x in custom_input.split(",") if x.strip()]
    broad_market = get_broad_market_tickers()
    all_tickers = list(set(broad_market + custom_tickers))
    
    data_period = "5y" if timeframe == "1wk" else "1y"
    
    st.info(f"Downloading historical data for {len(all_tickers)} tickers. Scanning for: **{scan_type}**...")
    
    data = yf.download(all_tickers, period=data_period, interval=timeframe, progress=False)
    st.session_state.full_data = data # Save for the charting tool later
    
    passed_gmma = []
    
    for ticker in all_tickers:
        try:
            close_prices = data['Close'][ticker].dropna()
            chart_state, comp_days, emas = evaluate_gmma(close_prices)
            
            # Allow through if it matches the scan, OR if it's standard bullish we still pass it if selected
            if chart_state == scan_type or (scan_type == "Standard Bullish (All short > All long)" and "Standard" in chart_state):
                passed_gmma.append({
                    "Ticker": ticker,
                    "Compression Periods": comp_days
                })
        except Exception:
            pass 
            
    st.write(f"✅ {len(passed_gmma)} stocks matched the chart pattern. Now checking Market Cap (>{min_market_cap}B)...")
    
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
                        "Periods Compressed": item["Compression Periods"],
                        "Market Cap ($B)": round(market_cap_b, 2),
                        "Price": round(info.get("currentPrice", info.get("regularMarketPrice", 0)), 2)
                    })
            except:
                pass
            progress_bar.progress((i + 1) / len(passed_gmma))
            
    st.session_state.scan_results = final_results

# 6. Display Results and Charts
if st.session_state.scan_results:
    st.success(f"Found {len(st.session_state.scan_results)} stocks matching your criteria!")
    
    # Create a sortable dataframe
    df_results = pd.DataFrame(st.session_state.scan_results)
    st.dataframe(df_results.sort_values(by="Periods Compressed", ascending=False), use_container_width=True)
    
    st.markdown("---")
    st.subheader("📊 Visual Charting")
    
    # Dropdown to select a stock from the successful results
    passed_tickers = df_results["Ticker"].tolist()
    selected_ticker = st.selectbox("Select a stock to view its GMMA chart:", passed_tickers)
    
    if selected_ticker and st.session_state.full_data is not None:
        # Extract data for just this ticker
        ticker_data = pd.DataFrame({
            'Open': st.session_state.full_data['Open'][selected_ticker],
            'High': st.session_state.full_data['High'][selected_ticker],
            'Low': st.session_state.full_data['Low'][selected_ticker],
            'Close': st.session_state.full_data['Close'][selected_ticker],
        }).dropna()
        
        # Recalculate EMAs for plotting
        _, _, emas = evaluate_gmma(ticker_data['Close'])
        
        # Isolate the last 20 candles (10 is often too tight to see the GMMA trend direction)
        lookback = 20 
        plot_data = ticker_data.iloc[-lookback:]
        
        fig = go.Figure()
        
        # Add Candlesticks
        fig.add_trace(go.Candlestick(
            x=plot_data.index,
            open=plot_data['Open'], high=plot_data['High'],
            low=plot_data['Low'], close=plot_data['Close'],
            name="Price"
        ))
        
        # Add Short EMAs (Green)
        for p in [3, 5, 8, 10, 12, 15]:
            fig.add_trace(go.Scatter(x=plot_data.index, y=emas[p].iloc[-lookback:], line=dict(color='green', width=1), name=f"EMA {p}", hoverinfo='none'))
            
        # Add Long EMAs (Red)
        for p in [30, 35, 40, 45, 50, 60]:
            fig.add_trace(go.Scatter(x=plot_data.index, y=emas[p].iloc[-lookback:], line=dict(color='red', width=1), name=f"EMA {p}", hoverinfo='none'))

        fig.update_layout(
            title=f"{selected_ticker} - Last {lookback} Periods GMMA",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            height=600,
            showlegend=False # Hiding legend because 12 lines makes it too cluttered
        )
        
        st.plotly_chart(fig, use_container_width=True)
elif st.session_state.full_data is not None:
    st.warning("No stocks met all the criteria right now. Try a different setup, or lower the Market Cap.")

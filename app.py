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

# 2. Get S&P 500 and NASDAQ 100 securely
@st.cache_data
def get_market_tickers():
    headers = {'User-Agent': 'Mozilla/5.0'}
    tickers = []
    
    # Get S&P 500
    try:
        sp_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp_html = requests.get(sp_url, headers=headers).text
        sp_df = pd.read_html(io.StringIO(sp_html))[0]
        tickers.extend(sp_df['Symbol'].tolist())
    except:
        pass
        
    # Get NASDAQ 100
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
        
    # Clean up tickers (Wikipedia uses dots, yfinance needs hyphens)
    clean_tickers = [t.replace('.', '-') for t in set(tickers) if type(t) == str]
    return clean_tickers if clean_tickers else ["AAPL", "MSFT", "NVDA", "SPY"]

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
        
    short_spread = max_s - min_s
    long_spread = max_l - min_l
    daily_compression = short_spread < (long_spread * 0.5)
    
    compression_count = 0
    for is_compressed in reversed(daily_compression.tolist()):
        if is_compressed:
            compression_count += 1
        else:
            break
            
    all_short_above_long = min_s.iloc[-1] > max_l.iloc[-1]
    mixed_short_long = (min_s.iloc[-1] <= max_l.iloc[-1]) and (max_s.iloc[-1] >= min_l.iloc[-1])
    
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
    broad_market = get_market_tickers()
    all_tickers = list(set(broad_market + custom_tickers))
    
    # Ensure at least 2 tickers to force yfinance to always return a MultiIndex DataFrame
    if len(all_tickers) < 2:
        all_tickers.append("SPY")
        
    data_period = "5y" if timeframe == "1wk" else "1y"
    
    st.info(f"Downloading historical data for {len(all_tickers)} tickers. Scanning for: **{scan_type}**...")
    
    data = yf.download(all_tickers, period=data_period, interval=timeframe, progress=False)
    st.session_state.full_data = data 
    
    passed_gmma = []
    
    for ticker in all_tickers:
        try:
            # Safely extract close prices whether it is a MultiIndex or not
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data['Close'].columns:
                    close_prices = data['Close'][ticker].dropna()
                else:
                    continue
            else:
                close_prices = data['Close'].dropna()
                
            chart_state, comp_days, emas = evaluate_gmma(close_prices)
            
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
    
    df_results = pd.DataFrame(st.session_state.scan_results)
    st.dataframe(df_results.sort_values(by="Periods Compressed", ascending=False), use_container_width=True)
    
    st.markdown("---")
    st.subheader("📊 Visual Charting")
    
    passed_tickers = df_results["Ticker"].tolist()
    selected_ticker = st.selectbox("Select a stock to view its GMMA chart:", passed_tickers)
    
    if selected_ticker and st.session_state.full_data is not None:
        try:
            if isinstance(st.session_state.full_data.columns, pd.MultiIndex):
                ticker_data = pd.DataFrame({
                    'Open': st.session_state.full_data['Open'][selected_ticker],
                    'High': st.session_state.full_data['High'][selected_ticker],
                    'Low': st.session_state.full_data['Low'][selected_ticker],
                    'Close': st.session_state.full_data['Close'][selected_ticker],
                }).dropna()
            else:
                ticker_data = st.session_state.full_data.dropna()
                
            _, _, emas = evaluate_gmma(ticker_data['Close'])
            
            lookback = 30 
            plot_data = ticker_data.iloc[-lookback:]
            
            fig = go.Figure()
            
            fig.add_trace(go.Candlestick(
                x=plot_data.index,
                open=plot_data['Open'], high=plot_data['High'],
                low=plot_data['Low'], close=plot_data['Close'],
                name="Price"
            ))
            
            for p in [3, 5, 8, 10, 12, 15]:
                fig.add_trace(go.Scatter(x=plot_data.index, y=emas[p].iloc[-lookback:], line=dict(color='green', width=1), name=f"EMA {p}", hoverinfo='none'))
                
            for p in [30, 35, 40, 45, 50, 60]:
                fig.add_trace(go.Scatter(x=plot_data.index, y=emas[p].iloc[-lookback:], line=dict(color='red', width=1), name=f"EMA {p}", hoverinfo='none'))

            fig.update_layout(
                title=f"{selected_ticker} - Last {lookback} Periods GMMA",
                yaxis_title="Price",
                xaxis_rangeslider_visible=False,
                height=600,
                showlegend=False 
            )
            
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.error("Could not generate chart for this ticker.")
elif st.session_state.full_data is not None:
    st.warning("No stocks met all the criteria right now. Try a different setup, or lower the Market Cap.")

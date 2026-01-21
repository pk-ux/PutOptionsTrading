import streamlit as st
import pandas as pd
import time
from options_screener import (
    load_config,
    calculate_metrics,
    screen_options,
    format_output,
    save_config_file,
    get_options_chain_massive,
    get_options_chain_yahoo,
    get_stock_price_massive,
    get_stock_price_yahoo,
)
from massive_api_client import massive_client
import os

# Page configuration
st.set_page_config(
    page_title="Put Options Screener",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Reduce top padding and compact sidebar
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    /* Compact sidebar */
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1rem;
    }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {
        gap: 0.3rem;
    }
    section[data-testid="stSidebar"] hr {
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'config' not in st.session_state:
    st.session_state.config = load_config()

if 'results' not in st.session_state:
    st.session_state.results = {}

if 'processing' not in st.session_state:
    st.session_state.processing = False

if 'stop_processing' not in st.session_state:
    st.session_state.stop_processing = False

if 'used_yahoo' not in st.session_state:
    # Track whether Yahoo Finance was used as a fallback in the last run
    st.session_state.used_yahoo = False

# ============================================================================
# Helper function to get live config from UI values
# ============================================================================
def get_live_config():
    """Build config from current UI widget values"""
    return {
        'data': {
            'symbols': st.session_state.config['data']['symbols']  # Already updated on change
        },
        'options_strategy': {
            'max_dte': st.session_state.max_dte,
            'min_dte': st.session_state.min_dte,
            'min_volume': st.session_state.min_volume,
            'min_open_interest': st.session_state.min_oi
        },
        'screening_criteria': {
            'min_annualized_return': st.session_state.min_return,
            'max_assignment_probability': st.session_state.max_assignment_prob
        },
        'output': st.session_state.config.get('output', {})
    }

# ============================================================================
# SIDEBAR - Configuration (Compact)
# ============================================================================
with st.sidebar:
    # Expiration & Liquidity in one row each
    st.caption("EXPIRATION (DTE)")
    col1, col2 = st.columns(2)
    with col1:
        min_dte = st.number_input("Min", min_value=0, max_value=364,
            value=st.session_state.config['options_strategy'].get('min_dte', 0), key='min_dte')
    with col2:
        max_dte = st.number_input("Max", min_value=1, max_value=365,
            value=st.session_state.config['options_strategy']['max_dte'], key='max_dte')
    
    st.caption("LIQUIDITY")
    col1, col2 = st.columns(2)
    with col1:
        min_volume = st.number_input("Min Vol", min_value=0, max_value=10000,
            value=st.session_state.config['options_strategy']['min_volume'], key='min_volume')
    with col2:
        min_oi = st.number_input("Min OI", min_value=0, max_value=10000,
            value=st.session_state.config['options_strategy']['min_open_interest'], key='min_oi')
    
    # Screening
    st.caption("SCREENING")
    col1, col2 = st.columns(2)
    with col1:
        min_return = st.number_input("Min Ret%", min_value=0.0, max_value=500.0,
            value=float(st.session_state.config['screening_criteria']['min_annualized_return']), 
            key='min_return', help="Minimum Annualized Return")
    with col2:
        max_assignment_prob = st.number_input("Max Prob%", min_value=5, max_value=50,
            value=int(st.session_state.config['screening_criteria'].get('max_assignment_probability', 20)),
            key='max_assignment_prob', help="Maximum Probability of Assignment")
    
    # Watchlist
    st.caption("WATCHLIST")
    current_symbols_text = ", ".join(st.session_state.config['data']['symbols'])
    symbols_input = st.text_area("Symbols", value=current_symbols_text, height=60,
        key='symbols_text_input', label_visibility="collapsed", placeholder="AAPL, TSLA...")
    
    if symbols_input:
        new_symbols = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]
        if new_symbols != st.session_state.config['data']['symbols']:
            st.session_state.config['data']['symbols'] = new_symbols
    
    # Save button
    if st.button("Save", use_container_width=True):
        config_to_save = get_live_config()
        save_config_file(config_to_save)
        st.success("Saved!")

# ============================================================================
# MAIN AREA
# ============================================================================

# Header
st.title("Put Options Screener")
st.caption("Discover profitable put option opportunities with real-time market data")

# Action Row
col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

with col1:
    selected_symbol = st.selectbox(
        "Select Stock",
        options=st.session_state.config['data']['symbols'],
        key='symbol_selector',
        label_visibility="collapsed"
    )

with col2:
    screen_single = st.button(
        "Screen Stock",
        disabled=st.session_state.processing,
        width="stretch",
        type="primary"
    )

with col3:
    screen_all = st.button(
        "Screen All",
        disabled=st.session_state.processing,
        width="stretch"
    )

with col4:
    if st.session_state.processing:
        if st.button("Stop", width="stretch"):
            st.session_state.stop_processing = True
            st.session_state.processing = False
            st.rerun()

# ============================================================================
# Processing Functions
# ============================================================================

def fetch_data_with_fallback(symbol, config):
    """
    Fetch current price and options chain, using Massive.com by default
    and automatically falling back to Yahoo Finance if needed.
    Returns (formatted_results_df or None, message, yahoo_used: bool)
    """
    yahoo_used = False

    # Price: try Massive first, then Yahoo
    current_price = get_stock_price_massive(symbol)
    if current_price is None:
        current_price = get_stock_price_yahoo(symbol)
        yahoo_used = True

    # Options chain: try Massive first, then Yahoo
    options = get_options_chain_massive(symbol, config)
    if options.empty:
        yahoo_chain = get_options_chain_yahoo(symbol, config)
        if not yahoo_chain.empty:
            options = yahoo_chain
            yahoo_used = True

    if options.empty:
        return None, f"No options data for {symbol}", yahoo_used

    options = calculate_metrics(options, current_price)
    filtered = screen_options(options, config)
    formatted = format_output(filtered, current_price)

    if not formatted.empty:
        return formatted, f"Found {len(formatted)} options for {symbol}", yahoo_used
    else:
        return None, f"No qualifying options for {symbol}", yahoo_used


def run_screening(symbols):
    """Run screening for given symbols"""
    st.session_state.processing = True
    st.session_state.stop_processing = False
    st.session_state.results = {}
    st.session_state.used_yahoo = False

    # Get live config from current UI values
    live_config = get_live_config()

    progress_bar = st.progress(0)
    status_text = st.empty()

    total = len(symbols)
    for i, symbol in enumerate(symbols):
        if st.session_state.stop_processing:
            status_text.warning("Screening stopped")
            break

        status_text.info(f"Processing {symbol}... ({i+1}/{total})")
        progress_bar.progress((i + 1) / total)

        try:
            result, message, yahoo_used = fetch_data_with_fallback(symbol, live_config)
        except Exception as e:
            result, message, yahoo_used = None, f"Error: {symbol} - {str(e)}", False

        if yahoo_used:
            st.session_state.used_yahoo = True

        if result is not None and not result.empty:
            st.session_state.results[symbol] = result

    # Create summary if multiple results
    if len(st.session_state.results) > 1:
        summary_rows = []
        for sym in st.session_state.results.keys():
            if sym != 'Summary':
                summary_rows.append(st.session_state.results[sym].iloc[0])
        if summary_rows:
            st.session_state.results['Summary'] = pd.DataFrame(summary_rows)

    progress_bar.empty()
    status_text.empty()
    st.session_state.processing = False
    st.rerun()

# Handle button clicks
if screen_single and selected_symbol:
    run_screening([selected_symbol])

if screen_all and st.session_state.config['data']['symbols']:
    run_screening(st.session_state.config['data']['symbols'])

# ============================================================================
# Results Display
# ============================================================================

def display_results_table(df, symbol_name, api_source=None):
    """Display results table"""
    if df.empty:
        st.info(f"No results for {symbol_name}")
        return
    
    display_df = df.copy().reset_index(drop=True)
    
    # Column mapping
    column_mapping = {
        'symbol': 'Symbol',
        'current_price': 'Price',
        'strike': 'Strike',
        'lastPrice': 'Premium',
        'volume': 'Vol',
        'open_interest': 'OI',
        'impliedVolatility': 'IV%',
        'delta': 'Delta',
        'annualized_return': 'Return%',
        'expiry': 'Expiry',
        'calendar_days': 'DTE'
    }
    
    if api_source == 'massive':
        column_mapping['theta'] = 'Decay'
    
    # Select and rename columns
    display_cols = [col for col in column_mapping.keys() if col in display_df.columns]
    display_df = display_df[display_cols]
    display_df = display_df.rename(columns=column_mapping)
    
    # Format columns
    if 'Price' in display_df.columns:
        display_df['Price'] = display_df['Price'].apply(lambda x: f"${x:.2f}")
    if 'Strike' in display_df.columns:
        display_df['Strike'] = display_df['Strike'].apply(lambda x: f"${x:.0f}")
    if 'Premium' in display_df.columns:
        display_df['Premium'] = display_df['Premium'].apply(lambda x: f"${x:.2f}")
    if 'Delta' in display_df.columns:
        display_df['Delta'] = display_df['Delta'].apply(lambda x: f"{x:.3f}")
    if 'Decay' in display_df.columns:
        display_df['Decay'] = display_df['Decay'].apply(lambda x: f"{x:.4f}")
    if 'Return%' in display_df.columns:
        display_df['Return%'] = display_df['Return%'].apply(lambda x: f"{x:.1f}%")
    if 'IV%' in display_df.columns:
        display_df['IV%'] = display_df['IV%'].apply(lambda x: f"{x:.1f}%")
    if 'Vol' in display_df.columns:
        display_df['Vol'] = display_df['Vol'].astype(int)
    if 'OI' in display_df.columns:
        display_df['OI'] = display_df['OI'].astype(int)
    if 'DTE' in display_df.columns:
        display_df['DTE'] = display_df['DTE'].astype(int)
    
    # Color coding for returns
    def highlight_returns(val):
        try:
            num = float(val.replace('%', ''))
            if num >= 50:
                return 'background-color: #28a745; color: white; font-weight: bold'
            elif num >= 30:
                return 'background-color: #ffc107; color: black; font-weight: bold'
        except:
            pass
        return ''
    
    if 'Return%' in display_df.columns:
        styled_df = display_df.style.map(highlight_returns, subset=['Return%'])
    else:
        styled_df = display_df.style
    
    # Calculate height based on rows (35px per row + 38px header)
    table_height = len(display_df) * 35 + 38
    st.dataframe(styled_df, width="stretch", hide_index=True, height=table_height)

# Show results
if st.session_state.results:
    st.divider()
    
    # Results header with dropdown
    col1, col2 = st.columns([4, 1])
    with col1:
        st.subheader("Results")
    
    # Build dropdown options
        dropdown_options = []
        if 'Summary' in st.session_state.results:
            dropdown_options.append("Summary")
        for symbol in st.session_state.results.keys():
            if symbol != 'Summary':
                dropdown_options.append(symbol)
        
    if dropdown_options:
        with col2:
            selected_view = st.selectbox(
                "View",
                options=dropdown_options,
                key='results_view_selector',
                label_visibility="collapsed"
            )
        
        if selected_view in st.session_state.results:
            display_results_table(
                st.session_state.results[selected_view],
                selected_view,
                'massive'  # Massive.com is the primary source for Greeks
            )

            # Yahoo Finance fallback disclaimer
            if st.session_state.used_yahoo:
                st.caption(
                    "Note: When Massive.com data was unavailable, prices or options "
                    "data were retrieved from Yahoo Finance."
                )
            
            # Show news for individual tickers (not Summary)
            if selected_view != 'Summary' and massive_client:
                st.caption("Latest News (Last 7 Days)")
                news_items = massive_client.get_ticker_news(selected_view, limit=10, max_age_days=7)
                if news_items:
                    for item in news_items:
                        date_str = f"**{item['date_display']}** - " if item.get('date_display') else ""
                        st.markdown(f"• {date_str}[{item['title']}]({item['url']})")
                else:
                    st.markdown("*No recent news in the last 7 days*")

elif not st.session_state.processing:
    # Empty state hint
    st.divider()
    st.info("Select a stock and click **Screen Stock** to find put options, or click **Screen All** to analyze your watchlist.")

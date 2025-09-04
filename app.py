import streamlit as st
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime
import asyncio
import concurrent.futures
from options_screener import (
    load_config, get_options_chain, calculate_metrics,
    screen_options, format_output, save_config_file, get_stock_price
)
import os

# Page configuration
st.set_page_config(
    page_title="Put Options Screener",
    page_icon="P",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'config' not in st.session_state:
    st.session_state.config = load_config()

if 'results' not in st.session_state:
    st.session_state.results = {}

if 'current_symbol' not in st.session_state:
    st.session_state.current_symbol = ""

if 'processing' not in st.session_state:
    st.session_state.processing = False

if 'progress_messages' not in st.session_state:
    st.session_state.progress_messages = []

if 'api_source' not in st.session_state:
    st.session_state.api_source = "alpaca"

def update_config():
    """Update configuration from form inputs"""
    st.session_state.config['options_strategy']['max_dte'] = st.session_state.max_dte
    st.session_state.config['options_strategy']['min_dte'] = st.session_state.min_dte
    st.session_state.config['options_strategy']['min_volume'] = st.session_state.min_volume
    st.session_state.config['options_strategy']['min_open_interest'] = st.session_state.min_oi
    st.session_state.config['screening_criteria']['min_annualized_return'] = st.session_state.min_return
    st.session_state.config['screening_criteria']['min_delta'] = st.session_state.min_delta
    st.session_state.config['screening_criteria']['max_delta'] = st.session_state.max_delta

def add_symbol():
    """Add new symbol to the list"""
    new_symbol = st.session_state.new_symbol_input.strip().upper()
    if new_symbol and new_symbol not in st.session_state.config['data']['symbols']:
        st.session_state.config['data']['symbols'].append(new_symbol)
        save_config_file(st.session_state.config)
        st.success(f"Added {new_symbol} to stock list")
        st.session_state.new_symbol_input = ""
    elif new_symbol in st.session_state.config['data']['symbols']:
        st.info(f"{new_symbol} is already in the list")

def save_settings():
    """Save current settings to config file"""
    update_config()
    
    # Parse and update symbols from text input
    if 'symbols_text_input' in st.session_state:
        symbols_text = st.session_state.symbols_text_input.strip()
        if symbols_text:
            # Parse comma-separated symbols and clean them
            symbols = [symbol.strip().upper() for symbol in symbols_text.split(',') if symbol.strip()]
            st.session_state.config['data']['symbols'] = symbols
        else:
            st.session_state.config['data']['symbols'] = []
    
    save_config_file(st.session_state.config)
    st.success("Settings and stock symbols saved successfully!")

def process_single_symbol(symbol, config, api_source="alpaca"):
    """Process a single symbol and return results"""
    try:
        # Get stock price using selected API
        current_price = get_stock_price(symbol, api_source)
        
        # Get options chain
        options = get_options_chain(symbol, config, api_source)
        
        if options.empty:
            return None, f"No options data found for {symbol}"
        
        # Calculate metrics
        options = calculate_metrics(options, current_price)
        
        # Screen options
        filtered = screen_options(options, config)
        
        # Format output
        formatted = format_output(filtered, current_price)
        
        if not formatted.empty:
            return formatted, f"{symbol} processing complete, found {len(formatted)} qualifying options"
        else:
            return None, f"No qualifying options found for {symbol}"
            
    except Exception as e:
        return None, f"Error processing {symbol}: {str(e)}"

def screen_symbols(symbols):
    """Screen multiple symbols with progress tracking"""
    st.session_state.processing = True
    st.session_state.results = {}
    st.session_state.progress_messages = []
    
    # Create progress bar and status container
    progress_bar = st.progress(0)
    status_container = st.empty()
    
    total_symbols = len(symbols)
    results = {}
    
    # Process symbols using ThreadPoolExecutor for parallel processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all tasks
        future_to_symbol = {
            executor.submit(process_single_symbol, symbol, st.session_state.config, st.session_state.api_source): symbol 
            for symbol in symbols
        }
        
        completed = 0
        for future in concurrent.futures.as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            completed += 1
            
            # Update progress
            progress = completed / total_symbols
            progress_bar.progress(progress)
            status_container.info(f"Processing {symbol}... ({completed}/{total_symbols})")
            
            try:
                result, message = future.result()
                if result is not None and not result.empty:
                    results[symbol] = result
                st.session_state.progress_messages.append(message)
            except Exception as e:
                st.session_state.progress_messages.append(f"Error processing {symbol}: {str(e)}")
    
    # Create summary if multiple symbols processed
    if len(symbols) > 1 and results:
        summary_rows = []
        for sym in symbols:
            if sym in results:
                summary_rows.append(results[sym].iloc[0])
        
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            results['Summary'] = summary_df
    
    st.session_state.results = results
    st.session_state.processing = False
    
    # Clear progress indicators
    progress_bar.empty()
    status_container.empty()
    
    # Show completion message
    if results:
        st.success(f"Screening completed! Found results for {len([k for k in results.keys() if k != 'Summary'])} symbols.")
    else:
        st.warning("No qualifying options found for any symbol.")

def display_results_table(df, symbol_name):
    """Display results table with color coding"""
    if df.empty:
        st.info(f"No results available for {symbol_name}")
        return
    
    st.subheader(f"{symbol_name} Screening Results")
    
    # Prepare display dataframe with proper column names
    display_df = df.copy().reset_index(drop=True)  # Reset index to ensure uniqueness
    
    column_mapping = {
        'symbol': 'Symbol',
        'current_price': 'Current Price',
        'strike': 'Strike Price',
        'lastPrice': 'Option Price',
        'volume': 'Volume',
        'open_interest': 'Open Interest',
        'impliedVolatility': 'Implied Volatility (%)',
        'delta': 'Delta',
        'annualized_return': 'Annualized Return (%)',
        'expiry': 'Expiration Date',
        'calendar_days': 'DTE'
    }
    
    # Rename columns that exist
    display_cols = [col for col in column_mapping.keys() if col in display_df.columns]
    display_df = display_df[display_cols]
    display_df = display_df.rename(columns=column_mapping)
    
    # Format numerical columns with explicit decimal places
    if 'Current Price' in display_df.columns:
        display_df['Current Price'] = display_df['Current Price'].apply(lambda x: f"{x:.2f}")
    if 'Strike Price' in display_df.columns:
        display_df['Strike Price'] = display_df['Strike Price'].apply(lambda x: f"{x:.2f}")
    if 'Option Price' in display_df.columns:
        display_df['Option Price'] = display_df['Option Price'].apply(lambda x: f"{x:.2f}")
    if 'Delta' in display_df.columns:
        display_df['Delta'] = display_df['Delta'].apply(lambda x: f"{x:.2f}")
    if 'Annualized Return (%)' in display_df.columns:
        display_df['Annualized Return (%)'] = display_df['Annualized Return (%)'].apply(lambda x: f"{x:.2f}")
    if 'Implied Volatility (%)' in display_df.columns:
        display_df['Implied Volatility (%)'] = display_df['Implied Volatility (%)'].apply(lambda x: f"{x:.2f}")
    if 'Volume' in display_df.columns:
        display_df['Volume'] = display_df['Volume'].astype(int)
    if 'Open Interest' in display_df.columns:
        display_df['Open Interest'] = display_df['Open Interest'].astype(int)
    if 'DTE' in display_df.columns:
        display_df['DTE'] = display_df['DTE'].astype(int)
    
    # Apply color coding using map function for the annualized return column
    def color_annualized_return(val):
        """Apply color coding to annualized return values"""
        try:
            # Convert string back to float for comparison
            numeric_val = float(val) if isinstance(val, str) else val
            if numeric_val >= 50:
                return 'background-color: #4CAF50; color: white; font-weight: bold'  # Green background with white text
            elif numeric_val >= 30:
                return 'background-color: #FFC107; color: black; font-weight: bold'  # Amber background with black text
        except (ValueError, TypeError):
            pass
        return ''
    
    # Apply styling only if Annualized Return column exists
    if 'Annualized Return (%)' in display_df.columns:
        styled_df = display_df.style.map(color_annualized_return, subset=['Annualized Return (%)'])
    else:
        styled_df = display_df.style
    
    st.dataframe(styled_df, width='stretch')

# Main application layout
st.title("Put Options Screener")

# API Data Source Selector
st.sidebar.header("Data Sources")
api_source = st.sidebar.radio(
    "Stock Prices Source:",
    options=["alpaca", "yahoo"],
    format_func=lambda x: "Alpaca (Real-time)" if x == "alpaca" else "Yahoo Finance (Free)",
    index=0 if st.session_state.api_source == "alpaca" else 1,
    help="Choose your data source for stock prices"
)
st.session_state.api_source = api_source

# Show what data comes from which API
st.sidebar.markdown("**Data Sources Used:**")
if api_source == "alpaca":
    st.sidebar.markdown("• **Stock Prices**: Alpaca (Real-time)")
    st.sidebar.markdown("• **Options Data**: Alpaca (Real chains)")
else:
    st.sidebar.markdown("• **Stock Prices**: Yahoo Finance")
    st.sidebar.markdown("• **Options Data**: Yahoo Finance (Real chains)")

# Show API connection status
if api_source == "alpaca":
    if os.getenv('ALPACA_API_KEY'):
        st.sidebar.success("Alpaca API Connected - Using same source for both stock prices and options data")
    else:
        st.sidebar.error("Alpaca API Keys Missing")
else:
    st.sidebar.success("Yahoo Finance Connected - Using same source for both stock prices and options data")

st.sidebar.info("**All data is real** - Selected API source provides both stock prices and options data consistently.")

st.sidebar.divider()

# Create tabs for main interface
tab1, tab2 = st.tabs(["Stock Symbols", "Screening Criteria"])

# Stock Symbols Tab
with tab1:
    st.header("Stock Symbol Selection")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Existing stock dropdown
        selected_symbol = st.selectbox(
            "Select Stock:",
            options=st.session_state.config['data']['symbols'],
            key='symbol_selector'
        )
        st.session_state.current_symbol = selected_symbol
    
    with col2:
        st.write("") # Spacer
    
    # Add new stock section
    st.subheader("Add New Stock")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        new_symbol = st.text_input(
            "Enter stock symbol (e.g., AAPL):",
            key='new_symbol_input'
        )
    
    with col2:
        st.write("")  # Spacer for alignment
        if st.button("Add", key='add_button'):
            add_symbol()
    
    # Action buttons
    st.subheader("Screening Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Screen Selected Stock", disabled=st.session_state.processing):
            if selected_symbol:
                screen_symbols([selected_symbol])
            else:
                st.warning("Please select a stock symbol first.")
    
    with col2:
        if st.button("Screen All Stocks", disabled=st.session_state.processing):
            if st.session_state.config['data']['symbols']:
                screen_symbols(st.session_state.config['data']['symbols'])
            else:
                st.warning("No stock symbols available.")

# Screening Criteria Tab
with tab2:
    st.header("Screening Criteria Configuration")
    
    # Light cards with strong contrast
    st.markdown("""
    <style>
    .stApp > div {
        padding-top: 0rem;
    }
    div[data-testid="stVerticalBlock"] > div.settings-card {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid #dee2e6;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    div[data-testid="stVerticalBlock"] > div.full-width-card {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid #dee2e6;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .settings-card h3, .full-width-card h3 {
        color: #212529 !important;
        margin-top: 0;
    }
    .settings-card .stTextArea label, .full-width-card .stTextArea label {
        color: #212529 !important;
    }
    .settings-card .stNumberInput label, .full-width-card .stNumberInput label {
        color: #212529 !important;
    }
    .settings-card p, .full-width-card p {
        color: #212529 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Stock Symbols - Full Width Card
    st.markdown('<div class="full-width-card">', unsafe_allow_html=True)
    st.subheader("Stock Symbols")
    current_symbols_text = ", ".join(st.session_state.config['data']['symbols'])
    symbols_input = st.text_area(
        "Stock Symbols (comma-separated):",
        value=current_symbols_text,
        help="Enter stock symbols separated by commas (e.g., AAPL, TSLA, NVDA, SPY)",
        key='symbols_text_input',
        height=100
    )
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Side-by-side cards for settings
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Options Strategy Settings")
        
        max_dte = st.number_input(
            "Max Days to Expiration:",
            min_value=1,
            max_value=365,
            value=st.session_state.config['options_strategy']['max_dte'],
            key='max_dte'
        )
        
        min_dte = st.number_input(
            "Min Days to Expiration:",
            min_value=0,
            max_value=364,
            value=st.session_state.config['options_strategy'].get('min_dte', 0),
            key='min_dte'
        )
        
        min_volume = st.number_input(
            "Minimum Volume:",
            min_value=0,
            max_value=10000,
            value=st.session_state.config['options_strategy']['min_volume'],
            key='min_volume'
        )
        
        min_oi = st.number_input(
            "Minimum Open Interest:",
            min_value=0,
            max_value=10000,
            value=st.session_state.config['options_strategy']['min_open_interest'],
            key='min_oi'
        )
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Screening Criteria Settings")
        
        min_return = st.number_input(
            "Min Annualized Return (%):",
            min_value=0.0,
            max_value=100.0,
            value=float(st.session_state.config['screening_criteria']['min_annualized_return']),
            key='min_return'
        )
        
        st.write("Delta Range:")
        col2a, col2b = st.columns(2)
        with col2a:
            min_delta = st.number_input(
                "Min Delta:",
                min_value=-1.0,
                max_value=0.0,
                value=float(st.session_state.config['screening_criteria']['min_delta']),
                step=0.05,
                key='min_delta'
            )
        with col2b:
            max_delta = st.number_input(
                "Max Delta:",
                min_value=-1.0,
                max_value=0.0,
                value=float(st.session_state.config['screening_criteria']['max_delta']),
                step=0.05,
                key='max_delta'
            )
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Save settings button
    if st.button("Save Settings"):
        save_settings()

# Results Display Section
if st.session_state.results:
    st.header("Screening Results")
    
    # Results selection dropdown
    result_options = list(st.session_state.results.keys())
    if 'Summary' in result_options:
        # Move Summary to front
        result_options.remove('Summary')
        result_options.insert(0, 'Summary')
    
    selected_result = st.selectbox(
        "Select results to display:",
        options=result_options,
        key='results_selector'
    )
    
    # Display selected results
    if selected_result and selected_result in st.session_state.results:
        display_results_table(st.session_state.results[selected_result], selected_result)

# Progress messages
if st.session_state.progress_messages:
    with st.expander("Processing Log", expanded=False):
        for message in st.session_state.progress_messages:
            if "Error" in message:
                st.error(message)
            elif "complete" in message or "found" in message:
                st.success(message)
            else:
                st.info(message)

# Processing indicator
if st.session_state.processing:
    st.info("Processing in progress...")

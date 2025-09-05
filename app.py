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

if 'stop_processing' not in st.session_state:
    st.session_state.stop_processing = False

if 'progress_messages' not in st.session_state:
    st.session_state.progress_messages = []

if 'api_source' not in st.session_state:
    st.session_state.api_source = "public"

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

def stop_processing():
    """Stop the current processing"""
    st.session_state.stop_processing = True
    st.session_state.processing = False

def screen_symbols(symbols):
    """Screen multiple symbols with progress tracking"""
    # Initialize processing state
    st.session_state.processing = True
    st.session_state.stop_processing = False
    st.session_state.results = {}
    st.session_state.progress_messages = []
    
    # Force UI refresh to show progress bar
    st.rerun()
    
def run_screening_process():
    """Background process for screening symbols"""
    if not hasattr(st.session_state, 'symbols_to_screen'):
        return
        
    symbols = st.session_state.symbols_to_screen
    total_symbols = len(symbols)
    results = {}
    
    # Update progress placeholders if they exist
    if hasattr(st.session_state, 'progress_placeholder') and hasattr(st.session_state, 'status_placeholder'):
        # Process symbols one by one with progress updates
        for i, symbol in enumerate(symbols):
            # Check if user wants to stop
            if st.session_state.get('stop_processing', False):
                st.session_state.status_placeholder.warning("🛑 Processing stopped by user")
                break
                
            # Update progress
            progress = i / total_symbols
            status_text = f"Processing {symbol}... ({i+1}/{total_symbols})"
            
            st.session_state.progress_placeholder.progress(progress)
            st.session_state.status_placeholder.info(f"🔄 {status_text}")
            
            try:
                result, message = process_single_symbol(symbol, st.session_state.config, st.session_state.api_source)
                if result is not None and not result.empty:
                    results[symbol] = result
                st.session_state.progress_messages.append(message)
            except Exception as e:
                st.session_state.progress_messages.append(f"Error processing {symbol}: {str(e)}")
            
            # Update final progress for this symbol
            progress = (i + 1) / total_symbols
            st.session_state.progress_placeholder.progress(progress)
        
        # Clear progress placeholders
        st.session_state.progress_placeholder.empty()
        st.session_state.status_placeholder.empty()
    
    # Create summary if multiple symbols processed
    if len(symbols) > 1 and results:
        summary_rows = []
        for sym in symbols:
            if sym in results:
                summary_rows.append(results[sym].iloc[0])
        
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            results['Summary'] = summary_df
    
    # Complete processing
    st.session_state.results = results
    st.session_state.processing = False
    
    # Clean up
    del st.session_state.symbols_to_screen
    if hasattr(st.session_state, 'progress_placeholder'):
        del st.session_state.progress_placeholder
    if hasattr(st.session_state, 'status_placeholder'):
        del st.session_state.status_placeholder

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
        'gamma': 'Gamma',
        'theta': 'Theta',
        'vega': 'Vega',
        'rho': 'Rho',
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
        display_df['Delta'] = display_df['Delta'].apply(lambda x: f"{x:.3f}")
    if 'Gamma' in display_df.columns:
        display_df['Gamma'] = display_df['Gamma'].apply(lambda x: f"{x:.4f}")
    if 'Theta' in display_df.columns:
        display_df['Theta'] = display_df['Theta'].apply(lambda x: f"{x:.4f}")
    if 'Vega' in display_df.columns:
        display_df['Vega'] = display_df['Vega'].apply(lambda x: f"{x:.4f}")
    if 'Rho' in display_df.columns:
        display_df['Rho'] = display_df['Rho'].apply(lambda x: f"{x:.4f}")
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
    options=["alpaca", "yahoo", "public"],
    format_func=lambda x: "Alpaca (Real-time)" if x == "alpaca" else ("Yahoo Finance (Free)" if x == "yahoo" else "Public.com (Real-time)"),
    index=0 if st.session_state.api_source == "alpaca" else (1 if st.session_state.api_source == "yahoo" else 2),
    help="Choose your data source for stock prices"
)
st.session_state.api_source = api_source

# Show what data comes from which API
st.sidebar.markdown("**Data Sources Used:**")
if api_source == "alpaca":
    st.sidebar.markdown("• **Stock Prices**: Alpaca (Real-time)")
    st.sidebar.markdown("• **Options Data**: Alpaca (Real chains)")
elif api_source == "public":
    st.sidebar.markdown("• **Stock Prices**: Public.com (Real-time)")
    st.sidebar.markdown("• **Options Data**: Public.com (Real chains)")
else:
    st.sidebar.markdown("• **Stock Prices**: Yahoo Finance")
    st.sidebar.markdown("• **Options Data**: Yahoo Finance (Real chains)")

# Show API connection status
if api_source == "alpaca":
    if os.getenv('ALPACA_API_KEY'):
        st.sidebar.success("Alpaca API Connected - Using same source for both stock prices and options data")
    else:
        st.sidebar.error("Alpaca API Keys Missing")
elif api_source == "public":
    if os.getenv('PUBLIC_ACCESS_TOKEN') and os.getenv('PUBLIC_ACCOUNT_ID'):
        st.sidebar.success("Public.com API Connected - Using same source for both stock prices and options data")
    else:
        st.sidebar.error("Public.com API Keys Missing")
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
    
    # Buttons in a single row - compact left-aligned layout
    col1, col2, col3, col4 = st.columns([2, 2, 1.5, 6])
    
    with col1:
        if st.button("Screen Selected Stock", disabled=st.session_state.processing):
            if selected_symbol:
                st.session_state.symbols_to_screen = [selected_symbol]
                screen_symbols([selected_symbol])
            else:
                st.warning("Please select a stock symbol first.")
    
    with col2:
        if st.button("Screen All Stocks", disabled=st.session_state.processing):
            if st.session_state.config['data']['symbols']:
                st.session_state.symbols_to_screen = st.session_state.config['data']['symbols']
                screen_symbols(st.session_state.config['data']['symbols'])
            else:
                st.warning("No stock symbols available.")
    
    # Stop button appears in third column when processing
    with col3:
        if st.session_state.processing:
            if st.button("🛑 Stop", type="secondary", key="stop_btn_inline"):
                stop_processing()
                st.rerun()
        else:
            st.write("")  # Empty space when not processing
    
    with col4:
        st.write("")  # Spacer to push buttons left
    
    # Progress bar and status - left aligned below buttons
    if hasattr(st.session_state, 'processing') and st.session_state.processing:
        # Create progress placeholders
        progress_placeholder = st.empty()
        status_placeholder = st.empty()
        
        # Show immediate progress feedback
        progress_placeholder.progress(0.0)
        status_placeholder.info("🔄 Starting screening...")
        
        # Store placeholders for updates
        st.session_state.progress_placeholder = progress_placeholder
        st.session_state.status_placeholder = status_placeholder
        
        # Run the actual screening process
        run_screening_process()
    elif hasattr(st.session_state, 'results') and st.session_state.results and not st.session_state.get('processing', False):
        # Show completion status when done
        num_results = len([k for k in st.session_state.results.keys() if k != 'Summary'])
        st.success(f"✅ Screening completed! Found results for {num_results} symbols.")

# Screening Criteria Tab
with tab2:
    st.header("Screening Criteria Configuration")
    
    # Stock Symbols - Full Width Container
    with st.container():
        st.subheader("Stock Symbols")
        current_symbols_text = ", ".join(st.session_state.config['data']['symbols'])
        symbols_input = st.text_area(
            "Stock Symbols (comma-separated):",
            value=current_symbols_text,
            help="Enter stock symbols separated by commas (e.g., AAPL, TSLA, NVDA, SPY)",
            key='symbols_text_input',
            height=100
        )
    
    st.divider()
    
    # Side-by-side containers for settings
    col1, col2 = st.columns(2)
    
    with col1:
        with st.container():
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
    
    with col2:
        with st.container():
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
    
    st.divider()
    
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

# Remove old processing indicator - now handled in main section

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
    page_icon=":chart_with_downwards_trend:",
    layout="wide"
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
    st.session_state.api_source = "yahoo"

def update_config():
    """Update configuration from form inputs"""
    st.session_state.config['options_strategy']['max_dte'] = st.session_state.max_dte
    st.session_state.config['options_strategy']['min_dte'] = st.session_state.min_dte
    st.session_state.config['options_strategy']['min_volume'] = st.session_state.min_volume
    st.session_state.config['options_strategy']['min_open_interest'] = st.session_state.min_oi
    st.session_state.config['screening_criteria']['min_annualized_return'] = st.session_state.min_return
    # Delta values are already negative from the input
    st.session_state.config['screening_criteria']['min_delta'] = st.session_state.min_delta
    st.session_state.config['screening_criteria']['max_delta'] = st.session_state.max_delta


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
    st.session_state.symbols_to_screen = symbols
    
    # Trigger UI refresh to start progress tracking
    st.rerun()
    
def run_screening_process():
    """Background process for screening symbols with real-time results updates"""
    if not hasattr(st.session_state, 'symbols_to_screen'):
        return
        
    symbols = st.session_state.symbols_to_screen
    total_symbols = len(symbols)
    
    # Initialize results if not already done
    if not hasattr(st.session_state, 'results'):
        st.session_state.results = {}
    
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
                    # Update results immediately for real-time display
                    st.session_state.results[symbol] = result
                    
                    # Create/update summary for multiple symbols
                    if len(symbols) > 1:
                        summary_rows = []
                        for processed_symbol in st.session_state.results.keys():
                            if processed_symbol != 'Summary' and processed_symbol in st.session_state.results:
                                summary_rows.append(st.session_state.results[processed_symbol].iloc[0])
                        
                        if summary_rows:
                            summary_df = pd.DataFrame(summary_rows)
                            st.session_state.results['Summary'] = summary_df
                    
                    # DON'T call st.rerun() here - it restarts the entire process!
                    # Results will show after all processing is complete
                    
                st.session_state.progress_messages.append(message)
            except Exception as e:
                st.session_state.progress_messages.append(f"Error processing {symbol}: {str(e)}")
            
            # Update final progress for this symbol
            progress = (i + 1) / total_symbols
            st.session_state.progress_placeholder.progress(progress)
        
        # Clear progress placeholders
        st.session_state.progress_placeholder.empty()
        st.session_state.status_placeholder.empty()
    
    # Complete processing
    st.session_state.processing = False
    
    # Debug: Log what we found
    num_results = len([k for k in st.session_state.results.keys() if k != 'Summary'])
    print(f"DEBUG: Screening complete. Found results for {num_results} symbols")
    print(f"DEBUG: Results keys: {list(st.session_state.results.keys())}")
    if st.session_state.results:
        for symbol, data in st.session_state.results.items():
            print(f"DEBUG: {symbol} has {len(data) if hasattr(data, '__len__') else 'N/A'} rows")
    
    # Clean up
    del st.session_state.symbols_to_screen
    if hasattr(st.session_state, 'progress_placeholder'):
        del st.session_state.progress_placeholder
    if hasattr(st.session_state, 'status_placeholder'):
        del st.session_state.status_placeholder
    
    # Force UI refresh to re-enable buttons
    st.rerun()

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
        'open_interest': 'OI',
        'impliedVolatility': 'IV (%)',
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
    if 'IV (%)' in display_df.columns:
        display_df['IV (%)'] = display_df['IV (%)'].apply(lambda x: f"{x:.2f}")
    if 'Volume' in display_df.columns:
        display_df['Volume'] = display_df['Volume'].astype(int)
    if 'OI' in display_df.columns:
        display_df['OI'] = display_df['OI'].astype(int)
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
    
    st.dataframe(styled_df, width="stretch")

# Main application layout with Stockpeers-inspired design
st.markdown("# 📉 Put Options Screener")
st.markdown("*Discover profitable put option opportunities with real-time market data.*")

st.markdown("")  # Add some space

# Actions Card - Top Left
actions_card = st.container(border=True)
with actions_card:
    st.subheader("▶️ Actions")
    
    # Stock selection dropdown in actions card
    selected_symbol = st.selectbox(
        "Choose stock to screen:",
        options=st.session_state.config['data']['symbols'],
        key='symbol_selector',
        placeholder="Select a stock symbol"
    )
    st.session_state.current_symbol = selected_symbol
    
    # Create columns for action buttons  
    action_cols = st.columns(3)
    
    with action_cols[0]:
        if st.button("Screen Selected Stock", disabled=st.session_state.processing, width="stretch"):
            if selected_symbol:
                st.session_state.symbols_to_screen = [selected_symbol]
                screen_symbols([selected_symbol])
            else:
                st.warning("Please select a stock symbol first.")
    
    with action_cols[1]:
        if st.button("Screen All Stocks", disabled=st.session_state.processing, width="stretch"):
            if st.session_state.config['data']['symbols']:
                st.session_state.symbols_to_screen = st.session_state.config['data']['symbols']
                screen_symbols(st.session_state.config['data']['symbols'])
            else:
                st.warning("No stock symbols available.")
    
    with action_cols[2]:
        # Stop button when processing
        if st.session_state.processing:
            if st.button("🛑 Stop Screening", type="secondary", width="stretch", key="stop_btn_inline"):
                stop_processing()
                st.rerun()
        else:
            st.markdown("")  # Empty space when not processing

st.markdown("")  # Add space

# Results display - Full width (moved to below Actions)
if not st.session_state.processing and hasattr(st.session_state, 'results') and st.session_state.results:
    # Full width results container
    results_container = st.container(border=True)
    with results_container:
        st.markdown("## 📊 Screening Results")
        
        # Create dropdown options - Summary + individual tickers
        dropdown_options = []
        if 'Summary' in st.session_state.results:
            dropdown_options.append("Summary")
        
        # Add individual ticker options
        for symbol in st.session_state.results.keys():
            if symbol != 'Summary':
                dropdown_options.append(symbol)
        
        # Default to Summary if available, otherwise first ticker
        default_selection = "Summary" if "Summary" in dropdown_options else dropdown_options[0]
        
        # Initialize selected view in session state if not exists
        if 'selected_results_view' not in st.session_state:
            st.session_state.selected_results_view = default_selection
        
        # Dropdown to select which results to view
        selected_view = st.selectbox(
            "View results for:",
            options=dropdown_options,
            index=dropdown_options.index(st.session_state.selected_results_view) if st.session_state.selected_results_view in dropdown_options else 0,
            key='results_view_selector'
        )
        st.session_state.selected_results_view = selected_view
        
        # Display the selected table
        if selected_view in st.session_state.results:
            display_results_table(st.session_state.results[selected_view], selected_view)

elif not hasattr(st.session_state, 'results') or not st.session_state.results:
    # Full width getting started container
    getting_started_container = st.container(border=True)
    with getting_started_container:
        st.markdown("## 💡 Getting Started")
        st.markdown("""
        1. **Choose your data source** in the configuration section below
        2. **Select a stock symbol** in the Actions section above
        3. **Click "Screen Selected Stock"** or "Screen All Stocks"  
        4. **Review results** and adjust configuration as needed
        """)

# Progress tracking
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
    # Note: run_screening_process() will set processing=False and call st.rerun() when done
    run_screening_process()

# Bottom configuration section
st.markdown("")  # Add space

st.markdown("## 🔧 Screening Configuration")

# Configuration in clean containers
config_cols = st.columns(4)

# Stock Symbols Configuration
with config_cols[0].container(border=True):
    st.subheader("📋 Stock Symbols")
    current_symbols_text = ", ".join(st.session_state.config['data']['symbols'])
    symbols_input = st.text_area(
        "Enter symbols (comma-separated):",
        value=current_symbols_text,
        help="e.g., AAPL, TSLA, NVDA, SPY",
        key='symbols_text_input',
        height=100
    )
    
    # Update symbols from text input
    if symbols_input:
        new_symbols = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]
        if new_symbols != st.session_state.config['data']['symbols']:
            st.session_state.config['data']['symbols'] = new_symbols

# Data Source Configuration (moved below Stock Symbols Config)
with config_cols[1].container(border=True):
    st.subheader("🔗 Data Source")
    
    # API Source selection
    api_source = st.radio(
        "Choose your data source:",
        options=["public", "alpaca", "yahoo"],
        format_func=lambda x: "Public.com (Real-time)" if x == "public" else ("Alpaca (Real-time)" if x == "alpaca" else "Yahoo Finance (Free)"),
        index=2 if st.session_state.api_source == "yahoo" else (0 if st.session_state.api_source == "public" else 1),
        help="Choose your data source for stock prices and options data"
    )
    st.session_state.api_source = api_source
    
    # Show connection status
    if api_source == "alpaca":
        if os.getenv('ALPACA_API_KEY'):
            st.success("✅ Alpaca Connected")
        else:
            st.error("❌ Alpaca Keys Missing")
    elif api_source == "public":
        if os.getenv('PUBLIC_ACCESS_TOKEN') and os.getenv('PUBLIC_ACCOUNT_ID'):
            st.success("✅ Public.com Connected")
        else:
            st.error("❌ Public.com Keys Missing")
    else:
        st.success("✅ Yahoo Finance Connected")

# Options Strategy Settings  
with config_cols[2].container(border=True):
    st.subheader("📅 Strategy Settings")
    
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

# Screening Criteria Settings
with config_cols[3].container(border=True):
    st.subheader("🔍 Screening Criteria")
    
    min_return = st.number_input(
        "Min Annualized Return (%):",
        min_value=0.0,
        max_value=1000.0,
        value=st.session_state.config['screening_criteria']['min_annualized_return'],
        key='min_return'
    )
    
    min_delta = st.number_input(
        "Min Delta:",
        min_value=-1.0,
        max_value=0.0,
        value=float(st.session_state.config['screening_criteria']['min_delta']),
        key='min_delta',
        step=0.01
    )
    
    max_delta = st.number_input(
        "Max Delta:",
        min_value=-1.0,
        max_value=0.0,
        value=float(st.session_state.config['screening_criteria']['max_delta']),
        key='max_delta',
        step=0.01
    )
    
    # Save button
    if st.button("Save Settings", width="stretch"):
        save_settings()

st.markdown("")  # Add space

# Results section moved above - this space intentionally left empty

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

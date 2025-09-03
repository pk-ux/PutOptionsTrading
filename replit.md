# Put Options Screener

## Overview

A Streamlit-based web application for screening put options across multiple stock symbols. The application identifies profitable put option opportunities by analyzing options chains, calculating metrics like annualized returns and delta values, and filtering based on configurable criteria. Users can screen options across a customizable list of stock symbols with real-time data from Yahoo Finance.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Streamlit Framework**: Single-page web application with reactive UI components
- **Session State Management**: Persistent storage of configuration, results, and processing status across user interactions
- **Wide Layout Configuration**: Optimized for displaying tabular options data with expandable sidebar for controls
- **Real-time Updates**: Progress tracking and dynamic result display during screening operations

### Backend Architecture
- **Modular Design**: Core screening logic separated into `options_screener.py` module for reusability
- **Asynchronous Processing**: Concurrent futures implementation for parallel options chain processing across multiple symbols
- **Configuration-Driven**: JSON-based configuration system allowing runtime parameter adjustments
- **Data Processing Pipeline**: Sequential workflow of data fetching → metrics calculation → screening → formatting

### Data Layer
- **Yahoo Finance Integration**: Real-time options chain data retrieval using yfinance library
- **In-Memory Processing**: Pandas DataFrames for options data manipulation and analysis
- **JSON Configuration Storage**: File-based persistence of user preferences and screening parameters
- **Session-Based Results Caching**: Temporary storage of screening results in Streamlit session state

### Options Analytics Engine
- **Black-Scholes Metrics**: Delta calculation and other Greek computations using scipy.stats
- **Annualized Return Calculations**: Time-value based return projections considering days to expiration
- **Multi-Criteria Filtering**: Configurable screening based on volume, open interest, delta ranges, and return thresholds
- **Risk Assessment**: Delta-based risk categorization for put option strategies

## External Dependencies

### Financial Data Services
- **Yahoo Finance API**: Primary data source for stock prices and options chains via yfinance library
- **Real-time Market Data**: Live options pricing, volume, and open interest data

### Python Libraries
- **Streamlit**: Web application framework for interactive dashboard
- **Pandas**: Data manipulation and analysis
- **NumPy**: Numerical computations for options metrics
- **SciPy**: Statistical functions for options pricing models
- **yfinance**: Yahoo Finance data access wrapper

### Development Tools
- **JSON**: Configuration file format for persistent settings
- **Concurrent Futures**: Python standard library for parallel processing
- **DateTime**: Standard library for expiration date calculations and time-based metrics
#!/usr/bin/env python
"""
Backtest example using the EasyTrade framework.

This example demonstrates how to:
1. Load historical data
2. Configure a strategy
3. Run a backtest
4. Analyze results
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import os
import sys

# Add the parent directory to the path to import easytrade modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from easytrade.runner import EasyTradeRunner
from easytrade.strategies.momentum_strategy import MomentumStrategy

def load_sample_data():
    """
    Load sample price data for SPY and SPX.
    
    In a real-world scenario, you would load your actual historical data.
    
    Returns:
        Dictionary mapping symbol to DataFrame with OHLCV data
    """
    # Generate sample data for SPY with a slight upward trend
    n_days = 60
    dates = pd.date_range(start='2023-01-01', periods=n_days*78, freq='5min')
    dates = dates[dates.indexer_between_time('9:30', '16:00')]  # Market hours only
    
    # Create SPY data
    spy_base = 400.0  # Starting price
    spy_trend = np.linspace(0, 5, len(dates))  # Overall upward trend
    spy_cycle = 3.0 * np.sin(np.linspace(0, 8*np.pi, len(dates)))  # Cyclic pattern
    spy_noise = np.random.normal(0, 1.0, len(dates))  # Random noise
    
    spy_price = spy_base + spy_trend + spy_cycle + spy_noise
    
    spy_data = pd.DataFrame({
        'datetime': dates,
        'open': spy_price,
        'high': spy_price + np.random.uniform(0.1, 0.5, len(dates)),
        'low': spy_price - np.random.uniform(0.1, 0.5, len(dates)),
        'close': spy_price + np.random.uniform(-0.2, 0.2, len(dates)),
        'volume': np.random.randint(10000, 100000, len(dates))
    })
    
    # Create SPX data (similar pattern but 10x the value)
    spx_base = 4000.0  # Starting price
    spx_trend = np.linspace(0, 50, len(dates))  # Overall upward trend
    spx_cycle = 30.0 * np.sin(np.linspace(0, 8*np.pi, len(dates)))  # Cyclic pattern
    spx_noise = np.random.normal(0, 10.0, len(dates))  # Random noise
    
    spx_price = spx_base + spx_trend + spx_cycle + spx_noise
    
    spx_data = pd.DataFrame({
        'datetime': dates,
        'open': spx_price,
        'high': spx_price + np.random.uniform(1.0, 5.0, len(dates)),
        'low': spx_price - np.random.uniform(1.0, 5.0, len(dates)),
        'close': spx_price + np.random.uniform(-2.0, 2.0, len(dates)),
        'volume': np.random.randint(5000, 50000, len(dates))
    })
    
    # Add some volatility events
    # Create a few days with higher volatility
    vol_periods = [
        (300, 400),  # Period 1
        (800, 900),  # Period 2
        (1500, 1600)  # Period 3
    ]
    
    for start, end in vol_periods:
        # SPY volatility
        spy_data.loc[start:end, 'high'] = spy_data.loc[start:end, 'open'] + np.random.uniform(0.5, 2.0, end-start+1)
        spy_data.loc[start:end, 'low'] = spy_data.loc[start:end, 'open'] - np.random.uniform(0.5, 2.0, end-start+1)
        spy_data.loc[start:end, 'close'] = spy_data.loc[start:end, 'open'] + np.random.uniform(-1.0, 1.0, end-start+1)
        spy_data.loc[start:end, 'volume'] = np.random.randint(50000, 200000, end-start+1)
        
        # SPX volatility
        spx_data.loc[start:end, 'high'] = spx_data.loc[start:end, 'open'] + np.random.uniform(5.0, 20.0, end-start+1)
        spx_data.loc[start:end, 'low'] = spx_data.loc[start:end, 'open'] - np.random.uniform(5.0, 20.0, end-start+1)
        spx_data.loc[start:end, 'close'] = spx_data.loc[start:end, 'open'] + np.random.uniform(-10.0, 10.0, end-start+1)
        spx_data.loc[start:end, 'volume'] = np.random.randint(25000, 100000, end-start+1)
    
    return {
        'SPY': spy_data,
        'SPX': spx_data
    }

def run_backtest():
    """Run a backtest using the momentum strategy."""
    # Load sample data
    print("Loading sample data...")
    data = load_sample_data()
    
    # Print data stats
    for symbol, df in data.items():
        print(f"{symbol} data: {len(df)} bars, date range: {df['datetime'].min()} to {df['datetime'].max()}")
    
    # Create strategy with custom config
    strategy_config = {
        # Trading parameters
        "position_size": 100,  # Number of shares to trade
        "min_profit_target": 0.01,  # 1% profit target
        "stop_loss": 0.005,  # 0.5% stop loss
        "max_position_duration": 60,  # 1 hour max position duration
        
        # Momentum parameters
        "momentum_threshold": 0.3,  # Lowered for more signals
        "momentum_lookback": 15,  # Shortened lookback period
        
        # SPX parameters
        "spx_consistency_threshold": 0.5,  # Lowered for more signals
        "spx_consecutive_bars": 2,  # Lowered for more signals
        
        # Filters and entry conditions
        "min_trade_spacing": 10,  # 10 minutes between trades
        "max_daily_trades": 8,  # Increased max trades per day
    }
    
    print("Creating momentum strategy...")
    strategy = MomentumStrategy(strategy_config)
    
    # Create runner in backtest mode
    print("Setting up backtest...")
    runner = EasyTradeRunner(mode="backtest")
    runner.setup_backtest(
        strategy=strategy,
        data=data,
        initial_capital=100000.0,
        commission=0.0005  # 0.05% commission
    )
    
    # Run the backtest
    print("Running backtest...")
    results = runner.run()
    
    # Print results
    print("\nBacktest Results:")
    print(f"Initial Capital: ${results['initial_value']:.2f}")
    print(f"Final Value: ${results['final_value']:.2f}")
    print(f"PnL: ${results['pnl']:.2f} ({results['pnl_pct']:.2f}%)")
    
    # Plot results
    print("\nGenerating plots...")
    runner.plot(style='candle')
    
    return results

if __name__ == "__main__":
    print("EasyTrade Backtest Example")
    print("==========================")
    
    try:
        results = run_backtest()
        print("\nBacktest completed successfully.")
    except Exception as e:
        print(f"\nError during backtest: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 
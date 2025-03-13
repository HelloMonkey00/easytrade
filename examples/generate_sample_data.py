#!/usr/bin/env python
"""
Script to generate sample OHLCV data for testing.
"""
import os
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def generate_random_walk(start_price: float, days: int, volatility: float = 0.01,
                        trend: float = 0.0001) -> pd.DataFrame:
    """
    Generate a random walk price series.
    
    Args:
        start_price: Starting price
        days: Number of days to generate
        volatility: Daily volatility
        trend: Daily trend
        
    Returns:
        DataFrame with OHLCV data
    """
    # Generate daily returns
    daily_returns = np.random.normal(trend, volatility, days)
    
    # Calculate price series
    prices = start_price * np.cumprod(1 + daily_returns)
    
    # Generate timestamps
    start_date = datetime.now() - timedelta(days=days)
    timestamps = [start_date + timedelta(days=i) for i in range(days)]
    
    # Generate OHLCV data
    data = []
    for i, price in enumerate(prices):
        # Generate intraday volatility
        intraday_vol = volatility * price * 0.5
        
        # Generate OHLC
        open_price = price
        high_price = price + abs(np.random.normal(0, intraday_vol))
        low_price = price - abs(np.random.normal(0, intraday_vol))
        close_price = np.random.normal(price, intraday_vol)
        
        # Ensure high >= open, close, low and low <= open, close
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        
        # Generate volume
        volume = np.random.lognormal(10, 1)
        
        data.append({
            'timestamp': timestamps[i],
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
    
    return pd.DataFrame(data)


def generate_sine_wave(start_price: float, days: int, amplitude: float = 10.0,
                      period: float = 50.0, volatility: float = 0.01,
                      trend: float = 0.0001) -> pd.DataFrame:
    """
    Generate a sine wave price series with noise.
    
    Args:
        start_price: Starting price
        days: Number of days to generate
        amplitude: Amplitude of sine wave
        period: Period of sine wave in days
        volatility: Daily volatility
        trend: Daily trend
        
    Returns:
        DataFrame with OHLCV data
    """
    # Generate timestamps
    start_date = datetime.now() - timedelta(days=days)
    timestamps = [start_date + timedelta(days=i) for i in range(days)]
    
    # Generate sine wave
    t = np.arange(days)
    sine_wave = amplitude * np.sin(2 * np.pi * t / period)
    
    # Generate trend
    trend_series = np.arange(days) * trend
    
    # Generate noise
    noise = np.random.normal(0, volatility * start_price, days)
    
    # Combine components
    prices = start_price + sine_wave + trend_series + noise
    
    # Generate OHLCV data
    data = []
    for i, price in enumerate(prices):
        # Generate intraday volatility
        intraday_vol = volatility * price * 0.5
        
        # Generate OHLC
        open_price = price
        high_price = price + abs(np.random.normal(0, intraday_vol))
        low_price = price - abs(np.random.normal(0, intraday_vol))
        close_price = np.random.normal(price, intraday_vol)
        
        # Ensure high >= open, close, low and low <= open, close
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        
        # Generate volume
        volume = np.random.lognormal(10, 1)
        
        data.append({
            'timestamp': timestamps[i],
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
    
    return pd.DataFrame(data)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Generate sample OHLCV data for testing')
    
    parser.add_argument('--output-dir', type=str, default='data',
                       help='Directory to save output files')
    parser.add_argument('--symbols', type=str, nargs='+', default=['AAPL', 'MSFT', 'GOOGL'],
                       help='Symbols to generate data for')
    parser.add_argument('--days', type=int, default=252,
                       help='Number of days to generate')
    parser.add_argument('--start-price', type=float, default=100.0,
                       help='Starting price')
    parser.add_argument('--volatility', type=float, default=0.015,
                       help='Daily volatility')
    parser.add_argument('--trend', type=float, default=0.0002,
                       help='Daily trend')
    parser.add_argument('--pattern', type=str, default='random',
                       choices=['random', 'sine'],
                       help='Price pattern to generate')
    
    return parser.parse_args()


def main():
    """Generate sample data."""
    # Parse command line arguments
    args = parse_args()
    
    # Create output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    # Generate data for each symbol
    for symbol in args.symbols:
        print(f"Generating data for {symbol}...")
        
        # Generate price series
        if args.pattern == 'random':
            df = generate_random_walk(
                start_price=args.start_price,
                days=args.days,
                volatility=args.volatility,
                trend=args.trend
            )
        else:  # sine
            df = generate_sine_wave(
                start_price=args.start_price,
                days=args.days,
                amplitude=args.start_price * 0.1,
                period=50.0,
                volatility=args.volatility,
                trend=args.trend
            )
        
        # Save to CSV
        output_file = os.path.join(args.output_dir, f"{symbol}.csv")
        df.to_csv(output_file, index=False)
        print(f"Saved {len(df)} rows to {output_file}")


if __name__ == '__main__':
    main() 
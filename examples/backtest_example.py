#!/usr/bin/env python
"""
Example script to run a backtest using the EasyTrade framework.
"""
import os
import sys
import logging
import argparse
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Add parent directory to path to import easytrade
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from easytrade.core.engine import TradingEngine
from easytrade.core.risk_manager import RiskManager
from easytrade.data.csv_provider import CSVDataProvider
from easytrade.execution.backtest import BacktestExecutionProvider
from easytrade.strategies.moving_average import MovingAverageCrossoverStrategy
from easytrade.utils.logger import setup_logger
from easytrade.utils.performance import calculate_performance_metrics, plot_equity_curve, plot_drawdown


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run a backtest using the EasyTrade framework')
    
    parser.add_argument('--data-dir', type=str, required=True,
                       help='Directory containing CSV data files')
    parser.add_argument('--symbols', type=str, nargs='+', required=True,
                       help='Symbols to trade')
    parser.add_argument('--short-window', type=int, default=10,
                       help='Short-term moving average window')
    parser.add_argument('--long-window', type=int, default=50,
                       help='Long-term moving average window')
    parser.add_argument('--position-size', type=float, default=0.1,
                       help='Position size as a fraction of portfolio value')
    parser.add_argument('--initial-cash', type=float, default=100000.0,
                       help='Initial cash balance')
    parser.add_argument('--commission-rate', type=float, default=0.001,
                       help='Commission rate as a decimal')
    parser.add_argument('--log-level', type=str, default='DEBUG',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Logging level')
    parser.add_argument('--output-dir', type=str, default='output',
                       help='Directory to save output files')
    
    return parser.parse_args()


def main():
    """Run the backtest."""
    # Parse command line arguments
    args = parse_args()
    
    # Set up logging
    log_level = getattr(logging, args.log_level)
    logger = setup_logger('backtest', log_level=log_level)
    
    # Create output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    # Create components
    data_provider = CSVDataProvider(args.data_dir)
    execution_provider = BacktestExecutionProvider(
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate
    )
    risk_manager = RiskManager(
        max_position_size=args.position_size * 2,  # Allow some flexibility
        max_order_size=args.position_size * 2,
        max_concentration=0.5,
        max_drawdown=0.2
    )
    strategy = MovingAverageCrossoverStrategy(
        short_window=args.short_window,
        long_window=args.long_window,
        position_size=args.position_size
    )
    
    # Set symbols for strategy
    strategy.set_symbols(args.symbols)
    
    # Create trading engine
    engine = TradingEngine(
        data_provider=data_provider,
        execution_provider=execution_provider,
        strategy=strategy,
        risk_manager=risk_manager
    )
    
    # Set engine reference in risk manager
    risk_manager.set_engine(engine)
    
    # Load data
    logger.info(f"Loading data from {args.data_dir}")
    data_provider.load_directory()
    
    # Check if data was loaded
    if not data_provider._data:
        logger.error("No data was loaded. Check if the data files exist and are in the correct format.")
        for symbol in args.symbols:
            file_path = os.path.join(args.data_dir, f"{symbol}.csv")
            if os.path.exists(file_path):
                logger.debug(f"File exists: {file_path}")
                # Try to load the file explicitly
                success = data_provider.load_csv_file(file_path, symbol)
                logger.debug(f"Explicit load of {file_path}: {'Success' if success else 'Failed'}")
            else:
                logger.error(f"File does not exist: {file_path}")
    
    # Set replay speed (faster for backtesting)
    data_provider.set_replay_speed(10.0)
    
    # Run backtest
    logger.info("Starting backtest")
    engine.run_backtest()
    
    # Get performance metrics
    metrics = execution_provider.get_performance_metrics()
    
    # Print performance metrics
    logger.info("Backtest completed")
    logger.info(f"Initial cash: ${metrics['initial_cash']:.2f}")
    logger.info(f"Final equity: ${metrics['final_equity']:.2f}")
    logger.info(f"P&L: ${metrics['pnl']:.2f} ({metrics['pnl_percent']:.2f}%)")
    logger.info(f"Number of trades: {metrics['num_trades']}")
    logger.info(f"Win ratio: {metrics['win_ratio']:.2f}")
    
    # Create equity curve
    equity_curve = []
    timestamps = []
    
    # Reset data provider and execution provider
    data_provider.reset()
    execution_provider.reset()
    
    # Make sure engine is not running
    if hasattr(engine, '_running') and engine._running:
        logger.debug("Stopping engine before second run")
        engine.stop()
    
    # Set up callback to record equity curve
    def record_equity(data):
        logger.debug(f"record_equity callback called with data for {len(data)} symbols")
        portfolio = execution_provider.get_portfolio()
        equity_curve.append(portfolio.equity)
        timestamps.append(list(data.values())[0].timestamp if data else datetime.now())
        logger.debug(f"Added equity point: {portfolio.equity} at {timestamps[-1]}")
    
    # Add callback to data provider
    data_provider.add_subscriber(record_equity)
    logger.debug("Added record_equity callback to data provider")
    
    # Run backtest again to record equity curve
    logger.info("Running backtest again to record equity curve")
    engine.run_backtest()
    
    # Check if we have any data points
    if not timestamps:
        logger.warning("No data points were recorded during the backtest. Cannot generate performance metrics or plots.")
        return
    
    # Calculate additional performance metrics
    days = (timestamps[-1] - timestamps[0]).days or 1
    perf_metrics = calculate_performance_metrics(equity_curve, days)
    
    # Print additional performance metrics
    logger.info(f"CAGR: {perf_metrics['cagr']:.2f}")
    logger.info(f"Sharpe ratio: {perf_metrics['sharpe_ratio']:.2f}")
    logger.info(f"Sortino ratio: {perf_metrics['sortino_ratio']:.2f}")
    logger.info(f"Max drawdown: {perf_metrics['max_drawdown']:.2f}")
    logger.info(f"Calmar ratio: {perf_metrics['calmar_ratio']:.2f}")
    
    # Plot equity curve
    equity_plot = plot_equity_curve(equity_curve, timestamps)
    equity_plot.savefig(os.path.join(args.output_dir, 'equity_curve.png'))
    
    # Plot drawdown
    drawdown_plot = plot_drawdown(equity_curve, timestamps)
    drawdown_plot.savefig(os.path.join(args.output_dir, 'drawdown.png'))
    
    logger.info(f"Plots saved to {args.output_dir}")


if __name__ == '__main__':
    main() 
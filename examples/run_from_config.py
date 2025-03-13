#!/usr/bin/env python
"""
Script to run a backtest using a configuration file.
"""
import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

# Add parent directory to path to import easytrade
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from easytrade.core.engine import TradingEngine
from easytrade.core.risk_manager import RiskManager
from easytrade.data.csv_provider import CSVDataProvider
from easytrade.execution.backtest import BacktestExecutionProvider
from easytrade.strategies.moving_average import MovingAverageCrossoverStrategy
from easytrade.utils.logger import setup_logger
from easytrade.utils.config import load_config
from easytrade.utils.performance import calculate_performance_metrics, plot_equity_curve, plot_drawdown


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run a backtest using a configuration file')
    
    parser.add_argument('--config', type=str, default='examples/config.yaml',
                       help='Path to configuration file')
    
    return parser.parse_args()


def create_data_provider(config):
    """Create a data provider based on configuration."""
    data_config = config.get('data_provider', {})
    provider_type = data_config.get('type', 'csv')
    
    if provider_type == 'csv':
        provider = CSVDataProvider(
            data_dir=data_config.get('data_dir', 'data'),
            date_format=data_config.get('date_format', '%Y-%m-%d %H:%M:%S'),
            timestamp_column=data_config.get('timestamp_column', 'timestamp'),
            ohlcv_columns=data_config.get('ohlcv_columns')
        )
        
        # Set replay speed
        replay_speed = data_config.get('replay_speed', 1.0)
        provider.set_replay_speed(replay_speed)
        
        return provider
    else:
        raise ValueError(f"Unsupported data provider type: {provider_type}")


def create_execution_provider(config):
    """Create an execution provider based on configuration."""
    exec_config = config.get('execution_provider', {})
    provider_type = exec_config.get('type', 'backtest')
    
    if provider_type == 'backtest':
        return BacktestExecutionProvider(
            initial_cash=exec_config.get('initial_cash', 100000.0),
            commission_rate=exec_config.get('commission_rate', 0.001)
        )
    else:
        raise ValueError(f"Unsupported execution provider type: {provider_type}")


def create_risk_manager(config):
    """Create a risk manager based on configuration."""
    risk_config = config.get('risk_manager', {})
    
    return RiskManager(
        max_position_size=risk_config.get('max_position_size', 0.1),
        max_order_size=risk_config.get('max_order_size', 0.05),
        max_concentration=risk_config.get('max_concentration', 0.25),
        max_drawdown=risk_config.get('max_drawdown', 0.1)
    )


def create_strategy(config):
    """Create a strategy based on configuration."""
    strategy_config = config.get('strategy', {})
    strategy_type = strategy_config.get('type', 'moving_average_crossover')
    parameters = strategy_config.get('parameters', {})
    
    if strategy_type == 'moving_average_crossover':
        return MovingAverageCrossoverStrategy(
            short_window=parameters.get('short_window', 10),
            long_window=parameters.get('long_window', 50),
            position_size=parameters.get('position_size', 0.1)
        )
    else:
        raise ValueError(f"Unsupported strategy type: {strategy_type}")


def setup_logging(config):
    """Set up logging based on configuration."""
    logging_config = config.get('logging', {})
    log_level = logging_config.get('level', 'INFO')
    log_file = logging_config.get('file')
    console_output = logging_config.get('console', True)
    
    return setup_logger(
        name='backtest',
        log_level=getattr(logging, log_level),
        log_file=log_file,
        console_output=console_output
    )


def main():
    """Run the backtest."""
    # Parse command line arguments
    args = parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set up logging
    logger = setup_logging(config)
    
    # Create output directory if it doesn't exist
    output_config = config.get('output', {})
    output_dir = output_config.get('directory', 'output')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Create components
    data_provider = create_data_provider(config)
    execution_provider = create_execution_provider(config)
    risk_manager = create_risk_manager(config)
    strategy = create_strategy(config)
    
    # Set symbols for strategy
    symbols = config.get('symbols', [])
    strategy.set_symbols(symbols)
    
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
    logger.info(f"Loading data for symbols: {', '.join(symbols)}")
    data_provider.load_directory()
    
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
    equity_plot.savefig(os.path.join(output_dir, 'equity_curve.png'))
    
    # Plot drawdown
    drawdown_plot = plot_drawdown(equity_curve, timestamps)
    drawdown_plot.savefig(os.path.join(output_dir, 'drawdown.png'))
    
    logger.info(f"Plots saved to {output_dir}")


if __name__ == '__main__':
    main() 
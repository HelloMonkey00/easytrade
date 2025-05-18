"""
EasyTrade runner for strategies in backtesting or live trading mode.
"""

import logging
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timedelta
import pandas as pd
import backtrader as bt
import pytz

from easytrade.core.strategy import Strategy
from easytrade.data.data_provider import DataProvider
from easytrade.data.ib_provider import IBDataProvider
from easytrade.data.backtrader_provider import BacktraderDataProvider
from easytrade.execution.execution_provider import ExecutionProvider
from easytrade.execution.ib_provider import IBExecutionProvider
from easytrade.execution.backtrader_provider import BacktraderExecutionProvider
from easytrade.utils.market_time import MarketTime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class EasyTradeRunner:
    """
    Runner for EasyTrade strategies in either backtesting or live trading mode.
    """
    
    def __init__(self, mode: str = "backtest"):
        """
        Initialize the EasyTrade runner.
        
        Args:
            mode: Trading mode ("backtest" or "live")
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        
        if mode not in ["backtest", "live"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'backtest' or 'live'")
            
        self.mode = mode
        self.strategy = None
        self.data_provider = None
        self.execution_provider = None
        self.cerebro = None
        self.backtrader_strategy = None
        
    def setup_backtest(self, strategy: Strategy, 
                      data: Dict[str, pd.DataFrame] = None,
                      start_date: datetime = None,
                      end_date: datetime = None,
                      initial_capital: float = 100000.0,
                      commission: float = 0.001):
        """
        Setup for backtesting mode.
        
        Args:
            strategy: Strategy to backtest
            data: Dictionary mapping symbol to DataFrame with OHLCV data
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_capital: Initial capital for backtest
            commission: Commission rate for backtest
        """
        if self.mode != "backtest":
            raise RuntimeError("Cannot setup backtest in live mode")
            
        self.strategy = strategy
        
        # Create Backtrader cerebro
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_capital)
        self.cerebro.broker.setcommission(commission=commission)
        
        # Create data provider
        self.data_provider = BacktraderDataProvider(self.cerebro)
        
        # Create execution provider
        self.execution_provider = BacktraderExecutionProvider(self.cerebro)
        
        # Connect providers to strategy
        self.strategy.set_data_provider(self.data_provider)
        self.strategy.set_execution_provider(self.execution_provider)
        
        # Load data if provided
        if data:
            for symbol, df in data.items():
                self.data_provider.load_market_data(symbol, df)
                
        # Create Backtrader strategy wrapper
        self._create_backtrader_strategy()
        
        # Add the strategy to cerebro
        self.cerebro.addstrategy(self.backtrader_strategy)
        
        self.logger.info("Backtest setup complete")
        
    def setup_live(self, strategy: Strategy,
                 ib_host: str = "127.0.0.1",
                 ib_port: int = 7497,
                 ib_client_id: int = 1,
                 symbols: List[str] = None):
        """
        Setup for live trading mode.
        
        Args:
            strategy: Strategy to run
            ib_host: Interactive Brokers TWS/Gateway host
            ib_port: Interactive Brokers TWS/Gateway port
            ib_client_id: Interactive Brokers client ID
            symbols: List of symbols to trade
        """
        if self.mode != "live":
            raise RuntimeError("Cannot setup live trading in backtest mode")
            
        self.strategy = strategy
        
        # Create IB data provider
        self.data_provider = IBDataProvider(
            host=ib_host,
            port=ib_port,
            client_id=ib_client_id,
            symbols=symbols
        )
        
        # Create IB execution provider
        self.execution_provider = IBExecutionProvider(
            host=ib_host,
            port=ib_port,
            client_id=ib_client_id
        )
        
        # Connect providers to strategy
        self.strategy.set_data_provider(self.data_provider)
        self.strategy.set_execution_provider(self.execution_provider)
        
        self.logger.info("Live trading setup complete")
        
    def run(self, **kwargs) -> Dict[str, Any]:
        """
        Run the strategy.
        
        Args:
            **kwargs: Additional arguments for the run
            
        Returns:
            Dictionary with run results
        """
        if not self.strategy:
            raise RuntimeError("No strategy set. Call setup_backtest or setup_live first")
            
        if self.mode == "backtest":
            return self._run_backtest(**kwargs)
        else:
            return self._run_live(**kwargs)
            
    def _run_backtest(self, **kwargs) -> Dict[str, Any]:
        """
        Run in backtest mode.
        
        Args:
            **kwargs: Additional arguments for the backtest
            
        Returns:
            Dictionary with backtest results
        """
        if not self.cerebro:
            raise RuntimeError("Cerebro not initialized. Call setup_backtest first")
            
        # Start strategy
        self.strategy.on_start()
        
        # Run the backtest
        results = self.cerebro.run(**kwargs)
        
        # Stop strategy
        self.strategy.on_stop()
        
        # Process results
        backtest_result = {
            "initial_value": self.cerebro.broker.startingcash,
            "final_value": self.cerebro.broker.getvalue(),
            "pnl": self.cerebro.broker.getvalue() - self.cerebro.broker.startingcash,
            "pnl_pct": (self.cerebro.broker.getvalue() / self.cerebro.broker.startingcash - 1) * 100
        }
        
        self.logger.info(f"Backtest complete. PnL: {backtest_result['pnl']:.2f} ({backtest_result['pnl_pct']:.2f}%)")
        
        return backtest_result
        
    def _run_live(self, run_duration: Optional[int] = None) -> Dict[str, Any]:
        """
        Run in live mode.
        
        Args:
            run_duration: Optional duration to run in seconds (None for indefinite)
            
        Returns:
            Dictionary with live trading results
        """
        if not self.data_provider or not self.execution_provider:
            raise RuntimeError("Providers not initialized. Call setup_live first")
            
        # Start providers
        self.data_provider.start()
        self.execution_provider.start()
        
        # Start strategy
        self.strategy.on_start()
        
        try:
            if run_duration:
                # Run for specified duration
                self.logger.info(f"Running strategy for {run_duration} seconds")
                start_time = datetime.now()
                while (datetime.now() - start_time).total_seconds() < run_duration:
                    # Sleep to avoid high CPU usage
                    import time
                    time.sleep(1)
            else:
                # Run indefinitely (until KeyboardInterrupt)
                self.logger.info("Running strategy indefinitely (Ctrl+C to stop)")
                
                while True:
                    # Sleep to avoid high CPU usage
                    import time
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            self.logger.info("Strategy stopped by user")
        except Exception as e:
            self.logger.error(f"Error running strategy: {str(e)}")
            raise
        finally:
            # Stop strategy
            self.strategy.on_stop()
            
            # Stop providers
            self.data_provider.stop()
            self.execution_provider.stop()
            
        # Get results
        positions = self.execution_provider.get_positions()
        
        # Calculate portfolio value
        portfolio_value = 0.0
        for symbol, position in positions.items():
            portfolio_value += position.quantity * position.current_price
            
        live_result = {
            "positions": positions,
            "portfolio_value": portfolio_value
        }
        
        self.logger.info(f"Live trading stopped. Portfolio value: {portfolio_value:.2f}")
        
        return live_result
        
    def plot(self, **kwargs):
        """
        Plot backtest results (only in backtest mode).
        
        Args:
            **kwargs: Arguments for Backtrader plot
        """
        if self.mode != "backtest":
            raise RuntimeError("Plotting is only available in backtest mode")
            
        if not self.cerebro:
            raise RuntimeError("No backtest results to plot")
            
        # Plot the results
        self.cerebro.plot(**kwargs)
        
    def _create_backtrader_strategy(self):
        """Create a Backtrader strategy wrapper for the EasyTrade strategy."""
        
        # Define the Backtrader strategy class
        class BacktraderStrategyWrapper(bt.Strategy):
            params = {
                'verbosity': 1  # Control logging verbosity
            }
            
            def __init__(self):
                # Store reference to runner
                self.runner = self
                
                # Access the EasyTrade strategy
                self.easytrade_strategy = self.runner.strategy
                
                # Set the Backtrader strategy in the execution provider
                self.runner.execution_provider.set_strategy(self)
                
                # Store the current bar data
                self.current_data = {}
                
            def next(self):
                # Process the current bar
                for data in self.datas:
                    symbol = data._name
                    
                    # Update current data
                    self.current_data[symbol] = self._create_bar(data, 0)
                    
                # Call the EasyTrade strategy's on_bar method
                self.easytrade_strategy.on_bar(self.current_data)
                
            def _create_bar(self, data, idx):
                """Create a Bar object from Backtrader data."""
                from easytrade.core.types import Bar
                
                timestamp = bt.num2date(data.datetime[idx])
                if timestamp.tzinfo is None:
                    timestamp = pytz.timezone('America/New_York').localize(timestamp)
                    
                return Bar(
                    timestamp=timestamp,
                    open=data.open[idx],
                    high=data.high[idx],
                    low=data.low[idx],
                    close=data.close[idx],
                    volume=data.volume[idx] if hasattr(data, 'volume') else 0
                )
                
        # Create a function to bind the runner to the strategy
        def bind_runner(cls):
            cls.runner = self
            return cls
            
        # Bind the runner to the strategy
        self.backtrader_strategy = bind_runner(BacktraderStrategyWrapper) 
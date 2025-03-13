#!/usr/bin/env python
"""
Basic tests for the EasyTrade framework.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

# Add parent directory to path to import easytrade
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from easytrade.core.types import Bar, Order, OrderType, OrderSide, TimeInForce, Position, Portfolio
from easytrade.core.strategy import Strategy
from easytrade.data.csv_provider import CSVDataProvider
from easytrade.execution.backtest import BacktestExecutionProvider
from easytrade.core.engine import TradingEngine


class TestStrategy(Strategy):
    """Simple test strategy that buys on the first bar and sells on the last bar."""
    
    def __init__(self):
        super().__init__()
        self.bars_received = 0
        self.max_bars = 10
        self.bought = False
        self.sold = False
        
    def on_data(self, data):
        self.bars_received += 1
        
        # Buy on first bar
        if self.bars_received == 1 and not self.bought:
            for symbol in data:
                self.buy(symbol, 10)
                self.bought = True
                
        # Sell on last bar
        if self.bars_received == self.max_bars and not self.sold:
            for symbol in data:
                self.sell(symbol, 10)
                self.sold = True


class BasicTests(unittest.TestCase):
    """Basic tests for the EasyTrade framework."""
    
    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test data
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data')
        if not os.path.exists(self.test_dir):
            os.makedirs(self.test_dir)
            
        # Create a test CSV file
        self.create_test_data()
        
    def create_test_data(self):
        """Create test data."""
        import pandas as pd
        
        # Create test data
        data = []
        start_date = datetime.now() - timedelta(days=10)
        
        for i in range(10):
            data.append({
                'timestamp': start_date + timedelta(days=i),
                'open': 100 + i,
                'high': 105 + i,
                'low': 95 + i,
                'close': 101 + i,
                'volume': 1000 + i * 100
            })
            
        # Save to CSV
        df = pd.DataFrame(data)
        df.to_csv(os.path.join(self.test_dir, 'TEST.csv'), index=False)
        
    def test_bar_creation(self):
        """Test Bar object creation."""
        bar = Bar(
            timestamp=datetime.now(),
            open=100.0,
            high=105.0,
            low=95.0,
            close=101.0,
            volume=1000.0
        )
        
        self.assertEqual(bar.open, 100.0)
        self.assertEqual(bar.high, 105.0)
        self.assertEqual(bar.low, 95.0)
        self.assertEqual(bar.close, 101.0)
        self.assertEqual(bar.volume, 1000.0)
        
    def test_order_creation(self):
        """Test Order object creation."""
        order = Order(
            id="test_order",
            symbol="TEST",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10.0,
            price=100.0
        )
        
        self.assertEqual(order.id, "test_order")
        self.assertEqual(order.symbol, "TEST")
        self.assertEqual(order.order_type, OrderType.MARKET)
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.quantity, 10.0)
        self.assertEqual(order.price, 100.0)
        
    def test_csv_provider(self):
        """Test CSVDataProvider."""
        provider = CSVDataProvider(self.test_dir)
        provider.load_directory()
        
        symbols = provider.get_symbols()
        self.assertIn("TEST", symbols)
        
        bar = provider.get_latest_bar("TEST")
        self.assertIsNone(bar)  # No data loaded yet
        
        # Get historical data
        start_date = datetime.now() - timedelta(days=10)
        end_date = datetime.now()
        bars = provider.get_historical_data("TEST", start_date, end_date)
        
        self.assertEqual(len(bars), 10)
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[9].open, 109.0)
        
    def test_backtest_execution(self):
        """Test BacktestExecutionProvider."""
        provider = BacktestExecutionProvider(initial_cash=10000.0)
        
        # Place a buy order
        order = provider.place_order(
            symbol="TEST",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.MARKET
        )
        
        self.assertIsNotNone(order)
        self.assertEqual(order.symbol, "TEST")
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.quantity, 10.0)
        
        # Process market data to execute the order
        bar = Bar(
            timestamp=datetime.now(),
            open=100.0,
            high=105.0,
            low=95.0,
            close=101.0,
            volume=1000.0
        )
        
        provider.process_market_data({"TEST": bar})
        
        # Check that the order was executed
        updated_order = provider.get_order(order.id)
        self.assertIsNotNone(updated_order)
        
        # Check portfolio
        portfolio = provider.get_portfolio()
        self.assertLess(portfolio.cash, 10000.0)  # Cash should be reduced
        
        # Check position
        position = provider.get_position("TEST")
        self.assertIsNotNone(position)
        self.assertEqual(position.symbol, "TEST")
        self.assertEqual(position.quantity, 10.0)
        
    def test_trading_engine(self):
        """Test TradingEngine with a simple strategy."""
        # Create components
        data_provider = CSVDataProvider(self.test_dir)
        execution_provider = BacktestExecutionProvider(initial_cash=10000.0)
        strategy = TestStrategy()
        
        # Set symbols for strategy
        strategy.set_symbols(["TEST"])
        
        # Create trading engine
        engine = TradingEngine(
            data_provider=data_provider,
            execution_provider=execution_provider,
            strategy=strategy
        )
        
        # Load data
        data_provider.load_directory()
        
        # Run backtest
        engine.run_backtest()
        
        # Check that the strategy executed trades
        self.assertTrue(strategy.bought)
        self.assertTrue(strategy.sold)
        
        # Check portfolio
        portfolio = execution_provider.get_portfolio()
        self.assertNotEqual(portfolio.cash, 10000.0)  # Cash should be different from initial
        
        # Get performance metrics
        metrics = execution_provider.get_performance_metrics()
        self.assertIn('pnl', metrics)
        
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        
        # Remove test directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)


if __name__ == '__main__':
    unittest.main() 
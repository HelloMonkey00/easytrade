"""
Trading engine that connects data providers, execution providers, and strategies.
"""
import logging
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta

from easytrade.core.strategy import Strategy
from easytrade.data.data_provider import DataProvider
from easytrade.execution.execution_provider import ExecutionProvider
from easytrade.core.types import Order, OrderType, OrderSide, TimeInForce, Position, Portfolio, Trade, Bar


class TradingEngine:
    """
    Trading engine that connects data providers, execution providers, and strategies.
    
    The trading engine is responsible for coordinating the flow of data and orders
    between the data provider, execution provider, and strategy.
    """
    
    def __init__(self, data_provider: DataProvider, execution_provider: ExecutionProvider,
                strategy: Strategy, risk_manager=None):
        """
        Initialize the trading engine.
        
        Args:
            data_provider: Data provider to use
            execution_provider: Execution provider to use
            strategy: Strategy to run
            risk_manager: Risk manager to use (optional)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.data_provider = data_provider
        self.execution_provider = execution_provider
        self.strategy = strategy
        self.risk_manager = risk_manager
        
        # Set up connections
        self.strategy.set_engine(self)
        self.data_provider.add_subscriber(self)
        self.execution_provider.add_order_callback(self.on_order_update)
        self.execution_provider.add_trade_callback(self.on_trade)
        
        self._running = False
        
    def start(self):
        """Start the trading engine."""
        if self._running:
            self.logger.warning("Trading engine already running")
            return
            
        self._running = True
        
        # Start components
        self.execution_provider.start()
        self.strategy.on_start()
        self.data_provider.start()
        
        self.logger.info("Trading engine started")
        
    def stop(self):
        """Stop the trading engine."""
        if not self._running:
            self.logger.warning("Trading engine not running")
            return
            
        self._running = False
        
        # Stop components
        self.data_provider.stop()
        self.strategy.on_stop()
        self.execution_provider.stop()
        
        self.logger.info("Trading engine stopped")
        
    def on_data(self, data: Dict[str, Bar]):
        """
        Called when new market data is available.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        if not self._running:
            return
            
        # Process market data in execution provider
        self.execution_provider.process_market_data(data)
        
        # Forward data to strategy
        self.strategy.on_data(data)
        
    def on_order_update(self, order: Order):
        """
        Called when an order status is updated.
        
        Args:
            order: Updated order
        """
        if not self._running:
            return
            
        # Forward order update to strategy
        self.strategy.on_order_update(order)
        
    def on_trade(self, trade: Trade):
        """
        Called when a trade is executed.
        
        Args:
            trade: Trade that occurred
        """
        if not self._running:
            return
            
        # Forward trade to strategy
        self.strategy.on_trade(trade)
        
    def place_order(self, symbol: str, side: OrderSide, quantity: float,
                   order_type: OrderType = OrderType.MARKET,
                   price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   time_in_force: TimeInForce = TimeInForce.DAY) -> Optional[Order]:
        """
        Place an order.
        
        Args:
            symbol: Symbol to trade
            side: Order side (BUY or SELL)
            quantity: Quantity to trade
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price (required for LIMIT and STOP_LIMIT orders)
            stop_price: Stop price (required for STOP and STOP_LIMIT orders)
            time_in_force: Time in force for the order
            
        Returns:
            Order object if successful, None otherwise
        """
        if not self._running:
            self.logger.error("Cannot place order: engine not running")
            return None
            
        # Apply risk management if available
        if self.risk_manager is not None:
            approved, modified_params = self.risk_manager.check_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                stop_price=stop_price
            )
            
            if not approved:
                self.logger.warning(f"Order rejected by risk manager: {symbol} {side.name} {quantity}")
                return None
                
            # Update parameters if modified
            if modified_params:
                symbol = modified_params.get('symbol', symbol)
                side = modified_params.get('side', side)
                quantity = modified_params.get('quantity', quantity)
                order_type = modified_params.get('order_type', order_type)
                price = modified_params.get('price', price)
                stop_price = modified_params.get('stop_price', stop_price)
                
        # Place order through execution provider
        return self.execution_provider.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force
        )
        
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if successful, False otherwise
        """
        if not self._running:
            self.logger.error("Cannot cancel order: engine not running")
            return False
            
        return self.execution_provider.cancel_order(order_id)
        
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get an order by ID.
        
        Args:
            order_id: ID of order to get
            
        Returns:
            Order object if found, None otherwise
        """
        return self.execution_provider.get_order(order_id)
        
    def get_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all orders, optionally filtered by symbol.
        
        Args:
            symbol: Symbol to filter by (optional)
            
        Returns:
            List of Order objects
        """
        return self.execution_provider.get_orders(symbol)
        
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position object if exists, None otherwise
        """
        return self.execution_provider.get_position(symbol)
        
    def get_positions(self) -> Dict[str, Position]:
        """
        Get all positions.
        
        Returns:
            Dictionary mapping symbol to Position object
        """
        return self.execution_provider.get_positions()
        
    def get_portfolio(self) -> Portfolio:
        """
        Get current portfolio.
        
        Returns:
            Portfolio object
        """
        return self.execution_provider.get_portfolio()
        
    def get_historical_data(self, symbol: str, period: str, interval: str):
        """
        Get historical data for a symbol.
        
        Args:
            symbol: Symbol to get data for
            period: Time period (e.g., '1d', '5d', '1m', '3m', '6m', '1y', '5y')
            interval: Data interval (e.g., '1m', '5m', '15m', '30m', '1h', '1d', '1wk', '1mo')
            
        Returns:
            DataFrame with historical data
        """
        if not hasattr(self.data_provider, 'get_historical_data'):
            self.logger.error("Data provider does not support historical data")
            return None
            
        # Convert period to start and end dates
        end_date = datetime.now()
        if period.endswith('d'):
            days = int(period[:-1])
            start_date = end_date - timedelta(days=days)
        elif period.endswith('m'):
            months = int(period[:-1])
            start_date = end_date - timedelta(days=months * 30)
        elif period.endswith('y'):
            years = int(period[:-1])
            start_date = end_date - timedelta(days=years * 365)
        else:
            raise ValueError(f"Invalid period: {period}")
            
        return self.data_provider.get_historical_data(symbol, start_date, end_date, interval)
        
    def get_latest_data(self, symbol: str) -> Optional[Bar]:
        """
        Get the latest data for a symbol.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            Latest Bar object for the symbol, or None if not available
        """
        if hasattr(self.data_provider, '_data') and symbol in self.data_provider._data:
            df = self.data_provider._data[symbol]
            if not df.empty:
                # Get the latest row
                row = df.iloc[-1]
                return Bar(
                    timestamp=row[self.data_provider.timestamp_column],
                    open=row[self.data_provider.ohlcv_columns['open']],
                    high=row[self.data_provider.ohlcv_columns['high']],
                    low=row[self.data_provider.ohlcv_columns['low']],
                    close=row[self.data_provider.ohlcv_columns['close']],
                    volume=row[self.data_provider.ohlcv_columns['volume']]
                )
        return None
        
    def run_backtest(self):
        """Run a backtest."""
        self.logger.debug("Starting backtest")
        
        # Check if data provider has data
        if hasattr(self.data_provider, '_data'):
            self.logger.debug(f"Data provider has {len(self.data_provider._data)} symbols loaded")
            for symbol, df in self.data_provider._data.items():
                self.logger.debug(f"Symbol {symbol} has {len(df)} data points")
        else:
            self.logger.warning("Data provider does not have _data attribute")
            
        # Make sure data provider is not already running
        if hasattr(self.data_provider, '_running') and self.data_provider._running:
            self.logger.warning("Data provider is already running, stopping it first")
            self.data_provider.stop()
            
            # Wait for thread to finish
            if hasattr(self.data_provider, '_thread') and self.data_provider._thread:
                self.data_provider._thread.join(timeout=1)
                
        # Reset data provider indices
        if hasattr(self.data_provider, '_current_index'):
            for symbol in self.data_provider._current_index:
                self.data_provider._current_index[symbol] = 0
                
        self.start()
        
        # Wait for the data provider to finish
        if hasattr(self.data_provider, '_thread') and self.data_provider._thread:
            self.logger.debug("Waiting for data provider thread to finish")
            
            # Wait in small increments to allow for keyboard interrupts
            start_time = datetime.now()
            timeout = 30  # 30 seconds timeout
            
            while self.data_provider._thread.is_alive():
                self.data_provider._thread.join(timeout=0.5)  # Wait for 0.5 seconds
                
                # Check if we've exceeded the timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    self.logger.warning(f"Data provider thread did not finish within {timeout} seconds timeout")
                    self.data_provider._running = False  # Force stop
                    break
                    
            self.logger.debug("Data provider thread finished")
        else:
            self.logger.warning("Data provider does not have a thread or thread is not running")
        
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for the backtest.
        
        Returns:
            Dictionary of performance metrics
        """
        if hasattr(self.execution_provider, 'get_performance_metrics'):
            return self.execution_provider.get_performance_metrics()
        else:
            self.logger.warning("Execution provider does not support performance metrics")
            return {} 
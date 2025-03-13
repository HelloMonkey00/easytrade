"""
Moving average crossover strategy.
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta

from easytrade.core.strategy import Strategy
from easytrade.core.types import Bar, Order, OrderType, OrderSide, TimeInForce


class MovingAverageCrossoverStrategy(Strategy):
    """
    Moving average crossover strategy.
    
    This strategy generates buy signals when the short-term moving average crosses
    above the long-term moving average, and sell signals when the short-term moving
    average crosses below the long-term moving average.
    """
    
    def __init__(self, short_window: int = 10, long_window: int = 50, 
                position_size: float = 1.0):
        """
        Initialize the strategy.
        
        Args:
            short_window: Short-term moving average window
            long_window: Long-term moving average window
            position_size: Position size as a fraction of portfolio value
        """
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window
        self.position_size = position_size
        
        self._data = {}  # symbol -> List[Bar]
        self._signals = {}  # symbol -> signal (1 = buy, -1 = sell, 0 = hold)
        
    def on_start(self):
        """Called when the strategy starts running."""
        self.logger.info(f"Starting MovingAverageCrossoverStrategy (short_window={self.short_window}, long_window={self.long_window})")
        
        # Initialize data and signals
        for symbol in self._symbols:
            self._data[symbol] = []
            self._signals[symbol] = 0
            
    def on_data(self, data: Dict[str, Bar]):
        """
        Called when new market data is available.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        # Update data
        for symbol, bar in data.items():
            if symbol in self._symbols:
                self._data[symbol].append(bar)
                
                # Calculate signals if we have enough data
                if len(self._data[symbol]) >= self.long_window:
                    self._calculate_signal(symbol)
                    self._execute_signal(symbol)
                    
    def _calculate_signal(self, symbol: str):
        """
        Calculate trading signal for a symbol.
        
        Args:
            symbol: Symbol to calculate signal for
        """
        # Extract close prices
        closes = [bar.close for bar in self._data[symbol]]
        
        # Calculate moving averages
        short_ma = np.mean(closes[-self.short_window:])
        long_ma = np.mean(closes[-self.long_window:])
        
        # Calculate previous moving averages
        prev_short_ma = np.mean(closes[-self.short_window-1:-1])
        prev_long_ma = np.mean(closes[-self.long_window-1:-1])
        
        # Determine signal
        prev_signal = self._signals[symbol]
        
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            # Crossover: short MA crosses above long MA (buy signal)
            signal = 1
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            # Crossover: short MA crosses below long MA (sell signal)
            signal = -1
        else:
            # No crossover
            signal = 0
            
        self._signals[symbol] = signal
        
        # Log signal
        if signal != 0:
            self.logger.info(f"Signal for {symbol}: {signal} (short_ma={short_ma:.2f}, long_ma={long_ma:.2f})")
            
    def _execute_signal(self, symbol: str):
        """
        Execute trading signal for a symbol.
        
        Args:
            symbol: Symbol to execute signal for
        """
        signal = self._signals[symbol]
        
        if signal == 0:
            return
            
        # Get current position
        position = self.get_position(symbol)
        
        # Get current portfolio
        portfolio = self.get_portfolio()
        
        # Calculate position size
        if portfolio.equity > 0:
            current_price = self._data[symbol][-1].close
            position_value = portfolio.equity * self.position_size
            quantity = position_value / current_price
            
            if signal > 0:  # Buy signal
                if position is None or position.quantity <= 0:
                    # No position or short position, go long
                    if position is not None and position.quantity < 0:
                        # Close short position first
                        self.close(symbol)
                        
                    # Open long position
                    self.logger.info(f"Buying {quantity:.2f} shares of {symbol} @ {current_price:.2f}")
                    # Use limit order with current price
                    self.buy(symbol, quantity, order_type=OrderType.LIMIT, price=current_price)
            elif signal < 0:  # Sell signal
                if position is None or position.quantity >= 0:
                    # No position or long position, go short
                    if position is not None and position.quantity > 0:
                        # Close long position first
                        self.close(symbol)
                        
                    # Open short position
                    self.logger.info(f"Selling {quantity:.2f} shares of {symbol} @ {current_price:.2f}")
                    # Use limit order with current price
                    self.sell(symbol, quantity, order_type=OrderType.LIMIT, price=current_price)
                    
    def on_order_update(self, order: Order):
        """
        Called when an order status is updated.
        
        Args:
            order: Updated order object
        """
        self.logger.info(f"Order update: {order.id} {order.symbol} {order.side.name} {order.status.name}")
        
    def on_stop(self):
        """Called when the strategy stops running."""
        self.logger.info("Stopping MovingAverageCrossoverStrategy")
        
        # Close all positions
        for symbol in self._symbols:
            position = self.get_position(symbol)
            if position is not None and position.quantity != 0:
                self.logger.info(f"Closing position for {symbol}")
                self.close(symbol) 
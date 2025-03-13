"""
Base Strategy class that traders will extend to implement their trading strategies.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
import logging
from datetime import datetime

from easytrade.core.types import Bar, Order, OrderType, OrderSide, TimeInForce


class Strategy(ABC):
    """
    Base Strategy class that traders will extend to implement their trading strategies.
    
    This class provides the interface for strategy implementation and handles
    communication with the trading engine.
    """
    
    def __init__(self):
        """Initialize the strategy."""
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._engine = None
        self._symbols = []
        self._parameters = {}
        
    def set_engine(self, engine):
        """Set the trading engine reference."""
        self._engine = engine
        
    def set_symbols(self, symbols: List[str]):
        """Set the symbols that this strategy will trade."""
        self._symbols = symbols
        
    def set_parameters(self, parameters: Dict[str, Any]):
        """Set strategy parameters."""
        self._parameters = parameters
        
    @abstractmethod
    def on_data(self, data: Dict[str, Bar]):
        """
        Called when new market data is available.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        pass
    
    def on_order_update(self, order: Order):
        """
        Called when an order status is updated.
        
        Args:
            order: Updated order object
        """
        pass
    
    def on_trade(self, trade):
        """
        Called when a trade is executed.
        
        Args:
            trade: Trade object
        """
        pass
    
    def on_start(self):
        """Called when the strategy starts running."""
        pass
    
    def on_stop(self):
        """Called when the strategy stops running."""
        pass
    
    def buy(self, symbol: str, quantity: float, order_type: OrderType = OrderType.MARKET,
            price: Optional[float] = None, stop_price: Optional[float] = None,
            time_in_force: TimeInForce = TimeInForce.DAY) -> Optional[Order]:
        """
        Place a buy order.
        
        Args:
            symbol: Symbol to buy
            quantity: Quantity to buy
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price (required for LIMIT and STOP_LIMIT orders)
            stop_price: Stop price (required for STOP and STOP_LIMIT orders)
            time_in_force: Time in force for the order
            
        Returns:
            Order object if successful, None otherwise
        """
        if self._engine is None:
            self.logger.error("Cannot place order: engine not set")
            return None
            
        return self._engine.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force
        )
    
    def sell(self, symbol: str, quantity: float, order_type: OrderType = OrderType.MARKET,
             price: Optional[float] = None, stop_price: Optional[float] = None,
             time_in_force: TimeInForce = TimeInForce.DAY) -> Optional[Order]:
        """
        Place a sell order.
        
        Args:
            symbol: Symbol to sell
            quantity: Quantity to sell
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price (required for LIMIT and STOP_LIMIT orders)
            stop_price: Stop price (required for STOP and STOP_LIMIT orders)
            time_in_force: Time in force for the order
            
        Returns:
            Order object if successful, None otherwise
        """
        if self._engine is None:
            self.logger.error("Cannot place order: engine not set")
            return None
            
        return self._engine.place_order(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force
        )
    
    def close(self, symbol: str) -> Optional[Order]:
        """
        Close an existing position.
        
        Args:
            symbol: Symbol to close position for
            
        Returns:
            Order object if successful, None otherwise
        """
        if self._engine is None:
            self.logger.error("Cannot close position: engine not set")
            return None
            
        position = self._engine.get_position(symbol)
        if position is None:
            self.logger.warning(f"No position to close for {symbol}")
            return None
            
        # Get current price
        current_price = position.current_price
        if current_price is None:
            # Try to get the latest price from the engine
            latest_data = self._engine.get_latest_data(symbol)
            if latest_data is not None:
                current_price = latest_data.close
                
        if position.quantity > 0:
            return self.sell(symbol, position.quantity, 
                           order_type=OrderType.LIMIT if current_price is not None else OrderType.MARKET,
                           price=current_price)
        elif position.quantity < 0:
            return self.buy(symbol, abs(position.quantity),
                          order_type=OrderType.LIMIT if current_price is not None else OrderType.MARKET,
                          price=current_price)
        else:
            self.logger.warning(f"Position for {symbol} has zero quantity")
            return None
    
    def get_position(self, symbol: str):
        """
        Get current position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position object if exists, None otherwise
        """
        if self._engine is None:
            self.logger.error("Cannot get position: engine not set")
            return None
            
        return self._engine.get_position(symbol)
    
    def get_portfolio(self):
        """
        Get current portfolio.
        
        Returns:
            Portfolio object
        """
        if self._engine is None:
            self.logger.error("Cannot get portfolio: engine not set")
            return None
            
        return self._engine.get_portfolio()
    
    def get_historical_data(self, symbol: str, period: str, interval: str):
        """
        Get historical data for a symbol.
        
        Args:
            symbol: Symbol to get data for
            period: Time period (e.g., '1d', '5d', '1mo', '3mo', '1y')
            interval: Bar interval (e.g., '1m', '5m', '1h', '1d')
            
        Returns:
            List of Bar objects
        """
        if self._engine is None:
            self.logger.error("Cannot get historical data: engine not set")
            return None
            
        return self._engine.get_historical_data(symbol, period, interval) 
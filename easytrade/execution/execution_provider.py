"""
Abstract base class for execution providers.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, Any
from datetime import datetime

from easytrade.core.types import Order, OrderType, OrderSide, TimeInForce, Position, Portfolio, Trade


class ExecutionProvider(ABC):
    """
    Abstract base class for execution providers.
    
    Execution providers are responsible for executing orders and managing positions.
    They abstract the details of connecting to brokers or exchanges.
    """
    
    def __init__(self):
        """Initialize the execution provider."""
        self._order_callbacks = []
        self._trade_callbacks = []
        
    def add_order_callback(self, callback):
        """
        Add a callback to be notified of order updates.
        
        Args:
            callback: Function to call with order updates
        """
        if callback not in self._order_callbacks:
            self._order_callbacks.append(callback)
            
    def remove_order_callback(self, callback):
        """
        Remove an order callback.
        
        Args:
            callback: Callback to remove
        """
        if callback in self._order_callbacks:
            self._order_callbacks.remove(callback)
            
    def add_trade_callback(self, callback):
        """
        Add a callback to be notified of trades.
        
        Args:
            callback: Function to call with trade updates
        """
        if callback not in self._trade_callbacks:
            self._trade_callbacks.append(callback)
            
    def remove_trade_callback(self, callback):
        """
        Remove a trade callback.
        
        Args:
            callback: Callback to remove
        """
        if callback in self._trade_callbacks:
            self._trade_callbacks.remove(callback)
            
    def notify_order_update(self, order: Order):
        """
        Notify all order callbacks of an order update.
        
        Args:
            order: Updated order
        """
        for callback in self._order_callbacks:
            callback(order)
            
    def notify_trade(self, trade: Trade):
        """
        Notify all trade callbacks of a trade.
        
        Args:
            trade: Trade that occurred
        """
        for callback in self._trade_callbacks:
            callback(trade)
            
    @abstractmethod
    def start(self):
        """Start the execution provider."""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the execution provider."""
        pass
    
    @abstractmethod
    def place_order(self, symbol: str, side: OrderSide, quantity: float,
                   order_type: OrderType = OrderType.MARKET,
                   price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   time_in_force: TimeInForce = TimeInForce.DAY) -> Order:
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
            Order object
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get an order by ID.
        
        Args:
            order_id: ID of order to get
            
        Returns:
            Order object if found, None otherwise
        """
        pass
    
    @abstractmethod
    def get_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all orders, optionally filtered by symbol.
        
        Args:
            symbol: Symbol to filter by (optional)
            
        Returns:
            List of Order objects
        """
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position object if exists, None otherwise
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        """
        Get all positions.
        
        Returns:
            Dictionary mapping symbol to Position object
        """
        pass
    
    @abstractmethod
    def get_portfolio(self) -> Portfolio:
        """
        Get current portfolio.
        
        Returns:
            Portfolio object
        """
        pass 
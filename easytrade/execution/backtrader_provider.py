"""
Backtrader execution provider adapter.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
import threading
import time
from datetime import datetime
import pandas as pd
import backtrader as bt

from easytrade.core.types import Order, OrderStatus, OrderSide, OrderType, Position
from easytrade.execution.execution_provider import ExecutionProvider


class BacktraderExecutionProvider(ExecutionProvider):
    """
    Execution provider adapter for Backtrader.
    
    This provider executes orders through the Backtrader engine and converts
    the results to the standard easytrade format.
    """
    
    def __init__(self, cerebro: bt.Cerebro, strategy=None):
        """
        Initialize the Backtrader execution provider.
        
        Args:
            cerebro: Backtrader cerebro instance
            strategy: Backtrader strategy instance (if already running)
        """
        super().__init__()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cerebro = cerebro
        self.strategy = strategy
        
        # Internal state tracking
        self._orders = {}  # Order ID -> Order mapping
        self._positions = {}  # Symbol -> Position mapping
        self._trades = []  # List of completed trades
        self._running = False
        self._update_thread = None
        self._next_order_id = 1000  # Start order IDs at 1000
        
    def start(self):
        """Start the execution provider."""
        if self._running:
            self.logger.warning("Execution provider is already running")
            return
            
        try:
            # Start update thread
            self._running = True
            self._update_thread = threading.Thread(target=self._update_loop)
            self._update_thread.daemon = True
            self._update_thread.start()
            
            self.logger.info("Backtrader execution provider started")
        except Exception as e:
            self.logger.error(f"Failed to start Backtrader execution provider: {str(e)}")
            self.stop()
            raise
            
    def stop(self):
        """Stop the execution provider."""
        self._running = False
        
        if self._update_thread is not None:
            self._update_thread.join(timeout=5.0)
            self._update_thread = None
            
        self.logger.info("Backtrader execution provider stopped")
        
    def place_order(self, order: Order) -> str:
        """
        Place an order.
        
        Args:
            order: Order to place
            
        Returns:
            Order ID
        """
        if not self._running:
            raise RuntimeError("Execution provider is not running")
            
        if not self.strategy:
            raise RuntimeError("No active strategy to place orders")
            
        # Generate order ID if not provided
        if not order.order_id:
            order.order_id = str(self._next_order_id)
            self._next_order_id += 1
            
        try:
            # Convert to Backtrader order
            bt_order = self._create_backtrader_order(order)
            
            # Update order status
            order.status = OrderStatus.SUBMITTED
            order.submit_time = datetime.now()
            
            # Store order
            self._orders[order.order_id] = order
            
            # Notify subscribers
            self.notify_order_update(order)
            
            return order.order_id
        except Exception as e:
            self.logger.error(f"Failed to place order: {str(e)}")
            
            # Update order status
            order.status = OrderStatus.REJECTED
            order.reject_reason = str(e)
            
            # Notify subscribers
            self.notify_order_update(order)
            
            raise
        
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            Whether the cancellation was successful
        """
        if not self._running:
            raise RuntimeError("Execution provider is not running")
            
        if not self.strategy:
            raise RuntimeError("No active strategy to cancel orders")
            
        # Check if order exists
        if order_id not in self._orders:
            self.logger.warning(f"Order {order_id} not found")
            return False
            
        order = self._orders[order_id]
        
        # Check if order can be cancelled
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED]:
            self.logger.warning(f"Order {order_id} cannot be cancelled (status: {order.status})")
            return False
            
        try:
            # Cancel Backtrader order (requires Backtrader internal order reference)
            if hasattr(order, '_bt_order') and order._bt_order:
                self.strategy.cancel(order._bt_order)
                
                # Update order status
                order.status = OrderStatus.CANCELED
                
                # Notify subscribers
                self.notify_order_update(order)
                
                return True
            else:
                self.logger.warning(f"No Backtrader order reference for order {order_id}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {str(e)}")
            return False
        
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get an order by ID.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order if found, None otherwise
        """
        return self._orders.get(order_id)
        
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """
        Get all orders with optional filtering by status.
        
        Args:
            status: Optional filter by order status
            
        Returns:
            List of orders
        """
        if status is None:
            return list(self._orders.values())
            
        return [order for order in self._orders.values() if order.status == status]
        
    def get_positions(self) -> Dict[str, Position]:
        """
        Get all current positions.
        
        Returns:
            Dictionary mapping symbol to Position object
        """
        return self._positions.copy()
        
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position if found, None otherwise
        """
        return self._positions.get(symbol)
        
    def _create_backtrader_order(self, order: Order) -> bt.Order:
        """
        Create a Backtrader order from an easytrade Order.
        
        Args:
            order: Easytrade Order object
            
        Returns:
            Backtrader order
        """
        # Check if strategy has buy/sell methods
        if not hasattr(self.strategy, 'buy') or not hasattr(self.strategy, 'sell'):
            raise RuntimeError("Strategy does not have buy/sell methods")
            
        # Get data feed for symbol
        data = self._get_data_for_symbol(order.symbol)
        if data is None:
            raise ValueError(f"No data feed found for symbol {order.symbol}")
            
        # Create Backtrader order
        bt_order = None
        
        # Set order size
        size = abs(order.quantity)
        
        # Handle different order types
        if order.side == OrderSide.BUY:
            if order.order_type == OrderType.MARKET:
                bt_order = self.strategy.buy(data=data, size=size)
            elif order.order_type == OrderType.LIMIT:
                bt_order = self.strategy.buy(data=data, size=size, price=order.limit_price)
            elif order.order_type == OrderType.STOP:
                bt_order = self.strategy.buy(data=data, size=size, exectype=bt.Order.Stop, 
                                           price=order.stop_price)
            elif order.order_type == OrderType.STOP_LIMIT:
                bt_order = self.strategy.buy(data=data, size=size, exectype=bt.Order.StopLimit,
                                           price=order.limit_price, plimit=order.stop_price)
        elif order.side == OrderSide.SELL:
            if order.order_type == OrderType.MARKET:
                bt_order = self.strategy.sell(data=data, size=size)
            elif order.order_type == OrderType.LIMIT:
                bt_order = self.strategy.sell(data=data, size=size, price=order.limit_price)
            elif order.order_type == OrderType.STOP:
                bt_order = self.strategy.sell(data=data, size=size, exectype=bt.Order.Stop,
                                            price=order.stop_price)
            elif order.order_type == OrderType.STOP_LIMIT:
                bt_order = self.strategy.sell(data=data, size=size, exectype=bt.Order.StopLimit,
                                            price=order.limit_price, plimit=order.stop_price)
        else:
            raise ValueError(f"Unsupported order side: {order.side}")
            
        if bt_order is None:
            raise RuntimeError("Failed to create Backtrader order")
            
        # Store Backtrader order reference
        order._bt_order = bt_order
        
        return bt_order
        
    def _get_data_for_symbol(self, symbol: str) -> Optional[bt.DataSeries]:
        """
        Get the Backtrader data feed for a symbol.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            Backtrader data feed if found, None otherwise
        """
        if not self.strategy or not hasattr(self.strategy, 'datas'):
            return None
            
        # First try exact match
        for data in self.strategy.datas:
            if data._name == symbol:
                return data
                
        # Then try case-insensitive match
        symbol_lower = symbol.lower()
        for data in self.strategy.datas:
            if data._name.lower() == symbol_lower:
                return data
                
        return None
        
    def _update_loop(self):
        """Background thread to update orders, positions, and notify subscribers."""
        while self._running:
            try:
                if not self.strategy:
                    time.sleep(0.5)
                    continue
                    
                # Update positions from strategy
                self._update_positions_from_strategy()
                
                # Update orders from strategy
                self._update_orders_from_strategy()
                
                # Sleep briefly
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Error in update loop: {str(e)}")
                time.sleep(1.0)  # Sleep briefly before retrying
                
    def _update_positions_from_strategy(self):
        """Update positions from Backtrader strategy."""
        if not hasattr(self.strategy, 'getposition'):
            return
            
        # Clear positions
        positions = {}
        
        # Get positions for each data feed
        for data in self.strategy.datas:
            symbol = data._name
            bt_position = self.strategy.getposition(data)
            
            if bt_position.size != 0:
                # Create Position object
                position = Position(
                    symbol=symbol,
                    quantity=bt_position.size,
                    entry_price=bt_position.price,
                    current_price=data.close[0],
                    unrealized_pnl=bt_position.size * (data.close[0] - bt_position.price),
                    realized_pnl=bt_position.pnl,
                    average_cost=bt_position.price
                )
                
                positions[symbol] = position
                
        # Update positions
        if positions != self._positions:
            self._positions = positions
            
            # Notify subscribers
            for position in positions.values():
                self.notify_position_update(position)
                
    def _update_orders_from_strategy(self):
        """Update orders from Backtrader strategy."""
        if not hasattr(self.strategy, '_orders'):
            return
            
        # Check for order updates
        updated_orders = []
        
        # Process Backtrader order updates
        for bt_order in self.strategy._orders:
            # Find corresponding easytrade order
            for order_id, order in self._orders.items():
                if hasattr(order, '_bt_order') and order._bt_order is bt_order:
                    # Update order status
                    new_status = self._convert_bt_status(bt_order.status)
                    
                    if order.status != new_status:
                        order.status = new_status
                        
                        # If filled, update fill details
                        if new_status == OrderStatus.FILLED:
                            order.fill_price = bt_order.executed.price
                            order.fill_time = datetime.now()
                            order.filled_quantity = abs(bt_order.executed.size)
                            
                        updated_orders.append(order)
                        
        # Notify subscribers of updated orders
        for order in updated_orders:
            self.notify_order_update(order)
            
    def _convert_bt_status(self, bt_status) -> OrderStatus:
        """
        Convert Backtrader order status to easytrade OrderStatus.
        
        Args:
            bt_status: Backtrader order status
            
        Returns:
            Easytrade OrderStatus
        """
        # Map Backtrader status to easytrade status
        if bt_status == bt.Order.Submitted:
            return OrderStatus.SUBMITTED
        elif bt_status == bt.Order.Accepted:
            return OrderStatus.ACCEPTED
        elif bt_status == bt.Order.Partial:
            return OrderStatus.PARTIALLY_FILLED
        elif bt_status == bt.Order.Completed:
            return OrderStatus.FILLED
        elif bt_status == bt.Order.Canceled:
            return OrderStatus.CANCELED
        elif bt_status == bt.Order.Rejected:
            return OrderStatus.REJECTED
        elif bt_status == bt.Order.Margin:
            return OrderStatus.REJECTED
        elif bt_status == bt.Order.Expired:
            return OrderStatus.CANCELED
        else:
            return OrderStatus.PENDING
            
    def set_strategy(self, strategy):
        """
        Set the active Backtrader strategy.
        
        Args:
            strategy: Backtrader strategy instance
        """
        self.strategy = strategy
        self.logger.info("Strategy set")
        
        # Initialize positions and orders
        if self.strategy:
            self._update_positions_from_strategy()
            self._update_orders_from_strategy()
            
    def place_market_order(self, symbol: str, quantity: float, side: OrderSide) -> str:
        """
        Place a market order.
        
        Args:
            symbol: Symbol to trade
            quantity: Quantity to trade
            side: Order side (BUY or SELL)
            
        Returns:
            Order ID
        """
        order = Order(
            symbol=symbol,
            quantity=quantity if side == OrderSide.BUY else -quantity,
            order_type=OrderType.MARKET,
            side=side
        )
        
        return self.place_order(order)
        
    def place_limit_order(self, symbol: str, quantity: float, side: OrderSide, 
                        limit_price: float) -> str:
        """
        Place a limit order.
        
        Args:
            symbol: Symbol to trade
            quantity: Quantity to trade
            side: Order side (BUY or SELL)
            limit_price: Limit price
            
        Returns:
            Order ID
        """
        order = Order(
            symbol=symbol,
            quantity=quantity if side == OrderSide.BUY else -quantity,
            order_type=OrderType.LIMIT,
            side=side,
            limit_price=limit_price
        )
        
        return self.place_order(order)
        
    def place_stop_order(self, symbol: str, quantity: float, side: OrderSide,
                       stop_price: float) -> str:
        """
        Place a stop order.
        
        Args:
            symbol: Symbol to trade
            quantity: Quantity to trade
            side: Order side (BUY or SELL)
            stop_price: Stop price
            
        Returns:
            Order ID
        """
        order = Order(
            symbol=symbol,
            quantity=quantity if side == OrderSide.BUY else -quantity,
            order_type=OrderType.STOP,
            side=side,
            stop_price=stop_price
        )
        
        return self.place_order(order)
        
    def place_stop_limit_order(self, symbol: str, quantity: float, side: OrderSide,
                             stop_price: float, limit_price: float) -> str:
        """
        Place a stop-limit order.
        
        Args:
            symbol: Symbol to trade
            quantity: Quantity to trade
            side: Order side (BUY or SELL)
            stop_price: Stop price
            limit_price: Limit price
            
        Returns:
            Order ID
        """
        order = Order(
            symbol=symbol,
            quantity=quantity if side == OrderSide.BUY else -quantity,
            order_type=OrderType.STOP_LIMIT,
            side=side,
            stop_price=stop_price,
            limit_price=limit_price
        )
        
        return self.place_order(order)
        
    def clear_orders(self):
        """Clear all orders (for testing purposes)."""
        self._orders.clear()
        
    def clear_positions(self):
        """Clear all positions (for testing purposes)."""
        self._positions.clear() 
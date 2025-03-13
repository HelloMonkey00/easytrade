"""
Backtest execution provider for simulating order execution.
"""
import uuid
import logging
from typing import Dict, List, Optional, Union, Any
from datetime import datetime
import copy

from easytrade.execution.execution_provider import ExecutionProvider
from easytrade.core.types import (
    Order, OrderType, OrderSide, OrderStatus, TimeInForce,
    Position, Portfolio, Trade, Bar
)


class BacktestExecutionProvider(ExecutionProvider):
    """
    Backtest execution provider for simulating order execution.
    
    This provider simulates order execution for backtesting purposes.
    It maintains a simulated portfolio and processes orders based on market data.
    """
    
    def __init__(self, initial_cash: float = 100000.0, commission_rate: float = 0.001):
        """
        Initialize the backtest execution provider.
        
        Args:
            initial_cash: Initial cash balance
            commission_rate: Commission rate as a decimal (e.g., 0.001 = 0.1%)
        """
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        
        # Initialize portfolio
        self.cash = initial_cash
        self.positions = {}  # symbol -> Position
        self.orders = {}  # order_id -> Order
        self.trades = []  # List of Trade objects
        
        self._running = False
        
    def start(self):
        """Start the execution provider."""
        self._running = True
        self.logger.info("Backtest execution provider started")
        
    def stop(self):
        """Stop the execution provider."""
        self._running = False
        self.logger.info("Backtest execution provider stopped")
        
    def reset(self):
        """Reset the execution provider to its initial state."""
        self.cash = self.initial_cash
        self.positions = {}
        self.orders = {}
        self.trades = []
        self._running = False
        self.logger.info("Backtest execution provider reset")
        
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
        # Validate order parameters
        if order_type in [OrderType.LIMIT, OrderType.STOP_LIMIT] and price is None:
            raise ValueError(f"Price is required for {order_type.name} orders")
            
        if order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and stop_price is None:
            raise ValueError(f"Stop price is required for {order_type.name} orders")
            
        # Create order
        order_id = str(uuid.uuid4())
        order = Order(
            id=order_id,
            symbol=symbol,
            order_type=order_type,
            side=side,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=OrderStatus.ACCEPTED,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self.orders[order_id] = order
        self.notify_order_update(order)
        
        self.logger.info(f"Order placed: {order.id} {order.side.name} {order.quantity} {order.symbol}")
        return order
        
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if successful, False otherwise
        """
        if order_id not in self.orders:
            self.logger.warning(f"Order {order_id} not found")
            return False
            
        order = self.orders[order_id]
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED]:
            self.logger.warning(f"Cannot cancel order {order_id} with status {order.status.name}")
            return False
            
        order.status = OrderStatus.CANCELED
        order.updated_at = datetime.now()
        self.notify_order_update(order)
        
        self.logger.info(f"Order canceled: {order_id}")
        return True
        
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get an order by ID.
        
        Args:
            order_id: ID of order to get
            
        Returns:
            Order object if found, None otherwise
        """
        return self.orders.get(order_id)
        
    def get_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all orders, optionally filtered by symbol.
        
        Args:
            symbol: Symbol to filter by (optional)
            
        Returns:
            List of Order objects
        """
        if symbol is None:
            return list(self.orders.values())
            
        return [order for order in self.orders.values() if order.symbol == symbol]
        
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position object if exists, None otherwise
        """
        return self.positions.get(symbol)
        
    def get_positions(self) -> Dict[str, Position]:
        """
        Get all positions.
        
        Returns:
            Dictionary mapping symbol to Position object
        """
        return self.positions
        
    def get_portfolio(self) -> Portfolio:
        """
        Get current portfolio.
        
        Returns:
            Portfolio object
        """
        return Portfolio(
            cash=self.cash,
            positions=copy.deepcopy(self.positions)
        )
        
    def process_market_data(self, data: Dict[str, Bar]):
        """
        Process market data and update orders and positions.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        if not self._running:
            return
            
        # Update positions with current prices
        for symbol, bar in data.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = bar.close
                
        # Process orders
        for order_id, order in list(self.orders.items()):
            if order.status not in [OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED]:
                continue
                
            if order.symbol not in data:
                continue
                
            bar = data[order.symbol]
            
            # Check if order should be executed
            if self._should_execute_order(order, bar):
                self._execute_order(order, bar)
                
    def _should_execute_order(self, order: Order, bar: Bar) -> bool:
        """
        Check if an order should be executed based on market data.
        
        Args:
            order: Order to check
            bar: Current market data for the order's symbol
            
        Returns:
            True if order should be executed, False otherwise
        """
        # For market orders, always execute
        if order.order_type == OrderType.MARKET:
            return True
            
        # For limit orders, check price
        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and bar.low <= order.price:
                return True
            elif order.side == OrderSide.SELL and bar.high >= order.price:
                return True
                
        # For stop orders, check price
        if order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY and bar.high >= order.stop_price:
                return True
            elif order.side == OrderSide.SELL and bar.low <= order.stop_price:
                return True
                
        # For stop-limit orders, check if stop price is reached
        if order.order_type == OrderType.STOP_LIMIT:
            if order.side == OrderSide.BUY and bar.high >= order.stop_price:
                # Convert to limit order
                order.order_type = OrderType.LIMIT
                return self._should_execute_order(order, bar)
            elif order.side == OrderSide.SELL and bar.low <= order.stop_price:
                # Convert to limit order
                order.order_type = OrderType.LIMIT
                return self._should_execute_order(order, bar)
                
        return False
        
    def _execute_order(self, order: Order, bar: Bar):
        """
        Execute an order.
        
        Args:
            order: Order to execute
            bar: Current market data for the order's symbol
        """
        # Determine execution price
        if order.order_type == OrderType.MARKET:
            # Use the open price for market orders
            execution_price = bar.open
        elif order.order_type == OrderType.LIMIT:
            # Use the limit price for limit orders
            execution_price = order.price
        elif order.order_type == OrderType.STOP:
            # Use the stop price for stop orders
            execution_price = order.stop_price
        else:
            # Shouldn't happen, but use the current price as a fallback
            execution_price = bar.close
            
        # Calculate commission
        commission = order.quantity * execution_price * self.commission_rate
        
        # Update cash and positions
        if order.side == OrderSide.BUY:
            # Check if we have enough cash
            cost = order.quantity * execution_price + commission
            if cost > self.cash:
                # Reject order if not enough cash
                order.status = OrderStatus.REJECTED
                order.updated_at = datetime.now()
                self.notify_order_update(order)
                self.logger.warning(f"Order {order.id} rejected: insufficient funds")
                return
                
            # Update cash
            self.cash -= cost
            
            # Update position
            if order.symbol in self.positions:
                position = self.positions[order.symbol]
                # Calculate new average entry price
                total_cost = (position.quantity * position.average_entry_price) + (order.quantity * execution_price)
                total_quantity = position.quantity + order.quantity
                position.average_entry_price = total_cost / total_quantity
                position.quantity = total_quantity
                position.current_price = bar.close
            else:
                # Create new position
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    average_entry_price=execution_price,
                    current_price=bar.close
                )
        else:  # SELL
            # Check if we have enough shares
            position = self.positions.get(order.symbol)
            if position is None or position.quantity < order.quantity:
                # Reject order if not enough shares
                order.status = OrderStatus.REJECTED
                order.updated_at = datetime.now()
                self.notify_order_update(order)
                self.logger.warning(f"Order {order.id} rejected: insufficient shares")
                return
                
            # Update cash
            self.cash += order.quantity * execution_price - commission
            
            # Update position
            position.quantity -= order.quantity
            position.current_price = bar.close
            
            # Remove position if quantity is zero
            if position.quantity == 0:
                del self.positions[order.symbol]
                
        # Update order
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = execution_price
        order.updated_at = datetime.now()
        self.notify_order_update(order)
        
        # Create trade
        trade = Trade(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            timestamp=bar.timestamp,
            order_id=order.id
        )
        self.trades.append(trade)
        self.notify_trade(trade)
        
        self.logger.info(f"Order executed: {order.id} {order.side.name} {order.quantity} {order.symbol} @ {execution_price}")
        
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Calculate performance metrics for the backtest.
        
        Returns:
            Dictionary of performance metrics
        """
        # Calculate portfolio value
        portfolio = self.get_portfolio()
        
        # Calculate profit/loss
        pnl = portfolio.equity - self.initial_cash
        pnl_percent = (pnl / self.initial_cash) * 100
        
        # Calculate number of trades
        num_trades = len(self.trades)
        
        # Calculate win/loss ratio
        winning_trades = [
            trade for trade in self.trades
            if (trade.side == OrderSide.BUY and trade.price < self.positions.get(trade.symbol, Position(trade.symbol, 0, 0)).average_entry_price) or
               (trade.side == OrderSide.SELL and trade.price > self.positions.get(trade.symbol, Position(trade.symbol, 0, 0)).average_entry_price)
        ]
        win_ratio = len(winning_trades) / num_trades if num_trades > 0 else 0
        
        return {
            'initial_cash': self.initial_cash,
            'final_equity': portfolio.equity,
            'pnl': pnl,
            'pnl_percent': pnl_percent,
            'num_trades': num_trades,
            'win_ratio': win_ratio
        } 
"""
Interactive Brokers execution provider.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime, timedelta
import logging
import time
import threading
import uuid
import pytz
from collections import defaultdict

from ib_insync import IB, Contract, Order as IBOrder, OrderStatus, Trade as IBTrade
from ib_insync.contract import Stock, Index, Option
from ib_insync.order import MarketOrder, LimitOrder, StopOrder, StopLimitOrder

from easytrade.core.types import Order, OrderType, OrderSide, TimeInForce, Position, Portfolio, Trade, OrderStatus as ETOrderStatus
from easytrade.execution.execution_provider import ExecutionProvider

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class IBExecutionProvider(ExecutionProvider):
    """
    Execution provider for Interactive Brokers.
    
    This provider connects to TWS or IB Gateway to execute trades.
    """
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1):
        """
        Initialize the IB execution provider.
        
        Args:
            host: TWS/IB Gateway host address
            port: TWS/IB Gateway port
            client_id: Client ID for the connection
        """
        super().__init__()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.host = host
        self.port = port
        self.client_id = client_id
        
        self.ib = IB()
        self.contracts = {}  # Symbol -> Contract mapping
        self.orders = {}  # Order ID -> Order mapping
        self.positions = {}  # Symbol -> Position mapping
        self.trades = []  # List of completed trades
        
        self._running = False
        self._update_thread = None
        self._order_id_to_trade = {}  # Map order IDs to IB Trade objects
        self._listening_events = False
        
    def start(self):
        """Start the execution provider."""
        if self._running:
            self.logger.warning("Execution provider is already running")
            return
            
        try:
            # Connect to IB
            self.logger.info(f"Connecting to IB at {self.host}:{self.port}")
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            
            # Start listening for events
            self._setup_event_handlers()
            
            # Start update thread
            self._running = True
            self._update_thread = threading.Thread(target=self._update_loop)
            self._update_thread.daemon = True
            self._update_thread.start()
            
            # Update initial positions
            self._update_positions()
            
            self.logger.info("IB execution provider started")
        except Exception as e:
            self.logger.error(f"Failed to start IB execution provider: {str(e)}")
            self.stop()
            raise
            
    def stop(self):
        """Stop the execution provider."""
        self._running = False
        
        if self._update_thread is not None:
            self._update_thread.join(timeout=5.0)
            self._update_thread = None
            
        if self.ib.isConnected():
            self.ib.disconnect()
            
        self._listening_events = False
        self.logger.info("IB execution provider stopped")
            
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
        if not self._running:
            self.logger.error("Cannot place order: execution provider not running")
            return self._create_rejected_order(symbol, side, quantity, order_type,
                                              price, stop_price, time_in_force,
                                              "Execution provider not running")
                                              
        # Get the contract
        contract = self._get_contract(symbol)
        if contract is None:
            self.logger.error(f"Failed to get contract for {symbol}")
            return self._create_rejected_order(symbol, side, quantity, order_type,
                                              price, stop_price, time_in_force,
                                              f"Failed to get contract for {symbol}")
        
        # Create the IB order
        ib_order = self._create_ib_order(side, quantity, order_type, price, stop_price, time_in_force)
        
        try:
            # Submit the order to IB
            trade = self.ib.placeOrder(contract, ib_order)
            
            # Create our order object
            order_id = str(ib_order.orderId)
            order = Order(
                id=order_id,
                symbol=symbol,
                order_type=order_type,
                side=side,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                status=ETOrderStatus.SUBMITTED,
                filled_quantity=0.0,
                average_fill_price=None,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            # Store the order and trade
            self.orders[order_id] = order
            self._order_id_to_trade[order_id] = trade
            
            # Notify subscribers
            self.notify_order_update(order)
            
            return order
        except Exception as e:
            self.logger.error(f"Failed to place order: {str(e)}")
            return self._create_rejected_order(symbol, side, quantity, order_type,
                                              price, stop_price, time_in_force,
                                              f"Failed to place order: {str(e)}")
                                              
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if successful, False otherwise
        """
        if not self._running:
            self.logger.error("Cannot cancel order: execution provider not running")
            return False
            
        # Check if we know about this order
        if order_id not in self.orders:
            self.logger.error(f"Unknown order ID: {order_id}")
            return False
            
        # Get the IB trade
        trade = self._order_id_to_trade.get(order_id)
        if trade is None:
            self.logger.error(f"No trade found for order ID: {order_id}")
            return False
            
        try:
            # Cancel the order
            self.ib.cancelOrder(trade.order)
            
            # Update the order status
            order = self.orders[order_id]
            order.status = ETOrderStatus.CANCELED
            order.updated_at = datetime.now()
            
            # Notify subscribers
            self.notify_order_update(order)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel order: {str(e)}")
            return False
            
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get an order by ID.
        
        Args:
            order_id: ID of order to get
            
        Returns:
            Order object if found, None otherwise
        """
        # Refresh order status first
        self._update_orders()
        
        return self.orders.get(order_id)
            
    def get_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all orders, optionally filtered by symbol.
        
        Args:
            symbol: Symbol to filter by (optional)
            
        Returns:
            List of Order objects
        """
        # Refresh order status first
        self._update_orders()
        
        if symbol is None:
            return list(self.orders.values())
        else:
            return [order for order in self.orders.values() if order.symbol == symbol]
            
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to get position for
            
        Returns:
            Position object if exists, None otherwise
        """
        # Refresh positions first
        self._update_positions()
        
        return self.positions.get(symbol)
            
    def get_positions(self) -> Dict[str, Position]:
        """
        Get all positions.
        
        Returns:
            Dictionary mapping symbol to Position object
        """
        # Refresh positions first
        self._update_positions()
        
        return self.positions
            
    def get_portfolio(self) -> Portfolio:
        """
        Get current portfolio.
        
        Returns:
            Portfolio object
        """
        # Refresh positions first
        self._update_positions()
        
        # Get account summary to get cash value
        account_values = self.ib.accountSummary()
        
        # Find the cash balance
        cash = 0.0
        for value in account_values:
            if value.tag == 'TotalCashValue' and value.currency == 'USD':
                cash = float(value.value)
                break
                
        return Portfolio(
            cash=cash,
            positions=self.positions
        )
        
    def _update_loop(self):
        """Background thread to update data and handle callbacks."""
        while self._running:
            try:
                # Process IB messages
                self.ib.sleep(0.1)
                
                # Update positions and orders periodically
                self._update_positions()
                self._update_orders()
                
                # Sleep briefly
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Error in update loop: {str(e)}")
                time.sleep(1.0)  # Sleep briefly before retrying
                
    def _setup_event_handlers(self):
        """Set up event handlers for IB callbacks."""
        if self._listening_events:
            return
            
        # Listen for order status events
        self.ib.orderStatusEvent += self._on_order_status
        
        # Listen for execution details
        self.ib.execDetailsEvent += self._on_execution_details
        
        # Listen for position changes
        self.ib.positionEvent += self._on_position
        
        self._listening_events = True
        
    def _on_order_status(self, trade: IBTrade):
        """
        Handle order status updates from IB.
        
        Args:
            trade: IB Trade object with updated status
        """
        # Get our order ID
        order_id = str(trade.order.orderId)
        
        # Update our order
        if order_id in self.orders:
            order = self.orders[order_id]
            
            # Map IB status to our status
            status = self._map_ib_status(trade.orderStatus.status)
            
            # Update order fields
            order.status = status
            order.filled_quantity = trade.orderStatus.filled
            order.average_fill_price = trade.orderStatus.avgFillPrice
            order.updated_at = datetime.now()
            
            # Notify subscribers
            self.notify_order_update(order)
            
            # If the order is filled, create a trade
            if status == ETOrderStatus.FILLED and order.filled_quantity > 0:
                self._create_trade_from_order(order)
                
    def _on_execution_details(self, trade: IBTrade, fill):
        """
        Handle execution details from IB.
        
        Args:
            trade: IB Trade object
            fill: Execution details
        """
        # Get our order ID
        order_id = str(trade.order.orderId)
        
        # Update our order
        if order_id in self.orders:
            order = self.orders[order_id]
            
            # Update filled quantity and average price
            order.filled_quantity = trade.orderStatus.filled
            order.average_fill_price = trade.orderStatus.avgFillPrice
            order.updated_at = datetime.now()
            
            # Notify subscribers
            self.notify_order_update(order)
            
            # If this is a new fill, create a trade
            if fill.execution.orderId == int(order_id) and order.filled_quantity > 0:
                self._create_trade_from_fill(order, fill)
                
    def _on_position(self, position):
        """
        Handle position updates from IB.
        
        Args:
            position: Position information from IB
        """
        # Get the symbol
        symbol = self._get_symbol_from_contract(position.contract)
        
        # Get the current price
        current_price = None
        try:
            ticker = self.ib.reqTickers(position.contract)[0]
            if ticker.last is not None:
                current_price = ticker.last
            elif ticker.close is not None:
                current_price = ticker.close
        except:
            pass
            
        # Create or update the position
        if position.position != 0:
            # Convert position to absolute value and determine average price
            abs_position = abs(position.position)
            avg_price = position.avgCost / abs_position if abs_position > 0 else 0
            
            # Create the position object
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=position.position,
                average_entry_price=avg_price,
                current_price=current_price
            )
        elif symbol in self.positions:
            # Position has been closed, remove it
            del self.positions[symbol]
            
    def _update_positions(self):
        """Update positions from IB."""
        if not self._running:
            return
            
        try:
            # Request positions from IB
            positions = self.ib.positions()
            
            # Process all positions
            for position in positions:
                self._on_position(position)
        except Exception as e:
            self.logger.error(f"Failed to update positions: {str(e)}")
            
    def _update_orders(self):
        """Update orders from IB."""
        if not self._running:
            return
            
        try:
            # Process all open trades
            for trade in self.ib.openTrades():
                self._on_order_status(trade)
        except Exception as e:
            self.logger.error(f"Failed to update orders: {str(e)}")
            
    def _get_contract(self, symbol: str):
        """
        Get a contract for a symbol.
        
        Args:
            symbol: Symbol to get contract for
            
        Returns:
            IB contract
        """
        # Check if we already have this contract
        if symbol in self.contracts:
            return self.contracts[symbol]
            
        try:
            # Parse the symbol to determine contract type
            if symbol.startswith('/'):
                # Futures contract
                parts = symbol[1:].split('-')
                underlying = parts[0]
                expiry = parts[1] if len(parts) > 1 else None
                
                contract = self.ib.reqFuturesContract(underlying, expiry)
            elif '-' in symbol:
                # Option contract
                parts = symbol.split('-')
                if len(parts) >= 3:
                    underlying = parts[0]
                    right = 'C' if 'C' in parts[1] else 'P'
                    strike = float(parts[1].replace('C', '').replace('P', ''))
                    expiry = parts[2]
                    
                    contract = Option(underlying, expiry, strike, right, exchange='SMART')
                    contracts = self.ib.qualifyContracts(contract)
                    if contracts:
                        contract = contracts[0]
                    else:
                        raise ValueError(f"Failed to qualify option contract: {symbol}")
                else:
                    raise ValueError(f"Invalid option symbol format: {symbol}")
            elif symbol in ['^SPX', 'SPX']:
                # SPX index
                contract = Index('SPX', 'CBOE')
                contracts = self.ib.qualifyContracts(contract)
                if contracts:
                    contract = contracts[0]
                else:
                    raise ValueError(f"Failed to qualify index contract: {symbol}")
            else:
                # Stock contract
                contract = Stock(symbol, 'SMART', 'USD')
                contracts = self.ib.qualifyContracts(contract)
                if contracts:
                    contract = contracts[0]
                else:
                    raise ValueError(f"Failed to qualify stock contract: {symbol}")
                    
            # Store the contract
            self.contracts[symbol] = contract
            
            return contract
        except Exception as e:
            self.logger.error(f"Failed to get contract for {symbol}: {str(e)}")
            return None
            
    def _get_symbol_from_contract(self, contract) -> str:
        """
        Get the symbol from a contract.
        
        Args:
            contract: IB contract
            
        Returns:
            Symbol string
        """
        if contract.secType == 'OPT':
            # Option contract
            return f"{contract.symbol}-{contract.right}{contract.strike}-{contract.lastTradeDateOrContractMonth}"
        elif contract.secType == 'FUT':
            # Futures contract
            return f"/{contract.symbol}-{contract.lastTradeDateOrContractMonth}"
        elif contract.secType == 'IND':
            # Index contract
            return f"^{contract.symbol}"
        else:
            # Stock or other contract
            return contract.symbol
            
    def _create_ib_order(self, side: OrderSide, quantity: float, order_type: OrderType,
                        price: Optional[float], stop_price: Optional[float],
                        time_in_force: TimeInForce) -> IBOrder:
        """
        Create an IB order object.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Quantity to trade
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price
            stop_price: Stop price
            time_in_force: Time in force
            
        Returns:
            IB Order object
        """
        # Set the action based on side
        action = 'BUY' if side == OrderSide.BUY else 'SELL'
        
        # Set the time in force
        tif = 'DAY'
        if time_in_force == TimeInForce.GTC:
            tif = 'GTC'
        elif time_in_force == TimeInForce.IOC:
            tif = 'IOC'
        elif time_in_force == TimeInForce.FOK:
            tif = 'FOK'
            
        # Create the appropriate order type
        if order_type == OrderType.MARKET:
            ib_order = MarketOrder(action, quantity, tif=tif)
        elif order_type == OrderType.LIMIT:
            if price is None:
                raise ValueError("Limit price is required for LIMIT orders")
            ib_order = LimitOrder(action, quantity, price, tif=tif)
        elif order_type == OrderType.STOP:
            if stop_price is None:
                raise ValueError("Stop price is required for STOP orders")
            ib_order = StopOrder(action, quantity, stop_price, tif=tif)
        elif order_type == OrderType.STOP_LIMIT:
            if price is None or stop_price is None:
                raise ValueError("Limit and stop prices are required for STOP_LIMIT orders")
            ib_order = StopLimitOrder(action, quantity, price, stop_price, tif=tif)
        else:
            raise ValueError(f"Unsupported order type: {order_type}")
            
        return ib_order
        
    def _map_ib_status(self, ib_status: str) -> ETOrderStatus:
        """
        Map IB order status to our status.
        
        Args:
            ib_status: IB order status string
            
        Returns:
            ETOrderStatus enum value
        """
        if ib_status == 'PendingSubmit' or ib_status == 'PendingCancel':
            return ETOrderStatus.SUBMITTED
        elif ib_status == 'PreSubmitted' or ib_status == 'ApiPending':
            return ETOrderStatus.ACCEPTED
        elif ib_status == 'Submitted':
            return ETOrderStatus.ACCEPTED
        elif ib_status == 'ApiCancelled' or ib_status == 'Cancelled':
            return ETOrderStatus.CANCELED
        elif ib_status == 'Filled':
            return ETOrderStatus.FILLED
        elif ib_status == 'PartiallyFilled':
            return ETOrderStatus.PARTIALLY_FILLED
        elif ib_status == 'Inactive':
            return ETOrderStatus.EXPIRED
        else:
            return ETOrderStatus.REJECTED
            
    def _create_rejected_order(self, symbol: str, side: OrderSide, quantity: float,
                              order_type: OrderType, price: Optional[float],
                              stop_price: Optional[float], time_in_force: TimeInForce,
                              reason: str) -> Order:
        """
        Create a rejected order object.
        
        Args:
            symbol: Symbol to trade
            side: Order side (BUY or SELL)
            quantity: Quantity to trade
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price
            stop_price: Stop price
            time_in_force: Time in force
            reason: Reason for rejection
            
        Returns:
            Order object with REJECTED status
        """
        # Create a unique ID
        order_id = str(uuid.uuid4())
        
        # Create the order object
        order = Order(
            id=order_id,
            symbol=symbol,
            order_type=order_type,
            side=side,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=ETOrderStatus.REJECTED,
            filled_quantity=0.0,
            average_fill_price=None,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Store the order
        self.orders[order_id] = order
        
        # Log the rejection
        self.logger.error(f"Order rejected: {reason}")
        
        # Notify subscribers
        self.notify_order_update(order)
        
        return order
        
    def _create_trade_from_order(self, order: Order):
        """
        Create a trade from a filled order.
        
        Args:
            order: Filled order
        """
        # Check if the order is filled
        if order.status != ETOrderStatus.FILLED:
            return
            
        # Create a trade object
        trade = Trade(
            symbol=order.symbol,
            side=order.side,
            quantity=order.filled_quantity,
            price=order.average_fill_price,
            timestamp=datetime.now(),
            order_id=order.id
        )
        
        # Add to trades list
        self.trades.append(trade)
        
        # Notify subscribers
        self.notify_trade(trade)
        
    def _create_trade_from_fill(self, order: Order, fill):
        """
        Create a trade from an execution fill.
        
        Args:
            order: Order object
            fill: Execution fill from IB
        """
        # Create a trade object
        trade = Trade(
            symbol=order.symbol,
            side=order.side,
            quantity=fill.execution.shares,
            price=fill.execution.price,
            timestamp=pd.to_datetime(fill.execution.time).to_pydatetime(),
            order_id=order.id
        )
        
        # Add to trades list
        self.trades.append(trade)
        
        # Notify subscribers
        self.notify_trade(trade) 
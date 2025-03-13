"""
Risk management component to control trading risk.
"""
import logging
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime, timedelta

from easytrade.core.types import OrderType, OrderSide, Position, Portfolio


class RiskManager:
    """
    Risk management component to control trading risk.
    
    The risk manager is responsible for enforcing risk limits and preventing
    excessive risk-taking by strategies.
    """
    
    def __init__(self, max_position_size: float = 0.1, max_order_size: float = 0.05,
                max_concentration: float = 0.25, max_drawdown: float = 0.1):
        """
        Initialize the risk manager.
        
        Args:
            max_position_size: Maximum position size as a fraction of portfolio value
            max_order_size: Maximum order size as a fraction of portfolio value
            max_concentration: Maximum concentration in a single symbol
            max_drawdown: Maximum allowed drawdown before stopping trading
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.max_position_size = max_position_size
        self.max_order_size = max_order_size
        self.max_concentration = max_concentration
        self.max_drawdown = max_drawdown
        
        self._engine = None
        self._initial_equity = None
        self._peak_equity = None
        
    def set_engine(self, engine):
        """
        Set the trading engine reference.
        
        Args:
            engine: Trading engine
        """
        self._engine = engine
        
    def check_order(self, symbol: str, side: OrderSide, quantity: float,
                   order_type: OrderType, price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if an order complies with risk limits.
        
        Args:
            symbol: Symbol to trade
            side: Order side (BUY or SELL)
            quantity: Quantity to trade
            order_type: Type of order (MARKET, LIMIT, etc.)
            price: Limit price (required for LIMIT and STOP_LIMIT orders)
            stop_price: Stop price (required for STOP and STOP_LIMIT orders)
            
        Returns:
            Tuple of (approved, modified_params)
            - approved: True if order is approved, False otherwise
            - modified_params: Modified order parameters if any, None otherwise
        """
        if self._engine is None:
            self.logger.error("Cannot check order: engine not set")
            return False, None
            
        # Get current portfolio
        portfolio = self._engine.get_portfolio()
        
        # Initialize equity tracking
        if self._initial_equity is None:
            self._initial_equity = portfolio.equity
            self._peak_equity = portfolio.equity
        else:
            self._peak_equity = max(self._peak_equity, portfolio.equity)
            
        # Check for drawdown
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - portfolio.equity) / self._peak_equity
            if drawdown > self.max_drawdown:
                self.logger.warning(f"Order rejected: drawdown {drawdown:.2%} exceeds limit {self.max_drawdown:.2%}")
                return False, None
                
        # Get current position
        position = self._engine.get_position(symbol)
        
        # Calculate order value
        order_price = price if price is not None else stop_price
        if order_price is None:
            # For market orders, use the latest price if available
            if position is not None and position.current_price is not None:
                order_price = position.current_price
            else:
                # Cannot determine order value, reject
                self.logger.warning(f"Order rejected: cannot determine order value for {symbol}")
                return False, None
                
        order_value = quantity * order_price
        
        # Check order size
        if portfolio.equity > 0:
            order_size_ratio = order_value / portfolio.equity
            if order_size_ratio > self.max_order_size:
                # Reduce order size to comply with limit
                modified_quantity = (self.max_order_size * portfolio.equity) / order_price
                self.logger.warning(f"Order size reduced: {quantity} -> {modified_quantity:.2f} {symbol}")
                return True, {'quantity': modified_quantity}
                
        # Check position size (for buys)
        if side == OrderSide.BUY and portfolio.equity > 0:
            # Calculate new position value
            if position is not None:
                new_position_value = position.market_value + order_value
            else:
                new_position_value = order_value
                
            position_size_ratio = new_position_value / portfolio.equity
            if position_size_ratio > self.max_position_size:
                # Reduce order size to comply with limit
                if position is not None and position.market_value > 0:
                    max_additional = (self.max_position_size * portfolio.equity) - position.market_value
                    if max_additional <= 0:
                        self.logger.warning(f"Order rejected: position size for {symbol} already at limit")
                        return False, None
                        
                    modified_quantity = max_additional / order_price
                    self.logger.warning(f"Order size reduced: {quantity} -> {modified_quantity:.2f} {symbol}")
                    return True, {'quantity': modified_quantity}
                else:
                    modified_quantity = (self.max_position_size * portfolio.equity) / order_price
                    self.logger.warning(f"Order size reduced: {quantity} -> {modified_quantity:.2f} {symbol}")
                    return True, {'quantity': modified_quantity}
                    
        # Check portfolio concentration
        if side == OrderSide.BUY and portfolio.equity > 0:
            # Calculate total position value
            total_position_value = sum(
                pos.market_value or 0 
                for pos in portfolio.positions.values() 
                if pos.market_value is not None
            )
            
            # Calculate new position value
            if position is not None:
                new_position_value = position.market_value + order_value
            else:
                new_position_value = order_value
                
            # Calculate new total position value
            new_total_position_value = total_position_value + order_value
            
            # Calculate concentration
            if new_total_position_value > 0:
                concentration = new_position_value / new_total_position_value
                if concentration > self.max_concentration:
                    # Reduce order size to comply with limit
                    max_position_value = self.max_concentration * (new_total_position_value - new_position_value) / (1 - self.max_concentration)
                    if position is not None and position.market_value > 0:
                        max_additional = max_position_value - position.market_value
                        if max_additional <= 0:
                            self.logger.warning(f"Order rejected: concentration for {symbol} already at limit")
                            return False, None
                            
                        modified_quantity = max_additional / order_price
                        self.logger.warning(f"Order size reduced: {quantity} -> {modified_quantity:.2f} {symbol}")
                        return True, {'quantity': modified_quantity}
                    else:
                        modified_quantity = max_position_value / order_price
                        self.logger.warning(f"Order size reduced: {quantity} -> {modified_quantity:.2f} {symbol}")
                        return True, {'quantity': modified_quantity}
                        
        # Order is approved
        return True, None 
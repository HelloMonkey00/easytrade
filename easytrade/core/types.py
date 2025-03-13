"""
Common data types and enums used throughout the framework.
"""
from enum import Enum, auto
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List, Union, Tuple


class OrderType(Enum):
    """Types of orders that can be placed."""
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()


class OrderSide(Enum):
    """Side of an order (buy or sell)."""
    BUY = auto()
    SELL = auto()


class OrderStatus(Enum):
    """Status of an order."""
    CREATED = auto()
    SUBMITTED = auto()
    ACCEPTED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class TimeInForce(Enum):
    """Time in force for an order."""
    DAY = auto()
    GTC = auto()  # Good Till Canceled
    IOC = auto()  # Immediate or Cancel
    FOK = auto()  # Fill or Kill


@dataclass
class Bar:
    """Represents OHLCV data for a single time period."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Bar to dictionary."""
        return {
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Bar':
        """Create Bar from dictionary."""
        return cls(
            timestamp=data['timestamp'],
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume']
        )


@dataclass
class Order:
    """Represents a trading order."""
    id: Optional[str] = None
    symbol: str = ""
    order_type: OrderType = OrderType.MARKET
    side: OrderSide = OrderSide.BUY
    quantity: float = 0.0
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Order to dictionary."""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'order_type': self.order_type.name,
            'side': self.side.name,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'time_in_force': self.time_in_force.name,
            'status': self.status.name,
            'filled_quantity': self.filled_quantity,
            'average_fill_price': self.average_fill_price,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    quantity: float
    average_entry_price: float
    current_price: Optional[float] = None
    
    @property
    def market_value(self) -> Optional[float]:
        """Calculate the current market value of the position."""
        if self.current_price is not None:
            return self.quantity * self.current_price
        return None
    
    @property
    def unrealized_pnl(self) -> Optional[float]:
        """Calculate the unrealized profit/loss."""
        if self.current_price is not None:
            return self.quantity * (self.current_price - self.average_entry_price)
        return None
    
    @property
    def unrealized_pnl_percent(self) -> Optional[float]:
        """Calculate the unrealized profit/loss as a percentage."""
        if self.current_price is not None and self.average_entry_price != 0:
            return ((self.current_price / self.average_entry_price) - 1) * 100
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Position to dictionary."""
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'average_entry_price': self.average_entry_price,
            'current_price': self.current_price,
            'market_value': self.market_value,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_percent': self.unrealized_pnl_percent
        }


@dataclass
class Trade:
    """Represents a completed trade."""
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp: datetime
    order_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Trade to dictionary."""
        return {
            'symbol': self.symbol,
            'side': self.side.name,
            'quantity': self.quantity,
            'price': self.price,
            'timestamp': self.timestamp,
            'order_id': self.order_id
        }


@dataclass
class Portfolio:
    """Represents a portfolio of positions and cash."""
    cash: float
    positions: Dict[str, Position]
    
    @property
    def equity(self) -> float:
        """Calculate the total equity (cash + position values)."""
        position_value = sum(
            pos.market_value or 0 
            for pos in self.positions.values() 
            if pos.market_value is not None
        )
        return self.cash + position_value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Portfolio to dictionary."""
        return {
            'cash': self.cash,
            'positions': {symbol: pos.to_dict() for symbol, pos in self.positions.items()},
            'equity': self.equity
        } 
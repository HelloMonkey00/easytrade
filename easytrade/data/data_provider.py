"""
Abstract base class for data providers.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta

from easytrade.core.types import Bar


class DataProvider(ABC):
    """
    Abstract base class for data providers.
    
    Data providers are responsible for retrieving market data from various sources
    and providing it to the trading engine in a standardized format.
    """
    
    def __init__(self):
        """Initialize the data provider."""
        self._subscribers = []
        
    def add_subscriber(self, subscriber):
        """
        Add a subscriber to receive data updates.
        
        Args:
            subscriber: Object that will receive data updates
        """
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)
            
    def remove_subscriber(self, subscriber):
        """
        Remove a subscriber.
        
        Args:
            subscriber: Subscriber to remove
        """
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)
            
    def notify_subscribers(self, data: Dict[str, Bar]):
        """
        Notify all subscribers with new data.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        for subscriber in self._subscribers:
            if callable(subscriber):
                # If subscriber is a callable (function), call it directly
                subscriber(data)
            elif hasattr(subscriber, 'on_data'):
                # If subscriber has an on_data method, call that
                subscriber.on_data(data)
            
    @abstractmethod
    def start(self):
        """Start the data provider."""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the data provider."""
        pass
    
    @abstractmethod
    def get_current_data(self, symbols: List[str]) -> Dict[str, Bar]:
        """
        Get current market data for the specified symbols.
        
        Args:
            symbols: List of symbols to get data for
            
        Returns:
            Dictionary mapping symbol to Bar object
        """
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, start_date: datetime, 
                           end_date: Optional[datetime] = None,
                           interval: str = '1d') -> List[Bar]:
        """
        Get historical market data for a symbol.
        
        Args:
            symbol: Symbol to get data for
            start_date: Start date for historical data
            end_date: End date for historical data (defaults to current time)
            interval: Bar interval (e.g., '1m', '5m', '1h', '1d')
            
        Returns:
            List of Bar objects
        """
        pass
    
    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Optional[Bar]:
        """
        Get the latest bar for a symbol.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            Bar object if available, None otherwise
        """
        pass
    
    @abstractmethod
    def get_symbols(self) -> List[str]:
        """
        Get all available symbols.
        
        Returns:
            List of available symbols
        """
        pass 
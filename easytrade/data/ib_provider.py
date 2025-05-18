"""
Interactive Brokers data provider.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import logging
import time
import threading
import pytz

from ib_insync import IB, Contract, ContractDetails, BarData, util
from ib_insync.contract import Stock, Index, Option

from easytrade.core.types import Bar
from easytrade.data.data_provider import DataProvider

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class IBDataProvider(DataProvider):
    """
    Data provider for Interactive Brokers.
    
    This provider connects to TWS or IB Gateway to retrieve market data.
    """
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1,
                 symbols: List[str] = None, update_interval: int = 5):
        """
        Initialize the IB data provider.
        
        Args:
            host: TWS/IB Gateway host address
            port: TWS/IB Gateway port
            client_id: Client ID for the connection
            symbols: List of symbols to subscribe to
            update_interval: Data update interval in seconds
        """
        super().__init__()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.host = host
        self.port = port
        self.client_id = client_id
        self.symbols = symbols or []
        self.update_interval = update_interval
        
        self.ib = IB()
        self.contracts = {}  # Symbol -> Contract mapping
        self.latest_data = {}  # Symbol -> Bar mapping
        self.historical_data = {}  # Symbol -> List[Bar] mapping
        
        self._running = False
        self._update_thread = None
        
    def start(self):
        """Start the data provider."""
        if self._running:
            self.logger.warning("Data provider is already running")
            return
            
        try:
            # Connect to IB
            self.logger.info(f"Connecting to IB at {self.host}:{self.port}")
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            
            # Subscribe to market data for all symbols
            self._subscribe_market_data()
            
            # Start update thread
            self._running = True
            self._update_thread = threading.Thread(target=self._update_loop)
            self._update_thread.daemon = True
            self._update_thread.start()
            
            self.logger.info("IB data provider started")
        except Exception as e:
            self.logger.error(f"Failed to start IB data provider: {str(e)}")
            self.stop()
            raise
            
    def stop(self):
        """Stop the data provider."""
        self._running = False
        
        if self._update_thread is not None:
            self._update_thread.join(timeout=5.0)
            self._update_thread = None
            
        if self.ib.isConnected():
            self.ib.disconnect()
            
        self.logger.info("IB data provider stopped")
            
    def get_current_data(self, symbols: List[str]) -> Dict[str, Bar]:
        """
        Get current market data for the specified symbols.
        
        Args:
            symbols: List of symbols to get data for
            
        Returns:
            Dictionary mapping symbol to Bar object
        """
        result = {}
        
        for symbol in symbols:
            if symbol in self.latest_data:
                result[symbol] = self.latest_data[symbol]
                
        return result
        
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
        if end_date is None:
            end_date = datetime.now()
            
        # Check if we already have this data
        if symbol in self.historical_data:
            # Filter existing data by date range
            cached_data = [
                bar for bar in self.historical_data[symbol]
                if start_date <= bar.timestamp <= end_date
            ]
            
            # If we have sufficient data, return it
            if len(cached_data) > 0:
                first_bar = cached_data[0]
                last_bar = cached_data[-1]
                
                if first_bar.timestamp <= start_date and last_bar.timestamp >= end_date:
                    return cached_data
                    
        # Request historical data from IB
        contract = self._get_contract(symbol)
        if contract is None:
            self.logger.error(f"Failed to get contract for {symbol}")
            return []
            
        duration = self._calculate_duration(start_date, end_date)
        bar_size = self._map_interval_to_bar_size(interval)
        
        try:
            # Make the request
            bars = self.ib.reqHistoricalData(
                contract=contract,
                endDateTime=end_date.strftime('%Y%m%d %H:%M:%S'),
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            # Convert to Bar objects
            result = []
            for bar in bars:
                timestamp = pd.to_datetime(bar.date).to_pydatetime()
                result.append(Bar(
                    timestamp=timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume
                ))
                
            # Update cache
            self.historical_data[symbol] = result
            
            return result
        except Exception as e:
            self.logger.error(f"Failed to get historical data for {symbol}: {str(e)}")
            return []
            
    def get_latest_bar(self, symbol: str) -> Optional[Bar]:
        """
        Get the latest bar for a symbol.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            Bar object if available, None otherwise
        """
        return self.latest_data.get(symbol)
        
    def get_symbols(self) -> List[str]:
        """
        Get all available symbols.
        
        Returns:
            List of available symbols
        """
        return list(self.contracts.keys())
        
    def add_symbol(self, symbol: str):
        """
        Add a symbol to track.
        
        Args:
            symbol: Symbol to add
        """
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            
            if self._running:
                # Subscribe to market data for this symbol
                contract = self._get_contract(symbol)
                if contract is not None:
                    self._subscribe_market_data_for_contract(contract)
                    
    def remove_symbol(self, symbol: str):
        """
        Remove a symbol from tracking.
        
        Args:
            symbol: Symbol to remove
        """
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            
            if symbol in self.contracts:
                contract = self.contracts[symbol]
                # Cancel market data for this symbol
                self.ib.cancelMktData(contract)
                del self.contracts[symbol]
            
            if symbol in self.latest_data:
                del self.latest_data[symbol]
                
            if symbol in self.historical_data:
                del self.historical_data[symbol]
                
    def _update_loop(self):
        """Background thread to update data and notify subscribers."""
        while self._running:
            try:
                # Process IB messages
                self.ib.sleep(0.1)
                
                # Collect latest data for all symbols
                current_data = {}
                for symbol, contract in self.contracts.items():
                    bar = self._get_latest_bar_for_contract(contract)
                    if bar is not None:
                        current_data[symbol] = bar
                        self.latest_data[symbol] = bar
                
                # Notify subscribers if we have data
                if current_data:
                    self.notify_subscribers(current_data)
                    
                # Sleep for the update interval
                time.sleep(self.update_interval)
            except Exception as e:
                self.logger.error(f"Error in update loop: {str(e)}")
                time.sleep(1.0)  # Sleep briefly before retrying
                
    def _subscribe_market_data(self):
        """Subscribe to market data for all symbols."""
        for symbol in self.symbols:
            contract = self._get_contract(symbol)
            if contract is not None:
                self._subscribe_market_data_for_contract(contract)
                
    def _subscribe_market_data_for_contract(self, contract):
        """
        Subscribe to market data for a contract.
        
        Args:
            contract: IB contract
        """
        try:
            # Subscribe to market data
            self.ib.reqMktData(contract, '', False, False)
            
            # Store the contract
            symbol = self._get_symbol_from_contract(contract)
            self.contracts[symbol] = contract
            
            self.logger.info(f"Subscribed to market data for {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to subscribe to market data: {str(e)}")
            
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
            
    def _get_latest_bar_for_contract(self, contract) -> Optional[Bar]:
        """
        Get the latest bar for a contract.
        
        Args:
            contract: IB contract
            
        Returns:
            Bar object if available, None otherwise
        """
        try:
            # Get the latest tick from IB
            ticker = self.ib.ticker(contract)
            
            # Check if we have valid data
            if not hasattr(ticker, 'last') or ticker.last is None:
                return None
                
            # Create a Bar object
            timestamp = datetime.now()
            if hasattr(ticker, 'time') and ticker.time is not None:
                timestamp = ticker.time
                
            return Bar(
                timestamp=timestamp,
                open=ticker.open,
                high=ticker.high,
                low=ticker.low,
                close=ticker.last,
                volume=ticker.volume
            )
        except Exception as e:
            self.logger.error(f"Failed to get latest bar: {str(e)}")
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
            
    def _calculate_duration(self, start_date: datetime, end_date: datetime) -> str:
        """
        Calculate duration string for historical data request.
        
        Args:
            start_date: Start date
            end_date: End date
            
        Returns:
            Duration string in IB format
        """
        delta = end_date - start_date
        days = delta.days
        
        if days <= 1:
            return "1 D"
        elif days <= 7:
            return "1 W"
        elif days <= 30:
            return "1 M"
        elif days <= 90:
            return "3 M"
        elif days <= 180:
            return "6 M"
        elif days <= 365:
            return "1 Y"
        else:
            years = days // 365
            return f"{years} Y"
            
    def _map_interval_to_bar_size(self, interval: str) -> str:
        """
        Map interval string to IB bar size string.
        
        Args:
            interval: Interval string (e.g., '1m', '5m', '1h', '1d')
            
        Returns:
            Bar size string in IB format
        """
        interval = interval.lower()
        
        if interval == '1s':
            return "1 secs"
        elif interval == '5s':
            return "5 secs"
        elif interval == '10s':
            return "10 secs"
        elif interval == '15s':
            return "15 secs"
        elif interval == '30s':
            return "30 secs"
        elif interval == '1m':
            return "1 min"
        elif interval == '2m':
            return "2 mins"
        elif interval == '5m':
            return "5 mins"
        elif interval == '10m':
            return "10 mins"
        elif interval == '15m':
            return "15 mins"
        elif interval == '30m':
            return "30 mins"
        elif interval == '1h':
            return "1 hour"
        elif interval == '2h':
            return "2 hours"
        elif interval == '4h':
            return "4 hours"
        elif interval == '1d':
            return "1 day"
        elif interval == '1w':
            return "1 week"
        elif interval == '1mo':
            return "1 month"
        else:
            # Default to 1 minute if unknown
            self.logger.warning(f"Unknown interval: {interval}, defaulting to 1 min")
            return "1 min" 
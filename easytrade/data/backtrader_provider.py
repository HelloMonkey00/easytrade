"""
Backtrader data provider adapter.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import logging
import time
import threading
import pytz
import backtrader as bt

from easytrade.core.types import Bar
from easytrade.data.data_provider import DataProvider

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class BacktraderDataProvider(DataProvider):
    """
    Data provider adapter for Backtrader.
    
    This provider retrieves data from backtrader DataFeeds and converts it to the
    standard easytrade format.
    """
    
    def __init__(self, cerebro: bt.Cerebro, data_interval: str = '5s'):
        """
        Initialize the Backtrader data provider.
        
        Args:
            cerebro: Backtrader cerebro instance with data feeds
            data_interval: Interval of the data feeds
        """
        super().__init__()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cerebro = cerebro
        self.data_interval = data_interval
        
        self.latest_data = {}  # Symbol -> Bar mapping
        self.data_feeds = {}  # Symbol -> DataFeed mapping
        self.historical_data = {}  # Symbol -> List[Bar] mapping
        
        self._running = False
        self._update_thread = None
        self._extract_data_feeds()
        
    def start(self):
        """Start the data provider."""
        if self._running:
            self.logger.warning("Data provider is already running")
            return
            
        try:
            # Start update thread
            self._running = True
            self._update_thread = threading.Thread(target=self._update_loop)
            self._update_thread.daemon = True
            self._update_thread.start()
            
            self.logger.info("Backtrader data provider started")
        except Exception as e:
            self.logger.error(f"Failed to start Backtrader data provider: {str(e)}")
            self.stop()
            raise
            
    def stop(self):
        """Stop the data provider."""
        self._running = False
        
        if self._update_thread is not None:
            self._update_thread.join(timeout=5.0)
            self._update_thread = None
            
        self.logger.info("Backtrader data provider stopped")
            
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
            
        # Check if we have this data already
        if symbol in self.historical_data:
            # Filter by date range
            return [
                bar for bar in self.historical_data[symbol]
                if start_date <= bar.timestamp <= end_date
            ]
            
        # If not in historical data, but we have a data feed
        if symbol in self.data_feeds:
            data_feed = self.data_feeds[symbol]
            
            # Extract historical data from the data feed
            try:
                # Convert Backtrader data to Bar objects
                result = []
                for i in range(len(data_feed)):
                    timestamp = bt.num2date(data_feed.datetime[i])
                    if timestamp.tzinfo is None:
                        timestamp = NY_TZ.localize(timestamp)
                    
                    if start_date <= timestamp <= end_date:
                        result.append(Bar(
                            timestamp=timestamp,
                            open=data_feed.open[i],
                            high=data_feed.high[i],
                            low=data_feed.low[i],
                            close=data_feed.close[i],
                            volume=data_feed.volume[i] if hasattr(data_feed, 'volume') else 0
                        ))
                
                # Store for future use
                self.historical_data[symbol] = result
                
                return result
            except Exception as e:
                self.logger.error(f"Failed to extract historical data: {str(e)}")
                
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
        return list(self.data_feeds.keys())
        
    def _extract_data_feeds(self):
        """Extract data feeds from cerebro instance."""
        if not hasattr(self.cerebro, 'datas'):
            self.logger.warning("No data feeds found in cerebro instance")
            return
            
        for i, data in enumerate(self.cerebro.datas):
            symbol = data._name
            if symbol is None or symbol == '':
                symbol = f"Data_{i}"
                
            self.data_feeds[symbol] = data
            self.logger.info(f"Found data feed for {symbol}")
            
    def _update_loop(self):
        """Background thread to update data and notify subscribers."""
        while self._running:
            try:
                # Update latest data for all symbols
                current_data = {}
                
                for symbol, data_feed in self.data_feeds.items():
                    # Check if there's data
                    if len(data_feed) > 0:
                        # Get the latest bar
                        index = 0  # Latest bar index
                        
                        timestamp = bt.num2date(data_feed.datetime[index])
                        if timestamp.tzinfo is None:
                            timestamp = NY_TZ.localize(timestamp)
                            
                        bar = Bar(
                            timestamp=timestamp,
                            open=data_feed.open[index],
                            high=data_feed.high[index],
                            low=data_feed.low[index],
                            close=data_feed.close[index],
                            volume=data_feed.volume[index] if hasattr(data_feed, 'volume') else 0
                        )
                        
                        current_data[symbol] = bar
                        self.latest_data[symbol] = bar
                
                # Notify subscribers if we have data
                if current_data:
                    self.notify_subscribers(current_data)
                    
                # Sleep briefly
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Error in update loop: {str(e)}")
                time.sleep(1.0)  # Sleep briefly before retrying
                
    def add_data_feed(self, symbol: str, data_feed):
        """
        Add a data feed.
        
        Args:
            symbol: Symbol for the data feed
            data_feed: Backtrader data feed
        """
        self.data_feeds[symbol] = data_feed
        
        # Extract historical data
        try:
            result = []
            for i in range(len(data_feed)):
                timestamp = bt.num2date(data_feed.datetime[i])
                if timestamp.tzinfo is None:
                    timestamp = NY_TZ.localize(timestamp)
                
                result.append(Bar(
                    timestamp=timestamp,
                    open=data_feed.open[i],
                    high=data_feed.high[i],
                    low=data_feed.low[i],
                    close=data_feed.close[i],
                    volume=data_feed.volume[i] if hasattr(data_feed, 'volume') else 0
                ))
            
            self.historical_data[symbol] = result
        except Exception as e:
            self.logger.error(f"Failed to extract historical data for {symbol}: {str(e)}")
            
    def load_dataframe(self, symbol: str, df: pd.DataFrame, datetime_col: str = 'datetime',
                      timeframe: int = bt.TimeFrame.Seconds, compression: int = 1):
        """
        Load data from a DataFrame.
        
        Args:
            symbol: Symbol for the data
            df: DataFrame with OHLCV data
            datetime_col: Name of the datetime column
            timeframe: Backtrader timeframe
            compression: Backtrader compression
        """
        # Convert DataFrame to Backtrader data feed
        data_feed = bt.feeds.PandasData(
            dataname=df,
            datetime=datetime_col,
            timeframe=timeframe,
            compression=compression
        )
        
        # Add the data feed
        self.cerebro.adddata(data_feed, name=symbol)
        self.add_data_feed(symbol, data_feed)
        
        self.logger.info(f"Added data feed for {symbol}")
        
        # Extract bars from the DataFrame
        try:
            result = []
            for i, row in df.iterrows():
                timestamp = pd.to_datetime(row[datetime_col])
                if timestamp.tzinfo is None:
                    timestamp = NY_TZ.localize(timestamp)
                
                result.append(Bar(
                    timestamp=timestamp,
                    open=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    volume=row['volume'] if 'volume' in row else 0
                ))
            
            self.historical_data[symbol] = result
            
            # Set latest data
            if result:
                self.latest_data[symbol] = result[-1]
        except Exception as e:
            self.logger.error(f"Failed to extract bars from DataFrame for {symbol}: {str(e)}")
            
    def load_market_data(self, symbol: str, df: pd.DataFrame, freq: str = '5S',
                        datetime_col: str = 'datetime'):
        """
        Load and process market data.
        
        Args:
            symbol: Symbol for the data
            df: DataFrame with raw data
            freq: Resampling frequency
            datetime_col: Name of the datetime column
        """
        # Process the DataFrame
        df = self._process_market_data(df, symbol, freq, datetime_col)
        
        # Determine timeframe and compression based on frequency
        timeframe, compression = self._map_freq_to_timeframe(freq)
        
        # Load the processed DataFrame
        self.load_dataframe(symbol, df, datetime_col, timeframe, compression)
        
    def _process_market_data(self, df: pd.DataFrame, symbol: str, freq: str = '5S',
                            datetime_col: str = 'datetime') -> pd.DataFrame:
        """
        Process market data DataFrame.
        
        Args:
            df: DataFrame with raw data
            symbol: Symbol for the data
            freq: Resampling frequency
            datetime_col: Name of the datetime column
            
        Returns:
            Processed DataFrame
        """
        # Ensure datetime column is datetime
        if datetime_col not in df.columns:
            if 'date' in df.columns:
                df[datetime_col] = pd.to_datetime(df['date'])
            else:
                raise ValueError(f"No datetime column found in DataFrame for {symbol}")
        else:
            df[datetime_col] = pd.to_datetime(df[datetime_col])
            
        # Standardize timezone
        if df[datetime_col].dt.tz is None:
            df[datetime_col] = df[datetime_col].dt.tz_localize('America/New_York')
        else:
            df[datetime_col] = df[datetime_col].dt.tz_convert('America/New_York')
            
        # Move SPY/QQQ data forward by 5 seconds to account for processing delay
        if symbol in ['SPY', 'QQQ']:
            df[datetime_col] = df[datetime_col] + timedelta(seconds=5)
            
        # Set index
        df.set_index(datetime_col, inplace=True)
        
        # Filter market hours
        df = df.between_time('09:30:00', '16:00:00')
        
        # Drop duplicate indices
        df = df[~df.index.duplicated(keep='first')]
        
        # Ensure OHLCV columns
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                # Use reasonable defaults if a column is missing
                if col == 'volume':
                    df[col] = 0
                elif col in ['high', 'low']:
                    df[col] = df['close'] if 'close' in df.columns else 0
                else:
                    df[col] = 0
                    
        return df
        
    def _map_freq_to_timeframe(self, freq: str) -> tuple:
        """
        Map frequency string to backtrader timeframe and compression.
        
        Args:
            freq: Frequency string (e.g., '5S', '1T', '1H')
            
        Returns:
            Tuple of (timeframe, compression)
        """
        freq = freq.upper()
        
        if freq.endswith('S'):
            timeframe = bt.TimeFrame.Seconds
            compression = int(freq[:-1])
        elif freq.endswith('T') or freq.endswith('MIN'):
            timeframe = bt.TimeFrame.Minutes
            compression = int(freq[:-1]) if freq.endswith('T') else int(freq[:-3])
        elif freq.endswith('H'):
            timeframe = bt.TimeFrame.Minutes
            compression = int(freq[:-1]) * 60
        elif freq.endswith('D'):
            timeframe = bt.TimeFrame.Days
            compression = int(freq[:-1])
        elif freq.endswith('W'):
            timeframe = bt.TimeFrame.Weeks
            compression = int(freq[:-1])
        elif freq.endswith('M'):
            timeframe = bt.TimeFrame.Months
            compression = int(freq[:-1])
        else:
            # Default to seconds
            self.logger.warning(f"Unknown frequency format: {freq}, defaulting to 1 second")
            timeframe = bt.TimeFrame.Seconds
            compression = 1
            
        return timeframe, compression 
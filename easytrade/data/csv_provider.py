"""
CSV data provider for loading historical OHLCV data from CSV files.
"""
import os
import pandas as pd
import logging
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta
import time
import threading

from easytrade.data.data_provider import DataProvider
from easytrade.core.types import Bar


class CSVDataProvider(DataProvider):
    """
    CSV data provider for loading historical OHLCV data from CSV files.
    
    This provider can load data from CSV files and simulate real-time data
    by replaying historical data at a specified speed.
    """
    
    def __init__(self, data_dir: str, date_format: str = '%Y-%m-%d %H:%M:%S.%f',
                 timestamp_column: str = 'timestamp',
                 ohlcv_columns: Dict[str, str] = None):
        """
        Initialize the CSV data provider.
        
        Args:
            data_dir: Directory containing CSV files
            date_format: Format of date strings in CSV files
            timestamp_column: Name of timestamp column in CSV files
            ohlcv_columns: Dictionary mapping OHLCV column names to CSV column names
        """
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.data_dir = data_dir
        self.date_format = date_format
        self.timestamp_column = timestamp_column
        
        # Default OHLCV column mappings
        self.ohlcv_columns = {
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }
        
        if ohlcv_columns is not None:
            self.ohlcv_columns.update(ohlcv_columns)
            
        self._data = {}  # Symbol -> DataFrame mapping
        self._current_index = {}  # Symbol -> current index in DataFrame
        self._running = False
        self._thread = None
        self._replay_speed = 1.0  # Speed multiplier for replaying data
        self._replay_interval = 1.0  # Seconds between data updates
        
    def load_csv_file(self, file_path: str, symbol: str = None) -> bool:
        """
        Load data from a CSV file.
        
        Args:
            file_path: Path to CSV file
            symbol: Symbol to associate with this data (defaults to filename without extension)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if symbol is None:
                symbol = os.path.splitext(os.path.basename(file_path))[0]
                
            df = pd.read_csv(file_path)
            self.logger.debug(f"Loaded CSV file {file_path} with {len(df)} rows")
            
            # Try to convert timestamp column to datetime with specified format
            try:
                df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column], format=self.date_format)
                self.logger.debug(f"Successfully parsed dates with format {self.date_format}")
            except ValueError:
                # If that fails, try with a more flexible approach
                self.logger.warning(f"Failed to parse dates with format {self.date_format}, trying flexible parsing")
                df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column])
                self.logger.debug(f"Successfully parsed dates with flexible parsing")
            
            # Sort by timestamp
            df = df.sort_values(by=self.timestamp_column)
            
            # Store data
            self._data[symbol] = df
            self._current_index[symbol] = 0
            
            self.logger.info(f"Loaded {len(df)} rows for {symbol} from {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading CSV file {file_path}: {e}")
            return False
            
    def load_directory(self) -> int:
        """
        Load all CSV files in the data directory.
        
        Returns:
            Number of files successfully loaded
        """
        count = 0
        self.logger.debug(f"Loading CSV files from directory: {self.data_dir}")
        
        # Check if directory exists
        if not os.path.exists(self.data_dir):
            self.logger.error(f"Data directory does not exist: {self.data_dir}")
            return count
            
        # List files in directory
        files = os.listdir(self.data_dir)
        self.logger.debug(f"Found {len(files)} files in directory: {files}")
        
        for filename in files:
            if filename.endswith('.csv'):
                file_path = os.path.join(self.data_dir, filename)
                symbol = os.path.splitext(filename)[0]
                self.logger.debug(f"Attempting to load {file_path} for symbol {symbol}")
                if self.load_csv_file(file_path, symbol):
                    count += 1
                    
        self.logger.info(f"Loaded {count} CSV files from {self.data_dir}")
        return count
        
    def set_replay_speed(self, speed: float):
        """
        Set the speed at which historical data is replayed.
        
        Args:
            speed: Speed multiplier (1.0 = real-time, 2.0 = 2x speed, etc.)
        """
        if speed <= 0:
            raise ValueError("Replay speed must be positive")
            
        self._replay_speed = speed
        self._replay_interval = 1.0 / speed
        
    def _replay_data(self):
        """Replay historical data at the specified speed."""
        self.logger.debug(f"Starting data replay with {len(self._data)} symbols")
        
        while self._running:
            # Get current data for all symbols
            data = {}
            for symbol, df in self._data.items():
                idx = self._current_index[symbol]
                if idx < len(df):
                    row = df.iloc[idx]
                    bar = Bar(
                        timestamp=row[self.timestamp_column],
                        open=row[self.ohlcv_columns['open']],
                        high=row[self.ohlcv_columns['high']],
                        low=row[self.ohlcv_columns['low']],
                        close=row[self.ohlcv_columns['close']],
                        volume=row[self.ohlcv_columns['volume']]
                    )
                    data[symbol] = bar
                    self._current_index[symbol] += 1
                    
            # Notify subscribers if we have data
            if data:
                self.logger.debug(f"Notifying subscribers with data for {len(data)} symbols")
                self.notify_subscribers(data)
            else:
                self.logger.debug("No data to send to subscribers")
                
            # Check if we've reached the end of all data
            if all(self._current_index[symbol] >= len(df) for symbol, df in self._data.items()):
                self.logger.info("Reached end of all data")
                self._running = False
                break
                
            # Sleep until next update
            time.sleep(self._replay_interval)
            
    def start(self):
        """Start the data provider."""
        if not self._data:
            self.load_directory()
            
        if not self._data:
            raise ValueError("No data loaded")
            
        self._running = True
        self._thread = threading.Thread(target=self._replay_data)
        self._thread.daemon = True
        self._thread.start()
        
        self.logger.info("CSV data provider started")
        
    def stop(self):
        """Stop the data provider."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
            
        self.logger.info("CSV data provider stopped")
        
    def reset(self):
        """Reset the data provider state."""
        self.logger.debug("Resetting CSV data provider")
        
        # Stop if running
        if self._running:
            self.stop()
            
        # Reset indices
        for symbol in self._current_index:
            self._current_index[symbol] = 0
            
        self.logger.debug("CSV data provider reset complete")
        
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
            if symbol in self._data:
                idx = self._current_index[symbol]
                if idx > 0:  # We have some data
                    row = self._data[symbol].iloc[idx - 1]
                    bar = Bar(
                        timestamp=row[self.timestamp_column],
                        open=row[self.ohlcv_columns['open']],
                        high=row[self.ohlcv_columns['high']],
                        low=row[self.ohlcv_columns['low']],
                        close=row[self.ohlcv_columns['close']],
                        volume=row[self.ohlcv_columns['volume']]
                    )
                    result[symbol] = bar
                    
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
        if symbol not in self._data:
            return []
            
        if end_date is None:
            end_date = datetime.now()
            
        # Filter data by date range
        df = self._data[symbol]
        mask = (df[self.timestamp_column] >= start_date) & (df[self.timestamp_column] <= end_date)
        filtered_df = df[mask]
        
        # Convert to Bar objects
        bars = []
        for _, row in filtered_df.iterrows():
            bar = Bar(
                timestamp=row[self.timestamp_column],
                open=row[self.ohlcv_columns['open']],
                high=row[self.ohlcv_columns['high']],
                low=row[self.ohlcv_columns['low']],
                close=row[self.ohlcv_columns['close']],
                volume=row[self.ohlcv_columns['volume']]
            )
            bars.append(bar)
            
        return bars
        
    def get_latest_bar(self, symbol: str) -> Optional[Bar]:
        """
        Get the latest bar for a symbol.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            Bar object if available, None otherwise
        """
        if symbol not in self._data:
            return None
            
        idx = self._current_index[symbol]
        if idx > 0:  # We have some data
            row = self._data[symbol].iloc[idx - 1]
            bar = Bar(
                timestamp=row[self.timestamp_column],
                open=row[self.ohlcv_columns['open']],
                high=row[self.ohlcv_columns['high']],
                low=row[self.ohlcv_columns['low']],
                close=row[self.ohlcv_columns['close']],
                volume=row[self.ohlcv_columns['volume']]
            )
            return bar
            
        return None
        
    def get_symbols(self) -> List[str]:
        """
        Get all available symbols.
        
        Returns:
            List of available symbols
        """
        return list(self._data.keys()) 
"""
SPX-related indicators.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Union, Optional, List, Tuple
import pytz

from easytrade.indicators.base import Indicator, BacktraderIndicatorMixin

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class SPXATRIndicator(Indicator):
    """
    Calculates Average True Range (ATR) for SPX data.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the SPX ATR indicator.
        
        Args:
            params: Dictionary of parameters including:
                - period: ATR calculation period (default: 180)
                - offset: Offset for the calculation (default: 20)
                - threshold: Threshold for signal generation (default: 82)
        """
        default_params = {
            'period': 180,
            'offset': 20,
            'threshold': 82
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate the SPX ATR indicator.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX OHLC data
                
        Returns:
            Dictionary with calculated ATR values:
                - 'atr': ATR value
                - 'is_signal': True if ATR is above threshold, False otherwise
        """
        # Extract data
        spx_df = data.get('spx')
        
        if spx_df is None or len(spx_df) == 0:
            self.logger.error("Missing or empty SPX data")
            return {'atr': 0, 'is_signal': False}
            
        # Make a copy to avoid modifying original data
        spx_df = spx_df.copy()
        
        # Get parameters
        period = self.get_param('period')
        offset = self.get_param('offset')
        threshold = self.get_param('threshold')
        
        # Ensure we have enough data
        if len(spx_df) < max(period, offset) + 1:
            return {'atr': 0, 'is_signal': False}
        
        # Calculate True Range
        spx_df['high_low'] = spx_df['high'] - spx_df['low']
        spx_df['high_close'] = abs(spx_df['high'] - spx_df['close'].shift(1))
        spx_df['low_close'] = abs(spx_df['low'] - spx_df['close'].shift(1))
        
        # True Range is the maximum of these three values
        spx_df['tr'] = spx_df[['high_low', 'high_close', 'low_close']].max(axis=1)
        
        # Calculate ATR as the average of True Range over the period
        spx_df['atr'] = spx_df['tr'].rolling(window=period, min_periods=1).mean()
        
        # Apply offset
        if offset > 0 and len(spx_df) > offset:
            atr_value = spx_df['atr'].iloc[-offset]
        else:
            atr_value = spx_df['atr'].iloc[-1]
        
        # Check if ATR is above threshold
        is_signal = atr_value > threshold
        
        return {
            'atr': atr_value,
            'is_signal': is_signal
        }


class SPXPriceIndicator(Indicator):
    """
    Calculates various price-based indicators for SPX.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the SPX price indicator.
        
        Args:
            params: Dictionary of parameters including:
                - period: Calculation period (default: 1)
        """
        default_params = {
            'period': 1
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate price-based metrics for SPX.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX OHLC data
                
        Returns:
            Dictionary with calculated values:
                - 'close': Current close price
                - 'change': Price change over period
                - 'range': Price range over period
                - 'max_price': Maximum price over period
                - 'min_price': Minimum price over period
        """
        # Extract data
        spx_df = data.get('spx')
        
        if spx_df is None or len(spx_df) == 0:
            self.logger.error("Missing or empty SPX data")
            return {}
            
        # Get parameters
        period = self.get_param('period')
        
        # Ensure period is at least 1
        period = max(1, period)
        
        # Ensure we have enough data
        if len(spx_df) < period:
            return {}
        
        # Get the period data
        period_data = spx_df.iloc[-period:]
        
        # Calculate metrics
        close_price = period_data['close'].iloc[-1]
        open_price = period_data['open'].iloc[0]
        max_price = period_data['high'].max()
        min_price = period_data['low'].min()
        price_change = close_price - open_price
        price_range = max_price - min_price
        
        return {
            'close': close_price,
            'open': open_price,
            'change': price_change,
            'range': price_range,
            'max_price': max_price,
            'min_price': min_price
        }


class SPXConsistencyIndicator(Indicator):
    """
    Analyzes SPX data for trend consistency and stability.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the consistency indicator.
        
        Args:
            params: Dictionary of parameters including:
                - window: Window for trend analysis (default: 360)
                - offset: Offset for the calculation (default: 18)
                - threshold: Threshold for signal generation (default: 8)
        """
        default_params = {
            'window': 360,
            'offset': 18,
            'threshold': 8
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate consistency and stability metrics for SPX.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX OHLC data
                - 'max4': Maximum value for reference
                - 'min4': Minimum value for reference
                
        Returns:
            Dictionary with calculated values:
                - 'is_consistent': True if trend is consistent, False otherwise
                - 'is_stable': True if trend is stable, False otherwise
                - 'trend': Direction of the trend ('up', 'down', or 'neutral')
        """
        # Extract data
        spx_df = data.get('spx')
        max4 = data.get('max4')
        min4 = data.get('min4')
        
        if spx_df is None or len(spx_df) == 0:
            self.logger.error("Missing or empty SPX data")
            return {'is_consistent': False, 'is_stable': False, 'trend': 'neutral'}
            
        # Get parameters
        window = self.get_param('window')
        offset = self.get_param('offset')
        threshold = self.get_param('threshold')
        
        # Ensure we have enough data
        if len(spx_df) < window:
            return {'is_consistent': False, 'is_stable': False, 'trend': 'neutral'}
        
        # Get window data
        if len(spx_df) > window:
            window_data = spx_df.iloc[-window:]
        else:
            window_data = spx_df.copy()
        
        # Check if max4 and min4 are provided, otherwise calculate them
        if max4 is None or min4 is None:
            max4 = window_data['high'].max()
            min4 = window_data['low'].min()
        
        # Calculate trend stability and consistency
        close_prices = window_data['close']
        
        # Calculate up and down bars
        up_bars = sum(1 for i in range(1, len(close_prices)) if close_prices.iloc[i] > close_prices.iloc[i-1])
        down_bars = sum(1 for i in range(1, len(close_prices)) if close_prices.iloc[i] < close_prices.iloc[i-1])
        
        # Determine trend direction
        if up_bars > down_bars:
            trend = 'up'
        elif down_bars > up_bars:
            trend = 'down'
        else:
            trend = 'neutral'
        
        # Check consistency
        consistency_ratio = max(up_bars, down_bars) / (up_bars + down_bars) if (up_bars + down_bars) > 0 else 0.5
        is_consistent = consistency_ratio > 0.65  # If more than 65% of bars are in the same direction
        
        # Check stability
        price_range = max4 - min4
        latest_range = window_data['high'].iloc[-offset:].max() - window_data['low'].iloc[-offset:].min()
        
        # Is stable if recent range is a small portion of the total range
        stability_ratio = latest_range / price_range if price_range > 0 else 1.0
        is_stable = stability_ratio < 0.3  # If recent range is less than 30% of total range
        
        # Additional check for threshold
        bars_above_threshold = sum(1 for i in range(1, len(close_prices)) 
                                  if abs(close_prices.iloc[i] - close_prices.iloc[i-1]) > threshold)
        
        # Adjust consistency based on threshold
        is_consistent = is_consistent and bars_above_threshold < 3  # Less than 3 bars with large price changes
        
        return {
            'is_consistent': is_consistent,
            'is_stable': is_stable,
            'trend': trend,
            'consistency_ratio': consistency_ratio,
            'stability_ratio': stability_ratio,
            'bars_above_threshold': bars_above_threshold
        }


class SPXConsecutiveBarsIndicator(Indicator):
    """
    Analyzes SPX data for consecutive bar patterns.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the consecutive bars indicator.
        
        Args:
            params: Dictionary of parameters including:
                - threshold: Primary threshold for bar detection (default: 7.5)
                - threshold2: Secondary threshold for bar detection (default: 30)
                - bars_needed: Number of consecutive bars needed (default: 4)
        """
        default_params = {
            'threshold': 7.5,
            'threshold2': 30,
            'bars_needed': 4
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate consecutive bar patterns.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX OHLC data
                
        Returns:
            Dictionary with calculated values:
                - 'consecutive_up': Number of consecutive up bars
                - 'consecutive_down': Number of consecutive down bars
                - 'is_up_signal': True if consecutive up bars exceed threshold
                - 'is_down_signal': True if consecutive down bars exceed threshold
        """
        # Extract data
        spx_df = data.get('spx')
        
        if spx_df is None or len(spx_df) == 0:
            self.logger.error("Missing or empty SPX data")
            return {'consecutive_up': 0, 'consecutive_down': 0, 'is_up_signal': False, 'is_down_signal': False}
            
        # Get parameters
        threshold = self.get_param('threshold')
        threshold2 = self.get_param('threshold2')
        bars_needed = self.get_param('bars_needed')
        
        # Ensure we have enough data
        if len(spx_df) < bars_needed:
            return {'consecutive_up': 0, 'consecutive_down': 0, 'is_up_signal': False, 'is_down_signal': False}
        
        # Calculate price changes
        spx_df['change'] = spx_df['close'].diff()
        
        # Get the last bars
        last_bars = spx_df.iloc[-bars_needed:]
        
        # Count consecutive bars
        consecutive_up = 0
        consecutive_down = 0
        current_run_up = 0
        current_run_down = 0
        
        for i in range(len(last_bars)):
            change = last_bars['change'].iloc[i]
            
            if change > 0:
                current_run_up += 1
                current_run_down = 0
            elif change < 0:
                current_run_down += 1
                current_run_up = 0
            else:
                # No change, reset both counters
                current_run_up = 0
                current_run_down = 0
                
            consecutive_up = max(consecutive_up, current_run_up)
            consecutive_down = max(consecutive_down, current_run_down)
        
        # Check if we have a signal
        # For up signal: Need consecutive up bars and total change exceeds threshold
        total_change = last_bars['close'].iloc[-1] - last_bars['close'].iloc[0]
        abs_change = abs(total_change)
        
        is_up_signal = (consecutive_up >= bars_needed and 
                       total_change > threshold and 
                       abs_change < threshold2)
                       
        is_down_signal = (consecutive_down >= bars_needed and 
                         total_change < -threshold and 
                         abs_change < threshold2)
        
        return {
            'consecutive_up': consecutive_up,
            'consecutive_down': consecutive_down,
            'is_up_signal': is_up_signal,
            'is_down_signal': is_down_signal,
            'total_change': total_change,
            'abs_change': abs_change
        }


class SPXTrendIndicator(Indicator):
    """
    Analyzes SPX data for trend detection and reversal signals.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the trend indicator.
        
        Args:
            params: Dictionary of parameters including:
                - adj_ratio: Adjustment ratio (default: 1.0)
                - threshold: Threshold for signal generation (default: 150)
                - delay: Delay for signal confirmation (default: 1)
        """
        default_params = {
            'adj_ratio': 1.0,
            'threshold': 150,
            'delay': 1
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate trend signals.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX OHLC data
                - 'momentum': Momentum data
                
        Returns:
            Dictionary with calculated values:
                - 'is_up_trend': True if upward trend detected
                - 'is_down_trend': True if downward trend detected
                - 'trend_strength': Strength of the trend
        """
        # Extract data
        spx_df = data.get('spx')
        momentum_df = data.get('momentum')
        
        if spx_df is None or len(spx_df) == 0:
            self.logger.error("Missing or empty SPX data")
            return {'is_up_trend': False, 'is_down_trend': False, 'trend_strength': 0}
            
        # Get parameters
        adj_ratio = self.get_param('adj_ratio')
        threshold = self.get_param('threshold')
        delay = self.get_param('delay')
        
        # Ensure we have enough data
        min_bars = delay + 10  # Need at least delay + some history
        if len(spx_df) < min_bars:
            return {'is_up_trend': False, 'is_down_trend': False, 'trend_strength': 0}
        
        # Adjust the threshold based on the ratio
        adj_threshold = threshold * adj_ratio
        
        # Calculate trend metrics
        # This is a simplified version - in the actual implementation, 
        # you would need more complex logic based on TradeAlgo1.py
        
        # For this example, we'll look at the recent price trend
        recent_bars = spx_df.iloc[-10:]
        price_change = recent_bars['close'].iloc[-1] - recent_bars['close'].iloc[0]
        
        # Calculate trend direction and strength
        trend_direction = 'up' if price_change > 0 else 'down'
        trend_strength = abs(price_change)
        
        # Apply delay if needed
        if delay > 0 and len(spx_df) > delay:
            delayed_change = spx_df['close'].iloc[-1] - spx_df['close'].iloc[-delay-1]
            # Check if trend direction is consistent after delay
            if (trend_direction == 'up' and delayed_change <= 0) or \
               (trend_direction == 'down' and delayed_change >= 0):
                # Trend direction changed during delay, reject signal
                return {'is_up_trend': False, 'is_down_trend': False, 'trend_strength': trend_strength}
        
        # Check if trend strength exceeds threshold
        is_significant = trend_strength > adj_threshold
        
        # Generate signals
        is_up_trend = trend_direction == 'up' and is_significant
        is_down_trend = trend_direction == 'down' and is_significant
        
        return {
            'is_up_trend': is_up_trend,
            'is_down_trend': is_down_trend,
            'trend_strength': trend_strength,
            'trend_direction': trend_direction
        }


class BacktraderSPXIndicator(BacktraderIndicatorMixin):
    """
    Backtrader-compatible wrapper for SPX indicators.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the backtrader adapter."""
        BacktraderIndicatorMixin.__init__(self)
        self._indicators = {
            'atr': SPXATRIndicator(kwargs.get('atr_params')),
            'price': SPXPriceIndicator(kwargs.get('price_params')),
            'consistency': SPXConsistencyIndicator(kwargs.get('consistency_params')),
            'consecutive': SPXConsecutiveBarsIndicator(kwargs.get('consecutive_params')),
            'trend': SPXTrendIndicator(kwargs.get('trend_params'))
        }
        
    def next(self):
        """
        Calculate all indicator values for the current bar (called by backtrader).
        """
        # Extract current data for SPX
        spx_data = self._bt_data
        
        # Convert to DataFrame (simplified example)
        spx_df = pd.DataFrame({
            'open': [spx_data.open[0]],
            'high': [spx_data.high[0]],
            'low': [spx_data.low[0]],
            'close': [spx_data.close[0]],
            'volume': [spx_data.volume[0]]
        })
        
        # Base data for all indicators
        base_data = {'spx': spx_df}
        
        # Calculate all indicators
        for name, indicator in self._indicators.items():
            result = indicator.calculate(base_data)
            # Update backtrader lines for this indicator
            self.update_bt_lines({f"{name}_{k}": v for k, v in result.items()}) 
"""
Momentum indicator implementations.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Union, Optional, List
import pytz

from easytrade.indicators.base import Indicator, BacktraderIndicatorMixin

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


def get_adj1_value(index: pd.DatetimeIndex, adj1_map: Dict[str, float]) -> pd.Series:
    """
    Get adjustment factor values for a time series index.
    
    Args:
        index: DatetimeIndex of the time series
        adj1_map: Mapping of time strings to adjustment factors
        
    Returns:
        Series of adjustment factors aligned with the index
    """
    # Convert index times to strings in the format used in adj1_map
    time_strings = index.strftime('%H:%M:%S')
    
    # Create adjustment factor series with the same index
    adj_factors = pd.Series([adj1_map.get(t, 1.0) for t in time_strings], index=index)
    
    # Replace zeros with 1.0 to avoid division by zero
    adj_factors = adj_factors.replace(0, 1.0)
    
    return adj_factors


class MomentumIndicator(Indicator):
    """
    Calculates momentum metrics based on price and volume data.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the momentum indicator.
        
        Args:
            params: Dictionary of parameters including:
                - period_spy: Rolling window for SPY calculations (default: 3)
                - period_spx: Rolling window for SPX calculations (default: 5)
                - adj1_map: Dictionary mapping time strings to adjustment factors
        """
        default_params = {
            'period_spy': 3,
            'period_spx': 5,
            'adj1_map': {}  # Default empty map
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate momentum metrics from SPY and SPX data.
        
        Args:
            data: Dictionary containing:
                - 'spy': DataFrame with SPY OHLCV data
                - 'spx': DataFrame with SPX OHLCV data
                
        Returns:
            Dictionary with calculated momentum values:
                - 'momentum': Cumulative momentum
                - 'mom_abs': Absolute cumulative momentum
                - 'spx_change_5s_abs': Absolute SPX price change
                - 'spy_change_5s_abs': Absolute SPY price change
                - 'd_momentum': Incremental momentum
        """
        # Extract data
        spy_df = data.get('spy')
        spx_df = data.get('spx')
        
        if spy_df is None or spx_df is None:
            self.logger.error("Missing required input data")
            return {}
            
        # Make copies to avoid modifying original data
        spy_df = spy_df.copy()
        spx_df = spx_df.copy()
        
        # Get parameters
        period_spy = self.get_param('period_spy')
        period_spx = self.get_param('period_spx')
        adj1_map = self.get_param('adj1_map')
        
        # Get SPX data at 5s intervals
        spx_df_5s = spx_df[::5].copy() if len(spx_df) > 5 else spx_df.copy()
        
        # Calculate rolling values
        spy_df['volume_n'] = spy_df['volume'].rolling(window=period_spy, min_periods=1).sum()
        spy_df['turnover_n'] = (spy_df['close'] * spy_df['volume']).rolling(window=period_spy, min_periods=1).sum()
        
        # Calculate average price
        spy_df['px_n'] = spy_df['turnover_n'] / spy_df['volume_n']
        
        # Calculate price changes
        spy_df['px_change'] = spy_df['px_n'] / spy_df['px_n'].shift(1) - 1.0
        spy_df['spx_change_5s'] = spx_df_5s['close'] - spx_df_5s['close'].shift(1)
        spy_df['spy_change_5s'] = spy_df['px_n'] - spy_df['px_n'].shift(1)
        
        # Calculate absolute changes
        spy_df['spx_change_5s_abs'] = (abs(spx_df_5s['close'] - spx_df_5s['close'].shift(1))).replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        spy_df['spy_change_5s_abs'] = (abs(spy_df['px_n'] - spy_df['px_n'].shift(1))).replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        
        # Apply adjustment factors
        if adj1_map:
            adj_factors = get_adj1_value(spy_df.index, adj1_map)
        else:
            # If no adjustment map provided, use 1.0 for all times
            adj_factors = pd.Series(1.0, index=spy_df.index)
            
        # Calculate momentum
        spy_df['d_momentum'] = spy_df['volume_n'] * spy_df['px_change'] / adj_factors
        spy_df['d_momentum'] = spy_df['d_momentum'].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        
        # Cumulative values
        spy_df['momentum'] = spy_df['d_momentum'].cumsum()
        spy_df['momentum'] = spy_df['momentum'].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        spy_df['mom_abs'] = (abs(spy_df['d_momentum'])).cumsum().replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
        
        # Return the calculated values
        return {
            'momentum': spy_df['momentum'].iloc[-1] if len(spy_df) > 0 else 0,
            'mom_abs': spy_df['mom_abs'].iloc[-1] if len(spy_df) > 0 else 0,
            'spx_change_5s_abs': spy_df['spx_change_5s_abs'].iloc[-1] if len(spy_df) > 0 else 0,
            'spy_change_5s_abs': spy_df['spy_change_5s_abs'].iloc[-1] if len(spy_df) > 0 else 0,
            'd_momentum': spy_df['d_momentum'].iloc[-1] if len(spy_df) > 0 else 0,
            'spy_df': spy_df  # Include the full DataFrame for further analysis
        }
    
    def prepare_momentum_data(self, spy_df: pd.DataFrame, spx_df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare momentum data in the format expected by backtrader.
        
        Args:
            spy_df: SPY price and volume data
            spx_df: SPX price data
            
        Returns:
            DataFrame with OHLCV data suitable for feeding into backtrader
        """
        # Calculate all momentum metrics
        data = {'spy': spy_df, 'spx': spx_df}
        result = self.calculate(data)
        
        # Get the processed DataFrame
        momentum_df = result.get('spy_df', pd.DataFrame())
        
        if momentum_df.empty:
            return pd.DataFrame()
            
        # For backtrader compatibility, set OHLC to momentum metrics
        momentum_df['open'] = momentum_df['momentum']
        momentum_df['high'] = momentum_df['mom_abs']
        momentum_df['low'] = momentum_df['spx_change_5s_abs']
        momentum_df['close'] = momentum_df['momentum']
        momentum_df['volume'] = momentum_df['d_momentum']
        
        # Drop unnecessary columns
        cols_to_drop = ['volume_n', 'turnover_n', 'px_n', 'px_change', 'd_momentum',
                        'mom_abs', 'spx_change_5s_abs', 'spy_change_5s_abs', 
                        'spx_change_5s', 'spy_change_5s']
        
        for col in cols_to_drop:
            if col in momentum_df.columns:
                momentum_df.drop(col, axis=1, inplace=True)
                
        return momentum_df


class BacktraderMomentumIndicator(BacktraderIndicatorMixin, MomentumIndicator):
    """
    Backtrader-compatible version of MomentumIndicator.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize both parent classes."""
        BacktraderIndicatorMixin.__init__(self)
        MomentumIndicator.__init__(self, kwargs.get('params'))
        
    def next(self):
        """
        Calculate indicator values for the current bar (called by backtrader).
        """
        # Extract current data
        spy_data = self._bt_data[0]  # SPY data
        spx_data = self._bt_data[1]  # SPX data
        
        # Convert to DataFrames (this would need to be adapted to your backtrader setup)
        # This is a simplified example
        spy_df = pd.DataFrame({
            'close': [spy_data.close[0]],
            'volume': [spy_data.volume[0]],
            # Add other necessary fields
        })
        
        spx_df = pd.DataFrame({
            'close': [spx_data.close[0]],
            # Add other necessary fields
        })
        
        # Calculate indicators
        data = {'spy': spy_df, 'spx': spx_df}
        result = self.calculate(data)
        
        # Update backtrader lines
        self.update_bt_lines(result) 
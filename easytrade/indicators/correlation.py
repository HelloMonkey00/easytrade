"""
Correlation indicator implementations.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Union, Optional, List
import pytz

from easytrade.indicators.base import Indicator, BacktraderIndicatorMixin

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class RhoIndicator(Indicator):
    """
    Calculates correlation (rho) between SPX and momentum metrics.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the rho indicator.
        
        Args:
            params: Dictionary of parameters including:
                - period_spx: Period for SPX calculation (default: 15)
        """
        default_params = {
            'period_spx': 15
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate rho (correlation) metrics.
        
        Args:
            data: Dictionary containing:
                - 'spx': DataFrame with SPX data
                - 'momentum': DataFrame with momentum data
                - 'sec': Number of seconds/bars to use (optional)
                
        Returns:
            Dictionary with calculated values:
                - 'rho': Correlation coefficient
                - 'rho_abs': Absolute value of the correlation
                - 'is_positive': True if correlation is positive
                - 'is_negative': True if correlation is negative
        """
        # Extract data
        spx_df = data.get('spx')
        momentum_df = data.get('momentum')
        sec = data.get('sec')
        
        if spx_df is None or momentum_df is None:
            self.logger.error("Missing required input data")
            return {'rho': 0, 'rho_abs': 0, 'is_positive': False, 'is_negative': False}
            
        # Get parameters
        period_spx = self.get_param('period_spx')
        
        # If sec is not provided, use the default period
        if sec is None:
            sec = period_spx
        
        # Ensure we have enough data
        if len(spx_df) < sec or len(momentum_df) < sec:
            return {'rho': 0, 'rho_abs': 0, 'is_positive': False, 'is_negative': False}
        
        # Extract the relevant data
        spx_prices = spx_df['close'].iloc[-sec:].values
        momentum_values = momentum_df['close'].iloc[-sec:].values
        
        # Calculate correlation
        try:
            if len(spx_prices) != len(momentum_values):
                # If length mismatch, resample to match
                if len(spx_prices) > len(momentum_values):
                    # Downsample SPX to match momentum
                    indices = np.linspace(0, len(spx_prices) - 1, len(momentum_values), dtype=int)
                    spx_prices = spx_prices[indices]
                else:
                    # Downsample momentum to match SPX
                    indices = np.linspace(0, len(momentum_values) - 1, len(spx_prices), dtype=int)
                    momentum_values = momentum_values[indices]
            
            # Calculate correlation coefficient
            rho = np.corrcoef(spx_prices, momentum_values)[0, 1]
            
            # Handle NaN values
            if np.isnan(rho):
                rho = 0
                
            rho_abs = abs(rho)
            is_positive = rho > 0
            is_negative = rho < 0
            
            return {
                'rho': rho,
                'rho_abs': rho_abs,
                'is_positive': is_positive,
                'is_negative': is_negative
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating correlation: {str(e)}")
            return {'rho': 0, 'rho_abs': 0, 'is_positive': False, 'is_negative': False}


class RhoChangeIndicator(Indicator):
    """
    Detects changes in correlation (rho) values over time.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the rho change indicator.
        
        Args:
            params: Dictionary of parameters including:
                - threshold_1: Primary threshold for change detection (default: 0.5)
                - threshold_2: Secondary threshold for change detection (default: 0.25)
                - threshold_3: Tertiary threshold for change detection (default: 0.1)
        """
        default_params = {
            'threshold_1': 0.5,
            'threshold_2': 0.25,
            'threshold_3': 0.1
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(default_params)
        
        # Initialize history tracking
        self._rho_history = []
        
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate rho change metrics.
        
        Args:
            data: Dictionary containing:
                - 'rho': Current rho value
                
        Returns:
            Dictionary with calculated values:
                - 'is_significant_change': True if a significant change is detected
                - 'change_type': Type of change ('major', 'medium', 'minor', 'none')
                - 'change_value': Magnitude of the change
        """
        # Extract data
        rho = data.get('rho')
        
        if rho is None:
            self.logger.error("Missing rho value")
            return {'is_significant_change': False, 'change_type': 'none', 'change_value': 0}
        
        # Get parameters
        threshold_1 = self.get_param('threshold_1')
        threshold_2 = self.get_param('threshold_2')
        threshold_3 = self.get_param('threshold_3')
        
        # Add current value to history
        self._rho_history.append(rho)
        
        # Keep only the most recent values (for memory efficiency)
        max_history = 100
        if len(self._rho_history) > max_history:
            self._rho_history = self._rho_history[-max_history:]
        
        # Need at least 2 values to calculate change
        if len(self._rho_history) < 2:
            return {'is_significant_change': False, 'change_type': 'none', 'change_value': 0}
        
        # Calculate change from previous value
        prev_rho = self._rho_history[-2]
        rho_change = abs(rho - prev_rho)
        
        # Determine change type
        if rho_change >= threshold_1:
            change_type = 'major'
            is_significant = True
        elif rho_change >= threshold_2:
            change_type = 'medium'
            is_significant = True
        elif rho_change >= threshold_3:
            change_type = 'minor'
            is_significant = True
        else:
            change_type = 'none'
            is_significant = False
        
        return {
            'is_significant_change': is_significant,
            'change_type': change_type,
            'change_value': rho_change
        }


class BacktraderRhoIndicator(BacktraderIndicatorMixin, RhoIndicator):
    """
    Backtrader-compatible version of RhoIndicator.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize both parent classes."""
        BacktraderIndicatorMixin.__init__(self)
        RhoIndicator.__init__(self, kwargs.get('params'))
        
        # Add a rho change detector
        self._rho_change = RhoChangeIndicator(kwargs.get('change_params'))
        
    def next(self):
        """
        Calculate indicator values for the current bar (called by backtrader).
        """
        # Extract current data
        spx_data = self._bt_data[0]  # SPX data
        momentum_data = self._bt_data[1]  # Momentum data
        
        # Convert to DataFrames (simplified example)
        spx_df = pd.DataFrame({
            'close': [d for d in spx_data.close.get(size=self.get_param('period_spx'))]
        })
        
        momentum_df = pd.DataFrame({
            'close': [d for d in momentum_data.close.get(size=self.get_param('period_spx'))]
        })
        
        # Calculate rho
        data = {'spx': spx_df, 'momentum': momentum_df}
        result = self.calculate(data)
        
        # Calculate rho change
        change_data = {'rho': result.get('rho', 0)}
        change_result = self._rho_change.calculate(change_data)
        
        # Combine results
        combined_result = {**result, **{f"change_{k}": v for k, v in change_result.items()}}
        
        # Update backtrader lines
        self.update_bt_lines(combined_result) 
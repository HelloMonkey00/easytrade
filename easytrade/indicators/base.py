"""
Base indicator class that can be used with both easytrade and backtrader.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
import pandas as pd
import numpy as np
import logging


class Indicator(ABC):
    """
    Base class for all indicators.
    
    Indicators should implement the calculate method which takes 
    input data and returns calculated indicator values.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize the indicator with optional parameters.
        
        Args:
            params: Dictionary of parameter name/value pairs
        """
        self.params = params or {}
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        
    @abstractmethod
    def calculate(self, data: Dict[str, Union[pd.DataFrame, np.ndarray]]) -> Dict[str, Any]:
        """
        Calculate the indicator value based on input data.
        
        Args:
            data: Dictionary containing input data for the calculation
            
        Returns:
            Dictionary containing calculated indicator values
        """
        pass
    
    def get_param(self, name: str, default: Any = None) -> Any:
        """
        Get a parameter value by name.
        
        Args:
            name: Parameter name
            default: Default value if parameter doesn't exist
            
        Returns:
            Parameter value
        """
        return self.params.get(name, default)
    
    def set_param(self, name: str, value: Any):
        """
        Set a parameter value.
        
        Args:
            name: Parameter name
            value: Parameter value
        """
        self.params[name] = value
        
    def update_params(self, params: Dict[str, Any]):
        """
        Update multiple parameters at once.
        
        Args:
            params: Dictionary of parameter name/value pairs
        """
        self.params.update(params)


class BacktraderIndicatorMixin:
    """
    Mixin class to adapt an Indicator for use with backtrader.
    
    This mixin adds methods necessary for backtrader integration.
    """
    
    def __init__(self):
        """Initialize the backtrader adapter."""
        self._bt_lines = {}
        self._bt_data = None
        
    def set_bt_data(self, data):
        """
        Set the backtrader data object.
        
        Args:
            data: Backtrader data object
        """
        self._bt_data = data
        
    def set_bt_line(self, name: str, line):
        """
        Associate a backtrader line with an indicator output.
        
        Args:
            name: Output name
            line: Backtrader line object
        """
        self._bt_lines[name] = line
        
    def get_bt_line(self, name: str):
        """
        Get the backtrader line for an indicator output.
        
        Args:
            name: Output name
            
        Returns:
            Backtrader line object
        """
        return self._bt_lines.get(name)
        
    def update_bt_lines(self, result: Dict[str, Any]):
        """
        Update backtrader lines with calculated values.
        
        Args:
            result: Dictionary of calculated values
        """
        for name, value in result.items():
            line = self.get_bt_line(name)
            if line is not None:
                line[0] = value 
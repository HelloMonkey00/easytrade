"""
Utility functions for performance analysis.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta


def calculate_returns(equity_curve: List[float]) -> np.ndarray:
    """
    Calculate returns from an equity curve.
    
    Args:
        equity_curve: List of equity values over time
        
    Returns:
        Array of returns
    """
    equity_array = np.array(equity_curve)
    returns = np.diff(equity_array) / equity_array[:-1]
    return returns


def calculate_sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, annualization_factor: int = 252) -> float:
    """
    Calculate Sharpe ratio.
    
    Args:
        returns: Array of returns
        risk_free_rate: Risk-free rate (annualized)
        annualization_factor: Annualization factor (252 for daily returns)
        
    Returns:
        Sharpe ratio
    """
    excess_returns = returns - (risk_free_rate / annualization_factor)
    return np.sqrt(annualization_factor) * np.mean(excess_returns) / np.std(excess_returns, ddof=1)


def calculate_sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, annualization_factor: int = 252) -> float:
    """
    Calculate Sortino ratio.
    
    Args:
        returns: Array of returns
        risk_free_rate: Risk-free rate (annualized)
        annualization_factor: Annualization factor (252 for daily returns)
        
    Returns:
        Sortino ratio
    """
    excess_returns = returns - (risk_free_rate / annualization_factor)
    downside_returns = excess_returns[excess_returns < 0]
    downside_deviation = np.std(downside_returns, ddof=1)
    
    if downside_deviation == 0:
        return np.inf
        
    return np.sqrt(annualization_factor) * np.mean(excess_returns) / downside_deviation


def calculate_max_drawdown(equity_curve: List[float]) -> float:
    """
    Calculate maximum drawdown.
    
    Args:
        equity_curve: List of equity values over time
        
    Returns:
        Maximum drawdown as a percentage
    """
    equity_array = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_array)
    drawdown = (peak - equity_array) / peak
    return np.max(drawdown)


def calculate_cagr(equity_curve: List[float], days: int) -> float:
    """
    Calculate Compound Annual Growth Rate (CAGR).
    
    Args:
        equity_curve: List of equity values over time
        days: Number of days in the backtest
        
    Returns:
        CAGR as a percentage
    """
    start_equity = equity_curve[0]
    end_equity = equity_curve[-1]
    years = days / 365.0
    
    return ((end_equity / start_equity) ** (1 / years)) - 1


def calculate_performance_metrics(equity_curve: List[float], days: int, risk_free_rate: float = 0.0) -> Dict[str, float]:
    """
    Calculate performance metrics.
    
    Args:
        equity_curve: List of equity values over time
        days: Number of days in the backtest
        risk_free_rate: Risk-free rate (annualized)
        
    Returns:
        Dictionary of performance metrics
    """
    returns = calculate_returns(equity_curve)
    
    total_return = (equity_curve[-1] / equity_curve[0]) - 1
    cagr = calculate_cagr(equity_curve, days)
    sharpe = calculate_sharpe_ratio(returns, risk_free_rate)
    sortino = calculate_sortino_ratio(returns, risk_free_rate)
    max_drawdown = calculate_max_drawdown(equity_curve)
    
    return {
        'total_return': total_return,
        'cagr': cagr,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'max_drawdown': max_drawdown,
        'calmar_ratio': cagr / max_drawdown if max_drawdown > 0 else np.inf
    }


def plot_equity_curve(equity_curve: List[float], timestamps: List[datetime] = None, title: str = 'Equity Curve'):
    """
    Plot equity curve.
    
    Args:
        equity_curve: List of equity values over time
        timestamps: List of timestamps corresponding to equity values
        title: Plot title
    """
    plt.figure(figsize=(12, 6))
    
    if timestamps is not None:
        plt.plot(timestamps, equity_curve)
        plt.xlabel('Date')
    else:
        plt.plot(equity_curve)
        plt.xlabel('Time')
        
    plt.ylabel('Equity')
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    
    return plt.gcf()


def plot_drawdown(equity_curve: List[float], timestamps: List[datetime] = None, title: str = 'Drawdown'):
    """
    Plot drawdown.
    
    Args:
        equity_curve: List of equity values over time
        timestamps: List of timestamps corresponding to equity values
        title: Plot title
    """
    equity_array = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_array)
    drawdown = (peak - equity_array) / peak
    
    plt.figure(figsize=(12, 6))
    
    if timestamps is not None:
        plt.plot(timestamps, drawdown)
        plt.xlabel('Date')
    else:
        plt.plot(drawdown)
        plt.xlabel('Time')
        
    plt.ylabel('Drawdown')
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    
    return plt.gcf()


def plot_returns_distribution(returns: np.ndarray, title: str = 'Returns Distribution'):
    """
    Plot returns distribution.
    
    Args:
        returns: Array of returns
        title: Plot title
    """
    plt.figure(figsize=(12, 6))
    
    plt.hist(returns, bins=50, alpha=0.75)
    plt.axvline(x=0, color='r', linestyle='--')
    plt.axvline(x=np.mean(returns), color='g', linestyle='-')
    
    plt.xlabel('Return')
    plt.ylabel('Frequency')
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    
    return plt.gcf()


def create_performance_report(equity_curve: List[float], timestamps: List[datetime], days: int, risk_free_rate: float = 0.0) -> Dict[str, Any]:
    """
    Create a comprehensive performance report.
    
    Args:
        equity_curve: List of equity values over time
        timestamps: List of timestamps corresponding to equity values
        days: Number of days in the backtest
        risk_free_rate: Risk-free rate (annualized)
        
    Returns:
        Dictionary containing performance metrics and plots
    """
    metrics = calculate_performance_metrics(equity_curve, days, risk_free_rate)
    returns = calculate_returns(equity_curve)
    
    equity_plot = plot_equity_curve(equity_curve, timestamps)
    drawdown_plot = plot_drawdown(equity_curve, timestamps)
    returns_plot = plot_returns_distribution(returns)
    
    return {
        'metrics': metrics,
        'plots': {
            'equity_curve': equity_plot,
            'drawdown': drawdown_plot,
            'returns_distribution': returns_plot
        }
    } 
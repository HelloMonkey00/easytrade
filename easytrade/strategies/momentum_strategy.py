"""
Momentum strategy based on the TradeAlgo1 implementation.

This strategy evaluates market momentum and SPX indicators to determine entry and exit points
for trades. It uses a combination of momentum, SPX indicators, and correlation (rho) to
make trading decisions.
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, time, timedelta
import math

from easytrade.core.strategy import Strategy
from easytrade.core.types import Order, OrderStatus, OrderSide, OrderType, Position, Bar
from easytrade.indicators.momentum import MomentumIndicator
from easytrade.indicators.spx import (
    SPXATRIndicator, SPXPriceIndicator, SPXConsistencyIndicator,
    SPXConsecutiveBarsIndicator, SPXTrendIndicator
)
from easytrade.indicators.correlation import RhoIndicator, RhoChangeIndicator
from easytrade.utils.market_time import MarketTime


class MomentumStrategy(Strategy):
    """
    Momentum strategy based on the TradeAlgo1 implementation.
    
    This strategy evaluates market momentum and SPX indicators to determine entry and exit points
    for trades. It uses a combination of momentum, SPX indicators, and correlation (rho) to
    make trading decisions.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the momentum strategy.
        
        Args:
            config: Strategy configuration parameters
        """
        super().__init__(name="MomentumStrategy")
        
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Default configuration
        self.config = {
            # Trading symbols
            "symbols": ["SPY", "SPX"],
            "trading_symbol": "SPY",
            
            # Trade parameters
            "position_size": 100,  # Number of shares to trade
            "min_profit_target": 0.1,  # Minimum profit target (percentage)
            "stop_loss": 0.05,  # Stop loss (percentage)
            "max_position_duration": 60,  # Maximum position duration (minutes)
            
            # Momentum parameters
            "momentum_threshold": 0.5,  # Threshold for momentum signals
            "momentum_lookback": 20,  # Lookback period for momentum calculation
            
            # SPX parameters
            "spx_atr_period": 14,  # Period for ATR calculation
            "spx_atr_threshold": 0.5,  # Threshold for ATR signals
            "spx_price_lookback": 20,  # Lookback period for price indicators
            "spx_consistency_window": 5,  # Window for consistency check
            "spx_consistency_threshold": 0.6,  # Threshold for consistency signals
            "spx_consecutive_bars": 3,  # Number of consecutive bars for signal
            "spx_trend_period": 20,  # Period for trend calculation
            "spx_trend_adjust": 0.5,  # Adjustment for trend detection
            
            # Correlation parameters
            "rho_period": 15,  # Period for correlation calculation
            "rho_change_threshold": 0.5,  # Threshold for correlation change
            
            # Filter parameters
            "min_trade_spacing": 15,  # Minimum time between trades (minutes)
            "market_direction_filter": True,  # Use market direction filter
            "volatility_filter": True,  # Use volatility filter
            
            # Entry conditions
            "momentum_entry": True,  # Use momentum for entry
            "spx_entry": True,  # Use SPX indicators for entry
            "rho_entry": True,  # Use correlation for entry
            
            # Risk management
            "max_daily_trades": 5,  # Maximum trades per day
            "max_drawdown": 0.02,  # Maximum drawdown allowed (percentage)
            "intraday_stop_time": time(15, 45),  # Stop trading at this time
        }
        
        # Update config with provided values
        if config:
            self.config.update(config)
            
        # Initialize indicators
        self.momentum_indicator = MomentumIndicator()
        self.spx_atr_indicator = SPXATRIndicator(
            period=self.config["spx_atr_period"],
            threshold=self.config["spx_atr_threshold"]
        )
        self.spx_price_indicator = SPXPriceIndicator(
            lookback=self.config["spx_price_lookback"]
        )
        self.spx_consistency_indicator = SPXConsistencyIndicator(
            window=self.config["spx_consistency_window"],
            threshold=self.config["spx_consistency_threshold"]
        )
        self.spx_consecutive_indicator = SPXConsecutiveBarsIndicator(
            threshold=self.config["spx_consecutive_bars"]
        )
        self.spx_trend_indicator = SPXTrendIndicator(
            period=self.config["spx_trend_period"],
            adjustment=self.config["spx_trend_adjust"]
        )
        self.rho_indicator = RhoIndicator(
            spx_period=self.config["rho_period"]
        )
        self.rho_change_indicator = RhoChangeIndicator(
            threshold=self.config["rho_change_threshold"]
        )
        
        # State variables
        self.last_trade_time = None
        self.daily_trades = 0
        self.current_position = None
        self.position_entry_time = None
        self.position_entry_price = None
        self.stop_loss_price = None
        self.profit_target_price = None
        
        # Market time
        self.market_time = MarketTime()
        
        # Data storage
        self.momentum_data = None
        self.spx_data = None
        self.rho_data = None
        
        # Indicators state
        self.indicators_state = {}
        
        self.logger.info("Momentum strategy initialized with config: %s", self.config)
        
    def on_start(self):
        """Called when the strategy is started."""
        self.logger.info("Momentum strategy started")
        
        # Reset state
        self.last_trade_time = None
        self.daily_trades = 0
        self.current_position = None
        self.position_entry_time = None
        self.position_entry_price = None
        self.stop_loss_price = None
        self.profit_target_price = None
        
    def on_stop(self):
        """Called when the strategy is stopped."""
        self.logger.info("Momentum strategy stopped")
        
        # Close any open positions
        if self.current_position:
            self.close_position("Strategy stopped")
            
    def on_bar(self, data: Dict[str, Bar]):
        """
        Process new bar data.
        
        Args:
            data: Dictionary mapping symbol to Bar object
        """
        # Check if we have data for all required symbols
        if not all(symbol in data for symbol in self.config["symbols"]):
            self.logger.warning("Missing data for required symbols")
            return
            
        # Extract data for SPY and SPX
        spy_bar = data.get(self.config["trading_symbol"])
        spx_bar = data.get("SPX")
        
        if spy_bar is None or spx_bar is None:
            self.logger.warning("Missing data for SPY or SPX")
            return
            
        # Check if market is open
        if not self.market_time.is_market_open(spy_bar.timestamp):
            return
            
        # Check if it's a new day
        if self.last_trade_time and spy_bar.timestamp.date() != self.last_trade_time.date():
            self.daily_trades = 0
            
        # Get historical data
        spy_data = self._get_historical_data(self.config["trading_symbol"])
        spx_data = self._get_historical_data("SPX")
        
        if len(spy_data) < self.config["momentum_lookback"] or len(spx_data) < self.config["spx_price_lookback"]:
            self.logger.warning("Not enough historical data for indicators")
            return
            
        # Calculate indicators
        self.momentum_data = self._calculate_momentum(spy_data)
        self.spx_data = self._calculate_spx_indicators(spx_data)
        
        # Calculate correlation (rho)
        if self.momentum_data is not None and self.spx_data is not None:
            self.rho_data = self._calculate_rho(self.momentum_data, self.spx_data)
            
        # Update indicators state
        self._update_indicators_state()
        
        # Manage existing position if any
        if self.current_position:
            self._manage_position(spy_bar)
        # Check for entry signals
        elif self.can_enter_trade():
            self._check_entry_signals(spy_bar)
            
    def on_order_update(self, order: Order):
        """
        Process order updates.
        
        Args:
            order: Updated order object
        """
        if order.status == OrderStatus.FILLED:
            self.logger.info(f"Order filled: {order.order_id}, {order.symbol}, {order.quantity}, {order.fill_price}")
            
            # Update position tracking
            if order.side == OrderSide.BUY and not self.current_position:
                # New long position
                self.current_position = "LONG"
                self.position_entry_time = datetime.now()
                self.position_entry_price = order.fill_price
                self.stop_loss_price = order.fill_price * (1 - self.config["stop_loss"])
                self.profit_target_price = order.fill_price * (1 + self.config["min_profit_target"])
                self.last_trade_time = datetime.now()
                self.daily_trades += 1
                
            elif order.side == OrderSide.SELL and self.current_position == "LONG":
                # Closing long position
                self.current_position = None
                self.position_entry_time = None
                self.position_entry_price = None
                self.stop_loss_price = None
                self.profit_target_price = None
                
    def on_position_update(self, position: Position):
        """
        Process position updates.
        
        Args:
            position: Updated position object
        """
        # Update current position based on the position data
        if position.symbol == self.config["trading_symbol"]:
            if position.quantity > 0:
                if not self.current_position:
                    self.current_position = "LONG"
                    self.position_entry_time = datetime.now()
                    self.position_entry_price = position.entry_price
                    self.stop_loss_price = position.entry_price * (1 - self.config["stop_loss"])
                    self.profit_target_price = position.entry_price * (1 + self.config["min_profit_target"])
            else:
                self.current_position = None
                self.position_entry_time = None
                self.position_entry_price = None
                self.stop_loss_price = None
                self.profit_target_price = None
                
    def can_enter_trade(self) -> bool:
        """
        Check if we can enter a new trade based on various constraints.
        
        Returns:
            Whether a new trade can be entered
        """
        # Check if we're already in a position
        if self.current_position:
            return False
            
        # Check trade spacing
        if (self.last_trade_time and 
            (datetime.now() - self.last_trade_time).total_seconds() < self.config["min_trade_spacing"] * 60):
            return False
            
        # Check daily trade limit
        if self.daily_trades >= self.config["max_daily_trades"]:
            return False
            
        # Check trading time
        if datetime.now().time() > self.config["intraday_stop_time"]:
            return False
            
        return True
        
    def _get_historical_data(self, symbol: str) -> pd.DataFrame:
        """
        Get historical data for a symbol and convert to DataFrame.
        
        Args:
            symbol: Symbol to get data for
            
        Returns:
            DataFrame with OHLCV data
        """
        # Get historical data from data provider
        bars = self.data_provider.get_historical_data(
            symbol,
            start_date=datetime.now() - timedelta(days=7),
            interval="5m"
        )
        
        # Convert to DataFrame
        if not bars:
            return pd.DataFrame()
            
        data = {
            "datetime": [bar.timestamp for bar in bars],
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
            "volume": [bar.volume for bar in bars]
        }
        
        df = pd.DataFrame(data)
        df.set_index("datetime", inplace=True)
        
        return df
        
    def _calculate_momentum(self, spy_data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate momentum indicators.
        
        Args:
            spy_data: DataFrame with SPY OHLCV data
            
        Returns:
            DataFrame with momentum indicators
        """
        # Calculate momentum using MomentumIndicator
        return self.momentum_indicator.calculate(spy_data, self.config["momentum_lookback"])
        
    def _calculate_spx_indicators(self, spx_data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate SPX indicators.
        
        Args:
            spx_data: DataFrame with SPX OHLCV data
            
        Returns:
            DataFrame with SPX indicators
        """
        # Calculate SPX ATR indicator
        atr_result = self.spx_atr_indicator.calculate(spx_data)
        
        # Calculate SPX price indicator
        price_result = self.spx_price_indicator.calculate(spx_data)
        
        # Calculate SPX consistency indicator
        consistency_result = self.spx_consistency_indicator.calculate(spx_data)
        
        # Calculate SPX consecutive bars indicator
        consecutive_result = self.spx_consecutive_indicator.calculate(spx_data)
        
        # Calculate SPX trend indicator
        trend_result = self.spx_trend_indicator.calculate(spx_data)
        
        # Combine all results
        result = pd.DataFrame({
            # ATR indicator
            "atr": atr_result["atr"],
            "atr_signal": atr_result["signal"],
            
            # Price indicator
            "price": price_result["price"],
            "price_change": price_result["price_change"],
            "price_range": price_result["price_range"],
            "max_price": price_result["max_price"],
            "min_price": price_result["min_price"],
            
            # Consistency indicator
            "is_consistent": consistency_result["is_consistent"],
            "trend_direction": consistency_result["trend_direction"],
            "is_stable": consistency_result["is_stable"],
            
            # Consecutive bars indicator
            "consecutive_up": consecutive_result["consecutive_up"],
            "consecutive_down": consecutive_result["consecutive_down"],
            "consecutive_signal": consecutive_result["signal"],
            
            # Trend indicator
            "trend_strength": trend_result["trend_strength"],
            "is_trend_change": trend_result["is_trend_change"],
            "trend_signal": trend_result["signal"]
        })
        
        return result
        
    def _calculate_rho(self, momentum_data: pd.DataFrame, spx_data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate correlation (rho) between momentum and SPX data.
        
        Args:
            momentum_data: DataFrame with momentum indicators
            spx_data: DataFrame with SPX indicators
            
        Returns:
            DataFrame with correlation indicators
        """
        # Calculate correlation using RhoIndicator
        rho_result = self.rho_indicator.calculate(spx_data, momentum_data)
        
        # Calculate correlation change using RhoChangeIndicator
        if "rho" in rho_result:
            change_result = self.rho_change_indicator.calculate(rho_result["rho"])
            
            # Combine results
            result = pd.DataFrame({
                "rho": rho_result["rho"],
                "rho_abs": rho_result["rho_abs"],
                "is_positive": rho_result["is_positive"],
                "is_negative": rho_result["is_negative"],
                "rho_change": change_result["change"],
                "is_significant_change": change_result["is_significant"],
                "change_direction": change_result["direction"]
            })
            
            return result
            
        return pd.DataFrame()
        
    def _update_indicators_state(self):
        """Update the internal state of all indicators."""
        # Extract the latest values for each indicator
        if self.momentum_data is not None and not self.momentum_data.empty:
            latest_momentum = self.momentum_data.iloc[-1].to_dict()
            self.indicators_state.update({"momentum": latest_momentum})
            
        if self.spx_data is not None and not self.spx_data.empty:
            latest_spx = self.spx_data.iloc[-1].to_dict()
            self.indicators_state.update({"spx": latest_spx})
            
        if self.rho_data is not None and not self.rho_data.empty:
            latest_rho = self.rho_data.iloc[-1].to_dict()
            self.indicators_state.update({"rho": latest_rho})
            
    def _check_entry_signals(self, spy_bar: Bar):
        """
        Check for entry signals and potentially enter a trade.
        
        Args:
            spy_bar: Latest SPY bar
        """
        # Skip if we can't enter a trade
        if not self.can_enter_trade():
            return
            
        # Check momentum entry conditions
        momentum_signal = self._check_momentum_entry()
        
        # Check SPX entry conditions
        spx_signal = self._check_spx_entry()
        
        # Check rho entry conditions
        rho_signal = self._check_rho_entry()
        
        # Combine signals
        entry_signals = []
        
        if self.config["momentum_entry"] and momentum_signal:
            entry_signals.append("momentum")
            
        if self.config["spx_entry"] and spx_signal:
            entry_signals.append("spx")
            
        if self.config["rho_entry"] and rho_signal:
            entry_signals.append("rho")
            
        # Enter trade if we have enough signals
        min_signals = sum([
            1 if self.config["momentum_entry"] else 0,
            1 if self.config["spx_entry"] else 0,
            1 if self.config["rho_entry"] else 0
        ])
        
        # Require at least 2 signals if all methods are enabled
        if min_signals > 2:
            min_signals = 2
            
        if len(entry_signals) >= min_signals:
            self._enter_trade(spy_bar, ", ".join(entry_signals))
            
    def _check_momentum_entry(self) -> bool:
        """
        Check momentum entry conditions.
        
        Returns:
            Whether momentum conditions are favorable for entry
        """
        if "momentum" not in self.indicators_state:
            return False
            
        momentum = self.indicators_state["momentum"]
        
        # Check cumulative momentum is positive and above threshold
        if momentum.get("cum_momentum", 0) > self.config["momentum_threshold"]:
            return True
            
        return False
        
    def _check_spx_entry(self) -> bool:
        """
        Check SPX entry conditions.
        
        Returns:
            Whether SPX conditions are favorable for entry
        """
        if "spx" not in self.indicators_state:
            return False
            
        spx = self.indicators_state["spx"]
        
        # Check for positive trend direction
        if spx.get("trend_direction", 0) > 0:
            # Check for consistency and stability
            if spx.get("is_consistent", False) and spx.get("is_stable", False):
                # Check for strong trend signal
                if spx.get("trend_signal", 0) > 0:
                    return True
                    
        return False
        
    def _check_rho_entry(self) -> bool:
        """
        Check correlation (rho) entry conditions.
        
        Returns:
            Whether correlation conditions are favorable for entry
        """
        if "rho" not in self.indicators_state:
            return False
            
        rho = self.indicators_state["rho"]
        
        # Check for positive correlation
        if rho.get("is_positive", False):
            # Check for significant correlation strength
            if rho.get("rho_abs", 0) > 0.7:
                return True
                
        # Check for correlation change
        if rho.get("is_significant_change", False) and rho.get("change_direction", 0) > 0:
            return True
            
        return False
        
    def _enter_trade(self, spy_bar: Bar, reason: str):
        """
        Enter a new trade.
        
        Args:
            spy_bar: Latest SPY bar
            reason: Reason for entering the trade
        """
        # Calculate position size
        position_size = self.config["position_size"]
        
        # Place order
        self.logger.info(f"Entering LONG position in {self.config['trading_symbol']}. Reason: {reason}")
        
        order = Order(
            symbol=self.config["trading_symbol"],
            quantity=position_size,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY
        )
        
        self.execution_provider.place_order(order)
        
    def _manage_position(self, spy_bar: Bar):
        """
        Manage an existing position.
        
        Args:
            spy_bar: Latest SPY bar
        """
        if not self.current_position:
            return
            
        # Check for stop loss
        if spy_bar.close <= self.stop_loss_price:
            self.close_position("Stop loss triggered")
            return
            
        # Check for profit target
        if spy_bar.close >= self.profit_target_price:
            self.close_position("Profit target reached")
            return
            
        # Check for maximum position duration
        if self.position_entry_time:
            duration = (datetime.now() - self.position_entry_time).total_seconds() / 60
            if duration >= self.config["max_position_duration"]:
                self.close_position("Maximum position duration reached")
                return
                
        # Check for end of day
        if datetime.now().time() >= self.config["intraday_stop_time"]:
            self.close_position("End of trading day")
            return
            
        # Check for exit signals
        if self._check_exit_signals():
            self.close_position("Exit signals triggered")
            return
            
    def _check_exit_signals(self) -> bool:
        """
        Check for exit signals.
        
        Returns:
            Whether exit signals are present
        """
        # Check momentum exit conditions
        momentum_exit = self._check_momentum_exit()
        
        # Check SPX exit conditions
        spx_exit = self._check_spx_exit()
        
        # Check rho exit conditions
        rho_exit = self._check_rho_exit()
        
        # Any single exit signal is enough to exit
        return momentum_exit or spx_exit or rho_exit
        
    def _check_momentum_exit(self) -> bool:
        """
        Check momentum exit conditions.
        
        Returns:
            Whether momentum conditions suggest exiting
        """
        if "momentum" not in self.indicators_state:
            return False
            
        momentum = self.indicators_state["momentum"]
        
        # Check for negative momentum
        if momentum.get("cum_momentum", 0) < -self.config["momentum_threshold"]:
            return True
            
        return False
        
    def _check_spx_exit(self) -> bool:
        """
        Check SPX exit conditions.
        
        Returns:
            Whether SPX conditions suggest exiting
        """
        if "spx" not in self.indicators_state:
            return False
            
        spx = self.indicators_state["spx"]
        
        # Check for negative trend direction
        if spx.get("trend_direction", 0) < 0:
            # Check for consistency and stability
            if spx.get("is_consistent", False) and spx.get("is_stable", False):
                # Check for negative trend signal
                if spx.get("trend_signal", 0) < 0:
                    return True
                    
        # Check for trend change
        if spx.get("is_trend_change", False) and spx.get("trend_signal", 0) < 0:
            return True
            
        return False
        
    def _check_rho_exit(self) -> bool:
        """
        Check correlation (rho) exit conditions.
        
        Returns:
            Whether correlation conditions suggest exiting
        """
        if "rho" not in self.indicators_state:
            return False
            
        rho = self.indicators_state["rho"]
        
        # Check for negative correlation
        if rho.get("is_negative", False):
            # Check for significant correlation strength
            if rho.get("rho_abs", 0) > 0.7:
                return True
                
        # Check for correlation change
        if rho.get("is_significant_change", False) and rho.get("change_direction", 0) < 0:
            return True
            
        return False
        
    def close_position(self, reason: str):
        """
        Close any current position.
        
        Args:
            reason: Reason for closing the position
        """
        if not self.current_position:
            return
            
        self.logger.info(f"Closing position in {self.config['trading_symbol']}. Reason: {reason}")
        
        # Get current position
        position = self.execution_provider.get_position(self.config["trading_symbol"])
        
        if position:
            # Place order to close position
            order = Order(
                symbol=self.config["trading_symbol"],
                quantity=-position.quantity,  # Negative to close
                order_type=OrderType.MARKET,
                side=OrderSide.SELL
            )
            
            self.execution_provider.place_order(order)
        else:
            # Reset position tracking if no actual position found
            self.current_position = None
            self.position_entry_time = None
            self.position_entry_price = None
            self.stop_loss_price = None
            self.profit_target_price = None 
"""
Market time utility functions for handling special dates and trading windows.
"""
from datetime import datetime, time, timedelta
from typing import Optional
import pytz

# New York timezone for market time calculations
NY_TZ = pytz.timezone('America/New_York')


class MarketTimeUtil:
    """
    Utility class for market time calculations and special date checks.
    """
    
    @staticmethod
    def convert_to_ny_time(dt: datetime) -> datetime:
        """
        Convert a datetime to New York timezone.
        
        Args:
            dt: Datetime to convert
            
        Returns:
            Datetime in New York timezone
        """
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        return dt.astimezone(NY_TZ)
    
    @staticmethod
    def is_market_open(dt: datetime) -> bool:
        """
        Check if the market is open at the given datetime.
        
        Args:
            dt: Datetime to check
            
        Returns:
            True if market is open, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Check if it's a weekday and within market hours (9:30 AM to 4:00 PM Eastern)
        return (ny_time.weekday() < 5 and  # Monday to Friday
                time(9, 30) <= t <= time(16, 0))
    
    @staticmethod
    def is_market_close_time(dt: datetime) -> bool:
        """
        Check if it's near market close time.
        
        Args:
            dt: Datetime to check
            
        Returns:
            True if it's close to market close, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        return time(15, 50) <= t <= time(16, 0)
    
    @staticmethod
    def is_half_day(dt: datetime) -> bool:
        """
        Check if the given date is a half trading day.
        
        Args:
            dt: Date to check
            
        Returns:
            True if it's a half day, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        date = ny_time.date()
        
        # Pre-holidays that are typically half days
        # July 3rd, day before Christmas, day before Independence Day
        if (date.month == 7 and date.day == 3) or \
           (date.month == 12 and date.day == 24) or \
           (date.month == 11 and date.day == 23):  # Day before Thanksgiving
            return True
        
        return False
    
    @staticmethod
    def is_ir_date(dt: datetime) -> bool:
        """
        Check if the given date is an interest rate announcement date.
        
        Args:
            dt: Date to check
            
        Returns:
            True if it's an IR date, False otherwise
        """
        # This is a placeholder - in a real implementation, you would check
        # against a calendar of actual FOMC meeting dates or other interest rate announcements
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        date = ny_time.date()
        
        # Example: First Wednesday of every other month might be FOMC
        # This is just an example and should be replaced with actual dates
        if date.weekday() == 2:  # Wednesday
            if date.day <= 7:  # First week
                if date.month in [1, 3, 5, 7, 9, 11]:  # Odd months
                    return True
        
        return False
    
    @staticmethod
    def is_treasury_date(dt: datetime) -> bool:
        """
        Check if the given date is a Treasury auction date.
        
        Args:
            dt: Date to check
            
        Returns:
            True if it's a Treasury date, False otherwise
        """
        # This is a placeholder - in a real implementation, you would check
        # against a calendar of actual Treasury auction dates
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        date = ny_time.date()
        t = ny_time.time()
        
        # Example: Treasury auctions at 1pm on Tuesdays
        if date.weekday() == 1:  # Tuesday
            if time(13, 0) <= t <= time(13, 5):  # Around 1pm
                return True
        
        return False
    
    @staticmethod
    def is_fed_chair_talking(dt: datetime, start_time: Optional[time] = None) -> bool:
        """
        Check if the Fed chair is scheduled to speak at the given time.
        
        Args:
            dt: Date and time to check
            start_time: Optional specific start time to check
            
        Returns:
            True if the Fed chair is speaking, False otherwise
        """
        # This is a placeholder - in a real implementation, you would check
        # against a calendar of Fed chair speaking events
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # If a specific start time is provided, check around that time
        if start_time is not None:
            # Check if current time is within 30 minutes of the specified start time
            start_mins = start_time.hour * 60 + start_time.minute
            current_mins = t.hour * 60 + t.minute
            
            return abs(current_mins - start_mins) <= 30
        
        return False
    
    @staticmethod
    def is_news_at_10am(dt: datetime) -> bool:
        """
        Check if there's important news at 10 AM.
        
        Args:
            dt: Date and time to check
            
        Returns:
            True if there's important news at 10 AM, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Check if it's around 10 AM
        return time(9, 55) <= t <= time(10, 5)
    
    @staticmethod
    def is_fed_news_at_2pm(dt: datetime) -> bool:
        """
        Check if there's Fed news at 2 PM.
        
        Args:
            dt: Date and time to check
            
        Returns:
            True if there's Fed news at 2 PM, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Check if it's an IR date and around 2 PM
        return MarketTimeUtil.is_ir_date(dt) and time(13, 55) <= t <= time(14, 5)
    
    @staticmethod
    def is_fed_news_after_2pm(dt: datetime, minutes_after: int = 15) -> bool:
        """
        Check if it's after Fed news at 2 PM.
        
        Args:
            dt: Date and time to check
            minutes_after: Minutes after 2 PM to check
            
        Returns:
            True if it's after Fed news at 2 PM, False otherwise
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Check if it's an IR date and after 2 PM but within the specified window
        if MarketTimeUtil.is_ir_date(dt):
            two_pm_mins = 14 * 60  # 2 PM in minutes
            current_mins = t.hour * 60 + t.minute
            
            return two_pm_mins <= current_mins <= two_pm_mins + minutes_after
        
        return False
    
    @staticmethod
    def get_trading_minutes_elapsed(dt: datetime) -> int:
        """
        Get the number of minutes elapsed since market open.
        
        Args:
            dt: Current datetime
            
        Returns:
            Minutes elapsed since market open
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Market opens at 9:30 AM
        market_open_mins = 9 * 60 + 30
        current_mins = t.hour * 60 + t.minute
        
        return max(0, current_mins - market_open_mins)
    
    @staticmethod
    def get_trading_minutes_remaining(dt: datetime) -> int:
        """
        Get the number of minutes remaining until market close.
        
        Args:
            dt: Current datetime
            
        Returns:
            Minutes remaining until market close
        """
        ny_time = MarketTimeUtil.convert_to_ny_time(dt)
        t = ny_time.time()
        
        # Market closes at 4:00 PM
        market_close_mins = 16 * 60
        current_mins = t.hour * 60 + t.minute
        
        return max(0, market_close_mins - current_mins) 
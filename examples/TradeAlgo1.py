import backtrader as bt
import pandas as pd
import numpy as np
import datetime 
from datetime import datetime, timedelta, time
import os
import requests
import pytz
import argparse
from typing import Optional, Tuple
import math   
import pandas as pd
import numpy as np
import os
import requests
import pytz
import argparse
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
ny_tz = pytz.timezone('America/New_York')
adj1_map = {}
class MarketData(bt.feeds.PandasData): # QQQ数据源类   3.40pm 之后 买入的是 1-2档期权
    lines = ('average', 'barcount',)
    params = (
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('average', 'average'),
        ('barcount', 'barCount'),
        ('openinterest', -1),)
def download_market_data(symbol: str, date: datetime, save_dir: str) -> Optional[str]:
    """
    从网站下载市场数据并保存到指定目录
    Parameters:
        symbol (str): 交易品种 (QQQ 或 SPX)
        date (datetime): 需要下载的日期
        save_dir (str): 保存目录
    Returns:
        Optional[str]: 保存的文件路径，如果下载失败则返回None
    """
    # 确保目录存在
    os.makedirs(save_dir, exist_ok=True)
    # 构建文件名
    filename = f"{symbol.lower()}.{date.strftime('%Y-%m-%d')}.csv"
    filepath = os.path.join(save_dir, filename)
    # 如果文件已存在，直接返回路径
    if os.path.exists(filepath):
        print(f"Found existing {symbol} data file: {filepath}")
        return filepath
    try:
        # TODO: 替换为实际的数据下载URL和认证信息
        base_url = "http://49.51.247.41:8000/marketdata/"
        url = f"{base_url}/{symbol.lower()}/{symbol.lower()}.{date.strftime('%Y-%m-%d')}.csv"
        print(f"Downloading {symbol} data for {date.strftime('%Y-%m-%d')}...")
        response = requests.get(url)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            print(f"Successfully downloaded {symbol} data to {filepath}")
            return filepath
        else:
            raise Exception(f"Failed to download {symbol} data: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error downloading {symbol} data: {str(e)}")
        return None
def process_market_data(df: pd.DataFrame, symbol: str, freq: str = '5S') -> pd.DataFrame:
    """    处理市场数据，包括时区转换和重采样
    Parameters:
        df (pd.DataFrame): 原始数据框
        symbol (str): 交易品种
        freq (str): 重采样频率 (默认5秒)
    Returns:
        pd.DataFrame: 处理后的数据框 """
    # 处理时间列
    df['datetime'] = pd.to_datetime(df['date'])
    # 标准化时区
    if df['datetime'].dt.tz is None:
        df['datetime'] = df['datetime'].dt.tz_localize('America/New_York')
    else:
        df['datetime'] = df['datetime'].dt.tz_convert('America/New_York')
    if symbol == 'QQQ' or symbol == 'SPY':
        # 把时间往后调5s
        df['datetime'] = df['datetime'] + timedelta(seconds=5)
    # 设置索引并过滤市场时间
    df.set_index('datetime', inplace=True)
    df = df.between_time('09:30:00', '16:00:00')
    df = df.drop('date', axis=1)
    return df
def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Run VWAP Momentum Strategy Backtest')
    parser.add_argument('--start-date', type=str, required=True,
                      help='Start date in YYYY-MM-DD format')
    parser.add_argument('--end-date', type=str, required=True,
                      help='End date in YYYY-MM-DD format')
    parser.add_argument('--abs-dir', type=float, default=100,
                      help='abs direction in float')
    parser.add_argument('--max-workers', type=int, default=4,
                      help='Maximum number of parallel workers for data preparation')
    parser.add_argument('--adj1-csv', type=str, default='adj1.csv',
                     help='Path to the adjust1 CSV file')
    args = parser.parse_args()
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
        abs_dir = args.abs_dir
        if end_date < start_date:
            raise ValueError("End date must be after start date")
    except ValueError as e:
        raise ValueError(f"Invalid date format or range: {str(e)}")
    return start_date, end_date, abs_dir, args.max_workers, args.adj1_csv
def load_adj1_data(csv_path: str):
    """    加载adj1调整因子数据    """
    try:
        # 创建时间到调整因子的映射
        df = pd.read_csv(csv_path)
        # 将时间列转换为索引
        df['time'] = pd.to_datetime(df['time']).dt.strftime('%H:%M:%S')       
        for i in range(len(df) - 1):
            current_time = df.iloc[i]['time']
            current_adj = df.iloc[i]['adj1']
            adj1_map[current_time] = current_adj 
    except Exception as e:
        print(f"Error loading adj1 data: {str(e)}")
        return {t.strftime('%H:%M:%S'): 1.0 for t in pd.date_range('09:30:00', '16:00:00', freq='5S')}
    return df['adj1']
def get_adj1_value(index: pd.DatetimeIndex) -> pd.Series:
    """
    获取时间序列索引对应的 adj1 调整因子值
    Args:
        index: DatetimeIndex of the time series
    Returns:
        pd.Series: Series of adjustment factors aligned with the index
    """
    # 将索引时间转换为与 adj1_map 键匹配的格式
    time_strings = index.strftime('%H:%M:%S')
    # 创建调整因子序列，确保索引与输入的 DataFrame 匹配
    adj_factors = pd.Series([adj1_map.get(t, 1.0) for t in time_strings], index=index)
    # 将所有为0的值替换为1，避免除以0的情况
    adj_factors = adj_factors.replace(0, 1.0)
    return adj_factors
# Helper function for momentum calculation
def calculate_momentum(df_spy: pd.DataFrame,df_spx: pd.DataFrame, period_spy: int = 3, period_spx: int = 5) -> pd.DataFrame:
    """
    Calculate momentum as per the simplified strategy.
    Period = 15s means N=3 bars for 5s data.
    """
    df_spx_5s_copy = df_spx[::5].copy()
    df_spy_copy = df_spy.copy()
    # Rolling calculations for N periods (default 15s = 3 bars of 5s data)
    df_spy_copy['volume_n'] =   df_spy_copy['volume'].rolling(window=period_spy, min_periods=1).sum()
    df_spy_copy['turnover_n'] = (df_spy_copy['close'] * df_spy_copy['volume']).rolling(window=period_spy, min_periods=1).sum()
    # Simon test: #其它方案 待测，close 用 avg 或者1/2(close+avg), or  1/2(close+H(涨) or L（跌）)，或者 1/3(close+H(涨) or L（跌） + avg)
    df_spy_copy['px_n'] =       df_spy_copy['turnover_n'] / df_spy_copy['volume_n']
    # Calculate % change over 1 bar (5s interval)
    df_spy_copy['px_change'] =  df_spy_copy['px_n'] / df_spy_copy['px_n'].shift(1) - 1.0
    df_spy_copy['spx_change_5s'] = df_spx_5s_copy['close'] - df_spx_5s_copy['close'].shift(1) 
    df_spy_copy['spy_change_5s'] = df_spy_copy['px_n'] - df_spy_copy['px_n'].shift(1) 
    df_spy_copy['spx_change_5s_abs'] = (abs(df_spx_5s_copy['close'] - df_spx_5s_copy['close'].shift(1))).replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    df_spy_copy['spy_change_5s_abs'] = (abs(df_spy_copy['px_n'] - df_spy_copy['px_n'].shift(1))).replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    # Calculate d_momentum and apply time adjustment
    df_spy_copy['d_momentum'] = df_spy_copy['volume_n'] * df_spy_copy['px_change'] / get_adj1_value(df_spy_copy.index)
    df_spy_copy['d_momentum'] = df_spy_copy['d_momentum'].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    # Cumulative momentum from market open
    df_spy_copy['momentum'] =   df_spy_copy['d_momentum'].cumsum()
    # Handle NaN and infinite values
    df_spy_copy['momentum'] =   df_spy_copy['momentum'].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    df_spy_copy['mom_abs'] =    (abs(df_spy_copy['d_momentum'])).cumsum().replace([np.inf, -np.inf], np.nan).ffill().fillna(0)  #simon ????
    # For Backtrader compatibility, set OHLC to momentum
    df_spy_copy.to_csv("spy."+start_date.strftime('%Y-%m-%d')+"_to_"+end_date.strftime('%Y-%m-%d') + "_mom_b.csv")
    df_spy_copy['open'] =   df_spy_copy['momentum']   # open = momentum
    df_spy_copy['high'] =   df_spy_copy['mom_abs']
    df_spy_copy['low'] =    df_spy_copy['spx_change_5s_abs']      # min4
    df_spy_copy['close'] =  df_spy_copy['momentum']      #  max (abs (momentum))
    df_spy_copy['volume'] = df_spy_copy['d_momentum']  # vol = dmom
    # Drop unnecessary columns
    df_spy_copy.drop(['volume_n', 'turnover_n', 'px_n', 'px_change', 'd_momentum','mom_abs','spx_change_5s_abs','spy_change_5s_abs'], axis=1, inplace=True)
    return df_spy_copy
class MomentumTrendStrategy(bt.Strategy):  #前2分钟 只用止损
    params = (
        ('atr_period', 22),     # ATR 周期
        ('abs_dir', 0.0),  # 3 or 3.01 = only trade super large sig 开始仓位=40%, 3.01 above = 3 + 其它过滤， 开始仓位=60% 
        ('abs_dir_ir_date_or_high_vol', 0.0),  #1.414 not allow to trade <= this 
        ('option_trading', True),  #  允许换仓
        ('stable_period', 9600),     # stable  and R<xxx, and 1.832075486019421 2.249433674856704 4.524530311558768 3.8425152115063006
        ('strong_threshold', 401),  # simon ? 360-500   case1 强阈值 = 200 * 1.618 ≈ 360   , 320 需要等待
        ('sig_threshold', 201),  #225/200 simon ? 180-200 150-200 test  之前是200， 先做判断   : 100 for 3, 160->120->100-110
        ('large_mom', 500),  # 400-500  ; sqrt[500/200]= 1.723 or 500      # 同上 重复了 or  520 /600    case1 强阈值 = 200 * 1.618 ≈ 320 # above this, not trade for 2a(b) 可能有太强的限制
        ('medium_threshold', 150),  # case2a 中等阈值 : 待测 test case
        ('consistency_threshold', 8),  # case2a 一致性条件阈值
        ('trend_bar_threshold1', 7.5),  # case2b 一致性趋势bar的阈值1, 实际用的 是 10， 10或者7.5  
        ('trend_bar_threshold2', 30),  #  case2b  一致性趋势bar的阈值2      # *6000 = 6-8points  * self.data_spx.close[0]*0.001 , mim_increment for spx last 5s case 1  ????? 1 or 2 if N=60  simon
        )   #反弹压力线，类似extreme2  但是反方向， todo  # *6000 = 6-8points  * self.data_spx.close[0]*0.001 , mim_increment for spx last 5s case 1  ????? 1 or 2 if N=60  simon      
    def __init__(self):
        self.data_spx = self.datas[0]  # SPX 数据
        self.data_spy = self.datas[1]  # SPY 数据
        self.data_momentum = self.datas[2]  # 动量数据
        self.data_cor3m = self.datas[3]  # 动量数据
        # self.abs_dir = min(100,self.datas[4])
        self.atr = bt.indicators.ATR(self.data_spy, period=self.params.atr_period)
        self.init_data()        # 初始化数据    
    def half_date(self): # to add more simon
        date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)
        date2=[datetime(2022,7,3),  datetime(2023,7,3),  datetime(2024,7,3),  datetime(2025,7,3),  datetime(2026,7,3),  datetime(2027,7,3),  datetime(2028,7,3),  datetime(2029,7,3),  datetime(2030,7,3),\
               datetime(2022,11,25),datetime(2023,11,24),datetime(2024,11,29),datetime(2025,11,28),datetime(2026,11,27),datetime(2027,11,26),datetime(2028,11,24),datetime(2029,11,23),datetime(2030,11,29),\
               datetime(2022,12,24),datetime(2023,12,24),datetime(2024,12,24),datetime(2025,12,24),datetime(2026,12,24),datetime(2027,12,24),datetime(2028,12,24),datetime(2029,12,24),datetime(2030,12,24)]
        return any(d.date() == date1.date() for d in date2)
    def ir_date(self): # to add more simon
        date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)
        date2=[datetime(2022,9,21),datetime(2022,11,2),datetime(2022,12,14),datetime(2023,2,1),datetime(2023,3,22),datetime(2023,5,3),datetime(2023,6,14),datetime(2023,7,26),\
               datetime(2023,9,20),datetime(2023,11,1),datetime(2023,12,13),datetime(2024,1,31),datetime(2024,3,20),datetime(2024,5,1),datetime(2024,6,12),datetime(2024,7,31),\
               datetime(2024,9,18),datetime(2024,11,7),datetime(2024,12,18),datetime(2025,1,29),datetime(2025,3,19),datetime(2025,5,7),datetime(2025,6,18),datetime(2025,7,30),\
               datetime(2025,9,17),datetime(2025,10,29),datetime(2025,12,10)]
        return any(d.date() == date1.date() for d in date2)
    def minute_date(self): # to add more simon
        date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)-21
        date2=[datetime(2022,9,21),datetime(2022,11,2),datetime(2022,12,14),datetime(2023,2,1),datetime(2023,3,22),datetime(2023,5,3),datetime(2023,6,14),datetime(2023,7,26),\
               datetime(2023,9,20),datetime(2023,11,1),datetime(2023,12,13),datetime(2024,1,31),datetime(2024,3,20),datetime(2024,5,1),datetime(2024,6,12),datetime(2024,7,31),\
               datetime(2024,9,18),datetime(2024,11,7),datetime(2024,12,18),datetime(2025,1,29),datetime(2025,3,19),datetime(2025,5,7),datetime(2025,6,18),datetime(2025,7,30),\
               datetime(2025,9,17),datetime(2025,10,29),datetime(2025,12,10)]
        return any(d.date() == date1.date() for d in date2)
    def fed_chair_talk_date_time(self,time_start:time):
        date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)-21
        date2=[datetime(2025,4,16)]
        # time_start = time(13,30,0) 
        return_value = any(d.date() == date1.date() for d in date2) and self.current_time_NY.time()>= time_start
        return return_value
    def treasury_date(self): # to add more simon 3pm
        date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)-21
        date2=[datetime(2022,9,21),datetime(2022,11,2),datetime(2022,12,14),datetime(2023,2,1),datetime(2023,3,22),datetime(2023,5,3),datetime(2023,6,14),datetime(2023,7,26),\
               datetime(2023,9,20),datetime(2023,11,1),datetime(2023,12,13),datetime(2024,1,31),datetime(2024,3,20),datetime(2024,5,1),datetime(2024,6,12),datetime(2024,7,31),\
               datetime(2024,9,18),datetime(2024,11,7),datetime(2024,12,18),datetime(2025,1,29),datetime(2025,3,19),datetime(2025,5,7),datetime(2025,6,18),datetime(2025,7,30),\
               datetime(2025,9,17),datetime(2025,10,29),datetime(2025,12,10)]
        return any(d.date() == date1.date() for d in date2)
    def init_data(self):        # 初始化数据
        self.allow_trend = True
        self.is_high_vol = False
        self.is_low_vol = False        
        self.max_sig_type = 0
        self.day_count = 0
        self.ir_2pm_mom = None
        self.ir_2pm_spx = None
        if self.day_count == 0: 
            self.record_list = []
            self.max_pnl = []
            self.pnl = [] 
            self.posi_ratio = []
            self.trade_type = []
            self.trade_start = []
            self.trade_end = []
        self.swap_count=0
        self.adj_ratio=1.0
        self.allow_swap_trade = self.p.option_trading
        self.afternoon_start =3600 * 3.25-600 if not self.half_date() else 3600*6.5
        self.noon_start =3600 * 2.5+5*60 if not self.half_date() else 3600*6.5
        self.noon_end =3600 * 4+5*60 if not self.half_date() else 3600*6.5
    
        self.abs_dir = self.p.abs_dir
        self.c_0 =1.0
        self.big_down_mom = False
        self.big_up_mom = False
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.current_max4 = 0
        self.current_min4 = 0
        self.current_max6 = 0
        self.current_min6 = 0
        self.current_max12 = 0
        self.current_min12 = 0
        self.previous_price_N = None
        self.abs_spx,self.spx,self.spy_close,self.spy_open,self.spy_high,self.spy_low = [], [],[], [], [],[]
        self.mom = []
        self.abs_mom = []
        self.d_mom = []
        self.mom_pos = []
        self.mom_neg = []
        self.abs_spy =  []
        self.rho =  []
        self.abs_rho =  []
        self.R_all,self.R_30_min,self.R_3_min,self.R_1_min = 0,0,0,0
        self.is_news_impact = False
        self.is_small_mom = True
        self.big_up_2,self.big_down_2=False,False
        self.close_lock,   self.trade_lock = False, False
        self.current_date = self.data_spx.datetime.date(0)
        self.stop_loss_price_worst = None
        self.if_can_trade = False
        # 入场等待细节 + 持仓跟踪
        self.is_ir_date = self.ir_date()
        self.buy_count, self.sell_count = 0,0
        self.position_size = 0   #abs value
        self.my_position = 0  
        self.entry_price = None 
        self.extreme_price0 = None
        self.ref_price0 = None

        self.cleanup()
        self.buy_super_sig_count, self.sell_super_sig_count = 0,0
        # 市场时间
        self.market_open_time,self.market_close_time = time(9, 30, 0),time(15, 59, 30)        # self.news_wait_start_1 = time(9, 59, 0)        # self.news_wait_end_1 = time(10, 00, 0)        # self.news_wait_start_2 = time(13, 59, 0)        # self.news_wait_end_2 = time(14, 00, 0)        # self.news_wait_start_3 = time(14, 59, 0)        # self.news_wait_end_3 = time(15, 00, 0)
        
        self.symmetric_ratio_up,self.symmetric_ratio_down=1.0,1.0
        
    def is_market_close_bar(self):
        # 检查是否为市场收盘 bar
        if len(self.data_spy) >= self.data_spy.buflen() - 1:
            return True
        current_date = self.data_spy.datetime.date(0)
        next_date = self.data_spy.datetime.date(2)
        if current_date != next_date:
            True
            print(self.R_all,self.R_30_min,self.R_3_min,self.R_1_min,self.pnl,self.max_sig_type,self.posi_ratio,self.trade_start,self.trade_end)
        return current_date != next_date
    
    def can_trade(self):
        # 检查是否在交易时间内
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.market_open_time <= current_time < self.market_close_time
    
    def news_impacted(self,threshold=30.0):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        if (time(10, 0, 0) <= current_time <= time(10, 0, 15) or time(14, 0, 0) <= current_time <= time(14, 0, 15)) and (not self.ir_date()):
            if (self.current_max4)>threshold or (self.current_min4)<threshold:
                self.is_news_impact = True
                
    def can_adj2_smaller(self):
        # 检查是否在交易时间内
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        trading1 = (time(9, 46, 0) <= current_time < time(12, 2, 0))# 待测
        trading2 = (time(13, 0, 10) <= current_time < time(15, 32, 0))# 待测
        trading3 = (time(13, 0, 6) <= current_time < time(13, 1, 45))# 待测
        trading4 = (time(12, 29, 6) <= current_time < time(13, 31, 30))# 待测
        trading5 = (time(13, 1, 0) <= current_time < time(13, 1, 30))# 待测
        if (trading1 or trading2 or trading3 or trading4 or trading5): 
            return True  # 待测
        else:
            return False
    def fed_news_reset_mom_before_2pm(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and current_time > time(13, 59, 55) and current_time <= time(13, 59, 59)
    def fed_news_at_2pm(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 0, 0) < current_time <= time(14, 0, 5))
    def fed_news_at_2pm_b(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 0, 5) < current_time <= time(14, 0, 10))
    def fed_news_at_2pm_c(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 0, 10) < current_time <= time(14, 0, 15))
    def fed_news_after_2pm_a(self): # simon ???????
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 0, 5) < current_time <= time(14, 3, 15))
    def fed_news_after_2pm_b(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 3, 15) < current_time <= time(14, 33, 15))
    def fed_news_after_230pm_c(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(14, 33, 15) < current_time <= time(15, 0, 5))
    def fed_news_after_3pm_d(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return self.is_ir_date and (time(15, 0, 5) < current_time <= time(15, 59, 0))
    def news_at_10_am(self):
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return time(10, 0, 0) < current_time <= time(10, 0, 15)
    def can_trade_noon_trend(self):  # bandwidth parameter
        # 检查是否在交易时间内  reverse case， 
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        yes_trading1 = time(11, 30, 45) > current_time or current_time > time(13, 30, 45) # (time(9, 30, 20) <= current_time < time(9, 58, 45))# 待测 
        A=self.buy_count+self.sell_count 
        return yes_trading1 and A==0 and not self.ir_date() and abs(self.data_momentum[0])<500*2 # profit taken
    def can_trade_consistent_trend(self):  # bandwidth parameter
        # 检查是否在交易时间内  reverse case， 
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        no_trading1 = time(9, 58, 45) <= current_time < time(10, 0, 45) # (time(9, 30, 20) <= current_time < time(9, 58, 45))# 待测 
        no_trading2 = self.is_ir_date and (time(13, 58, 30)  <= current_time < time(14, 0, 45))   # (time(10, 0, 45) <= current_time < time(13, 58, 30))# 待测
        no_trading3 = self.is_ir_date and (time(14, 28, 30)  <= current_time < time(14, 30, 5))  # treasury and ir rate release date
        no_trading4 = self.is_ir_date and (time(14, 34, 55) <= current_time < time(15, 2, 55))# 待测 # (time(14, 0, 45) <= current_time < time(14, 58, 45))# 待测        # trading4 = (time(15, 0, 45) <= current_time < time(15, 44, 45))# 待测
        no_trading5 = (time(15, 59, 5)<= current_time< time(15, 59, 59)) # or (time(15, 49, 45) <= current_time < time(15, 50, 45))  or  (time(15, 54, 45) <= current_time < time(15, 55, 45)) # 待测
        no_trading6 = (time(12, 59, 45) <= current_time <= time(13, 0, 55)) or (time(13, 59, 45) <= current_time <= time(14, 0, 55)) or (time(14, 59, 45) <= current_time <= time(15, 0, 55)) 
        # no_trading5 = (time(15, 44, 45)<= current_time< time(15, 45, 45)) or (time(15, 49, 45) <= current_time < time(15, 50, 45))  or  (time(15, 54, 45) <= current_time < time(15, 55, 45)) # 待测
        if (no_trading1 or no_trading2 or no_trading3 or no_trading4 or no_trading5 or no_trading5) or no_trading6: 
            return False  # 待测 ????????simon
        else:
            return True
    def check_consistency_stability(self, max4: float, min4: float) -> Tuple[bool, bool]:
        """
        检查一致性稳定条件
        Case 3a: 一致性稳定后的中信号入场
        """
        if (len(self.data_momentum) < 24):
            return False, False
        else:
            # 使用平均值作为2分钟分歧
            # 取(T-1min, T-2min) 中a_t的平均值
            d_mom_values = list(self.data_momentum.volume.get(size=48))
            # 计算每12个点的绝对值之和生成a_t_values
            a_t_values = []
            for i in range(0, len(d_mom_values) - 24):
                if i + 24 <= len(d_mom_values):
                    group_sum = sum(abs(x) for x in d_mom_values[i:i+24])
                    a_t_values.append(group_sum)
            # 使用平均值作为2分钟分歧
            # 取(T-1min, T-2min) 中a_t的平均值
            a_t_values = a_t_values[0:12]
            two_min_divergence = sum(a_t_values) / len(a_t_values) if len(a_t_values)>0 else 0.00000001
            # 检查是否满足一致性条件
            return max4 / two_min_divergence > self.p.consistency_threshold, min4 / two_min_divergence > self.p.consistency_threshold
    def check_consistency_trend2(self,window = 360,offset =18): #noon or long trend
        """
        offset <=36     18/12/4
        检查一致性趋势条件 market open
        Case 0: 一致性趋势后的中信号入场
        """
        if len(self.data_momentum.volume) < 36:  # 需要至少3分钟的数据  9.33.01am
            return False, 0, 0, 0
        window=min(len(self.data_momentum.volume),window + offset) #  # window2 = min(len(self.data_momentum.volume),window + offset)
        # 计算前30分钟的累计d_mom_positive和d_mom_negative         # window = 360  # 30分钟 = 360个5s bar
        recent_d_mom = list(self.data_momentum.volume.get(size=window))
        recent_d_mom =recent_d_mom[:-offset] 
        up_trend = sum(max(d, 0) for d in recent_d_mom)
        down_trend = sum(min(d, 0) for d in recent_d_mom)
        up_trend = max(up_trend,0.000001)
        down_trend = min(down_trend,0.000001)
        if abs(down_trend) <= 0.000001:  # 避免除以接近0的数         # 计算趋势比率
            trend_ratio = 100 if up_trend > 0 else 0
        else:
            trend_ratio = up_trend / (-down_trend)
        return True, trend_ratio,up_trend, down_trend
    def check_consecutive_bars_2(self, threshold=-2.0, threshold2=15,A=4):
        """1 检查连续3个bar是否都大于或小于给定阈值"""
        """2 检查连续两个的连续3个bar是否都大于或小于给定阈值2"""
        """3 检查连续4个bar是否都大于或小于给定阈值3 and max4/min4 >200"""
        if len(self.data_momentum.volume) <= 12: 
            # 3 or 4 bars 
            return False, False
        threshold = threshold*self.symmetric_ratio_up
        threshold2 = threshold2*self.symmetric_ratio_up

        last_5 = self.mom[-A:]#list(self.data_momentum.volume.get(size=A))
        bullish = all(d > threshold for d in last_5)
        bearish = all(d < -threshold for d in last_5)
        second_last_5 = self.mom[-2*A:-A] # list(self.data_momentum.volume.get(size=2*A))[:-A]  #simon to check for size=3 / 4 A+1

        bullish1 = any(d > threshold2 for d in last_5)
        bullish2 = any(d > threshold2 for d in second_last_5)
        bullish = (bullish and bullish2 and bullish1)  # bullish = (bullish and bullish2) or (bullish2 and bullish1) #and or 

        bearish1 = any(d < - threshold2 for d in last_5)
        bearish2 = any(d < - threshold2 for d in second_last_5)
        bearish = (bearish and bearish1 and bearish2)  # and or # bearish = (bearish and bearish2) or (bearish1 and bearish2) 
        A, B  = sum(last_5),sum(second_last_5)
        C = A+B 
        return bullish, bearish
    def check_consecutive_bars(self, threshold=7.5, threshold2=30,A=4):
        """1 检查连续3个bar是否都大于或小于给定阈值"""
        """2 检查连续两个的连续3个bar是否都大于或小于给定阈值2"""
        """3 检查连续4个bar是否都大于或小于给定阈值3 and max4/min4 >200"""
        if len(self.data_momentum.volume) <= 8: 
            # 3 or 4 bars 
            return False, False
        last_three = self.mom[-A:] # list(self.data_momentum.volume.get(size=A))
        bullish = all(d > threshold for d in last_three)
        bearish = all(d < -threshold for d in last_three)
        second_last_three = self.mom[-2*A:-A]  # list(self.data_momentum.volume.get(size=2*A))[:-A]  #simon to check for size=3 / 4 A+1

        bullish1 = any(d > threshold2 for d in last_three)
        bullish2 = any(d > threshold2 for d in second_last_three)
        bullish = (bullish and bullish2 and bullish1)  # bullish = (bullish and bullish2) or (bullish2 and bullish1) #and or 

        bearish1 = any(d < - threshold2 for d in last_three)
        bearish2 = any(d < - threshold2 for d in second_last_three)
        bearish = (bearish and bearish1 and bearish2)  # and or # bearish = (bearish and bearish2) or (bearish1 and bearish2) 
        return bullish, bearish
    def check_consecutive_bars2(self, threshold=1, threshold2=100):#30 200
        """ 检查连续4个bar是否都大于或小于给定阈值 and max4/min4 >阈值2, 200"""
        if len(self.data_momentum.volume) < 4:      return False, False
        last_4 = self.mom[-4:]  #list(self.data_momentum.volume.get(size=4))
        sum = last_4[0]+last_4[1]+last_4[2]+last_4[3]
        bullish = all(d > threshold for d in last_4) and sum>threshold2
        bearish = all(d < -threshold for d in last_4) and sum<-threshold2
        return bullish, bearish

    def one_min_trend_entry(self,ratio=1,N=6,delay:int=1): #used in a different way  ; argmax or argmin is possible to use
        if len(self.mom)-2>2*N:
            M= min (2*N,len(self.mom)-2)
            range_max,range_min,index_max,index_min=self.range_N()
            
            delay_spx=5*delay
            recent_data_mom = self.mom[-M-delay:-1-delay]  #list(self.data_momentum.close.get(size=M))
            high_mom, low_mom,max_index_mom,min_index_mom=self.calculate_series_max_min( recent_data_mom,0,True)
            
            recent_data = self.spx[-5*M-delay_spx:-1-delay_spx]  #list(self.data_spx.close.get(size=5*M))
            high, low,max_index,min_index=self.calculate_series_max_min( recent_data,0,False)
            
            A=1.1111111111 * self.p.sig_threshold  # adj_ratio
            B=0.002 * self.spx[-1-delay]*0.5
            D= 1.8 if self.fed_news_after_2pm_a() or self.fed_news_after_2pm_b()  else 1.0 
            N_mom=len(self.mom)-1
            Diff_1N,Diff_2N=0,0

            if N_mom>=2*N:
                Diff_1N = self.mom[-1-delay]-self.mom[-1 -N-delay]
                Diff_2N = self.mom[-1-N-delay]-self.mom[-1 -2*N-delay]
                Diff_3 = self.mom[-1-delay]-self.mom[-1 -3-delay]  #  N/2
                # Diff_2 =self.data_momentum.close[N_mom-N]-self.data_momentum.close[N_mom-2*N]
                # self.range_N()
                # 10 not use ratio
            if max_index_mom - min_index_mom<-(N+1) and self.spx[-1-delay]-recent_data[min_index]<1.35 \
                and self.mom[-1-delay]-recent_data_mom[min_index_mom]<10 and\
                Diff_1N<-ratio* A*0.45*D*self.symmetric_ratio_down and \
                Diff_2N<-ratio*A*0.45*D*self.symmetric_ratio_down and \
                    Diff_3<-ratio*A*0.2*D*self.symmetric_ratio_down \
                    and high - low>B and self.entry_type0 !="short" and not self.normal_down: 
                
                print(f'entry down trend-2: @ {self.spx[-1-delay]-recent_data[min_index],self.mom[-1]-recent_data_mom[min_index_mom],self.current_time_NY,self.symmetric_ratio_down, high - low, Diff_1N, Diff_2N,self.fed_news_after_2pm_b(),self.ir_date(),A,D} ')
                # self.sell_ trade(-1.082) 
                return -1
            elif max_index_mom - min_index_mom>(N+1) and -self.spx[-1-delay]+recent_data[max_index]<1.35 and\
                -self.mom[-1]+recent_data_mom[max_index_mom]<10 and \
                    Diff_1N> ratio* A*0.45*D*self.symmetric_ratio_up and \
                        Diff_2N> ratio* A*0.45*D*self.symmetric_ratio_up and \
                        Diff_3> ratio* A*0.2*D*self.symmetric_ratio_up and \
                high - low>B and self.entry_type0 !="long"  and not self.normal_up: #self.normal_up is False:
                print(f'entry up trend+2: @ {self.symmetric_ratio_up,-self.spx[-1-delay]+recent_data[max_index],-self.mom[-1]+recent_data_mom[max_index_mom],self.symmetric_ratio_up,self.current_time_NY,high - low,Diff_1N, Diff_2N,self.fed_news_after_2pm_b(),self.ir_date(),A,D}')
                # self.buy_tr ade(1.082) 
                return 1
        return 0
    
    def one_min_trend_exit(self,ratio=1.0,N=6,delay:int=1): #argmax or argmin is possible to use
        if len(self.mom)-delay<N:    N=len(self.mom)-delay
        M= min (2*N,len(self.mom))
        recent_data_mom = self.mom[-1-M:]
        high_mom, low_mom,max_index_mom,min_index_mom=self.calculate_series_max_min( recent_data_mom,0,True)
        if max(self.mom[-37-1:-1-1])>1000 or min(self.mom[-37-1:-1-1])<-1000:
            ratio = max(ratio,1.5)
        elif max(self.mom[-37-1:-1-1])>800 or min(self.mom[-37-1:-1-1])<-800:
            ratio = max(ratio,1.2)
        recent_data = self.spx[-1-5*M-5:-1-5]
        high, low,max_index,min_index=self.calculate_series_max_min( recent_data,0,False)
        Const_adj = ratio * np.power(N/12, 1/2.4) #.382
        
        A=Const_adj*200*self.enlarge_3_min() #simon???????????????? 180 /200
        B=Const_adj*0.00205 * self.data_spx.close[0]
        C= self.mom[-1-1]-self.mom[-1-1-M]
        if max_index_mom - min_index_mom<-N and self.mom[-1-1]-self.mom[-1-1-M] <- A*self.symmetric_ratio_down \
            and self.mom[-1-1]-self.mom[-1-1-N]<-0.4*A*self.symmetric_ratio_down \
                and self.mom[-1-1-N]-self.mom[-1-1-M]<-0.4*A*self.symmetric_ratio_down and \
            self.position and self.entry_type0=="long" and high - low>B: 
            # if max_index_mom - min_index_mom>6
            print(f'exit up trend-2: @ {N,M,C,ratio},{self.current_time_NY},{self.symmetric_ratio_down, high - low,self.mom[-1]-self.mom[-1-N],self.mom[-1]-self.mom[-1-2*N]}')
            return self.close_cleanup(40.0)
        elif max_index_mom - min_index_mom>N and self.mom[-1-1]-self.mom[-1-1-M] > A*self.symmetric_ratio_up \
            and self.mom[-1-1]-self.mom[-1-1-N]>0.4*A*self.symmetric_ratio_up \
                and self.mom[-1-1-N]-self.mom[-1-1-M]>0.4*A*self.symmetric_ratio_up and \
            self.position and self.entry_type0=="short"  and high - low>B: #self.normal_up is False:
            print(f'exit down trend-2: @ {N,M,C,ratio},{self.current_time_NY},{self.symmetric_ratio_up,high - low,self.mom[-1]-self.mom[-1-N],self.mom[-1]-self.mom[-1-2*N]}')
            return self.close_cleanup(40.1)
        return
    
    def calculate_series_max_min(self, series_values: List[float],offset=0,is_mom=False) -> Tuple[float, float,float, float]: #argmax or argmin is possible to use
        if  offset<0: offset = 0
            # raise ValueError("offset must be greater than 0")
        offset = min(len(series_values),offset)
        L = min(len(series_values),len(self.data_spx.close))
        if is_mom: L= min(len(series_values),len(self.mom))
        if len(series_values) < offset:         L = offset
            # raise ValueError("List length must be greater than offset")
        sub_spx_values = series_values[:L-offset] #list(self.data_momentum.volume.get(size=A*2))[:-A]
        if len(sub_spx_values)>0:
            high = max(sub_spx_values)
            low = min(sub_spx_values)
            max_index = max(enumerate(sub_spx_values), key=lambda x: x[1])[0] # 获取最大值的索引
            min_index = min(enumerate(sub_spx_values), key=lambda x: x[1])[0] # 获取最小值的索引
            return high, low,max_index,min_index
        else:
            return self.data_spx.close[0], self.data_spx.close[0],0,0
    
    def close_cleanup(self,a=0):
        size_1 = 0  # is_close = False
        if self.position and not self.close_lock: 
            self.record_list.append(self.current_time_NY)
            self.record_list.append(self.sec_since_last_sig)
            self.record_list.append(self.first_sig)
            # self.record_list.append(self.max_sig)
            self.record_list.append(self.max_direction)
            # self.record_list.append(self.current_direction)
        
            if self.entry_type0=="long":
                print(f"extrm price :  {self.current_time_NY,self.sec_since_last_sig,(self.extreme_price0-self.entry_price),(self.spx[-1]-self.entry_price)}")
                self.record_list.append((self.extreme_price0-self.entry_price))
                self.record_list.append((self.spx[-1]-self.entry_price))

                # self.record_list.append(self.current_time_NY,self.sec_since_last_sig,(self.extreme_price0-self.entry_price),(self.spx[-1]-self.entry_price))
            elif self.entry_type0=="short":
                print(f"extrm price :  {self.current_time_NY,self.sec_since_last_sig,-(self.extreme_price0-self.entry_price),-(self.spx[-1]-self.entry_price)}")
                
                self.record_list.append(-(self.extreme_price0-self.entry_price))
                self.record_list.append(-(self.spx[-1]-self.entry_price))

            print(f"close + cleanup @ {self.current_time_NY,self.early_exit}, close No.={a}, trend lasting second = {self.sec_since_last_sig}")
            if     self.entry_type0=="long":  size_1 =  1
            elif  self.entry_type0 =="short": size_1 = -1
            self.close(data=self.data_spx,size=size_1) #possize = self.getposition(data, self.broker).size #size = abs(size if size is not None else possize)
            self.cleanup()
            self.close_lock=True
            
        return size_1 # is_close
        
    def cleanup(self):
        self.max_profit = 0
        self.curent_profit = 0
        self.slope_local = 0
        self.longer_wait = False
        self.sec_since_trade = 0
        self.stop_loss = None
        self.stop_loss_sec = 3600*3.5 if self.half_date() else 3600*6.5
        
        self.first_sig = 0
        self.max_sig = 0
        self.current_direction= 0
        self.max_direction=0
        
        ratio = 0.2
        
        if abs(self.max_sig_type)>=3:
            ratio=0.4
            if abs(self.max_sig_type)>3:
                ratio=0.5
                if abs(self.max_sig_type)>4:
                    ratio=0.6
        
        # self.rho.append(rho)
        if self.entry_price is not None and self.extreme_price0 is not None:
            self.trade_type.append(self.max_sig_type)
            if self.max_sig_type >0 :
                self.pnl.append(-(self.entry_price-self.spx[-1]))
                self.max_pnl.append(-(self.entry_price-self.extreme_price0))
            elif self.max_sig_type <0 :   
                self.pnl.append((self.entry_price-self.spx[-1]))
                self.max_pnl.append(self.entry_price-self.extreme_price0)
                    
            self.posi_ratio.append(ratio)

        self.max_sig_type= 0
        
        self.swap_price = None
        self.size = 0.0 
        self.entry_type0 = None  # long or short
        
        self.trend_start_time = None
        self.sec_since_trend=0

        self.mom_up = False
        self.mom_down = False
        
        self.sig_time= None 
 
        self.sig_time_sec=None
        self.sig_type_sec=None  
        
        self.entry_mom = None
        
        self.big_up, self.big_down, self.normal_up, self.normal_down, self.consistency_up, self.consistency_down=False,False,False,False,False,False
        self.normal_up_10am, self.normal_down_10am = False,False # to finish
        self.stop_loss_price_worst = None
        self.second_wave = False #+self.buy_count<=1:
        self.spx_price_second_wave = None  # long or short    
        self.ref_time=None  # ???? Siomn for, not used
        
        self.sec_since_last_sig=0
        self.extreme_price_H = None
        self.extreme_price_L = None
        
        self.extreme_price0 = None
        self.extreme_mom0 = None
        
        self.ref_mom0=None
        self.ref_price0=None

        self.entry_rho,self.extreme_rho0,self.ref_rho0=0,0,0

        self.my_entry_time = None
        self.entry_time = None
        self.entry_time0 = None #?????
        
        self.early_exit = False # 如果反弹超过62% 则用
        self.early_exit_mom = False # 如果反弹超过38-40% 则用

        self.entry_price = None
           
    def range_N(self,N=6,delay=1,M=48):
        M=min(M,len(self.mom)-delay)
        if M<N:
            return 0, 0
        else:
            max_value,min_value=0,0
            max_index ,min_index = None,None
            for i in range(M-N):
                D_0 = self.mom[-i-1-delay]-self.mom[-i-N-1-delay]
                if D_0 > max_value: 
                    max_value=D_0
                    max_index = i
                if D_0 < min_value:
                    min_value=D_0
                    min_index = i
            return     max_value,min_value,max_index,min_index

    def set_max4_min4_value(self):
        A1,A2,A3,A4,A5,A6,A7,A8,A9=0,0,0,0,0,0,0,0,0
        N = len(self.mom)
        if N>=4:
            A1=self.mom[-1]-self.mom[-2]
            A2=self.mom[-1]-self.mom[-3]
            A3=self.mom[-1]-self.mom[-4]
            self.current_max3 =max(A1,A2,A3)
            self.current_min3 =min(A1,A2,A3)  #(self.d_mom[-1],self.d_mom[-1]+self.d_mom[-2],self.d_mom[-1]+self.d_mom[-2]+self.d_mom[-3])
        if N>=5:
            A4=self.mom[-1]-self.mom[-5]
            self.current_max4 =max(A1,A2,A3,A4)
            self.current_min4 =min(A1,A2,A3,A4)
        if N>=6:
            A5=self.mom[-1]-self.mom[-6]
            self.current_max5 =max(A1,A2,A3,A4,A5)
            self.current_min5 =min(A1,A2,A3,A4,A5)
        if N>=7:
            A6=self.mom[-1]-self.mom[-7]
            self.current_max6 =max(A1,A2,A3,A4,A5,A6)
            self.current_min6 =min(A1,A2,A3,A4,A5,A6)

        if N>=13:
            A7=self.mom[-1]-self.mom[-8]
            A8=self.mom[-1]-self.mom[-9]
            A9=self.mom[-1]-self.mom[-10]
            A10=self.mom[-1]-self.mom[-11]
            A11=self.mom[-1]-self.mom[-12]
            A12=self.mom[-1]-self.mom[-13]
            self.current_max12 =max(A1,A2,A3,A4,A5,A6,A7,A8,A9,A10,A11,A12)
            self.current_min12 =min(A1,A2,A3,A4,A5,A6,A7,A8,A9,A10,A11,A12)
        return self.current_max4, self.current_min4,self.current_max6, self.current_min6
    
    def mkt_close(self):         # 在市场收盘时平仓
        if self.is_market_close_bar():
            self.day_count =self.day_count +1
            pnl_1 = pd.Series(self.pnl)
            pnl_2 = pd.Series(self.trade_type)
            pnl_3 = pd.Series(self.max_pnl)
            pnl_4 = pd.Series(self.trade_start) 
            pnl_5 = pd.Series(self.trade_end) 
            # pnl_all = pd.Series(pnl_1,pnl_2,pnl_3) #pnl_all = pd.Series(pnl_1,pnl_2,pnl_3,pnl_4)
            pnl_all =pd.Series(self.record_list)
            
            if len(self.pnl)>0:
                pnl_all.to_csv("pnl recrod list till."+self.current_time_NY.strftime('%Y-%m-%d') + ".csv")

            if self.position:
                print(self.max_sig_type)
                print(f'mkt close, {self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                return self.close_cleanup()  #实盘 可以不close  交易所可以自动交割； 但是需要cleanup 清除信号
            
            # self.pnl.to_csv("pnl."+start_date.strftime('%Y-%m-%d')+"_to_"+end_date.strftime('%Y-%m-%d') + ".csv")
        return
    
    def set_ratio_2(self): #not used here
        N_1=len(self.mom)
        if self.fed_news_reset_mom_before_2pm():  
            self.close_cleanup()
            
        if len(self.mom)<=30:
            temp1 = np.average(self.mom)
            temp2 = np.average(self.mom)
        else:
            temp1 = np.average(self.mom[-30:-5])    
            temp2 = max(self.mom[:-6])-min(self.mom[:-6])

        temp1 = max(temp2/601, 1)  #601
        ratio_up= np.power(temp1,1/2.4) # simon ????????????
        self.symmetric_ratio_up = ratio_up
        ratio_down = ratio_up
        self.symmetric_ratio_down =self.symmetric_ratio_up
        return ratio_up,ratio_down
    
    def mom_rebounce(self): # assume rest ref in big signal， 以后用，暂时没有 not yet used
        if self.position and self.extreme_mom0 is not None and self.ref_mom0 is not None:
            if 0.382 +0.008<(self.mom[-1]-self.ref_mom0)/(self.extreme_mom0-self.ref_mom0):
                self.early_exit_mom = True

    def setup_ref_extreme(self,is_buy:bool): #????????? simon sig_time issue????
            interval=200
            size_N= min(len(self.data_spx.close),interval)  # 3 or 4 mins ?????simon
            size_M=min(int(size_N/5),len(self.mom))
            
            spx_high_N, spx_low_N, max_index,min_index = self.calculate_series_max_min(self.spx[-1-size_N:])
            mom_high_N, mom_low_N, max_index_mom,min_index_mom = self.calculate_series_max_min(self.mom[-1-size_M:])
            
            if self.ref_price0 is None: 
                self.ref_price0 = spx_low_N if is_buy else spx_high_N

            if (self.ir_date() and self.current_time_NY.time()>time(14,0,0)) or (self.current_time_NY.time()>time(10,0,0) and self.current_time_NY.time()<time(10,2,0)):
                interval=150
            R_all       = self.R_all 
            R_30_min    = self.R_30_min
            R_3_min     = self.R_3_min
            R_1_min     = self.R_1_min
            if (R_all>10 and R_30_min>8) or R_3_min>15 or R_1_min>20:           
                interval=120
            
            if self.ref_mom0 is None:
                self.ref_mom0 = mom_low_N if is_buy else mom_high_N
            if self.extreme_price0 is None or self.extreme_mom0 is None :# or self.position: #simon ??????
                self.extreme_price0 = spx_high_N  if is_buy else spx_low_N # self.data_spx.close[0]
                self.extreme_mom0 = mom_high_N if is_buy else mom_low_N   # self.mom[-1]
            else:
                self.extreme_price0 = max(self.extreme_price0, self.data_spx.close[0]) if is_buy else min(self.extreme_price0, self.data_spx.close[0]) 
                self.extreme_mom0 = max(self.extreme_mom0, self.mom[-1]) if is_buy else min(self.extreme_mom0, self.mom[-1]) #open = mom
    def enlarge_3_min(self): # 3pm?????
        real_current_time_NY=self.current_time_NY.time()
        a=1.0
        if real_current_time_NY>time(14,0,0) and real_current_time_NY<time(15,10,55) and self.ir_date(): a =1.35
        elif real_current_time_NY>time(9,30,0) and real_current_time_NY<time(9,35,5): a =1.2
        elif real_current_time_NY>time(10,0,20) and real_current_time_NY<time(10,0,55): a =1.2
        elif real_current_time_NY>time(15,30,0) and real_current_time_NY<time(16,0,0): a =1.12
        elif real_current_time_NY>time(14,59,0) and real_current_time_NY<=time(15,1,5): a =1.12
        elif real_current_time_NY>=time(13,59,0) and real_current_time_NY<=time(14,1,5) and (not self.is_ir_date): a =1.12
        return a
    
    def stop_loss_6_min(self,ratio=1,delay:int=5):
        if self.sec_since_last_sig>420:
            if self.position:
                A=4.0 if ratio<1.5 else 4.4 #1.5  or 0.1
                recent_data_all=list(self.data_spx.close.get(size=185))
                avg_px=(self.spx[-1]+self.spx[-1-1])/2            # abs_value = abs(self.ref_ price0-self.entry_price) #??????simon
                if self.ratio_confirm(0.45,0.6):
                    if self.entry_type0=="long" and self.spx[-1]<min(self.spx[-31:-6]) and self.entry_price-A>avg_px and not(self.spx[-1]-min(recent_data_all)>5.4): #simon ????5 or 3-4
                        return self.close_cleanup(36.0)
                    if self.entry_type0=="short" and self.spx[-1]>max(self.spx[-31:-6]) and self.entry_price+A<avg_px and not(max(recent_data_all)-self.spx[-1]>5.4) \
                        and True: #self.ref_pri ce0-self.data_spx[0]<(self.ref_p rice0-self.entry_price)
                        return self.close_cleanup(36.1)
    def ratio_confirm(self,A=0.36,B=0.5,C=0.36,D=0.5,delay1:int=1,delay2:int=5): # 0.382 or 0.42
        Sec_Start=420  # 300-400
        spx_ratio = min(A+(self.sec_since_last_sig-Sec_Start)/60*0.01, A*1.001) if self.sec_since_last_sig>Sec_Start else A
        mom_ratio = min(B+(self.sec_since_last_sig-Sec_Start)/60*0.01, B*1.001) if self.sec_since_last_sig>Sec_Start else B
        result = False  #true = extra condition of entry price
        if self.ref_mom0 is not None:    
            Ratio_mom_ref = (self.mom[-1-1] - self.ref_mom0)/                         (self.extreme_mom0 - self.ref_mom0)
            Ratio_spx_ref=     (self.spx[-1-5] - self.ref_price0)/          (self.extreme_price0 - self.ref_price0)
            Ratio_spx_entry_0= (self.extreme_price0    - self.spx[-1-5])/   (self.extreme_price0 - self.ref_price0)
            Ratio_spx_entry_1= (self.entry_price       - self.ref_price0 )/         (self.extreme_price0 - self.ref_price0)
            Ratio_spx_entry_2= (self.spx[-1-5] - self.entry_price)/         (self.extreme_price0 - self.ref_price0)
        
            A_0 = (self.spx[-1-5] - self.entry_price) if self.entry_type0 =="long" else (self.entry_price - self.spx[-1-5]) # stop loss+ add todo
            B_0 = (self.extreme_price0-self.ref_price0) if self.entry_type0 =="long" else -(self.extreme_price0-self.ref_price0) # stop loss+ add todo
            # ?????simon wait????
            abs_value = abs(self.ref_price0-self.entry_price)
        
            if A_0<self.ref_price0*0.004 and A_0<0.5*B_0: #and A_0<self.ref_price0*0.00325  ???????simon and A_0<0.382*B_0
                if Ratio_spx_ref<spx_ratio and Ratio_mom_ref<mom_ratio  and True: #and Ratio_spx_entry_0>min(0.618,A+0.1) and A_0 # self.ref_price0-self.data_spx[0]<(self.ref_price0-self.entry_price)
                    result=True
                elif Ratio_spx_ref<0.45 and (self.spx[-1-5]-self.entry_price)/(self.extreme_price0-self.ref_price0)<-0.25 and A_0<-self.ref_price0*0.00125:
                    result=True
        return result # (self.ref_price0 - self.data_spx.close[0])/(self.ref_price0 - self.extreme_price0)<spx_ratio and (self.ref_mom0 - self.mom[-1])/(self.ref_mom0 - self.extreme_mom0) <mom_ratio 
    def stop_loss_ratio_ref(self,R=0.42): # 0.382 or 0.42 #0.175 # 对错的 stoploss 出场的处理   to fix upgrade
        if self.sec_since_last_sig>260 and self.position and self.ref_price0 is not None and self.extreme_price0 is not None : 
            if self.ratio_confirm(): #abs(self.data_spx.close[0]-self.ref_price0)< R * abs(self.extreme_price0 - self.ref_price0):
                print (f"stop_loss_ref,  ratio = {self.current_time_NY,R,(self.spx[-6]-self.ref_price0)/(self.extreme_price0 - self.ref_price0)}")
                if self.entry_type0=="short" and self.spx[-1]>max(self.spx[-31:-6]):
                    return self.close_cleanup(36.1) #simon???
                elif self.entry_type0=="long" and self.spx[-1]<min(self.spx[-31:-6]):
                    return self.close_cleanup(36.2) #simon???
    
    def stop_loss_abs_small(self,R=0.42): # 0.382 or 0.42 #0.175 # 对错的 stoploss 出场的处理   to fix upgrade
        if self.position and self.ref_price0 is not None and self.extreme_price0 is not None : 
            # range = abs(self.extreme_price0 - self.ref_price0)
            if (abs(self.max_direction)==2 and self.sec_since_last_sig>260) : #abs(self.data_spx.close[0]-self.ref_price0)< R * abs(self.extreme_price0 - self.ref_price0):
                stop_level_1 = 0.00138*self.spx[-1]
                stop_level_2 = abs(self.ref_price0-self.extreme_price0)*0.382 # 0.5
                stop_level = stop_level_1 /2 + stop_level_2/2
                
                if self.entry_type0=="short" and self.spx[-1]>max(self.spx[-31:-6]):
                    return self.close_cleanup(32.1) #simon???
                elif self.entry_type0=="long" and self.spx[-1]<min(self.spx[-31:-6]):
                    return self.close_cleanup(32.2) #simon???

    def profit_taken_ratio_exit(self, threshold=0.3,delay:int = 5): # 0.382  0.45   0.478 consecutive 2 sec two seconds
        current_time = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        if (time(15, 10, 5) < current_time <= time(15, 58, 45)): threshold = 0.45
        a1 = 181 # simon ??????  180/210/225/ 240??
        if   self.fed_news_after_2pm_a():            
            a1=76
            threshold = 0.618
        elif self.fed_news_after_2pm_b():            
            a1=121
            threshold = 0.45
        elif self.fed_news_after_230pm_c():            
            a1=151
            threshold = 0.525
        elif self.fed_news_after_3pm_d():            
            a1=151

        if self.sec_since_last_sig> a1 and self.position and self.ref_price0 is not None and self.extreme_price0 is not None: #  self.position_taken:
            A, B,  N, N2= 1.5*threshold, 1.0250, 58,16  
            A=0.0
            N = min(N,len(self.data_spx.close))
            L_sec= 60*3 + N + N2
            if self.sec_since_last_sig > 60*3 + N + N2:  
                N_max_10=min(9*60+1,self.sec_since_last_sig+15)
                recent_data_ten_min=list(self.data_spx.close.get(size=N_max_10))
                recent_data_ten_minus2=recent_data_ten_min[:N_max_10-24]

                N_max_7=min(7*60+5,self.sec_since_last_sig+15)
                
                recent_data_five_minus2=recent_data_ten_min[:N_max_7-24]
                high5, low5,max_index5,min_index5    =self.calculate_series_max_min(recent_data_five_minus2,offset=0,is_mom=False)
            threshold = 0.25 # as function
            recent_data=list(self.data_spx.close.get(size=N))
            min_index = min(enumerate(recent_data), key=lambda x: x[1])[0] # 获取最小值的索引
            max_index = max(enumerate(recent_data), key=lambda x: x[1])[0] # 获取最大值的索引
            D=(self.ref_price0 - self.spx[-1-5])/(self.ref_price0 - self.extreme_price0)             
            
            C= self.spx[-1]*0.001 # 4.20 simon ??????
            if self.ratio_confirm() \
                and abs(self.entry_price - self.extreme_price0)>C \
                    and self.sec_since_last_sig > 60*4 + N + N2\
                        and abs(self.spx[-1] - self.extreme_price0)>self.spx[-1]*0.00135 \
                            and abs(self.ref_price0 - self.extreme_price0)>self.spx[-1]*0.0035 \
                                and abs(self.rho[-1] - self.extreme_rho0)>0.4*self.c_0 \
                                    and abs(self.rho[-1] - self.extreme_rho0)/abs(self.rho[-1] - self.ref_rho0)>0.5 \
                                        and abs(self.ref_mom0-self.mom[-1])<0.8*abs(self.ref_mom0-self.extreme_mom0): 
                ABC=-1.35
                if self.entry_type0=="long":
                    if  self.spx[-1] -recent_data[min_index] <B and \
                        -(self.entry_price - self.spx[-1-5]) +A<-threshold*(self.entry_price - self.extreme_price0) and \
                        -(self.entry_price - self.spx[-1-1-5])+A<-threshold*(self.entry_price - self.extreme_price0) \
                            and abs(self.ref_price0-self.spx[-1-5])<0.48*abs(self.ref_price0-self.extreme_price0) and \
                                 abs(self.ref_mom0-self.mom[-1-1])<0.8*abs(self.ref_mom0-self.extreme_mom0) \
                                    and self.spx[-1]<min(self.spx[-31:-6]):# two points stop loss \
                        if self.sec_since_last_sig > 60*3 + N + N2:                           # if self.data_spx.close[0]>recent_data[max_index]-1.0250:    
                            return self.close_cleanup(30.0)                            # return 1
                        elif self.sec_since_last_sig > 60*3 and self.sec_since_last_sig<= 60*3 + N + N2 and max_index < min_index: # and self.data_spx.close[0]>recent_data[max_index]-1.025: # and or  simon ????
                            return self.close_cleanup(30.1)                            # return 1
                    elif self.sec_since_last_sig>60*3 + N + N2 and self.data_spx.close[0]<low5+ABC: 
                        return self.close_cleanup(30.5)
                if self.entry_type0=="short": # 4.20 ???? simon?????? # b simon ?????????
                    if  recent_data[max_index]-self.spx[-1] <B and \
                        (self.entry_price - self.spx[-1-5])+A<threshold*(self.entry_price - self.extreme_price0) and \
                         (self.entry_price - self.spx[-1-1-5])+A<threshold*(self.entry_price - self.extreme_price0)  \
                            and abs(self.ref_price0-self.spx[-1-5])<0.48*abs(self.ref_price0-self.extreme_price0) and \
                                 abs(self.ref_mom0-self.mom[-1-1])<0.8*abs(self.ref_mom0-self.extreme_mom0) \
                                    and self.spx[-1]>max(self.spx[-31:-6]):# two points stop loss \
                        if self.sec_since_last_sig > 60*3 + N + N2:                           # if self.data_spx.close[0]>recent_data[max_index]-1.0250:    
                            return self.close_cleanup(30.2)                            # return -1
                        elif self.sec_since_last_sig > 60*3 and self.sec_since_last_sig<= 60*3 + N + N2 and max_index > min_index: # and self.data_spx.close[0]>recent_data[max_index]-1.025: # and or  simon ????
                            return self.close_cleanup(30.3)                            # return -1
                    elif self.sec_since_last_sig>60*3 + N + N2 and self.data_spx.close[0]>high5-ABC: 
                        return self.close_cleanup(30.6)
            return 0
        
    def close_check_by_opposite_sig(self,revesre_threshold=140.5): # self.normal_up = True  # up down不用交叉  平仓  #错止损的纠正 todo
        pos_size = 0  #simon???????????? delay and 140.4 with wait or 200 immediately, not complete yet by simon
        A = 0.85# 0.78 - 0.9
        if self.position:
            if self.ref_price0 is not None:
                profit_0 = self.data_spx[0]-self.ref_price0 if self.entry_type0=="long" else -(self.data_spx[0]-self.ref_price0)
                profit_1 = self.data_spx[0]-self.entry_price if self.entry_type0=="long" else -(self.data_spx[0]-self.entry_price)
            if self.sec_since_last_sig>60*10:
                if profit_0 > 50:  
                    revesre_threshold= 225
                elif profit_0 > 40:  
                    revesre_threshold= 204
                elif profit_0 > 30:  
                    revesre_threshold= 183
                elif profit_0 > 20:  
                    revesre_threshold= 162
            if self.entry_type0 == 'long' and self.current_min4<-revesre_threshold*np.power(self.symmetric_ratio_down,A): 
                # p rint(f'c5 closed by down 反向 sig, min4 =:')
                # p rint(self.current_time_NY,self.current_min4,-revesre_threshold*np.power(self.symmetric_ratio_down,A),revesre_threshold,self.max_mom,\
                #       self.min_mom,self.current_max4,self.symmetric_ratio_down,self.symmetric_ratio_up)                # pos_size = 1
                return self.close_cleanup(0.15)
            elif self.entry_type0 == 'short' and self.current_max4>revesre_threshold*np.power(self.symmetric_ratio_up,A):
                # p rint(f'c5.1 closed by up 反向 sig,  max4 = {self.current_max4,revesre_threshold*np.power(self.symmetric_ratio_up,A),self.symmetric_ratio_up,self.stop_loss_price,self.ref _price0,self.extreme_price0,self.ref_p rice0,self.symmetric_ratio_up,self.current_min4},max4 = {self.current_max4}, ratio_down = {self.symmetric_ratio_down},ratio_up = {self.symmetric_ratio_up}')
                # pos_size = -1
                return self.close_cleanup(1.0100)
        else:
            return 0 # pos_size
    def set_early_exit(self,threshold=100): # not fully used yet, sqrt ratio  #self.current_min3<-threshold*1 or
        if (self.entry_type0=="long" and self.current_min4<-threshold*np.power(self.symmetric_ratio_down,0.5)) or (self.entry_type0=="short" and self.current_max4> threshold*np.power(self.symmetric_ratio_up,0.5)):
            self.early_exit = True

    def rho_exit_with_mom_price_confirm(self,ratio=1.0,threshold=0.5,delay :int=0): # sqrt ratio 
        time1=self.current_time_NY.time()
        S_0=self.ir_date() and time1>time(14,0,0) and time1<time(14,2,0)
        diff_spx=0.0012*self.spx[-1]
        
        if self.ref_price0 is not None and self.extreme_mom0 is not None:
            diff_spx=max(0.0012*self.spx[-1],0.382*abs(self.ref_price0-self.extreme_mom0)) # 0.382 to be tested

        R_0=1.62 if S_0 else 1.0
        if self.ref_price0 is not None and self.extreme_price0 is not None:
            if abs(self.ref_price0-self.extreme_price0)>0.0162*self.spx[-1]:
                R_0 = R_0*1.2
            
        pos_size = 0
        if self.position and self.sec_since_last_sig>301: # no delay since rho is with delay 15s already
            A_rho = abs(self.rho[-1]-self.ref_rho0)/abs(self.extreme_rho0-self.ref_rho0) if (self.extreme_rho0!=self.ref_rho0) else 1
            spx_high, spx_low, max_index,min_index= self.calculate_series_max_min(list(self.data_spx.close.get(size=61)))
            if self.sec_since_last_sig>301 and abs(self.rho[-1]-self.ref_rho0) < threshold*abs(self.extreme_rho0-self.ref_rho0) \
                and abs(self.mom[-1]-self.ref_mom0)<max(0.5,min(threshold+0.1,0.618*1.1))*abs(self.extreme_mom0-self.ref_mom0)\
                    and abs(self.spx[-1]-self.ref_price0)<max(0.5,min(threshold+0.1,0.618))*abs(self.extreme_price0-self.ref_price0):
                print(f'rho exit: {self.current_time_NY},{self.rho[-1],self.ref_rho0,self.extreme_rho0,A_rho}')
                
                if self.spx[-1]<min(self.spx[-31:-6]) and self.entry_type0=="long" and self.spx[-1]-spx_high<-R_0*diff_spx :
                # and (self.rho[-1]-min(self.rho[-5:-1])/np.power(np.average(self.rho[-5:-1]/12,0.5)>R_0*threshold and \
                #          self.rho[-1]-min(self.rho[-5:-1] >Range_rho *0.382: # simon????????????
                    pos_size = 1
                    print(f'long posi rho exit not used : {self.current_time_NY},{ratio,self.current_min4,self.current_max4,self.rho[-1],self.ref_rho0,self.extreme_rho0,A_rho}')
                    return self.close_cleanup(81.12)  # self.spx[-1]>max(self.spx[-31:-6]):
                elif self.spx[-1]> max(self.spx[-31:-6]) and self.entry_type0=="short" and self.spx[-1]-spx_low> R_0*diff_spx:
                    # and (max(self.rho[-5:-1]-self.rho[-1])/np.power(np.average(self.rho[-5:-1]/12,0.5)>R_0*threshold and \
                    #      max(self.rho[-5:-1]-self.rho[-1] >Range_rho *0.382: # simon????????????
                    pos_size = -1
                    print(f'short posi rho exit not used : {self.current_time_NY},{ratio,self.current_min4,self.current_max4,self.rho[-1],self.ref_rho0,self.extreme_rho0,A_rho,self.spx[-1],spx_low,self.spx[-1]-spx_low}')
                    return self.close_cleanup(81.11)
        else:
            return 0 # pos_size         

    def d_rho_one_min(self,threshold=0.25): # sqrt ratio 
        # time1=self.current_time_NY.time()
        # S_0=self.ir_date() and time1>time(14,0,0) and time1<time(14,2,0)
        # R_0=1.62 if S_0 else 1.0 
        d_rho_up   = - (self.rho[-1]-max(self.rho[-5-12:-1]))/np.power(np.average(self.rho[-9:-3])/12,0.5)
        d_rho_down =   (self.rho[-1]-min(self.rho[-5-12:-1]))/np.power(np.average(self.rho[-9:-3])/12,0.5)
        return d_rho_up, d_rho_down
    def max_min_reverse_exit(self,threshold=140): # sqrt ratio , no delay or waiting time yet, 2nd version of this, partially duplicated
        time1=self.current_time_NY.time()
        
        S_0=self.ir_date() and time1>time(14,0,0) and time1<time(14,2,0)
        diff_spx=0.0012*self.spx[-1]
        R_0=1.62 if S_0 else 1.0
        
        if self.ref_price0 is not None and self.extreme_price0 is not None:
            if abs(self.ref_price0-self.extreme_price0)>0.0162*self.spx[-1]:
                R_0 = R_0*1.2
        pos_size = 0
        # if self.entry_type0=="short" and self.current_max4>145: 
        
        if self.position:
            # if self.entry_type0=="short"  \
            #     and self.current_max4> 140*np.power(self.symmetric_ratio_up,0.8): #self.current_max3>threshold*1 or
        
            spx_high, spx_low, max_index,min_index= self.calculate_series_max_min(list(self.data_spx.close.get(size=61)))
            if self.entry_type0=="long" and self.spx[-1]-spx_high<-R_0*diff_spx   \
                and self.current_min4<-R_0*threshold*np.power(self.symmetric_ratio_down,0.5): #self.current_min3<-threshold*1 or
                # p rint(self.data_spx.close[0],max(self.data_spx.close[-20:]),R_0*diff_spx)
                # prin t(f'Long position reverse exit by min 4, {self.symmetric_ratio_down,self.current_min4,self.current_min4,self.current_min5,self.current_min6,self.sig_time,self.sec_since_last_sig,self.entry_price,self .ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                pos_size = 1
                return self.close_cleanup(88.12)
            # self.spx[-1]-(self.spx[-61:-6])> R_0*diff_spx   \
            # and self.spx[-1]-spx_low> R_0*diff_spx  
            elif self.entry_type0=="short"  \
                and self.current_max4> R_0*threshold*np.power(self.symmetric_ratio_up,0.5): #self.current_max3>threshold*1 or
                print(f'Short position reverse exit by max 4, {self.symmetric_ratio_down,R_0*threshold*np.power(self.symmetric_ratio_down,0.5),self.current_max4,R_0,self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig} {self.spx[-1],spx_low, R_0*diff_spx  }')
                pos_size = -1
                return self.close_cleanup(89.12)
        else:
            return 0 # pos_size         
    def trend_3_min_exit(self,adj_ratio=1.0,delay:int=5):
        if self.position:
            Length_mom=len(self.mom)-1
            if Length_mom >36:
                A_75 = (75-0.15)*adj_ratio   *self.enlarge_3_min()*self.symmetric_ratio_down
                if (self.entry_type0=="long") and self.spx[-1]<min(self.spx[-31:-6]) and \
                    self.mom[-1-1]-self.mom[-1-1-18]    <-A_75 and\
                    self.mom[-1-1-18]-self.mom[-1-1-36] <-A_75: # 140 or 150-180    60-90
                        # p rint(self.current_time_NY,self.mom[-1]-self.mom[-1-18],self.mom[-1-18]-self.mom[-1-36])
                        if self.spx[-1]<min(self.spx[-31:-6]):
                            return self.close_cleanup(50.03) # only one close
                elif (self.entry_type0=="short") and self.spx[-1]>max(self.spx[-31:-6]) and \
                    self.mom[-1-1]-self.mom[-1-1-18]    > A_75 and\
                    self.mom[-1-1-18]-self.mom[-1-1-36] > A_75: # 140 or 150-180    60-90
                        # p rint(self.current_time_NY,self.mom[-1]-self.mom[-1-18],self.mom[-1-18]-self.mom[-1-36])
                        # prin t(self.current_time_NY,adj_ratio)
                        if self.spx[-1]>max(self.spx[-31:-6]):
                            return self.close_cleanup(50.4) # only one close
    def profit_max_current_sec(self,delay:int=5): # not yet used
        max_profit, current_profit, sec_since_max_profit  = 0,0,0
        if self.position:
            spx_high, spx_low, max_index,min_index= self.calculate_series_max_min(list(self.data_spx.close.get(size=self.sec_since_last_sig)))
            A_0=self.extreme_price0-self.ref_price0 if self.extreme_price0 is not None and self.ref_price0 is not None else 0
            ratio_1=0.35  #0.382 #??????????simon
            if self.sec_since_last_sig<=361:
                if   abs(A_0)<=12:                    ratio_1=0.25
                elif abs(A_0)<=13:                    ratio_1=0.26
                elif abs(A_0)<=14:                    ratio_1=0.27
                elif abs(A_0)<=15:                    ratio_1=0.28
                elif abs(A_0)<=16:                    ratio_1=0.29
                elif abs(A_0)<=17:                    ratio_1=0.3
                elif abs(A_0)<=18:                    ratio_1=0.31
                elif abs(A_0)<=19:                    ratio_1=0.32
                elif abs(A_0)<=20:                    ratio_1=0.33
                elif abs(A_0)<=21:                    ratio_1=0.34
            if self.current_time_NY.time()>time(10,0,5) and self.current_time_NY.time()<time(10,3,5):
                ratio_1 = 0.28
            min_period_in_sec = 301 # or 181    
            if self.extreme_price0 is not None and self.ref_price0 is not None\
                  and self.sec_since_last_sig>min_period_in_sec: 
                if abs(self.entry_price - self.extreme_price0)>self.spx[-1]*0.001 \
                    and abs(self.spx[-1] - self.extreme_price0)>self.spx[-1]*0.00135 \
                        and abs(self.ref_price0 - self.extreme_price0)>self.spx[-1]*0.0035\
                            and abs(self.rho[-1] - self.extreme_rho0)>0.4*self.c_0 \
                                and abs(self.rho[-1] - self.extreme_rho0)/abs(self.rho[-1] - self.ref_rho0)>0.5 \
                                    and abs(self.ref_mom0-self.mom[-1])<0.8*abs(self.ref_mom0-self.extreme_mom0):
                                    # abs(self.mom[-1] - self.extreme_mom0)/abs(self.mom[-1] - self.ref_mom0)>0.2 and \
                                    # 5 min? 15 range?# last three conditions is to be tested, second last [-2]
#####################
                # and abs(self.entry_price - self.extreme_price0)>C \
                #     and self.sec_since_last_sig > 60*4 + N + N2\
                #         and abs(self.spx[-1] - self.extreme_price0)>self.spx[-1]*0.00135 \
                #             and abs(self.ref_price0 - self.extreme_price0)>self.spx[-1]*0.0035 \
                #                 and abs(self.rho[-1] - self.extreme_rho0)>0.4*self.c_0 \
                #                     and abs(self.rho[-1] - self.extreme_rho0)/abs(self.rho[-1] - self.ref_rho0)>0.5 \
                #                         and abs(self.ref_mom0-self.mom[-1])<0.8*abs(self.ref_mom0-self.extreme_mom0): 
##########################

                    if self.entry_type0=="long":  # 10am or sec short???simon?
                        max_profit, current_profit, sec_since_max_profit = spx_high-self.entry_price,(self.data_spx.close[0]-self.entry_price),self.sec_since_last_sig-max_index-1    
                        if self.spx[-1-5]-self.ref_price0<ratio_1*A_0  and self.spx[-1]<min(self.spx[-61:-1-5]):
                            # pr int(self.data_spx.close[0],self. ref_price0,self.extreme_price0,ratio_1,A_0,self.spx[-1-5]-self.ref_price0)
                            self.close_cleanup(27.11)
                    elif self.entry_type0=="short":
                        max_profit, current_profit, sec_since_max_profit = self.entry_price-spx_low,-(self.data_spx.close[0]-self.entry_price),self.sec_since_last_sig-min_index-1    
                        if self.spx[-1-5]-self.ref_price0>ratio_1*A_0 and self.spx[-1]>max(self.spx[-61:-1-5]):
                            # pr int(self.data_spx.close[0],self.re f_price0,self.extreme_price0,ratio_1,A_0)
                            self.close_cleanup(27.22)
            if self.ref_price0 is not None and self.position:
                if current_profit<-self.ref_price0*0.0013:
                    # print(current_profit, current_profit/self.ref_price0)
                    self.close_cleanup(27.51)
        return max_profit, current_profit, sec_since_max_profit
    def rebounce_ratio_from_ref_exit(self, spx_ratio_threshold=0.6,delay1:int=1,delay2:int=5):
        # ir date() special
        if self.fed_news_after_2pm_a():  spx_ratio_threshold=0.5
        pos_size = 0
        mom_ratio_threshold=min(spx_ratio_threshold*1.33,0.9)
        if self.is_ir_date and self.ref_price0 is not None: 
            spx_ratio_threshold = spx_ratio_threshold *0.9
            mom_ratio_threshold= mom_ratio_threshold * 0.9
        # <=60*3+N+16  trend confirmation simon ?????????????    
        # if self.position and self.sec_since_last_sig>180: #120 seconds, # and recent trend confirm for exit simon
            ratio_spx=(self.spx[-1-5]-self.ref_price0)/(self.extreme_price0-self.ref_price0)
            ratio_mom=(self.mom[-1-1]-self.ref_mom0)/(self.extreme_mom0-self.ref_mom0)
            extra_seconds = 15 if self.fed_news_after_2pm_a() else 0
            if self.sec_since_last_sig>181+extra_seconds and ratio_spx<spx_ratio_threshold and ratio_mom<mom_ratio_threshold: #self.current_min3<-threshold*1 or
                if self.entry_type0=="long" and self.spx[-1]<min(self.spx[-31:-6]): #self.current_min3<-threshold*1 or
                    # pr int(f'long posi reverse exit by ratio, {ratio_spx,ratio_mom,self.symmetric_ratio_down,self.current_min3,self.current_min4,self.current_min5,self.current_min6,self.sig_time,self.sec_since_last_sig,self.entry_price,self .ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                    pos_size = 1
                elif self.entry_type0=="short" and self.spx[-1]>max(self.spx[-31:-6]): #self.current_max3>threshold*1 or
                    # print(f'short posi reverse exit by ratio, {ratio_spx,ratio_mom,self.sig_time,self.sec_since_last_sig,self.entry_price,self. ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                    pos_size = -1
                return self.close_cleanup(25.1) # only one close
        return 0 # pos_size     
        
    # def stop_loss_ratio(self,a=0.5,sec_waiting=150): # not used
    #     if self.position and self.stop_loss_price is not None: 
    #         if self.position and self.entry_type0=="long" and self.sec_since_last_sig>0 >sec_waiting:
    #             temp = self.entry_price*0.5+ self.ref_price0*0.5
    #             ratio=(self.data_spx.close[0]-self.stop_loss_price) / (self.extreme_price0-self.stop_loss_price)
    #             if ratio>a: 
    #                 pr int(f'stop loss by a=1, {self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref _price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
    #                 return self.close_cleanup(20)
    #     else:
    #         return 0
    def stop_loss_ref_entry(self, delay :int = 5, offset=1.25): # ,sec_waiting=120 first 120 seconds only stop loss, consecutive two points
        pos_size=0
        if self.entry_price is not None and self.ref_price0 is not None:
            A_0 = (self.spx[-1-5] - self.entry_price) if self.entry_type0 =="long" else (self.entry_price - self.spx[-1-5]) # stop loss+ add todo
            # B_0 = (self.extreme_price0-self.ref_price0) if self.entry_type0 =="long" else -(self.extreme_price0-self.ref_price0) # stop loss+ add todo
            if (self.entry_type0 =="long" and self.spx[-1]<min(self.spx[-16:-1-5])) or (self.entry_type0 =="short" and self.spx[-1]>max(self.spx[-16:-1-5])):
                B_1 = True  # delay = 5
            else:
                B_1 = False
            # Pct_max_loss=0.001
            if B_1 and A_0<self.ref_price0*0.00325 and \
                    abs(self.extreme_mom0 - self.mom[-1])>0.255*abs(self.extreme_mom0 - self.ref_mom0): #and A_0<self.ref_price0*0.00325
                if (self.spx[-1-5] - self.entry_price)/(self.extreme_price0-self.ref_price0)<-0.2 and A_0<-self.ref_price0*0.00105:
                    if self.position and self.stop_loss_price_worst is not None: 
                        if self.entry_type0 == 'long':
                            if self.spx[-1-5]<self.stop_loss_price_worst-offset: # and self.spx[-1-6]<self.stop_loss_price-offset:
                                pos_size=1        
                                print(f'long pos stop loss ratio by a=1.25, {self.extreme_price0-self.ref_price0,self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                            if self.entry_price-self.spx[-1-5]>0.382* abs(self.extreme_price0-self.ref_price0) and \
                                    self.spx[-1] < min(self.spx[-61:-6]) and self.spx[-6] - self.entry_price<-self.spx[-6]*0.001:
                                pos_size=-1
                                print(f'Long pos stop loss 2, {self.extreme_price0-self.ref_price0,self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')    
                        elif self.entry_type0 == 'short':
                            if self.spx[-1-5]>self.stop_loss_price_worst+offset: # and self.spx[-1-6]>self.stop_loss_price+offset: 
                                pos_size=-1
                                print(f'short pos stop loss ratio by a=1.25, {self.extreme_price0-self.ref_price0,self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                            if self.spx[-1-5]-self.entry_price>0.382* abs(self.extreme_price0-self.ref_price0) and \
                                    self.spx[-1] > max(self.spx[-61:-6]) and self.spx[-6] - self.entry_price> self.spx[-6]*0.001:
                                pos_size=-1
                                print(f'Short pos stop loss 2, {self.extreme_price0-self.ref_price0,self.sig_time,self.sec_since_last_sig,self.entry_price,self.ref_price0,self.data_spx.close[0],self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
            if pos_size !=0:
                return self.close_cleanup(21)
        return pos_size
    def set_sig(self,A=0):
        self.normal_up, self.normal_down, self.consistency_up, self.consistency_down=False,False,False,False
        if A>= 3:
            self.big_up=True
        elif A>= 2 and A<3:
            self.normal_up=True
        else:
            self.consistency_up=True
        if A<= -3:
            self.big_down=True
        elif A<= -2 and A> -3 :
            self.normal_down=True
        else:
            self.consistency_down=True
    def compute_sec(self):
        time1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return (time1.hour-9)*3600+(time1.minute-30)*60+time1.second
    def compute_rho(self,sec: int, period_spx: int = 15):
        if np.mod(sec,15)==0:
            rho=self.data_cor3m.close.get(size=1)[0]
            if len(self.rho)==0:
                self.rho.append(rho)
                self.abs_rho.append(0)
            else:
                d_rho=rho-self.rho[-1]
                self.rho.append(rho)
                self.abs_rho.append(abs(d_rho)+self.abs_rho[-1])
        # return abs(sec-70-len(self.rho)*15)<=60
        return len(self.rho)
        
    def compute_d_mom(self,sec: int, N_count: int = 4, period_spy: int = 5):
        R_all,R_3_min,R_2_min,R_1_min, R_30_min=1,1,1,1,1
        if np.mod(sec,5)==0 and sec>=5:
            index = sec/5-1
            if sec==5:
                price_N=self.data_spy.close.get(size=1)[0]
                self.mom.append(0)
                self.abs_mom.append(0)
            else:
                if sec==10:
                    vol_time_series=(self.data_spy.volume.get(size=N_count-1))
                    close_time_series= (self.data_spy.close.get(size=N_count-1))  # close_time_series= spy_df['close'][-N:]
                    vol_N=vol_time_series[-2]+vol_time_series[-1] #+vol_time_series[-2]        # vol_N=int(self.data_spy['volume'][0])+int(self.data_spy['volume'][-1])
                    turnover_N =vol_time_series[-2]*close_time_series[-2]+vol_time_series[-1]*close_time_series[-1] #+vol_time_series[-2]*close_time_series[-2] #average
                elif sec>=15:
                    vol_time_series=(self.data_spy.volume.get(size=N_count))
                    close_time_series= (self.data_spy.close.get(size=N_count))  # close_time_series= spy_df['close'][-N:]
                    vol_N=vol_time_series[-3]+vol_time_series[-1]+vol_time_series[-2]        # vol_N=int(self.data_spy['volume'][0])+int(self.data_spy['volume'][-1])
                    turnover_N =vol_time_series[-3]*close_time_series[-3]+vol_time_series[-1]*close_time_series[-1]+vol_time_series[-2]*close_time_series[-2] #average
                price_N =turnover_N/vol_N if vol_N>0 else self.previous_price_N
                d_mom_single=0
                if self.previous_price_N is None or (type(self.previous_price_N) is not float): # or self.d_mom==None:
                    self.mom.append(0)
                    self.abs_mom.append(0)
                elif type(self.previous_price_N) is float:
                    threshold = 1000 #simon?????
                    N_count=len(self.mom)-1
                    d_mom_single=vol_N*(price_N/self.previous_price_N-1)/adj_vector[index]  #/self.abs_ratio
                    current_mom=self.mom[N_count]+d_mom_single
                    self.mom.append(current_mom)
                    self.abs_mom.append(self.abs_mom[N_count]+abs(d_mom_single))
                    if current_mom>threshold:
                        self.big_up_mom = True
                        self.big_up_2=True
                    elif current_mom<-threshold:
                        self.big_down_mom = True
                        self.big_down_2=True
            self.previous_price_N=price_N        
        
        N_2_min= 24

        N_0_2min=36
        N_0_long=12*6+6
        N_0_short =12*3+4
        N_0_short_1_min =12*2+6
        N_90_sec= 18
        N_count= 36
        N_30_min= 360
        
        if len(self.mom)>N_30_min+N_0_long:
            R_30_min=(self.abs_mom[-1-N_0_long]-self.abs_mom[-1-N_0_long-N_30_min])/N_30_min
        elif len(self.mom)>N_0_long:
            R_30_min= self.abs_mom[-1-N_0_long]/ (len(self.mom)-N_0_long)
        elif len(self.mom)>0:
            R_30_min= self.abs_mom[-1]/len(self.mom)
        
        if len(self.mom)>N_count:
            R_all=self.abs_mom[-1-N_count]/(len(self.abs_mom)-N_count)
        elif len(self.abs_mom)>0:
            R_all=self.abs_mom[-1]/len(self.abs_mom)
        elif len(self.mom)>0:
            R_all= self.abs_mom[-1]/len(self.mom)
        
        if len(self.mom)>N_count+N_0_short:
            R_3_min=(self.abs_mom[-1-N_0_short]-self.abs_mom[-1-N_0_short-N_count])/N_count
        elif len(self.mom)>N_0_short:
            R_3_min= self.abs_mom[-1-N_0_short]/ (len(self.mom)-N_0_short)
        elif len(self.mom)>0:
            R_3_min= self.abs_mom[-1]/len(self.mom)
               
        if len(self.mom)>N_90_sec+N_0_short_1_min:
            R_1_min=(self.abs_mom[-1-N_0_short_1_min]-self.abs_mom[-1-N_0_short_1_min-N_90_sec])/N_90_sec
        elif len(self.mom)>N_0_short_1_min:
            R_1_min= self.abs_mom[-1-N_0_short_1_min]/ (len(self.mom)-N_0_short_1_min)
        elif len(self.mom)>0:
            R_1_min= self.abs_mom[-1]/len(self.mom)

        if len(self.mom)>N_2_min+N_0_2min:
            R_2_min=(self.abs_mom[-1-N_0_2min]-self.abs_mom[-1-N_0_2min-N_2_min])/N_2_min
        elif len(self.mom)>N_0_2min:
            R_2_min= self.abs_mom[-1-N_0_2min]/ (len(self.mom)-N_0_2min)
        elif len(self.mom)>0:
            R_2_min= self.abs_mom[-1]/len(self.mom)

        self.R_all =R_all
        self.R_30_min=R_30_min
        self.R_3_min=R_3_min
        self.R_1_min=R_1_min
        self.R_2_min=R_2_min

        if self.sec_since_last_sig>=5:
            A_0 = int(min(self.sec_since_last_sig, 540)/5)
            self.slope_local=(self.abs_mom[-1]-self.abs_mom[-1-A_0])/A_0
        
        return len(self.mom)
    # def univ_10am(self):
    #     date1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz)
    #     return date1.isoweekday()
    def news_10am(self):
        time1= bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
        return time1>=time(10,0,0) and time1<=time(10,5,35)

    def update_extreme(self):
        if self.longer_wait and self.extreme_price0 is not None and self.ref_price0 is not None :
            if self.extreme_price0 >self.ref_price0:
                self.extreme_price0 = max(self.extreme_price0,self.spx[-1])
                self.extreme_mom0 = max(self.extreme_mom0,self.mom[-1])
            
            elif self.extreme_price0 <self.ref_price0:
                self.extreme_price0 = min(self.extreme_price0,self.spx[-1])
                self.extreme_mom0 = min(self.extreme_mom0,self.mom[-1])
                
        if self.entry_type0=='long':
            self.extreme_price0 = self.data_spx.close[0] if self.extreme_price0 is None else max(self.extreme_price0, self.data_spx.close[0])
            self.extreme_mom0 = self.mom[-1] if self.extreme_mom0 is None else max(self.extreme_mom0, self.mom[-1]) #open = mom
                    
        if self.entry_type0=='short':
            self.extreme_price0 = self.data_spx.close[0] if self.extreme_price0 is None else min(self.extreme_price0, self.data_spx.close[0])
            self.extreme_mom0 = self.mom[-1] if self.extreme_mom0 is None else min(self.extreme_mom0, self.mom[-1]) #open = mom
            # 对错的 stoploss 出场的处理        # 更新历史数据
    # def atr_exit_spx(self,slope_spx_0, threshold=81.8):
    def my_atr_spx(self, period: int = 180, N_offset_1s:int=20,threshold=82): # 3-4min ,offset is already delayed
        slope,slope_0=0,0
        N_0=len(self.abs_spx)
        if N_0>period+N_offset_1s:
            slope = (self.abs_spx[-1-N_offset_1s]-self.abs_spx[-1-N_offset_1s-period])/period
            High,Low = max(self.spx[-1-N_offset_1s-period:-1-N_offset_1s]),min(self.spx[-1-N_offset_1s-period:-1-N_offset_1s])
        elif N_0>0:
            slope = (self.abs_spx[-1]-self.abs_spx[0])/N_0
            High,Low = max(self.spx),min(self.spx)
        if N_0>N_offset_1s:
            if self.entry_type0=="long":
                slope_0=(High - self.spx[-1-N_offset_1s] )/slope 
            elif self.entry_type0=="short":
                slope_0=(self.spx[-1-N_offset_1s] -Low)/slope 
        else:
            slope,slope_0=1,1
        return slope,slope_0
    def my_atr_spy_mom(self, period: int = 36, N_offset_5s:int=4): # 3-4min,offset is already delayed
        slope_spy,slope_mom,slope_spy_0,slope_mom_0=0,0,0,0
        N_0=len(self.abs_spy)
        if N_0>period+N_offset_5s:
            slope_spy = 2*(self.abs_spy[-1-N_offset_5s]-self.abs_spy[-1-period-N_offset_5s])/period # 10/5
            slope_mom = (self.abs_mom[-1-N_offset_5s]-self.abs_mom[-1-period-N_offset_5s])/period
            High_spy,Low_spy = max(self.spy_high[-1-N_offset_5s-period:-1-N_offset_5s]),min(self.spy_low[-1-N_offset_5s-period:-1-N_offset_5s])
            High_mom,Low_mom = max(self.mom[-1-N_offset_5s-period:-1-N_offset_5s]),min(self.mom[-1-N_offset_5s-period:-1-N_offset_5s])
        else:
            if len(self.mom)>0 and N_0>0:
                High_spy = max(self.spy_high) 
                Low_spy = min(self.spy_low)
                High_mom = max(self.mom)
                Low_mom = min(self.mom)
            
                slope_spy = (self.abs_spy[-1]-self.abs_spy[0])/N_0
                slope_mom = (self.abs_mom[-1]-self.abs_mom[0])/N_0
            else:
                slope_spy = 1
                slope_mom = 1
                High_spy = 0
                Low_spy = 0
                High_mom =0
                Low_mom = 0

        if N_0>N_offset_5s:
            if self.entry_type0=="long":
                slope_spy_0=(High_spy - self.spy_close[-1-N_offset_5s] )/slope_spy
                slope_mom_0=(High_mom - self.mom[-1-N_offset_5s] )/slope_mom
            elif self.entry_type0=="short":
                slope_spy_0=(self.spy_close[-1-N_offset_5s] -Low_spy)/slope_spy
                slope_mom_0=(self.mom[-1-N_offset_5s] -Low_mom)/slope_mom
        else:
            slope_spy,slope_mom,slope_spy_0,slope_mom_0=1,1,1,1
        return slope_spy,slope_mom,slope_spy_0,slope_mom_0
    
    def compute_spx(self,sec:int, period_spx: int = 1):
            sec=self.compute_sec()
            price=self.data_spx.close.get(size=1)[0]
            if len(self.spx)==0:
                self.abs_spx.append(0)                
            else:
                self.abs_spx.append(abs(price-self.spx[-1])+self.abs_spx[-1])    
            self.spx.append(price)
            # return abs(sec-2-len(self.spx))<=10
            if len(self.spx) < len(self.spy_close)*5 -10 and len(self.spy_close)>12:
                for i in range(100):
                    if len(self.spx) < len(self.spy_close)*5- 5 :
                        self.spx.append(self.spx[0] * self.spy_close[-1]/self.spy_close[0]) 
                        # True
            return len(self.spx)
    def compute_spy(self,sec:int, period_spy: int = 5):
        if np.mod(sec,5)==0:
            H=self.data_spy.high.get(size=1)[0]
            L=self.data_spy.low.get(size=1)[0]
            if len(self.abs_spy)==0:
                self.abs_spy.append(H-L)                
            else:
                self.abs_spy.append(H-L+self.abs_spy[-1])    
            self.spy_close.append(self.data_spy.close.get(size=1)[0])
            self.spy_open.append(self.data_spy.open.get(size=1)[0])
            self.spy_high.append(H)
            self.spy_low.append(L)
        # return abs(sec-8-len(self.spy_close)*5)<=12
        return len(self.spy_close)
    def rho_correction(self,diff=2.0):
        if len(self.rho)>=3:
            if (self.rho[-2]-self.rho[-1]>2 and self.rho[-2]-self.rho[-3]>2) or (self.rho[-2]-self.rho[-1]<-2 and self.rho[-2]-self.rho[-3]<-2):
                # p rint(self.current_time_NY, self.rho[-1],self.rho[-2],self.rho[-3],self.extreme_rho0)
                self.rho[-2] = self.rho[-1]
    def set_trend(self,up_down):
        self.trend_start_time=self.data_spx.datetime[0]
        self.mom_up = up_down
        self.mom_down = not(up_down)

        
    def swap_action(self,ratio=0.2): # 换仓动作
        portion_sign = self.max_sig_type
        return 0    
    
    def with_ref_extreme(self):
        return not (self.ref_price0 is None or self.extreme_price0 is None or self.ref_mom0 is None or self.extreme_mom0 is None or \
            len(self.spx)<30 or len(self.mom)<4)
    
    def with_ref_extreme_and_rho(self):
        return not (self.ref_price0 is None or self.extreme_price0 is None or self.ref_mom0 is None or self.extreme_mom0 is None or \
            len(self.spx)<30 or len(self.mom)<4 or len(self.rho)<4)
    
    def set_stop_loss(self,buy_sell,a=0.382,look_back_sec=181):
        if buy_sell:
            new_stop_loss=a*self.spx[-1] +(1-a)*min(self.spx[-look_back_sec:])
            if self.stop_loss is None:        
                self.stop_loss= new_stop_loss
            elif self.stop_loss is not None: 
                self.stop_loss= min(new_stop_loss,self.stop_loss)
        elif not buy_sell:
            new_stop_loss=a*self.spx[-1] +(1-a)*max(self.spx[-look_back_sec:])
            if self.stop_loss is None:        
                self.stop_loss= new_stop_loss
            elif self.stop_loss is not None: 
                self.stop_loss= max(new_stop_loss,self.stop_loss)

    def next(self):
        
        
        self.current_time_NY = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz) 
        
        time1= self.current_time_NY.time()
        allow_normal = self.can_trade_noon_trend() #time1>time(12,1,5) and  time1<time(13,59,50)      is_noon_trend  # trading1 = (time(9, 46, 0) <= time1 < time(12, 2, 0))# 待测 allow normal sig
        
        sec= self.compute_sec()
        ir_rho_inaccurate_illiquid_period = self.ir_date() and sec >3600*4.5 and sec <3600*4.5 +241
        ir_rho_inaccurate_illiquid_period_2 = sec >3600*.5 and sec <3600*.5 +241
                    
        if sec==1 or self.current_date != self.data_spx.datetime.date(0):            
            self.init_data()
            
        if (self.ir_date() and sec>4.5*3600 + 600 and sec<5.5*3600+60 and self.R_1_min>10) or self.R_1_min>10 or self.R_3_min>8:
            self.abs_dir=max(self.abs_dir,0)
        
        is_half_day = self.half_date()
        T_close = 3.5*3600 if self.half_date() else 6.5*3600
        sec_to_close = T_close - sec # 22 mins   22*60
        
        if self.position:
            print(time1,self.stop_loss)
            
        if self.position and self.entry_time0 is not None:
            self.sec_since_trade=(self.current_time_NY-self.entry_time0).seconds        # and self.myposition!=0             # =(self.current_time_NY-self.sig_time).seconds

        if (self.sig_time!=None) and not (self.is_market_close_bar()):#         # 计算信号发生多少sec了 
            real_sig_time_NY=bt.num2date(self.sig_time).replace(tzinfo=pytz.utc).astimezone(ny_tz)
            self.sec_since_last_sig=(self.current_time_NY-real_sig_time_NY).seconds        # and self.myposition!=0             # =(self.current_time_NY-self.sig_time).seconds
        else:
            self.sec_since_last_sig=0
        
        if self.sec_since_last_sig>500 and not self.position and self.longer_wait:
            self.cleanup()

        if (self.trend_start_time!=None) and not (self.is_market_close_bar()):#         # 计算信号发生多少sec了 
            trend_start_time_NY=bt.num2date(self.trend_start_time).replace(tzinfo=pytz.utc).astimezone(ny_tz)
            self.sec_since_trend=(self.current_time_NY-trend_start_time_NY).seconds        # and self.myposition!=0             # =(self.current_time_NY-self.sig_time).seconds
        else:
            self.sec_since_trend=0
        
        self.trade_lock, self.close_lock = False,False
        
        B_mom=self.compute_d_mom(sec) #compute momentum new method
        if self.ir_date() and (sec == 3600*4+1800-60 or sec == 3600*4+1800-59 or (sec >= 3600*4+1800-61 and sec <= 3600*4+1800-58)):
            self.ir_2pm_mom = self.mom[-1]
            self.ir_2pm_spx = self.spx[-1]
            
        B_spx=self.compute_spx(sec)
        if self.sec_since_last_sig>360:
            if self.position:
                self.stop_loss = self.entry_price
            else:
                self.stop_loss = None
        if self.sec_since_trade>360:
                            self.stop_loss = self.entry_price

        if self.sec_since_trade>480:
            # if self.entry_type0== "long":
                self.stop_loss = self.entry_price+0.08*(self.extreme_price0 - self.ref_price0)
            # elif self.entry_type0== "short":
                # self.stop_loss = self.entry_price-1.3

        if len(self.spx)>10:
            max_range=max(self.spx)-min(self.spx)
            max_range_mom=max(self.mom)-min(self.mom)
        
        if self.extreme_price0 is not None and self.extreme_mom0 is not None and self.longer_wait and self.ref_price0 is not None:
            if self.extreme_price0<self.ref_price0:
                self.extreme_price0 = min(self.extreme_price0,self.spx[-1])
                self.extreme_mom0 = min(self.extreme_mom0,self.mom[-1])           
            elif self.extreme_price0>self.ref_price0:
                self.extreme_price0 = max(self.extreme_price0,self.spx[-1])
                self.extreme_mom0 = max(self.extreme_mom0,self.mom[-1])
        B_spy=self.compute_spy(sec)
        
        B_rho=self.compute_rho(sec)
        
        self.rho_correction(2.0)
        
        if self.position:
            if self.entry_type0 =="long":
                self.max_profit = max(self.max_profit,self.extreme_price0-self.entry_price) 
                self.current_profit = (self.spx[-1]-self.entry_price) 
            elif self.entry_type0 =="short":
                self.max_profit = max(self.max_profit,-self.extreme_price0+self.entry_price) 
                self.current_profit = (-self.spx[-1]+self.entry_price) 

        if self.position and self.sec_since_trade>60*112 and sec_to_close<21*60+2 and abs(-self.extreme_price0+self.entry_price)>=self.spx[-1]*0.085:  #self.max_profit>self.spx[-1]*0.012: #60*120-240
            print( self.sec_since_last_sig,self.sec_since_trade)
             # and self.sec_since_last_sig> 60*112:
            self.close_cleanup(9999)
        
        if self.position and self.sec_since_trade>60*150 and sec_to_close<75*60+2 and abs(-self.extreme_price0+self.ref_price0)>=self.spx[-1]*0.0082:  #self.max_profit>self.spx[-1]*0.012: #60*120-240
            print( self.sec_since_last_sig,self.sec_since_trade)
             # and self.sec_since_last_sig> 60*112:
            self.close_cleanup(9998)

        if self.sec_since_last_sig>300:
            if self.position:
                if self.entry_type0=="long":
                    self.stop_loss=min(self.stop_loss,self.entry_price+0.06*(self.extreme_price0-self.entry_price))
                elif self.entry_type0=="short":
                    self.stop_loss=max(self.stop_loss,self.entry_price+0.06*(self.extreme_price0-self.entry_price))
        
        if self.sec_since_last_sig>375:
            if self.position:
                if self.entry_type0=="long":
                    self.stop_loss=min(self.stop_loss,self.entry_price+0.08*(self.extreme_price0-self.entry_price))
                elif self.entry_type0=="short":
                    self.stop_loss=max(self.stop_loss,self.entry_price+0.08*(self.extreme_price0-self.entry_price))
            # else:
            #     self.stop_loss = None

        if self.sec_since_last_sig>450:
            if self.position:
                if self.entry_type0=="long":
                    self.stop_loss=min(self.stop_loss,self.entry_price+0.1*(self.extreme_price0-self.entry_price))
                elif self.entry_type0=="short":
                    self.stop_loss=max(self.stop_loss,self.entry_price+0.1*(self.extreme_price0-self.entry_price))
        if self.sec_since_last_sig>540:
            if self.position:
                if self.entry_type0=="long":
                    self.stop_loss=min(self.stop_loss,self.entry_price+0.12*(self.extreme_price0-self.entry_price))
                elif self.entry_type0=="short":
                    self.stop_loss=max(self.stop_loss,self.entry_price+0.12*(self.extreme_price0-self.entry_price))

        if self.position and self.stop_loss is not None:
            if self.is_ir_date and (time(14, 0, 0) < time1 <= time(14, 6, 30)):
                if self.entry_type0=="long":
                    self.stop_loss=min(self.stop_loss,self.ir_2pm_spx*0.8+0.2*  self.entry_price)
                elif self.entry_type0=="short":
                    self.stop_loss=max(self.stop_loss,self.ir_2pm_spx*0.8+0.2*  self.entry_price)

                # self.extreme_price0

            abc=min(180,len(self.mom))
            S_1=(self.abs_mom[-1]-self.abs_mom[-1-abc])/abc
            if abs(self.extreme_mom0-self.mom[-1])/S_1>151: # 25 - 22
                print(f"{time1} : exit")
                # self.close_cleanup(1999)  
            if self.entry_type0=="long":
                if self.spx[-1]<self.stop_loss:
                    print(time1,self.stop_loss,self.entry_price,self.extreme_price0,self.spx[-1])
                    
                    print(self.extreme_mom0,self.mom[-1],self.ref_mom0,S_1,\
                          (self.extreme_mom0-self.mom[-1])/S_1)
                    self.close_cleanup(875)  
                    self.stop_loss = None

            elif self.entry_type0=="short":
                if self.spx[-1]>self.stop_loss:
                    print(self.stop_loss)
                    self.close_cleanup(-875) 
                    self.stop_loss = None 

        if len(self.rho) >= 14:
            rho_H=max(self.rho[-14:])
            rho_L=min(self.rho[-14:])
        elif len(self.rho) >= 5:
            rho_H=max(self.rho[-5:])
            rho_L=min(self.rho[-5:])

        if B_rho:
            if abs(sec_to_close-60*15)<=1:
                rho_H=max(self.rho[-9:])
                rho_L=min(self.rho[-9:])
            elif abs(sec_to_close-60*10)<=1:
                rho_H =max(self.rho[-8:])
                rho_L=min(self.rho[-8:])
            elif abs(sec_to_close-60*5)<=1:
                rho_H=max(self.rho[-7:])
                rho_L=min(self.rho[-7:])

            if self.ir_date() and abs(sec-3600*4.5)<=1:
                rho_H=max(self.rho[-14:])
                rho_L=min(self.rho[-14:])
            elif abs(sec-1800)<=1:
                rho_H=max(self.rho[-11:])
                rho_L=min(self.rho[-11:])
            elif abs(sec-3600*5.5)<=1:
                rho_H=max(self.rho[-9:])
                rho_L=min(self.rho[-9:])

        L_spx_ref = min ( len(self.spx)-1, 270)
        L_mom_5_ref = min ( len(self.spx)-1, 54)
        L_spx_4_min = min ( len(self.spx)-1, 240)
        L_mom_4_min = min ( len(self.spx)-1, 48)

        mom_near_up,mom_near_down,rho_near_up,rho_near_down = False,False,False,False
        if len(self.rho)>12:
            
            rho_series_1=self.rho[-5:]
            rho_series_2=self.rho[-19:-5]
            rho_series_last = self.rho[-1-12:]
            rho_series_second_last = self.rho[-1-24:-12-1]
            
            c_0,c_0_up,c_0_down, is_rho_up_1, is_rho_down_1, is_rho_up_2, is_rho_down_2,up_count,down_count =self.is_rho_change()
            
            is_rho_down_0 = is_rho_down_1 or is_rho_down_2
            is_rho_up_0 = is_rho_up_1 or is_rho_up_2
        else:
            c_0 = 1
            c_0_up = 0
            c_0_down=0
            rho_series_1=[]
            rho_series_2=[]
            rho_series_last = []
            rho_series_second_last = []

        N_period = min(len(self.spx),201)
        M_period = min(len(self.mom),41)
        if self.position and  (self.ref_price0 is None or  self.ref_mom0 is None or self.extreme_price0 is None or  self.extreme_mom0 is None):    True   # p rint("xxxx!!!!!")
        slope_spx,slope_spx_0=self.my_atr_spx()
        slope_spy, slope_mom,slope_spy_0, slope_mom_0  =self.my_atr_spy_mom()

        Var_spy=np.var(self.spy_close[-37:]) if len(self.spy_close)>36 else np.var(self.spy_close) # 暂时如此 var 的2.5 阈值
        Var_spy_long=np.var(self.spy_close[-120:]) if len(self.spy_close)>120 else np.var(self.spy_close) # 暂时如此 var 的2.5 阈值

        R_all,R_30_min, R_3_min, R_1_min  = self.R_all,    self.R_30_min,     self.R_3_min,    self.R_1_min 
        
        size_1 = min(len(self.data_spx.close),200)
        self.spx_high2, self.spx_low2, max_index,min_index= self.calculate_series_max_min(list(self.data_spx.close.get(size=size_1)),20)  
            
        self.mkt_close()
        if self.is_ir_date:
            if  self.position and self.current_time_NY.time()== time(13, 52, 20): #sec == 3600*4.5-40-60*7
                print(f'ir date close before 2pm, {self.data_spx.datetime.datetime(0)}: Closing position at market close, sec={self.sec_since_last_sig}')
                temp_close = self.close_cleanup(22)               
        max4, min4=0,0  # 5/6 bug fix # if self.ir_date() and time1>time(14,30,1) and time1<time(15,2,1): self.fed_day_adj=1.21
        if sec>=35:
            max4, min4,max6, min6=self.set_max4_min4_value()
        if len(self.mom)<=0:    return
                
        adj_ratio=1.0 # 后续应该写成连续函数，todo simon
        R_avg = 1.6  # simon??????????? 1.35  1.3-1.4-1.5 -1.6
        if R_all>0: 
            if (R_all>7 and R_30_min>9) or R_3_min>20 or R_3_min>30: 
                self.is_high_vol =True 
                self.is_low_vol =False

            if (R_all>12 and R_30_min>12) or R_3_min>25 or  R_1_min>35 :              #2.8
                adj_ratio=min(np.power(R_all/R_avg,1/2),4)
            elif (R_all>9 and R_30_min>10) or R_3_min>20 or  R_1_min>30 : 
                adj_ratio=2.5
            elif (R_all>7 and R_30_min>9) or R_3_min>15 or  R_1_min>25 : 
                adj_ratio=2.0
            elif (R_all>5 and R_30_min>6) or R_3_min>10 or  R_1_min>20 : 
                adj_ratio=1.5    
            else:
                adj_ratio=min(1.5,max(R_30_min/4,R_30_min/6,R_1_min/10))  
            #simon?????????
            if R_all<2.5 and R_30_min<3 and R_3_min<4.5 and R_1_min<6: 
                self.is_low_vol =True
                self.is_high_vol=False
                
                # adj_ratio=np.power(R_all/R_avg,1/2) # adj_ratio=0.8
                adj_ratio=max(R_all,R_30_min,R_3_min*0.618 )/R_avg # adj_ratio=0.8, 0.3333? simon?
                # adj_ratio=max(R_all,R_30_min,R_3_min*0.6 )/R_avg # adj_ratio=0.8, 0.3333? simon?

                adj_ratio_3min = max(R_3_min,R_1_min*0.8)/R_avg
                adj_ratio=max(0.3,adj_ratio) # simon??????????? 0.3

            if self.ir_date() and time1>time(14,1,10): # 3.10 以后可以缩小adj_ratio, todo simon ,semi-mannual
                # self.is_high_vol =True
                adj_ratio = max(1.5,adj_ratio)
        
        L_0 = min(len(self.mom),90)
        if L_0>4:
            if max(self.mom[-1-L_0:])>1000 or min(self.mom[-1-L_0:])<-1000:
                self.is_high_vol =True

        if self.buy_super_sig_count >0 or self.sell_super_sig_count >0:
            self.is_low_vol=False
            # self.is_high_vol=True
            adj_ratio = max(adj_ratio,1.2,np.power(R_all/R_30_min,1/2))

            R_all    = max(4,R_all)
            R_30_min = max(4,R_30_min)
            R_3_min = max(4,R_3_min)
            R_1_min = max(4,R_1_min)
            
        ratio_up, ratio_down = self.set_ratio_2()       # not used self.adjust_for_big_move()  must use after setting big_up or big_down

        self.adj_ratio=adj_ratio
        R_all_0 = max(0.5,R_all/3.2,R_30_min/4,R_3_min/5,R_1_min/7) # spx range  #and bearish_bars
        R_and_adj_ratio = max(0.5,R_all/3.2,R_30_min/4,R_3_min/5,R_1_min/7,adj_ratio)
        #stop loss
        if self.position and self.stop_loss is not None:
            if self.entry_type0=="long" and self.spx[-1] < self.stop_loss:
                    self.close_cleanup(+99)
            elif self.entry_type0=="short" and self.spx[-1] > self.stop_loss:
                    self.close_cleanup(-99)
        # 换仓
        if self.position and self.sec_since_last_sig > 58:
     
                # if abs(self.spx[-1]-self.swap_price)>20: 
                #     print(time1,self.spx[-1],self.swap_price )
                #     print("换换仓仓")
                local_dir = 0
                
                # adj_ratio=max(adj_ratio,1)
                a_0 = 1.2 if self.ir_date() and sec> 4.5*3600 else 1.0
                b_0 = 1.05 if self.R_1_min>10 or self.R_3_min> 5 or adj_ratio> 2.4 else 1.0
                adj_close = 0.5 if sec_to_close<=15*60 else 1.0
                change = abs(self.entry_price-self.extreme_price0)/self.spx[-1]
                                
                ratio = max(1 - (self.swap_count+1)/6,0)
                ratio = max(1 - change/0.025,0.1)
                
                if sec_to_close>60*15:
                    ratio=min(0.1,ratio)

                    option_ladder = 20 * a_0 * b_0 * adj_close
                elif sec_to_close>60*10:
                    option_ladder = 15 * a_0 * b_0 * adj_close
                else:
                    option_ladder = 10 * a_0 * b_0 * adj_close

                if ratio>0.05:
                    if self.entry_type0=="long":
                        if self.spx[-1]-self.swap_price > option_ladder: 
                            local_dir = 1
                            self.swap_price =self.spx[-1] 
                    elif self.entry_type0=="short":
                        if -(self.spx[-1]-self.swap_price) > option_ladder: 
                            local_dir = -1
                            self.swap_price =self.spx[-1] 
                
                if local_dir!=0 and self.p.option_trading and sec_to_close>60*5:
                    self.swap_count +=1 
                    print(f'换仓 swap hand ratio = {ratio}; time @: {self.current_time_NY}')   
                    is_swap = self.swap_action(ratio)
          
        if self.ir_date() and time1>time(14,1,0) and time1<time(14,3,10): # 150 or 200 ??????simon
            
            if abs(self.mom[-1]-self.mom[-1-40])>150: True
         
        # to test by ????????simon?????????? 10点加速方案  暂时如此，可以不用
        if time1>time(10,0,0) and time1<time(10,1,0): # 150 or 200 ??????simon
            if self.current_max4 >=151 * self.symmetric_ratio_up and \
                (self.spx[-1]>self.spx_high2) and (self.spx[-1]-self.spx_low2)>= self.spx[-1]*0.00152 and \
                    True:
                self.buy_trade(2.8) # yes  # p rint(self.current_time_NY,self.current_max4,self.symmetric_ratio_up,self.enlarge_3_min(),self.data_spx.close[0],self.spx_high2,self.spx_low2)
                self.normal_up =True                # self.normal_up_10am =True
            if self.current_max4 <= - 151 * self.symmetric_ratio_up and \
                (self.data_spx.close[0]<self.spx_low2) and (self.data_spx.close[0]-self.spx_high2)<= -self.data_spx.close[0]*0.00152 and \
                    True:
                self.sell_trade(-2.8)   # yes # p rint(self.current_time_NY,self.current_max4,self.symmetric_ratio_up,self.enlarge_3_min(),self.data_spx.close[0],self.spx_high2,self.spx_low2)
                self.normal_down =True                # self.normal_down_10am =True
          
        if True :# B_spx and B_spy: # not IR date  # simon - -ir date or high abs_mom days    
            if self.position:
                adj_ratio=max(adj_ratio,1)
            self.news_impacted(threshold=30)
            self.set_early_exit()
            self.mom_rebounce()
            d_mom_sum_180s,d_mom_sum_90s,d_mom_sum_sec_last_90s,d_mom_sum_45s=0,0,0,0
            if len(self.mom)>0:
                if len(self.mom) > 36+1+1:
                    d_mom_sum_180s = self.mom[-1-1] -min(self.mom[-1-36-1:-1-30-1]) if self.mom[-1-1] >self.mom[-1-1-36-1] else self.mom[-1-1] -max(self.mom[-1-36-1:-1-30-1])
                else: 
                    d_mom_sum_180s = self.mom[-1] -self.mom[0]  # 150s
                if len(self.mom) > 18+1+1:
                    d_mom_sum_90s = self.mom[-1-1] -min(self.mom[-1-18-1:-1-15-1]) if self.mom[-1-1] >self.mom[-1-18-1] else self.mom[-1-1] -max(self.mom[-1-18-1:-1-15-1])
                else: 
                    d_mom_sum_90s = self.mom[-1] -self.mom[0]  # 150s
                # d_mom_sum_90s = self.mom[-1] -self.mom[-1-18] if len(self.mom) > 18 else self.mom[-1] -self.mom[0]  # 150s
                d_mom_sum_sec_last_90s = d_mom_sum_180s - d_mom_sum_90s
                d_mom_sum_45s = self.mom[-1-1] -self.mom[-1-9-1] if len(self.mom) > 9+1 else self.mom[-1] -self.mom[0]  # 150s
                if len(self.mom) > 9+1+1:
                    d_mom_sum_45s = self.mom[-1-1] -min(self.mom[-1-9-1:-1-7-1]) if self.mom[-1-1] >self.mom[-1-9-1] else self.mom[-1-1] -max(self.mom[-1-9-1:-1-7-1])
                else: 
                    d_mom_sum_45s = self.mom[-1] -self.mom[0]  # 150s
            if len(self.mom) > 24:  # 150s
                mom_trend_120s, abs_mom_trend_120s = self.mom_and_abs(24,1)
            if len(self.mom) > 6:  # 150s                d_mom_sum_30s = sum(list(self.data_momentum.volume.get(size=6)))
                mom_trend_30s, abs_mom_trend_30s = self.mom_and_abs(6,1)
                
            # Case 3a: 一致性稳定后的中信号入场 也可以加限制，高波动天 case2 不用 
            # 强条件  可以不用 bullish_bars, bearish_bars
            bullish_bars, bearish_bars = self.check_consecutive_bars(self.p.trend_bar_threshold1 * self.symmetric_ratio_up,self.p.trend_bar_threshold2 * self.symmetric_ratio_up)
            # bullish_consistency, bearish_consistency = self.check_consistency_stability(self.current_max4, self.current_min4)
                    
            if not self.can_trade(): #todo simon
                self.if_can_trade=False
                return  

            # 先出场 # self.mom_rebounce()
            
            adj_rho=max(np.power(np.average(self.rho[-10:-2])/12,0.618),1) 

            if not self.position:
                if (not self.ir_date() and sec>3600*4.5) and sec> 60*5:
                    R_and_adj_ratio
                    self.mom[-1] - min(self.mom[-60:])
                    max(self.mom[-60:]) - self.mom[-1] 
                    True
            if self.position or self.longer_wait:
                if ir_rho_inaccurate_illiquid_period and self.entry_price is not None and \
                    self.ref_price0 is not None and self.extreme_price0 is not None:#or ir_rho_inaccurate_illiquid_period_2:
                    if abs(self.ref_price0-self.entry_price)<0.0025*self.spx[-1]:
                        print(self.ir_2pm_spx,self.extreme_price0)
                        if self.entry_type0=="long":
                            self.stop_loss=min(self.stop_loss,self.ref.price0*0.8+0.2*self.extreme_price0)
                        elif self.entry_type0=="short":
                            self.stop_loss=max(self.stop_loss,self.ref.price0*0.8+0.2*self.extreme_price0)

                      
                        
                self.update_extreme()     # 对错的 stoploss 出场的处理        # 更新历史数据
                if self.extreme_rho0 is  None:
                    self.extreme_rho0 = self.rho[-1]
                else:
                    if self.entry_type0=="long":
                        self.extreme_rho0 = min(self.extreme_rho0,self.rho[-1])
                        # p rint(self.extreme_rho0,self.current_time_NY)
                    if self.entry_type0=="short":
                        self.extreme_rho0 = max(self.extreme_rho0,self.rho[-1])
                # max_profit, current_profit, sec_since_max_profit = 0, 0, 0 # 可以写做 profit taken 函数
                if not(self.extreme_price0 is None or self.ref_price0 is None): 
                    max_profit, current_profit, sec_since_max_profit = self.profit_max_current_sec()
                    spx_high, spx_low, max_index,min_index= self.calculate_series_max_min(list(self.data_spx.close.get(size=self.sec_since_last_sig)))
                    # A_0=self.extreme_price0-self.ref_price0 if self.extreme_price0 is not None and self.ref_price0 is not None else 0
                    if self.ref_price0 is not None and self.extreme_price0 is not None and self.sec_since_last_sig >360:                    
                        A_0=self.ref_price0*0.65+0.35*self.extreme_price0
                        if self.entry_type0=="long":  # 10am or sec short???simon? and mom and rho simon
                            if self.spx[-6] < A_0 and self.spx[-1] < min(self.spx[-61:-6]) : 
                                # p rint(time1,self.sec_since_last_sig,A_0,self.ref_price0,self.extreme_price0,self.spx[-1])
                                self.close_cleanup(27.1)
                        elif self.entry_type0=="short":
                            if self.data_spx.close[0] > A_0 and self.spx[-1] > max(self.spx[-61:-6]) :
                                # pr int(time1,self.ref_price0,self.sec_since_last_sig,A_0,self.extreme_price0,self.data_spx.close[0])
                                self.close_cleanup(27.2)
                
                # threshold = 0.425, var = 0.025  rho vs var
                if  (self.entry_type0=="short" and max(self.rho[-14:-1])-self.rho[-1]>=0.425*adj_rho*max(1,Var_spy/0.025)):# /self.R_2_min:  # r_1min   r_2min, longer?????simon
                    # 不用delay
                    if self.spx[-1]-min(self.spx[-182:-1])>0.001*self.spx[-1]*max(1,adj_ratio):
                        # 可以不用
                        self.close_cleanup(77.235)  # ir date and 14-3.10pm, and r_3min, r_1min
                elif (self.entry_type0=="long" and self.rho[-1]-min(self.rho[-14:-1])>=0.425*adj_rho*max(1,Var_spy/0.025)):# /self.R_2_min:  # r_1min   r_2min, longer?????simon
                    if max(self.spx[-182:-1])-self.spx[-1]>0.001*self.spx[-1]*max(1,adj_ratio):
                        # 可以不用
                        self.close_cleanup(78.25)  # ir date and 14-3.10pm, and r_3min, r_1min


                close1 = self.max_min_reverse_exit() # exit by consistency check 150-125  20s              close2 = self.long_position_close_before_230_345pm()
                close2 = self.rho_exit_with_mom_price_confirm(ratio=adj_ratio) # pri nt only, no action to exit
                
                if  self.ref_mom0 is not None and self.extreme_mom0 is not None and self.extreme_rho0 is not None and self.ref_rho0 is not None:
                    if abs(self.rho[-1]-self.ref_rho0)>0.2*abs(self.extreme_rho0-self.ref_rho0) \
                    and abs(self.mom[-1]-self.ref_mom0)>0.2*abs(self.extreme_mom0-self.ref_mom0):
                        
                        B_Time_allow = self.sec_since_last_sig>600
                        B_allow = self.spx[-1]>max(self.spx[-601:-21]) 
                        if B_Time_allow:
                            if self.entry_type0=="long" and self.spx[-1]<min(self.spx[-421:-21]) : #self.spx[-1]>max(self.spx[-421:-21]) :
                                B_allow = True
                            elif self.entry_type0=="short" and self.spx[-1]>max(self.spx[-421:-21]) : 
                                B_allow = True 
                            else:
                                B_allow = False
                        else:
                            B_allow = True

                        N_0=min(len(self.spx),3600-300)  # at least 10 sec
                        if self.extreme_price0 is not None and self.ref_price0 is not None:
                            H_0= abs(self.spx[-1]-self.ref_price0)/abs(self.extreme_price0-self.ref_price0) if self.extreme_price0!=self.ref_price0 else 1.0
                        if self.entry_type0=="short" and len(self.spx)>48 and \
                            self.spx[-1]>max(self.spx[-91:-6]): # 91 or 61 and self.mom[-1]-min(self.mom[-48:-1]>15*adj_ratio: #simon??????????
                                P_1=self.spx[-1]-min(self.spx[-91:-1])
                                P_2=self.spx[-1]*max(1,adj_ratio)
                                
                                if (slope_spx_0>50 and slope_mom_0>25 and self.spx[-1]-min(self.spx[-181:-1])>0.00135*self.spx[-1]) or \
                                    (slope_spx_0>47.5 and slope_mom_0>25 and self.spx[-1]-min(self.spx[-181:-1])>0.0015*self.spx[-1])\
                                        and True: #B_allow:
                             
                                    R_rho = (self.rho[-1]-self.ref_rho0)/(self.extreme_rho0-self.ref_rho0)
                                    
                                    if self.sec_since_last_sig<3600-300 :#and P_1>0.00085*P_2 and True: #rho太慢，适合 3min的情况
                                        # if abs(self.ref_price0-self.extreme_price0)<self.ref_price0*0.005:
                                        if slope_spx_0>62 and slope_mom_0>29.9 and abs(self.spx[-1]-self.extreme_price0)>self.ref_price0*0.001\
                                            and H_0<=0.82 and R_rho<0.52 :
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.25)  # 82 ，  60   50/25   60/30????simon 等几分钟出场
                                        elif slope_spx_0>62 and slope_mom_0>30 and H_0<=0.8 and R_rho<0.52 : # .57
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.297)  # 82 ，  60   50/25   60/30????simon 等几分钟出场
                                    else:
                                        if self.spx[-1]>max(self.spx[-N_0:-10])  and H_0<=0.8 and R_rho<0.52 :# .62 and P_1>0.00085*P_2:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.23)
                                        elif slope_spx_0>65 and slope_mom_0>30 and H_0<=0.75 and R_rho<0.52 :# .62 and P_1>0.00085*P_2:# spx????????????simon and self.ref_price0-self.extreme_price0:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.21)  # 82 ，  60   50/25   60/30????simon
                                        elif slope_spx_0>70 and slope_mom_0>35 and H_0<=0.8 and R_rho<0.52 :#.7 and P_1>0.00085*P_2 and True: #rho太慢， 适合 3min的情况 # and self.ref_price0-self.extreme_price0:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.27)  # 82 ，  60   50/25   60/30????simon 等几分钟出场
                        if self.entry_type0=="long" and len(self.spx)>48 and \
                            self.spx[-1]<min(self.spx[-91:-6]): # and max(self.mom[-48:-1]-self.mom[-1]>15*adj_ratio: #simon?????????? 
                                P_1=max(self.spx[-91:-1])-self.spx[-1]
                                P_2=self.spx[-1]*max(1,adj_ratio)
                                if slope_spx_0>50 and slope_mom_0>25 and max(self.spx[-181:-1])-self.spx[-1]>0.00135*self.spx[-1] or\
                                    slope_spx_0>47.5 and slope_mom_0>25 and max(self.spx[-181:-1])-self.spx[-1]>0.0015*self.spx[-1]\
                                        and True: #B_allow:
                                    R_rho = (self.rho[-1]-self.ref_rho0)/(self.extreme_rho0-self.ref_rho0)
                                    if self.sec_since_last_sig<3600-300:# and P_1>0.00085*P_2:
                                        if slope_spx_0>62 and slope_mom_0>29.9 and abs(self.spx[-1]-self.extreme_price0)>self.ref_price0*0.001\
                                            and H_0<=0.82 and R_rho<0.52 :
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(78.26) # slope_mom_0> 27.5 or 25  # 82 ，  60   50/25   60/30????simon
                                        elif slope_spx_0>62 and slope_mom_0>30 and H_0<=0.8 and R_rho<0.52 : #.57
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(77.267)  # 82 ，  60   50/25   60/30????simon 等几分钟出场
                                    else:
                                        N_0=min(len(self.spx),3600-300)
                                        H_0= abs(self.spx[-1]-self.ref_price0)/abs(self.extreme_price0-self.ref_price0) if self.extreme_price0!=self.ref_price0 else 1.0
                                        H_0= abs(self.spx[-1]-self.ref_price0)/abs(self.extreme_price0-self.ref_price0) if self.extreme_price0!=self.ref_price0 else 1.0
                                        if self.spx[-1]<min(self.spx[-N_0:-10])   and H_0<=0.8 and R_rho<0.52:# .62  and P_1>0.00085*P_2:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(78.24)
                                        elif slope_spx_0>65 and slope_mom_0>30 and H_0<=0.75 and R_rho<0.52 :# .62 and H_0<=0.62 and R_rho<0.8:# and P_1>0.00085*P_2:# spx????????????simon and self.ref_price0-self.extreme_price0:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(78.22)  # 82 ，  60   50/25   60/30????simon
                                        elif slope_spx_0>70 and slope_mom_0>35 and H_0<=0.8 and R_rho<0.52:#.7  and P_1>0.00085*P_2:# and self.ref_price0-self.extreme_price0:
                                            print(time1,H_0,R_rho)
                                            # self.close_cleanup(78.28)  # 82 ，  60   50/25   60/30????simon                # if max4>20:   
              
                close3 = self.stop_loss_ref_entry() #offset=1
                close4 = self.trend_reverse_exit() #todo should larger threshold threshold=150, 90% threshold shrinkage
                close4a = self.trend_reverse_exit_2(adj_ratio) #tighter threshold  125  30s threshold=125
                close5 = self.close_check_by_opposite_sig() # no wait 不用等待 75%
                close6 = self.rebounce_ratio_from_ref_exit() # spx_ratio_threshold=0.618
                close7=self.profit_taken_ratio_exit()
                close_8=self.stop_loss_ratio_ref() # no complete

                if (time1==time(15,37,55) or time1==time(15,37,50)) and self.sec_since_last_sig>60*60*3.5 and self.position:
                    if max_profit>50:
                        self.close_cleanup(100)

                if (time1==time(13,55,55) or time1==time(13,55,50)) and self.ir_date() and self.position:
                    if self.sec_since_last_sig>=60*45:
                        self.close_cleanup(200)

                close_9=self.trend_3_min_exit(max(adj_ratio,1.2))
                self.one_min_trend_exit(max(adj_ratio,1.2)) # self.N_min_trend_exit(N=12 or 18)
                self.stop_loss_6_min()
            if  self.ref_price0 is not None and self.entry_type0 == 'long' and (self.data_spx.close[0] < (self.entry_price*.382 +.618* self.ref_price0-0.1)): # adj2 #if  self.entry_type0 == 'long' and (self.data_spx.close[0] < self.entry_price - sto p_loss*self.adj2):
                self.early_exit=True
            if  self.ref_price0 is not None and self.entry_type0 == 'short' and (self.data_spx.close[0] > (self.entry_price*.382 +.618*self.ref_price0+0.1)):# adj2 #if  self.entry_type0 == 'short' and (self.data_spx.close[0] > self.entry_price + sto p_loss*self.adj2):
                self.early_exit=True
            # 先更新ref extreme
            if self.position and self.entry_type0=='long':
                    self.extreme_price0 = self.data_spx.close[0] if self.extreme_price0 is None else max(self.extreme_price0, self.data_spx.close[0])
                    self.extreme_mom0 = self.mom[-1] if self.extreme_mom0 is None else max(self.extreme_mom0, self.mom[-1]) #open = mom
                    if self.extreme_rho0 is not None:
                        min(self.extreme_rho0, self.rho[-1]) #open = mom
                    elif len(self.rho)>10:
                        self.extreme_rho0 = min(self.rho[-10:-3])  
                    else:
                        self.extreme_rho0 = min(self.rho)  
            if self.position and self.entry_type0=='short':
                    self.extreme_price0 = self.data_spx.close[0] if self.extreme_price0 is None else min(self.extreme_price0, self.data_spx.close[0])
                    self.extreme_mom0 = self.mom[-1] if self.extreme_mom0 is None else min(self.extreme_mom0, self.mom[-1]) #open = mom
                    if self.extreme_rho0 is not None:
                        max(self.extreme_rho0, self.rho[-1]) #open = mom
                    elif len(self.rho)>10:
                        self.extreme_rho0 = max(self.rho[-10:-3])  
                    else:
                        self.extreme_rho0 = max(self.rho)  
            # 对错的 stoploss 出场的处理        # 更新历史数据
            N_lookback=120
            N_mom = max(1,math.floor(N_lookback/5))        
                    # self.close_check_2()  # rebounce 38.2% TODO: this Simon adj ratio should be 最近的几分钟，波动率等 最大幅度 50以上  早盘和下午区别对待  收盘前3.38pm 之后新波段
            # mom在信号后30s 稳定后的 反弹< 38.2% simon       # 前3分钟只用止损 todo       # 再信号 准备        # consistency_trend, trend_ratio,up_sum,down_sum = self.check_consistency_trend2()        # trend_diff = up_sum + down_sum
            
            if (sec>=3600*6.5- 60*15 or (self.half_date() and sec>=3600*3.5- 60*15)):
                L_mom=36
                avg_bar_mom = (self.abs_mom[-13]-self.abs_mom[-13-L_mom])/L_mom
                
                if sec_to_close >= 60*1 and sec_to_close <= 60*14: #(sec>6.5*3600-60*1):
                    
                    V_1=self.rho[-1]-max(self.rho[-21:])
                    V_2=self.rho[-1]-min(self.rho[-21:])
                    V_abs=self.abs_rho[-1]-self.abs_rho[-21]
                    
                    # series_mom=self.mom[-1-length_mom:]
                    series_abs_mom=self.abs_mom[-1-49:]
                    mom_series= self.mom[-49:]
                    abs_mom_series= self.abs_mom[-49:]
                    rho_series= self.rho[-21:]
                    abs_rho_series= self.abs_rho[-21:]
                    mom_min_index= np.argmin(mom_series) #size = 5 -30 
                    mom_max_index= np.argmax(mom_series) #size = 5 -30 

                    rho_min_index= np.argmin(rho_series) #size = 5 -30 
                    rho_max_index= np.argmax(rho_series) #size = 5 -30 

                    V_abs_2_min=self.abs_rho[-1]-self.abs_rho[-12]
                    
                    # if True: #(sec>=3600*6.5- 60*10 or (self.half_date() and sec>=3600*3.5- 60*10)):
                    if self.spx[-1]-min(self.spx[-156:])>self.spx[-1]*0.0018*max(1,avg_bar_mom) and self.spx[-1] > max(self.spx[-60*5:-30]):
                            # if np.mod(sec-2,15)==0:  
                            
                            if self.rho[-1]-rho_series[rho_max_index]<-c_0*0.16  \
                                and self.mom[-1]-mom_series[mom_min_index]>30*max(1,avg_bar_mom): #  \
                                #       abs_rho_series[-1]-abs_rho_series[rho_max_index],(rho_series[rho_max_index] -self.rho[-1]),\
                                #         (self.abs_mom[-1]-abs_mom_series[mom_min_index])/(self.mom[-1]-mom_series[mom_min_index]),\
                                #             (abs_rho_series[-1]-abs_rho_series[rho_max_index])/(rho_series[rho_max_index] -self.rho[-1]))
                                      # 1.15  ,  1.4
                                if         (self.abs_mom[-1]-abs_mom_series[mom_min_index])/(self.mom[-1]-mom_series[mom_min_index])<1.18\
                                            and (abs_rho_series[-1]-abs_rho_series[rho_max_index])/(rho_series[rho_max_index] -self.rho[-1])<1.5: # 0.23
                                    if True:  #np.mod(sec-2,15)==0: 
                                        self.set_trade(1.99978)
                                        True
                            
                            elif self.rho[-1]-rho_series[rho_min_index]> c_0*0.16  \
                                and self.mom[-1]-mom_series[mom_max_index]<-30*max(1,avg_bar_mom): #  \

                                #       abs_rho_series[-1]-abs_rho_series[rho_max_index],(rho_series[rho_max_index] -self.rho[-1]),\
                                #         (self.abs_mom[-1]-abs_mom_series[mom_min_index])/(self.mom[-1]-mom_series[mom_min_index]),\
                                #             (abs_rho_series[-1]-abs_rho_series[rho_max_index])/(rho_series[rho_max_index] -self.rho[-1]))
                                      
                                if         (self.abs_mom[-1]-abs_mom_series[mom_max_index])/abs(self.mom[-1]-mom_series[mom_max_index])<1.18\
                                            and (abs_rho_series[-1]-abs_rho_series[rho_min_index])/abs(rho_series[rho_min_index] -self.rho[-1])<1.5: # 0.23
                                    if True:  #np.mod(sec-2,15)==0: 
                                        self.set_trade(-1.99978)
                        
                   
                    if (V_1<-0.2*c_0 and (-V_1)/(V_abs+V_1)>1.5) or \
                        (V_1<-0.24*c_0 and (-V_1)/(V_abs+V_1)>1.4) or \
                            (V_1<-0.28*c_0 and (-V_1)/(V_abs+V_1)>1.3) or \
                                (V_1<-0.3*c_0 and (-V_1)/(V_abs+V_1)>1.2) or \
                                    (V_1<-0.32*c_0 and -V_1/(V_abs+V_1)>1.1):
                    # 0.543809524   0.565454545   0.585217391   0.603333333   0.62                      # 0.523809524   0.545454545   0.565217391   0.583333333   0.6
                        if self.mom[-1]-min(self.mom[-12:]) >=  max(0.5,avg_bar_mom)*40*self.symmetric_ratio_up:
                            self.set_trade(1.9991)
                       
                    if (V_2<-0.2*c_0 and (-V_2)/(V_abs-V_2)>1.5) or \
                        (V_2<-0.24*c_0 and (-V_2)/(V_abs-V_2)>1.4) or \
                            (V_2<-0.28*c_0 and (-V_2)/(V_abs-V_2)>1.3) or \
                                (V_2<-0.3*c_0 and (-V_2)/(V_abs-V_2)>1.2) or \
                                    (V_2<-0.32*c_0 and V_2/(V_abs-V_2)>1.1):
                    # 0.543809524   0.565454545   0.585217391   0.603333333   0.62                      # 0.523809524   0.545454545   0.565217391   0.583333333   0.6
                        if self.mom[-1]-max(self.mom[-12:]) <= - max(0.5,avg_bar_mom)*40*self.symmetric_ratio_down:
                            self.set_trade(-1.9991)

                    # if (self.mom[-1]-min(self.mom[-13:]))> max(0.5,avg_bar_mom)*0.3:
                if (self.rho[-1]-max(self.rho[-10:-1]))<-c_0*0.3: # 0.23
                    if (self.mom[-1]-min(self.mom[-13:]))> max(0.5,avg_bar_mom)*80*self.symmetric_ratio_up and self.mom[-1]>max(self.mom[-9:-5]):
                       
                        self.longer_wait=True
                        self.normal_up = True
                        self.set_trade(1.99942) #
                elif (self.rho[-1]-min(self.rho[-10:-1]))>c_0*0.24: # 0.3
                    if (self.mom[-1]-max(self.mom[-13:]))<- max(0.5,avg_bar_mom)*80*self.symmetric_ratio_down  and self.mom[-1]<min(self.mom[-9:-5]):
                        self.longer_wait=True 
                        self.normal_down = True
                        self.set_trade(-1.99942) 
                    # set_trade(-) 
            
            if len(self.spx) > 15 :  # 150s
                list_10=list(self.data_spx.close.get(size=10))[:-5] #???? simon to check for 15 or 10
                max_list_10=np.max(list_10)
                min_list_10=np.min(list_10)
                # ,max_list_10 max, , #12s or 15s, 150s or 180s 240s
                N_Normal =25  # 30 24 18   10am  150 加速
                
                # if self.ir_date() and sec>4.5*3600 and sec<=4.5*3600+60*15 and self.ir_2pm_mom is not None and self.ir_2pm_spx is not None:
                #     if self.mom[-1]-self.ir_2pm_mom > 410 and self.spx[-1]-self.ir_2pm_spx > self.spx[-1] * 0.0032:
                #         True
                #         # if True : # rho 
                #             # self.set_trade(3.61) # yes
                            
                #     elif self.mom[-1]-self.ir_2pm_mom < - 410 and self.spx[-1]-self.ir_2pm_spx < -self.spx[-1] * 0.0032:
                #         True
                #         # if True : # rho 
                #         #     self.set_trade(-3.61)  
                #             # yes self.with_ref_extreme()\
                if self.sec_since_last_sig<=200 and self.sec_since_last_sig<=500>25 and self.normal_up:
                    # print(time1,self.with_ref_extreme())
                    True
                if  self.with_ref_extreme() and self.sec_since_last_sig<=500 and (self.normal_down or self.normal_up or self.big_down or self.big_up ):
                    if self.sec_since_last_sig<90 and self.ref_price0 is not None and self.extreme_price0 is not None:
                        if max(self.spx[-61:]) - self.ref_price0 > 0.04*self.ref_price0 and max(self.mom[-13:])-self.ref_mom0>600:
                            self.set_trade(1.907) # yes

                        elif min(self.spx[-61:]) - self.ref_price0 <-0.04*self.ref_price0 and min(self.mom[-13:])-self.ref_mom0<-600:
                            self.set_trade(-1.907)  # yes

                    if (self.ir_date() and sec>3600*4.5 and sec<3600*4.5+60*10 and self.sec_since_last_sig> 18):
                        if self.mom[-1]-min(self.mom[-1-138:])>200 and max(self.spx[-610:]) - self.spx[-610] > 0.003*self.spx[-1]:
                            if self.spx[-1] > max(self.spx[-180:-60]) + 0.0015 * self.spx[-1]:
                                if self.rho[-1]-np.average(self.rho[-61:-51])<-c_0*0.24:
                                    self.set_trade(1.96) # yes
                                    if self.mom[-1]-min(self.mom[-1-138:])>300 and max(self.spx[-610:]) - self.spx[-610] > 0.004*self.spx[-1]:
                                        self.set_trade(1.976) # yes
                                        if self.mom[-1]-min(self.mom[-1-138:])>400 and max(self.spx[-610:]) - self.spx[-610] > 0.005*self.spx[-1]:
                                            self.set_trade(1.986) # yes

                        elif self.mom[-1]-min(self.mom[-1-62:])>200 and max(self.spx[-310:]) - self.spx[-310] > 0.003*self.spx[-1]:
                            if self.spx[-1] > max(self.spx[-140:-80]) + 0.0015 * self.spx[-1]:
                                if self.rho[-1]-np.average(self.rho[-41:-31])<-c_0*0.24:
                                    self.set_trade(1.951)  # yes
                        
                        if self.mom[-1]-max(self.mom[-1-138:])<-200 and min(self.spx[-610:]) - self.spx[-610] <-0.003*self.spx[-1]:
                            if self.spx[-1] <- min(self.spx[-180:-60]) - 0.0015 * self.spx[-1]:
                                if self.rho[-1]-np.average(self.rho[-61:-51])> +c_0*0.24:
                                    self.set_trade(-1.96) # yes
                                    if self.mom[-1]-max(self.mom[-1-138:])<-300 and min(self.spx[-610:]) - self.spx[-610] <- 0.004*self.spx[-1]:
                                        self.set_trade(-1.97) # yes
                                        if self.mom[-1]-max(self.mom[-1-138:])<-400 and min(self.spx[-610:]) - self.spx[-610] <- 0.005*self.spx[-1]:
                                            self.set_trade(-1.986)  # yes

                        elif self.mom[-1]-max(self.mom[-1-62:])<-200 and min(self.spx[-310:]) - self.spx[-310] <- 0.003*self.spx[-1]:
                            if self.spx[-1] < min(self.spx[-140:-80]) - 0.0015 * self.spx[-1]:
                                if self.rho[-1]-np.average(self.rho[-41:-31])>c_0*0.24:
                                    self.set_trade(-1.951)      # yes

                    if  self.with_ref_extreme() and len(self.mom)>1 and self.extreme_mom0 is not None and self.ref_mom0 is not None: #self.with_ref_extreme() and
                        if abs(self.extreme_mom0-self.mom[-1])<=0.1*(self.ref_mom0-self.extreme_mom0):
                            if is_rho_down_0 and self.normal_down and self.rho[-1]-self.ref_rho0>=adj_rho*0.09:
                                
                                True
                                self.set_trade(-1.12)  # yes
                                a=0.8
                                self.stop_loss= a*self.spx[-1] +(1-a)*max(self.spx[-181:])
                            elif is_rho_up_0 and self.normal_up and self.rho[-1]-self.ref_rho0<=adj_rho*0.09:
                                True
                                self.set_trade(1.12) # yes
                                a=0.8
                                self.stop_loss= a*self.spx[-1] +(1-a)*min(self.spx[-181:])

                if self.with_ref_extreme() and self.sec_since_last_sig>=N_Normal and self.sec_since_last_sig<=60*6.6:    
                   
                    spx_factor = self.spx[-1]/6000
                    H_0 = 0.7 
                    if self.ref_price0 is not None and self.extreme_price0 is not None:
                        if ir_rho_inaccurate_illiquid_period:
                                critical_px = self.ref_price0*0.82+0.18*self.extreme_price0
                        else:
                                critical_px = self.ref_price0*0.72+0.28*self.extreme_price0
                        critical_mom = self.ref_mom0*0.51+0.49*self.extreme_mom0
                    
                    if self.normal_up and self.mom[-1]>-1000:  ##simon???????????? if not self.is_high_vo l and
                        a= self.data_spx.close[0]-  max(self.spx[-12:-5]) 
                        b= self.data_spx.close[0]-  min(self.spx[-12:-6])   
                        print(time1,a,b,self.with_ref_extreme())
                        #,self.data_spx.close[-3],self.data_spx.close[-4] ???????? self.data_spx.close[0]-self.data_spx.close[-5]>0:    #??????? 0.05 0.5 反弹多少合适????????????
                        if self.ref_price0<self.extreme_price0 and self.spx[-1]>critical_px and self.mom[-1]>critical_mom:
                                if self.sell_super_sig_count==0 :
                                    if a>0.8 *spx_factor  and b>2.4 *spx_factor : # simon???????? #,self.data_spx.close[-3],self.data_spx.close[-4] ???????? self.data_spx.close[0]-self.data_spx.close[-5]>0:    #??????? 0.05 0.5 反弹多少合适????????????
                                        if self.rho_trend()>0  or ir_rho_inaccurate_illiquid_period or sec_to_close<60*15:
                                            if (self.mom[-1]-self.extreme_mom0)/(self.ref_mom0-self.extreme_mom0)<0.33 and \
                                            self.rho[-1]-max(self.rho[-13:-2])<-c_0*0.4:
                                                print(f"old buy normal with wait time :{a,b,self.data_spx.close[0],list_10,self.normal_down,self.big_up,self.current_min4,self.current_max4,self.normal_down,self.current_time_NY}")
                                                self.buy_trade(2.0) # yes

                                                self.set_stop_loss(True)
                                                self.stop_loss=self.ref_price0*0.8+0.2*self.spx[-1]
                    if self.normal_down and self.mom[-1]<1000:  ##simon????????????
                        a= self.spx[-1]- min (self.spx[-12:-5]) 
                        b= self.spx[-1]- max  (self.spx[-12:-6])   #,self.data_spx.close[-3],self.data_spx.close[-4] ???????? self.data_spx.close[0]-self.data_spx.close[-5]>0:    #??????? 0.05 0.5 反弹多少合适????????????
                        # print(self.current_time_NY,c_0,a,b,spx_factor,self.rho[-1]-min(self.rho[-13:-2]),\
                        #       self.mom[-1],self.ref_mom0,self.extreme_mom0,(self.mom[-1]-self.extreme_mom0)/(self.ref_mom0-self.extreme_mom0))
                        if self.ref_price0>self.extreme_price0 and self.spx[-1]< critical_px and self.mom[-1]<critical_mom:
                                if self.buy_super_sig_count==0 :
                                    print(time1,self.stop_loss,a,b,c_0,spx_factor,self.rho_trend(),max(self.rho[-25:-5])-min(self.rho[-20:-2]),\
                                          (self.mom[-1]-self.extreme_mom0)/(self.ref_mom0-self.extreme_mom0))
                                    if a<-0.8 *spx_factor and b<-2.4 *spx_factor:  #,self.data_spx.close[-3],self.data_spx.close[-4] ???????? self.data_spx.close[0]-self.data_spx.close[-5]>0:    #??????? 0.05 0.5 反弹多少合适????????????
                                        if max(self.rho[-25:-5])-min(self.rho[-20:-2])>c_0*0.2 or ir_rho_inaccurate_illiquid_period or sec_to_close<60*15:
                                            # self.rho_trend()<0 
                                            if (self.mom[-1]-self.extreme_mom0)/(self.ref_mom0-self.extreme_mom0)<0.33 and \
                                            max(self.rho[-25:-5])-min(self.rho[-20:-2])>c_0*0.2:
                                                print("Not Old sell normal with wait time a,b :")
                                                self.sell_trade(-2.0)   # yes    # simon
                                                self.stop_loss=self.ref_price0*0.8+0.2*self.spx[-1]
                                                print(self.stop_loss)

                    if self.sec_since_last_sig<61 and self.sec_since_last_sig>N_Normal+0:  ##simon????????????
                        if self.normal_down and self.rho_trend()<0 : # c_0_down > rho_threshold_local and c_0_up <=0 self.is_rho_change()<0: 
                                self.set_trade(-0.81) #############
                        if self.normal_up and self.rho_trend()>0 : # and c_0_up > rho_threshold_local and c_0_down <=0  self.is_rho_change()>0: 
                                self.set_trade(0.81) ############
                    
                    if sec_to_close<=60*15:
                        critical_mom = self.ref_mom0*0.9+0.1*self.extreme_mom0
                        critical_px = self.ref_price0*0.8+0.2*self.extreme_price0
                        spx_factor = spx_factor * 0.5
                                        
            if len(self.spx) > 241 and self.sec_since_last_sig>=18 and self.sec_since_last_sig<=241:  # 150s
                if not self.big_up and not self.big_up_2 and \
                    (self.big_down or self.normal_down): # (self.spx[-1]-max(self.spx[-91:-6]))<= -self.spx[-1]*0.001  # self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                    
                    if self.current_min12 <= -self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_down \
                            and (self.spx[-1]-max(self.spx[-241:-6]))<= -self.spx[-1]*0.001:
                        if self.rho_trend()<0 and not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)):  ##########################
                            self.set_trade(-1.82) # yes
                            print("-2yz")
                        elif abs(self.mom[-1]-self.ref_mom0)/abs(self.extreme_mom0-self.ref_mom0)>0.85 and \
                                abs(self.spx[-1]-self.ref_price0)/abs(self.extreme_price0-self.ref_price0)>0.85 and \
                                (self.rho[-1] - min(self.rho[-21:-9]))>0.24*c_0:
                            self.set_trade(-1.84) # yes
                            print("-2zz")
                       
                if not self.big_down and not self.big_down_2 and \
                    (self.big_up or self.normal_up):
                    if self.current_max12 >= self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_up \
                            and (self.spx[-1]-min(self.spx[-241:-6]))>= self.spx[-1]*0.001: # (self.spx[-1]-max(self.spx[-91:-6]))<= -self.spx[-1]*0.001  # self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                        if  (self.rho[-1]-min(self.rho[-1-21:-9]))/c_0< -0.24: # and (self.rho[-1]-max(self.rho[-1-21:-15]))/c_0<-0.12: # and \
                            if  self.rho_trend()>0 and not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)):# 
                                self.set_trade(1.82) # yes
                                print("+2yz")
                            elif abs(self.mom[-1]-self.ref_mom0)/abs(self.extreme_mom0-self.ref_mom0)>0.85 and \
                                abs(self.spx[-1]-self.ref_price0)/abs(self.extreme_price0-self.ref_price0)>0.85 and \
                                    -(self.rho[-1]-max(self.rho[-21:-9]))>0.24*c_0:
                                self.set_trade(1.84) # yes
                                print("+2zz")

            # current_time1 = bt.num2date(self.data_spx.datetime[0]).replace(tzinfo=pytz.utc).astimezone(ny_tz).time()
            if self.is_ir_date and (time(14, 0, 0) < time1 <= time(14, 4, 30)):
                if self.mom[-1]-self.ir_2pm_mom>200* self.symmetric_ratio_up: #if self.mom[-1]-self.ir_2pm_mom>200* self.symmetric_ratio_up:
                    self.set_trend(True)
                    self.longer_wait=True
                    self.set_trade(2) #2.05  1 or 2 simon
                    self.stop_loss=self.spx[-1]*0.2 + 0.8*self.ir_2pm_spx  #ref_price0
                    self.stop_loss_mom=self.mom[-1]*0.2 + 0.8*self.ir_2pm_mom #ref_mom0
                elif self.mom[-1]-self.ir_2pm_mom <= - 200 * self.symmetric_ratio_down:#self.ir_2pm_mom-self.mom[-1] <= - 200 * self.symmetric_ratio_down:
                    self.set_trend(False)
                    self.longer_wait=True
                    self.set_trade(-2) #  2.05  1 or 2 simon
                    self.stop_loss=self.spx[-1]*0.2 + 0.8*self.ir_2pm_spx #ref_price0
                    self.stop_loss_mom=self.mom[-1]*0.2 + 0.8*self.ir_2pm_mom #ref_mom0
                    print(time1,self.spx[-1],self.mom[-1],self.ir_2pm_mom,self.ir_2pm_spx,self.stop_loss,\
                          self.ref_price0, self.ref_mom0,self.extreme_price0, self.extreme_mom0)

            if self.fed_news_at_2pm():
                threshold_Fed_news_2pm=150 #150   50  100 25-30 simon ???????? ???????? ????????
                
                if self.current_max4>threshold_Fed_news_2pm* self.symmetric_ratio_up:
                    self.set_trend(True)
                    self.longer_wait=True
                    self.set_trade(2) # 1 or 2 simon
                    self.stop_loss=self.spx[-1]*0.2 + 0.8*self.ir_2pm_spx  #ref_price0

                    # self.set_stop_loss()
                    if self.current_max4>= 200* self.symmetric_ratio_up:
                        self.set_trade(3.0) # 1 or 2 simon
                    
                elif self.current_min4 <= - threshold_Fed_news_2pm * self.symmetric_ratio_down:
                    self.set_trend(False)
                    self.longer_wait=True
                    self.set_trade(-2) # 1 or 2 simon
                    self.stop_loss=self.spx[-1]*0.2 + 0.8*self.ir_2pm_spx #ref_price0
                    if self.current_min4<= -200* self.symmetric_ratio_down:
                        self.set_trade(-3.0) # 1 or 2 simon
                        self.set_stop_loss()
                        # self.longer_wait=False
                    
            if sec> 5.20*3600-60 and not self.ir_date() and R_30_min<1.2: # and sec_to_close<60*60: # not half day
                if   self.rho[-1] - max(self.rho[-6:-2])<-c_0*0.4 and self.mom[-1]-min(self.mom[-12*3-1:-2])> 150*adj_ratio:
                    print(time1,R_30_min) # weak and reverse market
                    print('buy')
                   
                elif self.rho[-1] - min(self.rho[-6:-2])> c_0*0.4 and self.mom[-1]-max(self.mom[-12*3-1:-2])<-150*adj_ratio:
                    print(time1,R_30_min)
                    print('sell')
                    
            if len(self.mom)>60:
                if self.spx[-1] >= min(self.spx[-36:-11])+0.0025*self.spx[-1]*max(adj_ratio,1)\
                        and self.spx[-1] >= max(self.spx[-36:-11])+0.002*self.spx[-1]*max(adj_ratio,1)\
                                and self.buy_super_sig_count<=0 :
                                self.set_trade(2)
                                self.longer_wait=True
                                if self.current_min4>-self.current_max4 >= self.p.strong_threshold * self.symmetric_ratio_up:
                                    if self.spx[-1] >= min(self.spx[-36:-11])+0.003*self.spx[-1]*max(adj_ratio,1)\
                        and self.spx[-1] >= max(self.spx[-36:-11])+0.0025*self.spx[-1]*max(adj_ratio,1):
                                        self.set_trade(3.25)
                                        self.longer_wait=False
              # not self.position 
                elif self.spx[-1] <= max(self.spx[-36:-11])-0.0025*self.spx[-1]*max(adj_ratio,1)\
                        and self.spx[-1] <= min(self.spx[-36:-11])-0.002*self.spx[-1]*max(adj_ratio,1)\
                                and self.buy_super_sig_count<=0 :
                                self.set_trade(-2)
                                self.longer_wait=True
                                if self.current_min4<-self.p.strong_threshold * self.symmetric_ratio_down:
                                    if self.spx[-1] <= max(self.spx[-36:-11])-0.003*self.spx[-1]*max(adj_ratio,1)\
                        and self.spx[-1] <= min(self.spx[-36:-11])-0.0025*self.spx[-1]*max(adj_ratio,1):
                                        self.set_trade(-3.25)
                                        self.longer_wait=False
            if sec_to_close<60*30 and self.abs_mom[-37] - self.abs_mom[-37-36]<16:
                range_max_6,range_min_6,index_max_6,index_min_6=self.range_N(6)

                if self.mom[-1]-max(self.mom[-25:-2])<-200: 
                    print(time1,self.rho[-1]-min(self.rho[-9:-2]),c_0,self.mom[-1]-max(self.mom[-25:-2])-range_min_6,self.mom[-1]-max(self.mom[-25:-2]), range_min_6, self.abs_mom[-37] - self.abs_mom[-37-36])
                if self.mom[-1]-max(self.mom[-25:-2])<-200 and self.mom[-1]-max(self.mom[-25:-2])-range_min_6<-50:
                    if self.rho[-1]-min(self.rho[-9:-2])>c_0*0.24 and 1-self.spx[-1]/max(self.spx[-181:-2])>0.00225:
                        print('short end ')
                        self.longer_wait=True
                        self.set_trade(-2)
                        
                elif self.mom[-1]-min(self.mom[-25:-2])>200 and self.mom[-1]-min(self.mom[-25:-2])-range_max_6>50:
                    if self.rho[-1]-max(self.rho[-9:-2])>-c_0*0.24 and self.spx[-1]/min(self.spx[-181:-2])-1>0.00225:
                        self.longer_wait=True
                        self.set_trade(2)
            
            if self.current_max4 >= self.p.strong_threshold * self.symmetric_ratio_up: 
                self.normal_up=True
                if self.mom[-2]+self.mom[-3]+self.mom[-4]>50 and \
                    (self.data_spx.close[0]>self.spx_high2) and (self.data_spx.close[0]-self.spx_low2)>= self.data_spx.close[0]*0.00172  : #  self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                  
                    if (self.spx[-1]>max(self.spx[-91:-36])+0.00172*self.spx[-1] \
                        and self.spx[-1]>min(self.spx[-91:-6])+0.0022*self.spx[-1]\
                            and self.spx[-1]>max(self.spx[-11:-3])-1) \
                                or (self.spx[-1]>max(self.spx[-11:-3])+1 and self.spx[-1]>max(self.spx[-11:-1])) and \
                                    self.spx[-1] >= min(self.spx[-61:-2])+0.00265*self.spx[-1]*max(adj_ratio,1):# and self.spx[-1]>max(self.spx[-61:-20])+0.00135*self.spx[-1] :
                        # if self.spx[-1]>max(self.spx[-300:-20])+0.001*self.spx[-1] :# and self.spx[-1]>max(self.spx[-61:-20])+0.00135*self.spx[-1] :
                        self.set_trend(True)
                        self.set_trade(3)
                        if self.current_max4 >= 1.25* self.p.strong_threshold * self.symmetric_ratio_up*max(adj_ratio,1) and \
                            self.spx[-1] >= min(self.spx[-61:-2])+0.00265*self.spx[-1]*max(adj_ratio,1):
                            self.set_trade(3.5)
                            if self.spx[-1] >= min(self.spx[-91:-36])+0.00285*self.spx[-1]*max(adj_ratio,1):
                                self.set_trade(4.5)

                        if self.spx[-1] >= min(self.spx[-91:-36])+0.00285*self.spx[-1]*max(adj_ratio,1) \
                            and self.spx[-1] >= max(self.spx[-91:-36])-0.0025*self.spx[-1]*max(adj_ratio,1)\
                             and self.sell_super_sig_count<=0 :
                            self.set_trade(4.2)
            
            elif self.current_min4 <= - self.p.strong_threshold * self.symmetric_ratio_down:
                self.normal_down=True
                if self.mom[-2]+self.mom[-3]+self.mom[-4]<-50 and \
                (self.data_spx.close[0]<self.spx_low2) and (self.data_spx.close[0]-self.spx_high2)<= -self.data_spx.close[0]*0.00172: #  self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                    if (self.spx[-1]<min(self.spx[-91:-36])-0.00172*self.spx[-1] \
                        and self.spx[-1]<max(self.spx[-91:-6])-0.0022*self.spx[-1]\
                            and self.spx[-1]<min(self.spx[-11:-3])+1)\
                                 or (self.spx[-1]<min(self.spx[-11:-3])-1 and self.spx[-1]<min(self.spx[-11:-1])) and \
                                    self.spx[-1] <= max(self.spx[-61:-2])-0.00265*self.spx[-1]*max(adj_ratio,1):# and self.spx[-1]<min(self.spx[-61:-20])-0.00135*self.spx[-1] :
                        self.set_trend(False)
                        self.set_trade(-3)
                        self.longer_wait=False
                        if self.current_min4 <= 1.25* self.p.strong_threshold * self.symmetric_ratio_down*max(adj_ratio,1) and \
                            max(self.spx[-61:-2])-self.spx[-1]>0.00265*self.spx[-1]*max(adj_ratio,1):
                            self.set_trade(-3.5)
                            self.longer_wait=False
                            if self.spx[-1] <= max(self.spx[-91:-36]) - 0.00285*self.spx[-1]*max(adj_ratio,1):
                                self.set_trade(-4.5)
                                self.longer_wait=False

                        if self.spx[-1] <= max(self.spx[-91:-36])-0.00285*self.spx[-1]*max(adj_ratio,1)\
                            and self.spx[-1] <= min(self.spx[-91:-36])-0.0025*self.spx[-1]*max(adj_ratio,1)\
                            and self.buy_super_sig_count<=0 :
                            self.set_trade(-4.2)
                            self.longer_wait=False
            
            elif not self.big_down and not self.big_down_2 and self.current_max4 >=  self.enlarge_3_min()* self.p.sig_threshold *max(adj_ratio,1)* self.symmetric_ratio_up \
                and (self.data_spx.close[0]>self.spx_high2) : #  self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                    if  self.spx[-1]>max(self.spx[-91:-46])+0.001*self.spx[-1]\
                          and (self.spx[-1]-min(self.spx[-91:-6]))>= self.spx[-1]*0.00152\
                            and not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)): #not allow_normal: # noon time
                        print("+2a")
                        self.normal_up=True
                        self.set_trend(True)
                        if not self.is_high_vol: # 10am
                            self.longer_wait=True
                            if sec>30*60 and sec<3260:
                                self.set_trade(2) 
                            else:
                                self.set_trade(2)

            elif not self.big_up and not self.big_up_2 and self.current_min4 <= -self.enlarge_3_min()* self.p.sig_threshold *max(adj_ratio,1)* self.symmetric_ratio_down \
                    and (self.data_spx.close[0]<self.spx_low2) : #  self.data_spx.close[0]*self.p.mim_increment_super_pct : #  :  # spx not drop #self.adj2:            # 也可以用等待方式 delay:
                    if self.spx[-1]<min(self.spx[-91:-46])-0.001*self.spx[-1]\
                          and (self.spx[-1]-max(self.spx[-91:-6]))<= -self.spx[-1]*0.00152 \
                            and not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)): #not allow_normal: # noon time
                        print("-2a")
                        self.normal_down=True
                        
                        self.set_trend(False)
                        if not self.is_high_vol:
                            self.longer_wait=True 
                            if sec>30*60 and sec<3260:
                                self.set_trade(-2) # 
                            else:
                                self.set_trade(-2) 
            
            ## 高波动天 case3a b 不用             # 计算前3分钟累计的d_mom之和
            elif self.can_trade_consistent_trend() and len(self.mom) > 48+1 :  # 150s
                # not self.ir_date() ?simon
                
                if not self.ir_date() and self.is_low_vol :# and self.buy_count ==0
                 
                    T_0=np.power(R_all*R_30_min,1/2)
                    R_extra=1 # R_extra=np.power(adj_ratio,0.5) 

                    #  下面考虑用min6 and max6  or min6/T_0<-90*R_extra
                    if (self.rho[-1]-min(self.rho[-33:])) >= c_0*0.24 and (min4<-T_0*82.5*R_extra ) \
                        and (self.abs_mom[-1-1]-self.abs_mom[-61]-1)/(max(self.mom[-61-1:-2-1])-self.mom[-1-1])<1.5:
                        if (self.abs_spx[-1-5]-self.abs_spx[-301-5])/(max(self.spx[-301-5:-2-5])-self.spx[-1-5])<3.5 \
                            and max(self.spx[-301-5:-2-5])-self.spx[-1-5]>=0.00135*self.spx[-1] \
                                and self.spx[-1]<min(self.spx[-61:-6]) :# and is_rho_down: 
                                self.set_trend(False)
                                if min4/T_0<-400*R_extra: # or max6/T_0<-450*R_extra:   # simon????????????200 or 225  , min6/max6????????? 
                                    if time1>time(11,38,0) and time1<time(14,14,0) or self.big_up or self.big_up_2:
                                        if  self.rho_trend()<0 : #is_rho_down_0 : # self.is_rho_change(0.24)<0:
                                            self.longer_wait=True
                                            self.set_trade(-1.62) # 
                                            
                                        print("-2b")
                                    else:
                                        if  self.rho_trend()<0 : # self.is_rho_change(0.24)<0:
                                            self.set_trade(-1.3)
                                elif (min4/T_0<-200*R_extra and min4/T_0>-400*R_extra) :#or min6/T_0<-300*R_extra:
                                    if self.rho_trend()<0:
                                        self.longer_wait=True
                                        self.set_trade(-1.48) # 
                                           # ????????????simon a b\ # 不需要 and (self.data_spx.close[0]-self.spx_low2)>= self.data_spx.close[0]*0.00152
                                        print("-2c")
                                elif min4/T_0>-200*R_extra: # and min6/T_0<-90*R_extra and min6/T_0>-300*R_extra: # ????????????simon a b\
                                    if time1>time(11,38,0) and time1<time(14,14,0) or self.big_up or self.big_up_2: #Simon??????????????? rho
                                        if  self.rho_trend()<0 : # self.is_rho_change(0.24)<0:
                                            self.longer_wait=True
                                            self.normal_down=True
                                            self.set_trade(-1.942) # 
                                             # 不需要 and (self.data_spx.close[0]-self.spx_low2)>= self.data_spx.close[0]*0.00152
                                        print("-2d")
                                    else:
                                        if  self.rho_trend()<0: # is_rho_down_0 : # self.is_rho_change(0.24)<0:
                                            self.set_trade(-0.251)
                                            self.stop_loss = self.spx[-1]+3
                                        # 下面考虑用min6 and min6   or max6/T_0>90*R_extra
                    elif (max(self.rho[-33:])-self.rho[-1]) >= c_0*0.24 and (max4>T_0*82.5*R_extra ) \
                        and (self.abs_mom[-1-1]-self.abs_mom[-61-1])/(self.mom[-1-1]-min(self.mom[-61-1:-2-1]))<1.5: 
                        if (self.abs_spx[-1-5]-self.abs_spx[-301-5])/(self.spx[-1-5]-min(self.spx[-301-5:-2-5]))<3.5 \
                            and self.spx[-1-5]-min(self.spx[-301-5:-2-5])>=0.00135*self.spx[-1]\
                                and self.spx[-1]>max(self.spx[-61:-6]) : # and is_rho_up:
                            self.set_trend(True)
                            if  max4/T_0>400*R_extra: # or max6/T_0>450*R_extra:   # simon????????????200 or 225  , min6/max6????????? 
                                if time1>time(11,38,0) and time1<time(14,14,0) or self.big_down or self.big_down_2:
                                    print("type2 b")
                                    if  self.rho_trend()>0: #is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.longer_wait=True
                                        self.normal_up=True
                                        
                                        self.set_trade(1.942) # 
                                else:
                                    if  self.rho_trend()>0: # is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.set_trade(1.3)
                            elif (max4/T_0>200*R_extra and max4/T_0<400*R_extra)  :#or max6/T_0>300*R_extra:
                                print("type2 c")
                                if  self.rho_trend()>0: #is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                    self.longer_wait=True
                                    self.set_trade(1.44) # 
                                     # ????????????simon a b\  #不需要 and (self.data_spx.close[0]-self.spx_low2)>= self.data_spx.close[0]*0.00152
                            elif max4/T_0<200*R_extra : # and max6/T_0>90*R_extra and max6/T_0<300*R_extra: # ????????????simon a b\
                                if time1>time(11,38,0) and time1<time(14,14,0) or self.big_down or self.big_down_2: #?????????????Simon??????????????? rho
                                    print("type2 d")
                                    if  self.rho_trend()>0: # is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.longer_wait=True
                                        self.set_trade(1.40)   
                                         # 不需要 and (self.data_spx.close[0]-self.spx_low2)>= self.data_spx.close[0]*0.00152
                                else:
                                    if  self.rho_trend()>0: # is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.set_trade(0.251)
                                        self.stop_loss = self.spx[-1]-3
                    
                    a_1=self.spy_close[-1-1]/min(self.spy_close[-1-48-1:-6-1])-1
                    a_2=self.spy_close[-1-1]/max(self.spy_close[-1-48-1:-6-1])-1
                    up_long=(self.mom[-1-1]-min(self.mom[-1-48-1:-6-1]))/adj_ratio #48 = 4 min
                    up_short=(self.mom[-1-1]-min(self.mom[-1-12-1:-2-1]))/adj_ratio
                    down_long=(self.mom[-1-1]-max(self.mom[-1-48-1:-6-1]))/adj_ratio
                    down_short=(self.mom[-1-1]-max(self.mom[-1-12-1:-6-1]))/adj_ratio
                    
                    if up_long> 150   and a_1   >+0.00135 and self.spx[-1]-max(self.spx[-61:-20])>2: #0.001-0.0014
                        
                            self.set_trend(True)
                            self.normal_up=True
                            if  up_short> 450 and is_rho_up_0:# and self.mom[-1]-min(self.mom[-1-12:-1]>150: 
                        
                                if self.rho_trend()>0: # 
                                    self.set_trade(1.9) 
                            elif up_short>200 and is_rho_up_0: 
                                print("type2 e")
                                if  self.rho_trend()>0  : # self.is_rho_change(0.24)>0:
                                    self.longer_wait=True
                                    self.set_trade(1.92) # 
                                     
                    elif down_long<-150 and a_2   <-0.00135 and self.spx[-1]-min(self.spx[-61:-20])<-2:
                        
                            self.set_trend(False)
                            if  down_short<-450 and is_rho_down_0:# and self.mom[-1]-max(self.mom[-1-12:-6])<-150: 
                        
                                if self.rho_trend()<0: # 
                                    self.set_trade(-1.9) 
                            elif down_short<-200 and is_rho_down_0: 
                                if self.rho_trend()<0: #  if  True : # self.is_rho_change(0.24)<0:
                                    self.longer_wait=True
                                    self.set_trade(-1.71) # 
                                    
                                    print("-2x")
                                    print(time1)
                                
                    # still missing +/-0.xxx case ?????????simon

                one_min_trend = self.one_min_trend_entry(adj_ratio)
                if one_min_trend > 0 and self.spx[-1]>max(self.spx[-61:-20]):                     
                    self.set_trend(True)
                    if self.rho_trend()>0: # is_rho_up_0 : # self.is_rho_change(0.24)>0:
                        # p rint( self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                        self.set_trade(1.081) 
                elif one_min_trend < 0 and self.spx[-1]<min(self.spx[-61:-20]):
                    self.set_trend(False)
                    if self.rho_trend()<0: # is_rho_down_0 : # self.is_rho_change(0.24)<0:
                        # p rint( self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                        self.set_trade(-1.081) 
                else:
                    list_30=list(self.data_spx.close.get(size=30))[:-10]
                    list_60=list(self.data_spx.close.get(size=60))[:-10]
                    A_75 = 75 * adj_ratio * self.enlarge_3_min() * self.symmetric_ratio_down
                    range_max_15,range_min_15,index_max_15,index_min_15=self.range_N(15)
                    range_max_12,range_min_12,index_max_12,index_min_12=self.range_N(12)
                    range_max_9,range_min_9,index_max_9,index_min_9=self.range_N(9)
                    range_max_6,range_min_6,index_max_6,index_min_6=self.range_N(6)
                    range_max_3,range_min_3,index_max_3,index_min_3=self.range_N(3)
                    range_max_2,range_min_2,index_max_2,index_min_2=self.range_N(2)
                    range_max_1,range_min_1,index_max_1,index_min_1=self.range_N(1)

                    # d_mom_sum_6 = self.data_momentum.volume[0]+self.data_momentum.volume[-1]+self.data_momentum.volume[-2]+self.data_momentum.volume[-3]+self.data_momentum.volume[-4]+self.data_momentum.volume[-5]
                    # case 3a 看涨条件
                    # if bullish_bars and self.current_max4 > self.p.medium_threshold * self.ratio_up and bullish_consistency and self.data_momentum.close[-6]>-600: # <=-600 说明当日大跌
                    # elif bearish_bars and self.current_min4 <- self.p.medium_threshold * self.ratio_down and bullish_consistency and self.data_momentum.close[-6]<600: # <=-600 说明当日大涨
                    # # elif bearish_bars and min4 <- self.p.medium_threshold * self.adj2 and bearish_consistency and self.data_momentum.close[-6] < 500: # >=-500 说明当日大涨
                    # case 3b 看涨条件 second_last_three = list(self.data_momentum.volume.get(size=4))[:-3]  #simon to check for
                    
                    #self.data_spx.close[0]<min(list_10)  # list_10=list(self.data_spx.close.get(size=10))[:-5] #???? simon to check for 15 or 10  simon
                        
                    if not self.big_down and not self.big_down_2 and bullish_bars and self.spx[-1]>max(list_10) and \
                        d_mom_sum_180s > adj_ratio* 150  * self.symmetric_ratio_up and mom_trend_30s > adj_ratio* 75  * self.symmetric_ratio_up and \
                        abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11 and \
                        abs_mom_trend_120s - abs(mom_trend_120s)<abs_mom_trend_120s/6 and self.spx[-1-5]-min(self.spx[-181-5:-151-5])>0.002*self.spx[-1]: # 140 or 150-180    60-90       
                            
                            if d_mom_sum_180s - range_max_6 > adj_ratio* 0.95* 75*self.symmetric_ratio_up\
                            and mom_trend_30s-range_max_3>adj_ratio*  0.1 *75  * self.symmetric_ratio_up\
                                and mom_trend_30s-range_max_2> adj_ratio* 0.3 *75  * self.symmetric_ratio_up\
                                    and mom_trend_30s-range_max_1> adj_ratio* 0.5 *75  * self.symmetric_ratio_up and \
                                        self.spx[-1]>max(self.spx[-61:-21]) : # spx 
                                # p rint(self.ny,d_mom_sum_180s , range_max_6,mom_trend_30s)
                                # p rint(R_all,R_30_min,R_3_min,R_1_min)
                                self.set_trend(True)
                                if self.rho_trend()>0: # if  is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                    self.set_trade(1.01) # no waiting time 1.1
                    elif not self.big_up and not self.big_up_2 and bearish_bars and self.spx[-1]<min(list_10) and \
                        d_mom_sum_180s <- adj_ratio* 150  * self.symmetric_ratio_down and mom_trend_30s <-adj_ratio*  75  * self.symmetric_ratio_down  and \
                        abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11 and \
                        abs_mom_trend_120s - abs(mom_trend_120s)<abs_mom_trend_120s/6 and  (self.spx[-1-5]-max(self.spx[-181-5:-151-5]))<-0.002*self.spx[-1] : #and \
                         #and self.spx[-1]<max(self.spx[-11:-6])  140 or 150-180    60-90
                            if d_mom_sum_180s - range_min_6 < -adj_ratio* 0.95* 75*self.symmetric_ratio_down\
                            and mom_trend_30s-range_min_3< -adj_ratio* 0.1 *75  * self.symmetric_ratio_down\
                                and mom_trend_30s-range_min_2< -adj_ratio* 0.3 *75  * self.symmetric_ratio_down\
                                    and mom_trend_30s-range_min_1< -adj_ratio* 0.5 *75  * self.symmetric_ratio_down  and \
                                        self.spx[-1]<min(self.spx[-61:-21]):  # spx 
                                # p rint(R_all,R_30_min,R_3_min,R_1_min)
                                self.set_trend(False)
                                if self.rho_trend()<0: # if  is_rho_down_0 : # self.is_rho_change()<0:
                                    # prin t(self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                                    self.set_trade(-1.01)   #-1.1
                    # new  shorter than 3min for high vol
                    elif not self.big_down and not self.big_down_2 and bullish_bars and self.spx[-1]>max(list_10) and \
                        d_mom_sum_90s> adj_ratio*75*self.symmetric_ratio_up   and d_mom_sum_sec_last_90s> adj_ratio*75*self.symmetric_ratio_up: # 140 or 150-180    60-90       
                            if d_mom_sum_180s - range_max_6 > adj_ratio*0.75* 75*self.symmetric_ratio_up \
                            and d_mom_sum_180s -range_max_3>adj_ratio*0.85* 75*self.symmetric_ratio_up \
                                and d_mom_sum_180s -range_max_2>adj_ratio*0.95* 75*self.symmetric_ratio_up \
                                    and d_mom_sum_180s -range_max_1>adj_ratio*1.05* 75*self.symmetric_ratio_up :# and \
                                # not self.normal_up and
                                if self.spx[-1]-min(self.spx[-181:-1])>0.00145*self.spx[-1] \
                                    and self.spx[-1]-max(self.spx[-11:-6])>0:  #simon????
                                # (self.data_spx[0]-min(self.data_spx[-10],self.data_spx[-9],self.data_spx[-8],self.data_spx[-7],self.data_spx[-6]))>0.0:
                                    self.set_trend(True)
                                    if self.rho_trend()>0: # if  is_rho_up_0: #c_0_up > 0.45 and c_0_down <-0.2: #  self.is_rho_change()>0:
                                        # p rint(self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                                        if not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)):
                                            if self.R_3_min<0.6:
                                                self.set_trade(1.72) # no waiting time
                                        
                    elif not self.big_up and not self.big_up_2 and bearish_bars and self.spx[-1]<min(list_10) and \
                        d_mom_sum_90s<-adj_ratio*75*self.symmetric_ratio_down and d_mom_sum_sec_last_90s<-adj_ratio*75*self.symmetric_ratio_down: # 140 or 150-180    60-90
                            # p rint(d_mom_sum_90s,self.current_time_NY,d_mom_sum_sec_last_90s,self.rho[-1],self.rho[-7],adj_ratio)
                            # p rint(d_mom_sum_180s , range_min_6 ,-adj_ratio*0.8* 75*self.symmetric_ratio_down)
                            # p rint(d_mom_sum_180s ,range_min_2,range_min_1,-adj_ratio*1* 75*self.symmetric_ratio_down)
                            # p rint(d_mom_sum_180s -range_min_1<-adj_ratio*1.05* 75*self.symmetric_ratio_down)
                            if d_mom_sum_180s - range_min_6 <-adj_ratio*0.75* 75*self.symmetric_ratio_down\
                            and d_mom_sum_180s -range_min_3<-adj_ratio*0.85* 75*self.symmetric_ratio_down \
                                and d_mom_sum_180s -range_min_2<-adj_ratio*0.95* 75*self.symmetric_ratio_down \
                                    and d_mom_sum_180s -range_min_1<-adj_ratio*1.05* 75*self.symmetric_ratio_down:
                                
                                if -(self.spx[-1]-max(self.spx[-181:-1]))>0.00145*self.spx[-1] \
                                    and self.spx[-1]-min(self.spx[-11:-6])<0:  #simon????
                                    # p rint(self.current_time_NY,adj_ratio,R_all,R_30_min,R_3_min,R_1_min,)
                                    # p rint(d_mom_sum_90s,d_mom_sum_sec_last_90s)
                                    # True
                                    # if self.rho[-1]- min(self.rho[-14:-1]>=0.18* c_0:
                                        self.set_trend(False)
                                        if self.rho_trend()<0: #  if  is_rho_down_0 : # or (c_0_down > 0.45 and c_0_up <-0.2): #self.is_rho_change()<0: #c_0_down > 0.24 and c_0_up<-0.12: #                                 
                                            if not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)):
                                                if self.R_3_min<0.6:
                                                    self.set_trade(-1.72)
                                                    # print(self.R_3_min)
                    elif not(self.entry_type0=="short")  \
                        and max4< 8 and d_mom_sum_90s <-A_75 \
                        and d_mom_sum_45s <-A_75/2.05 \
                            and d_mom_sum_sec_last_90s<-A_75 and -(self.spx[-1-5]-max(self.spx[-181-5-1:-151-5]))>0.002*self.spx[-1]: # 140 or 150-180    60-90
                        if self.spx[-1]<min(list_10):
                            self.set_trend(False)                    
                            if not self.news_10am():
                                if self.spx[-1]<min(list_30) : #simon??????????
                                    # self.set_trend(False)
                                    if self.rho_trend()<0: # if  is_rho_down_0 : # self.is_rho_change(0.24)<0:
                                        self.set_trade(-1.3)                    # p rint(self.current_time_NY,min4,max4,self.mom[-1]-self.mom[-1-18],self.symmetric_ratio_down,self.mom[-1-18]-self.mom[-1-36])                    # p rint(f"weekday ={self.univ_10am()}")
                            else: 
                                if self.spx[-1]<min(list_60) :
                                    # self.set_trend(False)
                                    if self.rho_trend()<0: # if  is_rho_down_0 : # self.is_rho_change(0.24)<0:
                                        self.set_trade(-1.31)
                                else:
                                    self.longer_wait = True
                                    # self.set_trend(False)
                                    if self.rho_trend()<0: # if  is_rho_down_0 : # self.is_rho_change(0.24)<0: 
                                        self.longer_wait=True
                                        self.set_trade(-1.8) # 
                                        
                                    print("2f")
                    # and not self.normal_up  to be tested
                    elif not(self.entry_type0=="long")  \
                        and min4> -8 and d_mom_sum_90s> A_75 \
                        and d_mom_sum_45s>A_75/2.05 \
                            and d_mom_sum_sec_last_90s>A_75 and (self.spx[-1-5]-min(self.spx[-181-5-1:-151-5]))>0.002*self.spx[-1]: # 140 or 150-180    60-90
                        if self.spx[-1]>max(list_10):                    # p rint(self.current_time_NY,min4,max4,self.mom[-1]-self.mom[-1-18],self.symmetric_ratio_down,self.mom[-1-18]-self.mom[-1-36])                    # p rint(f"weekday ={self.univ_10am()}")
                            self.set_trend(True)
                            if not self.news_10am():
                                if self.spx[-1]>max(list_30) :
                                    # p rint(self.current_time_NY,adj_ratio,R_30_min,R_3_min,R_1_min   )
                                    if self.rho_trend()>0: # if  is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.set_trade(1.333)
                            else: 
                                if self.spx[-1]>max(list_60) :
                                    if self.rho_trend()>0: # if  is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.set_trade(1.34)
                                else:
                                    
                                    print("type2 f")
                                    if self.rho_trend()>0: # if  is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                        self.longer_wait=True
                                        self.set_trade(1.82) # 
                                        
                    elif True : 
                        # not(self.current_min4 <= -self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_down) and \
                        #     not(self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_up):
                        
                        if not(self.current_min4 <= -self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_down) and \
                            not(self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_up) and \
                            not self.big_up and not self.big_up_2 and\
                            not self.normal_up and not self.normal_down and\
                            self.spx[-1-5]<min(self.spx[-21:-11])\
                            and R_all<2 and R_30_min<1.8 and R_3_min<4 and R_1_min<5.5: #and R_30_min<2.5   R_30_min<3
                            # R_all_0 = max(0.5,R_all/3.2,R_30_min/4,R_3_min/5,R_1_min/7) # spx range  #and bearish_bars
                            X_0=2.9
                            # time change 3.50 
                            A_0=90 if sec<23084 -5*60 else 45 # smaller for late time ?????simon
                            R_all=max(2.4,R_all) 
                            if self.mom[-1-1]-max(self.mom[-1-30-1:-1-27-1]) <- 150*max(1.2,R_all)/X_0 \
                                and self.spx[-1-5]-self.spx[-75-1-5]<-0.0008*self.spx[-1] and self.spx[-75-6]-self.spx[-150-5-1]<-0.001*self.spx[-1]\
                                    and self.mom[-1-1]-max(self.mom[-1-30-1:-1-1])- range_min_6<- 0.33 *150*R_all/X_0 \
                                        and 1-abs(mom_trend_30s)/abs_mom_trend_30s<1/11\
                                            and 1-abs(mom_trend_120s)/abs_mom_trend_120s<1/7 \
                                                and self.mom[-1-1]-self.mom[-1-15-1] <-0.4* 150*R_all/X_0\
                                                    and self.mom[-1-15-1]-self.mom[-1-30-1] <-0.4* 150*R_all/X_0\
                                                        and self.spx[-1]-min(self.spx[-11:-6])<0: 
                                    # and (abs_mom_trend_30s - abs(mom_trend_30s))<=abs_mom_trend_30s/6\
                                    #     and (abs_mom_trend_120s - abs(mom_trend_120s))<=abs_mom_trend_120s/11\            #         and True:
                                self.set_trend(False)
                                if self.rho_trend()<0: # if  is_rho_down_0 : # self.is_rho_change(0.24)<0:
                                    self.set_trade(-0.451)   #-1.1
                                # p rint(self.mom[-1]-self.mom[-1-30]- range_min_6, 150*R_all/X_0 *0.35\
                                #     ,self.mom[-1]-self.mom[-1-16] ,self.mom[-1-16]-self.mom[-1-30],\
                                #         mom_trend_120s,range_min_6,R_30_min,R_all,R_3_min,R_1_min,-150*R_all/X_0,\
                                #     mom_trend_30s*R_all/X_0,(mom_trend_30s),abs_mom_trend_30s,\
                                #        (mom_trend_120s),abs_mom_trend_120s,\
                                #       self.data_spx[0],self.data_spx[-75],self.data_spx[-150],self.data_spx[0]-self.data_spx[-75],self.data_spx[-75]-self.data_spx[-150],
                                #     d_mom_sum_180s,self.current_time_NY,sec,self.vol_ratio,R_all,R_1_min,R_3_min, self.vol_ratio/R_all)

                        elif not(self.current_min4 <= -self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_down) and \
                            not(self.enlarge_3_min()* self.p.sig_threshold *adj_ratio* self.symmetric_ratio_up) and \
                                not self.big_down and not self.big_down_2 and \
                            not self.normal_up and not self.normal_down and\
                            self.spx[-6]>max(self.spx[-21:-11])\
                            and R_all<2 and R_30_min<1.8 and R_3_min<4 and R_1_min<5.5: #and R_30_min<2.5   R_30_min<3
                            # R_all_0 = max(0.5,R_all/3.2,R_30_min/4,R_3_min/5,R_1_min/7) # spx range  #and bearish_bars
                            X_0=2.9
                            # time change 3.50 
                            R_all=max(2.4,R_all)
                            A_0=90 if sec<23084 -5*60 else 45 # smaller for late time ?????simon
                            if self.mom[-1-1]-min(self.mom[-1-30-1:-1-27-1]) > 150*R_all/X_0 \
                                and self.spx[-1-5]-self.spx[-75-6]>0.0008*self.spx[-1] and self.spx[-75-6]-(self.spx[-151-6])>0.001*self.spx[-1]\
                                    and self.mom[-1-1]-min(self.mom[-1-30-1:-1-1])- range_max_6> 0.33 *150*R_all/X_0 \
                                        and 1-abs(mom_trend_30s)/abs_mom_trend_30s<1/11\
                                            and 1-abs(mom_trend_120s)/abs_mom_trend_120s<1/7 \
                                                and self.mom[-1-1]-self.mom[-1-15-1] >0.4* 150*R_all/X_0\
                                                    and self.mom[-1-15-1]-self.mom[-1-30-1] >0.4* 150*R_all/X_0\
                                                        and self.spx[-1]-max(self.spx[-11:-6])>0: 
                                    # and (abs_mom_trend_30s - abs(mom_trend_30s))<=abs_mom_trend_30s/6\
                                    #     and (abs_mom_trend_120s - abs(mom_trend_120s))<=abs_mom_trend_120s/11\            #         and True:
                                self.set_trend(True)
                                if self.rho_trend()>0: # if  is_rho_up_0 : # self.is_rho_change(0.24)>0:
                                    self.set_trade(0.451)   #-1.1
                                # p rint(self.mom[-1]-self.mom[-1-30]- range_min_6, 150*R_all/X_0 *0.35\
                                #     ,self.mom[-1]-self.mom[-1-16] ,self.mom[-1-16]-self.mom[-1-30],\
                                #         mom_trend_120s,range_min_6,R_30_min,R_all,R_3_min,R_1_min,-150*R_all/X_0,\
                                #     mom_trend_30s*R_all/X_0,(mom_trend_30s),abs_mom_trend_30s,\
                                #        (mom_trend_120s),abs_mom_trend_120s,\
                                #       self.data_spx[0],self.data_spx[-75],self.data_spx[-150],self.data_spx[0]-self.data_spx[-75],self.data_spx[-75]-self.data_spx[-150],
                                #     d_mom_sum_180s,self.current_time_NY,sec,R_all,R_1_min,R_3_min)
                        # and bullish_bars

                        elif not(max4>200) and not(min4<-200) and not self.big_down and not self.big_down_2 \
                              and self.data_spx.close[0]>max(list_10) and max(R_all/3.2,R_30_min/4,R_3_min/5,R_1_min/7)<1:
                            X_0=2.9
                            Trend_0 = self.trend_3_min(adj_ratio,150*self.enlarge_3_min())
                            if Trend_0 ==1 and self.spx[-1]>max(self.spx[-61:-6]): 
                                # p rint(adj_ratio,max4,max6,min4)
                                self.set_trend(True)
                                if self.rho_trend()>0: # if  is_rho_up_0 : #up_count>0: #  c_0_up > rho_threshold_local: #self.is_rho_change()>0:
                                    # pri nt(self.current_time_NY, adj_ratio, R_1_min,R_3_min,R_30_min,R_all,is_rho_up_0 , is_rho_up_2, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                                    self.set_trade(0.41)   #-1.1
                                    
                            elif Trend_0 ==-1 and self.spx[-1]<min(self.spx[-61:-6]): 
                                # p rint(adj_ratio,max4,min4,R_30_min,R_3_min,R_1_min)
                                self.set_trend(False)
                                if self.rho_trend()<0: # if  is_rho_down_0  :# down_count>0: #  c_0_down > rho_threshold_local: # self.is_rho_change()<0:
                                    self.set_trade(-0.41)   #-1.1
                                    # prin t(self.current_time_NY, is_rho_down_0 , is_rho_down_2,c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)

                            Trend_0 = self.trend_3_min(adj_ratio,82.8) # simon????
                            d_rho_up, d_rho_down = self.d_rho_one_min()
                            if len(self.mom)>12*6:
                                mom_series_3_min = self.mom[-1-36:]  # 3.5 min
                                delay=1
                                high_mom_3_min, low_mom_3_min, max_index_mom_3_min,min_index_mom_3_min=self.calculate_series_max_min(mom_series_3_min,offset=delay,is_mom=True)
                                # self.rho[-1]-min(self.rho[-5:-1])/np.power(np.average(self.rho[-5:-1]/12,0.5)>R_0*threshold
                                # Range_rho = abs(self.ref_rho0-self.extreme_rho0)
                                if Trend_0 ==-1 : # d_rho_down>0.425: # 0.3- 0.4939  ????simon 
                                    # if self.rho_trend()<0:
                                        # p rint(adj_ratio,self.mom[-1],d_rho_down,self.current_time_NY,R_all,R_30_min,self.abs_mom[-1]-self.abs_mom[-1-36],\
                                        #     high_mom_3_min, low_mom_3_min, max_index_mom_3_min,min_index_mom_3_min)
                                        Z_1=abs(self.abs_mom[-1-36-max_index_mom_3_min-delay]-self.abs_mom[-1-36-min_index_mom_3_min-delay])
                                        Z_2=mom_series_3_min[max_index_mom_3_min] - mom_series_3_min[min_index_mom_3_min]
                                        Y_1=Z_2/(Z_1-Z_2)
                                        # p rint(Z_2,Z_2/(Z_1-Z_2)) # p rint(Z_1)                      # p rint(self.mom[-1-36-max_index_mom_3_min]-self.mom[-1-36-min_index_mom_3_min])
                                        Y_2=abs(self.mom[-1-delay]-self.mom[-1-36-delay])/(self.abs_mom[-1-delay]-self.abs_mom[-1-36-delay]-abs(self.mom[-1-delay]-self.mom[-1-36-delay]))
                                        if Y_1>=4.5 and Y_2>=2.95 and self.spx[-1]-max(self.spx[-37:])<-0.001*self.spx[-1]\
                                            and self.spx[-1]-min(self.spx[-11:-6])<0: # and True: # rho 条件 180 or 36 ????simon
                                            # p rint(self.spx[-1]-min(self.spx[-37:]),adj_ratio,self.mom[-1]-self.mom[-1-36],self.abs_mom[-1]-self.abs_mom[-1-36]) # p rint(Y_2)
                                            self.set_trend(False)
                                            if self.rho_trend()<0: #if  is_rho_up_0 : # c_0_down > rho_threshold_local: # self.is_rho_change()<0: #self.rho[-1]- min(self.rho[-14:-1]>=0.18* c_0:
                                                # prin t(self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                                                self.set_trade(-0.43)   #-1.1
                                    
                                if Trend_0 ==1: # and d_rho_up>0.425: # 0.3- 0.4939  ????simon
                                    # p rint(adj_ratio,self.mom[-1],d_rho_down,self.current_time_NY,R_all,R_30_min,self.abs_mom[-1]-self.abs_mom[-1-36],\
                                    #     high_mom_3_min, low_mom_3_min, max_index_mom_3_min,min_index_mom_3_min)
                                    Z_1=abs(self.abs_mom[-1-36-max_index_mom_3_min-delay]-self.abs_mom[-1-36-min_index_mom_3_min-delay])
                                    Z_2=mom_series_3_min[max_index_mom_3_min] - mom_series_3_min[min_index_mom_3_min]
                                    Y_1=Z_2/(Z_1-Z_2)
                                    # p rint(Z_2,Z_2/(Z_1-Z_2)) # p rint(Z_1)                         # p rint(self.mom[-1-36-max_index_mom_3_min]-self.mom[-1-36-min_index_mom_3_min])
                                    Y_2=abs(self.mom[-1-delay]-self.mom[-1-36-delay])/(self.abs_mom[-1-delay]-self.abs_mom[-1-36-delay]-abs(self.mom[-1-delay]-self.mom[-1-36-delay]))
                                    if Y_1>=4.5 and Y_2>=2.95 and self.spx[-1]-min(self.spx[-37:])>0.001*self.spx[-1]\
                                        and self.spx[-1]-max(self.spx[-11:-6])>0: # and True: # rho 条件 180 or 36 ????simon
                                        # p rint(Y_2) # p rint(self.spx[-1]-min(self.spx[-37:]),adj_ratio,self.mom[-1]-self.mom[-1-36],self.abs_mom[-1]-self.abs_mom[-1-36])
                                        self.set_trend(True)
                                        if self.rho_trend()>0: #is_rho_up_0 : #c_0_up > rho_threshold_local: # self.is_rho_change()>0: #self.rho[-1]- max(self.rho[-14:-1]<=-0.18* c_0: # = np.power((np.average(self.rho[-1-16:-4])/12),0.5)
                                            # pri nt(self.current_time_NY, c_0,c_0_up,c_0_down,self.rho[-16:],d_mom_sum_90s,d_mom_sum_180s)
                                            self.set_trade(0.43)   #-1.1
                            # # not used
                            # D_up=90 *adj_ratio# 160-180
                            # D_down=90*adj_ratio
                            # Z_up=max(self.mom)  #[-36:]
                            # if Z_up>600:
                            #     D_down=D_down* np.power(Z_up/600,0.5)
                            # Z_down=-min(self.mom) # asymmetric  [-36:]
                            # if Z_down>600:
                            #     D_up=D_down* np.power(Z_down/600,0.5)
                            
                            # # 可以不用
                            # if self.mom[-1] -low_mom_3_min > D_up\
                            #     and max_index_mom_3_min-min_index_mom_3_min>18 \
                            #     and self.mom[-1] -low_mom_3_min -range_max_6> D_up*0.5\
                            #     and self.mom[-1] -low_mom_3_min -range_max_9> D_up*0.4\
                            #     and self.mom[-1] -low_mom_3_min -range_max_12> D_up*0.3\
                            #     and self.mom[-1] -low_mom_3_min -range_max_15> D_up*0.2:  #>4-12
                            #     # p rint(self.current_time_NY,np.power(Z_down/600,0.382),adj_ratio,self.mom[-1] -low_mom_4_min, D_up, max_index_mom_4_min-min_index_mom_4_min,\
                            #     #       self.mom[-1] ,low_mom_4_min ,range_max_6,self.mom[-1] -low_mom_4_min -range_max_6,\
                            #     # self.mom[-1] -low_mom_4_min -range_max_9,\
                            #     # self.mom[-1] -low_mom_4_min -range_max_12,\
                            #     # self.mom[-1] -low_mom_4_min -range_max_15)
                            #     # self.set_trade(0.41)   #-1.1
                            #     True
                            #     # p rint(self.current_time_NY,R_all,R_30_min,R_3_min,R_1_min,self.data_spx.close[0], max(list_10),self.mom[-1] -min(self.mom[-48:]) ,\
                            #     #       d_mom_sum_180s , range_max_6,mom_trend_30s,mom_trend_30s-abs_mom_trend_30s)
                            # elif self.mom[-1] -high_mom_3_min < -D_down\
                            #     and max_index_mom_3_min-min_index_mom_3_min<-18\
                            #     and self.mom[-1] -high_mom_3_min -range_min_6< -D_down*0.5\
                            #     and self.mom[-1] -high_mom_3_min -range_min_9< -D_down*0.4\
                            #     and self.mom[-1] -high_mom_3_min -range_min_12< -D_down*0.3\
                            #     and self.mom[-1] -high_mom_3_min -range_min_15< -D_down*0.2      :  #>4-12
                            #     True
                            #     # self.set_trade(-0.41)   #-1.1
                            
                                # p rint(d_rho_down,self.current_time_NY,adj_ratio,self.mom[-1] -high_mom_3_min, D_down,max_index_mom_3_min-min_index_mom_3_min,\
                                #       self.mom[-1] -high_mom_3_min -range_min_6,\
                                #  self.mom[-1] -high_mom_3_min -range_min_9,\
                                #  self.mom[-1] -high_mom_3_min -range_min_12,\
                                #  self.mom[-1] -high_mom_3_min -range_min_15) #np.power(Z_up/600,0.382),

                        # if not self.big_down and not self.big_down_2  and self.data_spx.close[0]>max(list_10)  and \
                        #     self.mom[-1] -min(self.mom[-48:]) > 150 and self.mom[-1] -min(self.mom[-1-48:]) -range_max_6> 150*0.33\
                        #         and self.mom[-1] -min(mom_series_4_min) -range_max_9> 150*0.1\
                        #         and max_index_mom_4_min-min_index_mom_4_min>6:
                       
            # if sec_to_close<=1:
          
            #     mom_series = pd.Series(self.mom)      # d_mom_series = pd.Series(self.d_mom)         # d_mom_series.to_csv("d_mom."+self.current_time_NY.strftime('%Y-%m-%d') + ".csv")
            #     abs_mom_series = pd.Series(self.abs_mom)
            #     mom_series.to_csv("mom."+self.current_time_NY.strftime('%Y-%m-%d') + ".csv")
            #     abs_mom_series.to_csv("abs_mom."+self.current_time_NY.strftime('%Y-%m-%d') + ".csv")
        
        if len(self.rho)>48 and len(self.mom)>48*3 : # and self.sec_since_trend< 301: # simon###############
            if max(self.rho[-1-45:-5])-min(self.rho[-5:])>0.5*c_0 and self.spx[-1]>max(self.spx[-541:-31]): 
                True
                # p rint("abcd")
                # pri nt(self.current_time_NY)
        
        if len(self.rho)>16 and len(self.mom)>48 : 
            new_rho_adj_small = 1.0
            new_mom = (150)
            new_rho = (0.4)
            new_rho_adj_small = (0.32)
            if self.position : 
                if  self.ref_price0 is not None or self.extreme_price0 is not None: # 为什么bt 这里的ref 和extreme 在position的情况下 还是0？？？
                    # prin t('为什么bt 这里的ref 和extreme 在position的情况下 还是0？？？')
                    True
                if  self.ref_price0 is not None and self.extreme_price0 is not None: # 为什么bt 这里的ref 和extreme 在position的情况下 还是0？？？
                    if  abs(self.extreme_price0-self.ref_price0)>20:
                        new_mom = max(225,abs(self.extreme_mom0-self.ref_mom0)*0.382)
                        new_rho = max(0.6,abs(self.extreme_rho0-self.ref_rho0)*0.382)
                        new_rho_adj_small = max(0.32,abs(self.extreme_rho0-self.ref_rho0)*0.4) # 0.1 or 0.15 to be tested
            
            if len(self.rho)>5:
                length1=min(len(self.spx)-1,600)
                length2=min(len(self.spx)-1,720)
                length3=min(len(self.spx)-1,750)
                series_3=self.spx[-1-length3:-2]
                
                length_mom=min(len(self.mom)-1,120)

                series_mom=self.mom[-1-length_mom:]
                series_abs_mom=self.abs_mom[-1-length_mom:]
                mom_min_index= np.argmin(series_mom) #size = 5 -30 
                mom_max_index= np.argmax(series_mom) #size = 5 -30 

                B_threshold = 0.8
                up_abs =series_abs_mom[-1]-series_abs_mom[mom_min_index]
                up_mom =series_mom[-1]-series_mom[mom_min_index]
                # B_up = (up_abs-up_mom)/up_mom>B_threshold
                
                down_abs =series_abs_mom[-1]-series_abs_mom[mom_max_index]
                down_mom =-(series_mom[-1]-series_mom[mom_max_index])
                # B_down = (down_abs-down_mom)/down_mom>B_threshold

                z_max = abs(self.spx[-1]-max(self.spx[-1-length1:-1]))
                z_min = abs(self.spx[-1]-min(self.spx[-1-length1:-1]))
                zyx1 = (self.abs_spx[-1]-self.abs_spx[-1-length1])
                zyx2 = (self.abs_spx[-1]-self.abs_spx[-1-length2])
                
                ratio_xyz=max(zyx1*6/length1,0.68)
                ratio_xyz2=max(zyx2*6/length2,0.68)
                
                threshold_spx = 0.0025
                threshold_rho=c_0*(ratio_xyz*ratio_xyz)*1.05
                threshold_rho=c_0*(ratio_xyz2*ratio_xyz2)*1.01

                if self.mom[-1]-min(series_mom)>66*max(adj_ratio,1) and max(self.rho[-1-48:-5])-min(self.rho[-5:])>threshold_rho\
                    and self.spx[-1]-min(series_3)>self.spx[-1]*threshold_spx:
                    # if max(self.rho[-1-48:-5])-min(self.rho[-5:])>threshold_rho : # 0.618*max(zyx1*zyx1/6400,1)*c_0:
                        # pri nt(self.current_time_NY,zyx1,z_max,z_min,c_0,self.mom[-1]-min(series_mom),\
                        #       (max(self.rho[-1-48:-5])-min(self.rho[-5:]))/threshold_rho,\
                        # (self.spx[-1]-min(series_3))/self.spx[-1],Var_spy_long,ratio_xyz2/ratio_xyz)
                        # pri nt('+zyx')
                    if ratio_xyz < 1.5 and ratio_xyz2<1.5: # to be tested
                        if sec > 3600*2.5+5*60 and sec < 3600*4+5*60 and not is_half_day and adj_ratio<1.5 and \
                            not(self.ir_date() and sec> 3600*4.5-600): # to be tested
                            range_max_N,range_min_N,index_max_N,index_min_N=self.range_N(4,0,length_mom)
                            B_last4_mom_up = self.mom[-1]-min(series_mom)- range_max_N>66*max(adj_ratio,1)*0.618  # max6
                            if self.spx[-1]>np.average(self.spx[-20:-10]) and self.spx[-1]>self.spx[-20]:
                                if B_last4_mom_up and adj_ratio<1.4:
                                    if (self.spx[-1]-min(self.spx[-60*30:])<self.spx[-1]*0.0035): # can be removed
                                        if (up_abs-up_mom)/up_mom<0.7:
                                            self.longer_wait=True
                                            self.normal_up=True
                                            self.set_trade(1.536) # if sec > 3600*2.5+5*60: # to be tested
                                            self.stop_loss=min(self.spx[-length1:-2])*0.382+0.618*self.spx[-1]
                                                                                
                if self.mom[-1]-max(series_mom)<-66*max(adj_ratio,1) and min(self.rho[-1-48:-5])-max(self.rho[-5:])<-threshold_rho\
                    and self.spx[-1]-max(series_3)<-self.spx[-1]*threshold_spx:
                        # pr int(self.current_time_NY,zyx1,z_max,z_min,c_0,self.mom[-1]-max(series_mom),\
                        #       (min(self.rho[-1-48:-5])-max(self.rho[-5:]))/threshold_rho,\
                        # (self.spx[-1]-max(series_3))/self.spx[-1],Var_spy_long,ratio_xyz2/ratio_xyz)                        # print('-zyx')
                    if ratio_xyz < 1.5 and ratio_xyz2<1.5: # to be tested
                        if sec > 3600*2.5+5*60 and sec < 3600*4+5*60 and not is_half_day and adj_ratio<1.5 and \
                            not(self.ir_date() and sec> 3600*4.5-600): # to be tested
                            range_max_N,range_min_N,index_max_4,index_min_4=self.range_N(4,0,length_mom)
                            B_last4_mom_down = self.mom[-1]-max(series_mom)-range_min_N<-66*max(adj_ratio,1)*0.618  # min6
                            if self.spx[-1]<np.average(self.spx[-20:-10]) and self.spx[-1]<self.spx[-20]:
                                if B_last4_mom_down and adj_ratio<1.4: 
                                    if (self.spx[-1]-max(self.spx[-60*30:])>-self.spx[-1]*0.0035): # can be removed
                                        # print(adj_ratio,(down_abs-down_mom)/down_mom,up_abs,up_mom,down_abs,down_mom,self.current_time_NY,ratio_xyz2,z_max,z_min,c_0,self.mom[-1]-max(series_mom),\
                                        #       self.mom[-1]-min(series_mom), range_max_N,66*max(adj_ratio,1))
                                        if (down_abs-down_mom)/down_mom<0.7:
                                            self.longer_wait=True
                                            self.normal_down=True
                                            self.set_trade(-1.536) # if sec > 3600*2.5+5*60: # to be tested
                                            self.stop_loss=max(self.spx[-length1:-2])*0.382+0.618*self.spx[-1]
                                            
            if self.sec_since_trend>0 and self.sec_since_trend< 301: # simon###############
                # if self.mom_up and self.sec_since_trend<30 and min(self.rho[-5:])-max(self.rho[-17:-5])<-0.4*c_0:
                if self.mom[-1]-min(self.mom[-1-54:-1])>max(150,new_mom*adj_ratio *self.enlarge_3_min()*self.symmetric_ratio_up)\
                    and max(self.rho[-1-18:-5])-min(self.rho[-5:])>new_rho*c_0\
                        and min(self.rho[-8:-4])-self.rho[-1]>-new_rho_adj_small*c_0 : # and self.mom[-1]>np.average(self.mom[-5:-1]: # and min(self.rho[-19:-13])-min(self.rho[-5:])>0.1*c_0 :
                    # simon?????????????################### (self.rho[-8:-4])-self.rho[-1] # to be tested
                    if sec > 3600*2.5+5*60 and sec < 3600*4+5*60 and not is_half_day and adj_ratio<1.5 and \
                            not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)): # if sec> 3600*2: # to be tested
                        self.set_trend(True) # self.sig_type=0.1
                        self.set_trade(1.414) # to be tested
                        
                        if self.entry_type0 =="long":
                            self.second_wave= True
                        elif self.entry_type0 =="short":
                            # print(f"{self.ny }: @ this time, short posi should exit by rho change to be done to be tested")
                            print(f'{self.current_time_NY},@ this time, short posi should exit by rho change to be done to be tested')
                            # self.close_cleanup(0.618)

                    # print("xyz")
                    # pri nt(self.current_time_NY,self.sec_since_trend,self.mom_up,self.mom_down,max(self.rho[-21:-5]),min(self.rho[-5:]),c_0,\
                    #     (max(self.rho[-1-18:-5])-min(self.rho[-5:]))/c_0,self.mom[-1]-min(self.mom[-55:-1],adj_ratio,  \
                    #     (min(self.rho[-19:-13])-min(self.rho[-5:]))/c_0)
                    # if self.mom[-1]-min(self.mom[-1-12:-1]>0 and self.spx[-1]-min(self.spx[-1-12*4*5:-1]<self.spx[-1]*0.0015: prin t(self.current_time_NY,self.sec_since_trend,self.mom_up)
                elif self.mom[-1]-max(self.mom[-1-54:-1]) < -max(150,new_mom*adj_ratio*self.enlarge_3_min()*self.symmetric_ratio_down)\
                        and self.rho[-1]-min(self.rho[-1-18:-5]) >new_rho*c_0 \
                        and self.rho[-1]-max(self.rho[-8:-4])>-new_rho_adj_small*c_0 :    # and self.mom[-1]<np.average(self.mom[-5:-1]:
                    # simon?????????????################### (self.rho[-8:-4])-self.rho[-1] # to be tested
                    if sec > 3600*2.5+5*60 and sec < 3600*4+5*60 and not is_half_day and adj_ratio<1.5 and \
                            not(self.ir_date() and (sec> 3600*3.25-600 and not is_half_day)):
                        self.set_trend(False)
                        self.set_trade(-1.414) # to be tested
                        
                        if self.entry_type0 =="short":
                            self.second_wave= True
                        elif self.entry_type0 =="long":
                            print(f'{self.current_time_NY},@ this time, long posi should exit by rho change to be done to be tested')
                        # if self.mom[-1]-max(self.mom[-1-8:-3])<0 and self.spx[-1]-min(self.spx[-1-12*4*5:-1]<self.spx[-1]*0.0015: pri nt(self.current_time_NY,self.sec_since_trend,self.mom_down)
    def rho_trend(self,P1=0.4,P2=0.32,P3=0.1):
        result=0
        if len(self.rho)>2:
            if len(self.rho)>24:
                rho_series_last = self.rho[-1-12:]
                rho_series_second_last = self.rho[-1-24:-12-1]
            elif len(self.rho)>12: 
                rho_series_last = self.rho[-1-6:]
                rho_series_second_last = self.rho[-1-12:-6-1]
            elif len(self.rho)>6: 
                rho_series_last = self.rho[-1-3:]
                rho_series_second_last = self.rho[-1-6:-3-1]
            elif len(self.rho)>4: 
                rho_series_last = self.rho[-1-2:]
                rho_series_second_last = self.rho[-1-4:-2-1]
            elif len(self.rho)>2: 
                rho_series_last = self.rho[-1-1:]
                rho_series_second_last = self.rho[-1-2:-1-1]
            
            c_0 = np.power(np.average(rho_series_second_last)/12,0.5) #c_0 = np.power((np.average(self.rho[-1-18:-11])/12),0.5)

            if (max(rho_series_last)-min(rho_series_second_last))>P1*c_0 \
                            and (max(rho_series_last)-max(rho_series_second_last))>P2*c_0\
                            and (self.rho[-1] -max(rho_series_second_last))>P3*c_0:
                    result =-1
            elif -(min(rho_series_last)-max(rho_series_second_last))>P1*c_0 \
                            and -(min(rho_series_last)-min(rho_series_second_last))>P2*c_0\
                            and -(self.rho[-1] -min(rho_series_second_last))>P3*c_0:  # is_rho_down_0 :
                    result =1
        return result

    def is_rho_change(self,threshold_1=0.5,threshold_2=0.25,threshold_3=0.1):
        up_1 ,down_1,up_count,down_count=0,0,0,0
        is_up,is_down, is_up_2,is_down_2 =False,False,False,False
        if len(self.rho)>0 and len(self.rho)<=20:
            c_0 = np.power( np.average(self.rho)/12,0.5) #c_0 = np.power((np.average(self.rho[-1-18:-11])/12),0.5)  
        elif len(self.rho)>20:
            series_0 = self.rho[-1-24:-12-1]
            
            series_last = self.rho[-1-12:]
            series_sec_last = self.rho[-1-24:-12-1]
            
            series_rho_2 = self.rho[-1-24:-2]
            series_rho_all = self.rho[-1-24:]

            # if len(self.rho)>20: 
            c_0 = np.power( np.average(series_sec_last)/12,0.5) #c_0 = np.power((np.average(self.rho[-1-18:-11])/12),0.5)  
            
            up_1    =   -(min(series_last)-max(series_sec_last))/c_0 #max(self.rho[-14:-1]-self.rho[-1]
            up_2    =   -(min(series_last)-min(series_sec_last))/c_0
            up_3    =   -(self.rho[-1]-min(series_sec_last))/c_0
            
            down_1  =    (max(series_last)-min(series_sec_last))/c_0 #self.rho[-1]- min(self.rho[-14:-1]>=0.18* c_0
            down_2  =    (max(series_last)-max(series_sec_last))/c_0
            down_3  =    (self.rho[-1]-max(series_sec_last))/c_0
                        
            is_up = up_1 >= threshold_1     and up_2 >= threshold_2 and up_3 >= threshold_3 #c_0_down_2_pct > -rho_threshold_2_pct 
            is_down = down_1 >= threshold_1     and down_2 >= threshold_2 and down_3 >= threshold_3 #c_0_down_2_pct > -rho_threshold_2_pct 
            
            range_0= max(series_rho_all)-min(series_rho_all)

            c_0_up_2_pct = (min(series_rho_2)-self.rho[-1])/c_0 / range_0  #max(self.rho[-14:-1]-self.rho[-1]
            c_0_down_2_pct=(self.rho[-1]-max(series_rho_2))/c_0 / range_0  #self.rho[-1]- min(self.rho[-14:-1]>=0.18* c_0
        
            is_up_2 = (up_1 > 0.45 and down_1<-0.225) # or  is_up 
            is_down_2 = (down_1 > 0.45 and up_1<-0.225) # or is_down 
            up_count = 1*is_up + 1*is_up_2 
            down_count = 1*is_down + 1*is_down_2 
        
        self.c_0=c_0
        
        return c_0,up_1 ,down_1, is_up,is_down, is_up_2,is_down_2,up_count,down_count
    
    def trend_3_min(self,adj_ratio,threshold=150,delay:int=1):
                        A_0=36 #42
                        delay_spx=delay*5
                        mom_series_3_min = self.mom[-1-A_0-delay:-1-delay]  # 3.5 min
                        spx_series_15_min = self.spx[-1-15*60-delay_spx:-1-A_0-delay_spx]  # 3.5 min
                        range_max_3,range_min_3,index_max_3,index_min_3=self.range_N(3,delay=delay)
                        range_max_6,range_min_6,index_max_6,index_min_6=self.range_N(6,delay=delay)
                        range_max_9,range_min_9,index_max_9,index_min_9=self.range_N(9,delay=delay)
                        range_max_12,range_min_12,index_max_12,index_min_12=self.range_N(12,delay=delay)
                        range_max_15,range_min_15,index_max_15,index_min_15=self.range_N(15,delay=delay)

                        D_up=threshold *adj_ratio# 160-180
                        D_down=threshold*adj_ratio
                        Z_up=max(self.mom)  #[-36:]
                        if Z_up>600:
                            D_down=D_down* np.power(Z_up/600,0.5)
                        Z_down=-min(self.mom) # asymmetric  [-36:]
                        if Z_down>600:
                            D_up=D_down* np.power(Z_down/600,0.5)

                        high_spx_15_min, low_spx_15_min, max_index_spx_15_min,min_index_spx_15_min=self.calculate_series_max_min(spx_series_15_min,0,is_mom=False)
                        high_mom_4_min, low_mom_4_min, max_index_mom_4_min,min_index_mom_4_min=self.calculate_series_max_min(mom_series_3_min,0,is_mom=True)
                        if      self.mom[-1-delay] -low_mom_4_min > D_up\
                            and max_index_mom_4_min-min_index_mom_4_min>18 \
                            and self.mom[-1-delay] -low_mom_4_min -range_max_3> D_up*0.6\
                            and self.mom[-1-delay] -low_mom_4_min -range_max_6> D_up*0.5\
                            and self.mom[-1-delay] -low_mom_4_min -range_max_9> D_up*0.4\
                            and self.mom[-1-delay] -low_mom_4_min -range_max_12> D_up*0.3\
                            and self.mom[-1-delay] -low_mom_4_min -range_max_15> D_up*0.2:  #>4-12
                            # p rint(self.current_time_NY,np.power(Z_down/600,0.382),adj_ratio,self.mom[-1] -low_mom_4_min, D_up, max_index_mom_4_min-min_index_mom_4_min,\
                            #       self.mom[-1] ,low_mom_4_min ,range_max_6,self.mom[-1] -low_mom_4_min -range_max_6,\
                            # self.mom[-1] -low_mom_4_min -range_max_9,\
                            # self.mom[-1] -low_mom_4_min -range_max_12,\
                            # self.mom[-1] -low_mom_4_min -range_max_15)
                            if self.spx[-1]>=high_spx_15_min:
                                return 1 #self.set_t rade(0.41)   #-1.1
                            # p rint(self.current_time_NY,R_all,R_30_min,R_3_min,R_1_min,self.data_spx.close[0], max(list_10),self.mom[-1] -min(self.mom[-48-1:] ,\
                            #       d_mom_sum_180s , range_max_6,mom_trend_30s,mom_trend_30s-abs_mom_trend_30s)
                        elif    self.mom[-1-delay] -high_mom_4_min < -D_down\
                            and max_index_mom_4_min-min_index_mom_4_min<-18\
                            and self.mom[-1-delay] -high_mom_4_min -range_min_3< -D_down*0.6\
                            and self.mom[-1-delay] -high_mom_4_min -range_min_6< -D_down*0.5\
                            and self.mom[-1-delay] -high_mom_4_min -range_min_9< -D_down*0.4\
                            and self.mom[-1-delay] -high_mom_4_min -range_min_12< -D_down*0.3\
                            and self.mom[-1-delay] -high_mom_4_min -range_min_15< -D_down*0.2:  #>4-12
                            if self.spx[-1]<=low_spx_15_min:
                                return -1 # self.set_t rade(-0.41)   #-1.1
                        else:
                            return 0
    def set_trade(self, direction,mim_require =1.920,allow_small_trade_sec = 3600*2+600, posi_ratio=1.0): #sig_time issue, may over write sig_time case 2.0
        if self.current_direction > direction and direction>0:
            direction = self.current_direction
            return
        elif self.current_direction < direction and direction<0:
            direction = self.current_direction
            return
        if abs(direction)==2:
            self.longer_wait=True
        elif abs(direction)>2:
            self.longer_wait=False
        elif abs(direction)<2:
            True
            # self.longer_wait=False

        if self.sig_time is None: 
            self.sig_time=self.data_spx.datetime[0]
            print(f'{self.current_time_NY},prepare to set trade type, {direction,self.normal_down,self.data_spx.close[0]-self.spx_high2, self.data_spx.close[0]-self.spx_low2, direction,len(self.mom),max((self.mom)),self.abs_mom[len(self.mom)-1]}')
        
        if abs(direction)<mim_require:
            return
        sec=self.compute_sec()
        if sec<allow_small_trade_sec and abs(direction)< 2: return
        if self.ir_date() and sec>=3600*4.5:
            if (max(self.mom)>800 or min(self.mom)<-800) and abs(direction)<= 2: return   
        if self.R_3_min>8 and abs(direction)< 2: return

        if self.ir_date() and sec <3600*5.5+300:
            if abs(direction) <2: direction=0
        if not self.half_date() and sec <3600*2+750: #11.42.30
            if abs(direction) <2: direction=0
        if abs(direction)<self.abs_dir:
            direction=0

        if direction>=0 and self.current_direction>=0:
            self.max_direction = max(direction,self.current_direction)
        elif direction<=0 and self.current_direction<=0:
            self.max_direction = min(direction,self.current_direction)

        self.current_direction= direction
        
        if not self.position:
            self.first_sig = direction
            self.max_sig = direction
        else:
            if self.max_sig >=0 and direction>self.max_sig:
                self.max_sig = direction
            elif self.max_sig <=0 and direction<self.max_sig:
                self.max_sig = direction
        
        if direction >=4:
                self.size = 3
        elif direction >=3:
                self.size = 2
        elif direction > 0:
            self.size = 1
        elif direction <=-4:
                self.size = -3
        elif direction <=-3:
                self.size = -2
        elif direction < 0:
            self.size = -1

        if abs(direction)>0:
            if self.swap_price == None:
                self.swap_price = self.spx[-1] 

        if self.max_sig_type is None: 
            self.max_sig_type = direction
        else:
            if (self.max_sig_type>0 and direction<0) or (self.max_sig_type<0 and direction>0):
                if self.position: 
                    if (self.entry_type0 =="long" and direction<0 ) or\
                    (self.entry_type0 =="short" and direction>0 ) : 
                        self.close_cleanup(99)
                self.max_sig_type = direction
            
            if direction>=2 and direction >self.max_sig_type:
                self.max_sig_type =  direction
            elif direction<=-2 and direction < self.max_sig_type:
                self.max_sig_type =  direction
         
        if self.ir_date() and self.compute_sec()>3600*4.5 or self.R_1_min>10 or self.R_3_min>8 or self.R_30_min>6:
            if abs(direction)<= self.p.abs_dir_ir_date_or_high_vol : #1.414 abs - diff
                direction=0
        else:
            if self.buy_super_sig_count>0: 
                direction = max(0,direction)

            if self.sell_super_sig_count>0: 
                direction = min(0,direction)
        
        if self.entry_rho ==0: self.entry_rho=self.rho[-1]
        if not self.position:
            if direction>0:
                self.buy_signal_count +=1
                if len(self.rho)>10:
                    self.ref_rho0=max(self.rho[-17:])
                    self.extreme_rho0=min(self.rho[-5:]) 
                else :
                    self.ref_rho0=max(self.rho)
                    self.extreme_rho0=min(self.rho[-3:]) if len(self.rho)>2 else self.rho[-1]
            elif direction<0:
                self.sell_signal_count +=1
                if len(self.rho)>10:
                    self.ref_rho0=min(self.rho[-17:])
                    self.extreme_rho0=max(self.rho[-5:])
                else :
                    self.ref_rho0=min(self.rho)
                    self.extreme_rho0=max(self.rho[-3:]) if len(self.rho)>2 else self.rho[-1]
        self.set_sig(direction) #self.big_up=True # self.entry_set_buy()
        self.extreme_price0 = self.data_spx.close[0]  #simon ??????? reset extreme_price
        self.extreme_mom0 = self.mom[-1]
        if (direction>0):
            
            self.setup_ref_extreme(True)  #sec == 0            
            
            if direction>=3:
                self.buy_super_sig_count+=1
            
            if not self.position and not (self.longer_wait): #  or direction==2.99  possize = self.getposition(data, self.broker).size #size = abs(size if size is not None else possize)
                self.buy_trade(direction)  # yes  #加仓 # 并发 ## ==  ???? <= 无加仓 reset reference 间距60-90seconds  #  
            elif self.position and self.entry_type0=='long':
                self.second_wave=True
                self.spx_price_second_wave=self.data_spx.close[0]
        elif (direction<0):
            self.setup_ref_extreme(False)  #sec == 0            
            
            if direction<=-3:
                self.sell_super_sig_count+=1
            
            if not self.position  and not (self.longer_wait): #  or direction==-2.99 possize = self.getposition(data, self.broker).size #size = abs(size if size is not None else possize)
                self.sell_trade(direction)   # yes #加仓 # 并发 ## ==  ???? <= 无加仓 reset reference 间距60-90seconds  #  
            elif self.position and self.entry_type0=='short':
                self.second_wave=True # not used
                self.spx_price_second_wave=self.data_spx.close[0]
        if direction>=2:
            self.set_stop_loss(True)
        elif direction<=2 and direction>0:
            self.set_stop_loss(True,0.618)
        elif direction<=-2:
            self.set_stop_loss(False)
        elif direction>=-2 and direction<0:
            self.set_stop_loss(False,0.618)
            
    def trend_reverse_exit(self,threshold=140,ratio=1.0,delay :int =1,shrink=0.99): #v1
        # ratio mom ???? simon
        pos_size = 0
        threshold=threshold*ratio
        d_mom_sum_180s = self.mom[-1] -self.mom[-1-36] if len(self.mom) > 36 else self.mom[-1] -self.mom[0]  # 150s
        if self.position and len(self.mom)>6:
            mom_trend_120s, abs_mom_trend_120s = self.mom_and_abs(min(24,len(self.mom)),delay)  #if len(self.data_momentum.volume) >= 6:  150s  d_mom_sum_30s = sum(list(self.data_momentum.volume.get(size=6)))
            mom_trend_30s, abs_mom_trend_30s = self.mom_and_abs(min(6,len(self.mom)),delay)
            if self.entry_type0=="long" and  mom_trend_120s <- 180*self.symmetric_ratio_down and mom_trend_30s <- shrink*threshold*self.symmetric_ratio_down  and \
                    abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11 and \
                    abs_mom_trend_120s - abs(mom_trend_120s)<abs_mom_trend_120s/6 \
                        and self.spx[-1]<min(self.spx[-31:-6]):
                    pos_size = 1
                    return self.close_cleanup(23)
            elif self.entry_type0=="short" and mom_trend_120s > 180*self.symmetric_ratio_up and mom_trend_30s > shrink*threshold*self.symmetric_ratio_up and \
                    abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11 and \
                    abs_mom_trend_120s - abs(mom_trend_120s)<abs_mom_trend_120s/6 \
                        and self.spx[-1]>max(self.spx[-31:-6]): # 140 or 150-180    60-90    # 
                    pos_size = -1
                    return self.close_cleanup(24)
        return pos_size 
    def mom_and_abs(self,N=30,offset=0):
        if len(self.mom)>N+offset and len(self.abs_mom)>N+offset:
            return self.mom[-1-offset]-self.mom[-1-offset-N], self.abs_mom[-1-offset]-self.abs_mom[-1-offset-N]
        elif len(self.mom)>offset and len(self.abs_mom)>offset:
            return self.mom[-1-offset]-self.mom[0], self.abs_mom[-1-offset]-self.abs_mom[0]
        else:
            return 0,0
    def trend_reverse_exit_2(self,ratio=1,delay:int=1,threshold=150): # v2  threshold=135,shrink=0.9  # ratio mom ???? simon
        threshold = threshold*ratio
        pos_size = 0
        d_mom_sum_180s = self.mom[-1-1] -self.mom[-1-36-1] if len(self.mom) > 36 else self.mom[-1] -self.mom[0]  # 150s     
        if self.position and len(self.mom)>6+delay:
            mom_trend_120s, abs_mom_trend_120s = self.mom_and_abs(min(24,len(self.mom)),delay)  #if len(self.data_momentum.volume) >= 6:  150s  d_mom_sum_30s = sum(list(self.data_momentum.volume.get(size=6)))
            mom_trend_30s, abs_mom_trend_30s = self.mom_and_abs(min(6,len(self.mom)),delay)
            
            if self.entry_type0=="long" and  mom_trend_120s <- threshold*np.power(self.symmetric_ratio_down,0.95) and mom_trend_30s <- threshold*np.power(self.symmetric_ratio_down,0.95) and \
                    abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11  \
                        and self.spx[-1]<min(self.spx[-31:-6]):
                    pos_size = 1
                    return self.close_cleanup(25)
            elif self.entry_type0=="short" and mom_trend_120s > threshold*np.power(self.symmetric_ratio_up,0.95) and mom_trend_30s > threshold*np.power(self.symmetric_ratio_up,0.95) and \
                    abs_mom_trend_30s - abs(mom_trend_30s)<abs_mom_trend_30s/11 \
                        and self.spx[-1]>max(self.spx[-31:-6]): # 140 or 150-180    60-90    # 
                    pos_size = -1
                    return self.close_cleanup(26)
        return pos_size 
    def buy_trade(self, type=0): # yes
        self.buy_count +=1
        print(f' {self.current_time_NY}, buy type:{type}')
        self.max_direction = max(self.max_direction,type)
        # if type!=0:
        #     self. sig_time= self.data_spx.datetime[0]
        if not self.position_size and not self.trade_lock:
            self.buy(data=self.data_spx, size=1, exectype=bt.Order.Market) 
            self.trade_lock = True
        self.set_sig(type) # duplicate
        self.setup_ref_extreme(True) # duplicate
    def sell_trade(self, type=0): # yes
        self.sell_count +=1
        print(f'{self.current_time_NY}, sell type:{type}')
        self.max_direction = min(self.max_direction,type)
        # if type!=0:
        #     self. sig_time= self.data_spx.datetime[0]
        if not self.position_size and not self.trade_lock:
            self.sell(data=self.data_spx, size=1, exectype=bt.Order.Market) 
            self.trade_lock = True
        self.set_sig(type) # duplicate
        self.setup_ref_extreme(False)  # duplicate

    def notify_trade(self, trade):
        if trade.isopen:
            self.entry_price = trade.price
            self.entry_mom = self.mom[-1]
            self.entry_time = bt.num2date(trade.dtopen).replace(tzinfo=pytz.utc).astimezone(ny_tz).strftime('%Y-%m-%d %H:%M:%S')
            self.entry_time0 = bt.num2date(trade.dtopen).replace(tzinfo=pytz.utc).astimezone(ny_tz)
            self.entry_type0 = 'long' if trade.long else 'short'
            self.position_size = trade.size + self.position_size #possize = self.getposition(data, self.broker).size 
            self.my_position = self.my_position+trade.size if trade.long else self.my_position-trade.size
            #size = abs(size if size is not None else possize)
            spx_list = self.spx[-210:] # 
            ref_price0 = min(spx_list) if trade.long else max(spx_list) 
            range=abs(ref_price0 - self.entry_price)
            a=min(range/2,8)/range if range !=0 else 1.0
            self.stop_loss_price_worst = a*ref_price0 + (1-a)*self.entry_price #a*self.ref_price0 + (1-a)*self.extreme_price0 #self.stop_loss_price = self.data_spx.close[0]
            
            mom_list = list(self.data_spx.close.get(size=35))[:- 1 ] # 
            ref_mom0 = min(mom_list) if trade.long else max(mom_list) 
            self.stop_loss_mom = a*ref_mom0 + (1-a)*self.mom[-1]
            self.trade_lock = True

        if trade.isclosed:
            # if self.entry_type == 'long':
            #     trade.pnlcomm = self.extreme_price - self.entry_price - 3.0
            # else:
            #     trade.pnlcomm = self.entry_price - self.extreme_price - 3.0
            returns = trade.pnlcomm
            entry_time_ny = bt.num2date(trade.dtopen).replace(tzinfo=pytz.utc).astimezone(ny_tz).strftime('%Y-%m-%d %H:%M:%S')
            self.trade_start.append(entry_time_ny)
            exit_time_ny = bt.num2date(trade.dtclose).replace(tzinfo=pytz.utc).astimezone(ny_tz).strftime('%Y-%m-%d %H:%M:%S')
            self.trade_end.append(entry_time_ny)
            print(f'Trade closed: Entry {entry_time_ny}, Exit {exit_time_ny}, Returns: {returns:.2f}, Extrm: {(self.extreme_price0)}')
            self.extreme_price0 = None  #rho ref =0
            self.entry_type0 = None
            self.position_size = 0
            self.my_position = 0
            self.close_lock = True
            
# Modified run_backtest function
def run_backtest(spx_df: pd.DataFrame, spy_df: pd.DataFrame, momentum_df: pd.DataFrame, cor3m_df: pd.DataFrame, abs_dir : float = 0):
    cerebro = bt.Cerebro()
    
    # Add data feeds
    data_spx = MarketData(dataname=spx_df, timeframe=bt.TimeFrame.Seconds, compression=1)
    data_spy = MarketData(dataname=spy_df, timeframe=bt.TimeFrame.Seconds, compression=5)
    data_momentum = MarketData(dataname=momentum_df, timeframe=bt.TimeFrame.Seconds, compression=5)
    data_cor3m = MarketData(dataname=cor3m_df, timeframe=bt.TimeFrame.Seconds, compression=15)
    
    cerebro.adddata(data_spx, name='SPX')
    cerebro.adddata(data_spy, name='SPY')
    cerebro.adddata(data_momentum, name='Momentum')
    cerebro.adddata(data_cor3m, name='COR3M')
    
    # Add strategy
    cerebro.addstrategy(MomentumTrendStrategy)
    
    # Set cash and commission
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0)
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # Run backtest
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    results = cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    
    # Output analysis
    strat = results[0]
    print('\nStrategy Analysis:')
    print('Sharpe Ratio:', strat.analyzers.sharpe.get_analysis()['sharperatio'])
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    print('Max Drawdown: %.2f%%' % dd_analysis['max']['drawdown'])
    returns_analysis = strat.analyzers.returns.get_analysis()
    print('Annual Return: %.2f%%' % (returns_analysis['rnorm100']))
    trades_analysis = strat.analyzers.trades.get_analysis()
    print('\nTrade Analysis:')
    print('Total Trades:', trades_analysis.total.total)
    if trades_analysis.total.total > 0:
        print('Winning Trades:', trades_analysis.won.total)
        print('Losing Trades:', trades_analysis.lost.total)
        print('Win Rate: %.2f%%' % (trades_analysis.won.total / trades_analysis.total.total * 100))
    
    # Plot results
    cerebro.plot()

# Modified prepare_single_day_data
def prepare_single_day_data(date: datetime) -> Tuple[pd.DataFrame, pd.DataFrame]:
    try:
        spy_file = download_market_data('SPY', date, 'data2/spy')
        if not spy_file:
            raise Exception(f"Failed to obtain SPY data for {date}")
        
        # 下载并处理SPX数据
        spx_file = download_market_data('SPX', date, 'data2/spx')
        if not spx_file:
            raise Exception(f"Failed to obtain SPX data for {date}")
        
        cor3m_file = download_market_data('COR3M', date, 'data2/cor3m')
        if not cor3m_file:
            raise Exception(f"Failed to obtain COR3M data for {date}")
        
        spx_df = pd.read_csv(spx_file)
        spx_df = process_market_data(spx_df, 'SPX', '1S')
        spy_df = pd.read_csv(spy_file)
        spy_df = process_market_data(spy_df, 'SPY', '5S')
        cor3m_df = pd.read_csv(cor3m_file)
        cor3m_df = process_market_data(cor3m_df, 'COR3M', '15S')
        
        momentum_df = calculate_momentum(spy_df,spx_df)
        
        return spx_df, spy_df, momentum_df, cor3m_df
    except Exception as e:
        print(f"Error preparing data for {date}: {str(e)}")
        return None, None

# Modified prepare_multi_day_data
def prepare_multi_day_data(start_date: datetime, end_date: datetime, max_workers: int = 4) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    dates = pd.date_range(start=start_date, end=end_date, freq='B')
    all_data = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_date = {executor.submit(prepare_single_day_data, date): date for date in dates}
        for future in as_completed(future_to_date):
            date = future_to_date[future]
            try:
                data = future.result()
                if all(df is not None for df in data):
                    all_data.append(data)
            except Exception as e:
                print(f"Error processing date {date}: {str(e)}")
    
    return all_data

# Modified combine_daily_data
def combine_daily_data(daily_data: List[Tuple[pd.DataFrame, pd.DataFrame]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if not daily_data:
        raise ValueError("No valid data to combine")
    
    spx_dfs = []
    spy_dfs = []
    momentum_dfs = []
    cor3m_dfs = []
    
    for spx_df, spy_df, momentum_df, cor3m_df in daily_data:
        spx_dfs.append(spx_df)
        spy_dfs.append(spy_df)
        momentum_dfs.append(momentum_df)
        cor3m_dfs.append(cor3m_df)
    
    combined_spx = pd.concat(spx_dfs, axis=0)
    combined_spy = pd.concat(spy_dfs, axis=0)
    combined_momentum = pd.concat(momentum_dfs, axis=0)
    combined_cor3m = pd.concat(cor3m_dfs, axis=0)
    
    combined_spx.sort_index(inplace=True)
    combined_spy.sort_index(inplace=True)
    combined_momentum.sort_index(inplace=True)
    combined_cor3m.sort_index(inplace=True)
    
    return combined_spx, combined_spy, combined_momentum, combined_cor3m

if __name__ == '__main__':
    start_date, end_date, abs_dir,max_workers, adj1_csv = parse_args()
    print(f"Running backtest from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    # 加载adj1数据
    adj_vector=load_adj1_data(adj1_csv)
    
    daily_data = prepare_multi_day_data(start_date, end_date, max_workers)
    if not daily_data:
        raise Exception("No valid data available")
    
    spx_df, spy_df, momentum_df, cor3m_df = combine_daily_data(daily_data)
    run_backtest(spx_df, spy_df, momentum_df, cor3m_df,abs_dir)
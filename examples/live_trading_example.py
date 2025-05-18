#!/usr/bin/env python
"""
Live trading example using the EasyTrade framework with Interactive Brokers.

This example demonstrates how to:
1. Connect to Interactive Brokers TWS/Gateway
2. Configure a strategy for live trading
3. Run the strategy in live mode
4. Handle graceful shutdown

Note: You must have Interactive Brokers TWS or IB Gateway running
and properly configured before running this script.
"""

import sys
import os
import logging
import argparse
import time
from datetime import datetime
import signal

# Add the parent directory to the path to import easytrade modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from easytrade.runner import EasyTradeRunner
from easytrade.strategies.momentum_strategy import MomentumStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('live_trading.log')
    ]
)

# Global variable to track if we should exit
should_exit = False

def signal_handler(sig, frame):
    """Handle Ctrl+C and other termination signals."""
    global should_exit
    print("\nReceived termination signal. Shutting down gracefully...")
    should_exit = True

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run a live trading strategy using Interactive Brokers')
    
    parser.add_argument('--tws-host', type=str, default='127.0.0.1',
                        help='Host address for IB TWS/Gateway')
    parser.add_argument('--tws-port', type=int, default=7497,
                        help='Port for IB TWS/Gateway (7496/7497 for TWS, 4001/4002 for Gateway)')
    parser.add_argument('--client-id', type=int, default=1,
                        help='Client ID for IB connection')
    parser.add_argument('--paper-trading', action='store_true',
                        help='Use paper trading account')
    parser.add_argument('--symbols', type=str, nargs='+', default=['SPY', 'SPX'],
                        help='Symbols to trade')
    parser.add_argument('--position-size', type=int, default=100,
                        help='Number of shares per trade')
    parser.add_argument('--profit-target', type=float, default=0.01,
                        help='Profit target (as decimal, e.g., 0.01 for 1%)')
    parser.add_argument('--stop-loss', type=float, default=0.005,
                        help='Stop loss (as decimal, e.g., 0.005 for 0.5%)')
    parser.add_argument('--trading-symbol', type=str, default='SPY',
                        help='Symbol to trade (e.g., SPY)')
    parser.add_argument('--test-mode', action='store_true',
                        help='Run in test mode for a limited time')
    parser.add_argument('--test-duration', type=int, default=300,
                        help='Test mode duration in seconds')
    
    return parser.parse_args()

def run_live_trading(args):
    """
    Run a live trading strategy using Interactive Brokers.
    
    Args:
        args: Command line arguments
    """
    global should_exit
    
    logger = logging.getLogger('live_trading')
    
    # Print configuration
    logger.info("Live Trading Configuration:")
    logger.info(f"TWS/Gateway: {args.tws_host}:{args.tws_port}")
    logger.info(f"Client ID: {args.client_id}")
    logger.info(f"Paper Trading: {'Yes' if args.paper_trading else 'No'}")
    logger.info(f"Symbols: {', '.join(args.symbols)}")
    logger.info(f"Trading Symbol: {args.trading_symbol}")
    logger.info(f"Position Size: {args.position_size} shares")
    logger.info(f"Profit Target: {args.profit_target * 100:.2f}%")
    logger.info(f"Stop Loss: {args.stop_loss * 100:.2f}%")
    logger.info(f"Test Mode: {'Yes (' + str(args.test_duration) + ' seconds)' if args.test_mode else 'No'}")
    
    # Create strategy with custom config
    strategy_config = {
        # Trading symbols
        "symbols": args.symbols,
        "trading_symbol": args.trading_symbol,
        
        # Trade parameters
        "position_size": args.position_size,
        "min_profit_target": args.profit_target,
        "stop_loss": args.stop_loss,
        "max_position_duration": 120,  # 2 hours max position duration
        
        # Entry conditions
        "momentum_entry": True,
        "spx_entry": True,
        "rho_entry": True,
        
        # Risk management
        "max_daily_trades": 5,
    }
    
    # Create strategy
    logger.info("Creating momentum strategy...")
    strategy = MomentumStrategy(strategy_config)
    
    # Create runner in live mode
    logger.info("Setting up live trading...")
    runner = EasyTradeRunner(mode="live")
    runner.setup_live(
        strategy=strategy,
        ib_host=args.tws_host,
        ib_port=args.tws_port,
        ib_client_id=args.client_id,
        symbols=args.symbols
    )
    
    # Run the strategy
    if args.test_mode:
        logger.info(f"Running strategy in test mode for {args.test_duration} seconds...")
        try:
            results = runner.run(run_duration=args.test_duration)
        except Exception as e:
            logger.error(f"Error during strategy execution: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return
    else:
        logger.info("Running strategy indefinitely (Ctrl+C to stop)...")
        try:
            # Set up signal handler
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Start the strategy
            runner._data_provider.start()
            runner._execution_provider.start()
            strategy.on_start()
            
            # Run until exit signal
            while not should_exit:
                time.sleep(1)
                
                # Print status every minute
                if datetime.now().second == 0:
                    positions = runner._execution_provider.get_positions()
                    if positions:
                        logger.info(f"Current positions: {len(positions)}")
                        for symbol, position in positions.items():
                            logger.info(f"  {symbol}: {position.quantity} shares @ {position.entry_price:.2f}, "
                                      f"P&L: ${position.unrealized_pnl:.2f}")
                    else:
                        logger.info("No open positions")
                        
        except Exception as e:
            logger.error(f"Error during strategy execution: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Ensure clean shutdown
            logger.info("Shutting down strategy...")
            strategy.on_stop()
            runner._data_provider.stop()
            runner._execution_provider.stop()
    
    # Print final status
    logger.info("Strategy stopped")
    
    positions = runner._execution_provider.get_positions()
    if positions:
        logger.info("Final positions:")
        for symbol, position in positions.items():
            logger.info(f"  {symbol}: {position.quantity} shares @ {position.entry_price:.2f}, "
                      f"P&L: ${position.unrealized_pnl:.2f}")
    else:
        logger.info("No open positions at exit")

if __name__ == "__main__":
    print("EasyTrade Live Trading Example")
    print("==============================")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Parse command line arguments
    args = parse_args()
    
    try:
        run_live_trading(args)
        print("\nTrading completed successfully.")
    except Exception as e:
        print(f"\nError during trading: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 
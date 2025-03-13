# EasyTrade Examples

This directory contains example scripts demonstrating how to use the EasyTrade framework.

## Generate Sample Data

Before running the examples, you need to generate some sample data:

```bash
python generate_sample_data.py --output-dir data
```

This will create sample OHLCV data for AAPL, MSFT, and GOOGL in the `data` directory.

## Running a Backtest

### Using Command Line Arguments

You can run a backtest using command line arguments:

```bash
python backtest_example.py --data-dir data --symbols AAPL MSFT GOOGL
```

Additional options:
- `--short-window`: Short-term moving average window (default: 10)
- `--long-window`: Long-term moving average window (default: 50)
- `--position-size`: Position size as a fraction of portfolio value (default: 0.1)
- `--initial-cash`: Initial cash balance (default: 100000.0)
- `--commission-rate`: Commission rate as a decimal (default: 0.001)
- `--log-level`: Logging level (default: INFO)
- `--output-dir`: Directory to save output files (default: output)

### Using a Configuration File

You can also run a backtest using a configuration file:

```bash
python run_from_config.py --config config.yaml
```

The configuration file (`config.yaml`) contains all the settings for the backtest, including:
- Data provider configuration
- Execution provider configuration
- Risk manager configuration
- Strategy configuration
- Symbols to trade
- Backtest parameters
- Logging configuration
- Output configuration

## Example Strategies

The examples use the following strategies:

### Moving Average Crossover

This strategy generates buy signals when the short-term moving average crosses above the long-term moving average, and sell signals when the short-term moving average crosses below the long-term moving average.

Parameters:
- `short_window`: Short-term moving average window
- `long_window`: Long-term moving average window
- `position_size`: Position size as a fraction of portfolio value

## Output

The backtest examples generate the following output:
- Performance metrics (printed to console)
- Equity curve plot (saved to output directory)
- Drawdown plot (saved to output directory)

## Next Steps

After running these examples, you can:
1. Modify the configuration file to test different parameters
2. Implement your own strategies by extending the `Strategy` class
3. Implement additional data providers for other data sources
4. Implement additional execution providers for live trading 
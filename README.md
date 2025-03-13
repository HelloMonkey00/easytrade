# EasyTrade: Quantitative Trading Framework

EasyTrade is a modular Python framework for quantitative trading that separates trading strategy logic from data acquisition and order execution. This framework allows traders to focus exclusively on strategy development while programmers handle the technical aspects of market data retrieval and order execution.

## Features

- **Modular Architecture**: Clear separation between strategy, data provider, and execution modules
- **Strategy Development**: Simple API for traders to implement their strategies
- **Data Providers**: Standardized interfaces for market data acquisition
- **Execution Components**: Abstract interfaces for trade execution
- **Backtesting**: Integration with backtesting capabilities
- **Performance Metrics**: Tools for strategy evaluation and reporting

## Installation

```bash
pip install -r requirements.txt
```

## Project Structure

```
easytrade/
├── core/           # Core framework components
├── data/           # Data provider modules
├── execution/      # Execution modules
├── strategies/     # Strategy implementations
├── utils/          # Utility functions
└── tests/          # Test cases
```

## Usage

### Creating a Strategy

```python
from easytrade.core.strategy import Strategy

class SimpleMovingAverageStrategy(Strategy):
    def __init__(self, short_window=10, long_window=50):
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window
        
    def on_data(self, data):
        # Strategy logic here
        pass
```

### Running a Backtest

```python
from easytrade.core.engine import TradingEngine
from easytrade.data.csv_provider import CSVDataProvider
from easytrade.execution.backtest import BacktestExecutionProvider

# Create components
data_provider = CSVDataProvider("path/to/data.csv")
execution_provider = BacktestExecutionProvider()
strategy = SimpleMovingAverageStrategy()

# Create and run engine
engine = TradingEngine(data_provider, execution_provider, strategy)
engine.run()
```

## License

MIT
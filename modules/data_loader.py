import yfinance as yf
import pandas as pd
from typing import List, Dict, Any, Optional
import logging

class DataLoader:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.main_symbol = config['trading_assets']['main_symbol'].upper().strip()
        self.correlation_symbols = {k: v.upper().strip() for k, v in config['trading_assets']['correlation_symbols'].items()}

    def _detect_gaps(self, df: pd.DataFrame, expected_interval_mins: int) -> bool:
        if df.empty: return True
        time_diffs = df.index.to_series().diff().dt.total_seconds() / 60
        max_gap = time_diffs.max()
        if max_gap > (expected_interval_mins * 2):
            logging.error(f"Data Gap Detected: Max gap is {max_gap} mins, expected {expected_interval_mins} mins.")
            return True
        return False

    def _validate_df(self, df: pd.DataFrame, symbol: str, interval_mins: int) -> bool:
        if df is None or df.empty:
            logging.error(f"Validation Failed: {symbol} is empty.")
            return False
        if self._detect_gaps(df, interval_mins):
            logging.error(f"Validation Failed: {symbol} contains critical time gaps.")
            return False
        if len(df) < 2:
            logging.error(f"Validation Failed: {symbol} insufficient data length.")
            return False
        return True

    def fetch_latest_data(self, period: str = "1d", interval: str = "15m") -> Dict[str, pd.DataFrame]:
        interval_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
        mins = interval_map.get(interval, 15)
        data_store = {}
        try:
            main_df = yf.download(self.main_symbol, period=period, interval=interval, progress=False)
            if self._validate_df(main_df, self.main_symbol, mins):
                data_store['main'] = main_df
            else:
                raise ValueError(f"Critical data failure for {self.main_symbol}")

            for name, symbol in self.correlation_symbols.items():
                corr_df = yf.download(symbol, period=period, interval=interval, progress=False)
                if self._validate_df(corr_df, symbol, mins):
                    data_store[name] = corr_df
                else:
                    logging.warning(f"Correlation asset {symbol} rejected due to gaps.")

            return data_store
        except Exception as e:
            logging.error(f"DataLoader Critical Error: {e}")
            return {}

    def fetch_historical_data(self, symbol: str, start: str, end: str, interval: str = "1h") -> pd.DataFrame:
        symbol = symbol.upper().strip()
        try:
            df = yf.download(symbol, start=start, end=end, interval=interval, progress=False)
            # validate historical data similarly to latest fetch
            interval_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
            mins = interval_map.get(interval, 60)
            if self._validate_df(df, symbol, mins):
                return df
            else:
                return pd.DataFrame()
        except Exception as e:
            logging.error(f"Historical DataLoader Error: {e}")
            return pd.DataFrame()

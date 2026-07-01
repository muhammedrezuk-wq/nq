import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
import logging
from .quant_logic import ProbabilityEngine, MacroExpert, CorrelationExpert, QuantExpert, FlowExpert
from .data_loader import DataLoader

class Backtester:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.loader = DataLoader(config)
        self.engine = ProbabilityEngine(config)
        # pass DB path to MacroExpert to match constructor
        self.macro = MacroExpert(config['paths']['db_path'])
        self.corr = CorrelationExpert()
        self.quant = QuantExpert()
        self.flow = FlowExpert()

    def run(self, start_date: str, end_date: str, interval: str = "1h"):
        logging.info(f"Starting Realistic Backtest from {start_date} to {end_date}")
        
        # 1. جلب بيانات حقيقية للنازداك
        main_df = self.loader.fetch_historical_data(self.config['trading_assets']['main_symbol'], start_date, end_date, interval)
        if main_df.empty:
            logging.error("No historical data found for main asset.")
            return pd.DataFrame(), 0
            
        # 2. جلب بيانات حقيقية للأصول المرتبطة
        correlation_data = {}
        for name, symbol in self.config['trading_assets']['correlation_symbols'].items():
            df = self.loader.fetch_historical_data(symbol, start_date, end_date, interval)
            if not df.empty:
                correlation_data[name] = df
            else:
                logging.warning(f"Could not fetch historical data for {symbol}")

        results = []
        window = 20
        
        for i in range(window, len(main_df) - 1):
            # تقطيع البيانات لمحاكاة الوقت الحقيقي
            current_slice = {
                'main': main_df.iloc[i-window:i],
            }
            for name, df in correlation_data.items():
                # التأكد من أن التوقيت متزامن (Slicing based on index)
                current_slice[name] = df.iloc[i-window:i] if len(df) >= i else df.tail(window)
            
            experts = [
                self.macro.analyze(current_slice),
                self.corr.analyze(current_slice),
                self.quant.analyze(current_slice),
                self.flow.analyze(current_slice)
            ]
            
            state = "DEFAULT"
            # Now calculate bias, score, stability and confidence
            bias, score, stability, confidence = self.engine.calculate_final_bias(state, experts)
            
            # تقييم النجاح بناءً على الشمعة التالية (No Look-ahead Bias)
            future_price = main_df['Close'].iloc[i]
            current_price = main_df['Close'].iloc[i-1]
            actual_move = 1.0 if future_price > current_price else -1.0
            
            success = (bias == "BULLISH" and actual_move == 1.0) or \
                      (bias == "BEARISH" and actual_move == -1.0)
            
            results.append({
                'timestamp': main_df.index[i-1],
                'bias': bias,
                'score': score,
                'confidence': confidence,
                'success': success,
                'actual_move': actual_move
            })
            
        df_res = pd.DataFrame(results)
        win_rate = df_res['success'].mean() * 100 if not df_res.empty else 0
        
        logging.info(f"Backtest Complete. Realistic Win Rate: {win_rate:.2f}%")
        return df_res, win_rate

    def optimize_weights(self, start_date: str, end_date: str):
        # Logic for optimization...
        return {}, 0

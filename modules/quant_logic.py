import numpy as np
import pandas as pd
import sqlite3
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import logging

@dataclass
class ExpertResult:
    name: str
    score: float
    confidence: float
    reason: str

class ProbabilityEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.weights_map = config.get('expert_weights', {})

    def detect_market_state(self, data: Dict[str, pd.DataFrame]) -> Tuple[str, str]:
        try:
            main = data['main']['Close']
            if len(main) < 20: return "DEFAULT", "Insufficient data"
            recent_range = main.tail(20).max() - main.tail(20).min()
            avg_range = (main.diff().abs().rolling(20).mean()).iloc[-1]
            if recent_range > avg_range * 3:
                return "BREAKOUT", "High volatility: Range expansion detected"
            elif recent_range < avg_range * 1.2:
                return "DEAD_SESSION", "Low volatility: Market is sideways"
            return "NORMAL", "Standard market conditions"
        except Exception as e:
            return "DEFAULT", f"Analysis error: {e}"

    def calculate_final_bias(self, state: str, experts_results: List[ExpertResult]) -> Tuple[str, float, float, float]:
        """
        Returns: (bias_str, final_score, stability, confidence)
        final_score: weighted signed score (can be negative)
        confidence: [0..1] aggregated confidence for making a trade decision
        """
        weights = self.weights_map.get(state.upper(), self.weights_map.get('DEFAULT', {}))
        bulls, bears = 0, 0
        weighted_score = 0.0
        total_weight = 0.0
        
        linchpin_expert = None
        max_conf = 0.0

        for res in experts_results:
            weight = weights.get(res.name.lower(), 0.1)
            score = 0.0 if np.isnan(res.score) else res.score
            conf = 0.0 if np.isnan(res.confidence) else res.confidence
            
            if score > 0.4: bulls += 1
            elif score < -0.4: bears += 1
            
            weighted_score += (score * conf * weight)
            total_weight += weight

            # Linchpin Logic: One high-confidence expert can drive the bias
            if conf > 0.8 and abs(score) > 0.7:
                if conf > max_conf:
                    max_conf = conf
                    linchpin_expert = res

        agreement_bonus = 0.0
        if bulls >= 2: agreement_bonus += 0.2
        if bears >= 2: agreement_bonus += 0.2
        
        final_score = weighted_score / total_weight if total_weight > 0 else 0
        
        # Apply Linchpin override if the engine is too neutral or contradictory
        if linchpin_expert and abs(final_score) < 0.2:
            final_score = linchpin_expert.score * 0.5 # Moderate shift towards linchpin
            
        # confidence is a bounded [0,1] measure derived from magnitude + agreement
        confidence = min(abs(final_score) + agreement_bonus, 1.0)
        
        bias = "NEUTRAL"
        if final_score > 0.1: bias = "BULLISH"
        elif final_score < -0.1: bias = "BEARISH"
        
        scores = [res.score for res in experts_results]
        stability = 1.0 - np.std(scores) if scores else 0.0
        
        return bias, final_score, stability, confidence

class MacroExpert:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def analyze(self, data: Dict[str, Any]) -> ExpertResult:
        try:
            # Use synchronous sqlite3 for compatibility with ProcessPoolExecutor
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # column name unified with database_manager -> impact_level
            cursor.execute("SELECT sentiment_score, impact_level FROM news_sentiment ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()

            if row:
                sentiment_score, impact_level = row
                conf = 0.9 if impact_level == "High" else 0.5 if impact_level == "Medium" else 0.2
                return ExpertResult("macro", float(sentiment_score), conf, f"News Sentiment: {impact_level} impact")
            else:
                return ExpertResult("macro", 0.0, 0.0, "No news data available")
        except Exception as e:
            return ExpertResult("macro", 0.0, 0.0, f"Sentiment Error: {e}")

class CorrelationExpert:
    def analyze(self, data: Dict[str, pd.DataFrame]) -> ExpertResult:
        try:
            if 'DXY' not in data or data['DXY'].empty:
                return ExpertResult("correlation", 0.0, 0.0, "DXY data missing")
            close = data['DXY']['Close'].squeeze()
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
            if len(close) < 5: return ExpertResult("correlation", 0.0, 0.0, "Insufficient DXY data")
            momentum = close.iloc[-1] - close.iloc[-5]
            if momentum > 0:
                return ExpertResult("correlation", -1.0, 0.8, f"DXY Rising ({momentum:.4f}) -> Bearish NQ")
            elif momentum < 0:
                return ExpertResult("correlation", 1.0, 0.8, f"DXY Falling ({momentum:.4f}) -> Bullish NQ")
            else:
                return ExpertResult("correlation", 0.0, 0.4, "DXY Stable")
        except Exception as e:
            return ExpertResult("correlation", 0.0, 0.0, f"Error: {e}")

class QuantExpert:
    def analyze(self, data: Dict[str, pd.DataFrame]) -> ExpertResult:
        try:
            if 'main' not in data or data['main'].empty:
                return ExpertResult("quant", 0.0, 0.0, "Main data missing")
            close = data['main']['Close'].squeeze()
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
            if len(close) < 20: return ExpertResult("quant", 0.0, 0.0, "Insufficient history")
            mean = close.rolling(20).mean().iloc[-1]
            std = close.rolling(20).std().iloc[-1]
            if std == 0: return ExpertResult("quant", 0.0, 0.0, "Zero volatility")
            z_score = (close.iloc[-1] - mean) / std
            if z_score > 2.0:
                return ExpertResult("quant", -1.0, 0.9, f"Overbought (Z={z_score:.2f}) -> Mean Reversion")
            elif z_score < -2.0:
                return ExpertResult("quant", 1.0, 0.9, f"Oversold (Z={z_score:.2f}) -> Mean Reversion")
            elif abs(z_score) > 1.0:
                score = -0.5 if z_score > 0 else 0.5
                return ExpertResult("quant", score, 0.5, f"Moderate deviation (Z={z_score:.2f})")
            else:
                return ExpertResult("quant", 0.0, 0.2, f"Price in balance (Z={z_score:.2f})")
        except Exception as e:
            return ExpertResult("quant", 0.0, 0.0, f"Error: {e}")

class FlowExpert:
    def analyze(self, data: Dict[str, pd.DataFrame]) -> ExpertResult:
        try:
            if 'main' not in data or data['main'].empty:
                return ExpertResult("flow", 0.0, 0.0, "Main data missing")
            main_df = data['main']
            if isinstance(main_df, pd.DataFrame):
                h, l, c, o = main_df['High'].squeeze(), main_df['Low'].squeeze(), main_df['Close'].squeeze(), main_df['Open'].squeeze()
            else: return ExpertResult("flow", 0.0, 0.0, "Invalid data format")
            if len(main_df) < 10: return ExpertResult("flow", 0.0, 0.0, "Insufficient history")
            range_last = h.iloc[-1] - l.iloc[-1]
            avg_range = (h - l).rolling(10).mean().iloc[-1]
            if range_last > avg_range * 1.5:
                score = 1.0 if c.iloc[-1] > o.iloc[-1] else -1.0
                return ExpertResult("flow", score, 0.8, f"Range Expansion ({range_last:.2f} > {avg_range:.2f}) -> Institutional Flow")
            elif (c.iloc[-1] > o.iloc[-1] and c.iloc[-2] > o.iloc[-2]):
                return ExpertResult("flow", 0.5, 0.4, "Short-term bullish continuity")
            elif (c.iloc[-1] < o.iloc[-1] and c.iloc[-2] < o.iloc[-2]):
                return ExpertResult("flow", -0.5, 0.4, "Short-term bearish continuity")
            else:
                return ExpertResult("flow", 0.0, 0.2, "Choppy price action")
        except Exception as e:
            return ExpertResult("flow", 0.0, 0.0, f"Error: {e}")

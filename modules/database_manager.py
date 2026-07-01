import aiosqlite
import logging
import os
from typing import List, Dict, Any, Optional

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        async with aiosqlite.connect(self.db_path, timeout=20) as conn:
            await conn.execute('PRAGMA journal_mode=WAL;')
            await conn.execute('PRAGMA synchronous=NORMAL;')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS market_data (
                    timestamp DATETIME PRIMARY KEY,
                    symbol TEXT,
                    open REAL, high REAL, low REAL, close REAL, volume REAL
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS trade_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    bias TEXT,
                    confidence REAL,
                    stability REAL,
                    lot_size REAL,
                    status TEXT DEFAULT 'PENDING'
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS expert_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    expert_name TEXT,
                    score REAL,
                    confidence REAL
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS news_sentiment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    sentiment_score REAL,
                    impact_level TEXT,
                    reason TEXT
                )
            ''')
            await conn.commit()

    async def insert_market_data(self, data: List[Dict[str, Any]]):
        async with aiosqlite.connect(self.db_path, timeout=20) as conn:
            await conn.execute('PRAGMA journal_mode=WAL;')
            await conn.executemany('''
                INSERT OR REPLACE INTO market_data (timestamp, symbol, open, high, low, close, volume)
                VALUES (:timestamp, :symbol, :open, :high, :low, :close, :volume)
            ''', data)
            await conn.commit()

    async def save_signal(self, signal: Dict[str, Any]):
        async with aiosqlite.connect(self.db_path, timeout=20) as conn:
            await conn.execute('PRAGMA journal_mode=WAL;')
            cursor = await conn.execute('''
                INSERT INTO trade_signals (symbol, bias, confidence, stability, lot_size)
                VALUES (?, ?, ?, ?, ?)
            ''', (signal['symbol'], signal['bias'], signal['confidence'], signal['stability'], signal['lot_size']))
            await conn.commit()
            return cursor.lastrowid

    async def save_expert_score(self, timestamp: str, expert: str, score: float, confidence: float):
        async with aiosqlite.connect(self.db_path, timeout=20) as conn:
            await conn.execute('PRAGMA journal_mode=WAL;')
            await conn.execute('''
                INSERT INTO expert_scores (timestamp, expert_name, score, confidence)
                VALUES (?, ?, ?, ?)
            ''', (timestamp, expert, score, confidence))
            await conn.commit()

    async def get_latest_sentiment(self):
        async with aiosqlite.connect(self.db_path, timeout=20) as conn:
            await conn.execute('PRAGMA journal_mode=WAL;')
            cursor = await conn.execute('SELECT sentiment_score, impact_level FROM news_sentiment ORDER BY timestamp DESC LIMIT 1')
            row = await cursor.fetchone()
            return row if row else (0.0, "Neutral")

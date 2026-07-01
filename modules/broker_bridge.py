import MetaTrader5 as mt5
import logging
from typing import Dict, Any
import aiosqlite
import asyncio
import time

class BrokerBridge:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.broker_cfg = config['broker']
        self.db_path = config['paths']['db_path']
        self.is_connected = False

    def connect(self, retries: int = 3, delay: int = 5) -> bool:
        if self.broker_cfg.get('platform') != 'MT5':
            return False
        for attempt in range(retries):
            try:
                # initialize MT5
                if not mt5.initialize():
                    logging.warning("MT5 initialize failed, retrying...")
                    time.sleep(delay)
                    continue

                # Prefer mt5.login for the Python API
                login_res = mt5.login(int(self.broker_cfg.get('account', 0)), password=self.broker_cfg.get('password'), server=self.broker_cfg.get('server'))
                if login_res:
                    self.is_connected = True
                    logging.info("Connected to MT5 server")
                    return True
                else:
                    logging.warning(f"MT5 login failed (attempt {attempt+1}).")
                    time.sleep(delay)
            except Exception as e:
                logging.error(f"MT5 connection exception: {e}")
                time.sleep(delay)
        return False

    async def send_signal_to_db(self, signal: Dict[str, Any]):
        """
        إرسال الإشارة إلى قاعدة البيانات بشكل غير متزامن بالكامل (Non-blocking).
        """
        try:
            async with aiosqlite.connect(self.db_path, timeout=20) as conn:
                # تفعيل WAL لضمان عدم القفل
                await conn.execute('PRAGMA journal_mode=WAL;')
                await conn.execute('''
                    INSERT INTO trade_signals (symbol, bias, confidence, stability, lot_size, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                ''', (signal['symbol'], signal['bias'], signal['confidence'], signal['stability'], signal['lot_size']))
                await conn.commit()
                logging.info(f"Signal archived in DB: {signal['bias']}")
        except Exception as e:
            logging.error(f"Async DB Signal Error: {e}")

    def execute_direct_trade(self, symbol: str, action: str, lot: float):
        # MT5 library is synchronous, handled by executor in main_monitor
        try:
            order_type = mt5.ORDER_TYPE_BUY if action == "BULLISH" else mt5.ORDER_TYPE_SELL
            tick = mt5.symbol_info_tick(symbol)
            if tick is None: return False
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": order_type,
                "price": tick.ask if action == "BULLISH" else tick.bid,
                "magic": 123456,
                "comment": "Muhammed_Rezuk_Quant_NQ Async Exec",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            return getattr(result, 'retcode', None) == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logging.error(f"Execution Error: {e}")
            return False

    def disconnect(self):
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.is_connected = False

import asyncio
import json
import logging
import traceback
import time
import os
import sys
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

try:
    from modules.database_manager import DatabaseManager
except ImportError: DatabaseManager = None
try:
    from modules.data_loader import DataLoader
except ImportError: DataLoader = None
try:
    from modules.quant_logic import ProbabilityEngine, MacroExpert, CorrelationExpert, QuantExpert, FlowExpert, ExpertResult
except ImportError: ProbabilityEngine = MacroExpert = CorrelationExpert = QuantExpert = FlowExpert = ExpertResult = None
try:
    from modules.broker_bridge import BrokerBridge
except ImportError: BrokerBridge = None
try:
    from modules.telegram_notifier import TelegramNotifier
except ImportError: TelegramNotifier = None

def load_config():
    base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, 'config.json')
    if not os.path.exists(config_path):
        print(f"\n❌ CRITICAL ERROR: Configuration file missing at {config_path}!")
        sys.exit(1)
    with open(config_path, 'r') as f:
        return json.load(f)

def verify_system_integrity():
    base_path = os.path.dirname(os.path.abspath(__file__))
    required_modules = ['modules/database_manager.py', 'modules/data_loader.py', 'modules/quant_logic.py', 'modules/broker_bridge.py', 'modules/telegram_notifier.py']
    print("\n🔍 Running System Integrity Check...")
    all_ok = True
    for module in required_modules:
        if not os.path.exists(os.path.join(base_path, module)):
            print(f"❌ MISSING: {module}")
            all_ok = False
    if all_ok: print("✅ System Integrity Verified.\n")
    return all_ok

def run_analysis_task(data, engine, macro, corr, quant, flow):
    try:
        if engine is None: return None, None, None, None, None, None, "Engine Missing"
        state, state_reason = engine.detect_market_state(data)
        results = []
        experts_map = {"macro": macro, "correlation": corr, "quant": quant, "flow": flow}
        for name, exp in experts_map.items():
            try:
                if exp: results.append(exp.analyze(data))
                else: results.append(ExpertResult(name, 0.0, 0.0, "Expert missing"))
            except Exception as e:
                results.append(ExpertResult(name, 0.0, 0.0, f"Analysis error: {e}"))
        # Now get final score, stability and confidence
        bias, final_score, stability, confidence = engine.calculate_final_bias(state, results)
        return state, results, bias, final_score, stability, confidence, state_reason
    except Exception as e:
        return None, None, None, None, None, None, str(e)

async def main():
    if not verify_system_integrity():
        print("⚠️ System incomplete, but attempting to run...")
        
    config = load_config()
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Log directory setup
    log_relative_path = config['paths']['log_path']
    log_dir_name = os.path.dirname(log_relative_path)
    full_log_dir = os.path.join(base_path, log_dir_name)
    os.makedirs(full_log_dir, exist_ok=True)

    logging.basicConfig(filename=os.path.join(base_path, log_relative_path), level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    console = logging.StreamHandler()
    logging.getLogger().addHandler(console)

    full_db_path = os.path.join(base_path, config['paths']['db_path'])
    db = DatabaseManager(full_db_path) if DatabaseManager else None
    if db: await db.init_db()
    
    loader = DataLoader(config) if DataLoader else None
    engine = ProbabilityEngine(config) if ProbabilityEngine else None
    bridge = BrokerBridge(config) if BrokerBridge else None
    notifier = TelegramNotifier(config) if TelegramNotifier else None
    
    # Initialize Experts (MacroExpert now needs db_path)
    macro = MacroExpert(full_db_path) if MacroExpert else None
    corr = CorrelationExpert() if CorrelationExpert else None
    quant = QuantExpert() if QuantExpert else None
    flow = FlowExpert() if FlowExpert else None
    
    executor = ProcessPoolExecutor()
    loop = asyncio.get_running_loop()

    brain_id = config.get('brain_id', 'Unknown')
    strategy = config.get('strategy_name', 'Default_Strategy')

    logging.info(f"🚀 Brain #{brain_id} | {strategy} Online.")
    if bridge: bridge.connect()

    system_status = {"data_loader": "Unknown", "broker": "Unknown", "database": "OK", "telegram": "Unknown", "last_heartbeat": 0}

    try:
        while True:
            start_time = time.time()
            cycle_duration = 60 # Reduced to 60s for better responsiveness
            
            os.system('cls' if os.name == 'nt' else 'clear')
            print("╔" + "═"*90 + "╗")
            print(f"║ {'🧠 BRAIN #' + brain_id + ' | STRATEGY: ' + strategy :^88} ║")
            print(f"║ {'TIME: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') :^88} ║")
            print("╠" + "═"*90 + "╣")
            print(f"║ 📉 ASSETS: {config['trading_assets']['main_symbol']:<15} | {', '.join(config['trading_assets']['correlation_symbols'].values()):<60} ║")
            print("╠" + "═"*90 + "╣")
            
            data = None
            if loader:
                try:
                    data = await loop.run_in_executor(None, loader.fetch_latest_data)
                    system_status["data_loader"] = "OK" if data else "FAIL"
                except Exception as e:
                    system_status["data_loader"] = "ERROR"
                    if notifier: await notifier.send_critical_alert("DataLoader", str(e))

            if bridge:
                system_status["broker"] = "OK" if bridge.is_connected else "DISCONNECTED"
                if not bridge.is_connected: bridge.connect()

            if data and engine:
                try:
                    # now run analysis returning score and confidence separately
                    state, results, bias, score, stability, confidence, state_reason = await loop.run_in_executor(
                        executor, run_analysis_task, data, engine, macro, corr, quant, flow
                    )
                    if state:
                        print(f"║ {'SITUATION: ' + state + ' | ' + state_reason :^88} ║")
                        print("╠" + "═"*90 + "╣")
                        print(f"║ {'Expert':<15} | {'State':<12} | {'Weight':<10} | {'Score':<10} | {'Conf':<10} | {'Reasoning':<25} ║")
                        print("║" + "-"*88 + "║")
                        weights = config['expert_weights'].get(state.upper(), config['expert_weights']['DEFAULT'])
                        for res in results:
                            weight = weights.get(res.name.lower(), 0.0)
                            state_txt = "ACTIVE" if abs(res.score) > 0.1 else "SLEEPING"
                            if np.isnan(res.score): state_txt = "FAILED"
                            print(f"║ {res.name:<15} | {state_txt:<12} | {weight:<10.2f} | {res.score:<10.2f} | {res.confidence:<10.2%} | {res.reason:<25} ║")
                        print("║" + "-"*88 + "║")
                        print(f"║ {'🎯 FINAL BIAS: ' + bias + ' | SCORE: ' + f'{score:.2f}' + ' | CONFIDENCE: ' + f'{confidence:.2%}' + ' | STABILITY: ' + f'{stability:.2%}' :^88} ║")
                        
                        # use confidence (0..1) for threshold decisions
                        if confidence > config['risk_management']['confidence_threshold']:
                            signal = {
                                "symbol": config['trading_assets']['main_symbol'], 
                                "bias": bias, 
                                "confidence": confidence, 
                                "stability": stability, 
                                "lot_size": round(config['risk_management']['base_lot'] * (1+abs(confidence)), 2)
                            }
                            if bridge: await bridge.send_signal_to_db(signal)
                            if notifier and "YOUR_BOT_TOKEN" not in config['telegram']['bot_token']:
                                await notifier.send_signal_report(bias, abs(confidence), stability, signal['lot_size'])
                        
                        if db: await db.save_expert_score(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "all", score, confidence)
                except Exception as e:
                    logging.error(f"Logic Error: {e}")
                    traceback.print_exc()
            else:
                print(f"║ {'Waiting for data or engine initialization...':^88} ║")

            print("╠" + "═"*90 + "╣")
            tel_status = "OK" if notifier and "YOUR_BOT_TOKEN" not in config['telegram']['bot_token'] else "CONFIG_MISSING"
            status_line = f" Data: {system_status['data_loader']} | Broker: {system_status['broker']} | DB: {system_status['database']} | Telegram: {tel_status}"
            print(f"║ {status_line:<88} ║")
            print("╚" + "═"*90 + "╝")
            
            current_time = time.time()
            if current_time - system_status["last_heartbeat"] > 14400:
                if notifier and "YOUR_BOT_TOKEN" not in config['telegram']['bot_token']:
                    overall = "OK" if all(v == "OK" for k, v in system_status.items() if k != "last_heartbeat") else "WARNING"
                    await notifier.send_health_report({
                        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                        "Data": system_status["data_loader"], 
                        "Broker": system_status["broker"], 
                        "DB": system_status["database"], 
                        "Telegram": tel_status, 
                        "overall": overall
                    })
                system_status["last_heartbeat"] = current_time

            await asyncio.sleep(max(0, cycle_duration - (time.time() - start_time)))
            
    except Exception as e:
        logging.critical(f"CRITICAL: {e}")
        traceback.print_exc()
        await asyncio.sleep(30)
    finally:
        if notifier: await notifier.close()
        if bridge: bridge.disconnect()
        executor.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

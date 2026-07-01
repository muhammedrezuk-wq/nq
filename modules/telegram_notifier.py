import httpx
import logging
from typing import Dict, Any
from arabic_reshaper import reshape
import asyncio

class TelegramNotifier:
    def __init__(self, config: Dict[str, Any]):
        self.token = config['telegram']['bot_token']
        self.chat_id = config['telegram']['chat_id']
        self.username = config['telegram']['username']
        self.brain_id = config.get('brain_id', 'Unknown')
        self.strategy = config.get('strategy_name', 'Default_Strategy')
        self.client = httpx.AsyncClient(timeout=15.0)
        self.failure_count = 0

    def _format_text(self, text: str) -> str:
        """
        تنسيق النصوص العربية لتناسب تليجرام.
        نستخدم reshape فقط لأن تليجرام يتعامل مع RTL تلقائياً.
        """
        return reshape(text)

    async def send_message(self, message: str, retries: int = 3):
        """
        إرسال الرسائل بنظام إعادة المحاولة لضمان وصول التنبيهات.
        """
        formatted_msg = self._format_text(message)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": formatted_msg,
            "parse_mode": "HTML"
        }
        
        for attempt in range(retries):
            try:
                response = await self.client.post(url, json=payload)
                if response.status_code == 200:
                    self.failure_count = 0
                    return True
                else:
                    logging.error(f"Telegram API Error (Attempt {attempt+1}): {response.text}")
            except Exception as e:
                logging.error(f"Telegram Connection Error (Attempt {attempt+1}): {e}")
            
            await asyncio.sleep(2 ** attempt)

        self.failure_count += 1
        return False

    async def send_signal_report(self, bias: str, conf: float, stability: float, lot: float):
        """إرسال تقرير الإشارة بصيغة غرفة العمليات"""
        msg = (
            f"<b>🚀 إشارة جديدة: Brain #{self.brain_id}</b>\n"
            f"🛠 <b>الاستراتيجية:</b> {self.strategy}\n"
            f"----------------------------\n"
            f"📌 <b>الاتجاه:</b> {bias}\n"
            f"🎯 <b>الثقة:</b> {conf:.2%}\n"
            f"⚖️ <b>الاستقرار:</b> {stability:.2%}\n"
            f"💰 <b>حجم اللوت:</b> {lot}\n"
            f"----------------------------\n"
            f"✅ <i>تم إرسال الأمر إلى EA بنجاح</i>"
        )
        await self.send_message(msg)

    async def send_health_report(self, status_map: Dict[str, Any]):
        """إرسال تقرير نبض النظام الشامل"""
        status_text = ""
        for module, status in status_map.items():
            if module in ['time', 'overall']: continue
            icon = "✅" if status == "OK" else "❌"
            status_text += f"{icon} <b>{module}:</b> {status}\n"
        
        msg = (
            f"<b>🛡️ تقرير نبض النظام (Heartbeat)</b>\n"
            f"🧠 <b>العقل:</b> #{self.brain_id}\n"
            f"📅 الوقت: {status_map.get('time', 'N/A')}\n"
            f"----------------------------\n"
            f"{status_text}"
            f"----------------------------\n"
            f"⚙️ <b>الحالة العامة:</b> {status_map.get('overall', 'Unknown')}"
        )
        await self.send_message(msg)

    async def send_critical_alert(self, module: str, error: str):
        """إنذار فوري عند حدوث فشل حرج"""
        msg = (
            f"⚠️ <b>تنبيه فشل تقني حرج!</b>\n\n"
            f"🧠 <b>العقل المتأثر:</b> #{self.brain_id}\n"
            f"🚨 <b>المكون المتضرر:</b> {module}\n"
            f"❌ <b>الخطأ:</b> {error}\n\n"
            f"🛠 <i>النظام يحاول الإصلاح التلقائي الآن...</i>"
        )
        await self.send_message(msg)

    async def close(self):
        await self.client.aclose()

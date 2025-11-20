"""
Alert notification system (Telegram integration).
Sends critical events to user via Telegram bot.
"""
import logging
from typing import Optional
import aiohttp


logger = logging.getLogger(__name__)


class TelegramAlerter:
    """
    Telegram bot for sending trading alerts.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram alerter.

        Args:
            bot_token: Telegram bot token (from BotFather)
            chat_id: Telegram chat ID to send messages to
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

        if not self.enabled:
            logger.warning("Telegram alerts disabled (no bot_token or chat_id)")
        else:
            logger.info("Telegram alerts enabled")

    async def send_message(self, message: str):
        """
        Send message via Telegram bot.

        Args:
            message: Message text to send
        """
        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.debug(f"Alert sent: {message[:50]}...")
                    else:
                        logger.error(f"Failed to send alert: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Telegram alert error: {e}")

    async def alert_position_opened(self, symbol: str, side: str, size: float, price: float):
        """Alert on position open."""
        message = (
            f"📈 *Position Opened*\n"
            f"Symbol: `{symbol}`\n"
            f"Side: {side}\n"
            f"Size: {size:.4f}\n"
            f"Price: {price:.2f}"
        )
        await self.send_message(message)

    async def alert_position_closed(self, symbol: str, pnl: float, pnl_pct: float):
        """Alert on position close."""
        emoji = "✅" if pnl > 0 else "❌"
        message = (
            f"{emoji} *Position Closed*\n"
            f"Symbol: `{symbol}`\n"
            f"PnL: {pnl:.2f} ({pnl_pct:+.2f}%)"
        )
        await self.send_message(message)

    async def alert_risk_halt(self, reason: str):
        """Alert on trading halt."""
        message = (
            f"🚨 *TRADING HALTED*\n"
            f"Reason: {reason}\n"
            f"Manual intervention required."
        )
        await self.send_message(message)

    async def alert_volatility_spike(self, symbol: str, ratio: float):
        """Alert on abnormal volatility."""
        message = (
            f"⚠️ *Volatility Spike*\n"
            f"Symbol: `{symbol}`\n"
            f"ATR Ratio: {ratio:.2f}x normal\n"
            f"Strategy paused."
        )
        await self.send_message(message)

    async def alert_regime_change(self, old_regime: str, new_regime: str):
        """Alert on market regime change."""
        message = (
            f"🔄 *Regime Change*\n"
            f"{old_regime} → {new_regime}\n"
            f"Strategy adjusting..."
        )
        await self.send_message(message)

    async def alert_api_error(self, error_type: str, details: str):
        """Alert on API errors."""
        message = (
            f"⚡ *API Error*\n"
            f"Type: {error_type}\n"
            f"Details: {details}"
        )
        await self.send_message(message)

    async def alert_daily_summary(self, stats: dict):
        """Send daily performance summary."""
        message = (
            f"📊 *Daily Summary*\n"
            f"Trades: {stats.get('total_trades', 0)}\n"
            f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            f"Total PnL: {stats.get('total_pnl', 0):.2f}\n"
            f"Avg PnL: {stats.get('avg_pnl', 0):.2f}"
        )
        await self.send_message(message)


# Backwards compatibility alias
TelegramAlerts = TelegramAlerter

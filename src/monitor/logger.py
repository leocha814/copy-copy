"""
Structured CSV logging system.
Logs events in consistent format for analysis.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

from src.core.time_utils import now_utc


logger = logging.getLogger(__name__)


class StructuredLogger:
    """
    CSV-based structured logging for trading events.
    Format: ts, lvl, src, sym, evt, msg, kv
    """

    def __init__(self, log_dir: str = "logs", use_async: bool = True):
        """
        Initialize structured logger with async buffering.

        Args:
            log_dir: Directory for log files
            use_async: Enable async logging with QueueHandler (default: True)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create daily log file
        date_str = datetime.now().strftime("%Y%m%d")
        self.log_file = self.log_dir / f"trading_{date_str}.csv"

        # Initialize CSV file with headers if not exists
        if not self.log_file.exists():
            self._write_header()

        # Setup async logging with buffering
        self.use_async = use_async
        if use_async:
            import asyncio
            import queue
            import threading
            from logging.handlers import QueueHandler, QueueListener
            
            self._log_queue = queue.Queue(maxsize=1000)
            self._stop_event = threading.Event()
            self._listener_thread = threading.Thread(
                target=self._async_writer_loop,
                daemon=True
            )
            self._listener_thread.start()
        else:
            self._log_queue = None

        logger.info(f"Structured logger initialized: {self.log_file} (async={use_async})")

    def _write_header(self):
        """Write CSV header."""
        with open(self.log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['ts', 'lvl', 'src', 'sym', 'evt', 'msg', 'kv'])

    def _async_writer_loop(self):
        """Background thread for async log writing."""
        import queue
        
        buffer = []
        FLUSH_INTERVAL = 1.0  # seconds
        BATCH_SIZE = 50
        
        last_flush = datetime.now()
        
        while not self._stop_event.is_set():
            try:
                # Try to get log entries with timeout
                try:
                    entry = self._log_queue.get(timeout=0.1)
                    buffer.append(entry)
                except queue.Empty:
                    pass
                
                # Flush conditions: batch size or time interval
                now = datetime.now()
                should_flush = (
                    len(buffer) >= BATCH_SIZE or
                    (buffer and (now - last_flush).total_seconds() >= FLUSH_INTERVAL)
                )
                
                if should_flush:
                    self._flush_buffer(buffer)
                    buffer.clear()
                    last_flush = now
                    
            except Exception as e:
                logger.error(f"Async writer error: {e}")
        
        # Final flush on shutdown
        if buffer:
            self._flush_buffer(buffer)
    
    def _flush_buffer(self, buffer):
        """Flush buffered log entries to file."""
        if not buffer:
            return
        
        try:
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                for entry in buffer:
                    writer.writerow(entry)
        except Exception as e:
            logger.error(f"Failed to flush log buffer: {e}")
    
    def shutdown(self):
        """Gracefully shutdown async logger."""
        if self.use_async and hasattr(self, '_stop_event'):
            self._stop_event.set()
            if hasattr(self, '_listener_thread'):
                self._listener_thread.join(timeout=5.0)
            logger.info("Async logger shutdown complete")

    def log(
        self,
        level: str,
        source: str,
        symbol: str,
        event: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None
    ):
        """
        Log structured event with async buffering.

        Args:
            level: Log level (INFO, WARNING, ERROR, CRITICAL)
            source: Source component (strategy, risk, exchange, etc.)
            symbol: Trading symbol (or '' if not applicable)
            event: Event type (signal, order, position, risk, etc.)
            message: Human-readable message
            extra: Additional key-value data (will be JSON encoded)
        """
        timestamp = now_utc().isoformat()
        kv_json = json.dumps(extra) if extra else ''
        
        entry = [timestamp, level, source, symbol, event, message, kv_json]
        
        if self.use_async:
            # Send to async queue
            try:
                self._log_queue.put_nowait(entry)
            except Exception:
                # Queue full, fallback to sync write
                self._write_sync(entry)
        else:
            # Synchronous write
            self._write_sync(entry)
    
    def _write_sync(self, entry):
        """Write single entry synchronously (fallback)."""
        try:
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(entry)
        except Exception as e:
            # Last resort: print to stderr
            import sys
            print(f"CRITICAL: Failed to write log: {e}", file=sys.stderr)

    def info(self, source: str, symbol: str, event: str, message: str, extra: Optional[Dict] = None):
        """Log INFO level event."""
        self.log('INFO', source, symbol, event, message, extra)

    def warning(self, source: str, symbol: str, event: str, message: str, extra: Optional[Dict] = None):
        """Log WARNING level event."""
        self.log('WARNING', source, symbol, event, message, extra)

    def error(self, source: str, symbol: str, event: str, message: str, extra: Optional[Dict] = None):
        """Log ERROR level event (also logs to file only, Telegram via explicit call)."""
        self.log('ERROR', source, symbol, event, message, extra)
        # Note: Telegram alerts should be sent explicitly via send_error_to_telegram()

    def critical(self, source: str, symbol: str, event: str, message: str, extra: Optional[Dict] = None):
        """Log CRITICAL level event (also logs to file only, Telegram via explicit call)."""
        self.log('CRITICAL', source, symbol, event, message, extra)
        # Note: Telegram alerts should be sent explicitly via send_error_to_telegram()

    def log_signal(self, signal, executed: bool = False):
        """
        Log trading signal.

        Args:
            signal: Signal object
            executed: Whether signal was executed
        """
        self.info(
            source='strategy',
            symbol=signal.symbol,
            event='signal',
            message=signal.reason,
            extra={
                'side': signal.side.value,
                'regime': signal.regime.value,
                'executed': executed,
                'indicators': signal.indicators
            }
        )

    def log_order(self, symbol: str, side: str, size: float, price: float, order_result: Dict):
        """
        Log order execution.

        Args:
            symbol: Trading symbol
            side: Order side
            size: Order size
            price: Execution price
            order_result: Order execution result from exchange
        """
        self.info(
            source='execution',
            symbol=symbol,
            event='order',
            message=f"{side} {size:.4f} @ {price:.2f}",
            extra={
                'side': side,
                'size': size,
                'price': price,
                'order_id': order_result.get('id'),
                'status': order_result.get('status'),
                'slippage': order_result.get('slippage'),
                'fees': order_result.get('fees')
            }
        )

    def log_position(self, action: str, position):
        """
        Log position event.

        Args:
            action: Action type ('open', 'close', 'update')
            position: Position object
        """
        message = f"{action.upper()}: {position.side.value} {position.size:.4f}"

        self.info(
            source='position',
            symbol=position.symbol,
            event=f'position_{action}',
            message=message,
            extra={
                'side': position.side.value,
                'size': position.size,
                'entry_price': position.entry_price,
                'current_price': position.current_price,
                'unrealized_pnl': position.unrealized_pnl,
                'stop_loss': position.stop_loss,
                'take_profit': position.take_profit
            }
        )

    def log_trade(self, trade):
        """
        Log completed trade.

        Args:
            trade: Trade object
        """
        self.info(
            source='trade',
            symbol=trade.symbol,
            event='trade_closed',
            message=f"PnL: {trade.pnl:.2f} ({trade.pnl_pct:.2f}%)",
            extra={
                'side': trade.side.value,
                'size': trade.size,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'pnl_pct': trade.pnl_pct,
                'fees': trade.fees,
                'slippage': trade.slippage,
                'duration_seconds': trade.duration_seconds
            }
        )

    def log_risk_event(self, event_type: str, message: str, details: Optional[Dict] = None):
        """
        Log risk management event.

        Args:
            event_type: Risk event type (halt, limit_breach, etc.)
            message: Event description
            details: Additional details
        """
        level = 'CRITICAL' if 'halt' in event_type else 'WARNING'

        self.log(
            level=level,
            source='risk',
            symbol='',
            event=event_type,
            message=message,
            extra=details
        )

    async def send_error_to_telegram(self, alerter, message: str, extra: Optional[Dict] = None):
        """
        Send ERROR/CRITICAL logs to Telegram.
        
        Args:
            alerter: TelegramAlerter instance
            message: Error message
            extra: Additional context
        """
        if alerter and alerter.enabled:
            error_text = f"🔴 *Trading Bot Error*\n{message}"
            if extra:
                error_text += f"\n\nDetails: `{json.dumps(extra, indent=2)}`"
            await alerter.send_message(error_text)

    def log_regime_change(self, old_regime, new_regime, indicators: Dict):
        """
        Log market regime change.

        Args:
            old_regime: Previous MarketRegime
            new_regime: New MarketRegime
            indicators: Current indicator values
        """
        self.info(
            source='regime',
            symbol='',
            event='regime_change',
            message=f"{old_regime.value} → {new_regime.value}",
            extra={
                'old_regime': old_regime.value,
                'new_regime': new_regime.value,
                'indicators': indicators
            }
        )

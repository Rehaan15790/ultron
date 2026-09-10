import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from src.config import settings

class AuditLogger:
    def __init__(self):
        self.logger = logging.getLogger("ultron.audit")
        self.logger.setLevel(logging.INFO)
        
        # Prevent adding multiple handlers if imported multiple times
        if not self.logger.handlers:
            # Rotating file handler (JSON Lines). Every routing decision is
            # logged, so an unbounded file fills the disk over time.
            handler = RotatingFileHandler(
                settings.AUDIT_LOG_PATH,
                maxBytes=settings.AUDIT_MAX_BYTES,
                backupCount=settings.AUDIT_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
            
            # Console Handler (Optional, for dev)
            console = logging.StreamHandler()
            console.setLevel(logging.WARNING) 
            self.logger.addHandler(console)

    def log_event(self, event_type: str, details: dict):
        """
        Logs a security event.
        event_type: router.decision | tool.allowed | tool.denied | tool.error | ollama.error | model.anomaly
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "details": details
        }
        self.logger.info(json.dumps(record))

# Singleton instance
audit = AuditLogger()
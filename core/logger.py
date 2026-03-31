"""
Modulo di logging avanzato per il sistema HelperBot.
Fornisce logging asincrono con rotazione automatica dei file.
"""

import logging
import os
import asyncio
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from queue import Queue
import threading
from logging.handlers import RotatingFileHandler

# Configurazione globale
LOG_DIR = Path("logs")
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5

# Livelli di log
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# Tipi di log
LOG_TYPES = ["errors", "access", "tickets", "admin", "ratelimit"]

# Formatter professionale
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(log_type)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class AsyncLogHandler(logging.Handler):
    """Handler asincrono per il logging non-bloccante."""
    
    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue
    
    def emit(self, record: logging.LogRecord):
        try:
            self.queue.put_nowait(record)
        except Exception:
            pass


class LogWriter(threading.Thread):
    """Thread per scrivere i log in background."""
    
    def __init__(self, queue: Queue, handlers: dict):
        super().__init__(daemon=True)
        self.queue = queue
        self.handlers = handlers
        self.running = True
    
    def run(self):
        while self.running:
            try:
                record = self.queue.get(timeout=0.1)
                if record is None:
                    continue
                
                log_type = record.log_type
                if log_type in self.handlers:
                    self.handlers[log_type].emit(record)
                
                self.queue.task_done()
            except Exception:
                continue
    
    def stop(self):
        self.running = False


class LoggerManager:
    """Manager centrale per tutti i logger."""
    
    def __init__(self):
        self.loggers: dict = {}
        self.handlers: dict = {}
        self.queue: Optional[Queue] = None
        self.writer: Optional[LogWriter] = None
        self.formatter: Optional[logging.Formatter] = None
    
    def setup(self):
        """Inizializza il sistema di logging."""
        # Crea la directory dei log
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Crea il formatter
        self.formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
        
        # Coda per logging asincrono
        self.queue = Queue(maxsize=1000)
        
        # Crea i logger per ogni tipo
        for log_type in LOG_TYPES:
            self._create_logger(log_type)
        
        # Avvia il writer asincrono
        self.writer = LogWriter(self.queue, self.handlers)
        self.writer.start()
    
    def _create_logger(self, log_type: str):
        """Crea un logger specifico per un tipo di log."""
        logger = logging.getLogger(f"helperbot.{log_type}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        
        # Crea il file handler con rotazione
        log_file = LOG_DIR / f"{log_type}.log"
        handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(self.formatter)
        
        # Handler asincrono
        async_handler = AsyncLogHandler(self.queue)
        async_handler.setFormatter(self.formatter)
        
        # Aggiungi attributo custom per il tipo di log
        class LogRecord(logging.LogRecord):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.log_type = log_type
        
        async_handler.setFormatter(self.formatter)
        
        # Salva riferimenti
        self.loggers[log_type] = logger
        self.handlers[log_type] = handler
    
    def log(self, log_type: str, level: str, message: str):
        """Logga un messaggio."""
        if log_type not in self.loggers:
            return
        
        log_level = LOG_LEVELS.get(level.upper(), logging.INFO)
        logger = self.loggers[log_type]
        
        # Crea record con attributo custom
        record = logging.LogRecord(
            name=f"helperbot.{log_type}",
            level=log_level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None
        )
        record.log_type = log_type
        
        # Usa il writer asincrono
        if self.queue:
            try:
                self.queue.put_nowait(record)
            except Exception:
                pass
        else:
            # Fallback sincrono
            logger.log(log_level, message)
    
    def rotate_logs(self):
        """Ruota manualmente i file di log."""
        for handler in self.handlers.values():
            if isinstance(handler, RotatingFileHandler):
                handler.doRollover()
    
    def shutdown(self):
        """Chiude il sistema di logging."""
        if self.writer:
            self.writer.stop()
            self.queue.put(None)
            self.writer.join(timeout=1.0)
        
        for handler in self.handlers.values():
            handler.close()
        
        logging.shutdown()


# Istanza globale del manager
_logger_manager: Optional[LoggerManager] = None


def setup_logger() -> LoggerManager:
    """
    Inizializza il sistema di logging.
    
    Returns:
        LoggerManager: L'istanza del manager dei logger.
    """
    global _logger_manager
    
    if _logger_manager is None:
        _logger_manager = LoggerManager()
        _logger_manager.setup()
    
    return _logger_manager


def get_logger_manager() -> Optional[LoggerManager]:
    """
    Ottiene l'istanza del manager dei logger.
    
    Returns:
        Optional[LoggerManager]: L'istanza del manager, o None se non inizializzato.
    """
    return _logger_manager


def log_error(message: str, level: str = "ERROR"):
    """
    Logga un errore.
    
    Args:
        message: Il messaggio da loggare.
        level: Il livello di log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    if _logger_manager:
        _logger_manager.log("errors", level, message)


def log_access(message: str, level: str = "INFO"):
    """
    Logga un accesso.
    
    Args:
        message: Il messaggio da loggare.
        level: Il livello di log.
    """
    if _logger_manager:
        _logger_manager.log("access", level, message)


def log_ticket(message: str, level: str = "INFO"):
    """
    Logga un'operazione su ticket.
    
    Args:
        message: Il messaggio da loggare.
        level: Il livello di log.
    """
    if _logger_manager:
        _logger_manager.log("tickets", level, message)


def log_admin(message: str, level: str = "INFO"):
    """
    Logga un'operazione admin.
    
    Args:
        message: Il messaggio da loggare.
        level: Il livello di log.
    """
    if _logger_manager:
        _logger_manager.log("admin", level, message)


def log_ratelimit(message: str, level: str = "WARNING"):
    """
    Logga una violazione rate limit.
    
    Args:
        message: Il messaggio da loggare.
        level: Il livello di log.
    """
    if _logger_manager:
        _logger_manager.log("ratelimit", level, message)


def rotate_logs():
    """
    Ruota manualmente i file di log se necessario.
    """
    if _logger_manager:
        _logger_manager.rotate_logs()


def shutdown_logging():
    """
    Chiude il sistema di logging in modo sicuro.
    """
    global _logger_manager
    
    if _logger_manager:
        _logger_manager.shutdown()
        _logger_manager = None


# Inizializzazione automatica all'importazione
def _auto_init():
    """Inizializza automaticamente il logger all'importazione."""
    setup_logger()


# Esporta le costanti
__all__ = [
    "setup_logger",
    "get_logger_manager",
    "log_error",
    "log_access",
    "log_ticket",
    "log_admin",
    "log_ratelimit",
    "rotate_logs",
    "shutdown_logging",
    "LOG_DIR",
    "LOG_TYPES",
    "LOG_LEVELS",
]

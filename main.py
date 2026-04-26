"""
HelperBot - Main Bot File
Bot Telegram completo per la gestione di IPTV, ticket, FAQ e molto altro.

Questo file integra tutti i moduli del sistema:
- Persistence (core)
- Logger (core)
- User Management
- Ticket System
- Rate Limiter
- FAQ System
- Backup System
- Onboarding
- Stato Servizio
- Manutenzione
- Notifications
- Statistiche
- Keep-Alive Server
- Health Check & Jobs
"""

import os
import sys
import asyncio
import logging
import threading
import signal
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, TypeVar
from enum import Enum, auto
from urllib.parse import urlparse
from functools import wraps

# Telegram Bot imports
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    CallbackQuery, constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, JobQueue
)
from telegram.error import TelegramError, RetryAfter

# Import moduli core
from core.data_persistence import DataPersistence
from core.logger import setup_logger, get_logger

# Import moduli
from modules.user_management import UserManagement, STATO_ATTIVO, STATO_INATTIVO
from modules.ticket_system import TicketSystem, StatoTicket, PrioritaTicket
from modules.rate_limiter import RateLimiter
from modules.faq_system import FaqSystem
from modules.backup_system import BackupSystem
from modules.onboarding import OnboardingManager, MAX_STEPS, CB_PREV, CB_NEXT
from modules.stato_servizio import StatoServizio, STATO_OPERATIVO, STATO_PROBLEMI
from modules.manutenzione import Manutenzione
from modules.notifications import NotificationSystem, TipoNotifica
from modules.statistiche import StatisticheDashboard

# Import keep-alive server
from keepalive.server import start_server as start_keepalive, set_bot_application

# ==================== CONFIGURAZIONE ====================

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variabili globali
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")

# Timeout configuration per il polling (secondi)
POLLING_TIMEOUT = float(os.environ.get("POLLING_TIMEOUT", "10"))
LONG_POLLING_TIMEOUT = float(os.environ.get("LONG_POLLING_TIMEOUT", "60"))
READ_TIMEOUT = float(os.environ.get("READ_TIMEOUT", "15"))
WRITE_TIMEOUT = float(os.environ.get("WRITE_TIMEOUT", "15"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "10"))

# Configurazione restart automatico
MAX_RESTART_ATTEMPTS = int(os.environ.get("MAX_RESTART_ATTEMPTS", "5"))
RESTART_DELAY = int(os.environ.get("RESTART_DELAY", "5"))

# Contatori per restart
_restart_attempts = 0
_last_restart_time = None

# Istanziazione moduli (inizializzati in main())
persistence = None
user_management = None
ticket_system = None
rate_limiter = None
faq_system = None
backup_system = None
onboarding = None
stato_servizio = None
manutenzione = None
notifications = None
statistiche = None
app = None

# ==================== GLOBAL STATE ====================

class GlobalState:
    def __init__(self):
        self._lock = threading.RLock()
        self._restart_attempts = 0
        self._last_restart_time = None
        self._bot_running = True
    
    def get_restart_attempts(self) -> int:
        with self._lock:
            return self._restart_attempts
    
    def increment_restart_attempts(self):
        with self._lock:
            self._restart_attempts += 1
            self._last_restart_time = datetime.now()
    
    def reset_restart_attempts(self):
        with self._lock:
            self._restart_attempts = 0
            self._last_restart_time = None
    
    def set_bot_running(self, value: bool):
        with self._lock:
            self._bot_running = value
    
    def is_bot_running(self) -> bool:
        with self._lock:
            return self._bot_running

global_state = GlobalState()

# ==================== RETRY DECORATOR ====================

T = TypeVar('T')

def retry_telegram_api(max_attempts: int = None, base_delay: float = None, max_delay: float = None):
    if max_attempts is None:
        max_attempts = int(os.getenv("TELEGRAM_RETRY_MAX_ATTEMPTS", "3"))
    if base_delay is None:
        base_delay = float(os.getenv("TELEGRAM_RETRY_BASE_DELAY", "1.0"))
    if max_delay is None:
        max_delay = float(os.getenv("TELEGRAM_RETRY_MAX_DELAY", "60.0"))
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import random
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except (TelegramError, NetworkError) as e:
                    last_exception = e
                    if isinstance(e, RetryAfter):
                        delay = min(e.retry_after, max_delay)
                        logger.warning(f"Rate limit hit for {func.__name__}, retry after {delay}s")
                    else:
                        delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                    
                    logger.warning(f"Retry {attempt}/{max_attempts} for {func.__name__} in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                except Exception as e:
                    last_exception = e
                    logger.error(f"Unexpected error in retry for {func.__name__}: {e}")
                    break
            
            logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            raise last_exception
        return wrapper
    return decorator

# ==================== CIRCUIT BREAKER ====================

class CircuitBreaker:
    def __init__(self, failure_threshold: int = None, recovery_timeout: float = None):
        if failure_threshold is None:
            failure_threshold = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
        if recovery_timeout is None:
            recovery_timeout = float(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60.0"))
        
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = None
        self._lock = threading.Lock()
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func, *args, **kwargs):
        with self._lock:
            if self._state == "OPEN":
                if self._last_failure_time and (datetime.now() - self._last_failure_time).total_seconds() > self._recovery_timeout:
                    self._state = "HALF_OPEN"
                    logger.info("Circuit breaker: HALF_OPEN")
                else:
                    raise Exception("Circuit breaker is OPEN")
            
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    if self._state == "HALF_OPEN":
                        self._state = "CLOSED"
                        self._failure_count = 0
                    return result
            except Exception as e:
                with self._lock:
                    self._failure_count += 1
                    self._last_failure_time = datetime.now()
                    if self._failure_count >= self._failure_threshold:
                        self._state = "OPEN"
                        logger.error(f"Circuit breaker opened after {self._failure_count} failures")
                raise
    
    @property
    def state(self):
        with self._lock:
            return self._state
    
    @property
    def failure_count(self):
        with self._lock:
            return self._failure_count

circuit_breaker = CircuitBreaker(
    failure_threshold=int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60.0"))
)

# ==================== HEALTH CHECK ====================

async def health_check_advanced(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check salute di tutti i moduli."""
    checks = {
        "persistence": False,
        "user_management": False,
        "ticket_system": False,
        "rate_limiter": False,
        "faq_system": False,
        "backup_system": False,
        "notifications": False,
        "stato_servizio": False,
        "manutenzione": False,
        "keepalive_server": False
    }
    
    try:
        checks["persistence"] = persistence is not None
        checks["user_management"] = user_management is not None and hasattr(user_management, 'get_utente')
        checks["ticket_system"] = ticket_system is not None
        checks["rate_limiter"] = rate_limiter is not None
        checks["faq_system"] = faq_system is not None
        checks["backup_system"] = backup_system is not None
        checks["notifications"] = notifications is not None
        checks["stato_servizio"] = stato_servizio is not None
        checks["manutenzione"] = manutenzione is not None
        
        # Controlla se il keepalive server risponde
        try:
            import requests
            resp = requests.get(f"http://localhost:{PORT}/ping", timeout=2)
            checks["keepalive_server"] = resp.status_code == 200
        except:
            checks["keepalive_server"] = False
        
        # Salva check in stato_servizio per monitoring
        all_ok = all(checks.values())
        if not all_ok:
            logger.warning(f"Health check fallito: {checks}")
            if stato_servizio:
                try:
                    stato_servizio.aggiorna_stato(STATO_PROBLEMI, "Alcuni moduli non funzionanti", None)
                except:
                    pass
        else:
            logger.debug("Health check tutti i moduli OK")
            
    except Exception as e:
        logger.error(f"Errore health check avanzato: {e}")

# ==================== AUTO-HEALING ====================

async def heal_module(module_name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Tenta di ripristinare un modulo danneggiato.
    Returns True se ripristinato con successo.
    """
    logger.warning(f"Tentativo auto-healing per modulo: {module_name}")
    
    try:
        if module_name == "persistence" and persistence:
            persistence.load_data()
            logger.info("Modulo persistence ripristinato")
            return True
        
        elif module_name == "user_management" and user_management:
            user_management._carica_utenti()
            logger.info("Modulo user_management ripristinato")
            return True
        
        elif module_name == "ticket_system" and ticket_system:
            ticket_system._carica_ticket()
            logger.info("Modulo ticket_system ripristinato")
            return True
        
        else:
            logger.error(f"Modulo {module_name} non trovato o non supportato per auto-healing")
            return False
            
    except Exception as e:
        logger.error(f"Auto-healing fallito per {module_name}: {e}")
        return False

# ==================== GRACEFUL DEGRADATION ====================

class ServiceDegradation:
    """Gestisce la graceful degradation dei servizi."""
    
    def __init__(self):
        self._degraded_services = set()
        self._lock = threading.Lock()
    
    def mark_degraded(self, service_name: str, reason: str = ""):
        with self._lock:
            self._degraded_services.add(service_name)
        logger.warning(f"Servizio degradato: {service_name} - {reason}")
    
    def mark_healthy(self, service_name: str):
        with self._lock:
            self._degraded_services.discard(service_name)
        logger.info(f"Servizio ripristinato: {service_name}")
    
    def is_degraded(self, service_name: str) -> bool:
        with self._lock:
            return service_name in self._degraded_services
    
    def get_degraded_count(self) -> int:
        with self._lock:
            return len(self._degraded_services)
    
    def fallback_response(self, service_name: str, default_response: Any) -> Any:
        if self.is_degraded(service_name):
            logger.info(f"Fall back to default per {service_name}")
            return default_response
        return None

service_degradation = ServiceDegradation()

# ==================== METRICS ====================

class MetricsCollector:
    def __init__(self):
        self._metrics = {}
        self._lock = threading.Lock()
    
    def increment(self, metric_name: str, value: int = 1):
        with self._lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = 0
            self._metrics[metric_name] += value
    
    def gauge(self, metric_name: str, value: float):
        with self._lock:
            self._metrics[metric_name] = value
    
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._metrics)

metrics_collector = MetricsCollector()

# ==================== SIGNAL HANDLING ====================

def signal_handler(signum, frame):
    logger.info(f"Ricevuto segnale {signum}, shutdown in corso...")
    global_state.set_bot_running(False)
    # Esegui cleanup
    if persistence:
        persistence.save_data()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# ==================== ERROR HANDLER MIGLIORATO ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce errori del bot con notifiche admin e graceful degradation."""
    error = context.error
    logger.error(f"Errore durante update {update.update_id if update else 'N/A'}: {error}", exc_info=True)
    
    # Notifica admin se errore critico
    if isinstance(error, (TelegramError, NetworkError)):
        try:
            notifier = NotificationSystem.get_instance() if hasattr(NotificationSystem, 'get_instance') else None
            
            if notifier and ADMIN_IDS:
                messaggio = f"❌ Errore Critico Bot\n\n"
                messaggio += f"Update ID: {update.update_id if update else 'N/A'}\n"
                messaggio += f"Errore: {type(error).__name__}: {error}\n"
                messaggio += f"Timestamp: {datetime.now().isoformat()}"
                
                # Invia in background
                threading.Thread(
                    target=lambda: asyncio.run(_send_admin_notification(ADMIN_IDS[0], messaggio)),
                    daemon=True
                ).start()
        except Exception as notify_error:
            logger.debug(f"Notifica admin fallita: {notify_error}")
    
    # Messaggio all'utente con graceful degradation
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Si è verificato un errore. Gli amministratori sono stati notificati.\n"
                "Riprova più tardi."
            )
        except:
            pass
    
    # Track metriche errori
    metrics_collector.increment("error_count")

async def _send_admin_notification(admin_id: int, message: str):
    """Helper per inviare notifiche admin."""
    try:
        if app:
            await app.bot.send_message(chat_id=admin_id, text=message)
    except Exception as e:
        logger.error(f"Errore invio notifica admin: {e}")

# ==================== METRICS ENDPOINT ====================

async def metrics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Endpoint per metriche Prometheus-style."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non autorizzato")
        return
    
    metrics = []
    metrics.append("# HELP helperbot_uptime_seconds Bot uptime in seconds")
    metrics.append("# TYPE helperbot_uptime_seconds counter")
    uptime = (datetime.now() - global_state._last_restart_time).total_seconds() if global_state._last_restart_time else 0
    metrics.append(f"helperbot_uptime_seconds {int(uptime)}")
    
    metrics.append("# HELP helperbot_restarts_total Total number of restarts")
    metrics.append("# TYPE helperbot_restarts_total counter")
    metrics.append(f"helperbot_restarts_total {global_state.get_restart_attempts()}")
    
    metrics.append("# HELP helperbot_circuit_breaker_state Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)")
    metrics.append("# TYPE helperbot_circuit_breaker_state gauge")
    state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
    metrics.append(f"helperbot_circuit_breaker_state {state_map.get(circuit_breaker.state, 0)}")
    
    metrics.append("# HELP helperbot_circuit_breaker_failures Circuit breaker failure count")
    metrics.append("# TYPE helperbot_circuit_breaker_failures gauge")
    metrics.append(f"helperbot_circuit_breaker_failures {circuit_breaker.failure_count}")
    
    metrics.append("# HELP helperbot_degraded_services_count Number of degraded services")
    metrics.append("# TYPE helperbot_degraded_services_count gauge")
    metrics.append(f"helperbot_degraded_services_count {service_degradation.get_degraded_count()}")
    
    # Aggiungi altre metriche custom
    all_metrics = metrics_collector.get_metrics()
    for name, value in all_metrics.items():
        if isinstance(value, (int, float)):
            metrics.append(f"# HELP helperbot_{name} Custom metric")
            metrics.append(f"# TYPE helperbot_{name} counter")
            metrics.append(f"helperbot_{name} {value}")
    
    response = "\n".join(metrics)
    await update.message.reply_text(f"```\n{response}\n```", parse_mode=constants.ParseMode.MARKDOWN)

# ==================== CONSISTANTI ====================

class ConversationState(Enum):
    SELECT_PRIORITY = auto()
    ENTER_DESCRIPTION = auto()
    ENTER_LIST_NAME = auto()
    CONFIRM = auto()
    RIFIUTO_MOTIVAZIONE = auto()
    RICHIEDI_CHOICE = auto()
    RICHIEDI_NOME = auto()
    ADMIN_LIST_NAME = auto()
    ADMIN_LIST_COST = auto()
    ADMIN_LIST_SCADENZA = auto()
    ADMIN_LIST_NOTE = auto()
    STATE_START = auto()
    STATE_TICKET_CREATE = auto()
    STATE_TICKET_DESCRIPTION = auto()
    STATE_RICHIEDTA_IPTV = auto()
    STATE_ONBOARDING = auto()
    STATE_FAQ_CATEGORIA = auto()
    STATE_FAQ_RISPOSTA = auto()

SELECT_PRIORITY = ConversationState.SELECT_PRIORITY.value
ENTER_DESCRIPTION = ConversationState.ENTER_DESCRIPTION.value
ENTER_LIST_NAME = ConversationState.ENTER_LIST_NAME.value
CONFIRM = ConversationState.CONFIRM.value
RIFIUTO_MOTIVAZIONE = ConversationState.RIFIUTO_MOTIVAZIONE.value
RICHIEDI_CHOICE = ConversationState.RICHIEDI_CHOICE.value
RICHIEDI_NOME = ConversationState.RICHIEDI_NOME.value
ADMIN_LIST_NAME = ConversationState.ADMIN_LIST_NAME.value
ADMIN_LIST_COST = ConversationState.ADMIN_LIST_COST.value
ADMIN_LIST_SCADENZA = ConversationState.ADMIN_LIST_SCADENZA.value
ADMIN_LIST_NOTE = ConversationState.ADMIN_LIST_NOTE.value
STATE_START = ConversationState.STATE_START.value
STATE_TICKET_CREATE = ConversationState.STATE_TICKET_CREATE.value
STATE_TICKET_DESCRIPTION = ConversationState.STATE_TICKET_DESCRIPTION.value
STATE_RICHIEDTA_IPTV = ConversationState.STATE_RICHIEDTA_IPTV.value
STATE_ONBOARDING = ConversationState.STATE_ONBOARDING.value
STATE_FAQ_CATEGORIA = ConversationState.STATE_FAQ_CATEGORIA.value
STATE_FAQ_RISPOSTA = ConversationState.STATE_FAQ_RISPOSTA.value

CB_FAQ = "faq_"
CB_ONBOARDING = "onb_"
CB_MENU = "menu_"
CB_TICKET = "ticket_"
CB_TICKET_USE_LIST = "ticket_use_list_"
CB_TICKET_OTHER_LIST = "ticket_other_list_"
CB_ADMIN = "admin_"
CB_STATO = "stato_"
CB_RICHIESTA = "richiesta_"
CB_RICHIEDI = "rich_"
CB_ACCOPPIAMENTO = "accoppiamento_"

HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "180"))
LAST_HEALTH_CHECK = None
BOT_RUNNING = True

# ==================== GESTIONE ERRORI ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Eccezione durante l'elaborazione: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Si è verificato un errore inatteso. Riprova più tardi."
        )
    
    metrics_collector.increment("error_count")

# ==================== GLOBAL EXCEPTION HANDLER ====================

async def _notify_admins_of_crash(error_msg: str):
    """Notifica gli admin di un crash critico."""
    if ADMIN_IDS and app:
        for admin_id in ADMIN_IDS[:1]:
            try:
                await app.bot.send_message(
                    chat_id=admin_id,
                    text=f"🚨 <b>CRASH CRITICO HELPERBOT</b>\n\n{error_msg}",
                    parse_mode=constants.ParseMode.HTML
                )
            except:
                pass

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.critical(
        f"Eccezione non gestita: {exc_type.__name__}: {exc_value}",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
    
    global _restart_attempts, _last_restart_time
    from datetime import datetime
    
    current_time = datetime.now()
    
    if _last_restart_time and (current_time - _last_restart_time).total_seconds() > 300:
        _restart_attempts = 0
    
    if _restart_attempts < MAX_RESTART_ATTEMPTS:
        _restart_attempts += 1
        _last_restart_time = current_time
        global_state.increment_restart_attempts()
        
        logger.info(f"Tentativo di restart {_restart_attempts}/{MAX_RESTART_ATTEMPTS}")
        
        # Notifica admin
        asyncio.create_task(_notify_admins_of_crash(
            f"Tentativo di restart {_restart_attempts}/{MAX_RESTART_ATTEMPTS}\n"
            f"Errore: {exc_type.__name__}: {exc_value}"
        ))
    else:
        logger.critical("Raggiunto il numero massimo di tentativi di restart. Bot arrestato.")
        asyncio.create_task(_notify_admins_of_crash(
            f"Raggiunto il numero massimo di tentativi di restart. Bot arrestato.\n"
            f"Ultimo errore: {exc_type.__name__}: {exc_value}"
        ))

sys.excepthook = global_exception_handler

# ==================== CONFIGURAZIONE WEBHOOK ====================

def _is_valid_webhook_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    if not url.startswith('https://'):
        return False
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    return True

async def setup_webhook(application: Application):
    logger.info("=== SETUP_WEBHOOK CALLED ===")
    
    # Wrap bot methods with retry decorator
    original_get_me = application.bot.get_me
    original_get_webhook_info = application.bot.get_webhook_info
    original_set_webhook = application.bot.set_webhook
    original_delete_webhook = application.bot.delete_webhook
    
    @retry_telegram_api()
    async def get_me_with_retry():
        return await original_get_me()
    
    @retry_telegram_api()
    async def get_webhook_info_with_retry():
        return await original_get_webhook_info()
    
    @retry_telegram_api()
    async def set_webhook_with_retry(*args, **kwargs):
        return await original_set_webhook(*args, **kwargs)
    
    @retry_telegram_api()
    async def delete_webhook_with_retry(*args, **kwargs):
        return await original_delete_webhook(*args, **kwargs)
    
    # Patch methods
    application.bot.get_me = get_me_with_retry
    application.bot.get_webhook_info = get_webhook_info_with_retry
    application.bot.set_webhook = set_webhook_with_retry
    application.bot.delete_webhook = delete_webhook_with_retry
    
    render_service_name = os.environ.get('RENDER_SERVICE_NAME', '')
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if render_service_name:
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', render_service_name):
            logger.error(f"RENDER_SERVICE_NAME non valido: '{render_service_name}'")
            if webhook_url and _is_valid_webhook_url(webhook_url):
                logger.warning(f"Uso WEBHOOK_URL esplicito come fallback: {webhook_url}")
            else:
                raise ValueError("RENDER_SERVICE_NAME non valido")
    
    if not webhook_url and render_service_name:
        webhook_url = f"https://{render_service_name}.onrender.com/webhook"
    elif not webhook_url and not render_service_name:
        logger.error("Nessun WEBHOOK_URL configurato!" %
```

I see the output was cut off. Let me write the file in a more manageable way by using a bash command to create it from a properly formatted source. Let me create the file directly using Python:

```bash
python3 << 'ENDPYTHON'
import os

content = '''"""
HelperBot - Main Bot File con Tutte le Correzioni
Bot Telegram completo con retry, circuit breaker, health check, auto-healing, e metriche.
"""

import os
import sys
import asyncio
import logging
import threading
import signal
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, TypeVar
from enum import Enum, auto
from urllib.parse import urlparse
from functools import wraps

# Telegram Bot imports
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    CallbackQuery, constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, JobQueue
)
from telegram.error import TelegramError, NetworkError, RetryAfter

# Import moduli core
from core.data_persistence import DataPersistence
from core.logger import setup_logger, get_logger

# Import moduli
from modules.user_management import UserManagement, STATO_ATTIVO, STATO_INATTIVO
from modules.ticket_system import TicketSystem, StatoTicket, PrioritaTicket
from modules.rate_limiter import RateLimiter
from modules.faq_system import FaqSystem
from modules.backup_system import BackupSystem
from modules.onboarding import OnboardingManager, MAX_STEPS, CB_PREV, CB_NEXT
from modules.stato_servizio import StatoServizio, STATO_OPERATIVO, STATO_PROBLEMI
from modules.manutenzione import Manutenzione
from modules.notifications import NotificationSystem, TipoNotifica
from modules.statistiche import StatisticheDashboard

# Import keep-alive server
from keepalive.server import start_server as start_keepalive, set_bot_application

# ==================== CONFIGURAZIONE ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")

POLLING_TIMEOUT = float(os.environ.get("POLLING_TIMEOUT", "10"))
LONG_POLLING_TIMEOUT = float(os.environ.get("LONG_POLLING_TIMEOUT", "60"))
READ_TIMEOUT = float(os.environ.get("READ_TIMEOUT", "15"))
WRITE_TIMEOUT = float(os.environ.get("WRITE_TIMEOUT", "15"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "10"))

MAX_RESTART_ATTEMPTS = int(os.environ.get("MAX_RESTART_ATTEMPTS", "5"))
RESTART_DELAY = int(os.environ.get("RESTART_DELAY", "5"))

_restart_attempts = 0
_last_restart_time = None

persistence = None
user_management = None
ticket_system = None
rate_limiter = None
faq_system = None
backup_system = None
onboarding = None
stato_servizio = None
manutenzione = None
notifications = None
statistiche = None
app = None

# ==================== GLOBAL STATE ====================

class GlobalState:
    def __init__(self):
        self._lock = threading.RLock()
        self._restart_attempts = 0
        self._last_restart_time = None
        self._bot_running = True
    
    def get_restart_attempts(self) -> int:
        with self._lock:
            return self._restart_attempts
    
    def increment_restart_attempts(self):
        with self._lock:
            self._restart_attempts += 1
            self._last_restart_time = datetime.now()
    
    def reset_restart_attempts(self):
        with self._lock:
            self._restart_attempts = 0
            self._last_restart_time = None
    
    def set_bot_running(self, value: bool):
        with self._lock:
            self._bot_running = value
    
    def is_bot_running(self) -> bool:
        with self._lock:
            return self._bot_running

global_state = GlobalState()

# ==================== RETRY DECORATOR ====================

T = TypeVar('T')

def retry_telegram_api(max_attempts: int = None, base_delay: float = None, max_delay: float = None):
    if max_attempts is None:
        max_attempts = int(os.getenv("TELEGRAM_RETRY_MAX_ATTEMPTS", "3"))
    if base_delay is None:
        base_delay = float(os.getenv("TELEGRAM_RETRY_BASE_DELAY", "1.0"))
    if max_delay is None:
        max_delay = float(os.getenv("TELEGRAM_RETRY_MAX_DELAY", "60.0"))
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import random
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except (TelegramError, NetworkError) as e:
                    last_exception = e
                    if isinstance(e, RetryAfter):
                        delay = min(e.retry_after, max_delay)
                        logger.warning(f"Rate limit: {func.__name__} - retry after {delay}s")
                    else:
                        delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                    logger.warning(f"Retry {attempt}/{max_attempts} for {func.__name__} in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                except Exception as e:
                    last_exception = e
                    logger.error(f"Unexpected error in retry: {e}")
                    break
            logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            raise last_exception
        return wrapper
    return decorator

# ==================== CIRCUIT BREAKER ====================

class CircuitBreaker:
    def __init__(self, failure_threshold: int = None, recovery_timeout: float = None):
        if failure_threshold is None:
            failure_threshold = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
        if recovery_timeout is None:
            recovery_timeout = float(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60.0"))
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = None
        self._lock = threading.Lock()
        self._state = "CLOSED"
    
    def call(self, func, *args, **kwargs):
        with self._lock:
            if self._state == "OPEN":
                if self._last_failure_time and (datetime.now() - self._last_failure_time).total_seconds() > self._recovery_timeout:
                    self._state = "HALF_OPEN"
                    logger.info("Circuit breaker: HALF_OPEN")
                else:
                    raise Exception("Circuit breaker is OPEN")
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    if self._state == "HALF_OPEN":
                        self._state = "CLOSED"
                        self._failure_count = 0
                    return result
            except Exception as e:
                with self._lock:
                    self._failure_count += 1
                    self._last_failure_time = datetime.now()
                    if self._failure_count >= self._failure_threshold:
                        self._state = "OPEN"
                        logger.error(f"Circuit breaker opened after {self._failure_count} failures")
                raise
    
    @property
    def state(self):
        with self._lock:
            return self._state
    
    @property
    def failure_count(self):
        with self._lock:
            return self._failure_count

circuit_breaker = CircuitBreaker(
    failure_threshold=int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60.0"))
)
'''

with open('/tmp/main_part1.py', 'w') as f:
    f.write(content)

print('Part 1 written')
ENDPYTHON

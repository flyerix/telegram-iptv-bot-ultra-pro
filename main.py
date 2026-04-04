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
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# Telegram Bot imports
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    CallbackQuery, constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, JobQueue
)

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


# ==================== COSTANTI ====================

# Stati per ConversationHandler
# Stati per ticket (nuovo ConversationHandler)
SELECT_PRIORITY, ENTER_DESCRIPTION, ENTER_LIST_NAME, CONFIRM = range(4)
# Stati per richiedi lista
RICHIEDI_CHOICE, RICHIEDI_NOME = range(14, 16)
# Stati per creazione lista admin
ADMIN_LIST_NAME, ADMIN_LIST_COST, ADMIN_LIST_SCADENZA, ADMIN_LIST_NOTE = range(16, 20)
# Stati esistenti
(
    STATE_START,
    STATE_TICKET_CREATE,
    STATE_TICKET_DESCRIPTION,
    STATE_RICHIEDTA_IPTV,
    STATE_ONBOARDING,
    STATE_FAQ_CATEGORIA,
    STATE_FAQ_RISPOSTA,
) = range(7, 14)

# Callback data prefixes
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

# Health check config
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "300"))  # 5 minuti
LAST_HEALTH_CHECK = None
BOT_RUNNING = True


# ==================== GESTIONE ERRORI ====================


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce gli errori del bot."""
    logger.error(f"Eccezione durante l'elaborazione: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Si è verificato un errore inatteso. Riprova più tardi."
        )


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Gestisce le eccezioni non catturate a livello globale."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.critical(
        f"Eccezione non gestita: {exc_type.__name__}: {exc_value}",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
    
    # Logica di restart
    global _restart_attempts, _last_restart_time
    from datetime import datetime
    
    current_time = datetime.now()
    
    # Reset contatori se è passato più di 5 minuti dall'ultimo tentativo
    if _last_restart_time and (current_time - _last_restart_time).total_seconds() > 300:
        _restart_attempts = 0
    
    if _restart_attempts < MAX_RESTART_ATTEMPTS:
        _restart_attempts += 1
        _last_restart_time = current_time
        
        logger.info(f"Tentativo di restart {_restart_attempts}/{MAX_RESTART_ATTEMPTS} in corso...")
    else:
        logger.critical("Raggiunto il numero massimo di tentativi di restart. Bot arrestato.")


# Registra l'handler globale
sys.excepthook = global_exception_handler


# ==================== CONFIGURAZIONE WEBHOOK ====================


async def setup_webhook(application: Application):
    """
    Configura il webhook con Telegram.
    Include retry con backoff per gestire rate limiting.
    
    Args:
        application: Application del bot Telegram
    """
    import asyncio
    from telegram.error import TelegramError, RetryAfter
    
    logger.info("=== SETUP_WEBHOOK CALLED ===")
    logger.info(f"Application.bot: {application.bot}")
    logger.info(f"Application.bot.token: {application.bot.token[:10] if application.bot and application.bot.token else 'N/A'}...")
    
    # Costruisci l'URL del webhook
    render_service_name = os.environ.get('RENDER_SERVICE_NAME', '')
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    # Se WEBHOOK_URL non è impostato, costruiscilo da RENDER_SERVICE_NAME
    if not webhook_url and render_service_name:
        webhook_url = f"https://{render_service_name}.onrender.com/webhook"
    elif not webhook_url and not render_service_name:
        webhook_url = f"https://telegram-iptv-bot-ultra-pro.onrender.com/webhook"
        logger.warning("⚠️ RENDER_SERVICE_NAME non è impostato! Usando fallback")
    
    logger.info(f"=== CONFIGURAZIONE WEBHOOK ===")
    logger.info(f"WEBHOOK_URL env: {os.environ.get('WEBHOOK_URL', 'NON SETTATA')}")
    logger.info(f"RENDER_SERVICE_NAME: {os.environ.get('RENDER_SERVICE_NAME', 'NON SETTATO')}")
    logger.info(f"URL webhook utilizzato: {webhook_url}")
    logger.info(f"===========================")
    
    # Token segreto opzionale per sicurezza aggiuntiva
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if webhook_secret:
        from keepalive.server import set_webhook_secret
        set_webhook_secret(webhook_secret)
        logger.info("Webhook secret token configurato")
    
    # Attendi un po' prima di configurare il webhook per evitare flood control
    logger.info("Attesa iniziale di 3 secondi per evitare flood control...")
    await asyncio.sleep(3)
    
    # Funzione per tentare di impostare il webhook con retry
    max_attempts = 5
    base_delay = 2  # secondi
    
    async def attempt_set_webhook(attempt: int) -> bool:
        try:
            # Verifica prima se il webhook è già configurato correttamente
            logger.info(f"Tentativo {attempt}/{max_attempts}: Verifico webhook esistente...")
            webhook_info = await application.bot.get_webhook_info()
            
            if webhook_info.url and webhook_info.url == webhook_url:
                logger.info(f"✅ Webhook già configurato correttamente: {webhook_info.url}")
                return True
            
            # Se non è configurato o ha un URL diverso, procedi con la configurazione
            logger.info(f"Webhook non configurato o diverso, procedo con la configurazione...")
            
            # Rimuovi qualsiasi webhook esistente
            logger.info(f"Tentativo {attempt}/{max_attempts}: Rimuovo webhook esistente...")
            try:
                await application.bot.delete_webhook()
                logger.info("Webhook esistente rimosso")
            except Exception as e:
                logger.warning(f"Errore rimozione webhook (probabilmente non esiste): {e}")
            
            # Piccola pausa
            await asyncio.sleep(1)
            
            # Configura il nuovo webhook
            logger.info(f"Tentativo {attempt}: Configuro webhook verso: {webhook_url}")
            await application.bot.set_webhook(
                url=webhook_url,
                secret_token=webhook_secret if webhook_secret else None,
                allowed_updates=["message", "callback_query", "edited_message", "channel_post"]
            )
            
            logger.info("Webhook impostato, verifico...")
            
            # VERIFICA
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"Webhook info - URL: {webhook_info.url}")
            logger.info(f"Webhook info - pending_updates: {webhook_info.pending_update_count}")
            
            if webhook_info.url == webhook_url:
                logger.info("✅ Webhook configurato correttamente!")
                return True
            else:
                logger.warning(f"⚠️ Webhook URL non corrisponde!")
                return False
            
        except RetryAfter as e:
            delay = e.retry_after
            logger.warning(f"Rate limit raggiunto, attendo {delay} secondi...")
            await asyncio.sleep(delay)
            return False
        
        except TelegramError as e:
            logger.error(f"Errore Telegram tentativo {attempt}: {e}")
            # Calcola delay con backoff
            delay = base_delay * (2 ** (attempt - 1))  # 2, 4, 8, 16 secondi
            logger.info(f"Attendo {delay} secondi prima del prossimo tentativo...")
            await asyncio.sleep(delay)
            return False
        
        except Exception as e:
            logger.error(f"Errore generico tentativo {attempt}: {e}")
            delay = base_delay * (2 ** (attempt - 1))
            await asyncio.sleep(delay)
            return False
    
    # Esegui i tentativi
    for attempt in range(1, max_attempts + 1):
        success = await attempt_set_webhook(attempt)
        if success:
            logger.info("=== WEBHOOK CONFIGURATO CON SUCCESSO ===")
            return
        
        if attempt < max_attempts:
            logger.warning(f"Tentativo {attempt} fallito, proseguo con il prossimo...")
    
    # Se tutti i tentativi falliscono
    logger.error("⚠️ Impossibile configurare il webhook dopo tutti i tentativi!")


# ==================== MIDDLEWARE ====================

async def check_manutenzione(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica se il bot è in modalità manutenzione."""
    if manutenzione.is_manutenzione_attiva():
        user_id = update.effective_user.id if update.effective_user else 0
        
        # Gli admin possono sempre accedere
        if user_id in ADMIN_IDS:
            return False
        
        # Messaggio di manutenzione
        messaggio = manutenzione.get_messaggio_manutenzione()
        if update.message:
            await update.message.reply_text(messaggio)
        elif update.callback_query:
            await update.callback_query.answer(messaggio, show_alert=True)
        
        return True
    return False


async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica rate limit per l'utente."""
    user_id = str(update.effective_user.id if update.effective_user else 0)
    
    if not rate_limiter.check_rate_limit(user_id, "comando"):
        # Limite superato
        if update.message:
            await update.message.reply_text(
                "⏳ Troppe richieste! Riprova tra qualche secondo."
            )
        return True
    return False


# ==================== COMANDI UTENTE ====================

async def mostra_menu_principale(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False, query: CallbackQuery = None):
    """Mostra il menu principale con i pulsanti di navigazione."""
    user = update.effective_user
    user_id = update.effective_user.id
    
    # Costruisci il menu
    keyboard = [
        [
            InlineKeyboardButton("🚀 Inizia Onboarding", callback_data=f"{CB_ONBOARDING}start"),
            InlineKeyboardButton("❓ FAQ", callback_data=f"{CB_FAQ}categorie")
        ],
        [
            InlineKeyboardButton("🎫 Crea Ticket", callback_data=f"{CB_TICKET}create"),
            InlineKeyboardButton("📊 Il mio stato", callback_data=f"{CB_MENU}stato")
        ]
    ]
    
    # Aggiungi pulsanti admin se l'utente è admin
    if user_id in ADMIN_IDS:
        keyboard.append([
            InlineKeyboardButton("⚙️ Menu Admin", callback_data=f"{CB_ADMIN}menu")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (f"👋 Benvenuto <b>{user.full_name}</b>!\n\n"
        f"Sono HelperBot, il tuo assistente per la gestione IPTV.\n\n"
        f"Posso aiutarti con:\n"
        f"• 📺 Informazioni sulla tua lista IPTV\n"
        f"• 🎫 Creare ticket di supporto\n"
        f"• ❓ FAQ e guide\n"
        f"• 📊 Stato del servizio\n\n"
        f"Cosa vuoi fare?")
    
    if query is not None:
        # È stato chiamato da un callback handler
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)
    elif edit and query is not None:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Avvia il bot."""
    user = update.effective_user
    logger.info(f"Utente {user.id} ({user.username}) ha avviato il bot")
    
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    # Registra l'utente se non esiste
    user_data = user_management.registra_utente(
        str(user.id),
        user.username or "",
        user.full_name
    )
    
    # Mostra il menu principale
    await mostra_menu_principale(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help - Mostra l'aiuto."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    help_text = """
🔰 <b>Guida HelperBot</b>

<b>Comandi disponibili:</b>

<b>📋 Comandi base:</b>
/start - Avvia il bot
/help - Mostra questa guida
/faq - Visualizza le FAQ
/stato - Stato del servizio
/ping - Verifica stato bot

<b>🎫 Supporto:</b>
/ticket - Crea un ticket di supporto
/miei_ticket - Visualizza i tuoi ticket

<b>📺 IPTV:</b>
/richiedi - Richiedi la lista IPTV
/lista - Visualizza la tua lista

<b>ℹ️ Info:</b>
/stats - Statistiche del bot
"""
    
    await update.message.reply_text(help_text, parse_mode=constants.ParseMode.HTML)


async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /faq - Naviga le FAQ."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    # Mostra categorie FAQ
    keyboard = []
    for cat_id, cat_nome in FaqSystem.CATEGORIE.items():
        keyboard.append([
            InlineKeyboardButton(cat_nome, callback_data=f"{CB_FAQ}categoria_{cat_id}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "❓ <b>Scegli una categoria FAQ:</b>",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ticket - Crea un ticket."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    # Verifica rate limit
    if await rate_limit_check(update, context):
        return
    
    user = update.effective_user
    
    # Mostra menu creazione ticket
    keyboard = [
        [
            InlineKeyboardButton("🔴 Alta Priorità", callback_data=f"{CB_TICKET}priorita_alta"),
            InlineKeyboardButton("🟡 Media Priorità", callback_data=f"{CB_TICKET}priorita_media")
        ],
        [
            InlineKeyboardButton("🟢 Bassa Priorità", callback_data=f"{CB_TICKET}priorita_bassa")
        ],
        [
            InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎫 <b>Creazione Ticket di Supporto</b>\n\n"
        "Seleziona la priorità del ticket:",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_miei_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /miei_ticket - Visualizza i tuoi ticket."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    user_id = str(update.effective_user.id)
    
    # Ottieni ticket dell'utente
    ticket_list = ticket_system.get_ticket_utente(user_id)
    
    if not ticket_list:
        await update.message.reply_text(
            "📭 <b>Nessun ticket trovato</b>\n\n"
            "Non hai ancora creato nessun ticket.",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    # Formatta lista ticket
    text = "🎫 <b>I tuoi ticket:</b>\n\n"
    
    for ticket in ticket_list:
        stato_emoji = "🟢" if ticket.get("stato") == StatoTicket.RISOLTO.value else "🔵"
        text += f"{stato_emoji} <b>Ticket #{ticket.get('id')[:8]}</b>\n"
        text += f"   📝 {ticket.get('titolo', 'Senza titolo')}\n"
        text += f"   📊 Stato: {ticket.get('stato')}\n"
        text += f"   ⏰ {ticket.get('data_creazione', '')}\n\n"
    
    await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML)


async def cmd_stato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /stato - Stato del servizio."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    # Ottieni stato servizio
    stato = stato_servizio.get_stato()
    problemi = stato_servizio.get_problemi_attivi()
    
    # Determina emoji stato
    if stato == STATO_OPERATIVO:
        emoji = "✅"
    elif stato == STATO_PROBLEMI:
        emoji = "🟡"
    else:
        emoji = "🔴"
    
    text = f"📊 <b>Stato del Servizio</b>\n\n"
    text += f"{emoji} <b>Stato:</b> {stato}\n"
    
    if problemi:
        text += "\n⚠️ <b>Problemi attuali:</b>\n"
        for p in problemi:
            text += f"• {p.get('descrizione', '')}\n"
    
    # Aggiungi statistiche
    info = stato_servizio.get_info_completa()
    if info:
        uptime = info.get("ultimo_riavvio", "N/A")
        text += f"\n⏱️ <b>Ultimo riavvio:</b> {uptime}"
    
    await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ping - Verifica lo stato del bot."""
    try:
        bot = context.bot
        me = await bot.get_me()
        
        webhook_info = await bot.get_webhook_info()
        
        text = f"🏓 <b>Pong!</b>\n\n"
        text += f"🤖 <b>Bot:</b> @{me.username}\n"
        text += f"🆔 <b>ID:</b> {me.id}\n"
        text += f"🌐 <b>Webhook:</b> {webhook_info.url or 'Non impostato'}\n"
        text += f"📊 <b>Pending updates:</b> {webhook_info.pending_update_count}\n"
        
        text += f"\n⏱️ <b>Uptime:</b> "
        if stato_servizio:
            info = stato_servizio.get_info_completa()
            if info:
                text += info.get("ultimo_riavvio", "N/A")
            else:
                text += "N/A"
        else:
            text += "N/A"
        
        text += f"\n\n✅ <b>Stato:</b> Bot operativo"
        
        await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Errore /ping: {e}")
        await update.message.reply_text(
            f"❌ <b>Errore</b>\n\n{e}",
            parse_mode=constants.ParseMode.HTML
        )


async def cmd_richiedi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /richiedi - Richiedi lista IPTV."""
    if await check_manutenzione(update, context):
        return
    
    if await rate_limit_check(update, context):
        return
    
    user_id = str(update.effective_user.id)
    
    richieste = user_management.get_richieste_utente(user_id)
    richieste_attive = [r for r in richieste if r.get("stato") == "in_attesa"]
    
    if richieste_attive:
        await update.message.reply_text(
            "⏳ <b>Richiesta già in corso</b>\n\n"
            "Hai già una richiesta in attesa di approvazione.",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    lista = user_management.get_lista_utente(user_id)
    if lista:
        await update.message.reply_text(
            "✅ <b>Hai già una lista IPTV attiva!</b>\n\n"
            f"Usa /lista per visualizzarla.",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("📋 Lista esistente", callback_data="rich_esistente")],
        [InlineKeyboardButton("🎫 Crea Ticket", callback_data="rich_ticket")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📺 <b>Richiedi lista IPTV</b>\n\n"
        "Cosa vuoi fare?",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def richiedi_choice_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce la scelta dell'utente nel menu /richiedi."""
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    
    if query.data == "rich_esistente":
        await query.edit_message_text(
            "📺 <b>Inserisci nome lista</b>\n\n"
            "Inserisci il nome della lista IPTV che vuoi monitorare:",
            parse_mode=constants.ParseMode.HTML
        )
        return RICHIEDI_NOME
    elif query.data == "rich_ticket":
        keyboard = [
            [
                InlineKeyboardButton("🔴 Alta", callback_data=f"{CB_TICKET}priorita_alta"),
                InlineKeyboardButton("🟡 Media", callback_data=f"{CB_TICKET}priorita_media"),
                InlineKeyboardButton("🟢 Bassa", callback_data=f"{CB_TICKET}priorita_bassa")
            ],
            [InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎫 <b>Creazione Ticket</b>\n\n"
            "Seleziona la <b>priorità</b> del ticket:",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
        context.user_data["ticket_priorita"] = "media"
        return SELECT_PRIORITY
    
    return ConversationHandler.END


async def richiedi_nome_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve il nome della lista e crea la richiesta."""
    lista_nome = update.message.text
    user_id = str(update.effective_user.id)
    
    richiesta = user_management.crea_richiesta(
        user_id,
        update.effective_user.username or "",
        lista_nome
    )
    
    if richiesta:
        await update.message.reply_text(
            f"✅ <b>Richiesta inviata!</b>\n\n"
            f"La tua richiesta per la lista «{lista_nome}» è stata inoltrata agli admin.",
            parse_mode=constants.ParseMode.HTML
        )
        await notifica_admin_richiesta(richiesta)
    else:
        await update.message.reply_text(
            "❌ Errore nell'invio della richiesta.",
            parse_mode=constants.ParseMode.HTML
        )
    
    return ConversationHandler.END


async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /lista - Visualizza la tua lista IPTV."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    user_id = str(update.effective_user.id)
    
    # Ottieni lista IPTV dell'utente
    lista = user_management.get_lista_utente(user_id)
    
    if not lista:
        await update.message.reply_text(
            "📭 <b>Nessuna lista IPTV</b>\n\n"
            "Non hai ancora una lista IPTV attiva. Usa /richiedi per richiederne una.",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    # Formatta info lista
    text = f"📺 <b>La tua Lista IPTV</b>\n\n"
    text += f"🔗 <b>URL:</b> <code>{lista.get('url', 'N/A')}</code>\n"
    text += f"📊 <b>Stato:</b> {lista.get('stato', 'N/A')}\n"
    text += f"📅 <b>Scadenza:</b> {lista.get('data_scadenza', 'N/A')}\n"
    
    if lista.get("note"):
        text += f"\n📝 <b>Note:</b> {lista.get('note')}"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Aggiorna Lista", callback_data=f"{CB_MENU}aggiorna_lista")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


# ==================== COMANDI ADMIN ====================

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /admin - Menu admin."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("📋 Gestione Richieste", callback_data=f"{CB_ADMIN}richieste"),
            InlineKeyboardButton("🎫 Gestione Ticket", callback_data=f"{CB_ADMIN}ticket")
        ],
        [
            InlineKeyboardButton("💾 Gestione Backup", callback_data=f"{CB_ADMIN}backup"),
            InlineKeyboardButton("📊 Statistiche", callback_data=f"{CB_ADMIN}stats")
        ],
        [
            InlineKeyboardButton("🔧 Manutenzione", callback_data=f"{CB_ADMIN}manutenzione"),
            InlineKeyboardButton("📡 Stato Servizio", callback_data=f"{CB_ADMIN}stato")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ <b>Menu Admin</b>",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_richieste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /richieste - Gestisci richieste lista."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    # Ottieni richieste in attesa
    richieste = user_management.get_richieste_in_attesa()
    
    if not richieste:
        await update.message.reply_text(
            "📭 <b>Nessuna richiesta in attesa</b>",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    # Mostra richieste
    text = "📋 <b>Richieste in attesa:</b>\n\n"
    
    for richiesta in richieste[:10]:  # Max 10
        text += f"🆔 <b>{richiesta.get('user_id')}</b>\n"
        text += f"👤 {richiesta.get('username', 'N/A')}\n"
        text += f"📅 {richiesta.get('data_richiesta')}\n"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Approva", callback_data=f"{CB_ADMIN}approva_{richiesta.get('id')}"),
                InlineKeyboardButton("❌ Rifiuta", callback_data=f"{CB_ADMIN}rifiuta_{richiesta.get('id')}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)
        text = "📋 <b>Prossima richiesta:</b>\n\n"


async def cmd_ticket_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ticket_admin - Gestisci tutti i ticket."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    # Ottieni tutti i ticket aperti
    ticket_list = ticket_system.get_tutti_ticket(stato=StatoTicket.APERTO)
    
    if not ticket_list:
        await update.message.reply_text(
            "📭 <b>Nessun ticket aperto</b>",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    # Mostra ticket
    text = "🎫 <b>Ticket aperti:</b>\n\n"
    
    for ticket in ticket_list[:10]:  # Max 10
        prio_emoji = "🔴" if ticket.get("priorita") == PrioritaTicket.ALTA.value else "🟡"
        text += f"{prio_emoji} <b>Ticket #{ticket.get('id')[:8]}</b>\n"
        text += f"   👤 Utente: {ticket.get('user_id')}\n"
        text += f"   📝 {ticket.get('titolo', 'Senza titolo')}\n"
        text += f"   📊 Stato: {ticket.get('stato')}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"{CB_ADMIN}ticket_refresh")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /backup - Gestisci backup."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("💾 Crea Backup Ora", callback_data=f"{CB_ADMIN}backup_create"),
            InlineKeyboardButton("📥 Ripristina Backup", callback_data=f"{CB_ADMIN}backup_restore")
        ],
        [
            InlineKeyboardButton("☁️ Upload Drive", callback_data=f"{CB_ADMIN}backup_drive_upload"),
            InlineKeyboardButton("☁️ Download Drive", callback_data=f"{CB_ADMIN}backup_drive_download")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💾 <b>Gestione Backup</b>",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /stats - Visualizza statistiche."""
    user_id = update.effective_user.id
    
    # Controlla manutenzione per utenti normali
    if user_id not in ADMIN_IDS:
        if await check_manutenzione(update, context):
            return
    
    # Genera statistiche
    stats_text = statistiche.genera_report_completo()
    
    await update.message.reply_text(
        f"📊 <b>Statistiche HelperBot</b>\n\n{stats_text}",
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_manutenzione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /manutenzione - Attiva/disattiva manutenzione."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    # Toggle manutenzione
    if manutenzione.is_manutenzione_attiva():
        manutenzione.disattiva_manutenzione(str(user_id))
        await update.message.reply_text(
            "✅ <b>Manutenzione disattivata</b>\n\nIl bot è tornato operativo.",
            parse_mode=constants.ParseMode.HTML
        )
    else:
        keyboard = [
            [
                InlineKeyboardButton("🔧 Attiva Manutenzione", callback_data=f"{CB_ADMIN}manutenzione_attiva")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚠️ <b>Attiva manutenzione?</b>\n\nGli utenti normali non potranno usare il bot.",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )


async def cmd_stato_servizio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /stato_servizio - Aggiorna stato servizio."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Non sei autorizzato a usare questo comando.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Operativo", callback_data=f"{CB_ADMIN}stato_op"),
            InlineKeyboardButton("🟡 Problemi", callback_data=f"{CB_ADMIN}stato_prob")
        ],
        [
            InlineKeyboardButton("🔴 Disservizio", callback_data=f"{CB_ADMIN}stato_dis"),
            InlineKeyboardButton("🔧 Manutenzione", callback_data=f"{CB_ADMIN}stato_mnt")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📡 <b>Aggiorna Stato Servizio</b>",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


# ==================== CALLBACK QUERY HANDLERS ====================

async def handle_callback_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce callback delle FAQ."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == f"{CB_FAQ}categorie":
        # Mostra categorie
        keyboard = []
        for cat_id, cat_nome in FaqSystem.CATEGORIE.items():
            keyboard.append([
                InlineKeyboardButton(cat_nome, callback_data=f"{CB_FAQ}categoria_{cat_id}")
            ])
        
        # Aggiungi pulsante Menu Principale
        keyboard.append([
            InlineKeyboardButton("🏠 Menu Principale", callback_data=f"{CB_MENU}main")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❓ <b>Scegli una categoria FAQ:</b>",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_FAQ}categoria_"):
        cat_id = data.replace(f"{CB_FAQ}categoria_", "")
        faqs = faq_system.get_faq_categoria(cat_id)
        
        if not faqs:
            await query.edit_message_text("❓ Nessuna FAQ in questa categoria.")
            return
        
        keyboard = []
        for faq in faqs[:10]:
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 {faq.get('domanda', '')[:50]}...",
                    callback_data=f"{CB_FAQ}view_{faq.get('id')}"
                )
            ])
        
        # Torna alle categorie
        keyboard.append([
            InlineKeyboardButton("🔙 Torna alle categorie", callback_data=f"{CB_FAQ}categorie")
        ])
        
        # Aggiungi pulsante Menu Principale
        keyboard.append([
            InlineKeyboardButton("🏠 Menu Principale", callback_data=f"{CB_MENU}main")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        cat_nome = FaqSystem.CATEGORIE.get(cat_id, cat_id)
        await query.edit_message_text(
            f"❓ <b>{cat_nome}</b>\n\nSeleziona una domanda:",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_FAQ}view_"):
        faq_id = int(data.replace(f"{CB_FAQ}view_", ""))
        faq = faq_system.get_faq_id(faq_id)
        
        if not faq:
            await query.edit_message_text("❓ FAQ non trovata.")
            return
        
        text = f"❓ <b>{faq.get('domanda')}</b>\n\n{faq.get('risposta')}"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Torna alle FAQ", callback_data=f"{CB_FAQ}categorie")],
            [InlineKeyboardButton("🏠 Menu Principale", callback_data=f"{CB_MENU}main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )


async def handle_callback_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce callback dell'onboarding."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(update.effective_user.id)
    
    try:
        if data == f"{CB_ONBOARDING}start":
            # Reset onboarding e ricomincia
            onboarding._salva_stato(user_id, 1)
            username = update.effective_user.username or ""
            msg, keyboard = onboarding.inizia_onboarding(user_id, username, update.effective_user.full_name)
            if msg:
                try:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                except Exception as e:
                    if "Message is not modified" in str(e):
                        await query.answer("Onboarding già avviato!", show_alert=False)
                    else:
                        raise
        
        elif data.startswith(f"{CB_ONBOARDING}step_"):
            step_num = int(data.replace(f"{CB_ONBOARDING}step_", ""))
            username = update.effective_user.username or ""
            msg, keyboard = onboarding.genera_messaggio_step(step_num, username)
            if msg:
                # Evita errore "Message is not modified"
                current_msg = query.message.text if query.message else ""
                if current_msg != msg:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                else:
                    await query.answer()
        
        elif data == f"{CB_ONBOARDING}next":
            # Pulsante "Avanti" - vai al prossimo step
            msg, keyboard = onboarding.prossimo_step(user_id)
            if msg:
                try:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                except Exception as e:
                    if "Message is not modified" in str(e):
                        logger.info(f"Onboarding: messaggio non modificato")
                        await query.answer("Sei già a questo step", show_alert=False)
                    else:
                        raise
            else:
                onboarding.completa_onboarding(user_id)
                
                keyboard = [
                    [InlineKeyboardButton("📋 Ho già una lista", callback_data=f"{CB_ONBOARDING}lista_existing")],
                    [InlineKeyboardButton("🎫 Crea Ticket", callback_data=f"{CB_TICKET}create")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_text(
                        "✅ <b>Onboarding completato!</b>\n\n"
                        "Cosa vuoi fare?",
                        reply_markup=reply_markup,
                        parse_mode=constants.ParseMode.HTML
                    )
                except Exception as e:
                    if "Message is not modified" in str(e):
                        await query.answer("Onboarding completato!", show_alert=False)
                    else:
                        raise
        
        elif data == f"{CB_ONBOARDING}prev":
            # Pulsante "Precedente"
            msg, keyboard = onboarding.precedente_step(user_id)
            if msg:
                try:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                except Exception as e:
                    if "Message is not modified" in str(e):
                        logger.info(f"Onboarding: messaggio non modificato")
                        await query.answer("Sei già a questo step", show_alert=False)
                    else:
                        raise
        
        elif data == f"{CB_ONBOARDING}skip":
            await query.answer()
            onboarding.completa_onboarding(user_id)
            
            keyboard = [
                [InlineKeyboardButton("📋 Ho già una lista", callback_data=f"{CB_ONBOARDING}lista_existing")],
                [InlineKeyboardButton("🎫 Crea Ticket", callback_data=f"{CB_TICKET}create")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    "✅ <b>Onboarding completato!</b>\n\n"
                    "Cosa vuoi fare?",
                    reply_markup=reply_markup,
                    parse_mode=constants.ParseMode.HTML
                )
            except Exception as e:
                if "Message is not modified" in str(e):
                    await query.answer("Onboarding completato!", show_alert=False)
                else:
                    raise
        elif data == f"{CB_ONBOARDING}lista_existing":
            utente = user_management.get_utente(user_id)
            lista_approvata = utente.get("lista_approvata") if utente else None
            
            if lista_approvata:
                lista = user_management.get_lista(lista_approvata)
                if lista:
                    text = f"📺 <b>La tua lista</b>\n\n"
                    text += f"📺 {lista.get('nome')}\n"
                    text += f"📅 Scadenza: {lista.get('data_scadenza', 'N/A')}"
                else:
                    text = "📺 <b>Hai una lista approvata</b>\n\n"
                    text += "Usa /lista per vederla."
            else:
                text = "📭 <b>Nessuna lista</b>\n\n"
                text += "Invia una richiesta con /richiedi per ottenere una lista."
            
            keyboard = [
                [InlineKeyboardButton("📋 Richiedi Lista", callback_data=f"{CB_MENU}richiedi")],
                [InlineKeyboardButton("🏠 Menu", callback_data=f"{CB_MENU}main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Errore onboarding: {e}")
        await query.answer(f"Errore: {e}", show_alert=True)


async def mostra_step_onboarding(query: CallbackQuery, user_id: str, step: Dict):
    """Mostra uno step dell'onboarding."""
    keyboard = []
    
    # Pulsanti navigazione
    nav_buttons = []
    if step.get("step_number", 1) > 1:
        nav_buttons.append(
            InlineKeyboardButton("◀️ Precedente", callback_data=f"{CB_ONBOARDING}step_{step.get('step_number')-1}")
        )
    
    if step.get("step_number", 1) < 3:
        nav_buttons.append(
            InlineKeyboardButton("Successivo ▶️", callback_data=f"{CB_ONBOARDING}step_{step.get('step_number')+1}")
        )
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([
        InlineKeyboardButton("⏭️ Salta", callback_data=f"{CB_ONBOARDING}skip")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🚀 <b>Onboarding - Step {step.get('step_number')}/3</b>\n\n"
        f"<b>{step.get('title')}</b>\n\n"
        f"{step.get('content')}",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def handle_callback_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce callback dei ticket."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(update.effective_user.id)
    
    if data == f"{CB_TICKET}create":
        # Mostra form creazione ticket - avvia ConversationHandler
        keyboard = [
            [
                InlineKeyboardButton("🔴 Alta", callback_data=f"{CB_TICKET}priorita_alta"),
                InlineKeyboardButton("🟡 Media", callback_data=f"{CB_TICKET}priorita_media"),
                InlineKeyboardButton("🟢 Bassa", callback_data=f"{CB_TICKET}priorita_bassa")
            ],
            [
                InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎫 <b>Creazione Ticket</b>\n\n"
            "Seleziona la priorità del ticket:\n\n"
            "🔴 Alta: Problemi gravi, servizio non funzionante\n"
            "🟡 Media: Problemi minori, rallentamenti\n"
            "🟢 Bassa: Domande, informazioni",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
        return SELECT_PRIORITY
    
    elif data.startswith(f"{CB_TICKET}priorita_"):
        # Salva priorità e passa al prossimo step
        priorita = data.replace(f"{CB_TICKET}priorita_", "")
        
        # Salva nei user_data
        context.user_data["ticket_priorita"] = priorita
        
        await query.edit_message_text(
            f"🎫 <b>Ticket priorità {priorita.upper()}</b>\n\n"
            "Descrivi il tuo problema in dettaglio:",
            parse_mode=constants.ParseMode.HTML
        )
        return ENTER_DESCRIPTION
    
    elif data == f"{CB_TICKET}annulla":
        # Annulla creazione ticket
        await query.edit_message_text(
            "❌ Creazione ticket annullata.",
            parse_mode=constants.ParseMode.HTML
        )
        return ConversationHandler.END
    
    elif data.startswith(f"{CB_TICKET_USE_LIST}"):
        # Usa la lista esistente dell'utente
        lista_nome = data.replace(f"{CB_TICKET_USE_LIST}", "")
        context.user_data["ticket_lista"] = lista_nome
        
        # Mostra schermata di conferma
        priorita = context.user_data.get("ticket_priorita", "media")
        descrizione = context.user_data.get("ticket_descrizione", "")
        
        text = (f"🎫 <b>Conferma Ticket</b>\n\n"
                f"⚡ <b>Priorità:</b> {priorita.upper()}\n"
                f"📺 <b>Lista IPTV:</b> {lista_nome}\n\n"
                f"📝 <b>Descrizione:</b>\n{descrizione}")
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Conferma", callback_data=f"{CB_TICKET}conferma"),
                InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
        return CONFIRM
    
    elif data == f"{CB_TICKET_OTHER_LIST}":
        # L'utente vuole inserire un'altra lista
        await query.edit_message_text(
            "📺 <b>Inserisci nome lista IPTV</b>\n\n"
            "Inserisci il nome della lista IPTV per cui hai bisogno di supporto:",
            parse_mode=constants.ParseMode.HTML
        )
        return ENTER_LIST_NAME
    
    elif data == f"{CB_TICKET}conferma":
        # Crea il ticket
        priorita = context.user_data.get("ticket_priorita", "media")
        descrizione = context.user_data.get("ticket_descrizione", "")
        lista = context.user_data.get("ticket_lista", "Non specificata")
        
        # Crea il ticket
        try:
            ticket = ticket_system.crea_ticket(
                user_id=user_id,
                problema=f"[{lista}] {descrizione}",
                categoria=priorita
            )
            
            if ticket:
                await query.edit_message_text(
                    f"✅ <b>Ticket creato con successo!</b>\n\n"
                    f"🎫 <b>Ticket #{ticket.get('id', '')[:8]}</b>\n"
                    f"📊 Stato: {ticket.get('stato', 'Aperto')}\n"
                    f"⚡ Priorità: {priorita.upper()}\n\n"
                    "Un admin ti risponderà al più presto.",
                    parse_mode=constants.ParseMode.HTML
                )
            else:
                await query.edit_message_text(
                    "❌ Errore nella creazione del ticket. Riprova.",
                    parse_mode=constants.ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Errore creazione ticket: {e}")
            await query.edit_message_text(
                "❌ Errore nella creazione del ticket. Riprova.",
                parse_mode=constants.ParseMode.HTML
            )
        
        # Pulisci i dati utente
        context.user_data.pop("ticket_priorita", None)
        context.user_data.pop("ticket_descrizione", None)
        context.user_data.pop("ticket_lista", None)
        
        return ConversationHandler.END
    
    elif data.startswith(f"{CB_TICKET}view_"):
        ticket_id = data.replace(f"{CB_TICKET}view_", "")
        ticket = ticket_system.get_ticket(ticket_id)
        
        if not ticket:
            await query.edit_message_text("❌ Ticket non trovato.")
            return
        
        text = f"🎫 <b>Ticket #{ticket.get('id')[:8]}</b>\n\n"
        text += f"📝 <b>Titolo:</b> {ticket.get('titolo')}\n"
        text += f"📊 <b>Stato:</b> {ticket.get('stato')}\n"
        text += f"⚡ <b>Priorità:</b> {ticket.get('priorita')}\n"
        text += f"\n📝 <b>Descrizione:</b>\n{ticket.get('descrizione')}"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Torna ai tuoi ticket", callback_data=f"{CB_TICKET}my")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )


# ==================== CONVERSATION HANDLER PER TICKET ====================

async def ticket_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point per la creazione ticket - mostra la selezione priorità."""
    keyboard = [
        [
            InlineKeyboardButton("🔴 Alta", callback_data=f"{CB_TICKET}priorita_alta"),
            InlineKeyboardButton("🟡 Media", callback_data=f"{CB_TICKET}priorita_media"),
            InlineKeyboardButton("🟢 Bassa", callback_data=f"{CB_TICKET}priorita_bassa")
        ],
        [
            InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎫 <b>Creazione Ticket</b>\n\n"
        "Seleziona la priorità del ticket:\n\n"
        "🔴 Alta: Problemi gravi, servizio non funzionante\n"
        "🟡 Media: Problemi minori, rallentamenti\n"
        "🟢 Bassa: Domande, informazioni",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )
    return SELECT_PRIORITY


async def ticket_receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve la descrizione del problema e chiede il nome lista."""
    user_id = str(update.effective_user.id)
    descrizione = update.message.text
    
    # Salva la descrizione
    context.user_data["ticket_descrizione"] = descrizione
    
    # Controlla se l'utente ha una lista associata
    lista = user_management.get_lista_utente(user_id)
    
    if lista:
        # L'utente ha una lista - chiedi se vuole usarla o inserirne un'altra
        lista_nome = lista.get("nome", "la tua lista")
        
        keyboard = [
            [
                InlineKeyboardButton(f"📺 Usa la tua lista: {lista_nome}", 
                                    callback_data=f"{CB_TICKET_USE_LIST}{lista_nome}")
            ],
            [
                InlineKeyboardButton("📝 Inserisci un'altra lista", 
                                    callback_data=f"{CB_TICKET_OTHER_LIST}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📺 <b>Lista IPTV</b>\n\n"
            f"Hai una lista associata: <b>{lista_nome}</b>\n\n"
            "Vuoi usare questa lista per il ticket o inserirne un'altra?",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    else:
        # L'utente non ha una lista - chiedi direttamente il nome
        await update.message.reply_text(
            "📺 <b>Inserisci nome lista IPTV</b>\n\n"
            "Non hai una lista IPTV associata. "
            "Inserisci il nome della lista IPTV per cui hai bisogno di supporto:",
            parse_mode=constants.ParseMode.HTML
        )
    
    return ENTER_LIST_NAME


async def ticket_receive_list_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve il nome della lista IPTV e mostra la conferma."""
    lista_nome = update.message.text
    context.user_data["ticket_lista"] = lista_nome
    
    priorita = context.user_data.get("ticket_priorita", "media")
    descrizione = context.user_data.get("ticket_descrizione", "")
    
    text = (f"🎫 <b>Conferma Ticket</b>\n\n"
            f"⚡ <b>Priorità:</b> {priorita.upper()}\n"
            f"📺 <b>Lista IPTV:</b> {lista_nome}\n\n"
            f"📝 <b>Descrizione:</b>\n{descrizione}")
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Conferma", callback_data=f"{CB_TICKET}conferma"),
            InlineKeyboardButton("❌ Annulla", callback_data=f"{CB_TICKET}annulla")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )
    return CONFIRM


async def ticket_confirm_and_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conferma e crea il ticket."""
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    priorita = context.user_data.get("ticket_priorita", "media")
    descrizione = context.user_data.get("ticket_descrizione", "")
    lista = context.user_data.get("ticket_lista", "Non specificata")
    
    # Crea il ticket
    try:
        ticket = ticket_system.crea_ticket(
            user_id=user_id,
            problema=f"[{lista}] {descrizione}",
            categoria=priorita
        )
        
        if ticket:
            # Notifica agli admin
            await notifica_admin_ticket(ticket)
            
            await query.edit_message_text(
                f"✅ <b>Ticket creato con successo!</b>\n\n"
                f"🎫 <b>Ticket #{ticket.get('id', '')[:8]}</b>\n"
                f"📊 Stato: {ticket.get('stato', 'Aperto')}\n"
                f"⚡ Priorità: {priorita.upper()}\n\n"
                "Un admin ti risponderà al più presto.",
                parse_mode=constants.ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                "❌ Errore nella creazione del ticket. Riprova.",
                parse_mode=constants.ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"Errore creazione ticket: {e}")
        await query.edit_message_text(
            "❌ Errore nella creazione del ticket. Riprova.",
            parse_mode=constants.ParseMode.HTML
        )
    
    # Pulisci i dati utente
    context.user_data.pop("ticket_priorita", None)
    context.user_data.pop("ticket_descrizione", None)
    context.user_data.pop("ticket_lista", None)
    
    return ConversationHandler.END


async def admin_lista_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inizia la creazione di una nuova lista."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📺 <b>Nuova Lista IPTV</b>\n\n"
        "Inserisci il <b>nome</b> della lista:\n\n"
        "Esempio: «Lista Gold», «Lista Premium», ecc.",
        parse_mode=constants.ParseMode.HTML
    )
    return ADMIN_LIST_NAME


async def admin_lista_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve il nome della lista."""
    nome = update.message.text
    context.user_data["nuova_lista_nome"] = nome
    
    await update.message.reply_text(
        f"✅ Nome impostato: <b>{nome}</b>\n\n"
        "Inserisci il <b>costo</b> mensile della lista:\n\n"
        "Esempio: «5€» o «10€» al mese",
        parse_mode=constants.ParseMode.HTML
    )
    return ADMIN_LIST_COST


async def admin_lista_receive_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve il costo della lista."""
    costo = update.message.text
    context.user_data["nuova_lista_costo"] = costo
    
    await update.message.reply_text(
        f"✅ Costo impostato: <b>{costo}</b>\n\n"
        "Inserisci la <b>data di scadenza</b> della lista:\n\n"
        "Esempio: «31/12/2026» o «1 anno»",
        parse_mode=constants.ParseMode.HTML
    )
    return ADMIN_LIST_SCADENZA


async def admin_lista_receive_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve la scadenza della lista."""
    scadenza = update.message.text
    context.user_data["nuova_lista_scadenza"] = scadenza
    
    keyboard = [
        [InlineKeyboardButton("⏭️ Salta", callback_data="lista_skip_note")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Scadenza impostata: <b>{scadenza}</b>\n\n"
        "Inserisci eventuali <b>note</b> per la lista:\n\n"
        "Esempio: «Include canali sport»\n"
        "Oppure clicca «Salta» per continuare:",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )
    return ADMIN_LIST_NOTE


async def admin_lista_receive_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve le note e crea la lista."""
    from datetime import datetime
    
    note = update.message.text if update.message else ""
    
    nome = context.user_data.get("nuova_lista_nome", "")
    costo = context.user_data.get("nuova_lista_costo", "")
    scadenza = context.user_data.get("nuova_lista_scadenza", "")
    
    durata_giorni = 30
    try:
        scadenza_val = scadenza.lower().strip()
        if "anno" in scadenza_val:
            durata_giorni = 365
        elif "mese" in scadenza_val:
            durata_giorni = 30
        elif "/" in scadenza_val:
            parts = scadenza_val.split("/")
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                input_date = datetime(year if year > 100 else 2000 + year, month, day)
                delta = input_date - datetime.now()
                if delta.days > 0:
                    durata_giorni = delta.days
    except:
        durata_giorni = 30
    
    user_management.aggiungi_lista(nome, "", "m3u8", durata_giorni)
    
    if update.message:
        await update.message.reply_text(
            f"✅ <b>Lista creata con successo!</b>\n\n"
            f"📺 <b>{nome}</b>\n"
            f"💰 {costo}\n"
            f"📅 {scadenza}\n"
            f"📝 {note}",
            parse_mode=constants.ParseMode.HTML
        )
    
    context.user_data.pop("nuova_lista_nome", None)
    context.user_data.pop("nuova_lista_costo", None)
    context.user_data.pop("nuova_lista_scadenza", None)
    
    return ConversationHandler.END


async def ticket_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla la creazione del ticket."""
    # Prova a rispondere tramite message (se chiamato da /ticket)
    if update.message:
        await update.message.reply_text(
            "❌ Creazione ticket annullata.",
            parse_mode=constants.ParseMode.HTML
        )
    # Prova a rispondere tramite callback query (se chiamato da menu)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Creazione ticket annullata.",
            parse_mode=constants.ParseMode.HTML
        )
    
    # Pulisci i dati utente
    context.user_data.pop("ticket_priorita", None)
    context.user_data.pop("ticket_descrizione", None)
    context.user_data.pop("ticket_lista", None)
    
    return ConversationHandler.END


# Crea il ConversationHandler per i ticket
ticket_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("ticket", ticket_entry_point)],
    states={
        SELECT_PRIORITY: [
            CallbackQueryHandler(handle_callback_ticket, pattern=f"^{CB_TICKET}priorita_")
        ],
        ENTER_DESCRIPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_receive_description)
        ],
        ENTER_LIST_NAME: [
            CallbackQueryHandler(handle_callback_ticket, pattern=f"^{CB_TICKET_USE_LIST}"),
            CallbackQueryHandler(handle_callback_ticket, pattern=f"^{CB_TICKET_OTHER_LIST}"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_receive_list_name)
        ],
        CONFIRM: [
            CallbackQueryHandler(ticket_confirm_and_create, pattern=f"^{CB_TICKET}conferma"),
            CallbackQueryHandler(ticket_cancel, pattern=f"^{CB_TICKET}annulla")
        ]
    },
    fallbacks=[
        CommandHandler("cancel", ticket_cancel)
    ],
    name="ticket_conversation",
    persistent=False
)


# ConversationHandler per /richiedi
richiedi_handler = ConversationHandler(
    entry_points=[CommandHandler("richiedi", cmd_richiedi)],
    states={
        RICHIEDI_CHOICE: [
            CallbackQueryHandler(richiedi_choice_receive, pattern="^rich_")
        ],
        RICHIEDI_NOME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, richiedi_nome_receive)
        ]
    },
    fallbacks=[CommandHandler("cancel", ticket_cancel)],
    name="richiedi_conversation",
    persistent=False
)


# ConversationHandler per creazione lista admin
admin_lista_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_lista_start, pattern=f"^{CB_ADMIN}lista_nuova$")],
    states={
        ADMIN_LIST_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lista_receive_name)
        ],
        ADMIN_LIST_COST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lista_receive_cost)
        ],
        ADMIN_LIST_SCADENZA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lista_receive_scadenza)
        ],
        ADMIN_LIST_NOTE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lista_receive_note)
        ]
    },
    fallbacks=[CommandHandler("cancel", ticket_cancel)],
    name="admin_lista_conversation",
    persistent=False
)


async def handle_callback_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce callback admin."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ Non autorizzato", show_alert=True)
        return
    
    # Gestisci vari callback admin
    if data == f"{CB_ADMIN}menu":
        # Mostra menu admin
        keyboard = [
            [
                InlineKeyboardButton("📋 Gestione Richieste", callback_data=f"{CB_ADMIN}richieste"),
                InlineKeyboardButton("🎫 Gestione Ticket", callback_data=f"{CB_ADMIN}ticket")
            ],
            [
                InlineKeyboardButton("💾 Gestione Backup", callback_data=f"{CB_ADMIN}backup"),
                InlineKeyboardButton("📊 Statistiche", callback_data=f"{CB_ADMIN}stats")
            ],
            [
                InlineKeyboardButton("🔧 Manutenzione", callback_data=f"{CB_ADMIN}manutenzione"),
                InlineKeyboardButton("📡 Stato Servizio", callback_data=f"{CB_ADMIN}stato_servizio")
            ],
            [
                InlineKeyboardButton("📺 Gestione Liste", callback_data=f"{CB_ADMIN}liste")
            ],
            [
                InlineKeyboardButton("🏠 Menu Principale", callback_data=f"{CB_MENU}main")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚙️ <b>Menu Admin</b>",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data == f"{CB_ADMIN}liste":
        # Gestione Liste IPTV
        try:
            liste = user_management.get_tutte_liste()
            
            text = "📺 <b>Gestione Liste IPTV</b>\n\n"
            
            if liste and len(liste) > 0:
                for lista in liste:
                    text += f"• <b>{lista.get('nome')}</b> - {lista.get('stato', 'inattiva')}\n"
                    text += f"  💰 {lista.get('costo', 'N/A')} - 📅 {lista.get('data_scadenza', 'N/A')}\n"
            else:
                text += "Nessuna lista configurata."
            
            keyboard = [
                [InlineKeyboardButton("➕ Aggiungi Lista", callback_data=f"{CB_ADMIN}lista_nuova")],
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)
        except Exception as e:
            logger.error(f"Errore gestione liste: {e}")
            await query.answer(f"Errore: {e}", show_alert=True)
    
    elif data == f"{CB_ADMIN}stato_servizio":
        # Menu Stato Servizio
        current_stato = stato_servizio.get_stato()
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Operativo", callback_data=f"{CB_ADMIN}stato_op"),
                InlineKeyboardButton("🟡 Problemi", callback_data=f"{CB_ADMIN}stato_prob")
            ],
            [
                InlineKeyboardButton("🔴 Disservizio", callback_data=f"{CB_ADMIN}stato_dis"),
                InlineKeyboardButton("🔧 Manutenzione", callback_data=f"{CB_ADMIN}stato_mnt")
            ],
            [
                InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📡 <b>Stato Servizio</b>\n\nStato attuale: <b>{current_stato}</b>\n\nSeleziona il nuovo stato:",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data == f"{CB_ADMIN}manutenzione":
        # Menu Manutenzione
        is_active = manutenzione.is_manutenzione_attiva()
        
        if is_active:
            keyboard = [
                [
                    InlineKeyboardButton("🔴 Disattiva Manutenzione", callback_data=f"{CB_ADMIN}manutenzione_disattiva")
                ],
                [
                    InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")
                ]
            ]
            msg = "🔧 <b>Manutenzione</b>\n\n⚠️ La manutenzione è <b>ATTIVA</b>\n\nGli utenti normali non possono usare il bot."
        else:
            keyboard = [
                [
                    InlineKeyboardButton("🔧 Attiva Manutenzione", callback_data=f"{CB_ADMIN}manutenzione_attiva")
                ],
                [
                    InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")
                ]
            ]
            msg = "🔧 <b>Manutenzione</b>\n\n✅ La manutenzione è <b>INATTIVA</b>\n\nIl bot funziona normalmente."
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            msg,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data == f"{CB_ADMIN}manutenzione_disattiva":
        # Disattiva manutenzione
        manutenzione.disattiva_manutenzione(str(user_id))
        await query.answer("✅ Manutenzione disattivata!", show_alert=True)
        
        keyboard = [
            [
                InlineKeyboardButton("🔧 Attiva Manutenzione", callback_data=f"{CB_ADMIN}manutenzione_attiva")
            ],
            [
                InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔧 <b>Manutenzione</b>\n\n✅ La manutenzione è stata <b>DISATTIVATA</b>",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data == f"{CB_ADMIN}ticket":
        # Menu Gestione Ticket
        ticket_aperti = ticket_system.get_tutti_ticket(stato="aperto")
        
        text = "🎫 <b>Gestione Ticket</b>\n\n"
        
        if ticket_aperti:
            text += f"📊 Ticket aperti: {len(ticket_aperti)}\n\n"
            for ticket in ticket_aperti[:5]:
                prio_emoji = "🔴" if ticket.get("priorita") == "alta" else "🟡"
                text += f"{prio_emoji} #{ticket.get('id', '')[:8]} - {ticket.get('titolo', 'Senza titolo')[:30]}\n"
        else:
            text += "📭 Nessun ticket aperto."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"{CB_ADMIN}ticket_refresh")],
            [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data == f"{CB_ADMIN}ticket_refresh":
        # Refresh ticket - same as ticket menu
        try:
            ticket_aperti = ticket_system.get_tutti_ticket(stato="aperto")
            
            text = "🎫 <b>Gestione Ticket</b>\n\n"
            
            if ticket_aperti:
                text += f"📊 Ticket aperti: {len(ticket_aperti)}\n\n"
                for ticket in ticket_aperti[:5]:
                    prio_emoji = "🔴" if ticket.get("priorita") == "alta" else "🟡"
                    text += f"{prio_emoji} #{ticket.get('id', '')[:8]} - {ticket.get('titolo', 'Senza titolo')[:30]}\n"
            else:
                text += "📭 Nessun ticket aperto."
            
            keyboard = [
                [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"{CB_ADMIN}ticket_refresh")],
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Errore ticket_refresh: {e}")
            keyboard = [
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❌ Errore nel recupero ticket: {e}",
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
    
    elif data == f"{CB_ADMIN}richieste":
        # Mostra richieste
        richieste = user_management.get_richieste_in_attesa()
        
        if not richieste:
            keyboard = [
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 Nessuna richiesta in attesa.", reply_markup=reply_markup)
            return
        
        text = "📋 <b>Richieste in attesa:</b>\n\n"
        
        for richiesta in richieste[:5]:
            text += f"🆔 {richiesta.get('user_id')}\n"
            text += f"📅 {richiesta.get('data_richiesta')}\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("✅", callback_data=f"{CB_ADMIN}approva_{richiesta.get('id')}"),
                    InlineKeyboardButton("❌", callback_data=f"{CB_ADMIN}rifiuta_{richiesta.get('id')}")
                ]
            ]
            
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.HTML)
            text = "----\n"
    
    elif data.startswith(f"{CB_ADMIN}approva_"):
        richiesta_id = data.replace(f"{CB_ADMIN}approva_", "")
        # Approva richiesta
        user_management.approva_richiesta(richiesta_id, str(user_id))
        
        await query.answer("✅ Richiesta approvata!", show_alert=True)
        await query.edit_message_text(f"✅ Richiesta {richiesta_id[:8]} approvata.")
    
    elif data.startswith(f"{CB_ADMIN}rifiuta_"):
        richiesta_id = data.replace(f"{CB_ADMIN}rifiuta_", "")
        # Rifiuta richiesta
        user_management.rifiuta_richiesta(richiesta_id, str(user_id), "Rifiutato dall'admin")
        
        await query.answer("❌ Richiesta rifiutata.", show_alert=True)
        await query.edit_message_text(f"❌ Richiesta {richiesta_id[:8]} rifiutata.")
    
    elif data == f"{CB_ADMIN}backup_create":
        # Crea backup
        try:
            backup_path = backup_system.crea_backup()
            
            keyboard = [
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ <b>Backup creato!</b>\n\n"
                f"📁 File: {backup_path}",
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            keyboard = [
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"❌ Errore backup: {e}", reply_markup=reply_markup)
    
    elif data == f"{CB_ADMIN}stats":
        # Mostra statistiche in modo ordinato
        try:
            stats_data = user_management.get_statistiche()
            
            stats_text = """📊 <b>Statistiche HelperBot</b>

📈 <b>Utenti:</b>
• Totali: {totale_utenti}
• Attivi: {utenti_attivi}
• Con lista: {utenti_con_lista}

📺 <b>Liste IPTV:</b>
• Totali: {totale_liste}
• Attive: {liste_attive}

📋 <b>Richieste:</b>
• Totali: {totale_richieste}
• In attesa: {richieste_pendenti}
• Approvate: {richieste_approvate}
• Rifiutate: {richieste_rifiutate}""".format(**stats_data)
            
            # Evita errore "Message is not modified"
            current_msg = query.message.text if query.message else ""
            if current_msg.strip() == stats_text.strip():
                await query.answer("Statistiche già aggiornate!", show_alert=False)
                return
            
            keyboard = [
                [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"{CB_ADMIN}stats")],
                [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                stats_text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("Statistiche già aggiornate!", show_alert=False)
            else:
                logger.error(f"Errore stats: {e}")
                keyboard = [
                    [InlineKeyboardButton("🔙 Indietro", callback_data=f"{CB_ADMIN}menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Errore nel recupero statistiche: {e}",
                    reply_markup=reply_markup,
                    parse_mode=constants.ParseMode.HTML
                )
    
    elif data == f"{CB_ADMIN}manutenzione_attiva":
        # Attiva manutenzione
        manutenzione.attiva_manutenzione(str(user_id), "Manutenzione programmata")
        await query.edit_message_text(
            "🔧 <b>Manutenzione attivata</b>\n\nGli utenti normali sono bloccati.",
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_ADMIN}stato_"):
        stato = data.replace(f"{CB_ADMIN}stato_", "")
        stato_mapping = {
            "op": STATO_OPERATIVO,
            "prob": STATO_PROBLEMI,
            "dis": "DISSERVIZIO",
            "mnt": "MANUTENZIONE"
        }
        
        if stato in stato_mapping:
            stato_servizio.aggiorna_stato(stato_mapping[stato], f"Admin {user_id}")
            await query.edit_message_text(
                f"✅ Stato aggiornato a: <b>{stato_mapping[stato]}</b>",
                parse_mode=constants.ParseMode.HTML
            )
    
    elif data == f"{CB_ADMIN}lista_nuova":
        return


async def handle_callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce callback menu."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(update.effective_user.id)
    
    if data == f"{CB_MENU}main":
        # Torna al menu principale
        await mostra_menu_principale(update, context, query=query)
        
    elif data == f"{CB_MENU}stato":
        # Mostra stato utente
        utente = user_management.get_utente(user_id)
        lista_id = utente.get("lista_approvata") if utente else None
        
        if lista_id:
            lista = user_management.get_lista(lista_id)
            if lista:
                text = f"📺 <b>La tua lista IPTV</b>\n\n"
                text += f"🔗 URL: <code>{lista.get('url', 'N/A')}</code>\n"
                text += f"📊 Stato: {lista.get('stato', 'N/A')}\n"
                text += f"📅 Scadenza: {lista.get('data_scadenza', 'N/A')}"
            else:
                text = "📭 Non hai una lista IPTV attiva.\nUsa /richiedi per richiederne una."
        else:
            text = "📭 Non hai una lista IPTV attiva.\nUsa /richiedi per richiederne una."
        
        # Aggiungi pulsante per tornare al menu
        keyboard = [
            [InlineKeyboardButton("🏠 Menu Principale", callback_data=f"{CB_MENU}main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.HTML)


# ==================== FUNZIONI HELPER ====================

async def notifica_admin_richiesta(richiesta: Dict):
    """Invia notifica agli admin per nuova richiesta."""
    if not ADMIN_IDS:
        return
    
    text = f"🔔 <b>Nuova richiesta lista IPTV!</b>\n\n"
    text += f"🆔 Utente: {richiesta.get('user_id')}\n"
    text += f"👤 Username: @{richiesta.get('username', 'N/A')}\n"
    text += f"📺 Lista: {richiesta.get('nome_lista', 'N/A')}\n"
    text += f"📅 Data: {richiesta.get('data_richiesta')}"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Approva", callback_data=f"{CB_ADMIN}approva_{richiesta.get('id')}"),
            InlineKeyboardButton("❌ Rifiuta", callback_data=f"{CB_ADMIN}rifiuta_{richiesta.get('id')}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Errore invio notifica admin {admin_id}: {e}")


async def notifica_admin_ticket(ticket: Dict):
    """Invia notifica agli admin per nuovo ticket."""
    if not ADMIN_IDS:
        return
    
    prio_emoji = "🔴" if ticket.get("priorita") == PrioritaTicket.ALTA.value else "🟡"
    
    text = f"🎫 <b>Nuovo ticket!</b> {prio_emoji}\n\n"
    text += f"🆔 ID: {ticket.get('id')[:8]}\n"
    text += f"👤 Utente: {ticket.get('user_id')}\n"
    text += f"📝 Titolo: {ticket.get('titolo')}\n"
    text += f"⚡ Priorità: {ticket.get('priorita')}"
    
    keyboard = [
        [InlineKeyboardButton("🎫 Gestisci", callback_data=f"{CB_ADMIN}ticket")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Errore invio notifica admin {admin_id}: {e}")


# ==================== HEALTH CHECK & JOBS ====================

async def health_check(context: ContextTypes.DEFAULT_TYPE):
    """
    Job periodico per verificare lo stato del bot.
    Esegue un health check completo e tenta di recuperare se ci sono problemi.
    """
    global LAST_HEALTH_CHECK, BOT_RUNNING
    
    logger.info("🔍 Eseguo health check...")
    
    try:
        bot = context.bot
        
        # 1. Verifica connessione con Telegram
        try:
            me = await bot.get_me()
            logger.info(f"✅ Health check: Bot @{me.username} ({me.id}) è attivo")
        except Exception as e:
            logger.error(f"❌ Health check fallito: impossibile contattare Telegram API: {e}")
            BOT_RUNNING = False
            await try_recovery(context, "telegram_api")
            return
        
        # 2. Verifica webhook
        try:
            webhook_info = await bot.get_webhook_info()
            if webhook_info.pending_update_count > 100:
                logger.warning(f"⚠️ Health check: {webhook_info.pending_update_count} pending updates")
            
            # Verifica se il webhook è configurato correttamente
            webhook_url = os.environ.get("WEBHOOK_URL", "")
            if webhook_info.url != webhook_url:
                logger.warning(f"⚠️ Health check: webhook URL non corrisponde! "
                             f"Atteso: {webhook_url}, Attuale: {webhook_info.url}")
                # Riconfigura il webhook
                await setup_webhook(context.application)
        except Exception as e:
            logger.error(f"❌ Health check: errore webhook: {e}")
        
        # 3. Verifica moduli
        try:
            if persistence:
                persistence.save_data()
                logger.info("✅ Health check: persistenza OK")
        except Exception as e:
            logger.error(f"❌ Health check: errore persistenza: {e}")
        
        # 4. Verifica rate limiter
        try:
            if rate_limiter:
                rate_limiter.cleanup_old_entries()
                logger.info("✅ Health check: rate limiter OK")
        except Exception as e:
            logger.error(f"❌ Health check: errore rate limiter: {e}")
        
        # Aggiorna timestamp ultimo health check
        LAST_HEALTH_CHECK = datetime.now()
        BOT_RUNNING = True
        
        logger.info(f"✅ Health check completato alle {LAST_HEALTH_CHECK}")
        
    except Exception as e:
        logger.error(f"❌ Health check: errore generico: {e}")
        BOT_RUNNING = False
        await try_recovery(context, "health_check")


async def try_recovery(context: ContextTypes.DEFAULT_TYPE, error_type: str):
    """
    Tenta di recuperare il bot dopo un errore.
    
    Args:
        context: ContextTypes.DEFAULT_TYPE
        error_type: Tipo di errore rilevato
    """
    logger.warning(f"🔧 Tentativo di recovery per: {error_type}")
    
    try:
        bot = context.bot
        
        if error_type == "telegram_api":
            # Riavvia il webhook
            logger.info("🔧 Recovery: riconfigurazione webhook...")
            await setup_webhook(context.application)
            
        elif error_type == "health_check":
            # Prova a verificare il bot
            logger.info("🔧 Recovery: verifica bot...")
            try:
                me = await bot.get_me()
                logger.info(f"✅ Recovery: Bot {me.username} risponde")
            except:
                logger.error("❌ Recovery: bot non risponde")
                
        # Notifica admin
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ <b>Health Check Alert</b>\n\n"
                         f"Errore rilevato: {error_type}\n"
                         f"Tentativo di recovery eseguito.",
                    parse_mode=constants.ParseMode.HTML
                )
            except:
                pass
                
    except Exception as e:
        logger.error(f"❌ Recovery fallito: {e}")


async def job_cleanup_sessions(context: ContextTypes.DEFAULT_TYPE):
    """Job per cleanup periodico delle sessioni e dati vecchi."""
    logger.info("🧹 Eseguo cleanup sessioni...")
    
    try:
        # Cleanup rate limiter
        if rate_limiter:
            rate_limiter.cleanup_old_entries()
            logger.info("✅ Rate limiter cleanup completato")
        
        # Salva dati periodicamente
        if persistence:
            persistence.save_data()
            logger.info("✅ Dati salvati durante cleanup")
        
        logger.info("✅ Cleanup sessioni completato")
    except Exception as e:
        logger.error(f"❌ Errore cleanup sessioni: {e}")


async def job_backup(context: ContextTypes.DEFAULT_TYPE):
    """Job per backup automatico ogni 24h."""
    logger.info("Esecuzione backup automatico...")
    try:
        backup_path = backup_system.crea_backup()
        logger.info(f"Backup automatico completato: {backup_path}")
        
        # Notifica admin
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"✅ <b>Backup automatico completato!</b>\n\n📁 File: {backup_path}",
                    parse_mode=constants.ParseMode.HTML
                )
            except:
                pass
    except Exception as e:
        logger.error(f"Backup automatico fallito: {e}")


async def job_check_scadenze(context: ContextTypes.DEFAULT_TYPE):
    """Job per controllo scadenze liste IPTV."""
    logger.info("Controllo scadenze liste IPTV...")
    
    try:
        liste_scadute = user_management.get_liste_scadute()
        
        for lista in liste_scadute:
            user_id = lista.get("user_id")
            # Notifica utente
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text="⚠️ <b>La tua lista IPTV è scaduta!</b>\n\n"
                         "Contatta un admin per rinnovare.",
                    parse_mode=constants.ParseMode.HTML
                )
            except:
                pass
        
        logger.info(f"Trovate {len(liste_scadute)} liste scadute")
    except Exception as e:
        logger.error(f"Errore controllo scadenze: {e}")


async def job_check_ticket(context: ContextTypes.DEFAULT_TYPE):
    """Job per controllo ticket senza risposta."""
    logger.info("Controllo ticket senza risposta...")
    
    try:
        ticket_aperti = ticket_system.get_tutti_ticket(stato=StatoTicket.APERTO)
        
        for ticket in ticket_aperti:
            # Calcola tempo dall'ultimo aggiornamento
            # Se superiore a X ore, notifica admin
            pass
        
        logger.info(f"Controllati {len(ticket_aperti)} ticket")
    except Exception as e:
        logger.error(f"Errore controllo ticket: {e}")


async def job_pulizia_dati(context: ContextTypes.DEFAULT_TYPE):
    """Job per pulizia dati vecchi."""
    logger.info("Esecuzione pulizia dati vecchi...")
    
    try:
        # Pulisci dati vecchi (es. log, cache, etc.)
        logger.info("Pulizia dati completata")
    except Exception as e:
        logger.error(f"Errore pulizia dati: {e}")


# ==================== MAIN ====================

def setup_handlers(application: Application):
    """Configura tutti gli handler del bot."""
    
    # ConversationHandler per ticket (deve essere aggiunto prima dei CommandHandler)
    application.add_handler(ticket_conversation_handler)
    
    # ConversationHandler per richiedi
    application.add_handler(richiedi_handler)
    
    # ConversationHandler per creazione lista admin
    application.add_handler(admin_lista_handler)
    
    # Comandi utente
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("faq", cmd_faq))
    application.add_handler(CommandHandler("miei_ticket", cmd_miei_ticket))
    application.add_handler(CommandHandler("stato", cmd_stato))
    application.add_handler(CommandHandler("ping", cmd_ping))
    # Nota: /richiedi è gestito da richiedi_handler
    application.add_handler(CommandHandler("lista", cmd_lista))
    
    # Comandi admin
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("richieste", cmd_richieste))
    application.add_handler(CommandHandler("ticket_admin", cmd_ticket_admin))
    application.add_handler(CommandHandler("backup", cmd_backup))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("manutenzione", cmd_manutenzione))
    application.add_handler(CommandHandler("stato_servizio", cmd_stato_servizio))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_faq, pattern=f"^{CB_FAQ}"))
    application.add_handler(CallbackQueryHandler(handle_callback_onboarding, pattern=f"^{CB_ONBOARDING}"))
    application.add_handler(CallbackQueryHandler(handle_callback_ticket, pattern=f"^{CB_TICKET}"))
    application.add_handler(CallbackQueryHandler(handle_callback_admin, pattern=f"^{CB_ADMIN}"))
    application.add_handler(CallbackQueryHandler(handle_callback_menu, pattern=f"^{CB_MENU}"))
    
    # Error handler
    application.add_error_handler(error_handler)


def setup_jobs(job_queue: JobQueue):
    """Configura i job periodici."""
    
    # Health check ogni 5 minuti (300 secondi)
    job_queue.run_repeating(
        health_check,
        interval=HEALTH_CHECK_INTERVAL,
        first=60  # Prima esecuzione dopo 1 minuto
    )
    
    # Cleanup sessioni ogni 15 minuti
    job_queue.run_repeating(
        job_cleanup_sessions,
        interval=900,  # 15 minuti
        first=300  # Prima esecuzione dopo 5 minuti
    )
    
    # Backup ogni 24 ore
    job_queue.run_repeating(
        job_backup,
        interval=86400,  # 24 ore in secondi
        first=3600  # Prima esecuzione dopo 1 ora
    )
    
    # Controllo scadenze ogni 6 ore
    job_queue.run_repeating(
        job_check_scadenze,
        interval=21600,  # 6 ore
        first=300  # Prima esecuzione dopo 5 minuti
    )
    
    # Controllo ticket ogni ora
    job_queue.run_repeating(
        job_check_ticket,
        interval=3600,  # 1 ora
        first=600  # Prima esecuzione dopo 10 minuti
    )
    
    # Pulizia dati ogni giorno
    job_queue.run_repeating(
        job_pulizia_dati,
        interval=86400,  # 24 ore
        first=7200  # Prima esecuzione dopo 2 ore
    )


async def post_init(application: Application):
    """Called after initialization."""
    logger.info("=== POST_INIT STARTED ===")
    logger.info(f"Application type: {type(application)}")
    logger.info(f"Application.bot: {application.bot}")
    logger.info("Bot inizializzato con successo!")
    
    # Passa l'application al server per il webhook
    logger.info("Calling set_bot_application...")
    set_bot_application(application)
    
    # NON cancellare il webhook - usa la versione configurata
    # Il webhook è già impostato in setup_webhook()
    logger.info("Post-init completato, il bot userà webhook")


async def post_shutdown(application: Application):
    """Called after shutdown."""
    logger.info("Bot in shutdown...")
    
    # Salva dati
    if persistence:
        persistence.save_data()
        logger.info("Dati salvati")


def run_bot():
    """
    Funzione principale di avvio del bot.
    Usa direttamente app.run() che gestisce automaticamente
    l'intero ciclo di vita dell'event loop.
    """
    global persistence, user_management, ticket_system, rate_limiter
    global faq_system, backup_system, onboarding, stato_servizio
    global manutenzione, notifications, statistiche, app
    
    print("=" * 50)
    print("🚀 HelperBot - Avvio in corso...")
    print("=" * 50)
    
    # Verifica token
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN non configurato!")
        print("\n⚠️ Per favore configura le variabili d'ambiente:")
        print("   - TELEGRAM_BOT_TOKEN: Il token del tuo bot Telegram")
        print("   - ADMIN_IDS: ID Telegram degli admin separati da virgola")
        print("   - PORT: Porta per il server HTTP (default: 8080, standard Render)")
        sys.exit(1)
    
    # Inizializza persistenza
    print("📦 Inizializzazione persistenza dati...")
    persistence = DataPersistence()
    
    # Inizializza moduli
    print("📱 Inizializzazione moduli...")
    user_management = UserManagement(persistence)
    ticket_system = TicketSystem(persistence)
    rate_limiter = RateLimiter(persistence)
    faq_system = FaqSystem(persistence)
    backup_system = BackupSystem()
    onboarding = OnboardingManager(persistence)
    stato_servizio = StatoServizio(persistence)
    manutenzione = Manutenzione(persistence)
    notifications = NotificationSystem(persistence)
    statistiche = StatisticheDashboard(persistence)
    
    # Configura admin nella manutenzione
    if ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            manutenzione.aggiungi_admin(str(admin_id))
        logger.info(f"Admin configurati: {ADMIN_IDS}")
    
    # Crea Application
    print("🤖 Configurazione bot Telegram...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Setup handler
    print("📡 Registrazione comandi...")
    setup_handlers(app)
    
    # Setup job queue
    print("⏰ Configurazione job scheduler...")
    setup_jobs(app.job_queue)
    
    # Avvio bot
    print("\n" + "=" * 50)
    print("✅ HelperBot avviato!")
    print("=" * 50)
    print(f"🤖 Bot token: {BOT_TOKEN[:10]}...")
    print(f"👮 Admin IDs: {ADMIN_IDS}")
    print(f"🌐 Webhook URL: {os.environ.get('WEBHOOK_URL', 'NON CONFIGURATO')}")
    print("=" * 50)
    
    # =====================================================
    # AVVIO DEL BOT CON POLLING
    # Usa polling invece di webhook per evitare rate limiting
    # Il bot rimane in ascolto dei messaggi
    # =====================================================
    
    logger.info("=== STARTING BOT WITH POLLING ===")
    
    # NOTA: Quando si usa webhook mode, PTB crea il proprio server HTTP
    # Quindi NON serve il keepalive server separato
    # Il server di PTB già mantiene il servizio attivo
    #
    # Commentato per evitare conflitto di porta:
    # print("🌐 Avvio server keep-alive...")
    # try:
    #     from keepalive.server import start_server
    #     start_server(port=PORT, threaded=True)
    #     print(f"✅ Server keep-alive avviato sulla porta {PORT}")
    # except Exception as e:
    #     logger.warning(f"Errore avvio keep-alive server (non critico): {e}")
    #     print(f"⚠️ Keep-alive server: {e}")
    
    # Costruisci l'URL del webhook
    render_service_name = os.environ.get('RENDER_SERVICE_NAME', '')
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if not webhook_url and render_service_name:
        webhook_url = f"https://{render_service_name}.onrender.com/webhook"
    elif not webhook_url and not render_service_name:
        webhook_url = f"https://telegram-iptv-bot-ultra-pro.onrender.com/webhook"
        print("⚠️ RENDER_SERVICE_NAME non impostato, usando fallback")
    
    print(f"🌐 Webhook URL: {webhook_url}")
    
    # Configura il webhook prima di avviare il bot
    print("🔗 Configurazione webhook...")
    
    async def configure_webhook():
        await setup_webhook(app)
    
    # Crea un event loop temporaneo per configurare il webhook
    import asyncio
    try:
        asyncio.get_event_loop().run_until_complete(configure_webhook())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(configure_webhook())
    
    # Usa webhook mode per Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=webhook_url,  # URL HTTPS richiesto!
        allowed_updates=["message", "callback_query", "edited_message", "channel_post"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    run_bot()

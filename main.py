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
    
    Args:
        application: Application del bot Telegram
    """
    from telegram.error import TelegramError
    
    # Costruisci l'URL del webhook
    render_service_name = os.environ.get('RENDER_SERVICE_NAME', '')
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    # Se WEBHOOK_URL non è impostato, costruiscilo da RENDER_SERVICE_NAME
    if not webhook_url and render_service_name:
        webhook_url = f"https://{render_service_name}.onrender.com/webhook"
    elif not webhook_url and not render_service_name:
        # Né WEBHOOK_URL né RENDER_SERVICE_NAME sono impostati
        # Prova a ricostruirlo da una variabile o usa un fallback
        webhook_url = f"https://helperbot.onrender.com/webhook"
        logger.warning("⚠️ RENDER_SERVICE_NAME non è impostato! Usando fallback: helperbot.onrender.com")
        logger.warning("⚠️ Assicurati che il nome del servizio su Render corrisponda a helperbot!")
    
    # LOG DETTAGLIATO: Mostra quale URL viene utilizzato
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
    
    try:
        # Rimuovi qualsiasi webhook esistente prima di configurarne uno nuovo
        logger.info("Rimuovo webhook esistente...")
        await application.bot.delete_webhook()
        logger.info("Webhook esistente rimosso")
        
        # Configura il nuovo webhook
        logger.info(f"Configuro webhook verso: {webhook_url}")
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=webhook_secret if webhook_secret else None,
            allowed_updates=["message", "callback_query", "edited_message", "channel_post"]
        )
        
        logger.info("Webhook impostato, verifico...")
        
        # VERIFICA: Controlla che il webhook sia stato impostato correttamente
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"Webhook info - URL: {webhook_info.url}")
        logger.info(f"Webhook info - pending_updates: {webhook_info.pending_update_count}")
        
        if webhook_info.url == webhook_url:
            logger.info("✅ Webhook configurato correttamente! Telegram invierà gli update a questo URL.")
        else:
            logger.warning(f"⚠️ Webhook URL non corrisponde! Atteso: {webhook_url}, Attuale: {webhook_info.url}")
        
        logger.info("=== WEBHOOK CONFIGURATO CON SUCCESSO ===")
        
    except TelegramError as e:
        logger.error(f"Errore nella configurazione del webhook: {e}")
        raise


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


async def cmd_richiedi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /richiedi - Richiedi lista IPTV."""
    # Controlla manutenzione
    if await check_manutenzione(update, context):
        return
    
    # Verifica rate limit
    if await rate_limit_check(update, context):
        return
    
    user_id = str(update.effective_user.id)
    
    # Controlla se ha già una richiesta in pendenza
    richieste = user_management.get_richieste_by_user(user_id)
    richieste_attive = [r for r in richieste if r.get("stato") == "in_attesa"]
    
    if richieste_attive:
        await update.message.reply_text(
            "⏳ <b>Richiesta già in corso</b>\n\n"
            "Hai già una richiesta in attesa di approvazione.",
            parse_mode=constants.ParseMode.HTML
        )
        return
    
    # Crea nuova richiesta
    richiesta = user_management.crea_richiesta(
        user_id,
        update.effective_user.username or "",
        update.effective_user.full_name
    )
    
    if richiesta:
        await update.message.reply_text(
            "✅ <b>Richiesta inviata!</b>\n\n"
            "La tua richiesta è stata inoltrata agli admin. "
            "Riceverai una notifica quando sarà approvata.",
            parse_mode=constants.ParseMode.HTML
        )
        
        # Notifica admin
        await notifica_admin_richiesta(richiesta)
    else:
        await update.message.reply_text(
            "❌ <b>Errore</b>\n\n"
            "Non è stato possibile creare la richiesta. Riprova.",
            parse_mode=constants.ParseMode.HTML
        )


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
    ticket_list = ticket_system.get_ticket_aperti()
    
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
    
    if data == f"{CB_ONBOARDING}start":
        # Avvia onboarding
        username = update.effective_user.username or ""
        msg, keyboard = onboarding.genera_messaggio_step(1, username)
        if msg:
            # Evita errore "Message is not modified"
            current_msg = query.message.text if query.message else ""
            if current_msg != msg:
                await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
            else:
                await query.answer()
    
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
        username = update.effective_user.username or ""
        current_step = onboarding.get_step(user_id)
        
        if current_step < MAX_STEPS:
            msg, keyboard = onboarding.genera_messaggio_step(current_step + 1, username)
            if msg:
                # Evita errore "Message is not modified" controllando se il messaggio è cambiato
                current_msg = query.message.text if query.message else ""
                if current_msg != msg:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                else:
                    await query.answer()
        else:
            # Se siamo all'ultimo step, completa l'onboarding
            onboarding.completa_onboarding(user_id)
            await query.edit_message_text(
                "✅ <b>Onboarding completato!</b>\n\n"
                "Puoi sempre ripetere l'onboarding con /start",
                parse_mode=constants.ParseMode.HTML
            )
    
    elif data == f"{CB_ONBOARDING}prev":
        # Pulsante "Precedente"
        username = update.effective_user.username or ""
        current_step = onboarding.get_step(user_id)
        
        if current_step > 1:
            msg, keyboard = onboarding.genera_messaggio_step(current_step - 1, username)
            if msg:
                # Evita errore "Message is not modified"
                current_msg = query.message.text if query.message else ""
                if current_msg != msg:
                    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
                else:
                    await query.answer()
    
    elif data == f"{CB_ONBOARDING}skip":
        # Salta onboarding
        onboarding.completa_onboarding(user_id)
        # Evita errore "Message is not modified"
        current_msg = query.message.text if query.message else ""
        skip_msg = "✅ <b>Onboarding completato!</b>\n\nPuoi sempre ripetere l'onboarding con /start"
        if current_msg != skip_msg:
            await query.edit_message_text(
                skip_msg,
                parse_mode=constants.ParseMode.HTML
            )


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
                InlineKeyboardButton("📡 Stato Servizio", callback_data=f"{CB_ADMIN}stato")
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
    elif data == f"{CB_ADMIN}richieste":
        # Mostra richieste
        richieste = user_management.get_richieste_in_attesa()
        
        if not richieste:
            await query.edit_message_text("📭 Nessuna richiesta in attesa.")
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
        user_management.rifiuta_richiesta(richiesta_id, str(user_id))
        
        await query.answer("❌ Richiesta rifiutata.", show_alert=True)
        await query.edit_message_text(f"❌ Richiesta {richiesta_id[:8]} rifiutata.")
    
    elif data == f"{CB_ADMIN}backup_create":
        # Crea backup
        try:
            backup_path = backup_system.crea_backup()
            await query.edit_message_text(
                f"✅ <b>Backup creato!</b>\n\n"
                f"📁 File: {backup_path}",
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Errore backup: {e}")
    
    elif data == f"{CB_ADMIN}stats":
        # Mostra statistiche
        stats_text = statistiche.genera_report_completo()
        await query.edit_message_text(
            f"📊 <b>Statistiche</b>\n\n{stats_text}",
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


# ==================== JOB SCHEDULER ====================

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
        # Notifica eliminata - usa il metodo corretto se necessario


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
            
            # Notifica admin - rimossa per incompatibilità
        
        logger.info(f"Trovate {len(liste_scadute)} liste scadute")
    except Exception as e:
        logger.error(f"Errore controllo scadenze: {e}")


async def job_check_ticket(context: ContextTypes.DEFAULT_TYPE):
    """Job per controllo ticket senza risposta."""
    logger.info("Controllo ticket senza risposta...")
    
    try:
        ticket_aperti = ticket_system.get_ticket_aperti()
        
        for ticket in ticket_aperti:
            # Calcola tempo dall'ultimo aggiornamento
            # Se superiore a X ore, notifica admin
            # (implementazione semplificata)
            pass
        
        logger.info(f"Controllati {len(ticket_aperti)} ticket")
    except Exception as e:
        logger.error(f"Errore controllo ticket: {e}")


async def job_pulizia_dati(context: ContextTypes.DEFAULT_TYPE):
    """Job per pulizia dati vecchi."""
    logger.info("Esecuzione pulizia dati vecchi...")
    
    try:
        # Pulisci dati vecchi (es. log, cache, etc.)
        # Implementazione specifica a seconda delle esigenze
        logger.info("Pulizia dati completata")
    except Exception as e:
        logger.error(f"Errore pulizia dati: {e}")


# ==================== MAIN ====================

def setup_handlers(application: Application):
    """Configura tutti gli handler del bot."""
    
    # ConversationHandler per ticket (deve essere aggiunto prima dei CommandHandler)
    application.add_handler(ticket_conversation_handler)
    
    # Comandi utente
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("faq", cmd_faq))
    application.add_handler(CommandHandler("miei_ticket", cmd_miei_ticket))
    application.add_handler(CommandHandler("stato", cmd_stato))
    application.add_handler(CommandHandler("richiedi", cmd_richiedi))
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
    logger.info("Bot inizializzato con successo!")
    
    # Passa l'application al server per il webhook
    set_bot_application(application)
    
    # Configura il webhook con Telegram
    await setup_webhook(application)
    
    # NOTA: Il server keep-alive viene avviato in main() dopo questa funzione
    # per evitare che post_init blocchi l'esecuzione
    logger.info("=== POST_INIT COMPLETE: webhook configurato ===")


async def post_shutdown(application: Application):
    """Called after shutdown."""
    logger.info("Bot in shutdown...")
    
    # Salva dati
    if persistence:
        persistence.save_data()
        logger.info("Dati salvati")


def main():
    """Funzione principale di avvio del bot."""
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
    print(f"🌐 Webhook URL: {os.environ.get('WEBHOOK_URL', 'NON CONFIGURATO - Sara generato automaticamente da RENDER_SERVICE_NAME')}")
    print(f"🔧 Render Service Name: {os.environ.get('RENDER_SERVICE_NAME', 'NON SETTATO')}")
    print("=" * 50)
    
    # =====================================================
    # AVVIO SERVER KEEP-ALIVE PRIMA DEL LOOP INFINITO
    # =====================================================
    # Questo deve essere chiamato qui perché post_init non blocca
    # Il server deve partire PRIMA del loop infinito
    logger.info("=== STARTING KEEP-ALIVE SERVER IN main() ===")
    logger.info(f"=== PORT: {PORT}, HOST: {HOST} ===")
    
    try:
        # Usa threaded=False per eseguire nel main thread - più affidabile su Render.com
        result = start_keepalive(PORT, threaded=False)
        logger.info(f"=== start_keepalive result: {result} ===")
    except Exception as e:
        logger.error(f"=== EXCEPTION in start_keepalive: {e} ===")
        import traceback
        logger.error(traceback.format_exc())
    
    # Messaggio che appare nei log prima del loop
    logger.info("Bot in esecuzione in modalità webhook...")
    print("\n🌐 Server HTTP in ascolto, bot in modalità webhook...")
    print("   (Il bot riceve gli update via HTTP)")
    
    import time
    # Loop infinito per mantenere il processo in vita
    # Il server HTTP gestirà le richieste in entrata
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()

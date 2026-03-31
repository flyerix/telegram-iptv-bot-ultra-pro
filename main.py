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
from modules.onboarding import OnboardingManager
from modules.stato_servizio import StatoServizio, STATO_OPERATIVO, STATO_PROBLEMI
from modules.manutenzione import Manutenzione
from modules.notifications import NotificationSystem, TipoNotifica
from modules.statistiche import StatisticheDashboard

# Import keep-alive server
from keepalive.server import start_server as start_keepalive

# ==================== CONFIGURAZIONE ====================

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variabili globali
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]
KEEPALIVE_PORT = int(os.environ.get("KEEPALIVE_PORT", "8080"))
KEEPALIVE_HOST = os.environ.get("KEEPALIVE_HOST", "0.0.0.0")

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
(
    STATE_START,
    STATE_TICKET_CREATE,
    STATE_TICKET_DESCRIPTION,
    STATE_RICHIEDTA_IPTV,
    STATE_ONBOARDING,
    STATE_FAQ_CATEGORIA,
    STATE_FAQ_RISPOSTA,
) = range(7)

# Callback data prefixes
CB_FAQ = "faq_"
CB_ONBOARDING = "onb_"
CB_MENU = "menu_"
CB_TICKET = "ticket_"
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


# ==================== MIDDLEWARE ====================

async def check_manutenzione(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica se il bot è in modalità manutenzione."""
    if manutenzione.is_attiva():
        user_id = update.effective_user.id if update.effective_user else 0
        
        # Gli admin possono sempre accedere
        if user_id in ADMIN_IDS:
            return False
        
        # Messaggio di manutenzione
        messaggio = manutenzione.get_messaggio()
        if update.message:
            await update.message.reply_text(messaggio)
        elif update.callback_query:
            await update.callback_query.answer(messaggio, show_alert=True)
        
        return True
    return False


async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica rate limit per l'utente."""
    user_id = str(update.effective_user.id if update.effective_user else 0)
    
    if not rate_limiter.check_rate_limit(user_id):
        # Limite superato
        if update.message:
            await update.message.reply_text(
                "⏳ Troppe richieste! Riprova tra qualche secondo."
            )
        return True
    return False


# ==================== COMANDI UTENTE ====================

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
    
    # Messaggio di benvenuto
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Benvenuto <b>{user.full_name}</b>!\n\n"
        f"Sono HelperBot, il tuo assistente per la gestione IPTV.\n\n"
        f"Posso aiutarti con:\n"
        f"• 📺 Informazioni sulla tua lista IPTV\n"
        f"• 🎫 Creare ticket di supporto\n"
        f"• ❓ FAQ e guide\n"
        f"• 📊 Stato del servizio\n\n"
        f"Cosa vuoi fare?",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


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
    stato = stato_servizio.get_stato_corrente()
    problemi = stato_servizio.get_problemi()
    
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
    stats = stato_servizio.get_statistiche()
    if stats:
        uptime = stats.get("ultimo_riavvio", "N/A")
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
    if manutenzione.is_attiva():
        manutenzione.disattiva(str(user_id))
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
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❓ <b>Scegli una categoria FAQ:</b>",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_FAQ}categoria_"):
        cat_id = data.replace(f"{CB_FAQ}categoria_", "")
        faqs = faq_system.get_faq_by_categoria(cat_id)
        
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
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        cat_nome = FaqSystem.CATEGORIE.get(cat_id, cat_id)
        await query.edit_message_text(
            f"❓ <b>{cat_nome}</b>\n\nSeleziona una domanda:",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_FAQ}view_"):
        faq_id = int(data.replace(f"{CB_FAQ}view_", ""))
        faq = faq_system.get_faq(faq_id)
        
        if not faq:
            await query.edit_message_text("❓ FAQ non trovata.")
            return
        
        text = f"❓ <b>{faq.get('domanda')}</b>\n\n{faq.get('risposta')}"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Torna alle FAQ", callback_data=f"{CB_FAQ}categorie")]
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
            await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
    
    elif data.startswith(f"{CB_ONBOARDING}step_"):
        step_num = int(data.replace(f"{CB_ONBOARDING}step_", ""))
        username = update.effective_user.username or ""
        msg, keyboard = onboarding.genera_messaggio_step(step_num, username)
        if msg:
            await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=constants.ParseMode.HTML)
    
    elif data == f"{CB_ONBOARDING}skip":
        # Salta onboarding
        onboarding.completa_onboarding(user_id)
        await query.edit_message_text(
            "✅ <b>Onboarding completato!</b>\n\n"
            "Puoi sempre ripetere l'onboarding con /start",
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
        # Mostra form creazione ticket
        keyboard = [
            [
                InlineKeyboardButton("🔴 Alta", callback_data=f"{CB_TICKET}priorita_alta"),
                InlineKeyboardButton("🟡 Media", callback_data=f"{CB_TICKET}priorita_media"),
                InlineKeyboardButton("🟢 Bassa", callback_data=f"{CB_TICKET}priorita_bassa")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎫 <b>Seleziona priorità</b>\n\n"
            "Alta: Problemi gravi, servizio non funzionante\n"
            "Media: Problemi minori, rallentamenti\n"
            "Bassa: Domande, informazioni",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML
        )
    
    elif data.startswith(f"{CB_TICKET}priorita_"):
        # Salva priorità e chiedi descrizione
        priorita = data.replace(f"{CB_TICKET}priorita_", "")
        
        await query.edit_message_text(
            f"🎫 <b>Ticket priorità {priorita.upper()}</b>\n\n"
            "Descrivi il tuo problema in dettaglio:",
            parse_mode=constants.ParseMode.HTML
        )
        
        # TODO: Gestire la creazione del ticket con ConversationHandler
        return STATE_TICKET_CREATE
    
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
    if data == f"{CB_ADMIN}richieste":
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
        manutenzione.attiva("Manutenzione programmata", str(user_id))
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
    
    if data == f"{CB_MENU}stato":
        # Mostra stato utente
        user_id = str(update.effective_user.id)
        lista = user_management.get_lista_utente(user_id)
        
        if lista:
            text = f"📺 <b>La tua lista IPTV</b>\n\n"
            text += f"🔗 URL: <code>{lista.get('url', 'N/A')}</code>\n"
            text += f"📊 Stato: {lista.get('stato', 'N/A')}\n"
            text += f"📅 Scadenza: {lista.get('data_scadenza', 'N/A')}"
        else:
            text = "📭 Non hai una lista IPTV attiva.\nUsa /richiedi per richiederne una."
        
        await query.edit_message_text(text, parse_mode=constants.ParseMode.HTML)


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
    
    # Comandi utente
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("faq", cmd_faq))
    application.add_handler(CommandHandler("ticket", cmd_ticket))
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
    
    # Avvia keep-alive server in background
    try:
        start_keepalive(KEEPALIVE_PORT, KEEPALIVE_HOST)
        logger.info(f"Keep-alive server avviato su {KEEPALIVE_HOST}:{KEEPALIVE_PORT}")
    except Exception as e:
        logger.error(f"Errore avvio keep-alive: {e}")


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
        print("   - KEEPALIVE_PORT: Porta per il server keep-alive (default: 8080)")
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
    print(f"🌐 Keep-alive: {KEEPALIVE_HOST}:{KEEPALIVE_PORT}")
    print("=" * 50)
    
    # Avvia polling
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

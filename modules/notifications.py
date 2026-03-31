"""
Modulo per le notifiche intelligenti di HelperBot.
Gestisce notifiche automatiche, code, retry e report giornalieri.

Caratteristiche:
- Notifiche automatiche per ticket senza risposta, backup falliti,
  violazioni rate limit, scadenze IPTV e cambi stato servizio
- Tipi di notifiche: immediate, differite, periodiche
- Coda notifiche con retry automatico
- Log delle notifiche inviate
- Report giornaliero per gli admin

Utilizza il modulo di persistenza per la coda delle notifiche.
"""

import uuid
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from threading import Lock
from collections import deque

from core.data_persistence import DataPersistence

# Importa costanti dagli altri moduli
from modules.user_management import STATO_ATTIVO, STATO_LISTA_ATTIVA, STATO_LISTA_SCADUTA
from modules.stato_servizio import STATO_OPERATIVO, STATO_PROBLEMI, STATO_MANUTENZIONE, STATO_DISSERVIZIO

# Configurazione logger
logger = logging.getLogger(__name__)


# ==================== COSTANTI ====================

class TipoNotifica(Enum):
    """Tipi di notifica supportati."""
    TICKET_SENZA_RISPOSTA = "ticket_senza_risposta"
    BACKUP_FALLITO = "backup_fallito"
    RATE_LIMIT_VIOLATO = "rate_limit_violato"
    SCADENZA_IMMINENTE = "scadenza_imminente"
    STATO_SERVIZIO = "stato_servizio"
    REPORT_GIORNALIERO = "report_giornaliero"
    GENERICA = "generica"


class PrioritaNotifica(Enum):
    """Livelli di priorità per le notifiche."""
    CRITICA = 1      # Notifiche critiche che richiedono attenzione immediata
    ALTA = 2          # Notifiche importanti
    MEDIA = 3         # Notifiche normali
    BASSA = 4         # Notifiche a bassa priorità


class StatoNotifica(Enum):
    """Stati di una notifica nella coda."""
    IN_CODA = "in_coda"
    INVIATA = "inviata"
    FALLITA = "fallita"
    ANNULLATA = "annullata"


# Costanti configurazione
ORE_SENZA_RISPOSTA_DEFAULT = 24  # Ore prima di notificare ticket senza risposta
GIORNI_SCADENZA_DEFAULT = 3     # Giorni prima della scadenza per notifica
MAX_RETRY = 3                    # Numero massimo di tentativi per ogni notifica
INTERVALLO_RETRY_SECONDI = 60     # Intervallo tra i retry in secondi
MAX_NOTIFICHE_CODA = 1000        # Massimo notifiche in coda


# ==================== DATACLASS ====================

@dataclass
class Notifica:
    """Rappresenta una singola notifica."""
    id: str
    user_id: int
    tipo: str
    messaggio: str
    priorità: int
    stato: str
    data_creazione: str
    data_invio: Optional[str] = None
    retry_count: int = 0
    errore: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LogNotifica:
    """Rappresenta una notifica già inviata nel log."""
    id: str
    user_id: int
    tipo: str
    messaggio: str
    priorità: int
    data_invio: str
    successo: bool
    errore: Optional[str] = None


@dataclass
class NotificaStatoServizio:
    """Rappresenta una notifica di cambio stato servizio."""
    vecchio_stato: str
    nuovo_stato: str
    timestamp: str


# ==================== ECCEZIONI ====================

class NotificheError(Exception):
    """Eccezione personalizzata per errori nel sistema notifiche."""
    pass


class CodaPienaError(NotificheError):
    """Eccezione quando la coda delle notifiche è piena."""
    pass


class NotificaNonTrovataError(NotificheError):
    """Eccezione quando una notifica non viene trovata."""
    pass


# ==================== CLASSE PRINCIPALE ====================

class NotificationSystem:
    """
    Sistema di notifiche intelligenti per HelperBot.
    Gestisce l'invio, la coda e il retry delle notifiche.
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls, persistence: Optional[DataPersistence] = None):
        """
        Implementa il pattern Singleton per il sistema notifiche.
        
        Args:
            persistence: Istanza di DataPersistence opzionale
            
        Returns:
            L'istanza singleton del sistema notifiche
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, persistence: Optional[DataPersistence] = None):
        """
        Inizializza il sistema notifiche.
        
        Args:
            persistence: Istanza di DataPersistence opzionale
        """
        # Evita re-inizializzazione
        if self._initialized:
            return
        
        self.persistence = persistence
        self._lock = Lock()
        
        # Configurazione
        self.ore_senza_risposta = ORE_SENZA_RISPOSTA_DEFAULT
        self.giorni_scadenza = GIORNI_SCADENZA_DEFAULT
        
        # Code e cache
        self._coda_notifiche: deque = deque(maxlen=MAX_NOTIFICHE_CODA)
        self._log_notifiche: List[LogNotifica] = []
        self._notifiche_attive: Dict[str, Notifica] = {}
        
        # Admin IDs (configurabile)
        self._admin_ids: List[int] = []
        
        # Callback per l'invio effettivo (da configurare esternamente)
        self._send_callback: Optional[Callable] = None
        
        # Flag per il report giornaliero
        self._ultimo_report: Optional[datetime] = None
        
        self._initialized = True
        logger.info("Sistema notifiche inizializzato")
    
    # ==================== METODI DI CONFIGURAZIONE ====================
    
    def imposta_admin(self, admin_ids: List[int]) -> None:
        """
        Imposta gli ID degli admin che ricevono le notifiche di sistema.
        
        Args:
            admin_ids: Lista di ID utente Telegram per gli admin
        """
        self._admin_ids = admin_ids
        logger.info(f"Admin impostati: {admin_ids}")
    
    def imposta_callback_invio(self, callback: Callable) -> None:
        """
        Imposta la funzione callback per l'invio effettivo delle notifiche.
        
        Args:
            callback: Funzione async che accetta (user_id, messaggio) e restituisce bool
        """
        self._send_callback = callback
        logger.info("Callback di invio notifiche configurato")
    
    def imposta_configurazione(self, ore_senza_risposta: int = ORE_SENZA_RISPOSTA_DEFAULT,
                                giorni_scadenza: int = GIORNI_SCADENZA_DEFAULT) -> None:
        """
        Configura i parametri del sistema notifiche.
        
        Args:
            ore_senza_risposta: Ore prima di notificare ticket senza risposta
            giorni_scadenza: Giorni prima della scadenza per notifica
        """
        self.ore_senza_risposta = ore_senza_risposta
        self.giorni_scadenza = giorni_scadenza
        logger.info(f"Configurazione notifiche: {ore_senza_risposta}h/{giorni_scadenza}gg")
    
    # ==================== METODI DI INVIO NOTIFICHE ====================
    
    async def invia_notifica(self, user_id: int, tipo: TipoNotifica, 
                           messaggio: str, priorità: PrioritaNotifica = PrioritaNotifica.MEDIA,
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Invia una notifica a un utente.
        
        Args:
            user_id: ID utente Telegram
            tipo: Tipo di notifica
            messaggio: Contenuto della notifica
            priorità: Priorità della notifica
            metadata: Dati aggiuntivi opzionali
            
        Returns:
            ID della notifica creata
            
        Raises:
            NotificheError: Se l'invio fallisce
        """
        notifica_id = str(uuid.uuid4())
        
        with self._lock:
            # Crea l'oggetto notifica
            notifica = Notifica(
                id=notifica_id,
                user_id=user_id,
                tipo=tipo.value,
                messaggio=messaggio,
                priorità=priorità.value,
                stato=StatoNotifica.IN_CODA.value,
                data_creazione=datetime.now().isoformat(),
                metadata=metadata or {}
            )
            
            # Aggiungi alla coda
            self._coda_notifiche.append(notifica)
            self._notifiche_attive[notifica_id] = notifica
            
            logger.debug(f"Notifica {notifica_id} aggiunta alla coda per user {user_id}")
        
        # Prova a inviare immediatamente se è una notifica di priorità critica
        if priorità == PrioritaNotifica.CRITICA:
            await self._processa_notifica(notifica_id)
        
        return notifica_id
    
    async def _processa_notifica(self, notifica_id: str) -> bool:
        """
        Processa l'invio di una singola notifica.
        
        Args:
            notifica_id: ID della notifica da inviare
            
        Returns:
            True se l'invio ha avuto successo
        """
        with self._lock:
            if notifica_id not in self._notifiche_attive:
                return False
            
            notifica = self._notifiche_attive[notifica_id]
        
        # Usa callback se disponibile
        if self._send_callback:
            try:
                successo = await self._send_callback(
                    notifica.user_id, 
                    notifica.messaggio
                )
                
                if successo:
                    await self._notifica_inviata(notifica)
                    return True
                else:
                    await self._notifica_fallita(notifica, "Invio fallito")
                    return False
                    
            except Exception as e:
                logger.error(f"Errore nell'invio della notifica {notifica_id}: {e}")
                await self._notifica_fallita(notifica, str(e))
                return False
        else:
            # Simula invio se non c'è callback
            logger.warning(f"Nessun callback configurato, notifica {notifica_id} simulata")
            await self._notifica_inviata(notifica)
            return True
    
    async def _notifica_inviata(self, notifica: Notifica) -> None:
        """
        Marca una notifica come inviata con successo.
        
        Args:
            notifica: Notifica inviata
        """
        with self._lock:
            notifica.stato = StatoNotifica.INVIATA.value
            notifica.data_invio = datetime.now().isoformat()
            
            # Crea entry per il log
            log_entry = LogNotifica(
                id=notifica.id,
                user_id=notifica.user_id,
                tipo=notifica.tipo,
                messaggio=notifica.messaggio,
                priorità=notifica.priorità,
                data_invio=notifica.data_invio,
                successo=True
            )
            
            self._log_notifiche.append(log_entry)
            
            # Rimuovi dalle notifiche attive
            if notifica.id in self._notifiche_attive:
                del self._notifiche_attive[notifica.id]
        
        logger.info(f"Notifica {notifica.id} inviata con successo a {notifica.user_id}")
    
    async def _notifica_fallita(self, notifica: Notifica, errore: str) -> None:
        """
        Gestisce il fallimento di una notifica.
        
        Args:
            notifica: Notifica fallita
            errore: Messaggio di errore
        """
        with self._lock:
            notifica.retry_count += 1
            notifica.errore = errore
            
            if notifica.retry_count >= MAX_RETRY:
                # Numero massimo di tentativi raggiunto
                notifica.stato = StatoNotifica.FALLITA.value
                
                # Crea entry per il log
                log_entry = LogNotifica(
                    id=notifica.id,
                    user_id=notifica.user_id,
                    tipo=notifica.tipo,
                    messaggio=notifica.messaggio,
                    priorità=notifica.priorità,
                    data_invio=datetime.now().isoformat(),
                    successo=False,
                    errore=errore
                )
                
                self._log_notifiche.append(log_entry)
                
                # Rimuovi dalle notifiche attive
                if notifica.id in self._notifiche_attive:
                    del self._notifiche_attive[notifica.id]
                
                logger.error(f"Notifica {notifica.id} fallita dopo {MAX_RETRY} tentativi")
            else:
                # Rimetti in coda per retry
                notifica.stato = StatoNotifica.IN_CODA.value
                self._coda_notifiche.append(notifica)
                logger.warning(f"Notifica {notifica.id} fallita, retry {notifica.retry_count}/{MAX_RETRY}")
    
    # ==================== GESTIONE CODE ====================
    
    async def processa_coda(self) -> None:
        """Processa tutte le notifiche in coda."""
        # Copia la coda per non bloccare durante l'elaborazione
        with self._lock:
            coda_copy = list(self._coda_notifiche)
            self._coda_notifiche.clear()
        
        for notifica in coda_copy:
            if notifica.stato == StatoNotifica.IN_CODA.value:
                await self._processa_notifica(notifica.id)
    
    async def retry_notifiche_fallite(self) -> None:
        """Riprova a inviare le notifiche fallite."""
        with self._lock:
            for notifica_id, notifica in list(self._notifiche_attive.items()):
                if notifica.stato == StatoNotifica.IN_CODA.value and notifica.retry_count > 0:
                    await self._processa_notifica(notifica_id)
    
    def get_notifiche_in_coda(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista delle notifiche in coda.
        
        Returns:
            Lista di dizionari con i dati delle notifiche in coda
        """
        with self._lock:
            return [
                {
                    "id": n.id,
                    "user_id": n.user_id,
                    "tipo": n.tipo,
                    "messaggio": n.messaggio,
                    "priorità": n.priorità,
                    "stato": n.stato,
                    "data_creazione": n.data_creazione,
                    "retry_count": n.retry_count
                }
                for n in self._coda_notifiche
            ]
    
    def get_log_notifiche(self, limite: int = 100) -> List[Dict[str, Any]]:
        """
        Restituisce il log delle notifiche inviate.
        
        Args:
            limite: Numero massimo di entry da restituire
            
        Returns:
            Lista di dizionari con i dati delle notifiche inviate
        """
        with self._lock:
            log_slice = self._log_notifiche[-limite:] if limite > 0 else self._log_notifiche
            return [
                {
                    "id": l.id,
                    "user_id": l.user_id,
                    "tipo": l.tipo,
                    "messaggio": l.messaggio,
                    "priorità": l.priorità,
                    "data_invio": l.data_invio,
                    "successo": l.successo,
                    "errore": l.errore
                }
                for l in log_slice
            ]
    
    # ==================== NOTIFICHE AUTOMATICHE ====================
    
    async def notifica_ticket_senza_risposta(self, persistence: DataPersistence) -> List[int]:
        """
        Notifica gli admin dei ticket senza risposta da più di X ore.
        
        Args:
            persistence: Istanza di DataPersistence per accedere ai ticket
            
        Returns:
            Lista di ID delle notifiche create
        """
        if not persistence:
            logger.warning("Persistence non fornito a notifica_ticket_senza_risposta")
            return []
        
        notifica_ids = []
        now = datetime.now()
        soglia_tempo = now - timedelta(hours=self.ore_senza_risposta)
        
        # Carica i ticket dal database
        try:
            with persistence._lock:
                ticket_data = persistence._data.get("ticket", {})
            
            # Cerca ticket aperti senza risposta
            for ticket_id, ticket in ticket_data.items():
                stato = ticket.get("stato", "")
                # Considera solo ticket aperti o in lavorazione
                if stato not in ["aperto", "in_lavorazione"]:
                    continue
                
                # Controlla la data dell'ultimo messaggio
                ultimo_messaggio = ticket.get("ultimo_messaggio", ticket.get("data_creazione", ""))
                if ultimo_messaggio:
                    try:
                        data_ultimo = datetime.fromisoformat(ultimo_messaggio)
                        if data_ultimo < soglia_tempo:
                            # Crea notifica per ogni admin
                            for admin_id in self._admin_ids:
                                messaggio = (
                                    f"⚠️ <b>Ticket senza risposta</b>\n\n"
                                    f"Ticket #{ticket_id[:8]}\n"
                                    f"Stato: {stato}\n"
                                    f"Orario: {data_ultimo.strftime('%d/%m/%Y %H:%M')}\n"
                                    f"Da tempo: {self.ore_senza_risposta}h+"
                                )
                                
                                notifica_id = await self.invia_notifica(
                                    admin_id,
                                    TipoNotifica.TICKET_SENZA_RISPOSTA,
                                    messaggio,
                                    PrioritaNotifica.ALTA,
                                    {"ticket_id": ticket_id}
                                )
                                notifica_ids.append(notifica_id)
                    except Exception as e:
                        logger.error(f"Errore nel controllo ticket {ticket_id}: {e}")
            
            if notifica_ids:
                logger.info(f"Create {len(notifica_ids)} notifiche per ticket senza risposta")
                
        except Exception as e:
            logger.error(f"Errore nel rilevamento ticket senza risposta: {e}")
        
        return notifica_ids
    
    async def notifica_backup_fallito(self, errore: str, admin_ids: Optional[List[int]] = None) -> List[int]:
        """
        Notifica gli admin di un backup fallito.
        
        Args:
            errore: Messaggio di errore del backup
            admin_ids: Lista opzionale di admin (usa self._admin_ids se non fornita)
            
        Returns:
            Lista di ID delle notifiche create
        """
        dest_admin = admin_ids if admin_ids else self._admin_ids
        
        if not dest_admin:
            logger.warning("Nessun admin configurato per notifica backup fallito")
            return []
        
        notifica_ids = []
        now = datetime.now()
        
        for admin_id in dest_admin:
            messaggio = (
                f"❌ <b>Backup Fallito</b>\n\n"
                f"Data: {now.strftime('%d/%m/%Y %H:%M')}\n"
                f"Errore: {errore}"
            )
            
            notifica_id = await self.invia_notifica(
                admin_id,
                TipoNotifica.BACKUP_FALLITO,
                messaggio,
                PrioritaNotifica.CRITICA,
                {"errore": errore}
            )
            notifica_ids.append(notifica_id)
        
        logger.warning(f"Create {len(notifica_ids)} notifiche per backup fallito")
        return notifica_ids
    
    async def notifica_rate_limit_violato(self, user_id: int, violazioni_totali: int,
                                       persistence: DataPersistence) -> Optional[str]:
        """
        Notifica gli admin quando un utente viola il rate limit 3+ volte.
        
        Args:
            user_id: ID dell'utente che ha violato il rate limit
            violazioni_totali: Numero totale di violazioni
            persistence: Istanza di DataPersistence per i dati utente
            
        Returns:
            ID della notifica creata, o None
        """
        # Crea solo se ci sono almeno 3 violazioni
        if violazioni_totali < 3:
            return None
        
        username = f"utente_{user_id}"
        
        # Prova a ottenere il nome utente
        if persistence:
            try:
                with persistence._lock:
                    utenti = persistence._data.get("utenti", {})
                    if user_id in utenti:
                        username = utenti[user_id].get("username", username)
            except Exception as e:
                logger.error(f"Errore nel recupero dati utente: {e}")
        
        for admin_id in self._admin_ids:
            messaggio = (
                f"⚠️ <b>Rate Limit Violato</b>\n\n"
                f"Utente: {username}\n"
                f"ID: {user_id}\n"
                f"Violazioni: {violazioni_totali}"
            )
            
            notifica_id = await self.invia_notifica(
                admin_id,
                TipoNotifica.RATE_LIMIT_VIOLATO,
                messaggio,
                PrioritaNotifica.ALTA,
                {"user_id": user_id, "violazioni": violazioni_totali}
            )
            
            logger.warning(f"Notifica rate limit per utente {user_id}: {violazioni_totali} violazioni")
            return notifica_id
        
        return None
    
    async def notifica_scadenza_imminente(self, persistence: DataPersistence) -> List[int]:
        """
        Notifica gli utenti con liste IPTV in scadenza tra X giorni.
        
        Args:
            persistence: Istanza di DataPersistence per accedere alle liste
            
        Returns:
            Lista di ID delle notifiche create
        """
        if not persistence:
            logger.warning("Persistence non fornito a notifica_scadenza_imminente")
            return []
        
        notifica_ids = []
        now = datetime.now()
        soglia_scadenza = now + timedelta(days=self.giorni_scadenza)
        
        try:
            with persistence._lock:
                liste_data = persistence._data.get("liste_iptv", {})
            
            # Cerca liste in scadenza
            for lista_id, lista in liste_data.items():
                stato = lista.get("stato", "")
                if stato != STATO_LISTA_ATTIVA:
                    continue
                
                data_scadenza = lista.get("data_scadenza")
                if not data_scadenza:
                    continue
                
                try:
                    scadenza_dt = datetime.fromisoformat(data_scadenza)
                    
                    # Notifica se la scadenza è entro X giorni
                    if now <= scadenza_dt <= soglia_scadenza:
                        user_id = lista.get("user_id")
                        if not user_id:
                            continue
                        
                        giorni_rimanenti = (scadenza_dt - now).days
                        
                        messaggio = (
                            f"⏰ <b>Scadenza Lista IPTV</b>\n\n"
                            f"La tua lista scade tra <b>{giorni_rimanenti} giorni</b>\n"
                            f"Data: {scadenza_dt.strftime('%d/%m/%Y')}\n\n"
                            f"Rinnova in tempo per non interruzioni!"
                        )
                        
                        notifica_id = await self.invia_notifica(
                            user_id,
                            TipoNotifica.SCADENZA_IMMINENTE,
                            messaggio,
                            PrioritaNotifica.MEDIA,
                            {"lista_id": lista_id, "data_scadenza": data_scadenza}
                        )
                        notifica_ids.append(notifica_id)
                        
                except Exception as e:
                    logger.error(f"Errore nel controllo lista {lista_id}: {e}")
            
            if notifica_ids:
                logger.info(f"Create {len(notifica_ids)} notifiche per scadenze imminenti")
                
        except Exception as e:
            logger.error(f"Errore nel rilevamento scadenze: {e}")
        
        return notifica_ids
    
    async def notifica_stato_servizio(self, vecchio_stato: str, nuovo_stato: str) -> List[int]:
        """
        Notifica gli admin quando lo stato del servizio cambia.
        
        Args:
            vecchio_stato: Stato precedente
            nuovo_stato: Nuovo stato
            
        Returns:
            Lista di ID delle notifiche create
        """
        # Determina priorità basata sul nuovo stato
        if nuovo_stato in [STATO_DISSERVIZIO, STATO_PROBLEMI]:
            priorità = PrioritaNotifica.CRITICA
        elif nuovo_stato == STATO_MANUTENZIONE:
            priorità = PrioritaNotifica.ALTA
        else:
            priorità = PrioritaNotifica.MEDIA
        
        # Emoji basato sullo stato
        emoji_stato = {
            STATO_OPERATIVO: "✅",
            STATO_PROBLEMI: "⚠️",
            STATO_MANUTENZIONE: "🔧",
            STATO_DISSERVIZIO: "❌"
        }.get(nuovo_stato, "❓")
        
        notifica_ids = []
        now = datetime.now()
        
        for admin_id in self._admin_ids:
            messaggio = (
                f"{emoji_stato} <b>Stato Servizio Aggiornato</b>\n\n"
                f"Vecchio stato: {vecchio_stato}\n"
                f"Nuovo stato: {nuovo_stato}\n"
                f"Data: {now.strftime('%d/%m/%Y %H:%M')}"
            )
            
            notifica_id = await self.invia_notifica(
                admin_id,
                TipoNotifica.STATO_SERVIZIO,
                messaggio,
                priorità,
                {"vecchio_stato": vecchio_stato, "nuovo_stato": nuovo_stato}
            )
            notifica_ids.append(notifica_id)
        
        logger.info(f"Notifica cambio stato servizio: {vecchio_stato} -> {nuovo_stato}")
        return notifica_ids
    
    # ==================== REPORT GIORNALIERO ====================
    
    async def invia_report_giornaliero(self, persistence: DataPersistence, 
                                       force: bool = False) -> List[int]:
        """
        Invia il report giornaliero agli admin.
        
        Args:
            persistence: Istanza di DataPersistence per i dati
            force: Se True, forza l'invio anche se già inviato oggi
            
        Returns:
            Lista di ID delle notifiche create
        """
        now = datetime.now()
        
        # Controlla se già inviato oggi
        if not force and self._ultimo_report:
            ultimo = self._ultimo_report
            if ultimo.date() == now.date():
                logger.debug("Report giornaliero già inviato oggi")
                return []
        
        if not persistence:
            logger.warning("Persistence non fornito a invia_report_giornaliero")
            return []
        
        try:
            # Raccogli statistiche
            with persistence._lock:
                utenti = persistence._data.get("utenti", {})
                liste = persistence._data.get("liste_iptv", {})
                ticket = persistence._data.get("ticket", {})
            
            # Statistiche utenti
            totale_utenti = len(utenti)
            utenti_attivi = sum(1 for u in utenti.values() if u.get("stato") == STATO_ATTIVO)
            
            # Statistiche liste
            totale_liste = len(liste)
            liste_attive = sum(1 for l in liste.values() if l.get("stato") == STATO_LISTA_ATTIVA)
            liste_scadute = sum(1 for l in liste.values() if l.get("stato") == STATO_LISTA_SCADUTA)
            
            # Statistiche ticket
            totale_ticket = len(ticket)
            ticket_aperti = sum(1 for t in ticket.values() if t.get("stato") == "aperto")
            ticket_risolti = sum(1 for t in ticket.values() if t.get("stato") == "risolto")
            
            # Statistiche coda notifiche
            with self._lock:
                notifiche_coda = len(self._coda_notifiche)
                notifiche_oggi = sum(
                    1 for log in self._log_notifiche 
                    if datetime.fromisoformat(log.data_invio).date() == now.date()
                )
            
            # Costruisci report
            report = (
                f"📊 <b>Report Giornaliero</b>\n\n"
                f"<b>Utenti:</b> {utenti_attivi}/{totale_utenti} attivi\n"
                f"<b>Liste IPTV:</b> {liste_attive}/{totale_liste} attive, {liste_scadute} scadute\n"
                f"<b>Ticket:</b> {totale_ticket} totali, {ticket_aperti} aperti, {ticket_risolti} risolti\n"
                f"<b>Notifiche:</b> {notifiche_coda} in coda, {notifiche_oggi} inviate oggi\n\n"
                f"<i>Generato: {now.strftime('%d/%m/%Y %H:%M')}</i>"
            )
            
            notifica_ids = []
            for admin_id in self._admin_ids:
                notifica_id = await self.invia_notifica(
                    admin_id,
                    TipoNotifica.REPORT_GIORNALIERO,
                    report,
                    PrioritaNotifica.BASSA,
                    {"totale_utenti": totale_utenti, "totale_ticket": totale_ticket}
                )
                notifica_ids.append(notifica_id)
            
            self._ultimo_report = now
            
            logger.info(f"Report giornaliero inviato a {len(notifica_ids)} admin")
            return notifica_ids
            
        except Exception as e:
            logger.error(f"Errore nella generazione report giornaliero: {e}")
            return []
    
    # ==================== METODI DI UTILITÀ ====================
    
    def get_statistiche(self) -> Dict[str, Any]:
        """
        Restituisce le statistiche del sistema notifiche.
        
        Returns:
            Dizionario con le statistiche
        """
        with self._lock:
            return {
                "notifiche_in_coda": len(self._coda_notifiche),
                "notifiche_attive": len(self._notifiche_attive),
                "log_totale": len(self._log_notifiche),
                "notifiche_oggi": sum(
                    1 for log in self._log_notifiche
                    if datetime.fromisoformat(log.data_invio).date() == datetime.now().date()
                ),
                "configurazione": {
                    "ore_senza_risposta": self.ore_senza_risposta,
                    "giorni_scadenza": self.giorni_scadenza,
                    "admin_configurati": len(self._admin_ids)
                }
            }
    
    async def pulisci_log_notifiche(self, giorni_retention: int = 30) -> int:
        """
        Pulisce le vecchie entry dal log delle notifiche.
        
        Args:
            giorni_retention: Giorni di retention per il log
            
        Returns:
            Numero di entry rimosse
        """
        now = datetime.now()
        soglia = now - timedelta(days=giorni_retention)
        
        with self._lock:
            vecchio_count = len(self._log_notifiche)
            self._log_notifiche = [
                log for log in self._log_notifiche
                if datetime.fromisoformat(log.data_invio) > soglia
            ]
            rimosse = vecchio_count - len(self._log_notifiche)
        
        if rimosse > 0:
            logger.info(f"Rimosse {rimosse} entry vecchie dal log notifiche")
        
        return rimosse
    
    @classmethod
    def reset_instance(cls) -> None:
        """
        Resetta l'istanza singleton (utile per i test).
        """
        with cls._lock:
            cls._instance = None
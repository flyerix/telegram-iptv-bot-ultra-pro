"""
Modulo per il sistema ticket di supporto con priorità automatica.
Gestisce creazione, gestione e risoluzione dei ticket di supporto.

Utilizza il modulo di persistenza per salvare i dati su file JSON.
"""

import uuid
import threading
import logging
import re
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)


# ==================== DATACLASSES ====================

@dataclass
class Ticket:
    """Rappresenta un ticket di supporto."""
    id: str
    user_id: str
    titolo: str
    problema: str
    categoria: str
    priorità: str
    stato: str
    data_creazione: str
    data_aggiornamento: str
    data_risposta: Optional[str] = None
    data_chiusura: Optional[str] = None
    risposte: List[Dict[str, Any]] = field(default_factory=list)
    admin_assegnato: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    risoluzione: Optional[str] = None
    motivo_riapertura: Optional[str] = None
    eliminato: bool = False
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Converte il dataclass in dizionario."""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Ticket':
        """Crea un Ticket da dizionario."""
        return Ticket(**data)


@dataclass
class TicketResponse:
    """Rappresenta una risposta a un ticket."""
    admin_id: str
    risposta: str
    data_risposta: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TicketResponse':
        return TicketResponse(**data)


@dataclass
class TicketFilter:
    """Filtro per la ricerca dei ticket."""
    stato: Optional[str] = None
    priorità: Optional[str] = None
    user_id: Optional[str] = None
    data_from: Optional[str] = None
    data_to: Optional[str] = None
    categoria: Optional[str] = None
    eliminato: Optional[bool] = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


# ==================== COSTANTI ====================

class StatoTicket(Enum):
    """Stati possibili di un ticket."""
    APERTO = "aperto"
    IN_LAVORAZIONE = "in_lavorazione"
    RISOLTO = "risolto"
    CHIUSO = "chiuso"
    RIAPERTO = "riaperto"


class PrioritaTicket(Enum):
    """Livelli di priorità per i ticket."""
    ALTA = "alta"
    MEDIA = "media"
    BASSA = "bassa"


class CategoriaTicket(Enum):
    """Categorie di problemi per i ticket."""
    CONNESSIONE = "connessione"
    STREAMING = "streaming"
    ACCOUNT = "account"
    PAGAMENTO = "pagamento"
    TECNICO = "tecnico"
    ALTRO = "altro"


class ChangeType(Enum):
    """Tipi di modifica per l'audit trail."""
    CREAZIONE = "creazione"
    AGGIORNAMENTO = "aggiornamento"
    RISPOSTA = "risposta"
    CHIUSURA = "chiusura"
    RIAPERTURA = "riapertura"
    PRIORITA = "priorità"
    ELIMINAZIONE = "eliminazione"
    RIPRISTINO = "ripristino"


# Costanti per la priorità automatica
PAROLE_CHIAVE_ALTA_PRIORITA = [
    "non funziona", "errore", "bloccato", "urgente", "emergenza",
    "non riesco", "impossibile", "crash", "non carica", "pantalla nera",
    "nessun canale", " zero canali", "problemi gravi", "fermo", "non si apre",
    "errore 500", "errore 404", "timeout", "connessione rifiutata"
]

PAROLE_CHIAVE_MEDIA_PRIORITA = [
    "lento", "buffer", "qualità", "intermittente", "a volte",
    "di tanto in tanto", "problemi frequenti", "instabile"
]

PAROLE_CHIAVE_BASSA_PRIORITA = [
    "domanda", "info", "informazione", "come fare", "come si fa",
    "piccolo problema", "preferenza", "suggerimento"
]

# Orario notturno/weekend (priorità alta)
ORARIO_NOTTURNO_INIZIO = 22  # 22:00
ORARIO_NOTTURNO_FINE = 7     # 07:00
GIORNI_FESTIVI = [5, 6]      # Sabato (5) e Domenica (6)

# Giorni di scadenza per attivare priorità alta
GIORNI_SCADENZA_ALLERTA = 3

# Numero di ticket recenti per abbassare priorità
TICKET_RECENTI_SOGLIA = 3
GIORNI_TICKET_RECENTI = 7

# TTL cache statistiche (60 secondi)
STATS_CACHE_TTL = 60


# ==================== CLASSE PRINCIPALE ====================

class TicketSystem:
    """
    Sistema di gestione ticket di supporto con priorità automatica.
    Thread-safe con lock gerarchico e cache statistiche.
    """

    def __init__(self, persistence: DataPersistence, user_management: Any = None):
        """
        Inizializza il sistema ticket.

        Args:
            persistence: Istanza del modulo di persistenza dati
            user_management: Istanza del modulo gestione utenti (opzionale)
        """
        self.persistence = persistence
        self.user_management = user_management

        # 2.1 - Lock gerarchico
        self._global_lock = threading.RLock()
        self._ticket_locks = defaultdict(threading.RLock)
        self._index_lock = threading.RLock()

        # 2.5 - Indice utente per O(1) lookup
        self._user_ticket_index: Dict[str, List[str]] = defaultdict(list)
        self._index_initialized = False

        # 2.3 - Cache statistiche con TTL
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._stats_timestamp: float = 0

        logger.info("Modulo TicketSystem inizializzato")

    # ------------------------------------------------------------------
    #  METODI DI HELPERS - LOCK GERRARCHICO E AUDIT
    # ------------------------------------------------------------------

    def _get_ticket_lock(self, ticket_id: str) -> threading.RLock:
        """Restituisce il lock per un dato ticket."""
        return self._ticket_locks[ticket_id]

    def _invalidate_stats_cache(self) -> None:
        """Invalida la cache delle statistiche."""
        with self._global_lock:
            self._stats_cache = None
            self._stats_timestamp = 0

    def _add_audit_trail(self, ticket: Ticket, admin_id: Optional[str],
                         change_type: ChangeType, details: Dict[str, Any]) -> None:
        """Registra una modifica nell'audit trail."""
        entry = {
            "admin_id": admin_id,
            "timestamp": datetime.now().isoformat(),
            "change_type": change_type.value,
            "details": details
        }
        ticket.audit_trail.append(entry)

    def _ensure_index(self) -> None:
        """Inizializza l'indice user_id -> ticket_ids se non già fatto."""
        with self._index_lock:
            if self._index_initialized:
                return
            ticket_data = self.persistence.get_data("ticket") or {}
            for tid, tdata in ticket_data.items():
                uid = tdata.get("user_id")
                if uid:
                    if tid not in self._user_ticket_index[uid]:
                        self._user_ticket_index[uid].append(tid)
            self._index_initialized = True

    def _update_user_index_add(self, user_id: str, ticket_id: str) -> None:
        """Aggiunge un ticket all'indice per user_id."""
        with self._index_lock:
            if ticket_id not in self._user_ticket_index[user_id]:
                self._user_ticket_index[user_id].append(ticket_id)

    def _update_user_index_remove(self, user_id: str, ticket_id: str) -> None:
        """Rimuove un ticket dall'indice per user_id."""
        with self._index_lock:
            if ticket_id in self._user_ticket_index[user_id]:
                self._user_ticket_index[user_id].remove(ticket_id)

    def _update_user_index_update(self, old_user_id: str,
                                  new_user_id: str, ticket_id: str) -> None:
        """Aggiorna l'indice quando cambia user_id."""
        with self._index_lock:
            if old_user_id != new_user_id:
                if ticket_id in self._user_ticket_index[old_user_id]:
                    self._user_ticket_index[old_user_id].remove(ticket_id)
                if ticket_id not in self._user_ticket_index[new_user_id]:
                    self._user_ticket_index[new_user_id].append(ticket_id)

    def _save_ticket(self, ticket: Ticket) -> None:
        """Salva un ticket su persistence."""
        self.persistence.update_data(f"ticket.{ticket.id}", ticket.to_dict())

    # ------------------------------------------------------------------
    #  2.7 DATACLASS CONVERSION
    # ------------------------------------------------------------------

    def _to_ticket(self, data: Dict[str, Any]) -> Ticket:
        """Converte dict in Ticket (compatibilità dati esistenti)."""
        default_fields = {
            'risposte': [], 'tags': [], 'risoluzione': None,
            'motivo_riapertura': None, 'eliminato': False, 'audit_trail': []
        }
        for k, v in default_fields.items():
            if k not in data:
                data[k] = v
        return Ticket.from_dict(data)

    # ------------------------------------------------------------------
    #  CREAZIONE TICKET
    # ------------------------------------------------------------------

    def crea_ticket(self, user_id: str, problema: str,
                    categoria: str = "altro") -> Dict[str, Any]:
        """
        Crea un nuovo ticket di supporto con priorità automatica.
        Thread-safe.
        """
        try:
            categoria_valida = self._valida_categoria(categoria)
            ticket_id = self._genera_id_ticket()
            priorità = self.assegna_priorita_automatica(user_id, problema,
                                                        categoria_valida)
            stato = StatoTicket.APERTO.value
            now = datetime.now().isoformat()

            ticket = Ticket(
                id=ticket_id, user_id=user_id,
                titolo=problema[:50], problema=problema,
                categoria=categoria_valida, priorità=priorità, stato=stato,
                data_creazione=now, data_aggiornamento=now,
                data_risposta=None, data_chiusura=None,
                risposte=[], admin_assegnato=None,
                tags=self._estrai_tags(problema), eliminato=False,
                audit_trail=[], risoluzione=None, motivo_riapertura=None
            )

            self._add_audit_trail(ticket, admin_id=None,
                                  change_type=ChangeType.CREAZIONE,
                                  details={"user_id": user_id,
                                           "categoria": categoria_valida})

            self._save_ticket(ticket)
            self._update_user_index_add(user_id, ticket_id)

            logger.info(f"Ticket {ticket_id} creato da utente {user_id}")
            return ticket.to_dict()

        except Exception as e:
            logger.error(f"Errore nella creazione del ticket: {e}")
            raise TicketSystemError(f"Impossibile creare il ticket: {e}")

    def _genera_id_ticket(self) -> str:
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"

    def _valida_categoria(self, categoria: str) -> str:
        categoria = categoria.lower().strip()
        categorie_valide = [c.value for c in CategoriaTicket]
        if categoria in categorie_valide:
            return categoria
        for cat in CategoriaTicket:
            if categoria in cat.value:
                return cat.value
        return CategoriaTicket.ALTRO.value

    def _estrai_tags(self, problema: str) -> List[str]:
        tags = []
        problema_lower = problema.lower()
        for parola in PAROLE_CHIAVE_ALTA_PRIORITA:
            if parola in problema_lower:
                tags.append("urgente")
                break
        tecnologie = ["m3u", "m3u8", "xtream", "kodi", "plex", "smarttv",
                      "firestick"]
        for tech in tecnologie:
            if tech in problema_lower:
                tags.append(tech)
        return list(set(tags))

    # ------------------------------------------------------------------
    #  2.2 - PRIORITA' AUTOMATICA (eccezioni propagate/loggate)
    # ------------------------------------------------------------------

    def assegna_priorita_automatica(self, user_id: str, problema: str,
                                    categoria: str) -> str:
        punteggio = 0
        punteggio += self._calcola_punteggio_parole_chiave(problema)

        # 2.2 - _è_utente_vip e _lista_in_scadenza non silenziano eccezioni
        try:
            if self._è_utente_vip(user_id):
                punteggio += 20
                logger.debug(f"Utente {user_id} è VIP, +20 punti")
        except Exception as e:
            logger.error(
                f"Errore in _è_utente_vip per utente {user_id}: "
                f"{traceback.format_exc()}")
            # Propaga l'eccezione ma fallo gestire al chiamante
            raise

        try:
            if self._lista_in_scadenza(user_id):
                punteggio += 25
                logger.debug(f"Utente {user_id} in scadenza, +25 punti")
        except Exception as e:
            logger.error(
                f"Errore in _lista_in_scadenza per utente {user_id}: "
                f"{traceback.format_exc()}")
            raise

        punteggio += self._calcola_punteggio_frequenza(user_id)

        if self._è_orario_notturno_o_festivo():
            punteggio += 15

        punteggio += self._calcola_punteggio_categoria(categoria)

        if punteggio >= 50:
            return PrioritaTicket.ALTA.value
        elif punteggio >= 20:
            return PrioritaTicket.MEDIA.value
        return PrioritaTicket.BASSA.value

    def _calcola_punteggio_parole_chiave(self, problema: str) -> float:
        punteggio = 0
        problema_lower = problema.lower()
        for parola in PAROLE_CHIAVE_ALTA_PRIORITA:
            if parola in problema_lower:
                punteggio += 30
                break
        for parola in PAROLE_CHIAVE_MEDIA_PRIORITA:
            if parola in problema_lower:
                punteggio += 10
                break
        for parola in PAROLE_CHIAVE_BASSA_PRIORITA:
            if parola in problema_lower:
                punteggio -= 15
                break
        return punteggio

    def _è_utente_vip(self, user_id: str) -> bool:
        """Verifica se l'utente è VIP. Propaga eccezioni o logga traceback."""
        try:
            if self.user_management:
                utente = self.user_management.get_utente(user_id)
                if utente:
                    return utente.get("is_vip", False) or utente.get("vip", False)
            return False
        except Exception:
            logger.error(
                f"Errore in _è_utente_vip({user_id}): {traceback.format_exc()}")
            # L'eccezione viene propagata (non silenziata)
            raise

    def _lista_in_scadenza(self, user_id: str) -> bool:
        """Verifica se la lista dell'utente sta per scadere."""
        try:
            if self.user_management:
                utente = self.user_management.get_utente(user_id)
                if utente and utente.get("data_scadenza"):
                    scadenza = datetime.fromisoformat(
                        utente["data_scadenza"].split('.')[0])
                    giorni_rimanenti = (scadenza - datetime.now()).days
                    return (GIORNI_SCADENZA_ALLERTA >= giorni_rimanenti >= 0)
            return False
        except Exception:
            logger.error(
                f"Errore in _lista_in_scadenza({user_id}): "
                f"{traceback.format_exc()}")
            raise

    def _calcola_punteggio_frequenza(self, user_id: str) -> float:
        try:
            # Usa l'indice per O(n) invece di O(n*m)
            ticket_ids = self._user_ticket_index.get(user_id, [])
            now = datetime.now()
            cutoff = now - timedelta(days=GIORNI_TICKET_RECENTI)
            count = 0
            for tid in ticket_ids:
                t = self.get_ticket(tid)
                if t and not t.get('eliminato', False):
                    d = t.get("data_creazione", "")
                    try:
                        if datetime.fromisoformat(d) > cutoff:
                            count += 1
                    except Exception:
                        pass

            if count >= TICKET_RECENTI_SOGLIA:
                return -20
            elif count >= 1:
                return -5
            return 0
        except Exception:
            logger.error(f"Errore in _calcola_punteggio_frequenza: {traceback.format_exc()}")
            return 0

    def _è_orario_notturno_o_festivo(self) -> bool:
        now = datetime.now()
        if now.hour >= ORARIO_NOTTURNO_INIZIO or now.hour < ORARIO_NOTTURNO_FINE:
            return True
        if now.weekday() in GIORNI_FESTIVI:
            return True
        return False

    def _calcola_punteggio_categoria(self, categoria: str) -> float:
        categorie_alte = ["connessione", "account", "pagamento"]
        categorie_medie = ["streaming", "tecnico"]
        if categoria in categorie_alte:
            return 15
        elif categoria in categorie_medie:
            return 5
        return 0

    # ------------------------------------------------------------------
    #  2.4 - GET TICKET_PENDENTI + GET_TUTTI_TICKET
    # ------------------------------------------------------------------

    def get_ticket(self, ticket_id: str,
                   use_shared_lock: bool = False) -> Optional[Dict[str, Any]]:
        """
        Ottiene un ticket. use_shared_lock=True per letture concorrenti.
        """
        try:
            with self._get_ticket_lock(ticket_id):
                ticket_data = self.persistence.get_data(f"ticket.{ticket_id}")
                return dict(ticket_data) if ticket_data else None
        except Exception as e:
            logger.error(f"Errore nel recupero del ticket {ticket_id}: {e}")
            return None

    def get_ticket_utente(self, user_id: str) -> List[Dict[str, Any]]:
        """
        2.5 - Performance migliorata con indice. O(n) invece di O(n²).
        """
        try:
            self._ensure_index()
            ticket_ids = list(self._user_ticket_index.get(user_id, []))
            result = []
            for tid in ticket_ids:
                t = self.get_ticket(tid)
                if t and not t.get('eliminato', False):
                    result.append(t)
            result.sort(key=lambda x: x.get("data_creazione", ""), reverse=True)
            return result
        except Exception as e:
            logger.error(f"Errore nel recupero dei ticket per utente {user_id}: {e}")
            return []

    def get_tutti_ticket(self, stato: Optional[str] = None,
                        priorità: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        2.1 - Usa lock globale per operazioni bulk.
              Legge tutti i ticket con lock condiviso.
        """
        try:
            with self._global_lock:
                ticket_data = self.persistence.get_data("ticket") or {}
                risultato = []
                for tid, tdata in ticket_data.items():
                    if tdata.get('eliminato', False):
                        continue
                    risultato.append(dict(tdata))

                if stato:
                    risultato = [t for t in risultato if t.get("stato") == stato]
                if priorità:
                    risultato = [t for t in risultato if t.get("priorità") == priorità]

                priorità_ordine = {"alta": 0, "media": 1, "bassa": 2}
                risultato.sort(
                    key=lambda x: (
                        priorità_ordine.get(x.get("priorità"), 3),
                        x.get("data_creazione", "")
                    )
                )
                return risultato
        except Exception as e:
            logger.error(f"Errore nel recupero dei ticket: {e}")
            return []

    def find_tickets(self, stato: Optional[str] = None,
                     priorità: Optional[str] = None,
                     user_id: Optional[str] = None,
                     data_from: Optional[str] = None,
                     data_to: Optional[str] = None,
                     categoria: Optional[str] = None,
                     eliminato: bool = False,
                     page: Optional[int] = None,
                     per_page: int = 20) -> Dict[str, Any]:
        """
        Query ticket by criteria con paginazione.
        """
        try:
            with self._global_lock:
                ticket_data = self.persistence.get_data("ticket") or {}
                risultato = []

                for tid, tdata in ticket_data.items():
                    tdict = dict(tdata)
                    if tdict.get('eliminato', False) != eliminato:
                        continue
                    if stato and tdict.get("stato") != stato:
                        continue
                    if priorità and tdict.get("priorità") != priorità:
                        continue
                    if user_id and tdict.get("user_id") != user_id:
                        continue
                    if categoria and tdict.get("categoria") != categoria:
                        continue
                    if data_from:
                        td = tdict.get("data_creazione", "")
                        if td and td < data_from:
                            continue
                    if data_to:
                        td = tdict.get("data_creazione", "")
                        if td and td > data_to:
                            continue
                    risultato.append(tdict)

                priorità_ordine = {"alta": 0, "media": 1, "bassa": 2}
                risultato.sort(
                    key=lambda x: (
                        priorità_ordine.get(x.get("priorità"), 3),
                        x.get("data_creazione", "")
                    ), reverse=False
                )

                total = len(risultato)
                if page is not None:
                    start = (page - 1) * per_page
                    end = start + per_page
                    risultato = risultato[start:end]

                return {
                    "tickets": risultato,
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": (total + per_page - 1) // per_page if page else 1
                }
        except Exception as e:
            logger.error(f"Errore in find_tickets: {e}")
            return {"tickets": [], "total": 0, "page": page, "per_page": per_page}

    def get_ticket_pendenti(self, stato: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        2.4 - Distingue chiaramente 'pendenti' vs 'in_attesa'.
        Restituisce ticket con stato specifico o 'pendenti' (aperti/in_lavorazione).
        """
        stati_pendenti = [StatoTicket.APERTO.value, StatoTicket.IN_LAVORAZIONE.value]
        if stato:
            stati_pendenti = [stato]
        try:
            with self._global_lock:
                ticket_data = self.persistence.get_data("ticket") or {}
                risultato = []
                for tid, tdata in ticket_data.items():
                    if tdata.get('eliminato', False):
                        continue
                    if tdata.get("stato") in stati_pendenti:
                        risultato.append(dict(tdata))
                priorità_ordine = {"alta": 0, "media": 1, "bassa": 2}
                risultato.sort(
                    key=lambda x: (
                        priorità_ordine.get(x.get("priorità"), 3),
                        x.get("data_creazione", "")
                    )
                )
                return risultato
        except Exception as e:
            logger.error(f"Errore in get_ticket_pendenti: {e}")
            return []

    def get_paginati(self, page: int = 1, per_page: int = 20,
                     stato: Optional[str] = None,
                     priorità: Optional[str] = None) -> Dict[str, Any]:
        """
        Ottiene ticket con paginazione.
        """
        return self.find_tickets(stato=stato, priorità=priorità,
                                 page=page, per_page=per_page,
                                 eliminato=False)

    # ==================== RISPOSTE ====================

    def rispondi_ticket(self, ticket_id: str, admin_id: str,
                       risposta: str) -> Dict[str, Any]:
        """
        Aggiunge una risposta a un ticket (lock per-ticket).
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        if ticket_data["stato"] in [StatoTicket.CHIUSO.value,
                                    StatoTicket.RISOLTO.value]:
            raise InvalidStateError(
                f"Impossibile rispondere a un ticket {ticket_data['stato']}")

        with self._get_ticket_lock(ticket_id):
            try:
                now = datetime.now().isoformat()
                ticket = self._to_ticket(ticket_data)

                nuova_risposta = TicketResponse(
                    admin_id=admin_id, risposta=risposta,
                    data_risposta=now).to_dict()

                ticket.risposte.append(nuova_risposta)
                ticket.data_risposta = now
                ticket.data_aggiornamento = now

                if ticket.stato == StatoTicket.APERTO.value:
                    ticket.stato = StatoTicket.IN_LAVORAZIONE.value

                ticket.admin_assegnato = admin_id

                self._add_audit_trail(ticket, admin_id=admin_id,
                                      change_type=ChangeType.RISPOSTA,
                                      details={"risposta": risposta})

                self._save_ticket(ticket)
                logger.info(
                    f"Risposta aggiunta al ticket {ticket_id} da admin {admin_id}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(
                    f"Errore nella risposta al ticket {ticket_id}: {e}")
                raise TicketSystemError(
                    f"Impossibile rispondere al ticket: {e}")

    # ==================== CHIUSURA E RIAPERTURA ====================

    def chiudi_ticket(self, ticket_id: str, admin_id: str,
                     risoluzione: Optional[str] = None) -> Dict[str, Any]:
        """
        Chiude un ticket (lock per-ticket + invalidate cache statistiche).
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")

        with self._get_ticket_lock(ticket_id):
            try:
                now = datetime.now().isoformat()
                ticket = self._to_ticket(ticket_data)

                ticket.stato = StatoTicket.RISOLTO.value
                ticket.data_chiusura = now
                ticket.data_aggiornamento = now
                ticket.risoluzione = risoluzione or "Ticket chiuso"

                self._add_audit_trail(ticket, admin_id=admin_id,
                                      change_type=ChangeType.CHIUSURA,
                                      details={"risoluzione": ticket.risoluzione})

                self._save_ticket(ticket)
                self._invalidate_stats_cache()

                logger.info(f"Ticket {ticket_id} chiuso da admin {admin_id}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(f"Errore nella chiusura del ticket {ticket_id}: {e}")
                raise TicketSystemError(f"Impossibile chiudere il ticket: {e}")

    def riapri_ticket(self, ticket_id: str, admin_id: str,
                     motivo: Optional[str] = None) -> Dict[str, Any]:
        """
        Riapre un ticket (lock per-ticket).
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        if ticket_data["stato"] not in [StatoTicket.CHIUSO.value,
                                        StatoTicket.RISOLTO.value]:
            raise InvalidStateError(
                f"Impossibile riaprire un ticket {ticket_data['stato']}")

        with self._get_ticket_lock(ticket_id):
            try:
                now = datetime.now().isoformat()
                ticket = self._to_ticket(ticket_data)

                ticket.stato = StatoTicket.RIAPERTO.value
                ticket.data_aggiornamento = now
                ticket.motivo_riapertura = motivo or "Richiesto dall'utente"

                self._add_audit_trail(ticket, admin_id=admin_id,
                                      change_type=ChangeType.RIAPERTURA,
                                      details={"motivo": ticket.motivo_riapertura})

                self._save_ticket(ticket)
                self._invalidate_stats_cache()

                logger.info(f"Ticket {ticket_id} riaperto da admin {admin_id}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(
                    f"Errore nella riapertura del ticket {ticket_id}: {e}")
                raise TicketSystemError(
                    f"Impossibile riaprire il ticket: {e}")

    # ==================== MODIFICA PRIORITÀ ====================

    def modifica_priorita(self, ticket_id: str,
                         nuova_priorità: str) -> Dict[str, Any]:
        """
        Modifica manualmente la priorità di un ticket (lock per-ticket).
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")

        priorità_valide = [p.value for p in PrioritaTicket]
        if nuova_priorità not in priorità_valide:
            raise TicketSystemError(
                f"Priorità non valida: {nuova_priorità}")

        with self._get_ticket_lock(ticket_id):
            try:
                ticket = self._to_ticket(ticket_data)
                vecchia_priorità = ticket.priorità
                ticket.priorità = nuova_priorità
                ticket.data_aggiornamento = datetime.now().isoformat()

                self._add_audit_trail(ticket, admin_id=None,
                                      change_type=ChangeType.PRIORITA,
                                      details={"da": vecchia_priorità,
                                               "a": nuova_priorità})

                self._save_ticket(ticket)
                logger.info(
                    f"Priorità ticket {ticket_id} modificata da {vecchia_priorità} a {nuova_priorità}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(
                    f"Errore nella modifica della priorità del ticket {ticket_id}: {e}")
                raise TicketSystemError(
                    f"Impossibile modificare la priorità: {e}")

    # ==================== OPERAZIONI BULK ====================

    def chiudi_massivo(self, ticket_ids: List[str], admin_id: str,
                      risoluzione: str = "Chiusura massiva") -> Dict[str, Any]:
        """
        Bulk operation atomica: chiude più ticket.
        Usa lock globale per garantire atomicità.
        """
        with self._global_lock:
            risultati = {"chiusi": [], "falliti": []}
            for tid in ticket_ids:
                try:
                    ticket_data = self.get_ticket(tid)
                    if not ticket_data:
                        risultati["falliti"].append({"id": tid, "errore": "non trovato"})
                        continue
                    if ticket_data["stato"] in [StatoTicket.CHIUSO.value, StatoTicket.RISOLTO.value]:
                        risultati["falliti"].append({"id": tid, "errore": "già chiuso"})
                        continue

                    ticket = self._to_ticket(ticket_data)
                    now = datetime.now().isoformat()
                    ticket.stato = StatoTicket.RISOLTO.value
                    ticket.data_chiusura = now
                    ticket.data_aggiornamento = now
                    ticket.risoluzione = risoluzione

                    self._add_audit_trail(ticket, admin_id=admin_id,
                                          change_type=ChangeType.CHIUSURA,
                                          details={"bulk": True, "risoluzione": risoluzione})

                    self._save_ticket(ticket)
                    risultati["chiusi"].append(tid)
                    logger.info(f"Ticket {tid} chiuso (bulk) da admin {admin_id}")
                except Exception as e:
                    logger.error(f"Errore chiusura bulk ticket {tid}: {e}")
                    risultati["falliti"].append({"id": tid, "errore": str(e)})

            if risultati["chiusi"]:
                self._invalidate_stats_cache()

            return risultati

    # ==================== SOFT-DELETE ====================

    def elimina_ticket_soft(self, ticket_id: str, admin_id: str) -> Dict[str, Any]:
        """
        Soft-delete di un ticket invece di rimozione fisica.
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")

        with self._get_ticket_lock(ticket_id):
            try:
                ticket = self._to_ticket(ticket_data)
                ticket.eliminato = True
                ticket.stato = StatoTicket.CHIUSO.value
                ticket.data_aggiornamento = datetime.now().isoformat()

                self._add_audit_trail(ticket, admin_id=admin_id,
                                      change_type=ChangeType.ELIMINAZIONE,
                                      details={"soft_delete": True})

                self._save_ticket(ticket)
                self._invalidate_stats_cache()

                logger.info(f"Ticket {ticket_id} soft-deleted da admin {admin_id}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(f"Errore soft-delete ticket {ticket_id}: {e}")
                raise TicketSystemError(f"Impossibile eliminare il ticket: {e}")

    def ripristina_ticket(self, ticket_id: str, admin_id: str) -> Dict[str, Any]:
        """
        Ripristina un ticket soft-delete.
        """
        ticket_data = self.get_ticket(ticket_id)
        if not ticket_data:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")

        with self._get_ticket_lock(ticket_id):
            try:
                ticket = self._to_ticket(ticket_data)
                if not ticket.eliminato:
                    raise InvalidStateError("Il ticket non è stato eliminato")

                ticket.eliminato = False
                ticket.stato = StatoTicket.RISOLTO.value
                ticket.data_aggiornamento = datetime.now().isoformat()

                self._add_audit_trail(ticket, admin_id=admin_id,
                                      change_type=ChangeType.RIPRISTINO,
                                      details={"soft_delete_undo": True})

                self._save_ticket(ticket)

                logger.info(f"Ticket {ticket_id} ripristinato da admin {admin_id}")
                return ticket.to_dict()

            except Exception as e:
                logger.error(f"Errore ripristino ticket {ticket_id}: {e}")
                raise TicketSystemError(f"Impossibile ripristinare il ticket: {e}")

    # ==================== SUGGERIMENTI FAQ ====================

    def suggerisci_faq(self, problema: str) -> List[Dict[str, Any]]:
        """
        Suggerisce FAQ rilevanti basandosi sul problema descritto.
        """
        problema_lower = problema.lower()
        risultati = []

        for faq in FAQ_BASE:
            punteggio = 0

            for domanda in faq.get("domande", []):
                if domanda.lower() in problema_lower:
                    punteggio += 30
                parole_domanda = domanda.lower().split()
                for parola in parole_domanda:
                    if len(parola) > 3 and parola in problema_lower:
                        punteggio += 5

            if punteggio > 0:
                risultati.append({"faq": faq, "punteggio": punteggio})

        risultati.sort(key=lambda x: x["punteggio"], reverse=True)
        return risultati[:3]

    def verifica_e_suggerisci(self, problema: str) -> Dict[str, Any]:
        """
        Verifica se esistono suggerimenti e restituisce un messaggio completo.
        """
        faq_rilevanti = self.suggerisci_faq(problema)

        if faq_rilevanti:
            messaggio = "Ho trovato alcune FAQ che potrebbero aiutarti:\n\n"
            for i, item in enumerate(faq_rilevanti, 1):
                faq = item["faq"]
                messaggio += f"{i}. *{faq['risposta']}*\n\n"
            messaggio += "Vuoi comunque aprire un ticket di supporto?"

            return {
                "suggerimenti_disponibili": True,
                "messaggio": messaggio,
                "faq": faq_rilevanti
            }

        return {
            "suggerimenti_disponibili": False,
            "messaggio": None,
            "faq": []
        }

    # ==================== STATISTICHE (con cache TTL 60s) ====================

    def get_statistiche(self) -> Dict[str, Any]:
        """
        2.3 - Cache statistiche con TTL 60s.
        Invalida on ticket change.
        """
        now_ts = datetime.now().timestamp()

        # Cache hit se valida
        if self._stats_cache is not None and \
           (now_ts - self._stats_timestamp) < STATS_CACHE_TTL:
            logger.debug("Cache statistiche HIT")
            return dict(self._stats_cache)

        with self._global_lock:
            try:
                ticket_data = self.persistence.get_data("ticket") or {}

                statistiche = {
                    "totale": 0,
                    "aperti": 0, "in_lavorazione": 0, "risolti": 0, "chiusi": 0, "riaperti": 0,
                    "priorità_alta": 0, "priorità_media": 0, "priorità_bassa": 0,
                    "ticket_oggi": 0, "ticket_questa_settimana": 0,
                    "per_categoria": {},
                    "per_utente": {},
                    "ticket_eliminati": 0
                }

                oggi = datetime.now().date()
                inizio_settimana = oggi - timedelta(days=oggi.weekday())

                for tdata in ticket_data.values():
                    eliminato = tdata.get('eliminato', False)
                    if eliminato:
                        statistiche["ticket_eliminati"] += 1
                        continue

                    stato = tdata.get("stato", "")
                    priorità = tdata.get("priorità", "")
                    categoria = tdata.get("categoria", "altro")
                    user_id = tdata.get("user_id", "")

                    statistiche["totale"] += 1

                    if stato == StatoTicket.APERTO.value:
                        statistiche["aperti"] += 1
                    elif stato == StatoTicket.IN_LAVORAZIONE.value:
                        statistiche["in_lavorazione"] += 1
                    elif stato == StatoTicket.RISOLTO.value:
                        statistiche["risolti"] += 1
                    elif stato == StatoTicket.CHIUSO.value:
                        statistiche["chiusi"] += 1
                    elif stato == StatoTicket.RIAPERTO.value:
                        statistiche["riaperti"] += 1

                    if priorità == PrioritaTicket.ALTA.value:
                        statistiche["priorità_alta"] += 1
                    elif priorità == PrioritaTicket.MEDIA.value:
                        statistiche["priorità_media"] += 1
                    elif priorità == PrioritaTicket.BASSA.value:
                        statistiche["priorità_bassa"] += 1

                    statistiche["per_categoria"][categoria] = \
                        statistiche["per_categoria"].get(categoria, 0) + 1
                    if user_id:
                        statistiche["per_utente"][user_id] = \
                            statistiche["per_utente"].get(user_id, 0) + 1

                    try:
                        d = tdata.get("data_creazione", "")
                        if d:
                            data_cr = datetime.fromisoformat(d.split('.')[0])
                            if data_cr.date() == oggi:
                                statistiche["ticket_oggi"] += 1
                            if data_cr.date() >= inizio_settimana:
                                statistiche["ticket_questa_settimana"] += 1
                    except Exception:
                        pass

                self._stats_cache = dict(statistiche)
                self._stats_timestamp = now_ts
                logger.debug("Cache statistiche calcolata e aggiornata")
                return statistiche

            except Exception as e:
                logger.error(f"Errore nel calcolo delle statistiche: {e}")
                return {}

    # ==================== NOTIFICHE ====================

    def notifica_risposta(self, ticket_id: str) -> Dict[str, Any]:
        """Prepara i dati per la notifica di risposta al ticket."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return {}

        return {
            "ticket_id": ticket_id,
            "user_id": ticket.get("user_id"),
            "stato": ticket.get("stato"),
            "priorità": ticket.get("priorità"),
            "ultima_risposta": ticket.get("risposte", [])[-1] if ticket.get("risposte") else None
        }

    def notifica_chiusura(self, ticket_id: str) -> Dict[str, Any]:
        """Prepara i dati per la notifica di chiusura del ticket."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return {}

        return {
            "ticket_id": ticket_id,
            "user_id": ticket.get("user_id"),
            "stato": ticket.get("stato"),
            "risoluzione": ticket.get("risoluzione"),
            "data_chiusura": ticket.get("data_chiusura")
        }

    # ==================== UTILITY DIAGNOSTICA ====================

    def get_index_stats(self) -> Dict[str, Any]:
        """Info di debug sull'indice."""
        with self._index_lock:
            return {
                "index_initialized": self._index_initialized,
                "users_count": len(self._user_ticket_index),
                "total_indexed_tickets": sum(len(v) for v in self._user_ticket_index.values())
            }

    def get_lock_stats(self) -> Dict[str, Any]:
        """Info di debug sui lock."""
        with self._global_lock:
            return {
                "global_lock_acquired": self._global_lock._is_owned(),
                "ticket_locks_count": len(self._ticket_locks)
            }


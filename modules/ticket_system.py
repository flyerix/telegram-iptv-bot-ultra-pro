"""
Modulo per il sistema ticket di supporto con priorità automatica.
Gestisce creazione, gestione e risoluzione dei ticket di supporto.

Utilizza il modulo di persistenza per salvare i dati su file JSON.
"""

import uuid
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)


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
GIORNI_FESTIVI = [5, 6]      # Sabato (5) e Domenica (6) in Python (0=Lunedì)

# Giorni di scadenza per attivare priorità alta
GIORNI_SCADENZA_ALLERTA = 3

# Numero di ticket recenti per abbassare priorità
TICKET_RECENTI_SOGLIA = 3
GIORNI_TICKET_RECENTI = 7


# ==================== FAQ ====================

FAQ_BASE = [
    {
        "id": "faq_001",
        "categoria": "connessione",
        "domande": [
            "non si connette", "non connect", "errore connessione",
            "impossibile connettersi", "connessione rifiutata"
        ],
        "risposta": "Prova questi passaggi:\n1. Verifica la tua connessione internet\n2. Riavvia il router\n3. Prova un altro dispositivo\n4. Controlla se il server è online"
    },
    {
        "id": "faq_002",
        "categoria": "streaming",
        "domande": [
            "buffer", "lento", "si blocca", "interrotto", "caricamento"
        ],
        "risposta": "Per problemi di streaming:\n1. Riduci la qualità video\n2. Prova un altro canale\n3. Riavvia l'app\n4. Controlla la tua velocità internet (minimo 10Mbps)"
    },
    {
        "id": "faq_003",
        "categoria": "account",
        "domande": [
            "account", "login", "password", "accesso", "non riesco ad entrare"
        ],
        "risposta": "Per problemi di account:\n1. Controlla le credenziali\n2. Resetta la password\n3. Verifica che l'account sia attivo\n4. Contatta per supporto"
    },
    {
        "id": "faq_004",
        "categoria": "streaming",
        "domande": [
            "nessun canale", "zero canali", "canali non funzionano", "lista vuota"
        ],
        "risposta": "Per problemi con i canali:\n1. Aggiorna la lista M3U\n2. Verifica l'abbonamento attivo\n3. Prova a reinstallare l'app\n4. Controlla lo stato del servizio"
    },
    {
        "id": "faq_005",
        "categoria": "pagamento",
        "domande": [
            "pagamento", "rinnovo", "scadenza", "abbonamento", "renew"
        ],
        "risposta": "Per problemi di pagamento:\n1. Controlla la data di scadenza\n2. Verifica il metodo di pagamento\n3. Richiedi il rinnovo\n4. Contatta per assistenza pagamenti"
    }
]


# ==================== ECCEZIONI ====================

class TicketSystemError(Exception):
    """Eccezione personalizzata per errori nel sistema ticket."""
    pass


class TicketNotFoundError(TicketSystemError):
    """Eccezione per ticket non trovato."""
    pass


class InvalidStateError(TicketSystemError):
    """Eccezione per stato non valido."""
    pass


# ==================== CLASE PRINCIPALE ====================

class TicketSystem:
    """
    Sistema di gestione ticket di supporto con priorità automatica.
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
        logger.info("Modulo TicketSystem inizializzato")
    
    # ==================== CREAZIONE TICKET ====================
    
    def crea_ticket(self, user_id: str, problema: str, categoria: str = "altro") -> Dict[str, Any]:
        """
        Crea un nuovo ticket di supporto con priorità automatica.
        
        Args:
            user_id: ID dell'utente che crea il ticket
            problema: Descrizione del problema
            categoria: Categoria del problema
            
        Returns:
            Dizionario con i dati del ticket creato
            
        Raises:
            TicketSystemError: Se la creazione del ticket fallisce
        """
        try:
            # Valida la categoria
            categoria_valida = self._valida_categoria(categoria)
            
            # Genera ID univoco
            ticket_id = self._genera_id_ticket()
            
            # Assegna priorità automatica
            priorità = self.assegna_priorita_automatica(user_id, problema, categoria_valida)
            
            # Determina lo stato iniziale
            stato = StatoTicket.APERTO.value
            
            # Crea il ticket
            now = datetime.now().isoformat()
            nuovo_ticket = {
                "id": ticket_id,
                "user_id": user_id,
                "problema": problema,
                "categoria": categoria_valida,
                "priorità": priorità,
                "stato": stato,
                "data_creazione": now,
                "data_aggiornamento": now,
                "data_risposta": None,
                "data_chiusura": None,
                "risposte": [],
                "admin_assegnato": None,
                "tags": self._estrai_tags(problema)
            }
            
            # Salva il ticket
            self.persistence.update_data(f"ticket.{ticket_id}", nuovo_ticket)
            
            logger.info(f"Ticket {ticket_id} creato da utente {user_id} con priorità {priorità}")
            
            return nuovo_ticket
            
        except Exception as e:
            logger.error(f"Errore nella creazione del ticket per utente {user_id}: {e}")
            raise TicketSystemError(f"Impossibile creare il ticket: {e}")
    
    def _genera_id_ticket(self) -> str:
        """Genera un ID univoco per il ticket."""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    def _valida_categoria(self, categoria: str) -> str:
        """Valida e normalizza la categoria."""
        categoria = categoria.lower().strip()
        categorie_valide = [c.value for c in CategoriaTicket]
        
        if categoria in categorie_valide:
            return categoria
        
        # Prova a trovare una corrispondenza
        for cat in CategoriaTicket:
            if categoria in cat.value:
                return cat.value
        
        return CategoriaTicket.ALTRO.value
    
    def _estrai_tags(self, problema: str) -> List[str]:
        """Estrae tag rilevanti dal problema."""
        tags = []
        problema_lower = problema.lower()
        
        # Estrai parole chiave
        for parola in PAROLE_CHIAVE_ALTA_PRIORITA:
            if parola in problema_lower:
                tags.append("urgente")
                break
        
        # Estrai tecnologie
        tecnologie = ["m3u", "m3u8", "xtream", "kodi", "plex", "smarttv", "firestick"]
        for tech in tecnologie:
            if tech in problema_lower:
                tags.append(tech)
        
        return list(set(tags))
    
    # ==================== PRIORITÀ AUTOMATICA ====================
    
    def assegna_priorita_automatica(self, user_id: str, problema: str, 
                                     categoria: str) -> str:
        """
        Assegna priorità automaticamente basandosi su più fattori.
        
        Args:
            user_id: ID dell'utente
            problema: Descrizione del problema
            categoria: Categoria del problema
            
        Returns:
            Priorità assegnata (alta, media, bassa)
        """
        punteggio = 0
        
        # 1. Parole chiave nel messaggio
        punteggio += self._calcola_punteggio_parole_chiave(problema)
        
        # 2. Stato dell'utente (VIP)
        if self._è_utente_vip(user_id):
            punteggio += 20
            logger.debug(f"Utente {user_id} è VIP, +20 punti priorità")
        
        # 3. Lista in scadenza
        if self._lista_in_scadenza(user_id):
            punteggio += 25
            logger.debug(f"Utente {user_id} ha lista in scadenza, +25 punti priorità")
        
        # 4. Frequenza ticket recenti
        punteggio_frequenza = self._calcola_punteggio_frequenza(user_id)
        punteggio += punteggio_frequenza
        
        # 5. Orario di apertura
        if self._è_orario_notturno_o_festivo():
            punteggio += 15
            logger.debug("Orario notturno/festivo, +15 punti priorità")
        
        # 6. Categoria
        punteggio += self._calcola_punteggio_categoria(categoria)
        
        # Determina priorità finale
        if punteggio >= 50:
            priorità = PrioritaTicket.ALTA.value
        elif punteggio >= 20:
            priorità = PrioritaTicket.MEDIA.value
        else:
            priorità = PrioritaTicket.BASSA.value
        
        logger.info(f"Priorità calcolata per utente {user_id}: {priorità} (punteggio: {punteggio})")
        return priorità
    
    def _calcola_punteggio_parole_chiave(self, problema: str) -> float:
        """Calcola il punteggio basato sulle parole chiave."""
        punteggio = 0
        problema_lower = problema.lower()
        
        # Parole alta priorità
        for parola in PAROLE_CHIAVE_ALTA_PRIORITA:
            if parola in problema_lower:
                punteggio += 30
                break
        
        # Parole media priorità
        for parola in PAROLE_CHIAVE_MEDIA_PRIORITA:
            if parola in problema_lower:
                punteggio += 10
                break
        
        # Parole bassa priorità
        for parola in PAROLE_CHIAVE_BASSA_PRIORITA:
            if parola in problema_lower:
                punteggio -= 15
                break
        
        return punteggio
    
    def _è_utente_vip(self, user_id: str) -> bool:
        """Verifica se l'utente è VIP."""
        try:
            if self.user_management:
                utente = self.user_management.get_utente(user_id)
                if utente:
                    return utente.get("is_vip", False) or utente.get("vip", False)
            return False
        except Exception:
            return False
    
    def _lista_in_scadenza(self, user_id: str) -> bool:
        """Verifica se la lista dell'utente sta per scadere."""
        try:
            if self.user_management:
                utente = self.user_management.get_utente(user_id)
                if utente and utente.get("data_scadenza"):
                    scadenza = datetime.fromisoformat(utente["data_scadenza"])
                    giorni_rimanenti = (scadenza - datetime.now()).days
                    return giorni_rimanenti <= GIORNI_SCADENZA_ALLERTA and giorni_rimanenti >= 0
            return False
        except Exception:
            return False
    
    def _calcola_punteggio_frequenza(self, user_id: str) -> float:
        """Calcola il punteggio basato sulla frequenza di ticket recenti."""
        try:
            ticket = self.persistence.get_data("ticket") or {}
            ticket_utente = [
                t for t in ticket.values()
                if t.get("user_id") == user_id
                and datetime.fromisoformat(t.get("data_creazione", "2000-01-01")) 
                   > datetime.now() - timedelta(days=GIORNI_TICKET_RECENTI)
            ]
            
            num_ticket = len(ticket_utente)
            
            if num_ticket >= TICKET_RECENTI_SOGLIA:
                return -20  # Abbassa priorità
            elif num_ticket >= 1:
                return -5  # Leggera riduzione
            
            return 0
        except Exception:
            return 0
    
    def _è_orario_notturno_o_festivo(self) -> bool:
        """Verifica se è orario notturno o festivo."""
        now = datetime.now()
        
        # Controlla orario notturno
        if now.hour >= ORARIO_NOTTURNO_INIZIO or now.hour < ORARIO_NOTTURNO_FINE:
            return True
        
        # Controlla weekend (5=Sabato, 6=Domenica in Python)
        if now.weekday() in GIORNI_FESTIVI:
            return True
        
        return False
    
    def _calcola_punteggio_categoria(self, categoria: str) -> float:
        """Calcola il punteggio basato sulla categoria."""
        categorie_alte = ["connessione", "account", "pagamento"]
        categorie_medie = ["streaming", "tecnico"]
        
        if categoria in categorie_alte:
            return 15
        elif categoria in categorie_medie:
            return 5
        
        return 0
    
    # ==================== GESTIONE TICKET ====================
    
    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene i dati di un ticket.
        
        Args:
            ticket_id: ID del ticket
            
        Returns:
            Dizionario con i dati del ticket o None se non trovato
        """
        try:
            ticket = self.persistence.get_data(f"ticket.{ticket_id}")
            return ticket if ticket else None
        except Exception as e:
            logger.error(f"Errore nel recupero del ticket {ticket_id}: {e}")
            return None
    
    def get_ticket_utente(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Ottiene tutti i ticket di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Lista di ticket dell'utente
        """
        try:
            ticket = self.persistence.get_data("ticket") or {}
            ticket_utente = [
                t for t in ticket.values()
                if t.get("user_id") == user_id
            ]
            # Ordina per data creazione decrescente
            ticket_utente.sort(
                key=lambda x: x.get("data_creazione", ""), 
                reverse=True
            )
            return ticket_utente
        except Exception as e:
            logger.error(f"Errore nel recupero dei ticket per utente {user_id}: {e}")
            return []
    
    def get_tutti_ticket(self, stato: Optional[str] = None, 
                        priorità: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Ottiene tutti i ticket con filtri opzionali.
        
        Args:
            stato: Filtro per stato (opzionale)
            priorità: Filtro per priorità (opzionale)
            
        Returns:
            Lista di ticket filtrati
        """
        try:
            ticket = self.persistence.get_data("ticket") or {}
            risultato = list(ticket.values())
            
            if stato:
                risultato = [t for t in risultato if t.get("stato") == stato]
            
            if priorità:
                risultato = [t for t in risultato if t.get("priorità") == priorità]
            
            # Ordina per priorità e data
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
    
    # ==================== RISPOSTE ====================
    
    def rispondi_ticket(self, ticket_id: str, admin_id: str, risposta: str) -> Dict[str, Any]:
        """
        Aggiunge una risposta a un ticket.
        
        Args:
            ticket_id: ID del ticket
            admin_id: ID dell'admin che risponde
            risposta: Testo della risposta
            
        Returns:
            Dizionario con i dati aggiornati del ticket
            
        Raises:
            TicketNotFoundError: Se il ticket non esiste
            InvalidStateError: Se il ticket è già chiuso
        """
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        
        if ticket["stato"] in [StatoTicket.CHIUSO.value, StatoTicket.RISOLTO.value]:
            raise InvalidStateError(f"Impossibile rispondere a un ticket {ticket['stato']}")
        
        try:
            now = datetime.now().isoformat()
            
            nuova_risposta = {
                "admin_id": admin_id,
                "risposta": risposta,
                "data_risposta": now
            }
            
            risposte = ticket.get("risposte", [])
            risposte.append(nuova_risposta)
            
            # Aggiorna il ticket
            ticket["risposte"] = risposte
            ticket["data_risposta"] = now
            ticket["data_aggiornamento"] = now
            
            # Se era aperto, passa in lavorazione
            if ticket["stato"] == StatoTicket.APERTO.value:
                ticket["stato"] = StatoTicket.IN_LAVORAZIONE.value
            
            ticket["admin_assegnato"] = admin_id
            
            self.persistence.update_data(f"ticket.{ticket_id}", ticket)
            
            logger.info(f"Risposta aggiunta al ticket {ticket_id} da admin {admin_id}")
            
            return ticket
            
        except Exception as e:
            logger.error(f"Errore nella risposta al ticket {ticket_id}: {e}")
            raise TicketSystemError(f"Impossibile rispondere al ticket: {e}")
    
    # ==================== CHIUSURA E RIAPERTURA ====================
    
    def chiudi_ticket(self, ticket_id: str, admin_id: str, 
                     risoluzione: Optional[str] = None) -> Dict[str, Any]:
        """
        Chiude un ticket.
        
        Args:
            ticket_id: ID del ticket
            admin_id: ID dell'admin che chiude il ticket
            risoluzione: Descrizione della risoluzione (opzionale)
            
        Returns:
            Dizionario con i dati aggiornati del ticket
            
        Raises:
            TicketNotFoundError: Se il ticket non esiste
        """
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        
        try:
            now = datetime.now().isoformat()
            
            ticket["stato"] = StatoTicket.RISOLTO.value
            ticket["data_chiusura"] = now
            ticket["data_aggiornamento"] = now
            ticket["risoluzione"] = risoluzione or "Ticket chiuso"
            
            self.persistence.update_data(f"ticket.{ticket_id}", ticket)
            
            logger.info(f"Ticket {ticket_id} chiuso da admin {admin_id}")
            
            return ticket
            
        except Exception as e:
            logger.error(f"Errore nella chiusura del ticket {ticket_id}: {e}")
            raise TicketSystemError(f"Impossibile chiudere il ticket: {e}")
    
    def riapri_ticket(self, ticket_id: str, admin_id: str, 
                     motivo: Optional[str] = None) -> Dict[str, Any]:
        """
        Riapre un ticket chiuso.
        
        Args:
            ticket_id: ID del ticket
            admin_id: ID dell'admin che riapre il ticket
            motivo: Motivo della riapertura (opzionale)
            
        Returns:
            Dizionario con i dati aggiornati del ticket
            
        Raises:
            TicketNotFoundError: Se il ticket non esiste
            InvalidStateError: Se il ticket non è chiuso
        """
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        
        if ticket["stato"] not in [StatoTicket.CHIUSO.value, StatoTicket.RISOLTO.value]:
            raise InvalidStateError(f"Impossibile riaprire un ticket {ticket['stato']}")
        
        try:
            now = datetime.now().isoformat()
            
            ticket["stato"] = StatoTicket.RIAPERTO.value
            ticket["data_aggiornamento"] = now
            ticket["motivo_riapertura"] = motivo or "Richiesto dall'utente"
            
            self.persistence.update_data(f"ticket.{ticket_id}", ticket)
            
            logger.info(f"Ticket {ticket_id} riaperto da admin {admin_id}")
            
            return ticket
            
        except Exception as e:
            logger.error(f"Errore nella riapertura del ticket {ticket_id}: {e}")
            raise TicketSystemError(f"Impossibile riaprire il ticket: {e}")
    
    # ==================== MODIFICA PRIORITÀ ====================
    
    def modifica_priorita(self, ticket_id: str, nuova_priorità: str) -> Dict[str, Any]:
        """
        Modifica manualmente la priorità di un ticket.
        
        Args:
            ticket_id: ID del ticket
            nuova_priorità: Nuova priorità (alta, media, bassa)
            
        Returns:
            Dizionario con i dati aggiornati del ticket
            
        Raises:
            TicketNotFoundError: Se il ticket non esiste
            TicketSystemError: Se la priorità non è valida
        """
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {ticket_id} non trovato")
        
        priorità_valide = [p.value for p in PrioritaTicket]
        if nuova_priorità not in priorità_valide:
            raise TicketSystemError(f"Priorità non valida: {nuova_priorità}")
        
        try:
            vecchia_priorità = ticket.get("priorità")
            ticket["priorità"] = nuova_priorità
            ticket["data_aggiornamento"] = datetime.now().isoformat()
            
            self.persistence.update_data(f"ticket.{ticket_id}", ticket)
            
            logger.info(f"Priorità ticket {ticket_id} modificata da {vecchia_priorità} a {nuova_priorità}")
            
            return ticket
            
        except Exception as e:
            logger.error(f"Errore nella modifica della priorità del ticket {ticket_id}: {e}")
            raise TicketSystemError(f"Impossibile modificare la priorità: {e}")
    
    # ==================== SUGGERIMENTI FAQ ====================
    
    def suggerisci_faq(self, problema: str) -> List[Dict[str, Any]]:
        """
        Suggerisce FAQ rilevanti basandosi sul problema descritto.
        
        Args:
            problema: Descrizione del problema dell'utente
            
        Returns:
            Lista di FAQ rilevanti con punteggio di rilevanza
        """
        problema_lower = problema.lower()
        risultati = []
        
        for faq in FAQ_BASE:
            punteggio = 0
            
            # Controlla corrispondenze con le domande della FAQ
            for domanda in faq.get("domande", []):
                if domanda.lower() in problema_lower:
                    punteggio += 30
                # Controlla parole parziali
                parole_domanda = domanda.lower().split()
                for parola in parole_domanda:
                    if len(parola) > 3 and parola in problema_lower:
                        punteggio += 5
            
            if punteggio > 0:
                risultati.append({
                    "faq": faq,
                    "punteggio": punteggio
                })
        
        # Ordina per punteggio decrescente
        risultati.sort(key=lambda x: x["punteggio"], reverse=True)
        
        # Limita a 3 risultati
        return risultati[:3]
    
    def verifica_e_suggerisci(self, problema: str) -> Dict[str, Any]:
        """
        Verifica se esistono suggerimenti e restituisce un messaggio completo.
        
        Args:
            problema: Descrizione del problema
            
        Returns:
            Dizionario con suggerimenti e messaggio
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
    
    # ==================== STATISTICHE ====================
    
    def get_statistiche(self) -> Dict[str, Any]:
        """
        Ottiene statistiche sui ticket.
        
        Returns:
            Dizionario con le statistiche
        """
        try:
            ticket = self.persistence.get_data("ticket") or {}
            
            statistiche = {
                "totale": len(ticket),
                "aperti": 0,
                "in_lavorazione": 0,
                "risolti": 0,
                "chiusi": 0,
                "riaperti": 0,
                "priorità_alta": 0,
                "priorità_media": 0,
                "priorità_bassa": 0,
                "ticket_oggi": 0,
                "ticket_questa_settimana": 0
            }
            
            oggi = datetime.now().date()
            inizio_settimana = oggi - timedelta(days=oggi.weekday())
            
            for t in ticket.values():
                # Conta stati
                stato = t.get("stato", "")
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
                
                # Conta priorità
                priorità = t.get("priorità", "")
                if priorità == PrioritaTicket.ALTA.value:
                    statistiche["priorità_alta"] += 1
                elif priorità == PrioritaTicket.MEDIA.value:
                    statistiche["priorità_media"] += 1
                elif priorità == PrioritaTicket.BASSA.value:
                    statistiche["priorità_bassa"] += 1
                
                # Conta per data
                try:
                    data_creazione = datetime.fromisoformat(t.get("data_creazione", ""))
                    if data_creazione.date() == oggi:
                        statistiche["ticket_oggi"] += 1
                    if data_creazione.date() >= inizio_settimana:
                        statistiche["ticket_questa_settimana"] += 1
                except Exception:
                    pass
            
            return statistiche
            
        except Exception as e:
            logger.error(f"Errore nel calcolo delle statistiche: {e}")
            return {}
    
    # ==================== GESTIONE NOTIFICHE ====================
    
    def notifica_risposta(self, ticket_id: str) -> Dict[str, Any]:
        """
        Prepara i dati per la notifica di risposta al ticket.
        
        Args:
            ticket_id: ID del ticket
            
        Returns:
            Dizionario con i dati per la notifica
        """
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
        """
        Prepara i dati per la notifica di chiusura del ticket.
        
        Args:
            ticket_id: ID del ticket
            
        Returns:
            Dizionario con i dati per la notifica
        """
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

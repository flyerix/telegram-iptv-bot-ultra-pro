"""
Modulo di rate limiting anti-spam per HelperBot.
Gestisce limiti di utilizzo, blacklist e whitelist per prevenire abusi.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

# Configurazione del logger
logger = logging.getLogger(__name__)


class TipoLimite(Enum):
    """Tipi di limiti supportati."""
    COMANDO = "comando"
    TICKET = "ticket"


@dataclass
class LimiteConfig:
    """Configurazione per un tipo di limite."""
    max_count: int  # Numero massimo di azioni
    finestra_tempo: timedelta  # Finestra temporale per il limite


@dataclass
class Violazione:
    """Rappresenta una violazione del rate limit."""
    tipo: str
    timestamp: str
    motivo: str
    durata_blacklist_minuti: int = 0


@dataclass
class UtenteRateLimit:
    """Dati di rate limiting per un utente."""
    # Contatori comandi
    contatore_comandi: int = 0
    timestamp_primo_comando: Optional[str] = None
    timestamp_ultimo_comando: Optional[str] = None
    
    # Contatori ticket
    contatore_ticket: int = 0
    timestamp_primo_ticket: Optional[str] = None
    timestamp_ultimo_ticket: Optional[str] = None
    
    # Blacklist
    blacklist: bool = False
    blacklist_fine: Optional[str] = None
    blacklist_motivo: Optional[str] = None
    
    # Whitelist
    whitelist: bool = False
    
    # Violazioni
    violazioni: List[Dict[str, Any]] = field(default_factory=list)
    
    # Cooldown
    in_cooldown: bool = False
    cooldown_fine: Optional[str] = None


class RateLimiter:
    """
    Classe principale per la gestione del rate limiting anti-spam.
    Implementa limiti configurabili, blacklist/whitelist e tracking delle violazioni.
    """
    
    # Configurazione predefinita dei limiti
    DEFAULT_LIMITS: Dict[TipoLimite, LimiteConfig] = {
        TipoLimite.COMANDO: LimiteConfig(
            max_count=5,
            finestra_tempo=timedelta(minutes=1)
        ),
        TipoLimite.TICKET: LimiteConfig(
            max_count=2,
            finestra_tempo=timedelta(hours=1)
        )
    }
    
    # Durata default della blacklist in minuti
    DEFAULT_BLACKLIST_DURATION = 30
    
    # Durata del cooldown dopo superamento limiti
    COOLDOWN_DURATION = timedelta(minutes=5)
    
    # Tempo di retention dei dati vecchi (7 giorni)
    DATA_RETENTION_DAYS = 7
    
    def __init__(self, persistence, custom_limits: Optional[Dict[TipoLimite, LimiteConfig]] = None,
                 blacklist_default_duration: int = DEFAULT_BLACKLIST_DURATION):
        """
        Inizializza il rate limiter.
        
        Args:
            persistence: Istanza di DataPersistence per la memorizzazione
            custom_limits: Dizionario custom di limiti (opzionale)
            blacklist_default_duration: Durata default della blacklist in minuti
        """
        self.persistence = persistence
        self.limiti = custom_limits if custom_limits else self.DEFAULT_LIMITS.copy()
        self.blacklist_default_duration = blacklist_default_duration
        
        # Inizializza la struttura dati se non esiste
        self._init_data_structure()
        
        logger.info("RateLimiter inizializzato con successo")
    
    def _init_data_structure(self) -> None:
        """Inizializza la struttura dati per il rate limiting."""
        rate_limits_data = self.persistence.get_data("rate_limits")
        if rate_limits_data is None:
            self.persistence.update_data("rate_limits", {})
            logger.info("Struttura rate_limits inizializzata")
    
    def _get_utente_data(self, user_id: str) -> UtenteRateLimit:
        """Ottiene i dati di rate limiting per un utente."""
        data = self.persistence.get_data(f"rate_limits.{user_id}")
        if data is None:
            return UtenteRateLimit()
        return UtenteRateLimit(**data)
    
    def _save_utente_data(self, user_id: str, data: UtenteRateLimit) -> None:
        """Salva i dati di rate limiting per un utente."""
        # Converti in dict, gestendo campi opzionali
        data_dict = {
            "contatore_comandi": data.contatore_comandi,
            "timestamp_primo_comando": data.timestamp_primo_comando,
            "timestamp_ultimo_comando": data.timestamp_ultimo_comando,
            "contatore_ticket": data.contatore_ticket,
            "timestamp_primo_ticket": data.timestamp_primo_ticket,
            "timestamp_ultimo_ticket": data.timestamp_ultimo_ticket,
            "blacklist": data.blacklist,
            "blacklist_fine": data.blacklist_fine,
            "blacklist_motivo": data.blacklist_motivo,
            "whitelist": data.whitelist,
            "violazioni": data.violazioni,
            "in_cooldown": data.in_cooldown,
            "cooldown_fine": data.cooldown_fine
        }
        self.persistence.update_data(f"rate_limits.{user_id}", data_dict)
    
    def _get_timestamp(self) -> str:
        """Ottiene il timestamp corrente in formato ISO."""
        return datetime.now().isoformat()
    
    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Converte una stringa timestamp in datetime."""
        if ts_str is None:
            return None
        try:
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None
    
    def _is_within_time_window(self, timestamp: Optional[str], finestra: timedelta) -> bool:
        """Verifica se un timestamp è entro la finestra temporale specificata."""
        if timestamp is None:
            return False
        
        ts = self._parse_timestamp(timestamp)
        if ts is None:
            return False
        
        return datetime.now() - ts <= finestra
    
    def _check_and_reset_counters(self, user_data: UtenteRateLimit, tipo: TipoLimite) -> None:
        """Controlla e resetta i contatori se la finestra temporale è scaduta."""
        config = self.limiti.get(tipo)
        if config is None:
            return
        
        if tipo == TipoLimite.COMANDO:
            if user_data.timestamp_primo_comando:
                if not self._is_within_time_window(user_data.timestamp_primo_comando, config.finestra_tempo):
                    user_data.contatore_comandi = 0
                    user_data.timestamp_primo_comando = None
                    user_data.timestamp_ultimo_comando = None
        
        elif tipo == TipoLimite.TICKET:
            if user_data.timestamp_primo_ticket:
                if not self._is_within_time_window(user_data.timestamp_primo_ticket, config.finestra_tempo):
                    user_data.contatore_ticket = 0
                    user_data.timestamp_primo_ticket = None
                    user_data.timestamp_ultimo_ticket = None
    
    def check_rate_limit(self, user_id: str, tipo: str) -> Tuple[bool, str, Optional[int]]:
        """
        Verifica se un utente può eseguire un'azione.
        
        Args:
            user_id: ID dell'utente
            tipo: Tipo di azione ("comando" o "ticket")
            
        Returns:
            Tuple (bool, messaggio, minuti_blocco_rimanenti)
            - bool: True se l'azione è consentita
            - messaggio: Spiegazione del risultato
            - minuti_blocco_rimanenti: Minuti rimanenti se bloccato, None altrimenti
        """
        # Verifica whitelist (utenti VIP/admin hanno sempre accesso)
        if self.is_whitelisted(user_id):
            return True, "Whitelist: accesso consentito", None
        
        # Verifica blacklist
        if self.is_blacklisted(user_id):
            user_data = self._get_utente_data(user_id)
            if user_data.blacklist_fine:
                fine = self._parse_timestamp(user_data.blacklist_fine)
                if fine:
                    remaining = (fine - datetime.now()).total_seconds() / 60
                    if remaining > 0:
                        return False, f"Blacklist attiva: {user_data.blacklist_motivo}", int(remaining + 1)
                    else:
                        # Blacklist scaduta, rimuovila
                        self.rimuovi_blacklist(user_id)
        
        # Verifica cooldown
        user_data = self._get_utente_data(user_id)
        if user_data.in_cooldown and user_data.cooldown_fine:
            fine = self._parse_timestamp(user_data.cooldown_fine)
            if fine and fine > datetime.now():
                remaining = (fine - datetime.now()).total_seconds() / 60
                return False, f"Cooldown attivo: riprova tra {int(remaining)} minuti", int(remaining + 1)
            else:
                # Cooldown terminato
                user_data.in_cooldown = False
                user_data.cooldown_fine = None
                self._save_utente_data(user_id, user_data)
        
        # Determina il tipo di limite
        try:
            tipo_enum = TipoLimite(tipo.lower())
        except ValueError:
            logger.warning(f"Tipo di limite sconosciuto: {tipo}")
            return True, "Tipo sconosciuto, accesso consentito", None
        
        # Verifica e resetta contatori se necessario
        self._check_and_reset_counters(user_data, tipo_enum)
        
        config = self.limiti.get(tipo_enum)
        if config is None:
            return True, "Nessun limite configurato", None
        
        # Controlla il limite
        current_count = (user_data.contatore_comandi if tipo_enum == TipoLimite.COMANDO 
                         else user_data.contatore_ticket)
        
        if current_count >= config.max_count:
            # Limite superato, attiva cooldown
            user_data.in_cooldown = True
            user_data.cooldown_fine = (datetime.now() + self.COOLDOWN_DURATION).isoformat()
            self._save_utente_data(user_id, user_data)
            
            # Registra violazione
            self._registra_violazione(user_id, tipo_enum, "Limite superato")
            
            return False, f"Limite {tipo} superato ({current_count}/{config.max_count}). Cooldown attivo.", int(self.COOLDOWN_DURATION.total_seconds() / 60)
        
        return True, f"Limite ok ({current_count + 1}/{config.max_count})", None
    
    def _registra_violazione(self, user_id: str, tipo: TipoLimite, motivo: str) -> None:
        """Registra una violazione per un utente."""
        user_data = self._get_utente_data(user_id)
        
        violazione = {
            "tipo": tipo.value,
            "timestamp": self._get_timestamp(),
            "motivo": motivo
        }
        
        user_data.violazioni.append(violazione)
        
        # Limita lo storico violazioni a 50 elementi
        if len(user_data.violazioni) > 50:
            user_data.violazioni = user_data.violazioni[-50:]
        
        self._save_utente_data(user_id, user_data)
        logger.info(f"Violazione registrata per utente {user_id}: {tipo.value} - {motivo}")
    
    def registra_comando(self, user_id: str) -> bool:
        """
        Registra un comando eseguito dall'utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se il comando è stato registrato, False se bloccato
        """
        # Verifica whitelist
        if self.is_whitelisted(user_id):
            return True
        
        # Verifica rate limit
        allowed, msg, _ = self.check_rate_limit(user_id, "comando")
        if not allowed:
            logger.warning(f"Comando bloccato per {user_id}: {msg}")
            return False
        
        # Registra il comando
        user_data = self._get_utente_data(user_id)
        now = self._get_timestamp()
        
        # Reset contatore se necessario
        config = self.limiti.get(TipoLimite.COMANDO)
        if config and user_data.timestamp_primo_comando:
            if not self._is_within_time_window(user_data.timestamp_primo_comando, config.finestra_tempo):
                user_data.contatore_comandi = 0
                user_data.timestamp_primo_comando = None
        
        if user_data.contatore_comandi == 0:
            user_data.timestamp_primo_comando = now
        
        user_data.contatore_comandi += 1
        user_data.timestamp_ultimo_comando = now
        
        self._save_utente_data(user_id, user_data)
        if config:
            logger.debug(f"Comando registrato per {user_id}: {user_data.contatore_comandi}/{config.max_count}")
        return True
    
    def registra_ticket(self, user_id: str) -> bool:
        """
        Registra l'apertura di un ticket da parte dell'utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se il ticket è stato registrato, False se bloccato
        """
        # Verifica whitelist
        if self.is_whitelisted(user_id):
            return True
        
        # Verifica rate limit
        allowed, msg, _ = self.check_rate_limit(user_id, "ticket")
        if not allowed:
            logger.warning(f"Ticket bloccato per {user_id}: {msg}")
            return False
        
        # Registra il ticket
        user_data = self._get_utente_data(user_id)
        now = self._get_timestamp()
        
        # Reset contatore se necessario
        config = self.limiti.get(TipoLimite.TICKET)
        if config and user_data.timestamp_primo_ticket:
            if not self._is_within_time_window(user_data.timestamp_primo_ticket, config.finestra_tempo):
                user_data.contatore_ticket = 0
                user_data.timestamp_primo_ticket = None
        
        if user_data.contatore_ticket == 0:
            user_data.timestamp_primo_ticket = now
        
        user_data.contatore_ticket += 1
        user_data.timestamp_ultimo_ticket = now
        
        self._save_utente_data(user_id, user_data)
        if config:
            logger.debug(f"Ticket registrato per {user_id}: {user_data.contatore_ticket}/{config.max_count}")
        return True
    
    def aggiungi_blacklist(self, user_id: str, motivo: str, durata_minuti: Optional[int] = None) -> bool:
        """
        Aggiunge un utente alla blacklist.
        
        Args:
            user_id: ID dell'utente
            motivo: Motivo della blacklist
            durata_minuti: Durata della blacklist in minuti (default: configurazione)
            
        Returns:
            True se l'operazione è riuscita
        """
        durata = durata_minuti if durata_minuti else self.blacklist_default_duration
        
        user_data = self._get_utente_data(user_id)
        user_data.blacklist = True
        user_data.blacklist_motivo = motivo
        user_data.blacklist_fine = (datetime.now() + timedelta(minutes=durata)).isoformat()
        
        # Rimuovi dalla whitelist se presente
        if user_data.whitelist:
            user_data.whitelist = False
            logger.info(f"Utente {user_id} rimosso dalla whitelist per essere aggiunto alla blacklist")
        
        self._save_utente_data(user_id, user_data)
        
        # Registra violazione
        self._registra_violazione(user_id, TipoLimite.COMANDO, f"Blacklist: {motivo}")
        
        logger.info(f"Utente {user_id} aggiunto alla blacklist per {durata} minuti: {motivo}")
        return True
    
    def rimuovi_blacklist(self, user_id: str) -> bool:
        """
        Rimuove un utente dalla blacklist.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'operazione è riuscita
        """
        user_data = self._get_utente_data(user_id)
        
        if not user_data.blacklist:
            logger.debug(f"Utente {user_id} non era in blacklist")
            return True
        
        user_data.blacklist = False
        user_data.blacklist_fine = None
        user_data.blacklist_motivo = None
        
        self._save_utente_data(user_id, user_data)
        logger.info(f"Utente {user_id} rimosso dalla blacklist")
        return True
    
    def is_blacklisted(self, user_id: str) -> bool:
        """
        Verifica se un utente è in blacklist.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'utente è in blacklist
        """
        user_data = self._get_utente_data(user_id)
        
        if not user_data.blacklist:
            return False
        
        # Verifica se la blacklist è scaduta
        if user_data.blacklist_fine:
            fine = self._parse_timestamp(user_data.blacklist_fine)
            if fine and fine <= datetime.now():
                # Blacklist scaduta, rimuovila automaticamente
                self.rimuovi_blacklist(user_id)
                return False
        
        return True
    
    def is_whitelisted(self, user_id: str) -> bool:
        """
        Verifica se un utente è in whitelist.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'utente è in whitelist
        """
        user_data = self._get_utente_data(user_id)
        return user_data.whitelist
    
    def aggiungi_whitelist(self, user_id: str) -> bool:
        """
        Aggiunge un utente alla whitelist (utenti VIP/admin).
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'operazione è riuscita
        """
        user_data = self._get_utente_data(user_id)
        user_data.whitelist = True
        
        # Rimuovi dalla blacklist se presente
        if user_data.blacklist:
            user_data.blacklist = False
            user_data.blacklist_fine = None
            user_data.blacklist_motivo = None
            logger.info(f"Utente {user_id} rimosso dalla blacklist per essere aggiunto alla whitelist")
        
        self._save_utente_data(user_id, user_data)
        logger.info(f"Utente {user_id} aggiunto alla whitelist")
        return True
    
    def rimuovi_whitelist(self, user_id: str) -> bool:
        """
        Rimuove un utente dalla whitelist.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'operazione è riuscita
        """
        user_data = self._get_utente_data(user_id)
        
        if not user_data.whitelist:
            logger.debug(f"Utente {user_id} non era in whitelist")
            return True
        
        user_data.whitelist = False
        self._save_utente_data(user_id, user_data)
        logger.info(f"Utente {user_id} rimosso dalla whitelist")
        return True
    
    def get_violazioni(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Ottiene lo storico delle violazioni per un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Lista delle violazioni
        """
        user_data = self._get_utente_data(user_id)
        return user_data.violazioni.copy()
    
    def get_stato_rate_limit(self, user_id: str) -> Dict[str, Any]:
        """
        Ottiene lo stato completo del rate limit per un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Dizionario con lo stato del rate limit
        """
        user_data = self._get_utente_data(user_id)
        
        # Calcola contatori attuali
        config_comandi = self.limiti.get(TipoLimite.COMANDO)
        config_ticket = self.limiti.get(TipoLimite.TICKET)
        
        # Verifica se i contatori sono ancora validi
        contatore_comandi = user_data.contatore_comandi
        contatore_ticket = user_data.contatore_ticket
        
        if config_comandi and user_data.timestamp_primo_comando:
            if not self._is_within_time_window(user_data.timestamp_primo_comando, config_comandi.finestra_tempo):
                contatore_comandi = 0
        
        if config_ticket and user_data.timestamp_primo_ticket:
            if not self._is_within_time_window(user_data.timestamp_primo_ticket, config_ticket.finestra_tempo):
                contatore_ticket = 0
        
        # Calcola cooldown rimanente
        cooldown_rimanente = None
        if user_data.in_cooldown and user_data.cooldown_fine:
            fine = self._parse_timestamp(user_data.cooldown_fine)
            if fine:
                remaining = (fine - datetime.now()).total_seconds() / 60
                if remaining > 0:
                    cooldown_rimanente = int(remaining + 1)
                else:
                    cooldown_rimanente = 0
        
        # Calcola blacklist rimanente
        blacklist_rimanente = None
        if user_data.blacklist and user_data.blacklist_fine:
            fine = self._parse_timestamp(user_data.blacklist_fine)
            if fine:
                remaining = (fine - datetime.now()).total_seconds() / 60
                if remaining > 0:
                    blacklist_rimanente = int(remaining + 1)
                else:
                    blacklist_rimanente = 0
        
        return {
            "user_id": user_id,
            "whitelist": user_data.whitelist,
            "blacklist": user_data.blacklist,
            "blacklist_motivo": user_data.blacklist_motivo,
            "blacklist_rimanente_minuti": blacklist_rimanente,
            "comandi": {
                "contatore": contatore_comandi,
                "limite": config_comandi.max_count if config_comandi else None,
                "finestra": config_comandi.finestra_tempo.total_seconds() / 60 if config_comandi else None,
                "ultimo_comando": user_data.timestamp_ultimo_comando
            },
            "ticket": {
                "contatore": contatore_ticket,
                "limite": config_ticket.max_count if config_ticket else None,
                "finestra": config_ticket.finestra_tempo.total_seconds() / 60 if config_ticket else None,
                "ultimo_ticket": user_data.timestamp_ultimo_ticket
            },
            "in_cooldown": user_data.in_cooldown,
            "cooldown_rimanente_minuti": cooldown_rimanente,
            "violazioni_count": len(user_data.violazioni)
        }
    
    def pulisci_rate_limits(self) -> Dict[str, int]:
        """
        Pulisce i dati di rate limiting vecchi.
        
        Returns:
            Dizionario con il numero di elementi rimossi per categoria
        """
        stats = {
            "utenti_processati": 0,
            "cooldown_rimossi": 0,
            "dati_utente_rimossi": 0
        }
        
        rate_limits_data = self.persistence.get_data("rate_limits") or {}
        now = datetime.now()
        
        # Data di cutoff per la retention
        cutoff_date = now - timedelta(days=self.DATA_RETENTION_DAYS)
        
        users_to_remove = []
        
        for user_id, user_data_dict in rate_limits_data.items():
            stats["utenti_processati"] += 1
            
            # Converti in oggetto per elaborazione
            user_data = UtenteRateLimit(**user_data_dict)
            modified = False
            
            # Pulisci cooldown scaduti
            if user_data.in_cooldown and user_data.cooldown_fine:
                fine = self._parse_timestamp(user_data.blacklist_fine)
                if fine and fine <= now:
                    user_data.in_cooldown = False
                    user_data.cooldown_fine = None
                    stats["cooldown_rimossi"] += 1
                    modified = True
            
            # Rimuovi blacklist scadute
            if user_data.blacklist and user_data.blacklist_fine:
                fine = self._parse_timestamp(user_data.blacklist_fine)
                if fine and fine <= now:
                    user_data.blacklist = False
                    user_data.blacklist_fine = None
                    user_data.blacklist_motivo = None
                    modified = True
            
            # Pulisci timestamp vecchi (non nella finestra attiva)
            config = self.limiti.get(TipoLimite.COMANDO)
            if user_data.timestamp_primo_comando:
                ts = self._parse_timestamp(user_data.timestamp_primo_comando)
                if ts and ts <= cutoff_date:
                    user_data.contatore_comandi = 0
                    user_data.timestamp_primo_comando = None
                    user_data.timestamp_ultimo_comando = None
                    modified = True
            
            config = self.limiti.get(TipoLimite.TICKET)
            if user_data.timestamp_primo_ticket:
                ts = self._parse_timestamp(user_data.timestamp_primo_ticket)
                if ts and ts <= cutoff_date:
                    user_data.contatore_ticket = 0
                    user_data.timestamp_primo_ticket = None
                    user_data.timestamp_ultimo_ticket = None
                    modified = True
            
            # Pulisci violazioni vecchie (più vecchie di 30 giorni)
            if user_data.violazioni:
                violazioni_recenti = []
                cutoff_violazioni = now - timedelta(days=30)
                for v in user_data.violazioni:
                    ts = self._parse_timestamp(v.get("timestamp"))
                    if ts and ts > cutoff_violazioni:
                        violazioni_recenti.append(v)
                
                if len(violazioni_recenti) != len(user_data.violazioni):
                    user_data.violazioni = violazioni_recenti
                    modified = True
            
            # Determina se l'utente può essere rimosso completamente
            can_remove = (
                not user_data.blacklist and
                not user_data.whitelist and
                not user_data.in_cooldown and
                user_data.contatore_comandi == 0 and
                user_data.contatore_ticket == 0 and
                len(user_data.violazioni) == 0
            )
            
            if can_remove and user_data.timestamp_primo_comando is None and user_data.timestamp_primo_ticket is None:
                users_to_remove.append(user_id)
                stats["dati_utente_rimossi"] += 1
            elif modified:
                self._save_utente_data(user_id, user_data)
        
        # Rimuovi utenti non necessari
        for user_id in users_to_remove:
            try:
                # Rimuovi usando direttamente persistence
                rate_limits_data = self.persistence.get_data("rate_limits") or {}
                if user_id in rate_limits_data:
                    del rate_limits_data[user_id]
                    self.persistence.update_data("rate_limits", rate_limits_data)
            except Exception as e:
                logger.error(f"Errore nella rimozione dati utente {user_id}: {e}")
        
        logger.info(f"Pulizia rate limits completata: {stats}")
        return stats
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Ottiene statistiche globali sul rate limiting.
        
        Returns:
            Dizionario con le statistiche
        """
        rate_limits_data = self.persistence.get_data("rate_limits") or {}
        
        total_users = len(rate_limits_data)
        whitelisted = 0
        blacklisted = 0
        in_cooldown = 0
        total_violations = 0
        
        for user_data_dict in rate_limits_data.values():
            user_data = UtenteRateLimit(**user_data_dict)
            if user_data.whitelist:
                whitelisted += 1
            if user_data.blacklist:
                blacklisted += 1
            if user_data.in_cooldown:
                in_cooldown += 1
            total_violations += len(user_data.violazioni)
        
        return {
            "total_users": total_users,
            "whitelisted_users": whitelisted,
            "blacklisted_users": blacklisted,
            "users_in_cooldown": in_cooldown,
            "total_violations": total_violations,
            "limits": {
                "comandi": {
                    "max_per_finestra": self.limiti[TipoLimite.COMANDO].max_count,
                    "finestra_minuti": self.limiti[TipoLimite.COMANDO].finestra_tempo.total_seconds() / 60
                },
                "ticket": {
                    "max_per_finestra": self.limiti[TipoLimite.TICKET].max_count,
                    "finestra_minuti": self.limiti[TipoLimite.TICKET].finestra_tempo.total_seconds() / 60
                }
            }
        }
    
    def aggiorna_limiti(self, tipo: TipoLimite, max_count: int, finestra_minuti: int) -> bool:
        """
        Aggiorna la configurazione di un limite.
        
        Args:
            tipo: Tipo di limite da aggiornare
            max_count: Numero massimo di azioni
            finestra_minuti: Durata della finestra in minuti
            
        Returns:
            True se l'operazione è riuscita
        """
        if tipo not in self.limiti:
            logger.warning(f"Tipo di limite non valido: {tipo}")
            return False
        
        self.limiti[tipo] = LimiteConfig(
            max_count=max_count,
            finestra_tempo=timedelta(minutes=finestra_minuti)
        )
        
        logger.info(f"Limite aggiornato per {tipo.value}: {max_count}/{finestra_minuti}min")
        return True
    
    def reset_utente(self, user_id: str) -> bool:
        """
        Reset completo dei dati di rate limit per un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'operazione è riuscita
        """
        rate_limits_data = self.persistence.get_data("rate_limits") or {}
        
        if user_id in rate_limits_data:
            del rate_limits_data[user_id]
            self.persistence.update_data("rate_limits", rate_limits_data)
            logger.info(f"Dati rate limit resettati per utente {user_id}")
            return True
        
        return False
    
    def get_utenti_blacklist(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista degli utenti in blacklist con i dettagli.
        
        Returns:
            Lista degli utenti in blacklist
        """
        rate_limits_data = self.persistence.get_data("rate_limits") or {}
        blacklist = []
        
        for user_id, user_data_dict in rate_limits_data.items():
            user_data = UtenteRateLimit(**user_data_dict)
            if user_data.blacklist:
                blacklist.append({
                    "user_id": user_id,
                    "motivo": user_data.blacklist_motivo,
                    "scadenza": user_data.blacklist_fine
                })
        
        return blacklist
    
    def get_utenti_whitelist(self) -> List[str]:
        """
        Ottiene la lista degli utenti in whitelist.
        
        Returns:
            Lista degli ID utenti in whitelist
        """
        rate_limits_data = self.persistence.get_data("rate_limits") or {}
        whitelist = []
        
        for user_id, user_data_dict in rate_limits_data.items():
            user_data = UtenteRateLimit(**user_data_dict)
            if user_data.whitelist:
                whitelist.append(user_id)
        
        return whitelist


def create_rate_limiter(persistence, config: Optional[Dict[str, Any]] = None) -> RateLimiter:
    """
    Factory function per creare un'istanza di RateLimiter con configurazione personalizzata.
    
    Args:
        persistence: Istanza di DataPersistence
        config: Dizionario opzionale con configurazione custom
        
    Returns:
        Istanza configurata di RateLimiter
    """
    custom_limits = None
    blacklist_duration = RateLimiter.DEFAULT_BLACKLIST_DURATION
    
    if config:
        # Parsa configurazione custom
        limits_config = config.get("limits", {})
        blacklist_duration = config.get("blacklist_duration_minutes", RateLimiter.DEFAULT_BLACKLIST_DURATION)
        
        custom_limits = {}
        
        if "comandi" in limits_config:
            custom_limits[TipoLimite.COMANDO] = LimiteConfig(
                max_count=limits_config["comandi"].get("max", 5),
                finestra_tempo=timedelta(minutes=limits_config["comandi"].get("minuti", 1))
            )
        
        if "ticket" in limits_config:
            custom_limits[TipoLimite.TICKET] = LimiteConfig(
                max_count=limits_config["ticket"].get("max", 2),
                finestra_tempo=timedelta(minutes=limits_config["ticket"].get("minuti", 60))
            )
    
    return RateLimiter(persistence, custom_limits, blacklist_duration)

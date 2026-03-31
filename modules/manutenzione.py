"""
Modulo per la gestione della modalità manutenzione del bot.
Gestisce attivazione/disattivazione manutenzione, blocco utenti e messaggi personalizzati.

Utilizza il modulo di persistenza per salvare i dati su file JSON.
Integra con il sistema di rate limiting e stato servizio.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

# ==================== COSTANTI MANUTENZIONE ====================
KEY_ADMIN_IDS = "admin_ids"
KEY_MANUTENZIONE_ATTIVA = "manutenzione_attiva"
KEY_MANUTENZIONE_DATA_INIZIO = "data_inizio"
KEY_MANUTENZIONE_DATA_FINE = "data_fine"
KEY_MANUTENZIONE_MOTIVO = "motivo"
KEY_MANUTENZIONE_ADMIN_ATTIVATORE = "admin_attivatore"
KEY_MANUTENZIONE_MESSAGGIO = "messaggio_personalizzato"
KEY_TICKET_IN_CODA = "ticket_in_coda"
KEY_RICHIESTE_IPTV_IN_PAUSA = "richieste_iptv_in_pausa"

# Chiave per la struttura dati persistita
KEY_CONFIGURAZIONE = "configurazione"
KEY_STORICO = "storico_manutenzioni"


class ManutenzioneError(Exception):
    """Eccezione personalizzata per errori nella gestione manutenzione."""
    pass


class Manutenzione:
    """
    Classe per la gestione della modalità manutenzione.
    Gestisce attivazione/disattivazione, blocco utenti e messaggi personalizzati.
    """
    
    # Struttura dati predefinita per la configurazione manutenzione
    DEFAULT_CONFIGURAZIONE: Dict[str, Any] = {
        KEY_ADMIN_IDS: [],  # Lista ID admin autorizzati
        KEY_MANUTENZIONE_ATTIVA: False,
        KEY_MANUTENZIONE_DATA_INIZIO: None,
        KEY_MANUTENZIONE_DATA_FINE: None,
        KEY_MANUTENZIONE_MOTIVO: None,
        KEY_MANUTENZIONE_ADMIN_ATTIVATORE: None,
        KEY_MANUTENZIONE_MESSAGGIO: None,
        KEY_TICKET_IN_CODA: [],
        KEY_RICHIESTE_IPTV_IN_PAUSA: False
    }
    
    # Comandi consentiti durante la manutenzione per utenti normali
    COMANDI_CONSENTITI_DURANTE_MANUTENZIONE = [
        "faq",
        "help",
        "start",
        "/faq",
        "/help",
        "/start"
    ]
    
    def __init__(self, persistence: DataPersistence, 
                 rate_limiter: Optional[Any] = None,
                 stato_servizio: Optional[Any] = None):
        """
        Inizializza il gestore manutenzione.
        
        Args:
            persistence: Istanza del modulo di persistenza dati
            rate_limiter: Istanza del rate limiter (opzionale, per integrazione)
            stato_servizio: Istanza dello stato servizio (opzionale, per integrazione)
        """
        self.persistence = persistence
        self.rate_limiter = rate_limiter
        self.stato_servizio = stato_servizio
        self._inizializza_dati()
        logger.info("Modulo Manutenzione inizializzato")
    
    def _inizializza_dati(self) -> None:
        """Inizializza la struttura dati se non presente."""
        dati = self.persistence.get_data("manutenzione")
        if not dati or dati == {}:
            struttura = self._get_struttura_default()
            self.persistence.update_data("manutenzione", struttura)
            logger.info("Struttura dati manutenzione inizializzata")
    
    def _get_struttura_default(self) -> Dict[str, Any]:
        """Restituisce una copia della struttura dati predefinita."""
        import copy
        return copy.deepcopy(self.DEFAULT_CONFIGURAZIONE)
    
    def _get_dati(self) -> Dict[str, Any]:
        """Ottiene i dati della manutenzione dalla persistenza."""
        dati = self.persistence.get_data("manutenzione")
        if not dati:
            dati = self._get_struttura_default()
            self.persistence.update_data("manutenzione", dati)
        return dati
    
    def _salva_dati(self) -> None:
        """Salva i dati della manutenzione."""
        # DataPersistence ha auto_save attivo per default
        pass
    
    def _aggiungi_a_storico(self, azione: str, admin_id: Optional[str] = None,
                            motivo: Optional[str] = None) -> None:
        """Aggiunge un evento allo storico manutenzioni."""
        dati = self._get_dati()
        
        if KEY_STORICO not in dati:
            dati[KEY_STORICO] = []
        
        evento = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "azione": azione,
            "admin_id": admin_id,
            "motivo": motivo
        }
        dati[KEY_STORICO].append(evento)
        
        # Limita lo storico agli ultimi 50 eventi
        if len(dati.get(KEY_STORICO, [])) > 50:
            dati[KEY_STORICO] = dati[KEY_STORICO][-50:]
        
        self.persistence.update_data("manutenzione", dati)
    
    # ==================== GESTIONE ADMIN ====================
    
    def aggiungi_admin(self, admin_id: str) -> Tuple[bool, str]:
        """
        Aggiunge un admin alla lista degli amministratori.
        
        Args:
            admin_id: ID dell'admin da aggiungere
            
        Returns:
            Tuple (bool, messaggio)
        """
        dati = self._get_dati()
        
        admin_ids = dati.get(KEY_ADMIN_IDS, [])
        if admin_id in admin_ids:
            return False, f"L'admin {admin_id} è già presente nella lista"
        
        admin_ids.append(admin_id)
        dati[KEY_ADMIN_IDS] = admin_ids
        self.persistence.update_data("manutenzione", dati)
        
        # Aggiungi alla whitelist del rate limiter se disponibile
        if self.rate_limiter:
            try:
                self.rate_limiter.whitelist_user(admin_id)
            except Exception as e:
                logger.warning(f"Errore nell'aggiungere admin alla whitelist rate limiter: {e}")
        
        logger.info(f"Admin {admin_id} aggiunto alla lista admin")
        return True, f"Admin {admin_id} aggiunto con successo"
    
    def rimuovi_admin(self, admin_id: str) -> Tuple[bool, str]:
        """
        Rimuove un admin dalla lista degli amministratori.
        
        Args:
            admin_id: ID dell'admin da rimuovere
            
        Returns:
            Tuple (bool, messaggio)
        """
        dati = self._get_dati()
        
        admin_ids = dati.get(KEY_ADMIN_IDS, [])
        if admin_id not in admin_ids:
            return False, f"L'admin {admin_id} non è presente nella lista"
        
        admin_ids.remove(admin_id)
        dati[KEY_ADMIN_IDS] = admin_ids
        self.persistence.update_data("manutenzione", dati)
        
        # Rimuovi dalla whitelist del rate limiter se disponibile
        if self.rate_limiter:
            try:
                self.rate_limiter.remove_whitelist(admin_id)
            except Exception as e:
                logger.warning(f"Errore nel rimuovere admin dalla whitelist rate limiter: {e}")
        
        logger.info(f"Admin {admin_id} rimosso dalla lista admin")
        return True, f"Admin {admin_id} rimosso con successo"
    
    def get_admin_ids(self) -> List[str]:
        """
        Restituisce la lista degli ID admin.
        
        Returns:
            Lista degli ID admin
        """
        dati = self._get_dati()
        return dati.get(KEY_ADMIN_IDS, [])
    
    def is_admin(self, user_id: str) -> bool:
        """
        Verifica se un utente è admin.
        
        Args:
            user_id: ID dell'utente da verificare
            
        Returns:
            True se l'utente è admin, False altrimenti
        """
        admin_ids = self.get_admin_ids()
        return str(user_id) in [str(aid) for aid in admin_ids]
    
    # ==================== ATTIVAZIONE/DISATTIVAZIONE MANUTENZIONE ====================
    
    def attiva_manutenzione(self, admin_id: str, motivo: str, 
                           durata_minuti: Optional[int] = None,
                           messaggio_personalizzato: Optional[str] = None) -> Dict[str, Any]:
        """
        Attiva la modalità manutenzione.
        
        Args:
            admin_id: ID dell'admin che attiva la manutenzione
            motivo: Motivo della manutenzione
            durata_minuti: Durata della manutenzione in minuti (opzionale)
            messaggio_personalizzato: Messaggio personalizzato per gli utenti (opzionale)
            
        Returns:
            Dizionario con i dettagli dell'attivazione
            
        Raises:
            ManutenzioneError: Se l'utente non è admin o la manutenzione è già attiva
        """
        # Verifica che l'utente sia admin
        if not self.is_admin(admin_id):
            raise ManutenzioneError(f"L'utente {admin_id} non è autorizzato ad attivare la manutenzione")
        
        dati = self._get_dati()
        
        # Verifica se la manutenzione è già attiva
        if dati.get(KEY_MANUTENZIONE_ATTIVA, False):
            raise ManutenzioneError("La modalità manutenzione è già attiva")
        
        # Calcola la data di fine
        data_inizio = datetime.now()
        if durata_minuti:
            data_fine = data_inizio + timedelta(minutes=durata_minuti)
        else:
            data_fine = None
        
        # Aggiorna i dati
        dati[KEY_MANUTENZIONE_ATTIVA] = True
        dati[KEY_MANUTENZIONE_DATA_INIZIO] = data_inizio.isoformat()
        dati[KEY_MANUTENZIONE_DATA_FINE] = data_fine.isoformat() if data_fine else None
        dati[KEY_MANUTENZIONE_MOTIVO] = motivo
        dati[KEY_MANUTENZIONE_ADMIN_ATTIVATORE] = admin_id
        dati[KEY_MANUTENZIONE_MESSAGGIO] = messaggio_personalizzato
        dati[KEY_RICHIESTE_IPTV_IN_PAUSA] = True
        dati[KEY_TICKET_IN_CODA] = []
        
        self.persistence.update_data("manutenzione", dati)
        
        # Aggiorna lo stato servizio se disponibile
        if self.stato_servizio:
            try:
                from modules.stato_servizio import STATO_MANUTENZIONE
                self.stato_servizio.aggiorna_stato(
                    STATO_MANUTENZIONE, 
                    f"Manutenzione attivata: {motivo}",
                    admin_id
                )
            except Exception as e:
                logger.warning(f"Errore nell'aggiornare stato servizio: {e}")
        
        # Aggiungi allo storico
        self._aggiungi_a_storico("attivazione", admin_id, motivo)
        
        logger.info(f"Manutenzione attivata da admin {admin_id}. Motivo: {motivo}. "
                   f"Durata: {durata_minuti} minutes" if durata_minuti else "Durata: indefinita")
        
        return {
            "success": True,
            "manutenzione_attiva": True,
            "data_inizio": data_inizio.isoformat(),
            "data_fine": data_fine.isoformat() if data_fine else None,
            "motivo": motivo,
            "admin_attivatore": admin_id,
            "messaggio_personalizzato": messaggio_personalizzato
        }
    
    def disattiva_manutenzione(self, admin_id: str) -> Dict[str, Any]:
        """
        Disattiva la modalità manutenzione.
        
        Args:
            admin_id: ID dell'admin che disattiva la manutenzione
            
        Returns:
            Dizionario con i dettagli della disattivazione
            
        Raises:
            ManutenzioneError: Se l'utente non è admin o la manutenzione non è attiva
        """
        # Verifica che l'utente sia admin
        if not self.is_admin(admin_id):
            raise ManutenzioneError(f"L'utente {admin_id} non è autorizzato a disattivare la manutenzione")
        
        dati = self._get_dati()
        
        # Verifica se la manutenzione è attiva
        if not dati.get(KEY_MANUTENZIONE_ATTIVA, False):
            raise ManutenzioneError("La modalità manutenzione non è attiva")
        
        # Salva le informazioni prima di disattivare
        motivo = dati.get(KEY_MANUTENZIONE_MOTIVO, "N/A")
        data_inizio = dati.get(KEY_MANUTENZIONE_DATA_INIZIO)
        ticket_in_coda = dati.get(KEY_TICKET_IN_CODA, [])
        richieste_pausate = dati.get(KEY_RICHIESTE_IPTV_IN_PAUSA, False)
        
        # Disattiva la manutenzione
        dati[KEY_MANUTENZIONE_ATTIVA] = False
        dati[KEY_MANUTENZIONE_DATA_INIZIO] = None
        dati[KEY_MANUTENZIONE_DATA_FINE] = None
        dati[KEY_MANUTENZIONE_MOTIVO] = None
        dati[KEY_MANUTENZIONE_ADMIN_ATTIVATORE] = None
        dati[KEY_MANUTENZIONE_MESSAGGIO] = None
        dati[KEY_RICHIESTE_IPTV_IN_PAUSA] = False
        
        self.persistence.update_data("manutenzione", dati)
        
        # Aggiorna lo stato servizio se disponibile
        if self.stato_servizio:
            try:
                from modules.stato_servizio import STATO_OPERATIVO
                self.stato_servizio.aggiorna_stato(
                    STATO_OPERATIVO, 
                    "Manutenzione completata",
                    admin_id
                )
            except Exception as e:
                logger.warning(f"Errore nell'aggiornare stato servizio: {e}")
        
        # Aggiungi allo storico
        self._aggiungi_a_storico("disattivazione", admin_id, motivo)
        
        logger.info(f"Manutenzione disattivata da admin {admin_id}. "
                   f"Ticket in coda: {len(ticket_in_coda)}")
        
        return {
            "success": True,
            "manutenzione_attiva": False,
            "data_inizio": data_inizio,
            "motivo": motivo,
            "ticket_in_coda": ticket_in_coda,
            "richieste_iptv_pausate": richieste_pausate,
            "admin_disattivatore": admin_id
        }
    
    def is_manutenzione_attiva(self) -> bool:
        """
        Verifica se la modalità manutenzione è attiva.
        
        Returns:
            True se la manutenzione è attiva, False altrimenti
        """
        dati = self._get_dati()
        
        # Verifica prima il flag esplicito
        if not dati.get(KEY_MANUTENZIONE_ATTIVA, False):
            return False
        
        # Verifica se è impostata una data di fine e se è passata
        data_fine = dati.get(KEY_MANUTENZIONE_DATA_FINE)
        if data_fine:
            try:
                data_fine_dt = datetime.fromisoformat(data_fine)
                if datetime.now() > data_fine_dt:
                    # La manutenzione è terminata automaticamente
                    logger.info("Manutenzione terminata automaticamente per raggiungimento data fine")
                    self._disattivazione_automatica()
                    return False
            except (ValueError, TypeError):
                pass
        
        return True
    
    def _disattivazione_automatica(self) -> None:
        """Disattiva automaticamente la manutenzione."""
        dati = self._get_dati()
        dati[KEY_MANUTENZIONE_ATTIVA] = False
        dati[KEY_MANUTENZIONE_DATA_FINE] = None
        self.persistence.update_data("manutenzione", dati)
        
        if self.stato_servizio:
            try:
                from modules.stato_servizio import STATO_OPERATIVO
                self.stato_servizio.aggiorna_stato(STATO_OPERATIVO, "Manutenzione terminata automaticamente")
            except Exception:
                pass
    
    # ==================== INFORMAZIONI MANUTENZIONE ====================
    
    def get_info_manutenzione(self) -> Dict[str, Any]:
        """
        Restituisce le informazioni sulla manutenzione attiva.
        
        Returns:
            Dizionario con le informazioni sulla manutenzione
        """
        dati = self._get_dati()
        
        manutenzione_attiva = self.is_manutenzione_attiva()
        
        info = {
            "manutenzione_attiva": manutenzione_attiva,
            "data_inizio": dati.get(KEY_MANUTENZIONE_DATA_INIZIO),
            "data_fine": dati.get(KEY_MANUTENZIONE_DATA_FINE),
            "motivo": dati.get(KEY_MANUTENZIONE_MOTIVO),
            "admin_attivatore": dati.get(KEY_MANUTENZIONE_ADMIN_ATTIVATORE),
            "messaggio_personalizzato": dati.get(KEY_MANUTENZIONE_MESSAGGIO),
            "ticket_in_coda": dati.get(KEY_TICKET_IN_CODA, []),
            "richieste_iptv_in_pausa": dati.get(KEY_RICHIESTE_IPTV_IN_PAUSA, False),
            "admin_ids": dati.get(KEY_ADMIN_IDS, [])
        }
        
        # Calcola durata rimanente
        if manutenzione_attiva and info["data_fine"]:
            try:
                data_fine = datetime.fromisoformat(info["data_fine"])
                rimanente = data_fine - datetime.now()
                if rimanente.total_seconds() > 0:
                    info["durata_rimanente_minuti"] = int(rimanente.total_seconds() / 60)
                else:
                    info["durata_rimanente_minuti"] = 0
            except (ValueError, TypeError):
                info["durata_rimanente_minuti"] = None
        else:
            info["durata_rimanente_minuti"] = None
        
        return info
    
    def get_messaggio_manutenzione(self) -> str:
        """
        Restituisce il messaggio di manutenzione da mostrare agli utenti.
        
        Returns:
            Messaggio di manutenzione
        """
        dati = self._get_dati()
        messaggio_personalizzato = dati.get(KEY_MANUTENZIONE_MESSAGGIO)
        
        if messaggio_personalizzato:
            return messaggio_personalizzato
        
        # Messaggio predefinito
        data_fine = dati.get(KEY_MANUTENZIONE_DATA_FINE)
        if data_fine:
            try:
                data_fine_dt = datetime.fromisoformat(data_fine)
                data_fine_formattata = data_fine_dt.strftime("%d/%m/%Y %H:%M")
                return (f"⚠️ **Modalità Manutenzione**\n\n"
                       f"Il bot è temporaneamente fuori servizio per manutenzione.\n\n"
                       f"**Motivo:** {dati.get(KEY_MANUTENZIONE_MOTIVO, 'Non specificato')}\n"
                       f"**Ritorno previsto:** {data_fine_formattata}\n\n"
                       f"Ci scusiamo per il disagio.")
            except (ValueError, TypeError):
                pass
        
        return (f"⚠️ **Modalità Manutenzione**\n\n"
               f"Il bot è temporaneamente fuori servizio per manutenzione.\n\n"
               f"**Motivo:** {dati.get(KEY_MANUTENZIONE_MOTIVO, 'Non specificato')}\n\n"
               f"Ci scusiamo per il disagio.")
    
    # ==================== GESTIONE COMANDI UTENTE ====================
    
    def gestisci_comando_utente(self, user_id: str, comando: str) -> Tuple[bool, Optional[str]]:
        """
        Verifica se un comando può essere eseguito durante la manutenzione.
        
        Args:
            user_id: ID dell'utente che esegue il comando
            comando: Comando da verificare
            
        Returns:
            Tuple (bool, messaggio). bool indica se il comando è consentito,
            messaggio contiene il messaggio da mostrare se bloccato
        """
        # Se la manutenzione non è attiva, consenti sempre
        if not self.is_manutenzione_attiva():
            return True, None
        
        # Se l'utente è admin, consenti sempre
        if self.is_admin(user_id):
            return True, None
        
        # Normalizza il comando
        comando_norm = comando.lower().strip()
        if comando_norm.startswith("/"):
            comando_norm = comando_norm[1:]
        
        # Verifica se è un comando consentito
        for cmd_consentito in self.COMANDI_CONSENTITI_DURANTE_MANUTENZIONE:
            cmd_norm = cmd_consentito.lower().strip()
            if cmd_norm.startswith("/"):
                cmd_norm = cmd_norm[1:]
            
            if comando_norm == cmd_norm:
                return True, None
        
        # Comando bloccato
        logger.info(f"Comando '{comando}' bloccato per utente {user_id} durante manutenzione")
        return False, self.get_messaggio_manutenzione()
    
    # ==================== GESTIONE TICKET IN CODA ====================
    
    def aggiungi_ticket_in_coda(self, ticket_id: str, user_id: str, 
                                tipo_richiesta: str) -> None:
        """
        Aggiunge un ticket alla coda durante la manutenzione.
        
        Args:
            ticket_id: ID del ticket
            user_id: ID dell'utente
            tipo_richiesta: Tipo di richiesta
        """
        if not self.is_manutenzione_attiva():
            return
        
        dati = self._get_dati()
        
        ticket_in_coda = dati.get(KEY_TICKET_IN_CODA, [])
        
        # Verifica se il ticket è già in coda
        for ticket in ticket_in_coda:
            if ticket.get("ticket_id") == ticket_id:
                return
        
        ticket_in_coda.append({
            "ticket_id": ticket_id,
            "user_id": user_id,
            "tipo_richiesta": tipo_richiesta,
            "data_inserimento": datetime.now().isoformat()
        })
        
        dati[KEY_TICKET_IN_CODA] = ticket_in_coda
        self.persistence.update_data("manutenzione", dati)
        
        logger.info(f"Ticket {ticket_id} aggiunto alla coda manutenzione")
    
    def rimuovi_ticket_dalla_coda(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """
        Rimuove un ticket dalla coda.
        
        Args:
            ticket_id: ID del ticket da rimuovere
            
        Returns:
            Dizionario con i dettagli del ticket rimosso, o None se non trovato
        """
        dati = self._get_dati()
        
        ticket_in_coda = dati.get(KEY_TICKET_IN_CODA, [])
        ticket_trovato = None
        
        for i, ticket in enumerate(ticket_in_coda):
            if ticket.get("ticket_id") == ticket_id:
                ticket_trovato = ticket
                ticket_in_coda.pop(i)
                break
        
        if ticket_trovato:
            dati[KEY_TICKET_IN_CODA] = ticket_in_coda
            self.persistence.update_data("manutenzione", dati)
            logger.info(f"Ticket {ticket_id} rimosso dalla coda manutenzione")
        
        return ticket_trovato
    
    def get_ticket_in_coda(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista dei ticket in coda.
        
        Returns:
            Lista dei ticket in coda
        """
        dati = self._get_dati()
        return dati.get(KEY_TICKET_IN_CODA, [])
    
    def svuota_coda_ticket(self) -> int:
        """
        Svuota la coda dei ticket.
        
        Returns:
            Numero di ticket rimossi
        """
        dati = self._get_dati()
        
        ticket_in_coda = dati.get(KEY_TICKET_IN_CODA, [])
        count = len(ticket_in_coda)
        
        dati[KEY_TICKET_IN_CODA] = []
        self.persistence.update_data("manutenzione", dati)
        
        logger.info(f"Coda ticket svuotata: {count} ticket rimossi")
        return count
    
    # ==================== GESTIONE RICHIESTE IPTV ====================
    
    def is_richieste_iptv_in_pausa(self) -> bool:
        """
        Verifica se le richieste IPTV sono in pausa.
        
        Returns:
            True se le richieste sono in pausa, False altrimenti
        """
        if not self.is_manutenzione_attiva():
            return False
        
        dati = self._get_dati()
        return dati.get(KEY_RICHIESTE_IPTV_IN_PAUSA, False)
    
    # ==================== METODI UTILITY ====================
    
    def puo_accedere(self, user_id: str) -> bool:
        """
        Verifica se un utente può accedere al bot durante la manutenzione.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'utente può accedere, False altrimenti
        """
        # Se la manutenzione non è attiva, tutti possono accedere
        if not self.is_manutenzione_attiva():
            return True
        
        # Solo gli admin possono accedere durante la manutenzione
        return self.is_admin(user_id)
    
    def get_storico(self) -> List[Dict[str, Any]]:
        """
        Restituisce lo storico delle manutenzioni.
        
        Returns:
            Lista degli eventi di manutenzione
        """
        dati = self._get_dati()
        return dati.get(KEY_STORICO, [])
    
    def resetta_configurazione(self) -> None:
        """
        Resetta la configurazione ai valori predefiniti.
        NOTA: Mantiene la lista degli admin
        """
        dati = self._get_dati()
        
        # Salva la lista admin
        admin_ids = dati.get(KEY_ADMIN_IDS, [])
        
        # Resetta tutto
        struttura = self._get_struttura_default()
        struttura[KEY_ADMIN_IDS] = admin_ids
        
        self.persistence.update_data("manutenzione", struttura)
        
        logger.info("Configurazione manutenzione resettata ai valori predefiniti")

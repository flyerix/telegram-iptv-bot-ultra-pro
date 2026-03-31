"""
Modulo per la gestione dello stato del servizio.
Gestisce lo stato operativo del servizio, problemi noti, manutenzioni e uptime.

Utilizza il modulo di persistenza per salvare i dati su file JSON.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

# ==================== COSTANTI STATI SERVIZIO ====================
STATO_OPERATIVO = "OPERATIVO"
STATO_PROBLEMI = "PROBLEMI"
STATO_MANUTENZIONE = "MANUTENZIONE"
STATO_DISSERVIZIO = "DISSERVIZIO"

# Lista stati validi
STATI_VALIDI = [
    STATO_OPERATIVO,
    STATO_PROBLEMI,
    STATO_MANUTENZIONE,
    STATO_DISSERVIZIO
]

# Chiavi per la struttura dati persistita
KEY_STATO_CORRENTE = "stato_corrente"
KEY_PROBLEMI = "problemi"
KEY_MANUTENZIONI = "manutenzioni"
KEY_STORICO = "storico"
KEY_STATISTICHE = "statistiche"


class StatoServizioError(Exception):
    """Eccezione personalizzata per errori nella gestione dello stato servizio."""
    pass


class StatoServizio:
    """
    Classe per la gestione dello stato del servizio.
    Gestisce stato operativo, problemi noti, manutenzioni e calcolo uptime.
    """
    
    # Struttura dati predefinita per stato servizio
    DEFAULT_STRUTTURA: Dict[str, Any] = {
        KEY_STATO_CORRENTE: STATO_OPERATIVO,
        KEY_PROBLEMI: [],
        KEY_MANUTENZIONI: [],
        KEY_STORICO: [],
        KEY_STATISTICHE: {
            "ultimo_riavvio": datetime.now().isoformat(),
            "totale_downtime_minuti": 0,
            "inizio_monitoraggio": datetime.now().isoformat()
        }
    }
    
    def __init__(self, persistence: DataPersistence):
        """
        Inizializza il gestore stato servizio.
        
        Args:
            persistence: Istanza del modulo di persistenza dati
        """
        self.persistence = persistence
        self._inizializza_dati()
        logger.info("Modulo StatoServizio inizializzato")
    
    def _inizializza_dati(self) -> None:
        """Inizializza la struttura dati se non presente."""
        dati = self.persistence.get_data("stato_servizio")
        if not dati or dati == {}:
            # Inizializza con struttura predefinita
            struttura = self._get_struttura_default()
            self.persistence.update_data("stato_servizio", struttura)
            logger.info("Struttura dati stato servizio inizializzata")
    
    def _get_struttura_default(self) -> Dict[str, Any]:
        """Restituisce una copia della struttura dati predefinita."""
        import copy
        return copy.deepcopy(self.DEFAULT_STRUTTURA)
    
    def _get_dati(self) -> Dict[str, Any]:
        """Ottiene i dati dello stato servizio dalla persistenza."""
        dati = self.persistence.get_data("stato_servizio")
        if not dati:
            dati = self._get_struttura_default()
            self.persistence.update_data("stato_servizio", dati)
        return dati
    
    def _salva_dati(self) -> None:
        """Salva i dati dello stato servizio."""
        # DataPersistence ha auto_save attivo per default
        pass
    
    def _aggiungi_a_storico(self, azione: str, stato: str, motivo: str, 
                           admin_id: Optional[str] = None) -> None:
        """Aggiunge un evento allo storico."""
        dati = self._get_dati()
        evento = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "azione": azione,
            "stato": stato,
            "motivo": motivo,
            "admin_id": admin_id
        }
        dati[KEY_STORICO].append(evento)
        
        # Limita lo storico agli ultimi 100 eventi
        if len(dati[KEY_STORICO]) > 100:
            dati[KEY_STORICO] = dati[KEY_STORICO][-100:]
        
        self.persistence.update_data("stato_servizio", dati)
        
    # ==================== METODI PUBBLICI ====================
    
    def get_stato(self) -> str:
        """
        Restituisce lo stato attuale del servizio.
        
        Returns:
            Stato attuale del servizio (OPERATIVO, PROBLEMI, MANUTENZIONE, DISSERVIZIO)
        """
        dati = self._get_dati()
        return dati.get(KEY_STATO_CORRENTE, STATO_OPERATIVO)
    
    def aggiorna_stato(self, nuovo_stato: str, motivo: str, 
                       admin_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggiorna lo stato del servizio manualmente.
        
        Args:
            nuovo_stato: Nuovo stato del servizio
            motivo: Motivo del cambio di stato
            admin_id: ID dell'admin che effettua il cambio
            
        Returns:
            Dizionario con il nuovo stato e dettagli
            
        Raises:
            StatoServizioError: Se lo stato non è valido
        """
        if nuovo_stato not in STATI_VALIDI:
            raise StatoServizioError(f"Stato non valido: {nuovo_stato}")
        
        vecchio_stato = self.get_stato()
        
        # Aggiorna lo stato
        dati = self._get_dati()
        dati[KEY_STATO_CORRENTE] = nuovo_stato
        
        # Aggiorna statistiche se il servizio era in disservizio
        if vecchio_stato == STATO_DISSERVIZIO and nuovo_stato != STATO_DISSERVIZIO:
            # Il servizio è tornato operativo
            pass
        elif nuovo_stato == STATO_DISSERVIZIO and vecchio_stato != STATO_DISSERVIZIO:
            # Il servizio è passato in disservizio
            pass
        
        self.persistence.update_data("stato_servizio", dati)
        
        # Aggiungi allo storico
        self._aggiungi_a_storico(
            azione="cambio_stato",
            stato=nuovo_stato,
            motivo=motivo,
            admin_id=admin_id
        )
        
        logger.info(f"Stato servizio aggiornato: {vecchio_stato} -> {nuovo_stato}. Motivo: {motivo}")
        
        return {
            "stato": nuovo_stato,
            "stato_precedente": vecchio_stato,
            "motivo": motivo,
            "timestamp": datetime.now().isoformat(),
            "admin_id": admin_id
        }
    
    def aggiungi_problema(self, titolo: str, descrizione: str, 
                          admin_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggiunge un problema noto alla lista.
        
        Args:
            titolo: Titolo del problema
            descrizione: Descrizione dettagliata del problema
            admin_id: ID dell'admin che aggiunge il problema
            
        Returns:
            Dizionario con i dettagli del problema aggiunto
            
        Raises:
            StatoServizioError: Se il titolo è vuoto
        """
        if not titolo or not titolo.strip():
            raise StatoServizioError("Il titolo del problema non può essere vuoto")
        
        dati = self._get_dati()
        
        problema = {
            "id": str(uuid.uuid4()),
            "titolo": titolo.strip(),
            "descrizione": descrizione.strip() if descrizione else "",
            "data_segnalazione": datetime.now().isoformat(),
            "admin_id": admin_id,
            "stato": "attivo"
        }
        
        dati[KEY_PROBLEMI].append(problema)
        self.persistence.update_data("stato_servizio", dati)
        
        # Aggiungi allo storico
        self._aggiungi_a_storico(
            azione="aggiungi_problema",
            stato=self.get_stato(),
            motivo=f"Problema: {titolo}",
            admin_id=admin_id
        )
        
        # Se c'è almeno un problema attivo, imposta lo stato a PROBLEMI
        if self.get_stato() == STATO_OPERATIVO:
            self.aggiorna_stato(STATO_PROBLEMI, f"Problema aggiunto: {titolo}", admin_id)
        
        logger.info(f"Problema aggiunto: {titolo}")
        
        return problema
    
    def rimuovi_problema(self, problema_id: str) -> bool:
        """
        Rimuove un problema dalla lista dei problemi noti.
        
        Args:
            problema_id: ID del problema da rimuovere
            
        Returns:
            True se il problema è stato rimosso, False se non trovato
        """
        dati = self._get_dati()
        problemi = dati[KEY_PROBLEMI]
        
        problema_trovato = None
        for problema in problemi:
            if problema.get("id") == problema_id:
                problema_trovato = problema
                break
        
        if not problema_trovato:
            logger.warning(f"Problema non trovato: {problema_id}")
            return False
        
        # Rimuovi il problema
        dati[KEY_PROBLEMI] = [p for p in problemi if p.get("id") != problema_id]
        self.persistence.update_data("stato_servizio", dati)
        
        # Aggiungi allo storico
        self._aggiungi_a_storico(
            azione="rimuovi_problema",
            stato=self.get_stato(),
            motivo=f"Problema risolto: {problema_trovato.get('titolo')}",
            admin_id=None
        )
        
        # Se non ci sono più problemi, ripristina stato a OPERATIVO
        if len(dati[KEY_PROBLEMI]) == 0 and self.get_stato() == STATO_PROBLEMI:
            self.aggiorna_stato(STATO_OPERATIVO, "Tutti i problemi risolti", None)
        
        logger.info(f"Problema rimosso: {problema_trovato.get('titolo')}")
        
        return True
    
    def get_problemi_attivi(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista dei problemi attivi.
        
        Returns:
            Lista dei problemi attivi
        """
        dati = self._get_dati()
        return [p for p in dati.get(KEY_PROBLEMI, []) if p.get("stato") == "attivo"]
    
    def aggiungi_manutenzione(self, inizio: datetime, fine_prevista: datetime, 
                              motivo: str, admin_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggiunge una manutenzione programmata.
        
        Args:
            inizio: Data e ora di inizio manutenzione
            fine_prevista: Data e ora prevista di fine manutenzione
            motivo: Motivo della manutenzione
            admin_id: ID dell'admin che aggiunge la manutenzione
            
        Returns:
            Dizionario con i dettagli della manutenzione aggiunta
            
        Raises:
            StatoServizioError: Se le date non sono valide
        """
        if fine_prevista <= inizio:
            raise StatoServizioError("La data di fine deve essere successiva alla data di inizio")
        
        dati = self._get_dati()
        
        manutenzione = {
            "id": str(uuid.uuid4()),
            "data_inizio": inizio.isoformat(),
            "data_fine_prevista": fine_prevista.isoformat(),
            "data_fine_effettiva": None,
            "motivo": motivo.strip(),
            "admin_id": admin_id,
            "stato": "in_corso" if inizio <= datetime.now() else "programmata"
        }
        
        dati[KEY_MANUTENZIONI].append(manutenzione)
        self.persistence.update_data("stato_servizio", dati)
        
        # Aggiungi allo storico
        self._aggiungi_a_storico(
            azione="aggiungi_manutenzione",
            stato=STATO_MANUTENZIONE,
            motivo=f"Manutenzione: {motivo}",
            admin_id=admin_id
        )
        
        # Se la manutenzione è già iniziata, imposta lo stato a MANUTENZIONE
        if inizio <= datetime.now():
            self.aggiorna_stato(STATO_MANUTENZIONE, f"Manutenzione iniziata: {motivo}", admin_id)
        
        logger.info(f"Manutenzione aggiunta: {motivo}")
        
        return manutenzione
    
    def termina_manutenzione(self, manutenzione_id: str) -> bool:
        """
        Termina una manutenzione in corso.
        
        Args:
            manutenzione_id: ID della manutenzione da terminare
            
        Returns:
            True se la manutenzione è stata terminata, False se non trovata
        """
        dati = self._get_dati()
        manutenzioni = dati[KEY_MANUTENZIONI]
        
        manutenzione_trovata = None
        for manutenzione in manutenzioni:
            if manutenzione.get("id") == manutenzione_id:
                manutenzione_trovata = manutenzione
                break
        
        if not manutenzione_trovata:
            logger.warning(f"Manutenzione non trovata: {manutenzione_id}")
            return False
        
        # Aggiorna la manutenzione
        manutenzione_trovata["data_fine_effettiva"] = datetime.now().isoformat()
        manutenzione_trovata["stato"] = "completata"
        
        # Aggiorna nella lista
        dati[KEY_MANUTENZIONI] = [
            m if m.get("id") != manutenzione_id else manutenzione_trovata 
            for m in manutenzioni
        ]
        
        self.persistence.update_data("stato_servizio", dati)
        
        # Aggiungi allo storico
        self._aggiungi_a_storico(
            azione="termina_manutenzione",
            stato=STATO_OPERATIVO,
            motivo=f"Manutenzione completata: {manutenzione_trovata.get('motivo')}",
            admin_id=None
        )
        
        # Ripristina stato a OPERATIVO se non ci sono altre manutenzioni in corso
        manutenzioni_attive = self.get_manutenzioni_attive()
        if not manutenzioni_attive:
            self.aggiorna_stato(STATO_OPERATIVO, "Manutenzione completata", None)
        
        logger.info(f"Manutenzione terminata: {manutenzione_trovata.get('motivo')}")
        
        return True
    
    def get_manutenzioni_attive(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista delle manutenzioni in corso o programmate.
        
        Returns:
            Lista delle manutenzioni attive
        """
        dati = self._get_dati()
        ora = datetime.now()
        
        attive = []
        for m in dati.get(KEY_MANUTENZIONI, []):
            if m.get("stato") in ["in_corso", "programmata"]:
                data_inizio = datetime.fromisoformat(m.get("data_inizio"))
                if m.get("stato") == "programmata" and data_inizio > ora:
                    # Manutenzione futura
                    attive.append(m)
                elif m.get("stato") == "in_corso":
                    attive.append(m)
        
        return attive
    
    def get_storico(self, limite: int = 50) -> List[Dict[str, Any]]:
        """
        Restituisce lo storico dei cambi di stato.
        
        Args:
            limite: Numero massimo di eventi da restituire
            
        Returns:
            Lista degli eventi storici (più recenti prima)
        """
        dati = self._get_dati()
        storico = dati.get(KEY_STORICO, [])
        
        # Ordina per timestamp decrescente
        storico_ordinato = sorted(storico, key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return storico_ordinato[:limite]
    
    def calcola_uptime(self) -> float:
        """
        Calcola la percentuale di uptime del servizio.
        
        Returns:
            Percentuale di uptime (0-100)
        """
        dati = self._get_dati()
        statistiche = dati.get(KEY_STATISTICHE, {})
        
        inizio_monitoraggio = statistiche.get("inizio_monitoraggio")
        if not inizio_monitoraggio:
            return 100.0
        
        try:
            inizio = datetime.fromisoformat(inizio_monitoraggio)
        except (ValueError, TypeError):
            return 100.0
        
        # Calcola tempo totale monitorato
        tempo_totale = datetime.now() - inizio
        minuti_totali = tempo_totale.total_seconds() / 60
        
        if minuti_totali <= 0:
            return 100.0
        
        # Calcola downtime totale dagli eventi di disservizio
        storico = dati.get(KEY_STORICO, [])
        downtime_minuti = 0
        
        inizio_disservizio = None
        for evento in sorted(storico, key=lambda x: x.get("timestamp", "")):
            if evento.get("azione") == "cambio_stato":
                stato = evento.get("stato")
                timestamp = evento.get("timestamp")
                
                if stato == STATO_DISSERVIZIO:
                    try:
                        inizio_disservizio = datetime.fromisoformat(timestamp)
                    except (ValueError, TypeError):
                        pass
                elif inizio_disservizio and stato != STATO_DISSERVIZIO:
                    # Fine disservizio
                    try:
                        fine = datetime.fromisoformat(timestamp)
                        downtime_minuti += (fine - inizio_disservizio).total_seconds() / 60
                    except (ValueError, TypeError):
                        pass
                    inizio_disservizio = None
        
        # Se ancora in disservizio, calcola fino ad ora
        if inizio_disservizio:
            downtime_minuti += (datetime.now() - inizio_disservizio).total_seconds() / 60
        
        uptime_percentuale = ((minuti_totali - downtime_minuti) / minuti_totali) * 100
        
        # Arrotonda a 2 decimali
        return round(max(0.0, min(100.0, uptime_percentuale)), 2)
    
    def get_info_completa(self) -> Dict[str, Any]:
        """
        Restituisce un riepilogo completo dello stato del servizio.
        
        Returns:
            Dizionario con tutte le informazioni sullo stato del servizio
        """
        return {
            "stato": self.get_stato(),
            "problemi_attivi": self.get_problemi_attivi(),
            "manutenzioni_attive": self.get_manutenzioni_attive(),
            "uptime_percentuale": self.calcola_uptime(),
            "storico": self.get_storico(10),
            "info_servizio": self._get_dati().get(KEY_STATISTICHE, {})
        }
    
    def reset_statistiche(self) -> None:
        """Resetta le statistiche di uptime (da usare con cautela)."""
        dati = self._get_dati()
        dati[KEY_STATISTICHE] = {
            "ultimo_riavvio": datetime.now().isoformat(),
            "totale_downtime_minuti": 0,
            "inizio_monitoraggio": datetime.now().isoformat()
        }
        dati[KEY_STORICO] = []
        self.persistence.update_data("stato_servizio", dati)
        
        self._aggiungi_a_storico(
            azione="reset_statistiche",
            stato=self.get_stato(),
            motivo="Statistiche resettate",
            admin_id=None
        )
        
        logger.warning("Statistiche stato servizio resettate")

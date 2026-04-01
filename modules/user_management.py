"""
Modulo per la gestione degli utenti e delle liste IPTV.
Gestisce registrazione, profili utente, liste IPTV e richieste.

Utilizza il modulo di persistenza per salvare i dati su file JSON.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

# Costanti per gli stati
STATO_ATTIVO = "attivo"
STATO_INATTIVO = "inattivo"
STATO_SOSPESO = "sospeso"
STATO_BLOCCATO = "bloccato"

# Costanti per le richieste
STATO_IN_ATTESA = "in_attesa"
STATO_APPROVATA = "approvata"
STATO_RIFIUTATA = "rifiutata"

# Costanti per le liste IPTV
TIPO_M3U = "m3u"
TIPO_M3U8 = "m3u8"
TIPO_XTREAM = "xtream"
TIPO_ALTRO = "altro"

STATO_LISTA_ATTIVA = "attiva"
STATO_LISTA_INATTIVA = "inattiva"
STATO_LISTA_SCADUTA = "scaduta"


class UserManagementError(Exception):
    """Eccezione personalizzata per errori nella gestione utenti."""
    pass


class UserManagement:
    """
    Classe per la gestione degli utenti e delle liste IPTV.
    """
    
    def __init__(self, persistence: DataPersistence):
        """
        Inizializza il gestore utenti.
        
        Args:
            persistence: Istanza del modulo di persistenza dati
        """
        self.persistence = persistence
        logger.info("Modulo UserManagement inizializzato")
    
    # ==================== GESTIONE LISTE UTENTE ====================
    
    def get_lista_utente(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene la lista IPTV associata a un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Dizionario con i dati della lista o None se non associata
        """
        try:
            utente = self.get_utente(user_id)
            if not utente:
                return None
            lista_id = utente.get("lista_approvata")
            if not lista_id:
                return None
            return self.get_lista(lista_id)
        except Exception as e:
            logger.error(f"Errore nel recupero della lista per l'utente {user_id}: {e}")
            return None
    
    # ==================== GESTIONE UTENTI ====================
    
    def registra_utente(self, user_id: str, username: str, nome: str) -> Dict[str, Any]:
        """
        Registra un nuovo utente al primo accesso.
        Se l'utente esiste già, restituisce i dati esistenti.
        
        Args:
            user_id: ID univoco dell'utente (solitamente ID Telegram)
            username: Username dell'utente
            nome: Nome completo o nome visualizzato
            
        Returns:
            Dizionario con i dati dell'utente registrato
            
        Raises:
            UserManagementError: Se la registrazione fallisce
        """
        try:
            # Verifica se l'utente esiste già
            utente_esistente = self.get_utente(user_id)
            if utente_esistente:
                logger.info(f"Utente {user_id} già registrato, restituzione dati esistenti")
                return utente_esistente
            
            # Crea nuovo utente
            nuovo_utente = {
                "id": user_id,
                "username": username,
                "nome": nome,
                "data_registrazione": datetime.now().isoformat(),
                "stato": STATO_ATTIVO,
                "lista_approvata": None,
                "data_scadenza": None,
                "ultimo_accesso": datetime.now().isoformat()
            }
            
            # Salva l'utente
            self.persistence.update_data(f"utenti.{user_id}", nuovo_utente)
            logger.info(f"Utente {username} (ID: {user_id}) registrato con successo")
            
            return nuovo_utente
            
        except Exception as e:
            logger.error(f"Errore nella registrazione dell'utente {user_id}: {e}")
            raise UserManagementError(f"Impossibile registrare l'utente: {e}")
    
    def get_utente(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene i dati di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Dizionario con i dati dell'utente o None se non trovato
        """
        try:
            utente = self.persistence.get_data(f"utenti.{user_id}")
            return utente if utente else None
        except Exception as e:
            logger.error(f"Errore nel recupero dell'utente {user_id}: {e}")
            return None
    
    def aggiorna_stato_utente(self, user_id: str, stato: str) -> bool:
        """
        Aggiorna lo stato di un utente.
        
        Args:
            user_id: ID dell'utente
            stato: Nuovo stato (attivo, inattivo, sospeso, bloccato)
            
        Returns:
            True se l'aggiornamento ha avuto successo
        """
        stati_validi = [STATO_ATTIVO, STATO_INATTIVO, STATO_SOSPESO, STATO_BLOCCATO]
        
        if stato not in stati_validi:
            logger.warning(f"Stato non valido: {stato}")
            return False
        
        try:
            utente = self.get_utente(user_id)
            if not utente:
                logger.warning(f"Utente {user_id} non trovato")
                return False
            
            utente["stato"] = stato
            self.persistence.update_data(f"utenti.{user_id}", utente)
            logger.info(f"Stato utente {user_id} aggiornato a: {stato}")
            return True
            
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento dello stato dell'utente {user_id}: {e}")
            return False
    
    def ha_lista_approvata(self, user_id: str) -> bool:
        """
        Controlla se l'utente ha una lista approvata.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'utente ha una lista approvata
        """
        try:
            utente = self.get_utente(user_id)
            if not utente:
                return False
            
            # Controlla se ha una lista e se è ancora valida
            if utente.get("lista_approvata"):
                data_scadenza = utente.get("data_scadenza")
                if data_scadenza:
                    scadenza = datetime.fromisoformat(data_scadenza)
                    if scadenza > datetime.now():
                        return True
                elif utente.get("lista_approvata"):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Errore nel controllo lista approvata per {user_id}: {e}")
            return False
    
    def aggiorna_ultimo_accesso(self, user_id: str) -> bool:
        """
        Aggiorna il timestamp dell'ultimo accesso dell'utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'aggiornamento ha avuto successo
        """
        try:
            utente = self.get_utente(user_id)
            if not utente:
                # Registra automaticamente l'utente
                self.registra_utente(user_id, f"user_{user_id}", f"Utente {user_id}")
                return True
            
            utente["ultimo_accesso"] = datetime.now().isoformat()
            self.persistence.update_data(f"utenti.{user_id}", utente)
            return True
            
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento ultimo accesso per {user_id}: {e}")
            return False
    
    def get_tutti_utenti(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista di tutti gli utenti registrati.
        
        Returns:
            Lista di dizionari con i dati degli utenti
        """
        try:
            utenti = self.persistence.get_data("utenti")
            return list(utenti.values()) if utenti else []
        except Exception as e:
            logger.error(f"Errore nel recupero degli utenti: {e}")
            return []
    
    # ==================== GESTIONE LISTE IPTV ====================
    
    def aggiungi_lista(self, nome: str, url: str, tipo: str, durata_giorni: int = 30) -> Dict[str, Any]:
        """
        Aggiunge una nuova lista IPTV.
        
        Args:
            nome: Nome della lista
            url: URL della lista (M3U, M3U8, Xtream, ecc.)
            tipo: Tipo di lista (m3u, m3u8, xtream, altro)
            durata_giorni: Durata in giorni della lista (default 30)
            
        Returns:
            Dizionario con i dati della lista creata
            
        Raises:
            UserManagementError: Se l'aggiunta della lista fallisce
        """
        tipi_validi = [TIPO_M3U, TIPO_M3U8, TIPO_XTREAM, TIPO_ALTRO]
        
        if tipo.lower() not in tipi_validi:
            logger.warning(f"Tipo lista non valido: {tipo}, utilizzo 'altro'")
            tipo = TIPO_ALTRO
        
        try:
            lista_id = str(uuid.uuid4())[:8]  # UUID breve
            
            nuova_lista = {
                "id": lista_id,
                "nome": nome,
                "url": url,
                "tipo": tipo.lower(),
                "data_aggiunta": datetime.now().isoformat(),
                "data_scadenza": (datetime.now() + timedelta(days=durata_giorni)).isoformat(),
                "stato": STATO_LISTA_ATTIVA
            }
            
            self.persistence.update_data(f"liste_iptv.{lista_id}", nuova_lista)
            logger.info(f"Lista IPTV '{nome}' (ID: {lista_id}) aggiunta con successo")
            
            return nuova_lista
            
        except Exception as e:
            logger.error(f"Errore nell'aggiunta della lista IPTV: {e}")
            raise UserManagementError(f"Impossibile aggiungere la lista: {e}")
    
    def get_lista(self, lista_id: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene i dati di una lista IPTV.
        
        Args:
            lista_id: ID della lista
            
        Returns:
            Dizionario con i dati della lista o None se non trovata
        """
        try:
            lista = self.persistence.get_data(f"liste_iptv.{lista_id}")
            return lista if lista else None
        except Exception as e:
            logger.error(f"Errore nel recupero della lista {lista_id}: {e}")
            return None
    
    def aggiorna_lista(self, lista_id: str, **kwargs) -> bool:
        """
        Aggiorna i dati di una lista IPTV.
        
        Args:
            lista_id: ID della lista
            **kwargs: Campi da aggiornare (nome, url, tipo, durata_giorni, stato)
            
        Returns:
            True se l'aggiornamento ha avuto successo
        """
        try:
            lista = self.get_lista(lista_id)
            if not lista:
                logger.warning(f"Lista {lista_id} non trovata")
                return False
            
            # Aggiorna i campi specificati
            for key, value in kwargs.items():
                if key == "durata_giorni":
                    # Ricalcola la data di scadenza
                    lista["data_scadenza"] = (datetime.now() + timedelta(days=value)).isoformat()
                elif key in ["nome", "url", "tipo", "stato"]:
                    lista[key] = value
            
            lista["data_aggiornamento"] = datetime.now().isoformat()
            self.persistence.update_data(f"liste_iptv.{lista_id}", lista)
            logger.info(f"Lista IPTV {lista_id} aggiornata")
            
            return True
            
        except Exception as e:
            logger.error(f"Errore nell'aggiornamento della lista {lista_id}: {e}")
            return False
    
    def rimuovi_lista(self, lista_id: str) -> bool:
        """
        Rimuove una lista IPTV.
        
        Args:
            lista_id: ID della lista da rimuovere
            
        Returns:
            True se la rimozione ha avuto successo
        """
        try:
            lista = self.get_lista(lista_id)
            if not lista:
                logger.warning(f"Lista {lista_id} non trovata")
                return False
            
            self.persistence.delete_data(f"liste_iptv.{lista_id}")
            logger.info(f"Lista IPTV {lista_id} rimossa")
            
            return True
            
        except Exception as e:
            logger.error(f"Errore nella rimozione della lista {lista_id}: {e}")
            return False
    
    def assegna_lista(self, user_id: str, lista_id: str) -> bool:
        """
        Assegna una lista IPTV a un utente.
        
        Args:
            user_id: ID dell'utente
            lista_id: ID della lista da assegnare
            
        Returns:
            True se l'assegnazione ha avuto successo
        """
        try:
            # Verifica utente
            utente = self.get_utente(user_id)
            if not utente:
                logger.warning(f"Utente {user_id} non trovato")
                return False
            
            # Verifica lista
            lista = self.get_lista(lista_id)
            if not lista:
                logger.warning(f"Lista {lista_id} non trovata")
                return False
            
            # Controlla se la lista è attiva
            if lista.get("stato") != STATO_LISTA_ATTIVA:
                logger.warning(f"Lista {lista_id} non è attiva")
                return False
            
            # Assegna la lista all'utente
            utente["lista_approvata"] = lista_id
            utente["data_scadenza"] = lista.get("data_scadenza")
            utente["stato"] = STATO_ATTIVO
            
            self.persistence.update_data(f"utenti.{user_id}", utente)
            logger.info(f"Lista {lista_id} assegnata all'utente {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Errore nell'assegnazione della lista {lista_id} a {user_id}: {e}")
            return False
    
    def revoca_lista(self, user_id: str) -> bool:
        """
        Revoca la lista IPTV assegnata a un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se la revoca ha avuto successo
        """
        try:
            utente = self.get_utente(user_id)
            if not utente:
                logger.warning(f"Utente {user_id} non trovato")
                return False
            
            utente["lista_approvata"] = None
            utente["data_scadenza"] = None
            
            self.persistence.update_data(f"utenti.{user_id}", utente)
            logger.info(f"Lista revocata all'utente {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Errore nella revoca della lista per {user_id}: {e}")
            return False
    
    def get_tutte_liste(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista di tutte le liste IPTV.
        
        Returns:
            Lista di dizionari con i dati delle liste
        """
        try:
            liste = self.persistence.get_data("liste_iptv")
            return list(liste.values()) if liste else []
        except Exception as e:
            logger.error(f"Errore nel recupero delle liste IPTV: {e}")
            return []
    
    def get_liste_attive(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista delle liste IPTV attive.
        
        Returns:
            Lista di dizionari con i dati delle liste attive
        """
        try:
            tutte_liste = self.get_tutte_liste()
            return [lista for lista in tutte_liste if lista.get("stato") == STATO_LISTA_ATTIVA]
        except Exception as e:
            logger.error(f"Errore nel recupero delle liste attive: {e}")
            return []
    
    # ==================== GESTIONE RICHIESTE ====================
    
    def crea_richiesta(self, user_id: str, username: str = "", nome_lista: str = "") -> Dict[str, Any]:
        """
        Crea una nuova richiesta di lista IPTV.
        
        Args:
            user_id: ID dell'utente che fa la richiesta
            nome_lista: Nome o descrizione della lista richiesta
            
        Returns:
            Dizionario con i dati della richiesta creata
            
        Raises:
            UserManagementError: Se la creazione della richiesta fallisce
        """
        try:
            # Verifica utente
            utente = self.get_utente(user_id)
            if not utente:
                # Registra automaticamente l'utente
                utente = self.registra_utente(user_id, f"user_{user_id}", f"Utente {user_id}")
            
            # Controlla se l'utente ha già una richiesta pendente
            richieste = self.get_richieste_pendenti()
            for richiesta in richieste:
                if richiesta.get("user_id") == user_id and richiesta.get("stato") == STATO_IN_ATTESA:
                    logger.warning(f"Utente {user_id} ha già una richiesta pendente")
                    raise UserManagementError("Hai già una richiesta in attesa di approvazione")
            
            richiesta_id = str(uuid.uuid4())[:8]
            
            nuova_richiesta = {
                "id": richiesta_id,
                "user_id": user_id,
                "username": utente.get("username", "sconosciuto"),
                "nome_utente": utente.get("nome", "sconosciuto"),
                "nome_lista": nome_lista,
                "stato": STATO_IN_ATTESA,
                "data_richiesta": datetime.now().isoformat(),
                "data_risposta": None,
                "admin_id": None,
                "motivo_rifiuto": None
            }
            
            # Aggiungi alla lista delle richieste
            richieste = self.persistence.get_data("richieste") or []
            richieste.append(nuova_richiesta)
            self.persistence.update_data("richieste", richieste)
            
            logger.info(f"Richiesta {richiesta_id} creata da utente {user_id}")
            
            return nuova_richiesta
            
        except UserManagementError:
            raise
        except Exception as e:
            logger.error(f"Errore nella creazione della richiesta: {e}")
            raise UserManagementError(f"Impossibile creare la richiesta: {e}")
    
    def get_richiesta(self, richiesta_id: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene i dati di una richiesta.
        
        Args:
            richiesta_id: ID della richiesta
            
        Returns:
            Dizionario con i dati della richiesta o None se non trovata
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            for richiesta in richieste:
                if richiesta.get("id") == richiesta_id:
                    return richiesta
            return None
        except Exception as e:
            logger.error(f"Errore nel recupero della richiesta {richiesta_id}: {e}")
            return None
    
    def get_richieste_pendenti(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista delle richieste in attesa.
        
        Returns:
            Lista di dizionari con i dati delle richieste pendenti
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            return [r for r in richieste if r.get("stato") == STATO_IN_ATTESA]
        except Exception as e:
            logger.error(f"Errore nel recupero delle richieste pendenti: {e}")
            return []
    
    def get_richieste_utente(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Ottiene la lista delle richieste di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Lista di dizionari con i dati delle richieste dell'utente
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            return [r for r in richieste if r.get("user_id") == user_id]
        except Exception as e:
            logger.error(f"Errore nel recupero delle richieste per {user_id}: {e}")
            return []
    
    def approva_richiesta(self, richiesta_id: str, admin_id: str) -> Tuple[bool, str]:
        """
        Approva una richiesta di lista IPTV.
        
        Args:
            richiesta_id: ID della richiesta da approvare
            admin_id: ID dell'admin che approva
            
        Returns:
            Tuple (successo, messaggio)
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            
            # Trova la richiesta
            richiesta_trovata = None
            for i, richiesta in enumerate(richieste):
                if richiesta.get("id") == richiesta_id:
                    richiesta_trovata = richiesta
                    break
            
            if not richiesta_trovata:
                return False, "Richiesta non trovata"
            
            if richiesta_trovata.get("stato") != STATO_IN_ATTESA:
                return False, f"Richiesta già processata (stato: {richiesta_trovata.get('stato')})"
            
            # Approva la richiesta
            richiesta_trovata["stato"] = STATO_APPROVATA
            richiesta_trovata["data_risposta"] = datetime.now().isoformat()
            richiesta_trovata["admin_id"] = admin_id
            
            # Aggiorna la lista delle richieste
            self.persistence.update_data("richieste", richieste)
            
            logger.info(f"Richiesta {richiesta_id} approvata da admin {admin_id}")
            
            return True, "Richiesta approvata con successo"
            
        except Exception as e:
            logger.error(f"Errore nell'approvazione della richiesta {richiesta_id}: {e}")
            return False, f"Errore nell'approvazione: {e}"
    
    def rifiuta_richiesta(self, richiesta_id: str, admin_id: str, motivo: str) -> Tuple[bool, str]:
        """
        Rifiuta una richiesta di lista IPTV.
        
        Args:
            richiesta_id: ID della richiesta da rifiutare
            admin_id: ID dell'admin che rifiuta
            motivo: Motivo del rifiuto
            
        Returns:
            Tuple (successo, messaggio)
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            
            # Trova la richiesta
            richiesta_trovata = None
            for richiesta in richieste:
                if richiesta.get("id") == richiesta_id:
                    richiesta_trovata = richiesta
                    break
            
            if not richiesta_trovata:
                return False, "Richiesta non trovata"
            
            if richiesta_trovata.get("stato") != STATO_IN_ATTESA:
                return False, f"Richiesta già processata (stato: {richiesta_trovata.get('stato')})"
            
            # Rifiuta la richiesta
            richiesta_trovata["stato"] = STATO_RIFIUTATA
            richiesta_trovata["data_risposta"] = datetime.now().isoformat()
            richiesta_trovata["admin_id"] = admin_id
            richiesta_trovata["motivo_rifiuto"] = motivo
            
            # Aggiorna la lista delle richieste
            self.persistence.update_data("richieste", richieste)
            
            logger.info(f"Richiesta {richiesta_id} rifiutata da admin {admin_id}")
            
            return True, "Richiesta rifiutata"
            
        except Exception as e:
            logger.error(f"Errore nel rifiuto della richiesta {richiesta_id}: {e}")
            return False, f"Errore nel rifiuto: {e}"
    
    def get_tutte_richieste(self) -> List[Dict[str, Any]]:
        """
        Ottiene la lista di tutte le richieste.
        
        Returns:
            Lista di dizionari con i dati delle richieste
        """
        try:
            richieste = self.persistence.get_data("richieste") or []
            return richieste
        except Exception as e:
            logger.error(f"Errore nel recupero delle richieste: {e}")
            return []
    
    # ==================== GESTIONE SCADENZE ====================
    
    def controlla_scadenze(self) -> List[Dict[str, Any]]:
        """
        Controlla le liste scadute e notifica gli utenti.
        
        Returns:
            Lista di dizionari con i dati degli utenti con liste scadute
        """
        try:
            utenti = self.get_tutti_utenti()
            utenti_scaduti = []
            now = datetime.now()
            
            for utente in utenti:
                data_scadenza = utente.get("data_scadenza")
                if data_scadenza:
                    scadenza = datetime.fromisoformat(data_scadenza)
                    if scadenza <= now:
                        # Lista scaduta, aggiorna stato
                        utente["lista_approvata"] = None
                        utente["data_scadenza"] = None
                        utente["stato"] = STATO_INATTIVO
                        
                        self.persistence.update_data(f"utenti.{utente['id']}", utente)
                        
                        utenti_scaduti.append({
                            "user_id": utente.get("id"),
                            "username": utente.get("username"),
                            "nome": utente.get("nome"),
                            "data_scadenza": data_scadenza
                        })
                        
                        logger.info(f"Lista scaduta per utente {utente.get('username')}")
            
            # Controlla anche le liste scadute
            liste = self.get_tutte_liste()
            for lista in liste:
                data_scadenza = lista.get("data_scadenza")
                if data_scadenza:
                    scadenza = datetime.fromisoformat(data_scadenza)
                    if scadenza <= now and lista.get("stato") == STATO_LISTA_ATTIVA:
                        lista["stato"] = STATO_LISTA_SCADUTA
                        self.persistence.update_data(f"liste_iptv.{lista['id']}", lista)
                        logger.info(f"Lista {lista['nome']} marcata come scaduta")
            
            if utenti_scaduti:
                logger.info(f"Trovati {len(utenti_scaduti)} utenti con liste scadute")
            
            return utenti_scaduti
            
        except Exception as e:
            logger.error(f"Errore nel controllo delle scadenze: {e}")
            return []
    
    def rinnova_lista(self, user_id: str, durata_giorni: int = 30) -> Tuple[bool, str]:
        """
        Rinnova la lista IPTV di un utente.
        
        Args:
            user_id: ID dell'utente
            durata_giorni: Durata del rinnovo in giorni
            
        Returns:
            Tuple (successo, messaggio)
        """
        try:
            utente = self.get_utente(user_id)
            if not utente:
                return False, "Utente non trovato"
            
            if not utente.get("lista_approvata"):
                return False, "Nessuna lista assegnata"
            
            # Ricalcola la data di scadenza
            nuova_scadenza = (datetime.now() + timedelta(days=durata_giorni)).isoformat()
            utente["data_scadenza"] = nuova_scadenza
            utente["stato"] = STATO_ATTIVO
            
            self.persistence.update_data(f"utenti.{user_id}", utente)
            logger.info(f"Lista rinnovata per utente {user_id} fino a {nuova_scadenza}")
            
            return True, f"Lista rinnovata per {durata_giorni} giorni"
            
        except Exception as e:
            logger.error(f"Errore nel rinnovo della lista per {user_id}: {e}")
            return False, f"Errore nel rinnovo: {e}"
    
    # ==================== METODI UTILITY ====================
    
    def get_statistiche(self) -> Dict[str, Any]:
        """
        Ottiene statistiche su utenti, liste e richieste.
        
        Returns:
            Dizionario con le statistiche
        """
        try:
            utenti = self.get_tutti_utenti()
            liste = self.get_tutte_liste()
            richieste = self.get_tutte_richieste()
            
            utenti_attivi = [u for u in utenti if u.get("stato") == STATO_ATTIVO]
            utenti_con_lista = [u for u in utenti if u.get("lista_approvata")]
            liste_attive = [l for l in liste if l.get("stato") == STATO_LISTA_ATTIVA]
            richieste_pendenti = [r for r in richieste if r.get("stato") == STATO_IN_ATTESA]
            
            return {
                "totale_utenti": len(utenti),
                "utenti_attivi": len(utenti_attivi),
                "utenti_con_lista": len(utenti_con_lista),
                "totale_liste": len(liste),
                "liste_attive": len(liste_attive),
                "totale_richieste": len(richieste),
                "richieste_pendenti": len(richieste_pendenti),
                "richieste_approvate": len([r for r in richieste if r.get("stato") == STATO_APPROVATA]),
                "richieste_rifiutate": len([r for r in richieste if r.get("stato") == STATO_RIFIUTATA])
            }
            
        except Exception as e:
            logger.error(f"Errore nel calcolo delle statistiche: {e}")
            return {}


# Funzioni di utilità per l'esportazione
def crea_istanza(persistence: DataPersistence) -> UserManagement:
    """
    Crea un'istanza del gestore utenti.
    
    Args:
        persistence: Istanza del modulo di persistenza
        
    Returns:
        Istanza di UserManagement
    """
    return UserManagement(persistence)

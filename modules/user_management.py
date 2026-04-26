"""Modulo per la gestione degli utenti e delle liste IPTV.
Gestisce registrazione, profili utente, liste IPTV e richieste.
Utilizza il modulo di persistenza per salvare i dati su file JSON.
"""

import uuid
import logging
import threading
import time
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
    Thread-safe con RLock, cache TTL 5min, indice secondario per liste.
    """

    def __init__(self, persistence: DataPersistence):
        self.persistence = persistence
        self._lock = threading.RLock()
        # Cache in memoria: user_id -> (dati, timestamp)
        self._user_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._cache_ttl = 300  # 5 minuti in secondi
        # Indice secondario per lookup liste per nome
        self._lista_name_index: Dict[str, str] = {}  # nome_lower -> lista_id
        self._metrics = {
            "cache_hits": 0,
            "cache_misses": 0,
        }
        logger.info("Modulo UserManagement inizializzato")

    # ==================== CACHE UTILITY ====================

    def _clear_expired_cache(self) -> None:
        now = time.time()
        expired = [
            uid for uid, (_, ts) in self._user_cache.items()
            if now - ts > self._cache_ttl
        ]
        for uid in expired:
            del self._user_cache[uid]

    def _invalidate_cache(self, user_id: str) -> None:
        self._user_cache.pop(user_id, None)

    def _update_cache(self, user_id: str, data: Dict[str, Any]) -> None:
        self._user_cache[user_id] = (data, time.time())

    # ==================== INDICE LISTE ====================

    def _rebuild_lista_index(self) -> None:
        with self._lock:
            self._lista_name_index.clear()
            try:
                liste = self.persistence.get_data("liste_iptv") or {}
                for lista_id, lista in liste.items():
                    nome = lista.get("nome", "").lower()
                    if nome:
                        self._lista_name_index[nome] = lista_id
            except Exception as e:
                logger.error(f"Errore nel rebuild dell'indice liste: {e}")

    def _add_to_lista_index(self, lista_id: str, nome: str) -> None:
        if nome:
            self._lista_name_index[nome.lower()] = lista_id

    def _remove_from_lista_index(self, nome: str) -> None:
        self._lista_name_index.pop(nome.lower(), None)

    # ==================== METRICHE ====================

    def get_stats(self) -> Dict[str, Any]:
        """
        Restituisce metriche del modulo.
        """
        try:
            utenti = self.persistence.get_data("utenti") or {}
            liste = self.persistence.get_data("liste_iptv") or {}
            richieste = self.persistence.get_data("richieste") or []

            utenti_attivi = sum(
                1 for u in utenti.values() if u.get("stato") == STATO_ATTIVO
            )
            utenti_con_lista = sum(
                1 for u in utenti.values() if u.get("lista_approvata")
            )
            liste_attive = sum(
                1 for l in liste.values() if l.get("stato") == STATO_LISTA_ATTIVA
            )
            richieste_pendenti = sum(
                1 for r in richieste if r.get("stato") == STATO_IN_ATTESA
            )
            richieste_approvate = sum(
                1 for r in richieste if r.get("stato") == STATO_APPROVATA
            )
            richieste_rifiutate = sum(
                1 for r in richieste if r.get("stato") == STATO_RIFIUTATA
            )

            self._clear_expired_cache()

            return {
                "totale_utenti": len(utenti),
                "utenti_attivi": utenti_attivi,
                "utenti_con_lista": utenti_con_lista,
                "totale_liste": len(liste),
                "liste_attive": liste_attive,
                "totale_richieste": len(richieste),
                "richieste_pendenti": richieste_pendenti,
                "richieste_approvate": richieste_approvate,
                "richieste_rifiutate": richieste_rifiutate,
                "cache_hits": self._metrics["cache_hits"],
                "cache_misses": self._metrics["cache_misses"],
                "cached_users": len(self._user_cache),
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo delle statistiche: {e}")
            return {}

    # ==================== GESTIONE LISTE UTENTE ====================

    def get_lista_utente(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            utente = self.get_utente(user_id)
            if not utente:
                return None
            lista_id = utente.get("lista_approvata")
            if not lista_id:
                return None
            return self.get_lista(lista_id)
        except IOError as e:
            logger.error(f"Errore IO nel recupero lista per utente {user_id}: {e}", exc_info=True)
            return None
        except ValueError as e:
            logger.error(f"Errore valore nel recupero lista per utente {user_id}: {e}", exc_info=True)
            return None
        except KeyError as e:
            logger.error(f"Errore chiave nel recupero lista per utente {user_id}: {e}", exc_info=True)
            return None

    # ==================== GESTIONE UTENTI ====================

    def registra_utente(self, user_id: str, username: str, nome: str) -> Dict[str, Any]:
        max_tentativi = 3
        for tentativo in range(max_tentativi):
            try:
                utente_esistente = self.get_utente(user_id)
                if utente_esistente:
                    logger.info(f"Utente {user_id} già registrato, restituzione dati esistenti")
                    return utente_esistente

                nuovo_utente = {
                    "id": user_id,
                    "username": username,
                    "nome": nome,
                    "data_registrazione": datetime.now().isoformat(),
                    "stato": STATO_ATTIVO,
                    "lista_approvata": None,
                    "data_scadenza": None,
                    "ultimo_accesso": datetime.now().isoformat(),
                }

                with self._lock:
                    self.persistence.update_data(f"utenti.{user_id}", nuovo_utente)
                    self._update_cache(user_id, nuovo_utente)

                logger.info(f"Utente {username} (ID: {user_id}) registrato con successo")
                return nuovo_utente

            except ValueError as e:
                logger.error(f"Errore valore nella registrazione utente {user_id} (tentativo {tentativo+1}/{max_tentativi}): {e}", exc_info=True)
                if tentativo == max_tentativi - 1:
                    raise UserManagementError(f"Impossibile registrare l'utente dopo {max_tentativi} tentativi: {e}")
                time.sleep(0.1 * (tentativo + 1))
            except KeyError as e:
                logger.error(f"Errore chiave nella registrazione utente {user_id} (tentativo {tentativo+1}/{max_tentativi}): {e}", exc_info=True)
                if tentativo == max_tentativi - 1:
                    raise UserManagementError(f"Impossibile registrare l'utente dopo {max_tentativi} tentativi: {e}")
                time.sleep(0.1 * (tentativo + 1))
            except Exception as e:
                logger.error(f"Errore imprevisto nella registrazione utente {user_id}: {e}", exc_info=True)
                raise UserManagementError(f"Impossibile registrare l'utente: {e}")

        raise UserManagementError(f"Impossibile registrare l'utente dopo {max_tentativi} tentativi")

    def get_utente(self, user_id: str) -> Optional[Dict[str, Any]]:
        self._clear_expired_cache()

        if user_id in self._user_cache:
            self._metrics["cache_hits"] += 1
            return self._user_cache[user_id][0]

        self._metrics["cache_misses"] += 1
        try:
            utente = self.persistence.get_data(f"utenti.{user_id}")
            if utente:
                self._update_cache(user_id, utente)
            return utente if utente else None
        except IOError as e:
            logger.error(f"Errore IO nel recupero utente {user_id}: {e}", exc_info=True)
            return None
        except ValueError as e:
            logger.error(f"Errore valore nel recupero utente {user_id}: {e}", exc_info=True)
            return None
        except KeyError as e:
            logger.error(f"Errore chiave nel recupero utente {user_id}: {e}", exc_info=True)
            return None

    def aggiorna_stato_utente(self, user_id: str, stato: str) -> bool:
        stati_validi = [STATO_ATTIVO, STATO_INATTIVO, STATO_SOSPESO, STATO_BLOCCATO]
        if stato not in stati_validi:
            logger.warning(f"Stato non valido: {stato}")
            return False

        try:
            with self._lock:
                utente = self.get_utente(user_id)
                if not utente:
                    logger.warning(f"Utente {user_id} non trovato")
                    return False

                utente["stato"] = stato
                self.persistence.update_data(f"utenti.{user_id}", utente)
                self._update_cache(user_id, utente)

            logger.info(f"Stato utente {user_id} aggiornato a: {stato}")
            return True
        except ValueError as e:
            logger.error(f"Errore valore nell'aggiornamento stato utente {user_id}: {e}", exc_info=True)
            return False
        except KeyError as e:
            logger.error(f"Errore chiave nell'aggiornamento stato utente {user_id}: {e}", exc_info=True)
            return False
        except IOError as e:
            logger.error(f"Errore IO nell'aggiornamento stato utente {user_id}: {e}", exc_info=True)
            return False

    def ha_lista_approvata(self, user_id: str) -> bool:
        try:
            utente = self.get_utente(user_id)
            if not utente:
                return False

            if utente.get("lista_approvata"):
                data_scadenza = utente.get("data_scadenza")
                if data_scadenza:
                    scadenza = datetime.fromisoformat(data_scadenza)
                    if scadenza > datetime.now():
                        return True
                elif utente.get("lista_approvata"):
                    return True

            return False
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nel controllo lista approvata per {user_id}: {e}", exc_info=True)
            return False

    def aggiorna_ultimo_accesso(self, user_id: str) -> bool:
        max_tentativi = 3
        for tentativo in range(max_tentativi):
            try:
                with self._lock:
                    utente = self.get_utente(user_id)
                    if not utente:
                        self.registra_utente(user_id, f"user_{user_id}", f"Utente {user_id}")
                        return True

                    utente["ultimo_accesso"] = datetime.now().isoformat()
                    self.persistence.update_data(f"utenti.{user_id}", utente)
                    self._update_cache(user_id, utente)
                return True
            except ValueError as e:
                logger.error(f"Errore valore aggiornamento accesso {user_id} (tentativo {tentativo+1}/{max_tentativi}): {e}", exc_info=True)
                if tentativo == max_tentativi - 1:
                    return False
                time.sleep(0.1 * (tentativo + 1))
            except KeyError as e:
                logger.error(f"Errore chiave aggiornamento accesso {user_id} (tentativo {tentativo+1}/{max_tentativi}): {e}", exc_info=True)
                if tentativo == max_tentativi - 1:
                    return False
                time.sleep(0.1 * (tentativo + 1))

        return False

    def get_tutti_utenti(self) -> List[Dict[str, Any]]:
        try:
            utenti = self.persistence.get_data("utenti")
            return list(utenti.values()) if utenti else []
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero degli utenti: {e}", exc_info=True)
            return []

    # ==================== GESTIONE LISTE IPTV ====================

    def aggiungi_lista(self, nome: str, url: str, tipo: str, durata_giorni: int = 30) -> Dict[str, Any]:
        tipi_validi = [TIPO_M3U, TIPO_M3U8, TIPO_XTREAM, TIPO_ALTRO]
        if tipo.lower() not in tipi_validi:
            logger.warning(f"Tipo lista non valido: {tipo}, utilizzo 'altro'")
            tipo = TIPO_ALTRO

        try:
            with self._lock:
                lista_id = str(uuid.uuid4())[:8]
                nuova_lista = {
                    "id": lista_id,
                    "nome": nome,
                    "url": url,
                    "tipo": tipo.lower(),
                    "data_aggiunta": datetime.now().isoformat(),
                    "data_scadenza": (datetime.now() + timedelta(days=durata_giorni)).isoformat(),
                    "stato": STATO_LISTA_ATTIVA,
                }
                self.persistence.update_data(f"liste_iptv.{lista_id}", nuova_lista)
                self._add_to_lista_index(lista_id, nome)

            logger.info(f"Lista IPTV '{nome}' (ID: {lista_id}) aggiunta con successo")
            return nuova_lista
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nell'aggiunta della lista IPTV: {e}", exc_info=True)
            raise UserManagementError(f"Impossibile aggiungere la lista: {e}")

    def get_lista(self, lista_id: str) -> Optional[Dict[str, Any]]:
        try:
            lista = self.persistence.get_data(f"liste_iptv.{lista_id}")
            return lista if lista else None
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero della lista {lista_id}: {e}", exc_info=True)
            return None

    def aggiorna_lista(self, lista_id: str, **kwargs) -> bool:
        try:
            with self._lock:
                lista = self.get_lista(lista_id)
                if not lista:
                    logger.warning(f"Lista {lista_id} non trovata")
                    return False

                vecchio_nome = lista.get("nome", "")
                for key, value in kwargs.items():
                    if key == "durata_giorni":
                        lista["data_scadenza"] = (datetime.now() + timedelta(days=value)).isoformat()
                    elif key in ["nome", "url", "tipo", "stato"]:
                        lista[key] = value

                lista["data_aggiornamento"] = datetime.now().isoformat()
                self.persistence.update_data(f"liste_iptv.{lista_id}", lista)

                nuovo_nome = lista.get("nome", "")
                if nuovo_nome != vecchio_nome:
                    self._remove_from_lista_index(vecchio_nome)
                    self._add_to_lista_index(lista_id, nuovo_nome)

            logger.info(f"Lista IPTV {lista_id} aggiornata")
            return True
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nell'aggiornamento della lista {lista_id}: {e}", exc_info=True)
            return False

    def rimuovi_lista(self, lista_id: str) -> bool:
        try:
            with self._lock:
                lista = self.get_lista(lista_id)
                if not lista:
                    logger.warning(f"Lista {lista_id} non trovata")
                    return False

                nome = lista.get("nome", "")
                self.persistence.delete_data(f"liste_iptv.{lista_id}")
                self._remove_from_lista_index(nome)

            logger.info(f"Lista IPTV {lista_id} rimossa")
            return True
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nella rimozione della lista {lista_id}: {e}", exc_info=True)
            return False

    def assegna_lista(self, user_id: str, lista_id: str) -> bool:
        try:
            with self._lock:
                utente = self.get_utente(user_id)
                if not utente:
                    logger.warning(f"Utente {user_id} non trovato")
                    return False

                lista = self.get_lista(lista_id)
                if not lista:
                    logger.warning(f"Lista {lista_id} non trovata")
                    return False

                if lista.get("stato") != STATO_LISTA_ATTIVA:
                    logger.warning(f"Lista {lista_id} non è attiva")
                    return False

                utente["lista_approvata"] = lista_id
                utente["data_scadenza"] = lista.get("data_scadenza")
                utente["stato"] = STATO_ATTIVO

                self.persistence.update_data(f"utenti.{user_id}", utente)
                self._update_cache(user_id, utente)

            logger.info(f"Lista {lista_id} assegnata all'utente {user_id}")
            return True
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nell'assegnazione della lista {lista_id} a {user_id}: {e}", exc_info=True)
            return False

    def revoca_lista(self, user_id: str) -> bool:
        try:
            with self._lock:
                utente = self.get_utente(user_id)
                if not utente:
                    logger.warning(f"Utente {user_id} non trovato")
                    return False

                utente["lista_approvata"] = None
                utente["data_scadenza"] = None

                self.persistence.update_data(f"utenti.{user_id}", utente)
                self._update_cache(user_id, utente)

            logger.info(f"Lista revocata all'utente {user_id}")
            return True
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nella revoca della lista per {user_id}: {e}", exc_info=True)
            return False

    def get_lista_by_name(self, nome: str) -> Optional[Dict[str, Any]]:
        try:
            nome_lower = nome.lower()
            lista_id = self._lista_name_index.get(nome_lower)
            if lista_id:
                return self.get_lista(lista_id)
            return None
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nella ricerca della lista per nome {nome}: {e}", exc_info=True)
            return None

    def assegna_lista_by_name(self, user_id: str, nome_lista: str) -> Tuple[bool, str]:
        try:
            lista = self.get_lista_by_name(nome_lista)
            if not lista:
                return False, f"Lista '{nome_lista}' non trovata"

            successo = self.assegna_lista(user_id, lista.get("id"))
            return successo, f"Lista '{nome_lista}' assegnata"
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nell'assegnazione della lista per nome a {user_id}: {e}", exc_info=True)
            return False, f"Errore: {e}"

    def get_tutte_liste(self, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            liste = self.persistence.get_data("liste_iptv")
            if not liste:
                return []
            result = list(liste.values())
            return result[:limit]
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero delle liste IPTV: {e}", exc_info=True)
            return []

    def get_liste_attive(self) -> List[Dict[str, Any]]:
        try:
            tutte_liste = self.get_tutte_liste()
            return [lista for lista in tutte_liste if lista.get("stato") == STATO_LISTA_ATTIVA]
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nel recupero delle liste attive: {e}", exc_info=True)
            return []

    # ==================== GESTIONE RICHIESTE ====================

    def crea_richiesta(self, user_id: str, username: str = "", nome_lista: str = "", tipo: str = "lista") -> Dict[str, Any]:
        try:
            utente = self.get_utente(user_id)
            if not utente:
                utente = self.registra_utente(user_id, f"user_{user_id}", f"Utente {user_id}")

            richieste = self.persistence.get_data("richieste") or []
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
                "tipo": tipo,
                "data_richiesta": datetime.now().isoformat(),
                "data_risposta": None,
                "admin_id": None,
                "motivo_rifiuto": None,
            }

            richieste.append(nuova_richiesta)
            self.persistence.update_data("richieste", richieste)

            logger.info(f"Richiesta {richiesta_id} creata da utente {user_id}")
            return nuova_richiesta
        except UserManagementError:
            raise
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nella creazione della richiesta: {e}", exc_info=True)
            raise UserManagementError(f"Impossibile creare la richiesta: {e}")

    def get_richiesta(self, richiesta_id: str) -> Optional[Dict[str, Any]]:
        try:
            richieste = self.persistence.get_data("richieste") or []
            for richiesta in richieste:
                if richiesta.get("id") == richiesta_id:
                    return richiesta
            return None
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero della richiesta {richiesta_id}: {e}", exc_info=True)
            return None

    def get_richieste_pendenti(self) -> List[Dict[str, Any]]:
        try:
            richieste = self.persistence.get_data("richieste") or []
            return [r for r in richieste if r.get("stato") == STATO_IN_ATTESA]
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero delle richieste pendenti: {e}", exc_info=True)
            return []

    def get_richieste_in_attesa(self) -> List[Dict[str, Any]]:
        return self.get_richieste_pendenti()

    def get_richieste_utente(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            richieste = self.persistence.get_data("richieste") or []
            return [r for r in richieste if r.get("user_id") == user_id]
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero delle richieste per {user_id}: {e}", exc_info=True)
            return []

    def approva_richiesta(self, richiesta_id: str, admin_id: str) -> Tuple[bool, str]:
        try:
            richieste = self.persistence.get_data("richieste") or []

            richiesta_trovata = None
            for i, richiesta in enumerate(richieste):
                if richiesta.get("id") == richiesta_id:
                    richiesta_trovata = richiesta
                    break

            if not richiesta_trovata:
                return False, "Richiesta non trovata"

            if richiesta_trovata.get("stato") != STATO_IN_ATTESA:
                return False, f"Richiesta già processata (stato: {richiesta_trovata.get('stato')})"

            richiesta_trovata["stato"] = STATO_APPROVATA
            richiesta_trovata["data_risposta"] = datetime.now().isoformat()
            richiesta_trovata["admin_id"] = admin_id

            self.persistence.update_data("richieste", richieste)

            logger.info(f"Richiesta {richiesta_id} approvata da admin {admin_id}")
            return True, "Richiesta approvata con successo"
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nell'approvazione della richiesta {richiesta_id}: {e}", exc_info=True)
            return False, f"Errore nell'approvazione: {e}"

    def rifiuta_richiesta(self, richiesta_id: str, admin_id: str, motivo: str) -> Tuple[bool, str]:
        try:
            richieste = self.persistence.get_data("richieste") or []

            richiesta_trovata = None
            for richiesta in richieste:
                if richiesta.get("id") == richiesta_id:
                    richiesta_trovata = richiesta
                    break

            if not richiesta_trovata:
                return False, "Richiesta non trovata"

            if richiesta_trovata.get("stato") != STATO_IN_ATTESA:
                return False, f"Richiesta già processata (stato: {richiesta_trovata.get('stato')})"

            richiesta_trovata["stato"] = STATO_RIFIUTATA
            richiesta_trovata["data_risposta"] = datetime.now().isoformat()
            richiesta_trovata["admin_id"] = admin_id
            richiesta_trovata["motivo_rifiuto"] = motivo

            self.persistence.update_data("richieste", richieste)

            logger.info(f"Richiesta {richiesta_id} rifiutata da admin {admin_id}")
            return True, "Richiesta rifiutata"
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nel rifiuto della richiesta {richiesta_id}: {e}", exc_info=True)
            return False, f"Errore nel rifiuto: {e}"

    def get_tutte_richieste(self) -> List[Dict[str, Any]]:
        try:
            richieste = self.persistence.get_data("richieste") or []
            return richieste
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero delle richieste: {e}", exc_info=True)
            return []

    # ==================== GESTIONE SCADENZE ====================

    def controlla_scadenze(self, batch_size: int = 100) -> List[Dict[str, Any]]:
        try:
            utenti = self.get_tutti_utenti()
            utenti_scaduti = []
            now = datetime.now()

            with self._lock:
                for i, utente in enumerate(utenti):
                    if i >= batch_size and batch_size > 0:
                        break
                    data_scadenza = utente.get("data_scadenza")
                    if data_scadenza:
                        scadenza = datetime.fromisoformat(data_scadenza)
                        if scadenza <= now:
                            # Prima imposta lista_approvata a None in modo atomico
                            utente["lista_approvata"] = None
                            utente["data_scadenza"] = None
                            utente["stato"] = STATO_INATTIVO

                            self.persistence.update_data(f"utenti.{utente['id']}", utente)
                            self._invalidate_cache(utente["id"])

                            utenti_scaduti.append({
                                "user_id": utente.get("id"),
                                "username": utente.get("username"),
                                "nome": utente.get("nome"),
                                "data_scadenza": data_scadenza,
                            })

                            logger.info(f"Lista scaduta per utente {utente.get('username')}")

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
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel controllo delle scadenze: {e}", exc_info=True)
            return []

    def rinnova_lista(self, user_id: str, durata_giorni: int = 30) -> Tuple[bool, str]:
        try:
            with self._lock:
                utente = self.get_utente(user_id)
                if not utente:
                    return False, "Utente non trovato"

                if not utente.get("lista_approvata"):
                    return False, "Nessuna lista assegnata"

                nuova_scadenza = (datetime.now() + timedelta(days=durata_giorni)).isoformat()
                utente["data_scadenza"] = nuova_scadenza
                utente["stato"] = STATO_ATTIVO

                self.persistence.update_data(f"utenti.{user_id}", utente)
                self._update_cache(user_id, utente)

            logger.info(f"Lista rinnovata per utente {user_id} fino a {nuova_scadenza}")
            return True, f"Lista rinnovata per {durata_giorni} giorni"
        except (ValueError, KeyError, IOError) as e:
            logger.error(f"Errore nel rinnovo della lista per {user_id}: {e}", exc_info=True)
            return False, f"Errore nel rinnovo: {e}"

    # ==================== GESTIONE SCADENZE - BATCH OPERATIONS ====================

    def cleanup_scadenze_batch(self, batch_size: int = 50) -> Dict[str, Any]:
        """
        Operazione batch per la pulizia delle scadenze.
        """
        risultati = {
            "utenti_disattivati": 0,
            "liste_scadute": 0,
            "errori": 0,
        }
        try:
            utenti = self.get_tutti_utenti()
            now = datetime.now()

            with self._lock:
                for i in range(0, min(len(utenti), batch_size)):
                    utente = utenti[i]
                    try:
                        data_scadenza = utente.get("data_scadenza")
                        if data_scadenza and datetime.fromisoformat(data_scadenza) <= now:
                            utente["lista_approvata"] = None
                            utente["data_scadenza"] = None
                            utente["stato"] = STATO_INATTIVO
                            self.persistence.update_data(f"utenti.{utente['id']}", utente)
                            self._invalidate_cache(utente["id"])
                            risultati["utenti_disattivati"] += 1
                    except (ValueError, KeyError):
                        risultati["errori"] += 1

                liste = self.get_tutte_liste(batch_size)
                for lista in liste:
                    try:
                        data_scadenza = lista.get("data_scadenza")
                        if data_scadenza and datetime.fromisoformat(data_scadenza) <= now:
                            if lista.get("stato") == STATO_LISTA_ATTIVA:
                                lista["stato"] = STATO_LISTA_SCADUTA
                                self.persistence.update_data(f"liste_iptv.{lista['id']}", lista)
                                risultati["liste_scadute"] += 1
                    except (ValueError, KeyError):
                        risultati["errori"] += 1

            logger.info(f"Cleanup batch: {risultati}")
            return risultati
        except Exception as e:
            logger.error(f"Errore nel cleanup batch: {e}", exc_info=True)
            return risultati

    # ==================== METODI UTILITY ====================

    def get_liste_scadute(self) -> List[Dict[str, Any]]:
        try:
            utenti = self.get_tutti_utenti()
            liste_scadute = []
            now = datetime.now()

            for utente in utenti:
                data_scadenza = utente.get("data_scadenza")
                if data_scadenza:
                    scadenza = datetime.fromisoformat(data_scadenza)
                    if scadenza <= now and utente.get("lista_approvata"):
                        liste_scadute.append({
                            "user_id": utente.get("id"),
                            "username": utente.get("username"),
                            "nome": utente.get("nome"),
                            "lista_id": utente.get("lista_approvata"),
                            "data_scadenza": data_scadenza,
                        })

            return liste_scadute
        except (IOError, ValueError, KeyError) as e:
            logger.error(f"Errore nel recupero liste scadute: {e}", exc_info=True)
            return []

    def get_statistiche(self) -> Dict[str, Any]:
        """Metodo legacy - usare get_stats()"""
        return self.get_stats()


# Funzioni di utilità per l'esportazione

def crea_istanza(persistence: DataPersistence) -> UserManagement:
    """
    Crea un'istanza del gestore utenti.
    """
    return UserManagement(persistence)

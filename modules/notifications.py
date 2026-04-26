import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable, Awaitable
from collections import deque
import time
import uuid
import copy
import os
import threading

# Costanti
MAX_QUEUE_SIZE = int(os.getenv("NOTIFICATION_MAX_QUEUE", "1000"))
MAX_LOG_ENTRIES = int(os.getenv("NOTIFICATION_MAX_LOG", "1000"))
MAX_RETRY_ATTEMPTS = int(os.getenv("NOTIFICATION_MAX_RETRY", "3"))
CALLBACK_TIMEOUT = int(os.getenv("NOTIFICATION_CALLBACK_TIMEOUT", "10"))
LOG_RETENTION_DAYS = int(os.getenv("NOTIFICATION_LOG_RETENTION", "30"))


logger = logging.getLogger(__name__)


from enum import Enum
from dataclasses import dataclass, field


class TipoNotifica(Enum):
    TICKET_SENZA_RISPOSTA = "ticket_senza_risposta"
    BACKUP_FALLITO = "backup_fallito"
    RATE_LIMIT_VIOLATO = "rate_limit_violato"
    SCADENZA_IMMINENTE = "scadenza_imminente"
    STATO_SERVIZIO = "stato_servizio"
    REPORT_GIORNALIERO = "report_giornaliero"
    GENERICA = "generica"


class PrioritaNotifica(Enum):
    CRITICA = 1
    ALTA = 2
    MEDIA = 3
    BASSA = 4


class StatoNotifica(Enum):
    IN_CODA = "in_coda"
    INVIATA = "inviata"
    FALLITA = "fallita"
    ANNULLATA = "annullata"


@dataclass
class Notifica:
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
    id: str
    user_id: int
    tipo: str
    messaggio: str
    priorità: int
    data_invio: str
    successo: bool
    errore: Optional[str] = None


class NotificheError(Exception):
    pass


class CodaPienaError(NotificheError):
    pass


class NotificaNonTrovataError(NotificheError):
    pass


class NotificationSystem:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, persistence: Any = None):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, persistence: Any = None) -> None:
        if getattr(self, "_initialized", False):
            return

        self.persistence = persistence
        self._lock = asyncio.Lock()
        self._coda_notifiche: deque = deque(maxlen=MAX_QUEUE_SIZE)
        self._notifiche_attive: Dict[str, Dict] = {}
        self._log_notifiche: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._admin_ids: List[int] = []
        self._send_callback: Optional[Callable] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._paused = False
        self._closed = False
        self.metrics = {
            "enqueued": 0,
            "sent": 0,
            "failed": 0,
            "retried": 0,
        }
        self._dead_letter_queue: deque = deque(maxlen=MAX_QUEUE_SIZE)
        self._initialized = True
        logger.info("NotificationSystem initialized")

    async def _acquire_state_lock(self) -> Any:
        return self._lock

    async def invia_notifica(
        self,
        user_id: int,
        tipo: TipoNotifica,
        messaggio: str,
        priorità: PrioritaNotifica = PrioritaNotifica.MEDIA,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        notifica_id = str(uuid.uuid4())
        notifica_dict = {
            "id": notifica_id,
            "user_id": user_id,
            "tipo": tipo.value,
            "messaggio": messaggio,
            "priorità": priorità.value,
            "stato": StatoNotifica.IN_CODA.value,
            "data_creazione": datetime.now(timezone.utc).isoformat(),
            "data_invio": None,
            "retry_count": 0,
            "errore": None,
            "metadata": copy.deepcopy(metadata) if metadata else {},
        }

        async with self._lock:
            if len(self._coda_notifiche) >= MAX_QUEUE_SIZE:
                oldest = self._coda_notifiche.popleft()
                logger.warning(f"Coda piena, rimossa notifica piu' vecchia: {oldest['id']}")
            self._coda_notifiche.append(notifica_dict)
            self._notifiche_attive[notifica_id] = notifica_dict
            self.metrics["enqueued"] += 1

        logger.debug(f"Notifica {notifica_id} accodata per user {user_id}")

        if priorità == PrioritaNotifica.CRITICA:
            asyncio.create_task(self._processa_notifica(notifica_id))

        return notifica_id

    async def _processa_notifica(self, notifica_id: str) -> bool:
        async with self._lock:
            if notifica_id not in self._notifiche_attive:
                return False
            notifica = copy.deepcopy(self._notifiche_attive[notifica_id])

        if self._paused:
            logger.warning(f"Sistema in pausa, notifica {notifica_id} in attesa")
            return False

        if self._send_callback:
            try:
                successo = await asyncio.wait_for(
                    self._send_callback(notifica["user_id"], notifica["messaggio"]),
                    timeout=CALLBACK_TIMEOUT,
                )
                if successo:
                    await self._notifica_inviata(notifica_id)
                    return True
                else:
                    await self._notifica_fallita(notifica_id, "Callback ha ritornato False")
                    return False
            except asyncio.TimeoutError:
                await self._notifica_fallita(notifica_id, f"Timeout dopo {CALLBACK_TIMEOUT}s")
                return False
            except Exception as e:
                await self._notifica_fallita(notifica_id, str(e))
                return False
        else:
            logger.warning(f"Nessun callback, notifica {notifica_id} simulata")
            await self._notifica_inviata(notifica_id)
            return True

    async def _notifica_inviata(self, notifica_id: str) -> None:
        async with self._lock:
            if notifica_id not in self._notifiche_attive:
                return
            notifica = self._notifiche_attive[notifica_id]
            notifica["stato"] = StatoNotifica.INVIATA.value
            notifica["data_invio"] = datetime.now(timezone.utc).isoformat()

            log_entry = {
                "id": notifica["id"],
                "user_id": notifica["user_id"],
                "tipo": notifica["tipo"],
                "messaggio": notifica["messaggio"],
                "priorità": notifica["priorità"],
                "data_invio": notifica["data_invio"],
                "successo": True,
                "errore": None,
            }
            self._log_notifiche.append(log_entry)
            if notifica_id in self._notifiche_attive:
                del self._notifiche_attive[notifica_id]

        self.metrics["sent"] += 1
        logger.info(f"Notifica {notifica_id} inviata a {notifica['user_id']}")
        await self._salva_stato()

    async def _notifica_fallita(self, notifica_id: str, errore: str) -> None:
        async with self._lock:
            if notifica_id not in self._notifiche_attive:
                return
            notifica = self._notifiche_attive[notifica_id]
            notifica["retry_count"] += 1
            notifica["errore"] = errore
            retry_count = notifica["retry_count"]

            if retry_count >= MAX_RETRY_ATTEMPTS:
                notifica["stato"] = StatoNotifica.FALLITA.value
                log_entry = {
                    "id": notifica["id"],
                    "user_id": notifica["user_id"],
                    "tipo": notifica["tipo"],
                    "messaggio": notifica["messaggio"],
                    "priorità": notifica["priorità"],
                    "data_invio": datetime.now(timezone.utc).isoformat(),
                    "successo": False,
                    "errore": errore,
                }
                self._log_notifiche.append(log_entry)
                if notifica_id in self._notifiche_attive:
                    del self._notifiche_attive[notifica_id]
                self._dead_letter_queue.append(copy.deepcopy(notifica))
                self.metrics["failed"] += 1
                logger.error(f"Notifica {notifica_id} fallita definitivamente, DLQ")
            else:
                notifica["stato"] = StatoNotifica.IN_CODA.value
                self._coda_notifiche.append(copy.deepcopy(notifica))
                self.metrics["retried"] += 1
                logger.warning(f"Notifica {notifica_id} fallita, retry {retry_count}/{MAX_RETRY_ATTEMPTS}")

        await self._salva_stato()

    async def processa_coda(self) -> None:
        async with self._lock:
            coda_copy = list(self._coda_notifiche)
            self._coda_notifiche.clear()

        for notifica_dict in coda_copy:
            if notifica_dict["stato"] == StatoNotifica.IN_CODA.value:
                await self._processa_notifica(notifica_dict["id"])

    async def _salva_stato(self) -> None:
        if self.persistence:
            try:
                coda_serializzata = list(self._coda_notifiche)
                await self.persistence.update_data("notification_queue", coda_serializzata)
            except Exception as e:
                logger.error(f"Errore salvataggio stato: {e}")

    async def carica_stato(self) -> None:
        if self.persistence:
            try:
                from core.data_persistence import DataPersistence
                coda_serializzata = await self.persistence.get_data("notification_queue")
                if isinstance(coda_serializzata, list):
                    async with self._lock:
                        self._coda_notifiche = deque(coda_serializzata, maxlen=MAX_QUEUE_SIZE)
                    logger.info(f"Stato carico: {len(coda_serializzata)} notifiche in coda")
            except Exception as e:
                logger.error(f"Errore caricamento stato: {e}")

    async def avvia_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Worker notifiche avviato")

    async def _worker_loop(self) -> None:
        while not self._closed:
            try:
                await self.processa_coda()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Errore nel worker loop: {e}")
                await asyncio.sleep(5)

    async def close(self) -> None:
        self._closed = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await self._salva_stato()
        logger.info("NotificationSystem chiuso")

    def pause(self) -> None:
        self._paused = True
        logger.info("NotificationSystem in pausa")

    def resume(self) -> None:
        self._paused = False
        logger.info("NotificationSystem ripreso")

    def get_queue_stats(self) -> Dict[str, int]:
        return {
            "coda_size": len(self._coda_notifiche),
            "attive": len(self._notifiche_attive),
            "log_size": len(self._log_notifiche),
            "dead_letter": len(self._dead_letter_queue),
            "paused": self._paused,
            "closed": self._closed,
        }

    def imposta_admin(self, admin_ids: List[int]) -> None:
        self._admin_ids = admin_ids
        logger.info(f"Admin impostati: {admin_ids}")

    def imposta_callback_invio(self, callback: Callable[[int, str], Awaitable[bool]]) -> None:
        self._send_callback = callback
        logger.info("Callback di invio configurata")

    async def notifica_ticket_senza_risposta(
        self, persistence: Any, ore_soglia: Optional[int] = None
    ) -> List[str]:
        if not persistence or not self._admin_ids:
            return []
        soglia = ore_soglia or getattr(self, "ore_senza_risposta", 24)
        now = datetime.now(timezone.utc)
        soglia_dt = now - timedelta(hours=soglia)
        notifica_ids = []
        try:
            ticket_data = await persistence.get_data("ticket") or {}
            for tid, ticket in ticket_data.items():
                stato = ticket.get("stato", "")
                if stato not in ("aperto", "in_lavorazione"):
                    continue
                ultimo_msg_str = ticket.get("ultimo_messaggio") or ticket.get("data_creazione", "")
                if not ultimo_msg_str:
                    continue
                try:
                    data_ultimo = datetime.fromisoformat(ultimo_msg_str.replace("Z", "+00:00"))
                    if data_ultimo < soglia_dt:
                        for aid in self._admin_ids:
                            mid = await self.invia_notifica(
                                aid,
                                TipoNotifica.TICKET_SENZA_RISPOSTA,
                                f"Ticket {tid[:8]} senza risposta da {soglia}+h",
                                PrioritaNotifica.ALTA,
                                {"ticket_id": tid},
                            )
                            notifica_ids.append(mid)
                except Exception as e:
                    logger.error(f"Errore ticket {tid}: {e}")
        except Exception as e:
            logger.error(f"Errore ticket senza risposta: {e}")
        return notifica_ids

    async def verifica_backup_fallito(
        self,
        callback_invio: Optional[Callable[[], Awaitable[bool]]] = None,
        admin_ids: Optional[List[int]] = None,
    ) -> List[str]:
        if not self._admin_ids:
            return []
        notifica_ids = []
        if callback_invio:
            try:
                ok = await asyncio.wait_for(callback_invio(), timeout=CALLBACK_TIMEOUT)
                if not ok:
                    for aid in admin_ids or self._admin_ids:
                        mid = await self.invia_notifica(
                            aid,
                            TipoNotifica.BACKUP_FALLITO,
                            "Backup fallito rilevato",
                            PrioritaNotifica.CRITICA,
                            {"errore": "callback fallita"},
                        )
                        notifica_ids.append(mid)
            except asyncio.TimeoutError:
                logger.error("Timeout verifica backup")
            except Exception as e:
                logger.error(f"Errore callback backup: {e}")
        return notifica_ids

    async def invia_report_giornaliero(
        self, persistence: Any, force: bool = False
    ) -> List[str]:
        if not persistence or not self._admin_ids:
            return []
        now = datetime.now(timezone.utc)
        _ultimo = getattr(self, "_ultimo_report", None)
        if not force and _ultimo:
            if _ultimo.date() == now.date():
                return []
        try:
            utenti = await persistence.get_data("utenti") or {}
            liste = await persistence.get_data("liste_iptv") or {}
            ticket = await persistence.get_data("ticket") or {}
            totali_u = len(utenti)
            attivi_u = sum(1 for u in utenti.values() if u.get("stato") == "attivo")
            totali_l = len(liste)
            attivi_l = sum(1 for l in liste.values() if l.get("stato") == "attiva")
            totali_t = len(ticket)
            aperti_t = sum(1 for t in ticket.values() if t.get("stato") == "aperto")
            async with self._lock:
                nc = len(self._coda_notifiche)
                no = sum(1 for l in self._log_notifiche
                        if datetime.fromisoformat(l["data_invio"].replace("Z","+00:00")).date() == now.date())
            report = f"Report: {attivi_u}/{totali_u} ut, {attivi_l}/{totali_l} ls, {aperti_t}/{totali_t} tk, {nc} coda, {no} oggi"
            notifica_ids = []
            for aid in self._admin_ids:
                mid = await self.invia_notifica(
                    aid,
                    TipoNotifica.REPORT_GIORNALIERO,
                    report,
                    PrioritaNotifica.BASSA,
                    {},
                )
                notifica_ids.append(mid)
            self._ultimo_report = now
            return notifica_ids
        except Exception as e:
            logger.error(f"Errore report: {e}")
            return []

    async def pulisci_log(self, giorni: int = LOG_RETENTION_DAYS) -> int:
        soglia = datetime.now(timezone.utc) - timedelta(days=giorni)
        async with self._lock:
            prec = len(self._log_notifiche)
            nuovi = deque(maxlen=MAX_LOG_ENTRIES)
            for l in self._log_notifiche:
                try:
                    if datetime.fromisoformat(l["data_invio"].replace("Z","+00:00")) >= soglia:
                        nuovi.append(l)
                except Exception:
                    nuovi.append(l)
            self._log_notifiche = nuovi
            rim = prec - len(self._log_notifiche)
        if rim:
            logger.info(f"Puliti {rim} log vecchi")
        return rim

    @classmethod
    def reset_instance(cls) -> None:
        import asyncio as a
        async def _r():
            async with cls._instance_lock:
                cls._instance = None
        try:
            loop = a.get_event_loop()
            if loop.is_running():
                a.run_coroutine_threadsafe(_r(), loop)
            else:
                a.run(_r())
        except RuntimeError:
            a.run(_r())
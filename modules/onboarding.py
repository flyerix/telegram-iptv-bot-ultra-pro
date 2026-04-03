"""
Modulo di onboarding guidato per nuovi utenti.
Gestisce l'introduzione del bot in 3 step interattivi.

Features:
- Onboarding in 3 step con navigazione avanti/indietro
- Messaggi interattivi con bottoni inline
- Possibilità di saltare l'onboarding
- Possibilità di rivedere l'onboarding in qualsiasi momento
- Salvataggio stato utente nella persistenza
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

# Costanti per gli step
STEP_1 = 1
STEP_2 = 2
STEP_3 = 3
MAX_STEPS = 3

# Callback data keys
CB_PREV = "onb_prev"
CB_NEXT = "onb_next"
CB_SKIP = "onb_skip"
CB_REVIEW = "onb_review"
CB_DONE = "onb_done"

# Chiavi persistenza
PERSIST_ONBOARDING = "onboarding"
PERSIST_USER_ONBOARDING = "utenti_onboarding"


class OnboardingError(Exception):
    """Eccezione personalizzata per errori nell'onboarding."""
    pass


class OnboardingStep:
    """
    Rappresenta un singolo step dell'onboarding con contenuto e pulsanti.
    """
    
    def __init__(self, step_number: int, title: str, content: str, 
                 inline_buttons: Optional[List[List[Dict[str, Any]]]] = None):
        """
        Inizializza uno step dell'onboarding.
        
        Args:
            step_number: Numero dello step (1-3)
            title: Titolo dello step
            content: Contenuto del messaggio (testo principale)
            inline_buttons: Lista di righe di bottoni inline
        """
        self.step_number = step_number
        self.title = title
        self.content = content
        self.inline_buttons = inline_buttons or []


def crea_inline_button(text: str, callback_data: str) -> Dict[str, Any]:
    """
    Crea un dizionario per un bottone inline.
    
    Args:
        text: Testo mostrato sul bottone
        callback_data: Dati callback per il bottone
        
    Returns:
        Dizionario rappresentante il bottone
    """
    return {"text": text, "callback_data": callback_data}


def crea_inline_keyboard(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Crea una inline keyboard markup per Telegram.
    
    Args:
        buttons: Lista di righe di bottoni
        
    Returns:
        Dizionario inline_keyboard markup
    """
    return {"inline_keyboard": buttons}


class OnboardingManager:
    """
    Gestore principale dell'onboarding guidato.
    Manage l'avvio, la navigazione e il completamento dell'onboarding.
    """
    
    def __init__(self, persistence: DataPersistence):
        """
        Inizializza il gestore onboarding.
        
        Args:
            persistence: Istanza del modulo di persistenza dati
        """
        self.persistence = persistence
        self._steps = self._init_steps()
        logger.info("Modulo OnboardingManager inizializzato")
    
    def _init_steps(self) -> Dict[int, OnboardingStep]:
        """
        Inizializza i 3 step dell'onboarding con i relativi contenuti.
        
        Returns:
            Dizionario step_number -> OnboardingStep
        """
        # ========== STEP 1: Cos'è il bot e cosa può fare ==========
        step1 = OnboardingStep(
            step_number=STEP_1,
            title="🎉 Benvenuto! Scopri il Bot",
            content="""👋 <b>Ciao! Benvenuto nel Bot IPTV!</b>

Questo è il tuo assistente per gestire tutto ciò che riguarda le liste IPTV in modo semplice e veloce.

<b>📋 Cosa può fare questo bot:</b>
• <b>Richiedere</b> la tua lista IPTV personale
• <b>Gestire</b> ticket di supporto per problemi tecnici
• <b>Consultare</b> FAQ con domande frequenti
• <b>Ricevere</b> aggiornamenti e notifiche importanti
• <b>e molto altro...</b>

<b>💡 Perché usare questo bot?</b>
Tutto in un unico posto: richieste, supporto e informazioni sempre disponibili 24/7!""""",
            inline_buttons=[
                [
                    crea_inline_button("⏭️ Salta onboarding", f"{CB_SKIP}"),
                    crea_inline_button("Avanti ➡️", f"{CB_NEXT}")
                ]
            ]
        )
        
        # ========== STEP 2: Come richiedere la lista IPTV ==========
        step2 = OnboardingStep(
            step_number=STEP_2,
            title="📺 Come ottenere la tua lista IPTV",
            content="""<b>📺 Come ottenere la tua lista IPTV</b>

La procedura per ottenere la tua lista IPTV è semplicissima:

<b>1️⃣ Invia la richiesta</b>
Usa il comando <code>/richiedi</code> per inviare una richiesta agli admin.

<b>2️⃣ Gli admin ti contatteranno</b>
Un admin verificherà la tua richiesta e ti contatterà privatamente per fornirti i dettagli della lista.

<b>3️⃣ Ricevi la tua lista</b>
Una volta approvata, riceverai l'URL della tua lista IPTV personalizzata.

<b>⏱️ Tempi di elaborazione</b>
• Richieste normali: 1-24 ore
• In caso di urgenze, aprendo un ticket la priorità sarà più alta

<b>💡 Consiglio:</b>
Se hai bisogno urgente della lista, usa <code>/ticket</code> e seleziona priorità Alta!""",
            inline_buttons=[
                [
                    crea_inline_button("⬅️ Indietro", f"{CB_PREV}"),
                    crea_inline_button("⏭️ Salta", f"{CB_SKIP}")
                ],
                [
                    crea_inline_button("Avanti ➡️", f"{CB_NEXT}")
                ]
            ]
        )
        
        # ========== STEP 3: Ticket, FAQ e funzioni principali ==========
        step3 = OnboardingStep(
            step_number=STEP_3,
            title="🎫 Ticket, FAQ e altre funzioni",
            content="""<b>🎫 Supporto e funzioni extra</b>

<b>📝 Ticket di supporto</b>
Hai un problema tecnico? Usa il comando <code>/ticket</code> per:
• Aprire un ticket con descrizione del problema
• Ottenere priorità automatica basata sulla gravità
• Tracciare lo stato del ticket
• Ricevere aggiornamenti automatici

<b>❓ FAQ - Domande Frequenti</b>
Prima di aprire un ticket, consulta le FAQ:
• Comando <code>/faq</code> per vedere tutte le domande
• Usa i bottoni per navigare tra le categorie
• Trova risposte a problemi comuni

<b>🔧 Altre funzioni utili</b>
• <code>/lista</code> - Visualizza la tua lista attuale
• <code>/stato</code> - Controlla lo stato della richiesta
• <code>/help</code> - Mostra tutti i comandi disponibili
• <code>/start</code> - Rivedi questo onboarding

<b>✅ Pronto a iniziare!</b>
Sei equipaggiato con tutto ciò che ti serve. Buon utilizzo! 🎉""",
            inline_buttons=[
                [
                    crea_inline_button("⬅️ Indietro", f"{CB_PREV}")
                ],
                [
                    crea_inline_button("✅ Completa onboarding", f"{CB_DONE}")
                ]
            ]
        )
        
        return {
            STEP_1: step1,
            STEP_2: step2,
            STEP_3: step3
        }
    
    def inizia_onboarding(self, user_id: str, username: str, 
                          nome: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Avvia l'onboarding per un nuovo utente.
        
        Args:
            user_id: ID dell'utente
            username: Username dell'utente
            nome: Nome dell'utente
            
        Returns:
            Tupla (messaggio, inline_keyboard)
        """
        logger.info(f"Avvio onboarding per utente {user_id} ({username})")
        
        # Salva lo stato iniziale dell'onboarding
        self._salva_stato(user_id, STEP_1)
        
        # Genera il messaggio per lo step 1
        return self.genera_messaggio_step(STEP_1, username)
    
    def get_step(self, user_id: str) -> int:
        """
        Ottiene lo step attuale dell'onboarding per l'utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Numero dello step attuale (1-3), 0 se non in onboarding
        """
        stato = self._carica_stato(user_id)
        if stato:
            return stato.get("step", 0)
        return 0
    
    def prossimo_step(self, user_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Avanza allo step successivo dell'onboarding.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Tupla (messaggio, inline_keyboard) o (None, None) se è l'ultimo step
        """
        current_step = self.get_step(user_id)
        
        if current_step >= MAX_STEPS:
            logger.info(f"Utente {user_id} ha già completato l'onboarding")
            return None, None
        
        new_step = current_step + 1
        self._salva_stato(user_id, new_step)
        
        logger.info(f"Utente {user_id} avanza allo step {new_step}")
        return self.genera_messaggio_step(new_step)
    
    def precedente_step(self, user_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Torna allo step precedente dell'onboarding.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Tupla (messaggio, inline_keyboard) o (None, None) se è il primo step
        """
        current_step = self.get_step(user_id)
        
        if current_step <= 1:
            logger.info(f"Utente {user_id} è già al primo step")
            return None, None
        
        new_step = current_step - 1
        self._salva_stato(user_id, new_step)
        
        logger.info(f"Utente {user_id} torna allo step {new_step}")
        return self.genera_messaggio_step(new_step)
    
    def salta_onboarding(self, user_id: str) -> str:
        """
        Salta completamente l'onboarding.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Messaggio di conferma
        """
        logger.info(f"Utente {user_id} salta l'onboarding")
        
        # Segna come completato
        self._salva_stato_completato(user_id)
        
        return """✅ <b>Onboarding saltato</b>

Sei un utente esperto! Puoi iniziare subito a usare il bot.

<i>Ricorda: puoi sempre rivedere questa guida iniziale in qualsiasi momento con il comando /start</i>

<b>Comandi rapidi:</b>
• /richiedi - Richiedi lista IPTV
• /ticket - Apri un ticket
• /faq - Leggi le FAQ
• /help - Mostra tutti i comandi"""
    
    def rivedi_onboarding(self, user_id: str, username: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Ricomincia l'onboarding da capo.
        
        Args:
            user_id: ID dell'utente
            username: Username dell'utente
            
        Returns:
            Tupla (messaggio, inline_keyboard)
        """
        logger.info(f"Utente {user_id} rivede l'onboarding")
        
        # Reset e riparti da step 1
        self._salva_stato(user_id, STEP_1)
        
        return self.genera_messaggio_step(STEP_1, username)
    
    def is_onboarding_completato(self, user_id: str) -> bool:
        """
        Verifica se l'onboarding è stato completato.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            True se l'onboarding è stato completato
        """
        stato = self._carica_stato(user_id)
        if stato:
            return stato.get("completato", False)
        return True  # Se non c'è stato, consideriamo completato
    
    def completa_onboarding(self, user_id: str) -> str:
        """
        Completa l'onboarding e restituisce il messaggio finale.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Messaggio di completamento
        """
        logger.info(f"Utente {user_id} completa l'onboarding")
        
        # Segna come completato
        self._salva_stato_completato(user_id)
        
        return """🎉 <b>Onboarding completato!</b>

Benvenuto nel team! Ora sai come:
• Richiedere la tua lista IPTV
• Usare i ticket di supporto
• Consultare le FAQ

<b>I prossimi passi:</b>
1. Usa <code>/richiedi</code> per richiedere la tua lista
2. In caso di problemi, usa <code>/ticket</code>
3. Consulta <code>/faq</code> per dubbi comuni

<b>⚡Nota:</b>
Ricorda che puoi rivedere questa guida in qualsiasi momento con <code>/start</code>

Buon divertimento! 🚀"""
    
    def genera_messaggio_step(self, step_number: int, 
                               username: str = "") -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Genera il messaggio per uno step specifico.
        
        Args:
            step_number: Numero dello step (1-3)
            username: Username dell'utente (opzionale)
            
        Returns:
            Tupla (messaggio di testo, inline_keyboard)
            
        Raises:
            OnboardingError: Se step_number non valido
        """
        if step_number < 1 or step_number > MAX_STEPS:
            raise OnboardingError(f"Step number invalido: {step_number}")
        
        step = self._steps[step_number]
        
        # Costruisci messaggio con indicatore step
        indicatore = f"📍 <b>Step {step_number}/{MAX_STEPS}</b>\n\n"
        messaggio = indicatore + step.content
        
        # Costruisci inline keyboard
        keyboard = None
        if step.inline_buttons:
            keyboard = crea_inline_keyboard(step.inline_buttons)
        
        # Aggiungi navigation bar se non presente
        if not keyboard:
            logger.debug("Nessuna inline_keyboard definita per lo step")
        
        return messaggio, keyboard
    
    def reset_onboarding(self, user_id: str) -> None:
        """
        Reset dell'onboarding per un utente (es. per riabilitarlo).
        
        Args:
            user_id: ID dell'utente
        """
        logger.info(f"Reset onboarding per utente {user_id}")
        
        # Rimuovi lo stato
        self._rimuovi_stato(user_id)
    
    def process_callback(self, callback_data: str, user_id: str, 
                       username: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool]:
        """
        Processa un callback dall inline keyboard.
        
        Args:
            callback_data: Dati callback dal bottone
            user_id: ID dell'utente
            username: Username dell'utente
            
        Returns:
            Tupla (messaggio, inline_keyboard, bool_completato)
        """
        logger.info(f"Processo callback '{callback_data}' per utente {user_id}")
        
        if callback_data == CB_PREV:
            msg, kb = self.precedente_step(user_id)
            return msg, kb, False
        elif callback_data == CB_NEXT:
            # Se siamo al MAX_STEPS, significa completamento
            if self.get_step(user_id) >= MAX_STEPS:
                msg = self.completa_onboarding(user_id)
                return msg, None, True
            else:
                msg, kb = self.prossimo_step(user_id)
                return msg, kb, False
        elif callback_data == CB_SKIP:
            msg = self.salta_onboarding(user_id)
            return msg, None, True
        elif callback_data == CB_DONE:
            msg = self.completa_onboarding(user_id)
            return msg, None, True
        elif callback_data == CB_REVIEW:
            msg, kb = self.rivedi_onboarding(user_id, username)
            return msg, kb, False
        else:
            logger.warning(f"Callback sconosciuto: {callback_data}")
            return None, None, False
    
    def _salva_stato(self, user_id: str, step: int) -> None:
        """
        Salva lo stato corrente dell'onboarding per l'utente.
        
        Args:
            user_id: ID dell'utente
            step: Step attuale
        """
        try:
            stato = {
                "step": step,
                "timestamp": datetime.now().isoformat()
            }
            self.persistence.update_data(f"{PERSIST_USER_ONBOARDING}.{user_id}", stato)
            logger.debug(f"Stato onboarding salvato per {user_id}: step {step}")
        except Exception as e:
            logger.error(f"Errore salvataggio stato: {e}")
            raise OnboardingError(f"Impossibile salvare stato: {e}")
    
    def _carica_stato(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Carica lo stato dell'onboarding per l'utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Dizionario stato o None
        """
        try:
            return self.persistence.get_data(f"{PERSIST_USER_ONBOARDING}.{user_id}")
        except Exception as e:
            logger.debug(f"Nessuno stato trovato per {user_id}: {e}")
            return None
    
    def _salva_stato_completato(self, user_id: str) -> None:
        """
        Salva lo stato come completato.
        
        Args:
            user_id: ID dell'utente
        """
        try:
            stato = {
                "step": MAX_STEPS,
                "completato": True,
                "timestamp": datetime.now().isoformat()
            }
            self.persistence.update_data(f"{PERSIST_USER_ONBOARDING}.{user_id}", stato)
            logger.info(f"Onboarding completato per {user_id}")
        except Exception as e:
            logger.error(f"Errore salvataggio completamento: {e}")
            raise OnboardingError(f"Impossibile salvare completamento: {e}")
    
    def _rimuovi_stato(self, user_id: str) -> None:
        """
        Rimuove lo stato dell'onboarding per l'utente.
        
        Args:
            user_id: ID dell'utente
        """
        try:
            # Imposta come non in onboarding (step 0 e non completato)
            stato = {
                "step": 0,
                "completato": True,  # Considerato già completato/non necessario
                "timestamp": datetime.now().isoformat()
            }
            self.persistence.update_data(f"{PERSIST_USER_ONBOARDING}.{user_id}", stato)
            logger.info(f"Stato onboarding rimosso per {user_id}")
        except Exception as e:
            logger.warning(f"Errore rimozione stato: {e}")


# Per retrocompatibilità
def inizia_onboarding(user_id: str, username: str, nome: str) -> Tuple[str, Dict[str, Any]]:
    """
   Funzione di utilità per avviare l'onboarding (retrocompatibilità).
    
    Args:
        user_id: ID dell'utente
        username: Username dell'utente
        nome: Nome dell'utente
        
    Returns:
        Tupla (messaggio, inline_keyboard)
    """
    # Questa funzione richiede un'istanza di OnboardingManager
    # Per retrocompatibilità, crea una funzione wrapper
    pass


# Esporta le classi e costanti principali
__all__ = [
    "OnboardingManager",
    "OnboardingStep", 
    "OnboardingError",
    "STEP_1",
    "STEP_2", 
    "STEP_3",
    "MAX_STEPS",
    "CB_PREV",
    "CB_NEXT",
    "CB_SKIP",
    "CB_REVIEW",
    "CB_DONE",
    "crea_inline_button",
    "crea_inline_keyboard"
]
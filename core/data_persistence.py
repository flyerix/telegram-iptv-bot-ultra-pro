"""
Modulo di persistenza dei dati per il bot HelperBot.
Gestisce il caricamento e il salvataggio dei dati su file JSON in modo thread-safe.
"""

import json
import os
import threading
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from datetime import datetime

# Configurazione del logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Costanti
DATA_DIR = Path("data")
DEFAULT_DATA_FILE = "database.json"
AUTO_SAVE = True  # Salva automaticamente dopo ogni modifica


class DataPersistenceError(Exception):
    """Eccezione personalizzata per errori di persistenza dei dati."""
    pass


class DataPersistence:
    """
    Classe per la gestione della persistenza dei dati.
    Implementa funzionalità thread-safe per la lettura e scrittura dei dati.
    """
    
    # Struttura dati predefinita
    DEFAULT_STRUCTURE: Dict[str, Any] = {
        "utenti": {},
        "liste_iptv": {},
        "richieste": [],
        "ticket": {},
        "rate_limits": {},
        "impostazioni": {},
        "stato_servizio": {},
        "manutenzione": {},
        "faq": {}
    }
    
    def __init__(self, data_dir: Union[str, Path] = DATA_DIR, 
                 auto_save: bool = AUTO_SAVE):
        """
        Inizializza il gestore di persistenza dei dati.
        
        Args:
            data_dir: Directory dove sono salvati i file JSON
            auto_save: Se True, salva automaticamente dopo ogni modifica
        """
        self.data_dir = Path(data_dir)
        self.auto_save = auto_save
        self.data_file = self.data_dir / DEFAULT_DATA_FILE
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._initialized = False
        
        # Crea la directory dei dati se non esiste
        self._ensure_data_dir()
        
        # Carica i dati all'avvio
        self.load_data()
    
    def _ensure_data_dir(self) -> None:
        """Crea la directory dei dati se non esiste."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Directory dati verificata: {self.data_dir}")
        except Exception as e:
            logger.error(f"Errore nella creazione della directory dati: {e}")
            raise DataPersistenceError(f"Impossibile creare la directory dati: {e}")
    
    def _get_default_structure(self) -> Dict[str, Any]:
        """Restituisce una copia della struttura dati predefinita."""
        import copy
        return copy.deepcopy(self.DEFAULT_STRUCTURE)
    
    def load_data(self) -> Dict[str, Any]:
        """
        Carica tutti i dati dal file JSON.
        
        Returns:
            Dizionario contenente tutti i dati caricati
            
        Raises:
            DataPersistenceError: Se il caricamento fallisce
        """
        with self._lock:
            try:
                if self.data_file.exists():
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
                    
                    # Unisci con la struttura predefinita per garantire tutte le chiavi
                    self._data = self._get_default_structure()
                    self._merge_data(self._data, loaded_data)
                    
                    logger.info(f"Dati caricati successfully da {self.data_file}")
                    logger.info(f"Chiavi caricate: {list(self._data.keys())}")
                else:
                    # Crea un nuovo file con la struttura predefinita
                    self._data = self._get_default_structure()
                    self._save_to_file()
                    logger.info(f"Creato nuovo file dati: {self.data_file}")
                
                self._initialized = True
                return self._data.copy()
                
            except json.JSONDecodeError as e:
                logger.error(f"Errore nel parsing JSON: {e}")
                # Backup del file corrotto
                self._backup_corrupted_file()
                # Ricrea con struttura predefinita
                self._data = self._get_default_structure()
                self._save_to_file()
                return self._data.copy()
                
            except IOError as e:
                logger.error(f"Errore di I/O durante il caricamento: {e}")
                raise DataPersistenceError(f"Impossibile caricare i dati: {e}")
    
    def _merge_data(self, default: Dict, loaded: Dict) -> None:
        """Unisce i dati caricati con la struttura predefinita."""
        for key in default.keys():
            if key in loaded:
                if isinstance(default[key], dict) and isinstance(loaded[key], dict):
                    default[key].update(loaded[key])
                elif isinstance(default[key], list) and isinstance(loaded[key], list):
                    default[key] = loaded[key]
                else:
                    default[key] = loaded[key]
    
    def _backup_corrupted_file(self) -> None:
        """Crea un backup del file JSON corrotto."""
        try:
            if self.data_file.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = self.data_dir / f"database_backup_{timestamp}.json"
                import shutil
                shutil.copy2(self.data_file, backup_file)
                logger.warning(f"Creato backup del file corrotto: {backup_file}")
        except Exception as e:
            logger.error(f"Errore nella creazione del backup: {e}")
    
    def _save_to_file(self) -> None:
        """
        Salva i dati su file JSON (metodo interno con lock).
        
        Raises:
            DataPersistenceError: Se il salvataggio fallisce
        """
        try:
            # Scrittura atomica: scrive su file temporaneo poi rinomina
            temp_file = self.data_file.with_suffix('.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
            
            # Sostituisci il file originale con quello temporaneo
            temp_file.replace(self.data_file)
            logger.debug(f"Dati salvati successfully su {self.data_file}")
            
        except IOError as e:
            logger.error(f"Errore di I/O durante il salvataggio: {e}")
            # Rimuovi il file temporaneo se esiste
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            raise DataPersistenceError(f"Impossibile salvare i dati: {e}")
    
    def save_data(self) -> bool:
        """
        Salva tutti i dati su file JSON.
        
        Returns:
            True se il salvataggio ha avuto successo, False altrimenti
        """
        with self._lock:
            try:
                self._save_to_file()
                logger.info("Dati salvati manualmente")
                return True
            except DataPersistenceError as e:
                logger.error(f"Errore nel salvataggio: {e}")
                return False
    
    def get_data(self, key: Optional[str] = None, 
                 default: Any = None) -> Any:
        """
        Ottiene un dato specifico o tutti i dati.
        
        Args:
            key: Chiave del dato da ottenere. Se None, restituisce tutti i dati.
            default: Valore di default se la chiave non esiste
            
        Returns:
            Il dato richiesto o il valore di default
        """
        with self._lock:
            if key is None:
                return self._data.copy()
            
            # Supporta chiavi annidate con notazione punto (es. "utenti.user123")
            if '.' in key:
                return self._get_nested_value(key, default)
            
            return self._data.get(key, default)
    
    def _get_nested_value(self, key: str, default: Any) -> Any:
        """Ottiene un valore da una chiave annidata."""
        keys = key.split('.')
        value = self._data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def update_data(self, key: str, value: Any, 
                    auto_save: Optional[bool] = None) -> bool:
        """
        Aggiorna un dato specifico.
        
        Args:
            key: Chiave del dato da aggiornare
            value: Nuovo valore
            auto_save: Override per il comportamento di salvataggio automatico
            
        Returns:
            True se l'aggiornamento ha avuto successo
        """
        with self._lock:
            try:
                # Supporta chiavi annidate con notazione punto
                if '.' in key:
                    self._set_nested_value(key, value)
                else:
                    if key not in self._data:
                        logger.warning(f"Chiave '{key}' non presente nella struttura dati")
                        # Aggiungi la chiave comunque
                    self._data[key] = value
                
                logger.debug(f"Aggiornato dato: {key}")
                
                # Salva automaticamente se abilitato
                should_save = auto_save if auto_save is not None else self.auto_save
                if should_save:
                    self._save_to_file()
                
                return True
                
            except Exception as e:
                logger.error(f"Errore nell'aggiornamento del dato '{key}': {e}")
                return False
    
    def _set_nested_value(self, key: str, value: Any) -> None:
        """Imposta un valore per una chiave annidata."""
        keys = key.split('.')
        data = self._data
        
        # Naviga fino al penultimo livello
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]
        
        # Imposta il valore finale
        data[keys[-1]] = value
    
    def delete_data(self, key: str, auto_save: Optional[bool] = None) -> bool:
        """
        Elimina un dato specifico.
        
        Args:
            key: Chiave del dato da eliminare
            auto_save: Override per il comportamento di salvataggio automatico
            
        Returns:
            True se l'eliminazione ha avuto successo
        """
        with self._lock:
            try:
                if '.' in key:
                    self._delete_nested_value(key)
                else:
                    if key in self._data:
                        del self._data[key]
                
                logger.debug(f"Eliminato dato: {key}")
                
                # Salva automaticamente se abilitato
                should_save = auto_save if auto_save is not None else self.auto_save
                if should_save:
                    self._save_to_file()
                
                return True
                
            except Exception as e:
                logger.error(f"Errore nell'eliminazione del dato '{key}': {e}")
                return False
    
    def _delete_nested_value(self, key: str) -> None:
        """Elimina un valore da una chiave annidata."""
        keys = key.split('.')
        data = self._data
        
        # Naviga fino al penultimo livello
        for k in keys[:-1]:
            if k not in data:
                return
            data = data[k]
        
        # Elimina il valore finale
        if keys[-1] in data:
            del data[keys[-1]]
    
    def get_all_keys(self) -> list:
        """
        Restituisce tutte le chiavi dei dati principali.
        
        Returns:
            Lista delle chiavi disponibili
        """
        with self._lock:
            return list(self._data.keys())
    
    def exists(self, key: str) -> bool:
        """
        Verifica se una chiave esiste nei dati.
        
        Args:
            key: Chiave da verificare
            
        Returns:
            True se la chiave esiste
        """
        with self._lock:
            if '.' in key:
                try:
                    value = self._get_nested_value(key, None)
                    return value is not None
                except Exception:
                    return False
            return key in self._data
    
    def clear_all_data(self, auto_save: bool = True) -> bool:
        """
        Ripristina tutti i dati alla struttura predefinita.
        
        Args:
            auto_save: Se True, salva automaticamente dopo il ripristino
            
        Returns:
            True se l'operazione ha avuto successo
        """
        with self._lock:
            self._data = self._get_default_structure()
            
            if auto_save:
                try:
                    self._save_to_file()
                    logger.info("Dati ripristinati alla struttura predefinita")
                except DataPersistenceError:
                    return False
            
            return True
    
    def reload_data(self) -> Dict[str, Any]:
        """
        Ricarica i dati dal file, scartando le modifiche non salvate.
        
        Returns:
            Dizionario contenente i dati ricaricati
        """
        return self.load_data()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Restituisce statistiche sui dati salvati.
        
        Returns:
            Dizionario con le statistiche
        """
        with self._lock:
            stats = {
                "file_path": str(self.data_file),
                "file_exists": self.data_file.exists(),
                "initialized": self._initialized,
                "auto_save": self.auto_save,
                "keys": {}
            }
            
            for key, value in self._data.items():
                if isinstance(value, dict):
                    stats["keys"][key] = f"{len(value)} elementi"
                elif isinstance(value, list):
                    stats["keys"][key] = f"{len(value)} elementi"
                else:
                    stats["keys"][key] = type(value).__name__
            
            return stats
    
    def __enter__(self) -> 'DataPersistence':
        """Context manager - entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager - exit."""
        if self.auto_save:
            self.save_data()


# Istanza globale del gestore di persistenza
_persistence_instance: Optional[DataPersistence] = None
_instance_lock = threading.Lock()


def get_persistence(data_dir: Union[str, Path] = DATA_DIR, 
                    auto_save: bool = AUTO_SAVE) -> DataPersistence:
    """
    Ottiene l'istanza singleton del gestore di persistenza.
    
    Args:
        data_dir: Directory dei dati
        auto_save: Salvataggio automatico
        
    Returns:
        Istanza di DataPersistence
    """
    global _persistence_instance
    
    if _persistence_instance is None:
        with _instance_lock:
            if _persistence_instance is None:
                _persistence_instance = DataPersistence(data_dir, auto_save)
    
    return _persistence_instance


def load_data() -> Dict[str, Any]:
    """
    Funzione di convenienza per caricare i dati.
    
    Returns:
        Dizionario con tutti i dati
    """
    return get_persistence().load_data()


def save_data() -> bool:
    """
    Funzione di convenienza per salvare i dati.
    
    Returns:
        True se il salvataggio ha avuto successo
    """
    return get_persistence().save_data()


def get_data(key: Optional[str] = None, default: Any = None) -> Any:
    """
    Funzione di convenienza per ottenere un dato.
    
    Args:
        key: Chiave del dato (opzionale)
        default: Valore di default
        
    Returns:
        Il dato richiesto
    """
    return get_persistence().get_data(key, default)


def update_data(key: str, value: Any, auto_save: Optional[bool] = None) -> bool:
    """
    Funzione di convenienza per aggiornare un dato.
    
    Args:
        key: Chiave del dato
        value: Nuovo valore
        auto_save: Override salvataggio automatico
        
    Returns:
        True se l'aggiornamento ha avuto successo
    """
    return get_persistence().update_data(key, value, auto_save)


def delete_data(key: str, auto_save: Optional[bool] = None) -> bool:
    """
    Funzione di convenienza per eliminare un dato.
    
    Args:
        key: Chiave del dato
        auto_save: Override salvataggio automatico
        
    Returns:
        True se l'eliminazione ha avuto successo
    """
    return get_persistence().delete_data(key, auto_save)


# Esempio di utilizzo
if __name__ == "__main__":
    # Test del modulo
    print("Test del modulo DataPersistence")
    print("-" * 40)
    
    # Crea un'istanza
    db = DataPersistence()
    
    # Aggiungi alcuni dati di test
    db.update_data("utenti.test_user", {"nome": "Test", "eta": 25})
    db.update_data("impostazioni.lingua", "it")
    
    # Leggi i dati
    print(f"Utenti: {db.get_data('utenti')}")
    print(f"Impostazioni: {db.get_data('impostazioni')}")
    print(f"Tutti i dati: {db.get_all_keys()}")
    
    # Statistiche
    print(f"Statistiche: {db.get_statistics()}")
    
    print("-" * 40)
    print("Test completato!")

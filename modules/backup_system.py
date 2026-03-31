"""
Modulo di backup per HelperBot.
Gestisce backup locali e remoti su Google Drive.

Caratteristiche:
- Backup locali automatici (ogni 24 ore) e manuali
- Conservazione ultimi 7 backup locali
- Upload automatico su Google Drive
- Download e ripristino da Drive
- Gestione sicura delle credenziali
"""

import json
import os
import shutil
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from threading import Lock
import glob

# Configurazione logger
logger = logging.getLogger(__name__)

# Costanti di configurazione
BACKUP_DIR = Path("backups")
DRIVE_TEMP_DIR = Path("drive_backup")
DATA_FILE = Path("data/database.json")
MAX_LOCAL_BACKUPS = 7
BACKUP_INTERVAL_HOURS = 24
DRIVE_FOLDER_NAME = "HelperBot Backups"

# File credenziali Google Drive
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
SCOPES = ['https://www.googleapis.com/auth/drive.file']


class BackupError(Exception):
    """Eccezione personalizzata per errori di backup."""
    pass


class DriveNotConfiguredError(BackupError):
    """Eccezione quando Google Drive non è configurato."""
    pass


class BackupSystem:
    """
    Sistema di backup completo per HelperBot.
    Gestisce backup locali e remoti su Google Drive.
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """Singleton pattern per garantire una sola istanza."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Inizializza il sistema di backup."""
        # Evita re-inizializzazione
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.backup_dir = BACKUP_DIR
        self.drive_temp_dir = DRIVE_TEMP_DIR
        self.data_file = DATA_FILE
        self.max_backups = MAX_LOCAL_BACKUPS
        self.backup_interval = BACKUP_INTERVAL_HOURS
        
        # Stato backup automatico
        self._last_auto_backup: Optional[datetime] = None
        self._auto_backup_enabled = False
        
        # Client Google Drive
        self._drive_service = None
        self._drive_folder_id = None
        
        # Inizializzazione directory
        self._ensure_directories()
        
        self._initialized = True
        logger.info("Sistema di backup inizializzato")
    
    def _ensure_directories(self) -> None:
        """Crea le directory necessarie se non esistono."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            self.drive_temp_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Directory backup create/verificate: {self.backup_dir}, {self.drive_temp_dir}")
        except Exception as e:
            logger.error(f"Errore nella creazione delle directory: {e}")
            raise BackupError(f"Impossibile creare le directory di backup: {e}")
    
    # ==================== BACKUP LOCALI ====================
    
    def crea_backup(self, nome_file: Optional[str] = None) -> Tuple[bool, str]:
        """
        Crea un backup locale del database.
        
        Args:
            nome_file: Nome personalizzato per il file di backup (opzionale)
                       Se non fornito, usa il formato automatico backup_YYYYMMDD_HHMMSS.json
        
        Returns:
            Tuple[bool, str]: (successo, messaggio/percorso)
        """
        try:
            # Verifica che il file dati esista
            if not self.data_file.exists():
                return False, f"File dati non trovato: {self.data_file}"
            
            # Genera nome file con timestamp
            if nome_file is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                nome_file = f"backup_{timestamp}.json"
            elif not nome_file.endswith('.json'):
                nome_file += ".json"
            
            backup_path = self.backup_dir / nome_file
            
            # Leggi dati correnti
            with open(self.data_file, 'r', encoding='utf-8') as src:
                data = json.load(src)
            
            # Aggiungi metadati al backup
            backup_data = {
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "original_file": str(self.data_file),
                    "version": "1.0"
                },
                "data": data
            }
            
            # Scrivi backup
            with open(backup_path, 'w', encoding='utf-8') as dst:
                json.dump(backup_data, dst, indent=2, ensure_ascii=False)
            
            logger.info(f"Backup locale creato: {backup_path}")
            
            # Elimina backup vecchi automaticamente
            self.elimina_backup_vecchi()
            
            return True, str(backup_path)
            
        except Exception as e:
            logger.error(f"Errore durante la creazione del backup: {e}")
            return False, f"Errore: {str(e)}"
    
    def get_lista_backup(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista di tutti i backup locali disponibili.
        
        Returns:
            Lista di dizionari con info sui backup (nome, dimensione, data)
        """
        backups = []
        
        try:
            # Trova tutti i file .json nella directory backup
            pattern = str(self.backup_dir / "*.json")
            files = glob.glob(pattern)
            
            for file_path in files:
                path = Path(file_path)
                try:
                    # Ottieni info file
                    stat = path.stat()
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    size_kb = stat.st_size / 1024
                    
                    # Prova a leggere i metadati
                    metadata = {}
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = json.load(f)
                            metadata = content.get('metadata', {})
                    except:
                        pass
                    
                    backups.append({
                        "nome": path.name,
                        "percorso": str(path),
                        "dimensione_kb": round(size_kb, 2),
                        "data_creazione": modified.strftime("%Y-%m-%d %H:%M:%S"),
                        "data_iso": modified.isoformat(),
                        "metadata": metadata
                    })
                except Exception as e:
                    logger.warning(f"Errore lettura backup {file_path}: {e}")
            
            # Ordina per data (più recenti prima)
            backups.sort(key=lambda x: x.get('data_iso', ''), reverse=True)
            
        except Exception as e:
            logger.error(f"Errore nella list backup: {e}")
        
        return backups
    
    def elimina_backup_vecchi(self) -> Tuple[int, List[str]]:
        """
        Elimina i backup più vecchi mantenendo solo gli ultimi N.
        
        Returns:
            Tuple[int, List[str]]: (numero eliminati, lista nomi file eliminati)
        """
        eliminati = []
        
        try:
            backups = self.get_lista_backup()
            
            if len(backups) <= self.max_backups:
                logger.info(f"Backup presenti: {len(backups)} (max: {self.max_backups}) - Nessuna eliminazione necessaria")
                return 0, []
            
            # Identifica backup da eliminare
            to_delete = backups[self.max_backups:]
            
            for backup in to_delete:
                try:
                    path = Path(backup['percorso'])
                    if path.exists():
                        path.unlink()
                        eliminati.append(backup['nome'])
                        logger.info(f"Backup eliminato: {backup['nome']}")
                except Exception as e:
                    logger.error(f"Errore eliminazione backup {backup['nome']}: {e}")
            
        except Exception as e:
            logger.error(f"Errore nell'eliminazione backup vecchi: {e}")
        
        return len(eliminati), eliminati
    
    def elimina_backup_locale(self, nome_file: str) -> Tuple[bool, str]:
        """
        Elimina un backup locale specifico.
        
        Args:
            nome_file: Nome del file di backup da eliminare
        
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        try:
            backup_path = self.backup_dir / nome_file
            
            if not backup_path.exists():
                return False, f"Backup non trovato: {nome_file}"
            
            backup_path.unlink()
            logger.info(f"Backup locale eliminato: {nome_file}")
            return True, f"Backup {nome_file} eliminato"
            
        except Exception as e:
            logger.error(f"Errore eliminazione backup: {e}")
            return False, f"Errore: {str(e)}"
    
    def get_info_backup(self, nome_file: str) -> Optional[Dict[str, Any]]:
        """
        Restituisce informazioni dettagliate su un backup specifico.
        
        Args:
            nome_file: Nome del file di backup
        
        Returns:
            Dizionario con info o None se non trovato
        """
        backups = self.get_lista_backup()
        for backup in backups:
            if backup['nome'] == nome_file:
                return backup
        return None
    
    # ==================== BACKUP AUTOMATICO ====================
    
    def abilita_backup_automatico(self) -> bool:
        """
        Abilita il backup automatico ogni 24 ore.
        
        Returns:
            bool: True se abilitato con successo
        """
        self._auto_backup_enabled = True
        self._last_auto_backup = datetime.now()
        logger.info("Backup automatico abilitato")
        return True
    
    def disabilita_backup_automatico(self) -> bool:
        """
        Disabilita il backup automatico.
        
        Returns:
            bool: True se disabilitato con successo
        """
        self._auto_backup_enabled = False
        logger.info("Backup automatico disabilitato")
        return True
    
    def verifica_backup_automatico(self) -> Tuple[bool, str]:
        """
        Verifica se è necessario eseguire un backup automatico.
        Da chiamare periodicamente (es. ogni ora).
        
        Returns:
            Tuple[bool, str]: (se eseguito, messaggio)
        """
        if not self._auto_backup_enabled:
            return False, "Backup automatico disabilitato"
        
        # Verifica se è passato abbastanza tempo
        if self._last_auto_backup is None:
            # Primo backup
            success, msg = self.crea_backup()
            if success:
                self._last_auto_backup = datetime.now()
            return success, msg
        
        elapsed = datetime.now() - self._last_auto_backup
        if elapsed >= timedelta(hours=self.backup_interval):
            success, msg = self.crea_backup()
            if success:
                self._last_auto_backup = datetime.now()
                
                # Upload automatico su Drive se configurato
                if self._drive_service is not None:
                    try:
                        self.upload_to_drive(msg.split('/')[-1])
                        logger.info("Backup automatico caricato su Google Drive")
                    except Exception as e:
                        logger.error(f"Errore upload automatico: {e}")
            
            return success, msg
        
        prossimo = self._last_auto_backup + timedelta(hours=self.backup_interval)
        return False, f"Prossimo backup automatico: {prossimo.strftime('%Y-%m-%d %H:%M:%S')}"
    
    # ==================== GOOGLE DRIVE ====================
    
    def _get_drive_service(self):
        """
        Ottiene il servizio Google Drive API.
        Usa authentication OAuth2 con service account.
        
        Returns:
            Servizio Google Drive o None se non configurato
        """
        # Se già inizializzato, restituisci
        if self._drive_service is not None:
            return self._drive_service
        
        try:
            # Importa google libraries
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from googleapiclient.errors import HttpError
            
            # Verifica presenza credenziali
            if not Path(CREDENTIALS_FILE).exists():
                logger.warning(f"File credenziali non trovato: {CREDENTIALS_FILE}")
                return None
            
            # Carica credenziali e crea servizio
            credentials = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE, scopes=SCOPES)
            
            self._drive_service = build('drive', 'v3', credentials=credentials)
            logger.info("Google Drive service inizializzato")
            
            # Trova o crea cartella backup
            self._ensure_drive_folder()
            
            return self._drive_service
            
        except ImportError:
            logger.warning("Google Drive libraries non installate. Esegui: pip install google-api-python-client google-auth-oauthlib")
            return None
        except Exception as e:
            logger.error(f"Errore inizializzazione Google Drive: {e}")
            return None
    
    def _ensure_drive_folder(self) -> Optional[str]:
        """
        Trova o crea la cartella per i backup su Google Drive.
        
        Returns:
            ID della cartella o None se errore
        """
        if self._drive_service is None:
            return None
        
        try:
            # Cerca cartella esistente
            query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self._drive_service.files().list(
                q=query, fields="files(id, name)").execute()
            
            if results.get('files'):
                self._drive_folder_id = results['files'][0]['id']
                logger.info(f"Trovata cartella Drive: {DRIVE_FOLDER_NAME} ({self._drive_folder_id})")
                return self._drive_folder_id
            
            # Crea nuova cartella
            file_metadata = {
                'name': DRIVE_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = self._drive_service.files().create(
                body=file_metadata, fields='id').execute()
            
            self._drive_folder_id = folder['id']
            logger.info(f"Creata cartella Drive: {DRIVE_FOLDER_NAME} ({self._drive_folder_id})")
            return self._drive_folder_id
            
        except Exception as e:
            logger.error(f"Errore nella gestione cartella Drive: {e}")
            return None
    
    def verifica_configurazione_drive(self) -> Tuple[bool, str]:
        """
        Verifica se Google Drive è configurato correttamente.
        
        Returns:
            Tuple[bool, str]: (configurato, messaggio)
        """
        service = self._get_drive_service()
        
        if service is None:
            return False, "Google Drive non configurato. Assicurati che credentials.json sia presente."
        
        if self._drive_folder_id is None:
            return False, "Errore: impossibile trovare/creare cartella backup su Drive"
        
        return True, "Google Drive configurato correttamente"
    
    def upload_to_drive(self, nome_backup: str, elimina_locale: bool = False) -> Tuple[bool, str]:
        """
        Carica un backup locale su Google Drive.
        
        Args:
            nome_backup: Nome del file di backup locale
            elimina_locale: Se True, elimina il file locale dopo l'upload
        
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        service = self._get_drive_service()
        
        if service is None:
            raise DriveNotConfiguredError("Google Drive non configurato")
        
        try:
            # Verifica file locale
            local_path = self.backup_dir / nome_backup
            if not local_path.exists():
                return False, f"Backup locale non trovato: {nome_backup}"
            
            # Copia in directory temporanea per upload
            temp_path = self.drive_temp_dir / nome_backup
            shutil.copy2(local_path, temp_path)
            
            try:
                # metadata per upload
                file_metadata = {
                    'name': nome_backup,
                    'parents': [self._drive_folder_id]
                }
                
                # Upload file
                media = MediaFileUpload(str(temp_path), resumable=True)
                file = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, createdTime'
                ).execute()
                
                logger.info(f"Backup caricato su Drive: {file.get('name')} (ID: {file.get('id')})")
                
                # Elimina locale se richiesto
                if elimina_locale:
                    local_path.unlink()
                    logger.info(f"Backup locale eliminato dopo upload: {nome_backup}")
                
                return True, f"Backup caricato: {file.get('name')}"
                
            finally:
                # Pulizia file temporaneo
                if temp_path.exists():
                    temp_path.unlink()
                    
        except Exception as e:
            logger.error(f"Errore upload Drive: {e}")
            return False, f"Errore upload: {str(e)}"
    
    def lista_backup_drive(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista dei backup disponibili su Google Drive.
        
        Returns:
            Lista di dizionari con info sui backup remoti
        """
        service = self._get_drive_service()
        
        if service is None:
            logger.warning("Google Drive non configurato")
            return []
        
        try:
            # Query per file nella cartella backup
            query = f"'{self._drive_folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name, size, createdTime, modifiedTime)",
                orderBy="createdTime desc"
            ).execute()
            
            backups = []
            for file in results.get('files', []):
                size_kb = int(file.get('size', 0)) / 1024 if file.get('size') else 0
                
                backups.append({
                    'id': file.get('id'),
                    'nome': file.get('name'),
                    'dimensione_kb': round(size_kb, 2),
                    'data_creazione': file.get('createdTime'),
                    'data_modifica': file.get('modifiedTime')
                })
            
            logger.info(f"Trovati {len(backups)} backup su Drive")
            return backups
            
        except Exception as e:
            logger.error(f"Errore list backup Drive: {e}")
            return []
    
    def download_from_drive(self, nome_backup: str, percorso_locale: Optional[str] = None) -> Tuple[bool, str]:
        """
        Scarica un backup da Google Drive.
        
        Args:
            nome_backup: Nome del backup su Drive
            percorso_locale: Percorso locale dove salvare (opzionale)
        
        Returns:
            Tuple[bool, str]: (successo, percorso file scaricato)
        """
        service = self._get_drive_service()
        
        if service is None:
            raise DriveNotConfiguredError("Google Drive non configurato")
        
        try:
            # Trova file su Drive
            query = f"name='{nome_backup}' and '{self._drive_folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query, fields="files(id, name)").execute()
            
            files = results.get('files', [])
            if not files:
                return False, f"Backup non trovato su Drive: {nome_backup}"
            
            file_id = files[0]['id']
            
            # Determina percorso locale
            if percorso_locale is None:
                percorso_locale = str(self.backup_dir / nome_backup)
            
            # Download
            request = service.files().get_media(fileId=file_id)
            
            with open(percorso_locale, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            
            logger.info(f"Backup scaricato da Drive: {nome_backup} -> {percorso_locale}")
            return True, percorso_locale
            
        except Exception as e:
            logger.error(f"Errore download Drive: {e}")
            return False, f"Errore: {str(e)}"
    
    def elimina_backup_drive(self, nome_backup: str) -> Tuple[bool, str]:
        """
        Elimina un backup da Google Drive.
        
        Args:
            nome_backup: Nome del backup da eliminare
        
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        service = self._get_drive_service()
        
        if service is None:
            raise DriveNotConfiguredError("Google Drive non configurato")
        
        try:
            # Trova file
            query = f"name='{nome_backup}' and '{self._drive_folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query, fields="files(id, name)").execute()
            
            files = results.get('files', [])
            if not files:
                return False, f"Backup non trovato su Drive: {nome_backup}"
            
            # Elimina
            service.files().delete(fileId=files[0]['id']).execute()
            logger.info(f"Backup eliminato da Drive: {nome_backup}")
            return True, f"Backup {nome_backup} eliminato da Drive"
            
        except Exception as e:
            logger.error(f"Errore eliminazione Drive: {e}")
            return False, f"Errore: {str(e)}"
    
    # ==================== RIPRISTINO ====================
    
    def ripristina_da_file(self, percorso_file: str) -> Tuple[bool, str]:
        """
        Ripristina i dati da un file di backup locale.
        
        Args:
            percorso_file: Percorso al file di backup
        
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        try:
            backup_path = Path(percorso_file)
            
            if not backup_path.exists():
                return False, f"File backup non trovato: {percorso_file}"
            
            # Leggi backup
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_content = json.load(f)
            
            # Estrai dati (formato con metadata o no)
            if 'data' in backup_content:
                data = backup_content['data']
            else:
                # Backup nel formato vecchio/semplice
                data = backup_content
            
            # Crea backup pre-restore per sicurezza
            if self.data_file.exists():
                pre_restore = self.backup_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                shutil.copy2(self.data_file, pre_restore)
                logger.info(f"Backup pre-restore creato: {pre_restore}")
            
            # Ripristina dati
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Dati ripristinati da: {percorso_file}")
            return True, f"Ripristino completato da: {percorso_file}"
            
        except Exception as e:
            logger.error(f"Errore ripristino: {e}")
            return False, f"Errore: {str(e)}"
    
    def ripristina_da_drive(self, nome_backup: str) -> Tuple[bool, str]:
        """
        Scarica e ripristina un backup da Google Drive.
        
        Args:
            nome_backup: Nome del backup su Drive
        
        Returns:
            Tuple[bool, str]: (successo, messaggio)
        """
        try:
            # Download da Drive
            success, percorso = self.download_from_drive(nome_backup)
            if not success:
                return False, percorso
            
            # Ripristina da file scaricato
            return self.ripristina_da_file(percorso)
            
        except Exception as e:
            logger.error(f"Errore ripristino da Drive: {e}")
            return False, f"Errore: {str(e)}"
    
    def get_stato_sistema(self) -> Dict[str, Any]:
        """
        Restituisce lo stato completo del sistema di backup.
        
        Returns:
            Dizionario con stato backup locali, Drive, e impostazioni
        """
        drive_configured, drive_msg = self.verifica_configurazione_drive()
        
        local_backups = self.get_lista_backup()
        
        drive_backups = []
        if drive_configured:
            drive_backups = self.lista_backup_drive()
        
        return {
            "backup_locali": {
                "totale": len(local_backups),
                "backup": local_backups[:5],  # Ultimi 5
                "max_conservati": self.max_backups,
                "directory": str(self.backup_dir)
            },
            "backup_drive": {
                "configurato": drive_configured,
                "messaggio": drive_msg,
                "totale": len(drive_backups),
                "backup": drive_backups[:5]  # Ultimi 5
            },
            "backup_automatico": {
                "abilitato": self._auto_backup_enabled,
                "ultimo_backup": self._last_auto_backup.isoformat() if self._last_auto_backup else None,
                "intervallo_ore": self.backup_interval
            },
            "drive_temp_dir": str(self.drive_temp_dir)
        }


# Helper function per import
def get_backup_system() -> BackupSystem:
    """Restituisce l'istanza singleton del sistema di backup."""
    return BackupSystem()


# Necessario per download Google Drive
try:
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    pass


# Esempio utilizzo standalone
if __name__ == "__main__":
    # Test del modulo
    print("=== Test Sistema Backup ===\n")
    
    bs = BackupSystem()
    
    # Test creazione backup
    print("1. Creazione backup locale...")
    success, msg = bs.crea_backup()
    print(f"   Risultato: {success} - {msg}")
    
    # Test lista backup
    print("\n2. Lista backup locali:")
    backups = bs.get_lista_backup()
    for b in backups:
        print(f"   - {b['nome']} ({b['dimensione_kb']} KB)")
    
    # Test stato sistema
    print("\n3. Stato sistema:")
    stato = bs.get_stato_sistema()
    print(f"   Backup locali: {stato['backup_locali']['totale']}")
    print(f"   Drive configurato: {stato['backup_drive']['configurato']}")
    print(f"   Backup automatico: {stato['backup_automatico']['abilitato']}")
    
    print("\n=== Test completato ===")

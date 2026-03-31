"""
Sistema FAQ avanzato per HelperBot IPTV
Gestisce le FAQ con categorie, ricerca per parole chiave e suggerimenti automatici
"""

import json
import os
import logging
from typing import List, Dict, Optional, Tuple
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

class FaqSystem:
    """
    Sistema avanzato di FAQ per supporto IPTV
    """
    
    CATEGORIE = {
        "CONNESSIONE": "🔗 Connessione",
        "BUFFERING": "⏳ Buffering/Lag",
        "APP_BLOCCATE": "🚫 App Bloccate",
        "CONTENUTI": "📺 Contenuti",
        "FIRESTICK": "🔥 FireStick",
        "GENERALE": "❓ Generale"
    }
    
    def __init__(self, persistence: DataPersistence):
        """
        Inizializza il sistema FAQ
        
        Args:
            persistence: Istanza per la persistenza dei dati
        """
        self.persistence = persistence
        self._initialize_data()

    def _initialize_data(self) -> None:
        """Inizializza i dati FAQ se non esistono"""
        faq_data = self.persistence.get_data("faq")
        if faq_data is None or (isinstance(faq_data, list) and len(faq_data) == 0):
            self._populate_initial_faq()
            logger.info("FAQ inizializzate con dati predefiniti")

    def _load_faq(self) -> List[Dict]:
        """Carica tutte le FAQ dal database"""
        try:
            faq_data = self.persistence.get_data("faq")
            if faq_data is None:
                return []
            return faq_data if isinstance(faq_data, list) else []
        except Exception as e:
            logger.error(f"Errore nel caricamento FAQ: {e}")
            return []

    def _save_faq(self, faq_list: List[Dict]) -> bool:
        """Salva tutte le FAQ nel database"""
        try:
            self.persistence.update_data("faq", faq_list)
            return True
        except Exception as e:
            logger.error(f"Errore nel salvataggio FAQ: {e}")
            return False
    
    def _get_next_id(self, faq_list: List[Dict]) -> int:
        """Calcola il prossimo ID disponibile"""
        if not faq_list:
            return 1
        return max(faq_item.get("id", 0) for faq_item in faq_list) + 1
    
    def _populate_initial_faq(self) -> None:
        """Popola il sistema con FAQ dettagliate per IPTV"""
        faq_list = []
        
        # ========== CATEGORIA CONNESSIONE ==========
        connessione_faq = [
            {
                "categoria": "CONNESSIONE",
                "domanda": "Come verificare la connessione al server IPTV?",
                "risposta": "Per verificare la connessione:\n\n1. Accedi al pannello utente sul nostro sito\n2. Vai alla sezione 'Stato Connessione'\n3. Verifica che il server sia 'Online'\n4. Controlla la latenza (ping)\n\nSe il server appare offline, prova:\n• Riavvia il router\n• Controlla che il tuo abbonamento sia attivo\n• Verifica le credenziali di accesso\n\nIl server potrebbe essere in manutenzione programmata - controlla gli aggiornamenti.",
                "parole_chiave": ["connessione", "server", "online", "offline", "ping", "verifica", "stato"],
                "ordine": 1
            },
            {
                "categoria": "CONNESSIONE",
                "domanda": "Errore 'Connessione rifiutata' o 'Server non raggiungibile'",
                "risposta": "Questo errore indica problemi di connessione al server. Ecco i passaggi per risolvere:\n\n1. **Verifica l'abbonamento**: Assicurati che il tuo abbonamento sia attivo e non scaduto\n\n2. **Controlla le credenziali**: Verifica che username e password siano corretti\n\n3. **Riavvia i dispositivi**: Riavvia il router, il dispositivo di streaming e l'app\n\n4. **Cambia server**: Prova a utilizzare un server alternativo dalla lista disponibile\n\n5. **Verifica DNS**: Prova a cambiare i DNS del router (8.8.8.8 e 8.8.4.4)\n\nSe il problema persiste, potrebbe essere un'interruzione del servizio - contatta il supporto.",
                "parole_chiave": ["errore", "rifiutata", "raggiungibile", "connessione", "server", "offline"],
                "ordine": 2
            },
            {
                "categoria": "CONNESSIONE",
                "domanda": "Come risolvere problemi di disconnessione frequenti?",
                "risposta": "Le disconnessioni frequenti possono essere causate da:\n\n**Problemi di rete:**\n• Segnale WiFi debole - avvicinati al router o usa connessione cablata\n• Sovraccarico della rete - troppi dispositivi collegati\n• Problemi con il provider internet\n\n**Problemi del server:**\n• Server sovraccarico - prova un server alternativo\n• Manutenzione programmata\n\n**Problemi del dispositivo:**\n• Cache piena - svuota la cache dell'app\n• App obsoleta - aggiorna all'ultima versione\n• Riavvio periodico del dispositivo\n\n**Soluzione rapida:** Riavvia router + dispositivo + app ogni 2-3 ore se il problema persiste.",
                "parole_chiave": ["disconnessione", "frequente", "caduta", "staccato", "riavvio", "wifi"],
                "ordine": 3
            },
            {
                "categoria": "CONNESSIONE",
                "domanda": "Quali porte devono essere aperte per IPTV?",
                "risposta": "Per il corretto funzionamento dell'IPTV devi aprire le seguenti porte:\n\n**Porte essenziali:**\n• TCP 80 - HTTP (streaming)\n• TCP 443 - HTTPS (streaming sicuro)\n• TCP 1935 - RTMP (streaming)\n• UDP 123 - NTP (sincronizzazione tempo)\n• UDP 5000-6000 - Protocollo RTP\n\n**Configurazione router:**\n1. Accedi al pannello del router (solitamente 192.168.1.1)\n2. Trova 'Port Forwarding' o 'Inoltro porte'\n3. Aggiungi le porte sopra indicate\n4. Indirizza verso l'IP del dispositivo\n\n⚠️ Attenzione: Alcuni ISP bloccano determinate porte. In tal caso, contatta il supporto per alternative.",
                "parole_chiave": ["porte", "aprire", "firewall", "router", "tcp", "udp", "forwarding"],
                "ordine": 4
            },
            {
                "categoria": "CONNESSIONE",
                "domanda": "Connessione lenta o instabile: come migliorare?",
                "risposta": "Guida completa per migliorare la velocità di connessione:\n\n**1. Testa la velocità:**\n• Speedtest.net per verificare la velocità effettiva\n• Minimo richiesto: 10-15 Mbps per HD, 25+ Mbps per 4K\n\n**2. Ottimizza la rete:**\n• Usa cavo Ethernet invece di WiFi\n• Posiziona il router in centro casa\n• Evita interferenze (microonde, cordless)\n\n**3. Configura QoS:**\n• Prioritizza il traffico IPTV nel router\n• Limita download/upload durante la visione\n\n**4. Server alternativo:**\n• Prova server con meno carico\n• Server geograficamente più vicini\n\n**5. VPN:**\n• Alcune VPN rallentano la connessione\n• Prova a disattivarla temporaneamente",
                "parole_chiave": ["lenta", "instabile", "velocità", " Mbps", " QoS", "migliorare", "ethernet"],
                "ordine": 5
            }
        ]
        
        # ========== CATEGORIA BUFFERING ==========
        buffering_faq = [
            {
                "categoria": "BUFFERING",
                "domanda": "Come risolvere il buffering persistente?",
                "risposta": "Il buffering è causato principalmente da problemi di rete o server. Ecco la guida completa:\n\n**Step 1 - Diagnosi rete:**\n• Testa la velocità: minimo 15 Mbps per HD\n• Pinga il server: deve essere < 100ms\n• Verifica che nessuno stia scaricando\n\n**Step 2 - Ottimizza il dispositivo:**\n• Chiudi app in background\n• Svuota cache: Impostazioni > App > IPTV > Cache\n• Riavvia il dispositivo\n\n**Step 3 - Cambia server:**\n• Prova un server alternativo\n• Server più vicino geograficamente\n\n**Step 4 - Impostazioni app:**\n• Riduci la qualità video temporaneamente\n• Disattiva auto-quality\n• Abilita hardware acceleration\n\n**Step 5 - Rete avanzata:**\n• Usa DNS 1.1.1.1 e 8.8.8.8\n• Prova VPN diversa\n• Contatta ISP per проблемi di linea",
                "parole_chiave": ["buffering", "caricamento", "lento", "stop", "riprendi", "attesa"],
                "ordine": 1
            },
            {
                "categoria": "BUFFERING",
                "domanda": "Buffering solo su alcuni canali: perché?",
                "risposta": "Se il buffering avviene solo su alcuni canali specifici:\n\n**Cause possibili:**\n• Canale con alto traffico - prova in orari diversi\n• Server specifico sovraccarico - cambia server\n• Canale in manutenzione - verifica stato canale\n• Qualità del canale bassa - il canale stesso ha problemi\n\n**Soluzioni:**\n1. Prova lo stesso canale su server diverso\n2. Verifica se altri canali funzionano bene\n3. Controlla se il canale è nella lista canali attivi\n4. Prova in momenti diversi della giornata\n5. Cambia la qualità del canale (se l'app lo permette)\n\nSe il problema è solo su 1-2 canali, molto probabilmente è il canale stesso ad avere problemi di trasmissione.",
                "parole_chiave": ["alcuni canali", "solo alcuni", "specifici", "singoli", "buffering", "lag"],
                "ordine": 2
            },
            {
                "categoria": "BUFFERING",
                "domanda": "Impostazioni consigliate per ridurre il buffering",
                "risposta": "Configurazione ottimale per minimizzare il buffering:\n\n**Impostazioni app IPTV:**\n```\nBuffer Size: 10-15 secondi\nVideo Buffer: 20-30 MB\nAuto Quality: Disattivato\nHardware Decoding: Attivato\nConnection Timeout: 15 secondi\nMax Connections: 1\n```\n\n**Impostazioni dispositivo:**\n•关闭 режим di risparmio energia\n• Aggiorna firmware dispositivo\n• Libera spazio storage (minimo 2GB liberi)\n• Disattiva app inutili in background\n\n**Impostazioni router:**\n• QoS attivo per priorità streaming\n• MTU ottimale: 1500\n• UPnP abilitato\n\n**Qualità video consigliata:**\n• 720p: 8 Mbps minimi\n• 1080p: 15 Mbps minimi\n• 4K: 25 Mbps minimi",
                "parole_chiave": ["impostazioni", "configurazione", "buffer", "size", "ottimizzare", "ridurre"],
                "ordine": 3
            },
            {
                "categoria": "BUFFERING",
                "domanda": "Il buffering peggiora la sera: normale?",
                "risposta": "Sì, è normale che il buffering aumenti nelle ore serali (19:00-24:00). Ecco perché:\n\n**Peak hours - Ore di picco:**\n• Più utenti connessi simultaneamente\n• Server sotto carico maggiore\n• Qualità della linea ISP ridotta\n\n**Soluzioni per le ore di picco:**\n1. **Cambia server** - prova server con meno carico\n2. **Riduci qualità** - passa da 1080p a 720p\n3. **Usa canali alternativi** - alcuni canali hanno meno traffico\n4. **Pianifica** - guarda contenuti on-demand fuori orario di picco\n5. **Precarica** - usa la funzione timeshift se disponibile\n\n**Consiglio:** Il problema non dipende da noi nelle ore serali - è un problema di saturazione della rete globale.",
                "parole_chiave": ["sera", "notte", "ore picco", "peak", "serale", "tardi", "troppi utenti"],
                "ordine": 4
            },
            {
                "categoria": "BUFFERING",
                "domanda": "Lag e freeze durante eventi sportivi live",
                "risposta": "Gli eventi sportivi (partite, UFC, wrestling) hanno sempre alto traffico. Suggerimenti:\n\n**Prima dell'evento (30 min prima):**\n1. Riavvia router e dispositivo\n2. Svuota cache dell'app\n3. Prepara2-3 server alternativi di backup\n4. Connettiti al server con minor carico\n\n**Durante l'evento:**\n• Se inizia il buffering, cambia immediatamente server\n• Tieni aperta lista canali per cambio rapido\n• Prova canale backup (spesso disponibile)\n• Riduci qualità a 720p se necessario\n\n**Server consigliati:**\n• Server 'Sport' dedicati (spesso hanno meno carico)\n• Server di notte/early morning\n• Server alternativi nelle notizie canale\n\n**Importante:** Non aspettare - cambia server al primo segno di buffering!",
                "parole_chiave": ["sport", "live", "partita", "calcio", "lag", "freeze", "evento", "match"],
                "ordine": 5
            }
        ]
        
        # ========== CATEGORIA APP_BLOCCATE ==========
        app_bloccate_faq = [
            {
                "categoria": "APP_BLOCCATE",
                "domanda": "L'app IPTV non si apre o va in crash",
                "risposta": "Se l'app non si apre o si chiude improvvisamente:\n\n**Step 1 - Riavvio:**\n• Riavvia il dispositivo\n• Forza chiusura e riapri l'app\n\n**Step 2 - Cache e dati:**\n• Impostazioni > App > IPTV > Svuota cache\n• Se persiste: Svuota dati + disinstalla + reinstalla\n\n**Step 3 - Aggiornamenti:**\n• Verifica di avere l'ultima versione\n• Aggiorna da store ufficiale\n\n**Step 4 - Compatibilità:**\n• Verifica che il dispositivo sia supportato\n• Android 6.0+ minimo richiesto\n• Firestick: verifica modello supportato\n\n**Step 5 - Reinstallazione pulita:**\n• Disinstalla completamente\n• Riavvia dispositivo\n• Installa versione recente\n• Non ripristinare backup (potrebbe causare conflitti)",
                "parole_chiave": ["crash", "non si apre", "si chiude", "app", "crashare", "chiude", "non parte"],
                "ordine": 1
            },
            {
                "categoria": "APP_BLOCCATE",
                "domanda": "Errore 'App non installata' o 'Package not found'",
                "risposta": "Questo errore indica un problema con l'installazione dell'app:\n\n**Soluzioni:**\n\n1. **Riprova l'installazione:**\n• Disconnetti e riconnetti il dispositivo\n• Riprova a scaricare l'app\n\n2. **Installazione manuale (APK):**\n• Scarica APK da fonte ufficiale\n• Abilita 'Origini sconosciute' nelle impostazioni\n• Installa l'APK direttamente\n\n3. **Problemi FireStick:**\n• Vai su Impostazioni > My Fire TV > Opzioni sviluppatore\n• Disattiva e riattiva 'App da origini sconosciute'\n• Riavvia il Firestick\n\n4. **Spazio insufficiente:**\n• Libera almeno 500MB\n• Disinstalla app inutilizzate\n• Clear cache sistema\n\n5. **Ultimo resort:**\n• Reset di fabbrica del dispositivo",
                "parole_chiave": ["non installata", "package", "errore", "installazione", "APK", "non trovata"],
                "ordine": 2
            },
            {
                "categoria": "APP_BLOCCATE",
                "domanda": "L'app viene bloccata dal Play Store o App Store",
                "seguito": "Gli store ufficiali (Play Store, App Store) spesso bloccano le app IPTV. Ecco come procedire:\n\n**Per Android:**\n1. Scarica l'APK direttamente dal nostro sito\n2. Vai su Impostazioni > Sicurezza > Origini sconosciute\n3. Abilita per il browser/downloader\n4. Installa l'APK\n\n**Per FireStick:**\n1. Vai su Impostazioni > My Fire TV > Opzioni sviluppatore\n2. Abilita 'App da origini sconosciute'\n3. Installa Downloader o ES File Explorer\n4. Usa l'app per scaricare l'APK IPTV\n\n**Per Apple TV/iOS:**\n• Necessario jailbreak o sideLOAD\n• Alternativa: usa AirPlay da iPhone/iPad\n\n⚠️ Attenzione: Scarica solo da fonti attendibili per evitare malware!",
                "parole_chiave": ["bloccata", "Play Store", "App Store", "rifiutata", "non disponibile", "store"],
                "ordine": 3
            },
            {
                "categoria": "APP_BLOCCATE",
                "domanda": "Errore 'Il file APK non è valido'",
                "risposta": "Se l'APK non viene riconosciuto come valido:\n\n**Possibili cause:**\n• Download interrotto o incompleto\n• File corrotto durante il download\n• Versione APK non compatibile\n\n**Soluzioni:**\n\n1. **Ricompleta download:**\n• Cancella il file e riscaricalo\n• Usa connessione stabile\n• Disattiva temporaneamente antivirus\n\n2. **Verifica integrità:**\n• Controlla la dimensione del file (solitamente 30-100MB)\n• Prova a verificare hash MD5 se disponibile\n\n3. **Versione corretta:**\n• Verifica che sia la versione per il tuo dispositivo\n•区分 Android TV vs Stick vs Smartphone\n• Verifica requisiti minimi Android\n\n4. **Metodo alternativo:**\n• Prova a installare tramite PC e adb\n• Prova altra fonte di download",
                "parole_chiave": ["APK", "non valido", "corrotto", "invalid", "errore installazione", "file"],
                "ordine": 4
            },
            {
                "categoria": "APP_BLOCCATE",
                "domanda": "L'app richiede permessi strani o viene rilevata come virus",
                "risposta": "Le app IPTV richiedono permessi legittimi per funzionare:\n\n**Permessi necessari (normali):**\n• Internet - per connettersi al server\n• Rete - per streaming\n• Storage - per cache e salvataggio\n• Installare app - per aggiornamenti\n\n**Se rilevata come virus:**\n• È un 'falso positivo' comune\n• Aggiungi esclusione nell'antivirus\n• Scarica solo da fonti ufficiali verificate\n• Controlla recensioni e reputazione\n\n**Permessi anomali (allarme):**\n• SMS e chiamate\n• Contatti\n• Posizione precisa\n• Camera e microfono\n\nSe l'app richiede questi, NON installarla e segnala!\n\n**Consiglio:** Disattiva Play Protect durante l'installazione temporaneamente.",
                "parole_chiave": ["permessi", "virus", "antivirus", "falso positivo", "strano", "richiede"],
                "ordine": 5
            }
        ]
        
        # ========== CATEGORIA CONTENUTI ==========
        contenuti_faq = [
            {
                "categoria": "CONTENUTI",
                "domanda": "Canale non trovato o canale non disponibile",
                "risposta": "Se un canale non appare o non è disponibile:\n\n**Verifiche preliminari:**\n1. Aggiorna la lista canali (refresh dalla app)\n2. Riavvia l'app per ricaricare la lista\n3. Verifica che il canale sia nella lista attiva\n\n**Se il canale proprio non esiste:**\n• Controlla la lista completa sul sito\n• Alcuni canali potrebbero essere rimossi temporaneamente\n• Verifica il pacchetto del tuo abbonamento\n\n**Se il canale c'è ma non funziona:**\n• Il canale potrebbe essere offline per manutenzione\n• Prova un server alternativo\n• Il canale potrebbe aver cambiato nome/frequenza\n\n**Info utili:**\n• Canali temporaneamente non disponibili: Max 24-48 ore\n• Canali rimossi dal bouquet: comunicazione preventiva\n• Canali nuovi: aggiunti settimanalmente",
                "parole_chiave": ["canale", "non trovato", "non disponibile", "mancante", "assente", "lista"],
                "ordine": 1
            },
            {
                "categoria": "CONTENUTI",
                "domanda": "Come vedere film e serie TV on-demand?",
                "risposta": "Guida per accedere ai contenuti on-demand:\n\n**Attraverso l'app IPTV:**\n1. Apri l'app e cerca la sezione 'VOD' o 'On Demand'\n2. Troverai film e serie organizzati per:\n   - Genere (Azione, Commedia, etc.)\n   - Anno di produzione\n   - Lingua\n   - Popolarità\n\n**Attraverso il portale web:**\n1. Accedi al pannello utente\n2. Vai su 'Catalogo VOD'\n3.Cerca e riproduci direttamente dal browser\n\n**Consigli:**\n• Usa la funzione ricerca per titolo specifico\n• I contenuti sono aggiornati quotidianamente\n• Serie TV: trovi anche episodi passati\n• Qualità disponibile: SD, HD, FullHD\n\n**Problemi VOD:** Se non trovi contenuti, verifica che il tuo abbonamento includa VOD.",
                "parole_chiave": ["film", "serie", "on demand", "VOD", "电影院", "guardare", "catalogo"],
                "ordine": 2
            },
            {
                "categoria": "CONTENUTI",
                "domanda": "Guide TV (EPG) non funziona o non si carica",
                "risposta": "Se la guida TV non appare o non si aggiorna:\n\n**Problemi comuni:**\n• Cache EPG corrotta\n• Server EPG non disponibile\n• Dati obsoleti\n\n**Soluzioni:**\n\n1. **Aggiorna EPG:**\n• Vai su Impostazioni > EPG > Aggiorna\n• Attendi il caricamento completo (può richiedere minuti)\n\n2. **Svuota cache EPG:**\n• Impostazioni > Cache > Cancella cache EPG\n\n3. **Riavvia l'app:**\n• Forza chiusura e riapri\n\n4. **Problemi ricorrenti:**\n• Alcuni canali non supportano EPG\n• EPG potrebbe essere disponibile solo per alcuni canali\n• Verifica connessione internet stabile\n\n**Nota:** L'EPG è fornito da terze parti e potrebbe avere ritardi di 24-48 ore.",
                "parole_chiave": ["EPG", "guida TV", "programma", "orario", "non si carica", "aggiorna"],
                "ordine": 3
            },
            {
                "categoria": "CONTENUTI",
                "domanda": "Come vedere canali in lingua originale (VO)?",
                "risposta": "Per guardare canali in lingua originale:\n\n**Metodo 1 - Tramite app:**\n1. Seleziona il canale desiderato\n2. Cerca opzioni audio (spesso tasto 'audio' o 'track')\n3. Seleziona la traccia audio originale\n\n**Metodo 2 - Lista canali:**\n• Molti canali hanno varianti:\n  - Canale + (es: Sky Sport +1)\n  - SD/HD con lingua diversa\n  - feed alternativi\n\n**Metodo 3 - Via portale:**\n• Accedi al pannello web\n• Filtra per lingua\n• Trova canali con audio originale\n\n**Canali con più lingue:**\n• Cinema (Sky, Netflix, etc.)\n• Sport internazionali\n• Documentari (National Geographic, Discovery)\n\n**Nota:** Non tutti i canali offrono tracce audio multiple.",
                "parole_chiave": ["lingua originale", "VO", "V.O.", "audio", "inglese", "originale", "traccia"],
                "ordine": 4
            },
            {
                "categoria": "CONTENUTI",
                "domanda": "Canali PPV (Pay Per View) e eventi speciali",
                "risposta": "Informazioni su eventi speciali e PPV:\n\n**Cosa sono i canali PPV:**\n• Canali per eventi speciali (partite, UFC, WWE)\n• Disponibili solo durante l'evento live\n\n**Come accedere:**\n• I canali PPV appaiono automaticamente nella lista\n• Non richiedono abbonamento extra se hai il pacchetto sport\n• Attivi 30-60 minuti prima dell'evento\n\n**Consigli per eventi live:**\n1. Controlla la sezione 'Eventi Live' nell'app\n2. Verifica gli aggiornamenti sul sito\n3. Tieni pronto un server alternativo\n4. Connettiti 15-20 minuti prima\n\n**Problemi con PPV:**\n• Se il canale non appare, verifica l'abbonamento\n• Controlla gli aggiornamenti settimanali\n• Alcuni eventi richiedono pay extra (comunicato separatamente)",
                "parole_chiave": ["PPV", "pay per view", "evento", "live", "speciale", "UFC", "wrestling"],
                "ordine": 5
            },
            {
                "categoria": "CONTENUTI",
                "domanda": "Registrazione (PVR) e timeshift non funzionano",
                "risposta": "Guida per utilizzare registrazione e timeshift:\n\n**Requisiti per registrazione:**\n• Spazio di archiviazione sufficiente\n• App che supporta PVR\n• Canale che supporta registrazione\n\n**Attivare timeshift:**\n1. Impostazioni > Timeshift > Abilita\n2. Imposta durata massima (1-24 ore)\n3. Seleziona spazio di archiviazione\n\n**Problemi comuni:**\n• **Non registra**: verifica spazio disponibile\n• **Playback non funziona**: formato non supportato\n• **Impossibile andare avanti/indietro**: timeshift non attivo\n\n**Limiti:**\n• Registrazioni temporanee (24-72 ore)\n• Non tutti i canali supportano registrazione\n• Qualità registrazione dipende dal canale\n\n**Consiglio:** Usa Timeshift per mettere in pausa il live!",
                "parole_chiave": ["registrazione", "PVR", "timeshift", "pausa", "registra", "salva"],
                "ordine": 6
            }
        ]
        
        # ========== CATEGORIA FIRESTICK ==========
        firestick_faq = [
            {
                "categoria": "FIRESTICK",
                "domanda": "Come svuotare la cache su FireStick?",
                "risposta": "Guida per svuotare la cache su FireStick:\n\n**Metodo 1 - Dalle impostazioni (metodo consigliato):**\n1. Vai su Impostazioni > My Fire TV > Applicazioni\n2. Seleziona l'app IPTV\n3. Clicca su 'Svuota cache'\n4. Conferma\n\n**Metodo 2 - Forza stop + cache:**\n1. Impostazioni > My Fire TV > Applicazioni\n2. Trova l'app IPTV\n3. Forza stop\n4. Svuota dati/cache\n5. Riavvia l'app\n\n**Quando farlo:**\n• Quando l'app è lenta\n• Quando noti buffering anomalo\n• Dopo aggiornamenti dell'app\n• Settimanalmente come manutenzione\n\n**Nota:** Svuotare la cache NON elimina i tuoi dati di accesso.",
                "parole_chiave": ["cache", "svuota", "pulizia", "FireStick", "memoria", "cancella"],
                "ordine": 1
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "Come reinstallare l'app IPTV su FireStick?",
                "risposta": "Reinstallazione pulita su FireStick:\n\n**Step 1 - Disinstalla:**\n1. Vai su Impostazioni > Applicazioni > Gestisci applicazioni installate\n2. Trova l'app IPTV\n3. Clicca su 'Disinstalla'\n4. Conferma\n\n**Step 2 - Riavvia FireStick:**\n1. Impostazioni > My Fire TV > Riavvia\n2. Attendi il riavvio completo\n\n**Step 3 - Reinstalla:**\n1. Scarica l'APK o usa Downloader\n2. Installa l'app\n3. Accedi con le tue credenziali\n\n**Dopo reinstallazione:**\n• Non ripristinare backup precedente\n• Configura da zero\n• Aggiorna subito se disponibile nuova versione\n\n**Pro tip:** Installa l'app due volte per assicurarti che sia pulita.",
                "parole_chiave": ["reinstalla", "disinstalla", "FireStick", "nuova installazione", "setup"],
                "ordine": 2
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "Problemi di rete WiFi su FireStick",
                "risposta": "Problemi di connessione WiFi su FireStick:\n\n**Verifiche base:**\n1. Verifica che WiFi sia connesso (icona nella barra)\n2. Prova a collegarti a internet (apri un'app)\n3. Testa altri dispositivi sulla stessa rete\n\n**Soluzioni per WiFi problematico:**\n\n**1. Riavvia router e FireStick**\n**2. Dimentica e riconnetti rete:**\n• Impostazioni > Rete > Dimentica rete\n• Riconnetti inserendo password\n\n**3. Cambia canale WiFi:**\n• Accedi al router\n• Cambia canale (usa 6 o 11, meno congestionati)\n\n**4. Usa DNS manuale:**\n• Impostazioni > Rete > Configura manualmente\n• DNS primario: 1.1.1.1\n• DNS secondario: 8.8.8.8\n\n**5. Ethernet:**\n• Usa adattatore Ethernet per稳定 connessione\n• Molto più stabile del WiFi",
                "parole_chiave": ["wifi", "rete", "connessione", "FireStick", "disconnesso", "non si connette"],
                "ordine": 3
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "FireStick lento: come migliorare le prestazioni?",
                "risposta": "Ottimizza le prestazioni del tuo FireStick:\n\n**1. Chiudi app in background:**\n• Vai su Impostazioni > Applicazioni\n• Forza chiusura app non utilizzate\n• Non lasciare app aperte che consumano RAM\n\n**2. Libera spazio:**\n• Cancella dati e cache app inutilizzate\n• Disinstalla app non usate\n• Lascia almeno 500MB liberi\n\n**3. Aggiorna tutto:**\n• Verifica aggiornamenti sistema (Impostazioni > My Fire TV > Info)\n• Aggiorna tutte le app\n\n**4. Disattiva servizi inutili:**\n• Impostazioni > Preferenze > Risparmio energia > Disattiva\n• Disattiva dati di utilizzo\n\n**5. Riavvio periodico:**\n• Riavvia il FireStick ogni 2-3 giorni\n• Stacca alimentazione 30 secondi\n\n**6. Cambia FireStick:**\n• Se ancora lento, potrebbe essere hardware\n• Modelli vecchi (1a/2a gen) sono lenti",
                "parole_chiave": ["lento", "prestazioni", "FireStick", "velocità", "ritardo", "ottimizza"],
                "ordine": 4
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "Errore 'Devi abilitare origini sconosciute'",
                "risposta": "Come abilitare origini sconosciute su FireStick:\n\n**Per Fire OS 7+ (2019+):**\n1. Impostazioni > My Fire TV > Opzioni sviluppatore\n2. Abilita 'App da origini sconosciute'\n3. Conferma\n\n**Per versioni precedenti:**\n1. Impostazioni > Sistema > Opzioni sviluppatore\n2. Abilita 'App da origini sconosciute'\n\n**Per app specifica (Downloader):**\n1. Impostazioni > App > Store gestito\n2. Trova Downloader\n3. Abilita 'Origini sconosciute'\n\n**Se disattivato automaticamente:**\n• Riavvia il FireStick\n• Riattiva l'opzione\n• Non funziona? Reset completo\n\n⚠️ Attenzione: Abilita solo per app fidate!",
                "parole_chiave": ["origini sconosciute", "abilita", "FireStick", "sviluppatore", "APK"],
                "ordine": 5
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "FireStick si spegne o va in sleep da solo",
                "risposta": "Se il FireStick si spegne automaticamente:\n\n**Impostazioni di risparmio energia:**\n1. Impostazioni > My Fire TV > Visore > Risparmio energia\n2. Disattiva 'Standby visivo'\n3. Impostazioni > Display > Timeout schermo > Mai\n\n**Problemi di alimentazione:**\n• Usa alimentatore originale (5V 1A)\n• Alimentatori deboli causano spegnimenti\n• Prova altra porta USB TV o alimentatore externo\n\n**Riavvio automatico:**\n• Controlla se sono presenti aggiornamenti\n• A volte aggiornamenti causano problemi\n• Riavvia manualmente dopo update\n\n**Problemi hardware:**\n• Se si spegne spesso, potrebbe essere difettoso\n• Prova con altro cavo HDMI\n• Prova in altra HDMI della TV\n\n**Come riavviare:**\n• Impostazioni > My Fire TV > Riavvia",
                "parole_chiave": ["spegne", "sleep", "standby", "si spegne", "FireStick", "notte"],
                "ordine": 6
            },
            {
                "categoria": "FIRESTICK",
                "domanda": "Come collegare FireStick via Ethernet?",
                "risposta": "Connessione Ethernet su FireStick:\n\n**Requisiti:**\n• Adattatore Ethernet Amazon (consigliato)\n• Oppure adattatore USB-Ethernet compatibile\n\n**Configurazione:**\n1. Collega adattatore Ethernet al FireStick\n2. Collega cavo Ethernet al router\n3. FireStick dovrebbe rilevare automaticamente\n4. Vai su Impostazioni > Rete\n5. Seleziona la rete Ethernet\n\n**Vantaggi Ethernet:**\n• Connessione più stabile\n• Minor latency\n• Nessun problema WiFi\n• Ideale per 4K e streaming pesante\n\n**Problemi risolti:**\n• Buffering da WiFi debole\n• Disconnessioni frequenti\n• Lag durante eventi live\n\n**Consiglio:** Se hai problemi WiFi, Ethernet è la soluzione migliore!",
                "parole_chiave": ["ethernet", "cavo", "rete cablata", "FireStick", "collega", "adattatore"],
                "ordine": 7
            }
        ]
        
        # ========== CATEGORIA GENERALE ==========
        generale_faq = [
            {
                "categoria": "GENERALE",
                "domanda": "Come faccio a rinnovare l'abbonamento?",
                "risposta": "Guida per il rinnovo dell'abbonamento:\n\n**Metodo 1 - Sito web:**\n1. Accedi al pannello utente\n2. Vai su 'Il mio abbonamento'\n3. Clicca su 'Rinnova ora'\n4. Scegli durata e metodo di pagamento\n5. Completa il pagamento\n\n**Metodo 2 - Tramite supporto:**\n• Contatta il supporto via ticket\n• Ti verranno forniti i dettagli per il pagamento\n\n**Metodo 3 - App:**\n• Alcune app IPTV permettono rinnovo diretto\n\n**Promemoria:**\n• Rinnova PRIMA della scadenza per evitare interruzioni\n• Controlla la data di scadenza nel pannello\n• Ricorda che il rinnovo è necessario ogni 1/3/6/12 mesi\n\n**Nota:** Non esistono abbonamenti 'a vita' - attenzione alle truffe!",
                "parole_chiave": ["rinnovo", "abbonamento", "scadenza", "rinnova", "pagamento", "prezzo"],
                "ordine": 1
            },
            {
                "categoria": "GENERALE",
                "domanda": "Posso usare lo stesso account su più dispositivi?",
                "risposta": "Informazioni su account multipli:\n\n**Policy standard:**\n• 1 connessione simultanea inclusa\n• Possibile aggiungere connessioni extra (contatta il supporto)\n\n**Dispositivi compatibili:**\n• Smartphone/Tablet Android\n• FireStick/Fire TV\n• Apple TV\n• Smart TV (Android)\n• PC/Mac (tramite app o browser)\n• Raspberry Pi\n\n**Attenzione:**\n• Usare lo stesso account su troppi dispositivi simultaneamente\n• Potrebbe causare disconnessioni\n• Non violare i termini di servizio\n\n**Consigli:**\n• Usa lo stesso account su max 2-3 dispositivi\n• Non guardare su tutti contemporaneamente\n• Se servono più connessioni, acquista extra",
                "parole_chiave": ["multi dispositivo", "più dispositivi", "connessioni", "simultaneo", "account"],
                "ordine": 2
            },
            {
                "categoria": "GENERALE",
                "domanda": "Come contattare il supporto tecnico?",
                "risposta": "Contatti per supporto tecnico:\n\n**1. Ticket system (consigliato):**\n• Crea un ticket dal bot Telegram\n• Usa comando /nuovo_ticket\n• Fornisci dettagli del problema\n\n**2. Email supporto:**\n• support@helperbot.it (se disponibile)\n\n**3. Orari di servizio:**\n• Lun-Ven: 09:00-20:00\n• Sab: 10:00-18:00\n• Domenica: solo emergenze\n\n**Quando creare un ticket:**\n• Problemi tecnici non risolti con FAQ\n• Guasto completo del servizio\n• Problemi di fatturazione\n• Richieste speciali\n\n**Per risposte rapide:**\n• Descrivi il problema in dettaglio\n• Includi screenshot se possibile\n• Indica dispositivo e app usata\n• Fornisci orario del problema",
                "parole_chiave": ["supporto", "contatto", "ticket", "aiuto", "tecnico", "numero"],
                "ordine": 3
            },
            {
                "categoria": "GENERALE",
                "domanda": "Quali sono le specifiche minime del dispositivo?",
                "risposta": "Requisiti minimi per utilizzare il servizio:\n\n**Android:**\n• Android 6.0 (Marshmallow) o superiore\n• 2GB RAM minimo\n• 500MB spazio libero\n\n**FireStick/Fire TV:**\n• Fire TV Stick Lite o superiore\n• Fire OS 7 o superiore\n\n**Smart TV:**\n• Smart TV con Android TV\n• Almeno 2GB RAM\n\n**Apple:**\n• iOS 12 o superiore\n• Apple TV 4K\n\n**PC:**\n• Windows 7+ / macOS 10+\n• Browser moderno (Chrome, Firefox)\n• 4GB RAM\n\n**Connessione internet:**\n• Minimo 10 Mbps (HD)\n• 25 Mbps (4K)\n• Connessione stabile\n\n**Nota:** Specifiche inferiori potrebbero funzionare ma con prestazioni ridotte.",
                "parole_chiave": ["requisiti", "specifiche", "minimi", "dispositivo", "compatibilità", "hardware"],
                "ordine": 4
            },
            {
                "categoria": "GENERALE",
                "domanda": "Il servizio è legale? Informazioni importanti",
                "risposta": "Informazioni importanti sulla legalità:\n\n**La nostra posizione:**\n• Forniamo tecnologia di streaming, non contenuti\n• Non siamo proprietari dei canali\n• I canali appartengono ai rispettivi broadcaster\n\n**Responsabilità dell'utente:**\n• L'utente è responsabile dell'uso che fa del servizio\n• Informati sulle leggi del tuo paese\n• Servizio per uso personale\n\n**Cosa NON facciamo:**\n• Non cloniamo canali\n• Non piratiamo contenuti\n• Non facilitiamo attività illegali\n\n**Alternative legali:**\n• Abbonamenti ufficiali ai broadcaster\n• Servizi come Netflix, Disney+, etc.\n\n**Nota:** Questa è una tecnologia di aggregazione di streaming legittima.",
                "parole_chiave": ["legale", "legalità", "legittimo", "canali", "copyright", "pirateria"],
                "ordine": 5
            },
            {
                "categoria": "GENERALE",
                "domanda": "Come cambiare lingua dell'interfaccia dell'app?",
                "risposta": "Cambiare lingua nell'app IPTV:\n\n**Metodo 1 - Impostazioni app:**\n1. Apri l'app IPTV\n2. Vai su Impostazioni (ingranaggio)\n3. Cerca 'Lingua' o 'Language'\n4. Seleziona la lingua desiderata\n\n**Metodo 2 - Impostazioni dispositivo:**\n• Android: Impostazioni > Lingua e immissione\n• FireStick: Impostazioni > Preferenze > Lingua\n\n**Lingue comuni disponibili:**\n• Italiano\n• Inglese\n• Spagnolo\n• Francese\n• Tedesco\n\n**Problemi lingua:**\n• Alcune app hanno traduzione incompleta\n• Ritorna a inglese se italiano ha bug\n• Aggiorna l'app per nuove traduzioni\n\n**Nota:** La lingua dell'app è indipendente dalla lingua dei canali!",
                "parole_chiave": ["lingua", "italiano", "inglese", "interfaccia", "traduzione", "impostazioni"],
                "ordine": 6
            },
            {
                "categoria": "GENERALE",
                "domanda": "Cosa fare in caso di disservizio generale?",
                "risposta": "Guida in caso di disservizio generale:\n\n**Step 1 - Verifica:**\n1. Controlla il nostro canale aggiornamenti (se disponibile)\n2. Prova a caricare il sito web\n3. Testa su altro dispositivo\n\n**Possibili cause:**\n• Manutenzione programmata\n• Problemi ai server principali\n• Problemi di rete del provider\n\n**Cosa fare:**\n• Attendi 15-30 minuti\n• Non creare ticket multipli\n• Segui gli aggiornamenti\n\n**Manutenzione:**\n• Di solito comunicata in anticipo\n• Durata massima 1-2 ore\n• Servizio ripristinato prima del previsto\n\n**Non è un disservizio se:**\n• Solo alcuni canali non funzionano\n• Solo il tuo dispositivo ha problemi\n• Hai problemi di connessione internet personale\n\n**Contatti durante emergenze:**\n• Canale Telegram per aggiornamenti",
                "parole_chiave": ["disservizio", "down", "non funziona", "servizio", "manutenzione", "problema"],
                "ordine": 7
            }
        ]
        
        # Combina tutte le FAQ
        faq_list = []
        faq_list.extend(connessione_faq)
        faq_list.extend(buffering_faq)
        faq_list.extend(app_bloccate_faq)
        faq_list.extend(contenuti_faq)
        faq_list.extend(firestick_faq)
        faq_list.extend(generale_faq)
        
        # Assegna ID a ciascuna FAQ
        for i, faq in enumerate(faq_list, start=1):
            faq["id"] = i
        
        # Salva nel file
        self._save_faq(faq_list)
        logger.info(f"Popolate {len(faq_list)} FAQ iniziali")
    
    def get_categorie(self) -> Dict[str, str]:
        """
        Restituisce tutte le categorie disponibili
        
        Returns:
            Dizionario con ID categoria e nome visualizzato
        """
        return self.CATEGORIE.copy()
    
    def get_faq_categoria(self, categoria: str) -> List[Dict]:
        """
        Restituisce tutte le FAQ di una categoria specifica
        
        Args:
            categoria: ID della categoria (es: 'CONNESSIONE')
            
        Returns:
            Lista di FAQ ordinate per ordine
        """
        faq_list = self._load_faq()
        category_faq = [f for f in faq_list if f.get("categoria") == categoria.upper()]
        return sorted(category_faq, key=lambda x: x.get("ordine", 0))
    
    def cerca_faq(self, testo: str) -> List[Dict]:
        """
        Cerca FAQ per parole chiave nel testo
        
        Args:
            testo: Testo da cercare
            
        Returns:
            Lista di FAQ che matchano con le parole chiave
        """
        if not testo or not testo.strip():
            return []
        
        faq_list = self._load_faq()
        testo_lower = testo.lower()
        
        # Estrai parole chiave dal testo di ricerca
        parole = testo_lower.split()
        
        risultati = []
        for faq in faq_list:
            # Cerca nelle parole chiave della FAQ
            keywords = faq.get("parole_chiave", [])
            match_score = 0
            
            for parola in parole:
                # Check nelle keywords
                for kw in keywords:
                    if parola in kw.lower():
                        match_score += 2
                
                # Check nel titolo (peso maggiore)
                if parola in faq.get("domanda", "").lower():
                    match_score += 3
                
                # Check nella risposta (peso minore)
                if parola in faq.get("risposta", "").lower():
                    match_score += 1
            
            if match_score > 0:
                faq_with_score = faq.copy()
                faq_with_score["match_score"] = match_score
                risultati.append(faq_with_score)
        
        # Ordina per match score decrescente
        return sorted(risultati, key=lambda x: x.get("match_score", 0), reverse=True)
    
    def suggerisci_faq(self, testo: str) -> Tuple[List[Dict], str]:
        """
        Suggerisce FAQ rilevanti per un problema descritto
        Utilizzato prima della creazione di un ticket
        
        Args:
            testo: Descrizione del problema
            
        Returns:
            Tuple con (lista_faq, suggerimento_testuale)
        """
        if not testo or len(testo.strip()) < 3:
            return [], ""
        
        # Cerca FAQ rilevanti
        risultati = self.cerca_faq(testo)
        
        if not risultati:
            # Prova con categorizzazione automatica basata su parole chiave
            return self._suggerimento_fallback(testo)
        
        # Prendi le prime 3 FAQ più rilevanti
        top_faq = risultati[:3]
        
        # Costruisci il suggerimento
        if len(top_faq) == 1:
            suggerimento = f"Ho trovato una FAQ che potrebbe aiutarti:\n\n"
        else:
            suggerimento = f"Ho trovato {len(top_faq)} FAQ che potrebbero aiutarti:\n\n"
        
        return top_faq, suggerimento
    
    def _suggerimento_fallback(self, testo: str) -> Tuple[List[Dict], str]:
        """
        Suggerimento basato su categorizzazione automatica
        quando la ricerca non trova risultati diretti
        """
        testo_lower = testo.lower()
        
        # Mappatura parole chiave -> categorie
        categorie_keywords = {
            "CONNESSIONE": ["conness", "server", "offline", "online", "disconness", "wifi", "ethernet", "ping", "porte", "lenta"],
            "BUFFERING": ["buffering", "caricamento", "lag", "stop", "attesa", "lento", "freez"],
            "APP_BLOCCATE": ["app", "crash", "non si apre", "install", "APK", "blocc", "error", "virus"],
            "CONTENUTI": ["canale", "film", "serie", "vod", "on demand", "epg", "guida", "non trovato"],
            "FIRESTICK": ["firestick", "fire tv", "cache", "reinstall", "slow", "prestazion"],
            "GENERALE": ["abbonamento", "rinnovo", "prezzo", "supporto", "contatto"]
        }
        
        # Trova la categoria più rilevante
        best_category = None
        best_score = 0
        
        for cat, keywords in categorie_keywords.items():
            score = sum(1 for kw in keywords if kw in testo_lower)
            if score > best_score:
                best_score = score
                best_category = cat
        
        if best_category and best_score > 0:
            category_faq = self.get_faq_categoria(best_category)
            if category_faq:
                return category_faq[:3], f"Basandomi sulla tua descrizione, sembra che tu stia riscontrando problemi di tipo '{self.CATEGORIE.get(best_category, best_category)}'. Ecco alcune FAQ che potrebbero aiutarti:\n\n"
        
        return [], ""
    
    def get_faq_id(self, faq_id: int) -> Optional[Dict]:
        """
        Ottiene una FAQ specifica per ID
        
        Args:
            faq_id: ID della FAQ
            
        Returns:
            Dizionario della FAQ o None se non trovata
        """
        faq_list = self._load_faq()
        for faq in faq_list:
            if faq.get("id") == faq_id:
                return faq.copy()
        return None
    
    def aggiungi_faq(self, categoria: str, domanda: str, risposta: str, 
                      parole_chiave: List[str] = None,
                  ordine: int = None) -> bool:
        """
        Aggiunge una nuova FAQ al sistema
        
        Args:
            categoria: Categoria della FAQ
            domanda: Testo della domanda
            risposta: Testo della risposta
            parole_chiave: Lista di parole chiave per la ricerca
            ordine: (Opzionale) Ordine di visualizzazione
            
        Returns:
            True se aggiunta con successo, False altrimenti
        """
        if categoria.upper() not in self.CATEGORIE:
            logger.error(f"Categoria non valida: {categoria}")
            return False
        
        faq_list = self._load_faq()
        
        # Determina l'ordine
        if ordine is None:
            # Usa il prossimo ordine disponibile nella categoria
            cat_faq = [f for f in faq_list if f.get("categoria") == categoria.upper()]
            ordine = max([f.get("ordine", 0) for f in cat_faq], default=0) + 1
        
        nuova_faq = {
            "id": self._get_next_id(faq_list),
            "categoria": categoria.upper(),
            "domanda": domanda.strip(),
            "risposta": risposta.strip(),
            "parole_chiave": [kw.strip().lower() for kw in parole_chiave],
            "ordine": ordine
        }
        
        faq_list.append(nuova_faq)
        
        if self._save_faq(faq_list):
            logger.info(f"FAQ aggiunta: ID {nuova_faq['id']} - {domanda[:50]}...")
            return True
        
        return False
    
    def modifica_faq(self, faq_id: int, categoria: Optional[str] = None, 
                     domanda: Optional[str] = None,
                     risposta: Optional[str] = None, 
                     parole_chiave: Optional[List[str]] = None,
                     ordine: Optional[int] = None) -> bool:
        """
        Modifica una FAQ esistente
        
        Args:
            faq_id: ID della FAQ da modificare
            categoria: (Opzionale) Nuova categoria
            domanda: (Opzionale) Nuova domanda
            risposta: (Opzionale) Nuova risposta
            parole_chiave: (Opzionale) Nuove parole chiave
            ordine: (Opzionale) Nuovo ordine
            
        Returns:
            True se modificata con successo, False altrimenti
        """
        faq_list = self._load_faq()
        
        for i, faq in enumerate(faq_list):
            if faq.get("id") == faq_id:
                # Verifica categoria
                if categoria and categoria.upper() not in self.CATEGORIE:
                    logger.error(f"Categoria non valida: {categoria}")
                    return False
                
                # Applica le modifiche
                if categoria:
                    faq_list[i]["categoria"] = categoria.upper()
                if domanda:
                    faq_list[i]["domanda"] = domanda.strip()
                if risposta:
                    faq_list[i]["risposta"] = risposta.strip()
                if parole_chiave is not None:
                    faq_list[i]["parole_chiave"] = [kw.strip().lower() for kw in parole_chiave]
                if ordine is not None:
                    faq_list[i]["ordine"] = ordine

                if self._save_faq(faq_list):
                    logger.info(f"FAQ modificata: ID {faq_id}")
                    return True

                return False
        
        logger.error(f"FAQ non trovata: ID {faq_id}")
        return False
    
    def rimuovi_faq(self, faq_id: int) -> bool:
        """
        Rimuove una FAQ dal sistema
        
        Args:
            faq_id: ID della FAQ da rimuovere
            
        Returns:
            True se rimossa con successo, False altrimenti
        """
        faq_list = self._load_faq()
        
        for i, faq in enumerate(faq_list):
            if faq.get("id") == faq_id:
                faq_list.pop(i)
                
                if self._save_faq(faq_list):
                    logger.info(f"FAQ rimossa: ID {faq_id}")
                    return True
                
                return False
        
        logger.error(f"FAQ non trovata per rimozione: ID {faq_id}")
        return False
    
    def get_stats(self) -> Dict:
        """
        Restituisce statistiche sul sistema FAQ
        
        Returns:
            Dizionario con statistiche
        """
        faq_list = self._load_faq()
        
        stats = {
            "totale_faq": len(faq_list),
            "per_categoria": {}
        }
        
        for cat_id in self.CATEGORIE.keys():
            count = sum(1 for f in faq_list if f.get("categoria") == cat_id)
            stats["per_categoria"][cat_id] = count
        
        return stats
    
    def build_keyboard_categorie(self) -> List[List[Dict]]:
        """
        Costruisce la keyboard inline per la selezione delle categorie
        
        Returns:
            Lista di pulsanti inline per categorie
        """
        keyboard = []
        row = []
        
        for cat_id, cat_name in self.CATEGORIE.items():
            row.append({"text": cat_name, "callback_data": f"faq_cat_{cat_id}"})
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        # Aggiungi l'ultima riga se presente
        if row:
            keyboard.append(row)
        
        # Aggiungi pulsante per cercare
        keyboard.append([{"text": "🔍 cerca FAQ", "callback_data": "faq_search"}])
        
        return keyboard
    
    def build_keyboard_faq_list(self, faq_list: List[Dict]) -> List[List[Dict]]:
        """
        Costruisce la keyboard inline per una lista di FAQ
        
        Args:
            faq_list: Lista di FAQ da mostrare
            
        Returns:
            Lista di pulsanti inline
        """
        keyboard = []
        
        for faq in faq_list:
            # Tronca il titolo per il bottone
            title = faq.get("domanda", "")[:40]
            if len(faq.get("domanda", "")) > 40:
                title += "..."
            
            keyboard.append([{
                "text": f"📋 {title}",
                "callback_data": f"faq_view_{faq.get('id')}"
            }])
        
        return keyboard
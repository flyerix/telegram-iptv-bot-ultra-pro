# 🤖 HelperBot - Bot Telegram per Gestione IPTV

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/Telegram-Bot-blue?style=flat-square" alt="Telegram">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Version-2.0.0-yellowgreen?style=flat-square" alt="Version">
</p>

HelperBot è un bot Telegram completo e avanzato progettato per la gestione di servizi IPTV. Offre un sistema integrato di gestione utenti, ticket di supporto, FAQ, backup automatici, statistiche e molto altro.

## 📋 Indice

1. [Descrizione del Progetto](#descrizione-del-progetto)
2. [Caratteristiche Principali](#caratteristiche-principali)
3. [Prerequisiti e Installazione](#prerequisiti-e-installazione)
4. [Configurazione](#configurazione)
5. [Avvio del Bot](#avvio-del-bot)
6. [Comandi Disponibili](#comandi-disponibili)
7. [Deployment Gratuito 24/7](#deployment-gratuito-247)
8. [Configurazione Google Drive (Opzionale)](#configurazione-google-drive-opzionale)
9. [Note sulla Sicurezza](#note-sulla-sicurezza)
10. [Struttura del Progetto](#struttura-del-progetto)
11. [Licenza e Ringraziamenti](#licenza-e-ringraziamenti)

---

## 1. Descrizione del Progetto

HelperBot è un bot Telegram multifunzionale sviluppato in Python che permette di:

- **Gestire utenti e liste IPTV**: Registrazione utenti, richiesta e assegnazione di liste IPTV
- **Supporto tecnico avanzato**: Sistema di ticket con priorità automatica e gestione delle richieste
- **FAQ dinamiche**: Sistema di FAQ categorizzate con ricerca
- **Backup automatici**: Backup locali e su Google Drive
- **Statistiche in tempo reale**: Dashboard visuale delle statistiche del bot
- **Notifiche intelligenti**: Sistema di notifiche proattive
- **Modalità manutenzione**: Possibilità di mettere il bot in manutenzione
- **Onboarding guidato**: Guida passo-passo per i nuovi utenti

Il bot è progettato per essere facilmente estendibile e deployabile su piattaforme gratuite.

---

## 2. Caratteristiche Principali

Il bot include **oltre 19 funzionalità avanzate**:

### 🎯 Gestione Utenti e IPTV
1. **Registrazione utenti automatica** - Gli utenti vengono registrati automaticamente al primo avvio
2. **Gestione richieste lista IPTV** - Sistema di richiesta/approvazione delle liste
3. **Scadenza automatica** - Gestione delle date di scadenza delle liste
4. **Note personalizzate** - Possibilità di aggiungere note agli utenti

### 🎫 Sistema Ticket
5. **Creazione ticket con priorità** - Ticket con priorità alta, media o bassa
6. **Assegnazione automatica** - Assegnazione automatica dei ticket agli admin
7. **Stati del ticket** - Aperto, in lavorazione, risolto, chiuso
8. **Cronologia ticket** - Storico completo delle interazioni

### ❓ Sistema FAQ
9. **FAQ categorizzate** - Organizzazione in categorie (Generale, IPTV, tecnico, pagamenti)
10. **Navigazione interattiva** - Menu inline per navigare le FAQ
11. **Ricerca FAQ** - Possibilità di cercare nelle domande frequenti

### 💾 Sistema Backup
12. **Backup locale automatico** - Salvataggio periodico dei dati in locale
13. **Backup Google Drive** - Backup su cloud (opzionale)
14. **Restore dei dati** - Possibilità di ripristinare da backup

### 📊 Statistiche e Monitoraggio
15. **Dashboard statistiche** - Statistiche visuali degli utenti e ticket
16. **Stato servizio in tempo reale** - Monitoraggio dello stato del bot
17. **Uptime tracking** - Tracciamento del tempo di attività

### 🔔 Sistema Notifiche
18. **Notifiche admin** - Notifiche agli admin per nuovi ticket/richieste
19. **Notifiche utente** - Messaggi automatici agli utenti (stato ticket, scadenze)

### ⚙️ Funzionalità Aggiuntive
20. **Rate limiting** - Protezione da abusi e spam
21. **Modalità manutenzione** - Possibilità di disabilitare il bot temporaneamente
22. **Onboarding guidato** - Procedura di benvenuto per nuovi utenti
23. **Keep-alive server** - Server integrato per evitare che il bot vada in sleep
24. **Logging avanzato** - Sistema di logging completo per debugging

---

## 3. Prerequisiti e Installazione

### Prerequisiti

- **Python 3.9 o superiore**
- **Token bot Telegram** ([Come ottenere un token](https://core.telegram.org/bots/tutorial#obtain-your-bot-token))
- **Account Telegram** per creare il bot

### Installazione

1. **Clona il repository o scarica i file:**

```bash
git clone https://github.com/tuouser/helperbot.git
cd helperbot
```

2. **Crea e attiva un ambiente virtuale (consigliato):**

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

3. **Installa le dipendenze:**

```bash
# Installa tutte le dipendenze (consigliato)
pip install -r requirements.txt

# Oppure installa solo le dipendenze principali
pip install python-telegram-bot>=20.0 Flask>=2.0.0 python-dotenv>=0.19.0
```

---

## 4. Configurazione

### Variabili d'Ambiente

Il bot utilizza le seguenti variabili d'ambiente. Puoi impostarle in un file `.env`:

```bash
# ============================================
# CONFIGURAZIONE OBBLIGATORIA
# ============================================

# Token del bot Telegram (obbligatorio)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# ID degli admin separati da virgola (obbligatorio)
# Per ottenere il tuo ID: @userinfobot su Telegram
ADMIN_IDS=123456789,987654321

# ============================================
# CONFIGURAZIONE OPZIONALE
# ============================================

# Porta per il server keep-alive (default: 8080)
KEEPALIVE_PORT=8080

# Host per il server keep-alive (default: 0.0.0.0)
KEEPALIVE_HOST=0.0.0.0

# ============================================
# CONFIGURAZIONE GOOGLE DRIVE (OPZIONALE)
# ============================================

# Per il backup su Google Drive (vedi sezione dedicata)
GOOGLE_DRIVE_CREDENTIALS=credentials.json
GOOGLE_DRIVE_TOKEN=token.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
```

### File `.env` Esempio

Crea un file `.env` nella root del progetto:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_IDS=123456789,987654321
KEEPALIVE_PORT=8080
KEEPALIVE_HOST=0.0.0.0
```

### Ottenere gli Admin IDs

1. Aggiungi [@userinfobot](https://t.me/userinfobot) su Telegram
2. Invia il comando `/start`
3. Copia il tuo **ID utente** (numero grande)
4. Aggiungilo alla variabile `ADMIN_IDS`

---

## 5. Avvio del Bot

### Avvio Locale

```bash
python main.py
```

Oppure con il bot in background:

```bash
# Windows (PowerShell)
Start-Process python main.py

# Linux/Mac
nohup python main.py &
```

### Verifica che il Bot sia Attivo

1. Apri Telegram
2. Cerca il tuo bot
3. Invia il comando `/start`

---

## 6. Comandi Disponibili

### 📋 Comandi Utente

| Comando | Descrizione |
|---------|-------------|
| `/start` | Avvia il bot e mostra il menu principale |
| `/help` | Mostra la guida e i comandi disponibili |
| `/faq` | Visualizza le FAQ organizzate per categorie |
| `/ticket` | Crea un nuovo ticket di supporto |
| `/miei_ticket` | Visualizza i tuoi ticket creati |
| `/richiedi` | Richiedi una lista IPTV |
| `/lista` | Visualizza la tua lista IPTV attiva |
| `/stato` | Visualizza lo stato del servizio |

### ⚙️ Comandi Admin

| Comando | Descrizione |
|---------|-------------|
| `/admin` | Apre il menu di amministrazione |
| `/richieste` | Visualizza e gestisce le richieste IPTV in attesa |
| `/broadcast` | Invia un messaggio a tutti gli utenti |
| `/stats` | Visualizza le statistiche del bot |
| `/backup` | Esegue un backup manuale |
| `/manutenzione` | Attiva/disattiva la modalità manutenzione |

### Callback Query (Menu Inline)

- `menu_stato` - Visualizza stato utente
- `menu_aggiorna_lista` - Aggiorna lista IPTV
- `faq_categorie` - Visualizza categorie FAQ
- `ticket_create` - Crea ticket
- `admin_*` - Menu admin

---

## 7. Deployment Gratuito 24/7

Puoi hostare il bot gratuitamente su diverse piattaforme. Ecco le più comuni:

### 🟣 Render (Consigliato)

1. **Crea un account** su [render.com](https://render.com)
2. **Connetti il tuo repository** GitHub
3. **Crea un nuovo Web Service** con queste impostazioni:

```
Name: helperbot
Environment: Python
Build Command: pip install -r requirements.txt
Start Command: python main.py
```

4. **Aggiungi le variabili d'ambiente** nella sezione "Environment Variables":
   - `TELEGRAM_BOT_TOKEN` = il tuo token
   - `ADMIN_IDS` = i tuoi ID admin

5. **Deploy!** 🎉

### 🚂 Railway

1. **Crea un account** su [railway.app](https://railway.app)
2. **Installa Railway CLI**:
```bash
npm install -g @railway/cli
```

3. **Deploya il bot**:
```bash
railway login
railway init
railway up
```

4. **Configura le variabili d'ambiente**:
```bash
railway variables set TELEGRAM_BOT_TOKEN=xxx
railway variables set ADMIN_IDS=xxx
```

### ☁️ Heroku (Alternativa)

1. **Crea un account** su [heroku.com](https://heroku.com)
2. **Crea un nuovo app**
3. **Connetti il repository GitHub**
4. **Configura le variabili d'ambiente** nelle impostazioni
5. **Deploya**

### ⚠️ Importante per Render/Railway

Aggiungi il file `runtime.txt` nella root del progetto:

```
python-3.9.18
```

### Keep-Alive Server

Il bot include un server keep-alive integrato che risponde alle richieste HTTP per evitare che il bot vada in sleep su piattaforme serverless. La porta predefinita è `8080`.

---

## 8. Configurazione Google Drive (Opzionale)

Il bot supporta il backup automatico su Google Drive.

### Passaggi per la Configurazione

1. **Crea un progetto su Google Cloud Console:**
   - Vai su [console.cloud.google.com](https://console.cloud.google.com)
   - Crea un nuovo progetto
   - Abilita Google Drive API

2. **Credenziali OAuth:**
   - Vai su "Credenziali" > "Crea credenziali" > "ID client OAuth"
   - Scarica le credenziali come `credentials.json`
   - Posiziona il file nella root del progetto

3. **Configura il token:**
   - Al primo avvio del bot,segui le istruzioni per autenticarti
   - Il token verrà salvato come `token.json`

4. **ID Cartella Drive:**
   - Crea una cartella su Google Drive
   - Copia l'ID dalla URL (stringa lunga alla fine)
   - Imposta la variabile `GOOGLE_DRIVE_FOLDER_ID`

### Variabili d'Ambiente Aggiuntive

```env
GOOGLE_DRIVE_CREDENTIALS=credentials.json
GOOGLE_DRIVE_TOKEN=token.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
```

---

## 9. Note sulla Sicurezza

⚠️ **Importanti raccomandazioni per la sicurezza:**

1. **Non condividere il Token**: Il token del bot è segreto. Non pubblicarlo mai.
2. **Proteggi gli Admin IDs**: Limita l'accesso admin alle persone fidate.
3. **Usa Environment Variables**: Non hardcodare credenziali nel codice.
4. **Backup regolari**: Esegui backup periodici dei dati.
5. **Log degli accessi**: Il bot registra tutti gli accessi per sicurezza.
6. **Rate Limiting**: Implementato per prevenire abusi.
7. **Validazione input**: Tutti gli input utente vengono validati.

### Protezione Dockerfile (se usato)

```dockerfile
# Non includere il token nel Dockerfile
# Usa argomenti invece
ARG TELEGRAM_BOT_TOKEN
ENV TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
```

---

## 10. Struttura del Progetto

```
helperbot/
├── 📁 core/                    # Moduli core del sistema
│   ├── data_persistence.py     # Gestione persistenza dati JSON
│   └── logger.py               # Sistema di logging avanzato
│
├── 📁 modules/                 # Moduli funzionalità
│   ├── user_management.py     # Gestione utenti e liste IPTV
│   ├── ticket_system.py       # Sistema ticket con priorità
│   ├── rate_limiter.py        # Rate limiting
│   ├── faq_system.py           # Sistema FAQ avanzato
│   ├── backup_system.py       # Backup locale e Google Drive
│   ├── onboarding.py           # Sistema di onboarding
│   ├── stato_servizio.py      # Stato servizio e uptime
│   ├── manutenzione.py         # Modalità manutenzione
│   ├── notifications.py        # Sistema notifiche
│   └── statistiche.py         # Dashboard statistiche
│
├── 📁 keepalive/               # Server keep-alive
│   ├── __init__.py
│   └── server.py               # Server Flask per ping
│
├── 📁 data/                    # Directory dati (creata automaticamente)
│   ├── users.json
│   ├── tickets.json
│   ├── richieste.json
│   ├── faq.json
│   └── backup/
│
├── 📄 main.py                  # File principale del bot
├── 📄 requirements.txt         # Dipendenze Python
├── 📄 .env                     # Variabili d'ambiente (non tracciare!)
├── 📄 .gitignore               # File ignorati da Git
├── 📄 runtime.txt              # Versione Python per deployment
└── 📄 README.md                # Questo file
```

---

## 11. Licenza e Ringraziamenti

### 📜 Licenza

Questo progetto è rilasciato sotto licenza **MIT**.

```
MIT License

Copyright (c) 2024 HelperBot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 🙏 Ringraziamenti

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** - Per l'eccellente libreria Telegram
- **[Flask](https://github.com/pallets/flask)** - Per il server keep-alive
- **[Google](https://google.github.io/google-api-python-client/docs/)** - Per le API Google Drive
- **[APScheduler](https://apscheduler.readthedocs.io/)** - Per lo scheduling dei backup

---

## ❓ Supporto

Se hai bisogno di aiuto:

1. Consulta le **FAQ** con il comando `/faq`
2. Crea un **ticket** con il comando `/ticket`
3. Contatta gli **admin** del bot

---

<p align="center">
  <strong>⭐ Se questo progetto ti è utile, considera di mettere una stella su GitHub!</strong>
</p>

<p align="center">
  <img src="https://komarev.com/ghpvc/?username=helperbot&label=Views&color=blueviolet" alt="GitHub views">
</p>

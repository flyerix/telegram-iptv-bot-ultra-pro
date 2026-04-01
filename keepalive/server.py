"""
Keep-Alive Server per HelperBot
Mantiene il bot online 24/7 con un server HTTP leggero
"""

import threading
import logging
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, Response
from typing import Dict, Any, Optional
import requests

# Variabile globale per l'application del bot (usata per webhook)
_bot_application = None
_webhook_secret_token = None

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Istanza Flask
app = Flask(__name__)

# Variabili globali per lo stato del server
_server = None
_server_thread = None
_is_running = False
_start_time = None

# Statistiche globali
stats = {
    "requests": 0,
    "ping_requests": 0,
    "health_requests": 0,
    "status_requests": 0,
    "start_time": None
}


def _get_uptime() -> str:
    """Calcola il tempo di attività del server"""
    if _start_time is None:
        return "0s"
    elapsed = int(time.time() - _start_time)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


@app.route('/')
def home():
    """Homepage con informazioni sul servizio"""
    stats["requests"] += 1
    logger.info(f"Richiesta homepage da {request.remote_addr}")
    
    return jsonify({
        "service": "HelperBot Keep-Alive Server",
        "version": "1.0.0",
        "status": "online",
        "uptime": _get_uptime(),
        "endpoints": {
            "/": "Homepage",
            "/ping": "Ping semplice",
            "/health": "Stato completo del servizio",
            "/status": "Status del bot"
        }
    })


@app.route('/ping')
def ping():
    """Endpoint ping - risposta semplice 'pong'"""
    stats["requests"] += 1
    stats["ping_requests"] += 1
    logger.debug(f"Ping da {request.remote_addr}")
    
    return jsonify({
        "status": "pong",
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route('/health')
def health():
    """Endpoint health - stato completo del servizio"""
    stats["requests"] += 1
    stats["health_requests"] += 1
    logger.info(f"Health check da {request.remote_addr}")
    
    return jsonify({
        "status": "healthy",
        "service": "helperbot-keepalive",
        "uptime": _get_uptime(),
        "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
        "requests": {
            "total": stats["requests"],
            "ping": stats["ping_requests"],
            "health": stats["health_requests"],
            "status": stats["status_requests"]
        },
        "server": {
            "running": _is_running,
            "port": _server
        },
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route('/status')
def status():
    """Endpoint status - stato del bot"""
    stats["requests"] += 1
    stats["status_requests"] += 1
    logger.info(f"Status check da {request.remote_addr}")
    
    # Leggi lo stato del bot dai dati (se disponibili)
    bot_status = _get_bot_status()
    
    return jsonify({
        "bot": {
            "status": "online",
            "uptime": _get_uptime()
        },
        "statistics": {
            "total_requests": stats["requests"],
            "ping_requests": stats["ping_requests"],
            "health_requests": stats["health_requests"],
            "status_requests": stats["status_requests"]
        },
        "timestamp": datetime.utcnow().isoformat()
    })


def _get_bot_status() -> Dict[str, Any]:
    """
    Ottiene lo stato del bot dalle statistiche globali
    Integra con gli altri moduli del bot se disponibili
    """
    status = {
        "active": True,
        "modules_loaded": []
    }
    
    # Prova a importare i moduli del bot per ottenere statistiche
    try:
        from modules import statistiche
        if hasattr(statistiche, 'get_stats'):
            status["stats"] = statistiche.get_stats()
    except ImportError:
        pass
    
    return status


def set_bot_application(application):
    """
    Imposta l'application del bot per il webhook
    
    Args:
        application: Application di telegram.ext
    """
    global _bot_application
    _bot_application = application
    logger.info("Application del bot impostata per il webhook")


def set_webhook_secret(secret_token: str):
    """
    Imposta il token segreto per la verifica del webhook
    
    Args:
        secret_token: Token segreto per autenticare le richieste
    """
    global _webhook_secret_token
    _webhook_secret_token = secret_token
    logger.info("Token segreto per webhook configurato")


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint webhook per ricevere update da Telegram
    """
    global _bot_application
    
    stats["requests"] += 1
    
    # Verifica che l'application sia configurata
    if _bot_application is None:
        logger.error("Application non configurata per webhook")
        return jsonify({"error": "Bot not configured"}), 500
    
    # Verifica il token segreto (se configurato)
    if _webhook_secret_token:
        secret_header = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret_header != _webhook_secret_token:
            logger.warning("Token segreto non valido per webhook")
            return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Parse del JSON ricevuto
        update_data = request.get_json()
        
        if not update_data:
            logger.warning("Nessun dato JSON ricevuto nel webhook")
            return jsonify({"error": "No data"}), 400
        
        logger.debug(f"Update ricevuta: {update_data.get('update_id', 'N/A')}")
        
        # Crea l'oggetto Update da Telegram
        from telegram import Update
        from telegram.ext import Application
        
        # Crea l'update manualmente
        update = Update.de_json(update_data, _bot_application.bot)
        
        # Processa l'update usando l'application
        # Usiamo un executor per gestire le coroutine in modo sicuro
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_async_process():
            """Esegui la coroutine in un nuovo event loop"""
            try:
                # Crea un nuovo event loop per questo thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(_bot_application.process_update(update))
                finally:
                    new_loop.close()
            except Exception as e:
                logger.error(f"Errore nell'elaborazione async: {e}")
        
        # Esegui in un thread pool per evitare problemi con l'event loop
        executor = ThreadPoolExecutor(max_workers=1)
        executor.submit(run_async_process)
        executor.shutdown(wait=False)
        
        return Response(status=200)
        
    except Exception as e:
        logger.error(f"Errore nel processing del webhook: {e}")
        return jsonify({"error": str(e)}), 500


def start_server(port: int = None, threaded: bool = True) -> bool:
    """
    Avvia il server keep-alive
    
    Args:
        port: Porta su cui eseguire il server (default: PORT env o 8080)
        threaded: Se True, esegue il server in un thread separato
    
    Returns:
        True se il server è stato avviato con successo
    """
    # Leggi la variabile d'ambiente PORT (standard Render.com)
    import os
    if port is None:
        port_env = os.environ.get("PORT") or os.environ.get("KEEPALIVE_PORT")
        if port_env is None:
            logger.warning("PORT environment variable not set, using default 8080")
            port = 8080
        else:
            port = int(port_env)
    
    logger.info(f"Configurazione server: porta={port}, host=0.0.0.0")
    global _server, _server_thread, _is_running, _start_time
    
    if _is_running:
        logger.warning(f"Server già in esecuzione sulla porta {port}")
        return False
    
    try:
        _start_time = time.time()
        stats["start_time"] = datetime.utcnow().isoformat()
        
        if threaded:
            # Avvia in un thread separato
            _server_thread = threading.Thread(
                target=_run_server,
                args=(port,),
                daemon=True
            )
            _server_thread.start()
            logger.info(f"Server keep-alive avviato in background sulla porta {port}")
            
            # Attendi che il server sia effettivamente in ascolto
            logger.info("Attesa per binding del server...")
            time.sleep(2)
            logger.info("Thread server avviato, procedura completata")
            
            # Avvia health check thread per monitorare il server
            health_thread = threading.Thread(
                target=_health_check_loop,
                args=(port,),
                daemon=True
            )
            health_thread.start()
        else:
            # Avvia bloccante
            _run_server(port)
        
        _is_running = True
        return True
        
    except Exception as e:
        logger.error(f"Errore nell'avvio del server: {e}")
        return False


def _health_check_loop(port: int):
    """
    Thread che monitora lo stato del server e lo riavvia se necessario.
    """
    # Attendi 30 secondi prima del primo health check per dare tempo al server di avviarsi
    logger.info("Health check: attesa iniziale di 30 secondi...")
    time.sleep(30)
    
    while _is_running:
        try:
            # Verifica che il server Flask risponda
            # Prova a fare una richiesta a localhost
            try:
                response = requests.get(f"http://localhost:{port}/health", timeout=2)
                if response.status_code != 200:
                    logger.warning("Health check fallito, riavvio server...")
                    _restart_server(port)
            except requests.exceptions.RequestException:
                logger.warning("Health check fallito (connessione rifiutata), riavvio server...")
                _restart_server(port)
        except Exception as e:
            logger.error(f"Errore health check: {e}")
        
        # Aspetta 60 secondi prima del prossimo check
        time.sleep(60)


def _restart_server(port: int):
    """
    Riavvia il server Flask.
    """
    global _is_running, _server_thread
    
    logger.info("Riavvio server keep-alive...")
    _is_running = False
    
    #少量的 attesa per il thread precedente
    time.sleep(2)
    
    # Riavvia il server
    _server_thread = threading.Thread(
        target=_run_server,
        args=(port,),
        daemon=True
    )
    _server_thread.start()
    _is_running = True
    _start_time = time.time()
    stats["start_time"] = datetime.utcnow().isoformat()
    logger.info("Server keep-alive riavviato con successo")


def _run_server(port: int):
    """Funzione interna per eseguire il server Flask"""
    global _server
    try:
        logger.info(f"Tentativo di avvio server Flask su porta {port}")
        # Usa threaded=True per gestire più richieste
        app.run(
            host='0.0.0.0',
            port=port,
            threaded=True,
            debug=False,
            use_reloader=False,  # Disabilita il reloader per evitare doppie istanze
            log_level=logging.INFO  # Assicura che il log di Flask sia visibile
        )
    except Exception as e:
        logger.error(f"Errore nell'esecuzione del server: {e}")
        import traceback
        logger.error(traceback.format_exc())
        _is_running = False


def stop_server() -> bool:
    """
    Ferma il server keep-alive
    
    Returns:
        True se il server è stato fermato con successo
    """
    global _is_running, _server
    
    if not _is_running:
        logger.warning("Server non in esecuzione")
        return False
    
    try:
        # Nota: Flask non supporta shutdown elegante da codice
        # Il thread verrà terminato quando il processo principale termina
        _is_running = False
        logger.info("Server keep-alive fermato")
        return True
    except Exception as e:
        logger.error(f"Errore nell'arresto del server: {e}")
        return False


def get_status() -> Dict[str, Any]:
    """
    Ottiene lo stato corrente del server
    
    Returns:
        Dizionario con lo stato del server
    """
    return {
        "running": _is_running,
        "uptime": _get_uptime() if _is_running else "0s",
        "requests": stats["requests"],
        "port": _server if isinstance(_server, int) else None,
        "start_time": stats.get("start_time")
    }


def reset_stats():
    """Resetta le statistiche delle richieste"""
    stats["requests"] = 0
    stats["ping_requests"] = 0
    stats["health_requests"] = 0
    stats["status_requests"] = 0
    logger.info("Statistiche resettate")


# Per testing diretto
if __name__ == '__main__':
    print("Avvio Keep-Alive Server...")
    start_server(port=5000, threaded=False)

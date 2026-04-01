"""
Keep-Alive Server per HelperBot
Mantiene il bot online 24/7 con un server HTTP leggero
"""

import threading
import logging
import time
from datetime import datetime
from flask import Flask, jsonify, request
from typing import Dict, Any, Optional
import requests

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


def start_server(port: int = 5000, threaded: bool = True) -> bool:
    """
    Avvia il server keep-alive
    
    Args:
        port: Porta su cui eseguire il server (default 5000)
        threaded: Se True, esegue il server in un thread separato
    
    Returns:
        True se il server è stato avviato con successo
    """
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
        # Usa threaded=True per gestire più richieste
        app.run(
            host='0.0.0.0',
            port=port,
            threaded=True,
            debug=False,
            use_reloader=False  # Disabilita il reloader per evitare doppie istanze
        )
    except Exception as e:
        logger.error(f"Errore nell'esecuzione del server: {e}")
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

"""
Keep-Alive Server per HelperBot
Mantiene il bot online 24/7 con un server HTTP leggero
"""

import threading
import logging
import time
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict, Any, Optional
import requests

# Variabile globale per l'application del bot (usata per webhook)
_bot_application = None
_webhook_secret_token = None

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Variabili globali per lo stato del server
_server = None
_server_thread = None
_is_running = False
_start_time = None
_port = None

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


class BotRequestHandler(BaseHTTPRequestHandler):
    """
    Handler personalizzato per gestire le richieste HTTP
    """
    
    def log_message(self, format, *args):
        """Override per usare il nostro logger"""
        logger.info(f"{self.address_string()} - {format % args}")
    
    def _send_json_response(self, data: Dict[str, Any], status_code: int = 200):
        """Invia una risposta JSON"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def do_GET(self):
        """Gestisce le richieste GET"""
        global stats
        
        if self.path == '/':
            stats["requests"] += 1
            logger.info(f"Richiesta homepage da {self.client_address}")
            
            self._send_json_response({
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
        
        elif self.path == '/ping':
            stats["requests"] += 1
            stats["ping_requests"] += 1
            logger.debug(f"Ping da {self.client_address}")
            
            self._send_json_response({
                "status": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif self.path == '/health':
            stats["requests"] += 1
            stats["health_requests"] += 1
            logger.info(f"Health check da {self.client_address}")
            
            self._send_json_response({
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
                    "port": _port
                },
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif self.path == '/status':
            stats["requests"] += 1
            stats["status_requests"] += 1
            logger.info(f"Status check da {self.client_address}")
            
            bot_status = _get_bot_status()
            
            self._send_json_response({
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
        
        else:
            # Rotta non trovata
            self._send_json_response({"error": "Not found"}, 404)
    
    def do_POST(self):
        """Gestisce le richieste POST"""
        global stats, _bot_application, _webhook_secret_token
        
        if self.path == '/webhook':
            stats["requests"] += 1
            
            # Verifica che l'application sia configurata
            if _bot_application is None:
                logger.error("Application non configurata per webhook")
                self._send_json_response({"error": "Bot not configured"}, 500)
                return
            
            # Verifica il token segreto (se configurato)
            if _webhook_secret_token:
                secret_header = self.headers.get('X-Telegram-Bot-Api-Secret-Token')
                if secret_header != _webhook_secret_token:
                    logger.warning("Token segreto non valido per webhook")
                    self._send_json_response({"error": "Unauthorized"}, 401)
                    return
            
            try:
                # Leggi il contenuto della richiesta
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    logger.warning("Nessun dato ricevuto nel webhook")
                    self._send_json_response({"error": "No data"}, 400)
                    return
                
                body = self.rfile.read(content_length)
                update_data = json.loads(body.decode('utf-8'))
                
                logger.debug(f"Update ricevuta: {update_data.get('update_id', 'N/A')}")
                
                # Crea l'oggetto Update da Telegram
                from telegram import Update
                
                # Crea l'update manualmente
                update = Update.de_json(update_data, _bot_application.bot)
                
                # Processa l'update usando l'application
                import asyncio
                from concurrent.futures import ThreadPoolExecutor
                
                def run_async_process():
                    """Esegui la coroutine in un nuovo event loop"""
                    try:
                        # Crea un nuovo event loop per questo thread
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            # Usa run_until_complete che blocca fino al completamento
                            new_loop.run_until_complete(_bot_application.process_update(update))
                        finally:
                            new_loop.close()
                    except Exception as e:
                        logger.error(f"Errore nell'elaborazione async: {e}")

                # Esegui in un thread pool - usa un executor condiviso
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future = executor.submit(run_async_process)
                    # Aspetta il completamento per evitare race conditions
                    try:
                        future.result(timeout=30)
                    except Exception as e:
                        logger.error(f"Timeout o errore nell'elaborazione: {e}")
                
                # Risposta vuota (200 OK)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{}')
                
            except json.JSONDecodeError as e:
                logger.error(f"Errore parsing JSON: {e}")
                self._send_json_response({"error": "Invalid JSON"}, 400)
            
            except Exception as e:
                logger.error(f"Errore nel processing del webhook: {e}")
                self._send_json_response({"error": str(e)}, 500)
        
        else:
            # Rotta non trovata
            self._send_json_response({"error": "Not found"}, 404)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Server HTTP che gestisce ogni richiesta in un thread separato"""
    daemon_threads = True


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


def start_server(port: int = None, threaded: bool = False) -> bool:
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
    
    logger.info(f"=== START_SERVER CALLED === port={port}, threaded={threaded}")
    logger.info(f"Configurazione server: porta={port}, host=0.0.0.0")
    logger.info(f"Environment variables: PORT={os.environ.get('PORT')}, KEEPALIVE_PORT={os.environ.get('KEEPALIVE_PORT')}")
    global _server, _server_thread, _is_running, _start_time, _port
    
    _port = port
    
    if _is_running:
        logger.warning(f"Server già in esecuzione sulla porta {port}")
        return False
    
    try:
        _start_time = time.time()
        stats["start_time"] = datetime.utcnow().isoformat()
        logger.info("=== STATS INITIALIZED ===")
        
        if threaded:
            # Avvia in un thread separato
            logger.info("=== CREATING SERVER THREAD ===")
            _server_thread = threading.Thread(
                target=_run_server,
                args=(port,),
                daemon=False  # Non daemon per evitare chiusura prematura
            )
            logger.info(f"=== THREAD CREATED, STARTING... === daemon={_server_thread.daemon}")
            _server_thread.start()
            logger.info(f"=== THREAD STARTED, thread.is_alive={_server_thread.is_alive()} ===")
            logger.info(f"Server keep-alive avviato in background sulla porta {port}")
            
            # Attendi che il server sia effettivamente in ascolto - tempo maggiore
            logger.info("=== WAITING FOR SERVER BINDING ===")
            max_wait = 10
            waited = 0
            while waited < max_wait:
                time.sleep(1)
                waited += 1
                logger.info(f"Attesa binding server... ({waited}/{max_wait}s), is_running={_is_running}")
                
                # Verifica anche che il server sia effettivamente in ascolto
                if verify_server_listening(port):
                    logger.info(f"=== SERVER IS LISTENING after {waited}s ===")
                    break
            
            logger.info(f"=== THREAD START COMPLETE, is_running={_is_running} ===")
            
            # Avvia health check thread per monitorare il server
            health_thread = threading.Thread(
                target=_health_check_loop,
                args=(port,),
                daemon=True
            )
            health_thread.start()
            logger.info("=== HEALTH CHECK THREAD STARTED ===")
        else:
            # Avvia bloccante
            logger.info("=== RUNNING SERVER IN MAIN THREAD (BLOCKING) ===")
            _run_server(port)
        
        _is_running = True
        logger.info(f"=== SERVER STARTUP COMPLETE, _is_running={_is_running} ===")
        return True
        
    except Exception as e:
        logger.error(f"=== ERROR IN start_server: {e} ===")
        import traceback
        logger.error(traceback.format_exc())
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
            # Verifica che il server HTTP risponda
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
    Riavvia il server HTTP.
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
    """Funzione interna per eseguire il server HTTP"""
    global _server, _is_running
    try:
        logger.info(f"=== _run_server CALLED with port={port} ===")
        logger.info(f"=== ATTEMPTING TO CREATE HTTPServer on 0.0.0.0:{port} ===")
        
        # Abilita reuse dell'indirizzo per evitare errori "Address already in use"
        import socketserver
        class ReusableTCPServer(socketserver.ThreadingMixIn, HTTPServer):
            allow_reuse_address = True
            daemon_threads = True
        
        # Crea il server con l'handler personalizzato e reuse address
        server = ReusableTCPServer(('0.0.0.0', port), BotRequestHandler)
        _server = server
        
        logger.info(f"=== HTTPServer CREATED SUCCESSFULLY ===")
        logger.info(f"Server HTTP in ascolto su 0.0.0.0:{port}")
        logger.info(f"=== ABOUT TO CALL serve_forever() ===")
        
        # Segnala che il server è in esecuzione PRIMA di chiamare serve_forever
        _is_running = True
        
        # Servi per sempre
        server.serve_forever()
        
        logger.info("=== serve_forever() RETURNED (unexpected!) ===")
        
    except Exception as e:
        logger.error(f"=== ERROR in _run_server: {e} ===")
        import traceback
        logger.error(traceback.format_exc())
        _is_running = False


def verify_server_listening(port: int) -> bool:
    """
    Verifica che il server sia effettivamente in ascolto sulla porta.
    Ritorna True se il server risponde, False altrimenti.
    """
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        if result == 0:
            logger.info(f"=== VERIFICATION: Server IS listening on port {port} ===")
            return True
        else:
            logger.error(f"=== VERIFICATION: Server NOT listening on port {port} (connect result: {result}) ===")
            return False
    except Exception as e:
        logger.error(f"=== VERIFICATION ERROR: {e} ===")
        return False


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
        if _server:
            _server.shutdown()
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
        "port": _port,
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

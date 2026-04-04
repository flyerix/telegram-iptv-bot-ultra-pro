"""
Keep-Alive Server per HelperBot
Mantiene il bot online 24/7 con un server HTTP leggero
"""

import threading
import logging
import time
import json
import signal
import sys
import os
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

# Variabili per watchdog e auto-restart
_watchdog_enabled = True
_watchdog_interval = 30  # secondi
_last_successful_health = None
_restart_count = 0
_last_restart_time = None
_bot_responsive = True

# Lock per thread-safety
_state_lock = threading.Lock()

# Statistiche globali
stats = {
    "requests": 0,
    "ping_requests": 0,
    "health_requests": 0,
    "status_requests": 0,
    "start_time": None,
    "webhook_requests": 0,
    "failed_requests": 0,
    "restart_count": 0
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
    
    def _verify_internal_auth(self) -> bool:
        """Verifica l'autenticazione interna per endpoint protetti"""
        auth_header = self.headers.get('X-Internal-Auth')
        expected = os.environ.get('INTERNAL_AUTH_KEY', 'keepalive_internal_key_2024')
        return auth_header == expected
    
    def do_GET(self):
        """Gestisce le richieste GET"""
        global stats, _bot_responsive
        
        try:
            if self.path == '/':
                stats["requests"] += 1
                logger.info(f"Richiesta homepage da {self.client_address}")
                
                self._send_json_response({
                    "service": "HelperBot Keep-Alive Server",
                    "version": "1.1.0",
                    "status": "online",
                    "uptime": _get_uptime(),
                    "bot_responsive": _bot_responsive,
                    "endpoints": {
                        "/": "Homepage",
                        "/ping": "Ping semplice",
                        "/health": "Stato completo del servizio",
                        "/status": "Status del bot",
                        "/restart": "Riavvia il server (POST)"
                    }
                })
            
            elif self.path == '/ping':
                stats["requests"] += 1
                stats["ping_requests"] += 1
                
                self._send_json_response({
                    "status": "pong",
                    "timestamp": datetime.utcnow().isoformat(),
                    "bot_responsive": _bot_responsive
                })
            
            elif self.path == '/health':
                stats["requests"] += 1
                stats["health_requests"] += 1
                
                health_status = _perform_deep_health_check()
                
                self._send_json_response({
                    "status": "healthy" if health_status["healthy"] else "degraded",
                    "service": "helperbot-keepalive",
                    "uptime": _get_uptime(),
                    "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
                    "bot_responsive": _bot_responsive,
                    "requests": {
                        "total": stats["requests"],
                        "ping": stats["ping_requests"],
                        "health": stats["health_requests"],
                        "status": stats["status_requests"],
                        "webhook": stats["webhook_requests"],
                        "failed": stats["failed_requests"]
                    },
                    "server": {
                        "running": _is_running,
                        "port": _port,
                        "thread_alive": _server_thread.is_alive() if _server_thread else False
                    },
                    "watchdog": {
                        "enabled": _watchdog_enabled,
                        "interval": _watchdog_interval,
                        "last_successful": _last_successful_health
                    },
                    "restart": {
                        "count": _restart_count,
                        "last_time": _last_restart_time
                    },
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            elif self.path == '/status':
                stats["requests"] += 1
                stats["status_requests"] += 1
                
                bot_status = _get_bot_status()
                
                self._send_json_response({
                    "bot": {
                        "status": "online" if _bot_responsive else "unresponsive",
                        "uptime": _get_uptime(),
                        "responsive": _bot_responsive
                    },
                    "server": {
                        "running": _is_running,
                        "port": _port,
                        "thread_alive": _server_thread.is_alive() if _server_thread else False
                    },
                    "statistics": {
                        "total_requests": stats["requests"],
                        "ping_requests": stats["ping_requests"],
                        "health_requests": stats["health_requests"],
                        "status_requests": stats["status_requests"],
                        "webhook_requests": stats["webhook_requests"],
                        "failed_requests": stats["failed_requests"]
                    },
                    "watchdog": {
                        "enabled": _watchdog_enabled,
                        "restart_count": _restart_count
                    },
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            else:
                self._send_json_response({"error": "Not found"}, 404)
        
        except Exception as e:
            logger.error(f"Errore nella gestione GET: {e}")
            stats["failed_requests"] += 1
            self._send_json_response({"error": str(e)}, 500)
    
    def do_POST(self):
        """Gestisce le richieste POST"""
        global stats, _bot_application, _webhook_secret_token
        
        if self.path == '/restart':
            # Endpoint per riavviare il server
            if not self._verify_internal_auth():
                self._send_json_response({"error": "Unauthorized"}, 401)
                return
            
            try:
                request_body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                body = json.loads(request_body.decode('utf-8')) if request_body else {}
                graceful = body.get('graceful', True)
                
                logger.warning(f"Richiesta restart ricevuta, graceful={graceful}")
                
                self._send_json_response({
                    "status": "restarting",
                    "message": "Server riavviato",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                # Thread per riavviare il server
                restart_port = _port if _port else 8080
                
                def delayed_restart():
                    time.sleep(2)
                    _restart_server(restart_port, graceful=graceful)
                
                threading.Thread(target=delayed_restart, daemon=True).start()
                
            except Exception as e:
                logger.error(f"Errore nel restart: {e}")
                self._send_json_response({"error": str(e)}, 500)
            return
        
        if self.path == '/webhook':
            stats["requests"] += 1
            stats["webhook_requests"] += 1
            
            if _bot_application is None:
                logger.error("Application non configurata per webhook")
                stats["failed_requests"] += 1
                self._send_json_response({"error": "Bot not configured"}, 500)
                return
            
            if _webhook_secret_token:
                secret_header = self.headers.get('X-Telegram-Bot-Api-Secret-Token')
                if secret_header != _webhook_secret_token:
                    logger.warning("Token segreto non valido per webhook")
                    stats["failed_requests"] += 1
                    self._send_json_response({"error": "Unauthorized"}, 401)
                    return
            
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    logger.warning("Nessun dato ricevuto nel webhook")
                    self._send_json_response({"error": "No data"}, 400)
                    return
                
                body = self.rfile.read(content_length)
                update_data = json.loads(body.decode('utf-8'))
                
                logger.debug(f"Update ricevuta: {update_data.get('update_id', 'N/A')}")
                
                from telegram import Update
                update = Update.de_json(update_data, _bot_application.bot)
                
                import asyncio
                from concurrent.futures import ThreadPoolExecutor, TimeoutError
                
                def run_async_process():
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            new_loop.run_until_complete(_bot_application.process_update(update))
                        finally:
                            new_loop.close()
                    except Exception as e:
                        logger.error(f"Errore nell'elaborazione async: {e}")
                        raise
                
                # Thread pool con timeout per evitare blocchi
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future = executor.submit(run_async_process)
                    try:
                        future.result(timeout=25)  # 25s timeout (lasciare margine)
                    except TimeoutError:
                        logger.error("Timeout nell'elaborazione webhook")
                        stats["failed_requests"] += 1
                        # Non mandiamo 500, il webhook sarà ritentato da Telegram
                    except Exception as e:
                        logger.error(f"Errore nell'elaborazione: {e}")
                        stats["failed_requests"] += 1
                
                # Risposta vuota (200 OK)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{}')
                
                # Bot ha risposto, è responsive
                global _bot_responsive
                _bot_responsive = True
                
            except json.JSONDecodeError as e:
                logger.error(f"Errore parsing JSON: {e}")
                stats["failed_requests"] += 1
                self._send_json_response({"error": "Invalid JSON"}, 400)
            
            except Exception as e:
                logger.error(f"Errore nel processing del webhook: {e}")
                stats["failed_requests"] += 1
                self._send_json_response({"error": str(e)}, 500)
        
        else:
            self._send_json_response({"error": "Not found"}, 404)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Server HTTP che gestisce ogni richiesta in un thread separato"""
    daemon_threads = True


def _perform_deep_health_check() -> Dict[str, Any]:
    """
    Esegue un health check approfondito del server e del bot.
    """
    global _last_successful_health, _bot_responsive
    
    result = {
        "healthy": True,
        "checks": {}
    }
    
    # Check 1: Server HTTP in esecuzione
    try:
        response = requests.get(f"http://localhost:{_port}/ping", timeout=3)
        result["checks"]["http_server"] = response.status_code == 200
        if not result["checks"]["http_server"]:
            result["healthy"] = False
    except Exception as e:
        logger.warning(f"HTTP server check failed: {e}")
        result["checks"]["http_server"] = False
        result["healthy"] = False
    
    # Check 2: Thread del server alive
    if _server_thread:
        result["checks"]["server_thread"] = _server_thread.is_alive()
        if not result["checks"]["server_thread"]:
            logger.warning("Server thread not alive")
            result["healthy"] = False
    else:
        result["checks"]["server_thread"] = False
        result["healthy"] = False
    
    # Check 3: Bot application configurato
    result["checks"]["bot_configured"] = _bot_application is not None
    
    # Check 4: Verifica che il bot sia stato chiamato di recente
    if _last_successful_health:
        time_since_last = time.time() - _last_successful_health
        result["checks"]["recent_activity"] = time_since_last < 300  # 5 minuti
        if time_since_last > 300:
            logger.warning(f"Nessuna attività recente: {time_since_last}s")
            # Non necessariamente unhealthy, ma potrebbe indicare problema
    
    if result["healthy"]:
        _last_successful_health = time.time()
    
    return result


def _get_bot_status() -> Dict[str, Any]:
    """
    Ottiene lo stato del bot dalle statistiche globali
    """
    status = {
        "active": True,
        "responsive": _bot_responsive,
        "modules_loaded": []
    }
    
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
    """
    global _bot_application
    _bot_application = application
    logger.info("Application del bot impostata per il webhook")


def set_webhook_secret(secret_token: str):
    """
    Imposta il token segreto per la verifica del webhook
    """
    global _webhook_secret_token
    _webhook_secret_token = secret_token
    logger.info("Token segreto per webhook configurato")


def start_server(port: Optional[int] = None, threaded: bool = False) -> bool:
    """
    Avvia il server keep-alive
    """
    import os
    if port is None:
        port_env = os.environ.get("PORT") or os.environ.get("KEEPALIVE_PORT")
        if port_env is None:
            logger.warning("PORT environment variable not set, using default 8080")
            port = 8080
        else:
            port = int(port_env)
    
    logger.info(f"=== START_SERVER CALLED === port={port}, threaded={threaded}")
    global _server, _server_thread, _is_running, _start_time, _port, _restart_count, _last_restart_time
    
    _port = port
    
    if _is_running:
        logger.warning(f"Server già in esecuzione sulla porta {port}")
        return False
    
    try:
        _start_time = time.time()
        stats["start_time"] = datetime.utcnow().isoformat()
        stats["restart_count"] = _restart_count
        
        if threaded:
            logger.info("=== CREATING SERVER THREAD ===")
            _server_thread = threading.Thread(
                target=_run_server,
                args=(port,),
                daemon=False
            )
            _server_thread.start()
            logger.info(f"=== THREAD STARTED, is_alive={_server_thread.is_alive()} ===")
            
            # Attesa per binding
            logger.info("=== WAITING FOR SERVER BINDING ===")
            max_wait = 10
            waited = 0
            while waited < max_wait:
                time.sleep(1)
                waited += 1
                if verify_server_listening(port):
                    logger.info(f"=== SERVER IS LISTENING after {waited}s ===")
                    break
            
            # Avvia watchdog thread
            watchdog_thread = threading.Thread(
                target=_watchdog_loop,
                args=(port,),
                daemon=True,
                name="WatchdogThread"
            )
            watchdog_thread.start()
            logger.info("=== WATCHDOG THREAD STARTED ===")
            
            # Avvia health check thread
            health_thread = threading.Thread(
                target=_health_check_loop,
                args=(port,),
                daemon=True,
                name="HealthCheckThread"
            )
            health_thread.start()
            logger.info("=== HEALTH CHECK THREAD STARTED ===")
        else:
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


def _watchdog_loop(port: int):
    """
    Watchdog che monitora lo stato del server e del bot.
    Riavvia automaticamente se il server non risponde.
    """
    global _watchdog_enabled, _bot_responsive, _restart_count, _last_restart_time
    
    logger.info(f"Watchdog started, interval={_watchdog_interval}s")
    
    # Attesa iniziale per permettere al server di avviarsi
    time.sleep(20)
    
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    while _is_running and _watchdog_enabled:
        try:
            # Check 1: Il server HTTP risponde?
            try:
                response = requests.get(f"http://localhost:{port}/ping", timeout=5)
                if response.status_code == 200:
                    consecutive_failures = 0
                    _bot_responsive = True
                else:
                    consecutive_failures += 1
                    logger.warning(f"Watchdog: server risponde con status {response.status_code}")
            except requests.exceptions.RequestException as e:
                consecutive_failures += 1
                logger.warning(f"Watchdog: server non risponde: {e}")
            
            # Check 2: Il thread è ancora alive?
            if _server_thread and not _server_thread.is_alive():
                logger.error("Watchdog: server thread non più alive!")
                consecutive_failures = max_consecutive_failures + 1
            
            current_port = _port if _port else 8080
            if consecutive_failures >= max_consecutive_failures:
                logger.error(f"Watchdog: {consecutive_failures} fallimenti consecutivi, riavvio...")
                _restart_server(current_port, graceful=False)
                consecutive_failures = 0
                _restart_count += 1
                _last_restart_time = datetime.utcnow().isoformat()
                
                # Reset flag responsive
                _bot_responsive = False
                
                # Attesa più lunga dopo restart
                time.sleep(30)
            else:
                time.sleep(_watchdog_interval)
                
        except Exception as e:
            logger.error(f"Errore nel watchdog: {e}")
            time.sleep(_watchdog_interval)


def _health_check_loop(port: int):
    """
    Thread che monitora lo stato del server e verifica il bot.
    """
    logger.info("Health check loop started")
    time.sleep(30)  # Attesa iniziale
    
    while _is_running:
        try:
            health = _perform_deep_health_check()
            
            if not health["healthy"]:
                logger.warning(f"Health check fallito: {health}")
                # Il watchdog gestirà il restart
            else:
                logger.debug(f"Health check OK: {health['checks']}")
                
        except Exception as e:
            logger.error(f"Errore health check: {e}")
        
        time.sleep(60)


def _restart_server(port: int = 8080, graceful: bool = True):
    """
    Riavvia il server HTTP.
    """
    global _is_running, _server_thread, _start_time, _restart_count, _last_restart_time
    
    logger.warning(f"Riavvio server (graceful={graceful})...")
    
    if graceful:
        time.sleep(5)
    
    _is_running = False
    
    # Ferma il server esistente
    if _server:
        try:
            _server.shutdown()
        except Exception as e:
            logger.warning(f"Errore shutdown server: {e}")
    
    # Attesa per cleanup
    time.sleep(3)
    
    # Nuovo thread per il server
    _server_thread = threading.Thread(
        target=_run_server,
        args=(port,),
        daemon=True,
        name="ServerThread-Restart"
    )
    _server_thread.start()
    
    # Attesa per binding
    time.sleep(5)
    
    _is_running = True
    _start_time = time.time()
    stats["start_time"] = datetime.utcnow().isoformat()
    _restart_count += 1
    _last_restart_time = datetime.utcnow().isoformat()
    stats["restart_count"] = _restart_count
    
    logger.info(f"Server riavviato (restart #{_restart_count})")


def _run_server(port: int):
    """Funzione interna per eseguire il server HTTP"""
    global _server, _is_running
    try:
        logger.info(f"=== _run_server CALLED with port={port} ===")
        
        import socketserver
        class ReusableTCPServer(socketserver.ThreadingMixIn, HTTPServer):
            allow_reuse_address = True
            daemon_threads = True
            # Timeout per evitare thread bloccati indefinitamente
            timeout = 60
        
        server = ReusableTCPServer(('0.0.0.0', port), BotRequestHandler)
        _server = server
        
        logger.info(f"=== HTTPServer CREATED on 0.0.0.0:{port} ===")
        
        _is_running = True
        
        server.serve_forever()
        
        logger.info("=== serve_forever() RETURNED ===")
        
    except Exception as e:
        logger.error(f"=== ERROR in _run_server: {e} ===")
        import traceback
        logger.error(traceback.format_exc())
        _is_running = False


def verify_server_listening(port: int) -> bool:
    """
    Verifica che il server sia effettivamente in ascolto sulla porta.
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
            logger.error(f"=== VERIFICATION: Server NOT listening on port {port} ===")
            return False
    except Exception as e:
        logger.error(f"=== VERIFICATION ERROR: {e} ===")
        return False


def stop_server() -> bool:
    """
    Ferma il server keep-alive
    """
    global _is_running, _server, _watchdog_enabled
    
    if not _is_running:
        logger.warning("Server non in esecuzione")
        return False
    
    try:
        _watchdog_enabled = False
        
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
    """
    return {
        "running": _is_running,
        "uptime": _get_uptime() if _is_running else "0s",
        "requests": stats["requests"],
        "port": _port,
        "start_time": stats.get("start_time"),
        "restart_count": _restart_count,
        "bot_responsive": _bot_responsive,
        "watchdog_enabled": _watchdog_enabled
    }


def reset_stats():
    """Resetta le statistiche delle richieste"""
    stats["requests"] = 0
    stats["ping_requests"] = 0
    stats["health_requests"] = 0
    stats["status_requests"] = 0
    stats["webhook_requests"] = 0
    stats["failed_requests"] = 0
    logger.info("Statistiche resettate")


def enable_watchdog(enabled: bool = True):
    """Abilita/disabilita il watchdog"""
    global _watchdog_enabled
    _watchdog_enabled = enabled
    logger.info(f"Watchdog {'abilitato' if enabled else 'disabilitato'}")


# Per testing diretto
if __name__ == '__main__':
    print("Avvio Keep-Alive Server...")
    start_server(port=5000, threaded=True)
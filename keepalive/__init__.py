"""
Keep-Alive Module per HelperBot
Esporta le funzionalità del server keep-alive
"""

from keepalive.server import (
    start_server,
    stop_server,
    get_status,
    set_bot_application,
    set_webhook_secret
)

__all__ = [
    'start_server',
    'stop_server',
    'get_status',
    'set_bot_application',
    'set_webhook_secret'
]

__version__ = "1.0.0"
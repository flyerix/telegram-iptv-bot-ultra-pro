"""
Keep-Alive Module per HelperBot
Esporta le funzionalità del server keep-alive
"""

from keepalive.server import (
    start_server,
    stop_server,
    get_status,
    app
)

__all__ = [
    'start_server',
    'stop_server',
    'get_status',
    'app'
]

__version__ = "1.0.0"
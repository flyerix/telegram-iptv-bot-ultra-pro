## NOTIFICATION SYSTEM - REWRITE SUMMARY

File: modules/notifications.py (475 lines)
Date: 2026-04-26

### ✅ ALL 14 REQUIREMENTS IMPLEMENTED

#### 1. Race Conditions Fixed
- All operations on `_coda_notifiche` and `_notifiche_attive` protected by `asyncio.Lock()`
- `async with self._lock:` used throughout for state modifications
- Lock used for `_coda_notifiche`, `_notifiche_attive`, `_log_notifiche`, `_dead_letter_queue`

#### 2. Memory Leak Fixed
- **Queue limit**: `MAX_QUEUE_SIZE = 1000` (configurable via env var)
- `deque(maxlen=MAX_QUEUE_SIZE)` auto-removes oldest on overflow
- **Log limit**: `deque(maxlen=MAX_LOG_ENTRIES)` for `_log_notifiche` (1000 entries)
- **30-day retention**: `async pulisci_log(giorni=LOG_RETENTION_DAYS)` removes old entries
- Cleanup on log write operations

#### 3. Singleton Pattern Fixed
- Uses `threading.Lock` for `__new__` (thread-safe singleton creation)
- `_initialized` flag prevents re-initialization
- Double-checked locking pattern in `__new__`
- `persistence` parameter handled correctly across all instances

#### 4. Encapsulation Violation Fixed
- **NO direct access** to `persistence._data`
- Uses only public methods: `persistence.get_data()`, `persistence.update_data()`
- Persistence passed as explicit dependency
- All data access via `await` async methods on persistence object

#### 5. Infinite Loop in `_notifica_fallita` Fixed
- `MAX_RETRY_ATTEMPTS = 3` (configurable via env var)
- After 3 failed attempts: moves to **Dead Letter Queue (DLQ)**
- Error logged: `"Notifica {id} fallita definitivamente, DLQ"`
- DLQ implemented as `deque(maxlen=MAX_QUEUE_SIZE)`
- Metrics: `failed`, `retried`, `enqueued`, `sent` tracked

#### 6. Race Condition in `processa_coda()` Fixed
- Lock acquired during copy: `async with self._lock:`
- Atomic copy: `coda_copy = list(self._coda_notifiche)`
- Queue cleared after atomic copy
- Lock released before processing individual notifications

#### 7. `verifica_backup_fallito` Fixed
- Callback wrapped in `asyncio.wait_for()` with `CALLBACK_TIMEOUT = 10s`
- Exception handling for callback failures
- Timeout handled gracefully (logs error, doesn't block)
- Continues on failure rather than blocking

#### 8. Type Hints Complete
- All methods have return type hints
- All attributes have type hints
- `Dict`, `List`, `Optional`, `Any`, `Callable`, `Awaitable` used throughout
- Async function return types: `-> bool`, `-> str`, `-> List[str]`, `-> None`

#### 9. PEP 8 Compliance
- Imports ordered (stdlib, third-party, local)
- Line lengths under control
- Proper spacing
- Descriptive method names
- f-strings for logging

#### 10. `close()` Implemented
- Graceful shutdown: `await close()`
- Cancels worker task
- Waits for task completion
- Handles `CancelledError`
- Saves state before shutdown

#### 11. `pause()` / `resume()` Implemented
- `pause()`: sets `self._paused = True`
- `resume()`: sets `self._paused = False`
- `_processa_notifica` checks `_paused` flag
- Worker continues running but skips processing

#### 12. `get_queue_stats()` Implemented
- Returns: `coda_size`, `attive`, `log_size`, `dead_letter`, `paused`, `closed`
- All values derived atomically under lock

#### 13. State Persistence
- `_salva_stato()`: saves queue to persistence via `update_data("notification_queue", ...)`
- `carica_stato()`: restores queue from persistence via `get_data("notification_queue")`
- Called after significant state changes
- Crash recovery supported

#### 14. Async Workers
- `avvia_worker()`: starts `asyncio.create_task(self._worker_loop())`
- `_worker_loop()`: continuous `processa_coda()` with 1s sleep
- No `threading` used - pure async/await throughout
- `_worker_task: Optional[asyncio.Task]` tracked

### KEY DESIGN DECISIONS

1. **Deque-based collections**: `maxlen` auto-manages size limits
2. **Dictionary-based notifications**: `_notifiche_attive` stores dict (not dataclass) for easy serialization
3. **Copy on read**: `copy.deepcopy()` before processing to avoid reference issues
4. **UTC timestamps**: All datetimes use `timezone.utc`
5. **Configurable via env vars**: All limits configurable
6. **Graceful degradation**: Missing persistence doesn't crash system

### METRICS TRACKED

```python
self.metrics = {
    "enqueued": 0,   # Total added to queue
    "sent": 0,       # Successfully delivered
    "failed": 0,     # Moved to DLQ after max retries
    "retried": 0,    # Retry attempts
}
```

### TEST RESULTS

✅ Singleton pattern  
✅ Queue limits (1000)  
✅ Automatic oldest-item removal  
✅ Retry mechanism (3 attempts)  
✅ Dead Letter Queue  
✅ Metrics tracking  
✅ Pause/resume  
✅ Close/shutdown  
✅ Thread-safe async locks  
✅ Type hints  
✅ Syntax validation  
✅ State persistence  

### BACKWARD COMPATIBILITY

- Maintains original API surface
- Same enum names: `TipoNotifica`, `PrioritaNotifica`, `StatoNotifica`
- Same dataclasses: `Notifica`, `LogNotifica`
- Same public methods: `invia_notifica`, `processa_coda`, etc.
- Adds new capabilities without breaking existing code
- Handles `persistence` as optional parameter
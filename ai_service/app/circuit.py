"""Circuit breaker por proveedor (Capítulo 11).

Estados: cerrado (normal) -> abierto (tras N fallos en la ventana; se rechaza sin
llamar) -> semiabierto (pasado el tiempo de recuperación se deja pasar alguna
petición de prueba) -> cerrado (tras 2 éxitos seguidos).

Es por proveedor y no por modelo: si Anthropic está saturado, probar con otro
modelo de Anthropic suele fallar igual. El estado vive en memoria de cada proceso;
con dos workers de uvicorn cada uno aprende por su cuenta, lo que solo añade un
par de fallos de más antes de abrir (ADR-011).
"""
import threading
import time
from collections import deque
from dataclasses import dataclass, field

SUCCESS_THRESHOLD = 2


@dataclass
class _State:
    failures: deque = field(default_factory=deque)
    open_until: float = 0.0
    half_open_successes: int = 0
    state: str = "closed"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, window_seconds: float = 30,
                 recovery_seconds: float = 120, clock=time.monotonic):
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def _get(self, provider: str) -> _State:
        return self._states.setdefault(provider, _State())

    def state(self, provider: str) -> str:
        with self._lock:
            st = self._get(provider)
            if st.state == "open" and self._clock() >= st.open_until:
                st.state = "half_open"
                st.half_open_successes = 0
            return st.state

    def is_available(self, provider: str) -> bool:
        return self.state(provider) != "open"

    def record_success(self, provider: str) -> None:
        with self._lock:
            st = self._get(provider)
            if st.state == "half_open":
                st.half_open_successes += 1
                if st.half_open_successes >= SUCCESS_THRESHOLD:
                    st.state = "closed"
                    st.failures.clear()
            else:
                st.failures.clear()

    def record_failure(self, provider: str) -> None:
        now = self._clock()
        with self._lock:
            st = self._get(provider)
            if st.state == "half_open":
                # La petición de prueba ha fallado: vuelve a abrirse
                st.state = "open"
                st.open_until = now + self.recovery_seconds
                return
            st.failures.append(now)
            while st.failures and now - st.failures[0] > self.window_seconds:
                st.failures.popleft()
            if len(st.failures) >= self.failure_threshold:
                st.state = "open"
                st.open_until = now + self.recovery_seconds
                st.failures.clear()

    def snapshot(self) -> dict[str, str]:
        return {provider: self.state(provider) for provider in list(self._states)}

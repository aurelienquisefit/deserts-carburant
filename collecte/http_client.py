"""Session HTTP « polie » partagée par tous les modules de collecte.

Règles appliquées (cohérentes avec les politiques d'usage des API utilisées) :

- un ``User-Agent`` explicite qui identifie le projet ;
- des délais d'attente (timeouts) systématiques ;
- des relances limitées avec attente exponentielle, uniquement sur les erreurs
  transitoires (429, 5xx), en respectant l'en-tête ``Retry-After`` ;
- une limitation de débit côté client (``RateLimiter``) pour les appels en série.

Le module s'appelle ``http_client`` (et non ``http``) pour ne pas masquer le
module ``http`` de la bibliothèque standard.
"""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT

DEFAULT_TIMEOUT = (10, 300)  # (connexion, lecture) en secondes


def make_session(user_agent: str = USER_AGENT, total_retries: int = 3,
                 backoff_factor: float = 2.0) -> requests.Session:
    """Construit une ``requests.Session`` configurée pour des relances raisonnables."""
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent})
    return session


class RateLimiter:
    """Garantit un intervalle minimal entre deux appels successifs.

    >>> rl = RateLimiter(min_interval_s=0.0)
    >>> rl.wait()  # premier appel : aucune attente
    0.0
    """

    def __init__(self, min_interval_s: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval_s = float(min_interval_s)
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> float:
        """Attend si nécessaire ; renvoie la durée d'attente effectuée (s)."""
        now = self._clock()
        waited = 0.0
        if self._last is not None:
            remaining = self.min_interval_s - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining
        self._last = self._clock()
        return waited

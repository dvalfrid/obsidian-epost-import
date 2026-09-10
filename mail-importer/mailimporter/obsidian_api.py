from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import quote

import requests
import urllib3

from .retry import with_retry

log = logging.getLogger("obsidian")

_RETRYABLE_NET = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


class ObsidianError(RuntimeError):
    pass


class _Transient(Exception):
    """5xx från API:t — värt att försöka igen."""


class ObsidianClient:
    """Tunn klient mot Local REST API-pluginet.

    Skapar ENDAST nya filer: varje skrivning föregås av en existenskontroll
    och befintliga filer rörs aldrig.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        verify_tls: bool,
        *,
        max_retries: int = 3,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._verify = verify_tls
        self._max_retries = max_retries
        self._should_stop = should_stop
        self._s = requests.Session()
        self._s.headers["Authorization"] = f"Bearer {api_key}"
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- internt ----------------------------------------------------
    def _vault_url(self, vault_path: str) -> str:
        safe = "/".join(quote(seg) for seg in vault_path.split("/"))
        return f"{self._base}/vault/{safe}"

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        def _do() -> requests.Response:
            resp = self._s.request(method, url, verify=self._verify, **kw)
            if resp.status_code >= 500:
                raise _Transient(f"{method} {url} -> {resp.status_code}")
            return resp

        return with_retry(
            _do,
            what=f"{method} {url}",
            retryable=_RETRYABLE_NET + (_Transient,),
            max_attempts=self._max_retries,
            should_stop=self._should_stop,
        )

    # ---- publikt --------------------------------------------------
    def ping(self) -> bool:
        try:
            resp = self._s.get(
                self._base + "/", timeout=10, verify=self._verify
            )
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def exists(self, vault_path: str) -> bool:
        resp = self._request("GET", self._vault_url(vault_path), timeout=30)
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        raise ObsidianError(
            f"Oväntad status {resp.status_code} vid kontroll av "
            f"{vault_path!r}: {resp.text[:200]}"
        )

    def create_file(
        self, vault_path: str, content: bytes, content_type: str
    ) -> bool:
        """Skapar filen om den saknas. Returnerar True om den skapades,
        False om den redan fanns. Skriver ALDRIG över en befintlig fil."""
        if self.exists(vault_path):
            log.info("Hoppar över — filen finns redan: %s", vault_path)
            return False

        resp = self._request(
            "PUT",
            self._vault_url(vault_path),
            data=content,
            headers={"Content-Type": content_type},
            timeout=60,
        )
        if resp.status_code not in (200, 201, 204):
            raise ObsidianError(
                f"PUT {vault_path!r} gav status {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        return True

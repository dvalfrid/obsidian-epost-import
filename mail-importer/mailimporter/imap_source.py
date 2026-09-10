from __future__ import annotations

import logging
import socket
import ssl

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from .config import Config

log = logging.getLogger("imap")

# Undantag som ska trigga full återanslutning (med backoff).
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    socket.error,
    ssl.SSLError,
    IMAPClientError,
    EOFError,
)


class ImapSource:
    """IMAP-läsning mot Proton Bridge.

    - Mappen väljs alltid read-only (EXAMINE) och meddelanden hämtas med
      BODY.PEEK[] så att \\Seen-flaggan på servern aldrig rörs.
    - Alla meddelanden hämtas oavsett läs-status.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._client: IMAPClient | None = None
        self._idling = False

    # ---- anslutning ------------------------------------------------
    def connect(self) -> None:
        self.logout()
        ctx = ssl.create_default_context()
        if not self._cfg.imap_verify_cert:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        client = IMAPClient(
            self._cfg.imap_host,
            port=self._cfg.imap_port,
            ssl=self._cfg.imap_ssl,
            ssl_context=ctx if self._cfg.imap_ssl else None,
            timeout=30,
        )
        if self._cfg.imap_starttls and not self._cfg.imap_ssl:
            client.starttls(ssl_context=ctx)
        client.login(self._cfg.imap_user, self._cfg.imap_pass)
        self._client = client
        log.info(
            "Ansluten till IMAP %s:%s som %s",
            self._cfg.imap_host, self._cfg.imap_port, self._cfg.imap_user,
        )

    def logout(self) -> None:
        if self._client is None:
            return
        try:
            if self._idling:
                self._client.idle_done()
            self._client.logout()
        except Exception:  # noqa: BLE001 - städning ska aldrig fälla
            pass
        finally:
            self._client = None
            self._idling = False

    # ---- kommandon ------------------------------------------------
    def _require(self) -> IMAPClient:
        if self._client is None:
            raise IMAPClientError("Inte ansluten till IMAP")
        return self._client

    def list_folders(self) -> list[str]:
        return [entry[2] for entry in self._require().list_folders()]

    def select(self) -> int:
        """Väljer den bevakade mappen read-only och returnerar UIDVALIDITY."""
        resp = self._require().select_folder(self._cfg.mailbox, readonly=True)
        return int(resp[b"UIDVALIDITY"])

    def all_uids(self) -> list[int]:
        """Alla UID:n i mappen, oavsett läs-status."""
        return sorted(self._require().search(["ALL"]))

    def fetch_raw(self, uid: int) -> bytes | None:
        resp = self._require().fetch([uid], ["BODY.PEEK[]"])
        data = resp.get(uid)
        if not data:
            return None
        return data.get(b"BODY[]") or data.get(b"RFC822")

    def idle_wait(self, timeout: int) -> bool:
        """Blockerar i IMAP IDLE upp till ``timeout`` sekunder. Returnerar
        True om servern signalerade aktivitet i mappen."""
        client = self._require()
        client.idle()
        self._idling = True
        try:
            responses = client.idle_check(timeout=timeout)
        finally:
            try:
                client.idle_done()
            finally:
                self._idling = False
        return bool(responses)

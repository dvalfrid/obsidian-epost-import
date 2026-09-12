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
        self._label_folders_cache: list[str] | None = None

    # ---- anslutning ------------------------------------------------
    def connect(self) -> None:
        self.logout()
        self._label_folders_cache = None
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

    def _label_folders(self) -> list[str]:
        """Proton-labels dyker upp i Bridge som egna mappar under
        'Labels/'. Cachas per anslutning — listas bara en gång."""
        if self._label_folders_cache is None:
            self._label_folders_cache = [
                f for f in self.list_folders() if f.startswith("Labels/")
            ]
        return self._label_folders_cache

    def discover_labels(self, message_id: str) -> list[str]:
        """Ett meddelande kan ha flera Proton-labels samtidigt, men IMAP
        visar bara vilken mapp vi råkar ha vald. Sök igenom alla
        Labels/*-mappar efter samma Message-ID för att hitta ALLA labels
        meddelandet har. Returnerar kort labelnamn (utan 'Labels/'-
        prefix). VÄXLAR vilken mapp som är vald på anslutningen — anroparen
        måste själv välja tillbaka den bevakade mappen efteråt.

        En trasig anslutning (NETWORK_ERRORS) bubblar vidare direkt så att
        huvudloopen återansluter. Övriga fel för en enskild mapp loggas
        och hoppas över, sökningen fortsätter med resten."""
        client = self._require()
        found: list[str] = []
        needle = f"<{message_id}>"
        for folder in self._label_folders():
            try:
                client.select_folder(folder, readonly=True)
                uids = client.search(["HEADER", "Message-ID", needle])
            except NETWORK_ERRORS:
                raise
            except Exception:  # noqa: BLE001 - en trasig mapp ska inte fälla resten
                log.warning("kunde inte söka Message-ID i %r", folder, exc_info=True)
                continue
            if uids:
                found.append(folder.split("/", 1)[1])
        return found

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

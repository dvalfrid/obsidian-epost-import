from __future__ import annotations

import logging
import socket
import ssl

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from .config import Config

log = logging.getLogger("imap")

# Exceptions that should trigger a full reconnect (with backoff).
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    socket.error,
    ssl.SSLError,
    IMAPClientError,
    EOFError,
)


class ImapSource:
    """IMAP reading against Proton Bridge.

    - The folder is always selected read-only (EXAMINE) and messages are
      fetched with BODY.PEEK[] so the \\Seen flag on the server is never
      touched.
    - All messages are fetched regardless of read status.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._client: IMAPClient | None = None
        self._idling = False
        self._label_folders_cache: list[str] | None = None

    # ---- connection --------------------------------------------------
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
            "Connected to IMAP %s:%s as %s",
            self._cfg.imap_host, self._cfg.imap_port, self._cfg.imap_user,
        )

    def logout(self) -> None:
        if self._client is None:
            return
        try:
            if self._idling:
                self._client.idle_done()
            self._client.logout()
        except Exception:  # noqa: BLE001 - cleanup should never fail
            pass
        finally:
            self._client = None
            self._idling = False

    # ---- commands ------------------------------------------------
    def _require(self) -> IMAPClient:
        if self._client is None:
            raise IMAPClientError("Not connected to IMAP")
        return self._client

    def list_folders(self) -> list[str]:
        return [entry[2] for entry in self._require().list_folders()]

    def select(self) -> int:
        """Selects the watched folder read-only and returns UIDVALIDITY."""
        resp = self._require().select_folder(self._cfg.mailbox, readonly=True)
        return int(resp[b"UIDVALIDITY"])

    def all_uids(self) -> list[int]:
        """All UIDs in the folder, regardless of read status."""
        return sorted(self._require().search(["ALL"]))

    def fetch_raw(self, uid: int) -> bytes | None:
        resp = self._require().fetch([uid], ["BODY.PEEK[]"])
        data = resp.get(uid)
        if not data:
            return None
        return data.get(b"BODY[]") or data.get(b"RFC822")

    def _label_folders(self) -> list[str]:
        """Proton labels show up in Bridge as their own folders under
        'Labels/'. Cached per connection — only listed once."""
        if self._label_folders_cache is None:
            self._label_folders_cache = [
                f for f in self.list_folders() if f.startswith("Labels/")
            ]
        return self._label_folders_cache

    def discover_labels(self, message_id: str) -> list[str]:
        """A message can have several Proton labels at once, but IMAP only
        shows which folder we happen to have selected. Search through all
        Labels/* folders for the same Message-ID to find ALL labels the
        message has. Returns short label names (without the 'Labels/'
        prefix). SWITCHES which folder is selected on the connection — the
        caller must reselect the watched folder afterward.

        A broken connection (NETWORK_ERRORS) bubbles straight up so the main
        loop reconnects. Other errors for a single folder are logged and
        skipped, and the search continues with the rest."""
        client = self._require()
        found: list[str] = []
        needle = f"<{message_id}>"
        for folder in self._label_folders():
            try:
                client.select_folder(folder, readonly=True)
                uids = client.search(["HEADER", "Message-ID", needle])
            except NETWORK_ERRORS:
                raise
            except Exception:  # noqa: BLE001 - one broken folder shouldn't fail the rest
                log.warning("could not search for Message-ID in %r", folder, exc_info=True)
                continue
            if uids:
                found.append(folder.split("/", 1)[1])
        return found

    def idle_wait(self, timeout: int) -> bool:
        """Blocks in IMAP IDLE for up to ``timeout`` seconds. Returns True if
        the server signaled activity in the folder."""
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

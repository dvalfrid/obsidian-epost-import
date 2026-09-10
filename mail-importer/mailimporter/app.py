from __future__ import annotations

import logging
import signal
import time

from .config import Config
from .imap_source import NETWORK_ERRORS, ImapSource
from .logging_setup import setup_logging
from .obsidian_api import ObsidianClient
from .processor import Processor
from .retry import RetryError, with_retry
from .state import State

log = logging.getLogger("app")


class Runner:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._stop = False
        self._state = State(cfg.state_db_path)
        self._obs = ObsidianClient(
            cfg.obsidian_api_url,
            cfg.obsidian_api_key,
            cfg.obsidian_verify_tls,
            max_retries=cfg.api_max_retries,
            should_stop=lambda: self._stop,
        )
        self._proc = Processor(self._obs, self._state, cfg)
        self._imap = ImapSource(cfg)

    # ---- livscykel ----------------------------------------------
    def _request_stop(self, signum, _frame) -> None:
        log.info(
            "Signal %s mottagen — avslutar när pågående import är klar",
            signal.Signals(signum).name,
        )
        self._stop = True

    def _sleep(self, seconds: float) -> None:
        """Avbrytbar sömn."""
        deadline = time.monotonic() + seconds
        while not self._stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    def _heartbeat(self) -> None:
        try:
            with open(self._cfg.heartbeat_path, "w", encoding="ascii") as fh:
                fh.write(str(int(time.time())))
        except OSError as exc:
            log.debug("Kunde inte skriva heartbeat: %s", exc)

    def _wait_for_obsidian(self) -> None:
        delay = 5
        while not self._stop:
            if self._obs.ping():
                log.info("Local REST API svarar (%s)", self._cfg.obsidian_api_url)
                return
            log.warning(
                "Väntar på Local REST API (%s) — nytt försök om %ss",
                self._cfg.obsidian_api_url, delay,
            )
            self._sleep(delay)
            delay = min(delay * 2, 60)

    # ---- arbete ------------------------------------------------
    def _run_once(self) -> None:
        uidvalidity = self._imap.select()
        stored = self._state.get_uidvalidity(self._cfg.mailbox)
        if stored is not None and stored != uidvalidity:
            log.warning(
                "UIDVALIDITY för %r ändrades (%s -> %s) — "
                "faller tillbaka på deduplicering via Message-ID",
                self._cfg.mailbox, stored, uidvalidity,
            )
        self._state.set_uidvalidity(self._cfg.mailbox, uidvalidity)

        uids = self._imap.all_uids()
        pending = [u for u in uids if not self._state.is_imported(uidvalidity, u)]
        if pending:
            log.info(
                "%d nya meddelanden i %r (%d totalt i mappen)",
                len(pending), self._cfg.mailbox, len(uids),
            )

        for uid in pending:
            if self._stop:
                log.info("Avbryter köbearbetning före UID %s (nedstängning)", uid)
                break
            try:
                try:
                    raw = with_retry(
                        lambda: self._imap.fetch_raw(uid),
                        what=f"IMAP-hämtning UID {uid}",
                        retryable=NETWORK_ERRORS,
                        max_attempts=self._cfg.api_max_retries,
                        should_stop=lambda: self._stop,
                    )
                except RetryError as exc:
                    # Slut på försök -> bubbla originalfelet så att
                    # huvudloopen återansluter med backoff.
                    raise (exc.__cause__ or exc)
                if not raw:
                    log.warning("UID %s: tomt svar från servern — försöker igen nästa körning", uid)
                    continue
                self._proc.process(uidvalidity, uid, raw)
            except NETWORK_ERRORS:
                raise  # bubbla upp -> återanslutning
            except Exception:  # noqa: BLE001
                log.exception(
                    "UID %s: import misslyckades — UID:t markeras INTE, "
                    "försök igen nästa körning", uid,
                )
            finally:
                self._heartbeat()

    # ---- huvudloop --------------------------------------------
    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)

        self._heartbeat()
        self._wait_for_obsidian()

        backoff = 5
        while not self._stop:
            try:
                self._imap.connect()
                backoff = 5
                self._run_once()  # backlog direkt vid anslutning
                last_poll = time.monotonic()

                while not self._stop:
                    self._heartbeat()
                    activity = self._imap.idle_wait(
                        max(5, min(self._cfg.idle_timeout, 300))
                    )
                    if self._stop:
                        break
                    poll_due = (time.monotonic() - last_poll) >= self._cfg.poll_interval
                    if activity or poll_due:
                        self._run_once()
                        last_poll = time.monotonic()

            except NETWORK_ERRORS as exc:
                if self._stop:
                    break
                log.warning("Nätverksfel (%s) — återansluter om %ss", exc, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, self._cfg.reconnect_backoff_max)
            except Exception:  # noqa: BLE001
                if self._stop:
                    break
                log.exception("Oväntat fel i huvudloopen — återansluter om %ss", backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, self._cfg.reconnect_backoff_max)
            finally:
                self._imap.logout()

        self._state.close()
        log.info("Avslutad rent")


def run() -> None:
    cfg = Config.from_env()
    setup_logging(cfg.log_level)
    if not cfg.obsidian_api_key:
        raise SystemExit("OBSIDIAN_API_KEY måste vara satt (hämtas via VNC, se README)")
    log.info(
        "obsidian-epost-import %s startar — mapp=%r, poll=%ss, idle=%ss",
        _version(), cfg.mailbox, cfg.poll_interval, cfg.idle_timeout,
    )
    Runner(cfg).run()


def _version() -> str:
    from . import __version__

    return __version__

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS imported (
    uidvalidity INTEGER NOT NULL,
    uid         INTEGER NOT NULL,
    message_id  TEXT,
    note_path   TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (uidvalidity, uid)
);
CREATE INDEX IF NOT EXISTS idx_imported_message_id ON imported (message_id);

CREATE TABLE IF NOT EXISTS mailbox_meta (
    mailbox     TEXT PRIMARY KEY,
    uidvalidity INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    """Krascha-säker tracking i en egen SQLite-fil (inte i valvet).

    (uidvalidity, uid) är primärnyckeln. message_id indexeras separat så att
    deduplicering kan falla tillbaka på Message-ID när UIDVALIDITY ändras.
    """

    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- läsning -------------------------------------------------------
    def is_imported(self, uidvalidity: int, uid: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM imported WHERE uidvalidity=? AND uid=?",
                (uidvalidity, uid),
            ).fetchone()
        return row is not None

    def note_for_message_id(self, message_id: str) -> str | None:
        if not message_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT note_path FROM imported WHERE message_id=? "
                "ORDER BY imported_at LIMIT 1",
                (message_id,),
            ).fetchone()
        return row[0] if row else None

    def get_uidvalidity(self, mailbox: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT uidvalidity FROM mailbox_meta WHERE mailbox=?",
                (mailbox,),
            ).fetchone()
        return int(row[0]) if row else None

    # ---- skrivning ---------------------------------------------------
    def mark_imported(
        self, uidvalidity: int, uid: int, message_id: str, note_path: str
    ) -> None:
        """Atomisk commit — detta ÄR 'klart'-markeringen. Vid krasch innan
        detta anrop importeras UID:t om nästa körning (anteckningen skapas
        bara om den saknas, så ingen dubblett)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO imported "
                "(uidvalidity, uid, message_id, note_path, imported_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uidvalidity, uid, message_id or None, note_path, _now()),
            )

    def set_uidvalidity(self, mailbox: str, uidvalidity: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO mailbox_meta (mailbox, uidvalidity, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(mailbox) DO UPDATE SET "
                "uidvalidity=excluded.uidvalidity, updated_at=excluded.updated_at",
                (mailbox, uidvalidity, _now()),
            )

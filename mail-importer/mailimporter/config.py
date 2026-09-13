from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"Environment variable {name} must be an integer (got {raw!r})") from exc


def _str(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and (val is None or val.strip() == ""):
        raise SystemExit(f"Environment variable {name} must be set")
    return (val or "").strip()


@dataclass(frozen=True)
class Config:
    # IMAP / Proton Bridge
    imap_host: str
    imap_port: int
    imap_user: str
    imap_pass: str
    imap_ssl: bool
    imap_starttls: bool
    imap_verify_cert: bool
    mailbox: str

    # Obsidian Local REST API
    obsidian_api_url: str
    obsidian_api_key: str
    obsidian_verify_tls: bool

    # Vault layout
    note_folder: str
    attachment_folder: str
    note_labels: list[str]

    # Runtime
    poll_interval: int
    idle_timeout: int
    reconnect_backoff_max: int
    api_max_retries: int

    # Local
    state_db_path: str
    heartbeat_path: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        labels = [s.strip() for s in _str("NOTE_LABELS", "Obsidian").split(",") if s.strip()]
        return cls(
            imap_host=_str("IMAP_HOST", required=True),
            imap_port=_int("IMAP_PORT", 1143),
            imap_user=_str("IMAP_USER", required=True),
            imap_pass=_str("IMAP_PASS", required=True),
            imap_ssl=_bool("IMAP_SSL", False),
            imap_starttls=_bool("IMAP_STARTTLS", True),
            imap_verify_cert=_bool("IMAP_VERIFY_CERT", False),
            mailbox=_str("MAILBOX", "Obsidian"),
            obsidian_api_url=_str("OBSIDIAN_API_URL", "https://obsidian:27124").rstrip("/"),
            obsidian_api_key=_str("OBSIDIAN_API_KEY"),
            obsidian_verify_tls=_bool("OBSIDIAN_API_VERIFY_TLS", False),
            note_folder=_str("NOTE_FOLDER", "Email").strip("/"),
            attachment_folder=_str("ATTACHMENT_FOLDER", "Email/attachments").strip("/"),
            note_labels=labels or ["Obsidian"],
            poll_interval=_int("POLL_INTERVAL_SECONDS", 300),
            idle_timeout=_int("IDLE_TIMEOUT_SECONDS", 60),
            reconnect_backoff_max=_int("RECONNECT_BACKOFF_MAX_SECONDS", 300),
            api_max_retries=_int("API_MAX_RETRIES", 3),
            state_db_path=_str("STATE_DB_PATH", "/data/state.sqlite3"),
            heartbeat_path=_str("HEARTBEAT_PATH", "/data/heartbeat"),
            log_level=_str("LOG_LEVEL", "INFO").upper(),
        )

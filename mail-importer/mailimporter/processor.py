from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from .config import Config
from .emailmsg import parse_email
from .imap_source import ImapSource
from .note_builder import attachment_filename, build_note, note_filename
from .obsidian_api import ObsidianClient
from .remote_fetch import extract_remote_resources, fetch_remote, remote_filename
from .state import State

log = logging.getLogger("processor")

_MARKDOWN_CT = "text/markdown"
_BINARY_CT = "application/octet-stream"


@dataclass
class _AttachmentPlan:
    original: str
    vault_path: str
    content_id: str | None
    content: bytes
    content_type: str
    source_url: str | None = None


class Processor:
    def __init__(
        self, obs: ObsidianClient, state: State, cfg: Config, imap: ImapSource
    ) -> None:
        self._obs = obs
        self._state = state
        self._cfg = cfg
        self._imap = imap
        self._http = requests.Session()

    def process(self, uidvalidity: int, uid: int, raw: bytes) -> None:
        """Processes ONE message. Re-raises on failure so the caller can log
        it and leave the UID unmarked as imported (retry next run). Only
        marks it "done" in SQLite once both the attachments and the note are
        in place."""
        parsed = parse_email(raw)

        note_name = note_filename(parsed.date, parsed.subject, parsed.message_id)
        note_path = f"{self._cfg.note_folder}/{note_name}"

        # Deduplication via Message-ID (covers a changed UIDVALIDITY).
        existing = self._state.note_for_message_id(parsed.message_id)
        if existing is not None:
            log.info(
                "UID %s: Message-ID already imported (%s) — marking UID as done",
                uid, existing,
            )
            self._state.mark_imported(uidvalidity, uid, parsed.message_id, existing)
            return

        # An email can have several Proton labels at once (Obsidian + Ida,
        # say) — IMAP only shows which folder we happen to have selected, so
        # we actively search through all Labels/* folders for the same
        # Message-ID. discover_labels() switches which folder is selected ->
        # reselect the watched folder right afterward before continuing.
        proton_labels = self._imap.discover_labels(parsed.message_id)
        self._imap.select()
        labels = list(proton_labels)
        for extra in self._cfg.note_labels:
            if extra not in labels:
                labels.append(extra)

        plans: list[_AttachmentPlan] = []
        for att in parsed.attachments:
            fname = attachment_filename(parsed.message_id, att.filename)
            plans.append(
                _AttachmentPlan(
                    original=att.filename,
                    vault_path=f"{self._cfg.attachment_folder}/{fname}",
                    content_id=att.content_id,
                    content=att.content,
                    content_type=att.content_type,
                )
            )

        # Best-effort: download remote http(s) images/documents referenced
        # in the body so they survive if the sender's server later goes
        # away. Failures (blocked host, timeout, too large, bad status) are
        # skipped silently — the original remote link is left in place.
        if self._cfg.remote_fetch_enabled:
            for resource in extract_remote_resources(parsed.body_markdown):
                fetched = fetch_remote(resource.url, self._cfg, self._http)
                if fetched is None:
                    continue
                content, content_type = fetched
                fname = remote_filename(resource.url, content_type)
                plans.append(
                    _AttachmentPlan(
                        original=resource.url,
                        vault_path=f"{self._cfg.attachment_folder}/{fname}",
                        content_id=None,
                        content=content,
                        content_type=content_type,
                        source_url=resource.url,
                    )
                )

        # 1. Attachments FIRST — if any fails, an exception is raised and the
        #    note is never created (the UID is not marked as done).
        for plan in plans:
            created = self._obs.create_file(plan.vault_path, plan.content, _BINARY_CT)
            log.info(
                "UID %s: attachment %r -> %s (%s)",
                uid, plan.original, plan.vault_path,
                "created" if created else "already existed",
            )

        # 2. The note that links the attachments.
        content = build_note(parsed, plans, labels).encode("utf-8")
        created = self._obs.create_file(note_path, content, _MARKDOWN_CT)
        log.info(
            "UID %s: note %s -> %s",
            uid, "created" if created else "already existed", note_path,
        )

        # 3. Done — atomic commit in the same SQLite transaction.
        self._state.mark_imported(uidvalidity, uid, parsed.message_id, note_path)

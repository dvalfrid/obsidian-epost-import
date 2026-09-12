from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .emailmsg import parse_email
from .imap_source import ImapSource
from .note_builder import attachment_filename, build_note, note_filename
from .obsidian_api import ObsidianClient
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


class Processor:
    def __init__(
        self, obs: ObsidianClient, state: State, cfg: Config, imap: ImapSource
    ) -> None:
        self._obs = obs
        self._state = state
        self._cfg = cfg
        self._imap = imap

    def process(self, uidvalidity: int, uid: int, raw: bytes) -> None:
        """Bearbetar ETT meddelande. Kastar vidare vid fel så att anroparen
        kan logga och låta bli att markera UID:t som importerat (försök igen
        nästa körning). Markerar 'klart' i SQLite först när både bilagor och
        anteckning ligger på plats."""
        parsed = parse_email(raw)

        note_name = note_filename(parsed.date, parsed.subject, parsed.message_id)
        note_path = f"{self._cfg.note_folder}/{note_name}"

        # Deduplicering via Message-ID (täcker ändrad UIDVALIDITY).
        existing = self._state.note_for_message_id(parsed.message_id)
        if existing is not None:
            log.info(
                "UID %s: Message-ID redan importerad (%s) — markerar UID som klar",
                uid, existing,
            )
            self._state.mark_imported(uidvalidity, uid, parsed.message_id, existing)
            return

        # Ett mejl kan ha flera Proton-labels samtidigt (Obsidian + Ida
        # t.ex.) — IMAP visar bara vilken mapp vi råkar ha vald, så vi
        # söker aktivt igenom alla Labels/*-mappar efter samma Message-ID.
        # discover_labels() växlar vilken mapp som är vald -> väl tillbaka
        # den bevakade mappen direkt efteråt innan vi fortsätter.
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

        # 1. Bilagor FÖRST — om någon misslyckas kastas undantag och
        #    anteckningen skapas aldrig (UID:t markeras inte som klart).
        for plan in plans:
            created = self._obs.create_file(plan.vault_path, plan.content, _BINARY_CT)
            log.info(
                "UID %s: bilaga %r -> %s (%s)",
                uid, plan.original, plan.vault_path,
                "skapad" if created else "fanns redan",
            )

        # 2. Anteckningen som länkar bilagorna.
        content = build_note(parsed, plans, labels).encode("utf-8")
        created = self._obs.create_file(note_path, content, _MARKDOWN_CT)
        log.info(
            "UID %s: anteckning %s -> %s",
            uid, "skapad" if created else "fanns redan", note_path,
        )

        # 3. Klart — atomisk commit i samma SQLite-transaktion.
        self._state.mark_imported(uidvalidity, uid, parsed.message_id, note_path)

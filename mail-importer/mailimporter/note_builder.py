from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Iterable, Protocol

import yaml
from slugify import slugify

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}


class _AttachmentLike(Protocol):
    original: str
    vault_path: str
    content_id: str | None


def short_hash(message_id: str, length: int = 10) -> str:
    """Short, deterministic hash of the Message-ID — used in filenames."""
    return hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:length]


def note_filename(date: datetime, subject: str, message_id: str) -> str:
    """{YYYY-MM-DD}-{subject-slug}-{short-hash}.md — deterministic and
    collision-safe against existing notes."""
    slug = slugify(subject, max_length=80) or "no-subject"
    return f"{date.strftime('%Y-%m-%d')}-{slug}-{short_hash(message_id)}.md"


def attachment_filename(message_id: str, original: str) -> str:
    """Deterministic attachment filename with the Message-ID hash as a
    prefix, so two emails with identically named attachments never collide."""
    original = original or "attachment"
    dot = original.rfind(".")
    if dot > 0:
        stem, ext = original[:dot], original[dot:]
    else:
        stem, ext = original, ""
    stem = slugify(stem, max_length=60) or "attachment"
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext).lower()
    return f"{short_hash(message_id)}-{stem}{ext}"


def _is_image(vault_path: str) -> bool:
    dot = vault_path.rfind(".")
    return dot > 0 and vault_path[dot:].lower() in _IMAGE_EXT


def _yaml_block(data: dict) -> str:
    return yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).strip()


def _rewrite_cids(body: str, attachments: Iterable[_AttachmentLike]) -> str:
    for att in attachments:
        if not att.content_id:
            continue
        embed = f"![[{att.vault_path}]]"
        body = re.sub(
            r"!\[[^\]]*\]\(\s*cid:" + re.escape(att.content_id) + r"\s*\)",
            embed,
            body,
            flags=re.IGNORECASE,
        )
        body = body.replace(f"cid:{att.content_id}", att.vault_path)
    return body


def build_note(
    parsed,
    attachments: list[_AttachmentLike],
    labels: list[str],
) -> str:
    frontmatter = {
        "date": parsed.date.isoformat(),
        "from": parsed.from_,
        "to": parsed.to,
        "subject": parsed.subject,
        "message_id": parsed.message_id,
        "labels": list(labels),
    }

    lines: list[str] = [
        "---",
        _yaml_block(frontmatter),
        "---",
        "",
        f"# {parsed.subject}",
        "",
        f"- **From:** {parsed.from_ or '—'}",
        f"- **To:** {', '.join(parsed.to) if parsed.to else '—'}",
    ]
    if parsed.cc:
        lines.append(f"- **Cc:** {', '.join(parsed.cc)}")
    lines += [
        f"- **Date:** {parsed.date.isoformat()}",
        f"- **Message-ID:** `{parsed.message_id}`",
        "",
    ]

    if attachments:
        lines.append("## Attachments")
        lines.append("")
        for att in attachments:
            link = f"![[{att.vault_path}]]" if _is_image(att.vault_path) else f"[[{att.vault_path}]]"
            lines.append(f"- {link}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(_rewrite_cids(parsed.body_markdown, attachments))
    lines.append("")

    return "\n".join(lines)

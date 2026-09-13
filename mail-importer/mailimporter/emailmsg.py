from __future__ import annotations

import email
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from bs4 import BeautifulSoup
from markdownify import markdownify as _md

log = logging.getLogger("parser")


@dataclass
class Attachment:
    filename: str
    content: bytes
    content_type: str
    content_id: str | None = None


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    date: datetime
    from_: str
    to: list[str]
    cc: list[str]
    body_markdown: str
    attachments: list[Attachment] = field(default_factory=list)
    synthetic_message_id: bool = False


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # noqa: BLE001 - malformed headers shouldn't fail the import
        return str(value).strip()


def _addr_list(msg: EmailMessage, header: str) -> list[str]:
    out: list[str] = []
    for name, addr in getaddresses(msg.get_all(header, [])):
        name = _decode(name)
        addr = addr.strip()
        if name and addr:
            out.append(f"{name} <{addr}>")
        elif addr:
            out.append(addr)
        elif name:
            out.append(name)
    return out


def _parse_date(msg: EmailMessage) -> datetime:
    raw = msg["Date"]
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


def _is_layout_table(table) -> bool:
    """Email clients/newsletters build their layouts almost exclusively with
    <table> (decades of Outlook-compatibility hacks) instead of CSS — even
    grids with dozens of "columns" that are really just page layout, not
    tabular data. A table is only assumed to be real data if it has <th>
    header cells; otherwise it's treated as layout. An explicit
    role="presentation" (common in modern email templates) always counts as
    layout regardless of <th>."""
    if (table.get("role") or "").strip().lower() == "presentation":
        return True
    return not table.find_all("th")


_BLOCK_TAGS = {
    "p", "div", "table", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
}


def _unwrap_layout_tables(soup: BeautifulSoup) -> None:
    """Unwraps layout tables (see _is_layout_table) into plain paragraphs so
    they don't turn into unreadable Markdown pipe tables. Real data tables
    (with <th>) are left alone and become real Markdown tables. Processes
    the innermost tables first (reversed) so nested layout tables get
    unwrapped correctly — a cell may already contain a previously unwrapped
    nested table (now a <div>)."""
    for table in reversed(soup.find_all("table")):
        if not _is_layout_table(table):
            continue
        replacement = soup.new_tag("div")
        for row in table.find_all("tr"):
            for cell in row.find_all(["td", "th"]):
                if not cell.get_text(strip=True) and not cell.find(["img"]):
                    continue  # empty cell (pure spacer) -> skip
                contents = list(cell.contents)
                block = soup.new_tag("div")
                if any(getattr(c, "name", None) in _BLOCK_TAGS for c in contents):
                    # Already contains block elements (e.g. an unwrapped
                    # nested table) — move them as-is. <p> must NEVER
                    # contain <div>/<table> (invalid HTML that markdownify
                    # would otherwise reinterpret unpredictably).
                    block.extend(contents)
                else:
                    # Plain text/inline content only — <p> guarantees a
                    # blank line between cells in the Markdown output.
                    inner = soup.new_tag("p")
                    inner.extend(contents)
                    block.append(inner)
                replacement.append(block)
        table.replace_with(replacement)


def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "meta", "link", "title"]):
        tag.decompose()
    _unwrap_layout_tables(soup)
    md_text = _md(
        str(soup),
        heading_style="ATX",   # preserves headings as #, ##, ...
        bullets="-",           # lists
    )
    # markdownify converts any remaining <table> to pipe tables and <a> to
    # links.
    md_text = re.sub(r"\n{3,}", "\n\n", md_text).strip()
    return md_text or "_(empty HTML content)_"


def parse_email(raw_bytes: bytes) -> ParsedEmail:
    msg: EmailMessage = email.message_from_bytes(  # type: ignore[assignment]
        raw_bytes, policy=policy.default
    )

    subject = _decode(msg["Subject"]) or "(no subject)"
    from_ = ", ".join(_addr_list(msg, "From")) or _decode(msg["From"])
    to = _addr_list(msg, "To")
    cc = _addr_list(msg, "Cc")
    date = _parse_date(msg)

    message_id = _decode(msg["Message-ID"]).strip().strip("<>").strip()
    synthetic = False
    if not message_id:
        digest = hashlib.sha256(raw_bytes).hexdigest()[:32]
        message_id = f"sha256-{digest}@no-message-id.local"
        synthetic = True
        log.warning("Message has no Message-ID — using synthetic id: %s", message_id)

    html_body: str | None = None
    text_body: str | None = None
    attachments: list[Attachment] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = (part.get_content_type() or "").lower()
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode(part.get_filename())

        is_body_candidate = ctype in ("text/plain", "text/html") and disposition != "attachment"

        if not is_body_candidate:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            cid = part.get("Content-ID")
            if cid:
                cid = cid.strip().strip("<>")
            attachments.append(
                Attachment(
                    filename=filename or f"attachment-{len(attachments) + 1}",
                    content=payload,
                    content_type=ctype or "application/octet-stream",
                    content_id=cid or None,
                )
            )
            continue

        try:
            text = part.get_content()
        except Exception:  # noqa: BLE001
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")

        if ctype == "text/html" and html_body is None:
            html_body = text
        elif ctype == "text/plain" and text_body is None:
            text_body = text

    if html_body:
        body_markdown = _html_to_markdown(html_body)
    elif text_body:
        body_markdown = text_body.strip() or "_(empty body)_"
    else:
        body_markdown = "_(no readable text content)_"

    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        date=date,
        from_=from_,
        to=to,
        cc=cc,
        body_markdown=body_markdown,
        attachments=attachments,
        synthetic_message_id=synthetic,
    )

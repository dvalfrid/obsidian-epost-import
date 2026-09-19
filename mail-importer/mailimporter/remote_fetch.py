from __future__ import annotations

import hashlib
import ipaddress
import logging
import mimetypes
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from slugify import slugify

from .config import Config

log = logging.getLogger("remote_fetch")

_DOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv", ".zip",
}

# Markdown produced by markdownify: ![alt](url) for images, [text](url) for
# links. The link pattern excludes a leading "!" so it doesn't also match
# image syntax.
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", re.IGNORECASE)
_LINK_MD_RE = re.compile(r"(?<!!)\[[^\]]*\]\((https?://[^\s)]+)\)", re.IGNORECASE)


@dataclass
class RemoteResource:
    url: str
    is_image: bool


def _url_ext(url: str) -> str:
    path = urlparse(url).path
    dot = path.rfind(".")
    return path[dot:].lower() if dot > 0 else ""


def extract_remote_resources(body_markdown: str) -> list[RemoteResource]:
    """Finds http(s) images (always) and http(s) links to known document
    types (only) referenced in already-converted Markdown body text. Plain
    navigational/tracking/unsubscribe links are left alone."""
    seen: set[str] = set()
    out: list[RemoteResource] = []
    for url in _IMAGE_MD_RE.findall(body_markdown):
        if url not in seen:
            seen.add(url)
            out.append(RemoteResource(url=url, is_image=True))
    for url in _LINK_MD_RE.findall(body_markdown):
        if url in seen:
            continue
        if _url_ext(url) in _DOC_EXTENSIONS:
            seen.add(url)
            out.append(RemoteResource(url=url, is_image=False))
    return out


def remote_filename(url: str, content_type: str) -> str:
    """Deterministic filename keyed on the URL itself (not the Message-ID)
    so the same resource linked from multiple emails maps to the same vault
    path — create_file()'s exists-check then dedupes it for free."""
    basename = urlparse(url).path.rsplit("/", 1)[-1] or "resource"
    dot = basename.rfind(".")
    if dot > 0:
        stem, ext = basename[:dot], basename[dot:]
    else:
        stem, ext = basename, ""
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext).lower()
    if not ext:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".bin"
    stem = slugify(stem, max_length=60) or "resource"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{digest}-{stem}{ext}"


def _is_public_host(hostname: str) -> bool:
    """SSRF guard: the URL comes from externally-received email content and
    this container can reach obsidian:27124 on its internal network — a
    crafted email must not be able to make the importer probe internal
    services or cloud metadata endpoints."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def fetch_remote(url: str, cfg: Config, session: requests.Session) -> tuple[bytes, str] | None:
    """Best-effort download. Returns (content, content_type) on success, or
    None on ANY failure (blocked/unresolvable host, redirect, non-2xx
    status, oversized, network error) — never raises. The caller's fallback
    is to leave the original remote link in place."""
    hostname = urlparse(url).hostname
    if not hostname or not _is_public_host(hostname):
        log.info("Remote fetch blocked (non-public host): %s", url)
        return None

    try:
        resp = session.get(
            url,
            timeout=cfg.remote_fetch_timeout,
            stream=True,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        log.info("Remote fetch failed for %s: %s", url, exc)
        return None

    with resp:
        if resp.status_code != 200:
            log.info("Remote fetch %s -> HTTP %s, skipping", url, resp.status_code)
            return None

        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        content_length = resp.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > cfg.remote_fetch_max_bytes:
                    log.info("Remote fetch %s exceeds max size, skipping", url)
                    return None
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > cfg.remote_fetch_max_bytes:
                log.info("Remote fetch %s exceeded max size while streaming, skipping", url)
                return None
            chunks.append(chunk)

        return b"".join(chunks), content_type

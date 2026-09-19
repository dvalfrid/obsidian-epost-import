from __future__ import annotations

from dataclasses import dataclass

from mailimporter.note_builder import _rewrite_remote_urls


@dataclass
class _FakeAttachment:
    original: str
    vault_path: str
    content_id: str | None = None
    source_url: str | None = None


def test_rewrite_remote_image_keeps_url_as_alt_text():
    body = "See this: ![cool logo](https://example.com/logo.png) neat."
    att = _FakeAttachment(
        original="https://example.com/logo.png",
        vault_path="Email/attachments/abc123-logo.png",
        source_url="https://example.com/logo.png",
    )
    result = _rewrite_remote_urls(body, [att])
    assert result == (
        "See this: ![[Email/attachments/abc123-logo.png|"
        "https://example.com/logo.png]] neat."
    )


def test_rewrite_remote_document_link_keeps_url_as_display_text():
    body = "Download the [invoice](https://example.com/invoice.pdf) here."
    att = _FakeAttachment(
        original="https://example.com/invoice.pdf",
        vault_path="Email/attachments/def456-invoice.pdf",
        source_url="https://example.com/invoice.pdf",
    )
    result = _rewrite_remote_urls(body, [att])
    assert result == (
        "Download the [[Email/attachments/def456-invoice.pdf|"
        "https://example.com/invoice.pdf]] here."
    )


def test_rewrite_leaves_body_untouched_when_no_source_url():
    body = "![alt](https://example.com/still-remote.png)"
    att = _FakeAttachment(
        original="whatever",
        vault_path="Email/attachments/whatever.png",
        source_url=None,
    )
    assert _rewrite_remote_urls(body, [att]) == body

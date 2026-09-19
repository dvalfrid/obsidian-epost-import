from __future__ import annotations

from pathlib import Path

import pytest

from mailimporter.emailmsg import parse_email
from mailimporter.remote_fetch import extract_remote_resources

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES = sorted(FIXTURES_DIR.glob("*.eml"))


@pytest.mark.skipif(
    not FIXTURES, reason="No .eml fixtures in tests/fixtures/ yet — see tests/fixtures/README.md"
)
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_real_email_parses_without_error(path: Path) -> None:
    """Sanity check against real (sanitized) email exports, on top of the
    synthetic .eml in test_integration_remote_resources.py — real HTML has
    quirks (nested layout tables, tracking pixels, odd header encodings)
    synthetic fixtures don't reproduce."""
    raw = path.read_bytes()
    parsed = parse_email(raw)
    assert parsed.body_markdown
    extract_remote_resources(parsed.body_markdown)  # must never raise


def test_newsletter_remote_images_fixture() -> None:
    """A sanitized real Mailchimp-style HTML newsletter (37 nested
    no-<th> layout tables, 21 remote images including a tracking pixel
    disguised as an <img> served from the *tracking* domain rather than the
    CDN, and ~35 personalized-tracking `<a href>` links with no document
    extension). Exercises: layout-table-heavy real HTML doesn't crash the
    parser, every remote <img> is extracted regardless of which domain
    serves it, and plain navigational/tracking links are correctly excluded
    since they don't end in a known document extension."""
    raw = (FIXTURES_DIR / "newsletter-remote-images.eml").read_bytes()
    parsed = parse_email(raw)

    assert parsed.subject == "Granne vill skriva servitut + Knepig husförsäljning"
    assert parsed.attachments == []

    resources = extract_remote_resources(parsed.body_markdown)
    images = {r.url for r in resources if r.is_image}
    docs = [r.url for r in resources if not r.is_image]

    assert len(images) == 21
    assert docs == []

    # A tracking pixel served from the click-tracking domain (not the CDN),
    # wrapped in <img> — must still be picked up like any other remote image.
    assert "https://example.com/redirect/MKAK7cDWDZhgXV4XZC70il" in images

    # A plain personalized tracking link (wraps a heading, not an image, no
    # document extension) — must NOT be treated as a downloadable resource.
    assert "https://example.com/redirect/HRv2NHlR8h2" not in images
    assert "https://example.com/redirect/HRv2NHlR8h2" not in docs

from __future__ import annotations

from email.message import EmailMessage

from mailimporter.emailmsg import parse_email
from mailimporter.remote_fetch import extract_remote_resources


def _build_eml() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Your receipt"
    msg["From"] = "shop@example.com"
    msg["To"] = "daniel@valfridsson.net"
    msg["Message-ID"] = "<abc123@example.com>"
    html = """
    <html><body>
      <p>Thanks for your order!</p>
      <img src="https://cdn.example.com/logo.png" alt="Logo">
      <p><a href="https://example.com/receipts/order-42.pdf">Download your receipt</a></p>
      <p><a href="https://example.com/unsubscribe">Unsubscribe</a></p>
    </body></html>
    """
    msg.set_content("Thanks for your order! (plain text fallback)")
    msg.add_alternative(html, subtype="html")
    return bytes(msg)


def test_parse_email_then_extract_remote_resources():
    parsed = parse_email(_build_eml())
    resources = extract_remote_resources(parsed.body_markdown)
    urls = {(r.url, r.is_image) for r in resources}

    assert ("https://cdn.example.com/logo.png", True) in urls
    assert ("https://example.com/receipts/order-42.pdf", False) in urls
    assert not any(u == "https://example.com/unsubscribe" for u, _ in urls)

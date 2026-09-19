# Real email fixtures

Drop **sanitized** `.eml` exports here — raw RFC 822 source, the same bytes
`parse_email()` receives from IMAP. Easiest way to get one: Proton Mail
webmail → open the message → the `⋮` menu → **"Export message"**.

These exist to exercise real-world HTML quirks (nested layout tables,
tracking pixels, oddly-encoded headers, unusual `cid:`/remote-image mixes)
that the synthetic fixture in `../test_integration_remote_resources.py`
doesn't reproduce.

## This repo is public — sanitize before committing

- Replace real names, addresses, phone numbers, order/account numbers with
  obviously fake placeholders. Keep the surrounding HTML tag structure
  (tables, divs, `<img>`/`<a>` placement) intact — that structure is what's
  actually under test.
- Replace the `From` / `To` / `Message-ID` headers with fake values.
- Genericize personalized tracking tokens in URLs (unsubscribe links,
  per-recipient query params, session tokens) — swap the domain/path for
  something like `https://example.com/...` if the token could identify the
  recipient. Keep the file extension (`.pdf`, `.png`, `.docx`, ...) so the
  remote-resource extraction logic is still exercised.
- Drop or fake any attachment content that isn't relevant to what you're
  testing (a 1x1 placeholder image is fine — the test doesn't care about
  pixel data).

## Usage

Files here are picked up automatically by `../test_real_email_fixtures.py`
— just drop a sanitized `.eml` and run `pytest`, no code changes needed.

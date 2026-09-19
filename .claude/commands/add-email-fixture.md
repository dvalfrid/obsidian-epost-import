---
description: Anonymize a real .eml export and add it as a pytest fixture with tailored assertions
argument-hint: <path-to-.eml-file>
---

Anonymize the `.eml` file at the path given in `$ARGUMENTS` and turn it into
a committed test fixture for the `obsidian-epost-import` mail-importer.
Follow every step below in order — this repo is public on GitHub, so
anonymization is not optional, and assertions must be derived from the
actual parser output, never invented.

## 0. Resolve the input

- `$ARGUMENTS` is a path to a raw `.eml` file (RFC 822 source — e.g.
  exported from Proton Mail webmail via the message's `⋮` menu → "Export
  message"). May be anywhere on disk, absolute or relative to the repo
  root.
- Read it with the Read tool. If it doesn't look like a raw email (no
  `From:`/`Subject:` headers near the top), stop and ask the user — don't
  guess.

## 1. Understand what's in it before anonymizing

By eye, identify:
- `Subject`, `From`, `To`, `Cc`, `Message-ID`, `Date`.
- The HTML body's `<img src="...">` and `<a href="...">` — which are
  `cid:` (embedded/inline), which are remote `http(s)://`.
- Any real MIME attachments (filename, content-type, Content-ID if inline).
- Any real personal data in the visible text: names, street addresses,
  phone numbers, order/invoice/account numbers, personalized greetings.

## 2. Anonymize (mandatory — this repo is public)

Produce a sanitized copy that preserves MIME/HTML **structure** exactly
(same tags, same table nesting, same number/placement of `<img>`/`<a>`,
same attachment count and content-types) while replacing:

- `From` / `To` / `Cc` display names and addresses → obviously fake
  (`Someone <someone@example.com>`, recipient → `daniel@example.com`).
- `Message-ID` → a fake one, e.g. `<fixture-<slug>@example.com>`.
- Any personal name, street address, phone number, order/invoice/account
  number in the subject or body → clearly fake placeholders (`Jane Doe`,
  `123 Fake Street`, `ORDER-000000`). Leave surrounding markup untouched.
- Every remote `http(s)://` URL (image `src` and document `href`) →
  `https://example.com/...`, keeping the **original file extension** on
  document links (`.pdf`, `.docx`, etc.) and a plausible image extension on
  image links — extraction logic keys off these extensions, so they must
  survive. Drop query-string tracking/session tokens entirely.
- Any real MIME attachment's binary payload → a minimal placeholder of the
  same content-type (a tiny valid PNG for images, literal bytes
  `%PDF-1.4\n%%EOF` for a PDF, etc.) — keep the filename, content-type, and
  `Content-ID` header exactly as-is, since cid-rewriting depends on them
  matching what the HTML references.
- Leave `Date` as-is (not sensitive) unless absent — then leave it absent.

Do not paraphrase or restructure the HTML beyond substituting the values
above — the point of a real fixture is to exercise the actual markup shape
(nested layout tables, unusual encodings, etc.), not a rewritten version of
it.

## 3. Name and place it

Pick a short kebab-case slug describing the shape being tested (e.g.
`newsletter-remote-images`, `receipt-pdf-attachment`,
`nested-layout-tables`). Write the sanitized file to:

```
mail-importer/tests/fixtures/<slug>.eml
```

If a very similar fixture already exists, ask the user whether to replace
it or pick a more specific name — don't silently overwrite.

## 4. Derive the correct assertions — don't guess them

Run the sanitized fixture through the actual parser and read its real
output before writing any assertion:

```bash
cd mail-importer
.venv/Scripts/python -c "
from mailimporter.emailmsg import parse_email
from mailimporter.remote_fetch import extract_remote_resources
raw = open('tests/fixtures/<slug>.eml', 'rb').read()
p = parse_email(raw)
print('subject:', p.subject)
print('attachments:', [(a.filename, a.content_type, a.content_id) for a in p.attachments])
print('remote:', extract_remote_resources(p.body_markdown))
print('---body---')
print(p.body_markdown)
"
```

(If the venv doesn't exist yet: `python -m venv .venv && .venv/Scripts/pip
install -r requirements-dev.txt` first.)

## 5. Add a dedicated test

Append a new test function to
`mail-importer/tests/test_real_email_fixtures.py`, below the existing
generic parametrized smoke test (keep that one — it still covers every
fixture generically). Name the new function `test_<slug_with_underscores>_fixture`.
Assert on the specific things that make this fixture worth having as a
named test, based on step 4's real output — for example:
- The exact set of remote resource URLs extracted and their `is_image`
  flag, if this fixture is about remote-resource extraction.
- The exact attachment filenames/content-ids, if it's about `cid` handling.
- That a specific layout-table quirk unwraps as expected, if that's the
  point of the fixture.

Load the fixture the same way the existing smoke test does
(`FIXTURES_DIR / "<slug>.eml"`).

## 6. Verify

```bash
cd mail-importer
.venv/Scripts/python -m pytest -q
```

All tests, including the new one, must pass. If something's off, fix the
fixture or the assertion — never loosen an assertion just to make it pass.

## 7. Do not commit

Leave the new/changed files unstaged. Committing to a public repo is the
user's call, not something to do automatically here.

## 8. Report back

Summarize in Swedish (this user communicates in Swedish): what kind of data
was anonymized (in general terms — never re-print the original PII), where
the fixture landed, what the new test asserts, and confirm the full suite
passes.

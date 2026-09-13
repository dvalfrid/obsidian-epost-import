# Security Policy

## Supported versions

Only the latest release receives security fixes.

| Version        | Supported |
| -------------- | --------- |
| Latest release | ✅        |
| Older versions | ❌        |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use one of these private channels:

- **GitHub private vulnerability reporting** —
  [Report a vulnerability](https://github.com/dvalfrid/obsidian-epost-import/security/advisories/new)
  (preferred)
- **Email** — daniel@valfridsson.net

Include as much of the following as possible:

- Type of issue (e.g. credential leakage, signature-verification bypass,
  container escape, injection)
- Steps to reproduce
- Affected version/image tag
- Potential impact

## Response timeline

|                 | Target                                      |
| --------------- | -------------------------------------------- |
| Acknowledgement | Within 7 days                               |
| Patch release   | Within 14 days of a confirmed vulnerability |

## Scope and threat model

This project handles real credentials for a Proton Mail account and writes
into a personal Obsidian vault. Security issues most relevant here:

- **Credential handling** — `IMAP_PASS` (Bridge password), `OBSIDIAN_API_KEY`,
  and Bridge's session/GPG secret store must never end up in logs, a Docker
  image layer, or the repo. `.env` is git-ignored; secrets are only ever
  passed via environment variables or named volumes.
- **Bridge's secret store** (`epost-import-bridge-config` volume) —
  compromising it is equivalent to full read access to the mailbox. See
  `bridge/entrypoint.sh` for how it's created and gated.
- **Supply chain** — `bridge/Dockerfile` downloads Proton's official `.deb`
  and verifies its OpenPGP signature against a pinned key fingerprint before
  installing; a change to that verification logic (or to the pinned
  fingerprint/base images) is security-sensitive and should be reviewed
  carefully.
- **`/var/run/docker.sock`** — the optional `autoheal` service mounts it,
  which is equivalent to root on the Docker host. This is a documented,
  deliberate trade-off (see README "Robustness & self-healing") with an
  opt-out; changes that grant socket access to any *other* service would
  need the same scrutiny.
- **Local REST API key** — grants create-only write access to the Obsidian
  vault; the plugin's port is intentionally never published to the host
  network, only reachable internally by `mail-importer`.
- **Injected email content** — HTML from arbitrary senders is parsed and
  converted to Markdown (`mail-importer/mailimporter/emailmsg.py`). It should
  never be interpreted as anything executable, and vault paths derived from
  email content (filenames, attachment names) are always sanitized/slugified
  before being used.

Out of scope: attacks that require an already-compromised Docker host or an
already-compromised Proton account; exposing the one-time setup ports
(Obsidian web UI, port 3001) to the internet instead of `127.0.0.1` only
(explicitly unsupported, see README Step 1/2).

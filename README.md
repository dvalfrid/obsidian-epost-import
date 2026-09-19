# obsidian-epost-import

Fetches email from a **Proton Mail label** via a **self-built, containerized
Proton Mail Bridge** and creates **notes + attachments** in the Obsidian
vault **Daniel** — through a **self-built, headless Obsidian instance in
Docker**. The whole chain (Bridge, Obsidian, the importer) runs in this
repo's own docker-compose stack, independent of any always-on computer.

```
                                                              Cloudflare Tunnel
                                                                      │
                                                                      ▼
┌───────────────┐  IMAP (143)  ┌─────────────────┐  https://obsidian:27124  ┌──────────────────────────┐
│  bridge       │◀────────────│  mail-importer  │─────────────────────────▶│  obsidian (LSIO image)   │
│  (own image)  │              │  (Python)       │      Local REST API      │  LiveSync ──▶ CouchDB     │
└───────────────┘              └─────────────────┘                          └──────────────────────────┘
        │                              │                                   (obsidian.valfridsson.se /
        ▼                              ▼                                    vault-daniel)
  Proton account (real         /data/state.sqlite3
  IMAP, real login)            (own volume, NOT in the vault)
```

---

## Prerequisites

Needed **either way** (prebuilt images or building from source):

- **Docker Engine + Docker Compose v2** (the `docker compose` command, not
  the old standalone `docker-compose` v1) — Docker Desktop on Windows/Mac,
  or Docker Engine + the compose plugin on Linux/NAS (most NAS "Container
  Manager"/"Docker" packages already include it).
- **`linux/amd64` only** — a NAS or PC with an Intel/AMD CPU. Published
  images aren't built for ARM (Raspberry Pi, some ARM-based Synology/QNAP
  models) — you'd have to add that yourself (see the platform comment in
  `.github/workflows/ci.yml`).
- **~2 GB RAM** free and a few GB of disk (the Obsidian base image alone is
  roughly 1 GB) — see "Resource limits" below for the per-service split.
- **A Proton account with Bridge access** — Mail Plus, Unlimited, Duo,
  Family, or Business. Not included in the free plan.
- **A LiveSync-compatible CouchDB backend** already reachable over HTTPS —
  this project does not create one for you, see "Bring your own CouchDB /
  LiveSync backend" right below.
- **A terminal** (PowerShell or Bash) and a text editor for `.env`.
- **A modern web browser**, for the one-time Obsidian setup step (Step 1).

Additionally, for **"Run without a dev environment"**: `curl` (already built
into Windows 10/11, macOS, and most Linux distros).

Additionally, for **"Quick start — from source"**: `git`.

---

## Bring your own CouchDB / LiveSync backend

This is its **own repo** and its **own docker-compose project**
(`name: obsidian-epost-import`) — it doesn't share a network, volumes, or
containers with anything else on your NAS.

It also doesn't set up CouchDB or a Cloudflare Tunnel for you. The Obsidian
container just configures the
[Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync) plugin to
sync **exactly like a regular client device would** — over HTTPS, against
whatever CouchDB instance and vault database you already have (or set up
separately). If you don't have one yet, see the
[Self-hosted LiveSync docs](https://github.com/vrtmrz/obsidian-livesync) for
how to run CouchDB, with or without a tunnel; that setup is independent of
this repo and can be shared across as many vaults and devices as you like.

> The URI/username/database shown in Step 1 (`https://obsidian.valfridsson.se`,
> `vault-daniel`) are the author's own values, used as a concrete example —
> substitute your own.

---

## About the `obsidian` container

Built on **[`lscr.io/linuxserver/obsidian`](https://docs.linuxserver.io/images/docker-obsidian/)**
(LinuxServer.io) — an actively maintained, version-tagged image that rebuilds
regularly for security updates. Obsidian runs there in a **Selkies desktop**
streamed to the browser (HTTPS, port 3001).

`./obsidian/Dockerfile` adds just **one** thin layer: an init script
(`obsidian/custom-cont-init.d/50-install-local-rest-api`) that preinstalls the
**obsidian-local-rest-api** plugin into the vault at startup. No Obsidian, VNC,
or sandboxing logic is maintained in this repo.

> The LSIO image grants "privileged access" to a full desktop. Never expose
> it to the internet, and consider an egress firewall that only allows
> outbound traffic to Cloudflare (for `obsidian.valfridsson.se`).

---

## About the `bridge` container

**Own image** (`./bridge/Dockerfile`), not a prebuilt one from Docker Hub. No
official Proton image exists, and the community alternatives we evaluated had
stopped publishing new builds to Docker Hub despite upstream Proton Bridge
still shipping new releases — pinning one of those would have meant running
months-old security patches in something that decrypts an entire mailbox, and
Proton has historically cut off login for outdated Bridge versions.

Our own image:

- Downloads Proton's **official** `.deb` package directly from
  `github.com/ProtonMail/proton-bridge/releases` (the same binary a native
  install would use).
- **Verifies the OpenPGP signature** against Proton's published signing key
  (fingerprint pinned in the Dockerfile) before installing — the build FAILS
  if it doesn't match.
- Uses `pass` (GNU) plus a headless-generated GPG key as the local secret
  store, since Bridge on Linux requires either `secret-service` (dbus, needs
  a desktop session — not available here) or `pass`.
- `socat` proxies Bridge's hardcoded `127.0.0.1`-only IMAP/SMTP ports
  (`1143`/`1025`, Bridge's own internal defaults) out to `143`/`25` on the
  container's interface, so `mail-importer` can reach them over
  `epost-import-net`. **The port numbers MUST differ** — `socat`'s
  "all interfaces" binding otherwise collides with Bridge's `127.0.0.1`
  binding for the same port number.
- Refuses to start in daemon mode (`docker compose up bridge`) if the
  one-time login (`init`) hasn't been run yet — logs a clear error instead of
  silently continuing with an unencrypted secret store, unlike the reference
  images we looked at.

See `bridge/entrypoint.sh` for the full logic. Upgrade by setting a newer
`BRIDGE_VERSION` in `.env` (see
[Proton Bridge releases](https://github.com/ProtonMail/proton-bridge/releases))
and `docker compose up -d --build bridge`.

Proton Mail Bridge is GPLv3-licensed; redistributing built binaries/images is
explicitly permitted as long as the source stays available, which Proton
already publishes at the URL above.

---

## Contents

```
obsidian-epost-import/
├── docker-compose.yml        # obsidian + bridge + mail-importer + autoheal, own network/volumes/limits
├── .env.example               # all environment variables
├── README.md
├── CLAUDE.md                  # context for the AI assistant
├── obsidian/
│   ├── Dockerfile             # FROM lscr.io/linuxserver/obsidian:<pinned> + init script
│   └── custom-cont-init.d/
│       └── 50-install-local-rest-api   # preinstalls the Local REST API plugin
├── bridge/
│   ├── Dockerfile              # FROM debian:bookworm-slim + official .deb + GPG verification
│   ├── entrypoint.sh           # init/daemon modes, pass/GPG secret store, socat proxy
│   └── gpg-batch-params        # headless GPG key generation for pass
└── mail-importer/
    ├── Dockerfile
    ├── requirements.txt
    └── mailimporter/           # the Python package (run: python -m mailimporter)
```

---

## Run without a dev environment (recommended)

You do **not** need to clone the repo or have Python/Dockerfiles locally — CI
publishes prebuilt images to GHCR for all three services. All you need is
`docker-compose.yml` + a `.env` file.

| Tag | Built | Use for |
|---|---|---|
| `:latest` | on every release (`vX.Y.Z`) | **normal operation** — follows the latest release |
| `:X.Y.Z` / `:X.Y` / `:X` | on every release | pin an exact version |
| `:main` / `:sha-<short>` | on every push to `main` | test the latest (may be unstable) |

```bash
mkdir obsidian-epost-import && cd obsidian-epost-import
curl -fsSLO https://raw.githubusercontent.com/dvalfrid/obsidian-epost-import/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/dvalfrid/obsidian-epost-import/main/.env.example
cp .env.example .env
# Edit .env — at minimum IMAP_USER, OBSIDIAN_WEB_PASSWORD

docker compose pull
```

Then continue with **Steps 1–3** below (identical whether you `pull`ed or
built from source) — they can't be automated away: the Obsidian GUI and the
Proton login require you, a real human, at the keyboard.

Update later: `docker compose pull && docker compose up -d`.
`docker-compose.yml` uses `:latest` for all three images — pin a version by
changing e.g. `image: ghcr.io/dvalfrid/obsidian-epost-import/bridge:0.1.0`.

---

## Quick start — from source

If you'd rather build it yourself (development, or reviewing the code before
running it):

```bash
git clone https://github.com/dvalfrid/obsidian-epost-import
cd obsidian-epost-import
cp .env.example .env
# Edit .env — at minimum IMAP_USER, OBSIDIAN_WEB_PASSWORD

# 1. Temporarily open the web UI port (step 1a), start just obsidian:
docker compose up -d --build obsidian

# 2. Configure LiveSync + get the Local REST API key via the web UI (step 1).
#    Put the key in .env as OBSIDIAN_API_KEY.

# 3. Close the web UI port again (step 2).

# 4. One-time login to Proton (step 3, INTERACTIVE — run in your own terminal):
docker compose build bridge
docker compose run --rm -it bridge init
#   -> login (email address, password, 2FA if enabled)
#   -> info  (Bridge password -> .env as IMAP_PASS)
#   -> exit

# 5. Find the exact label name and start everything:
docker compose up -d --build bridge
docker compose run --rm mail-importer list-folders   # look for e.g. "Labels/Obsidian"
#   set MAILBOX in .env to what you found
docker compose up -d --build
docker compose logs -f mail-importer
```

---

## Step 1 — One-time setup of the `obsidian` container

The headless Obsidian instance needs to be configured **once**: open the
vault, enable community plugins, log in LiveSync against CouchDB, and grab
the Local REST API key.

### 1a. Temporarily open the web UI port

In `docker-compose.yml`, under the `obsidian` service, **uncomment**:

```yaml
    ports:
      - "127.0.0.1:3001:3001"
```

Binding to `127.0.0.1` means the port can only be reached from the NAS
itself. Start it (builds automatically if you're running from source and
haven't already `pull`ed):

```bash
docker compose up -d obsidian
```

### 1b. Open the web UI

If you're at the NAS: go to `https://127.0.0.1:3001` (accept the self-signed
certificate).
From another machine — tunnel the port over SSH first:

```bash
ssh -L 3001:127.0.0.1:3001 <user>@<nas-ip>
# then open https://127.0.0.1:3001 in your own browser
```

Login: `OBSIDIAN_WEB_USER` / `OBSIDIAN_WEB_PASSWORD` from `.env`.

### 1c. Open the vault and enable community plugins

1. In Obsidian: **Open folder as vault** →
   `/config/Daniel` (must exactly match `OBSIDIAN_VAULT_NAME` from `.env`).
   The init script already placed the Local REST API plugin's files there.
2. **Settings → Community plugins** → if it says "Restricted mode", click
   **Turn on community plugins**.
3. **Local REST API** should now appear under **Installed plugins** — make
   sure it's **enabled** (toggle on). If the list is empty, the init script
   didn't run (no internet at startup?) — install the plugin manually via
   **Browse** instead.

### 1d. Configure Self-hosted LiveSync

1. **Settings → Community plugins → Browse** → search for **Self-hosted
   LiveSync** → install + enable (if not already present).
2. **LiveSync settings → Setup → "Open setup wizard" → "Set up manually"**.
3. Fill in your own CouchDB details (the same as any regular device would
   use — the values below are the author's own, shown as an example):

   | Field | Value |
   |---|---|
   | URI | `https://obsidian.valfridsson.se` |
   | Username | `daniel` |
   | Password | Daniel's CouchDB password |
   | Database | `vault-daniel` |

4. **Test** → green. **Next**.
5. Sync mode: **LiveSync**.
6. Enable **End-to-end encryption** and enter the **same passphrase** used on
   your other devices (otherwise the container can't read your encrypted
   notes).
7. **Apply**. Wait for the first sync to finish.

> Alternative: on an already-configured device, **"Copy setup URI"**, then in
> the container **"Connect with setup URI"** + passphrase.

### 1e. Get the Local REST API key

1. **Settings → Community plugins → Local REST API**.
2. Copy the **API Key** field.
3. Paste into `.env`:

   ```
   OBSIDIAN_API_KEY=<the-long-key>
   ```

4. Check that **"Binding Host"** in the plugin's settings is empty or
   `0.0.0.0` (not `127.0.0.1`) — otherwise `mail-importer` can't reach the
   port from its own container.

The plugin listens on **HTTPS 27124** with a self-signed certificate, which is
why `mail-importer` talks to `https://obsidian:27124` with
`OBSIDIAN_API_VERIFY_TLS=false` (default). To use unencrypted HTTP instead:
enable the plugin's "Non-encrypted (HTTP) Server" on 27123 and set
`OBSIDIAN_API_URL=http://obsidian:27123` in `.env`.

---

## Step 2 — Close the web UI exposure afterward

Once LiveSync is logged in and the key is in `.env`:

1. In `docker-compose.yml`, **comment out** the `ports:` block under
   `obsidian` again:

   ```yaml
    # ports:
    #   - "127.0.0.1:3001:3001"
   ```

2. Apply:

   ```bash
   docker compose up -d obsidian
   ```

   Check:

   ```bash
   docker ps --filter name=epost-import-obsidian   # no 3001 in PORTS
   ```

3. (Recommended) rotate `OBSIDIAN_WEB_PASSWORD` in `.env` now that it's no
   longer needed.

The Local REST API port (27124) is never exposed to the host network — only
via `expose:` internally on `epost-import-net`, reachable only by
`mail-importer`.

---

## Step 3 — One-time setup of the `bridge` container

Proton Bridge must be logged in **once**, interactively. This **cannot** be
automated (requires your password and possibly a live 2FA code) — you have to
run it yourself in a real terminal; this isn't something an AI assistant can
do for you.

### 3a. Log in

```bash
docker compose run --rm -it bridge init
```

(Builds automatically first if you're running from source and haven't
already `pull`ed.)

Wait until `Welcome to Proton Mail Bridge interactive shell` appears (it
generates a GPG key and initializes its secret store the first time — takes
a few seconds). Then, at that prompt:

1. `login` → your Proton address, password, 2FA code if enabled.
2. `info` → shows the account's IMAP/SMTP details, including the
   **Bridge password** (auto-generated, long — **not** your regular Proton
   password). Paste it into `.env` as `IMAP_PASS`.
3. `exit`.

> **After `login` a one-time sync begins** of the whole mailbox (can take a
> while depending on how much mail you have). It's crash-safe/resumable —
> you can safely run `info`/`exit` before it finishes; it continues in the
> background once you start `bridge` as a daemon in the next step. The log
> becomes a continuous stream of `Sync (...): X% ...` lines while this
> happens, which can make it hard to see what you're typing — your keystrokes
> are still received, just type and press Enter. Avoid Ctrl+C (risks killing
> the whole container since it was started with `--rm`).

### 3b. Start as a daemon

```bash
docker compose up -d bridge
```

The session stays in the volume — no new login is needed after this, neither
on container restart nor after a NAS power outage.

### 3c. Find the exact label name

Proton labels show up in Bridge as their own folders under `Labels/<name>`
(folders show up under `Folders/<name>`) — **not** just `<name>`:

```bash
docker compose run --rm mail-importer list-folders
```

Set `MAILBOX=Labels/Obsidian` (or whatever your label is called) in `.env`.

### Alternative: run Bridge natively instead

If you'd rather run Proton Mail Bridge as a regular program on a computer
instead of in Docker: install it from
[proton.me/mail/bridge](https://proton.me/mail/bridge) (requires a paid
plan), get the Bridge password from its GUI, and set in `.env`:

```
IMAP_HOST=host.docker.internal   # Bridge runs on the same machine as Docker
# IMAP_HOST=192.168.x.y          # Bridge runs on another machine on the LAN
IMAP_PORT=1143
```

Then remove/comment out the `bridge` service in `docker-compose.yml` (and its
`depends_on` entry in `mail-importer`). `host.docker.internal` works out of
the box on Docker Desktop; on Linux/NAS, `extra_hosts: host-gateway` (already
set in the compose file) resolves the name to the Docker host.

---

## How the import works

- **Long-running process** (no cron). **IMAP IDLE** gives near-real-time
  delivery; a **poll every 5 minutes** (`POLL_INTERVAL_SECONDS`) is a safety
  net.
- The folder is selected **read-only** and messages are fetched with
  **`BODY.PEEK[]`** — the `\Seen` flag on the server is never touched.
  **All** messages are fetched, regardless of read status.
- **Tracking** in `/data/state.sqlite3` (own volume
  `epost-import-importer-state`, **not** in the vault):
  `(uidvalidity, uid, message_id, note_path, imported_at)`.
  - A new message = `(uidvalidity, uid)` missing from the database.
  - **Changed `UIDVALIDITY`** → dedup falls back to **Message-ID**.
  - Messages without a `Message-ID` get a synthetic
    `sha256-…@no-message-id.local`.
- **Per new message:**
  1. Parses sender, recipients (To/Cc), subject, date, Message-ID, body.
     HTML → Markdown with headings, lists, and links preserved. `cid:`
     references are rewritten as links to the uploaded attachments.
  2. **All Proton labels the message has** are looked up (not just the
     watched one) — see "Multiple labels" below.
  3. **Attachments first** → `PUT` to `Email/attachments/` via Local REST API.
  4. **Then the note**, which links the attachments (`![[...]]` for images,
     otherwise `[[...]]`).
  5. **`(uidvalidity, uid, message_id)` is written to SQLite** — this is the
     actual "done" marker. If the process crashes before this, the UID is
     imported again next run; the note is only created if it's missing, so
     no duplicates.
- **Filename:** `{YYYY-MM-DD}-{subject-slug}-{10-char-hash-of-message-id}.md`
  — deterministic. Existing files are **never overwritten** (existence check
  before every `PUT`).
- **Frontmatter:** `date`, `from`, `to`, `subject`, `message_id`, `labels`.
- **Multiple labels in frontmatter:** IMAP only shows which folder you happen
  to have selected — a message with both the `Obsidian` and `Ida` labels only
  appears to be in `Labels/Obsidian` if you're just looking at the watched
  folder. The importer therefore searches through **all** `Labels/*` folders
  in Bridge for the same Message-ID and includes everything it finds in the
  frontmatter's `labels:`. `NOTE_LABELS` in `.env` is added as **extra**,
  static tags on top of the real Proton labels found (no longer the only
  source).
- **HTML tables in email:** most HTML email (newsletters, receipts,
  automated notifications) builds its **layout** with `<table>` — decades of
  Outlook-compatibility hacks — not to present real tabular data. Converted
  literally, these become absurd Markdown pipe tables (can end up with dozens
  of made-up "columns" that are really just page layout). A table is
  therefore only treated as **real data** (becomes an actual Markdown table)
  if it has **`<th>` header cells** and isn't marked `role="presentation"` —
  otherwise it's unwrapped into plain paragraphs/lines.
- **Remote images/documents:** emails often link to remote resources instead
  of embedding them (`<img src="https://...">`, links to PDFs/Word docs,
  etc.) — if the sender's server later disappears, the note would lose them.
  The importer best-effort downloads remote `http(s)` images and links to
  known document types (PDF, Word, Excel, PowerPoint, ODF, RTF, CSV, ZIP)
  and re-hosts them as normal vault attachments, rewriting the note to embed
  the local copy with the **original URL kept as its alt text** (images) or
  display text (documents). On any failure (host blocked, timeout, too
  large, non-2xx status) the original remote link is left untouched — it
  never affects the rest of the import. Disable with `REMOTE_FETCH_ENABLED=false`.
- **Error handling:** a failed Local REST API call → logged, the UID is
  **not** marked (retried next run), the queue continues with the rest.
  Retries with **exponential backoff, max 3 attempts** against both IMAP and
  the Local REST API.
- **Network errors:** automatic reconnection with backoff up to 5 minutes
  (`RECONNECT_BACKOFF_MAX_SECONDS`).
- **Graceful shutdown:** `SIGTERM` (`docker compose stop`) lets an in-progress
  import finish before the process exits. Can take up to
  `IDLE_TIMEOUT_SECONDS` (default 60) to respond; `stop_grace_period` in
  compose is set to 90s.

---

## Environment variables

See **`.env.example`** for the full list with comments. The most important:

| Variable | Default | Description |
|---|---|---|
| `IMAP_HOST` / `IMAP_PORT` | `bridge` / `143` | The `bridge` container's socat forward port (NOT Bridge's own internal `1143`) |
| `IMAP_USER` / `IMAP_PASS` | – | Address + **Bridge** password (from `info` in step 3a) |
| `IMAP_STARTTLS` / `IMAP_SSL` / `IMAP_VERIFY_CERT` | `true` / `false` / `false` | Bridge = STARTTLS, self-signed |
| `MAILBOX` | `Obsidian` | Watched label/folder — in practice usually `Labels/<name>`, `list-folders` shows the exact name |
| `OBSIDIAN_API_KEY` | – | From the Local REST API plugin (step 1e) |
| `OBSIDIAN_API_URL` | `https://obsidian:27124` | Internal service name, never an external IP |
| `OBSIDIAN_API_VERIFY_TLS` | `false` | Self-signed cert |
| `NOTE_FOLDER` / `ATTACHMENT_FOLDER` | `Email` / `Email/attachments` | Destination in the vault |
| `NOTE_LABELS` | `Obsidian` | Comma-separated, added **on top of** the real Proton labels discovered per email |
| `REMOTE_FETCH_ENABLED` | `true` | Download remote images/documents linked from email bodies into the vault |
| `REMOTE_FETCH_MAX_BYTES` | `26214400` | Max size (bytes) per downloaded remote resource |
| `REMOTE_FETCH_TIMEOUT_SECONDS` | `20` | Timeout per remote download |
| `POLL_INTERVAL_SECONDS` | `300` | Safety-net poll |
| `IDLE_TIMEOUT_SECONDS` | `60` | IDLE wait time / shutdown responsiveness |
| `RECONNECT_BACKOFF_MAX_SECONDS` | `300` | Max backoff on network errors |
| `API_MAX_RETRIES` | `3` | Retries against IMAP / Local REST API |
| `HEARTBEAT_MAX_AGE_SECONDS` | `900` | Docker HEALTHCHECK/autoheal: how old the heartbeat may get |
| `OBSIDIAN_BASE_TAG` | `v1.13.7-ls144` | Pinned LSIO image tag |
| `OBSIDIAN_WEB_USER` / `OBSIDIAN_WEB_PASSWORD` | `admin` / – | Basic auth for the web UI, one-time setup only |
| `OBSIDIAN_VAULT_NAME` | `Daniel` | Vault directory under `/config` |
| `LOCAL_REST_API_VERSION` | `5.1.0` | Plugin version the init script fetches |
| `PUID` / `PGID` | `1000` / `1000` | File owner inside the obsidian container |
| `BRIDGE_VERSION` | `3.26.0-1` | Pinned Proton Bridge version (see `bridge/Dockerfile`) |
| `*_MEM_LIMIT` / `*_CPUS` | see `.env.example` | Per-service resource limits |

---

## Operations & troubleshooting

```bash
docker compose ps                       # status + health
docker compose logs -f mail-importer    # import log
docker compose logs -f obsidian         # Obsidian / LiveSync / init script
docker compose logs -f bridge           # Proton Bridge / sync status
docker compose logs -f autoheal         # see if it restarted something for you
docker compose run --rm mail-importer list-folders   # list IMAP folders
docker compose restart mail-importer
docker compose stop                     # graceful (SIGTERM)
```

- **`docker: 'compose' is not a docker command'` (TerraMaster TNAS and some
  other NAS Docker packages)**: the engine is installed but the Compose v2
  CLI plugin isn't. Install it manually:
  ```bash
  mkdir -p ~/.docker/cli-plugins
  curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  docker compose version
  ```
  If the NAS's Docker daemon/CLI runs under a different account than your SSH
  session, check `docker info | grep -i cli-plugins` for the plugin search
  path and install there instead (e.g.
  `/usr/libexec/docker/cli-plugins/docker-compose`). Don't fall back to the
  legacy standalone `docker-compose` (hyphenated) binary — this repo relies
  on v2 syntax (see Prerequisites above).
- **`mail-importer` won't start / "waiting for Local REST API"**: the
  obsidian container isn't `healthy` yet. Most common the first time — you
  need to finish Step 1 (open the vault, enable community plugins, configure
  LiveSync) before the plugin starts listening on 27124. Check
  `docker compose logs obsidian`.
- **`mail-importer` can't reach `obsidian:27124`**: set **"Binding Host"** in
  the Local REST API plugin to empty or `0.0.0.0` (step 1e) — the default is
  `127.0.0.1`, which only works from inside the obsidian container itself.
- **The init script installed nothing**:
  `docker compose logs obsidian | grep local-rest-api`. No internet at
  startup? Install the plugin manually via **Browse** in the GUI.
- **`bridge` won't start / logs "no secret store found"**: the one-time login
  (step 3a) hasn't been done yet — `docker compose run --rm -it bridge init`.
- **`bridge` logs "address already in use"**: someone changed the port
  numbers in `bridge/entrypoint.sh`/`docker-compose.yml` so socat's forward
  port collides with Bridge's own `127.0.0.1` port. They MUST be different
  port numbers (143↔1143, 25↔1025) — see "About the `bridge` container".
- **No emails are imported**: wrong `MAILBOX` name (run `list-folders` —
  remember the `Labels/` prefix), or the Bridge password is wrong.
- **A message is missing a label in its frontmatter**: `mail-importer`
  searches all `Labels/*` folders at import time — labels added to an email
  **after** it's already been imported don't show up retroactively. Delete
  the note + its SQLite row (see below) to reimport it.
- **Want to force reimport of one specific email** (e.g. after a code fix):
  delete the note via the Local REST API (`DELETE /vault/<path>`) and the
  matching row in SQLite (`DELETE FROM imported WHERE uid = <uid>` in
  `/data/state.sqlite3` inside the `mail-importer` container), then restart
  `mail-importer`.
- **Want to force reimport of everything**: remove the tracking volume
  (`docker compose down` + `docker volume rm obsidian-epost-import_epost-import-importer-state`).
  Notes already in the vault still won't be overwritten.
- **Upgrade the obsidian image**: set a newer `OBSIDIAN_BASE_TAG` in `.env`
  (see [LSIO releases](https://github.com/linuxserver/docker-obsidian/releases)),
  run `docker compose up -d --build obsidian`.
- **Upgrade the bridge image**: set a newer `BRIDGE_VERSION` in `.env` (see
  [Proton Bridge releases](https://github.com/ProtonMail/proton-bridge/releases)),
  run `docker compose up -d --build bridge`.

---

## Resource limits & isolation from the NAS's other services

Set directly in `docker-compose.yml`:

| Service | RAM (`mem_limit`) | CPU (`cpus`) | Other |
|---|---|---|---|
| `obsidian` | `1g` | `1.0` | `shm_size: 1gb` (required by Electron) |
| `bridge` | `512m` | `0.5` | — |
| `mail-importer` | `512m` | `0.75` | `stop_grace_period: 90s` |
| `autoheal` | `64m` | `0.1` | see "Robustness & self-healing" below |

All four services run with `restart: unless-stopped`. A bug can therefore
never starve CouchDB, Cloudflared, or anything else on the NAS.

---

## Robustness & self-healing on NAS reboot/power loss

Goal: after a power outage or NAS reboot, the whole stack should come back up
on its own, with no manual steps. Here's how that holds together:

### What's already robust by design

- **`restart: unless-stopped`** on all four services → when dockerd comes
  back up after a power outage, Docker restarts them automatically, no
  matter how long the NAS was down. (The only exception: if you ran
  `docker compose stop` manually before the outage — Docker leaves them
  stopped then, as expected.)
- **Startup order doesn't matter.** `depends_on: condition: service_healthy`
  only governs the `docker compose up` command — dockerd's own restart-on-boot
  does NOT respect it. That's fine: `mail-importer` has its own
  `_wait_for_obsidian()` retry (backoff up to 60s) and connects as soon as
  the Local REST API responds, regardless of container startup order.
- **IMAP/network errors:** automatic reconnection with backoff up to
  `RECONNECT_BACKOFF_MAX_SECONDS` (default 300s) — covers both Proton Bridge
  not being up yet and temporary network hiccups.
- **`bridge` needs no new login on restart** — the session and the
  GPG key/pass secret store live in the persisted volume. An in-progress
  sync is resumable: if interrupted (restart, power loss) it continues where
  it left off rather than starting over.
- **Crash-safe SQLite:** WAL mode + `synchronous=FULL` + the "done" marker
  (`mark_imported`) being the last, atomic operation in every import. A power
  outage mid-import means, at worst, the same UID gets imported again next
  run — never a duplicate or a corrupted database (files are only written if
  missing).
- **LiveSync** in the obsidian container behaves like on any other device:
  the passphrase and connection remain in the persisted `/config` volume; it
  resumes syncing automatically when it comes back up — no new login is
  needed after the initial one-time setup.

### The gap that's already closed: hung (not crashed) containers

`restart: unless-stopped` only triggers when **the process actually exits**.
If Obsidian/Electron (or Bridge/the socat forwarding) freezes without that
showing up as an exit (the most common way a headless container "dies"), the
container stays up but unusable — Docker reports `unhealthy` but doesn't
restart it on its own.

That's covered by the **`autoheal`** service: it watches Docker's health
status for every container labeled `autoheal=true` (`obsidian`, `bridge`, and
`mail-importer`) and runs `docker restart` on them if they stay `unhealthy`
for a while.

> **Trade-off:** `autoheal` requires mounting `/var/run/docker.sock`, which
> in practice is equivalent to root access to the whole Docker host. That's a
> deliberate compromise for full self-healing. If you'd rather avoid that
> exposure: remove the `autoheal` service and the `labels: [autoheal=true]`
> entries on the other services in `docker-compose.yml` — you still get
> restarts on actual crashes, but you'll need to run `docker compose ps`
> yourself now and then and look for `unhealthy` if something hangs.

### The one manual prerequisite — Docker starting at boot

This is controlled by the NAS, not by this repo: make sure **Container
Manager/Docker is set to start automatically at boot** in TOS (otherwise
none of the above kicks in after a power outage). In TOS:
**Container Manager → Settings → "Enable at startup"** (the exact name may
vary between TOS versions). Any other self-hosted Docker service on the same
NAS relies on the same setting.

### Test it yourself

```bash
# Simulate a container hanging / crashing:
docker kill -s SIGSTOP epost-import-obsidian   # freeze it (unhealthy, not exited)
docker compose ps                              # watch "unhealthy" appear
#   ... wait out AUTOHEAL_START_PERIOD + a few healthcheck intervals ...
docker compose logs -f autoheal                 # watch it restart the container

# Simulate a power outage:
docker compose kill                             # hard, no graceful shutdown
docker compose ps                               # containers come back on
                                                 # their own (unless-stopped)
```

---

## Portability — the same stack locally (Windows) and on the NAS

The project is built to run **unchanged** on Windows/Docker Desktop now and
on TerraMaster TOS/Linux later:

- **No host paths, user IDs, or environment assumptions in
  `docker-compose.yml`.** Anything that differs between environments is
  driven by `.env`.
- **Only Docker-managed named volumes**, no bind mounts against `C:\...` or
  `/volume1/...`. Named volumes behave identically regardless of host
  machine. SQLite (the UID tracking) does frequent small writes/locks and is
  especially sensitive to the slow I/O and permission/notification issues a
  Windows bind mount via WSL2 can cause — hence a named volume.
- `host.docker.internal` (only relevant if you run Bridge natively instead of
  in the `bridge` container) resolves automatically on Docker Desktop and via
  `extra_hosts: host-gateway` on Linux.

### What you change in `.env` when moving to the NAS

| Variable | Why |
|---|---|
| `PUID` / `PGID` | Match your NAS user (run `id <user>` on the NAS via SSH) |
| `TZ` | If needed |
| `*_MEM_LIMIT` / `*_CPUS` | If the NAS has a different resource budget |

Everything else stays the same (including `IMAP_HOST=bridge` — Bridge runs in
Docker on both machines). On the NAS: `docker compose pull && docker compose up -d`
(or `docker compose up -d --build` if running from source).

### Named volumes — names and contents

Actual volume names = project name + volume key
(`docker volume ls | grep epost-import`):

| Volume | Contents | Needs moving? |
|---|---|---|
| `obsidian-epost-import_epost-import-obsidian-config` | Obsidian config, vault, plugins, LiveSync settings + E2E passphrase, Local REST API key | **No** — redo the one-time setup (step 1) on the NAS. The vault re-syncs from CouchDB anyway. |
| `obsidian-epost-import_epost-import-bridge-config` | Bridge's session, GPG key + pass secret store | **Recommended but not required.** If you don't move it, you'll need to redo the one-time login (step 3a, with 2FA) on the NAS — the mail account itself is unaffected. |
| `obsidian-epost-import_epost-import-importer-state` | `state.sqlite3` — which UIDs/Message-IDs have already been imported | **Optional.** If you don't move it, the importer does a one-time re-scan of the whole label on first run on the NAS. No duplicates are created (deterministic filenames, files are never overwritten) — just extra "already exists" log lines. |

### Moving / backing up a named volume between machines

The example moves the tracking volume. Swap the volume name to also move
`obsidian-config`.

**1. Stop the stack** (so SQLite isn't being written mid-copy / the WAL stays
consistent):

```bash
docker compose stop
```

**2. Export to a tar file** (run in the repo directory on the current
machine):

```bash
# Linux/macOS or Git Bash on Windows:
docker run --rm \
  -v obsidian-epost-import_epost-import-importer-state:/from:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/importer-state.tgz -C /from .
```

```powershell
# PowerShell on Windows (same thing, different pwd syntax):
docker run --rm `
  -v obsidian-epost-import_epost-import-importer-state:/from:ro `
  -v "${PWD}:/backup" `
  alpine tar czf /backup/importer-state.tgz -C /from .
```

**3. Copy `importer-state.tgz`** to the NAS (scp/SMB/USB).

**4. Import on the NAS** — create the volumes first, then restore:

```bash
# Creates the named volumes without starting the services:
docker compose create

docker run --rm \
  -v obsidian-epost-import_epost-import-importer-state:/to \
  -v "$PWD":/backup:ro \
  alpine sh -c "cd /to && tar xzf /backup/importer-state.tgz"

docker compose up -d
```

> Alternative to tar: `docker run --rm -v <volume>:/from -v <target>:/to alpine cp -a /from/. /to/`.
> The tar approach gives you a single file that's easier to move between
> machines and preserves permissions/timestamps.

### Clean start on the NAS (without moving anything)

With prebuilt images (see "Run without a dev environment"):

```bash
mkdir obsidian-epost-import && cd obsidian-epost-import
curl -fsSLO https://raw.githubusercontent.com/dvalfrid/obsidian-epost-import/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/dvalfrid/obsidian-epost-import/main/.env.example
cp .env.example .env   # fill in, adjust PUID/PGID
docker compose pull
docker compose up -d obsidian   # redo step 1 (one-time setup)
# put OBSIDIAN_API_KEY in .env, close the web UI port (step 2)
docker compose run --rm -it bridge init   # redo step 3a (one-time login)
docker compose up -d
```

...or from source: `git clone` instead of the two `curl` lines, and
`docker compose up -d --build` at the end.

---

## License

This project's own code is [MIT-licensed](LICENSE).

Third-party components keep their own licenses and aren't relicensed by
being used here:

- **Proton Mail Bridge** (built into the `bridge` image) is
  [GPLv3](https://github.com/ProtonMail/proton-bridge) — see
  "About the `bridge` container" above for how this repo builds and
  verifies it.
- **Obsidian** (bundled in the `obsidian` image via the LinuxServer.io base)
  is proprietary freeware; see [Obsidian's own terms](https://obsidian.md/license).
- The **obsidian-local-rest-api** and **Self-hosted LiveSync** plugins, and
  the Python dependencies in `mail-importer/requirements.txt`, are all
  separately open source under their own permissive/GPL-compatible licenses.

See [SECURITY.md](SECURITY.md) for the security policy and
[CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

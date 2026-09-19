# CLAUDE.md — Context for the AI assistant

## What this project does

A self-contained service that fetches email from a Proton Mail label (via a
self-built, containerized Proton Mail Bridge / IMAP) and creates Markdown
notes + attachments in the Obsidian vault `Daniel`, through a self-built
headless Obsidian container with the Local REST API plugin. The whole chain
runs in this repo's own docker-compose stack — no dependency on an always-on
external computer.

## Isolation — the most important thing

- **Its own** repo, **its own** docker-compose project
  (`name: obsidian-epost-import`).
- Shares **nothing** (network/volume/dependency) with `obsidian-nas-sync`
  (reference only — never modify anything there).
- The `obsidian` container here connects to CouchDB as **a regular client
  device would**: via `https://obsidian.valfridsson.se` (Cloudflare Tunnel),
  LiveSync plugin against the `vault-daniel` database. **No** internal
  Docker network to that other stack's `couchdb` container.

## Architecture

```
bridge (own image) ──IMAP:143──▶ mail-importer (Python) ──https──▶ obsidian:27124 (Local REST API)
  (Proton account)                     │                                    │
                              /data/state.sqlite3                   LiveSync ─▶ CouchDB (public URL)
                              (own volume, not in the vault)
```

Four services in `docker-compose.yml`:

1. `obsidian` — built from `./obsidian/Dockerfile`:
   `FROM lscr.io/linuxserver/obsidian:${OBSIDIAN_BASE_TAG}` + one init script.
   - The LSIO image maintains Obsidian + the Selkies desktop itself (web UI
     on 3001, HTTPS). We only add
     `obsidian/custom-cont-init.d/50-install-local-rest-api`, which
     preinstalls `obsidian-local-rest-api` into the vault at startup.
   - The script is baked in (COPY, root-owned) rather than bind-mounted —
     LSIO only runs `/custom-cont-init.d` scripts owned by root.
   - The web UI (3001) is only published on `127.0.0.1`, commented out,
     one-time setup only. The Local REST API (27124, HTTPS, self-signed) is
     `expose:`-only.
   - Single volume: `epost-import-obsidian-config:/config` (vault +
     `.obsidian` + plugins + LiveSync config + the REST API key).
   - `shm_size: 1gb` is required by Electron/Chromium.
2. `bridge` — **own** image (`./bridge/Dockerfile`), not a prebuilt one from
   Docker Hub. No official image exists, and the community alternatives we
   evaluated (e.g. `shenxn/protonmail-bridge`) had stopped publishing to
   Docker Hub despite upstream still shipping new releases — their build
   pipeline had silently broken.
   - Downloads Proton's **official** `.deb` from
     `github.com/ProtonMail/proton-bridge/releases` and **verifies the
     OpenPGP signature** against a pinned fingerprint (`bridge/Dockerfile`,
     `ARG BRIDGE_PUBKEY_FINGERPRINT`) — the build fails otherwise.
   - `pass` (GNU) + a headless-generated GPG key as the local secret store
     (Bridge requires `secret-service`-over-dbus or `pass` on Linux; no dbus
     here). See `bridge/gpg-batch-params` + `bridge/entrypoint.sh`.
   - `socat` proxies Bridge's hardcoded `127.0.0.1` binding (IMAP `1143`,
     SMTP `1025`, Bridge's own internal defaults) out to `143`/`25` on the
     container's interface. **The port numbers must differ** — `socat`'s
     "all interfaces" listener (`0.0.0.0:PORT`) otherwise collides with
     Bridge's `127.0.0.1:PORT` for the SAME port number ("address already in
     use").
   - Two entrypoint modes: `init` (interactive,
     `docker compose run --rm -it bridge init` → `login`/`info`/`exit`) and
     daemon (default `CMD`, requires the secret store to already exist —
     **refuses to start otherwise** instead of silently degrading to an
     unencrypted store like the reference images did).
   - Volume: `epost-import-bridge-config:/root` (session + GPG key + pass).
3. `mail-importer` — `./mail-importer/Dockerfile`, runs
   `python -m mailimporter`. Talks to `bridge:143` (IMAP) and
   `https://obsidian:27124` (REST API) over the internal `epost-import-net`
   network. `depends_on: obsidian (service_healthy), bridge (service_started)`.
   The importer has its own `_wait_for_obsidian()` retry regardless of
   startup order.
4. `autoheal` (`willfarrell/autoheal`) — restarts `obsidian`/`bridge`/
   `mail-importer` if Docker reports them `unhealthy` (hung but not crashed;
   `restart: unless-stopped` only reacts to an actual exit). Requires
   `/var/run/docker.sock` mounted — a deliberate security trade-off, see the
   comment in `docker-compose.yml` and README "Robustness & self-healing".
   Filters on `labels: [autoheal=true]` on the other three services.

Resource limits via `mem_limit`/`cpus` (obsidian 1g/1.0, bridge 512m/0.5,
importer 512m/0.75, autoheal 64m/0.1).

## One-time setup (cannot be automated away)

**Obsidian** — in the web UI (see README Step 1):
1. Open the vault `/config/<OBSIDIAN_VAULT_NAME>` (the init script already
   placed the plugin files there).
2. Turn on "Community plugins" (Restricted mode → off) + enable Local REST
   API.
3. Configure LiveSync (URI/user/pass/db + E2E passphrase).
4. Copy the Local REST API key → `.env` as `OBSIDIAN_API_KEY`.
5. Set the plugin's "Binding Host" to empty/`0.0.0.0` (default `127.0.0.1`,
   NOT reachable from other containers) so the importer can reach port 27124.

**Proton Bridge** — interactive, requires a real password + possibly 2FA
(README Step 3), can never be automated / run by an AI assistant:
```
docker compose run --rm -it bridge init
```
`login` → `info` (Bridge password → `.env` as `IMAP_PASS`) → `exit`. Then run
`docker compose up -d bridge` (daemon mode). The session is persisted in the
volume — no new login is needed after that, not even after a NAS reboot.

## The Python package (`mail-importer/mailimporter/`)

| Module | Responsibility |
|---|---|
| `config.py` | Reads all env vars → `Config` (frozen dataclass) |
| `app.py` | `Runner`: main loop, IMAP IDLE + poll, signal handling, backoff, heartbeat |
| `imap_source.py` | IMAPClient wrapper. Read-only select, `BODY.PEEK[]`, IDLE, `discover_labels()` (searches `Labels/*` for the same Message-ID). `NETWORK_ERRORS` |
| `emailmsg.py` | `parse_email()` → `ParsedEmail` (+ `Attachment`). HTML→MD via markdownify. `_is_layout_table()`/`_unwrap_layout_tables()` unwrap layout tables |
| `note_builder.py` | Filename, frontmatter, note content, `cid:` + remote-URL rewriting |
| `obsidian_api.py` | `ObsidianClient`: create-only `PUT` (existence check first), retries on network/5xx |
| `remote_fetch.py` | Best-effort download of remote `http(s)` images/documents linked in email bodies, SSRF-guarded |
| `processor.py` | `Processor.process()`: label discovery → attachments → remote resources → note → `mark_imported()` |
| `state.py` | SQLite: `imported(uidvalidity,uid,message_id,note_path,imported_at)` + `mailbox_meta` |
| `healthcheck.py` | Docker HEALTHCHECK — checks the heartbeat file's age |
| `__main__.py` | Dispatch: `run` (default), `list-folders`, `healthcheck` |

## Invariants — don't change without careful thought

- The `\Seen` flag is **never** touched — read-only select + `BODY.PEEK[]`.
- Tracking is keyed on `(uidvalidity, uid)` + a Message-ID fallback, **not**
  `\Seen`.
- The SQLite file lives in its own volume, **never** in the vault.
- Files are **only ever created** — `ObsidianClient.create_file()` does an
  `exists()` check before every `PUT`.
- Deterministic filename: `{YYYY-MM-DD}-{slug}-{sha1(message_id)[:10]}.md`.
- `mark_imported()` is the "done" marker and the last step (crash-safe).
- Attachments are uploaded **before** the note.
- The Local REST API port is never published to the host; the web UI (3001)
  is `127.0.0.1`-only.
- No cron — a long-running process with graceful `SIGTERM` shutdown.
- The obsidian container = LSIO image + a thin init layer. No Obsidian/VNC
  logic of our own. `OBSIDIAN_BASE_TAG` is always pinned; upgrade
  deliberately.
- The `obsidian` init script must chown **both** `OBS_DIR` (recursively, the
  plugin directory) **and** `VAULT_DIR` itself (non-recursively) — root's
  `mkdir -p` leaves the vault root root-owned otherwise, and Obsidian can't
  open it ("no permission to access folder").
- The bridge container = own image, built from Proton's official `.deb` +
  GPG signature verification. `BRIDGE_VERSION` is always pinned. socat's
  ports (143/25) and Bridge's internal ports (1143/1025) must use DIFFERENT
  numbers.
- `MAILBOX` in practice is almost always `Labels/<name>`, not just `<name>`
  — Proton labels show up as their own folders in Bridge. `list-folders`
  reveals the exact name.
- **Frontmatter `labels`** = all Proton labels the message actually has
  (discovered via `discover_labels()`, searching `Labels/*` by Message-ID) +
  `NOTE_LABELS` as extra static tags. No longer just `NOTE_LABELS`.
- **HTML tables:** a `<table>` counts as "real data" (becomes a Markdown
  pipe table) only if it has `<th>` and isn't `role="presentation"`.
  Everything else (in practice, most email templates' layout tables) is
  unwrapped into plain paragraphs. Cell content that already contains block
  elements (an already-unwrapped nested table) must NEVER be wrapped in
  `<p>` (invalid HTML — `<p>` can't contain `<div>`/`<table>`, and gets
  reinterpreted unpredictably by markdownify if it does). Two heuristics that
  were tried and are known-broken, don't reintroduce them: "single cell per
  row = layout" (misses wide layout tables with no header) and wrapping
  every cell in `<p>` unconditionally (breaks on nested tables, see above).
- **Remote resources (images/documents linked from email bodies):**
  best-effort downloaded into the vault as normal attachments (`remote_fetch.py`,
  keyed by `sha1(url)` so the same resource across emails dedupes for free)
  so they survive if the sender's server later disappears. The original
  remote URL is always kept — as the local embed's alt text
  (`![[path|url]]`) on success, or as the untouched original Markdown link
  on any failure (blocked host, timeout, oversized, bad status) — never as
  an error path that blocks the rest of the import. `_is_public_host()`
  rejects private/loopback/link-local/reserved resolved IPs before
  requesting — this container can reach `obsidian:27124` internally, and
  the URL comes from externally-received, attacker-influenceable email
  content, so this is a real SSRF guard, not defensive boilerplate. Don't
  follow redirects (`allow_redirects=False`) — a redirect is treated as a
  failure rather than re-validated per hop.
- The init script (obsidian) and the entrypoint (bridge) must be idempotent.
  The bridge entrypoint should refuse to start with a clear error rather
  than silently degrade (e.g. an unencrypted secret store).
- **Deploying a code change to a running service requires `docker compose up
  -d [--build] <service>`, never just `restart`.** `restart` only restarts
  the same container on its already-existing image; it never picks up a
  freshly built one. If unsure whether a container is running the current
  image: `docker inspect <container> --format '{{.Image}}'` should equal
  `docker image inspect <tag> --format '{{.Id}}'`.
- **Portability:** `docker-compose.yml` must not contain host paths,
  hardcoded UIDs, or Windows/NAS assumptions — everything environment-
  specific goes through `.env`. **Only named volumes, never bind mounts**
  (WSL2 bind mounts are slow and conflict with SQLite locks; named volumes
  behave the same on Windows and the NAS). See README "Portability" for
  moving volumes between machines. (`/var/run/docker.sock` in `autoheal` is
  an intentional exception — that path is identical on Docker Desktop and
  Linux, so it doesn't break the principle.)
- **Robustness:** `restart: unless-stopped` + `autoheal` + the internal
  retry loops together should bring the whole stack back up on its own after
  a NAS power outage, with no manual steps — the same standard as
  `obsidian-nas-sync`. `depends_on`/healthcheck conditions only govern
  `docker compose up`, not dockerd's own restart-on-boot; never rely on
  startup order there — rely on each service waiting for its own
  dependencies (already implemented). Bridge's sync is resumable — an
  interruption mid-sync loses nothing.

## Release & CI (GHCR)

- Three published images:
  `ghcr.io/dvalfrid/obsidian-epost-import/{obsidian,bridge,mail-importer}`.
  `docker-compose.yml` has both `image:` (prebuilt, `docker compose pull`)
  and `build:` (from source, `docker compose build`) on all three — the same
  file works both ways (see README "Run without a dev environment").
- `.github/workflows/ci.yml`: `verify` (syntax/config checks) → `images`
  (matrix build of all three, pushes to GHCR after `verify` passes).
  Tagging: `:main`/`:sha-<short>` on push to main, `:X.Y.Z`/`:X.Y`/`:X`/`:latest`
  on `vX.Y.Z` tags, nothing pushed on PRs. Builds `linux/amd64` only.
- `.github/workflows/release-please.yml` + `release-please-config.json`
  (`release-type: "simple"`, one shared version number for all three images)
  handles version bumps + `CHANGELOG.md` from Conventional Commits
  (`feat:`/`fix:`/`perf:` show up in the changelog). Commit with Conventional
  Commit prefixes going forward for this to keep working.
- Proton Bridge is GPLv3 — redistributing built binaries/images is
  explicitly permitted (source already public via Proton). OCI labels
  (`org.opencontainers.image.source`/`.licenses`) are set in
  `bridge/Dockerfile` for traceability.
- The repo and its GHCR packages are **public** (a deliberate choice — the
  git history was scanned for leaked secrets before making it public).
- GitHub repo setting "Allow GitHub Actions to create and approve pull
  requests" must be enabled for `release-please` to open its release PRs
  (`gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true`).
  Release PRs must be reviewed and merged by a human, never auto-merged.

## Reference values (from `obsidian-nas-sync` — read-only, never change there)

- LiveSync URI: `https://obsidian.valfridsson.se`
- Database / user for this vault: `vault-daniel` / `daniel`
- The E2E passphrase must match Daniel's other devices.

## Testing locally (Python side only)

```bash
cd mail-importer
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
PYTHONPATH=. .venv/Scripts/python -m mailimporter list-folders   # needs real .env values in the environment
```

Unit tests (`mail-importer/tests/`, pytest, run in CI): `.venv/Scripts/python
-m pytest -q` from `mail-importer/` (`pytest.ini` sets `pythonpath = .` so
`mailimporter` resolves without exporting `PYTHONPATH` manually). Covers
`emailmsg.py`/`note_builder.py`/`remote_fetch.py` — no real IMAP/Obsidian
server needed.

Adding a fixture from a real email: use the `/add-email-fixture
<path-to-.eml>` command (`.claude/commands/add-email-fixture.md`) — it
anonymizes a real exported `.eml` (this repo is public), drops it in
`mail-importer/tests/fixtures/`, and writes a dedicated test with
assertions derived from the actual parser output. Don't hand-write
fixtures/assertions for real emails outside that flow — the anonymization
steps there are load-bearing.

Quick regression test of the HTML→Markdown handling (tables, labels) without
a real IMAP server: call `parse_email()` directly on a hand-built `.eml`
(build a multipart/mixed message with `email.message.EmailMessage`) — see
`tests/test_integration_remote_resources.py` for the pattern.

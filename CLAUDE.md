# CLAUDE.md — Kontext för AI-assistenten

## Vad projektet gör

Fristående tjänst som hämtar epost från en Proton Mail-label (via Proton Mail
Bridge / IMAP) och skapar Markdown-anteckningar + bilagor i Obsidian-valvet
`Daniel`, genom en egen headless Obsidian-container med Local REST API-pluginet.

## Isolering — viktigast av allt

- **Eget** repo, **eget** docker-compose-projekt (`name: obsidian-epost-import`).
- Delar **inget** nätverk/volym/beroende med `obsidian-nas-sync`
  (`C:\Users\danie\Documents\dev\obsidian-nas-sync` — endast referens, ändra inget där).
- `obsidian`-containern här ansluter till CouchDB som **en vanlig klientenhet**:
  via `https://obsidian.valfridsson.se` (Cloudflare Tunnel), LiveSync-plugin mot
  databasen `vault-daniel`. **Inget** internt Docker-nätverk mot den andra stackens
  `couchdb`-container.

## Arkitektur

```
Proton Bridge (IMAP) ──▶ mail-importer (Python) ──https──▶ obsidian:27124 (Local REST API)
                              │                                    │
                     /data/state.sqlite3                   LiveSync ─▶ CouchDB (publik URL)
                     (egen volym, ej i valvet)
```

Två tjänster i `docker-compose.yml`:

1. `obsidian` — byggs från `./obsidian/Dockerfile`:
   `FROM lscr.io/linuxserver/obsidian:${OBSIDIAN_BASE_TAG}` + ett init-skript.
   - LSIO-imagen underhåller själv Obsidian + Selkies-desktop (webb-UI på 3001,
     HTTPS). Vi lägger bara till `obsidian/custom-cont-init.d/50-install-local-rest-api`
     som förinstallerar `obsidian-local-rest-api` i valvet vid start.
   - Skriptet bakas in (COPY, root-ägt) i stället för bind-mount — LSIO kör bara
     `/custom-cont-init.d`-skript som ägs av root.
   - Webb-UI (3001) publiceras bara på `127.0.0.1`, bortkommenterat, endast för
     engångskonfig. Local REST API (27124, HTTPS, självsignerat) är bara `expose:`.
   - En enda volym: `epost-import-obsidian-config:/config` (valv + `.obsidian` +
     plugins + LiveSync-config + REST API-nyckeln).
   - `shm_size: 1gb` krävs av Electron/Chromium.
2. `mail-importer` — `./mail-importer/Dockerfile`, kör `python -m mailimporter`.
   Pratar med `https://obsidian:27124` via interna nätet `epost-import-net`.
   `depends_on: obsidian (service_healthy)`; healthchecken curl:ar 27124. Vid
   allra första setupen är obsidian "unhealthy" tills GUI-stegen är gjorda —
   det är meningen. Importern har dessutom egen `_wait_for_obsidian()`-retry.

Resursgränser via `mem_limit`/`cpus` (obsidian 1g/1.0, importer 512m/0.75).

## Engångskonfiguration (kan inte automatiseras bort)

Måste göras i webb-UI:t en gång (se README steg 1):
1. Öppna valvet `/config/<OBSIDIAN_VAULT_NAME>` (init-skriptet la plugin-filerna där).
2. Slå på "Community plugins" (Restricted mode → av) + aktivera Local REST API.
3. Konfigurera LiveSync (URI/user/pass/db + E2E-passphrase).
4. Kopiera Local REST API-nyckeln → `.env` som `OBSIDIAN_API_KEY`.
5. Sätt pluginets "Binding Host" till tomt/`0.0.0.0` så importern når 27124.

## Python-paketet (`mail-importer/mailimporter/`)

| Modul | Ansvar |
|---|---|
| `config.py` | Läser alla env-vars → `Config` (frozen dataclass) |
| `app.py` | `Runner`: huvudloop, IMAP IDLE + poll, signalhantering, backoff, heartbeat |
| `imap_source.py` | IMAPClient-wrapper. Read-only select, `BODY.PEEK[]`, IDLE. `NETWORK_ERRORS` |
| `emailmsg.py` | `parse_email()` → `ParsedEmail` (+ `Attachment`). HTML→MD via markdownify |
| `note_builder.py` | Filnamn, frontmatter, notinnehåll, `cid:`-omskrivning |
| `obsidian_api.py` | `ObsidianClient`: create-only `PUT` (existenskontroll först), retry på nät/5xx |
| `processor.py` | `Processor.process()`: bilagor → not → `mark_imported()` |
| `state.py` | SQLite: `imported(uidvalidity,uid,message_id,note_path,imported_at)` + `mailbox_meta` |
| `healthcheck.py` | Docker HEALTHCHECK — kollar heartbeat-filens ålder |
| `__main__.py` | Dispatch: `run` (default), `list-folders`, `healthcheck` |

## Invarianter som inte ändras utan eftertanke

- `\Seen`-flaggan rörs **aldrig** — read-only select + `BODY.PEEK[]`.
- Tracking sker på `(uidvalidity, uid)` + Message-ID-fallback, **inte** `\Seen`.
- SQLite-filen ligger i egen volym, **aldrig** i valvet.
- Filer **skapas bara** — `ObsidianClient.create_file()` gör `exists()` före `PUT`.
- Filnamn deterministiskt: `{YYYY-MM-DD}-{slug}-{sha1(message_id)[:10]}.md`.
- `mark_imported()` är "klart"-markeringen och sista steget (krasch-säkert).
- Bilagor laddas upp **före** anteckningen.
- Local REST API-porten publiceras aldrig mot host; webb-UI (3001) bara på `127.0.0.1`.
- Ingen cron — långlivad process med graceful `SIGTERM`-shutdown.
- obsidian-containern = LSIO-image + tunt init-lager. Ingen egen Obsidian/VNC-logik.
  `OBSIDIAN_BASE_TAG` pinnas alltid; uppgradera medvetet.
- Init-skriptet ska vara idempotent och får **aldrig** fälla containern.
- **Portabilitet:** `docker-compose.yml` får inte innehålla host-sökvägar,
  hårdkodade uid:n eller Windows/NAS-antaganden — allt miljöspecifikt via `.env`.
  **Bara named volumes, aldrig bind mounts** (WSL2-bind-mounts är långsamma och
  trasslar med SQLite-locks; named volumes beter sig lika på Windows och NAS).
  Se README "Portabilitet" för volym-flytt mellan maskiner.

## Referensvärden (från obsidian-nas-sync, får läsas men inte ändras där)

- LiveSync-URI: `https://obsidian.valfridsson.se`
- Databas / användare för detta valv: `vault-daniel` / `daniel`
- E2E-passphrase måste vara samma som på Daniels övriga enheter.

## Testa lokalt (bara Python-delen)

```bash
cd mail-importer
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
PYTHONPATH=. .venv/Scripts/python -m mailimporter list-folders   # kräver .env-värden i miljön
```

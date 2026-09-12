# CLAUDE.md — Kontext för AI-assistenten

## Vad projektet gör

Fristående tjänst som hämtar epost från en Proton Mail-label (via en egen,
containeriserad Proton Mail Bridge / IMAP) och skapar Markdown-anteckningar +
bilagor i Obsidian-valvet `Daniel`, genom en egen headless Obsidian-container
med Local REST API-pluginet. Hela kedjan körs i den här repots egna
docker-compose-stack — inget beroende av en alltid-påslagen extern dator.

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
bridge (egen image) ──IMAP:143──▶ mail-importer (Python) ──https──▶ obsidian:27124 (Local REST API)
  (Proton-konto)                        │                                    │
                               /data/state.sqlite3                   LiveSync ─▶ CouchDB (publik URL)
                               (egen volym, ej i valvet)
```

Fyra tjänster i `docker-compose.yml`:

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
2. `bridge` — **egen** image (`./bridge/Dockerfile`), inte en färdig från
   Docker Hub. De undersökta community-imagerna (t.ex. `shenxn/protonmail-bridge`)
   hade slutat publiceras till Docker Hub ~17 månader innan detta skrevs trots
   att källkoden fortsatte bumpa version — byggpipelinen hade gått sönder tyst.
   - Hämtar Protons **officiella** `.deb` från
     `github.com/ProtonMail/proton-bridge/releases` och **verifierar
     OpenPGP-signaturen** mot en pinnad fingerprint (`bridge/Dockerfile`,
     `ARG BRIDGE_PUBKEY_FINGERPRINT`) — bygget fallerar annars.
   - `pass` (GNU) + headless-genererad GPG-nyckel som lokalt lösenordslager
     (Bridge kräver `secret-service`-dbus eller `pass` på Linux; ingen dbus
     här). Se `bridge/gpg-batch-params` + `bridge/entrypoint.sh`.
   - `socat` proxar Bridges hårdkodade `127.0.0.1`-bindning (IMAP `1143`,
     SMTP `1025`, Bridges egna interna standardportar) ut till `143`/`25` på
     containerns interface. **Portnumren måste skilja sig** — `socat`s
     "alla interface"-lyssning (`0.0.0.0:PORT`) kolliderar annars med Bridges
     `127.0.0.1:PORT` för SAMMA portnummer ("address already in use").
   - Två lägen i entrypointen: `init` (interaktivt, `docker compose run --rm -it
     bridge init` → `login`/`info`/`exit`) och daemon (default `CMD`, kräver
     att lösenordslagret redan finns — **vägrar starta annars** i stället för
     att som referensimagen tyst degradera till okrypterat).
   - Volym: `epost-import-bridge-config:/root` (session + GPG-nyckel + pass).
3. `mail-importer` — `./mail-importer/Dockerfile`, kör `python -m mailimporter`.
   Pratar med `bridge:143` (IMAP) och `https://obsidian:27124` (REST API) via
   interna nätet `epost-import-net`.
   `depends_on: obsidian (service_healthy), bridge (service_started)`.
   Importern har egen `_wait_for_obsidian()`-retry oavsett startordning.
4. `autoheal` (`willfarrell/autoheal`) — startar om `obsidian`/`bridge`/
   `mail-importer` om Docker rapporterar dem `unhealthy` (hängd men inte
   kraschad process; `restart: unless-stopped` reagerar bara på faktisk exit).
   Kräver `/var/run/docker.sock` inmonterad — medveten säkerhetsavvägning, se
   kommentaren i `docker-compose.yml` och README "Robusthet & självläkning".
   Filtrerar på `labels: [autoheal=true]` på de tre andra tjänsterna.

Resursgränser via `mem_limit`/`cpus` (obsidian 1g/1.0, bridge 512m/0.5,
importer 512m/0.75, autoheal 64m/0.1).

## Engångskonfiguration (kan inte automatiseras bort)

**Obsidian** — i webb-UI:t (se README steg 1):
1. Öppna valvet `/config/<OBSIDIAN_VAULT_NAME>` (init-skriptet la plugin-filerna där).
2. Slå på "Community plugins" (Restricted mode → av) + aktivera Local REST API.
3. Konfigurera LiveSync (URI/user/pass/db + E2E-passphrase).
4. Kopiera Local REST API-nyckeln → `.env` som `OBSIDIAN_API_KEY`.
5. Sätt pluginets "Binding Host" till tomt/`0.0.0.0` (default `127.0.0.1`,
   INTE nåbar från andra containrar) så importern når 27124.

**Proton Bridge** — interaktivt, kräver riktigt lösenord + ev. 2FA (README
steg 3), kan aldrig automatiseras/köras av en AI-assistent:
```
docker compose run --rm -it bridge init
```
`login` → `info` (Bridge-lösenordet → `.env` som `IMAP_PASS`) → `exit`.
Kör sedan `docker compose up -d bridge` (daemon-läge). Sessionen persisteras
i volymen — ingen ny inloggning behövs efter det, inte ens efter NAS-reboot.

## Python-paketet (`mail-importer/mailimporter/`)

| Modul | Ansvar |
|---|---|
| `config.py` | Läser alla env-vars → `Config` (frozen dataclass) |
| `app.py` | `Runner`: huvudloop, IMAP IDLE + poll, signalhantering, backoff, heartbeat |
| `imap_source.py` | IMAPClient-wrapper. Read-only select, `BODY.PEEK[]`, IDLE, `discover_labels()` (söker `Labels/*` efter samma Message-ID). `NETWORK_ERRORS` |
| `emailmsg.py` | `parse_email()` → `ParsedEmail` (+ `Attachment`). HTML→MD via markdownify. `_is_layout_table()`/`_unwrap_layout_tables()` packar upp layout-tabeller |
| `note_builder.py` | Filnamn, frontmatter, notinnehåll, `cid:`-omskrivning |
| `obsidian_api.py` | `ObsidianClient`: create-only `PUT` (existenskontroll först), retry på nät/5xx |
| `processor.py` | `Processor.process()`: labelupptäckt → bilagor → not → `mark_imported()` |
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
- bridge-containern = egen image, byggd från Protons officiella `.deb` +
  GPG-signaturverifiering. `BRIDGE_VERSION` pinnas alltid. socat-portarna
  (143/25) och Bridges interna portar (1143/1025) måste ha OLIKA nummer.
- MAILBOX i praktiken nästan alltid `Labels/<namn>`, inte bara `<namn>` —
  Proton-labels dyker upp som egna mappar i Bridge. `list-folders` avslöjar
  exakt namn.
- **Frontmatterns `labels`** = alla Proton-labels meddelandet faktiskt har
  (upptäckta via `discover_labels()`, sök över `Labels/*` på Message-ID) +
  `NOTE_LABELS` som extra statiska taggar. Inte längre bara `NOTE_LABELS`.
- **HTML-tabeller:** en `<table>` är bara "riktig data" (blir Markdown-
  pipe-tabell) om den har `<th>` och inte `role="presentation"`. Annat
  (i praktiken de flesta e-postmallars layout-tabeller) packas upp till
  vanliga stycken. Cellinnehåll som redan har block-element (en tidigare
  uppackad nästlad tabell) får ALDRIG wrappas i `<p>` (ogiltig HTML,
  `<p>` får inte innehålla `<div>`/`<table>` — tolkas om oförutsägbart).
- Init-skriptet (obsidian) och entrypointen (bridge) ska vara idempotenta.
  bridge-entrypointen ska HELLRE vägra starta med ett tydligt fel än att
  tyst degradera (t.ex. okrypterat lösenordslager).
- **Portabilitet:** `docker-compose.yml` får inte innehålla host-sökvägar,
  hårdkodade uid:n eller Windows/NAS-antaganden — allt miljöspecifikt via `.env`.
  **Bara named volumes, aldrig bind mounts** (WSL2-bind-mounts är långsamma och
  trasslar med SQLite-locks; named volumes beter sig lika på Windows och NAS).
  Se README "Portabilitet" för volym-flytt mellan maskiner.
  (`/var/run/docker.sock` i `autoheal` är undantaget — den sökvägen är
  identisk på Docker Desktop och Linux, så den bryter inte principen.)
- **Robusthet:** `restart: unless-stopped` + `autoheal` + interna retry-loopar
  ska tillsammans göra att hela stacken kommer igång själv efter ett
  NAS-strömavbrott, utan manuella steg — samma standard som `obsidian-nas-sync`.
  `depends_on`/healthcheck-villkor styr bara `docker compose up`, inte dockerds
  egen omstart-vid-boot; lita aldrig på startordning där, lita på att varje
  tjänst själv väntar in sina beroenden (redan implementerat). Bridges synk är
  resumable — ett avbrott mitt i förlorar inget.

## Lärdomar från verklig testning (bugfixar, i kronologisk ordning)

Allt nedan hittades genom att faktiskt köra stacken lokalt mot ett riktigt
Proton-konto, inte genom kodgranskning. Nämns här så de inte återupptäcks:

1. **`custom-cont-init.d`-skriptet chownade bara `.obsidian`, inte
   valvroten.** `mkdir -p` som root skapade `/config/Daniel` (roten) med fel
   ägare → Obsidian ("no permission to access folder"). Fix: chowna
   `VAULT_DIR` explicit (icke-rekursivt, billigt), utöver den rekursiva
   chown av `OBS_DIR`.
2. **`socat` saknades i `bridge`-imagens paketlista** — glömdes helt enkelt
   i första versionen av `apt-get install`. Upptäcktes genom att faktiskt
   testa cross-container-anslutning, inte bara "healthy"-status.
3. **`socat`s port kolliderade med Bridges egen port** när båda försökte
   binda samma portnummer (`1143`↔`1143`) på olika interface — `0.0.0.0`
   inkluderar `127.0.0.1`. Löst genom att låta socat lyssna på ANDRA
   portnummer (143/25) än Bridges interna (1143/1025).
4. **Local REST API-pluginets "Binding Host" är `127.0.0.1` som default**,
   inte `0.0.0.0` som ursprungligen antaget — måste sättas manuellt i GUI:t
   under Advanced, annars kan `mail-importer` aldrig nå den.
5. **`MAILBOX=Obsidian` fungerade inte** — Proton-labeln syns i Bridge som
   `Labels/Obsidian`, inte bara `Obsidian`. `list-folders` avslöjar detta.
6. **`shenxn/protonmail-bridge` visade sig ha slutat publiceras** ~17 månader
   innan Docker Hub-taggarna kollades mot GitHubs commit-historik — trots att
   källkoden fortsatte bumpa version. Ledde till att vi byggde en egen image.
7. **Ett meddelandes labels syns bara i den mapp man råkar ha vald över
   IMAP** — Bridge har ingen `X-GM-LABELS`-liknande extension. Löst med
   `discover_labels()`: sök `HEADER Message-ID` över alla `Labels/*`-mappar.
8. **HTML-tabellheuristiken itererade flera steg:** först "max 1 cell per
   rad = layout" (missade EasyParks 30+ kolumners layout-tabell) → sedan
   "har `<th>` = riktig data, annat = layout" (bättre, men cellinnehåll
   wrappades i `<p>` som kunde innehålla en redan uppackad `<div>` från en
   nästlad tabell → ogiltig HTML, tolkades om oförutsägbart av markdownify)
   → till sist: `<div>` alltid som ytterwrapper, `<p>` bara när cellen INTE
   redan har block-innehåll.

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

Snabb regressionstest av HTML→Markdown-hanteringen (tabeller, labels) utan
en riktig IMAP-server: kör `parse_email()` direkt på ett handbyggt `.eml`,
se t.ex. testmönstret som användes under utveckling (bygg ett
multipart/mixed-meddelande med `email.message.EmailMessage`).

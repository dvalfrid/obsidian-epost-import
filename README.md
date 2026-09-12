# obsidian-epost-import

Hämtar epost från en **Proton Mail-label** via en **egen, containeriserad
Proton Mail Bridge** och skapar **anteckningar + bilagor** i Obsidian-valvet
**Daniel** — genom en **egen, headless Obsidian-instans i Docker**. Hela
kedjan (Bridge, Obsidian, importern) körs i det här repots egen
docker-compose-stack, oberoende av någon alltid-påslagen dator.

```
                                                              Cloudflare Tunnel
                                                                      │
                                                                      ▼
┌───────────────┐  IMAP (143)  ┌─────────────────┐  https://obsidian:27124  ┌──────────────────────────┐
│  bridge       │◀────────────│  mail-importer  │─────────────────────────▶│  obsidian (LSIO-image)   │
│  (egen image) │              │  (Python)       │      Local REST API      │  LiveSync ──▶ CouchDB     │
└───────────────┘              └─────────────────┘                          └──────────────────────────┘
        │                              │                                   (obsidian.valfridsson.se /
        ▼                              ▼                                    vault-daniel)
  Proton-konto (verkligt      /data/state.sqlite3
  IMAP, riktig inloggning)    (egen volym, EJ i valvet)
```

---

## Helt fristående från `obsidian-nas-sync`

Det här är ett **eget repo** och ett **eget docker-compose-projekt**
(`name: obsidian-epost-import`). Det delar **inget** med `obsidian-nas-sync`:

| | obsidian-nas-sync | detta projekt |
|---|---|---|
| Compose-projekt | eget | `obsidian-epost-import` |
| Nätverk | `couchdb-internal` | `epost-import-net` |
| Volymer | `couchdb-...` | `epost-import-obsidian-config`, `epost-import-bridge-config`, `epost-import-importer-state` |
| Åtkomst till CouchDB | via `cloudflared`-container internt | **som vilken klient som helst**, via `https://obsidian.valfridsson.se` |

Obsidian-containern här ansluter till CouchDB **precis som en vanlig
klientenhet** — över den publika Cloudflare-Tunnel-URL:en, med LiveSync-pluginet
konfigurerat mot `vault-daniel`. Det finns **inget** internt Docker-nätverk mot
`couchdb`-containern i det andra projektet, och **inga** ändringar behöver göras
i `obsidian-nas-sync` för att det här ska fungera.

> `C:\Users\danie\Documents\dev\obsidian-nas-sync` används bara som referens
> (URL: `https://obsidian.valfridsson.se`, databas: `vault-daniel`). Rör inget där.

---

## Om obsidian-containern

Bygger på **[`lscr.io/linuxserver/obsidian`](https://docs.linuxserver.io/images/docker-obsidian/)**
(LinuxServer.io) — en aktivt underhållen, versionstaggad image som bygger om sig
löpande för säkerhetsuppdateringar. Obsidian körs där i en **Selkies-desktop**
som strömmas till webbläsaren (HTTPS, port 3001).

`./obsidian/Dockerfile` lägger bara till **ett** tunt lager: ett init-skript
(`obsidian/custom-cont-init.d/50-install-local-rest-api`) som förinstallerar
**obsidian-local-rest-api**-pluginet i valvet vid start. Ingen egen Obsidian-,
VNC- eller sandbox-logik underhålls i det här repot.

> LSIO-imagen ger "privileged access" till en full desktop. Exponera den aldrig
> mot internet, och överväg en egress-brandvägg som bara släpper ut trafik mot
> Cloudflare (för `obsidian.valfridsson.se`).

---

## Om bridge-containern

**Egen image** (`./bridge/Dockerfile`), inte en färdig från Docker Hub. De
undersökta community-imagerna (t.ex. `shenxn/protonmail-bridge`, 694★, 1M+
pulls) visade sig ha slutat publiceras till Docker Hub ~17 månader innan
detta skrevs, trots att källkoden fortsatte bumpa version — deras
byggpipeline hade gått sönder tyst. Att pinna en sådan image hade betytt
17 månader gamla säkerhetshål i något som dekrypterar hela brevlådan, och
Proton stänger historiskt av inloggning för för gamla Bridge-versioner.

Vår egen image:

- Hämtar Protons **officiella** `.deb`-paket direkt från
  `github.com/ProtonMail/proton-bridge/releases` (samma binär som en native
  installation skulle använda).
- **Verifierar OpenPGP-signaturen** mot Protons publicerade signeringsnyckel
  (fingerprint pinnad i Dockerfilen) innan installation — bygget FALLERAR om
  den inte stämmer. Det gör shenxn:s image inte alls.
- `pass` (GNU) + en headless-genererad GPG-nyckel som lokalt lösenordslager,
  eftersom Bridge på Linux kräver `secret-service` (dbus, kräver skrivbord —
  finns inte här) eller `pass`.
- `socat` proxar Bridges hårdkodade `127.0.0.1`-bara IMAP/SMTP-portar
  (`1143`/`1025`, Bridges egna interna standardportar) ut till `143`/`25` på
  containerns interface, så att `mail-importer` kan nå dem över
  `epost-import-net`. **Portnumren MÅSTE skilja sig** — `socat`s
  "alla interface"-bindning kolliderar annars med Bridges `127.0.0.1`-bindning
  för samma portnummer.
- Vägrar starta i daemon-läge (`docker compose up bridge`) om
  engångsinloggningen (`init`) inte körts än — loggar ett tydligt fel i
  stället för att som referensimagen tyst köra vidare med ett okrypterat
  lösenordslager.

Se `bridge/entrypoint.sh` för hela logiken. Uppgradera genom att sätta en
nyare `BRIDGE_VERSION` i `.env` (se
[Proton Bridge releases](https://github.com/ProtonMail/proton-bridge/releases))
och `docker compose up -d --build bridge`.

---

## Innehåll

```
obsidian-epost-import/
├── docker-compose.yml        # obsidian + bridge + mail-importer + autoheal, eget nät/volymer/resursgränser
├── .env.example              # alla miljövariabler
├── README.md
├── CLAUDE.md                 # kontext för AI-assistenten
├── obsidian/
│   ├── Dockerfile            # FROM lscr.io/linuxserver/obsidian:<pinnad> + init-skript
│   └── custom-cont-init.d/
│       └── 50-install-local-rest-api   # förinstallerar Local REST API-pluginet
├── bridge/
│   ├── Dockerfile            # FROM debian:bookworm-slim + officiell .deb + GPG-verifiering
│   ├── entrypoint.sh         # init/daemon-lägen, pass/GPG-lösenordslager, socat-proxy
│   └── gpg-batch-params      # headless GPG-nyckelgenerering åt pass
└── mail-importer/
    ├── Dockerfile
    ├── requirements.txt
    └── mailimporter/         # Python-paketet (kör: python -m mailimporter)
```

---

## Snabbstart

```bash
git clone <detta-repo> obsidian-epost-import
cd obsidian-epost-import
cp .env.example .env
# Redigera .env — minst IMAP_USER, OBSIDIAN_WEB_PASSWORD

# 1. Öppna webb-UI-porten tillfälligt (steg 1a), starta bara obsidian:
docker compose up -d --build obsidian

# 2. Konfigurera LiveSync + hämta Local REST API-nyckeln via webb-UI (steg 1).
#    Lägg nyckeln i .env som OBSIDIAN_API_KEY.

# 3. Stäng webb-UI-porten igen (steg 2).

# 4. Engångsinloggning mot Proton (steg 3, INTERAKTIVT — kör i egen terminal):
docker compose build bridge
docker compose run --rm -it bridge init
#   -> login (mejladress, lösenord, ev. 2FA)
#   -> info  (Bridge-lösenordet -> .env som IMAP_PASS)
#   -> exit

# 5. Hitta exakt label-namn och starta allt:
docker compose up -d bridge
docker compose run --rm mail-importer list-folders   # leta upp t.ex. "Labels/Obsidian"
#   sätt MAILBOX i .env till det du hittade
docker compose up -d --build
docker compose logs -f mail-importer
```

---

## Steg 1 — Engångskonfiguration av `obsidian`-containern

Den headless Obsidian-instansen måste konfigureras **en gång**: öppna valvet,
aktivera community-plugins, logga in LiveSync mot CouchDB och plocka ut
Local REST API-nyckeln.

### 1a. Öppna webb-UI-porten tillfälligt

I `docker-compose.yml`, under tjänsten `obsidian`, **avkommentera**:

```yaml
    ports:
      - "127.0.0.1:3001:3001"
```

Bindningen till `127.0.0.1` gör att porten bara går att nå från själva NAS:en.
Bygg och starta:

```bash
docker compose up -d --build obsidian
```

### 1b. Öppna webb-UI:t

Om du sitter vid NAS:en: gå till `https://127.0.0.1:3001` (acceptera det
självsignerade certet).
Om du sitter vid en annan dator — tunnla porten via SSH först:

```bash
ssh -L 3001:127.0.0.1:3001 <användare>@<nas-ip>
# öppna sedan https://127.0.0.1:3001 i din egen webbläsare
```

Inloggning: `OBSIDIAN_WEB_USER` / `OBSIDIAN_WEB_PASSWORD` från `.env`.

### 1c. Öppna valvet och slå på community-plugins

1. I Obsidian: **Open folder as vault** →
   `/config/Daniel` (måste heta exakt `OBSIDIAN_VAULT_NAME` från `.env`).
   Init-skriptet har redan lagt Local REST API-pluginets filer där.
2. **Settings → Community plugins** → om det står "Restricted mode": klicka
   **Turn on community plugins**.
3. Under **Installed plugins** ska nu **Local REST API** synas — se till att den
   är **aktiverad** (växeln på). Är listan tom kördes inte init-skriptet (ingen
   internet vid start?) — installera pluginet via **Browse** i stället.

### 1d. Konfigurera Self-hosted LiveSync

1. **Settings → Community plugins → Browse** → sök **Self-hosted LiveSync** →
   installera + aktivera (om den inte redan finns).
2. **LiveSync-inställningar → Setup → "Open setup wizard" → "Set up manually"**.
3. Fyll i (samma som en vanlig enhet skulle använda):

   | Fält | Värde |
   |---|---|
   | URI | `https://obsidian.valfridsson.se` |
   | Username | `daniel` |
   | Password | Daniels CouchDB-lösenord |
   | Database | `vault-daniel` |

4. **Test** → grönt. **Next**.
5. Sync-läge: **LiveSync**.
6. Aktivera **End-to-end encryption** och ange **samma passphrase** som på dina
   övriga enheter (annars kan containern inte läsa dina krypterade anteckningar).
7. **Apply**. Vänta tills första synken är klar.

> Alternativt: på en redan konfigurerad enhet, **"Copy setup URI"**, och i
> containern **"Connect with setup URI"** + passphrase.

### 1e. Hämta Local REST API-nyckeln

1. **Settings → Community plugins → Local REST API**.
2. Kopiera fältet **API Key**.
3. Klistra in i `.env`:

   ```
   OBSIDIAN_API_KEY=<den-långa-nyckeln>
   ```

4. Kontrollera att **"Binding Host"** i pluginets inställningar är tomt eller
   `0.0.0.0` (inte `127.0.0.1`) — annars når inte `mail-importer` porten från
   sin container.

Pluginet lyssnar på **HTTPS 27124** med självsignerat certifikat. Därför kör
`mail-importer` mot `https://obsidian:27124` med `OBSIDIAN_API_VERIFY_TLS=false`
(default). Vill du hellre köra oskyddad HTTP: aktivera pluginets
"Non-encrypted (HTTP) Server" på 27123 och sätt `OBSIDIAN_API_URL=http://obsidian:27123`
i `.env`.

---

## Steg 2 — Stäng webb-UI-exponeringen efteråt

När LiveSync är inloggat och nyckeln ligger i `.env`:

1. I `docker-compose.yml`, **kommentera bort** `ports:`-blocket under `obsidian`
   igen:

   ```yaml
    # ports:
    #   - "127.0.0.1:3001:3001"
   ```

2. Applicera:

   ```bash
   docker compose up -d obsidian
   ```

   Kontrollera:

   ```bash
   docker ps --filter name=epost-import-obsidian   # ingen 3001 i PORTS
   ```

3. (Rekommenderat) rotera `OBSIDIAN_WEB_PASSWORD` i `.env` nu när det inte
   behövs mer.

Local REST API-porten (27124) exponeras aldrig mot host-nätverket — bara via
`expose:` internt i `epost-import-net`, dit bara `mail-importer` har åtkomst.

---

## Steg 3 — Engångskonfiguration av `bridge`-containern

Proton Bridge måste loggas in **en gång**, interaktivt. Det här kan **inte**
automatiseras (kräver ditt lösenord + ev. 2FA-kod live) — måste köras av dig
i en riktig terminal, inte något jag/en AI-assistent kan göra åt dig.

### 3a. Bygg och logga in

```bash
docker compose build bridge
docker compose run --rm -it bridge init
```

Vänta tills `Welcome to Proton Mail Bridge interactive shell` visas (den
genererar en GPG-nyckel + initierar sitt lösenordslager första gången — några
sekunder). Skriv sedan, i den prompten:

1. `login` → din Proton-adress, lösenord, 2FA-kod om du har det aktiverat.
2. `info` → visar kontots IMAP/SMTP-uppgifter, inklusive **Bridge-lösenordet**
   (auto-genererat, långt — **inte** ditt vanliga Proton-lösenord). Klistra in
   det i `.env` som `IMAP_PASS`.
3. `exit`.

> **Efter `login` startar en engångs-synk** av hela brevlådan (kan ta lång
> stund beroende på hur mycket post du har). Den är krascha-säker/resumable —
> du kan lugnt köra `info`/`exit` innan den är klar, den fortsätter i
> bakgrunden när du startar `bridge` som daemon i nästa steg. Loggen blir
> under tiden en kontinuerlig ström av `Sync (...): X% ...`-rader som kan göra
> det svårt att se vad du skriver — dina tangenttryckningar tas ändå emot,
> bara skriv och tryck Enter. Undvik Ctrl+C (riskerar att döda hela
> containern eftersom den kördes med `--rm`).

### 3b. Starta som daemon

```bash
docker compose up -d bridge
```

Sessionen ligger kvar i volymen — ingen ny inloggning behövs efter det här,
varken vid omstart av containern eller efter ett NAS-strömavbrott.

### 3c. Hitta det exakta label-namnet

Proton-labels dyker i Bridge upp som egna mappar under `Labels/<namn>`
(mappar/folders under `Folders/<namn>`) — **inte** bara `<namn>`:

```bash
docker compose run --rm mail-importer list-folders
```

Sätt `MAILBOX=Labels/Obsidian` (eller vad din label heter) i `.env`.

### Alternativ: kör Bridge nativt i stället

Vill du hellre köra Proton Mail Bridge som ett vanligt program på en dator i
stället för i Docker: installera den från [proton.me/mail/bridge](https://proton.me/mail/bridge)
(kräver betalplan), hämta Bridge-lösenordet i dess GUI, och sätt i `.env`:

```
IMAP_HOST=host.docker.internal   # Bridge körs på samma maskin som Docker
# IMAP_HOST=192.168.x.y          # Bridge körs på en annan maskin i LAN:et
IMAP_PORT=1143
```

Ta då bort/kommentera bort `bridge`-tjänsten i `docker-compose.yml` (och dess
`depends_on` i `mail-importer`). `host.docker.internal` funkar på Docker
Desktop direkt; på Linux/NAS löser `extra_hosts: host-gateway` (redan satt i
compose) namnet till Docker-hosten.

---

## Hur importen fungerar

- **Långlivad process** (ingen cron). **IMAP IDLE** ger nästan-realtid; en
  **poll var 5:e minut** (`POLL_INTERVAL_SECONDS`) är säkerhetsnät.
- Mappen väljs **read-only** och meddelanden hämtas med **`BODY.PEEK[]`** —
  `\Seen`-flaggan på servern rörs aldrig. **Alla** meddelanden hämtas, oavsett
  läs-status.
- **Tracking** i `/data/state.sqlite3` (egen volym `epost-import-importer-state`,
  **inte** i valvet): `(uidvalidity, uid, message_id, note_path, imported_at)`.
  - Nytt meddelande = `(uidvalidity, uid)` saknas i databasen.
  - **Ändrad `UIDVALIDITY`** → dedup faller tillbaka på **Message-ID**.
  - Meddelanden utan `Message-ID` får ett syntetiskt `sha256-…@no-message-id.local`.
- **Per nytt meddelande:**
  1. Parsar avsändare, mottagare (To/Cc), ämne, datum, Message-ID, brödtext.
     HTML → Markdown med rubriker, listor och länkar bevarade.
     `cid:`-referenser skrivs om till länkar mot de uppladdade bilagorna.
  2. **Alla Proton-labels meddelandet har** slås upp (inte bara den bevakade)
     — se "Flera labels" nedan.
  3. **Bilagor först** → `PUT` till `Email/attachments/` via Local REST API.
  4. **Sedan anteckningen** som länkar bilagorna (`![[...]]` för bilder, annars `[[...]]`).
  5. **`(uidvalidity, uid, message_id)` skrivs till SQLite** — det är själva
     "klart"-markeringen. Kraschar processen innan dess importeras UID:t om vid
     nästa körning; anteckningen skapas bara om den saknas, så ingen dubblett.
- **Filnamn:** `{YYYY-MM-DD}-{slug-av-ämne}-{10-tecken-hash-av-message-id}.md` —
  deterministiskt. Befintliga filer **skrivs aldrig över** (existenskontroll
  före varje `PUT`).
- **Frontmatter:** `date`, `from`, `to`, `subject`, `message_id`, `labels`.
- **Flera labels i frontmatter:** IMAP visar bara vilken mapp man råkar ha
  vald — ett meddelande med både labeln `Obsidian` och `Ida` syns bara som
  liggande i `Labels/Obsidian` om man bara tittar i den bevakade mappen.
  Importern söker därför igenom **alla** `Labels/*`-mappar i Bridge efter
  samma Message-ID och tar med alla den hittar i frontmatterns `labels:`.
  `NOTE_LABELS` i `.env` läggs till som **extra**, statiska taggar utöver de
  verkliga Proton-labels som hittas (inte längre den enda källan).
- **HTML-tabeller i mejl:** de allra flesta HTML-mejl (nyhetsbrev, kvitton,
  automatiska utskick) bygger sin **layout** med `<table>` — decennier av
  Outlook-kompatibilitetshack — inte för att presentera riktig tabelldata.
  Rakt av konverterade blir sådana orimliga Markdown-pipe-tabeller (kan bli
  10-tals påhittade "kolumner" av ren sidlayout). En tabell antas därför vara
  **riktig data** (blir en riktig Markdown-tabell) bara om den har
  **`<th>`-rubrikceller** och inte är märkt `role="presentation"` — annars
  packas den upp till vanliga stycken/rader.
- **Felhantering:** ett misslyckat Local REST API-anrop → loggas, UID:t
  markeras **inte** (nytt försök nästa körning), kön fortsätter med resten.
  Retry med **exponential backoff, max 3 försök** mot både IMAP och Local REST API.
- **Nätverksfel:** automatisk återanslutning med backoff upp till 5 minuter
  (`RECONNECT_BACKOFF_MAX_SECONDS`).
- **Graceful shutdown:** `SIGTERM` (`docker compose stop`) låter en påbörjad
  import bli klar innan processen avslutas. Kan ta upp till `IDLE_TIMEOUT_SECONDS`
  (default 60) att reagera; `stop_grace_period` i compose är satt till 90 s.

---

## Miljövariabler

Se **`.env.example`** för fullständig lista med kommentarer. De viktigaste:

| Variabel | Default | Beskrivning |
|---|---|---|
| `IMAP_HOST` / `IMAP_PORT` | `bridge` / `143` | `bridge`-containerns socat-forward-port (INTE Bridges egna interna `1143`) |
| `IMAP_USER` / `IMAP_PASS` | – | Adress + **Bridge**-lösenord (från `info` i steg 3a) |
| `IMAP_STARTTLS` / `IMAP_SSL` / `IMAP_VERIFY_CERT` | `true` / `false` / `false` | Bridge = STARTTLS, självsignerat |
| `MAILBOX` | `Obsidian` | Bevakad label/mapp — oftast `Labels/<namn>` i praktiken, `list-folders` visar exakt namn |
| `OBSIDIAN_API_KEY` | – | Från Local REST API-pluginet (steg 1e) |
| `OBSIDIAN_API_URL` | `https://obsidian:27124` | Internt service-namn, aldrig extern IP |
| `OBSIDIAN_API_VERIFY_TLS` | `false` | Självsignerat cert |
| `NOTE_FOLDER` / `ATTACHMENT_FOLDER` | `Email` / `Email/attachments` | Mål i valvet |
| `NOTE_LABELS` | `Obsidian` | Kommaseparerat, läggs till **utöver** de riktiga Proton-labels som upptäcks per mejl |
| `POLL_INTERVAL_SECONDS` | `300` | Säkerhetsnäts-poll |
| `IDLE_TIMEOUT_SECONDS` | `60` | IDLE-väntetid / shutdown-svarstid |
| `RECONNECT_BACKOFF_MAX_SECONDS` | `300` | Max backoff vid nätfel |
| `API_MAX_RETRIES` | `3` | Försök mot IMAP / Local REST API |
| `HEARTBEAT_MAX_AGE_SECONDS` | `900` | Docker HEALTHCHECK/autoheal: hur gammal heartbeaten får bli |
| `OBSIDIAN_BASE_TAG` | `v1.13.7-ls144` | Pinnad LSIO-image-tagg |
| `OBSIDIAN_WEB_USER` / `OBSIDIAN_WEB_PASSWORD` | `admin` / – | Basic auth för webb-UI, endast engångskonfig |
| `OBSIDIAN_VAULT_NAME` | `Daniel` | Valvkatalog under `/config` |
| `LOCAL_REST_API_VERSION` | `5.1.0` | Plugin-version som init-skriptet hämtar |
| `PUID` / `PGID` | `1000` / `1000` | Fil-ägare i obsidian-containern |
| `BRIDGE_VERSION` | `3.26.0-1` | Pinnad Proton Bridge-version (se `bridge/Dockerfile`) |
| `*_MEM_LIMIT` / `*_CPUS` | se `.env.example` | Resursgränser per tjänst |

---

## Drift & felsökning

```bash
docker compose ps                       # status + health
docker compose logs -f mail-importer    # importloggen
docker compose logs -f obsidian         # Obsidian / LiveSync / init-skriptet
docker compose logs -f bridge           # Proton Bridge / sync-status
docker compose logs -f autoheal         # ser du en omstart den gjort åt dig
docker compose run --rm mail-importer list-folders   # lista IMAP-mappar
docker compose restart mail-importer
docker compose stop                     # graceful (SIGTERM)
```

- **`mail-importer` startar inte / "väntar på Local REST API"**: obsidian-containern
  är inte `healthy` än. Vanligast första gången — du måste slutföra steg 1
  (öppna valvet, slå på community-plugins, konfigurera LiveSync) innan pluginet
  börjar lyssna på 27124. Kolla `docker compose logs obsidian`.
- **`mail-importer` når inte `obsidian:27124`**: sätt **"Binding Host"** i Local
  REST API-pluginet till tomt eller `0.0.0.0` (steg 1e) — default är
  `127.0.0.1`, vilket bara fungerar inuti obsidian-containern själv.
- **Init-skriptet installerade inget**: `docker compose logs obsidian | grep local-rest-api`.
  Ingen internet vid start? Installera pluginet manuellt via **Browse** i GUI:t.
- **`bridge` startar inte / loggar "inget lösenordslager hittat"**: engångsinloggningen
  (steg 3a) är inte gjord än — `docker compose run --rm -it bridge init`.
- **`bridge` loggar "address already in use"**: någon har ändrat portnumren i
  `bridge/entrypoint.sh`/`docker-compose.yml` så att socats forward-port
  krockar med Bridges egen `127.0.0.1`-port. De MÅSTE vara olika portnummer
  (143↔1143, 25↔1025) — se "Om bridge-containern".
- **Inga mejl importeras**: fel `MAILBOX`-namn (kör `list-folders` — kom ihåg
  `Labels/`-prefixet), eller Bridge-lösenordet är fel.
- **Ett meddelande saknar en label i frontmatter**: `mail-importer` söker
  igenom alla `Labels/*`-mappar vid importtillfället — labels som läggs till
  på ett mejl **efter** att det redan importerats syns inte retroaktivt.
  Ta bort noten + dess SQLite-rad (se nedan) för att importera om den.
- **Vill tvinga om-import av ett specifikt mejl** (t.ex. efter en kod-fix):
  ta bort noten via Local REST API (`DELETE /vault/<sökväg>`) och motsvarande
  rad i SQLite (`DELETE FROM imported WHERE uid = <uid>` i `/data/state.sqlite3`
  inuti `mail-importer`-containern), starta sedan om `mail-importer`.
- **Vill tvinga om-import av allt**: ta bort tracking-volymen
  (`docker compose down` + `docker volume rm obsidian-epost-import_epost-import-importer-state`).
  Anteckningar som redan finns i valvet skrivs ändå inte över.
- **Uppgradera obsidian-imagen**: sätt en nyare `OBSIDIAN_BASE_TAG` i `.env`
  (se [LSIO releases](https://github.com/linuxserver/docker-obsidian/releases)),
  kör `docker compose up -d --build obsidian`.
- **Uppgradera bridge-imagen**: sätt en nyare `BRIDGE_VERSION` i `.env` (se
  [Proton Bridge releases](https://github.com/ProtonMail/proton-bridge/releases)),
  kör `docker compose up -d --build bridge`.

---

## Resursgränser & isolering mot NAS:ens övriga tjänster

Satta direkt i `docker-compose.yml`:

| Tjänst | RAM (`mem_limit`) | CPU (`cpus`) | Övrigt |
|---|---|---|---|
| `obsidian` | `1g` | `1.0` | `shm_size: 1gb` (krävs av Electron) |
| `bridge` | `512m` | `0.5` | — |
| `mail-importer` | `512m` | `0.75` | `stop_grace_period: 90s` |
| `autoheal` | `64m` | `0.1` | se "Robusthet & självläkning" nedan |

Alla fyra tjänster kör med `restart: unless-stopped`. En eventuell bugg kan
alltså aldrig svälta CouchDB, Cloudflared eller annat på NAS:en.

---

## Robusthet & självläkning vid NAS-omstart/strömavbrott

Målet: efter ett strömavbrott eller en omstart av NAS:en ska hela stacken komma
igång av sig själv, precis som `obsidian-nas-sync`. Så här hänger det ihop:

### Vad som redan är robust by design

- **`restart: unless-stopped`** på alla fyra tjänster → när dockerd kommer upp
  igen efter ett strömavbrott startar Docker om dem automatiskt, oavsett hur
  länge NAS:en var nere. (Enda undantaget: om du körde `docker compose stop`
  manuellt innan avbrottet — då låter Docker dem vara stoppade, som förväntat.)
- **Startordning spelar ingen roll.** `depends_on: condition: service_healthy`
  styr bara `docker compose up`-kommandot — dockerds egen omstart-vid-boot
  respekterar den INTE. Det är okej: `mail-importer` har egen
  `_wait_for_obsidian()`-retry (backoff upp till 60 s) och kopplar upp sig så
  fort Local REST API svarar, oavsett i vilken ordning containrarna kom igång.
- **IMAP/nätverksfel:** automatisk återanslutning med backoff upp till
  `RECONNECT_BACKOFF_MAX_SECONDS` (default 300 s) — täcker både att Proton
  Bridge inte hunnit starta än och tillfälliga nätverksglapp.
- **`bridge` behöver ingen ny inloggning vid omstart** — sessionen +
  GPG-nyckeln/pass-lösenordslagret ligger i den persisterade volymen. En
  pågående synk är resumable: avbryts den (omstart, strömavbrott) fortsätter
  den där den var, den börjar inte om från noll.
- **Krascha-säker SQLite:** WAL-läge + `synchronous=FULL` + att
  "klart"-markeringen (`mark_imported`) är den sista, atomiska operationen i
  varje import. Ett strömavbrott mitt i en import ger i värsta fall att samma
  UID importeras en gång till nästa körning — aldrig en dubblett eller en
  trasig databas (filer skrivs bara om de saknas).
- **LiveSync** i obsidian-containern beter sig som på vilken annan enhet som
  helst: passphrase och anslutning ligger kvar i den persisterade
  `/config`-volymen, den återupptar synken automatiskt när den kommer upp
  — ingen ny inloggning krävs efter första engångskonfigen.

### Det redan lösta gapet: hängda (inte kraschade) containrar

`restart: unless-stopped` triggar bara om **processen faktiskt avslutas**. Om
Obsidian/Electron (eller Bridge/socat-forwardningen) fryser utan att kraschen
syns som en exit (det vanligaste sättet en headless container "dör" på)
förblir containern uppe men obrukbar — Docker rapporterar `unhealthy` men
startar inget om av sig själv.

Det täcks av **`autoheal`**-tjänsten: den lyssnar på Dockers hälsostatus för
alla containrar märkta `autoheal=true` (`obsidian`, `bridge` och
`mail-importer`) och kör `docker restart` på dem om de är `unhealthy` en stund.

> **Avvägning:** `autoheal` kräver att `/var/run/docker.sock` monteras in,
> vilket i praktiken motsvarar root-åtkomst till hela Docker-hosten. Det är en
> medveten kompromiss för full självläkning. Vill du hellre slippa den
> exponeringen: ta bort `autoheal`-tjänsten och `labels: [autoheal=true]` på
> de två andra tjänsterna i `docker-compose.yml` — du behåller då fortfarande
> omstart vid faktiska krascher, men måste själv då och då köra
> `docker compose ps` och leta efter `unhealthy` om något hänger sig.

### Enda manuella förutsättningen — Docker startar vid boot

Det här styrs av NAS:en, inte av det här repot: se till att **Container
Manager/Docker är satt att starta automatiskt vid boot** i TOS (annars kommer
inget av ovanstående igång alls efter ett strömavbrott). Kontrollera i TOS:
**Container Manager → Settings → "Enable at startup"** (namn kan variera mellan
TOS-versioner). Detta är samma förutsättning som `obsidian-nas-sync` redan
förlitar sig på.

### Testa själv

```bash
# Simulera att en container hänger sig / kraschar:
docker kill -s SIGSTOP epost-import-obsidian   # frys (unhealthy, inte exit)
docker compose ps                              # se "unhealthy" dyka upp
#   ... vänta in AUTOHEAL_START_PERIOD + några healthcheck-intervall ...
docker compose logs -f autoheal                 # se den starta om containern

# Simulera ett strömavbrott:
docker compose kill                             # hårt, utan graceful shutdown
docker compose ps                               # containrarna kommer tillbaka
                                                 # av sig själva (unless-stopped)
```

---

## Portabilitet — samma stack lokalt (Windows) och på NAS:en

Projektet är byggt för att köra **oförändrat** på Windows/Docker Desktop och på
TerraMaster TOS/Linux senare:

- **Inga host-sökvägar, användar-ID:n eller miljöantaganden i `docker-compose.yml`.**
  Allt som skiljer miljöerna åt styrs via `.env`.
- **Bara Docker-hanterade named volumes**, inga bind mounts mot `C:\...` eller
  `/volume1/...`. Named volumes beter sig identiskt oavsett värdmaskin. SQLite
  (uid-trackingen) gör frekventa små writes/locks och är särskilt känsligt för
  den långsamma I/O och de rättighets-/notifieringsproblem en Windows-bind-mount
  via WSL2 kan ge — därför named volume.
- `host.docker.internal` (bara relevant om du kör Bridge nativt i stället för
  i `bridge`-containern) löser sig automatiskt på Docker Desktop och via
  `extra_hosts: host-gateway` på Linux.

### Vad du ändrar i `.env` när du flyttar till NAS:en

| Variabel | Varför |
|---|---|
| `PUID` / `PGID` | Matcha din NAS-användare (kör `id <användare>` på NAS:en via SSH) |
| `TZ` | Vid behov |
| `*_MEM_LIMIT` / `*_CPUS` | Om NAS:en har annan resursbudget |

Allt annat är oförändrat (inklusive `IMAP_HOST=bridge` — Bridge körs i Docker
på båda maskinerna). Bygg om på NAS:en med `docker compose up -d --build`.

### Named volumes — namn och innehåll

Faktiska volymnamn = projektnamn + volymnyckel (`docker volume ls | grep epost-import`):

| Volym | Innehåll | Behöver flyttas? |
|---|---|---|
| `obsidian-epost-import_epost-import-obsidian-config` | Obsidian-config, valv, plugins, LiveSync-inställningar + E2E-passphrase, Local REST API-nyckeln | **Nej** — gör om engångskonfigen (steg 1) på NAS:en. Valvet återsynkas ändå från CouchDB. |
| `obsidian-epost-import_epost-import-bridge-config` | Bridges session, GPG-nyckel + pass-lösenordslager | **Rekommenderat men inte nödvändigt.** Flyttar du den inte måste du köra engångsinloggningen (steg 3a, med 2FA) igen på NAS:en — själva mejlkontot påverkas inte. |
| `obsidian-epost-import_epost-import-importer-state` | `state.sqlite3` — vilka UID:n/Message-ID:n som redan importerats | **Valfritt.** Flyttar du den inte gör importern en engångs-omgenomgång av hela labeln vid första körningen på NAS:en. Inga dubbletter skapas (deterministiska filnamn, filer skrivs aldrig över) — bara extra `fanns redan`-loggar. |

### Flytta / säkerhetskopiera en named volume mellan maskiner

Exemplet flyttar tracking-volymen. Byt volymnamn för att ta med `obsidian-config` också.

**1. Stoppa stacken** (så SQLite inte skrivs mitt i / WAL:en är konsistent):

```bash
docker compose stop
```

**2. Exportera till en tar-fil** (kör i repo-mappen på nuvarande maskin):

```bash
# Linux/macOS eller Git Bash på Windows:
docker run --rm \
  -v obsidian-epost-import_epost-import-importer-state:/from:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/importer-state.tgz -C /from .
```

```powershell
# PowerShell på Windows (samma sak, annan pwd-syntax):
docker run --rm `
  -v obsidian-epost-import_epost-import-importer-state:/from:ro `
  -v "${PWD}:/backup" `
  alpine tar czf /backup/importer-state.tgz -C /from .
```

**3. Kopiera `importer-state.tgz`** till NAS:en (scp/SMB/USB).

**4. Importera på NAS:en** — skapa volymerna först, återställ sedan:

```bash
# Skapar named volumes utan att starta tjänsterna:
docker compose create

docker run --rm \
  -v obsidian-epost-import_epost-import-importer-state:/to \
  -v "$PWD":/backup:ro \
  alpine sh -c "cd /to && tar xzf /backup/importer-state.tgz"

docker compose up -d
```

> Alternativ till tar: `docker run --rm -v <volym>:/from -v <mål>:/to alpine cp -a /from/. /to/`.
> tar-varianten ger en enda fil som är enklare att flytta mellan maskiner och
> bevarar rättigheter/tidsstämplar.

### Ren start på NAS:en (utan att flytta något)

```bash
git clone <repo> && cd obsidian-epost-import
cp .env.example .env   # fyll i, justera PUID/PGID
docker compose up -d --build obsidian   # gör om steg 1 (engångskonfig)
# lägg OBSIDIAN_API_KEY i .env, stäng webb-UI-porten (steg 2)
docker compose run --rm -it bridge init   # gör om steg 3a (engångsinloggning)
docker compose up -d --build
```

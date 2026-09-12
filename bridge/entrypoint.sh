#!/bin/sh
# ------------------------------------------------------------------
#  Entrypoint för den egna Proton Bridge-imagen. Två lägen:
#
#    init      Interaktivt: skapar (om saknas) GPG-nyckel + pass-
#              lösenordslager, kör sedan Bridge-CLI:t så du kan
#              logga in. Körs EN gång (README "Steg 3"):
#                docker compose run --rm -it bridge init
#              I CLI:t: login -> info (Bridge-lösenordet, till
#              .env som IMAP_PASS) -> exit.
#
#    (inget)   Daemon-läge (default CMD). Kräver att `init` redan
#              körts (fäller annars med tydligt felmeddelande i
#              stället för att som originalreferensen tyst köra
#              vidare med okrypterat lösenordslager).
#
#  Bridge binder sina IMAP/SMTP-portar bara till 127.0.0.1 (hård-
#  kodat, av Protons design) — socat proxar samma portnummer ut på
#  containerns interface så att andra containrar på docker-nätverket
#  (t.ex. mail-importer) når dem.
# ------------------------------------------------------------------
set -eu

KEY_NAME="Proton Bridge"
PASS_STORE="${PASSWORD_STORE_DIR:-$HOME/.password-store}"

log() {
    echo "[bridge-entrypoint] $*"
}

has_keychain() {
    gpg --list-secret-keys "$KEY_NAME" >/dev/null 2>&1 && [ -d "$PASS_STORE" ]
}

ensure_keychain() {
    if ! gpg --list-secret-keys "$KEY_NAME" >/dev/null 2>&1; then
        log "genererar GPG-nyckel för lösenordslagret (engångsjobb, sparas i volymen)"
        gpg --batch --generate-key /gpg-batch-params
    fi
    if [ ! -d "$PASS_STORE" ]; then
        log "initierar pass-lösenordslager"
        pass init "$KEY_NAME" >/dev/null
    fi
}

start_forwarders() {
    # Bridge binder ALLTID till 127.0.0.1 (hårdkodat). socat måste
    # lyssna på ANDRA portnummer än Bridges egna (143/25, inte
    # 1143/1025) — annars kolliderar socats "alla interface"-bindning
    # (0.0.0.0:PORT) med Bridges 127.0.0.1:PORT för samma portnummer
    # och en av dem hinner aldrig binda ("address already in use").
    if ! command -v socat >/dev/null 2>&1; then
        log "FEL: socat saknas i imagen — IMAP/SMTP kan inte nås utifrån. Avbryter."
        exit 1
    fi
    socat TCP-LISTEN:143,fork,reuseaddr TCP:127.0.0.1:1143 &
    socat TCP-LISTEN:25,fork,reuseaddr TCP:127.0.0.1:1025 &
}

case "${1:-}" in
    init)
        ensure_keychain
        log "interaktivt Bridge-CLI. Kör: login  (följ prompten)"
        log "sedan: info   (visar Bridge-lösenordet -> .env som IMAP_PASS)"
        log "sedan: exit"
        exec protonmail-bridge --cli
        ;;
    *)
        if ! has_keychain; then
            log "FEL: inget lösenordslager hittat i volymen."
            log "Kör engångskonfigen först: docker compose run --rm -it bridge init"
            exit 1
        fi
        start_forwarders
        # Håller Bridge-CLI:t (som bara är interaktivt) vid liv som
        # daemon utan att någon är ansluten: en FIFO öppnad read+write
        # på samma fd ger aldrig EOF på stdin.
        FIFO="$(mktemp -u)"
        mkfifo "$FIFO"
        exec 3<>"$FIFO"
        rm -f "$FIFO"
        log "startar Proton Bridge i daemon-läge"
        exec protonmail-bridge --cli <&3
        ;;
esac

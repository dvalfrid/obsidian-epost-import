#!/bin/sh
# ------------------------------------------------------------------
#  Entrypoint for the own Proton Bridge image. Two modes:
#
#    init      Interactive: creates (if missing) a GPG key + pass
#              secret store, then runs the Bridge CLI so you can log
#              in. Run ONCE (README "Step 3"):
#                docker compose run --rm -it bridge init
#              In the CLI: login -> info (the Bridge password, put
#              it in .env as IMAP_PASS) -> exit.
#
#    (none)    Daemon mode (default CMD). Requires that `init` has
#              already been run (fails with a clear error message
#              otherwise, instead of silently continuing with an
#              unencrypted secret store like the reference images did).
#
#  Bridge only binds its IMAP/SMTP ports to 127.0.0.1 (hardcoded, by
#  Proton's design) — socat proxies the same port numbers out on the
#  container's interface so other containers on the Docker network
#  (e.g. mail-importer) can reach them.
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
        log "generating a GPG key for the secret store (one-time job, saved in the volume)"
        gpg --batch --generate-key /gpg-batch-params
    fi
    if [ ! -d "$PASS_STORE" ]; then
        log "initializing the pass secret store"
        pass init "$KEY_NAME" >/dev/null
    fi
}

start_forwarders() {
    # Bridge ALWAYS binds to 127.0.0.1 (hardcoded). socat must
    # listen on DIFFERENT port numbers than Bridge's own (143/25,
    # not 1143/1025) — otherwise socat's "all interfaces" binding
    # (0.0.0.0:PORT) collides with Bridge's 127.0.0.1:PORT for the
    # same port number and one of them never manages to bind
    # ("address already in use").
    if ! command -v socat >/dev/null 2>&1; then
        log "ERROR: socat is missing from the image — IMAP/SMTP can't be reached from outside. Aborting."
        exit 1
    fi
    socat TCP-LISTEN:143,fork,reuseaddr TCP:127.0.0.1:1143 &
    socat TCP-LISTEN:25,fork,reuseaddr TCP:127.0.0.1:1025 &
}

case "${1:-}" in
    init)
        ensure_keychain
        log "interactive Bridge CLI. Run: login  (follow the prompt)"
        log "then: info   (shows the Bridge password -> .env as IMAP_PASS)"
        log "then: exit"
        exec protonmail-bridge --cli
        ;;
    *)
        if ! has_keychain; then
            log "ERROR: no secret store found in the volume."
            log "Run the one-time setup first: docker compose run --rm -it bridge init"
            exit 1
        fi
        start_forwarders
        # Keeps the Bridge CLI (which is interactive-only) alive as a
        # daemon with nobody attached: a FIFO opened read+write on
        # the same fd never gets EOF on stdin.
        FIFO="$(mktemp -u)"
        mkfifo "$FIFO"
        exec 3<>"$FIFO"
        rm -f "$FIFO"
        log "starting Proton Bridge in daemon mode"
        exec protonmail-bridge --cli <&3
        ;;
esac

# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
#  Egen, självunderhållen Proton Mail Bridge-image.
#
#  Varför en egen image i stället för en färdig från Docker Hub:
#  ingen officiell finns, och de undersökta community-alternativen
#  (t.ex. shenxn/protonmail-bridge) visade sig ha slutat publiceras
#  ~17 månader innan detta skrevs, trots att källkoden fortsatte
#  bumpa version — dvs. deras publiceringspipeline hade gått sönder
#  tyst. Se CLAUDE.md för detaljer.
#
#  Hämtar Protons OFFICIELLA .deb-paket direkt från GitHub-releasen
#  och verifierar OpenPGP-signaturen mot Protons publicerade
#  signeringsnyckel (fingerprint pinnad nedan) innan installation.
#  Bygget FALLERAR om signaturen eller fingerprint inte stämmer.
#
#  Pinna BRIDGE_VERSION medvetet vid uppgradering — se
#  https://github.com/ProtonMail/proton-bridge/releases
# ------------------------------------------------------------------
FROM debian:bookworm-slim

# Proton Mail Bridge är GPLv3 — redistribution av byggda binärer/images
# är uttryckligen tillåtet under GPLv3 så länge källkoden görs
# tillgänglig, vilket Proton redan gör publikt (se source-labeln nedan).
LABEL org.opencontainers.image.source="https://github.com/dvalfrid/obsidian-epost-import" \
      org.opencontainers.image.description="Proton Mail Bridge, headless, byggd från Protons officiella .deb + GPG-signaturverifiering. Bridge självt: https://github.com/ProtonMail/proton-bridge (GPLv3)." \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ARG BRIDGE_VERSION=3.26.0-1
# Protons officiella signeringsnyckel ("Proton Technologies AG
# (ProtonMail Bridge developers) <bridge@protonmail.ch>"), hämtad
# och verifierad manuellt från https://proton.me/download/bridge/bridge_pubkey.gpg
# innan den pinnades här. Om den nedladdade nyckeln någonsin skulle
# avvika ska bygget stoppa — inte tyst lita på vad som ligger på URL:en.
ARG BRIDGE_PUBKEY_FINGERPRINT=D51E64D3E63EDC3EEF7864CEE2C75D68E6234B07

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg pass netcat-openbsd socat \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/bridge-install
RUN set -eux; \
    DEB="protonmail-bridge_${BRIDGE_VERSION}_amd64.deb"; \
    TAG="v${BRIDGE_VERSION%-*}"; \
    BASE_URL="https://github.com/ProtonMail/proton-bridge/releases/download/${TAG}"; \
    curl -fsSLO "${BASE_URL}/${DEB}"; \
    curl -fsSLO "${BASE_URL}/${DEB}.sig"; \
    curl -fsSL "https://proton.me/download/bridge/bridge_pubkey.gpg" -o pubkey.gpg; \
    export GNUPGHOME="$(mktemp -d)"; \
    gpg --import pubkey.gpg; \
    FPR="$(gpg --with-colons --fingerprint 2>/dev/null | awk -F: '/^fpr:/ {print $10; exit}')"; \
    if [ "$FPR" != "$BRIDGE_PUBKEY_FINGERPRINT" ]; then \
        echo "FEL: hämtad nyckels fingerprint ($FPR) matchar INTE pinnad ($BRIDGE_PUBKEY_FINGERPRINT)" >&2; \
        exit 1; \
    fi; \
    gpg --verify "${DEB}.sig" "${DEB}"; \
    apt-get update; \
    apt-get install -y --no-install-recommends "./${DEB}"; \
    rm -rf /var/lib/apt/lists/* /tmp/bridge-install "$GNUPGHOME"

COPY entrypoint.sh /entrypoint.sh
COPY gpg-batch-params /gpg-batch-params
RUN chmod 0755 /entrypoint.sh

ENV HOME=/root
WORKDIR /root
VOLUME ["/root"]
# 143/25: socats externt nåbara forward-portar (det andra containrar
# ska ansluta till). 1143/1025: Bridges egna interna (127.0.0.1-bara)
# portar — inte publicerade utåt, bara det som proxas.
EXPOSE 143 25

# Kollar BÅDE Bridges egen (interna) port och socat-forwarden utåt —
# om bara den ena kollas missas t.ex. en trasig/saknad socat-proxy
# (exakt det som hände under utveckling: porten "svarade" internt men
# ingen annan container nådde den). Meningslös innan `init` körts.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD nc -z 127.0.0.1 1143 && nc -z 127.0.0.1 143 || exit 1

ENTRYPOINT ["/entrypoint.sh"]

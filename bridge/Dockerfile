# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
#  Own, self-maintained Proton Mail Bridge image.
#
#  Why an own image instead of a prebuilt one from Docker Hub: no
#  official image exists, and the community alternatives we
#  evaluated (e.g. shenxn/protonmail-bridge) had stopped publishing
#  despite upstream still shipping new releases — their publish
#  pipeline had silently broken. See CLAUDE.md for details.
#
#  Downloads Proton's OFFICIAL .deb package directly from the GitHub
#  release and verifies the OpenPGP signature against Proton's
#  published signing key (fingerprint pinned below) before
#  installing. The build FAILS if the signature or fingerprint
#  doesn't match.
#
#  Pin BRIDGE_VERSION deliberately when upgrading — see
#  https://github.com/ProtonMail/proton-bridge/releases
# ------------------------------------------------------------------
FROM debian:bookworm-slim

# Proton Mail Bridge is GPLv3 — redistributing built binaries/images
# is explicitly permitted under GPLv3 as long as the source is made
# available, which Proton already does publicly (see the source
# label below).
LABEL org.opencontainers.image.source="https://github.com/dvalfrid/obsidian-epost-import" \
      org.opencontainers.image.description="Proton Mail Bridge, headless, built from Proton's official .deb + GPG signature verification. Bridge itself: https://github.com/ProtonMail/proton-bridge (GPLv3)." \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ARG BRIDGE_VERSION=3.26.0-1
# Proton's official signing key ("Proton Technologies AG
# (ProtonMail Bridge developers) <bridge@protonmail.ch>"), fetched
# and verified manually from
# https://proton.me/download/bridge/bridge_pubkey.gpg before being
# pinned here. If the downloaded key ever diverges, the build
# should stop — not silently trust whatever is at the URL.
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
        echo "ERROR: downloaded key's fingerprint ($FPR) does NOT match the pinned one ($BRIDGE_PUBKEY_FINGERPRINT)" >&2; \
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
# 143/25: socat's externally reachable forward ports (what other
# containers connect to). 1143/1025: Bridge's own internal
# (127.0.0.1-only) ports — never published outward, just what gets
# proxied.
EXPOSE 143 25

# Checks BOTH Bridge's own (internal) port and the socat forward —
# checking only one would miss a broken/missing socat proxy (the
# internal port can be fine while nothing else can actually reach
# it). Meaningless before `init` has been run.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD nc -z 127.0.0.1 1143 && nc -z 127.0.0.1 143 || exit 1

ENTRYPOINT ["/entrypoint.sh"]

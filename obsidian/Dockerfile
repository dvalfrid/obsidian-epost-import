# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
#  Thin layer on top of the maintained LinuxServer.io image.
#  Only addition: an init script that preinstalls the Local REST
#  API plugin into the vault. No Obsidian/VNC logic of our own —
#  all of that is maintained (and rebuilt regularly for CVEs) by LSIO.
#
#  ALWAYS pin a concrete tag. Newer tags:
#  https://github.com/linuxserver/docker-obsidian/releases
# ------------------------------------------------------------------
ARG OBSIDIAN_BASE_TAG=v1.13.7-ls144
FROM lscr.io/linuxserver/obsidian:${OBSIDIAN_BASE_TAG}

LABEL org.opencontainers.image.source="https://github.com/dvalfrid/obsidian-epost-import" \
      org.opencontainers.image.description="Headless Obsidian (LinuxServer.io base) + preinstalled Local REST API plugin, for obsidian-epost-import."

# LSIO only runs scripts in /custom-cont-init.d if the directory is
# owned by root (a security guard). So the script is baked in here
# instead of bind-mounted — that way ownership is guaranteed correct.
COPY --chown=root:root custom-cont-init.d/ /custom-cont-init.d/
RUN chmod 0755 /custom-cont-init.d/*

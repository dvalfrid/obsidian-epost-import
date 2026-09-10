# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
#  Tunt lager ovanpå den underhållna LinuxServer.io-imagen.
#  Enda tillägget: ett init-skript som förinstallerar Local REST
#  API-pluginet i valvet. Ingen egen Obsidian/VNC-logik — allt det
#  underhålls (och byggs om löpande för CVE:er) av LSIO.
#
#  Pinna ALLTID en konkret tagg. Nyare taggar:
#  https://github.com/linuxserver/docker-obsidian/releases
# ------------------------------------------------------------------
ARG OBSIDIAN_BASE_TAG=v1.13.7-ls144
FROM lscr.io/linuxserver/obsidian:${OBSIDIAN_BASE_TAG}

# LSIO kör bara skript i /custom-cont-init.d om katalogen ägs av root
# (säkerhetsspärr). Därför bakas skriptet in här i stället för att
# bind-monteras — då blir ägarskapet garanterat rätt.
COPY --chown=root:root custom-cont-init.d/ /custom-cont-init.d/
RUN chmod 0755 /custom-cont-init.d/*

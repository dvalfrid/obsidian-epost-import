FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# curl bara för Dockerns HEALTHCHECK-fallback och felsökning.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r importer \
    && useradd -r -g importer -u 10001 -m importer

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mailimporter ./mailimporter

RUN mkdir -p /data && chown -R importer:importer /data /app
USER importer

VOLUME ["/data"]

# Kollar heartbeat-filen som huvudloopen rör vid varje varv.
HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD ["python", "-m", "mailimporter", "healthcheck"]

ENTRYPOINT ["python", "-m", "mailimporter"]

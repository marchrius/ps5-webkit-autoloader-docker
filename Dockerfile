FROM python:3.13-alpine

ARG AUTOLOADER_VERSION=0.5.2
ARG AUTOLOADER_SHA256=""
LABEL org.opencontainers.image.title="PS5 WebKit Autoloader DNS host" \
      org.opencontainers.image.description="Local PSN DNS blocking and official WebKit installer hosting"

RUN apk add --no-cache dnsmasq openssl tini
WORKDIR /app
COPY app/fetch_release.py /app/fetch_release.py
RUN python /app/fetch_release.py "${AUTOLOADER_VERSION}" "${AUTOLOADER_SHA256}"
COPY app/ /app/
COPY config/ /config/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 53/udp 53/tcp 80/tcp 443/tcp
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]
ENTRYPOINT ["/sbin/tini", "--", "python", "/app/service.py"]

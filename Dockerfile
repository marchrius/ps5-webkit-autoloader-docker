# Keep the Python build and final runtime on the same Alpine release/ABI.
FROM python:3.13-alpine3.24 AS python-runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Removing these files before copying /usr/local avoids retaining them in
# the final image's lower layers. Preserve the standard library and runtime libs.
RUN apk info --depends .python-rundeps | sed '1d; /^$/d' > /python-rundeps.txt \
    && rm -rf /usr/local/include /usr/local/lib/pkgconfig \
       /usr/local/lib/python3.13/config-* \
       /usr/local/lib/python3.13/ensurepip \
       /usr/local/lib/python3.13/site-packages/pip \
       /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
       /usr/local/bin/pip* /usr/local/bin/python*-config

FROM python-runtime AS upstream-download

ARG AUTOLOADER_VERSION=0.6.1
ARG AUTOLOADER_SHA256=""
WORKDIR /app
COPY app/fetch_release.py /tmp/fetch_release.py
RUN python /tmp/fetch_release.py "${AUTOLOADER_VERSION}" "${AUTOLOADER_SHA256}"

FROM alpine:3.24 AS runtime

LABEL org.opencontainers.image.title="PS5 WebKit Autoloader DNS host" \
      org.opencontainers.image.description="Local PSN DNS blocking and official WebKit installer hosting" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PATH=/usr/local/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=python-runtime /usr/local/ /usr/local/
COPY --from=python-runtime /python-rundeps.txt /tmp/python-rundeps.txt
# Resolve the official Python image's native dependencies for this architecture.
RUN apk add --no-cache $(cat /tmp/python-rundeps.txt) \
       ca-certificates tzdata dnsmasq openssl tini \
    && rm /tmp/python-rundeps.txt
WORKDIR /app
COPY --from=upstream-download /app/upstream_host.py /app/UPSTREAM.txt /app/LICENSE.upstream /app/
COPY app/ /app/
COPY config/ /config/
COPY LICENSE /app/LICENSE
EXPOSE 53/udp 53/tcp 80/tcp 443/tcp
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]
ENTRYPOINT ["/sbin/tini", "--", "python", "/app/service.py"]

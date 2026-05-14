# syntax=docker/dockerfile:1
ARG USE_SLIM=false
ARG USE_PERMISSION_HARDENING=false

ARG BUILD_HASH=dev-build
# Override at your own risk - non-root configurations are untested
ARG UID=0
ARG GID=0

######## WebUI frontend ########
FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS build
ARG BUILD_HASH
# Sentry DSN for the browser client — baked into the static build via
# SvelteKit's $env/dynamic/public (adapter-static resolves at build time).
ARG PUBLIC_SENTRY_DSN=""

# Set Node.js options (heap limit Allocation failed - JavaScript heap out of memory)
ENV NODE_OPTIONS="--max-old-space-size=4096"

WORKDIR /app

# to store git revision in build
RUN apk add --no-cache git

COPY package.json package-lock.json ./
RUN npm ci --force

COPY . .
ENV APP_BUILD_HASH=${BUILD_HASH}
ENV PUBLIC_SENTRY_DSN=${PUBLIC_SENTRY_DSN}
RUN npm run build

######## WebUI backend ########
FROM python:3.11.14-slim-bookworm AS base

# OCI annotations — connect package on GHCR to the source repo.
LABEL org.opencontainers.image.source="https://github.com/T3-Venture-Labs-Limited/myah"
LABEL org.opencontainers.image.description="Myah — self-hostable web platform for Hermes Agent"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Use args
ARG USE_SLIM
ARG USE_PERMISSION_HARDENING
ARG UID
ARG GID

# Python settings
ENV PYTHONUNBUFFERED=1

## Basis ##
ENV ENV=prod \
    PORT=8080 \
    USE_SLIM_DOCKER=${USE_SLIM}

## Basis URL Config ##
ENV OPENAI_API_BASE_URL=""

## API Key and Security Config ##
ENV OPENAI_API_KEY="" \
    WEBUI_SECRET_KEY="" \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false

WORKDIR /app/backend

ENV HOME=/root
# Create user and group if not root
RUN if [ $UID -ne 0 ]; then \
    if [ $GID -ne 0 ]; then \
    addgroup --gid $GID app; \
    fi; \
    adduser --uid $UID --gid $GID --home $HOME --disabled-password --no-create-home app; \
    fi

# Make sure the user has access to the app and root directory
RUN chown -R $UID:$GID /app $HOME

# Install common system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git build-essential gcc netcat-openbsd curl jq \
    python3-dev \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# No Docker CLI install in the OSS variant — every endpoint that
# ``docker exec``-s into a per-user agent container is gated by
# ``is_oss_mode()`` in ``processes.py`` / ``containers.py`` and returns
# 501 with an upsell message (per spec §3 Q-oss-cron-processes-ui).
# The hosted variant installs the CLI in ``platform-hosted/Dockerfile``;
# see Workstream D Task D.4.

# install python dependencies
COPY --chown=$UID:$GID ./backend/requirements.txt ./requirements.txt

RUN set -e; \
    pip3 install --no-cache-dir uv; \
    uv pip install --system -r requirements.txt --no-cache-dir; \
    mkdir -p /app/backend/data; chown -R $UID:$GID /app/backend/data/; \
    rm -rf /var/lib/apt/lists/*;

# copy built frontend files
COPY --chown=$UID:$GID --from=build /app/build /app/build
# Myah fork: upstream CHANGELOG.md removed (see backend/myah/env.py); nothing to copy.
COPY --chown=$UID:$GID --from=build /app/package.json /app/package.json

# copy backend files
COPY --chown=$UID:$GID ./backend .

# Copy the cross-cutting `shared` package (Pydantic source-of-truth for the
# platform↔Hermes contract; consumed by routers/{openai,tasks,providers}.py
# and utils/{hermes_stream_handler,agent_proxy}.py via `from shared.contract
# import ...`). It lives at platform/shared/ in the source tree — outside
# platform/backend/ — so it isn't picked up by the backend COPY above.
# Placing it inside /app/backend/ keeps it on the WORKDIR-derived sys.path
# without needing a PYTHONPATH override.
COPY --chown=$UID:$GID ./shared ./shared

EXPOSE 8080

HEALTHCHECK CMD curl --silent --fail http://localhost:${PORT:-8080}/health | jq -ne 'input.status == true' || exit 1

# Minimal, atomic permission hardening for OpenShift (arbitrary UID):
# - Group 0 owns /app and /root
# - Directories are group-writable and have SGID so new files inherit GID 0
RUN if [ "$USE_PERMISSION_HARDENING" = "true" ]; then \
    set -eux; \
    chgrp -R 0 /app /root || true; \
    chmod -R g+rwX /app /root || true; \
    find /app -type d -exec chmod g+s {} + || true; \
    find /root -type d -exec chmod g+s {} + || true; \
    fi

USER $UID:$GID

ARG BUILD_HASH
ENV WEBUI_BUILD_VERSION=${BUILD_HASH}
ENV DOCKER=true

CMD [ "bash", "start.sh"]

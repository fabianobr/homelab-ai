FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

ARG DSH_VERSION=0.1.0-rc.7

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        g++ \
        git \
        make \
        python3 \
    && npm install -g --foreground-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
    && rm -rf /var/lib/apt/lists/* /root/.npm

RUN mkdir -p /workspace /dsh-home/.npm \
    && chown -R node:node /workspace /dsh-home

COPY --chown=node:node relay.mjs /usr/local/lib/deepseek-harness/relay.mjs

USER node
WORKDIR /workspace

ENV HOME=/dsh-home \
    DSH_HOME=/dsh-home \
    npm_config_cache=/dsh-home/.npm \
    DSH_TELEMETRY_DISABLED=1

# syntax=docker/dockerfile:1
# check=error=true

# Default values for versions
ARG THC_VERSION='0.36.0' \
    TINI_VERSION='0.19.0'

# Default values for variables that change less often
ARG DENO_DIR='/deno-dir' \
    GH_BASE_URL='https://github.com' \
    HOST='0.0.0.0' \
    PORT='8282'


# we can use these aliases and let dependabot remain simple
# inspired by:
# https://github.com/dependabot/dependabot-core/issues/2057#issuecomment-1351660410
FROM alpine:3.22 AS dependabot-alpine
FROM debian:13-slim AS dependabot-debian

# Retrieve the deno binary from the repository
FROM denoland/deno:bin-2.4.5 AS deno-bin


# Stage for creating the non-privileged user
FROM dependabot-alpine AS user-stage

RUN adduser -u 10001 -S appuser

# Stage for downloading files using curl from Debian
FROM dependabot-debian AS debian-curl
RUN DEBIAN_FRONTEND='noninteractive' && export DEBIAN_FRONTEND && \
    apt-get update && apt-get install -y curl

# Download tiny-health-checker from GitHub
FROM debian-curl AS thc-download
ARG GH_BASE_URL THC_VERSION
RUN arch="$(uname -m)" && \
    gh_url() { printf -- "${GH_BASE_URL}/%s/releases/download/%s/%s\n" "$@" ; } && \
    URL="$(gh_url dmikusa/tiny-health-checker v${THC_VERSION} thc-${arch}-unknown-linux-musl)" && \
    curl -fsSL --output /thc "${URL}" && chmod -v 00555 /thc

# Cache the thc binary as a layer
FROM scratch AS thc-bin
ARG THC_VERSION
ENV THC_VERSION="${THC_VERSION}"
COPY --from=thc-download /thc /thc

# Download tini from GitHub
FROM debian-curl AS tini-download
ARG GH_BASE_URL TINI_VERSION
RUN arch="$(dpkg --print-architecture)" && \
    gh_url() { printf -- "${GH_BASE_URL}/%s/releases/download/%s/%s\n" "$@" ; } && \
    URL="$(gh_url krallin/tini v${TINI_VERSION} tini-${arch})" && \
    curl -fsSL --output /tini "${URL}" && chmod -v 00555 /tini

# Cache the tini binary as a layer
FROM scratch AS tini-bin
ARG TINI_VERSION
ENV TINI_VERSION="${TINI_VERSION}"
COPY --from=tini-download /tini /tini

# Stage for using git from Debian
FROM dependabot-debian AS debian-git
RUN DEBIAN_FRONTEND='noninteractive' && export DEBIAN_FRONTEND && \
    apt-get update && apt-get install -y git

# Stage for using deno on Debian
FROM debian-git AS debian-deno

# cache dir for youtube.js library
RUN mkdir -v -p /var/tmp/youtubei.js

ARG DENO_DIR
RUN useradd --uid 1993 --user-group deno \
    && mkdir -v "${DENO_DIR}" \
    && chown deno:deno "${DENO_DIR}"

ENV DENO_DIR="${DENO_DIR}" \
    DENO_INSTALL_ROOT='/usr/local'

COPY --from=deno-bin /deno /usr/bin/deno

# Create a builder using deno on Debian
FROM debian-deno AS builder

WORKDIR /app

COPY deno.lock ./
COPY deno.json ./

COPY ./src/ ./src/




ENV DENO_DIR=/deno-dir



RUN chown -R deno:deno .

USER deno

RUN --mount=type=cache,target="/deno-dir",uid=1993,gid=1993 \
    deno cache --no-check src/main.ts
    
# To let the `deno task compile` know the current commit on which
# Invidious companion is being built, similar to how Invidious does it.
# Dependencies are cached in ${DENO_DIR} for our deno builder
# 💡 修正 1: ネイティブバイナリのコンパイル（メモリを大量消費）をスキップします。
# RUN --mount=type=bind,rw,source=.github,target=/app/.github \
# RUN    --mount=type=cache,target="${DENO_DIR}" \
#       deno task compile --no-check

FROM gcr.io/distroless/cc AS app

# Copy group file for the non-privileged user from the user-stage
COPY --from=user-stage /etc/group /etc/group

# Copy passwd file for the non-privileged user from the user-stage
COPY --from=user-stage /etc/passwd /etc/passwd

# 💡 修正 2: deno run に必要な Deno ランタイムとキャッシュをコピー
COPY --from=debian-deno /usr/bin/deno /usr/bin/deno
COPY --from=debian-deno /deno-dir /deno-dir

COPY --from=thc-bin /thc /thc
COPY --from=tini-bin /tini /tini

# Copy cache directory and set correct permissions
COPY --from=builder --chown=appuser:nogroup /var/tmp/youtubei.js /var/tmp/youtubei.js

# Set the working directory
WORKDIR /app

# 💡 修正 3: コンパイルされたバイナリの代わりに、ソースコードと設定ファイルをコピー
# COPY --from=builder /app/invidious_companion ./ <-- この行は削除
COPY --from=builder /app/src/ ./src/
COPY --from=builder /app/deno.json ./
COPY --from=builder /app/deno.lock ./


ARG HOST PORT THC_VERSION TINI_VERSION
EXPOSE "${PORT}/tcp"
ENV HOST="${HOST}" \
    PORT="${PORT}" \
    THC_PORT="${PORT}" \
    THC_PATH='/healthz' \
    THC_VERSION="${THC_VERSION}" \
    TINI_VERSION="${TINI_VERSION}"

COPY ./config/ ./config/

# Switch to non-privileged user
#USER appuser
# Deno実行ユーザーに切り替える（このステップは通常 Dockerfileの最後に近い場所にあります）
#USER deno

# 💡 修正 4: エントリポイントを Deno run でメインファイルを実行するように変更
ENTRYPOINT ["/tini", "--", "deno", "run", "-A", "/app/src/main.ts"]


HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=5 CMD ["/thc"]

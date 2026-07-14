FROM node:22-alpine AS web-builder

ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_FETCH_RETRIES=10
ARG NPM_FETCH_TIMEOUT=600000

WORKDIR /app
COPY web/package.json web/package-lock.json ./web/
WORKDIR /app/web
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry "${NPM_REGISTRY}" \
    && npm config set fetch-retries "${NPM_FETCH_RETRIES}" \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout "${NPM_FETCH_TIMEOUT}" \
    && npm ci --legacy-peer-deps --prefer-offline --no-audit --fund=false

COPY web /app/web
RUN npm run build


FROM python:3.11-slim AS runtime

ARG VERSION=0.2.8
ARG APT_MIRROR=http://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    PIP_INDEX_URL=${PIP_INDEX_URL}

RUN sed -i \
        -e "s|http://deb.debian.org|${APT_MIRROR}|g" \
        -e "s|https://deb.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        curl \
        libreoffice \
        tzdata \
        antiword \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} >/etc/timezone

WORKDIR /app

COPY pyproject.toml setup.py MANIFEST.in README.md README_zh.md /app/

RUN python - <<'PY' > /tmp/runtime-requirements.txt
from pathlib import Path
import tomllib

pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

for requirement in pyproject["build-system"]["requires"]:
    print(requirement)
for requirement in pyproject["project"]["dependencies"]:
    print(requirement)
PY

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        --default-timeout=300 \
        --retries=10 \
        -i ${PIP_INDEX_URL} \
        -r /tmp/runtime-requirements.txt \
    && pip uninstall -y numpy \
    && pip install --no-cache-dir -i ${PIP_INDEX_URL} numpy==1.26.4 \
    && pip install --no-cache-dir -i ${PIP_INDEX_URL} pymupdf xlrd openpyxl python-docx olefile

RUN --mount=type=cache,id=tiktoken-cl100k-base,target=/tmp/tiktoken-build-cache <<'SH'
set -e
mkdir -p "${TIKTOKEN_CACHE_DIR}" /tmp/tiktoken-build-cache
TIKTOKEN_CACHE_DIR=/tmp/tiktoken-build-cache python - <<'PY'
import os
import sys

cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", "")
print(f"[build] prewarming tiktoken cache -> {cache_dir}", file=sys.stderr)

try:
    import tiktoken
    tiktoken.get_encoding("cl100k_base")
except Exception as exc:
    print(f"[build] warning: failed to prewarm tiktoken cache: {exc}", file=sys.stderr)
else:
    print("[build] tiktoken cache ready: cl100k_base", file=sys.stderr)
PY
cp -a /tmp/tiktoken-build-cache/. "${TIKTOKEN_CACHE_DIR}/"
SH

COPY skills /app/skills
COPY webui /app/webui
COPY scripts /app/scripts
COPY --from=web-builder /app/web/dist /app/webui/web/dist

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        --no-build-isolation \
        --no-deps \
        .

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 18780
ENV WEBUI_VERSION=${VERSION}
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:18780/', timeout=3); sys.exit(0)"
ENTRYPOINT ["docker-entrypoint.sh"]

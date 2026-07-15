#!/usr/bin/env bash

set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-protect-webui:local}"
RELEASE_DIR="${RELEASE_DIR:-deployment/release}"
ARCHIVE_NAME="${ARCHIVE_NAME:-protect-webui-local.tar.gz}"
VERSION="${VERSION:-}"
APT_MIRROR="${APT_MIRROR:-http://mirrors.aliyun.com}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple/}"
PLATFORM="${PLATFORM:-}"
PUBLISHED_PORT="${PUBLISHED_PORT:-18780}"
CONTAINER_NAME="${CONTAINER_NAME:-protect-webui}"
TIMEZONE="${TIMEZONE:-Asia/Shanghai}"
WEBUI_LOG_LEVEL="${WEBUI_LOG_LEVEL:-INFO}"
WEBUI_ONLY="${WEBUI_ONLY:-true}"
WEBUI_AUTH_DISABLED="${WEBUI_AUTH_DISABLED:-true}"
INSTANCE_ROOT="${INSTANCE_ROOT:-/data/nanobot/user/public}"
CONFIG_FILE="${CONFIG_FILE:-/data/nanobot/config.json}"
SKILLS_ROOT="${SKILLS_ROOT:-/data/nanobot/skills}"
PRESERVE_EXISTING_DEPLOYMENT_FILES="${PRESERVE_EXISTING_DEPLOYMENT_FILES:-1}"
SKIP_BUILD=0

export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"

usage() {
  cat <<'EOF'
Usage: scripts/build-image-release.sh [options]

Build the local Docker image and prepare an intranet delivery directory.

Options:
  --image-tag <tag>        Docker image tag to build/export (default: protect-webui:local)
  --release-dir <dir>      Output directory for release files (default: deployment/release)
  --archive-name <name>    Image archive filename (default: protect-webui-local.tar.gz)
  --skip-build             Skip docker build and export the existing image only
  -h, --help               Show this help text

Environment overrides:
  VERSION                  WEBUI_VERSION build arg (default: pyproject.toml version)
  APT_MIRROR               Debian apt mirror used during docker build
  NPM_REGISTRY             npm registry used during docker build
  PIP_INDEX_URL            Python package index used during docker build
  DOCKER_BUILDKIT          Docker BuildKit switch (default: 1)
  PLATFORM                 Optional docker build --platform value
  PUBLISHED_PORT           Default published host port in generated compose file
  CONTAINER_NAME           Default container name in generated compose file
  TIMEZONE                 Default container timezone
  WEBUI_LOG_LEVEL          Default WEBUI log level
  WEBUI_ONLY               Default WEBUI_ONLY value
  WEBUI_AUTH_DISABLED      Default WEBUI_AUTH_DISABLED value
  INSTANCE_ROOT            Default host path for /root/.nanobot mount
  CONFIG_FILE              Default host path for config.json mount
  SKILLS_ROOT              Default host path for skills mount
  PRESERVE_EXISTING_DEPLOYMENT_FILES
                           Keep existing docker-compose.yml/config.json in release dir
                           and write refreshed templates to *.new (default: 1)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image-tag)
      IMAGE_TAG="${2:?missing value for --image-tag}"
      shift 2
      ;;
    --release-dir)
      RELEASE_DIR="${2:?missing value for --release-dir}"
      shift 2
      ;;
    --archive-name)
      ARCHIVE_NAME="${2:?missing value for --archive-name}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ABS_RELEASE_DIR="${ROOT_DIR}/${RELEASE_DIR}"
ARCHIVE_PATH="${ABS_RELEASE_DIR}/${ARCHIVE_NAME}"
SOURCE_RELEASE_DIR="${ROOT_DIR}/deployment/release"
TMP_RELEASE_DIR=""

if [[ -z "${VERSION}" ]]; then
  VERSION="$(awk -F'"' '/^version = "/ {print $2; exit}' "${ROOT_DIR}/pyproject.toml")"
fi

cleanup() {
  if [[ -n "${TMP_RELEASE_DIR}" && -d "${TMP_RELEASE_DIR}" ]]; then
    rm -rf "${TMP_RELEASE_DIR}"
  fi
}

trap cleanup EXIT

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker

if command -v pigz >/dev/null 2>&1; then
  COMPRESS_CMD="pigz"
else
  require_cmd gzip
  COMPRESS_CMD="gzip"
fi

require_cmd awk

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "[release] building image ${IMAGE_TAG}"
  build_args=(
    --build-arg "VERSION=${VERSION}"
    --build-arg "APT_MIRROR=${APT_MIRROR}"
    --build-arg "NPM_REGISTRY=${NPM_REGISTRY}"
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}"
    -t "${IMAGE_TAG}"
  )
  if [[ -n "${PLATFORM}" ]]; then
    build_args=(--platform "${PLATFORM}" "${build_args[@]}")
  fi
  docker build "${build_args[@]}" "${ROOT_DIR}"
else
  echo "[release] skipping build, exporting existing image ${IMAGE_TAG}"
  if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "Image does not exist: ${IMAGE_TAG}" >&2
    exit 1
  fi
fi

echo "[release] preparing ${ABS_RELEASE_DIR}"
TMP_RELEASE_DIR="$(mktemp -d "${ROOT_DIR}/.tmp-release-build.XXXXXX")"

for template_file in \
  docker-compose.yml \
  .env.example \
  config.template.json \
  config.json \
  README.md \
  DEPLOYMENT-GUIDE.md; do
  if [[ ! -f "${SOURCE_RELEASE_DIR}/${template_file}" ]]; then
    echo "Missing release template: ${SOURCE_RELEASE_DIR}/${template_file}" >&2
    exit 1
  fi
  cp "${SOURCE_RELEASE_DIR}/${template_file}" "${TMP_RELEASE_DIR}/${template_file}"
done

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  tmp_file="$(mktemp "${TMP_RELEASE_DIR}/env.XXXXXX")"
  awk -v key="${key}" -v value="${value}" 'BEGIN { FS = OFS = "=" } $1 == key { $0 = key "=" value } { print }' "${file}" > "${tmp_file}"
  mv "${tmp_file}" "${file}"
}

ENV_EXAMPLE="${TMP_RELEASE_DIR}/.env.example"
set_env_value "${ENV_EXAMPLE}" "CONTAINER_NAME" "${CONTAINER_NAME}"
set_env_value "${ENV_EXAMPLE}" "PUBLISHED_PORT" "${PUBLISHED_PORT}"
set_env_value "${ENV_EXAMPLE}" "TIMEZONE" "${TIMEZONE}"
set_env_value "${ENV_EXAMPLE}" "WEBUI_LOG_LEVEL" "${WEBUI_LOG_LEVEL}"
set_env_value "${ENV_EXAMPLE}" "WEBUI_ONLY" "${WEBUI_ONLY}"
set_env_value "${ENV_EXAMPLE}" "WEBUI_AUTH_DISABLED" "${WEBUI_AUTH_DISABLED}"
set_env_value "${ENV_EXAMPLE}" "INSTANCE_ROOT" "${INSTANCE_ROOT}"
set_env_value "${ENV_EXAMPLE}" "CONFIG_FILE" "${CONFIG_FILE}"
set_env_value "${ENV_EXAMPLE}" "SKILLS_ROOT" "${SKILLS_ROOT}"

echo "[release] exporting image archive ${ARCHIVE_PATH}"
docker save "${IMAGE_TAG}" | ${COMPRESS_CMD} -c > "${TMP_RELEASE_DIR}/${ARCHIVE_NAME}"

mkdir -p "${ABS_RELEASE_DIR}"

is_preserved_file() {
  case "$1" in
    docker-compose.yml|config.json)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

install_release_file() {
  local relative_path="$1"
  local source_path="${TMP_RELEASE_DIR}/${relative_path}"
  local target_path="${ABS_RELEASE_DIR}/${relative_path}"
  local target_dir

  target_dir="$(dirname "${target_path}")"
  mkdir -p "${target_dir}"

  if [[ "${PRESERVE_EXISTING_DEPLOYMENT_FILES}" != "0" ]] && is_preserved_file "${relative_path}" && [[ -e "${target_path}" ]]; then
    if cmp -s "${source_path}" "${target_path}"; then
      rm -f "${target_path}.new"
      echo "[release] kept unchanged ${relative_path}"
    else
      cp "${source_path}" "${target_path}.new"
      echo "[release] preserved existing ${relative_path}; wrote refreshed template ${relative_path}.new"
    fi
    return 0
  fi

  cp "${source_path}" "${target_path}"
  rm -f "${target_path}.new"
}

for release_file in \
  docker-compose.yml \
  .env.example \
  config.template.json \
  config.json \
  README.md \
  DEPLOYMENT-GUIDE.md \
  "${ARCHIVE_NAME}"; do
  install_release_file "${release_file}"
done

echo "[release] generated files:"
find "${ABS_RELEASE_DIR}" -maxdepth 2 -type f | sort

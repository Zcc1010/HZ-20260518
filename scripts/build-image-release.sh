#!/usr/bin/env bash

set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-protect-webui:local}"
RELEASE_DIR="${RELEASE_DIR:-deployment/release}"
ARCHIVE_NAME="${ARCHIVE_NAME:-protect-webui-local.tar.gz}"
PUBLISHED_PORT="${PUBLISHED_PORT:-18781}"
CONTAINER_NAME="${CONTAINER_NAME:-protect-webui-local}"
TIMEZONE="${TIMEZONE:-Asia/Shanghai}"
WEBUI_LOG_LEVEL="${WEBUI_LOG_LEVEL:-INFO}"
WEBUI_ONLY="${WEBUI_ONLY:-true}"
WEBUI_AUTH_DISABLED="${WEBUI_AUTH_DISABLED:-true}"
INSTANCE_ROOT="${INSTANCE_ROOT:-/data/nanobot/user/public}"
CONFIG_FILE="${CONFIG_FILE:-/data/nanobot/config.json}"
SKILLS_ROOT="${SKILLS_ROOT:-/data/nanobot/skills}"
SKIP_BUILD=0

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
  PUBLISHED_PORT           Default published host port in generated compose file
  CONTAINER_NAME           Default container name in generated compose file
  TIMEZONE                 Default container timezone
  WEBUI_LOG_LEVEL          Default WEBUI log level
  WEBUI_ONLY               Default WEBUI_ONLY value
  WEBUI_AUTH_DISABLED      Default WEBUI_AUTH_DISABLED value
  INSTANCE_ROOT            Default host path for /root/.nanobot mount
  CONFIG_FILE              Default host path for config.json mount
  SKILLS_ROOT              Default host path for skills mount
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

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "[release] building image ${IMAGE_TAG}"
  DOCKER_BUILDKIT=1 docker build -t "${IMAGE_TAG}" "${ROOT_DIR}"
else
  echo "[release] skipping build, exporting existing image ${IMAGE_TAG}"
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

echo "[release] exporting image archive ${ARCHIVE_PATH}"
docker save "${IMAGE_TAG}" | ${COMPRESS_CMD} -c > "${TMP_RELEASE_DIR}/${ARCHIVE_NAME}"

rm -rf "${ABS_RELEASE_DIR}"
mkdir -p "$(dirname "${ABS_RELEASE_DIR}")"
mv "${TMP_RELEASE_DIR}" "${ABS_RELEASE_DIR}"
TMP_RELEASE_DIR=""

echo "[release] generated files:"
find "${ABS_RELEASE_DIR}" -maxdepth 2 -type f | sort

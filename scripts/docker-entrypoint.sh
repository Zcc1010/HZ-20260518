#!/bin/sh
# docker-entrypoint.sh — nanobot-webui container startup script
#
# Supported environment variables:
#   WEBUI_PORT        HTTP port (default: 18780)
#   WEBUI_HOST        Bind address (default: 0.0.0.0)
#   WEBUI_WORKSPACE   Override workspace directory
#   WEBUI_CONFIG      Path to config file
#   WEBUI_LOG_FILE    Optional base file path; actual files rotate daily as <name>-YYYY-MM-DD.log
#   WEBUI_LOG_LEVEL   Log level: DEBUG / INFO / WARNING / ERROR (default: DEBUG)
#   WEBUI_ONLY        Set to "true" to skip IM channels / heartbeat
#   WEBUI_VERSION     Package version installed (set by Dockerfile ENV)

# Disable NumPy CPU optimizations for compatibility
export NPY_DISABLE_CPU_FEATURES="AVX512F AVX512CD AVX2 FMA"

PORT="${WEBUI_PORT:-18780}"
HOST="${WEBUI_HOST:-0.0.0.0}"
LOG_LEVEL="${WEBUI_LOG_LEVEL:-DEBUG}"
LOG_FILE="${WEBUI_LOG_FILE:-}"
VERSION="${WEBUI_VERSION:-0.0.0}"
DEFAULT_WORKSPACE="/root/.protection/workspace"
SEED_SKILLS_DIR="/app/skills"

resolve_workspace_path() {
    if [ -n "${WEBUI_WORKSPACE}" ]; then
        printf '%s\n' "${WEBUI_WORKSPACE}"
        return 0
    fi

    if [ -n "${WEBUI_CONFIG}" ] && [ -f "${WEBUI_CONFIG}" ]; then
        python3 - "${WEBUI_CONFIG}" <<'PY'
import json
import os
import sys

config_path = sys.argv[1]
default = "/root/.protection/workspace"

try:
    with open(config_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print(default)
    raise SystemExit(0)

workspace = (
    data.get("agents", {})
    .get("defaults", {})
    .get("workspace", default)
)
workspace = os.path.expandvars(os.path.expanduser(workspace))
print(workspace or default)
PY
        return 0
    fi

    printf '%s\n' "${DEFAULT_WORKSPACE}"
}

seed_runtime_skills() {
    if [ ! -d "${SEED_SKILLS_DIR}" ]; then
        return 0
    fi

    WORKSPACE_PATH="$(resolve_workspace_path)"
    TARGET_DIR="${WORKSPACE_PATH}/skills"

    mkdir -p "${TARGET_DIR}"
    if [ -n "$(ls -A "${TARGET_DIR}" 2>/dev/null)" ]; then
        echo "[entrypoint] using mounted skills -> ${TARGET_DIR}"
        return 0
    fi

    cp -R "${SEED_SKILLS_DIR}/." "${TARGET_DIR}/"
    echo "[entrypoint] seeded fallback skills -> ${TARGET_DIR}"
}

seed_agentplayground_app_skills() {
    if [ ! -d "${SEED_SKILLS_DIR}/g-file-contrast" ]; then
        return 0
    fi

    INSTANCE_ROOT="$(dirname "$(resolve_workspace_path)")"
    TARGET_DIR="${INSTANCE_ROOT}/agentplayground/g-file-compare/skills/g-file-contrast"

    mkdir -p "$(dirname "${TARGET_DIR}")"
    if [ -n "$(ls -A "${TARGET_DIR}" 2>/dev/null)" ]; then
        echo "[entrypoint] using app skill -> ${TARGET_DIR}"
        return 0
    fi

    cp -R "${SEED_SKILLS_DIR}/g-file-contrast" "${TARGET_DIR}"
    echo "[entrypoint] seeded app skill -> ${TARGET_DIR}"
}

run_webui() {
    CMD="$1"
    if [ -n "${LOG_FILE}" ]; then
        mkdir -p "$(dirname "${LOG_FILE}")"
        echo "[entrypoint] rotating log base -> ${LOG_FILE}"
        exec sh -c "${CMD} 2>&1 | python3 /app/scripts/tee_rotate_logs.py \"${LOG_FILE}\""
    fi

    exec sh -c "${CMD}"
}

# Build argument list
ARGS="--port ${PORT} --host ${HOST} --log-level ${LOG_LEVEL}"

if [ -n "${WEBUI_WORKSPACE}" ]; then
    ARGS="${ARGS} --workspace ${WEBUI_WORKSPACE}"
fi

if [ -n "${WEBUI_CONFIG}" ]; then
    ARGS="${ARGS} --config ${WEBUI_CONFIG}"
fi

if [ "${WEBUI_ONLY}" = "true" ]; then
    ARGS="${ARGS} --webui-only"
fi

seed_runtime_skills
seed_agentplayground_app_skills

# Prefer the dedicated command first, keep backward-compatible fallbacks.
if command -v nanobot-webui >/dev/null 2>&1; then
    echo "[entrypoint] nanobot-webui start ${ARGS}"
    run_webui "nanobot-webui start ${ARGS}"
fi

# Fallback for older packaged layouts.
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)
PATCH=$(echo "$VERSION" | cut -d. -f3 | cut -d. -f1)

use_new_cli=0
if [ "$MAJOR" -gt 0 ] 2>/dev/null; then
    use_new_cli=1
elif [ "$MAJOR" -eq 0 ] 2>/dev/null && [ "$MINOR" -gt 2 ] 2>/dev/null; then
    use_new_cli=1
elif [ "$MAJOR" -eq 0 ] 2>/dev/null && [ "$MINOR" -eq 2 ] 2>/dev/null && [ "$PATCH" -gt 5 ] 2>/dev/null; then
    use_new_cli=1
fi

if [ "$use_new_cli" -eq 1 ]; then
    echo "[entrypoint] nanobot webui start ${ARGS}"
    run_webui "nanobot webui start ${ARGS}"
fi

echo "[entrypoint] python -m webui ${ARGS}"
run_webui "python -m webui ${ARGS}"

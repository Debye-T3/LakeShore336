#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EPICS_HOST_ARCH="${EPICS_HOST_ARCH:-}"

if [ -z "$EPICS_HOST_ARCH" ] && [ -f "${PROJECT_ROOT}/configure/RELEASE.local" ]; then
    EPICS_BASE="$(awk -F= '/^EPICS_BASE[[:space:]]*=/{gsub(/[[:space:]]/, "", $2); print $2}' "${PROJECT_ROOT}/configure/RELEASE.local" | tail -n 1)"
    if [ -n "${EPICS_BASE:-}" ] && [ -x "${EPICS_BASE}/startup/EpicsHostArch" ]; then
        EPICS_HOST_ARCH="$("${EPICS_BASE}/startup/EpicsHostArch")"
    fi
fi

if [ -z "$EPICS_HOST_ARCH" ]; then
    candidate="$(find "${PROJECT_ROOT}/bin" -mindepth 2 -maxdepth 2 -type f -name ls336 -perm -111 2>/dev/null | head -n 1 || true)"
else
    candidate="${PROJECT_ROOT}/bin/${EPICS_HOST_ARCH}/ls336"
fi

if [ -z "${candidate:-}" ] || [ ! -x "$candidate" ]; then
    echo "Could not find built IOC binary." >&2
    echo "Run setup and build first:" >&2
    echo "  bash scripts/setup_epics_wsl.sh" >&2
    echo "  make" >&2
    exit 1
fi

cd "${PROJECT_ROOT}/iocBoot/iocLS336"
exec "$candidate" st.cmd

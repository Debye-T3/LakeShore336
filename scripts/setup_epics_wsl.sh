#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EPICS_ROOT=${EPICS_ROOT:-/opt/epics}
EPICS_BASE_TAG=${EPICS_BASE_TAG:-R7.0.8.1}
ASYN_TAG=${ASYN_TAG:-R4-44}
STREAM_TAG=${STREAM_TAG:-2.8.24}

need_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

clone_or_update() {
    local url="$1"
    local tag="$2"
    local dest="$3"

    if [ -d "${dest}/.git" ]; then
        git -C "$dest" fetch --tags --prune
    else
        git clone "$url" "$dest"
    fi

    git -C "$dest" checkout "$tag"
}

prepare_epics_root() {
    if [ -w "$(dirname "$EPICS_ROOT")" ]; then
        mkdir -p "$EPICS_ROOT/support"
        return
    fi

    sudo mkdir -p "$EPICS_ROOT/support"
    sudo chown -R "$(id -u):$(id -g)" "$EPICS_ROOT"
}

write_release() {
    cat > "${PROJECT_ROOT}/configure/RELEASE.local" <<EOF
EPICS_BASE=${EPICS_ROOT}/base
ASYN=${EPICS_ROOT}/support/asyn
STREAM=${EPICS_ROOT}/support/StreamDevice
EOF
}

need_command git
need_command make
need_command perl

prepare_epics_root

clone_or_update "https://github.com/epics-base/epics-base.git" "$EPICS_BASE_TAG" "${EPICS_ROOT}/base"
make -j -C "${EPICS_ROOT}/base"

clone_or_update "https://github.com/epics-modules/asyn.git" "$ASYN_TAG" "${EPICS_ROOT}/support/asyn"
cat > "${EPICS_ROOT}/support/asyn/configure/RELEASE.local" <<EOF
EPICS_BASE=${EPICS_ROOT}/base
EOF
make -j -C "${EPICS_ROOT}/support/asyn"

clone_or_update "https://github.com/paulscherrerinstitute/StreamDevice.git" "$STREAM_TAG" "${EPICS_ROOT}/support/StreamDevice"
cat > "${EPICS_ROOT}/support/StreamDevice/configure/RELEASE.local" <<EOF
EPICS_BASE=${EPICS_ROOT}/base
ASYN=${EPICS_ROOT}/support/asyn
EOF
make -j -C "${EPICS_ROOT}/support/StreamDevice"

write_release

echo "EPICS stack installed under ${EPICS_ROOT}"
echo "Wrote ${PROJECT_ROOT}/configure/RELEASE.local"
echo "Next: cd ${PROJECT_ROOT} && make"

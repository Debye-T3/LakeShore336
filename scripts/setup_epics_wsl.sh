#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EPICS_ROOT=${EPICS_ROOT:-/opt/epics}
EPICS_BASE_TAG=${EPICS_BASE_TAG:-R7.0.8.1}
ASYN_TAG=${ASYN_TAG:-R4-44}
STREAM_TAG=${STREAM_TAG:-2.8.24}
EPICS_BASE_URL=${EPICS_BASE_URL:-https://github.com/epics-base/epics-base.git}
ASYN_URL=${ASYN_URL:-https://github.com/epics-modules/asyn.git}
STREAM_URL=${STREAM_URL:-https://github.com/paulscherrerinstitute/StreamDevice.git}
EPICS_BASE_ARCHIVE=${EPICS_BASE_ARCHIVE:-}
ASYN_ARCHIVE=${ASYN_ARCHIVE:-}
STREAM_ARCHIVE=${STREAM_ARCHIVE:-}
GIT_ATTEMPTS=${GIT_ATTEMPTS:-3}

default_archive() {
    local current="$1"
    local relative_path="$2"
    local candidate="${PROJECT_ROOT}/${relative_path}"

    if [ -n "$current" ]; then
        echo "$current"
    elif [ -f "$candidate" ]; then
        echo "$candidate"
    else
        echo ""
    fi
}

EPICS_BASE_ARCHIVE="$(default_archive "$EPICS_BASE_ARCHIVE" "downloads/epics-base-R7.0.8.1.tar.gz")"
ASYN_ARCHIVE="$(default_archive "$ASYN_ARCHIVE" "downloads/asyn-R4-44.tar.gz")"
STREAM_ARCHIVE="$(default_archive "$STREAM_ARCHIVE" "downloads/StreamDevice-2.8.24.tar.gz")"

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
    local attempt=1

    while [ "$attempt" -le "$GIT_ATTEMPTS" ]; do
        echo "Git attempt ${attempt}/${GIT_ATTEMPTS}: ${url}"
        if [ -d "${dest}/.git" ]; then
            git -C "$dest" fetch --tags --prune && break
        elif [ -e "$dest" ]; then
            echo "Refusing to overwrite existing non-git path: $dest" >&2
            echo "Move it aside or remove it, then rerun this script." >&2
            exit 1
        else
            git clone --branch "$tag" --depth 1 "$url" "$dest" && break
        fi

        if [ "$attempt" -eq "$GIT_ATTEMPTS" ]; then
            echo "Git download failed after ${GIT_ATTEMPTS} attempts: ${url}" >&2
            echo "If GitHub is blocked or slow, rerun with an alternate URL, for example:" >&2
            echo "  EPICS_BASE_URL=<mirror-url> ASYN_URL=<mirror-url> STREAM_URL=<mirror-url> bash scripts/setup_epics_wsl.sh" >&2
            exit 1
        fi

        attempt=$((attempt + 1))
        sleep 5
    done

    git -C "$dest" checkout "$tag"
}

extract_archive() {
    local archive="$1"
    local dest="$2"
    local parent
    local temp_dir
    local extracted

    parent="$(dirname "$dest")"

    if [ -d "${dest}/.git" ] || [ -f "${dest}/configure/CONFIG" ]; then
        echo "Using existing source tree: $dest"
        return
    fi

    if [ -e "$dest" ]; then
        echo "Refusing to overwrite existing path: $dest" >&2
        echo "Move it aside or remove it, then rerun this script." >&2
        exit 1
    fi

    if [ ! -f "$archive" ]; then
        echo "Archive does not exist: $archive" >&2
        exit 1
    fi

    temp_dir="$(mktemp -d)"
    tar -xzf "$archive" -C "$temp_dir"
    extracted="$(find "$temp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

    if [ -z "$extracted" ]; then
        echo "Archive did not contain a top-level source directory: $archive" >&2
        exit 1
    fi

    mkdir -p "$parent"
    mv "$extracted" "$dest"
    rm -rf "$temp_dir"
}

prepare_source() {
    local archive="$1"
    local url="$2"
    local tag="$3"
    local dest="$4"

    if [ -n "$archive" ]; then
        echo "Using local archive: $archive"
        extract_archive "$archive" "$dest"
    else
        clone_or_update "$url" "$tag" "$dest"
    fi
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

if [ ! -f /usr/include/tirpc/rpc/rpc.h ]; then
    echo "Missing RPC headers required by asyn VXI-11 support." >&2
    echo "Install them with:" >&2
    echo "  sudo apt update" >&2
    echo "  sudo apt install -y libtirpc-dev" >&2
    exit 1
fi

PCRE_MULTIARCH="$(gcc -print-multiarch 2>/dev/null || dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo x86_64-linux-gnu)"
if [ ! -f "/usr/lib/${PCRE_MULTIARCH}/libpcre.a" ]; then
    echo "Missing static PCRE library required by StreamDevice." >&2
    echo "Install it with:" >&2
    echo "  sudo apt update" >&2
    echo "  sudo apt install -y libpcre3-dev" >&2
    exit 1
fi

prepare_epics_root

prepare_source "$EPICS_BASE_ARCHIVE" "$EPICS_BASE_URL" "$EPICS_BASE_TAG" "${EPICS_ROOT}/base"
make -j -C "${EPICS_ROOT}/base"

prepare_source "$ASYN_ARCHIVE" "$ASYN_URL" "$ASYN_TAG" "${EPICS_ROOT}/support/asyn"
cat > "${EPICS_ROOT}/support/asyn/configure/RELEASE.local" <<EOF
EPICS_BASE=${EPICS_ROOT}/base
EOF
cat > "${EPICS_ROOT}/support/asyn/configure/CONFIG_SITE.local" <<EOF
USR_INCLUDES_Linux += -I/usr/include/tirpc
SYS_LIBS_Linux += tirpc
EOF
make -j -C "${EPICS_ROOT}/support/asyn/asyn"

prepare_source "$STREAM_ARCHIVE" "$STREAM_URL" "$STREAM_TAG" "${EPICS_ROOT}/support/StreamDevice"
cat > "${EPICS_ROOT}/support/StreamDevice/configure/RELEASE.local" <<EOF
EPICS_BASE=${EPICS_ROOT}/base
ASYN=${EPICS_ROOT}/support/asyn
CALC=
SYNAPPS=
PCRE=
EOF
cat > "${EPICS_ROOT}/support/StreamDevice/configure/CONFIG_SITE.local" <<EOF
PCRE_INCLUDE=/usr/include
PCRE_LIB=/usr/lib/${PCRE_MULTIARCH}
EOF
make -j -C "${EPICS_ROOT}/support/StreamDevice/src"

write_release

echo "EPICS stack installed under ${EPICS_ROOT}"
echo "Wrote ${PROJECT_ROOT}/configure/RELEASE.local"
echo "Next: cd ${PROJECT_ROOT} && make"

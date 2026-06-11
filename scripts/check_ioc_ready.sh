#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

failures=0

check() {
    local description="$1"
    shift

    if "$@"; then
        echo "OK: ${description}"
    else
        echo "FAIL: ${description}" >&2
        failures=$((failures + 1))
    fi
}

check "make is available" command -v make
check "configure/RELEASE.local exists" test -f configure/RELEASE.local
check "IOC startup script exists" test -f iocBoot/iocLS336/st.cmd
check "IOC binary exists after build" test -x bin/linux-x86_64/ls336

echo
echo "Build command:"
echo "  make"
echo
echo "Start IOC:"
echo "  cd iocBoot/iocLS336"
echo "  ../../bin/linux-x86_64/ls336 st.cmd"
echo
echo "Readback checks:"
echo "  caget LS336:ColdHead:TEMP_RBV"
echo "  caget LS336:Sample:TEMP_RBV"
echo "  caget LS336:Loop1:SETP_RBV"
echo "  caget LS336:Loop1:HTR_RBV"
echo
echo "Safe write checks:"
echo "  caput LS336:Loop1:SETP 300"
echo "  caput LS336:Loop1:RAMP:ENABLE 1"
echo "  caput LS336:Loop1:RAMP:RATE 1"

if [ "$failures" -gt 0 ]; then
    exit 1
fi

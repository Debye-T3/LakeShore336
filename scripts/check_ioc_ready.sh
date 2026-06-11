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
check "Python test runner exists" test -x scripts/run_tests.sh
check "IOC run script exists" test -x scripts/run_ioc.sh
check "IOC startup script exists" test -f iocBoot/iocLS336/st.cmd
check "IOC binary exists after build" test -n "$(find bin -mindepth 2 -maxdepth 2 -type f -name ls336 -perm -111 2>/dev/null | head -n 1)"

if [ ! -f configure/RELEASE.local ]; then
    echo
    echo "Missing configure/RELEASE.local."
    echo "Run this from Linux to install EPICS dependencies and write it:"
    echo "  bash scripts/setup_epics_wsl.sh"
fi

echo
echo "Repository tests:"
echo "  bash scripts/run_tests.sh"
echo
echo "Build command:"
echo "  make"
echo
echo "Start IOC:"
echo "  bash scripts/run_ioc.sh"
echo
echo "Readback checks:"
echo "  caget LS336:IDN"
echo "  caget LS336:ColdHead:TEMP_RBV"
echo "  caget LS336:Sample:TEMP_RBV"
echo "  caget LS336:Loop1:SETP_RBV"
echo "  caget LS336:Loop1:HTR_RBV"
echo "  caget LS336:COMM:STATUS"
echo
echo "Safe write checks:"
echo "  caput LS336:Loop1:SETP 300"
echo "  caput LS336:Loop1:RAMP:ENABLE 1"
echo "  caput LS336:Loop1:RAMP:RATE 1"
echo "  caput LS336:Loop1:WARMUP:TARGET 300"
echo "  caput LS336:Loop1:WARMUP:STEP 5"
echo "  caput LS336:Loop1:WARMUP:NEXT.PROC 1"

if [ "$failures" -gt 0 ]; then
    exit 1
fi

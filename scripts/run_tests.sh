#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ "${1-}" == "--ioc-integration" ]]; then
    exec python3 -m pytest -q tests/test_ioc_integration.py -rs
fi

if python3 -c "import pytest" >/dev/null 2>&1; then
    exec python3 -m pytest -q "$@"
fi

echo "pytest is not installed; using the built-in lightweight test runner."

python3 - "$@" <<'PY'
import importlib.util
import inspect
import sys
import traceback
from pathlib import Path


root = Path.cwd()
test_paths = sorted((root / "tests").glob("test_*.py"))
selected = set(sys.argv[1:])
failures = 0
total = 0

for path in test_paths:
    if selected and str(path) not in selected and path.name not in selected:
        continue

    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name, func in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue

        total += 1
        test_id = f"{path.relative_to(root)}::{name}"
        try:
            func()
        except Exception:
            failures += 1
            print(f"FAIL {test_id}")
            traceback.print_exc()
        else:
            print(f"PASS {test_id}")

if total == 0:
    print("No tests collected.")
    sys.exit(1)

print(f"{total - failures} passed, {failures} failed")
sys.exit(1 if failures else 0)
PY

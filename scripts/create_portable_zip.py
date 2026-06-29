#!/usr/bin/env python3
"""Create the Lake Shore 336 portable ZIP while preserving empty directories."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def create_zip(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Package directory not found: {source}")
    if source == output or source in output.parents:
        raise ValueError("Output ZIP must be outside the package directory")

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            if path.is_dir():
                info = ZipInfo(f"{relative}/")
                info.external_attr = 0o40775 << 16
                archive.writestr(info, b"")
            else:
                archive.write(path, relative)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        create_zip(args.source, args.output)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        return 1
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

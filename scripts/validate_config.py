#!/usr/bin/env python3
"""Validate versioned Desired State before a deployment."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "control-plane"))

from app.configuration import load_configuration


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    configuration = load_configuration(root / "config")
    print(f"Configuration valid: {configuration.checksum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

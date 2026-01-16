"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | dependency management]
DECISIONS:
- Use a plain deps.txt file and pip install -r -> simple setup -> UNSUPPORTED: packaging policy
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    deps_path = Path("deps.txt")
    if not deps_path.exists():
        print("deps.txt not found")
        return 1

    command = [sys.executable, "-m", "pip", "install", "-r", str(deps_path)]
    print("Installing dependencies:")
    print(" ".join(command))
    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
